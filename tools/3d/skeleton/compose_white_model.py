#!/usr/bin/env python3
"""把 `render_white_model.py` 的图合成【白模体检图】：4 全身视角 + 手/头/脚特写。

用法（工作区根，纯 python3）：
    python3 tools/3d/skeleton/compose_white_model.py --dir tmp/whitemodel
"""
from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FONTS = ["/System/Library/Fonts/Hiragino Sans GB.ttc",
         "/System/Library/Fonts/StHeiti Medium.ttc",
         "/System/Library/Fonts/Supplemental/Songti.ttc",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
LABEL = {"front": "正面", "three_quarter": "四分之三", "side": "侧面", "back": "背面",
         "hand": "手  [注意] 连指手套形", "head": "头  [注意] 无五官", "foot": "脚"}
NOTES = ["白模体检 · 结论",
         "(字体无 emoji 字形，故写 [注意] 而非符号)",
         "",
         "手：手指未分（连指手套形）",
         "    也因此使有效臂展偏短",
         "头：完全无五官",
         "    但按契约头本就是独立资产",
         "    故不算缺陷",
         "脚：形制粗糙，脚趾只有轮廓",
         "体表：全四边形控制笼",
         "    + SUBSURF 1/2 级，平滑",
         "网格：女 5256 v / 男 5466 v",
         "    男女拓扑不同",
         "    不能跨性别复用服装件"]


def font(sz):
    for p in FONTS:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="tmp/whitemodel")
    a = ap.parse_args()
    d = os.path.join(REPO, a.dir)
    meta = json.load(open(f"{d}/white_meta.json", encoding="utf-8"))
    f_t, f_h, f_s = font(30), font(23), font(19)
    RH1, RH2, PAD = 700, 430, 22

    for sex in ("female", "male"):
        rec = meta[sex]
        views = [(v, Image.open(f"{d}/raw/{sex}_{v}.png").convert("RGB")) for v in rec["views"]]
        cups = [(c, Image.open(f"{d}/raw/{sex}_{c}.png").convert("RGB")) for c in rec["closeups"]]
        scaled = []
        for name, im in views:
            w = max(2, round(im.size[0] * RH1 / im.size[1]))
            scaled.append((name, im.resize((w, RH1), Image.LANCZOS)))
        scaled2 = []
        for name, im in cups:
            w = max(2, round(im.size[0] * RH2 / im.size[1]))
            scaled2.append((name, im.resize((w, RH2), Image.LANCZOS)))
        row1w = sum(w for _, im in scaled for w in [im.size[0]]) + PAD * (len(scaled) + 1)
        row2w = sum(im.size[0] for _, im in scaled2) + PAD * (len(scaled2) + 1)
        TXT = 640
        W = max(row1w, row2w) + TXT
        H = 96 + RH1 + 54 + RH2 + 56
        sheet = Image.new("RGB", (W, H), (255, 255, 255))
        dr = ImageDraw.Draw(sheet)
        dr.text((PAD, 16), f"{sex}  ·  白模体检  ·  身高 {rec['height_m']:.4f} m  ·  "
                           f"原始 A-pose  ·  正交投影  ·  影棚光", fill=(15, 15, 15), font=f_t)

        x = PAD
        for name, im in scaled:
            sheet.paste(im, (x, 88))
            dr.rectangle([x, 88, x + im.size[0], 88 + RH1], outline=(165, 165, 165))
            dr.text((x + 4, 88 + RH1 + 6), LABEL.get(name, name), fill=(35, 35, 35), font=f_h)
            x += im.size[0] + PAD
        y2 = 88 + RH1 + 54
        x = PAD
        for name, im in scaled2:
            sheet.paste(im, (x, y2))
            dr.rectangle([x, y2, x + im.size[0], y2 + RH2], outline=(165, 165, 165))
            dr.text((x + 4, y2 + RH2 + 6), LABEL.get(name, name), fill=(35, 35, 35), font=f_s)
            x += im.size[0] + PAD

        tx, ty = W - TXT + 8, 88
        for line in NOTES:
            dr.text((tx, ty), line, fill=(30, 30, 30) if (not line.startswith((" ", "手", "头", "脚", "体", "网", "(")) or line.endswith("结论")) else (95, 95, 95),
                    font=f_h if (line.endswith("结论") or line[:2] in ("手：", "头：", "脚：", "体表", "网格")) else f_s)
            ty += 32

        fn = f"{d}/white_{sex}.png"
        sheet.save(fn)
        print(f"[white-sheet] {os.path.relpath(fn, REPO)}  {sheet.size[0]}×{sheet.size[1]}")


if __name__ == "__main__":
    main()
