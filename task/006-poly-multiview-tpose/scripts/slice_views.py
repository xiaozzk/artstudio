"""006 拼图切割：把一张 2×2 四方向拼图切成 front / left / right / back 四张单图。

口径（转身图专用，别改成各自贴边裁）：

- 拼图按 **2×2 等分**，格子名 `tl/tr/bl/br`；输出名与格子的映射由 `--map` 给（默认
  `front=tl,left=tr,right=bl,back=br`；**三视图**用 `front=tl,side=tr,back=bl` —— 右下空格自动跳过）；
- 每格各自求「非背景」bbox，再取**四格 bbox 的并集**（换算到格内局部坐标）作为**统一裁切窗口**；
  四张图裁**同一个窗口** → 四张尺寸一致、人物比例一致（各自贴边裁会破坏同比例）；
- 背景判定：透明（alpha 低）**或**接近四角底色（默认自动取整图四角中位色，灰底 205 场景容差 12）；
- **网格线剔除**：模型常顺手画出 2×2 分隔线，它是「贯穿全图」的细线，会被误判成前景并把每格 bbox
  撑满整格。故先剔除分隔线再求 bbox。判定**只在画布中线 ±`--band` px 内找**「整行/整列前景占比 >
  `--ratio`」的线（分隔线必在中线），**不能全图扫** —— 上下两格人物竖向对齐，躯干所在列在上下两格里
  都是前景，全图扫会把它当成竖线剔掉，人物身上会留缝（踩过）；
- 统一窗口再按 `--inset` 内缩，保证分隔线像素不进成品（窗口对四格一致 → 比例仍一致）。

用法（**工作区根**执行）：

    python task/006-poly-multiview-tpose/scripts/slice_views.py \
        --sheet task/006-poly-multiview-tpose/output/step2-multiview-tpose/<拼图>.png \
        --out-dir task/006-poly-multiview-tpose/output/views
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

NAMES = ("front", "left", "right", "back")
CELLS = {"tl": (0, 0), "tr": (1, 0), "bl": (0, 1), "br": (1, 1)}


def foreground_mask(img: Image.Image, tol: int) -> tuple[np.ndarray, np.ndarray]:
    """返回 (前景掩码, 底色 RGB)。前景 = 不透明且与四角底色差异超过 tol 的像素。"""
    arr = np.asarray(img.convert("RGBA")).astype(np.int16)
    rgb, alpha = arr[..., :3], arr[..., 3]
    corners = np.stack([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
    bg = np.median(corners, axis=0)
    diff = np.abs(rgb - bg).max(axis=2)
    return (diff > tol) & (alpha > 8), bg


def strip_grid_lines(
    mask: np.ndarray, ratio: float = 0.85, halo: int = 2, band: int = 32
) -> tuple[np.ndarray, list[int], list[int]]:
    """清掉 2×2 分隔线，返回 (新掩码, 线行, 线列)。

    只在中线 ±band px 内找线：分隔线必过中线；全图扫会把「上下两格都覆盖到的躯干列」误判成竖线。
    """
    h, w = mask.shape
    row_lo, row_hi = max(0, h // 2 - band), min(h, h // 2 + band)
    col_lo, col_hi = max(0, w // 2 - band), min(w, w // 2 + band)
    rows = [r for r in range(row_lo, row_hi) if mask[r].sum() / w > ratio]
    cols = [c for c in range(col_lo, col_hi) if mask[:, c].sum() / h > ratio]
    for r in rows:
        mask[max(0, r - halo): r + halo + 1, :] = False
    for c in cols:
        mask[:, max(0, c - halo): c + halo + 1] = False
    return mask, rows, cols


def bbox_of(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True, help="2×2 四方向拼图")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--pad", type=int, default=16, help="统一窗口外扩像素（默认 16）")
    ap.add_argument("--tol", type=int, default=12, help="底色容差（默认 12）")
    ap.add_argument("--no-trim", action="store_true", help="不裁统一窗口，直接出四等分格")
    ap.add_argument("--keep-grid", action="store_true", help="保留分隔线（不做网格线剔除）")
    ap.add_argument("--ratio", type=float, default=0.85, help="线判定：整行/整列前景占比阈值")
    ap.add_argument("--band", type=int, default=32, help="只在中线 ±band px 内找分隔线")
    ap.add_argument("--inset", type=int, default=3, help="统一窗口四边内缩像素（默认 3，挡分隔线）")
    ap.add_argument(
        "--map",
        default="front=tl,left=tr,right=bl,back=br",
        help="输出名=格子（tl/tr/bl/br），逗号分隔；三视图用 front=tl,side=tr,back=bl",
    )
    args = ap.parse_args()

    mapping: list[tuple[str, str]] = []
    for item in args.map.split(","):
        name, _, cell = item.partition("=")
        cell = cell.strip().lower()
        if cell not in CELLS:
            raise SystemExit(f"--map 里的格子必须是 tl/tr/bl/br，收到 {cell!r}")
        mapping.append((name.strip(), cell))

    sheet_path = Path(args.sheet).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sheet = Image.open(sheet_path)
    w, h = sheet.size
    cw, ch = w // 2, h // 2
    mask, bg = foreground_mask(sheet, args.tol)
    print(f"sheet {sheet_path.name} {sheet.size} {sheet.mode} bg={tuple(int(v) for v in bg)}")
    if not args.keep_grid:
        mask, rows, cols = strip_grid_lines(mask, ratio=args.ratio, band=args.band)
        print(f"grid lines stripped: rows={rows} cols={cols}")

    cells = {
        name: (CELLS[cell][0] * cw, CELLS[cell][1] * ch, CELLS[cell][0] * cw + cw, CELLS[cell][1] * ch + ch)
        for name, cell in mapping
    }

    boxes: dict[str, tuple[int, int, int, int]] = {}
    for name, (x0, y0, x1, y1) in cells.items():
        bb = bbox_of(mask[y0:y1, x0:x1])
        if bb is None:
            print(f"  [WARN] {name}: 格内没有前景像素")
            continue
        boxes[name] = bb
        print(f"  {name}: cell-local bbox {bb} -> {bb[2]-bb[0]}x{bb[3]-bb[1]}")

    if not boxes:
        raise SystemExit("映射的格子里都没检测到前景，拼图口径不对，先人工看图")

    if args.no_trim:
        win = (0, 0, cw, ch)
    else:
        x0 = min(b[0] for b in boxes.values())
        y0 = min(b[1] for b in boxes.values())
        x1 = max(b[2] for b in boxes.values())
        y1 = max(b[3] for b in boxes.values())
        x0, y0 = max(args.inset, x0 - args.pad), max(args.inset, y0 - args.pad)
        x1, y1 = min(cw - args.inset, x1 + args.pad), min(ch - args.inset, y1 + args.pad)
        win = (x0, y0, x1, y1)
        for name, b in boxes.items():
            if b[0] < x0 or b[1] < y0 or b[2] > x1 or b[3] > y1:
                print(f"  [WARN] {name}: bbox {b} 超出统一窗口 {win}，该方向会被裁到边")
    print(f"uniform window {win} -> {win[2]-win[0]}x{win[3]-win[1]}")

    for name, cell in mapping:
        if name not in boxes:
            print(f"  [SKIP] {name}: 空格，不产出")
            continue
        cx, cy = cells[name][0], cells[name][1]
        box = (cx + win[0], cy + win[1], cx + win[2], cy + win[3])
        out = sheet.crop(box)
        dst = out_dir / f"{name}.png"
        out.save(dst)
        print(f"  wrote {dst.name} {out.size} {out.mode}")


if __name__ == "__main__":
    main()
