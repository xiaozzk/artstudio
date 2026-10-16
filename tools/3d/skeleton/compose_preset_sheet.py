#!/usr/bin/env python3
"""把 `compare_body_presets.py` 的 4 个体型预设剪影合成【对比图】：并排 + 叠加 + 围度表。

**为什么用叠加**：单看 4 张并排很难判断"腰差多少"，**把轮廓叠在同一坐标系里**一眼就看出来。
各图由 `compare_body_presets.py` 以**固定取景**渲出 → **逐像素对齐**，可以直接叠。

**轮廓怎么画**（踩过）：不要逐像素判邻域（慢且断断续续），用形态学滤波：
`dilate = alpha.filter(MaxFilter(k))`，`edge = dilate - alpha` → 干净连续的描边。

用法（工作区根，纯 python3）：
    python3 tools/3d/skeleton/compose_preset_sheet.py --dir tmp/bodycmp
"""
from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FONTS = ["/System/Library/Fonts/Hiragino Sans GB.ttc",
         "/System/Library/Fonts/StHeiti Medium.ttc",
         "/System/Library/Fonts/Supplemental/Songti.ttc",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
COLORS = {"Thin": (40, 90, 200), "Regular": (16, 140, 84),
          "Muscular": (230, 130, 20), "Fat": (205, 40, 40)}
ORDER = ["Thin", "Regular", "Muscular", "Fat"]
BAND = ["现实健康区间 WHtR = 0.40 ~ 0.49", "（WHO 建议 < 0.50）",
        "Bodiez 预设是「区间带硬切换」——", "Regular 与 Muscular 之间没有中间档，",
        "所以「稍微加粗一点」它做不到。"]


def font(sz):
    for p in FONTS:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def edge_mask(al: Image.Image, k: int = 5) -> Image.Image:
    """alpha 的轮廓：形态学膨胀 - 原图。k 越大描边越粗。"""
    return ImageChops.subtract(al.filter(ImageFilter.MaxFilter(k)), al)


def paint(img: Image.Image, mask: Image.Image, color) -> None:
    img.paste(Image.new("RGB", img.size, color), mask=mask)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="tmp/bodycmp")
    a = ap.parse_args()
    d = os.path.join(REPO, a.dir)
    meta = json.load(open(f"{d}/presets.json", encoding="utf-8"))
    f_t, f_h, f_s = font(28), font(23), font(19)

    for sex in ("female", "male"):
        rec = meta[sex]
        ims = {}
        for name in ORDER:
            p = f"{d}/raw/preset_{sex}_{name}.png"
            if os.path.isfile(p):
                ims[name] = Image.open(p).convert("RGBA")
        if not ims:
            continue
        rw = min(i.size[0] for i in ims.values())
        rh = min(i.size[1] for i in ims.values())
        ims = {k: v.crop((0, 0, rw, rh)) for k, v in ims.items()}
        alphas = {k: v.split()[3] for k, v in ims.items()}

        H = 660
        sc = H / rh
        w1 = int(rw * sc)
        PAD, TOP, ROWGAP = 26, 84, 44
        TXT = 470
        W = PAD + (w1 + PAD) * 4 + TXT
        sheet = Image.new("RGB", (W, TOP + H + ROWGAP + H + 210), (255, 255, 255))
        dr = ImageDraw.Draw(sheet)
        dr.text((PAD, 14), f"{sex}  ·  体型预设对比  ·  目标身高 {rec['target_height_m']} m  ·  "
                           f"正交投影 / 固定取景 / 像素正方形", fill=(15, 15, 15), font=f_t)
        dr.text((PAD, 50), "围度用「软尺量法」：水平切片 → XY 凸包周长（已剔除手臂/手指顶点）",
                fill=(95, 95, 95), font=f_s)

        # ── 第二行：叠加（先画，占左半）──
        y2 = TOP + H + ROWGAP
        ov = Image.new("RGB", (rw, rh), (255, 255, 255))
        for name in ORDER:
            paint(ov, edge_mask(alphas[name], 5), COLORS[name])
        sheet.paste(ov.resize((w1 * 2 + PAD, H), Image.LANCZOS), (PAD, y2))
        dr.rectangle([PAD, y2, PAD + w1 * 2 + PAD, y2 + H], outline=(150, 150, 150))
        dr.text((PAD, y2 + H + 8), "叠加：4 个预设的轮廓（同坐标系）", fill=(15, 15, 15), font=f_s)

        # ── 围度表（第二行右侧）──
        tx, ty = PAD + (w1 + PAD) * 2 + PAD * 2, y2
        dr.text((tx, ty), "围度 (cm)", fill=(15, 15, 15), font=f_h); ty += 36
        dr.text((tx, ty), f"{'预设':<8}{'胸':>8}{'腰':>8}{'臀':>8}", fill=(60, 60, 60), font=f_s)
        ty += 30
        for name in ORDER:
            g = rec["presets"][name]["girth_m"]
            dr.text((tx, ty), f"{name:<9}{g['chest']*100:8.1f}{g['waist']*100:8.1f}{g['hip']*100:8.1f}",
                    fill=COLORS[name], font=f_s)
            ty += 30
        ty += 18
        dr.text((tx, ty), "腰围 / 身高  (WHtR)", fill=(15, 15, 15), font=f_h); ty += 36
        for name in ORDER:
            r = rec["presets"][name]["girth_over_height"]["waist"]
            dr.text((tx, ty), f"{name:<9}{r:.4f}" + ("   ← 低于健康区间" if r < 0.40 else ""),
                    fill=COLORS[name], font=f_s)
            ty += 30
        ty += 16
        for line in BAND:
            dr.text((tx, ty), line, fill=(95, 95, 95), font=f_s)
            ty += 27

        # ── 第一行：4 个预设并排 ──
        for i, name in enumerate(ORDER):
            x = PAD + (w1 + PAD) * i
            im = Image.new("RGB", (rw, rh), (255, 255, 255))
            tint = tuple(int(255 - (255 - c) * 0.22) for c in COLORS[name])
            im.paste(tint, mask=alphas[name])
            paint(im, edge_mask(alphas[name], 5), COLORS[name])
            sheet.paste(im.resize((w1, H), Image.LANCZOS), (x, TOP))
            dr.rectangle([x, TOP, x + w1, TOP + H], outline=(150, 150, 150))
            g = rec["presets"][name]["girth_m"]
            dr.text((x + 4, TOP + H + 8), f"{name}   腰 {g['waist']*100:.1f} cm", fill=COLORS[name], font=f_h)

        fn = f"{d}/compare_{sex}.png"
        sheet.save(fn)
        print(f"[sheet] {os.path.relpath(fn, REPO)}  {sheet.size[0]}×{sheet.size[1]}")


if __name__ == "__main__":
    main()
