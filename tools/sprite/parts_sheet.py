#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parts_sheet.py — 把一组部件贴图摆成"互不重叠、相邻间隔 ≥ N 像素"的参考图。

**为什么需要**：原画是叠好的成品，相邻部件互相压着（比如手臂压在指虎上），喂给 AI 时它看到的是
"一整块"，会顺着重叠边界把两个部件画成一个。把每个部件按 alpha 裁出来、彼此留出 ≥N px 空隙，
模型才能看清"这是几个独立零件"（与 AGENTS.md 的"给整张拼图 + 明说每块是独立图层"同源）。

算法（确定性，无随机）：
    1. 每个部件按 alpha 非零区域裁紧（trim），记录裁紧后的尺寸
    2. shelf packing：按高度降序依次放进"货架"；同一行内相邻间隔 = gutter，行间距 = gutter，
       画布宽度按总面积自动估算（`--width` 可强制）
    3. **自检**：逐对计算矩形间距，断言最小值 ≥ gutter；可见像素都在各自矩形内部，
       故矩形间距 ≥ N ⇒ 像素间距 ≥ N

用法：
    python tools/sprite/parts_sheet.py --parts a.png b.png c.png --out sheet.png
    python tools/sprite/parts_sheet.py --from-dir assets/武僧/images_original --out sheet.png --gutter 20
    python tools/sprite/parts_sheet.py --from-dir <目录> --out sheet.png --json-out layout.json
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os

from PIL import Image

BG_DEFAULT = 205          # 纯灰底 205：深色描边的部件在这种底上边界最清楚（仓库既有约定）


def trim(im: Image.Image) -> Image.Image:
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def pack(sizes, gutter, canvas_w=None):
    """shelf packing → [(x, y, w, h)]，保证两两矩形间距 ≥ gutter。"""
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
    total = sum((w + gutter) * (h + gutter) for w, h in sizes)
    if canvas_w is None:
        canvas_w = max(max(w for w, _ in sizes), int(math.sqrt(total) * 1.15))
    placed = [None] * len(sizes)
    x = y = row_h = 0
    for i in order:
        w, h = sizes[i]
        if x > 0 and x + w > canvas_w:
            x, y, row_h = 0, y + row_h + gutter, 0
        placed[i] = (x, y, w, h)
        x += w + gutter
        row_h = max(row_h, h)
    return placed, canvas_w, y + row_h


def min_gap(placed) -> float:
    """逐对矩形间距的最小值（斜对角取欧氏距离）。"""
    best = None
    for i, (x1, y1, w1, h1) in enumerate(placed):
        for x2, y2, w2, h2 in placed[i + 1:]:
            dx = max(x2 - (x1 + w1), x1 - (x2 + w2), 0)
            dy = max(y2 - (y1 + h1), y1 - (y2 + h2), 0)
            gap = math.hypot(dx, dy) if (dx and dy) else max(dx, dy)
            best = gap if best is None else min(best, gap)
    return float("inf") if best is None else best


def collect_parts(parts, from_dir, pattern, exclude):
    files = list(parts or [])
    if from_dir:
        files += sorted(glob.glob(os.path.join(from_dir, pattern)))
    files = [f for f in files if os.path.basename(f) not in set(exclude or [])]
    if not files:
        raise SystemExit("没有输入部件：给 --parts 或 --from-dir")
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="部件排布：互不重叠、相邻间隔 ≥ N px 的参考图")
    ap.add_argument("--parts", nargs="+", help="部件 PNG 列表")
    ap.add_argument("--from-dir", help="从目录取部件（配合 --pattern/--exclude）")
    ap.add_argument("--pattern", default="*.png")
    ap.add_argument("--exclude", nargs="*", default=["desktop.ini"], help="按文件名排除")
    ap.add_argument("--out", required=True)
    ap.add_argument("--gutter", type=int, default=20, help="相邻部件最小间隔（像素），默认 20")
    ap.add_argument("--bg", type=int, default=BG_DEFAULT, help="底色灰度，默认 205")
    ap.add_argument("--width", type=int, default=0, help="强制画布宽度（0=自动）")
    ap.add_argument("--json-out", default=None, help="落盘排布表")
    a = ap.parse_args(argv)

    files = collect_parts(a.parts, a.from_dir, a.pattern, a.exclude)
    parts = []
    for p in files:
        im = Image.open(p).convert("RGBA")
        t = trim(im)
        parts.append({"path": p, "name": os.path.splitext(os.path.basename(p))[0],
                      "orig": im.size, "img": t, "size": t.size})

    placed, cw, ch = pack([p["size"] for p in parts], a.gutter, a.width or None)
    gap = min_gap(placed)
    if gap < a.gutter:
        raise SystemExit(f"排布自检失败：最小间距 {gap:.1f} < {a.gutter}（算法或参数有问题）")

    canvas = Image.new("RGB", (cw, ch), (a.bg, a.bg, a.bg))
    for p, (x, y, _w, _h) in zip(parts, placed):
        canvas.paste(p["img"], (x, y), p["img"])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    canvas.save(a.out)

    print(f"部件 {len(parts)} 个，画布 {cw}x{ch}，最小间距 {gap:.1f}px（要求 ≥{a.gutter}）")
    for p, (x, y, w, h) in zip(parts, placed):
        print(f"  {p['name']:14s} 原图 {p['orig'][0]}x{p['orig'][1]} → 裁紧 {w}x{h}  @({x},{y})")
    if a.json_out:
        json.dump({"out": a.out, "canvas": [cw, ch], "gutter": a.gutter, "min_gap": gap,
                   "parts": [{"name": p["name"], "src": p["path"], "orig": list(p["orig"]),
                              "trim": list(p["size"]), "box": list(placed[i])}
                             for i, p in enumerate(parts)]},
                  open(a.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"排布表 → {a.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
