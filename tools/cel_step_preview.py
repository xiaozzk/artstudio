# -*- coding: utf-8 -*-
"""cel_step_preview.py — 平涂资产的分阶预览生成器（纯本地，零 AI 额度）

用途：把已有的**平涂**资产渲染成「0 阶 / 1 阶 / 2 阶」对照图，用来判断
"要不要给这个部件加暗部"、"加一阶还是两阶"。不修改源文件，只输出预览。

算法（确定性，可复现）：
  1. 对每个部件的 alpha 做距离变换 d，归一化得 dn（0=贴边, 1=部件核心）
  2. 取背光侧权重 shadowness = clamp(-dot(径向方向, 光方向), 0, 1)
  3. 阴影场 field = (1 - dn) ** edge_pow * shadowness
     → 同时满足"靠近轮廓"与"位于背光侧"的地方才变暗，形成沿形体的暗部
  4. 按阈值硬切分档（cel 的关键是**硬边**，不是渐变），乘到 RGB，alpha 与线稿不动

这与 SKILL 里"no gradient"的约定一致：产出的暗部是**形状**，不是过渡。

用法：
  python tools/cel_step_preview.py                     # 用默认 Eva 资产出对照图
  python tools/cel_step_preview.py --src <png> --outdir <dir>
  python tools/cel_step_preview.py --light -0.7 -0.7 --edge-pow 3.0
"""
from __future__ import annotations

import argparse
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

DEFAULT_SRC = r"D:\spine\meowa\split_base_skin\base_ref\base_parts_sheet_fix2.png"
DEFAULT_OUTDIR = r"D:\spine\meowa\refs\cel_style"
BG = (205, 205, 205, 255)          # 工作区约定：纯灰底 205
FONT = "C:/Windows/Fonts/msyh.ttc"

# Eva 拼图实测 bbox（python tools/cel_step_preview.py --bbox-report 可重新导出）
PART_BBOX = {
    "torso": (557, 901, 890, 1605),
    "leg": (439, 1676, 598, 2519),
    "arm": (148, 1011, 416, 1586),
}
PART_LABEL_CN = {"torso": "躯干", "leg": "腿部", "arm": "手臂"}


def cel_shade(rgba, steps, light=(-0.62, -0.78), edge_pow=3.0):
    """给单个部件叠加硬边分阶。steps=0 原样返回。"""
    if steps <= 0:
        return rgba.copy()
    out = rgba.copy()
    alpha = rgba[..., 3] > 40
    if not alpha.any():
        return out
    h, w = alpha.shape

    d = ndimage.distance_transform_edt(alpha)
    dn = d / max(float(d.max()), 1.0)

    ys, xs = np.mgrid[0:h, 0:w]
    cy = float(np.mean(np.nonzero(alpha)[0]))
    cx = float(np.mean(np.nonzero(alpha)[1]))
    vy, vx = ys - cy, xs - cx
    norm = np.hypot(vx, vy)
    norm[norm == 0] = 1.0

    L = np.asarray(light, dtype=np.float64)
    L = L / np.hypot(*L)
    dot = (vx / norm) * L[0] + (vy / norm) * L[1]   # +1 朝光 / -1 背光
    shadowness = np.clip(-dot, 0.0, 1.0)

    field = np.clip(1.0 - dn, 0.0, 1.0) ** edge_pow * shadowness
    field = np.where(alpha, field, 0.0)

    if steps == 1:
        mult = np.ones_like(field)
        mult[field > 0.24] = 0.86
    else:
        mult = np.ones_like(field)
        mult[field > 0.20] = 0.90
        mult[field > 0.48] = 0.78

    rgb = out[..., :3].astype(np.float64) * mult[..., None]
    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return out


def _fit(img, box_w, box_h):
    w, h = img.size
    s = min(box_w / w, box_h / h)
    return img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)


def _panel(src_rgba, bbox, steps, box_w, box_h, **kw):
    x0, y0, x1, y1 = bbox
    crop = cel_shade(src_rgba[y0:y1, x0:x1].copy(), steps, **kw)
    im = _fit(Image.fromarray(crop, "RGBA"), box_w, box_h)
    bg = Image.new("RGBA", (box_w, box_h), BG)
    bg.alpha_composite(im, ((box_w - im.width) // 2, (box_h - im.height) // 2))
    return bg.convert("RGB")


def build_grid(src_path, outdir, bbox_map=None, **kw):
    src = np.array(Image.open(src_path).convert("RGBA"))
    bbox_map = bbox_map or PART_BBOX
    os.makedirs(outdir, exist_ok=True)

    BOX_W, BOX_H, PAD, LABEL_W = 280, 520, 18, 132
    HEADER_H, TITLE_H, ROW_LABEL_H = 76, 58, 30
    cols = [("平涂 / 0 阶", 0), ("赛璐璐 1 阶", 1), ("赛璐璐 2 阶", 2)]
    rows = list(bbox_map.items())

    W = LABEL_W + len(cols) * (BOX_W + PAD) + PAD
    row_h = BOX_H + ROW_LABEL_H
    H = TITLE_H + HEADER_H + len(rows) * (row_h + PAD) + PAD
    canvas = Image.new("RGB", (W, H), (238, 238, 238))
    dr = ImageDraw.Draw(canvas)
    f_title = ImageFont.truetype(FONT, 30)
    f_head = ImageFont.truetype(FONT, 24)
    f_row = ImageFont.truetype(FONT, 22)

    dr.text((PAD, 14), "Eva 资产 · 平涂 vs 赛璐璐分阶对照（同一网格，仅改暗部阶数）",
            font=f_title, fill=(20, 20, 20))
    for ci, (name, _) in enumerate(cols):
        dr.text((LABEL_W + PAD + ci * (BOX_W + PAD) + 6, TITLE_H + 16), name,
                font=f_head, fill=(10, 10, 10))

    for ri, (key, bbox) in enumerate(rows):
        ry = TITLE_H + HEADER_H + ri * (row_h + PAD)
        dr.text((PAD, ry + ROW_LABEL_H + BOX_H // 2 - 12),
                PART_LABEL_CN.get(key, key), font=f_row, fill=(10, 10, 10))
        for ci, (_, steps) in enumerate(cols):
            p = _panel(src, bbox, steps, BOX_W, BOX_H, **kw)
            canvas.paste(p, (LABEL_W + PAD + ci * (BOX_W + PAD), ry + ROW_LABEL_H))

    grid = os.path.join(outdir, "eva_flat_vs_cel_1step_2step.png")
    canvas.save(grid)
    print("SAVED", grid, canvas.size)

    for key, bbox in rows:
        x0, y0, x1, y1 = bbox
        crop = cel_shade(src[y0:y1, x0:x1].copy(), 2, **kw)
        im = Image.fromarray(crop, "RGBA")
        bg = Image.new("RGBA", im.size, BG)
        bg.alpha_composite(im)
        f = os.path.join(outdir, f"eva_{key}_2step.png")
        bg.convert("RGB").save(f)
        print("SAVED", f, im.size)


def bbox_report(src_path, min_area=1500):
    """导出源图各连通部件的 bbox，便于填写 --bbox。"""
    a = np.array(Image.open(src_path).convert("RGBA"))
    lab, _ = ndimage.label(a[..., 3] > 40)
    rows = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        area = int((lab[sl] == i).sum())
        if area < min_area:
            continue
        rows.append((area, sl[1].start, sl[0].start, sl[1].stop, sl[0].stop))
    rows.sort(reverse=True)
    for area, x0, y0, x1, y1 in rows:
        print(f"area={area:8d}  bbox=({x0},{y0},{x1},{y1})  wh={x1-x0}x{y1-y0}")


def main():
    ap = argparse.ArgumentParser(description="平涂资产分阶预览生成器")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR)
    ap.add_argument("--light", nargs=2, type=float, default=[-0.62, -0.78],
                    metavar=("LX", "LY"), help="光方向（指向光源），默认左上")
    ap.add_argument("--edge-pow", type=float, default=3.0,
                    help="越大暗部越贴轮廓（覆盖面越小）")
    ap.add_argument("--bbox-report", action="store_true", help="只打印部件 bbox")
    args = ap.parse_args()

    if args.bbox_report:
        bbox_report(args.src)
        return
    build_grid(args.src, args.outdir, light=tuple(args.light), edge_pow=args.edge_pow)


if __name__ == "__main__":
    main()
