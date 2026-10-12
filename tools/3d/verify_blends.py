#!/usr/bin/env python3
"""verify_blends.py —— 由 Blender 执行：逐份打开 download/ubc-blend/*.blend，
从**已落盘的 .blend 文件**重新测量验收指标（不依赖转换时的内存结果）。

每份输出一行 `VERIFY_RESULT {json}`，最后一行 `VERIFY_DONE n`。
用法：
  "/Applications/Blender.app/Contents/MacOS/Blender" -b --factory-startup \
      --python download/ubc-blend/tools/verify_blends.py 2>&1 | tee -a tmp/pack2blend/logs/ubc.log
"""
import bpy
import glob
import json
import os
import struct

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OUT = ROOT + "/download/ubc-blend"
HELPER = "glTF_not_exported"
EXPECTED_WH = {"UBC_Standard_ALL.blend": [1600, 1000]}


def png_size(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return list(struct.unpack(">II", head[16:24]))
    except Exception:  # noqa: BLE001
        return None


def main():
    blends = sorted(glob.glob(OUT + "/*.blend"))
    for path in blends:
        bpy.ops.wm.open_mainfile(filepath=path)
        base = os.path.basename(path)
        meshes, unskinned, tris, verts, detail = [], [], 0, 0, []
        for o in bpy.data.objects:
            if o.type != 'MESH' or not o.data:
                continue
            if any(c.name == HELPER for c in o.users_collection):
                continue
            o.data.calc_loop_triangles()
            t = len(o.data.loop_triangles)
            tris += t
            verts += len(o.data.vertices)
            arm_mod = [m.object.name if m.object else None for m in o.modifiers
                       if m.type == 'ARMATURE']
            has_arm = bool([m for m in o.modifiers if m.type == 'ARMATURE'])
            meshes.append(o.name)
            if not has_arm:
                unskinned.append(o.name)
            detail.append({"name": o.name, "tris": t, "verts": len(o.data.vertices),
                           "vgroups": len(o.vertex_groups),
                           "armature_mod": has_arm, "armature": arm_mod})
        rigs = [{"name": o.name, "bones": len(o.data.bones)}
                for o in bpy.data.objects if o.type == 'ARMATURE']
        imgs = [i for i in bpy.data.images if i.name != 'Render Result']
        size_zero = [i.name for i in imgs if tuple(i.size) == (0, 0)]
        packed_bytes_zero = [i.name for i in imgs
                             if i.packed_file is not None and i.packed_file.size == 0]
        preview = os.path.join(OUT, "preview", base[:-6] + ".png")
        pv = {"out": preview, "exists": os.path.exists(preview),
              "expected_wh": EXPECTED_WH.get(base, [600, 800])}
        if pv["exists"]:
            pv["bytes"] = os.path.getsize(preview)
            pv["wh"] = png_size(preview)
            pv["wh_ok"] = pv["wh"] == pv["expected_wh"]
        res = {
            "out": path,
            "size_mb": round(os.path.getsize(path) / 1048576, 2),
            "mesh_count": len(meshes),
            "meshes": meshes,
            "mesh_detail": detail,
            "unskinned": unskinned,
            "rigs": rigs,
            "tris": tris,
            "verts": verts,
            "images": {"total": len(imgs),
                       "packed": len([i for i in imgs if i.packed_file is not None]),
                       "unpacked": [i.name for i in imgs if i.packed_file is None],
                       "size_zero": size_zero,
                       "packed_bytes_zero": packed_bytes_zero},
            "collections": sorted(c.name for c in bpy.data.collections
                                  if c.name != HELPER),
            "readme_text": any(t.name == "README_转换说明" for t in bpy.data.texts),
            "preview": pv,
            "ok": True,
        }
        print("VERIFY_RESULT " + json.dumps(res, ensure_ascii=False), flush=True)
    print("VERIFY_DONE %d" % len(blends), flush=True)


main()