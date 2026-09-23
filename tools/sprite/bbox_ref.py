#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bbox_ref.py — 画「身体比例 bbox 参考图」, 并把比例换算到任意目标分辨率。

用途:
  1. 给 AI 当比例参考(把 bbox 参考图作为参考图喂进去, 让它照比例生成/编辑);
  2. 给自己当验收标尺(生成结果拆件后, 用同一张参考图核对比例是否跑偏);
  3. 把归一化比例(0~1)换算成任意目标分辨率下的像素坐标。

用法:

  # 生成参考图(带原图做底, 半透明)
  python tools/sprite/bbox_ref.py spec.json -o out_dir

  # 纯线框比例示意图(不叠原图, 适合直接喂给 AI)
  python tools/sprite/bbox_ref.py spec.json -o out_dir --no-base

  # 换算到目标分辨率: 内容高度 2048
  python tools/sprite/bbox_ref.py spec.json -o out_dir --target-height 2048

spec.json 结构:
{
  "canvas": [385, 1672],
  "base_image": "tmp/head_split/_composite_full.png",   // 相对工作区根；可为 null
  "parts": [
    {"name": "head", "bbox": [4, 1, 359, 484], "color": "#e6553d"}
  ],
  "hlines": [{"y": 442, "label": "shoulder"}],
  "vlines": [{"x": 192.5, "label": "center"}]
}

输出:
  out_dir/bbox_ref.png          带底图的标注参考图
  out_dir/bbox_schematic.png    纯线框比例示意图(黑底/白底矢量风格)
  out_dir/bbox_ref.json         归一化比例 + 目标分辨率像素表
  out_dir/bbox_ref.md           同内容的 markdown 表格
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PALETTE = [
    "#e6553d", "#3d91e6", "#4caf50", "#ffb300", "#9c27b0", "#00bcd4",
    "#e91e63", "#795548", "#3f51b5", "#8bc34a", "#ff5722", "#009688",
    "#cddc39", "#607d8b", "#f44336", "#2196f3",
]


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover
        return ImageFont.load_default()


def hex_to_rgb(s: str):
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def text_size(d, txt, f):
    b = d.textbbox((0, 0), txt, font=f)
    return b[2] - b[0], b[3] - b[1], b[1]


def render(canvas_w, canvas_h, parts, hlines, vlines, base_img,
           dim_base=0.45, schematic=False, title="") -> Image.Image:
    if schematic:
        im = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    elif base_img is not None:
        layer = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        layer.paste(base_img, (0, 0), base_img if base_img.mode == "RGBA" else None)
        arr = np.array(layer).astype(np.float32)
        arr = arr * dim_base + 255.0 * (1 - dim_base)
        im = Image.fromarray(arr.astype(np.uint8))
    else:
        im = Image.new("RGB", (canvas_w, canvas_h), (250, 250, 250))

    d = ImageDraw.Draw(im, "RGBA")
    fs = max(10, min(canvas_w, canvas_h) // 55)
    fsm = font(max(9, fs - 2))

    # 网格(每 10%) + 左侧百分比刻度
    for pct in range(0, 11):
        y = min(canvas_h - 1, int(canvas_h * pct / 10))
        d.line([0, y, canvas_w, y], fill=(0, 0, 0, 55), width=1)
        lab = f"{pct*10}%"
        tw, th, off = text_size(d, lab, fsm)
        d.rectangle([0, y + 1, tw + 6, y + th + off + 4], fill=(255, 255, 255, 190))
        d.text((3, y + 2), lab, fill=(90, 90, 90), font=fsm)

    placed: list[tuple[int, int, int, int]] = []

    def place(x, y, w, h, pref="down"):
        """在 (x,y) 附近找一个不与已放置标签重叠的位置。"""
        cand = []
        if pref == "down":
            cand += [(x, y + k * (h + 2)) for k in range(0, 14)]
            cand += [(x, y - (k + 1) * (h + 2)) for k in range(0, 14)]
        else:
            cand += [(x, y - (k + 1) * (h + 2)) for k in range(0, 14)]
            cand += [(x, y + k * (h + 2)) for k in range(0, 14)]
        for cx, cy in cand:
            cy = max(0, min(canvas_h - h - 1, cy))
            cx = max(0, min(canvas_w - w - 1, cx))
            r = (cx, cy, cx + w, cy + h)
            if not any(r[0] < q[2] and q[0] < r[2] and r[1] < q[3] and q[1] < r[3]
                       for q in placed):
                placed.append(r)
                return cx, cy
        placed.append((x, y, x + w, y + h))
        return x, y

    # 部件
    for i, p in enumerate(parts):
        x0, y0, x1, y1 = p["bbox"]
        c = hex_to_rgb(p.get("color") or PALETTE[i % len(PALETTE)])
        fill_a = 34 if schematic else 52
        d.rectangle([x0, y0, x1 - 1, y1 - 1],
                    fill=c + (fill_a,), outline=c + (255,), width=2)
        if schematic:
            d.line([x0, (y0 + y1) // 2, x1, (y0 + y1) // 2], fill=c + (90,), width=1)
            d.line([(x0 + x1) // 2, y0, (x0 + x1) // 2, y1], fill=c + (90,), width=1)
        w, h = x1 - x0, y1 - y0
        pct = 100.0 * h / canvas_h
        txt = f"{p['name']} {w}x{h} ({pct:.1f}%H)"
        tw, th, off = text_size(d, txt, fsm)
        bx, by = place(x0 + 3, y0 + 3 if h > fs * 2.2 else y0 - th - off - 5,
                       tw + 6, th + off + 4, pref="down" if h > fs * 2.2 else "up")
        d.rectangle([bx, by, bx + tw + 6, by + th + off + 4], fill=c + (238,))
        d.text((bx + 3, by + 1), txt, fill=(255, 255, 255), font=fsm)

    # 关键横线
    for hl in hlines:
        y = int(round(hl["y"]))
        col = hex_to_rgb(hl.get("color", "#d81b60"))
        d.line([0, y, canvas_w, y], fill=col + (255,), width=1)
        lab = f"{hl['label']} y={y} ({100.0 * y / canvas_h:.1f}%)"
        tw, th, off = text_size(d, lab, fsm)
        bx, by = place(canvas_w - tw - 10, y - th - off - 4, tw + 6, th + off + 4,
                       pref="up")
        d.rectangle([bx, by, bx + tw + 6, by + th + off + 4], fill=col + (238,))
        d.text((bx + 3, by + 1), lab, fill=(255, 255, 255), font=fsm)

    # 关键竖线
    for vl in vlines:
        x = int(round(vl["x"]))
        col = hex_to_rgb(vl.get("color", "#1e88e5"))
        d.line([x, 0, x, canvas_h], fill=col + (150,), width=1)

    if title:
        ft = font(max(13, fs + 3))
        tw, th, off = text_size(d, title, ft)
        d.rectangle([0, 0, tw + 12, th + off + 8], fill=(25, 25, 25, 235))
        d.text((6, 4), title, fill=(255, 255, 255), font=ft)
    return im


def main() -> int:
    ap = argparse.ArgumentParser(description="生成身体比例 bbox 参考图 + 目标分辨率换算")
    ap.add_argument("spec", type=Path)
    ap.add_argument("-o", "--out-dir", type=Path, required=True)
    ap.add_argument("--no-base", action="store_true", help="不叠底图(生成纯线框)")
    ap.add_argument("--dim", type=float, default=0.45, help="底图保留亮度比例 0~1")
    ap.add_argument("--target-height", type=int, default=None,
                    help="额外输出该内容高度下的像素坐标换算")
    ap.add_argument("--target-canvas", default=None,
                    help="画布尺寸 WxH, 按画布等比缩放(与 --target-height 二选一)")
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    cw, ch = spec.get("canvas", [None, None])
    parts = spec.get("parts", [])
    hlines = spec.get("hlines", [])
    vlines = spec.get("vlines", [])
    if not parts:
        print("[ERROR] spec 里没有 parts")
        return 2
    if cw is None or ch is None:
        xs = [p["bbox"][2] for p in parts]
        ys = [p["bbox"][3] for p in parts]
        cw = max(xs) + 1
        ch = max(ys) + 1
        print(f"[i] spec 未给 canvas, 由 parts 推出 {cw}x{ch}")

    base = None
    bp = spec.get("base_image")
    if not args.no_base and bp:
        p = Path(bp)
        if p.is_file():
            base = Image.open(p).convert("RGBA")
            if base.size != (cw, ch):
                print(f"[w] 底图尺寸 {base.size} != canvas {(cw, ch)}, 已贴到左上角")
        else:
            print(f"[w] 底图不存在: {bp}")

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    im = render(cw, ch, parts, hlines, vlines, base, args.dim, False,
                title=f"proportion ref  canvas {cw}x{ch}")
    im.save(out_dir / "bbox_ref.png")
    sch = render(cw, ch, parts, hlines, vlines, None, 1.0, True,
                 title=f"proportion schematic  H={ch}px")
    sch.save(out_dir / "bbox_schematic.png")

    # ---- 归一化 + 目标分辨率换算
    sx = sy = 1.0
    tgt = None
    if args.target_height:
        sy = args.target_height / ch
        sx = sy
        tgt = [int(round(cw * sx)), int(round(ch * sy))]
    elif args.target_canvas:
        tw, th = (int(v) for v in args.target_canvas.lower().split("x"))
        sx, sy = tw / cw, th / ch
        tgt = [tw, th]

    def scale_bbox(b):
        return [round(b[0] * sx, 2), round(b[1] * sy, 2),
                round(b[2] * sx, 2), round(b[3] * sy, 2)]

    table = []
    for i, p in enumerate(parts):
        x0, y0, x1, y1 = p["bbox"]
        row = dict(
            name=p["name"],
            color=p.get("color") or PALETTE[i % len(PALETTE)],
            bbox=[x0, y0, x1, y1],
            size=[x1 - x0, y1 - y0],
            center=[round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)],
            norm_bbox=[round(x0 / cw, 6), round(y0 / ch, 6),
                       round(x1 / cw, 6), round(y1 / ch, 6)],
            h_ratio=round((y1 - y0) / ch, 6),
            top_pct=round(100.0 * y0 / ch, 3),
            bottom_pct=round(100.0 * y1 / ch, 3),
        )
        if tgt:
            row["target_bbox"] = scale_bbox(p["bbox"])
            row["target_size"] = [round((x1 - x0) * sx, 2), round((y1 - y0) * sy, 2)]
        table.append(row)

    norm = dict(
        source_spec=str(args.spec),
        canvas=[cw, ch],
        content_bbox=spec.get("content_bbox"),
        head_units=spec.get("head_units"),
        target_canvas=tgt,
        scale=[round(sx, 6), round(sy, 6)],
        hlines=[dict(y=h["y"], label=h["label"],
                     norm_y=round(h["y"] / ch, 6),
                     target_y=round(h["y"] * sy, 2) if tgt else None)
                for h in hlines],
        vlines=[dict(x=v["x"], label=v["label"],
                     norm_x=round(v["x"] / cw, 6),
                     target_x=round(v["x"] * sx, 2) if tgt else None)
                for v in vlines],
        parts=table,
    )
    (out_dir / "bbox_ref.json").write_text(
        json.dumps(norm, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- markdown
    md = ["# 比例参考 bbox 表", "",
          f"- 源 spec: `{args.spec}`",
          f"- 画布: **{cw} × {ch} px**"]
    if tgt:
        md.append(f"- 目标分辨率: **{tgt[0]} × {tgt[1]} px**"
                  f" (scale x{sx:.4f}, y{sy:.4f})")
    md += ["", "| # | 部件 | bbox [L,T,R,B] | 宽×高 | 中心 | 高/总高 | 顶部% | 底部% |",
           "|---|------|----------------|-------|------|---------|-------|--------|"]
    for i, r in enumerate(table):
        md.append(f"| {i} | `{r['name']}` | {r['bbox']} | {r['size'][0]}×{r['size'][1]} "
                  f"| ({r['center'][0]}, {r['center'][1]}) | {r['h_ratio']*100:.1f}% "
                  f"| {r['top_pct']:.1f}% | {r['bottom_pct']:.1f}% |")
    if hlines:
        md += ["", "## 关键横线", "", "| 位置 | y | 占高 |" + (" 目标 y |" if tgt else ""),
               "|------|---|------|" + ("--------|" if tgt else "")]
        for h in norm["hlines"]:
            md.append(f"| {h['label']} | {h['y']} | {h['norm_y']*100:.2f}% |"
                      + (f" {h['target_y']} |" if tgt else ""))
    (out_dir / "bbox_ref.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"{'#':>3} {'name':<16} {'bbox':<26} {'w x h':<12} {'h/H':>7}  top%   bot%")
    print("-" * 78)
    for r in table:
        print(f"{table.index(r):>3} {r['name']:<16} {str(r['bbox']):<26} "
              f"{str(r['size'][0]) + 'x' + str(r['size'][1]):<12} "
              f"{r['h_ratio']*100:>6.1f}% {r['top_pct']:>6.1f} {r['bottom_pct']:>6.1f}")
    print("-" * 78)
    print(f"[OK] {out_dir}\\bbox_ref.png  bbox_schematic.png  "
          f"bbox_ref.json  bbox_ref.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
