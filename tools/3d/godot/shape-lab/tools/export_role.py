# -*- coding: utf-8 -*-
"""shape-lab 烘焙器 · Blender 侧单角色导出器（.blend → .glb，贴图内嵌）。

只用一次 Blender 进程导一个角色，便于把失败精确定位到某个文件。由 `bake.py` 驱动调用：

    "<blender>" --background --factory-startup --python-exit-code 1 \
        --python tools/3d/godot/shape-lab/tools/export_role.py -- \
        --src <src.blend> --dst <dst.glb> [--report <export.json>]

导出配方**逐项照抄** `tools/3d/godot/preview/blender/export_glb.py`（该文件已实测可用）：

  * `open_mainfile` → **内存里**把所有 shape key value 清零（绝不 save 回源文件）；
  * 删掉相机 / 灯（`.blend` 里带着预览相机与灯，会顶掉 Godot 侧取景）；
  * `export_format="GLB"`、`export_morph=True`、`export_morph_normal=True`、`export_skins=True`、
    **`export_apply=False`**（True 会把 Armature 修改器烘掉，等于毁掉换装/蒙皮）、
    `export_animations=False`、`export_cameras/lights=False`；
  * 导出参数名跨 Blender 版本变过 → 逐项查 `get_rna_type().properties` 里存在才设。

额外（本任务新增，已报备 lead）：
  * **剔除"杂散网格"**：无材质 + 无顶点组 + 无 ARMATURE 修改器的 MESH 对象（两个标准体里各有一个
    `Icosphere`，42 顶点 / 80 面、以原点为心半径 1 m）。它不是角色的一部分，留在 glb 里会在
    Godot 预览里变成一个罩住脚部的大球。剔除对象会记进 EXPORT_JSON 的 `removed` 字段。
  * 打印 `EXPORT_JSON {...}` 一行，供驱动组 manifest：网格（顶点/面/材质/shape key/顶点组）、
    骨架（名字/骨数）、以及三份高度量测（骨架 rest 世界 Z 范围 / 网格 rest 世界 Z 范围 / 逐件 Z 范围）。

本脚本不写回任何 `assets/**` 文件。
"""
import json
import os
import sys

import bpy

MORPH_CONTRACT = ("BS_Thin", "BS_Heavy")


def _parse_argv(argv):
    out = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--"):
            key = tok[2:]
            val = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else "1"
            out[key] = val
            i += 2
        else:
            i += 1
    return out


def _world_z_range(ob):
    """对象的 rest 世界 Z 范围（matrix_world @ 顶点局部坐标）。"""
    mw = ob.matrix_world
    zmin = zmax = None
    for v in ob.data.vertices:
        z = (mw @ v.co).z
        if zmin is None or z < zmin:
            zmin = z
        if zmax is None or z > zmax:
            zmax = z
    if zmin is None:
        return None
    return [round(zmin, 6), round(zmax, 6)]


def _is_debris(ob):
    """无材质 + 无顶点组 + 无骨架修改器 → 判定为杂散网格（保守三条件同时满足）。"""
    if ob.type != 'MESH':
        return False
    if [m for m in ob.data.materials if m is not None]:
        return False
    if len(ob.vertex_groups) > 0:
        return False
    if any(m.type == 'ARMATURE' for m in ob.modifiers):
        return False
    return True


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    args = _parse_argv(argv)
    src = args["src"]
    dst = args["dst"]
    report_path = args.get("report")

    bpy.ops.wm.open_mainfile(filepath=src)

    # ① shape key 值清零（只在内存里改，不 save）
    zeroed = []
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.data.shape_keys:
            for kb in ob.data.shape_keys.key_blocks:
                kb.value = 0.0
            zeroed.append(ob.name)

    # ② 删相机 / 灯
    removed = []
    for ob in list(bpy.data.objects):
        if ob.type in {'CAMERA', 'LIGHT'}:
            removed.append({"name": ob.name, "type": ob.type, "reason": "camera_or_light",
                            "verts": None, "polys": None, "z_range": None})
            bpy.data.objects.remove(ob, do_unlink=True)

    # ③ 剔除杂散网格（见文件头说明）
    for ob in list(bpy.data.objects):
        if _is_debris(ob):
            removed.append({"name": ob.name, "type": ob.type, "reason": "debris_no_material_no_weights",
                            "verts": len(ob.data.vertices), "polys": len(ob.data.polygons),
                            "z_range": _world_z_range(ob)})
            bpy.data.objects.remove(ob, do_unlink=True)

    # ④ 导出参数（照抄 preview/blender/export_glb.py；逐项确认 RNA 里存在）
    props = bpy.ops.export_scene.gltf.get_rna_type().properties
    kw = {"filepath": dst, "export_format": "GLB"}
    wanted = {
        "export_apply": False,          # 千万不能 True：会把 Armature 修改器烘掉
        "export_morph": True,           # shape key → glTF morph target
        "export_morph_normal": True,
        "export_skins": True,
        "export_yup": True,
        "export_cameras": False,
        "export_lights": False,
        "use_selection": False,
        "export_animations": False,     # 静态预览，不需要动画
        "export_def_bones": False,
        "export_tangents": False,
        "export_materials": "EXPORT",
        "export_image_format": "AUTO",
        "export_extras": False,
        "export_reset_pose_bones": False,
        "export_all_influences": False,
        "export_hierarchy_full_collections": False,
    }
    applied = {}
    missing = []
    for k, v in wanted.items():
        if k in props:
            kw[k] = v
            applied[k] = v
        else:
            missing.append(k)

    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    bpy.ops.export_scene.gltf(**kw)

    # ⑤ 导出后的事实（组 manifest 用）
    meshes = {}
    mesh_z_all = [None, None]
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        zr = _world_z_range(ob)
        sk = [k.name for k in ob.data.shape_keys.key_blocks] if ob.data.shape_keys else []
        used = set()
        for poly in ob.data.polygons:
            used.update(poly.vertices)
        meshes[ob.name] = {
            "verts": len(ob.data.vertices),
            "faces": len(ob.data.polygons),
            "materials": [m.name for m in ob.data.materials if m is not None],
            "shape_keys": sk,
            "morph_names": [n for n in MORPH_CONTRACT if n in sk],
            "vertex_groups": len(ob.vertex_groups),
            "armature_modifier": any(m.type == 'ARMATURE' for m in ob.modifiers),
            "parent": ob.parent.name if ob.parent else None,
            "z_range": zr,
            # glTF 只导出被面引用的顶点 → 自检要用"被引用顶点数"，不是 len(vertices)。
            # 实测：两具男装的 Head_SuperHero_Male 有 7 个游离顶点（1562 → 1555）+ 6 条游离边。
            "verts_referenced": len(used),
            "verts_loose": len(ob.data.vertices) - len(used),
            "edges": len(ob.data.edges),
            "loose_edges": sum(1 for e in ob.data.edges
                               if not any(v in used for v in e.vertices)),
        }
        if zr:
            for i, z in enumerate(zr):
                if mesh_z_all[i] is None or (z < mesh_z_all[i] if i == 0 else z > mesh_z_all[i]):
                    mesh_z_all[i] = z

    armatures = []
    for ob in bpy.data.objects:
        if ob.type != 'ARMATURE':
            continue
        mw = ob.matrix_world
        zs = []
        for b in ob.data.bones:
            zs.append((mw @ b.head_local).z)
            zs.append((mw @ b.tail_local).z)
        armatures.append({
            "name": ob.name,
            "bones": len(ob.data.bones),
            "bone_names": sorted(b.name for b in ob.data.bones),
            "z_min": round(min(zs), 6),
            "z_max": round(max(zs), 6),
            "z_range": round(max(zs) - min(zs), 6),
            "scale": [round(s, 6) for s in ob.scale],
        })

    rep = {
        "src": src,
        "dst": dst,
        "bytes": os.path.getsize(dst),
        "blender_version_string": bpy.app.version_string,
        "blender_version_cycle": getattr(bpy.app, "version_cycle", None),
        "export_kw_applied": applied,
        "export_kw_missing": missing,
        "zeroed_shape_key_objects": sorted(zeroed),
        "removed": removed,
        "meshes": meshes,
        "mesh_z_all": mesh_z_all,
        "mesh_z_range_all": (round(mesh_z_all[1] - mesh_z_all[0], 6)
                             if mesh_z_all[0] is not None and mesh_z_all[1] is not None else None),
        "armatures": armatures,
        "images": [{"name": im.name, "size": list(im.size),
                    "packed": bool(im.packed_file), "filepath": im.filepath}
                   for im in bpy.data.images],
    }
    print("EXPORT_JSON " + json.dumps(rep, ensure_ascii=False))
    if report_path:
        os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)


main()
