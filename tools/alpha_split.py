#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alpha_split.py — 按 alpha(透明背景) 连通域把一张整图拆成多个部件。

思路: 让 AI 生成「整图 / 拆件图」(部件之间有间隙、背景透明或纯色),
      再用本工具纯算法拆件 —— 不依赖 AI 做语义分割, 也不需要把结果对齐回原图。

典型用法:

  # 1) AI 输出带透明背景 -> 直接拆
  python tools/alpha_split.py in.png -o out_dir

  # 2) AI 输出纯色背景(如 #cccccc) -> 先抠色再拆
  python tools/alpha_split.py in.png -o out_dir --bg auto --bg-tol 18

  # 3) 拆件图里线条有可能断开(头发高光/眉毛两笔) -> 形态学闭运算 + 间隙合并
  python tools/alpha_split.py in.png -o out_dir --close 2 --merge-gap 6

  # 4) 归一化到目标分辨率(整体内容高度 = 2048)
  python tools/alpha_split.py in.png -o out_dir --fit-height 2048

  # 5) 指定部件名(数量必须匹配, 否则报错并给出实际数量)
  python tools/alpha_split.py in.png -o out_dir --names hair,brow,eye,mouth,ear,head

输出:
  out_dir/parts/part_00_<name>.png      裁剪到 bbox 的部件
  out_dir/parts_full/part_00_<name>.png 与原画布同尺寸(Spine 导入自动对齐)
  out_dir/label_map.png                 彩色索引图(哪块是哪个部件)
  out_dir/preview.png                   标注了序号/名字的预览图
  out_dir/manifest.json                 每个部件的 bbox / 尺寸 / 面积 / 质心
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 基础工具

PALETTE = [
    (230, 85, 61), (61, 145, 230), (76, 175, 80), (255, 179, 0),
    (156, 39, 176), (0, 188, 212), (233, 30, 99), (121, 85, 72),
    (63, 81, 181), (139, 195, 74), (255, 87, 34), (0, 150, 136),
    (205, 220, 57), (96, 125, 139), (244, 67, 54), (33, 150, 243),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def font(size: int):
    """Pillow >= 10.1 的 load_default 支持指定字号(内置 Aileron, 仅 ASCII)。"""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - 老版本 Pillow
        return ImageFont.load_default()


def hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def load_rgba(path: Path) -> np.ndarray:
    im = Image.open(path)
    if im.mode in ("CMYK", "I;16", "F"):
        im = im.convert("RGB")
    return np.array(im.convert("RGBA"))


def detect_bg_color(rgba: np.ndarray) -> tuple[int, int, int]:
    """取图像四边框(2px)上不透明像素的中位色作为背景色。"""
    h, w = rgba.shape[:2]
    k = 2
    border = np.concatenate([
        rgba[0:k, :, :].reshape(-1, 4),
        rgba[h - k:h, :, :].reshape(-1, 4),
        rgba[:, 0:k, :].reshape(-1, 4),
        rgba[:, w - k:w, :].reshape(-1, 4),
    ])
    border = border[border[:, 3] > 128]
    if border.size == 0:
        return (255, 255, 255)
    med = np.median(border[:, :3], axis=0)
    return tuple(int(v) for v in med)  # type: ignore[return-value]


def key_out_background(rgba: np.ndarray, bg: tuple[int, int, int],
                       tol: float, edge_soft: int = 1) -> np.ndarray:
    """把与背景同色且**与画布边缘连通**的像素变透明(内部同色像素保留)。

    只删与边缘连通的背景，可以避免角色内部恰好同色的区域被误挖空。
    """
    out = rgba.copy()
    rgb = rgba[:, :, :3].astype(np.int32)
    dist = np.sqrt(((rgb - np.array(bg, dtype=np.int32)) ** 2).sum(axis=2))
    bgmask = (dist <= tol).astype(np.uint8)
    bgmask[rgba[:, :, 3] < 128] = 1  # 已透明的也算背景

    n, labels, stats, _ = cv2.connectedComponentsWithStats(bgmask, connectivity=4)
    h, w = bgmask.shape
    border_labels = set(np.unique(np.concatenate([
        labels[0, :], labels[h - 1, :], labels[:, 0], labels[:, w - 1],
    ])).tolist())
    border_labels.discard(0)
    kill = np.isin(labels, list(border_labels))
    out[kill, 3] = 0
    if edge_soft > 0 and kill.any():
        # 只在「贴着背景的边缘像素」上做 matte 渐变。
        # 渐变分母按前景连通域各自估计(该域内色距的 95 分位), 于是:
        #   - 实心块: 内部色距远超分母 -> 保持满不透明
        #   - 细线稿: 分母 ~= 线本身色距 -> 抗锯齿像素得到正确的半透明
        k = np.ones((3, 3), np.uint8)
        nb = cv2.dilate(kill.astype(np.uint8), k, iterations=edge_soft) > 0
        ramp = nb & ~kill
        if ramp.any():
            n2, lab2 = cv2.connectedComponents((~kill).astype(np.uint8), connectivity=8)
            fac = np.ones(dist.shape, np.float32)
            floor = max(1.0, tol * 1.6)
            for i in range(1, n2):
                m = (lab2 == i)
                if not m.any():
                    continue
                denom = max(float(np.percentile(dist[m], 95)), floor)
                fac[m] = np.clip(dist[m].astype(np.float32) / denom, 0.0, 1.0)
            out[ramp, 3] = (out[ramp, 3] * fac[ramp]).astype(np.uint8)
    return out


# ---------------------------------------------------------------- 连通域

def split_components(alpha: np.ndarray, close_px: int, min_area: int,
                     merge_gap: int, merge_contained: bool):
    """返回 (labels, stats_list, n_kept)。labels 已按合并结果重编号(1..n)。"""
    mask = (alpha > 8).astype(np.uint8)
    if close_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px * 2 + 1,) * 2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = []
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, 0]), int(stats[i, 1]),
                            int(stats[i, 2]), int(stats[i, 3]), int(stats[i, 4]))
        if area < min_area:
            continue
        comps.append(dict(old=i, bbox=(x, y, x + w, y + h), area=area,
                          centroid=(float(cents[i, 0]), float(cents[i, 1]))))

    if not comps:
        return None, []

    # ---- union-find 合并
    parent = list(range(len(comps)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    if merge_gap > 0:
        for i in range(len(comps)):
            ax0, ay0, ax1, ay1 = comps[i]["bbox"]
            for j in range(i + 1, len(comps)):
                bx0, by0, bx1, by1 = comps[j]["bbox"]
                dx = max(0, max(ax0, bx0) - min(ax1, bx1))
                dy = max(0, max(ay0, by0) - min(ay1, by1))
                if dx <= merge_gap and dy <= merge_gap:
                    union(i, j)

    if merge_contained:
        for i in range(len(comps)):
            ax0, ay0, ax1, ay1 = comps[i]["bbox"]
            for j in range(len(comps)):
                if i == j:
                    continue
                bx0, by0, bx1, by1 = comps[j]["bbox"]
                inside = (bx0 <= ax0 and by0 <= ay0 and ax1 <= bx1 and ay1 <= by1)
                if inside and comps[j]["area"] >= comps[i]["area"] * 4:
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(comps)):
        groups.setdefault(find(i), []).append(i)

    out_labels = np.zeros_like(labels)
    merged = []
    for gi, (_, members) in enumerate(sorted(
            groups.items(), key=lambda kv: min(comps[m]["bbox"][1] for m in kv[1]))):
        mask_i = np.isin(labels, [comps[m]["old"] for m in members])
        out_labels[mask_i] = gi + 1
        ys, xs = np.nonzero(mask_i)
        bb = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        merged.append(dict(
            index=gi,
            bbox=list(bb),
            size=[bb[2] - bb[0], bb[3] - bb[1]],
            area=int(mask_i.sum()),
            centroid=[float(xs.mean()), float(ys.mean())],
            merged_from=len(members),
        ))
    return out_labels, merged


def apply_regions(labels: np.ndarray, parts: list[dict],
                  regions: list[dict]) -> tuple[np.ndarray, list[dict]]:
    """按区域把多个连通域归并成一个部件。

    regions: [{"name": "eye", "bbox": [l, t, r, b]}, ...]
    规则: 连通域质心落在哪个 region 就归到哪个部件; 多个 region 命中时取面积最小的;
          未命中任何 region 的连通域各自独立成件。
    """
    regs = sorted(regions, key=lambda r: (r["bbox"][2] - r["bbox"][0]) *
                  (r["bbox"][3] - r["bbox"][1]))
    groups: dict[str, list[int]] = {}
    for p in parts:
        cx, cy = p["centroid"]
        name = None
        for r in regs:
            x0, y0, x1, y1 = r["bbox"]
            if x0 <= cx < x1 and y0 <= cy < y1:
                name = r["name"]
                break
        groups.setdefault(name or f"_{p['index']}", []).append(p["index"])

    out = np.zeros_like(labels)
    merged = []
    items = sorted(groups.items(),
                   key=lambda kv: min(next(p["bbox"][1] for p in parts
                                           if p["index"] == i) for i in kv[1]))
    for gi, (name, idxs) in enumerate(items):
        mask = np.isin(labels, [i + 1 for i in idxs])
        out[mask] = gi + 1
        ys, xs = np.nonzero(mask)
        bb = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        merged.append(dict(index=gi, name=name.lstrip("_"),
                           bbox=list(bb), size=[bb[2] - bb[0], bb[3] - bb[1]],
                           area=int(mask.sum()),
                           centroid=[round(float(xs.mean()), 2), round(float(ys.mean()), 2)],
                           merged_from=len(idxs),
                           from_region=not name.startswith("_")))
    return out, merged


# ---------------------------------------------------------------- 输出

def save_label_map(labels: np.ndarray, path: Path) -> None:
    h, w = labels.shape
    rgb = np.full((h, w, 3), 255, np.uint8)
    for i in range(1, int(labels.max()) + 1):
        rgb[labels == i] = PALETTE[(i - 1) % len(PALETTE)]
    Image.fromarray(rgb).save(path)


def save_preview(rgba: np.ndarray, parts: list[dict], path: Path,
                 scale_bar: bool = True) -> None:
    h, w = rgba.shape[:2]
    # 浅灰格背景, 便于看透明区域
    tile = 16
    yy, xx = np.mgrid[0:h, 0:w]
    checker = (((yy // tile) + (xx // tile)) % 2).astype(np.uint8)
    bg = np.where(checker[..., None] == 0, 236, 208).astype(np.uint8)
    bg = np.repeat(bg, 3, axis=2)
    a = (rgba[:, :, 3:4].astype(np.float32) / 255.0)
    comp = (rgba[:, :, :3].astype(np.float32) * a + bg.astype(np.float32) * (1 - a))
    im = Image.fromarray(comp.astype(np.uint8))
    d = ImageDraw.Draw(im)
    f = font(max(11, min(w, h) // 60))
    for p in parts:
        x0, y0, x1, y1 = p["bbox"]
        c = PALETTE[p["index"] % len(PALETTE)]
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=c, width=2)
        txt = f"{p['index']}:{p['name']}"
        tb = d.textbbox((0, 0), txt, font=f)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ly = max(0, y0 - th - 4)
        d.rectangle([x0, ly, x0 + tw + 6, ly + th + 4], fill=c)
        d.text((x0 + 3, ly + 1), txt, fill=(255, 255, 255), font=f)
    if scale_bar:
        f2 = font(max(12, min(w, h) // 48))
        d.rectangle([0, 0, w - 1, h - 1], outline=(120, 120, 120), width=1)
        d.text((6, h - 22), f"canvas {w}x{h}", fill=(60, 60, 60), font=f2)
    im.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="按 alpha 连通域把整图拆成部件(透明背景分割)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="输入图(PNG, 建议 RGBA)")
    ap.add_argument("-o", "--out-dir", type=Path, required=True)
    ap.add_argument("--bg", default=None,
                    help="背景色 keying: 'auto' 或 #RRGGBB; 默认 None=直接用 alpha")
    ap.add_argument("--bg-tol", type=float, default=18.0, help="背景色容差(欧氏距离)")
    ap.add_argument("--close", type=int, default=0, dest="close_px",
                    help="形态学闭运算半径(连接断开的线条/高光)")
    ap.add_argument("--min-area", type=int, default=24, help="最小连通域面积(去噪)")
    ap.add_argument("--merge-gap", type=int, default=0,
                    help="bbox 间距 <= N px 的连通域合并(同一部件的碎片)")
    ap.add_argument("--merge-contained", action="store_true",
                    help="把完全落在更大连通域 bbox 内的小块并入(如眼珠/高光)")
    ap.add_argument("--regions", type=Path, default=None,
                    help="区域归并 JSON: [{\"name\":\"eye\",\"bbox\":[l,t,r,b]}], "
                         "质心落在区域内的连通域合并为同一部件(双眼/双眉合成一件)")
    ap.add_argument("--names", default=None,
                    help="逗号分隔的部件名, 数量必须与拆出的部件数一致")
    ap.add_argument("--sort", choices=["reading", "area", "x", "y"], default="reading",
                    help="部件编号顺序, 默认 reading=自上而下、自左而右")
    ap.add_argument("--fit-height", type=int, default=None,
                    help="归一化: 缩放使整体内容高度 = N (保比例)")
    ap.add_argument("--fit-scale", type=float, default=None,
                    help="归一化: 直接指定缩放倍率")
    ap.add_argument("--no-full", action="store_true",
                    help="不输出与原画布同尺寸的 parts_full")
    ap.add_argument("--json-out", type=Path, default=None,
                    help="manifest 路径, 默认 <out-dir>/manifest.json")
    args = ap.parse_args()

    if not args.input.is_file():
        log(f"[ERROR] 输入文件不存在: {args.input}")
        return 2

    rgba = load_rgba(args.input)
    src_h, src_w = rgba.shape[:2]
    log(f"[i] 输入 {args.input.name}  {src_w}x{src_h}")

    if args.bg is not None:
        bg = detect_bg_color(rgba) if args.bg == "auto" else hex_to_rgb(args.bg)
        rgba = key_out_background(rgba, bg, args.bg_tol)
        log(f"[i] 背景 keying: rgb{bg} tol={args.bg_tol}")

    # ---- 归一化缩放(以「整体内容高度」为基准, 而不是画布高度)
    alpha0 = rgba[:, :, 3]
    ys, xs = np.nonzero(alpha0 > 8)
    if ys.size == 0:
        log("[ERROR] 图像全透明, 没有可拆的内容")
        return 3
    content = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    content_h = content[3] - content[1]
    log(f"[i] 内容 bbox {list(content)}  内容高度 {content_h}px")

    scale = 1.0
    if args.fit_height:
        scale = args.fit_height / content_h
    elif args.fit_scale:
        scale = args.fit_scale
    if abs(scale - 1.0) > 1e-9:
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4
        rgba = cv2.resize(rgba, (new_w, new_h), interpolation=interp)
        log(f"[i] 缩放 x{scale:.4f} -> {new_w}x{new_h}")

    h, w = rgba.shape[:2]
    labels, parts = split_components(rgba[:, :, 3], args.close_px, args.min_area,
                                     args.merge_gap, args.merge_contained)
    if labels is None:
        log("[ERROR] 没拆出任何连通域, 试试降低 --min-area 或加大 --close")
        return 4

    if args.regions:
        if not args.regions.is_file():
            log(f"[ERROR] regions 文件不存在: {args.regions}")
            return 6
        regions = json.loads(args.regions.read_text(encoding="utf-8"))
        if isinstance(regions, dict):
            regions = regions.get("regions", regions.get("parts", []))
        before = len(parts)
        labels, parts = apply_regions(labels, parts, regions)
        log(f"[i] 区域归并: {before} 个连通域 -> {len(parts)} 个部件 "
            f"({len(regions)} 个 region)")

    order = {"reading": lambda p: (p["bbox"][1], p["bbox"][0]),
             "area": lambda p: -p["area"],
             "x": lambda p: p["centroid"][0],
             "y": lambda p: p["centroid"][1]}[args.sort]
    parts.sort(key=order)

    names = [s.strip() for s in args.names.split(",") if s.strip()] if args.names else None
    given: dict[int, str] = {}
    if names:
        unnamed = [i for i, p in enumerate(parts) if not p.get("from_region")]
        if len(names) == len(parts):
            given = {i: n for i, n in enumerate(names)}          # 完整覆盖
        elif unnamed and len(names) == len(unnamed):
            given = {i: n for i, n in zip(unnamed, names)}        # 只补 region 没命名的
        else:
            log(f"[ERROR] --names 给了 {len(names)} 个; 实际 {len(parts)} 个部件"
                f"(其中 {len(unnamed)} 个未被 --regions 命名)")
            for p in parts:
                log(f"        #{p['index']:>2} {str(p['bbox']):<26} area={p['area']}")
            return 5

    out_dir: Path = args.out_dir
    (out_dir / "parts").mkdir(parents=True, exist_ok=True)
    if not args.no_full:
        (out_dir / "parts_full").mkdir(parents=True, exist_ok=True)

    rgba_img = Image.fromarray(rgba)
    table = []
    for i, p in enumerate(parts):
        name = given.get(p["index"]) or p.get("name") or f"part_{i:02d}"
        slug = f"{i:02d}_{name}"
        x0, y0, x1, y1 = p["bbox"]
        crop = rgba[y0:y1, x0:x1].copy()
        # 只保留本连通域(去掉同 bbox 内其它部件的像素)
        keep = (labels[y0:y1, x0:x1] == (p["index"] + 1))
        crop[:, :, 3] = np.where(keep, crop[:, :, 3], 0)
        Image.fromarray(crop).save(out_dir / "parts" / f"part_{slug}.png")
        if not args.no_full:
            full = np.zeros_like(rgba)
            full[y0:y1, x0:x1] = crop
            Image.fromarray(full).save(out_dir / "parts_full" / f"part_{slug}.png")
        rec = dict(index=i, name=name, bbox=p["bbox"], size=p["size"],
                   area=p["area"], centroid=[round(v, 2) for v in p["centroid"]],
                   merged_from=p["merged_from"],
                   file=f"parts/part_{slug}.png",
                   file_full=None if args.no_full else f"parts_full/part_{slug}.png")
        p["name"] = name
        p["index"] = i
        table.append(rec)

    save_label_map(labels, out_dir / "label_map.png")
    save_preview(rgba, parts, out_dir / "preview.png")

    manifest = dict(
        source=str(args.input), source_canvas=[src_w, src_h],
        canvas=[w, h], scale=round(scale, 6),
        content_bbox=list(content), part_count=len(table),
        params=dict(bg=args.bg, bg_tol=args.bg_tol, close=args.close_px,
                    min_area=args.min_area, merge_gap=args.merge_gap,
                    merge_contained=bool(args.merge_contained), sort=args.sort),
        parts=table,
    )
    json_path = args.json_out or (out_dir / "manifest.json")
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    # ---- 报表
    log("")
    log(f"{'#':>3} {'name':<12} {'bbox (L,T,R,B)':<24} {'size':<12} {'area':>8}")
    log("-" * 66)
    for r in table:
        log(f"{r['index']:>3} {r['name']:<12} "
            f"{str(r['bbox']):<24} {str(r['size']):<12} {r['area']:>8}")
    log("-" * 66)
    log(f"[OK] {len(table)} 个部件 -> {out_dir}")
    log(f"     parts/ parts_full/ label_map.png preview.png {json_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
