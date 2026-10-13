"""Lead 验证（纠错版）：穿模到底出在哪些件上？逐件定位。

背景：上一版发现「服装自带 Regular 手臂皮肤」与 Superhero 标准体手臂**亚毫米级重合**，
因此"体形基准不匹配"的解释**存疑**。本版逐件测穿模率，定位真正的病灶。
"""
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
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


def bvh_of(obj):
    me = obj.data
    me.calc_loop_triangles()
    pts = eval_pts(obj)
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    verts = [c for t in tris for c in (pts[t[0]], pts[t[1]], pts[t[2]])]
    return BVHTree.FromPolygons(verts, [(3*i, 3*i+1, 3*i+2) for i in range(len(tris))])


def pen(obj, tree):
    ins = tot = 0
    for p in eval_pts(obj):
        tot += 1
        hit = tree.find_nearest(p)
        if hit and hit[0] is not None and (p - hit[0]).dot(hit[1]) < 0:
            ins += 1
    return ins, tot


for sex, outfit, body_obj in CASES:
    print(f"\n{'#'*74}\n# {sex}  {outfit}\n{'#'*74}")
    bpy.ops.wm.open_mainfile(
        filepath=f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits/{outfit}.blend")
    rigA = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
    # 剥离皮肤面
    for o in [x for x in bpy.data.objects if x.type == 'MESH' and not x.name.startswith("Icosphere")]:
        names = [m.name if m else "" for m in o.data.materials]
        kill = {i for i, n in enumerate(names) if n.startswith("MI_Regular_")}
        if not kill:
            continue
        bpy.context.view_layer.objects.active = o
        for x in bpy.context.view_layer.objects:
            x.select_set(x is o)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')      # ← 必须先清空，否则会把整件删光
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
    tree = bvh_of(body)

    print(f"{'件':<32}{'顶点':>7}{'穿模':>7}{'比例':>9}   包围盒 z 范围")
    tot_i = tot_n = 0
    rows = []
    for o in sorted(cloth, key=lambda x: x.name):
        i, n = pen(o, tree)
        pts = eval_pts(o)
        z0, z1 = min(p.z for p in pts), max(p.z for p in pts)
        tot_i += i; tot_n += n
        rows.append((o.name, n, i, 100*i/n))
        print(f"  {o.name:<30}{n:7d}{i:7d}{100*i/n:8.1f}%   {z0:6.3f}..{z1:6.3f}")
    print(f"  {'合计':<30}{tot_n:7d}{tot_i:7d}{100*tot_i/tot_n:8.1f}%")
    rows.sort(key=lambda r: -r[3])
    print(f"  ★ 最严重的三件: " + ", ".join(f"{r[0]} {r[3]:.1f}%" for r in rows[:3]))

print("\nDONE")