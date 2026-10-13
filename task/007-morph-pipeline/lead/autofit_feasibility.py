"""Lead 决定性验证（A 方案可行性）：一个朴素的「自动去穿模外推」能把穿模压下去吗？

链路：剥离皮肤面 → 骨空间 refit → 反复把落在体内的布料顶点推到体表外（留 0.8 cm 间隙）
指标：① 穿模率（最近点+法线，带距离闸门）② 边长拉伸比的离散度（外推会不会把布料扯坏）

若穿模能压到 ~0–2% 且拉伸离散度不大 → **A 方案（保留 Superhero 标准体）是可自动化的**，
不必换同源标准体（B）、也不必人工重塑。

只读资产，不写 .blend。
"""
import bpy, statistics
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
CLEAR = 0.008        # 布料与皮肤的目标间隙 0.8 cm
GATE = 0.05          # 距离闸门：只统计"贴在这件附近"的顶点
CASES = [("Female", "Outfit_Female_Ranger", "Body_Female"),
         ("Male", "Outfit_Male_Ranger", "Body_Male")]


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


def bvh_body(obj):
    me = obj.data
    me.calc_loop_triangles()
    pts = eval_pts(obj)
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    verts = [c for t in tris for c in (pts[t[0]], pts[t[1]], pts[t[2]])]
    return BVHTree.FromPolygons(verts, [(3*i, 3*i+1, 3*i+2) for i in range(len(tris))])


def penetration(objs, tree):
    ins = tot = 0
    for o in objs:
        for p in eval_pts(o):
            tot += 1
            hit = tree.find_nearest(p)
            if hit and hit[0] is not None:
                loc, nor, idx, dist = hit
                if dist < GATE and (p - loc).dot(nor) < 0:
                    ins += 1
    return ins, tot


def stretch(objs):
    r = []
    for o in objs:
        rest = [o.matrix_world @ v.co for v in o.data.vertices]
        dfm = eval_pts(o)
        for e in o.data.edges:
            a, b = e.vertices
            l0 = (rest[a] - rest[b]).length
            if l0 > 1e-6:
                r.append((dfm[a] - dfm[b]).length / l0)
    if not r:
        return 0, 0, 0
    r.sort()
    n = len(r)
    return r[n // 2], r[int(n * .95)], r[-1]


for sex, outfit, body_obj in CASES:
    print(f"\n{'#'*76}\n# {sex}\n{'#'*76}")
    bpy.ops.wm.open_mainfile(
        filepath=f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits/{outfit}.blend")
    rigA = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
    restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}
    for o in list(bpy.data.objects):
        if o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o, do_unlink=True)
    for o in [x for x in bpy.data.objects if x.type == 'MESH']:
        names = [m.name if m else "" for m in o.data.materials]
        kill = {i for i, n in enumerate(names) if n.startswith("MI_Regular_")}
        if not kill:
            continue
        bpy.context.view_layer.objects.active = o
        for x in bpy.context.view_layer.objects:
            x.select_set(x is o)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        for p in o.data.polygons:
            p.select = p.material_index in kill
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.delete(type='FACE')
        bpy.ops.object.mode_set(mode='OBJECT')
    cloth = [o for o in bpy.data.objects
             if o.type == 'MESH' and len(o.data.polygons) > 0 and not o.name.startswith("Icosphere")]

    with bpy.data.libraries.load(f"{ROOT}/assets/3d/rig/bodies/Body_{sex}_Standard.blend") as (s, d):
        d.objects = [body_obj]
    for o in d.objects:
        if o:
            bpy.context.scene.collection.objects.link(o)
    body = bpy.data.objects[body_obj]
    rigB = body.find_armature()
    restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}
    tree = bvh_body(body)

    def report(tag):
        i, n = penetration(cloth, tree)
        p50, p95, mx = stretch(cloth)
        print(f"  {tag:<34} 穿模 {i:5d}/{n:5d} = {100*i/n:5.2f}%    "
              f"拉伸 p50 {p50:.3f} p95 {p95:.3f} max {mx:.3f}")
        return i, n

    # ① 原始（挂自带 rig）
    report("① 原始（挂自带 rig）")

    # ② 骨空间 refit 到标准体
    for o in cloth:
        mw = o.matrix_world; inv = mw.inverted()
        gn = {vg.index: vg.name for vg in o.vertex_groups}
        for vi, v in enumerate(o.data.vertices):
            gs = [(gn[g.group], g.weight) for g in v.groups if g.weight > 1e-6 and g.group in gn]
            s = sum(w for _, w in gs)
            if s <= 0:
                continue
            vA = mw @ v.co
            acc = Vector((0, 0, 0))
            for bn, w in gs:
                w /= s
                acc += ((restB[bn] @ restA[bn].inverted() @ vA) * w
                        if bn in restA and bn in restB else vA * w)
            v.co = inv @ acc
    for o in cloth:
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.object = rigB
    bpy.context.view_layer.update()
    report("② 骨空间 refit 后")

    # ③ 自动去穿模外推（3 轮）
    for rnd in range(3):
        moved = 0
        for o in cloth:
            mw = o.matrix_world
            for v in o.data.vertices:
                p = mw @ v.co
                hit = tree.find_nearest(p)
                if not hit or hit[0] is None:
                    continue
                loc, nor, idx, dist = hit
                if dist < GATE and (p - loc).dot(nor) < CLEAR:
                    tgt = loc + nor * CLEAR
                    v.co = mw.inverted() @ tgt
                    moved += 1
        bpy.context.view_layer.update()
        i, n = penetration(cloth, tree)
        print(f"     外推第 {rnd+1} 轮：移动 {moved:5d} 顶点 → 穿模 {100*i/n:5.2f}%")
    report("③ refit + 自动外推后")

    # ④ 再叠体形 morph（BS_Heavy=1）看是否稳
    kbs = body.data.shape_keys
    if kbs and "BS_Heavy" in kbs.key_blocks:
        kbs.key_blocks["BS_Heavy"].value = 1.0
        bpy.context.view_layer.update()
        report("④ 之上再叠 BS_Heavy=1")
        kbs.key_blocks["BS_Heavy"].value = 0.0
        bpy.context.view_layer.update()

print("\nDONE")