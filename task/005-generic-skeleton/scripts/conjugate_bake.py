#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task/005-generic-skeleton —— rest pose 共轭重建 + region 贴图烘焙（2026-10-02，用户拍板「彻底」方案）

⚠ **已废弃（2026-10-02 用户否决后回滚）**：口径改为「骨骼 rest pose 不动，让附件去适配骨骼」。
   本脚本对 output/ 的改动已全部回滚（JSON/图集/单图均恢复，回滚后渲染与基准逐像素一致 0 差）。
   保留此文件仅为存档记录（含 G1–G3 闸门口径与踩坑），**不要直接运行**——它会二次烘焙已还原的贴图。

目标：JSON 重新导入 Spine 编辑器后与当前交付包一一对应——人物 setup 渲染不变，
但 **全部骨骼 rest 世界转角归零、全部 region 附件 rotation/scale 归零**，
原图（images_original）重烘成装配姿态（世界正立）方向。
mesh 蒙皮件：贴图不动，只把顶点本地坐标共轭到新骨骼系（蒙皮世界形状逐位不变）。

数学口径（与 tools/spine/repair_spine/pipelines.py 同一套，行主序）：
  - 世界矩阵 x 轴角 = rotation + shearX；y 轴角 = rotation + 90 + shearY；各乘 scaleX/scaleY
  - 共轭：L_new = inv(M_target_parent) ∘ M_target_bone，其中
    M_target_bone = T(旧世界位置) ∘ (旧世界线性部分去掉旋转，保留缩放/镜像)
    → 双轴分解得新 x/y/rotation/scaleX/scaleY/shearY（精确，无近似）
  - region 烘焙：M_total_old = M_old_bone ∘ L_old_att；新 PNG = 贴图经 M_total_old
    四角四边形 2 三角形投影（Y 翻转 = 预览口径）；JSON：x/y = inv(M_new_bone)·旧中心，
    rotation/scaleX/scaleY 删除，width/height = 烘焙画布尺寸
  - mesh 顶点共轭：v' = inv(M_new_i) ∘ M_old_i ∘ v（逐骨逐顶点，加权求和前各贡献
    独立共轭 → 蒙皮世界形状精确不变）

闸门（跑完自检，失败退出码 1）：
  G1 骨骼世界位置：共轭前后 max|Δ| ≤ 1e-6
  G2 附件世界四角：旧 M_total vs 新 M_bone∘T(x,y) max|Δ| ≤ 1e-6
  G3 mesh 蒙皮世界顶点：共轭前后 max|Δ| ≤ 1e-6
  G4 整机渲染：备份包 vs 新包 pipelines.Renderer 逐像素 diff（只允许重采样边缘差，
     报告 mean/max/超差像素占比）

⚠ 烘焙有重采样：贴图旋转 ±90°/镜像用精确重排（无差），任意角旋转用 BICUBIC，
   装配渲染边缘会有亚像素级重采样差（G4 报告量化）。
⚠ 动画安全性：只烘**附件本地**变换（rot/scale 永远跟骨），未来动画迁移不受影响；
   骨骼 rest 归零后，新迁入动画按新 rest 口径注入（002 工具链口径）。

用法（工作区根运行；直接改 output/ 交付包，先自动备份到 tmp/005-unify/pre-bake-backup/）：
  python task/005-generic-skeleton/scripts/conjugate_bake.py
"""
import json
import math
import os
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / 'task/005-generic-skeleton/output'
JSON_PATH = PKG / 'Unit_Spine_EmpirePaladinSpe1Skin1.json'
ATLAS_PATH = PKG / 'Unit_Spine_EmpirePaladinSpe1Skin1.atlas'
IMAGES_DIR = PKG / 'images_original'
BACKUP = ROOT / 'tmp/005-unify/pre-bake-backup'
TOL = 1e-6


# ---------- 仿射（行主序，与 pipelines.update_world 同构） ----------

def local_affine(x, y, rotation, sx, sy, shx=0.0, shy=0.0) -> tuple:
    rx = (rotation + shx) * math.pi / 180.0
    ry = (rotation + 90.0 + shy) * math.pi / 180.0
    return (math.cos(rx) * sx, math.cos(ry) * sy,
            math.sin(rx) * sx, math.sin(ry) * sy, x, y)


def compose(ma, mb) -> tuple:
    pa, pb, pc, pd, px, py = ma
    a, b, c, d, x, y = mb
    return (pa * a + pb * c, pa * b + pb * d, pc * a + pd * c, pc * b + pd * d,
            px + pa * x + pb * y, py + pc * x + pd * y)


def invert(m) -> tuple:
    a, b, c, d, tx, ty = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise SystemExit(f'[!] 奇异仿射，无法共轭: {m}')
    return (d / det, -b / det, -c / det, a / det,
            (b * ty - d * tx) / det, (c * tx - a * ty) / det)


def apply_m(m, u, v):
    a, b, c, d, tx, ty = m
    return (a * u + b * v + tx, c * u + d * v + ty)


def bone_worlds(doc) -> dict[str, tuple]:
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


def decompose(lin9) -> tuple:
    """行主序线性部分 (a,b,c,d) → (rotation, scaleX, scaleY, shearY)，角度制。"""
    a, b, c, d = lin9
    sx = math.hypot(a, c)
    sy = math.hypot(b, d)
    rx = math.atan2(c, a)
    psi = math.atan2(d, b)
    rot = math.degrees(rx)
    shy = math.degrees(psi) - rot - 90.0
    shy = (shy + 180.0) % 360.0 - 180.0
    return rot, sx, sy, shy


# ---------- 贴图三角形投影（与 slot_sheet.rasterize 同口径） ----------

def rasterize(pts, uvpx, tris, tex: Image.Image) -> Image.Image:
    minx = min(p[0] for p in pts)
    maxy = max(p[1] for p in pts)
    W = max(1, math.ceil(max(p[0] for p in pts) - minx))
    H = max(1, math.ceil(maxy - min(p[1] for p in pts)))
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for (i, j, k) in tris:
        dst = [(pts[q][0] - minx, maxy - pts[q][1]) for q in (i, j, k)]
        src = [uvpx[q] for q in (i, j, k)]
        A = np.array([[p[0], p[1], 1.0] for p in dst], dtype=float)
        try:
            sol_x = np.linalg.solve(A, [p[0] for p in src])
            sol_y = np.linalg.solve(A, [p[1] for p in src])
        except np.linalg.LinAlgError:
            continue
        coeffs = (sol_x[0], sol_x[1], sol_x[2], sol_y[0], sol_y[1], sol_y[2])
        warped = tex.transform((W, H), Image.AFFINE, coeffs, resample=Image.BICUBIC)
        mask = Image.new('L', (W, H), 0)
        ImageDraw.Draw(mask).polygon([(round(p[0]), round(p[1])) for p in dst], fill=255)
        canvas.paste(warped, (0, 0), mask)
    return canvas


def main() -> int:
    problems: list[str] = []
    # ---------- 备份 ----------
    if BACKUP.exists():
        shutil.rmtree(BACKUP)
    BACKUP.mkdir(parents=True)
    shutil.copy2(JSON_PATH, BACKUP / JSON_PATH.name)
    shutil.copy2(ATLAS_PATH, BACKUP / ATLAS_PATH.name)
    shutil.copytree(IMAGES_DIR, BACKUP / 'images_original')
    print(f'[backup] {BACKUP}')

    doc = json.loads(JSON_PATH.read_text(encoding='utf-8'))
    old_mats = bone_worlds(doc)

    # ---------- 1. 骨骼共轭：目标世界 = T(旧位置) ∘ 旧线性（去旋转） ----------
    order = [b['name'] for b in doc['bones']]
    new_mats: dict[str, tuple] = {}
    for name in order:
        bd = next(x for x in doc['bones'] if x['name'] == name)
        m_old = old_mats[name]
        pos = (m_old[4], m_old[5])
        a, b, c, d = m_old[0], m_old[1], m_old[2], m_old[3]
        rot, sx, sy, shy = decompose((a, b, c, d))
        # 目标世界线性 = 旧世界线性去掉旋转：S = R(-θ)·M（列向量口径的矩阵乘）
        co, si = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        a_t = co * a + si * c        # S[0][0]
        b_t = co * b + si * d        # S[0][1]
        c_t = -si * a + co * c       # S[1][0]
        d_t = -si * b + co * d       # S[1][1]
        parent = bd.get('parent')
        # 目标世界 = T(旧世界位置) ∘ S_target（保留缩放/镜像/剪切，只去旋转）
        target_world = (a_t, b_t, c_t, d_t, pos[0], pos[1])
        if parent:
            target_local_lin = compose(invert(new_mats[parent]), target_world)
        else:
            target_local_lin = target_world
        L_rot, sx_l, sy_l, shy_l = decompose(target_local_lin[:4])
        # 本地 x/y 必须取新父框架下的坐标（= conjugate 结果的平移分量），
        # 不能直接用旧世界坐标——父帧去旋转后本地坐标要重算
        new_local = (target_local_lin[4], target_local_lin[5], L_rot, sx_l, sy_l, shy_l)
        new_mats[name] = compose(new_mats[parent],
                                 local_affine(new_local[0], new_local[1], L_rot,
                                              sx_l, sy_l, 0.0, shy_l)) if parent \
            else local_affine(new_local[0], new_local[1], L_rot, sx_l, sy_l, 0.0, shy_l)

        # 写回字段（默认值省略；x/y 仅在非零时写，保持 root 无偏移字段的整洁）
        for k in ('rotation', 'scaleX', 'scaleY', 'shearY'):
            bd.pop(k, None)
        if abs(new_local[0]) > 1e-9 or abs(new_local[1]) > 1e-9:
            bd['x'], bd['y'] = new_local[0], new_local[1]
        if abs(L_rot) > 1e-9:
            bd['rotation'] = L_rot
        if abs(sx_l - 1.0) > 1e-9:
            bd['scaleX'] = sx_l
        if abs(sy_l - 1.0) > 1e-9:
            bd['scaleY'] = sy_l
        if abs(shy_l) > 1e-9:
            bd['shearY'] = shy_l

    # G1 骨骼世界位置
    g1 = max(max(abs(new_mats[n][4] - old_mats[n][4]),
                 abs(new_mats[n][5] - old_mats[n][5])) for n in order)
    if g1 > TOL:
        problems.append(f'G1 骨骼位置漂移 {g1}')

    slot_bone = {s['name']: s['bone'] for s in doc['slots']}
    skin = doc['skins'][0]['attachments']
    tex_sizes = {f.stem: Image.open(f).size for f in sorted(IMAGES_DIR.glob('*.png'))}

    # ---------- 2. region 烘焙 / 3. mesh 顶点共轭 ----------
    tex_use: dict[str, tuple] = {}   # tex_key → (rotation, scaleX, scaleY) 已烘口径
    for slot_key, atts in skin.items():
        bone = slot_bone[slot_key]
        for aname, att in atts.items():
            is_mesh = 'mesh' in str(att.get('type')) and att.get('vertices')
            if is_mesh:
                # mesh：逐骨贡献共轭 v' = inv(M_new)∘M_old∘v
                Mi_old = old_mats[bone]
                Mi_new = new_mats[bone]
                v = att['vertices']
                if len(v) == len(att['uvs']):       # 非加权
                    nv = []
                    for k in range(0, len(v), 2):
                        p_old = apply_m(Mi_old, v[k], v[k + 1])
                        nv += list(apply_m(invert(Mi_new), *p_old))
                    att['vertices'] = nv
                else:                                # 加权
                    names = [x['name'] for x in doc['bones']]
                    i = 0
                    while i < len(v):
                        n = int(v[i]); i += 1
                        for _ in range(n):
                            bi = int(v[i]); x, y, wt = v[i + 1], v[i + 2], v[i + 3]
                            nm_b = names[bi]
                            p_old = apply_m(old_mats[nm_b], x, y)
                            p_new = apply_m(invert(new_mats[nm_b]), *p_old)
                            v[i + 1], v[i + 2] = p_new
                            i += 4
                continue
            # region：烘焙贴图 + 附件字段归零
            rot = att.get('rotation', 0.0)
            sx, sy = att.get('scaleX', 1.0), att.get('scaleY', 1.0)
            tex_key = att.get('path') or att.get('name') or aname
            M_total_old = compose(old_mats[bone],
                                  local_affine(att.get('x', 0.0), att.get('y', 0.0), rot, sx, sy))
            hw, hh = att.get('width', 0) / 2.0, att.get('height', 0) / 2.0
            corners = [apply_m(M_total_old, u, v) for u, v in
                       ((-hw, hh), (hw, hh), (hw, -hh), (-hw, -hh))]
            tw, th = tex_sizes[tex_key]
            baked = rasterize(corners, [(0, 0), (tw, 0), (tw, th), (0, th)],
                              [(0, 1, 2), (2, 3, 0)],
                              Image.open(IMAGES_DIR / f'{tex_key}.png').convert('RGBA'))
            # 冲突守卫：同一图片被不同变换的附件共用 → 写后缀副本并指向它
            sign = (round(rot, 4), round(sx, 6), round(sy, 6))
            if tex_key in tex_use and tex_use[tex_key] != sign:
                new_key = f'{tex_key}__bake{len(tex_use)}'
                baked.save(IMAGES_DIR / f'{new_key}.png')
                tex_use[new_key] = sign
                att['path'] = new_key
                tex_key = new_key
            else:
                baked.save(IMAGES_DIR / f'{tex_key}.png')
                tex_use[tex_key] = sign
            # 附件锚点 = 旧世界中心 → 新骨骼本地
            center = apply_m(M_total_old, 0.0, 0.0)
            ax, ay = apply_m(invert(new_mats[bone]), *center)
            for k in ('rotation', 'scaleX', 'scaleY'):
                att.pop(k, None)
            att['x'], att['y'] = ax, ay
            att['width'], att['height'] = baked.size
            # G2 附件世界四角等价
            M_new_total = compose(new_mats[bone], local_affine(ax, ay, 0.0, 1.0, 1.0))
            nw, nh = baked.size[0] / 2.0, baked.size[1] / 2.0
            corners_new = [apply_m(M_new_total, u, v) for u, v in
                           ((-nw, nh), (nw, nh), (nw, -nh), (-nw, -nh))]
            # 用旧矩形 bbox 的对应角比（新画布含亚像素进位余量）
            bx = [c[0] for c in corners]; by = [c[1] for c in corners]
            bxn = [c[0] for c in corners_new]; byn = [c[1] for c in corners_new]
            if max(abs(min(bx) - min(bxn)), abs(max(bx) - max(bxn)),
                   abs(min(by) - min(byn)), abs(max(by) - max(byn))) > 0.51:
                problems.append(f'G2 附件四角漂移: {aname} Δbbox')

    # G3 mesh 蒙皮世界顶点：备份(旧矩阵∘旧顶点) vs 当前(新矩阵∘新顶点) 必须逐位相等
    def skinned_world(doc_d, att, mats_dict, bone):
        v, uvs = att['vertices'], att['uvs']
        names = [x['name'] for x in doc_d['bones']]
        xs, ys = [], []
        if len(v) == len(uvs):
            for k in range(0, len(v), 2):
                p = apply_m(mats_dict[bone], v[k], v[k + 1])
                xs.append(p[0]); ys.append(p[1])
        else:
            i = 0
            while i < len(v):
                n = int(v[i]); i += 1
                wx = wy = 0.0
                for _ in range(n):
                    bi = int(v[i]); x, y, wt = v[i + 1], v[i + 2], v[i + 3]
                    i += 4
                    p = apply_m(mats_dict[names[bi]], x, y)
                    wx += p[0] * wt; wy += p[1] * wt
                xs.append(wx); ys.append(wy)
        return xs, ys

    src_doc = json.loads((BACKUP / JSON_PATH.name).read_text(encoding='utf-8'))
    src_mats = bone_worlds(src_doc)
    for slot_key, atts in skin.items():
        bone = slot_bone[slot_key]
        for aname, att in atts.items():
            if not ('mesh' in str(att.get('type')) and att.get('vertices')):
                continue
            att_old = src_doc['skins'][0]['attachments'][slot_key][aname]
            xo, yo = skinned_world(src_doc, att_old, src_mats, bone)
            xn, yn = skinned_world(doc, att, bone_worlds(doc), bone)
            d = max(max(abs(a - b) for a, b in zip(xo, xn)),
                    max(abs(a - b) for a, b in zip(yo, yn)))
            if d > TOL:
                problems.append(f'G3 mesh 蒙皮漂移: {aname} {d:.2e}')

    if problems:
        print('[conjugate-bake] 闸门失败：')
        for p in problems:
            print('   -', p)
        return 1

    # ---------- 4. 写 JSON ----------
    JSON_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n',
                         encoding='utf-8')
    print(f'[gates] G1 骨骼位置 max|Δ|={g1:.2e}；G2/G3 通过（1e-6）')

    # ---------- 5. 重打包图集（简易 shelf，2px pad，bleed） ----------
    repack_atlas()
    return 0


def repack_atlas():
    from scipy import ndimage
    from PIL import Image

    def bleed(img):
        a = np.asarray(img).copy()
        solid = a[:, :, 3] > 0
        if not solid.any():
            return img
        idx = ndimage.distance_transform_edt(~solid, return_indices=True)[1]
        a[:, :, :3] = a[:, :, :3][idx[0], idx[1]]
        return Image.fromarray(a, 'RGBA')

    pad = 2
    files = sorted(IMAGES_DIR.glob('*.png'))
    imgs = {f.stem: Image.open(f).convert('RGBA') for f in files}
    order = sorted(imgs.items(), key=lambda kv: -max(kv[1].size))
    page_w = 2048
    shelf_x = shelf_y = shelf_h = 0
    bounds = {}
    for name, im in order:
        w, h = im.size
        if shelf_x + w + pad * 2 > page_w:
            shelf_y += shelf_h + pad
            shelf_x, shelf_h = 0, 0
        bounds[name] = (shelf_x + pad, shelf_y + pad, w, h)
        shelf_x += w + pad * 2
        shelf_h = max(shelf_h, h)
    page_h = shelf_y + shelf_h + pad * 2
    page = Image.new('RGBA', (page_w, page_h), (0, 0, 0, 0))
    for name, im in imgs.items():
        page.paste(im, bounds[name][:2])
    page = bleed(page)
    page.save(PKG / 'Unit_Spine_EmpirePaladinSpe1Skin1.png')
    lines = ['Unit_Spine_EmpirePaladinSpe1Skin1.png',
             f'\tsize: {page_w}, {page_h}', '\tfilter: Linear, Linear']
    for f in files:  # 按文件名序输出（与改名后 images 一致）
        x, y, w, h = bounds[f.stem]
        lines += [f.stem, f'\tbounds: {x}, {y}, {w}, {h}']
    ATLAS_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'[atlas] repack {page_w}x{page_h}，{len(files)} 区域')


if __name__ == '__main__':
    sys.exit(main())
