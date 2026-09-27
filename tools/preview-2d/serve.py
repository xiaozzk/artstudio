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

def _parse_atlas_pages(atlas_path: Path) -> list[str]:
    """从 .atlas 里提取图集页 png 文件名（相对 atlas 目录）。
    页名行 = 顶格、无冒号、以图片扩展名结尾。
    注意不能依赖「下一行是 size:」——libgdx 新版 atlas 的页头字段
    （size/format/filter/repeat/pma）顺序不固定，实测法袍法师是 filter 在前。"""
    pages: list[str] = []
    try:
        lines = atlas_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return pages
    for line in lines:
        s = line.strip()
        if (s and not line.startswith((" ", "\t")) and ":" not in s
                and s.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
            pages.append(s)
    return pages


def scan_spine_for_character(char_dir: Path, base: Path | None = None) -> dict | None:
    """
    检测角色目录下的 Spine 资产（骨架 json + atlas + 图集页），解析元信息。
    返回 None 表示该目录没有可用 spine 资产。
    骨架识别靠内容嗅探（顶层有 skeleton+bones 键），不看文件名——
    交付包里文件名与目录名常不一致（如「法袍法师/Magic Gril.json」）。
    base：rel 路径的基准目录（默认 ASSETS_2D）。
    """
    base = base or ASSETS_2D
    if not char_dir.is_dir():
        return None
    skeleton = None
    json_rel = None
    for jf in sorted(char_dir.glob("*.json")):
        try:
            doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(doc, dict) and "skeleton" in doc and "bones" in doc:
            skeleton = doc
            json_rel = jf.relative_to(base).as_posix()
            break
    if skeleton is None:
        return None

    atlas_rel = None
    pages: list[str] = []
    for af in sorted(char_dir.glob("*.atlas")):
        ps = _parse_atlas_pages(af)
        # 至少能引到一页图集才算可用
        ok_pages = [p for p in ps if (char_dir / p).is_file()]
        if ok_pages:
            atlas_rel = af.relative_to(base).as_posix()
            pages = ok_pages
            break
    if atlas_rel is None:
        return None

    anims = sorted(skeleton.get("animations", {}).keys())
    skins = [s.get("name", "?") for s in skeleton.get("skins", [])]
    return {
        "json": json_rel,
        "atlas": atlas_rel,
        "pages": pages,
        "version": skeleton.get("skeleton", {}).get("spine", "?"),
        "animations": anims,
        "n_animations": len(anims),
        "skins": skins,
        "n_skins": len(skins),
        "n_bones": len(skeleton.get("bones", [])),
        "n_slots": len(skeleton.get("slots", [])),
    }


def scan_task_outputs() -> dict[str, dict]:
    """
    扫描 task/*/output/<包名>/ 下的实验产物（迁移产物等），并入 spine_index。
    前端 key 形如 "实验/<task目录名>/<包名>"；url_prefix 指到该包目录，
    json/atlas 字段退化为纯文件名。
    实验包通常没有复原预览图，前端按「无图卡片」渲染。
    """
    out: dict[str, dict] = {}
    task_root = WORKSPACE_ROOT / "task"
    if not task_root.is_dir():
        return out
    for output_dir in sorted(task_root.glob("*/output")):
        task_name = output_dir.parent.name
        for pkg in sorted(output_dir.iterdir()):
            if not pkg.is_dir():
                continue
            sp = scan_spine_for_character(pkg, base=pkg)
            if sp is None:
                continue
            sp["url_prefix"] = f"/{output_dir.relative_to(WORKSPACE_ROOT).as_posix()}/{pkg.name}/"
            out[f"实验/{task_name}/{pkg.name}"] = sp
    return out


def scan_previews() -> tuple[list[dict], dict]:
    """
    扫描 assets/2d/<category>/<gender>/<character>/复原预览图*.png
    返回 (扁平图片列表, spine_index)。
    每条图片包含 category/gender/character/variant/rel_path/size。
    rel_path 是基于 assets/2d 的正斜杠相对路径。
    spine_index: "cat/gender/char" → spine 元信息（json/atlas/动画/皮肤/骨骼数）。
    """
    if not ASSETS_2D.is_dir():
        print(f"[!] 找不到 {ASSETS_2D}", file=sys.stderr)
        sys.exit(1)

    items: list[dict] = []
    spine_index: dict[str, dict] = {}
    char_dirs_done: set[Path] = set()
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
        # 顺手扫该角色目录的 spine 资产（每角色一次）
        char_dir = p.parent
        if char_dir not in char_dirs_done:
            char_dirs_done.add(char_dir)
            sp = scan_spine_for_character(char_dir)
            if sp is not None:
                spine_index[f"{category}/{gender}/{character}"] = sp
    # 并入 task/*/output/ 的实验产物（迁移产物等）
    spine_index.update(scan_task_outputs())
    return items, spine_index


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


def write_manifest(items: list[dict], grouped: dict, spine_index: dict) -> Path:
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workspace_root": WORKSPACE_ROOT.as_posix(),
        "count": len(items),
        "items": items,
        "grouped": grouped,
        "spine_index": spine_index,
    }
    MANIFEST_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return MANIFEST_PATH


def print_scan_summary(items: list[dict], grouped: dict, spine_index: dict | None = None) -> None:
    n_img = len(items)
    n_char = sum(len(chars) for genders in grouped.values() for chars in genders.values())
    print(f"[scan] 共 {n_img} 张预览图，覆盖 {len(grouped)} 个分类 / {n_char} 个角色。")
    if spine_index is not None:
        n_anim = sum(v["n_animations"] for v in spine_index.values())
        print(f"[scan] 其中 {len(spine_index)} 个角色带 Spine 资产（共 {n_anim} 个动画）。")
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
    items, spine_index = scan_previews()
    grouped = group_items(items)
    p = write_manifest(items, grouped, spine_index)
    print_scan_summary(items, grouped, spine_index)
    print(f"[scan] 清单已写入 {p}")
    return 0


def cmd_serve(args) -> int:
    items, spine_index = scan_previews()
    grouped = group_items(items)
    write_manifest(items, grouped, spine_index)
    print_scan_summary(items, grouped, spine_index)
    print(f"[manifest] {MANIFEST_PATH}")

    port = find_free_port(args.port)
    host = args.host
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}{HTML_URL_PATH}"
    print(f"[ready] 浏览器访问: {url}")
    print("        （按 Ctrl+C 停止服务）")

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
