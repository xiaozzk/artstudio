#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""附件组件总览图（换肤用组件图）：把包里的附件按 rig setup 装配姿态拼成总览图。

纯本地、确定性（PIL+numpy），不消耗 AI 额度。

渲染口径（2026-10-02 用户拍板，除整体缩放外 1:1 复刻 preview-setup-pose）：
  每格内容 = 附件在 setup pose 下的**装配姿态**（含骨世界旋转 + 附件 x/y/rotation/
  scaleX/scaleY 的完整叠加），不是原始贴图方向：
  - region/普通附件：四角四边形（附件变换 + 骨骼世界矩阵）按 2 三角形投影
  - mesh/linkedmesh：加权/非加权顶点蒙皮后按 JSON triangles 逐三角形投影
  展示尺寸 = 世界 bbox（旋转后的包围盒）；全图共用一个全局缩放（最大件定标），
  任意两格的相对大小、朝向 = 预览图里的真实相对大小。
  标注完整骨名/槽名（多附件槽追加附件名）；无附件空槽不出格；多附件槽连排。

世界矩阵 = Spine 官方双轴公式（同 pipelines.update_world）：
  x 轴角 = rotation + shearX，y 轴角 = rotation + 90 + shearY，各自乘 scaleX/scaleY。
  ⚠ 不能用 R·diag(sx,sy) 手动展开：分量抄错位在镜像域（scaleX=-1）下会把
  蒙皮形状整体翻转（本包 hip 带 scaleX=-1，实测踩过）。

排序（--sort bone，默认）——坐标 > 顶层 > 子骨骼 > 名称相似度 > 槽序：
  主键 = 所挂骨骼 setup 世界 y（10px 桶，从高到低 = 从头到脚）；次键 = 层级深度
  （父骨先于子骨）；再 bones[] 序、槽名相似度（去 left/right 的部件基名，
  左右件成对相邻，left 在前）、slots[] 槽序。
  注：y / depth 取自 `render_rig.compute_world`（2026-10-02 修为真仿射世界矩阵，
  depth 为真层级；旧实现 depth 恒为 0，这一层排序此前实际未生效）。
  其余模式：slot=按 JSON slots 数组顺序（绘制顺序）；size=按图片体积（旧口径）。

用法（工作区根运行）：
  python task/005-generic-skeleton/scripts/slot_sheet.py <包目录> [-o 输出.png] [--sort bone]
包目录需含 *.json（骨架）+ images_original/（附件单图）。旧包无 images_original 时退回包根。
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CELL_W, CELL_H, LABEL_H, COLS, BUCKET = 360, 300, 64, 5, 10
BG_FRAME = (200, 200, 210)

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


# ---------- 拼图 ----------

def make_sheet(rows, img_dir: Path, out: Path, doc: dict):
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

    pad_px = 8                                   # 格内边距
    # 全局缩放：所有装配 bbox 都能塞进格子（最大件决定）
    s = 1.0
    for (_, (w, h)) in rasters.values():
        if w > 0 and h > 0:
            s = min(s, (CELL_W - 2 * pad_px) / w, (CELL_H - 2 * pad_px) / h)

    n_rows = (len(rows) + COLS - 1) // COLS
    sheet = Image.new('RGB', (COLS * CELL_W, n_rows * (CELL_H + LABEL_H)), BG_FRAME)
    d = ImageDraw.Draw(sheet)
    f_bone, f_slot, f_att = find_font(15), find_font(15), find_font(13)

    slot_att_count: dict[str, int] = {}
    for _, slot, _, _ in rows:
        slot_att_count[slot] = slot_att_count.get(slot, 0) + 1

    for i, (idx, slot, bone, att) in enumerate(rows):
        cx, cy = (i % COLS) * CELL_W, (i // COLS) * (CELL_H + LABEL_H)
        cell = Image.new('RGBA', (CELL_W - 8, CELL_H - 8), (180, 180, 195, 255))
        cd = ImageDraw.Draw(cell)
        for yy in range(0, CELL_H - 8, 24):  # 棋盘底可辨透明边界
            for xx in range(0, CELL_W - 8, 24):
                if (xx // 24 + yy // 24) % 2 == 0:
                    cd.rectangle([xx, yy, xx + 23, yy + 23], fill=(205, 205, 220, 255))
        if att in rasters:
            img, (tw, th) = rasters[att]
        else:
            img = Image.open(img_dir / f'{att}.png').convert('RGBA')
            tw, th = img.size
        disp = (max(1, round(tw * s)), max(1, round(th * s)))
        img = img.resize(disp, Image.LANCZOS)
        cell.alpha_composite(img, ((CELL_W - 8 - img.width) // 2,
                                   (CELL_H - 8 - img.height) // 2))
        sheet.paste(cell.convert('RGB'), (cx + 4, cy + 4))
        d.rectangle([cx + 4, cy + CELL_H, cx + CELL_W - 4, cy + CELL_H + LABEL_H - 4],
                    fill=(25, 25, 35))
        d.text((cx + 10, cy + CELL_H + 4), f'bone {bone}', fill=(150, 235, 150), font=f_bone)
        d.text((cx + 10, cy + CELL_H + 24), slot, fill=(120, 220, 255), font=f_slot)
        if slot_att_count[slot] > 1:  # 多附件槽（三态等）才追加附件名小字
            d.text((cx + 10, cy + CELL_H + 44), f'att {att}', fill=(255, 230, 120), font=f_att)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f'saved {out} {sheet.size} cells={len(rows)} global_scale={s:.3f}')


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('pkg', type=Path)
    ap.add_argument('-o', '--out', type=Path, default=Path('tmp/slot-sheet.png'))
    ap.add_argument('--sort', choices=('bone', 'slot', 'size'), default='bone')
    a = ap.parse_args(argv[1:])
    pkg = a.pkg.resolve()
    img_dir = pkg / 'images_original'
    if not img_dir.is_dir():
        img_dir = pkg  # 旧包单图直接放包根
    doc = load_doc(pkg)
    rows = sort_rows(collect_rows(doc, img_dir), doc, a.sort)
    make_sheet(rows, img_dir, a.out, doc)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
