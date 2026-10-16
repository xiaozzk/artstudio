#!/usr/bin/env python3
"""白模展示 / 体检图：4 个全身视角 + 手·头·脚特写（男女各一张）。

**为什么用 A-pose**：T-pose 的腋下拉伸会干扰"看造型"这件事（低模 + 47° 大角度的必然代价，见 SPEC F37）。
A-pose 是这具白模的**原始姿态**，看它"本来长什么样"才是这个脚本的目的。

**为什么带特写**：白模的弱项集中在**手（连指手套形）/ 头（无五官，因为头要单独建模）/ 脚**，
全身图看不出来。这一排就是给"值不值得当基础"下判断用的。

用法：
    Blender -b --factory-startup --python-exit-code 1 \
      --python tools/3d/skeleton/render_white_model.py -- --out tmp/whitemodel
    python3 tools/3d/skeleton/compose_white_model.py --dir tmp/whitemodel
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_body_reference import BODIEZ, RACE, bbox, reset  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
# (标签, 绕 Z 方位角°, 俯仰°, 取景高度比例)
VIEWS = [("front", 0.0, 0.0, 1.0), ("three_quarter", 45.0, 6.0, 1.0),
         ("side", 90.0, 0.0, 1.0), ("back", 180.0, 0.0, 1.0)]
# 特写：**按区域质心自动对准**（手在 x≈±0.6，对准身体中轴只会拍到胯 —— 第一版就踩了）
HAND_PAT = r"hand|thumb|f_(index|middle|ring|pinky)|palm"
CLOSEUPS = [("hand", "hand"), ("head", "head"), ("foot", "foot")]
PX = 760.0


def args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    o = {"out": "tmp/whitemodel"}
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            o["out"] = argv[i + 1]
    return o


def world_verts(body) -> list:
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    me = ev.to_mesh()
    ps = [(v.index, ev.matrix_world @ v.co) for v in me.vertices]
    ev.to_mesh_clear()
    return ps


def region_center(body, bb: dict, kind: str) -> tuple:
    """返回 (中心 Vector, 取景尺寸)。**按区域自动对准**，不猜坐标。"""
    ps = world_verts(body)
    H = bb["z"][1] - bb["z"][0]
    if kind == "hand":
        gi = {g.index for g in body.vertex_groups if re.search(HAND_PAT, g.name, re.I)}
        sel = [p for i, p in ps
               if i < len(body.data.vertices)
               and sum(g.weight for g in body.data.vertices[i].groups if g.group in gi) > 0.5]
        if not sel:
            sel = [p for _, p in ps if abs(p.x) > bb["x"][1] * 0.75]
    elif kind == "head":
        sel = [p for _, p in ps if p.z > bb["z"][0] + H * 0.90]
    else:
        sel = [p for _, p in ps if p.z < bb["z"][0] + H * 0.06]
    # ⚠ 手/脚是**左右成对**的：取两只的质心会落回中轴 x=0（第一版又踩了）→ 只取一侧
    if kind in ("hand", "foot"):
        one = [p for p in sel if p.x > 0]
        if one:
            sel = one
    cx = sum(p.x for p in sel) / len(sel)
    cz = sum(p.z for p in sel) / len(sel)
    ext = max(max(p.x for p in sel) - min(p.x for p in sel),
              max(p.z for p in sel) - min(p.z for p in sel))
    return Vector((cx, 0, cz)), ext * 1.6


def shoot(center: Vector, az: float, elev: float, ortho: float,
          rx: int, ry: int, path: str) -> None:
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = rx, ry
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGB"
    cam = bpy.data.cameras.new("c")
    cam.type = "ORTHO"
    cam.ortho_scale = max(rx, ry) / PX
    co = bpy.data.objects.new("c", cam)
    scene.collection.objects.link(co)
    d = Vector((math.sin(math.radians(az)), -math.cos(math.radians(az)),
                math.tan(math.radians(elev)))).normalized()
    co.location = center + d * 8.0
    co.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    scene.camera = co
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.studio_light = "Default"
    sh.color_type = "MATERIAL"
    sh.show_shadows = True
    sh.shadow_intensity = 0.35
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(co, do_unlink=True)


def main() -> None:
    a = args()
    outdir = os.path.join(REPO, a["out"])
    raw = os.path.join(outdir, "raw")
    os.makedirs(raw, exist_ok=True)
    spec = json.load(open(RACE, encoding="utf-8"))
    targets = {s["id"]: s["mesh_height_m"] for s in spec["sexes"]}
    meta = {}

    for sex in ("female", "male"):
        bpy.ops.wm.open_mainfile(filepath=os.path.join(BODIEZ, f"modular_{sex}_base.blend"))
        arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
        body = next(o for o in bpy.data.objects if o.type == "MESH"
                    and o.name.startswith("Geo_") and "Body" in o.name)
        for o in bpy.data.objects:
            if o.type == "MESH" and o is not body:
                o.hide_render = True
            if o.type in ("LIGHT", "CAMERA", "FONT"):
                o.hide_render = True
        body.data.materials.clear()
        mat = bpy.data.materials.new("clay")
        mat.use_nodes = True
        b = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        b.inputs["Base Color"].default_value = (0.86, 0.845, 0.83, 1)
        b.inputs["Roughness"].default_value = 0.55
        body.data.materials.append(mat)

        reset(arm)
        h0 = bbox(body)["z"][1] - bbox(body)["z"][0]
        k = targets[sex] / h0
        arm.scale = (k, k, k)
        bpy.context.view_layer.update()
        bb = bbox(body)
        H = bb["z"][1] - bb["z"][0]
        cz = (bb["z"][0] + bb["z"][1]) / 2
        # 全身视角：取景按身高；侧视/背视的横向范围也按身高，避免切边
        for tag, az, elev, _ in VIEWS:
            half = H * 0.56
            shoot(Vector((0, 0, cz)), az, elev, half,
                  round(H * 1.12 * PX / 2) * 2, round(H * 1.12 * PX),
                  f"{raw}/{sex}_{tag}.png")
            print(f"[white] {sex} {tag}  (取景 ±{half:.3f} m)")
        for tag, kind in CLOSEUPS:
            c, s = region_center(body, bb, kind)
            shoot(c, 0.0, 0.0, s, round(s * PX), round(s * PX * 1.06), f"{raw}/{sex}_{tag}.png")
            print(f"[white] {sex} {tag} 特写  中心=({c.x:+.3f},{c.z:.3f})  取景 {s:.3f} m")
        meta[sex] = {"height_m": H, "target_height_m": targets[sex],
                     "views": [v[0] for v in VIEWS], "closeups": [c[0] for c in CLOSEUPS]}

    json.dump(meta, open(f"{outdir}/white_meta.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[white] 元数据 {os.path.relpath(outdir, REPO)}/white_meta.json")


if __name__ == "__main__":
    main()
