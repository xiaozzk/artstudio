#!/usr/bin/env python3
"""
2D 预览图浏览器 —— 启动脚本

步骤：
  1. 扫描 assets/2d/**/复原预览图*.png
  2. 生成 tools/preview-2d/preview-manifest.json（结构化清单）
  3. 在工作区根启动 `python -m http.server`（端口自动避让）
  4. 1.5s 后用默认浏览器打开预览页

用法：
  python tools/preview-2d/serve.py [子命令] [选项]

子命令：
  scan      只扫描 + 生成 manifest，不启动服务器（便于 CI 复用）
  serve     扫描 + 生成 manifest + 启动服务器 + 打开浏览器  [默认]
  (无)      默认 serve

选项：
  --port <n>       指定端口（默认自动 8000 起的空端口）
  --no-browser     不自动打开浏览器
  --host <addr>    绑定地址（默认 127.0.0.1；写 0.0.0.0 暴露给局域网）

按 Ctrl+C 停止。
"""

import argparse
import json
import socket
import sys
import threading
import time
import webbrowser
from collections import OrderedDict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# tools/preview-2d/ 的祖父就是工作区根
WORKSPACE_ROOT = SCRIPT_DIR.parent.parent
ASSETS_2D = WORKSPACE_ROOT / "assets" / "2d"
MANIFEST_PATH = SCRIPT_DIR / "preview-manifest.json"
HTML_URL_PATH = "/tools/preview-2d/preview.html"

# 主分类排序（其他类目放末尾）
CATEGORY_ORDER = ["恶魔", "哥布林", "精灵", "人形", "兽人"]
GENDER_ORDER = ["男", "女", ""]


# ---------- 扫描 ----------

def scan_previews() -> list[dict]:
    """
    扫描 assets/2d/<category>/<gender>/<character>/复原预览图*.png
    返回扁平列表，每条包含 category/gender/character/variant/rel_path/size。
    rel_path 是基于 assets/2d 的正斜杠相对路径。
    """
    if not ASSETS_2D.is_dir():
        print(f"[!] 找不到 {ASSETS_2D}", file=sys.stderr)
        sys.exit(1)

    items: list[dict] = []
    for p in sorted(ASSETS_2D.rglob("复原预览图*.png")):
        if not p.is_file():
            continue
        rel = p.relative_to(ASSETS_2D)
        parts = rel.parts
        # 期望层级：category / gender / character [/<filename>]
        if len(parts) < 4:
            print(f"[!] 跳过层级不符的预览图: {rel}", file=sys.stderr)
            continue
        category, gender, character = parts[0], parts[1], parts[2]
        filename = p.name
        # 提取变体：复原预览图.png -> "__default__"；
        # 复原预览图_xxx.png -> "xxx"
        stem = p.stem
        if stem == "复原预览图":
            variant = "__default__"
        elif stem.startswith("复原预览图_"):
            variant = stem[len("复原预览图_"):]
        else:
            variant = stem
        items.append({
            "category": category,
            "gender": gender,
            "character": character,
            "variant": variant,
            "filename": filename,
            "rel_path": rel.as_posix(),
            "size": p.stat().st_size,
        })
    return items


def group_items(items: list[dict]) -> dict:
    """将扁平列表按 category/gender/character 分组；保持 CATEGORY_ORDER/GENDER_ORDER 顺序。"""
    grouped: "OrderedDict[str, OrderedDict[str, OrderedDict[str, list[dict]]]]" = OrderedDict()
    for it in items:
        bucket = grouped.setdefault(it["category"], OrderedDict())
        sub = bucket.setdefault(it["gender"], OrderedDict())
        sub.setdefault(it["character"], []).append(it)
    # 重新排序：每个层级按预定义顺序排，其它（含空字符串）放末尾
    def sort_keys(d: dict, order: list[str]) -> list:
        return sorted(d.keys(), key=lambda k: (order.index(k) if k in order else len(order), k))
    sorted_grouped = OrderedDict()
    for c in sort_keys(grouped, CATEGORY_ORDER):
        sorted_grouped[c] = OrderedDict()
        for g in sort_keys(grouped[c], GENDER_ORDER):
            sorted_grouped[c][g] = grouped[c][g]
    return sorted_grouped


def write_manifest(items: list[dict], grouped: dict) -> Path:
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workspace_root": WORKSPACE_ROOT.as_posix(),
        "count": len(items),
        "items": items,
        "grouped": grouped,
    }
    MANIFEST_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return MANIFEST_PATH


def print_scan_summary(items: list[dict], grouped: dict) -> None:
    n_img = len(items)
    n_char = sum(len(chars) for genders in grouped.values() for chars in genders.values())
    print(f"[scan] 共 {n_img} 张预览图，覆盖 {len(grouped)} 个分类 / {n_char} 个角色。")
    for cat, genders in grouped.items():
        for g, chars in genders.items():
            sample = ", ".join(list(chars.keys())[:3])
            extra = f" 等 {len(chars)} 个" if len(chars) > 3 else ""
            print(f"        {cat}/{g or '其他'}: {len(chars)} 角色（{sample}{extra}）")


# ---------- HTTP server ----------

def find_free_port(preferred: int | None) -> int:
    if preferred is not None:
        if _port_available(preferred):
            return preferred
        print(f"[!] 端口 {preferred} 已被占用，自动寻找空闲端口。")
    p = 8000 if preferred is None else preferred + 1
    while p < 65535:
        if _port_available(p):
            return p
        p += 1
    raise RuntimeError("找不到空闲端口（尝试范围 8000..65534）")


def _port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def start_server(port: int, host: str, ready_evt: threading.Event) -> None:
    """
    在工作区根目录启动 `python -m http.server`。
    启动后置 ready_evt，便于上层流程衔接。
    """
    import subprocess
    cmd = [
        sys.executable,
        "-u",  # unbuffered：日志及时打到当前终端
        "-m",
        "http.server",
        str(port),
        "--bind",
        host,
        "--directory",
        str(WORKSPACE_ROOT),
    ]
    print(f"[http] 启动: cd {WORKSPACE_ROOT} && " + " ".join(cmd[2:]))
    proc = subprocess.Popen(cmd)
    # 等 server 端口起来
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("http.server 进程意外退出")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect((host if host != "0.0.0.0" else "127.0.0.1", port))
                ready_evt.set()
                break
            except OSError:
                time.sleep(0.15)
    # 把子进程接管给前台
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\n[http] 已停止。")


# ---------- 入口 ----------

def cmd_scan(_args) -> int:
    items = scan_previews()
    grouped = group_items(items)
    p = write_manifest(items, grouped)
    print_scan_summary(items, grouped)
    print(f"[scan] 清单已写入 {p}")
    return 0


def cmd_serve(args) -> int:
    items = scan_previews()
    grouped = group_items(items)
    write_manifest(items, grouped)
    print_scan_summary(items, grouped)
    print(f"[manifest] {MANIFEST_PATH}")

    port = find_free_port(args.port)
    host = args.host
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}{HTML_URL_PATH}"
    print(f"[ready] 浏览器访问: {url}")
    print(f"        （按 Ctrl+C 停止服务）")

    ready = threading.Event()

    def opener():
        if args.no_browser:
            return
        if not ready.wait(timeout=8.0):
            return
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"[!] 自动打开浏览器失败：{e}", file=sys.stderr)

    threading.Thread(target=opener, daemon=True).start()
    try:
        start_server(port, host, ready)
    except RuntimeError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="2D 预览图浏览器 —— 扫描 + 启动服务。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("cmd", nargs="?", default="serve",
                    choices=["scan", "serve"],
                    help="子命令（默认 serve）")
    ap.add_argument("--port", type=int, default=None,
                    help="HTTP 端口（默认自动找空闲端口，从 8000 起）")
    ap.add_argument("--host", default="127.0.0.1",
                    help="绑定地址（默认 127.0.0.1；想暴露局域网写 0.0.0.0）")
    ap.add_argument("--no-browser", action="store_true",
                    help="不自动打开浏览器")
    args = ap.parse_args()

    if args.cmd == "scan":
        return cmd_scan(args)
    return cmd_serve(args)


if __name__ == "__main__":
    sys.exit(main())
