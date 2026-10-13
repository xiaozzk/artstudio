"""Lead 验证：量化「几何贴合需要多大的变形量」。

决策意义：
  如果身体顶出布料只有 1–2 cm，那么"把布料向外推一点"就能贴合（可能可自动化）；
  如果是 5–10 cm，那就是重塑，必须换同源标准体（B 方案）。

做法：对每个标准体顶点，量它到对应服装件表面的【有符号距离】（用服装的法线定向）：
  > 0 = 身体在布料【外面】 → 这就是"顶出来"的深度
只统计落在该件 z 范围内的身体顶点，避免跨部位误配。

只读资产，不写 .blend。
"""
import bpy, statistics
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
CASES = [("Female", "Outfit_Female_Ranger", "Body_Female"),
         ("Male", "Outfit_Male_Ranger", "Body_Male")]


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


def bvh_pts(obj):
    me = obj.data
    me.calc_loop_triangles()
    pts = eval_pts(obj)
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    verts = [c for t in tris for c in (pts[t[0]], pts[t[1]], pts[t[2]])]
    return BVHTree.FromPolygons(verts, [(3*i, 3*i+1, 3*i+2) for i in range(len(tris))])


for sex, outfit, body_obj in CASES:
    print(f"\n{'#'*76}\n# {sex}   {outfit}  vs  {body_obj}\n{'#'*76}")
    bpy.ops.wm.open_mainfile(
        filepath=f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits/{outfit}.blend")
    for o in list(bpy.data.objects):
        if o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o, do_unlink=True)
    # 剥离皮肤面（这次先 DESELECT，避免整件被删 —— Lead 已踩过的坑）
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
    bpts = eval_pts(body)

    print(f"{'件':<30}{'覆盖z范围':>18}{'身体顶点':>9}{'凸出>0':>9}{'p95':>9}{'最大':>9}")
    all_pro = []
    for o in sorted(cloth, key=lambda x: x.name):
        cpts = eval_pts(o)
        z0, z1 = min(p.z for p in cpts), max(p.z for p in cpts)
        tree = bvh_pts(o)
        pro = []
        for p in bpts:
            if z0 - 0.02 <= p.z <= z1 + 0.02:
                hit = tree.find_nearest(p)
                if hit and hit[0] is not None:
                    loc, nor, idx, dist = hit
                    # 距离闸门：只认"就贴在这件附近"的顶点，否则会把脖子/另一条手臂
                    # 到这块护肩的距离也算进来（Lead 踩过：p95 会飙到 60 cm 这种荒谬值）
                    if dist < 0.05:
                        d = (p - loc).dot(nor)
                        if d > 0:
                            pro.append(d)
        all_pro += pro
        if pro:
            pro.sort()
            print(f"  {o.name:<28}{z0:7.3f}..{z1:6.3f}{len(pro):9d}"
                  f"{len(pro):9d}{pro[int(len(pro)*.95)]*100:8.2f}{pro[-1]*100:8.2f}"
                  f"  (cm)")
        else:
            print(f"  {o.name:<28}{z0:7.3f}..{z1:6.3f}{0:9d}{0:9d}{'-':>8}{'-':>8}")
    if all_pro:
        all_pro.sort()
        n = len(all_pro)
        print(f"\n  ★ 身体顶出布料的深度（全部件汇总，{n} 个顶点凸出）:")
        print(f"     中位数 {statistics.median(all_pro)*100:.2f} cm   "
              f"p75 {all_pro[int(n*.75)]*100:.2f}  p95 {all_pro[int(n*.95)]*100:.2f}  "
              f"最大 {all_pro[-1]*100:.2f} cm")
        print(f"  ★ 判读: 若中位数 ≤ 2 cm → 简单外推/收缩可能自动化; "
              f"若 p95 > 4 cm → 需要重塑(倾向 B 方案)")

print("\nDONE")