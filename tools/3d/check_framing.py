#!/usr/bin/env python3
"""check_all_framing.py —— 由 Blender 执行：量化 UBC_Standard_ALL.blend 的 grid 预览取景。

用途：判断 layout=grid 的总览图里是否有件被画幅裁切、以及相邻件是否互相穿插。
只读 .blend，不写任何文件；输出一行 `FRAMING_RESULT {json}`。
"""
import bpy
import json
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

BLEND = ("/Users/zhenkunzhu/Desktop/project/artstudio/download/ubc-blend/"
         "UBC_Standard_ALL.blend")
HELPER = "glTF_not_exported"
W, H = 1600, 1000   # spec 里 ALL 的 preview 分辨率（.blend 内保存的是 Blender 默认 1920x1080）


def main():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    sc = bpy.context.scene
    cam = sc.camera
    items, helpers = [], []
    for o in bpy.data.objects:
        if o.type not in ('MESH', 'ARMATURE') or o.parent is not None:
            continue
        if o.type == 'MESH' and not o.data:
            continue
        helper = any(c.name == HELPER for c in o.users_collection)
        xs, ys = [], []
        for corner in o.bound_box:
            p = world_to_camera_view(sc, cam, o.matrix_world @ Vector(corner))
            xs.append(p.x * W)
            ys.append((1.0 - p.y) * H)
        rec = {"name": o.name, "type": o.type,
               "px": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]}
        (helpers if helper else items).append(rec)

    def clipped(it):
        x0, y0, x1, y1 = it["px"]
        return x0 < 0 or y0 < 0 or x1 > W or y1 > H

    def overlap(a, b):
        ax0, ay0, ax1, ay1 = a["px"]
        bx0, by0, bx1, by1 = b["px"]
        ox = min(ax1, bx1) - max(ax0, bx0)
        oy = min(ay1, by1) - max(ay0, by0)
        if ox > 0 and oy > 0:
            return [ox, oy]
        return None

    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ov = overlap(items[i], items[j])
            if ov:
                pairs.append({"a": items[i]["name"], "b": items[j]["name"],
                              "overlap_px": ov})
    inside = [i["name"] for i in items if not clipped(i)]
    outside = [i["name"] for i in items if clipped(i)]
    res = {"blend": BLEND, "resolution": [W, H],
           "camera": {"loc": [round(v, 3) for v in cam.location], "lens": cam.data.lens},
           "top_level_items": len(items) + len(helpers),
           "asset_items": len(items), "helper_items": len(helpers),
           "fully_inside": len(inside), "inside": inside,
           "clipped": [i for i in items if clipped(i)], "clipped_names": outside,
           "helper_names": [h["name"] for h in helpers],
           "overlap_pairs": pairs, "items": items}
    print("FRAMING_RESULT " + json.dumps(res, ensure_ascii=False), flush=True)


main()