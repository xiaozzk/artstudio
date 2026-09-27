#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local_edit.py — 本地图片编辑（mini-local stable-diffusion.cpp / Qwen-Image-2.1 图生图）

**纯局域网、不消耗任何 API 额度**（机器在 mini-local 192.168.3.28:7863，GPU 在那边跑）。
图片编辑场景的两个入口：
    * 本工具（这里）：免费、参数全（cfg/steps/seed/sampler 可调）、单张慢（1024² ≈ 8.5 min）；
    * zenmux_edit.py（同目录）：花 ZenMux 额度、快、多 mask 消化 —— 免费预演先走这里，
      满意效果再考虑花钱复刻（口径见 local-edit.md / zenmux-edit.md）。

服务接口（文档：mini-local ~/Desktop/project/llm/docs/sd-server-qwen-i2i-api.md）
    * 健康检查   GET  /v1/models                  → {"data":[{"id":"sd-cpp-local",...}]}
    * 图生图编辑 POST /sdapi/v1/img2img           → JSON，init_images/mask 全部 base64 data-URI
    * 能力/默认值 GET  /sdcpp/v1/capabilities     → 全量默认值（调参前先看）

子命令
    check       健康检查 + 服务默认值摘要（免费、秒回）
    edit        图生图编辑（可带 mask 局部重绘；**不花钱**，但占 GPU 数分钟）

用法示例（一律在工作区根下执行）
    python tools/image-edit/local_edit.py check
    python tools/image-edit/local_edit.py check --json
    python tools/image-edit/local_edit.py edit -i assets/eva_bone/parts/hero.png \\
        -p "把手里那把剑换成一把发光的短杖" --mask tmp/m_weapon.png --seed 42
    python tools/image-edit/local_edit.py edit -i part.png \\
        -p "Extract only the head" --transparent --denoise 0.85 --out tmp/head.png

硬事实 / 实测口径（2026-09-28 对接口文档核对）
    * 路由用 **/sdapi/v1/img2img** 而不是 /v1/images/edits：OpenAI 路由**只**解析
      image/mask/prompt/n/size/output_format，steps / cfg_scale / seed / sampler **不可覆盖**
      （走服务默认 cfg=7.0）；CLI 验证对齐口径是 cfg=6.0，img2img 全参可调。
    * 服务默认 seed=42、steps=20、cfg=7.0；本工具默认显式传 **cfg=6.0 / steps=20 / seed=42**
      （--seed -1 = 随机，出图后从 info 里回读真实 seed 写进边车 json）。
    * **RNG 与 CLI 不是同一条随机序列**：CLI 跑 --rng cpu，服务端 default（cuda）——
      即使 seed/steps/cfg 全一致，服务端与 CLI 出图也不同，别拿 seed 做跨端复现。
    * Qwen-Image 编辑参考图编码走 ref_image_args = "preset=qwen"（默认带上；--no-ref-args 关）。
    * 尺寸必须 **32 的倍数**，64~4096；默认跟随输入图四舍五入到 32 倍数
      （输入不是 32 倍数时告警：服务端会把 init 图 resize 到目标尺寸）。
    * mask 语义（img2img）：**白 = 重绘**。默认 --mask-polarity marked（涂白=要改，直接用）；
      若 mask 是"透明洞=要改"（zenmux 同款约定），用 --mask-polarity hole 自动翻转。
      mask 尺寸与输入图不同时自动缩放并告警。
    * 输出格式 png（唯一保留 alpha 通道）；--transparent 会在 prompt 末尾追加官方 RGBA 透明底指令。
    * 性能（RTX 4060 Ti 16G）：1024² ~8.5 min（VAE 在 CPU）、640×896 ~3 min；
      默认 --timeout 1200s。VAE 提速见文档「把 VAE 改 GPU」。

产出纪律
    * 产物旁写同名 `.json` 边车（请求参数 + 服务端 info meta + 真实 seed + 耗时），便于复现与对账。
    * 默认产物落 tmp/local-edit/<时间戳>/（中间产物口径）；要固定路径用 --out。
    * 本工具**免费且无计费风险**，失败可以直接重跑，不需要像 zenmux 那样先 dry-run 核账。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    print("缺少依赖 requests：python -m pip install requests", file=sys.stderr)
    raise SystemExit(3)

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

if hasattr(sys.stdout, "reconfigure"):      # Windows 控制台默认 cp936，中文/特殊字符会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parents[2]             # 工作区根（tools/image-edit/ → 上两级）

# 服务地址：优先 .env / 环境变量 SD_SERVER_HOST；缺省 = mini-local（192.168.3.28）的 7863
DEFAULT_HOST = "http://192.168.3.28:7863"
ENV_KEY = "SD_SERVER_HOST"

# 与 CLI 验证对齐的显式参数（服务默认 cfg=7.0，对齐口径是 6.0 —— 见 local-edit.md）
DEFAULT_CFG_SCALE = 6.0
DEFAULT_STEPS = 20
DEFAULT_DENOISE = 0.75
DEFAULT_SAMPLER = "euler"
DEFAULT_SCHEDULER = "default"
DEFAULT_REF_ARGS = "preset=qwen"                       # Qwen-Image 编辑参考图编码（同 CliT 的 -r）
SIZE_MULT = 32
SIZE_MIN = 64
SIZE_MAX = 4096
BATCH_MIN, BATCH_MAX = 1, 8
DEFAULT_TIMEOUT = 900                                  # 秒；1024² 实测 ~8.5 min，留余量
TRANSPARENT_SUFFIX = "This is an RGBA image with transparency. The background is fully transparent."


def load_env() -> dict:
    """读工作区根 .env（KEY=VALUE，# 注释，忽略引号）—— 与 zenmux_edit.py 同一套约定。"""
    env = {}
    p = BASE / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_host(args_host: str | None) -> str:
    if args_host:
        return args_host.rstrip("/")
    env = load_env()
    return (env.get(ENV_KEY) or os.environ.get(ENV_KEY) or DEFAULT_HOST).rstrip("/")


def to_data_uri(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def load_image(path: str) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img


def snap32(v: int) -> int:
    """四舍五入到 32 的倍数并夹进 [64, 4096]（服务端尺寸约束）。"""
    v = max(v, SIZE_MIN)
    v = min(v, SIZE_MAX)
    return int(round(v / SIZE_MULT)) * SIZE_MULT


def prepare_mask(mask_path: str, polarity: str, target_wh: tuple[int, int]) -> Image.Image:
    """把人画的 mask 翻成 img2img 需要的「白 = 重绘」二值图，并对齐到输入图尺寸。

    polarity:
      marked —— 涂白 / 不透明 = 要重绘（常见画法，直接用亮度）
      hole   —— 透明（alpha=0）= 要重绘（zenmux 系约定）
    """
    m = load_image(mask_path)
    if m.size != target_wh:
        print(f"[warn] mask 尺寸 {m.size[0]}x{m.size[1]} ≠ 输入图 {target_wh[0]}x{target_wh[1]}，已自动缩放")
        m = m.resize(target_wh, Image.LANCZOS)
    if polarity == "hole":
        a = m.convert("RGBA").getchannel("A")
        g = a.point(lambda v: 255 if v < 128 else 0)   # 透明 → 白（重绘）
    else:
        g = m.convert("L").point(lambda v: 255 if v >= 128 else 0)
    return g


def build_payload(args, img: Image.Image, w: int, h: int) -> dict:
    prompt = args.prompt
    if args.transparent:
        prompt = prompt.rstrip() + " " + TRANSPARENT_SUFFIX
    payload = {
        "init_images": [to_data_uri(img.convert("RGBA"))],
        "prompt": prompt,
        "negative_prompt": args.negative_prompt,
        "denoising_strength": args.denoise,
        "cfg_scale": args.cfg_scale,
        "steps": args.steps,
        "seed": args.seed,
        "batch_size": args.batch,
        "width": w,
        "height": h,
        "sampler_name": args.sampler,
        "scheduler": args.scheduler,
        "clip_skip": -1,
    }
    if args.ref_args:
        payload["ref_image_args"] = args.ref_args
    if args.mask:
        payload["mask"] = to_data_uri(prepare_mask(args.mask, args.mask_polarity, img.size))
        payload["inpainting_mask_invert"] = 0        # mask 已本地翻成「白=重绘」，不再让服务端反转
    if args.enable_hr:
        payload["enable_hr"] = True
        payload["hr_scale"] = args.hr_scale
        payload["hr_upscaler"] = "Latent"
    return payload


def cmd_check(args) -> int:
    host = get_host(args.host)
    try:
        r = requests.get(f"{host}/v1/models", timeout=10)
        r.raise_for_status()
        models = r.json().get("data", [])
    except Exception as e:   # noqa: BLE001 —— 给一句能照着做的提示
        print(f"[fail] 连不上 sd-server（{host}）：{e}")
        print("       到 mini-local 上起服务：./run-qwen-i2i.sh start（或 status 看状态）")
        return 1
    ids = [m.get("id") for m in models]
    print(f"[ok] sd-server 在线：{host}")
    print(f"     模型：{', '.join(map(str, ids)) or '（空）'}")
    try:
        cap = requests.get(f"{host}/sdcpp/v1/capabilities", timeout=10).json()
        d = cap.get("defaults", {})
        sp = d.get("sample_params", {})
        txt_cfg = sp.get("txt_cfg") or (sp.get("guidance") or {}).get("txt_cfg")
        print(f"     默认：steps={sp.get('sample_steps')} txt_cfg={txt_cfg}（本工具显式传 {DEFAULT_CFG_SCALE} 对齐 CLI）"
              f" size={d.get('width')}x{d.get('height')} strength={d.get('strength')}")
        print(f"     尺寸限制 {SIZE_MIN}~{SIZE_MAX}px（{SIZE_MULT} 倍数）；batch {BATCH_MIN}~{BATCH_MAX}；格式 png（保 alpha）/jpeg/webp")
        if args.json:
            print(json.dumps(cap, ensure_ascii=False, indent=2))
    except Exception:    # noqa: BLE001 —— capabilities 拿不到不影响健康结论
        pass
    print("[结论] check 通过")
    return 0


def cmd_edit(args) -> int:
    host = get_host(args.host)
    img_path = Path(args.image)
    if not img_path.exists():
        print(f"[fail] 输入图不存在：{img_path}")
        return 2
    img = load_image(str(img_path))

    w = snap32(args.width if args.width else img.width)
    h = snap32(args.height if args.height else img.height)
    if (args.width or img.width) % SIZE_MULT or (args.height or img.height) % SIZE_MULT:
        print(f"[warn] 目标尺寸取整到 {SIZE_MULT} 倍数：{w}x{h}（服务端会把 init 图 resize 过去，边长不是 32 倍数时构图会略变）")

    if args.mask and not Path(args.mask).exists():
        print(f"[fail] mask 不存在：{args.mask}")
        return 2

    payload = build_payload(args, img, w, h)
    out_dir = Path(args.out_dir) if args.out_dir else BASE / "tmp" / "local-edit" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[run] POST {host}/sdapi/v1/img2img")
    print(f"      {img_path.name} {img.size[0]}x{img.size[1]} → {w}x{h}  denoise={args.denoise} cfg={args.cfg_scale} "
          f"steps={args.steps} seed={args.seed} batch={args.batch} sampler={args.sampler}"
          + (f" mask={Path(args.mask).name}({args.mask_polarity})" if args.mask else ""))
    t0 = time.time()
    try:
        r = requests.post(f"{host}/sdapi/v1/img2img", json=payload, timeout=args.timeout)
    except requests.exceptions.Timeout:
        print(f"[fail] 超时（>{args.timeout}s）。1024² 实测 ~8.5min，大图请加 --timeout；服务还在跑的话耐心等或看 mini-local 日志")
        return 1
    except Exception as e:   # noqa: BLE001
        print(f"[fail] 请求失败：{e}")
        print("       先 python tools/image-edit/local_edit.py check 确认服务在线")
        return 1
    elapsed = time.time() - t0

    if r.status_code != 200:
        print(f"[fail] HTTP {r.status_code}：{r.text[:500]}")
        print("       400 = 缺 prompt/缺 image/尺寸非 32 倍数；500 = 推理异常（看 mini-local 日志）")
        return 1

    data = r.json()
    images = data.get("images") or []
    if not images:
        print("[fail] 响应里没有 images")
        return 1

    info = {}
    try:
        info = json.loads(data.get("info") or "{}")
    except Exception:    # noqa: BLE001
        info = {"raw": str(data.get("info"))[:300]}

    # 输出命名：--out 固定路径，或 out-dir 下按输入图 stem + 序号
    saved = []
    for i, b64 in enumerate(images, 1):
        if args.out:
            out_path = Path(args.out) if len(images) == 1 else Path(args.out).with_name(
                f"{Path(args.out).stem}_{i}{Path(args.out).suffix}")
        else:
            out_path = out_dir / f"{img_path.stem}_edit{i}.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(b64))
        seed_i = info.get("seed", args.seed)
        meta = {
            "tool": "local_edit.py",
            "host": host,
            "input": str(img_path),
            "mask": args.mask,
            "mask_polarity": args.mask_polarity if args.mask else None,
            "prompt": payload["prompt"],
            "negative_prompt": args.negative_prompt,
            "params": {k: payload[k] for k in ("denoising_strength", "cfg_scale", "steps", "seed",
                                               "width", "height", "sampler_name", "scheduler",
                                               "ref_image_args", "batch_size") if k in payload},
            "server_info": info,
            "elapsed_sec": round(elapsed, 1),
            "output": str(out_path),
        }
        out_path.with_suffix(out_path.suffix + ".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        saved.append(out_path)
        print(f"[ok] {out_path}  （seed={seed_i}，{elapsed:.1f}s）")

    if len(saved) == 1:
        print(f"[结论] 完成：{saved[0]}（边车 {saved[0].with_suffix(saved[0].suffix + '.json').name}）")
    else:
        print(f"[结论] 完成：{len(saved)} 张 → {out_dir}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="local_edit.py",
        description="本地图片编辑：mini-local stable-diffusion.cpp / Qwen-Image-2.1 图生图（免费，不消耗 API 额度）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：python tools/image-edit/local_edit.py edit -i a.png -p '把剑换成短杖' --mask m.png --seed 42\n"
               "    服务地址优先级：--host > .env 的 SD_SERVER_HOST > 缺省 " + DEFAULT_HOST)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="健康检查 + 服务默认值摘要（免费、秒回）")
    pc.add_argument("--host", help="覆盖服务地址（默认读 .env 的 SD_SERVER_HOST，再缺省 " + DEFAULT_HOST + "）")
    pc.add_argument("--json", action="store_true", help="附打印 capabilities 原始 JSON")
    pc.set_defaults(func=cmd_check)

    pe = sub.add_parser("edit", help="图生图编辑（免费，占 GPU 数分钟）")
    pe.add_argument("-i", "--image", required=True, help="输入图（PNG 保留 alpha）")
    pe.add_argument("-p", "--prompt", required=True, help="编辑描述（单行；--transparent 自动追加 RGBA 透明底指令）")
    pe.add_argument("--mask", help="重绘 mask：默认涂白=要改（--mask-polarity 可反）；自动缩放到输入图尺寸")
    pe.add_argument("--mask-polarity", choices=("marked", "hole"), default="marked",
                    help="marked=涂白/不透明=重绘（默认）；hole=透明(alpha=0)=重绘（zenmux 同款约定）")
    pe.add_argument("--denoise", type=float, default=DEFAULT_DENOISE, help="denoising_strength，1.0=完全重绘，小=保原图（默认 0.75）")
    pe.add_argument("--cfg-scale", type=float, default=DEFAULT_CFG_SCALE, help="默认 6.0（显式传，对齐 CLI；服务默认 7.0）")
    pe.add_argument("--steps", type=int, default=DEFAULT_STEPS, help="默认 20")
    pe.add_argument("--seed", type=int, default=42, help="默认 42；-1=随机（真实 seed 会写进边车 json）")
    pe.add_argument("--batch", type=int, default=1, help="一次出几张（1-8，默认 1）")
    pe.add_argument("--width", type=int, help="输出宽（缺省=输入图宽取整 32 倍数）")
    pe.add_argument("--height", type=int, help="输出高（缺省=输入图高取整 32 倍数）")
    pe.add_argument("--sampler", default=DEFAULT_SAMPLER, help="默认 euler")
    pe.add_argument("--scheduler", default=DEFAULT_SCHEDULER, help="默认 default")
    pe.add_argument("--ref-args", dest="ref_args", default=DEFAULT_REF_ARGS,
                    help=f"ref_image_args（默认 {DEFAULT_REF_ARGS}，Qwen 编辑参考图编码）")
    pe.add_argument("--no-ref-args", dest="ref_args", action="store_const", const=None, help="不带 ref_image_args")
    pe.add_argument("--negative-prompt", default="", help="负向提示词")
    pe.add_argument("--transparent", action="store_true", help="prompt 末尾追加官方 RGBA 透明底指令（抠件场景）")
    pe.add_argument("--enable-hr", dest="enable_hr", action="store_true", help="开高清修复（hr_scale 默认 2.0）")
    pe.add_argument("--hr-scale", dest="hr_scale", type=float, default=2.0, help=argparse.SUPPRESS)
    pe.add_argument("--out", help="产物固定路径（多张时自动加序号）；缺省落 tmp/local-edit/<时间戳>/")
    pe.add_argument("--out-dir", help="产物目录（缺省 tmp/local-edit/<时间戳>/）")
    pe.add_argument("--host", help="覆盖服务地址（默认读 .env 的 SD_SERVER_HOST）")
    pe.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"HTTP 超时秒数（默认 {DEFAULT_TIMEOUT}）")
    pe.set_defaults(func=cmd_edit)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
