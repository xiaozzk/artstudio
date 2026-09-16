#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""outfit-split.py — 服装拆件拼图 → 独立服装部件贴图

把「万能编辑 / 生图」产出的**服装拆件拼图**（纯灰底 205）切成可换装的
独立部件 PNG：去灰底（边界 flood fill，不动白裙内部的灰阶阴影）→ 连通域 → 自动认件。

与 `slice-sheet.py` 的分工：那个认的是**人体部位**（torso / left_leg / 五官…，名字写死），
本工具认的是**服装件**（白裙上身 / 白裙摆 / 长筒袜 ×2 / 短靴 ×2），判据来自颜色与长宽比。

用法：
    python tools/outfit-split.py --sheet <拼图.png> --out <目录>
    python tools/outfit-split.py --sheet <拼图.png> --out <目录> --preview <预览.png>

输出去 <目录>：`<部件名>.png` × N + `outfit-manifest.json`（bbox / 尺寸 / 分类依据）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

# 裙摆回纹腰带的判据（暖棕色）
RUST = dict(r_min=90, r_minus_b=30, r_minus_g=20)
WHITE_MIN = 200          # 白裙的「白」下限（min 通道）
WHITE_SAT = 26           # 白裙的「灰」上限（max-min）


def load_rgba(path: Path) -> np.ndarray:
    im = Image.open(path)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return np.array(im)


def border_bg_color(a: np.ndarray) -> np.ndarray:
    """取四角与四边中点的中位色当背景色。"""
    h, w = a.shape[:2]
    pts = [a[0, 0], a[0, w - 1], a[h - 1, 0], a[h - 1, w - 1],
           a[0, w // 2], a[h - 1, w // 2], a[h // 2, 0], a[h // 2, w - 1]]
    return np.median(np.stack([p[:3].astype(np.float32) for p in pts]), axis=0)


def knockout_gray(a: np.ndarray, tol: float, ramp: float) -> tuple[np.ndarray, np.ndarray]:
    """边界 flood fill 去灰底，返回 (rgba, bg_mask)。只清与画布边界连通的灰，件内灰阶阴影保留。"""
    h, w = a.shape[:2]
    rgb = a[..., :3].astype(np.float32)
    bg = border_bg_color(a)
    dist = np.abs(rgb - bg).max(axis=2)

    bgish = dist <= tol
    lab, n = ndi.label(bgish, structure=np.ones((3, 3), bool))
    border_ids = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    border_ids.discard(0)
    bg_mask = np.isin(lab, list(border_ids)) if border_ids else np.zeros((h, w), bool)

    alpha = np.full((h, w), 255.0, np.float32)
    ring = ndi.binary_dilation(bg_mask, np.ones((3, 3), bool), iterations=2) & ~bg_mask
    alpha[ring] = np.clip((dist[ring] - tol) / max(ramp - tol, 1.0), 0.0, 1.0) * 255.0
    alpha[bg_mask] = 0.0

    out = a.copy()
    out[..., 3] = np.round(alpha).astype(np.uint8)
    out[bg_mask] = (0, 0, 0, 0)
    return out, bg_mask


def clean_alpha(rgba: np.ndarray, clean_alpha: int, junk_alpha: int) -> tuple[np.ndarray, int, int]:
    """与 slice-sheet.py 同口径：alpha ≤ clean 的像素连 RGB 一起清零；alpha ≤ junk 的极淡像素归零。"""
    a = rgba.copy()
    al = a[..., 3]
    cleaned = faint = 0
    if clean_alpha >= 0:
        m = al <= clean_alpha
        cleaned = int(m.sum())
        a[m] = (0, 0, 0, 0)
    if junk_alpha > 0:
        m = (a[..., 3] > 0) & (a[..., 3] <= junk_alpha)
        faint = int(m.sum())
        a[m] = (0, 0, 0, 0)
    return a, cleaned, faint


def audit(rgba: np.ndarray) -> dict:
    al = rgba[..., 3]
    rgb_nonzero = rgba[..., :3].any(axis=2)
    return dict(invisible=int(((al <= 16) & rgb_nonzero).sum()),
                faint=int(((al >= 1) & (al <= 8)).sum()))


def piece_stats(tile: np.ndarray, alpha_floor: int) -> dict:
    al = tile[..., 3]
    solid = al > alpha_floor
    n = int(solid.sum())
    r = tile[..., 0].astype(np.int32)[solid]
    g = tile[..., 1].astype(np.int32)[solid]
    b = tile[..., 2].astype(np.int32)[solid]
    mn = np.minimum(np.minimum(r, g), b)
    mx = np.maximum(np.maximum(r, g), b)
    white = int((((mn > WHITE_MIN) & ((mx - mn) < WHITE_SAT))).sum())
    rust = int(((r > RUST["r_min"]) & ((r - b) > RUST["r_minus_b"]) & ((r - g) > RUST["r_minus_g"])).sum())
    dark = int((mx < 130).sum())
    h, w = tile.shape[:2]
    return dict(pixels=n, white=white, rust=rust, dark=dark,
                white_frac=white / max(n, 1), rust_frac=rust / max(n, 1),
                dark_frac=dark / max(n, 1), w=w, h=h, aspect=h / max(w, 1))


def classify(st: dict) -> str:
    if st["rust_frac"] > 0.02:
        return "skirt"
    if st["white_frac"] > 0.30:
        return "bodice"
    if st["aspect"] >= 2.2 or st["dark_frac"] > 0.5 and st["aspect"] > 1.6:
        return "stocking"
    return "boot"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tol", type=float, default=18.0, help="灰底容差（默认 18）")
    ap.add_argument("--ramp", type=float, default=70.0, help="边缘 alpha 渐变的色差上限（默认 70）")
    ap.add_argument("--alpha-floor", type=int, default=8)
    ap.add_argument("--min-area", type=int, default=800, help="小于它的连通域当碎渣（默认 800）")
    ap.add_argument("--clean-alpha", type=int, default=1, help="alpha ≤ 它的像素连 RGB 一起清零（-1 = 关）")
    ap.add_argument("--junk-alpha", type=int, default=8, help="alpha ≤ 它的极淡像素归零（0 = 关）")
    ap.add_argument("--preview", default=None)
    args = ap.parse_args()

    sheet = Path(args.sheet)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    a = load_rgba(sheet)
    rgba, bg_mask = knockout_gray(a, args.tol, args.ramp)
    rgba, n_clean, n_faint = clean_alpha(rgba, args.clean_alpha, args.junk_alpha)
    print(f"sheet {sheet.name} {a.shape[1]}x{a.shape[0]}  bg color {border_bg_color(a)}  "
          f"bg px {int(bg_mask.sum())}  残色清零 {n_clean}  极淡归零 {n_faint}")

    solid = rgba[..., 3] > args.alpha_floor
    lab, n = ndi.label(solid, structure=np.ones((3, 3), bool))
    boxes = ndi.find_objects(lab)
    cand = []
    for i, sl in enumerate(boxes, 1):
        ys, xs = sl
        tile = rgba[ys, xs].copy()
        area = int((lab[sl] == i).sum())
        if area < args.min_area:
            continue
        st = piece_stats(tile, args.alpha_floor)
        kind = classify(st)
        cand.append(dict(kind=kind, tile=tile, area=area,
                         x0=int(xs.start), y0=int(ys.start), x1=int(xs.stop), y1=int(ys.stop),
                         cx=(xs.start + xs.stop) / 2, st=st))

    # 同类按 x 排序，命名 left / right（= 拼图里的左 / 右）
    groups: dict[str, list] = {}
    for c in cand:
        groups.setdefault(c["kind"], []).append(c)
    for kind, lst in groups.items():
        lst.sort(key=lambda c: c["cx"])

    names = {"skirt": ["dress_skirt"], "bodice": ["dress_bodice"],
             "stocking": ["stocking_left", "stocking_right"],
             "boot": ["boot_left", "boot_right"]}

    manifest = {"format": "spine-outfit-split", "version": 1, "sheet": sheet.name,
                "sheetSize": [a.shape[1], a.shape[0]], "bgColor": [float(v) for v in border_bg_color(a)],
                "knockout": {"tol": args.tol, "ramp": args.ramp, "alphaFloor": args.alpha_floor,
                             "minArea": args.min_area, "cleanAlpha": args.clean_alpha, "junkAlpha": args.junk_alpha},
                "audit": audit(rgba),
                "parts": {}, "written": [],
                "notes": ["left / right = 拼图画面里的左 / 右；同款左右为一对镜像，按需指派到角色左右肢。"]}

    print(f"检出 {len(cand)} 件：")
    for kind in ["bodice", "skirt", "stocking", "boot"]:
        lst = groups.get(kind, [])
        if not lst:
            print(f"  !! 缺件：{kind}")
            manifest["notes"].append(f"缺件：{kind}")
            continue
        for idx, c in enumerate(lst):
            nm = names[kind][idx] if idx < len(names[kind]) else f"{kind}_{idx + 1}"
            f = out_dir / f"{nm}.png"
            Image.fromarray(c["tile"]).save(f)
            manifest["parts"][nm] = {
                "file": f.name, "kind": kind,
                "sheetBBox": [c["x0"], c["y0"], c["x1"], c["y1"]],
                "w": c["st"]["w"], "h": c["st"]["h"], "pixels": c["st"]["pixels"],
                "whiteFrac": round(c["st"]["white_frac"], 3),
                "rustFrac": round(c["st"]["rust_frac"], 3),
                "darkFrac": round(c["st"]["dark_frac"], 3),
            }
            manifest["written"].append(f.name)
            print(f"  {nm:16s} {c['st']['w']:4d}x{c['st']['h']:<4d} px {c['st']['pixels']:7d} "
                  f"white {c['st']['white_frac']:.2f} rust {c['st']['rust_frac']:.2f} dark {c['st']['dark_frac']:.2f} "
                  f"@({c['x0']},{c['y0']})")

    (out_dir / "outfit-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), "utf8")

    if args.preview:
        prev = np.zeros_like(rgba)
        prev[..., :3] = 205
        prev[..., 3] = 255
        m = rgba[..., 3] > args.alpha_floor
        prev[m] = rgba[m]
        im = Image.fromarray(prev).convert("RGB")
        d = ImageDraw.Draw(im)
        for nm, p in manifest["parts"].items():
            x0, y0, x1, y1 = p["sheetBBox"]
            d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(220, 40, 40))
            d.text((x0 + 4, y0 + 4), nm, fill=(200, 30, 30))
        im.save(args.preview)
        print("preview ->", args.preview)

    print("manifest ->", out_dir / "outfit-manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
