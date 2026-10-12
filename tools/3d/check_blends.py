"""accept.py —— Lead 终验：一份 spec 列出的所有 .blend 逐份重开断言（只读）

用法：
  "/Applications/Blender.app/Contents/MacOS/Blender" -b --factory-startup \
      --python tools/3d/check_blends.py -- <manifest.json>
manifest.json: {"blends": ["/abs/a.blend", ...]}
每份输出一行 ACCEPT_RESULT {json}。
"""
import bpy
import json
import os
import sys
from mathutils import Vector

HELPER = "glTF_not_exported"


def helper_names():
    for c in bpy.data.collections:
        if c.name == HELPER:
            return [o.name for o in c.objects], c.hide_render
    return [], None


def bbox(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        mw = o.matrix_world
        for corner in o.bound_box:
            w = mw @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    if not objs:
        return None
    return {"size": [round(hi[i] - lo[i], 3) for i in range(3)]}


def check(path):
    bpy.ops.wm.open_mainfile(filepath=path)
    base = os.path.basename(path)
    low = path.lower()
    # 上游资产本身分两类：蒙皮件（65 骨 rig）与静态件（Origin at 0 发型，源无骨架）。
    # 静态件识别：文件名含 __Origin0、或所在目录含 origin0（FBX 侧按目录命名）、或 *_ALL 混装件。
    static_allowed = ("origin0" in low) or ("_all." in low) or base.startswith("MCO-Fantasy")
    helpers, helper_hidden = helper_names()
    rigs = [o for o in bpy.data.objects if o.type == 'ARMATURE']
    real = [o for o in bpy.data.objects
            if o.type == 'MESH' and o.data and o.name not in helpers]
    unskinned, groups_zero, statics, defects = [], [], [], []
    tris = verts = 0
    for o in real:
        verts += len(o.data.vertices)
        o.data.calc_loop_triangles()
        tris += len(o.data.loop_triangles)
        has_mod = any(m.type == 'ARMATURE' and m.object for m in o.modifiers)
        ngroups = len(o.vertex_groups)
        if has_mod and ngroups > 0:
            continue
        if not has_mod and ngroups == 0:
            statics.append(o.name)
            continue
        defects.append("%s(mod=%s,vgroups=%d)" % (o.name, has_mod, ngroups))
        if has_mod:
            groups_zero.append(o.name)
        else:
            unskinned.append(o.name)
    imgs = [i for i in bpy.data.images if i.name != 'Render Result']
    # 贴图两种形态都算合格：① pack 在 .blend 内；② 外部文件（共享贴图库，相对路径可解析）。
    # 2026-10 去重改造后，assets/3d/blend/ 一律走外部共享 textures/，故不能再要求 packed==total。
    def _resolved(i):
        if i.packed_file is not None:
            return True
        fp = bpy.path.abspath(i.filepath) if i.filepath else ""
        return bool(fp) and os.path.exists(fp)
    packed = [i for i in imgs if i.packed_file is not None]
    external = [i for i in imgs if i.packed_file is None and _resolved(i)]
    dangling = [{"image": i.name, "filepath": i.filepath} for i in imgs if not _resolved(i)]
    size0 = [i.name for i in imgs if tuple(i.size) == (0, 0)]
    mats_tex = [m.name for m in bpy.data.materials
                if m.use_nodes and any(n.type == 'TEX_IMAGE' and n.image for n in m.node_tree.nodes)]
    checks = {
        "has_rig": len(rigs) >= 1,
        "all_65_bones": bool(rigs) and all(len(o.data.bones) == 65 for o in rigs),
        "mesh_count": len(real),
        "skinned_count": len(real) - len(statics) - len(defects),
        "static_count": len(statics),
        "static_allowed": static_allowed,
        "unskinned": unskinned,
        "vertex_groups_zero": groups_zero,
        "defects": defects,
        "images_total": len(imgs),
        "images_packed": len(packed),
        "images_external": len(external),
        "images_dangling": dangling,
        "images_size_zero": size0,
        "materials_with_texture": len(mats_tex),
        "helper_hidden": (helper_hidden is True) if helper_hidden is not None else True,
        "text_blocks": [t.name for t in bpy.data.texts],
    }
    ok = (not defects
          and (checks["has_rig"] or static_allowed)
          and (static_allowed or not statics)
          and len(imgs) > 0 and not dangling and not size0
          and checks["materials_with_texture"] >= 1 and checks["helper_hidden"])
    return {
        "path": path,
        "size_mb": round(os.path.getsize(path) / 1048576, 2),
        "rigs": [{"name": o.name, "bones": len(o.data.bones)} for o in rigs],
        "verts": verts, "tris": tris,
        "materials": len(bpy.data.materials),
        "bbox": bbox(real),
        "checks": checks,
        "ok": ok,
    }


def main():
    manifest = sys.argv[sys.argv.index("--") + 1]
    with open(manifest, encoding="utf-8") as fh:
        paths = json.load(fh)["blends"]
    for p in paths:
        try:
            res = check(p)
        except Exception as e:
            import traceback
            traceback.print_exc()
            res = {"path": p, "ok": False, "error": str(e)}
        print("ACCEPT_RESULT " + json.dumps(res, ensure_ascii=False), flush=True)
    print("ACCEPT_DONE files=%d" % len(paths), flush=True)


main()