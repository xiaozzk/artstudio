"""Lead 决定性验证：服装「贴合(refit)」这一步到底必不必要、效果如何？

问题背景（SPEC §1-F1）：服装自带 rig 与标准体 rig 的 rest 姿态
  · 女侧 差 0/65  → refit 理论上应是 no-op
  · 男侧 差 58/65（最大位置差 3.4 cm）→ refit 必须做吗？不做会怎样？

三种状态各测一次「布料顶点落入标准体内部」的穿模率：
  ① 基线   ：服装挂【服装自带 rig】，标准体挂自己的 rig（各自就位）
  ② 不贴合 ：服装改挂【标准体 rig】，顶点坐标不动（= 天真"共用骨架"）
  ③ 贴合后 ：顶点按骨空间变换 RestA⁻¹→RestB 重绑，再挂标准体 rig

骨空间重绑公式（线性混合蒙皮的重绑）：
  rᵢ   = RestAᵢ⁻¹ · v          （顶点在骨 i 的 rest 局部空间里的位置）
  v'   = Σ wᵢ · RestBᵢ · rᵢ    （用标准体的 rest 重新摆回去）

全程 headless，只读旧资产，不写任何 .blend。
"""
import bpy, os, math
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OLD = f"{ROOT}/assets/3d/blend"
NEW = f"{ROOT}/assets/3d/rig"

CASES = [("Female", f"{OLD}/outfits-gltf-per-asset/outfits/Outfit_Female_Ranger.blend",
          f"{NEW}/bodies/Body_Female_Standard.blend", "Body_Female"),
         ("Male", f"{OLD}/outfits-gltf-per-asset/outfits/Outfit_Male_Ranger.blend",
          f"{NEW}/bodies/Body_Male_Standard.blend", "Body_Male")]


def strip_skin(obj):
    """剔除材质名以 MI_Regular_ 开头的面 —— 服装自带的 Regular 身体皮肤"""
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
    after = len(obj.data.polygons)
    return before - after, before


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


def body_tree(obj):
    me = obj.data
    me.calc_loop_triangles()
    pts = eval_pts(obj)
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    verts = [c for t in tris for c in (pts[t[0]], pts[t[1]], pts[t[2]])]
    idx = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))]
    return BVHTree.FromPolygons(verts, idx)


def penetration(obj, tree):
    inside = tot = 0
    for p in eval_pts(obj):
        hit = tree.find_nearest(p)
        if hit and hit[0] is not None:
            tot += 1
            if (p - hit[0]).dot(hit[1]) < 0:
                inside += 1
    return inside, tot


def weights_of(obj):
    """顶点 → [(骨名, 权重)]"""
    gname = {vg.index: vg.name for vg in obj.vertex_groups}
    out = []
    for v in obj.data.vertices:
        gs = [(gname[g.group], g.weight) for g in v.groups if g.weight > 1e-6 and g.group in gname]
        s = sum(w for _, w in gs)
        out.append([(n, w / s) for n, w in gs] if s > 0 else [])
    return out


for sex, outfit_path, body_path, body_obj in CASES:
    print(f"\n{'#'*76}\n# {sex}\n{'#'*76}")

    # ── 服装自带 rig 的 rest ──
    bpy.ops.wm.open_mainfile(filepath=outfit_path)
    rigA = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
    restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}
    armA_name = rigA.name
    meshes = [o for o in bpy.data.objects
              if o.type == 'MESH' and not o.name.startswith("Icosphere")]
    print(f"服装 rig: {armA_name} ({len(restA)} 骨)  件数 {len(meshes)}")

    # 剥离皮肤面
    stripped = {}
    for o in meshes:
        n, before = strip_skin(o)
        if n:
            stripped[o.name] = (n, before)
    if stripped:
        for k, (n, b) in stripped.items():
            print(f"  剥离皮肤: {k:32s} {n}/{b} 面 ({100*n/b:.0f}%)")

    cloth = [o for o in meshes if len(o.data.polygons) > 0]
    W = {o.name: weights_of(o) for o in cloth}
    V0 = {o.name: [o.matrix_world @ v.co for v in o.data.vertices] for o in cloth}

    # ── 标准体 rest ──
    with bpy.data.libraries.load(body_path) as (src, dst):
        dst.objects = [body_obj]
    for o in dst.objects:
        if o:
            bpy.context.scene.collection.objects.link(o)
    body = bpy.data.objects[body_obj]
    for o in bpy.data.objects:
        if o.type == 'ARMATURE' and o.name in restA:
            pass
    rigB = body.find_armature()
    restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}
    print(f"标准体: {body_obj} ({len(restB)} 骨)  rig={rigB.name}")
    tree = body_tree(body)

    # ① 基线：服装挂自带 rig
    for o in cloth:
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.object = rigA
    bpy.context.view_layer.update()
    b0 = sum(penetration(o, tree)[0] for o in cloth)
    n_tot = sum(penetration(o, tree)[1] for o in cloth)
    print(f"\n  ① 基线（服装挂自带 rig {armA_name}）      穿模 {b0:5d}/{n_tot} = {100*b0/n_tot:5.2f}%")

    # ② 不贴合：改挂标准体 rig，顶点不动
    for o in cloth:
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.object = rigB
    bpy.context.view_layer.update()
    b1 = sum(penetration(o, tree)[0] for o in cloth)
    print(f"  ② 不贴合（改挂标准体 rig，顶点不动）      穿模 {b1:5d}/{n_tot} = {100*b1/n_tot:5.2f}%")

    # ③ 骨空间贴合
    moved = []
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
                if bn in restA and bn in restB:
                    acc += (restB[bn] @ restA[bn].inverted() @ vA) * w
                else:
                    acc += vA * w
            nv = inv @ acc
            moved.append((nv - v.co).length)
            v.co = nv
    bpy.context.view_layer.update()
    b2 = sum(penetration(o, tree)[0] for o in cloth)
    print(f"  ③ 骨空间贴合（RestA⁻¹→RestB 重绑）        穿模 {b2:5d}/{n_tot} = {100*b2/n_tot:5.2f}%")
    if moved:
        moved.sort()
        print(f"     贴合位移: 最大 {moved[-1]*100:6.2f} cm  p95 {moved[int(len(moved)*.95)]*100:6.2f} cm  "
              f"平均 {sum(moved)/len(moved)*100:6.3f} cm  移动>1mm 的顶点 {sum(1 for d in moved if d>1e-3)}/{len(moved)}")

    print(f"\n  ★ 结论：refit {'有效' if b2 < b1 - 5 else '几乎无影响（女侧预期如此）'}："
          f" {100*b1/n_tot:.2f}% → {100*b2/n_tot:.2f}%（基线 {100*b0/n_tot:.2f}%）")

print("\nDONE")