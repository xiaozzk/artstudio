#!/usr/bin/env python3
"""
2D 预览图浏览器 —— 多库扫描 + 预览服务

步骤：
  1. 扫描各「预览库」：**只有含骨架 json（+ atlas）的目录才成组**，顺带识别 Spine 元信息
  2. 生成 tools/preview-2d/preview-manifest.json（结构化清单）
  3. 起一个内置 HTTP 服务（静态文件 + 库文件 + 管理 API）
  4. 1.2s 后用默认浏览器打开预览页

预览库（library）概念：
  - 每个库 = 一个磁盘目录，扫描结果互相独立，网页顶部用下拉切换
  - 内置 3 个：assets/2d（默认）、download/preview-2d-imports（导入库）、
    task/*/output/（实验产物，虚拟库）
  - 「＋ 新建预览目录」= 注册任意磁盘目录（不存在会自动创建）
  - 「📥 导入资源」= 从浏览器选文件/文件夹复制进库，**默认禁止写进 assets/2d**，
    导入的目录与默认目录分开

卡片的画面是浏览器里**实时渲**出来的（spine-player 定格一帧），不读文件夹里的离线 PNG，
渲染相关的坑见 preview.html 的注释。

用法：
  python tools/preview-2d/serve.py [子命令] [选项]

子命令：
  scan      只扫描 + 生成 manifest，不启动服务器（便于 CI / skill 速览复用）
  serve     扫描 + 生成 manifest + 启动服务器 + 打开浏览器  [默认]
  (无)      默认 serve

选项：
  --port <n>       指定端口（默认自动 8000 起的空端口）
  --no-browser     不自动打开浏览器
  --host <addr>    绑定地址（默认 127.0.0.1；写 0.0.0.0 暴露给局域网）
  --lib <id|path>  只扫描指定库（可重复）；默认全部

按 Ctrl+C 停止。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
# tools/preview-2d/ 的祖父就是工作区根
WORKSPACE_ROOT = SCRIPT_DIR.parent.parent
MANIFEST_PATH = SCRIPT_DIR / "preview-manifest.json"
LIBS_PATH = SCRIPT_DIR / "libraries.json"
HTML_URL_PATH = "/tools/preview-2d/preview.html"
# 静态只暴露这个子目录（HTML / vendor / manifest），够用且不把 .env、.git 暴露出去
STATIC_ROOT = SCRIPT_DIR
STATIC_URL_PREFIX = "/tools/preview-2d/"
# 库文件的虚拟 URL 前缀：/@lib/<库 id>/<库内相对路径>
LIB_URL_PREFIX = "/@lib/"

# 默认库 / 导入库 / 实验产物（虚拟）——内置三件套
BUILTIN_LIBS = [
    {"id": "assets-2d", "name": "assets/2d", "kind": "default",
     "path": "assets/2d", "builtin": True},
    {"id": "imports", "name": "导入资源", "kind": "import",
     "path": "download/preview-2d-imports", "builtin": True},
    {"id": "task-outputs", "name": "实验产物", "kind": "task",
     "path": "task", "builtin": True},
]

# 仅用于**排序**（目录级），不是筛选维度
DIR_ORDER = ["恶魔", "哥布林", "精灵", "人形", "兽人"]
SKIP_DIR_NAMES = {"node_modules", "__pycache__", ".venv", "venv",
                  "site-packages", "Blender", "_MACOSX", "System Volume Information"}
MAX_UPLOAD = 2 * 1024 * 1024 * 1024  # 单文件 2 GiB
MAX_JSON_BODY = 4 * 1024 * 1024

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".atlas": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".wasm": "application/wasm",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

STATE: dict = {"config": None, "manifest": None, "lock": threading.RLock()}


# ---------- 库配置 ----------

def builtin_libraries() -> list[dict]:
    return [dict(b) for b in BUILTIN_LIBS]


def lib_id_for_path(path: Path) -> str:
    """同一路径永远得到同一个 id（重启后下拉/URL 保持稳定）。"""
    digest = hashlib.md5(str(path).encode("utf-8", "replace")).hexdigest()[:8]
    return f"lib-{digest}"


def lib_root(lib: dict) -> Path:
    p = Path(str(lib.get("path", ""))).expanduser()
    return p if p.is_absolute() else (WORKSPACE_ROOT / p)


def display_path(lib: dict) -> str:
    p = lib_root(lib)
    try:
        return p.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except Exception:
        return p.as_posix()


def load_config() -> dict:
    libs: list[dict] = []
    if LIBS_PATH.is_file():
        try:
            raw = json.loads(LIBS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("libraries"), list):
                libs = [l for l in raw["libraries"] if isinstance(l, dict)]
        except Exception as e:  # 配置坏了不该让工具起不来
            print(f"[!] libraries.json 解析失败，按内置库重建：{e}", file=sys.stderr)
    by_id: dict[str, dict] = {}
    for l in libs:
        lid = str(l.get("id") or "").strip()
        if not lid or lid in by_id:
            continue
        l["id"] = lid
        l.setdefault("name", lid)
        l.setdefault("kind", "custom")
        l.setdefault("path", "")
        l.setdefault("builtin", False)
        by_id[lid] = l
    for b in builtin_libraries():  # 内置库缺失就补回（用户删自定义库不影响内置）
        if b["id"] not in by_id:
            by_id[b["id"]] = b
    cfg = {"libraries": list(by_id.values())}
    for l in cfg["libraries"]:
        if l.get("kind") == "import":  # 导入库先建好，页面上就是个 0 张图的空库
            try:
                lib_root(l).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                print(f"[!] 导入库目录建不出来：{e}", file=sys.stderr)
    save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    LIBS_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def find_lib(cfg: dict, ident: str) -> dict | None:
    for l in cfg["libraries"]:
        if l["id"] == ident:
            return l
    for l in cfg["libraries"]:  # 也允许用路径 / 名称定位
        if str(l.get("path")) == ident or l.get("name") == ident:
            return l
    return None


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


def scan_spine_dir(char_dir: Path) -> dict | None:
    """
    检测目录下的 Spine 资产（骨架 json + atlas + 图集页），解析元信息。
    返回 None 表示没有可用 spine 资产。json / atlas 字段是**目录内的相对文件名**。
    骨架识别靠内容嗅探（顶层有 skeleton+bones 键），不看文件名——
    交付包里文件名与目录名常不一致（如「法袍法师/Magic Gril.json」）。
    """
    if not char_dir.is_dir():
        return None
    skeleton = None
    json_name = ""
    for jf in sorted(char_dir.glob("*.json")):
        try:
            doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(doc, dict) and "skeleton" in doc and "bones" in doc:
            skeleton, json_name = doc, jf.name
            break
    if skeleton is None:
        return None

    for af in sorted(char_dir.glob("*.atlas")):
        pages = [p for p in _parse_atlas_pages(af) if (char_dir / p).is_file()]
        if not pages:  # 至少能引到一页图集才算可用
            continue
        anims = sorted(skeleton.get("animations", {}).keys())
        skins = [s.get("name", "?") for s in skeleton.get("skins", [])]
        return {
            "json": json_name,
            "atlas": af.name,
            "pages": pages,
            "version": skeleton.get("skeleton", {}).get("spine", "?"),
            "animations": anims,
            "n_animations": len(anims),
            "skins": skins,
            "n_skins": len(skins),
            "n_bones": len(skeleton.get("bones", [])),
            "n_slots": len(skeleton.get("slots", [])),
        }
    return None


def lib_url(lib_id: str) -> str:
    return f"{LIB_URL_PREFIX}{lib_id}/"


def sort_key_dir(d: str) -> tuple:
    head = d.split("/", 1)[0]
    idx = DIR_ORDER.index(head) if head in DIR_ORDER else len(DIR_ORDER)
    return (idx, head, d)


def scan_filesystem_library(lib: dict) -> dict:
    """
    普通库：**只有含骨架 json（+ atlas）的目录才成组**。
    预览图、部件图、图集页一概不收 —— 卡片上的画面由前端用 spine-player 实时渲 setup pose，
    不再读文件夹里那些离线渲好的 PNG。
    """
    root = lib_root(lib)
    groups: list[dict] = []
    if not root.is_dir():
        return {"exists": False, "groups": []}
    for dirpath, dirnames, _files in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d not in SKIP_DIR_NAMES)
        d = Path(dirpath)
        rel = d.relative_to(root).as_posix()
        rel = "" if rel == "." else rel
        spine = scan_spine_dir(d)
        if spine is None:
            continue
        groups.append({
            "dir": rel,
            "rel": rel,
            "base": lib_url(lib["id"]) + (quote(rel, safe="/") + "/" if rel else ""),
            "spine": spine,
        })
    groups.sort(key=lambda g: sort_key_dir(g["dir"]))
    return {"exists": True, "groups": groups}


def scan_task_library(lib: dict) -> dict:
    """
    实验产物（task/*/output/<包名>/）：只收含骨架+图集的包，按任务分目录。
    dir 是给人看的（<task>/<包名>），rel 是真实路径（含 output/），URL 用 rel。
    """
    groups: list[dict] = []
    task_root = lib_root(lib)
    if not task_root.is_dir():
        return {"exists": False, "groups": []}
    for output_dir in sorted(task_root.glob("*/output")):
        task_name = output_dir.parent.name
        for pkg in sorted(output_dir.iterdir()):
            if not pkg.is_dir():
                continue
            spine = scan_spine_dir(pkg)
            if spine is None:
                continue
            # dir 是给人看的（<task>/<包名>），rel 是真实路径（含 output/），URL 用 rel
            rel = f"{task_name}/output/{pkg.name}"
            display = f"{task_name}/{pkg.name}"
            base = lib_url(lib["id"]) + quote(rel, safe="/") + "/"
            groups.append({
                "dir": display,
                "rel": rel,
                "base": base,
                "spine": spine,
            })
    groups.sort(key=lambda g: sort_key_dir(g["dir"]))
    return {"exists": True, "groups": groups}


def scan_library(lib: dict) -> dict:
    scanned = scan_task_library(lib) if lib.get("kind") == "task" else scan_filesystem_library(lib)
    groups = scanned["groups"]
    return {
        "id": lib["id"],
        "name": lib.get("name", lib["id"]),
        "kind": lib.get("kind", "custom"),
        "path": str(lib.get("path", "")),
        "display_path": display_path(lib),
        "builtin": bool(lib.get("builtin")),
        "exists": scanned["exists"],
        "url_prefix": lib_url(lib["id"]),
        # 只报「组数 / 动画总数」——不统计图片数（卡片画面是实时渲的，图片数没意义）
        "group_count": len(groups),
        "anim_count": sum(g["spine"]["n_animations"] for g in groups if g.get("spine")),
        "groups": groups,
    }


def build_manifest(cfg: dict, only: list[str] | None = None) -> dict:
    libs_out: list[dict] = []
    wanted = set(only or [])
    for lib in cfg["libraries"]:
        if wanted and not (lib["id"] in wanted or str(lib.get("path")) in wanted
                           or lib.get("name") in wanted):
            continue
        libs_out.append(scan_library(lib))
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workspace_root": WORKSPACE_ROOT.as_posix(),
        "group_count": sum(l["group_count"] for l in libs_out),
        "library_count": len(libs_out),
        "libraries": libs_out,
    }


def rescan(only: list[str] | None = None) -> dict:
    """重扫并重写 manifest；返回 manifest 本身。"""
    with STATE["lock"]:
        cfg = STATE["config"] or load_config()
        if only:
            # 只重扫指定库，其余库沿用上次的扫描结果
            prev = {l["id"]: l for l in (STATE["manifest"] or {}).get("libraries", [])}
            manifest = build_manifest(cfg, only)
            if prev:
                ids = {l["id"] for l in manifest["libraries"]}
                merged = [prev[i] for i in prev if i not in ids]
                manifest["libraries"] = manifest["libraries"] + merged
        else:
            manifest = build_manifest(cfg)
        manifest["group_count"] = sum(l["group_count"] for l in manifest["libraries"])
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        STATE["manifest"] = manifest
        return manifest


def print_scan_summary(manifest: dict) -> None:
    print(f"[scan] 生成于 {manifest['generated_at']}，共 {len(manifest['libraries'])} 个预览库，"
          f"{manifest['group_count']} 组 Spine 资源。")
    for lib in manifest["libraries"]:
        if not lib["exists"]:
            print(f"        [!] 库「{lib['name']}」目录不存在：{lib['display_path']}")
            continue
        print(f"        库「{lib['name']}」{lib['display_path']}："
              f"{lib['group_count']} 组 / 共 {lib['anim_count']} 个动画")
        for g in lib["groups"]:  # skill「全量包速览」依赖这段输出
            sp = g.get("spine")
            if not sp:
                continue
            print(f"            {g['dir']} · Spine {sp['version']} · "
                  f"{sp['n_animations']} 动画 · {sp['n_bones']} 骨骼 · {sp['n_skins']} 皮肤")


# ---------- HTTP 服务 ----------

def _port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


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


def safe_join(root: Path, rel: str) -> Path | None:
    """把 URL 相对路径拼到 root 下并确认没逃出去（防 ../ 穿越）。"""
    rel = unquote(rel or "").replace("\\", "/").lstrip("/")
    if not rel:
        return None
    parts = [seg for seg in rel.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in parts):
        return None
    target = (root / Path(*parts)).resolve() if parts else None
    if target is None:
        return None
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """浏览器/脚本随时会掐连接，别把栈喷一屏。"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        sys.stderr.write(f"[http] 处理请求出错：{exc}\n")


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "preview2d"
    protocol_version = "HTTP/1.1"

    # --- 基础响应
    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code: int, msg: str) -> None:
        self._json({"ok": False, "error": msg}, code)

    def _send_file(self, path: Path, head_only: bool = False) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            return self._err(404, "文件不存在")
        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control",
                          "no-store" if path.suffix.lower() in (".html", ".json") else "max-age=600")
        self.end_headers()
        if head_only:
            return
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 16)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Content-Length 非法")
        if n > MAX_JSON_BODY:
            raise ValueError("请求体过大")
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return obj

    # --- 路由
    def do_GET(self) -> None:
        self._handle(head_only=False)

    def do_HEAD(self) -> None:
        self._handle(head_only=True)

    def _handle(self, head_only: bool) -> None:
        route = urlparse(self.path).path
        try:
            if route.startswith(LIB_URL_PREFIX):
                return self._serve_lib_file(route[len(LIB_URL_PREFIX):], head_only)
            if route.startswith("/api/"):
                if head_only or route == "/api/manifest":
                    return self._json(self._current_manifest())
                return self._err(404, f"未知 API：{route}")
            return self._serve_static(route, head_only)
        except Exception as e:  # 任何异常都回 JSON，别把栈喷到浏览器
            return self._err(500, f"{type(e).__name__}: {e}")

    def _serve_static(self, route: str, head_only: bool) -> None:
        # 静态只服务 tools/preview-2d/（HTML / vendor / 清单），其余一律 404，
        # 这样 .env / .git / 整个仓库都不会被本机 HTTP 端口暴露出去。
        if not route.startswith(STATIC_URL_PREFIX):
            return self._err(404, f"未找到：{route}（静态只服务 {STATIC_URL_PREFIX}）")
        rel = route[len(STATIC_URL_PREFIX):]
        target = safe_join(STATIC_ROOT, rel)
        if target is None or not target.is_file():
            return self._err(404, f"未找到：{route}")
        self._send_file(target, head_only)

    def _serve_lib_file(self, raw: str, head_only: bool) -> None:
        parts = unquote(raw).split("/", 1)
        if len(parts) != 2:
            return self._err(400, "库文件路径格式应为 /@lib/<库id>/<库内相对路径>")
        with STATE["lock"]:
            cfg = STATE["config"] or load_config()
            lib = find_lib(cfg, parts[0])
        if not lib:
            return self._err(404, f"未知库：{parts[0]}")
        target = safe_join(lib_root(lib), parts[1])
        if target is None or not target.is_file():
            return self._err(404, f"未找到：{parts[1]}")
        self._send_file(target, head_only)

    def _current_manifest(self) -> dict:
        with STATE["lock"]:
            if STATE["manifest"] is None:
                return rescan()
            return STATE["manifest"]

    # --- POST API
    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            if route == "/api/rescan":
                return self._json(self._api_rescan())
            if route == "/api/library/add":
                return self._json(self._api_add_library())
            if route == "/api/library/remove":
                return self._json(self._api_remove_library())
            if route == "/api/import":
                return self._json(self._api_import())
            return self._err(404, f"未知 API：{route}")
        except ValueError as e:
            self._err(400, str(e))
        except Exception as e:
            self._err(500, f"{type(e).__name__}: {e}")

    def _api_rescan(self) -> dict:
        body = self._read_json_body()
        only = body.get("lib")
        only = [str(only)] if only else None
        return {"ok": True, "manifest": rescan(only)}

    def _api_add_library(self) -> dict:
        """新建（= 注册）一个预览目录：不存在就创建。"""
        body = self._read_json_body()
        raw_path = str(body.get("path") or "").strip().strip('"')
        if not raw_path:
            raise ValueError("请填写目录路径")
        p = Path(raw_path).expanduser()
        p = p if p.is_absolute() else (WORKSPACE_ROOT / p)
        p = p.resolve()
        # 目录白名单式的安全兜底：别把工作区根 / 工具目录本身注册成"预览库"
        for bad in (WORKSPACE_ROOT, WORKSPACE_ROOT.parent, WORKSPACE_ROOT / ".git",
                    SCRIPT_DIR, WORKSPACE_ROOT / "tools"):
            if p == bad:
                raise ValueError(f"不能把 {p} 注册为预览目录")
        existed = p.is_dir()
        p.mkdir(parents=True, exist_ok=True)
        with STATE["lock"]:
            cfg = STATE["config"] or load_config()
            lib_id = lib_id_for_path(p)
            name = str(body.get("name") or "").strip() or p.name or lib_id
            for l in cfg["libraries"]:
                if l["id"] == lib_id:
                    l["name"] = name
                    save_config(cfg)
                    return {"ok": True, "id": lib_id, "created": False,
                            "manifest": rescan([lib_id])}
            cfg["libraries"].append({"id": lib_id, "name": name, "kind": "custom",
                                     "path": str(p), "builtin": False})
            save_config(cfg)
            print(f"[lib] {'已存在，登记为预览库' if existed else '已创建目录并登记为预览库'}：{p}")
            return {"ok": True, "id": lib_id, "created": not existed,
                    "manifest": rescan([lib_id])}

    def _api_remove_library(self) -> dict:
        """从清单里移除一个库。**只删配置，不动磁盘上的任何文件。**"""
        body = self._read_json_body()
        lib_id = str(body.get("id") or "").strip()
        with STATE["lock"]:
            cfg = STATE["config"] or load_config()
            lib = find_lib(cfg, lib_id)
            if not lib:
                raise ValueError(f"未知库：{lib_id}")
            if lib.get("builtin"):
                raise ValueError(f"内置库「{lib.get('name')}」不可移除")
            cfg["libraries"] = [l for l in cfg["libraries"] if l["id"] != lib["id"]]
            save_config(cfg)
            print(f"[lib] 已从清单移除（文件保留）：{lib.get('display_path') or lib.get('path')}")
            return {"ok": True, "manifest": rescan()}

    def _api_import(self) -> dict:
        """
        导入单个文件：请求体就是文件原始字节，头里带目标库与库内相对路径。
        （一个文件一个请求——避开 multipart 解析，天然流式、还能逐文件报进度。）

        硬约束：默认库 assets/2d **不可写**，导入内容必须落在独立目录。
        """
        lib_id = str(self.headers.get("X-Lib-Target") or "").strip()
        rel = str(self.headers.get("X-File-Path") or "").strip()
        if not lib_id or not rel:
            raise ValueError("缺少 X-Lib-Target 或 X-File-Path")
        with STATE["lock"]:
            cfg = STATE["config"] or load_config()
            lib = find_lib(cfg, lib_id)
        if not lib:
            raise ValueError(f"未知库：{lib_id}")
        if lib.get("kind") == "default":
            raise ValueError("默认库 assets/2d 只读：导入的资源请落到独立目录"
                             "（导入库或自建库）")
        if lib.get("kind") == "task":
            raise ValueError("实验产物库是虚拟的，不可写入")
        root = lib_root(lib)
        target = safe_join(root, rel)
        if target is None:
            raise ValueError(f"非法相对路径：{rel}")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Content-Length 非法")
        if length <= 0:
            raise ValueError("空文件")
        if length > MAX_UPLOAD:
            raise ValueError(f"单文件超过上限（{MAX_UPLOAD // (1024*1024)} MiB）")
        target.parent.mkdir(parents=True, exist_ok=True)
        remaining = length
        with open(target, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        if remaining:
            target.unlink(missing_ok=True)
            raise ValueError(f"上传被截断：{rel}")
        return {"ok": True, "path": target.relative_to(root).as_posix(),
                "size": length, "target": lib.get("name")}

    # 静默常规访问日志，只留错误
    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def log_error(self, fmt, *args):
        sys.stderr.write("[http] " + (fmt % args) + "\n")


def cmd_scan(args) -> int:
    STATE["config"] = load_config()
    manifest = rescan(args.lib or None)   # args.lib 是 append 的 list，别再包一层
    print_scan_summary(manifest)
    print(f"[scan] 清单已写入 {MANIFEST_PATH}")
    if args.lib:
        print("[scan] 注意：本次只扫了指定库，preview-manifest.json 现在是**局部清单**"
              "（网页上只会出现这些库）；要全量就去掉 --lib 再扫一次。")
    return 0


def cmd_serve(args) -> int:
    STATE["config"] = load_config()
    only = args.lib or None   # append 的 list
    manifest = rescan(only)
    print_scan_summary(manifest)
    print(f"[manifest] {MANIFEST_PATH}")
    print(f"[libs] 库配置 {LIBS_PATH}")

    port = find_free_port(args.port)
    host = args.host
    shown_host = host if host != "0.0.0.0" else "127.0.0.1"
    url = f"http://{shown_host}:{port}{HTML_URL_PATH}"
    try:
        httpd = PreviewServer((host, port), PreviewHandler)
    except OSError as e:
        print(f"[!] 启动 HTTP 服务失败：{e}", file=sys.stderr)
        return 1
    print(f"[ready] 浏览器访问: {url}")
    print("        （按 Ctrl+C 停止服务）")

    if not args.no_browser:
        def opener():
            time.sleep(1.2)
            try:
                webbrowser.open(url)
            except Exception as e:
                print(f"[!] 自动打开浏览器失败：{e}", file=sys.stderr)
        threading.Thread(target=opener, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[http] 已停止。")
    finally:
        httpd.server_close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="2D 预览图浏览器 —— 多库扫描 + 预览服务。",
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
    ap.add_argument("--lib", action="append",
                    help="只扫描指定库（id / 路径 / 名称，可重复）")
    args = ap.parse_args()

    if args.cmd == "scan":
        return cmd_scan(args)
    return cmd_serve(args)


if __name__ == "__main__":
    sys.exit(main())
