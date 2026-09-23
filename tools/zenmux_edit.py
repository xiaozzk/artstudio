#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zenmux_edit.py — ZenMux 图片编辑（Vertex AI 协议 :predict 默认；OpenAI Images 协议保留可选）

协议（2026-09-23 起默认 --protocol vertex）：
    * vertex（默认）：POST https://zenmux.ai/api/vertex-ai/v1/publishers/{provider}/models/{model}:predict
      ZenMux 统一生图/编辑入口（OpenAI / 腾讯混元 / 通义 / Flux / Kling / Imagen 等都走这里）。
      文生图 = instances[0].prompt；图编辑 = instances[0].referenceImages（Raw + 可选 Mask，
      mask 语义不变：透明 alpha=0 = 要重绘）。响应 predictions[]：bytesBase64Encoded（Google 系）
      或 gcsUri（腾讯系 COS 签名 URL，工具自动下载）。⚠ background / moderation / SSE 流式
      该协议不支持（background 被忽略，透明件走「纯色底 + tools/flatbg_cut.py 本地抠底」）。
      实测 2026-09-23：tencent/hy-image-v3.0 已可用（目录还没收录），文生图 / 图生图均 200。
    * openai（旧路径，--protocol openai 启用）：/api/v1/images/edits，支持 SSE 流式保活与
      multipart 上传；下列联网行为段落描述的是这条路径。

初心：在素材图上**标记若干部位**，只让模型重绘这些部位（换一把武器 / 换一件衣服 / 改配色），
其余像素尽量不动。

子命令
    check       自检：key、模型是否在架、mask 覆盖面积、PAYG 余额（不花额度）
    balance     查 PAYG 余额（Management API Key，免费）
    cost        查账单（Management API Key，免费）：按模型/时间看花了多少、几次请求
    generation  按 generationId 查单次调用明细（Management API Key，免费）
    edit        图片编辑（**消耗 ZenMux 额度**）

用法示例
    python tools/zenmux_edit.py check
    python tools/zenmux_edit.py balance
    python tools/zenmux_edit.py cost --models openai/gpt-image-2 --dimension BIZ_DT
    python tools/zenmux_edit.py edit --image assets/eva_bone/parts/hero.png \\
        --mask tmp/m_weapon.png --mask-prompt "把手里那把剑换成一把发光的短杖" \\
        --mask tmp/m_coat.png   --mask-prompt "把这件外套换成深红色皮甲" \\
        --mask-mode sequential --min-credits 1 --out-dir tmp/zenmux-edit/run1

联网行为（2026-09 实测口径）
    * **vertex（默认）单次 POST、无 SSE**；openai 协议**默认走 SSE 流式**
      （`--stream`，`--partials 0`）：服务端每 10 秒发一次 `: ZENMUX PROCESSING`
      保活注释，连接不空闲，最不容易被网关掐断；`--no-stream` 可退回一次性 JSON。
    * **不自动重试**（没有任何 retry 开关）：实测被掐断 / 超时的请求**照样计费**，
      自动重试=可能重复烧钱。失败就停下来，用 `cost` / `balance` 核账后人工决定。
    * **每次调用都记录标识**：完整响应头 + `created` + token 用量 + 请求指纹写进
      `<out-dir>/requests.jsonl` 与 `_responses/`，方便跟后台 Logs 页的 Request ID 对账。
    * 图片**没有 Files API**（`/files` 404、上传 500），所以图没法"上传一次、按 id 反复引用"；
      openai 协议要少传字节只能用 `--image-url`（外部可访问 URL）；vertex 只收 base64 内嵌。

成本控制
    * `balance` / `cost` / `edit --min-credits X` 三条路。openai 系
      quality=high **一次 $0.15~0.18**（账单实测），low 估 $0.01~0.02；
      **hy 系单价未实测**，跑完 `cost --models tencent/hy-image-v3.0` 核账。

关于 mask 的硬事实（2026-09 核对官方文档，详见 tools/zenmux-edit.md）
    * **两种协议都只接受 1 个 mask**，且只作用于第一张输入图
      （vertex = referenceImages 里的一个 REFERENCE_TYPE_MASK；openai = 单 mask 字段；
      输入图上限：openai 16 张、Flux 8、Kling 1）。"多个 mask"必须由本工具消化：
        - union      把 N 个 mask 并成 1 张 → 1 次调用（省钱，但模型分不清哪块该改成什么）
        - sequential 每个 mask 一次调用，上一张输出当下一张输入 → 真正的"逐块改"（准，N 倍花费）
        - separate   每个 mask 各出 1 张（都基于原图）→ N 个候选，互相不叠加
    * mask 语义：**透明（alpha=0）= 要重绘的区域**，不透明 = 保留。
      人画的 mask 通常是"涂白/不透明 = 要改"，本工具默认按这个读入（--mask-polarity marked），
      再自动翻成 API 需要的透明洞；若你的 mask 本身就是"透明洞 = 要改"，用 --mask-polarity hole。
    * 输入图与 mask 必须同尺寸：本工具自动把 mask 缩放到第一张输入图的尺寸（并告警）。

产出纪律
    * 每次调用都会记录：HTTP 状态、响应头（全量）、`created`、token usage、请求指纹，
      写成同名 `.json` 边车 + 追加进 `<out-dir>/requests.jsonl`，方便跟后台 Logs 页对账。
    * **不自动重试**：实测被掐断/超时的请求照样计费，所以宁可失败也不替用户重复花钱。
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
DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"          # OpenAI 协议 + 平台管理（余额/账单）端点
VERTEX_BASE_URL = "https://zenmux.ai/api/vertex-ai"    # Vertex AI 协议端点（:predict 统一生图/编辑）
DEFAULT_PROTOCOL = "vertex"                            # 2026-09-23 起默认切到 Vertex 协议（支持的模型更多）
PROTOCOLS = ("vertex", "openai")
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

# 单张编辑的成本（USD/张）。high 是**账单实测**（7 次请求 $1.2009，见 tools/zenmux-edit.md）；
# low / medium 按 OpenAI 官方 quality 分档的 output token 比例（272:1056:4160）从 high 折算，
# 标"估"的部分还没打真机验证。计费大头是 image_output（≈$30/MTok），input 图 ≈$8/MTok。
COST_PER_IMAGE = {"low": "约 $0.01（出图）+ 每张输入图约 $0.008（估）", "medium": "约 $0.04~0.05（估）",
                  "high": "$0.15~0.18（实测）", "xhigh": "更高（未估）", "max": "更高（未估）",
                  "auto": "未知（由服务端定档）"}

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


def fetch_cost(base_url: str, key: str, dimension: str, query_time: str, models: list, timeout: int = 30) -> dict:
    """GET /management/cost —— 官方账单口径（Analysis > Cost）。Management API Key only。"""
    params = {"type": "cost", "query_dimension": dimension, "query_time": query_time}
    if models:
        params["model_slugs"] = ",".join(models)
    r = requests.get(base_url.rstrip("/") + "/management/cost", headers={"Authorization": f"Bearer {key}"},
                     params=params, timeout=(10, timeout))
    if r.status_code >= 400:
        msg, etype, code = parse_error_body(r)
        raise ApiError(r.status_code, msg or r.reason,
                       r.headers.get("x-request-id") or r.headers.get("x-zenmux-request-id") or "", etype, code)
    body = r.json()
    if not isinstance(body, dict) or not body.get("success", True):
        raise ApiError(200, f"cost 响应结构不认识：{json.dumps(body, ensure_ascii=False)[:200]}")
    return body.get("data") or {}


def default_cost_time(dimension: str, now=None) -> str:
    now = now or datetime.now()
    return {"BIZ_MTH": now.strftime("%Y%m"), "BIZ_DT": now.strftime("%Y%m%d"),
            "BIZ_HOUR": now.strftime("%Y%m%d%H")}.get(dimension, now.strftime("%Y%m"))


def fetch_generation(base_url: str, key: str, gen_id: str, timeout: int = 30) -> dict:
    """GET /management/generation?id=<generationId> —— 单次调用明细（用量/账单）。免费。"""
    r = requests.get(base_url.rstrip("/") + "/management/generation", params={"id": gen_id},
                     headers={"Authorization": f"Bearer {key}"}, timeout=(10, timeout))
    if r.status_code >= 400:
        msg, etype, code = parse_error_body(r)
        raise ApiError(r.status_code, msg or r.reason,
                       r.headers.get("x-request-id") or r.headers.get("x-zenmux-request-id") or "", etype, code)
    body = r.json()
    return body.get("data") if isinstance(body, dict) and "data" in body else body


def cmd_generation(args) -> int:
    """按 generationId 查单次调用明细（免费）。id 从控制台 Logs 页的 Request 搜索框里拿。"""
    key, source = resolve_management_key(args)
    if not key:
        die("没有 Management API Key（.env 的 ZENMUX_MANAGEMENT_API_KEY）")
    warn_if_plain_key(key, source)
    try:
        data = fetch_generation(args.base_url, key, args.id, args.timeout)
    except ApiError as e:
        hint = ""
        if e.status in (403, 404):
            hint = ("\n       id 必须是**你账号真实产生**的 generationId（形如 2534CCEDTKJR00217635，"
                    "在控制台 Logs 页的 Request 搜索框里查）。实测：格式不对 → 404 Not Found；"
                    "格式对但不属于本账号 → 403。另外只认个人账号的 sk-mg- 管理型 key。")
        die(f"查调用明细失败：{e}" + hint, 2)
    log(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_cost(args) -> int:
    """查账单（免费）。用来回答"刚那次被掐断的请求到底计费没有"。"""
    key, source = resolve_management_key(args)
    if not key:
        die("没有 Management API Key。在**工作区根** .env 里加一行：\n"
            "    ZENMUX_MANAGEMENT_API_KEY=sk-mg-...\n"
            "在 https://zenmux.ai/platform/management 创建")
    warn_if_plain_key(key, source)
    qt = args.time or default_cost_time(args.dimension)
    models = [m for spec in (args.models or []) for m in spec.split(",") if m]
    if not models and getattr(args, "model", None) and args.model != DEFAULT_MODEL:
        warn(f"cost 按 --models 过滤；你给的 --model {args.model} 在这里被忽略（现在查全部模型）")
    try:
        data = fetch_cost(args.base_url, key, args.dimension, qt, models, args.timeout)
    except ApiError as e:
        hint = ""
        if e.status == 429:
            hint = "\n       账单接口与 Usage 共享 60 次/分钟限流，等一分钟再试"
        elif e.status == 403 or e.etype == "access_denied":
            hint = "\n       只认个人账号的 sk-mg- 管理型 key（组织 key / 普通 key 会被拒）"
        die(f"查账单失败：{e}" + hint, 2)

    if args.json:
        log(json.dumps(data, ensure_ascii=False, indent=2))
    s = data.get("summary") or {}
    log(f"账单 {args.dimension}={qt}" + (f"  模型={','.join(models)}" if models else "（全部模型）"))
    if not s.get("totalCost") and not s.get("requestCounts"):
        log("  （该时间段没有数据；账单有 3~5 分钟延迟，刚跑完的请求可能还没入库）")
    else:
        log(f"  合计 ${s.get('totalCost')}   请求 {s.get('requestCounts')} 次   均价 ${s.get('requestAvgCost')}")
        log(f"  输入 ${s.get('inputCost')} / 输出 ${s.get('outputCost')} / 其它 ${s.get('otherCost')}"
            f"   共 {s.get('totalTokens')} tokens")
    for row in (data.get("analysis") or {}).get("costByModel") or []:
        log(f"  · {row.get('bizTime')}  {row.get('modelSlug')}  ${row.get('billAmount')}  {row.get('requestCounts')} 次")
    for row in (data.get("analysis") or {}).get("costByTokenType") or []:
        log(f"  · 计费项 {row.get('tokenType')}: ${row.get('billAmount')}")
    return 0


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
              stream: bool, on_partial=None, image_refs: list | None = None, mask_ref: str | None = None):
    """发一次 images/edits。返回 (图片字节列表, meta dict)。

    `image_refs` / `mask_ref`：可选的 `file:<FILE_ID>` / `<https URL>` 引用（JSON 通道专用），
    用来跳过本地图像字节 —— 实测 ZenMux **没有 Files API**（`/files` 404、上传 500），
    所以 file_id 只能是你从别处拿到的；URL 需要图片能被公网访问。
    """
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
        if image_refs:
            body["images"] = [ref_to_image_url(r) for r in image_refs]
        else:
            body["images"] = [{"image_url": data_url(b)} for b in images]
        if mask_ref:
            body["mask"] = ref_to_image_url(mask_ref)
        elif mask_png:
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

    response_headers = {k: v for k, v in r.headers.items()}
    request_id = (r.headers.get("x-request-id") or r.headers.get("x-zenmux-request-id")
                  or r.headers.get("x-generation-id") or "")
    ctype = (r.headers.get("content-type") or "").lower()
    if r.status_code >= 400:
        msg, etype, code = parse_error_body(r)
        err = ApiError(r.status_code, msg or r.reason, request_id, etype, code)
        err.headers = response_headers
        raise err

    meta = {"request_id": request_id, "status": r.status_code, "content_type": ctype,
            "elapsed_s": round(time.time() - t0, 2), "endpoint": url, "transport": args.transport,
            "started_at": datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
            "response_headers": response_headers}

    if stream and "text/event-stream" in ctype:
        images_out, sse = parse_sse(r, on_partial, request_id)
        r.close()
        meta["events"] = len(sse)
        if sse:
            meta["usage"] = sse[-1].get("usage")
            meta["created"] = sse[-1].get("created_at")
            meta["size_returned"] = sse[-1].get("size")
            meta["background_returned"] = sse[-1].get("background")
            meta["response_body"] = strip_b64(sse[-1])
    else:
        if stream:
            warn(f"服务端没返回 SSE（content-type={ctype or '未知'}），按一次性 JSON 解析")
        try:
            body = r.json()
        except ValueError:
            err = ApiError(r.status_code, "响应不是 JSON：" + (r.text or "")[:300], request_id)
            err.headers = response_headers
            raise err
        images_out = decode_images(body, request_id)
        meta["usage"] = body.get("usage")
        meta["created"] = body.get("created")
        meta["revised_prompt"] = (body.get("data") or [{}])[0].get("revised_prompt") if body.get("data") else None
        meta["size_returned"] = body.get("size")
        meta["background_returned"] = body.get("background")
        meta["output_format_returned"] = body.get("output_format")
        meta["response_body"] = strip_b64(body)      # 去掉 b64，保留所有 id / usage 字段
    meta["elapsed_s"] = round(time.time() - t0, 2)
    meta["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return images_out, meta


# --------------------------------------------------------------------------- Vertex AI 协议（:predict）


def split_model(model: str) -> tuple:
    """'tencent/hy-image-v3.0' → ('tencent', 'hy-image-v3.0')；没有 '/' 则 provider 为空。"""
    if "/" in model:
        return tuple(model.split("/", 1))
    return "", model


# Vertex 协议下按**模型家族**兼容（2026-09-23 就两族；新模型照表加一格即可）。
# 能力都来自 ZenMux 官方文档的参数映射表 + 实测：
#   expenditure: openai 用 imageSize/quality 透传；hy 用 aspectRatio(+sampleImageSize/enhancePrompt)
FAMILIES = {
    "openai": {
        "match": lambda provider, model: provider == "openai",
        "label": "OpenAI gpt-image 系",
        "size_param": "imageSize",            # 顶层透传
        "quality_param": "quality",           # 顶层透传：low/medium/high/auto
        "n_max": 10,
        "enhance": False,                     # 文档未列，非支持面
        "negative": False,                    # mapping 表里没有 negativePrompt
    },
    "hy": {
        "match": lambda provider, model: provider == "tencent" and model.startswith("hy"),
        "label": "腾讯混元 hy-image 系",
        "size_param": None,                   # 不吃 imageSize；走 parameters.aspectRatio
        "quality_param": None,                # 没有 quality 分档
        "n_max": 1,                           # 官方文档：Hunyuan 单次只能出 1 图
        "enhance": True,                      # 支持 enhancePrompt（文档明确列了 Hunyuan）
        "negative": None,                     # 文档只列 Imagen/Kling/通义，未证实——带上传，被 400 就去掉
    },
}
FAMILY_DEFAULT = {                              # 未收录家族的兜底（通义/Flux/Kling 等按这个走）
    "label": "Vertex 通用（未实测家族）",
    "size_param": None,
    "quality_param": None,
    "n_max": 10,
    "enhance": True,
}


def model_family(model: str) -> str:
    """'openai/gpt-image-2' → 'openai'；'tencent/hy-image-v3.0' → 'hy'；其余 'generic'。"""
    provider, model = split_model(model)
    for name, fam in FAMILIES.items():
        if fam["match"](provider, model):
            return name
    return "generic"


def family_of(model: str) -> dict:
    return FAMILIES.get(model_family(model), FAMILY_DEFAULT)


def size_to_aspect(size_spec: str, base_size: tuple) -> str | None:
    """把 --size 规格换成 Vertex 的 aspectRatio（非 OpenAI 模型用）；auto → None（不发）。"""
    spec = size_spec
    if spec == "match":
        w, h = base_size
    elif spec == "auto":
        return None
    else:
        m = re.fullmatch(r"(\d{3,5})x(\d{3,5})", (spec or "").strip())
        if not m:
            return None
        w, h = int(m.group(1)), int(m.group(2))
    from math import gcd
    g = gcd(w, h) or 1
    return f"{w // g}:{h // g}"


def post_edit_vertex(session, args, key, prompt: str, images: list, mask_png: bytes | None):
    """ZenMux Vertex AI 协议：POST {vertex_url}/v1/publishers/{provider}/models/{model}:predict

    对应官方 SDK 的 generate_images（无输入图）/ edit_image（有输入图）。返回 (图片列表, meta)。
    请求体（Vertex AI predict 格式）：
        instances[0] = {"prompt": ..., "referenceImages": [Raw×N, Mask?(maskMode=USER_PROVIDED)]}
        parameters   = {"sampleCount": n, "outputOptions": {"mimeType": ...}, ...}
    透传参数（SDK 的 http_options.extra_body → REST 请求体顶层）：
        OpenAI 模型：imageSize / quality；非 OpenAI（如腾讯混元）：sampleImageSize（1K/2K/4K）。
    响应 predictions[]：bytesBase64Encoded（Google 系）或 gcsUri（腾讯系 COS 签名 URL，直接 GET）。
    """
    provider, model = split_model(args.model)
    if not provider:
        die(f"Vertex 协议需要 provider/model 形式的模型名（如 tencent/hy-image-v3.0），收到：{args.model}")
    url = args.vertex_url.rstrip("/") + f"/v1/publishers/{provider}/models/{model}:predict"

    refs = []
    for i, b in enumerate(images):
        refs.append({"referenceType": "REFERENCE_TYPE_RAW", "referenceId": i + 1,
                     "referenceImage": {"bytesBase64Encoded": base64.b64encode(b).decode("ascii"),
                                        "mimeType": "image/png"}})
    if mask_png:
        refs.append({"referenceType": "REFERENCE_TYPE_MASK", "referenceId": len(images) + 1,
                     "referenceImage": {"bytesBase64Encoded": base64.b64encode(mask_png).decode("ascii"),
                                        "mimeType": "image/png"},
                     "maskImageConfig": {"maskMode": "MASK_MODE_USER_PROVIDED"}})
    instance: dict = {"prompt": prompt}
    if refs:
        instance["referenceImages"] = refs

    mime = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}[args.output_format]
    fam = family_of(args.model)                            # 家族能力表（openai / hy / 通用）
    params: dict = {"sampleCount": args.n, "outputOptions": {"mimeType": mime}}
    if args.output_compression is not None and args.output_format in ("jpeg", "webp"):
        params["outputOptions"]["compressionQuality"] = args.output_compression
    if args.negative_prompt:
        if fam.get("negative") is False:
            warn(f"--negative-prompt：{fam['label']} 不支持该参数，已忽略")
        else:
            if fam is FAMILY_DEFAULT or "negative" not in fam:
                info(f"negativePrompt 对 {fam['label']} 未在官方文档列出（Imagen/Kling/通义 支持），已带上；被 400 就去掉")
            params["negativePrompt"] = args.negative_prompt
    if args.enhance_prompt:
        if fam.get("enhance"):
            params["enhancePrompt"] = True            # Hunyuan / Flux / 通义 支持
        else:
            warn(f"--enhance-prompt：{fam['label']} 不支持该参数，已忽略")

    body: dict = {"instances": [instance], "parameters": params}
    if fam["size_param"] and args.size_resolved:
        body[fam["size_param"]] = args.size_resolved           # openai：顶层透传 imageSize
    if fam["quality_param"] and args.quality and args.quality != "auto":
        body[fam["quality_param"]] = args.quality              # openai：顶层透传 quality
    if not fam["size_param"]:                                  # 非 openai 家族：aspectRatio 控比例
        aspect = args.aspect_ratio or size_to_aspect(args.size, getattr(args, "_base_size", (1024, 1024)))
        if aspect:
            params["aspectRatio"] = aspect
        if args.sample_image_size:
            body["sampleImageSize"] = args.sample_image_size   # 1K/2K/4K 透传（火山/百度/混元系）

    if args.dump_request:
        dump = json.loads(json.dumps(body))                # 深拷贝后折叠 base64
        for ref in dump["instances"][0].get("referenceImages", []):
            img = ref.get("referenceImage", {})
            if "bytesBase64Encoded" in img:
                img["bytesBase64Encoded"] = f"<base64 {len(img['bytesBase64Encoded'])} chars>"
        dump["_note"] = f"protocol=vertex predict，provider={provider}"
        write_dump(args, dump)

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    t0 = time.time()
    r = session.post(url, headers=headers, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                     timeout=(10, args.timeout))
    response_headers = {k: v for k, v in r.headers.items()}
    request_id = (r.headers.get("x-request-id") or r.headers.get("x-zenmux-request-id")
                  or r.headers.get("x-generation-id") or "")
    if r.status_code >= 400:
        msg, etype, code = parse_error_body(r)
        err = ApiError(r.status_code, msg or r.reason, request_id, etype, code)
        err.headers = response_headers
        raise err
    try:
        resp_body = r.json()
    except ValueError:
        err = ApiError(r.status_code, "响应不是 JSON：" + (r.text or "")[:300], request_id)
        err.headers = response_headers
        raise err

    preds = resp_body.get("predictions") or []
    out = []
    for i, p in enumerate(preds):
        if p.get("bytesBase64Encoded"):
            out.append(base64.b64decode(p["bytesBase64Encoded"]))
        elif p.get("gcsUri"):
            out.append(p["gcsUri"])                        # 腾讯系：COS 签名 URL，save_outputs 会下载
        else:
            warn(f"predictions[{i}] 既没有 bytesBase64Encoded 也没有 gcsUri，字段：{list(p.keys())}")
    if not out:
        raise ApiError(200, f"响应里没有图片：{json.dumps(resp_body, ensure_ascii=False)[:300]}", request_id)

    meta = {"request_id": request_id, "status": r.status_code, "protocol": "vertex",
            "content_type": (r.headers.get("content-type") or "").lower(),
            "elapsed_s": round(time.time() - t0, 2), "endpoint": url, "transport": "vertex-predict",
            "started_at": datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "response_headers": response_headers,
            "usage": resp_body.get("usageMetadata") or resp_body.get("usage"),
            "response_body": strip_b64(resp_body)}
    return out, meta


def strip_b64(obj):
    """递归把 b64_json / 超长字符串换成占位符，保留响应里所有 id / usage 字段。"""
    if isinstance(obj, dict):
        return {k: (f"<base64 {len(v)} chars>" if k in ("b64_json", "partial_image", "image_base64",
                                                         "bytesBase64Encoded")
                    and isinstance(v, str) else strip_b64(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_b64(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 2000:
        return f"<{len(obj)} chars>"
    return obj


def ref_to_image_url(ref: str) -> dict:
    """`file:<id>` → {"file_id": id}；`url:<https://…>` → {"image_url": url}；其它当 URL 透传。"""
    if ref.startswith("file:"):
        return {"file_id": ref[5:].strip()}
    if ref.startswith("url:"):
        return {"image_url": ref[4:].strip()}
    return {"image_url": ref}


def sha256_file(path) -> str:
    import hashlib
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


def record_request(out_dir, entry: dict) -> None:
    """把每次调用追加进 <out-dir>/requests.jsonl —— 出问题时按时间/用量跟后台 Logs 对账。"""
    try:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        entry = dict(entry)
        entry.setdefault("logged_at", datetime.now().isoformat(timespec="seconds"))
        with open(out_dir / "requests.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError as e:                                     # 记账失败不该拖垮主流程
        warn(f"写 requests.jsonl 失败：{e}")


def save_response_dump(out_dir, tag: str, meta: dict) -> None:
    """把响应体（b64 已折叠）单独存一份：里面有服务端返回的所有 id / usage 字段。"""
    body = meta.get("response_body")
    if not body:
        return
    try:
        d = Path(out_dir) / "_responses"
        d.mkdir(parents=True, exist_ok=True)
        payload = {"saved_at": datetime.now().isoformat(timespec="seconds"),
                   "request_id": meta.get("request_id"), "created": meta.get("created"),
                   "response_headers": meta.get("response_headers"), "body": body}
        (d / f"response{tag or '-main'}.json").write_text(
            json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    except OSError as e:
        warn(f"写响应存档失败：{e}")


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
            elif args.protocol == "vertex":
                # 目录有滞后：2026-09-23 实测 tencent/hy-image-v3.0 未收录但 :predict 已可用
                log(f"[warn] --model {args.model} 不在模型目录里。Vertex 协议的目录可能滞后"
                    f"（新模型未收录也能用），不确定就先 --dry-run 再小额试一张")
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
            try:
                if args.protocol == "vertex":
                    url = (args.vertex_url.rstrip("/")
                           + "/v1/publishers/openai/models/__zenmux_key_probe__:predict")
                    body = {"instances": [{"prompt": "probe"}], "parameters": {"sampleCount": 1}}
                else:
                    url = args.base_url.rstrip("/") + "/images/edits"
                    tiny = png_bytes(Image.new("RGBA", (16, 16), (0, 0, 0, 255)))
                    body = {"model": "__zenmux_key_probe__", "prompt": "probe", "n": 1,
                            "images": [{"image_url": data_url(tiny)}]}
                r = requests.post(url,
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
    # background：openai 协议默认 transparent；vertex 不支持该参数 → 解析为 none（不发也不告警）
    bg_explicit = args.background
    if args.background is None:
        args.background = "transparent" if args.protocol == "openai" else "none"
    if args.n < 1 or args.n > 10:
        die(f"--n {args.n} 不合法：只能 1~10")
    if args.n > 1:
        warn(f"--n {args.n}：ZenMux 对部分模型会直接 400（Parameter n grater than 1 is not supported）；"
             f"另外 sequential 串行只用第一张输出")
    if args.protocol == "vertex":
        fam = family_of(args.model)
        if args.n > fam["n_max"]:
            die(f"--n {args.n}：{args.model}（{fam['label']}）单次最多 {fam['n_max']} 张 → --n {fam['n_max']}")
        if bg_explicit not in (None, "none"):
            warn("Vertex 协议**不支持 background 参数**（官方映射表标 ❌），已忽略。"
                 "要透明件：prompt 里要纯色底（如 #FF00FF）+ tools/flatbg_cut.py 本地抠底")
        if args.transport != "json":
            die("Vertex 协议只走 JSON（base64 内嵌 instances）——multipart 是 OpenAI 协议的上传通道")
        if args.image_url or args.mask_url:
            die("--image-url / --mask-url 是 OpenAI 协议的 JSON 通道特性；Vertex 协议只支持本地字节内嵌")
        if args.stream:
            info("Vertex :predict 走单次 POST（无 SSE）；--stream 只对 OpenAI 协议生效")
        if args.moderation or args.input_fidelity:
            warn("--moderation / --input-fidelity 是 OpenAI 协议参数，Vertex 协议不支持，已忽略")
        if fam["quality_param"] is None and args.quality not in ("low", "auto"):
            info(f"quality={args.quality} 对 {fam['label']} 无意义（无 quality 分档），不会发送")
        if args.aspect_ratio and not re.fullmatch(r"\d{1,4}:\d{1,4}", args.aspect_ratio):
            die(f"--aspect-ratio {args.aspect_ratio} 需要 '宽:高' 形式（如 1:1 / 16:9 / 3:2）")
    else:
        if args.aspect_ratio or args.sample_image_size or args.enhance_prompt or args.negative_prompt:
            warn("--aspect-ratio / --sample-image-size / --enhance-prompt / --negative-prompt "
                 "是 Vertex 协议参数，OpenAI 协议下会被忽略")
    if args.protocol == "openai" and args.background == "transparent" and args.output_format == "jpeg":
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
    args._base_size = base.size                             # vertex 的 size→aspectRatio 换算要用

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
    if args.protocol == "vertex":
        vp, vm = split_model(args.model)
        fam = family_of(args.model)
        sent = []
        if fam["size_param"] and args.size_resolved:
            sent.append(f"{fam['size_param']}={args.size_resolved}")
        if fam["quality_param"] and args.quality and args.quality != "auto":
            sent.append(f"{fam['quality_param']}={args.quality}")
        if not fam["size_param"]:
            aspect = args.aspect_ratio or size_to_aspect(args.size, getattr(args, "_base_size", (1, 1)))
            if aspect:
                sent.append(f"aspectRatio={aspect}")
            if args.sample_image_size:
                sent.append(f"sampleImageSize={args.sample_image_size}")
            if args.enhance_prompt and fam.get("enhance"):
                sent.append("enhancePrompt=on")
        log(f"  端点     {args.vertex_url}/v1/publishers/{vp}/models/{vm}:predict    协议=Vertex AI")
        log(f"  家族     {fam['label']}（size/quality 分发见上）")
    else:
        log(f"  端点     {args.base_url}/images/edits    传输={args.transport}    协议=OpenAI Images")
    log(f"  模型     {args.model}")
    log(f"  输出     n={args.n} size={args.size_resolved} quality={args.quality} "
        f"format={args.output_format}"
        + (f" background={args.background}" if args.protocol == "openai" else "（vertex 不支持 background，忽略）")
        + (f" stream=on(partials={args.partials})" if (args.stream and args.protocol == "openai") else ""))
    if args.protocol == "vertex" and sent:
        log(f"  发送     " + "；".join(sent))
    log(f"  输入     {len(images)} 张：" + "、".join(f"{Path(p).name}{list(im.size)}" for p, im in zip(args.image, images)))
    log(f"  mask     {len(edit_masks)} 张，模式={args.mask_mode}")
    for s in steps:
        log(f"  · 调用[{s.tag or '-main'}] mask={'+'.join(Path(x).name for x in s.mask_srcs) or '无'}"
            f"  prompt={s.prompt[:60]!r}  # {s.note}")
    if size_note:
        log(f"  尺寸     {size_note}")
    log(f"  产物     {out_dir}/")
    if args.protocol == "vertex":
        famcost = family_of(args.model)
        cost_note = (f"单张 {COST_PER_IMAGE.get(args.quality, '未知')}"
                     if famcost["quality_param"] else
                     f"{famcost['label']} 无 quality 分档，单价未实测 → 跑完 cost 核账")
    else:
        cost_note = f"单张 {COST_PER_IMAGE.get(args.quality, '未知')}（quality={args.quality}）"
    log(f"  成本     {cost_note}；本次约 {len(steps)} 次调用"
        f"（**无自动重试**：被掐断也计费，失败就停下核账）")
    log("─────────────────────────────────────────────────────")

    if args.protocol == "openai" and ("2.5" in args.model) and args.background == "transparent":
        warn("gpt-image-2.5 在 edit 端可能不支持 background=transparent（ZenMux 文档列了该取值，"
             "但第三方实测会 400）。真被拒时工具**不会**自动回退：加 --background opaque 再跑，"
             "透明件用「纯色底 + tools/flatbg_cut.py 本地抠底」")

    image_refs = []
    for ref in args.image_url or []:
        image_refs.append(ref)
    if image_refs and len(image_refs) != len(args.image):
        die(f"--image-url 给了 {len(image_refs)} 个，--image 有 {len(args.image)} 个：两者要按下标一一对应"
            f"（只想用外链、不传本地图的话，--image 仍要给占位路径用于取尺寸）")
    if image_refs and args.transport != "json":
        die("--image-url / --mask-url 只在 --transport json 下有效（multipart 必须上传字节）")
    mask_ref = args.mask_url

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
    # 体积上限按协议走（这两个数字都是 OpenAI 协议口径的，vertex 的 :predict 无公开字段上限）
    raw_cap = int(DATA_URL_FIELD_LIMIT / 4 * 3) if args.protocol == "openai" else UPLOAD_LIMIT_BYTES
    cap_note = ("JSON 通道的 image_url 字段上限（base64 ≈20MiB → 原图 ≤15MB）"
                if args.protocol == "openai" else "保守上限 50MB（vertex 无公开字段上限）")
    for si, step in enumerate(steps, 1):
        img_bytes = [png_bytes(im) for im in cur_images]
        for i, b in enumerate(img_bytes):
            if len(b) > raw_cap:
                die(f"第 {i + 1} 张输入图 {len(b) / 1048576:.1f}MB 超过 {cap_note}"
                    f"，请用 --max-side 2048 之类的参数缩小输入"
                    + ("，或改用 --transport multipart" if args.protocol == "openai" else ""))
        step_mask = step.mask
        if step_mask is not None and step_mask.size != cur_images[0].size:
            # sequential 串行时，上一步输出尺寸可能变了，mask 必须跟着走（API 要求同尺寸）
            warn(f"mask 尺寸 {step_mask.size[0]}x{step_mask.size[1]} ≠ 当前输入图 "
                 f"{cur_images[0].size[0]}x{cur_images[0].size[1]}，已最近邻缩放")
            step_mask = step_mask.resize(cur_images[0].size, Image.NEAREST)
        mask_png = api_mask_png(step_mask) if step_mask is not None else None
        if mask_png and len(mask_png) > UPLOAD_LIMIT_BYTES:
            die(f"mask PNG {len(mask_png) / 1048576:.1f}MB 超过上保守限 50MB——"
                f"缩小输入图或简化 mask（细碎选区用 --mask-grow 之外不要叠太多层）")
        if mask_png and args.protocol == "openai" and len(mask_png) > MASK_PNG_WARN_BYTES:
            warn(f"mask PNG {len(mask_png) / 1048576:.1f}MB 偏大（第三方文档称 mask 限 4MB，官方未写），"
                 f"缩小输入图或简化 mask 更稳")

        log(f"[{si}/{len(steps)}] 调用中…（prompt: {step.prompt[:50]}）")
        args.dump_suffix = step.tag
        try:
            if args.protocol == "vertex":
                out, meta = post_edit_vertex(session, args, key, step.prompt, img_bytes, mask_png)
            else:
                out, meta = post_edit(
                    session, args, key, step.prompt, img_bytes, mask_png, args.stream,
                    on_partial=(make_partial_printer(out_dir, name, step.tag)
                                if args.stream and args.save_partials else print_partial),
                    image_refs=image_refs, mask_ref=mask_ref)
        except ApiError as e:
            rid = f" (request_id={e.request_id})" if e.request_id else ""
            record_request(out_dir, {"tag": step.tag, "ok": False, "status": e.status,
                                     "type": e.etype, "code": e.code, "message": e.message,
                                     "request_id": e.request_id,
                                     "response_headers": getattr(e, "headers", None),
                                     "model": args.model, "prompt": step.prompt,
                                     "inputs": [str(p) for p in args.image],
                                     "masks": [str(m) for m in step.mask_srcs]})
            status_for_hint = e.status or (int(e.code) if (e.code or "").isdigit() else 0)
            hints = {
                400: "参数被拒：看上面的 message；background 被拒就换 --background opaque（+本地抠底），"
                     "multipart 图片字段被拒就加 --multipart-field image。**400 是校验错、不计费**，改完可直接重跑",
                402: "余额不足 / 账户欠费 / 订阅额度用尽 → https://zenmux.ai/platform",
                403: "access_denied = key 无效或没带对（ZenMux 用 403 报鉴权，不是 401）；"
                     "safety_check_failed = 上游安全策略拦了，改 prompt / 换模型",
                404: "模型不在当前套餐 / 不存在 / 不支持该接口 → check 看模型列表，或换 Pay-As-You-Go key",
                413: "prompt 太长",
                422: "平台校验过了但上游处理不了：去掉高级参数（--input-fidelity / --moderation 等）再试",
                429: "限流 → 稍后再跑（脚本不会自动重试）",
                500: "平台内部错误。**可能已经计费**：先 `cost` 核账再决定要不要重跑",
            }.get(status_for_hint, "")
            if e.etype == "access_denied":
                hints = ("key 无效或没带对（ZenMux 用 403 报鉴权）→ 检查 .env 的 ZENMUX_API_KEY；"
                         "若 key 是 sk-mg- 开头，那是**管理型** key，模型接口一律 403，"
                         "要用普通 API Key 生图")
            die(f"{e}{rid}" + (f"\n       {hints}" if hints else ""), 2)
        except requests.exceptions.ReadTimeout as e:
            record_request(out_dir, {"tag": step.tag, "ok": False, "type": "read_timeout",
                                     "message": str(e), "model": args.model, "prompt": step.prompt})
            die(f"读超时：{e}\n"
                f"       ⚠ 请求已经发出去了，上游很可能已经出图并计费（实测有 364s 跑完、客户端先放弃的情况）。\n"
                f"       先别重跑：`python tools/zenmux_edit.py cost --dimension BIZ_DT` 看这几分钟有没有扣款，"
                f"再人工决定（工具**不会**自动重试）", 2)
        except requests.RequestException as e:
            # ⚠ 实测（2026-09-22）：被网关掐断的请求**照样计费**（7 次计费里 5 次没拿到图）。
            # 因此这里绝不自动重试。
            drop = "RemoteDisconnected" in str(e) or "Connection aborted" in str(e)
            record_request(out_dir, {"tag": step.tag, "ok": False,
                                     "type": "connection_dropped" if drop else "connection_error",
                                     "message": str(e), "model": args.model, "prompt": step.prompt})
            extra = ""
            if drop:
                extra = ("\n       ↳ 被掐断多半是 `--background transparent`（实测该参数在 edit 端点会被网关断连）；"
                         "要透明件就 `--background opaque` + prompt 要纯色底（如 #FF00FF）再本地抠底。"
                         "\n       ↳ ⚠ 这次请求**很可能已经计费**（实测被掐断的都进了账单）："
                         "`python tools/zenmux_edit.py cost --dimension BIZ_DT` 核一下。"
                         "\n       ↳ 工具不会自动重试（重复烧钱的代价 >> 省下的那点时间）。")
            die(f"网络错误：{e}" + extra, 2)

        meta.update({"model": args.model, "protocol": args.protocol,
                     "params": {"n": args.n, "size": args.size_resolved,
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
                           "created": meta.get("created"), "outputs": [str(p) for p in written]})
        # 请求台账：完整响应头 + created + usage + 请求指纹（跟后台 Logs 页对账用）
        record_request(out_dir, {
            "tag": step.tag, "ok": True, "status": meta.get("status"), "model": args.model,
            "prompt": step.prompt, "transport": meta.get("transport"), "stream": bool(args.stream),
            "params": meta.get("params"), "request_id": meta.get("request_id"),
            "created": meta.get("created"), "usage": meta.get("usage"),
            "response_headers": meta.get("response_headers"),
            "inputs": [str(p) for p in args.image], "masks": [str(m) for m in step.mask_srcs],
            "input_sha256": [sha256_file(p) for p in (args.image or [])],
            "outputs": [str(p) for p in written], "elapsed_s": meta.get("elapsed_s"),
            "started_at": meta.get("started_at"), "finished_at": meta.get("finished_at"),
        })
        save_response_dump(out_dir, step.tag, meta)
        shapes = "、".join(probe_image_shape(b) if isinstance(b, bytes) else "url" for b in out)
        usage = meta.get("usage") or {}
        log(f"      ✓ {len(written)} 张 {shapes}  {meta.get('elapsed_s')}s"
            f"  request_id={meta.get('request_id') or '-'}"
            + (f"  created={meta.get('created')}" if meta.get("created") else "")
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
    p.add_argument("--protocol", choices=PROTOCOLS, default=DEFAULT_PROTOCOL,
                   help=f"默认 {DEFAULT_PROTOCOL}（ZenMux 统一 :predict，模型最多）；"
                        f"openai=旧 /images/edits 路径（SSE 流式 / multipart / background 参数只在它上面有效）")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL,
                   help=f"OpenAI 协议与平台管理端点，默认 {DEFAULT_BASE_URL}")
    p.add_argument("--vertex-url", default=VERTEX_BASE_URL,
                   help=f"Vertex AI 协议端点，默认 {VERTEX_BASE_URL}")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"默认 {DEFAULT_MODEL}（编辑精度优先）。Vertex 协议下可选："
                        f"tencent/hy-image-v3.0（混元图像 3.0，2026-09-23 实测可用；单次只出 1 张）、"
                        f"openai/gpt-image-2.5-flare（速度优先）、openai/gpt-image-2、"
                        f"qwen/qwen-image-2.0 等——完整名单看 ZenMux Model Catalog（目录有滞后，"
                        f"新模型未收录也可能已能用）")
    p.add_argument("--timeout", type=int, default=600,
                   help="单次请求超时秒数，默认 600。图片编辑实测 100~365s：读超时=客户端主动放弃，"
                        "但服务端可能仍在跑并**照常计费**（实测有一次 364s 跑完、我们提前放弃，钱照扣）")


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
    g2.add_argument("--quality", default="low", choices=("low", "medium", "high", "xhigh", "max", "auto"),
                    help="默认 low（约 $0.01~0.02/张，估）。medium≈$0.04~0.05、high≈$0.15~0.18（实测）；"
                         "xhigh/max 只有 2.5 系列认")
    g2.add_argument("--background", default=None, choices=("transparent", "opaque", "auto", "none"),
                    help="**仅 openai 协议**：默认 transparent；vertex 协议不支持该参数（不传，"
                         "透明底走「纯色底 + flatbg_cut.py 本地抠底」）。none=完全不传该字段")
    g2.add_argument("--output-format", default="png", choices=("png", "jpeg", "webp"), help="默认 png")
    g2.add_argument("--output-compression", type=int, default=None, help="仅 jpeg/webp，0-100")
    g2.add_argument("--moderation", default=None, choices=("low", "auto"))
    g2.add_argument("--input-fidelity", default=None, choices=("high", "low"),
                    help="第三方文档称 gpt-image-2.5 传它会 400（ZenMux 文档未明确）；不确定就别传")
    g2.add_argument("--transport", default="json", choices=("json", "multipart"),
                    help="json=base64 data URL（默认，符合本项目要求）；multipart=OpenAI SDK 那种表单上传")
    g2.add_argument("--multipart-field", default="image[]", choices=("image[]", "image"),
                    help="multipart 的图片字段名：ZenMux 正文写 image、curl 示例写 image[]；"
                         "默认 image[]，被 400 拒绝时按报错提示改这里")
    g2.add_argument("--stream", dest="stream", action="store_true", default=True,
                    help="走 SSE 流式（**默认开**）：每 10s 有保活数据，连接不空闲、最不容易被网关掐断")
    g2.add_argument("--no-stream", dest="stream", action="store_false",
                    help="退回一次性 JSON 响应（长请求更容易被网关断连）")
    g2.add_argument("--partials", type=int, default=0, choices=(0, 1, 2, 3),
                    help="流式中间图数量，默认 0（只要最终图，不产生额外中间图）")
    g2.add_argument("--save-partials", action="store_true", help="把中间图落盘到 _partials/")
    g2.add_argument("--image-url", action="append", default=[],
                    help="用外部引用代替本地上传图（JSON 通道）：`file:<FILE_ID>` 或 `https://…`。"
                         "实测 ZenMux 没有 Files API，file_id 只能来自别处")
    g2.add_argument("--mask-url", default=None, help="mask 的外部引用（同上）")
    g2.add_argument("--out-dir", default=None, help="默认 tmp/zenmux-edit/<时间戳>/；重名不覆盖，自动加 -2")
    g2.add_argument("--name", default=None, help="输出文件名前缀，默认 <输入图名>-edit")
    g2.add_argument("--max-side", type=int, default=0, help="输入图最长边上限（0=不缩；超 15MB 时用它）")
    g2.add_argument("--dry-run", action="store_true", help="只做本地校验/预览/打印计划，不调 API")
    g2.add_argument("--dump-request", action="store_true",
                    help="把请求体（base64 折叠）写到 out-dir/request<步骤>.json，便于复盘参数")
    g2.add_argument("--min-credits", type=float, default=0.0,
                    help="成本控制：开跑前查余额（Management API Key），低于该美元数直接拒跑；跑完打印余额差")
    # 说明：这里**故意没有**任何重试开关 —— 实测被掐断/超时的请求照样计费，自动重试可能重复烧钱。

    g3 = p.add_argument_group("Vertex 协议（--protocol vertex，默认）")
    g3.add_argument("--aspect-ratio", default=None,
                    help="非 openai 家族（hy 等）的比例覆盖，'宽:高' 形式（1:1 / 16:9 / 3:2）；"
                         "默认由 --size 折算")
    g3.add_argument("--sample-image-size", default=None, choices=("1K", "2K", "4K"),
                    help="分辨率档位透传（官方列了火山/百度；hy 未明说，被 400 就去掉）")
    g3.add_argument("--enhance-prompt", action="store_true",
                    help="prompt 自动增强（Hunyuan / Flux / 通义 支持；openai 家族不支持会被忽略）")
    g3.add_argument("--negative-prompt", default=None,
                    help="负向提示词（官方支持：Imagen / Kling / 通义；hy 未证实，被 400 就去掉）")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-") and argv[0] not in ("check", "edit", "balance", "cost", "generation"):
        die(f"未知子命令 {argv[0]}（只有 check / balance / cost / generation / edit）")
    if argv and argv[0].startswith("-"):
        argv = ["edit"] + argv                                   # 省略子命令时默认 edit

    ap = argparse.ArgumentParser(
        prog="zenmux_edit.py", description="ZenMux 图片编辑（Vertex AI :predict 默认，"
              "兼容 openai/gpt-image 与 tencent/hy-image；--protocol openai 回旧路径）",
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

    pcost = sub.add_parser("cost", help="查账单（不花额度）：按模型/时间看花了多少、几次请求")
    add_common(pcost)
    pcost.add_argument("--dimension", default="BIZ_MTH", choices=("BIZ_MTH", "BIZ_DT", "BIZ_HOUR"),
                       help="BIZ_MTH=按月(按天出桶) / BIZ_DT=按天(按小时出桶) / BIZ_HOUR=按小时(按分钟出桶)")
    pcost.add_argument("--time", default=None, help="YYYYMM / YYYYMMDD / YYYYMMDDHH，默认当前（BIZ_HOUR 用 UTC）")
    pcost.add_argument("--models", action="append", default=[],
                       help="模型 slug（可逗号分隔、可重复），默认全部。注意不是 --model（那个只给 edit 用）")
    pcost.add_argument("--json", action="store_true", help="输出原始 JSON")

    pg = sub.add_parser("generation", help="按 generationId 查单次调用明细（不花额度；id 从控制台 Logs 页拿）")
    add_common(pg)
    pg.add_argument("--id", required=True, help="generationId，形如 2534CCEDTKJR00217635")

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
    if args.cmd == "cost":
        return cmd_cost(args)
    if args.cmd == "generation":
        return cmd_generation(args)
    return cmd_edit(args)


if __name__ == "__main__":
    raise SystemExit(main())
