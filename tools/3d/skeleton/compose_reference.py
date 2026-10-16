#!/usr/bin/env python3
"""把 `make_body_reference.py` 渲出的透明底正交图合成为【比例参考图】。

**为什么标注在渲染器之外做**（踩过的坑）：
  · Blender Workbench 的 `color_type='SINGLE'` 会把**标志线也涂成同一个颜色** → 线消失；
    且背景与身体几乎同色，剪影根本看不清。
  · 渲染器里加文字标签要造 Text 对象、还要处理朝向 —— 脆且难对齐。
  → Blender 只出**透明底正交图**（几何可信），**标注与配色由 PIL 做**（可控、可复算）。

三个必须做对的地方（每条都踩过）：
  ① **画幅边距由标签实测宽度决定**（两遍绘制）—— 写死 130 px 会把 `crown 100.0%` 切掉；
  ② **相邻标志点要合组** —— `chin 87.1%` 与 `head_base 87.5%` 只差 **5.6 px**，不合组就互相盖住；
  ③ **必须用含中日韩字形的字体** —— 用 Arial 中文会渲染成方块。

用法（工作区根，纯 python3）：
    python3 tools/3d/skeleton/compose_reference.py --dir tmp/bodyref --sex female
"""
from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
RED = (214, 40, 40)
BLUE = (30, 90, 200)
INK = (25, 25, 25)
HEAD_COUNT = 8
GROUP_PX = 22.0          # 行距小于此值的标志点合成一组标签


def font(size: int):
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def row_of(z: float, zc: float, ry: int, ppm: float) -> float:
    """世界高度 z → 像素行（相机中心 zc，图像中心行 ry/2，正方形像素）。"""
    return ry / 2 - (z - zc) * ppm


def groups_for(gmap: dict, zc: float, ry: int, ppm: float, H: float) -> list:
    rows = sorted((row_of(H * p / 100.0, zc, ry, ppm), n, p) for n, p in gmap.items())
    out, cur = [], []
    for it in rows:
        if cur and it[0] - cur[-1][0] < GROUP_PX:
            cur.append(it)
        else:
            if cur:
                out.append(cur)
            cur = [it]
    if cur:
        out.append(cur)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="tmp/bodyref")
    ap.add_argument("--sex", default="female")
    a = ap.parse_args()
    d = os.path.join(REPO, a.dir)
    meta = json.load(open(f"{d}/ref_meta.json", encoding="utf-8"))
    ppm = meta["px_per_m"]
    H = meta["target_height_m"]
    gmap = {g["name"]: g["pct"] for g in meta["guides"]}
    f13, f12, f11 = font(21), font(19), font(17)

    # ── 第一遍：量出所有标签的最大宽度 → 定画幅边距（否则标签被切）──
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    max_r = max_l = 0
    for tag, pose in meta["poses"].items():
        zc = (pose["bbox"]["z"][0] + pose["bbox"]["z"][1]) / 2
        ry = max(2, round((pose["bbox"]["z"][1] - pose["bbox"]["z"][0]) * meta["margin"] * ppm))
        for g in groups_for(gmap, zc, ry, ppm, H):
            max_r = max(max_r, probe.textlength("  ".join(f"{n} {p:.1f}%" for _, n, p in g), font=f13))
            max_l = max(max_l, probe.textlength("  ".join(f"{H*p/100:.3f}m" for _, _, p in g), font=f12))
    PAD_L = int(max_l) + 56
    PAD_R = int(max_r) + 26
    PAD_T, PAD_B = 46, 46
    print(f"[compose] 量得 左边距 {PAD_L} px / 右边距 {PAD_R} px")

    jobs = []
    for tag, pose in meta["poses"].items():
        jobs.append((f"{tag}_shaded", f"raw/{tag}_front.png", "shaded", pose))
        jobs.append((f"{tag}_silhouette", f"raw/{tag}_front.png", "silhouette", pose))
    jobs.append(("side_shaded", "raw/side.png", "shaded", meta["poses"]["apose"]))

    for name, src, kind, pose in jobs:
        p = os.path.join(d, src)
        if not os.path.isfile(p):
            continue
        im = Image.open(p).convert("RGBA")
        rw, rh = im.size
        zc = (pose["bbox"]["z"][0] + pose["bbox"]["z"][1]) / 2
        out = Image.new("RGB", (rw + PAD_L + PAD_R, rh + PAD_T + PAD_B), (255, 255, 255))
        if kind == "silhouette":
            body = Image.new("RGB", im.size, (255, 255, 255))
            body.paste((16, 16, 16), mask=im.split()[3])
        else:
            body = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im).convert("RGB")
        out.paste(body, (PAD_L, PAD_T))
        dr = ImageDraw.Draw(out)

        def R(z):
            return PAD_T + row_of(z, zc, rh, ppm)

        # 头身比刻度（左侧，蓝）
        for i in range(HEAD_COUNT + 1):
            y = R(H * i / HEAD_COUNT)
            dr.line([(PAD_L - 30, y), (PAD_L - 6, y)], fill=BLUE, width=2)
            dr.text((PAD_L - 54, y - 11), str(i), fill=BLUE, font=f12)
        dr.text((12, PAD_T - 34), f"头身比刻度（1/{HEAD_COUNT} 身高）", fill=BLUE, font=f12)

        # 标志点横线（红）+ 合组标签
        for g in groups_for(gmap, zc, rh, ppm, H):
            yl = sum(i[0] for i in g) / len(g)
            for y, _, _ in g:
                dr.line([(PAD_L - 4, y), (PAD_L + rw + 4, y)], fill=RED, width=2)
            dr.text((PAD_L + rw + 10, yl - 11),
                    "  ".join(f"{n} {p:.1f}%" for _, n, p in g), fill=RED, font=f13)
            dr.text((PAD_L - max_l - 12, yl - 11),
                    "  ".join(f"{H*p/100:.3f}m" for _, _, p in g), fill=INK, font=f12)

        tagtxt = "A-pose（原始）" if name.startswith("apose") else (
            "T-pose（摆平）" if name.startswith("tpose") else "A-pose 侧视")
        kindtxt = {"silhouette": "纯剪影", "shaded": "平光"}[kind]
        dr.text((PAD_L, PAD_T + rh + 8),
                f"{a.sex} · {tagtxt} · {kindtxt} · 身高 {H:.4f} m · {ppm:.0f} px/m · "
                f"臂展/身高 {pose['span_over_height']:.4f} · 正交投影",
                fill=INK, font=f11)
        fn = f"{d}/ref_{a.sex}_{name}.png"
        out.save(fn)
        print(f"[compose] {os.path.relpath(fn, REPO)}  {out.size[0]}×{out.size[1]}")


if __name__ == "__main__":
    main()
