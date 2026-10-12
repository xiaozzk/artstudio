#!/usr/bin/env python3
"""pack2blend.py —— 由 Blender 执行：把一批 glTF / FBX 批量转成自包含 .blend

用法（在工作区根执行）：
  "/Applications/Blender.app/Contents/MacOS/Blender" -b --factory-startup \
      --python tools/3d/pack2blend.py -- <spec.json>

spec.json:
{
  "jobs": [
    {
      "out":       "/abs/path/out.blend",            # 必填
      "title":     "显示名",
      "notes":     "写进 .blend 内 README 的额外说明",
      "imports":   [ {"format": "gltf"|"fbx", "file": "/abs/x.gltf", "collection": "A/B"} ],
      "relink":    {"enabled": true, "search_dirs": ["/abs/Textures", "/abs/gltf"]},
                   # enabled 默认 true；即使不写，也会用各 import 文件所在目录重链坏引用
      "preview":   {"out": "/abs/p.png", "w": 900, "h": 1200, "layout": "none"|"grid"},
      "grid":      {"dx": 1.35, "dy": 1.75}
    }
  ]
}

每个 job 输出一行 `JOB_RESULT {json}`，便于上游脚本汇总。
写作用域约定：本脚本只写 spec 里显式声明的 out / preview.out，不碰别的路径。
"""
import bpy
import json
import math
import os
import sys
from mathutils import Vector

HELPER = "glTF_not_exported"   # glTF 导入器放"骨骼显示辅助体"的集合


# ---------------------------------------------------------------- 基础工具
def argv_spec():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("需要 spec 路径：... -- <spec.json>")
    return argv[argv.index("--") + 1]


def fresh(scene_name, engine="BLENDER_EEVEE"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.name = scene_name
    try:
        sc.unit_settings.system = 'METRIC'
    except Exception:
        pass
    for name in (engine, "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"):
        try:
            sc.render.engine = name
            break
        except Exception:
            continue
    return sc


def new_coll(name, parent=None):
    coll = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(coll)
    return coll


def import_one(entry, coll):
    """导入单个文件；真实资产移进 coll，导入器辅助体留在 HELPER 集合里（不渲染）。"""
    path = entry["file"]
    fmt = entry.get("format", "gltf").lower()
    before = set(bpy.data.objects)
    if fmt == "gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    elif fmt == "fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise SystemExit("不支持的 format: " + fmt)
    new = [o for o in bpy.data.objects if o not in before]
    real = []
    for o in new:
        if any(c.name == HELPER for c in o.users_collection):
            continue
        real.append(o)
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    rig_name = "RIG_" + os.path.basename(path).rsplit(".", 1)[0]
    for a in [o for o in real if o.type == 'ARMATURE']:
        a.name = rig_name
        a.data.name = rig_name
    return real


def hide_helpers():
    for c in bpy.data.collections:
        if c.name == HELPER:
            c.hide_render = True
            c.hide_viewport = True


def _name_candidates(base):
    """坏引用兜底：上游包存在 T_Eye_Normal_png.png 这类写错的名字，实际文件是 T_Eye_Normal.png。"""
    stem, ext = os.path.splitext(base)
    cands = [base]
    if stem.endswith("_png"):
        cands.append(stem[:-4] + ext)
    if stem.endswith("_normal") and not stem.endswith("_Normal"):
        pass
    return cands


def relink_images(search_dirs):
    """贴图重链：
    - FBX 里贴图常是作者机器的绝对路径（C:/Dropbox/...）→ 按文件名找回；
    - glTF 里也存在写错的名字（T_Eye_Normal_png.png）→ 归一化后再找。
    只对『当前路径不存在』的 image 生效。"""
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
        found = None
        for cand in _name_candidates(base):
            hit = index.get(cand.lower())
            if hit:
                found = hit
                break
        if found:
            img.filepath = found
            img.filepath_raw = found
            img.reload()
            fixed.append({"image": img.name, "orig_name": base,
                          "path": found, "renamed": os.path.basename(found) != base})
        else:
            missing.append({"image": img.name, "orig": img.filepath})
    return fixed, missing


def top_level():
    """顶层件 = 无父级、非相机/灯光、且不属于导入器辅助集合（否则 grid 会多排隐藏的骨骼辅助体）。"""
    return [o for o in bpy.data.objects
            if o.parent is None and o.type not in ('CAMERA', 'LIGHT')
            and not any(c.name == HELPER for c in o.users_collection)]


def layout_grid(dx=2.4, dy=2.6):
    """dx 默认 2.4 m：角色 A-pose 臂展约 1.86 m，太小会互相穿模。"""
    objs = sorted(top_level(), key=lambda x: x.name)
    cols = max(1, math.ceil(math.sqrt(len(objs))))
    for i, o in enumerate(objs):
        r, c = divmod(i, cols)
        o.location.x += (c - (cols - 1) / 2.0) * dx
        o.location.y += r * dy


def bbox_of_meshes():
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    n = 0
    for o in bpy.data.objects:
        if o.type != 'MESH' or not o.data:
            continue
        if any(c.name == HELPER for c in o.users_collection):
            continue
        n += 1
        mw = o.matrix_world
        for corner in o.bound_box:
            w = mw @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    if n == 0:
        return None
    return {"min": [round(x, 4) for x in lo], "max": [round(x, 4) for x in hi],
            "size": [round(hi[i] - lo[i], 4) for i in range(3)]}


def setup_stage():
    sc = bpy.context.scene
    # 关键：layout_grid() 改过对象 location 后必须刷新，否则 matrix_world 还是旧的 → 相机会按旧 bbox 取景而裁掉内容
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    bb = bbox_of_meshes()
    if not bb:
        return
    center = Vector([(bb["min"][i] + bb["max"][i]) / 2.0 for i in range(3)])
    size = max(bb["size"][0], bb["size"][1], bb["size"][2], 0.1)
    cd = bpy.data.cameras.new("Camera")
    cd.lens = 55
    cam = bpy.data.objects.new("Camera", cd)
    cam.location = (center.x, center.y - size * 2.6, center.z + size * 0.08)
    cam.rotation_euler = (center - Vector(cam.location)).to_track_quat('-Z', 'Y').to_euler()
    sc.collection.objects.link(cam)
    sc.camera = cam
    sd = bpy.data.lights.new("Sun", 'SUN')
    sd.energy = 4.0
    sun = bpy.data.objects.new("Sun", sd)
    sun.rotation_euler = (math.radians(52), 0, math.radians(35))
    sc.collection.objects.link(sun)
    fd = bpy.data.lights.new("Fill", 'AREA')
    fd.energy = 200
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


def render_to(path, w, h):
    sc = bpy.context.scene
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.image_settings.file_format = 'PNG'
    sc.render.filepath = path
    try:
        bpy.ops.render.render(write_still=True)
        return {"ok": True, "engine": sc.render.engine}
    except Exception as e:
        sc.render.engine = 'BLENDER_WORKBENCH'
        try:
            bpy.ops.render.render(write_still=True)
            return {"ok": True, "engine": sc.render.engine, "fallback": str(e)}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}


def write_readme(title, src_files, coll_names, notes):
    t = bpy.data.texts.new("README_转换说明")
    t.write(
        "%s\n%s\n\n"
        "由 glTF/FBX 反向生成的 .blend（不是作者原始文件）\n"
        "生成：Blender 5.2.2 headless + tools/3d/pack2blend.py\n"
        "许可：CC0 1.0 Universal（商用免署名）。作者 Quaternius — https://quaternius.com\n"
        "%s\n"
        "源文件\n------\n%s\n\n"
        "集合\n----\n%s\n\n"
        "骨架\n----\n65 骨通用人形 rig，骨名与 Universal Base Characters 一致\n"
        "（root/pelvis/spine_01..03/neck_01/Head/clavicle_l/upperarm_l/.../thigh_l/calf_l/foot_l/ball_l）。\n\n"
        "注意\n----\n"
        "* 网格/蒙皮/UV/骨骼/材质(Principled BSDF) 齐全，贴图已全部 pack（自包含）。\n"
        "* 没有作者原始 .blend 的编辑历史与自定义节点组（Source 版才有）。\n"
        "* glTF 中除 COLOR_0 外的额外顶点色通道 Blender 不保留（本系列实测为纯白，无损失）。\n"
        "* 集合 %s 是 glTF 导入器的骨骼显示辅助体，已设为不渲染；删掉会让骨骼显示变形。\n"
        % (title, "=" * len(title), notes, "\n".join("  - " + s for s in src_files),
           "\n".join("  - " + c for c in coll_names), HELPER)
    )


# ---------------------------------------------------------------- 主流程
def run_job(job):
    title = job.get("title") or os.path.basename(job["out"])
    fresh(title)
    coll_names = []
    for entry in job.get("imports", []):
        coll = new_coll(entry.get("collection") or "Assets")
        import_one(entry, coll)
        coll_names.append(coll.name)
    hide_helpers()

    relink_cfg = job.get("relink", {})
    enabled = relink_cfg.get("enabled", True)   # 默认开：兜住上游坏引用/绝对路径
    dirs = list(relink_cfg.get("search_dirs", []))
    dirs += [os.path.dirname(e["file"]) for e in job.get("imports", [])]
    relink_info = {"enabled": enabled, "search_dirs": dirs, "fixed": [], "missing": []}
    if enabled:
        fixed, missing = relink_images(dirs)
        relink_info["fixed"] = fixed
        relink_info["missing"] = missing

    layout = (job.get("preview") or {}).get("layout", "none")
    extra_note = ""
    if layout == "grid":
        g = job.get("grid", {})
        layout_grid(g.get("dx", 2.4), g.get("dy", 2.6))
        extra_note = ("\n* 本文件是**总览布局**：各件按网格排开（非原点对齐），便于在一个视图里浏览全部内容。\n"
                      "  需要原点对齐、可装配的单件请用同一批产出的 per-asset 单件 .blend。\n")

    setup_stage()
    try:
        bpy.ops.file.pack_all()
    except Exception as e:
        print("WARN pack_all:", e)

    write_readme(title, [e["file"] for e in job.get("imports", [])], coll_names,
                 (job.get("notes", "") + extra_note))

    verts = tris = 0
    meshes = []
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.data and not any(c.name == HELPER for c in o.users_collection):
            v = len(o.data.vertices)
            o.data.calc_loop_triangles()
            t = len(o.data.loop_triangles)
            verts += v
            tris += t
            meshes.append({"name": o.name, "verts": v, "tris": t,
                           "vgroups": len(o.vertex_groups),
                           "skinned": any(m.type == 'ARMATURE' and m.object for m in o.modifiers)})
    rigs = [{"name": o.name, "bones": len(o.data.bones)} for o in bpy.data.objects if o.type == 'ARMATURE']
    imgs = [i for i in bpy.data.images if i.name != 'Render Result']
    out = job["out"]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)

    res = {
        "out": out,
        "size_mb": round(os.path.getsize(out) / 1048576, 2),
        "objects": len(bpy.data.objects),
        "meshes": meshes,
        "mesh_count": len(meshes),
        "unskinned": [m["name"] for m in meshes if not m["skinned"]],
        "rigs": rigs,
        "verts": verts,
        "tris": tris,
        "bbox": bbox_of_meshes(),
        "images": {"total": len(imgs),
                   "packed": len([i for i in imgs if i.packed_file is not None]),
                   "size_zero": [i.name for i in imgs if tuple(i.size) == (0, 0)]},
        "materials": sorted(m.name for m in bpy.data.materials),
        "collections": coll_names,
        "relink": relink_info,
    }
    pv = job.get("preview")
    if pv:
        res["preview"] = render_to(pv["out"], pv.get("w", 900), pv.get("h", 1200))
        res["preview"]["out"] = pv["out"]
    return res


def main():
    spec_path = argv_spec()
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    jobs = spec["jobs"] if isinstance(spec, dict) else spec
    for i, job in enumerate(jobs):
        try:
            res = run_job(job)
            res["index"] = i
            res["ok"] = True
        except Exception as e:
            import traceback
            traceback.print_exc()
            res = {"index": i, "ok": False, "out": job.get("out"), "error": str(e)}
        print("JOB_RESULT " + json.dumps(res, ensure_ascii=False), flush=True)
    print("PACK2BLEND_DONE jobs=%d" % len(jobs), flush=True)


main()