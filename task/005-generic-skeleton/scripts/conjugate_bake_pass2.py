#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conjugate_bake 第二轮：把全部骨骼框架共轭为**纯平移**（线性=恒等）。

⚠ **已废弃（2026-10-02 用户否决）**：口径改为「骨骼 rest pose 不动，附件去适配骨骼」，
   本文件从未执行（属排查中途产物），保留仅作记录。

背景：第一轮共轭（conjugate_bake.py）把旋转归零但保留了缩放/镜像（hip 的
scaleX=-1 被表示成 shearY=-180 的 y 镜像框架）。烘焙成世界正立的附件内容
穿过镜像框架时被二次镜像 → G4 渲染 25% 像素损伤（头/角/手/靴翻转）。

本轮修复（在**已烘焙**状态上前进，不重烘像素）：
  - 目标世界 = T(当前位置)（线性=恒等，位置不变）
  - 骨骼本地 = 纯平移：x/y = pos − parent_pos，rotation/scaleX/scaleY/shearY 全部删除
  - 附件：内容（世界正立像素）不动；锚点 x/y = 旧世界中心 − 骨位置（世界系偏移）
  - mesh 顶点：逐骨贡献再共轭 v' = inv(T(pos))∘M_cur∘v（世界形状逐位不变）
  - 图集/页图**不动**（像素内容没变，bounds 仍有效）

闸门：
  G1 骨骼位置不变（≤1e-9）
  G2 附件世界 bbox 前后一致（≤0.51px，亚像素进位）
  G3 mesh 蒙皮世界点前后一致（≤1e-6）

用法（工作区根运行；改前自动备份当前状态到 tmp/005-unify/pre-pass2-backup/）：
  python task/005-generic-skeleton/scripts/conjugate_bake_pass2.py
"""
import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / 'task/005-generic-skeleton/output'
JSON_PATH = PKG / 'Unit_Spine_EmpirePaladinSpe1Skin1.json'
BACKUP = ROOT / 'tmp/005-unify/pre-pass2-backup'


def local_affine(x, y, rotation, sx, sy, shx=0.0, shy=0.0):
    rx = (rotation + shx) * math.pi / 180.0
    ry = (rotation + 90.0 + shy) * math.pi / 180.0
    return (math.cos(rx) * sx, math.cos(ry) * sy,
            math.sin(rx) * sx, math.sin(ry) * sy, x, y)


def compose(ma, mb):
    pa, pb, pc, pd, px, py = ma
    a, b, c, d, x, y = mb
    return (pa * a + pb * c, pa * b + pb * d, pc * a + pd * c, pc * b + pd * d,
            px + pa * x + pb * y, py + pc * x + pd * y)


def invert(m):
    a, b, c, d, tx, ty = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise SystemExit(f'[!] 奇异仿射: {m}')
    return (d / det, -b / det, -c / det, a / det,
            (b * ty - d * tx) / det, (c * tx - a * ty) / det)


def apply_m(m, u, v):
    a, b, c, d, tx, ty = m
    return (a * u + b * v + tx, c * u + d * v + ty)


def bone_worlds(doc):
    bones = {b['name']: b for b in doc['bones']}
    cache = {}

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


def main():
    problems = []
    if BACKUP.exists():
        shutil.rmtree(BACKUP)
    BACKUP.mkdir(parents=True)
    shutil.copy2(JSON_PATH, BACKUP / JSON_PATH.name)
    print(f'[backup] {BACKUP}')

    doc = json.loads(JSON_PATH.read_text(encoding='utf-8'))
    cur = bone_worlds(doc)                       # 当前（含镜像框架）世界矩阵
    order = [b['name'] for b in doc['bones']]

    # 目标世界 = T(pos)；新本地 = 纯平移
    new_local: dict[str, tuple] = {}
    for name in order:
        bd = next(x for x in doc['bones'] if x['name'] == name)
        pos = (cur[name][4], cur[name][5])
        parent = bd.get('parent')
        if parent:
            lx, ly = pos[0] - (cur[parent][4], cur[parent][5])[0], \
                pos[1] - (cur[parent][4], cur[parent][5])[1]
        else:
            lx, ly = pos
        new_local[name] = (lx, ly)
        for k in ('rotation', 'scaleX', 'scaleY', 'shearY', 'shearX'):
            bd.pop(k, None)
        if abs(lx) > 1e-9 or abs(ly) > 1e-9:
            bd['x'], bd['y'] = lx, ly
    new_worlds = bone_worlds(doc)

    # G1 位置不变
    g1 = max(max(abs(new_worlds[n][4] - cur[n][4]),
                 abs(new_worlds[n][5] - cur[n][5])) for n in order)
    if g1 > 1e-9:
        problems.append(f'G1 位置漂移 {g1:.3e}')

    slot_bone = {s['name']: s['bone'] for s in doc['slots']}
    skin = doc['skins'][0]['attachments']

    # 附件：重锚定（内容不动）
    for slot_key, atts in skin.items():
        bone = slot_bone[slot_key]
        for aname, att in atts.items():
            if 'mesh' in str(att.get('type')) and att.get('vertices'):
                continue                          # mesh 下面单独处理
            anchor = (att.get('x', 0.0), att.get('y', 0.0))
            center = apply_m(cur[bone], *anchor)  # 旧世界中心
            ax, ay = center[0] - new_worlds[bone][4], center[1] - new_worlds[bone][5]
            att['x'], att['y'] = ax, ay
            w, h = att.get('width', 0) / 2.0, att.get('height', 0) / 2.0
            old_bb = (min(center[0] - w, center[0] + w), max(center[0] - w, center[0] + w),
                      min(center[1] - h, center[1] + h), max(center[1] - h, center[1] + h))
            # 旧 quad = M_cur∘T(anchor)∘rect；镜像/正交框架下 bbox=轴对齐矩形
            corners_old = [apply_m(compose(cur[bone], local_affine(anchor[0], anchor[1], 0, 1, 1)), u, v)
                           for u, v in ((-w, h), (w, h), (w, -h), (-w, -h))]
            corners_new = [apply_m(compose(new_worlds[bone], local_affine(ax, ay, 0, 1, 1)), u, v)
                           for u, v in ((-w, h), (w, h), (w, -h), (-w, -h))]
            for axis, ca, cn in (('x', corners_old, corners_new), ('y', None, None)):
                pass
            dx = max(max(abs(c[0] - n[0]) for c, n in zip(corners_old, corners_new)),
                     max(abs(c[1] - n[1]) for c, n in zip(corners_old, corners_new)))
            if dx > 0.51:
                problems.append(f'G2 附件四角漂移: {aname} {dx:.3f}')

    # mesh 顶点：逐骨贡献再共轭 v' = inv(T(pos))∘M_cur∘v
    def reconj(doc_d, mats_from):
        names = [x['name'] for x in doc_d['bones']]
        for slot_key, atts in doc_d['skins'][0]['attachments'].items():
            bone = slot_bone[slot_key]
            for aname, att in atts.items():
                if not ('mesh' in str(att.get('type')) and att.get('vertices')):
                    continue
                v = att['vertices']
                if len(v) == len(att['uvs']):
                    for k in range(0, len(v), 2):
                        p = apply_m(mats_from[bone], v[k], v[k + 1])
                        v[k], v[k + 1] = p[0] - new_worlds[bone][4], p[1] - new_worlds[bone][5]
                else:
                    i = 0
                    while i < len(v):
                        n = int(v[i]); i += 1
                        for _ in range(n):
                            bi = int(v[i]); x, y, wt = v[i + 1], v[i + 2], v[i + 3]
                            i += 4
                            p = apply_m(mats_from[names[bi]], x, y)
                            v[i - 3], v[i - 2] = p[0] - new_worlds[names[bi]][4], \
                                p[1] - new_worlds[names[bi]][5]

    # G3：先在副本上算共轭结果并比对，通过后才写回真身
    import copy
    trial = copy.deepcopy(doc)
    trial_worlds = bone_worlds(trial)             # 与 cur 相同（doc 已改本地？）
    # 注意：doc 的 bone 字段已被改写 → cur 仍是改写前的世界矩阵快照，直接用 cur
    names = [x['name'] for x in doc['bones']]
    for slot_key, atts in doc['skins'][0]['attachments'].items():
        bone = slot_bone[slot_key]
        for aname, att in atts.items():
            if not ('mesh' in str(att.get('type')) and att.get('vertices')):
                continue
            v = att['vertices']
            if len(v) == len(att['uvs']):
                for k in range(0, len(v), 2):
                    p = apply_m(cur[bone], v[k], v[k + 1])
                    v[k], v[k + 1] = p[0] - new_worlds[bone][4], p[1] - new_worlds[bone][5]
            else:
                i = 0
                while i < len(v):
                    n = int(v[i]); i += 1
                    for _ in range(n):
                        bi = int(v[i]); x, y, wt = v[i + 1], v[i + 2], v[i + 3]
                        i += 4
                        p = apply_m(cur[names[bi]], x, y)
                        v[i - 3], v[i - 2] = p[0] - new_worlds[names[bi]][4], \
                            p[1] - new_worlds[names[bi]][5]

    # G3 验证：备份(旧框架∘旧顶点) vs 新(纯平移框架∘新顶点)
    src = json.loads((BACKUP / JSON_PATH.name).read_text(encoding='utf-8'))
    src_mats = bone_worlds(src)

    def skinned(doc_d, att, mats_dict, bone):
        v, uvs = att['vertices'], att['uvs']
        nm = [x['name'] for x in doc_d['bones']]
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
                    p = apply_m(mats_dict[nm[bi]], x, y)
                    wx += p[0] * wt; wy += p[1] * wt
                xs.append(wx); ys.append(wy)
        return xs, ys

    for slot_key, atts in doc['skins'][0]['attachments'].items():
        bone = slot_bone[slot_key]
        for aname, att in atts.items():
            if not ('mesh' in str(att.get('type')) and att.get('vertices')):
                continue
            att_old = src['skins'][0]['attachments'][slot_key][aname]
            xo, yo = skinned(src, att_old, src_mats, bone)
            xn, yn = skinned(doc, att, bone_worlds(doc), bone)
            d = max(max(abs(a - b) for a, b in zip(xo, xn)),
                    max(abs(a - b) for a, b in zip(yo, yn)))
            if d > 1e-6:
                problems.append(f'G3 mesh 蒙皮漂移: {aname} {d:.3e}')

    if problems:
        print('[pass2] 闸门失败：')
        for p in problems:
            print('   -', p)
        return 1

    JSON_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n',
                         encoding='utf-8')
    print(f'[pass2] OK：G1 max|Δ|={g1:.2e}；G2/G3 通过；骨骼字段只剩 x/y/length；'
          f'附件 rot=0/scale=1 锚点重算；图集未动')
    return 0


if __name__ == '__main__':
    sys.exit(main())
