#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flatbg_cut.py — 把"纯色底出图"的部件抠成透明件，并按参考部件缩放贴合。

**为什么走纯色底而不是让模型输出透明底**：实测 ZenMux 的图片编辑端点收到
`background=transparent` 会**被网关直接掐断连接**（RemoteDisconnected，不是 4xx）。
改成"纯色底出图 + 本地抠底"更稳，也更好验收：底越纯，alpha 越干净。

算法：
    1. 自动估底色 = 四边像素的中位数（也可 --bg-color RRGGBB 指定）
    2. alpha = 像素到底色的 RGB 距离做软阈值（--lo/--hi 可调），再轻微模糊
    3. **反混合去边（despill）**：观测色 = a·前景 + (1-a)·底色 ⇒ 前景 = (观测 - (1-a)·底色)/a
       —— 这一步是通用的，任何底色都能去掉边缘彩边
    4. `--fit-to 参考件.png`：按"参考件 alpha 最大 XY ↔ 生成件 alpha 最大 XY"求等比缩放比，
       缩放后**中心对齐参考件的 alpha 占位中心**，贴回参考件的画布尺寸
       —— 这样产出的附件可以直接顶替原附件，UV / 挂点都不用改（用户 2026-09-21 口径）

用法：
    python tools/flatbg_cut.py --in keyed.png --out part.png --fit-to assets/武僧/images_original/weapon_11.png
    python tools/flatbg_cut.py --in keyed.png --out part.png                 # 只抠底，不缩放
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
from PIL import Image, ImageFilter


def estimate_bg(rgb: np.ndarray, border: int = 4) -> np.ndarray:
    h, w, _ = rgb.shape
    b = max(1, min(border, h // 4, w // 4))
    edges = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                            rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    return np.median(edges, axis=0)


def key_out(rgb: np.ndarray, bg: np.ndarray, lo: float, hi: float) -> tuple:
    d = np.sqrt(((rgb.astype(np.float32) - bg) ** 2).sum(axis=2))
    a = np.clip((d - lo) / max(1e-6, hi - lo), 0, 1)
    af = a[..., None]
    fg = np.where(af > 0.02, (rgb.astype(np.float32) - (1 - af) * bg) / np.maximum(af, 0.02), rgb)
    return np.clip(fg, 0, 255).astype(np.uint8), (a * 255).astype(np.uint8)


def alpha_box(im: Image.Image, thr: int = 40):
    a = np.asarray(im.getchannel("A"))
    ys, xs = np.nonzero(a > thr)
    if len(xs) == 0:
        raise SystemExit("alpha 全空：底色估错或 --lo/--hi 不合适")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="纯色底抠件 + 按参考部件缩放贴合")
    ap.add_argument("--in", dest="src", required=True, help="纯色底出图")
    ap.add_argument("--out", required=True, help="输出透明件 PNG")
    ap.add_argument("--bg-color", default="auto", help="底色 RRGGBB 或 auto（默认取四边中位数）")
    ap.add_argument("--lo", type=float, default=60, help="距离下阈：≤ 此为全透明，默认 60")
    ap.add_argument("--hi", type=float, default=140, help="距离上阈：≥ 此为全不透明，默认 140")
    ap.add_argument("--feather", type=float, default=0.5, help="alpha 羽化半径，默认 0.5")
    ap.add_argument("--fit-to", default=None, help="参考部件 PNG：按 alpha 最大 XY 缩放贴合它的画布")
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args(argv)

    im = Image.open(a.src).convert("RGB")
    rgb = np.asarray(im)
    if a.bg_color == "auto":
        bg = estimate_bg(rgb)
    else:
        bg = np.array([int(a.bg_color[i:i + 2], 16) for i in (0, 2, 4)], float)
    fg, alpha = key_out(rgb, bg, a.lo, a.hi)
    cut = Image.fromarray(fg, "RGB").convert("RGBA")
    cut.putalpha(Image.fromarray(alpha, "L").filter(ImageFilter.GaussianBlur(a.feather)))
    print(f"输入 {im.size}  估计底色 RGB {bg.round(1).tolist()}  alpha 覆盖 "
          f"{(np.asarray(cut.getchannel('A')) > 40).mean() * 100:.1f}%")

    info = {"src": a.src, "size": list(im.size), "bg": [round(float(v), 1) for v in bg],
            "lo": a.lo, "hi": a.hi}
    nbox = alpha_box(cut)
    nw, nh = nbox[2] - nbox[0] + 1, nbox[3] - nbox[1] + 1
    info["new_max_xy"] = [nw, nh]
    info["new_box"] = list(nbox)

    if a.fit_to:
        ref = Image.open(a.fit_to).convert("RGBA")
        obox = alpha_box(ref)
        ow, oh = obox[2] - obox[0] + 1, obox[3] - obox[1] + 1
        kx, ky = ow / nw, oh / nh
        k = min(kx, ky)                                     # 等比，避免拉伸变形
        print(f"参考件 {os.path.basename(a.fit_to)} {ref.size} alpha maxXY={ow}x{oh} @{obox}")
        print(f"生成件 alpha maxXY={nw}x{nh} @{nbox} → 缩放 宽×{kx:.4f} / 高×{ky:.4f} → 等比×{k:.4f}")
        piece = cut.crop((nbox[0], nbox[1], nbox[2] + 1, nbox[3] + 1))
        piece = piece.resize((max(1, round(nw * k)), max(1, round(nh * k))), Image.LANCZOS)
        out = Image.new("RGBA", ref.size, (0, 0, 0, 0))
        ccx, ccy = (obox[0] + obox[2]) / 2, (obox[1] + obox[3]) / 2
        out.alpha_composite(piece, (int(round(ccx - piece.width / 2)), int(round(ccy - piece.height / 2))))
        info.update({"fit_to": a.fit_to, "ref_max_xy": [ow, oh], "ref_box": list(obox),
                     "scale_x": round(kx, 4), "scale_y": round(ky, 4), "scale_used": round(k, 4),
                     "out_size": list(out.size)})
    else:
        out = cut

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    out.save(a.out)
    print(f"输出 → {a.out}（{out.size[0]}x{out.size[1]} RGBA）")
    if a.json_out:
        json.dump(info, open(a.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"指标 → {a.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
