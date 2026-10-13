"""Lead 验证：量化「体形基准不匹配」的幅度。

思路（巧妙点）：服装里的 `MI_Regular_*` 面 **就是 Regular 身体的表面**（裸露的小臂/手）。
拿这些点去量它们相对【Superhero 标准体】表面的有符号距离：
  · 负值 = 落在 Superhero 身体【内部】→ 说明 Regular 比 Superhero 【细】
  · 正值 = 在外面 → Regular 比 Superhero 【粗】
中位数即为两者的围度差量级。

只读资产，不写 .blend。
"""
import bpy, statistics
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
CASES = [("Female", "Outfit_Female_Ranger", "MI_Regular_Female", "Body_Female"),
         ("Male", "Outfit_Male_Ranger", "MI_Regular_Male", "Body_Male"),
         ("Male-Peasant", "Outfit_Male_Peasant", "MI_Regular_Male", "Body_Male")]


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


for sex, outfit, skinmat, body_obj in CASES:
    print(f"\n{'='*72}\n{sex}  ·  服装 {outfit} 的皮肤面 vs 标准体 {body_obj}\n{'='*72}")
    bpy.ops.wm.open_mainfile(
        filepath=f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits/{outfit}.blend")

    skin_pts = []
    for o in bpy.data.objects:
        if o.type != 'MESH' or o.name.startswith("Icosphere"):
            continue
        names = [m.name if m else "" for m in o.data.materials]
        idxs = {i for i, n in enumerate(names) if n.startswith("MI_Regular_")}
        if not idxs:
            continue
        mw = o.matrix_world
        used = set()
        for p in o.data.polygons:
            if p.material_index in idxs:
                used.update(p.vertices)
        skin_pts += [mw @ o.data.vertices[i].co for i in used]
        print(f"  {o.name}: 皮肤面顶点 {len(used)}")
    if not skin_pts:
        print("  （无皮肤面，跳过）")
        continue

    with bpy.data.libraries.load(f"{ROOT}/assets/3d/rig/bodies/Body_{'Female' if 'Female' in body_obj else 'Male'}_Standard.blend") as (s, d):
        d.objects = [body_obj]
    for o in d.objects:
        if o:
            bpy.context.scene.collection.objects.link(o)
    body = bpy.data.objects[body_obj]
    bpy.context.view_layer.update()
    me = body.data
    me.calc_loop_triangles()
    bp = eval_pts(body)
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    verts = [c for t in tris for c in (bp[t[0]], bp[t[1]], bp[t[2]])]
    tree = BVHTree.FromPolygons(verts, [(3*i, 3*i+1, 3*i+2) for i in range(len(tris))])

    sd = []
    for p in skin_pts:
        hit = tree.find_nearest(p)
        if hit and hit[0] is not None:
            sd.append((p - hit[0]).dot(hit[1]))       # >0 在外, <0 在内
    sd.sort()
    n = len(sd)
    inside = sum(1 for d in sd if d < 0)
    print(f"\n  样本 {n} 个点")
    print(f"  ★ 落在 Superhero 标准体【内部】的比例: {inside}/{n} = {100*inside/n:.1f}%")
    print(f"  ★ 有符号距离: 中位数 {statistics.median(sd)*100:+.2f} cm   "
          f"均值 {statistics.fmean(sd)*100:+.2f} cm")
    print(f"     p5 {sd[int(n*.05)]*100:+.2f}  p95 {sd[int(n*.95)]*100:+.2f}  "
          f"最小 {sd[0]*100:+.2f}  最大 {sd[-1]*100:+.2f} cm")
    print(f"  → 解读: 服装自带的 Regular 身体表面相对 Superhero 标准体整体"
          f"{'【缩进体内】' if statistics.median(sd) < 0 else '【凸出体外】'}"
          f"约 {abs(statistics.median(sd))*100:.2f} cm")

print("\nDONE")