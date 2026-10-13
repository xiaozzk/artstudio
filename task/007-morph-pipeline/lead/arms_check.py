"""判定 `*_Arms` 的 60% 穿模是真穿模还是度量伪影。
渲染：亮红标准体 + 剥离皮肤面后的 Arms 袖子（其它件隐藏）。
若袖子明显套在手臂外面 → 60% 是伪影；若手臂把袖子撑爆 → 是真穿模。
"""
import bpy, os

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OUT = f"{ROOT}/task/007-morph-pipeline/lead/arms_check.png"
bpy.ops.wm.open_mainfile(
    filepath=f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits/Outfit_Male_Ranger.blend")

for o in list(bpy.data.objects):
    if o.name.startswith("Icosphere"):
        bpy.data.objects.remove(o, do_unlink=True)

# 剥离皮肤面
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

arms = bpy.data.objects["Male_Ranger_Arms"]
for o in bpy.data.objects:
    if o.type == 'MESH' and o is not arms:
        o.hide_render = True

with bpy.data.libraries.load(f"{ROOT}/assets/3d/rig/bodies/Body_Male_Standard.blend") as (s, d):
    d.objects = ["Body_Male"]
for o in d.objects:
    if o:
        bpy.context.scene.collection.objects.link(o)
body = bpy.data.objects["Body_Male"]

red = bpy.data.materials.new("POKE")
red.use_nodes = True
b = next(n for n in red.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
b.inputs["Base Color"].default_value = (1.0, 0.05, 0.05, 1.0)
body.data.materials.clear()
body.data.materials.append(red)

cd = bpy.data.cameras.new("C"); cam = bpy.data.objects.new("C", cd)
bpy.context.scene.collection.objects.link(cam)
cam.location = (0.95, -0.75, 1.45); cam.rotation_euler = (1.30, 0, 0.90); cd.lens = 60
bpy.context.scene.camera = cam
for nm, loc, e in (("K", (2.5, -2, 3), 1800), ("F", (-2, -1.5, 1.8), 700)):
    ld = bpy.data.lights.new(nm, 'AREA'); ld.energy = e; ld.size = 3
    lo = bpy.data.objects.new(nm, ld); lo.location = loc; lo.rotation_euler = (0.8, 0, 0.9)
    bpy.context.scene.collection.objects.link(lo)

sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = 1200, 900
sc.render.filepath = OUT
sc.render.image_settings.file_format = 'PNG'
bpy.ops.render.render(write_still=True)
print("渲染:", OUT, os.path.exists(OUT))
print("Arms 件剥离后剩余面数:", len(arms.data.polygons))
print("DONE")