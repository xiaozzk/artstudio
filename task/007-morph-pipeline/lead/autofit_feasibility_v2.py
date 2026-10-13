"""Lead 决定性验证 v2（修正两个自我欺骗）：
  bug1 穿模率自我实现 —— 用最近点+法线去推顶点，再用同一判据量 → 必然≈0
       修正：改用【独立的 6 方向射线奇偶】作为验收判据
  bug2 拉伸度量失效 —— stretch() 拿"修改后"的坐标当 rest → 恒为 1.000
       修正：加载时就快照原始坐标 V_orig，之后所有失真都相对它算

只读资产，不写 .blend。
"""
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
CLEAR, GATE = 0.008, 0.05
DIRS = [Vector((1, 0, 0)), Vector((-1, 0, 0)), Vector((0, 1, 0)),
        Vector((0, -1, 0)), Vector((0, 0, 1)), Vector((0, 0, -1))]
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


def inside_parity(tree, p):
    odd = 0
    for d in DIRS:
        o = p.copy(); n = 0
        for _ in range(24):
            hit = tree.ray_cast(o, d)
            if hit[0] is None:
                break
            n += 1
            o = hit[0] + d * 1e-4
        if n % 2 == 1:
            odd += 1
    return odd >= 4


def pen_parity(objs, tree):
    ins = tot = 0
    for o in objs:
        for p in eval_pts(o):
            tot += 1
            if inside_parity(tree, p):
                ins += 1
    return ins, tot


def pen_nearest(objs, tree):
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


def stretch(objs, V0):
    r = []
    for o in objs:
        cur = [o.matrix_world @ v.co for v in o.data.vertices]
        orig = V0[o.name]
        for e in o.data.edges:
            a, b = e.vertices
            l0 = (orig[a] - orig[b]).length
            if l0 > 1e-6:
                r.append((cur[a] - cur[b]).length / l0)
    r.sort()
    n = len(r)
    return (r[n // 2], r[int(n * .95)], r[int(n * .99)], r[-1]) if n else (0, 0, 0, 0)


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
    V0 = {o.name: [o.matrix_world @ v.co for v in o.data.vertices] for o in cloth}   # ← 真·原始快照

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
        ip, tp = pen_parity(cloth, tree)      # 独立判据
        inr, tn = pen_nearest(cloth, tree)
        p50, p95, p99, mx = stretch(cloth, V0)
        print(f"  {tag:<30} 奇偶 {100*ip/tp:6.2f}%  最近点 {100*inr/tn:6.2f}%   "
              f"拉伸 p50 {p50:.3f} p95 {p95:.3f} p99 {p99:.3f} max {mx:.3f}")

    report("① 原始")
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
    report("② 骨空间 refit")

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
                    v.co = mw.inverted() @ (loc + nor * CLEAR)
                    moved += 1
        bpy.context.view_layer.update()
        ip, tp = pen_parity(cloth, tree)
        print(f"     外推第 {rnd+1} 轮：移动 {moved:5d} → 奇偶判据穿模 {100*ip/tp:5.2f}%")
    report("③ refit + 3 轮外推")

print("\nDONE")