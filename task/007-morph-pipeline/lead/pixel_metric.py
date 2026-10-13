"""Lead 决定性验证（最终判据）：**像素法** —— 不含任何网格拓扑假设。

为什么必须换判据：verifier 的拓扑审计发现标准体 `Body_Female` **不是单个闭合曲面**
（7376 顶点里最大连通域仅 903，共 26 个连通域、48 条边界环、面绕向不一致）。
于是"点在体内"（射线奇偶 / 最近点法线定向）在肩、臂区域**不可靠** —— 而那正是
报出 60% 穿模的地方。像素法绕开全部这些假设：

    把标准体染亮红 → 身体露出来的地方就是红十字 → 数红像素占比即可

三个状态各渲一张：① 原始（不贴合）② 骨空间 refit ③ refit + 自动去穿模外推
只读资产，不写 .blend。
"""
import bpy, os
from mathutils import Vector

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OUTDIR = f"{ROOT}/task/007-morph-pipeline/lead"
CLEAR, GATE = 0.008, 0.05
CASES = [("Female", "Outfit_Female_Ranger", "Body_Female"),
         ("Male", "Outfit_Male_Ranger", "Body_Male")]


def build(sex, outfit, body_obj):
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
    red = bpy.data.materials.new("POKE")
    red.use_nodes = True
    b = next(n for n in red.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    b.inputs["Base Color"].default_value = (1.0, 0.02, 0.02, 1.0)
    b.inputs["Roughness"].default_value = 0.6
    body.data.materials.clear()
    body.data.materials.append(red)
    return cloth, body, rigA, rigB, restA, restB


def setup_cam(res=(760, 1180)):
    cd = bpy.data.cameras.new("C"); cam = bpy.data.objects.new("C", cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (0, -4.6, 0.92); cam.rotation_euler = (1.5708, 0, 0); cd.lens = 50
    bpy.context.scene.camera = cam
    for nm, loc, e in (("K", (2.6, -3.2, 3.4), 2400), ("F", (-2.6, -2.2, 1.6), 900)):
        ld = bpy.data.lights.new(nm, 'AREA'); ld.energy = e; ld.size = 4
        lo = bpy.data.objects.new(nm, ld); lo.location = loc; lo.rotation_euler = (0.8, 0, 0.85)
        bpy.context.scene.collection.objects.link(lo)
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.image_settings.file_format = 'PNG'
    sc.render.film_transparent = True            # ← alpha = 剪影，最可靠
    sc.world = sc.world or bpy.data.worlds.new("W")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.09, 0.10, 0.12, 1)
    try:
        sc.view_settings.view_transform = "Standard"   # AgX 会把纯红压成鲑鱼粉，必须关掉
    except Exception as e:
        print("view_transform 设置失败:", e)


def shot(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    px = list(img.pixels)
    w, h = img.size
    red = sil = 0
    for i in range(0, len(px), 4):
        r, g, bl = px[i], px[i+1], px[i+2]
        if px[i+3] < 0.5:                            # 透明＝背景
            continue
        sil += 1
        if r > 0.25 and (r - max(g, bl)) > 0.10:
            red += 1
    bpy.data.images.remove(img)
    return red, sil, (100.0*red/sil if sil else 0.0)


for sex, outfit, body_obj in CASES:
    print(f"\n{'#'*76}\n# {sex}  {outfit}\n{'#'*76}")
    cloth, body, rigA, rigB, restA, restB = build(sex, outfit, body_obj)

    # ① 原始
    for o in cloth:
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.object = rigA
    bpy.context.view_layer.update()
    setup_cam()
    r, s, f = shot(f"{OUTDIR}/px_{sex}_1_baseline.png")
    print(f"  ① 原始（挂自带 rig）        红像素 {r:6d}/{s:6d} = {f:6.2f}%")
    base = f

    # ② 骨空间 refit
    for o in cloth:
        mw = o.matrix_world; inv = mw.inverted()
        gn = {vg.index: vg.name for vg in o.vertex_groups}
        for vi, v in enumerate(o.data.vertices):
            gs = [(gn[g.group], g.weight) for g in v.groups if g.weight > 1e-6 and g.group in gn]
            ss = sum(w for _, w in gs)
            if ss <= 0:
                continue
            vA = mw @ v.co
            acc = Vector((0, 0, 0))
            for bn, w in gs:
                w /= ss
                acc += ((restB[bn] @ restA[bn].inverted() @ vA) * w
                        if bn in restA and bn in restB else vA * w)
            v.co = inv @ acc
    for o in cloth:
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.object = rigB
    bpy.context.view_layer.update()
    r, s, f = shot(f"{OUTDIR}/px_{sex}_2_refit.png")
    print(f"  ② 骨空间 refit              红像素 {r:6d}/{s:6d} = {f:6.2f}%   (相对① {f-base:+.2f})")

    # ③ 自动去穿模外推
    from mathutils.bvhtree import BVHTree
    me = body.data; me.calc_loop_triangles()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg); mm = ev.to_mesh()
    bp = [ev.matrix_world @ v.co for v in mm.vertices]
    ev.to_mesh_clear()
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    verts = [c for t in tris for c in (bp[t[0]], bp[t[1]], bp[t[2]])]
    tree = BVHTree.FromPolygons(verts, [(3*i, 3*i+1, 3*i+2) for i in range(len(tris))])
    for rnd in range(3):
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
        bpy.context.view_layer.update()
    r, s, f = shot(f"{OUTDIR}/px_{sex}_3_autofit.png")
    print(f"  ③ refit + 自动外推(3轮)     红像素 {r:6d}/{s:6d} = {f:6.2f}%   (相对① {f-base:+.2f})")

print("\nDONE")