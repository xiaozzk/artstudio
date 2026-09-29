#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local_edit.py — 本地图片编辑（mini-local sd-server / Qwen-Image-2.1 图生图，提交-轮询）

**纯局域网、不消耗任何 API 额度**（机器在 mini-local 192.168.3.28:7863，GPU 在那边跑）。
图片编辑场景的两个入口：
    * 本工具（这里）：免费、参数全、提交-轮询（无长连接，服务是 FastAPI + 单 worker 串行）；
    * zenmux_edit.py（同目录）：花 ZenMux 额度、快、多 mask 消化。
    先免费试效果再考虑花钱（口径见 local-edit.md / zenmux-edit.md）。

服务接口（文档：mini-local ~/Desktop/project/llm/docs/sd-server-qwen-i2i-api.md）
    * Python 实现 infer-engine/sd-server/server.py（FastAPI + 单 worker），推理引擎
      stable-diffusion.cpp 的 sd-cli（每任务 spawn）。
    * **提交-轮询**：POST 生成路由一律返回 `202 {id, poll_url}`，
      用 `GET /jobs/{id}` 轮询直到 completed / failed / cancelled。
    * 状态机：queued（含 queue_position）→ generating → completed / failed（error = stderr 尾 8 行）。
    * 队列上限 10（第 11 个提交 429）；排队中可 DELETE 取消，generating 中不可（409）；
      结果保留 **10 分钟 TTL**（404 = 已过期），每次新提交前自动清理。
    * 服务端默认：steps=20 / cfg_scale=6.0（已与 CLI 对齐）/ sample_method=euler / size=1024x1024；
      **RNG 强制 cpu（CLI 层写死）—— seed/cfg 相同即可与服务端复现同一张图**。

子命令
    check       健康检查 + 队列状态（免费、秒回）
    edit        提交图生图编辑任务 → 轮询 → 落盘（免费，占 GPU 数分钟）

用法示例（一律在工作区根下执行）
    python tools/image-edit/local_edit.py check
    python tools/image-edit/local_edit.py edit -i assets/eva_bone/parts/hero.png \\
        -p "把手里那把剑换成一把发光的短杖" --mask tmp/m_weapon.png --seed 42
    python tools/image-edit/local_edit.py edit -i part.png \\
        -p "Extract only the head" --transparent --denoise 0.85 --out tmp/head.png

edit 硬口径（2026-09-28 对 Python 版服务文档核对）
    * 走 **POST /sdapi/v1/img2img**（A1111 base64 风格，JSON）：
      init_images（data URI）/ mask（白=重绘，本工具自动翻极性并缩放对齐）/
      width+height（32 倍数，64~4096）/ steps / cfg_scale / sample_method / seed。
      文档未列 ref_image_args / scheduler / clip_skip（Python 层不收）——不再发送。
    * mask 语义：**白 = 重绘**。默认 --mask-polarity marked（涂白=要改，直接用）；
      "透明洞=要改"（zenmux 同款约定）用 --mask-polarity hole 自动翻转。
      ⚠ mask 在 Python 服务上**未实测**（文档原话），首次用先小图验证。
    * --seed -1 = 随机；Python 服务不回传实际 seed，边车 json 里如实记 -1。
    * 透明输出：png（唯一保留 alpha）；--transparent 会在 prompt 末尾追加官方 RGBA 透明底指令。
    * 提交 429 = 队列满（上限 10，等一会或让服务端调 SD_SERVER_MAX_PENDING_JOBS）；
      轮询 404 = 结果过期（TTL 10 分钟）；failed 的 error 是 sd-cli stderr 尾 8 行，
      完整日志在 mini-local `./run-qwen-i2i.sh logs`。
    * 本工具**免费且无计费风险**，失败可以直接重跑；但单 worker 串行 —— 别并发轰炸。

产出纪律
    * 产物旁写同名 `.json` 边车（请求参数 + job id / 状态时间戳 + 耗时），便于复现与对账。
    * 默认产物落 tmp/local-edit/<时间戳>/；要固定路径用 --out。
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

# 服务地址：优先 .env / 环境变量 SD_SERVER_HOST；缺省 = mini-local 的 7863
DEFAULT_HOST = "http://192.168.3.28:7863"
ENV_KEY = "SD_SERVER_HOST"

# 与 CLI 验证对齐的显式参数（Python 服务默认就是 6.0 / 20 / euler —— 文档第 7 节）
DEFAULT_CFG_SCALE = 6.0
DEFAULT_STEPS = 20
DEFAULT_DENOISE = 0.75
DEFAULT_SAMPLER = "euler"                              # 服务字段名 sample_method
SIZE_MULT = 32
SIZE_MIN = 64
SIZE_MAX = 4096
DEFAULT_TIMEOUT = 1200                                 # 提交+轮询总时长上限（秒）；1024² ~8.5min + 排队余量
DEFAULT_POLL_INTERVAL = 5                              # 轮询间隔（秒），文档建议 5-10s
TRANSPARENT_SUFFIX = "This is an RGBA image with transparency. The background is fully transparent."
TERMINAL = ("completed", "failed", "cancelled")


def load_env() -> dict:
    """读工作区根 .env（KEY=VALUE，忽略引号）—— 与 zenmux_edit.py 同一套约定。"""
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


def snap32(v: int) -> int:
    """四舍五入到 32 的倍数并夹进 [64, 4096]（服务端尺寸约束）。"""
    v = min(max(v, SIZE_MIN), SIZE_MAX)
    return int(round(v / SIZE_MULT)) * SIZE_MULT


def prepare_mask(mask_path: str, polarity: str, target_wh: tuple[int, int]) -> Image.Image:
    """把人画的 mask 翻成服务需要的「白 = 重绘」二值图，并对齐到输入图尺寸。

    polarity:
      marked —— 涂白 / 不透明 = 要重绘（常见画法，直接按亮度）
      hole   —— 透明（alpha=0）= 要重绘（zenmux 同款约定）
    """
    m = Image.open(mask_path)
    m.load()
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
        "width": w,
        "height": h,
        "steps": args.steps,
        "cfg_scale": args.cfg_scale,
        "sample_method": args.sampler,
        "seed": args.seed,
        "denoising_strength": args.denoise,     # A1111 img2img 兼容字段；文档字段表未单列，服务端默认 0.75
    }
    if args.negative_prompt:
        payload["negative_prompt"] = args.negative_prompt
    if args.mask:
        payload["mask"] = to_data_uri(prepare_mask(args.mask, args.mask_polarity, img.size))
    return payload


def fmt_sec(s: float) -> str:
    return f"{int(s // 60)}m{int(s % 60):02d}s" if s >= 60 else f"{s:.1f}s"


def cmd_check(args) -> int:
    host = get_host(args.host)
    try:
        r = requests.get(f"{host}/v1/models", timeout=10)
        r.raise_for_status()
        body = r.json()
    except Exception as e:   # noqa: BLE001
        print(f"[fail] 连不上 sd-server（{host}）：{e}")
        print("       到 mini-local 上起服务：./run-qwen-i2i.sh start（或 status 看状态）")
        return 1
    models = body.get("data", []) if isinstance(body, dict) else []
    print(f"[ok] sd-server 在线：{host}")
    print(f"     模型：{', '.join(m.get('id', '?') for m in models) or '（空）'}")
    extra = {k: v for k, v in body.items() if k != "data"} if isinstance(body, dict) else {}
    if extra:
        print(f"     队列/状态：{json.dumps(extra, ensure_ascii=False)}")
    print("     服务默认：steps=20 cfg=6.0（与 CLI 对齐）sample_method=euler size=1024x1024")
    print(f"     单 worker 串行；队列上限 10（429=满）；结果 TTL 10 分钟；尺寸 32 倍数 {SIZE_MIN}~{SIZE_MAX}")
    if args.json:
        print(json.dumps(body, ensure_ascii=False, indent=2))
    print("[结论] check 通过")
    return 0


def submit_job(host: str, payload: dict, timeout: int) -> str:
    """POST 提交任务，返回 job id。失败直接 SystemExit 对应退出码。"""
    r = requests.post(f"{host}/sdapi/v1/img2img", json=payload, timeout=timeout)
    if r.status_code == 429:
        print("[fail] 429 队列已满（上限 10）。等在跑的任务结束再提交；"
              "或到 mini-local 用 SD_SERVER_MAX_PENDING_JOBS=20 ./run-qwen-i2i.sh restart 加大队列")
        raise SystemExit(1)
    if r.status_code != 202:
        print(f"[fail] 提交返回 HTTP {r.status_code}：{r.text[:500]}")
        print("       400 = 尺寸非法 / 缺 prompt / 图片格式识别失败")
        raise SystemExit(1)
    job = r.json()
    jid = job.get("id") or job.get("poll_url", "").rsplit("/", 1)[-1]
    if not jid:
        print(f"[fail] 提交响应里没有任务 id：{json.dumps(job)[:300]}")
        raise SystemExit(1)
    print(f"[queued] job id = {jid}（poll: GET {host}/jobs/{jid}）")
    return jid


def poll_job(host: str, jid: str, deadline: float, interval: int, t0: float) -> dict:
    """轮询 GET /jobs/{id} 直到终态；返回任务 JSON。打印状态迁移与排队位次。t0 = 提交时刻。"""
    last = None
    last_beat = time.time()
    while True:
        if time.time() > deadline:
            print(f"[fail] 总时长超过 --timeout；任务还在队列/生成中也说不定 —— 记下 job id 手工查："
                  f"GET {host}/jobs/{jid}（结果 10 分钟 TTL）")
            raise SystemExit(1)
        try:
            r = requests.get(f"{host}/jobs/{jid}", timeout=30)
        except Exception as e:   # noqa: BLE001 —— 单次网络抖动不放弃，下一轮再试
            print(f"[warn] 轮询请求失败（下轮重试）：{e}")
            time.sleep(interval)
            continue
        if r.status_code == 404:
            print(f"[fail] 404：任务不存在或结果已过期（TTL 10 分钟）—— job id {jid}")
            raise SystemExit(1)
        if r.status_code != 200:
            print(f"[fail] 轮询返回 HTTP {r.status_code}：{r.text[:300]}")
            raise SystemExit(1)
        job = r.json()
        st = job.get("status")
        now = time.time()
        if st != last:
            line = f"[poll] {st}"
            if st == "queued":
                line += f"（第 {job.get('queue_position', '?')} 位）"
            print(f"{line}  已等待 {fmt_sec(now - t0)}")
            last = st
            last_beat = now
        elif now - last_beat >= 60:                 # 同状态心跳，防止看着像卡死
            print(f"[poll] 仍为 {st}… 已等待 {fmt_sec(now - t0)}")
            last_beat = now
        if st in TERMINAL:
            return job
        time.sleep(interval)


def cmd_edit(args) -> int:
    host = get_host(args.host)
    img_path = Path(args.image)
    if not img_path.exists():
        print(f"[fail] 输入图不存在：{img_path}")
        return 2
    if args.mask and not Path(args.mask).exists():
        print(f"[fail] mask 不存在：{args.mask}")
        return 2
    img = Image.open(str(img_path))
    img.load()

    w = snap32(args.width if args.width else img.width)
    h = snap32(args.height if args.height else img.height)
    raw_w = args.width or img.width
    raw_h = args.height or img.height
    if raw_w % SIZE_MULT or raw_h % SIZE_MULT:
        print(f"[warn] 目标尺寸取整到 {SIZE_MULT} 倍数：{w}x{h}（服务端会把输入图 resize 过去，构图会略变）")

    payload = build_payload(args, img, w, h)

    print(f"[run] POST {host}/sdapi/v1/img2img")
    print(f"      {img_path.name} {img.size[0]}x{img.size[1]} → {w}x{h}  denoise={args.denoise}（denoising_strength，"
          f"A1111 兼容字段；服务端默认 0.75）cfg={args.cfg_scale} steps={args.steps} seed={args.seed} "
          f"sampler={args.sampler}"
          + (f" mask={Path(args.mask).name}({args.mask_polarity})" if args.mask else "")
          + ("  transparent=追加 RGBA 透明底指令" if args.transparent else ""))

    t0 = time.time()
    jid = submit_job(host, payload, timeout=60)
    deadline = t0 + args.timeout
    job = poll_job(host, jid, deadline, args.poll_interval, t0)
    total = time.time() - t0

    if job.get("status") != "completed":
        err = job.get("error") or ""
        print(f"[fail] 任务 {job.get('status')}：{err[:400]}")
        print("       完整日志到 mini-local 看：./run-qwen-i2i.sh logs")
        return 1

    result = job.get("result") or {}
    b64 = result.get("b64_json")
    if not b64:
        print(f"[fail] completed 但没有 b64_json：{json.dumps(result)[:300]}")
        return 1

    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = Path(args.out_dir) if args.out_dir else BASE / "tmp" / "local-edit" / datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"{img_path.stem}_edit.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(b64))

    meta = {
        "tool": "local_edit.py",
        "host": host,
        "job": {k: job.get(k) for k in ("id", "kind", "status", "created", "started", "completed", "error")},
        "job_queue_elapsed_sec": (round(job["started"] - job["created"], 1)
                                  if job.get("started") and job.get("created") else None),
        "input": str(img_path),
        "mask": args.mask,
        "mask_polarity": args.mask_polarity if args.mask else None,
        "prompt": payload["prompt"],
        "negative_prompt": args.negative_prompt,
        "params": {k: payload[k] for k in ("width", "height", "steps", "cfg_scale",
                                           "sample_method", "seed", "denoising_strength") if k in payload},
        "server_result_file": result.get("file"),
        "elapsed_sec": round(total, 1),
        "output": str(out_path),
    }
    out_path.with_suffix(out_path.suffix + ".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] {out_path}")
    if result.get("file"):
        print(f"     服务端留档：{result['file']}")
    print(f"[结论] 完成：{out_path}（总耗时 {fmt_sec(total)}，job {jid}）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="local_edit.py",
        description="本地图片编辑：mini-local stable-diffusion.cpp / Qwen-Image-2.1 图生图（提交-轮询，免费）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：python tools/image-edit/local_edit.py edit -i a.png -p '把剑换成短杖' --mask m.png --seed 42\n"
               "    服务地址优先级：--host > .env 的 SD_SERVER_HOST > 缺省 " + DEFAULT_HOST)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="健康检查 + 队列状态（免费、秒回）")
    pc.add_argument("--host", help="覆盖服务地址（默认读 .env 的 SD_SERVER_HOST）")
    pc.add_argument("--json", action="store_true", help="附打印 /v1/models 原始 JSON")
    pc.set_defaults(func=cmd_check)

    pe = sub.add_parser("edit", help="提交图生图编辑任务 → 轮询 → 落盘（免费，占 GPU 数分钟）")
    pe.add_argument("-i", "--image", required=True, help="输入图（PNG 保留 alpha）")
    pe.add_argument("-p", "--prompt", required=True, help="编辑描述（单行；--transparent 自动追加 RGBA 透明底指令）")
    pe.add_argument("--mask", help="重绘 mask：默认涂白=要改（--mask-polarity 可反）；自动缩放到输入图尺寸。⚠ Python 服务未实测 mask")
    pe.add_argument("--mask-polarity", choices=("marked", "hole"), default="marked",
                    help="marked=涂白/不透明=重绘（默认）；hole=透明(alpha=0)=重绘（zenmux 同款约定）")
    pe.add_argument("--denoise", type=float, default=DEFAULT_DENOISE, help="denoising_strength，1.0=完全重绘，小=保原图（默认 0.75）")
    pe.add_argument("--cfg-scale", type=float, default=DEFAULT_CFG_SCALE, help="默认 6.0（服务默认已与 CLI 对齐）")
    pe.add_argument("--steps", type=int, default=DEFAULT_STEPS, help="默认 20")
    pe.add_argument("--seed", type=int, default=42, help="默认 42；-1=随机（服务不回传实际 seed）。RNG 已与 CLI 同序列，可复现")
    pe.add_argument("--width", type=int, help="输出宽（缺省=输入图宽取整 32 倍数）")
    pe.add_argument("--height", type=int, help="输出高（缺省=输入图高取整 32 倍数）")
    pe.add_argument("--sampler", default=DEFAULT_SAMPLER, help="sample_method，默认 euler")
    pe.add_argument("--negative-prompt", default="", help="负向提示词")
    pe.add_argument("--transparent", action="store_true", help="prompt 末尾追加官方 RGBA 透明底指令（抠件场景）")
    pe.add_argument("--out", help="产物固定路径；缺省落 tmp/local-edit/<时间戳>/")
    pe.add_argument("--out-dir", help="产物目录（缺省 tmp/local-edit/<时间戳>/）")
    pe.add_argument("--host", help="覆盖服务地址（默认读 .env 的 SD_SERVER_HOST）")
    pe.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"提交+轮询总时长上限秒（默认 {DEFAULT_TIMEOUT}）")
    pe.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL, help=f"轮询间隔秒（默认 {DEFAULT_POLL_INTERVAL}）")
    pe.set_defaults(func=cmd_edit)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
