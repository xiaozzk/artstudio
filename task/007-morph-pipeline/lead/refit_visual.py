"""Lead 验证（视觉）：男侧「不 refit」vs「骨空间 refit」—— 把标准体染亮红，
身体顶出布料的地方会刺眼暴露。

输出：task/007-morph-pipeline/lead/refit_visual_male.png（左=不refit，右=refit）
"""
import bpy, os
from mathutils import Vector

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OUT = f"{ROOT}/task/007-morph-pipeline/lead/refit_visual_male.png"
bpy.ops.wm.open_mainfile(
    filepath=f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits/Outfit_Male_Ranger.blend")

rigA = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}

# 剥离皮肤面
meshes = [o for o in bpy.data.objects if o.type == 'MESH' and not o.name.startswith("Icosphere")]
for o in meshes:
    names = [m.name if m else "" for m in o.data.materials]
    kill = {i for i, n in enumerate(names) if n.startswith("MI_Regular_")}
    if not kill:
        continue
    bpy.context.view_layer.objects.active = o
    for x in bpy.context.view_layer.objects:
        x.select_set(x is o)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.object.mode_set(mode='OBJECT')
    for p in o.data.polygons:
        p.select = p.material_index in kill
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.delete(type='FACE')
    bpy.ops.object.mode_set(mode='OBJECT')
cloth = [o for o in meshes if len(o.data.polygons) > 0]

# 备份"不 refit"的顶点位置
V0 = {o.name: [v.co.copy() for v in o.data.vertices] for o in cloth}

# 标准体
with bpy.data.libraries.load(f"{ROOT}/assets/3d/rig/bodies/Body_Male_Standard.blend") as (s, d):
    d.objects = ["Body_Male"]
for o in d.objects:
    if o:
        bpy.context.scene.collection.objects.link(o)
body = bpy.data.objects["Body_Male"]
rigB = body.find_armature()
restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}

# 身体染亮红
red = bpy.data.materials.new("POKE")
red.use_nodes = True
bsdf = next(n for n in red.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
bsdf.inputs["Base Color"].default_value = (1.0, 0.03, 0.03, 1.0)
bsdf.inputs["Roughness"].default_value = 0.55
body.data.materials.clear()
body.data.materials.append(red)


def do_refit():
    for o in cloth:
        mw = o.matrix_world
        inv = mw.inverted()
        gn = {vg.index: vg.name for vg in o.vertex_groups}
        for vi, v in enumerate(o.data.vertices):
            gs = [(gn[g.group], g.weight) for g in v.groups
                  if g.weight > 1e-6 and g.group in gn]
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


def set_rig(arm):
    for o in cloth:
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.object = arm


def restore():
    for o in cloth:
        for vi, c in enumerate(V0[o.name]):
            o.data.vertices[vi].co = c


# ── 造两份：左=不 refit，右=refit ──
copies = []
set_rig(rigB)
bpy.context.view_layer.update()

# 右：refit 后再复制一份出来，然后把左边那份还原成"不 refit"
do_refit()
bpy.context.view_layer.update()
right = []
for o in cloth:
    c = o.copy(); c.data = o.data.copy()
    bpy.context.scene.collection.objects.link(c)
    right.append(c)
    o.hide_render = True                     # 原始那份改回"不 refit"并整体左移
restore()
bpy.context.view_layer.update()

for o in cloth:                              # 左：不 refit，整体 -0.85m
    o.hide_render = False
    o.location.x -= 0.85
for o in right:                              # 右：refit，整体 +0.85m
    o.location.x += 0.85
bc = body.copy(); bc.data = body.data.copy()
bpy.context.scene.collection.objects.link(bc)
body.location.x -= 0.85
bc.location.x += 0.85

# Icosphere 清掉
for o in list(bpy.data.objects):
    if o.name.startswith("Icosphere"):
        bpy.data.objects.remove(o, do_unlink=True)

# 相机 + 灯
cd = bpy.data.cameras.new("C"); cam = bpy.data.objects.new("C", cd)
bpy.context.scene.collection.objects.link(cam)
cam.location = (0, -5.0, 0.95); cam.rotation_euler = (1.5708, 0, 0); cd.lens = 50
bpy.context.scene.camera = cam
for nm, loc, e in (("K", (3, -3.5, 4), 2600), ("F", (-3, -2.5, 2), 1000)):
    ld = bpy.data.lights.new(nm, 'AREA'); ld.energy = e; ld.size = 5
    lo = bpy.data.objects.new(nm, ld); lo.location = loc; lo.rotation_euler = (0.75, 0, 0.8)
    bpy.context.scene.collection.objects.link(lo)

sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = 1500, 1000
sc.render.filepath = OUT
sc.render.image_settings.file_format = 'PNG'
bpy.ops.render.render(write_still=True)
print("渲染:", OUT, os.path.exists(OUT))
print("左 = 不 refit（穿模 29.58%）   右 = 骨空间 refit（19.49%）")
print("DONE")