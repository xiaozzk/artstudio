#!/usr/bin/env python3
"""anim_preview.py — 把交付包渲染成单文件离线预览 HTML（官方 spine-player 内嵌）。

用途：动画迁移的验收出口。agent 跑完 anim_retarget.py 后调它，
双击产物 html 即可在浏览器里切动画/切皮肤验收，无需起服务、无需联网。

用法：
  python3 tools/spine/anim/anim_preview.py <包目录或骨架json> [-o 输出.html]
      [--animation attack] [--skin default]

实现要点（2026-09-25 实测）：
- player 4.3 的 config 字段是 skeleton/atlas（不是 4.2 的 jsonUrl/atlasUrl）
- json/atlas/png 全部 base64 内嵌进 rawDataURIs；player js/css 读本地 vendor
  （tools/preview-2d/vendor/spine-player/）内联，产物完全离线自包含
- 图集页按 atlas 页头行解析（页名=顶格无冒号+图片扩展名；字段序不固定，
  别依赖"下一行是 size:"）
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[3]
VENDOR = WORKSPACE / "tools" / "preview-2d" / "vendor" / "spine-player"


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def parse_atlas_pages(atlas_path: Path) -> list[str]:
    pages = []
    for line in atlas_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if (s and not line.startswith((" ", "\t")) and ":" not in s
                and s.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
            pages.append(s)
    return pages


def load_package(path: Path) -> tuple[Path, Path, Path]:
    """返回 (骨架json, atlas, 包目录)。"""
    pkg_dir = path if path.is_dir() else path.parent
    json_path = None
    if path.is_file() and path.suffix == ".json":
        json_path = path
    else:
        for jf in sorted(pkg_dir.glob("*.json")):
            try:
                doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(doc, dict) and "bones" in doc and "skeleton" in doc:
                json_path = jf
                break
    if json_path is None:
        raise SystemExit(f"[!] {pkg_dir} 下找不到骨架 json")
    atlas_files = sorted(pkg_dir.glob("*.atlas"))
    if not atlas_files:
        raise SystemExit(f"[!] {pkg_dir} 下没有 .atlas")
    return json_path, atlas_files[0], pkg_dir


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="交付包 → 单文件离线 spine 预览 HTML")
    ap.add_argument("pkg", help="包目录或骨架 json 路径")
    ap.add_argument("-o", "--output", default=None, help="输出 html（默认 <包目录>/preview.html）")
    ap.add_argument("--animation", default=None, help="默认播放的动画名")
    ap.add_argument("--skin", default=None, help="默认皮肤名")
    args = ap.parse_args(argv[1:])

    json_path, atlas_path, pkg_dir = load_package(Path(args.pkg))
    doc = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    pages = parse_atlas_pages(atlas_path)

    player_js = (VENDOR / "spine-player.js").read_text(encoding="utf-8")
    player_css = (VENDOR / "spine-player.css").read_text(encoding="utf-8")

    raw = {
        json_path.name: "data:application/json;base64," + b64(json_path),
        atlas_path.name: "data:text/plain;base64," + b64(atlas_path),
    }
    for p in pages:
        pp = pkg_dir / p
        if pp.is_file():
            raw[p] = "data:image/png;base64," + b64(pp)

    anims = sorted(doc.get("animations", {}).keys())
    skins = [s.get("name", "?") for s in doc.get("skins", [])]
    title = f"{pkg_dir.name} · Spine 预览"
    animation = args.animation or (anims[0] if anims else None)
    raw_js = json.dumps(raw, ensure_ascii=False)
    config_bits = [
        f'skeleton: "{json_path.name}"',
        f'atlas: "{atlas_path.name}"',
        'rawDataURIs: RAW',
        'showControls: true',
        'backgroundColor: "#161a22"',
        'alpha: false',
    ]
    if animation:
        config_bits.append(f'animation: {json.dumps(animation)}')
    if args.skin:
        config_bits.append(f'skin: {json.dumps(args.skin)}')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{player_css}</style>
<style>
  body {{ margin:0; background:#0f1115; color:#e8ecf1;
         font-family:-apple-system,"PingFang SC",sans-serif; }}
  .bar {{ padding:10px 16px; border-bottom:1px solid #2a3140;
         font:12px ui-monospace,Consolas,monospace; color:#93a0b3; }}
  .bar b {{ color:#ffd479; }}
  #box {{ height: calc(100vh - 40px); }}
  #box .spine-player {{ height: 100%; }}
</style>
</head>
<body>
<div class="bar">{pkg_dir.name} · Spine <b>{doc.get('skeleton',{}).get('spine','?')}</b>
 · <b>{len(anims)}</b> 动画（{' / '.join(anims)}） · <b>{len(skins)}</b> 皮肤</div>
<div id="box"></div>
<script>{player_js}</script>
<script>
const RAW = {raw_js};
new spine.SpinePlayer(document.getElementById('box'), {{
  {', '.join(config_bits)},
  success: (p) => {{ try {{ p.play?.(); }} catch (_) {{}} }},
  error: (p, msg) => {{
    document.getElementById('box').innerHTML =
      '<div style="padding:40px;color:#ff7b72">加载失败：' + msg + '</div>';
  }},
}});
</script>
</body>
</html>"""
    out = Path(args.output) if args.output else pkg_dir / "preview.html"
    out.write_text(html, encoding="utf-8")
    print(f"[preview] {out}（{out.stat().st_size / 1024:.0f} KB，{len(anims)} 动画）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
