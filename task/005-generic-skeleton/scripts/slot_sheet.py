#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""附件组件总览图（换肤用组件图）：把包里的附件按 rig setup 装配姿态拼成总览图。

纯本地、确定性（PIL+numpy），不消耗 AI 额度。

渲染口径（**纯渲染口径**，2026-10-10 用户拍板收敛；源头是 2026-10-02 的装配姿态口径）：
  每格内容 = 附件在 setup pose 下的**装配姿态**（含骨世界旋转 + 附件 x/y/rotation/
  scaleX/scaleY 的完整叠加），不是原始贴图方向，**也不贴 images_original 原图**：
  - region/普通附件：四角四边形（附件变换 + 骨骼世界矩阵）按 2 三角形投影
  - mesh/linkedmesh：加权/非加权顶点蒙皮后按 JSON triangles 逐三角形投影
  展示尺寸 = 世界 bbox（旋转后的包围盒）；全图**共用一个全局缩放**（`--max-size`
  与最大件共同定标），任意两格的相对大小、朝向 = 渲染图（preview-setup-pose）里的真实关系。
  实测对账（2026-10-10，14 件逐件 vs `pipelines.py render` 单件隔离渲染）：
  内容盒尺寸差 0–5px（渲染侧恒偏大 = ss=3→LANCZOS 抗锯齿外溢）、质心偏移 ≤3px、
  对齐后 >2px 之外的轮廓差 0–2px ⇒ 几何同源，逐像素差异只来自采样链。
  标注完整骨名/槽名（多附件槽追加附件名）；无附件空槽不出格；多附件槽连排。

布局（2026-10-10 新增）：最大件占 **2×2 大格**，其余各占 1×1，全图仍共用一个全局
  缩放 ⇒ 既保住跨件相对大小可比，又把整体字号/件体量比等格网格放大约 1.8×
  （005 包：s 0.690 → 1.278）。成品长边锁在 `--max-size`（默认 2048）以内，
  无需事后二次缩放。

⚠ 生图方向陷阱（2026-10-10 实测，换肤必读）：本图是**装配方向**，而回灌用的贴图是
  **原图方向**，两者在 6 件上差 ~90°（arm_upper_left/right、hand_left、body、hair_back、
  skirt），hand_right 42°、tail 27°。照本图方向画件再存回 `images_original/` 会转错，
  而 `flatbg_cut.py --fit-to` 只做等比缩放 + 中心对齐、**不含旋转**。
  要拿方向/像素尺寸当尺子，另出原图口径（见 task/005 notes）。

世界矩阵 = Spine 官方双轴公式（同 pipelines.update_world）：
  x 轴角 = rotation + shearX，y 轴角 = rotation + 90 + shearY，各自乘 scaleX/scaleY。
  ⚠ 不能用 R·diag(sx,sy) 手动展开：分量抄错位在镜像域（scaleX=-1）下会把
  蒙皮形状整体翻转（实测踩过）。镜像域位置：2026-10-02 起在 root_bone
  （原在 hip_bone，已共轭上移，渲染逐像素不变）；判断一律逐骨查 scale 正负，不写死骨名。

排序（--sort bone，默认）——坐标 > 顶层 > 子骨骼 > 名称相似度 > 槽序：
  主键 = 所挂骨骼 setup 世界 y（10px 桶，从高到低 = 从头到脚）；次键 = 层级深度
  （父骨先于子骨）；再 bones[] 序、槽名相似度（去 left/right 的部件基名，
  左右件成对相邻，left 在前）、slots[] 槽序。
  注：y / depth 取自 `render_rig.compute_world`（2026-10-02 修为真仿射世界矩阵，
  depth 为真层级；旧实现 depth 恒为 0，这一层排序此前实际未生效）。
  其余模式：slot=按 JSON slots 数组顺序（绘制顺序）；size=按图片体积（旧口径）。

用法（工作区根运行）：
  python task/005-generic-skeleton/scripts/slot_sheet.py <包目录> [-o 输出.png]
      [--sort bone] [--max-size 2048] [--cols 5] [--label-h 84] [--no-hero]
包目录需含 *.json（骨架）+ images_original/（附件单图）。旧包无 images_original 时退回包根。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BUCKET = 10
LABEL_FONT = (15, 15, 13)
BG_FRAME = (200, 200, 210)
CELL_PAD = 8            # 格内边距（画）+ 定标余量另算
SCALE_PAD = 16          # 定标时每格四边各留的余量（= 2*CELL_PAD）

# 世界坐标/层级计算复用渲染器的同一套数学（骨骼链旋转累乘，Y-up）
_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / 'tools' / 'spine' / 'anim'))
from render_rig import compute_world  # noqa: E402


def find_font(sz: int):
    for p in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\arial.ttf',
              '/System/Library/Fonts/Supplemental/Arial.ttf',
              '/System/Library/Fonts/Helvetica.ttc'):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                continue
    return ImageFont.load_default()


def load_doc(pkg: Path) -> dict:
    for jf in sorted(pkg.glob('*.json')):
        try:
            doc = json.loads(jf.read_text(encoding='utf-8'))
        except Exception:
            continue
        if isinstance(doc, dict) and 'bones' in doc and 'slots' in doc:
            return doc
    raise SystemExit(f'[!] {pkg} 下找不到骨架 json（顶层需有 skeleton+bones 键）')


# ---------- 世界矩阵（Spine 官方双轴公式，行主序） ----------

def local_affine(x, y, rotation, sx, sy, shx=0.0, shy=0.0) -> tuple:
    """(a,b,c,d,tx,ty)：x' = a*u + b*v + tx；y' = c*u + d*v + ty。"""
    rx = (rotation + shx) * math.pi / 180.0
    ry = (rotation + 90.0 + shy) * math.pi / 180.0
    return (math.cos(rx) * sx, math.cos(ry) * sy,
            math.sin(rx) * sx, math.sin(ry) * sy, x, y)


def compose(ma, mb) -> tuple:
    """parent·local（行主序）。"""
    pa, pb, pc, pd, px, py = ma
    a, b, c, d, x, y = mb
    return (pa * a + pb * c, pa * b + pb * d, pc * a + pd * c, pc * b + pd * d,
            px + pa * x + pb * y, py + pc * x + pd * y)


def world_matrices(doc: dict) -> dict[str, tuple]:
    bones = {b['name']: b for b in doc['bones']}
    cache: dict[str, tuple] = {}

    def resolve(name):
        if name in cache:
            return cache[name]
        b = bones[name]
        m = local_affine(b.get('x', 0.0), b.get('y', 0.0), b.get('rotation', 0.0),
                         b.get('scaleX', 1.0), b.get('scaleY', 1.0),
                         b.get('shearX', 0.0), b.get('shearY', 0.0))
        p = b.get('parent')
        if p:
            m = compose(resolve(p), m)
        cache[name] = m
        return m

    for n in bones:
        resolve(n)
    return cache


def apply_m(m, u, v):
    a, b, c, d, tx, ty = m
    return (a * u + b * v + tx, c * u + d * v + ty)


# ---------- 附件几何：世界顶点 + 贴图 uv 像素 + 三角形 ----------

def geom_of(doc: dict, mats: dict, tex_sizes: dict, bone: str,
            aname: str, att: dict):
    tex_key = att.get('path') or att.get('name') or aname
    if 'mesh' in str(att.get('type')) and att.get('vertices'):
        pts = mesh_world_points(doc, mats, att, bone)
        tw, th = tex_sizes[tex_key]
        uvs = att['uvs']
        uvpx = [(uvs[2 * i] * tw, uvs[2 * i + 1] * th) for i in range(len(uvs) // 2)]
        tris = [(att['triangles'][k], att['triangles'][k + 1], att['triangles'][k + 2])
                for k in range(0, len(att['triangles']), 3)]
    else:  # region / 普通：四角四边形（附件变换 + 骨骼世界矩阵）
        w, h = att.get('width', 0), att.get('height', 0)
        L = local_affine(att.get('x', 0.0), att.get('y', 0.0), att.get('rotation', 0.0),
                         att.get('scaleX', 1.0), att.get('scaleY', 1.0))
        M = compose(mats[bone], L)
        hw, hh = w / 2.0, h / 2.0
        pts = [apply_m(M, u, v) for u, v in
               ((-hw, hh), (hw, hh), (hw, -hh), (-hw, -hh))]  # 局部 y-up 四角
        tw, th = tex_sizes[tex_key]
        # uv (0,0)=左上 ↔ 局部 (-hw, +hh)
        uvpx = [(0, 0), (tw, 0), (tw, th), (0, th)]
        tris = [(0, 1, 2), (2, 3, 0)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bbox = (max(xs) - min(xs), max(ys) - min(ys))
    return pts, uvpx, tris, bbox


def mesh_world_points(doc: dict, mats: dict, att: dict, bone: str) -> list[tuple]:
    """mesh 附件蒙皮后的世界顶点（加权/非加权），行主序点变换。"""
    v, uvs = att['vertices'], att['uvs']
    pts = []
    if len(v) == len(uvs):  # 非加权：绑定到 slot 骨骼
        m = mats[bone]
        for k in range(0, len(v), 2):
            pts.append(apply_m(m, v[k], v[k + 1]))
    else:                   # 加权：骨数, [骨索引,x,y,权重]*
        names = [b['name'] for b in doc['bones']]
        i = 0
        while i < len(v):
            n = int(v[i])
            i += 1
            wx = wy = 0.0
            for _ in range(n):
                bi = int(v[i])
                x, y, wt = v[i + 1], v[i + 2], v[i + 3]
                i += 4
                p = apply_m(mats[names[bi]], x, y)
                wx += p[0] * wt
                wy += p[1] * wt
            pts.append((wx, wy))
    return pts


def rasterize(pts, uvpx, tris, tex: Image.Image) -> Image.Image:
    """把贴图经世界三角形投影回图像空间（Y 翻转为预览口径）。返回整 bbox 画布（不裁剪）。"""
    minx = min(p[0] for p in pts)
    maxy = max(p[1] for p in pts)
    W = max(1, math.ceil(max(p[0] for p in pts) - minx))
    H = max(1, math.ceil(maxy - min(p[1] for p in pts)))
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for (i, j, k) in tris:
        dst = [(pts[q][0] - minx, maxy - pts[q][1]) for q in (i, j, k)]  # Y-up → Y-down
        src = [uvpx[q] for q in (i, j, k)]
        A = np.array([[p[0], p[1], 1.0] for p in dst], dtype=float)
        try:
            sol_x = np.linalg.solve(A, [p[0] for p in src])
            sol_y = np.linalg.solve(A, [p[1] for p in src])
        except np.linalg.LinAlgError:                                   # 退化三角形
            continue
        coeffs = (sol_x[0], sol_x[1], sol_x[2], sol_y[0], sol_y[1], sol_y[2])
        warped = tex.transform((W, H), Image.AFFINE, coeffs, resample=Image.BICUBIC)
        mask = Image.new('L', (W, H), 0)
        ImageDraw.Draw(mask).polygon([(round(p[0]), round(p[1])) for p in dst], fill=255)
        canvas.paste(warped, (0, 0), mask)
    return canvas


# ---------- 行收集与排序 ----------

def collect_rows(doc: dict, img_dir: Path) -> list[tuple]:
    """返回 [(slot序, 槽名, 骨名, 附件名)]；空槽（无附件）不出格。"""
    skin_atts: dict[str, list] = {}
    for sk in doc.get('skins', []):
        for slot, atts in sk.get('attachments', {}).items():
            skin_atts.setdefault(slot, [])
            for n in atts:
                if n not in skin_atts[slot]:
                    skin_atts[slot].append(n)

    rows = []
    for idx, s in enumerate(doc['slots']):
        name, bone = s['name'], s.get('bone', '')
        atts = list(skin_atts.get(name, []))
        if s.get('attachment') and s['attachment'] not in atts:
            atts.insert(0, s['attachment'])
        if not atts:
            continue
        for n in atts:
            if (img_dir / f'{n}.png').is_file():
                rows.append((idx, name, bone, n))
            else:
                print(f'[!] 缺图跳过: slot={name} att={n}（无 {img_dir}/{n}.png）')
    return rows


def sort_rows(rows, doc, mode: str):
    if mode == 'bone':  # 坐标 > 顶层(深度) > 骨序 > 名称相似度 > 槽序
        world = compute_world(doc)
        bone_order = {b['name']: i for i, b in enumerate(doc['bones'])}
        # 以包内最低骨骼为参考原点分桶：整体平移（如 skeleton.x/y）不影响排序
        y0 = min((b.get('y', 0.0) for b in world.values()), default=0.0)

        def key(r):
            _, slot, bone, _ = r
            w = world.get(bone, {})
            tokens = slot.split('_')
            side = 0 if 'left' in tokens else (1 if 'right' in tokens else -1)
            base = '_'.join(t for t in tokens if t not in ('left', 'right'))
            return (-int((w.get('y', 0.0) - y0) // BUCKET), w.get('depth', 0),
                    bone_order.get(bone, 10**6), base, side, r[0])
        return sorted(rows, key=key)
    if mode == 'slot':
        return sorted(rows, key=lambda r: r[0])
    if mode == 'size':
        return sorted(rows, key=lambda r: (-os.path.getsize(f'{r[3]}.png')
                                           if Path(f'{r[3]}.png').exists() else 0, r[0]))
    raise SystemExit(f'[!] 未知排序: {mode}')


# ---------- 布局求解 ----------

def solve_layout(n_parts: int, boxes: dict, hero: str | None, max_size: int,
                 cols: int, label_h: int):
    """返回 (COLS, ROWS, CELL_W, CELL_H, s)。

    约束：cols*CELL_W <= max_size 且 rows*(CELL_H+label_h) <= max_size；
    目标：在**所有件都能塞进自己格子**的前提下把统一缩放 s 取到最大。
    hero 占 2x2（其画区 = 2*CELL_W 宽、2*CELL_H+label_h 高）。
    """
    need = n_parts + (3 if hero else 0)          # hero 多占 3 个格位
    rows = max(1, math.ceil(need / cols))
    if hero and rows < 2:                        # 单行放不下 2x2，退化为等比网格
        hero, need = None, n_parts
        rows = max(1, math.ceil(need / cols))
    cell_w = max_size // cols
    cell_h = max_size // rows - label_h
    if cell_h <= SCALE_PAD:
        raise SystemExit(f'[!] 格子太矮（{cell_h}px）：调小 --cols 或 --label-h')

    s = float('inf')
    for name, (w, h) in boxes.items():
        if w <= 0 or h <= 0:
            continue
        if name == hero:
            bw, bh = 2 * cell_w, 2 * cell_h + label_h
        else:
            bw, bh = cell_w, cell_h
        s = min(s, (bw - SCALE_PAD) / w, (bh - SCALE_PAD) / h)
    if not math.isfinite(s) or s <= 0:
        raise SystemExit('[!] 无法定标（附件 bbox 全为 0？）')
    return cols, rows, cell_w, cell_h, s


# ---------- 拼图 ----------

def make_sheet(rows, img_dir: Path, out: Path, doc: dict,
               max_size: int = 2048, cols: int = 5, label_h: int = 84,
               hero: bool = True):
    mats = world_matrices(doc)
    tex_sizes = {f.stem: Image.open(f).size for f in sorted(img_dir.glob('*.png'))}
    slot_bone = {s['name']: s.get('bone', '') for s in doc['slots']}

    # 每附件：按装配姿态光栅化一次 → (图, bbox)
    rasters: dict[str, tuple[Image.Image, tuple]] = {}
    seen: set[str] = set()
    for slot_key, atts in doc['skins'][0]['attachments'].items():
        for aname, att in atts.items():
            if aname in seen or aname not in tex_sizes:
                continue
            seen.add(aname)
            pts, uvpx, tris, bbox = geom_of(doc, mats, tex_sizes,
                                            slot_bone.get(slot_key, ''), aname, att)
            tex = Image.open(img_dir / f'{aname}.png').convert('RGBA')
            rasters[aname] = (rasterize(pts, uvpx, tris, tex), bbox)

    boxes = {n: b for n, (_, b) in rasters.items()}
    # 大件（bbox 面积最大）占 2x2；其余按 order 顺序填格
    hero_att = None
    if hero and rows:
        hero_att = max((r for r in rows if r[3] in boxes),
                       key=lambda r: boxes[r[3]][0] * boxes[r[3]][1])[3]

    COLS, ROWS, CELL_W, CELL_H, s = solve_layout(
        len(rows), boxes, hero_att, max_size, cols, label_h)
    print(f'[slot_sheet] 布局 {COLS}x{ROWS}  格 {CELL_W}x{CELL_H}+{label_h}  '
          f'hero={hero_att}  全局 s={s:.3f}  成品 {COLS * CELL_W}x{ROWS * (CELL_H + label_h)}')

    # 占位：hero 占 (0,0)(0,1)(1,0)(1,1)
    taken = {(0, 0), (0, 1), (1, 0), (1, 1)} if hero_att else set()
    free = [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in taken]
    rest = [r for r in rows if r[3] != hero_att]
    if len(rest) > len(free):
        raise SystemExit(f'[!] 格位不够：需要 {len(rest)}，只有 {len(free)}')
    place = ([((0, 0), next(r for r in rows if r[3] == hero_att))] if hero_att else []) \
        + list(zip(free, rest))

    f_bone, f_slot, f_att = (find_font(sz) for sz in LABEL_FONT)
    sheet = Image.new('RGB', (COLS * CELL_W, ROWS * (CELL_H + label_h)), BG_FRAME)
    d = ImageDraw.Draw(sheet)
    slot_att_count: dict[str, int] = {}
    for _, slot, _, _ in rows:
        slot_att_count[slot] = slot_att_count.get(slot, 0) + 1

    for (gr, gc), (idx, slot, bone, att) in place:
        span = 2 if att == hero_att else 1
        bw = CELL_W * span
        bh = CELL_H * span + (label_h if span == 2 else 0)   # hero 画区吃掉行 0 的标签带
        cx, cy = gc * CELL_W, gr * (CELL_H + label_h)
        cell = Image.new('RGBA', (bw - CELL_PAD, bh - CELL_PAD), (180, 180, 195, 255))
        cd = ImageDraw.Draw(cell)
        for yy in range(0, bh - CELL_PAD, 24):               # 棋盘底可辨透明边界
            for xx in range(0, bw - CELL_PAD, 24):
                if (xx // 24 + yy // 24) % 2 == 0:
                    cd.rectangle([xx, yy, xx + 23, yy + 23], fill=(205, 205, 220, 255))
        if att in rasters:
            img, (tw, th) = rasters[att]
        else:
            img = Image.open(img_dir / f'{att}.png').convert('RGBA')
            tw, th = img.size
        disp = (max(1, round(tw * s)), max(1, round(th * s)))
        img = img.resize(disp, Image.LANCZOS)
        cell.alpha_composite(img, ((bw - CELL_PAD - img.width) // 2,
                                   (bh - CELL_PAD - img.height) // 2))
        sheet.paste(cell.convert('RGB'), (cx + CELL_PAD // 2, cy + CELL_PAD // 2))
        d.rectangle([cx + 4, cy + bh, cx + bw - 4, cy + bh + label_h - 4], fill=(25, 25, 35))
        d.text((cx + 10, cy + bh + 4), f'bone {bone}', fill=(150, 235, 150), font=f_bone)
        d.text((cx + 10, cy + bh + 22), slot, fill=(120, 220, 255), font=f_slot)
        if slot_att_count[slot] > 1:                        # 多附件槽（三态等）才追加附件名小字
            d.text((cx + 10, cy + bh + 44), f'att {att}', fill=(255, 230, 120), font=f_att)

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f'-> {out}  {sheet.size}  cells={len(rows)}  '
          f'{"OK <= " + str(max_size) if max(sheet.size) <= max_size else "!! 超出 " + str(max_size)}')
    return sheet


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('pkg', type=Path)
    ap.add_argument('-o', '--out', type=Path, default=Path('tmp/slot-sheet.png'))
    ap.add_argument('--sort', choices=('bone', 'slot', 'size'), default='bone')
    ap.add_argument('--max-size', type=int, default=2048,
                    help='成品长边上限（默认 2048；全图统一缩放后保证不超过它）')
    ap.add_argument('--cols', type=int, default=5, help='列数（默认 5）')
    ap.add_argument('--label-h', type=int, default=84, help='每格标签带高度（默认 84）')
    ap.add_argument('--no-hero', dest='hero', action='store_false',
                    help='关掉「最大件占 2x2」的布局，退回全等格网格')
    a = ap.parse_args(argv[1:])
    pkg = a.pkg.resolve()
    img_dir = pkg / 'images_original'
    if not img_dir.is_dir():
        img_dir = pkg  # 旧包单图直接放包根
    doc = load_doc(pkg)
    rows = sort_rows(collect_rows(doc, img_dir), doc, a.sort)
    make_sheet(rows, img_dir, a.out, doc, max_size=a.max_size, cols=a.cols,
               label_h=a.label_h, hero=a.hero)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))