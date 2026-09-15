#!/usr/bin/env python3
"""给切件贴图补描边（默认内描边）—— 解决「同色部件叠在一起看不出轮廓」。

## 为什么需要它

拼图里切出来的**皮肤件**（脸型 / 躯干 / 四肢）在原画里就是没有线稿的纯色块：
把 `merged_sheet_FINAL.png` 的脸型区域放大看，整张脸是一个平涂色块，
**下颚线、脖子边界一个像素都没画**。切下来之后脸压在躯干的脖子/肩膀上，
两侧同色 → 边界彻底消失，成品就是个「没有下巴的脸」。

线稿并非不存在，只是只画在头发/五官上（实测该美术的线色核心 = `rgb(24,14,12)`）。
→ 给脸型补一条**和现有线稿同色**的描边，下颚线就回来了。

## 关键约束（为什么只改 RGB）

**alpha 一个字节都不动。** 于是：

* 贴图尺寸不变 → 项目里部件记的 `image.width/height`、`pivot`、部位 bbox、裁剪框全都不用改；
* 轮廓位置不变 → 描边不会越出部位框，导出的「越界校验」照样 0 溢出；
* 「裁剪只遮挡不改原图」的约定不受影响 —— 这是另一件事，别混。

描边权重来自**到轮廓的有符号距离**：

    轮廓内侧 width 像素 → 线色；再往里 soft 像素线性淡出（抗锯齿）
    轮廓外的半透明抗锯齿像素 → 也拉成线色
      （不这么做最外一圈会留一条**亮边**，缩放到图集里就显成灰边，正是切件阶段费劲清掉的东西）

## 幂等

写回时在 PNG 里打一个 tEXt 标记 `SpineOutline=<参数 JSON>`：

* 同参数重跑 → 跳过（不会越描越黑）；
* 参数变了 → 报错，要显式 `--force`；
* 想彻底还原 → 重跑 `python tools/slice-sheet.py`（切件是确定性的，输出可复现）。

## 用法

    # 按配置批量（切件后跑一遍即可复现）
    python tools/outline-part.py --config assets/eva_bone/parts/outline.json --project human_female

    # 单件、临时改参数
    python tools/outline-part.py head_base --width 2.5 --color "#241a17" --project human_female

    # 只出对照图（原图 | 描边），不落盘
    python tools/outline-part.py head_base --preview tmp/head_base_outline.png --width 1.5,2,2.5

    # 体检模式：报告会改多少，不写
    python tools/outline-part.py --config assets/eva_bone/parts/outline.json --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARTS_DIR = ROOT / 'assets' / 'eva_bone' / 'parts'
LAB_PROJECTS = ROOT / 'tools' / 'dressup-lab' / 'projects'
MARKER = 'SpineOutline'

DEFAULTS = {'width': 2.0, 'color': '#241a17', 'soft': 1.0}
# 透明阈值：alpha ≤ 1.5/255 的像素涂了也看不见，反而会把图集的透明区染色（bleed 时会渗出来）
INVISIBLE = 1.5 / 255.0


# ---------------------------------------------------------------- 基础

def hex_to_rgb(s: str) -> tuple:
    t = str(s).strip().lstrip('#')
    if len(t) == 3:
        t = ''.join(c * 2 for c in t)
    if len(t) != 6:
        raise ValueError(f'颜色要写成 #RRGGBB：{s!r}')
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def parse_params(cfg: dict = None, *, width=None, color=None, soft=None) -> dict:
    """默认值 ← 配置段 ← 命令行，逐层覆盖"""
    p = dict(DEFAULTS)
    for src in (cfg or {},):
        for k in DEFAULTS:
            if src.get(k) is not None:
                p[k] = src[k]
    if width is not None:
        p['width'] = width
    if color is not None:
        p['color'] = color
    if soft is not None:
        p['soft'] = soft
    p['width'] = float(p['width'])
    p['soft'] = float(p['soft'])
    p['color'] = '#%02x%02x%02x' % hex_to_rgb(p['color'])
    return p


def read_marker(path: Path) -> dict | None:
    """读回上次描边的参数（没打过标记返回 None）"""
    try:
        with Image.open(path) as im:
            raw = (getattr(im, 'text', None) or {}).get(MARKER)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return {'raw': raw}


def save_png(path: Path, arr: np.ndarray, params: dict) -> None:
    info = PngInfo()
    info.add_text(MARKER, json.dumps(params, ensure_ascii=False, separators=(',', ':')))
    Image.fromarray(arr, 'RGBA').save(path, 'PNG', optimize=True, pnginfo=info)


# ---------------------------------------------------------------- 描边

def stroke_weight(alpha: np.ndarray, width: float, soft: float) -> np.ndarray:
    """权重场 ∈ [0,1]：轮廓内侧 `width` px → 1，再往内 `soft` px 线性淡出。"""
    a = alpha.astype(np.float32) / 255.0
    inside = a >= 0.5
    if not inside.any():
        return np.zeros(a.shape, np.float32)
    d_in = ndimage.distance_transform_edt(inside)      # 内部像素 → 最近外部像素的距离
    d_out = ndimage.distance_transform_edt(~inside)    # 外部像素 → 最近内部像素的距离
    signed = np.where(inside, d_in - 0.5, -(d_out - 0.5))   # 近似有符号距离，轮廓处 ≈ 0
    w = np.clip((width - signed) / max(float(soft), 1e-6), 0.0, 1.0)
    w[a <= INVISIBLE] = 0.0
    return w.astype(np.float32)


def apply_outline(arr: np.ndarray, params: dict):
    """返回 (新图, 权重场, 统计)。alpha 原样保留。"""
    w = stroke_weight(arr[..., 3], params['width'], params['soft'])
    color = np.array(hex_to_rgb(params['color']), np.float32)
    rgb = arr[..., :3].astype(np.float32)
    mixed = rgb * (1.0 - w[..., None]) + color * w[..., None]
    out = arr.copy()
    out[..., :3] = np.clip(np.rint(mixed), 0, 255).astype(np.uint8)
    delta = np.abs(out[..., :3].astype(np.int16) - arr[..., :3].astype(np.int16))
    stat = {
        'strokePixels': int((w > 0.5).sum()),
        'touchedPixels': int((w > 0).sum()),
        'alphaChanged': int((out[..., 3] != arr[..., 3]).sum()),
        'maxRgbDelta': int(delta.max()) if delta.size else 0,
        'meanRgbDeltaOnTouched': round(float(delta.max(axis=2)[w > 0].mean()), 2) if (w > 0).any() else 0.0,
    }
    return out, w, stat


# ---------------------------------------------------------------- 预览

def compose(arr: np.ndarray, bg=(90, 90, 90)) -> Image.Image:
    im = Image.fromarray(arr, 'RGBA')
    plate = Image.new('RGBA', im.size, tuple(bg) + (255,))
    plate.alpha_composite(im)
    return plate.convert('RGB')


def write_preview(path: Path, arr: np.ndarray, variants: list, scale: int = 3) -> None:
    """一条横向对照图：原图 | 各参数档，中灰底（透明区才看得见边界）"""
    tiles = [(f'原图 {arr.shape[1]}x{arr.shape[0]}', compose(arr))]
    for params in variants:
        out, _, stat = apply_outline(arr, params)
        label = f"w={params['width']:g} {params['color']}"
        tiles.append((label, compose(out)))
    pad, top = 8, 22
    w = sum(t.width for _, t in tiles) + pad * (len(tiles) + 1)
    h = max(t.height for _, t in tiles) + pad * 2 + top
    sheet = Image.new('RGB', (w, h), (32, 34, 40))
    x = pad
    for label, tile in tiles:
        sheet.paste(tile, (x, pad + top))
        x += tile.width + pad
    sheet = sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    print(f'对照图 → {path}  ({sheet.width}x{sheet.height})')
    for label, _ in tiles:
        print(f'   · {label}')


# ---------------------------------------------------------------- 主流程

def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text('utf8'))
    parts = cfg.get('parts') or {}
    if isinstance(parts, list):                     # 允许 ["head_base", ...] 简写
        parts = {str(k): {} for k in parts}
    return {'default': cfg.get('default') or {}, 'parts': parts}


def targets_from(parts_dir: Path, args, cfg) -> list:
    names = list(args.parts)
    if args.config:
        names += [k for k in cfg['parts'] if k not in names]
    if args.all:
        names += [p.stem for p in sorted(parts_dir.glob('*.png')) if p.stem not in names]
    if not names:
        sys.exit('没有指定部件：给个名字、--config 或 --all')
    out = []
    for n in names:
        src = parts_dir / f'{n}.png'
        if not src.exists():
            print(f'  ! 跳过 {n}：找不到 {src}')
            continue
        entry = cfg['parts'].get(n) if args.config else None
        out.append((n, src, parse_params(entry, width=args.width, color=args.color, soft=args.soft)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description='给切件贴图补描边（内描边，只改 RGB）')
    ap.add_argument('parts', nargs='*', help='部件名（不含 .png），可多个')
    ap.add_argument('--config', help='描边配置 JSON（列出哪些部件 + 参数）')
    ap.add_argument('--all', action='store_true', help='对 --config 里列的全部部件执行（+ 位置参数）')
    ap.add_argument('--parts-dir', default=str(DEFAULT_PARTS_DIR), help='切件目录')
    ap.add_argument('--width', help='描边宽度 px（预览时可写 1.5,2,2.5 出多档对照）')
    ap.add_argument('--color', help='线色 #RRGGBB（默认取该美术线稿色 #241a17）')
    ap.add_argument('--soft', type=float, help='内侧抗锯齿淡出宽度 px（默认 1）')
    ap.add_argument('--project', help='同时覆盖到该项目 images/ 下的同名贴图（默认只写切件目录）')
    ap.add_argument('--preview', help='只出对照图到该路径，不落盘')
    ap.add_argument('--check', action='store_true', help='只报告不写')
    ap.add_argument('--force', action='store_true', help='已有标记且参数不同时，仍然重描')
    args = ap.parse_args()

    parts_dir = Path(args.parts_dir)
    cfg = load_config(Path(args.config)) if args.config else {'default': {}, 'parts': {}}

    # 预览：--width 支持逗号多档
    if args.preview:
        if not args.parts:
            sys.exit('--preview 需要指定部件名')
        src = parts_dir / f'{args.parts[0]}.png'
        arr = np.array(Image.open(src).convert('RGBA'))
        widths = [float(x) for x in str(args.width or DEFAULTS['width']).split(',') if x.strip()]
        base = parse_params(cfg['parts'].get(args.parts[0]), color=args.color, soft=args.soft)
        variants = [dict(base, width=w) for w in widths]
        write_preview(Path(args.preview), arr, variants)
        return 0

    width = float(str(args.width).split(',')[0]) if args.width else None
    targets = targets_from(parts_dir, args, cfg)
    if not targets:
        sys.exit('没有可处理的部件')

    rc = 0
    for name, src, params in targets:
        prev = read_marker(src)
        if prev and not args.force:
            if all(prev.get(k) == params.get(k) for k in ('width', 'color', 'soft')):
                print(f'= {name}: 已按 {params["width"]:g}px {params["color"]} 描过（跳过）')
                continue
            print(f'! {name}: 已描过（{prev.get("width")}px {prev.get("color")}），'
                  f'现在要 {params["width"]:g}px {params["color"]} → 需要 --force')
            rc = 1
            continue

        before = np.array(Image.open(src).convert('RGBA'))
        after, _, stat = apply_outline(before, params)
        flag = '' if stat['alphaChanged'] == 0 else f'  !! alpha 变了 {stat["alphaChanged"]} px'
        print(f'* {name}: {before.shape[1]}x{before.shape[0]}  描边 {stat["strokePixels"]} px  '
              f'最大 RGB 变化 {stat["maxRgbDelta"]}  触及区均值 {stat["meanRgbDeltaOnTouched"]}{flag}')
        if stat['alphaChanged']:
            print('  !! alpha 不应改变，已中止')
            rc = 1
            continue
        if args.check:
            continue
        save_png(src, after, params)
        print(f'  → 写回 {src.relative_to(ROOT)}')
        if args.project:
            dst = LAB_PROJECTS / args.project / 'images' / f'{name}.png'
            if dst.exists():
                dst.write_bytes(src.read_bytes())
                print(f'  → 覆盖 {dst.relative_to(ROOT)}')
            else:
                print(f'  · 项目里没有同名贴图，跳过：{dst.relative_to(ROOT)}')
        rc = rc or 0
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
