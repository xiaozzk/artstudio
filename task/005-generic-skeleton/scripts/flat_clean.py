# -*- coding: utf-8 -*-
"""熵减少 / 平涂清理：把 AI 出图压成「干净平涂 + 清晰边界」，为切件做准备。

算法（确定性、零成本）——**按区域建调色板**，而不是按像素面积筛颜色：

1. 只保留最大前景连通域（清掉背景里的 alpha 碎点）。
2. 可选 mean-shift 预正则（`--sp/--sr`，默认关）。
3. **区域化**：把前景按 `--quant` 量化后取连通域；**面积 ≥ `--min-area` 的区域**，
   以其真实平均色作为调色板的一项。
   → 关键：小特征（眼睛、嘴、耳环）是**一个区域**，无论其内部有没有渐变都能整块保住；
   而抗锯齿过渡带是 1–2px 细条，区域面积不足 → 不进调色板，被吸附到邻居颜色。
4. 每个前景像素吸附到最近的调色板颜色 → 平涂区变纯色、边界变硬边。
5. 可选去杂点（`--min-px`）。

alpha 通道**保留原样**：外轮廓仍抗锯齿，内部色块是硬边界。

用法::

    python task/005-generic-skeleton/scripts/flat_clean.py <in.png> <out.png> \
        [--quant 12] [--min-area 80] [--sp 0] [--sr 0] [--min-px 0]

输出打印前后对照：颜色数 / 香农熵 / 色块数。
"""
import argparse

import cv2
import numpy as np
from PIL import Image


def load(path):
    return np.array(Image.open(path).convert("RGBA"))


def shannon(rgb, fg, quant=4):
    q = (rgb[fg] // quant) * quant
    _, c = np.unique(q.reshape(-1, 3), axis=0, return_counts=True)
    p = c / c.sum()
    return float(-(p * np.log2(p)).sum()), int(len(c))


def patch_count(rgb, fg, quant=16, min_frac=0.001):
    q = rgb[fg].astype(np.int32) // quant
    lab = np.zeros(rgb.shape[:2], np.int32) - 1
    lab[fg] = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
    thr = min_frac * fg.sum()
    total = 0
    for v in np.unique(lab[fg]):
        n, _, st, _ = cv2.connectedComponentsWithStats((lab == v).astype(np.uint8), 4)
        if n > 1:
            total += int((st[1:, 4] >= thr).sum())
    return total


def clean_alpha(a):
    fg = (a[..., 3] > 16).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg, 8)
    if n > 1:
        keep = lab == (1 + int(np.argmax(st[1:, 4])))
        a = a.copy()
        a[~keep, 3] = 0
    return a


def region_palette(rgb, fg, quant, min_area):
    """区域面积 >= min_area 的区域，各自取真实平均色 → 调色板。"""
    q = (rgb.astype(np.int32) // quant)
    key = q[..., 0] * 100000 + q[..., 1] * 1000 + q[..., 2]
    key = np.where(fg, key, -1)
    pal = []
    for v in np.unique(key[fg]):
        n, cc, st, _ = cv2.connectedComponentsWithStats((key == v).astype(np.uint8), 4)
        for i in range(1, n):
            if st[i, 4] < min_area:
                continue
            pal.append(rgb[cc == i].mean(axis=0))
    return np.round(np.array(pal)).astype(np.uint8)


def snap(rgb, fg, pal, chunk=40000):
    ys, xs = np.nonzero(fg)
    px = rgb[fg].astype(np.int32)
    p = pal.astype(np.int32)
    lab = np.empty(len(px), np.int32)
    for s in range(0, len(px), chunk):
        e = min(s + chunk, len(px))
        d = ((px[s:e, None, :] - p[None, :, :]) ** 2).sum(axis=2)
        lab[s:e] = d.argmin(axis=1)
    out = rgb.copy()
    out[ys, xs] = pal[lab].astype(np.uint8)
    return out


def despeckle(rgb, fg, min_px, quant=8):
    key = (rgb.astype(np.int32) // quant)
    key = np.where(fg, key[..., 0] * 100000 + key[..., 1] * 1000 + key[..., 2], -1)
    out = key.copy()
    for v in np.unique(key[fg]):
        n, cc, st, _ = cv2.connectedComponentsWithStats((key == v).astype(np.uint8), 4)
        for i in range(1, n):
            if st[i, 4] >= min_px:
                continue
            x, y, w, h = (int(t) for t in st[i, :4])
            y0, y1 = max(0, y - 2), min(key.shape[0], y + h + 2)
            x0, x1 = max(0, x - 2), min(key.shape[1], x + w + 2)
            patch, ccx = key[y0:y1, x0:x1], cc[y0:y1, x0:x1]
            nb = patch[(ccx != i) & (patch >= 0)]
            if nb.size == 0:
                continue
            vals, cnts = np.unique(nb, return_counts=True)
            sel = cc[y:y + h, x:x + w] == i
            out[y:y + h, x:x + w][sel] = vals[int(np.argmax(cnts))]
    res = rgb.copy()
    for v in np.unique(out[fg]):
        sel = out == v
        if sel.any():
            res[sel] = np.round(rgb[sel].mean(axis=0)).astype(np.uint8)
    return res


def main():
    ap = argparse.ArgumentParser(description="熵减少 / 平涂清理（按区域建调色板）")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--quant", type=int, default=12, help="区域量化级（默认 12，越小区域越细）")
    ap.add_argument("--min-area", type=int, default=80, help="区域最小面积（默认 80 像素）")
    ap.add_argument("--sp", type=float, default=0, help="mean-shift 空间半径（0 = 不做）")
    ap.add_argument("--sr", type=float, default=0, help="mean-shift 颜色半径（0 = 不做）")
    ap.add_argument("--min-px", type=int, default=0, help="去杂点阈值（0 = 不做）")
    ap.add_argument("--no-snap", action="store_true",
                    help="跳过区域调色板吸附，只做 mean-shift（最保守，小特征零风险）")
    args = ap.parse_args()

    a = clean_alpha(load(args.src))
    fg = a[..., 3] > 16
    rgb = a[..., :3].copy()

    h0, c0 = shannon(rgb, fg)
    p0 = patch_count(rgb, fg)

    work = rgb
    if args.sp > 0 and args.sr > 0:
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        work = cv2.cvtColor(cv2.pyrMeanShiftFiltering(bgr, args.sp, args.sr, maxLevel=1),
                            cv2.COLOR_BGR2RGB)
        work[~fg] = rgb[~fg]

    pal = np.zeros((0, 3), np.uint8)
    if args.no_snap:
        out = work.copy()
    else:
        pal = region_palette(work, fg, args.quant, args.min_area)
        out = snap(work, fg, pal)
    if args.min_px > 0:
        out = despeckle(out, fg, args.min_px)

    res = a.copy()
    res[..., :3] = out
    Image.fromarray(res).save(args.dst)

    h1, c1 = shannon(out, fg)
    p1 = patch_count(out, fg)
    print(f"{args.src} -> {args.dst}")
    print(f"  参数 quant={args.quant} min_area={args.min_area} sp={args.sp} sr={args.sr} "
          f"min_px={args.min_px}")
    print(f"  区域调色板 {len(pal)} 色")
    print(f"  颜色数 {c0} -> {c1}  ({100 * (c1 / c0 - 1):+.0f}%)")
    print(f"  香农熵 {h0:.2f} -> {h1:.2f} bit  ({100 * (h1 / h0 - 1):+.0f}%)")
    print(f"  色块数 {p0} -> {p1}  ({100 * (p1 / p0 - 1):+.0f}%)")


if __name__ == "__main__":
    main()
