"""Lead 决定性验证（V2）：换用「射线奇偶」内外判定 + 噪声底校准。

V1 用「最近点 + 法线定向」判内外，但该法在凹面（腋下/胯部/乳下）会误判。
本版：
  · 内外判定改为 **6 方向射线奇偶表决**（身体是闭合网格，此法更可靠）
  · **噪声底校准**：造一个"必然在体外"的合成壳（标准体躯干沿法线外推 1.5 cm），
    测出该指标的系统噪声，再据此校正真实穿模率
  · 同时保留 V1 口径，两个口径并列表格，暴露度量差异

只读旧资产 + 新标准体，不写任何 .blend。
"""
import bpy, os, math
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OLD = f"{ROOT}/assets/3d/blend"
NEW = f"{ROOT}/assets/3d/rig"
DIRS = [Vector((1, 0, 0)), Vector((-1, 0, 0)), Vector((0, 1, 0)),
        Vector((0, -1, 0)), Vector((0, 0, 1)), Vector((0, 0, -1))]

CASES = [("Female", f"{OLD}/outfits-gltf-per-asset/outfits/Outfit_Female_Ranger.blend",
          f"{NEW}/bodies/Body_Female_Standard.blend", "Body_Female"),
         ("Male", f"{OLD}/outfits-gltf-per-asset/outfits/Outfit_Male_Ranger.blend",
          f"{NEW}/bodies/Body_Male_Standard.blend", "Body_Male")]


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


def bvh_of(obj):
    me = obj.data
    me.calc_loop_triangles()
    pts = eval_pts(obj)
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    verts = [c for t in tris for c in (pts[t[0]], pts[t[1]], pts[t[2]])]
    idx = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))]
    return BVHTree.FromPolygons(verts, idx)


def inside_parity(tree, p):
    """6 方向射线奇偶表决；返回 (在内部?, 奇数方向数)"""
    odd = 0
    for d in DIRS:
        o = p.copy()
        n = 0
        for _ in range(24):
            hit = tree.ray_cast(o, d)
            if hit[0] is None:
                break
            n += 1
            o = hit[0] + d * 1e-4
        if n % 2 == 1:
            odd += 1
    return odd >= 4, odd


def inside_nearest(tree, p):
    hit = tree.find_nearest(p)
    if not hit or hit[0] is None:
        return False
    return (p - hit[0]).dot(hit[1]) < 0


def measure(objs, tree, use_parity=True):
    ins = tot = 0
    for o in objs:
        for p in eval_pts(o):
            tot += 1
            if (inside_parity(tree, p)[0] if use_parity else inside_nearest(tree, p)):
                ins += 1
    return ins, tot


def strip_skin(obj):
    names = [m.name if m else "" for m in obj.data.materials]
    kill = {i for i, n in enumerate(names) if n.startswith("MI_Regular_")}
    if not kill:
        return 0, 0
    before = len(obj.data.polygons)
    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.view_layer.objects:
        o.select_set(o is obj)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.object.mode_set(mode='OBJECT')
    for p in obj.data.polygons:
        if p.material_index in kill:
            p.select = True
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.delete(type='FACE')
    bpy.ops.object.mode_set(mode='OBJECT')
    return before - len(obj.data.polygons), before


def weights_of(obj):
    gn = {vg.index: vg.name for vg in obj.vertex_groups}
    out = []
    for v in obj.data.vertices:
        gs = [(gn[g.group], g.weight) for g in v.groups if g.weight > 1e-6 and g.group in gn]
        s = sum(w for _, w in gs)
        out.append([(n, w / s) for n, w in gs] if s > 0 else [])
    return out


for sex, outfit_path, body_path, body_obj in CASES:
    print(f"\n{'#'*78}\n# {sex}\n{'#'*78}")
    bpy.ops.wm.open_mainfile(filepath=outfit_path)
    rigA = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
    restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}
    meshes = [o for o in bpy.data.objects if o.type == 'MESH' and not o.name.startswith("Icosphere")]
    for o in meshes:
        strip_skin(o)
    cloth = [o for o in meshes if len(o.data.polygons) > 0]
    W = {o.name: weights_of(o) for o in cloth}

    with bpy.data.libraries.load(body_path) as (src, dst):
        dst.objects = [body_obj]
    for o in dst.objects:
        if o:
            bpy.context.scene.collection.objects.link(o)
    body = bpy.data.objects[body_obj]
    rigB = body.find_armature()
    restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}
    tree = bvh_of(body)

    # ── 噪声底校准：把标准体躯干面片沿法线外推 1.5 cm，造一个"必然在体外"的壳 ──
    me = body.data
    me.calc_loop_triangles()
    try:
        vn = [v.vector.copy() for v in me.vertex_normals]
    except Exception:
        vn = [Vector((0, 0, 1))] * len(me.vertices)
    bodypts = eval_pts(body)
    keep = [t for t in me.loop_triangles
            if all(0.80 <= bodypts[i].z <= 1.50 for i in t.vertices)]
    tot_n = tot_p = 0
    for t in keep:
        for i in t.vertices:
            p = bodypts[i] + vn[i] * 0.015
            tot_n += 1
            if inside_nearest(tree, p):
                tot_p += 1
    print(f"噪声底校准（合成壳 {len(keep)} 三角面 / {tot_n} 顶点，必然在体外）：")
    print(f"   · 最近点+法线 口径误判 {100*tot_p/max(tot_n,1):5.2f}%   ← V1 口径的系统噪声")
    nb = sum(1 for t in keep for i in t.vertices
             if inside_parity(tree, bodypts[i] + vn[i] * 0.015)[0])
    print(f"   · 射线奇偶   口径误判 {100*nb/max(tot_n,1):5.2f}%   ← 本版口径的系统噪声")

    print(f"\n{'状态':<34}{'穿模率(射线奇偶)':>18}{'穿模率(最近点)':>16}")
    rows = []
    for label, refit, useB in (("① 基线（服装挂自带 rig）", False, False),
                               ("② 不贴合（改挂标准体 rig）", False, True),
                               ("③ 骨空间贴合后", True, True)):
        for o in cloth:
            for m in o.modifiers:
                if m.type == 'ARMATURE':
                    m.object = rigB if useB else rigA
        if refit:
            for o in cloth:
                mw = o.matrix_world
                inv = mw.inverted()
                for vi, v in enumerate(o.data.vertices):
                    ws = W[o.name][vi]
                    if not ws:
                        continue
                    vA = mw @ v.co
                    acc = Vector((0, 0, 0))
                    for bn, w in ws:
                        acc += ((restB[bn] @ restA[bn].inverted() @ vA) * w
                                if bn in restA and bn in restB else vA * w)
                    v.co = inv @ acc
        bpy.context.view_layer.update()
        ip, tp = measure(cloth, tree, True)
        inr, tn = measure(cloth, tree, False)
        rows.append((label, ip, tp, inr, tn))
        print(f"{label:<30}{100*ip/tp:12.2f}%{100*inr/tn:14.2f}%")
    print("DONE-CASE")

print("\nALL DONE")