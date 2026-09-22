#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zenmux_edit.py — ZenMux 图片编辑（OpenAI Images 协议 + mask 局部重绘）

初心：在素材图上**标记若干部位**，只让模型重绘这些部位（换一把武器 / 换一件衣服 / 改配色），
其余像素尽量不动。

子命令
    check   自检：是否读到 ZENMUX_API_KEY、模型是否在架、输入图与 mask 计划是否合法、PAYG 余额（不花额度）
    balance 查 PAYG 余额（Management API Key，**不花额度**）—— 跑批前后做成本控制用
    edit    图片编辑（**消耗 ZenMux 额度**）

用法示例
    python tools/zenmux_edit.py check
    python tools/zenmux_edit.py balance
    python tools/zenmux_edit.py edit --image assets/eva_bone/parts/hero.png \\
        --mask tmp/m_weapon.png --mask-prompt "把手里那把剑换成一把发光的短杖" \\
        --mask tmp/m_coat.png   --mask-prompt "把这件外套换成深红色皮甲" \\
        --mask-mode sequential --min-credits 1 --out-dir tmp/zenmux-edit/run1

成本控制
    * `balance`：查余额（Management API Key，免费）。key 写 .env 的 ZENMUX_MANAGEMENT_API_KEY。
      **注意 key 分两类**：`sk-mg-` 开头的是**管理型** key，只能打余额/用量这类平台接口，
      打模型接口一律 403 access_denied（实测）—— 生图必须另配普通 API Key 到 ZENMUX_API_KEY。
    * `edit --min-credits X`：开跑前查一次余额，低于 X 美元直接拒跑；跑完再查一次，
      打印本次余额差（≈本次实际花费）并写 run-summary.json。
    * 每次调用仍然打印 token usage；默认 --retries 0，不自动重试（避免重复计费）。

关于 mask 的硬事实（2026-09 核对官方文档，详见 tools/zenmux-edit.md）
    * OpenAI Images 协议（/v1/images/edits）**一个请求只接受 1 个 mask**，且只作用于第一张输入图；
      输入图最多 16 张。所以"多个 mask"必须由本工具消化：
        - union      把 N 个 mask 并成 1 张 → 1 次调用（省钱，但模型分不清哪块该改成什么）
        - sequential 每个 mask 一次调用，上一张输出当下一张输入 → 真正的"逐块改"（准，N 倍花费）
        - separate   每个 mask 各出 1 张（都基于原图）→ N 个候选，互相不叠加
    * mask 语义：**透明（alpha=0）= 要重绘的区域**，不透明 = 保留。
      人画的 mask 通常是"涂白/不透明 = 要改"，本工具默认按这个读入（--mask-polarity marked），
      再自动翻成 API 需要的透明洞；若你的 mask 本身就是"透明洞 = 要改"，用 --mask-polarity hole。
    * 输入图与 mask 必须同尺寸：本工具自动把 mask 缩放到第一张输入图的尺寸（并告警）。

产出纪律
    * 每次调用都会打印 HTTP 状态、x-request-id、token usage，并把 params/usage 写成同名 .json 边车文件。
    * 默认 --retries 0：不自动重试，避免 5xx / 超时下重复计费。确实要重试请显式 --retries N。
    * 中间产物（mask 预览、每步输出）默认落 tmp/zenmux-edit/<时间戳>/；生成产物请显式 --out-dir。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    print("缺少依赖 requests：python -m pip install requests", file=sys.stderr)
    raise SystemExit(3)

from PIL import Image, ImageChops, ImageFilter, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

if hasattr(sys.stdout, "reconfigure"):      # Windows 控制台默认 cp936，中文/特殊字符会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent.parent          # 工作区根
DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-image-2.5-sunburst"
MAX_INPUT_IMAGES = 16                                   # GPT image 模型输入图上限
# JSON(base64) 通道：OpenAI schema 对 image_url 字符串字段的 maxLength = 20971520（≈20MiB），
# base64 会膨胀 4/3，所以原图约 15MB 就到顶。multipart 通道没有这个字段限制，走 50MB 文件上限。
DATA_URL_FIELD_LIMIT = 20 * 1024 * 1024
UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024                  # 单张图/单个 mask 的上传上限（文档：<50MB）
MASK_PNG_WARN_BYTES = 4 * 1024 * 1024                  # 第三方文档称 mask PNG 限 4MB；官方未写，超了先告警
CUSTOM_SIZE_MIN_PX = 655_360                           # 自定义尺寸约束（ZenMux Vertex 协议文档，仅 gpt-image-2/2.5）
CUSTOM_SIZE_MAX_PX = 8_294_400
CUSTOM_SIZE_MAX_SIDE = 3840
PRESET_SIZES = ("1024x1024", "1536x1024", "1024x1536", "auto")
MASK_MODES = ("union", "sequential", "separate")

_USAGE_LOG: list = []                                   # 每个 step 的用量，收尾写进 run-summary.json

# --------------------------------------------------------------------------- 日志


def log(msg: str) -> None:
    print(msg, flush=True)


def info(msg: str) -> None:
    print(f"[info] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[warn] {msg}", flush=True)


def die(msg: str, code: int = 2):
    print(f"[fail] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


# --------------------------------------------------------------------------- .env / key


def load_env() -> dict:
    """读工作区根与当前目录的 .env（按 AGENTS.md：latin-1 解析、不做中文注释）。"""
    vals: dict = {}
    paths = []
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        paths.append(cwd_env)
    root_env = BASE / ".env"
    if root_env.exists() and root_env != cwd_env:
        paths.append(root_env)
    for p in paths:
        try:
            text = p.read_text(encoding="latin-1")
        except OSError as e:
            warn(f"读不到 {p}：{e}")
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return vals


def resolve_api_key(args) -> str:
    key = getattr(args, "api_key", None) or os.environ.get("ZENMUX_API_KEY") or load_env().get("ZENMUX_API_KEY")
    if not key:
        die(
            "没有 ZENMUX_API_KEY。请在**工作区根** .env 里加一行（不要贴到对话里）：\n"
            "    ZENMUX_API_KEY=sk-你的key\n"
            "key 在 https://zenmux.ai/platform 创建。"
        )
    return key.strip()


def mask_key(key: str) -> str:
    return key[:6] + "…" + key[-4:] if len(key) > 12 else "…"


def key_kind_hint(key: str) -> str:
    """sk-mg- 是 Management API Key：只能打平台接口（余额/用量），**打模型接口一律 403**。

    实测（2026-09，free 计划 + PAYG 余额）：拿 sk-mg- key 调 /chat/completions 与 /images/edits
    全部返回 403 access_denied（消息里带 api_key_source: payg）；而 /management/payg/balance、
    /management/subscription/detail 正常。更坑的是 /images/edits 的 **JSON 通道**在鉴权前就 500，
    所以用管理型 key 打 JSON 编辑通道会看到 "HTTP 500 internal_server_error" 而不是 403，极易误判。
    """
    if key.startswith("sk-mg-"):
        return ("这是**管理型** key（sk-mg-）：只能打余额/用量等平台接口，打模型接口一律 403 access_denied。"
                "生图请在 https://zenmux.ai/platform 建一个**普通** API Key 写进 .env 的 ZENMUX_API_KEY"
                "（管理型 key 留给 ZENMUX_MANAGEMENT_API_KEY 查余额）")
    return ""


# --------------------------------------------------------------------------- 余额（成本控制）


def resolve_management_key(args) -> tuple:
    """返回 (key, 来源标签)。余额接口只认 Management API Key（sk-mg-…），普通 key 会 403。"""
    env = load_env()
    explicit = getattr(args, "api_key", None)
    if explicit:
        return explicit.strip(), "--api-key"
    for name in ("ZENMUX_MANAGEMENT_API_KEY", "ZENMUX_API_KEY"):
        val = os.environ.get(name) or env.get(name)
        if val:
            return val.strip(), name
    return "", ""


def warn_if_plain_key(key: str, source: str) -> None:
    if source == "ZENMUX_API_KEY" and not key.startswith("sk-mg-"):
        warn("用的是普通 ZENMUX_API_KEY；余额接口只认 Management API Key（sk-mg-…）——"
             "若下面 403，请去 https://zenmux.ai/platform/management 建一个写进 .env 的 ZENMUX_MANAGEMENT_API_KEY")


def fetch_balance(base_url: str, key: str, timeout: int = 30) -> dict:
    """GET /management/payg/balance —— 官方文档：仅接受 Management API Key。"""
    r = requests.get(base_url.rstrip("/") + "/management/payg/balance",
                     headers={"Authorization": f"Bearer {key}"}, timeout=(10, timeout))
    if r.status_code >= 400:
        msg, etype, code = parse_error_body(r)
        raise ApiError(r.status_code, msg or r.reason,
                       r.headers.get("x-request-id") or r.headers.get("x-zenmux-request-id") or "", etype, code)
    body = r.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise ApiError(200, f"余额响应结构不认识：{json.dumps(body, ensure_ascii=False)[:200]}")
    return data


def format_balance(data: dict) -> str:
    cur = (data.get("currency") or "usd").upper()
    total = data.get("total_credits")
    top = data.get("top_up_credits")
    bonus = data.get("bonus_credits")
    parts = [f"余额 {total} {cur}"]
    if top is not None or bonus is not None:
        parts.append(f"（充值 {top} + 赠送 {bonus}）")
    return "".join(parts)


def cmd_balance(args) -> int:
    key, source = resolve_management_key(args)
    if not key:
        die("没有 Management API Key。在**工作区根** .env 里加一行：\n"
            "    ZENMUX_MANAGEMENT_API_KEY=sk-mg-...\n"
            "在 https://zenmux.ai/platform/management 创建（余额接口不接受普通 API Key）")
    if source != "--api-key":
        warn_if_plain_key(key, source)
    try:
        data = fetch_balance(args.base_url, key, args.timeout)
    except ApiError as e:
        hint = ""
        if e.status == 403 or e.etype == "access_denied":
            hint = ("\n       余额接口只认 Management API Key（sk-mg-…）："
                    "https://zenmux.ai/platform/management 建一个，写进 .env 的 ZENMUX_MANAGEMENT_API_KEY")
        elif e.status == 422:
            hint = "\n       该接口有独立限流（文档：超出返回 422），等一分钟再试"
        die(f"查余额失败：{e}" + hint, 2)
    if args.json:
        log(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        log(format_balance(data) + f"    [来源 {source}]")
    total = data.get("total_credits")
    if isinstance(total, (int, float)) and total <= 0:
        warn("余额 ≤ 0：跑 edit 会被 402 拒（insufficient_credit / reject_no_credit），先充值")
        return 1
    return 0


# --------------------------------------------------------------------------- 图像与 mask


def load_image(path: str | Path) -> Image.Image:
    p = Path(path)
    if not p.exists():
        die(f"输入图不存在：{p}")
    im = Image.open(p)
    im.load()                       # 手机 MPO/HDR 多帧 JPEG 只保留第一帧（否则 edits 会 400）
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.mode or im.mode == "P" and "transparency" in im.info else "RGB")
    return im


def shrink_longest_side(im: Image.Image, max_side: int) -> Image.Image:
    w, h = im.size
    if max_side <= 0 or max(w, h) <= max_side:
        return im
    k = max_side / float(max(w, h))
    return im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def sniff_ext(data: bytes, fallback: str = "png") -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return fallback


def data_url(payload: bytes, ext: str = "png") -> str:
    mime = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp"}[ext]
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


def read_edit_mask(path: str | Path, polarity: str, threshold: int, target_size: tuple) -> Image.Image:
    """把用户 mask 读成内部约定：'L' 图，255 = **要重绘**的区域。"""
    p = Path(path)
    if not p.exists():
        die(f"mask 不存在：{p}")
    im = Image.open(p)
    im.load()
    has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
    gray = im.convert("RGBA").getchannel("A") if has_alpha else im.convert("L")
    if has_alpha:
        # PS 常见的坑：存成 RGBA 但 alpha 全是 255，真正画的是黑白亮度 → 用亮度重读
        hist = gray.histogram()
        total = sum(hist) or 1
        if max(hist) / total > 0.98:
            warn(f"{p.name}: alpha 通道基本是常数（{hist.index(max(hist))}/{total} 像素），"
                 f"改按亮度读 mask")
            gray = im.convert("L")
    if polarity == "marked":
        edit = gray.point(lambda v: 255 if v >= threshold else 0)
    else:  # hole：透明/暗 = 要改
        edit = gray.point(lambda v: 255 if v < threshold else 0)
    if im.size != tuple(target_size):
        warn(f"{p.name}: {im.size[0]}x{im.size[1]} 与输入图 {target_size[0]}x{target_size[1]} 不一致，"
             f"已用最近邻缩放到输入图尺寸")
        edit = edit.resize(tuple(target_size), Image.NEAREST)
    return edit


def grow_mask(edit: Image.Image, grow: int) -> Image.Image:
    if grow == 0:
        return edit
    filt = ImageFilter.MaxFilter(3) if grow > 0 else ImageFilter.MinFilter(3)
    for _ in range(abs(int(grow))):
        edit = edit.filter(filt)
    return edit


def feather_mask(edit: Image.Image, radius: float) -> Image.Image:
    return edit.filter(ImageFilter.GaussianBlur(radius)) if radius and radius > 0 else edit


def coverage(edit: Image.Image) -> float:
    hist = edit.histogram()
    total = sum(hist)
    return (sum(hist[128:]) / total) if total else 0.0


def api_mask_png(edit: Image.Image) -> bytes:
    """内部 mask → API mask：透明（alpha=0）= 要重绘的区域。"""
    alpha = edit.point(lambda v: 255 - v)
    rgba = Image.merge("RGBA", (Image.new("L", edit.size, 0),) * 3 + (alpha,))
    return png_bytes(rgba)


def mask_preview(base: Image.Image, edit: Image.Image, out_path: Path) -> None:
    """红=要重绘（半透明，底图仍可见），绿线=mask 边界；给人眼验收 polarity/grow 用。"""
    if base.size != edit.size:
        base = base.resize(edit.size, Image.LANCZOS)
    rgb = base.convert("RGB").copy()
    red = Image.new("RGB", edit.size, (255, 60, 60))
    rgb.paste(red, (0, 0), edit.point(lambda v: v // 2))              # 50% 红 = 要重绘
    edge = edit.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    rgb.paste(Image.new("RGB", edit.size, (0, 255, 120)), (0, 0), edge)   # 绿线 = 边界
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(out_path)


def _clamp_custom_size(w: int, h: int) -> tuple:
    """把尺寸夹进文档给的自定义尺寸约束：16 倍数、单边 ≤3840、总像素 655,360~8,294,400。"""
    w, h = max(16, (w // 16) * 16), max(16, (h // 16) * 16)
    if max(w, h) > CUSTOM_SIZE_MAX_SIDE:
        k = CUSTOM_SIZE_MAX_SIDE / float(max(w, h))
        w, h = max(16, (int(w * k) // 16) * 16), max(16, (int(h * k) // 16) * 16)
    if w * h > CUSTOM_SIZE_MAX_PX:                       # 例如 3840x3840 = 14.7M，超预算
        k = (CUSTOM_SIZE_MAX_PX / float(w * h)) ** 0.5
        w, h = max(16, (int(w * k) // 16) * 16), max(16, (int(h * k) // 16) * 16)
    if w * h < CUSTOM_SIZE_MIN_PX:
        # 输入图比自定义尺寸的下限还小：只能等比放大到合法下限（并告警，别让人以为尺寸被改了）
        k = (CUSTOM_SIZE_MIN_PX / float(w * h)) ** 0.5
        nw, nh = (int(w * k + 15) // 16) * 16, (int(h * k + 15) // 16) * 16
        warn(f"输入图 {w}x{h} 小于自定义尺寸的下限（总像素 ≥{CUSTOM_SIZE_MIN_PX}），"
             f"match 只能放大到 {nw}x{nh}；想要别的尺寸请显式 --size")
        w, h = nw, nh
    return w, h


def resolve_size(spec: str, base_size: tuple) -> tuple:
    """返回 (size_param, note)。spec 支持 预设 / auto / match / WxH。"""
    if spec == "match":
        w16, h16 = _clamp_custom_size(*base_size)
        if max(w16, h16) / float(min(w16, h16)) > 3.0:
            warn("输入图宽高比超过 3:1，自定义尺寸可能被拒（改用 --size 1024x1024 / 1536x1024）")
        note = (f"match 输入图 {base_size[0]}x{base_size[1]} → {w16}x{h16}"
                f"（16 倍数、单边 ≤3840、总像素 {CUSTOM_SIZE_MIN_PX}~{CUSTOM_SIZE_MAX_PX}；"
                f"自定义尺寸 ZenMux 文档只对 gpt-image-2 / 2.5 明示）")
        return f"{w16}x{h16}", note
    if spec not in PRESET_SIZES:
        m = re.fullmatch(r"(\d{3,5})x(\d{3,5})", spec.strip())
        if not m:
            die(f"--size {spec} 不认识：用 1024x1024 / 1536x1024 / 1024x1536 / auto / match 或 WxH")
        w, h = int(m.group(1)), int(m.group(2))
        if w % 16 or h % 16:
            warn(f"自定义尺寸 {w}x{h} 不是 16 的倍数，上游可能拒绝（文档要求宽高都是 16 的倍数）")
        if max(w, h) > CUSTOM_SIZE_MAX_SIDE or not (CUSTOM_SIZE_MIN_PX <= w * h <= CUSTOM_SIZE_MAX_PX):
            warn(f"自定义尺寸 {w}x{h} 超出文档区间（16 倍数 / 单边 ≤{CUSTOM_SIZE_MAX_SIDE} / "
                 f"总像素 {CUSTOM_SIZE_MIN_PX}~{CUSTOM_SIZE_MAX_PX}），可能被拒")
        return f"{w}x{h}", ""
    return spec, ""


# --------------------------------------------------------------------------- 计划


@dataclass
class Step:
    tag: str                       # 输出前缀后缀，如 "" / "-s1" / "-m2"
    prompt: str
    mask: Image.Image | None       # 内部 mask（255 = 要重绘），None = 不带 mask 的整图编辑
    mask_srcs: list                # 参与合成的原始 mask 路径
    note: str = ""


def pair_prompts(args, n_masks: int) -> list:
    """--mask-prompt 按下标与 --mask 配对；不足的落回 --prompt。"""
    prompts = list(args.mask_prompt or [])
    if len(prompts) > n_masks:
        warn(f"--mask-prompt 给了 {len(prompts)} 条，但只有 {n_masks} 个 mask，多出的忽略")
        prompts = prompts[:n_masks]
    while len(prompts) < n_masks:
        prompts.append(args.prompt or "")
    return prompts


def build_steps(args, edit_masks: list) -> list:
    n = len(edit_masks)
    if n == 0:
        return [Step("", args.prompt, None, [], "整图编辑（未提供 mask）")]
    prompts = pair_prompts(args, n)
    mode = args.mask_mode
    if mode == "union" or n == 1:
        if n > 1:
            union = edit_masks[0]
            for m in edit_masks[1:]:
                union = ImageChops.lighter(union, m)
            if any(p and p != args.prompt for p in prompts):
                warn("union 模式把多块并成一张 mask，模型分不清哪块该改成什么；"
                     "要做到「A 换武器、B 换衣服」请用 --mask-mode sequential")
            extra = [p for p in prompts if p and p != args.prompt]
            prompt = (args.prompt or "") + ("\n同时需要：" + "；".join(extra) if extra else "")
            return [Step("", prompt.strip(), union, list(args.mask),
                         f"union：{n} 张 mask 并成 1 张，1 次调用")]
        return [Step("", prompts[0] or args.prompt, edit_masks[0], list(args.mask), "单 mask，1 次调用")]
    if mode == "sequential":
        steps = []
        for i, m in enumerate(edit_masks):
            if not prompts[i]:
                die(f"第 {i + 1} 个 mask 没有 prompt：请给 --prompt 或第 {i + 1} 条 --mask-prompt")
            steps.append(Step(f"-s{i + 1}", prompts[i], m, [args.mask[i]],
                              "上一张输出作为下一次输入（逐块改，N 次调用）"))
        return steps
    if mode == "separate":
        steps = []
        for i, m in enumerate(edit_masks):
            if not prompts[i]:
                die(f"第 {i + 1} 个 mask 没有 prompt：请给 --prompt 或第 {i + 1} 条 --mask-prompt")
            steps.append(Step(f"-m{i + 1}", prompts[i], m, [args.mask[i]],
                              "每个 mask 各出 1 张，都基于原图（N 个候选，N 次调用）"))
        return steps
    die(f"未知 --mask-mode {mode}")


# --------------------------------------------------------------------------- HTTP


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str, request_id: str = "", etype: str = "", code: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.request_id = request_id
        self.etype = etype          # 官方建议：用 error.type 做分支，message 只用于展示
        self.code = code

    def __str__(self) -> str:
        bits = []
        if self.status:
            bits.append(f"HTTP {self.status}")
        if self.code and self.code != str(self.status):
            bits.append(f"code={self.code}")
        if self.etype:
            bits.append(f"type={self.etype}")
        head = " ".join(bits)
        return f"{head}：{self.message}" if head else self.message


def parse_error_body(r) -> tuple:
    """返回 (message, type, code)。ZenMux 统一结构 {"error": {"code","type","message"}}。"""
    try:
        body = r.json()
    except ValueError:
        return (r.text or "")[:400], "", ""
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or ""), str(err.get("type") or ""), str(err.get("code") or "")
    if isinstance(err, str):
        return err, "", ""
    return json.dumps(body, ensure_ascii=False)[:400], "", ""


def post_edit(session, args, key, prompt: str, images: list, mask_png: bytes | None,
              stream: bool, on_partial=None):
    """发一次 images/edits。返回 (图片字节列表, meta dict)。"""
    url = args.base_url.rstrip("/") + "/images/edits"
    params: dict = {
        "model": args.model,
        "prompt": prompt,
        "n": args.n,
        "size": args.size_resolved,
        "quality": args.quality,
        "output_format": args.output_format,
    }
    if args.background and args.background != "none":
        params["background"] = args.background
    if args.output_compression is not None:
        params["output_compression"] = args.output_compression
    if args.moderation:
        params["moderation"] = args.moderation
    if args.input_fidelity:
        params["input_fidelity"] = args.input_fidelity
    if stream:
        params["stream"] = True
        params["partial_images"] = args.partials

    headers = {"Authorization": f"Bearer {key}"}
    if args.transport == "json":
        body = dict(params)
        body["images"] = [{"image_url": data_url(b)} for b in images]
        if mask_png:
            body["mask"] = {"image_url": data_url(mask_png)}
        payload = json.dumps(body, ensure_ascii=False)
        if args.dump_request:
            dump = dict(body)
            dump["images"] = [{"image_url": f"<data:image/png;base64, {len(b)} bytes>"} for b in images]
            if mask_png:
                dump["mask"] = {"image_url": f"<data:image/png;base64, {len(mask_png)} bytes>"}
            dump["_note"] = f"transport=json，{len(images)} 张输入图；真实请求体里是完整 base64 data URL"
            write_dump(args, dump)
        t0 = time.time()
        r = session.post(url, headers={**headers, "Content-Type": "application/json"},
                         data=payload.encode("utf-8"), timeout=(10, args.timeout), stream=stream)
    else:
        field = args.multipart_field          # 文档正文写 image，curl 示例写 image[]，用 flag 兜底
        files = [(field, (f"image{i + 1}.png", b, "image/png")) for i, b in enumerate(images)]
        if mask_png:
            files.append(("mask", ("mask.png", mask_png, "image/png")))
        data = {k: ("true" if v is True else str(v)) for k, v in params.items()}
        if args.dump_request:
            write_dump(args, {"_note": "transport=multipart，下面是表单字段（文件只记体积）",
                              "params": data, "file_field": field,
                              "images_bytes": [len(b) for b in images],
                              "mask_bytes": len(mask_png) if mask_png else None})
        t0 = time.time()
        r = session.post(url, headers=headers, data=data, files=files, timeout=(10, args.timeout), stream=stream)

    request_id = r.headers.get("x-request-id") or r.headers.get("x-zenmux-request-id") or ""
    ctype = (r.headers.get("content-type") or "").lower()
    if r.status_code >= 400:
        msg, etype, code = parse_error_body(r)
        raise ApiError(r.status_code, msg or r.reason, request_id, etype, code)

    meta = {"request_id": request_id, "status": r.status_code, "content_type": ctype,
            "elapsed_s": round(time.time() - t0, 2), "endpoint": url, "transport": args.transport}

    if stream and "text/event-stream" in ctype:
        images_out, sse = parse_sse(r, on_partial, request_id)
        r.close()
        meta["events"] = len(sse)
        if sse:
            meta["usage"] = sse[-1].get("usage")
            meta["created"] = sse[-1].get("created_at")
            meta["size_returned"] = sse[-1].get("size")
            meta["background_returned"] = sse[-1].get("background")
    else:
        if stream:
            warn(f"服务端没返回 SSE（content-type={ctype or '未知'}），按一次性 JSON 解析")
        try:
            body = r.json()
        except ValueError:
            raise ApiError(r.status_code, "响应不是 JSON：" + (r.text or "")[:300], request_id)
        images_out = decode_images(body, request_id)
        meta["usage"] = body.get("usage")
        meta["created"] = body.get("created")
        meta["revised_prompt"] = (body.get("data") or [{}])[0].get("revised_prompt") if body.get("data") else None
        meta["size_returned"] = body.get("size")
        meta["background_returned"] = body.get("background")
        meta["output_format_returned"] = body.get("output_format")
    meta["elapsed_s"] = round(time.time() - t0, 2)
    return images_out, meta


def write_dump(args, payload: dict) -> None:
    """把请求体（base64 折叠）写到 out-dir，多步调用各写一份，便于复盘参数。"""
    out_dir = Path(args.dump_request)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = getattr(args, "dump_suffix", "") or ""
    (out_dir / f"request{tag}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def decode_images(body: dict, request_id: str = "") -> list:
    data = body.get("data") or []
    out = []
    for i, item in enumerate(data):
        b64 = item.get("b64_json")
        if b64:
            out.append(base64.b64decode(b64))
        elif item.get("url"):
            out.append(item["url"])          # 少数模型回 URL，交给调用方处理
        else:
            warn(f"响应 data[{i}] 既没有 b64_json 也没有 url，跳过")
    if not out:
        raise ApiError(200, f"响应里没有图片：{json.dumps(body, ensure_ascii=False)[:300]}", request_id)
    return out


def parse_sse(resp, on_partial=None, request_id: str = "") -> tuple:
    """解析 image_edit.partial_image / image_edit.completed 事件。

    流一旦开始，ZenMux 出错不会回标准 JSON，而是在流内发失败事件或直接断流
    （见 error-codes 的 "Errors During Streaming"），所以这里必须显式识别 error 事件。
    """
    done = []
    partials = []
    event_name = ""
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip()
        if not line:
            continue
        if line.startswith(":"):            # ": ZENMUX PROCESSING" 保活注释，按 SSE 规范忽略
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk in ("", "[DONE]"):
            continue
        try:
            ev = json.loads(chunk)
        except ValueError:
            continue
        etype = str(ev.get("type") or event_name or "")
        err = ev.get("error") if isinstance(ev.get("error"), dict) else None
        if err or "error" in etype.lower() or "failed" in etype.lower():
            payload = err or ev
            msg = str(payload.get("message") or payload.get("detail") or json.dumps(ev, ensure_ascii=False)[:300])
            raise ApiError(0, f"流内错误：{msg}", request_id,
                           str(payload.get("type") or etype), str(payload.get("code") or ""))
        if etype.endswith("partial_image"):
            partials.append(ev)
            if on_partial:
                on_partial(ev.get("partial_image_index", len(partials) - 1), ev)
        elif etype.endswith("completed") or "b64_json" in ev:
            done.append(ev)
    if not done:
        raise ApiError(0, f"流式响应里没有 completed 事件（收到 {len(partials)} 个 partial）——"
                          f"流可能被中断或上游出错；先用 x-request-id 去 platform 日志核对是否已计费",
                       request_id)
    out = []
    for ev in done:
        b64 = ev.get("b64_json")
        if b64:
            out.append(base64.b64decode(b64))
    if not out:
        raise ApiError(200, "completed 事件里没有 b64_json")
    return out, done


# --------------------------------------------------------------------------- 产出


def unique_path(path: Path) -> Path:
    """不覆盖既有产物：重名就加 -2 / -3 …"""
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not cand.exists():
            warn(f"{path.name} 已存在，改写为 {cand.name}（不覆盖旧产物）")
            return cand
    return path


def save_outputs(out_dir: Path, prefix: str, images: list, meta: dict, fmt: str) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, item in enumerate(images):
        name = f"{prefix}.{fmt}" if len(images) == 1 else f"{prefix}-{i + 1}.{fmt}"
        path = out_dir / name
        if isinstance(item, bytes):
            ext = sniff_ext(item, fmt)
            if ext != fmt:
                path = out_dir / (f"{prefix}.{ext}" if len(images) == 1 else f"{prefix}-{i + 1}.{ext}")
            path = unique_path(path)
            path.write_bytes(item)
        else:                                      # 服务端给了 URL
            path = unique_path(path)
            r = requests.get(item, timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
        side = unique_path(path.with_suffix(".json"))
        side.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written


def probe_image_shape(data: bytes):
    try:
        with Image.open(io.BytesIO(data)) as im:
            return f"{im.size[0]}x{im.size[1]} {im.mode}"
    except Exception:
        return "无法解析"


# --------------------------------------------------------------------------- check


def fetch_catalog(base_url: str, timeout: int = 30) -> list:
    r = requests.get(base_url.rstrip("/") + "/models", timeout=timeout)
    r.raise_for_status()
    return (r.json().get("data") or [])


def cmd_check(args) -> int:
    ok = True
    env = load_env()
    key = args.api_key or os.environ.get("ZENMUX_API_KEY") or env.get("ZENMUX_API_KEY")
    if key:
        log(f"[ok]   ZENMUX_API_KEY 已读到（{mask_key(key)}，来自 {'命令行/环境变量' if (args.api_key or os.environ.get('ZENMUX_API_KEY')) else '.env'}）")
        hint = key_kind_hint(key)
        if hint:
            ok = False
            log(f"[fail] {hint}")
    else:
        ok = False
        log("[fail] 没有 ZENMUX_API_KEY —— 在工作区根 .env 加一行 ZENMUX_API_KEY=sk-...")

    try:
        models = fetch_catalog(args.base_url)
        img_models = [m for m in models if "image" in (m.get("output_modalities") or [])]
        log(f"[ok]   ZenMux 可达，模型 {len(models)} 个，其中可出图 {len(img_models)} 个：")
        for m in img_models:
            mark = " ←当前 --model" if m.get("id") == args.model else ""
            log(f"         {m.get('id')}{mark}")
        ids = {m.get("id") for m in models}
        if args.model not in ids:
            plain = args.model.split("/")[-1]
            hit = [i for i in ids if i.split("/")[-1] == plain]
            if hit:
                log(f"[warn] --model {args.model} 不在列表里，但存在同名不同前缀：{hit}")
            else:
                ok = False
                log(f"[fail] --model {args.model} 不在模型列表里")
        elif "image" not in next(m for m in models if m.get("id") == args.model).get("output_modalities", []):
            ok = False
            log(f"[fail] --model {args.model} 不能出图")
    except Exception as e:                                     # noqa: BLE001
        log(f"[warn] 拉模型列表失败（离线也能用 --dry-run）：{e}")

    if args.image:
        try:
            im = load_image(args.image[0])
            log(f"[ok]   输入图 {args.image[0]}：{im.size[0]}x{im.size[1]} {im.mode}，共 {len(args.image)} 张")
            if len(args.image) > MAX_INPUT_IMAGES:
                ok = False
                log(f"[fail] 输入图 {len(args.image)} 张，超过上限 {MAX_INPUT_IMAGES}")
            for i, m in enumerate(args.mask or [], 1):
                edit = read_edit_mask(m, args.mask_polarity, args.mask_threshold, im.size)
                edit = grow_mask(edit, args.mask_grow)
                pct = coverage(edit)
                flag = "ok  " if 0.0 < pct < 0.95 else "warn"
                log(f"[{flag}] mask{i} {m}：覆盖 {pct * 100:.1f}%"
                    + ("（空 mask，检查 --mask-polarity/--mask-threshold）" if pct <= 0 else
                       "（几乎全选，多半 polarity 反了 → 试 --mask-polarity hole）" if pct >= 0.95 else ""))
        except SystemExit:
            ok = False
        except Exception as e:                                 # noqa: BLE001
            ok = False
            log(f"[fail] 检查输入失败：{e}")

    if args.probe:
        if not key:
            log("[warn] 没有 key，跳过探活")
        else:
            # 探活：故意用一个不存在的模型名，只验证鉴权（ZenMux 的 key 无效是 403 access_denied）
            tiny = png_bytes(Image.new("RGBA", (16, 16), (0, 0, 0, 255)))
            body = {"model": "__zenmux_key_probe__", "prompt": "probe", "n": 1,
                    "images": [{"image_url": data_url(tiny)}]}
            try:
                r = requests.post(args.base_url.rstrip("/") + "/images/edits",
                                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                  data=json.dumps(body).encode("utf-8"), timeout=(10, args.timeout))
                msg, etype, code = parse_error_body(r) if r.status_code >= 400 else ("", "", "")
                if r.status_code == 403 or etype == "access_denied" or r.status_code == 401:
                    ok = False
                    log(f"[fail] 鉴权探活 HTTP {r.status_code} type={etype}（key 无效 / 无权）：{msg}")
                elif r.status_code >= 400:
                    log(f"[ok]   鉴权探活 HTTP {r.status_code} type={etype or '-'}——不是鉴权错误，说明 key 被接受"
                        f"（预期服务端直接拒掉不存在的模型，不出图；若万一返回 2xx 请去 platform 用量页核对）")
                else:
                    ok = False
                    log(f"[warn] 探活竟然 HTTP {r.status_code}：服务端接受了不存在的模型名，"
                        f"可能真的出了图，去 https://zenmux.ai/platform 用量页核对该 request-id")
            except Exception as e:                             # noqa: BLE001
                log(f"[warn] 探活失败（网络）：{e}")

    mg_key, mg_src = resolve_management_key(args)
    if mg_key:
        warn_if_plain_key(mg_key, mg_src)
        try:
            data = fetch_balance(args.base_url, mg_key, args.timeout)
            total = data.get("total_credits")
            log(f"[ok]   {format_balance(data)}（成本控制，来源 {mg_src}）")
            if isinstance(total, (int, float)) and total <= 0:
                ok = False
                log("[fail] 余额 ≤ 0：edit 会被 402 拒，先充值")
        except ApiError as e:
            log(f"[warn] 查余额失败：{e}（不影响 edit；余额接口只认 Management API Key）")
        except Exception as e:                                 # noqa: BLE001
            log(f"[warn] 查余额失败（网络）：{e}")
    else:
        log("[warn] 没配 Management API Key，跳过余额检查（要成本控制就写 ZENMUX_MANAGEMENT_API_KEY）")

    log("[结论] " + ("自检通过，可以 edit（会消耗额度）" if ok else "自检有问题，先按上面的 [fail] 修"))
    return 0 if ok else 1


# --------------------------------------------------------------------------- edit


def cmd_edit(args) -> int:
    key = resolve_api_key(args)
    hint = key_kind_hint(key)
    if hint:
        warn(hint)

    # ---- 本地参数校验：能在花钱前拦下的错误，绝不发给服务端
    if args.n < 1 or args.n > 10:
        die(f"--n {args.n} 不合法：只能 1~10")
    if args.n > 1:
        warn(f"--n {args.n}：ZenMux 对部分模型会直接 400（Parameter n grater than 1 is not supported）；"
             f"另外 sequential 串行只用第一张输出")
    if args.background == "transparent" and args.output_format == "jpeg":
        die("background=transparent 必须配 png 或 webp（jpeg 不支持透明）→ 改 --output-format png")
    if args.output_compression is not None and args.output_format == "png":
        warn("--output-compression 只对 jpeg / webp 有效，png 下会被忽略")

    images = [load_image(p) for p in args.image]
    if len(images) > MAX_INPUT_IMAGES:
        die(f"输入图 {len(images)} 张，超过上限 {MAX_INPUT_IMAGES}")
    if any(args.max_side and max(im.size) > args.max_side for im in images):
        images = [shrink_longest_side(im, args.max_side) for im in images]
        info(f"输入图已缩到最长边 ≤{args.max_side}：{[f'{i.size[0]}x{i.size[1]}' for i in images]}")
    base = images[0]

    edit_masks = []
    for m in args.mask or []:
        edit = read_edit_mask(m, args.mask_polarity, args.mask_threshold, base.size)
        edit = grow_mask(edit, args.mask_grow)
        edit = feather_mask(edit, args.mask_feather)
        pct = coverage(edit)
        if pct <= 0.0:
            die(f"mask {m} 里没有任何候选区域（覆盖 0%）——检查 --mask-polarity / --mask-threshold")
        if pct >= 0.95:
            warn(f"mask {m} 覆盖 {pct * 100:.1f}%，几乎全选；多半 polarity 反了 → 试 --mask-polarity hole")
        info(f"mask {Path(m).name}：要重绘 {pct * 100:.1f}%（polarity={args.mask_polarity}, grow={args.mask_grow}, feather={args.mask_feather}）")
        edit_masks.append(edit)

    if not args.prompt and not any(args.mask_prompt or []):
        die("必须给 --prompt（或每个 mask 一条 --mask-prompt）")
    if not (args.mask or []) and not args.prompt:
        die("没有 mask 时必须给 --prompt：--mask-prompt 只与 --mask 按下标配对，单独给会被忽略"
            "（否则会发一个空 prompt 上去，白白吃一次 400）")

    args.size_resolved, size_note = resolve_size(args.size, base.size)
    steps = build_steps(args, edit_masks)

    out_dir = Path(args.out_dir) if args.out_dir else BASE / "tmp" / "zenmux-edit" / datetime.now().strftime("%Y%m%d-%H%M%S")
    name = args.name or (Path(args.image[0]).stem + "-edit")

    log("── 计划 ─────────────────────────────────────────────")
    log(f"  端点     {args.base_url}/images/edits    传输={args.transport}")
    log(f"  模型     {args.model}")
    log(f"  输出     n={args.n} size={args.size_resolved} quality={args.quality} "
        f"background={args.background or '省略'} format={args.output_format}"
        + (f" stream=on(partials={args.partials})" if args.stream else ""))
    log(f"  输入     {len(images)} 张：" + "、".join(f"{Path(p).name}{list(im.size)}" for p, im in zip(args.image, images)))
    log(f"  mask     {len(edit_masks)} 张，模式={args.mask_mode}")
    for s in steps:
        log(f"  · 调用[{s.tag or '-main'}] mask={'+'.join(Path(x).name for x in s.mask_srcs) or '无'}"
            f"  prompt={s.prompt[:60]!r}  # {s.note}")
    if size_note:
        log(f"  尺寸     {size_note}")
    log(f"  产物     {out_dir}/")
    log(f"  费用     约 {len(steps)} 次图片编辑调用（--retries={args.retries}）")
    log("─────────────────────────────────────────────────────")

    if ("2.5" in args.model) and args.background == "transparent":
        warn("gpt-image-2.5 在 edit 端可能不支持 background=transparent（ZenMux 文档列了该取值，"
             "但第三方实测会 400）：真被拒时 --bg-fallback 会自动去掉该字段重试一次，那张图可能是不透明底。"
             "要保证透明底，改 --model openai/gpt-image-2")

    if args.dump_request:
        args.dump_request = out_dir            # post_edit 里按步骤写 request<tag>.json
        out_dir.mkdir(parents=True, exist_ok=True)

    # mask 预览（验收 polarity/grow，不花钱）
    if edit_masks and args.mask_preview:
        mdir = out_dir / "_masks"
        for src, edit in zip(args.mask, edit_masks):
            stem = Path(src).stem
            mask_preview(base, edit, mdir / f"{stem}-preview.png")
            (mdir / f"{stem}-api.png").write_bytes(api_mask_png(edit))
        info(f"mask 预览（红=要重绘 / 绿线=边界）→ {mdir}")

    if args.dry_run:
        if args.dump_request:
            info(f"dry-run：请求体预览写到 {args.dump_request}")
        log("[dry-run] 没有调用 API，没有花额度。")
        return 0

    # ---- 成本控制：跑之前守一次余额（--min-credits），跑完再查一次算余额差
    credits_before = None
    mg_key, mg_src = resolve_management_key(args)
    if args.min_credits > 0:
        if not mg_key:
            warn(f"--min-credits {args.min_credits} 没有生效：没配 Management API Key"
                 f"（.env 的 ZENMUX_MANAGEMENT_API_KEY），无法查余额")
        else:
            try:
                data = fetch_balance(args.base_url, mg_key, args.timeout)
                credits_before = data.get("total_credits")
                log(f"余额守卫：{format_balance(data)}（来源 {mg_src}）")
                if not isinstance(credits_before, (int, float)):
                    warn("余额字段不是数字，守卫跳过")
                    credits_before = None
                elif credits_before < args.min_credits:
                    die(f"余额 {credits_before} 低于 --min-credits {args.min_credits}，先充值再跑"
                        f"（https://zenmux.ai/platform）")
            except ApiError as e:
                warn(f"余额查询失败（{e}），守卫跳过；要成本控制请配 Management API Key")
            except Exception as e:                             # noqa: BLE001
                warn(f"余额查询失败（网络：{e}），守卫跳过")

    session = requests.Session()
    cur_images = images
    results = []
    for si, step in enumerate(steps, 1):
        img_bytes = [png_bytes(im) for im in cur_images]
        limit = DATA_URL_FIELD_LIMIT if args.transport == "json" else UPLOAD_LIMIT_BYTES
        for i, b in enumerate(img_bytes):
            raw_cap = int(limit / 4 * 3) if args.transport == "json" else limit
            if len(b) > raw_cap:
                die(f"第 {i + 1} 张输入图 {len(b) / 1048576:.1f}MB 超过 "
                    f"{'JSON 通道的 image_url 字段上限（base64 ≈20MiB → 原图 ≤15MB）' if args.transport == 'json' else '上传上限 50MB'}"
                    f"，请用 --max-side 2048 之类的参数缩小输入，或改用 --transport multipart")
        step_mask = step.mask
        if step_mask is not None and step_mask.size != cur_images[0].size:
            # sequential 串行时，上一步输出尺寸可能变了，mask 必须跟着走（API 要求同尺寸）
            warn(f"mask 尺寸 {step_mask.size[0]}x{step_mask.size[1]} ≠ 当前输入图 "
                 f"{cur_images[0].size[0]}x{cur_images[0].size[1]}，已最近邻缩放")
            step_mask = step_mask.resize(cur_images[0].size, Image.NEAREST)
        mask_png = api_mask_png(step_mask) if step_mask is not None else None
        if mask_png and len(mask_png) > UPLOAD_LIMIT_BYTES:
            die(f"mask PNG {len(mask_png) / 1048576:.1f}MB 超过上传上限 50MB——"
                f"缩小输入图或简化 mask（细碎选区用 --mask-grow 之外不要叠太多层）")
        if mask_png and len(mask_png) > MASK_PNG_WARN_BYTES:
            warn(f"mask PNG {len(mask_png) / 1048576:.1f}MB 偏大（第三方文档称 mask 限 4MB，官方未写），"
                 f"缩小输入图或简化 mask 更稳")

        log(f"[{si}/{len(steps)}] 调用中…（prompt: {step.prompt[:50]}）")
        attempt = 0
        bg_dropped = False
        field_fallback = False
        args.dump_suffix = step.tag
        while True:
            try:
                out, meta = post_edit(session, args, key, step.prompt, img_bytes, mask_png,
                                      args.stream, on_partial=make_partial_printer(out_dir, name, step.tag)
                                      if args.stream and args.save_partials else print_partial)
                break
            except ApiError as e:
                rid = f" (x-request-id={e.request_id})" if e.request_id else ""
                if (e.status == 400 and not bg_dropped and args.bg_fallback
                        and re.search(r"background|transparent", e.message or "", re.I)):
                    warn(f"400 与 background 有关，自动去掉 background 重试一次：{e.message}{rid}")
                    args.background = "none"
                    bg_dropped = True
                    continue
                if (e.status == 400 and not field_fallback and args.transport == "multipart"
                        and args.multipart_field == "image[]" and re.search(r"image", e.message or "", re.I)):
                    warn(f"multipart 字段名 image[] 被拒，换成 image 重试一次：{e.message}{rid}")
                    args.multipart_field = "image"
                    field_fallback = True
                    continue
                if e.status in (429, 500, 502, 503, 504, 520, 524) and attempt < args.retries:
                    attempt += 1
                    wait = min(30, 3 * attempt)
                    warn(f"HTTP {e.status}（{e.message}）{rid}，{wait}s 后重试 {attempt}/{args.retries}")
                    time.sleep(wait)
                    continue
                status_for_hint = e.status or (int(e.code) if (e.code or "").isdigit() else 0)
                hints = {
                    400: "参数被拒：看上面的 message；transparent 背景不被某模型支持时用 --background opaque",
                    402: "余额不足 / 账户欠费 / 订阅额度用尽 → https://zenmux.ai/platform",
                    403: "access_denied = key 无效或没带对（ZenMux 用 403 报鉴权，不是 401）；"
                         "safety_check_failed = 上游安全策略拦了，改 prompt / 换模型",
                    404: "模型不在当前套餐 / 不存在 / 不支持该接口 → check 看模型列表，或换 Pay-As-You-Go key",
                    413: "prompt 太长",
                    422: "平台校验过了但上游处理不了：去掉高级参数（--input-fidelity / --moderation 等）再试",
                    429: "限流 → 降低频率，或稍后重试",
                }.get(status_for_hint, "")
                if e.etype == "access_denied":
                    hints = ("key 无效或没带对（ZenMux 用 403 报鉴权）→ 检查 .env 的 ZENMUX_API_KEY；"
                             "若 key 是 sk-mg- 开头，那是**管理型** key，模型接口一律 403，"
                             "要用普通 API Key 生图")
                die(f"{e}{rid}" + (f"\n       {hints}" if hints else ""), 2)
            except requests.exceptions.ReadTimeout as e:
                if args.retry_on_timeout and attempt < args.retries:
                    attempt += 1
                    warn(f"读超时（{e}），按 --retry-on-timeout 重试 {attempt}/{args.retries}"
                         f"——注意上游可能已经出图并计费")
                    time.sleep(5)
                    continue
                die(f"读超时：{e}\n"
                    f"       ⚠ 请求已经发出去了，上游可能已出图并计费。先别重跑，"
                    f"拿 x-request-id 去 https://zenmux.ai/platform 日志核对；"
                    f"确需自动重试用 --retry-on-timeout", 2)
            except requests.RequestException as e:
                # 连接阶段失败 = 请求没送达，重试安全；读超时单独处理（见上）
                extra = ""
                if "RemoteDisconnected" in str(e) or "Connection aborted" in str(e):
                    extra = ("\n       ↳ 实测：edit 端点上 **background=transparent** 会被网关直接掐断连接"
                             "（不是 4xx）。组件/透明需求建议改 --background opaque，"
                             "并在 prompt 里要\"纯色底\"（如纯洋红 #FF00FF），本地抠底得到透明件；"
                             "多图 multipart 偶发同症状，加 --retries 2 可过")
                if attempt < args.retries:
                    attempt += 1
                    warn(f"连接失败（{e}），5s 后重试 {attempt}/{args.retries}（请求未送达，不会重复计费）")
                    time.sleep(5)
                    continue
                die(f"网络错误：{e}（默认不重试，避免重复计费；确实要重试用 --retries N）" + extra, 2)

        meta.update({"model": args.model, "params": {"n": args.n, "size": args.size_resolved,
                                                     "quality": args.quality, "background": args.background,
                                                     "output_format": args.output_format,
                                                     "stream": bool(args.stream)},
                     "inputs": [str(p) for p in args.image],
                     "masks": [str(m) for m in step.mask_srcs],
                     "mask_mode": args.mask_mode, "prompt": step.prompt,
                     "saved_at": datetime.now().isoformat(timespec="seconds")})
        written = save_outputs(out_dir, name + step.tag, out, meta, args.output_format)
        results += written
        _USAGE_LOG.append({"step": si, "tag": step.tag, "tokens": (meta.get("usage") or {}).get("total_tokens"),
                           "elapsed": meta.get("elapsed_s"), "request_id": meta.get("request_id"),
                           "outputs": [str(p) for p in written]})
        shapes = "、".join(probe_image_shape(b) if isinstance(b, bytes) else "url" for b in out)
        usage = meta.get("usage") or {}
        log(f"      ✓ {len(written)} 张 {shapes}  {meta.get('elapsed_s')}s"
            f"  request-id={meta.get('request_id') or '-'}"
            + (f"  tokens={usage.get('total_tokens')}" if usage else ""))
        for w in written:
            log(f"        {w}")

        if si < len(steps):
            nxt = out[0]
            if isinstance(nxt, bytes):
                following = Image.open(io.BytesIO(nxt))
                following.load()
                cur_images = [following] + images[1:]
            else:
                warn("本步返回的是 URL，无法直接作为下一步输入；下一步仍用原图")

    log("── 完成 ─────────────────────────────────────────────")
    log(f"  共 {len(results)} 个产物：{out_dir}")
    summary = {"saved_at": datetime.now().isoformat(timespec="seconds"), "model": args.model,
               "calls": len(steps), "outputs": [str(p) for p in results],
               "total_tokens": sum((o.get("tokens") or 0) for o in _USAGE_LOG), "min_credits": args.min_credits}
    if credits_before is not None and mg_key:
        try:
            after = fetch_balance(args.base_url, mg_key, args.timeout).get("total_credits")
            if isinstance(after, (int, float)):
                spent = round(credits_before - after, 6)
                log(f"  余额     {credits_before} → {after}，本次消耗 ≈ {spent} USD（余额差，含同账号其它会话的话会偏大）")
                summary["credits_before"] = credits_before
                summary["credits_after"] = after
                summary["credits_spent"] = spent
        except Exception as e:                                 # noqa: BLE001
            warn(f"跑完查余额失败：{e}")
    if _USAGE_LOG:
        log(f"  用量     " + "；".join(f"step{o['step']}: {o.get('tokens') or '?'} tokens"
                                      f"（{o.get('elapsed')}s）" for o in _USAGE_LOG))
    (out_dir / "run-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  账单明细 {out_dir / 'run-summary.json'}")
    log("  建议：把要留的那张手工挑走，别让中间态留在入库目录（见 AGENTS.md 删除规则）")
    return 0


def print_partial(idx, ev) -> None:
    log(f"      · partial #{idx}（{ev.get('size') or ''} {ev.get('quality') or ''}）")


def make_partial_printer(out_dir: Path, name: str, tag: str):
    pdir = out_dir / "_partials"

    def _p(idx, ev) -> None:
        b64 = ev.get("b64_json")
        if not b64:
            return
        pdir.mkdir(parents=True, exist_ok=True)
        p = pdir / f"{name}{tag}-partial{idx}.png"
        p.write_bytes(base64.b64decode(b64))
        log(f"      · partial #{idx} → {p.name}")

    return _p


# --------------------------------------------------------------------------- CLI


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--api-key", help="ZENMUX_API_KEY（默认读环境变量/工作区根 .env）")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"默认 {DEFAULT_BASE_URL}")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"默认 {DEFAULT_MODEL}（编辑精度优先）。同价可选 openai/gpt-image-2.5-flare（速度优先）、"
                        f"openai/gpt-image-2.5-sunburst-2026-09-08（钉版本）、openai/gpt-image-2"
                        f"（上一代；文档明确支持 background=transparent）、openai/gpt-image-1.5")
    p.add_argument("--timeout", type=int, default=300, help="单次请求超时秒数，默认 300")


def add_edit_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--image", "-i", action="append", required=True,
                   help="输入图（可重复，最多 16 张；第 1 张为 mask 的作用对象，也是 image 1）")
    p.add_argument("--mask", "-m", action="append", default=[],
                   help="mask 图（可重复；多个 mask 由 --mask-mode 决定怎么消化）")
    p.add_argument("--mask-prompt", action="append", default=[],
                   help="与 --mask 按下标配对的分区指令；sequential/separate 模式必需")
    p.add_argument("--prompt", "-p", default="", help="编辑指令")
    p.add_argument("--mask-mode", choices=MASK_MODES, default="union",
                   help="union=并成一张(1 次调用) / sequential=逐块改并串起来(N 次) / separate=各出 1 张(N 次)")

    g = p.add_argument_group("mask 处理")
    g.add_argument("--mask-polarity", choices=("marked", "hole"), default="marked",
                   help="marked=不透明/涂白处要重绘（默认，符合人手画 mask 的习惯）；hole=透明/黑色处要重绘")
    g.add_argument("--mask-threshold", type=int, default=128, help="二值化阈值，默认 128")
    g.add_argument("--mask-grow", type=int, default=0, help="正=向外膨胀 N px（把武器边缘一起吃进去），负=腐蚀")
    g.add_argument("--mask-feather", type=float, default=0.0, help="羽化半径 px，默认 0")
    g.add_argument("--mask-preview", dest="mask_preview", action="store_true", default=True)
    g.add_argument("--no-mask-preview", dest="mask_preview", action="store_false")

    g2 = p.add_argument_group("输出与请求")
    g2.add_argument("--n", type=int, default=1, help="每次调用出图张数，默认 1；ZenMux 对 n>1 可能直接 400")
    g2.add_argument("--size", default="1024x1024",
                    help="默认 1024x1024；也可 1536x1024 / 1024x1536 / auto / match（跟随输入图，16 倍数）")
    g2.add_argument("--quality", default="medium", choices=("low", "medium", "high", "xhigh", "max", "auto"),
                    help="默认 medium；xhigh/max 只有 2.5 系列认（ZenMux 文档只列 low/medium/high/auto）")
    g2.add_argument("--background", default="transparent", choices=("transparent", "opaque", "auto", "none"),
                    help="默认 transparent（除非强调不透明）；none=完全不传该字段。transparent 只能配 png/webp")
    g2.add_argument("--output-format", default="png", choices=("png", "jpeg", "webp"), help="默认 png")
    g2.add_argument("--output-compression", type=int, default=None, help="仅 jpeg/webp，0-100")
    g2.add_argument("--moderation", default=None, choices=("low", "auto"))
    g2.add_argument("--input-fidelity", default=None, choices=("high", "low"),
                    help="第三方文档称 gpt-image-2.5 传它会 400（ZenMux 文档未明确）；不确定就别传")
    g2.add_argument("--transport", default="json", choices=("json", "multipart"),
                    help="json=base64 data URL（默认，符合本项目要求）；multipart=OpenAI SDK 那种表单上传")
    g2.add_argument("--multipart-field", default="image[]", choices=("image[]", "image"),
                    help="multipart 的图片字段名：ZenMux 正文写 image、curl 示例写 image[]（默认 image[]，"
                         "被 400 拒绝时自动退回 image）")
    g2.add_argument("--stream", action="store_true", help="走 SSE，边生成边收 partial image")
    g2.add_argument("--partials", type=int, default=1, choices=(0, 1, 2, 3), help="流式中间图数量，默认 1")
    g2.add_argument("--save-partials", action="store_true", help="把中间图落盘到 _partials/")
    g2.add_argument("--out-dir", default=None, help="默认 tmp/zenmux-edit/<时间戳>/；重名不覆盖，自动加 -2")
    g2.add_argument("--name", default=None, help="输出文件名前缀，默认 <输入图名>-edit")
    g2.add_argument("--max-side", type=int, default=0, help="输入图最长边上限（0=不缩；超 15MB 时用它）")
    g2.add_argument("--dry-run", action="store_true", help="只做本地校验/预览/打印计划，不调 API")
    g2.add_argument("--dump-request", action="store_true",
                    help="把请求体（base64 折叠）写到 out-dir/request<步骤>.json，便于复盘参数")
    g2.add_argument("--retries", type=int, default=0,
                    help="可重试错误（429/500/502/503/504/520/524 + 连接失败）的重试次数，默认 0")
    g2.add_argument("--retry-on-timeout", action="store_true",
                    help="读超时也重试（默认不重试：请求可能已送达并计费）")
    g2.add_argument("--min-credits", type=float, default=0.0,
                    help="成本控制：开跑前查余额（Management API Key），低于该美元数直接拒跑；跑完打印余额差")
    g2.add_argument("--bg-fallback", dest="bg_fallback", action="store_true", default=True,
                    help="background 参数被 400 拒绝时，去掉该字段重试一次（默认开）")
    g2.add_argument("--no-bg-fallback", dest="bg_fallback", action="store_false")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-") and argv[0] not in ("check", "edit", "balance"):
        die(f"未知子命令 {argv[0]}（只有 check / balance / edit）")
    if argv and argv[0].startswith("-"):
        argv = ["edit"] + argv                                   # 省略子命令时默认 edit

    ap = argparse.ArgumentParser(
        prog="zenmux_edit.py", description="ZenMux 图片编辑（OpenAI Images 协议 + mask 局部重绘）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：python tools/zenmux_edit.py edit -i a.png -m weapon.png -m coat.png "
               "--mask-prompt '换成发光短杖' --mask-prompt '换成深红皮甲' --mask-mode sequential")
    sub = ap.add_subparsers(dest="cmd")

    pc = sub.add_parser("check", help="自检（不花额度）")
    add_common(pc)
    pc.add_argument("--image", action="append", default=[], help="顺带校验这张图/mask")
    pc.add_argument("--mask", action="append", default=[])
    pc.add_argument("--mask-polarity", choices=("marked", "hole"), default="marked")
    pc.add_argument("--mask-threshold", type=int, default=128)
    pc.add_argument("--mask-grow", type=int, default=0)
    pc.add_argument("--probe", action="store_true",
                    help="探活：用不存在的模型名验证鉴权是否被接受（预期 4xx、不出图）")

    pb = sub.add_parser("balance", help="查 PAYG 余额（不花额度，成本控制）")
    add_common(pb)
    pb.add_argument("--json", action="store_true", help="输出原始 JSON")

    pe = sub.add_parser("edit", help="图片编辑（消耗额度）")
    add_common(pe)
    add_edit_args(pe)

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 0
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "balance":
        return cmd_balance(args)
    return cmd_edit(args)


if __name__ == "__main__":
    raise SystemExit(main())
