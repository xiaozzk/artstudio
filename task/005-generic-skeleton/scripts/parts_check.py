#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parts_check.py — 部件拆解表「组件数量」校验规则。

用途：拆解表生成后自动核对组件数是否等于预期（默认 23 件，005 包口径）。
      不一致就报 FAIL，并把缺件/多件位置指出来，供后续局部生成补件。

用法：
  python task/005-generic-skeleton/scripts/parts_check.py <拆解表.png> [--expect 23]
      [--grid 5x5] [--min-area 400] [--json 报告.json]

判定口径：
  - 前景 = alpha>16（已去背）；若整图不透明则退化为「与四角底色差 >10」
  - 组件 = 8 连通域；面积 < --min-area 的当作噪点/碎屑剔除
  - 格占用 = 每格前景像素 > 格面积 0.2%
退出码：0 = 数量一致；1 = 不一致。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def foreground(im: Image.Image) -> np.ndarray:
    a = np.asarray(im.convert("RGBA")).astype(np.int16)
    rgb, al = a[..., :3], a[..., 3]
    if (al < 16).mean() > 0.02:            # 有透明区 → 用 alpha
        return al > 16
    h, w = rgb.shape[:2]
    c = np.stack([rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]])
    return np.abs(rgb - c.mean(axis=0)).max(axis=-1) > 10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet", type=Path)
    ap.add_argument("--expect", type=int, default=23, help="预期组件数（默认 23）")
    ap.add_argument("--grid", default="5x5", help="排版行列，如 5x5")
    ap.add_argument("--min-area", type=int, default=400, help="组件最小面积（像素）")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()

    rows, cols = (int(v) for v in a.grid.lower().split("x"))
    im = Image.open(a.sheet)
    m = foreground(im)
    H, W = m.shape

    lab, n_raw = ndimage.label(m, structure=np.ones((3, 3), dtype=int))
    sizes = ndimage.sum(m, lab, range(1, n_raw + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= a.min_area]
    objs = ndimage.find_objects(lab)
    comps = []
    for i in keep:
        sl = objs[i - 1]
        comps.append({
            "area": int(sizes[i - 1]),
            "bbox": [int(sl[1].start), int(sl[0].start), int(sl[1].stop), int(sl[0].stop)],
            "center": [int((sl[1].start + sl[1].stop) / 2), int((sl[0].start + sl[0].stop) / 2)],
        })
    comps.sort(key=lambda c: (c["center"][1] // (H // rows), c["center"][0]))

    cell_h, cell_w = H / rows, W / cols
    occ = np.zeros((rows, cols), dtype=int)
    for r in range(rows):
        for c in range(cols):
            sub = m[int(r * cell_h):int((r + 1) * cell_h), int(c * cell_w):int((c + 1) * cell_w)]
            occ[r, c] = int(sub.sum())
    occupied = int((occ > cell_h * cell_w * 0.002).sum())

    print(f"[parts_check] {a.sheet.name}  {im.size[0]}x{im.size[1]}")
    print(f"  原始连通域 {n_raw} 个 → 剔除碎屑(<{a.min_area}px)后 **{len(comps)} 个组件**"
          f"（预期 {a.expect}）")
    print(f"  {rows}x{cols} 格占用：{occupied} 格有内容")
    print("  占用矩阵：")
    for r in range(rows):
        print("    " + " ".join("■" if occ[r, c] > cell_h * cell_w * 0.002 else "·" for c in range(cols)))
    print("  组件清单（按格序）：")
    for k, c in enumerate(comps, 1):
        print(f"    #{k:2d}  面积 {c['area']:7d}  bbox={c['bbox']}  中心={c['center']}")

    ok = len(comps) == a.expect
    print(f"  ⇒ {'PASS' if ok else 'FAIL'}：组件数 {len(comps)} vs 预期 {a.expect}")
    if a.json:
        a.json.write_text(json.dumps({
            "sheet": str(a.sheet), "size": list(im.size), "expect": a.expect,
            "components": comps, "occupied_cells": occupied, "pass": ok,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  报告 → {a.json}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
