"""build_tryon.py —— 试穿合成：UBC 头部（裁成 head-only）+ 服装套装 + 可选发型 → 单 rig 的 .blend

背景（实测数据）：
  · 服装 Readme 明确「只用 Base Characters 的头部，用全身会穿模」；
  · 两套资产骨骼**同名 65 骨**，且 Head / neck_01 的 rest 变换逐位相同
    （Head (0, 0.0829, 0)、neck_01 (0, 0.2151, 0)），差异只在 upperarm_l / thigh_l（肩宽/胯宽）
    → 把 UBC 头部 mesh 重新挂到「服装自带的 rig」上，无需权重迁移即可保持在正确位置。

用法：
  "/Applications/Blender.app/Contents/MacOS/Blender" -b --factory-startup \
      --python tools/3d/build_tryon.py

产出：download/tryon-blend/*.blend + preview/*.png + tryon-report.json
"""
import bpy
import bmesh
import json
import math
import os
from mathutils import Vector

ROOT = os.environ.get("ARTSTUDIO_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MCO = ROOT + "/download/modular-outfits-fantasy/Modular Character Outfits - Fantasy[Standard]"
UBC = ROOT + "/download/ubc/Universal Base Characters[Standard]"
GL_OUTFIT = MCO + "/Exports/glTF (Godot-Unreal)/Outfits"
GL_HEAD = UBC + "/Base Characters/Godot - UE"
GL_HAIR = UBC + "/Hairstyles/Rigged to Head Bone/glTF (Godot -Unreal)"
OUT = ROOT + "/assets/3d/blend/tryon"

HEAD_BONES = {"Head", "neck_01"}
HEAD_WEIGHT_MIN = 0.5

JOBS = [
    {"name": "TryOn_Male_Peasant", "outfit": "Male_Peasant", "head": "Superhero_Male_FullBody",
     "hair": "Hair_SimpleParted"},
    {"name": "TryOn_Female_Peasant", "outfit": "Female_Peasant", "head": "Superhero_Female_FullBody",
     "hair": "Hair_Long"},
    {"name": "TryOn_Male_Ranger", "outfit": "Male_Ranger", "head": "Superhero_Male_FullBody",
     "hair": None},
    {"name": "TryOn_Female_Ranger", "outfit": "Female_Ranger", "head": "Superhero_Female_FullBody",
     "hair": None},
]

REPORT = {}


def fresh(name):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.name = name
    try:
        sc.unit_settings.system = 'METRIC'
        sc.render.engine = 'BLENDER_EEVEE'
    except Exception:
        pass
    return sc


def new_coll(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def import_into(path, coll, fmt="gltf"):
    before = set(bpy.data.objects)
    if fmt == "gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        bpy.ops.import_scene.fbx(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    real = []
    for o in new:
        if any(c.name == "glTF_not_exported" for c in o.users_collection):
            continue
        real.append(o)
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    return real


def head_only(mesh_obj, report):
    """按顶点组权重裁掉非头部顶点（只留 Head / neck_01 权重 > 0.5 的）。"""
    me = mesh_obj.data
    gname = {g.index: g.name for g in mesh_obj.vertex_groups}
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    dl = bm.verts.layers.deform.active          # bmesh 里顶点组权重走 deform layer：
    drop = []                                    # v[dl] 是 {group_index: weight}
    for v in bm.verts:
        dw = v[dl] if dl is not None else {}
        w = sum(weight for gi, weight in dw.items() if gname.get(gi) in HEAD_BONES)
        if w <= HEAD_WEIGHT_MIN:
            drop.append(v)
    total = len(bm.verts)
    bmesh.ops.delete(bm, geom=drop, context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.update()
    report["head_cut"] = {"mesh": mesh_obj.name, "verts_before": total,
                          "verts_after": len(me.vertices),
                          "kept_pct": round(100.0 * len(me.vertices) / max(total, 1), 1),
                          "criterion": "sum(weight on Head,neck_01) > %.1f" % HEAD_WEIGHT_MIN}


def rebind_to_rig(mesh_objs, rig, drop_rigs):
    """把 mesh 挂到目标 rig（保持世界变换），再删掉它们原来的 armature。"""
    mw = rig.matrix_world
    for o in mesh_objs:
        if o.type != 'MESH':
            continue
        world = o.matrix_world.copy()
        o.parent = rig
        o.matrix_parent_inverse = mw.inverted()
        o.matrix_world = world
        for m in o.modifiers:
            if m.type == 'ARMATURE':
                m.object = rig
        if not any(m.type == 'ARMATURE' for m in o.modifiers):
            md = o.modifiers.new("Armature", 'ARMATURE')
            md.object = rig
    for r in drop_rigs:
        if r and r.type == 'ARMATURE':
            bpy.data.objects.remove(r, do_unlink=True)


def setup_stage():
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    objs = [o for o in bpy.data.objects if o.type == 'MESH' and o.data]
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        mw = o.matrix_world
        for c in o.bound_box:
            w = mw @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    center = (lo + hi) / 2.0
    size = max((hi - lo).x, (hi - lo).y, (hi - lo).z, 0.1)
    sc = bpy.context.scene
    cd = bpy.data.cameras.new("Camera")
    cd.lens = 60
    cam = bpy.data.objects.new("Camera", cd)
    cam.location = (center.x + size * 0.30, center.y - size * 2.6, center.z + size * 0.06)
    cam.rotation_euler = (center - Vector(cam.location)).to_track_quat('-Z', 'Y').to_euler()
    sc.collection.objects.link(cam)
    sc.camera = cam
    sd = bpy.data.lights.new("Sun", 'SUN')
    sd.energy = 4.0
    sun = bpy.data.objects.new("Sun", sd)
    sun.rotation_euler = (math.radians(52), 0, math.radians(35))
    sc.collection.objects.link(sun)
    fd = bpy.data.lights.new("Fill", 'AREA')
    fd.energy = 220
    fd.size = 4
    fo = bpy.data.objects.new("Fill", fd)
    fo.location = (center.x - size * 1.4, center.y - size * 0.9, center.z + size * 0.3)
    fo.rotation_euler = (center - Vector(fo.location)).to_track_quat('-Z', 'Y').to_euler()
    sc.collection.objects.link(fo)
    w = bpy.data.worlds.new("World")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.05, 0.055, 0.065, 1.0)
        bg.inputs[1].default_value = 1.0
    return {"min": [round(x, 3) for x in lo], "max": [round(x, 3) for x in hi]}


def relink_images(search_dirs):
    """同 pack2blend.py：坏引用按文件名归一化找回（T_Eye_Normal_png.png → T_Eye_Normal.png）。"""
    index = {}
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in files:
                index.setdefault(fn.lower(), os.path.join(root, fn))
    fixed, missing = [], []
    for img in bpy.data.images:
        if img.name == 'Render Result' or img.packed_file is not None:
            continue
        cur = bpy.path.abspath(img.filepath) if img.filepath else ""
        if cur and os.path.exists(cur):
            continue
        base = os.path.basename((img.filepath or "").replace("\\", "/"))
        stem, ext = os.path.splitext(base)
        cands = [base] + ([stem[:-4] + ext] if stem.endswith("_png") else [])
        found = next((index.get(c.lower()) for c in cands if index.get(c.lower())), None)
        if found:
            img.filepath = found
            img.filepath_raw = found
            img.reload()
            fixed.append({"image": img.name, "orig_name": base, "path": found})
        else:
            missing.append({"image": img.name, "orig": img.filepath})
    return fixed, missing


def write_readme(title, lines):
    t = bpy.data.texts.new("README_试穿说明")
    t.write(title + "\n" + "=" * len(title) + "\n" + "\n".join(lines) + "\n")


def bbox_of(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return {"min": [round(x, 4) for x in lo], "max": [round(x, 4) for x in hi]}


os.makedirs(OUT, exist_ok=True)
os.makedirs(OUT + "/preview", exist_ok=True)

for job in JOBS:
    name = job["name"]
    print("=== " + name, flush=True)
    fresh(name)
    rep = {"outfit": job["outfit"], "head_src": job["head"], "hair": job["hair"]}

    # 1) 服装（自带 rig，作为最终 rig）
    c_outfit = new_coll("Outfit")
    import_into(os.path.join(GL_OUTFIT, job["outfit"] + ".gltf"), c_outfit)
    rigs = [o for o in c_outfit.objects if o.type == 'ARMATURE']
    rig = rigs[0]
    rig.name = "RIG_" + name
    rig.data.name = rig.name
    rep["final_rig"] = rig.name
    rep["final_rig_bones"] = len(rig.data.bones)

    # 2) UBC 头部（3 个 mesh：body / eyes / eyebrows）
    c_head = new_coll("Head_from_UBC")
    head_objs = import_into(os.path.join(GL_HEAD, job["head"] + ".gltf"), c_head)
    head_rigs = [o for o in head_objs if o.type == 'ARMATURE']
    head_meshes = [o for o in head_objs if o.type == 'MESH']
    body = max(head_meshes, key=lambda o: len(o.data.vertices))
    head_only(body, rep)
    for o in head_meshes:
        o.name = "Head_" + o.name if not o.name.startswith("Head_") else o.name

    # 3) 可选发型（HeadBone 变体，skinned，同名骨）
    hair_objs = []
    if job["hair"]:
        c_hair = new_coll("Hair")
        hair_objs = import_into(os.path.join(GL_HAIR, job["hair"] + ".gltf"), c_hair)

    # 4) 统一挂到服装 rig，删掉多余骨架
    drop = [o for o in (head_objs + hair_objs) if o.type == 'ARMATURE']
    rebind_to_rig([o for o in (head_objs + hair_objs) if o.type == 'MESH'], rig, drop)
    rep["dropped_rigs"] = len(drop)

    fixed, missing = relink_images([
        GL_OUTFIT, GL_HEAD, GL_HAIR,
        MCO + "/Textures",
        UBC + "/Base Characters/Textures",
        UBC + "/Hairstyles/Textures",
    ])
    rep["relink"] = {"fixed": fixed, "missing": missing}
    try:
        bpy.ops.file.pack_all()
    except Exception as e:
        print("  pack_all:", e)

    stage_bb = setup_stage()
    rep["bbox"] = stage_bb

    meshes = [o for o in bpy.data.objects if o.type == 'MESH' and o.data]
    rep["meshes"] = [{"name": o.name, "verts": len(o.data.vertices),
                      "skinned": any(m.type == 'ARMATURE' and m.object for m in o.modifiers),
                      "vgroups": len(o.vertex_groups)} for o in meshes]
    rep["materials"] = sorted({ms.material.name for o in meshes for ms in o.material_slots if ms.material})
    imgs = [i for i in bpy.data.images if i.name != 'Render Result']
    rep["images"] = {"total": len(imgs), "packed": len([i for i in imgs if i.packed_file is not None]),
                     "size_zero": [i.name for i in imgs if tuple(i.size) == (0, 0)]}
    rep["armatures"] = [{"name": o.name, "bones": len(o.data.bones)}
                        for o in bpy.data.objects if o.type == 'ARMATURE']
    head_mesh = [o for o in meshes if o.name.startswith("Head_") and len(o.data.vertices) > 200]
    rep["head_bbox"] = bbox_of(head_mesh) if head_mesh else None

    write_readme("试穿合成：" + name, [
        "来源：Modular Character Outfits - Fantasy[Standard] 的 %s 套装" % job["outfit"],
        "      + Universal Base Characters[Standard] 的 %s 头部" % job["head"],
        ("      + 发型 %s" % job["hair"]) if job["hair"] else "      （Ranger 有兜帽，未加发型）",
        "",
        "做法：按 Readme「服装只需头部」裁剪 Base Characters 身体 mesh —— 只保留",
        "      顶点组 Head / neck_01 权重和 > %.1f 的顶点，其余删除；再把头部 3 个 mesh" % HEAD_WEIGHT_MIN,
        "      重新挂到**服装自带的 rig**上（不删服装骨架、不复用 UBC 骨架），",
        "      因此本文件只有一根 %d 骨 rig，可直接做动画。" % len(rig.data.bones),
        "",
        "为什么不用权重迁移：两套资产骨名逐根相同，且 Head / neck_01 的 rest 变换逐位一致",
        "（Head (0, 0.0829, 0)、neck_01 (0, 0.2151, 0)），差异只在 upperarm_l / thigh_l（肩宽/胯宽）。",
        "所以头部 mesh 直接绑定到服装 rig 即落在正确位置；服装是 Regular 体型，",
        "UBC 标准版只有 Superhero 体型 —— 颈部/肩部细小差异属于上游体型差异，非绑定错误。",
        "",
        "许可：两包均为 CC0 1.0（商用免署名），作者 Quaternius。",
        "注意：本文件是 GLTF→Blender 反向生成 + 脚本合成的结果，不是作者原始 .blend。",
    ])

    out = os.path.join(OUT, name + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    rep["out"] = out
    rep["size_mb"] = round(os.path.getsize(out) / 1048576, 2)

    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 700, 1000
    sc.render.image_settings.file_format = 'PNG'
    sc.render.filepath = os.path.join(OUT, "preview", name + ".png")
    try:
        bpy.ops.render.render(write_still=True)
        rep["preview"] = sc.render.filepath
    except Exception as e:
        rep["preview_error"] = str(e)
    REPORT[name] = rep
    print("  saved %.2f MB | rig %d 骨 | head cut %s | imgs %s" % (
        rep["size_mb"], rep["final_rig_bones"], rep.get("head_cut", {}).get("kept_pct"),
        rep["images"]), flush=True)

with open(os.path.join(OUT, "tryon-report.json"), "w", encoding="utf-8") as fh:
    json.dump(REPORT, fh, ensure_ascii=False, indent=1)
print("TRYON DONE")