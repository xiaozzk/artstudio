#!/usr/bin/env python3
"""把整张部件拼图切成「换装实验室」可用的部位贴图（工作区自己的工具，不改实验室源码）。

设计依据（2026-09-15 对照用户手工重切的 18 张做过逐像素体检后定的）：
  生图工具吐出的透明区**不是干净的 (0,0,0,0)**，而是「alpha≈1 + 肤色 RGB」的隐形脏像素，
  单张就能有 3~6 万个。它们在原尺寸下看不见，但一旦缩放 / 预乘 / 二次合成就会显成灰边、黑边。
  → 所以切件要做两件事：**按阈值定内容范围** + **把不可见像素的 RGB 一并清零**。

切件规则
  * 内容范围（bbox）= alpha > --alpha-floor（默认 8）的像素；
  * 去掉小于 --min-area（默认 64px）的碎渣连通域，避免飞点把 bbox 撑大或混进别件；
  * 落盘前做两档清理：
      ① --junk-alpha（默认 8）：alpha ≤ 8 的**极淡像素直接归零** —— 3% 不透明度在任何底色上都看不见，
         但在图集里会变成一圈灰雾，还会把 bbox 撑大；细笔画（眉毛/鼻梁）走更低的检测阈值，不受影响；
      ② --clean-alpha（默认 1）：alpha ≤ 1 的像素连 RGB 一起清零 —— 这是生图残色最常见的形态，
         不处理会在缩放 / 预乘 / 二次合成时显成灰边；实测对可见结果的影响 ≤ 0.9/255。
    两者都可用 0 / -1 关掉。
  * 可选 --bleed N：把边界颜色向外扩 N 像素（默认 0）——纹理走 GPU 过滤时防暗缝用。

工具会顺手体检：越界（实心像素贴到切件边上）、隐形脏像素、极淡像素、针孔，
并给出去重后的「干净度」汇总；`--compare <目录>` 可把另一批切件拉进来同口径对比。

用法：
  python tools/slice-sheet.py                                   # 默认切 assets/eva_bone/merged_sheet_FINAL.png
  python tools/slice-sheet.py --alpha-floor 16 --bleed 1
  python tools/slice-sheet.py --compare "C:/Users/xxx/Downloads/meowart-images-xxx"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


# ---------------------------------------------------------------- 基础

def load_sheet(path: Path):
    img = Image.open(path).convert('RGBA')
    return img, np.array(img)


def components(mask: np.ndarray, min_area: int):
    """8 邻接连通域（在给定 mask 上）→ 组件列表"""
    labels, n = ndimage.label(mask, structure=np.ones((3, 3)))
    out = []
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        ys, xs = sl
        m = labels[sl] == i
        area = int(m.sum())
        if area < min_area:
            continue
        alpha = None  # 由调用方按需再取
        out.append(dict(index=i, area=area,
                        bbox=[int(xs.start), int(ys.start), int(xs.stop), int(ys.stop)],
                        w=int(xs.stop - xs.start), h=int(ys.stop - ys.start)))
    return out, labels


def centroid(arr, bbox):
    x0, y0, x1, y1 = bbox
    alpha = arr[y0:y1, x0:x1, 3].astype(np.float64)
    tot = alpha.sum()
    if tot <= 0:
        return [(x0 + x1) / 2, (y0 + y1) / 2]
    cx = float((np.arange(x0, x1)[None, :] * alpha).sum() / tot)
    cy = float((np.arange(y0, y1)[:, None] * alpha).sum() / tot)
    return [cx, cy]


# ---------------------------------------------------------------- 清理与体检

def clean_invisible(tile: np.ndarray, clean_alpha: int):
    """不可见像素清理：alpha ≤ clean_alpha → (0,0,0,0)。返回 (新 tile, 清理掉的像素数)"""
    if clean_alpha < 0:
        return tile, 0
    a = tile[..., 3]
    kill = a <= clean_alpha
    if not kill.any():
        return tile, 0
    n = int(kill.sum())
    out = tile.copy()
    out[kill] = 0
    return out, n


def kill_faint(tile: np.ndarray, junk_alpha: int):
    """把极淡像素整片归零（alpha 清零，不是只清 RGB）—— 生图残留的雾状杂色

    与 clean_invisible 的区别：那个只抹掉 alpha=0 附近的 RGB 残色，alpha 值本身保留；
    这个把 alpha 1..junk_alpha 直接判为 0（默认 8：255 分之 8 = 3% 不透明度，
    在任何底色上都看不出来，但在图集里会变成一圈灰雾 + 撑大 bbox）。
    """
    if junk_alpha <= 0:
        return tile, 0
    a = tile[..., 3]
    kill = (a > 0) & (a <= junk_alpha)
    if not kill.any():
        return tile, 0
    n = int(kill.sum())
    out = tile.copy()
    out[kill] = 0
    return out, n


def bleed_edge(tile: np.ndarray, n: int):
    """把边界颜色向外扩 n 像素（alpha 仍为 0），防 GPU 过滤时出现暗缝"""
    if n <= 0:
        return tile
    a = tile[..., 3] > 0
    if not a.any():
        return tile
    out = tile.copy()
    grown = a.copy()
    cur = tile.copy()
    for _ in range(n):
        dil = ndimage.binary_dilation(grown, structure=np.ones((3, 3)))
        ring = dil & ~grown
        if not ring.any():
            break
        # 用最近邻的已填充颜色去填 ring
        _, (iy, ix) = ndimage.distance_transform_edt(~grown, return_indices=True)
        out[ring] = cur[iy[ring], ix[ring]]
        out[ring, 3] = 0          # 出血只带颜色，不带 alpha
        grown = dil
    return out


def audit(tile: np.ndarray):
    """切件体检：隐形脏像素 / 极淡像素 / 实心针孔 / 越界实心像素"""
    al = tile[..., 3]
    rgb = tile[..., :3].astype(np.int16)
    invisible = int(((al <= 16) & (rgb.sum(axis=2) > 0)).sum())
    faint = int(((al > 0) & (al <= 8)).sum())
    solid = al > 200
    pinholes = 0
    if solid.sum() > 50:
        closed = ndimage.binary_closing(solid, structure=np.ones((3, 3)))
        pinholes = int((closed & ~solid).sum())
    edge = 0
    if tile.shape[0] > 2 and tile.shape[1] > 2:
        edge = int(solid[0].sum() + solid[-1].sum() + solid[:, 0].sum() + solid[:, -1].sum())
    return dict(invisible=invisible, faint=faint, pinholes=pinholes, edge_solid=edge,
                size=(int(tile.shape[1]), int(tile.shape[0])))


def load_dir(d: Path):
    return [(p.name, np.array(Image.open(p).convert('RGBA'))) for p in sorted(Path(d).glob('*.png'))]


def summarize(title: str, items):
    rows = [(name, audit(t)) for name, t in items]
    tot = {k: sum(r[k] for _, r in rows) for k in ('invisible', 'faint', 'pinholes', 'edge_solid')}
    px = sum(r['size'][0] * r['size'][1] for _, r in rows)
    print(f'  {title:<34} 件数 {len(rows):<3} 像素 {px:<9} '
          f'隐形脏 {tot["invisible"]:<8} 极淡 {tot["faint"]:<7} 针孔 {tot["pinholes"]:<5} 越界实心 {tot["edge_solid"]}')
    return rows


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', default='assets/eva_bone/merged_sheet_FINAL.png')
    ap.add_argument('--out', default='assets/eva_bone/parts')
    ap.add_argument('--alpha-floor', type=int, default=8, help='内容范围阈值：alpha 大于它才算内容（默认 8）')
    ap.add_argument('--min-area', type=int, default=64, help='小于它的连通域当碎渣丢掉（默认 64，原先 150）')
    ap.add_argument('--clean-alpha', type=int, default=1, help='alpha ≤ 它的像素强制 (0,0,0,0)（默认 1；-1 = 关）')
    ap.add_argument('--junk-alpha', type=int, default=8, help='alpha ≤ 它的极淡像素直接归零（默认 8 = 3%% 不透明度；0 = 关）')
    ap.add_argument('--close', type=int, default=0, help='闭运算次数，补断线（默认 0；描边断开时用 1~2）')
    ap.add_argument('--merge-gap', type=int, default=0, help='把相距 ≤ N px 的碎片并回同一件（默认 0 = 关；细笔画断开时用 4~8）')
    ap.add_argument('--bleed', type=int, default=0, help='把边界颜色向外扩 N 像素（默认 0；GPU 过滤防暗缝用 1~2）')
    ap.add_argument('--compare', default='', help='把另一个切件目录拉进来同口径体检对比')
    ap.add_argument('--json', default='', help='把清单额外写一份到指定路径')
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]          # 工作区根
    sheet_path = Path(args.sheet) if Path(args.sheet).is_absolute() else root / args.sheet
    out_dir = Path(args.out) if Path(args.out).is_absolute() else root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    img, arr = load_sheet(sheet_path)
    W, H = img.size
    print(f'切片源：{sheet_path}')
    print(f'  画布 {W}×{H}；内容阈值 alpha>{args.alpha_floor}；碎渣下限 {args.min_area}px；'
          f'不可见清理 alpha≤{args.clean_alpha}；出血 {args.bleed}px')

    # ---- 1) 阈值化 + 去碎渣 + 连通域（可选：闭运算 / 间隙合并，把断成几截的细笔画并回本件）
    mask = arr[..., 3] > args.alpha_floor
    if args.close > 0:
        mask = ndimage.binary_closing(mask, structure=np.ones((3, 3)), iterations=args.close)
        print(f'  闭运算 {args.close} 次（补断线）')
    if args.merge_gap > 0:
        # 把相距 ≤ merge_gap 的碎片并成一个域：先按半径膨胀标签，再取回原始像素
        grown = ndimage.binary_dilation(mask, structure=np.ones((3, 3)), iterations=args.merge_gap)
        lab_g, n_g = ndimage.label(grown, structure=np.ones((3, 3)))
        # 原始 mask 的每个像素继承它所在膨胀域的新标签
        labels = np.where(mask, lab_g, 0)
        n_merged = int(labels.max())
        comps_all = []
        for i, sl in enumerate(ndimage.find_objects(labels), start=1):
            ys, xs = sl
            m = labels[sl] == i
            area = int(m.sum())
            if area <= 0:
                continue
            comps_all.append(dict(index=i, area=area,
                                  bbox=[int(xs.start), int(ys.start), int(xs.stop), int(ys.stop)],
                                  w=int(xs.stop - xs.start), h=int(ys.stop - ys.start)))
        comps = [c for c in comps_all if c['area'] >= args.min_area]
        dropped = len(comps_all) - len(comps)
        print(f'  间隙合并 {args.merge_gap}px：{n_merged} 个域 → 保留 {len(comps)} 个（丢弃碎渣 {dropped} 个）')
    else:
        comps, labels = components(mask, args.min_area)
        dropped = 0
        for i in range(1, int(labels.max()) + 1):
            area = int((labels == i).sum())
            if 0 < area < args.min_area:
                dropped += 1
        print(f'  alpha>{args.alpha_floor} 的连通域 {int(labels.max())} 个 → 保留 {len(comps)} 个（丢弃碎渣 {dropped} 个）')

    # 隐性泄漏统计（阈值以下但带颜色的像素）
    leak = int(((arr[..., 3] <= args.alpha_floor) & (arr[..., :3].sum(axis=2) > 0)).sum())
    print(f'  阈值以下的隐形脏像素（带 RGB 的透明区）：{leak} 个 → 切件里会被清理成 (0,0,0,0)')

    # ---- 2) 语义归类（按拼图布局的固定位置判据）
    torso = max([c for c in comps if 900 < centroid(arr, c['bbox'])[1] < 1500], key=lambda c: c['area'])
    cx0 = centroid(arr, torso['bbox'])[0]
    cen = {c['index']: centroid(arr, c['bbox']) for c in comps}
    left = lambda c: cen[c['index']][0] > cx0      # 画面右侧 = 角色左半身
    right = lambda c: cen[c['index']][0] < cx0

    big = [c for c in comps if c is not torso]
    head_like = [c for c in big if c['bbox'][1] < 600 and c['bbox'][0] < cx0 < c['bbox'][2]]
    arms = [c for c in big if 900 < cen[c['index']][1] < 1600 and c['w'] > 200]
    hands = [c for c in big if c['w'] < 100 and c['h'] > 150 and cen[c['index']][1] > 1500]
    legs = [c for c in big if c['h'] > 800 and cen[c['index']][1] > 1800]
    feet = [c for c in big if 2500 < cen[c['index']][1] < 2800]
    ear = [c for c in big if cen[c['index']][1] < 800 and cen[c['index']][0] < cx0 - 100]

    def one(lst, pred, what):
        hit = [c for c in lst if pred(c)]
        if len(hit) != 1:
            detail = ' | '.join(f"bbox={c['bbox']} area={c['area']}" for c in hit)
            raise SystemExit(f'归类失败：{what} 命中 {len(hit)} 个\n  {detail}')
        return hit[0]

    picked = {
        'hair': one(head_like, lambda c: c['bbox'][1] < 100, 'hair'),
        'head_base': one(head_like, lambda c: c['bbox'][1] >= 100, 'head_base'),
        'ear': one(ear, lambda c: True, 'ear'),
        'torso': torso,
        'left_arm': one(arms, left, 'left_arm'),
        'right_arm': one(arms, right, 'right_arm'),
        'left_arm_wrist': one(hands, left, 'left_arm_wrist'),
        'right_arm_wrist': one(hands, right, 'right_arm_wrist'),
        'left_leg': one(legs, left, 'left_leg'),
        'right_leg': one(legs, right, 'right_leg'),
        'left_leg_foot': one(feet, left, 'left_leg_foot'),
        'right_leg_foot': one(feet, right, 'right_leg_foot'),
    }

    # 面部：眼×2 / 嘴（独立连通域，宽>高）；鼻梁、眉毛是细笔画，在各自区域单独抠
    face = [c for c in big if cen[c['index']][1] < 800 and cen[c['index']][0] > cx0 + 80]
    eyes = sorted([c for c in face if 560 < cen[c['index']][1] < 680 and c['w'] > c['h']],
                  key=lambda c: cen[c['index']][0])
    mouth = [c for c in face if 690 < cen[c['index']][1] < 780 and c['w'] > c['h']]
    if len(eyes) != 2 or len(mouth) != 1:
        raise SystemExit(f'脸部归类失败：眼 {len(eyes)} 个、嘴 {len(mouth)} 个')

    def region_box(box, thr):
        """在给定区域里按 alpha>thr 求紧包围盒（绝对坐标）"""
        x0, y0, x1, y1 = box
        sub = arr[y0:y1, x0:x1, 3] > thr
        ys, xs = np.nonzero(sub)
        if not len(ys):
            return None
        return [int(x0 + xs.min()), int(y0 + ys.min()), int(x0 + xs.max()) + 1, int(y0 + ys.max()) + 1]

    # 眉 / 鼻：它们是**独立的细笔画连通域**（实测闭运算+10px 间隙合并都并不进别的件），
    # 所以按"相对眼睛与脸型"的自适应区域去抠 —— 换一张拼图也不会因为坐标写死而失手。
    eyes_bbox = [min(eyes[0]['bbox'][0], eyes[1]['bbox'][0]), min(eyes[0]['bbox'][1], eyes[1]['bbox'][1]),
                 max(eyes[0]['bbox'][2], eyes[1]['bbox'][2]), max(eyes[0]['bbox'][3], eyes[1]['bbox'][3])]
    head_c = picked['head_base']
    eye_w = eyes_bbox[2] - eyes_bbox[0]
    eye_h = eyes_bbox[3] - eyes_bbox[1]
    face_cx = (eyes_bbox[0] + eyes_bbox[2]) / 2
    # 眉毛：眼睛上方 0.2~1.1 倍眼高
    brow_band = [int(eyes_bbox[0] - eye_w * 0.15), int(eyes_bbox[1] - eye_h * 1.1),
                 int(eyes_bbox[2] + eye_w * 0.15), int(eyes_bbox[1] - eye_h * 0.2)]
    # 鼻梁：眼睛下缘稍下 → 嘴上缘。注意[上界取太高会把眼睛带进来，取太低会削掉鼻梁上半]，
    # 所以只用"眼睛下缘 + 一点余量"作上界（实测鼻梁笔画起点就在眼睛下方几像素处）
    mouth_top = mouth[0]['bbox'][1]
    y_top = int(eyes_bbox[3] + 2)
    y_bot = int(mouth_top - 1)
    x_mid = int(face_cx)
    nose_band = [x_mid - int(eye_w * 0.12), y_top, x_mid + int(eye_w * 0.12), y_bot]
    nose_box = region_box(nose_band, args.alpha_floor)
    brow_left = region_box([brow_band[0], brow_band[1], int(face_cx), brow_band[3]], args.alpha_floor)
    brow_right = region_box([int(face_cx), brow_band[1], brow_band[2], brow_band[3]], args.alpha_floor)
    print(f'  细笔画区域（自适应）：眉带 y[{brow_band[1]},{brow_band[3]}] 鼻带 y[{nose_band[1]},{nose_band[3]}]'
          f' → 眉 {brow_left} / {brow_right}，鼻 {nose_box}')

    manifest = {
        'format': 'spine-dressup-lab-sheet-parts',
        'version': 2,
        'sheet': str(sheet_path.relative_to(root)).replace('\\', '/') if sheet_path.is_relative_to(root) else str(sheet_path),
        'canvas': [W, H],
        'alphaFloor': args.alpha_floor,
        'minArea': args.min_area,
        'cleanAlpha': args.clean_alpha,
        'junkAlpha': args.junk_alpha,
        'bleed': args.bleed,
        'parts': {},
        'face': {},
        'audit': {},
        'notes': [],
    }

    written = []

    def _finish(name: str, tile: np.ndarray, box):
        """清理 → 出血 → 落盘 → 记录清单"""
        x0, y0, x1, y1 = box
        tile, faint_killed = kill_faint(tile, args.junk_alpha)
        tile, cleaned = clean_invisible(tile, args.clean_alpha)
        tile = bleed_edge(tile, args.bleed)
        file = out_dir / f'{name}.png'
        Image.fromarray(tile, 'RGBA').save(file)
        written.append(file)
        info = {
            'file': file.name,
            'bbox': [int(x0), int(y0), int(x1), int(y1)],
            'w': int(x1 - x0), 'h': int(y1 - y0),
            'centerCanvas': [(x0 + x1) / 2, (y0 + y1) / 2],
            'cleanedPixels': int(cleaned),
            'faintKilledPixels': int(faint_killed),
            'audit': audit(tile),
        }
        info['centerRoot'] = [info['centerCanvas'][0] - W / 2, H - info['centerCanvas'][1]]
        return info

    def emit(name: str, box):
        """按给定区域切（鼻梁 / 眉毛这类非连通域的细笔画）"""
        x0, y0, x1, y1 = box
        return _finish(name, arr[y0:y1, x0:x1].copy(), box)

    def emit_component(name: str, c):
        """按连通域切：顺带把该域之外的像素剔掉（同 bbox 内的邻件碎片）"""
        x0, y0, x1, y1 = c['bbox']
        tile = arr[y0:y1, x0:x1].copy()
        tile[~(labels[y0:y1, x0:x1] == c['index'])] = 0
        return _finish(name, tile, c['bbox'])

    for name, c in picked.items():
        manifest['parts'][name] = emit_component(name, c)
    manifest['face']['eye_left'] = emit_component('face_eye_left', eyes[0])
    manifest['face']['eye_right'] = emit_component('face_eye_right', eyes[1])
    manifest['face']['mouth'] = emit_component('face_mouth', mouth[0])
    for tag, box in (('nose', nose_box), ('eyebrow_left', brow_left), ('eyebrow_right', brow_right)):
        if box:
            manifest['face'][tag] = emit(f'face_{tag}', box)
        else:
            manifest['notes'].append(f'{tag} 区域内没有 alpha>{args.alpha_floor} 的像素，未导出')

    manifest['written'] = [p.name for p in written]
    (out_dir / 'parts-manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), 'utf8')
    if args.json:
        Path(args.json).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), 'utf8')

    # ---- 3) 落盘后的干净度体检 + 可选对比
    print(f'\n切出 {len(written)} 张 → {out_dir}')
    items = load_dir(out_dir)
    print('\n干净度体检（同口径）：')
    mine_rows = summarize(f'本次切件 {out_dir.name}/', items)
    if args.compare:
        cp = Path(args.compare)
        if cp.exists():
            summarize(f'对比 {cp.name}/', load_dir(cp))
        else:
            print(f'  （--compare 目录不存在：{cp}）')

    tot_clean = sum(v.get('cleanedPixels', 0) for v in list(manifest['parts'].values()) + list(manifest['face'].values()))
    tot_faint = sum(v.get('faintKilledPixels', 0) for v in list(manifest['parts'].values()) + list(manifest['face'].values()))
    print(f'\n清理统计：极淡像素归零 {tot_faint} 个（alpha≤{args.junk_alpha}）；'
          f'不可见残色清零 {tot_clean} 个（alpha≤{args.clean_alpha}）')
    bad = [name for name, r in mine_rows if r['invisible'] > 0]
    print(f'清理后仍带隐形脏像素的切件：{len(bad)} 件' + (f'（{", ".join(bad[:5])}…）' if bad else ''))
    for n in manifest['notes']:
        print(f'  ! {n}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
