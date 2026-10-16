#!/usr/bin/env python3
"""从 Bodiez 基础网格拉出「标准/中型」体型，出【比例参考图】（给 GPT 生图 / Tripo 当约束）。

⚠ 产出是**参考件**（派生自第三方件），**不是生产资产** → 一律写 `tmp/`，不入库。

## 设计要点（每条都是踩出来的）

| # | 要点 | 为什么 |
|---|---|---|
| 1 | **正交投影** | 透视会畸变比例；比例参考的前提是无畸变 |
| 2 | **像素正方形**（px/m 恒定） | 否则比例被画幅拉伸，AI 会读错 |
| 3 | 取景**按包围盒**，且必须容纳 **T-pose 臂展** | 只按高度取景会把手臂切掉（第一版就踩了） |
| 4 | **渲透明通道 + PIL 合成**，不用渲染器单色模式 | Workbench `color_type='SINGLE'` 会把标志线也涂成同色（线消失），且背景与身体同色 |
| 5 | ⭐ **两种姿态都出**：**A-pose（原始）** 与 **T-pose（摆平）** | 实测该件**基础姿是 A-pose**（上臂俯角 **+47.7°**，臂展/身高 **0.7098**）。摆成 T-pose 会**必然拉扯腋下蒙皮**（线性混合蒙皮，低模尤甚）→ 剪影会出现"翅膀状"假形状。<br>**A-pose 版**：解剖真实、无拉扯 → 看体型；**T-pose 版**：合契约 → 看比例 / 喂生成器 |

用法：
    Blender -b --factory-startup --python-exit-code 1 \
      --python tools/3d/skeleton/make_body_reference.py -- --sex female --out tmp/bodyref
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

import bpy

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BODIEZ = os.path.join(REPO, "download", "bodiez",
                     "Bodiez人体基础网格Blender模型：可指定男女×体型预设×比例调节×FBXGLBOBJ导出")
RACE = os.path.join(REPO, "assets", "3d", "rig", "races", "humanoid", "race.json")

SLIDERS = ["Body_Type", "Hip_Wide", "Tall_Short", "Shoulder_Type", "Body_Size",
           "Arm_Size", "Leg_Size", "Head_Size", "Breast_Size"]
GUIDES = [("crown", 100.0), ("eye", 93.3), ("chin", 87.1), ("head_base", 87.5),
          ("neck", 83.6), ("shoulder", 81.0), ("spine_03", 72.4),
          ("hip", 52.4), ("crotch", 50.0), ("knee", 30.0), ("ankle", 4.4)]
PX_PER_M = 820.0
MARGIN = 1.07


def args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    o = {"sex": "female", "out": "tmp/bodyref"}
    for i, a in enumerate(argv):
        if a in ("--sex", "--out") and i + 1 < len(argv):
            o[a[2:]] = argv[i + 1]
    return o


def reset(arm) -> None:
    arm.scale = (1, 1, 1)
    for n in SLIDERS:
        if n in arm.pose.bones:
            arm.pose.bones[n].location = (0, 0, 0)
    bpy.context.view_layer.update()


def tpose(arm) -> list:
    """把上臂摆成水平（T-pose）。

    ⚠ 骨名按**模式**找，不写死 —— Bodiez 用 Rigify 风格 `upper_arm.L/.R`，
    我们自己的 profile 是 UE 风格 `upperarm_l/r`（第一版写死了 UE 名 → 什么都没发生且不报错）。
    """
    from mathutils import Vector, Matrix
    pat = re.compile(r"upper[_.]?arm", re.I)
    rep = []
    for n in [b.name for b in arm.pose.bones if pat.search(b.name)]:
        pb = arm.pose.bones[n]
        d = (pb.tail - pb.head).normalized()
        rep.append(f"{n} 原俯角 {math.degrees(math.asin(-d.z)):+.1f}°")
        t = Vector((1.0 if d.x > 0 else -1.0, 0.0, 0.0))
        axis = d.cross(t)
        if axis.length > 1e-6:
            pb.matrix = Matrix.Rotation(d.angle(t), 4, axis.normalized()) @ pb.matrix
    bpy.context.view_layer.update()
    for n in [b.name for b in arm.pose.bones if pat.search(b.name)]:
        pb = arm.pose.bones[n]
        d = (pb.tail - pb.head).normalized()
        rep.append(f"{n} 新俯角 {math.degrees(math.asin(-d.z)):+.1f}°")
    return rep


def bbox(body) -> dict:
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    me = ev.to_mesh()
    ps = [ev.matrix_world @ v.co for v in me.vertices]
    b = {"x": (min(p.x for p in ps), max(p.x for p in ps)),
         "y": (min(p.y for p in ps), max(p.y for p in ps)),
         "z": (min(p.z for p in ps), max(p.z for p in ps))}
    ev.to_mesh_clear()
    return b


def render(b: dict, axis: str, shaded: bool, path: str) -> None:
    scene = bpy.context.scene
    if axis == "front":
        w, loc, rot = b["x"][1] - b["x"][0], (0, -8, 0), (math.pi / 2, 0, 0)
    else:
        w, loc, rot = b["y"][1] - b["y"][0], (8, 0, 0), (math.pi / 2, 0, math.pi / 2)
    h = b["z"][1] - b["z"][0]
    rx = max(2, round(w * MARGIN * PX_PER_M))
    ry = max(2, round(h * MARGIN * PX_PER_M))
    scene.render.resolution_x, scene.render.resolution_y = rx, ry
    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"

    cam = bpy.data.cameras.new("c")
    cam.type = "ORTHO"
    cam.ortho_scale = max(rx, ry) / PX_PER_M        # ortho_scale 作用于【较大的像素维】
    co = bpy.data.objects.new("c", cam)
    scene.collection.objects.link(co)
    co.location = (loc[0], loc[1], (b["z"][0] + b["z"][1]) / 2)
    co.rotation_euler = rot
    scene.camera = co
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "STUDIO" if shaded else "FLAT"
    sh.color_type = "MATERIAL"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(co, do_unlink=True)
    print(f"[ref] {os.path.relpath(path, REPO)}  ({rx}x{ry} px)")


def main() -> None:
    a = args()
    spec = json.load(open(RACE, encoding="utf-8"))
    target = next(s for s in spec["sexes"] if s["id"] == a["sex"])["mesh_height_m"]
    outdir = os.path.join(REPO, a["out"])
    raw = os.path.join(outdir, "raw")
    os.makedirs(raw, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=os.path.join(BODIEZ, f"modular_{a['sex']}_base.blend"))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    body = next(o for o in bpy.data.objects if o.type == "MESH"
                and o.name.startswith("Geo_") and "Body" in o.name)
    reset(arm)
    h0 = bbox(body)["z"][1] - bbox(body)["z"][0]
    k = target / h0
    print(f"[ref] sex={a['sex']}  复位 {h0:.4f} m → 契约目标 {target} m（缩放 x{k:.4f}）")

    for o in bpy.data.objects:
        if o.type == "MESH" and o is not body:
            o.hide_render = True
        if o.type in ("LIGHT", "CAMERA", "FONT"):
            o.hide_render = True
    body.data.materials.clear()
    mat = bpy.data.materials.new("ref_white")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0.82, 0.80, 0.78, 1)
    bsdf.inputs["Roughness"].default_value = 0.6
    body.data.materials.append(mat)

    poses = {}
    for tag, do_tpose in (("apose", False), ("tpose", True)):
        reset(arm)
        arm.scale = (k, k, k)
        bpy.context.view_layer.update()
        if do_tpose:
            for line in tpose(arm):
                print(f"[pose] {line}")
        b = bbox(body)
        h1 = b["z"][1] - b["z"][0]
        span = b["x"][1] - b["x"][0]
        poses[tag] = {"bbox": b, "height_m": h1, "span_m": span,
                      "span_over_height": span / h1}
        print(f"[ref] 【{tag}】高 {h1:.4f} m | 臂展 {span:.4f} m | 臂展/身高 {span/h1:.4f}")
        render(b, "front", True, f"{raw}/{tag}_front.png")
        render(b, "front", False, f"{raw}/{tag}_front_flat.png")
        if tag == "apose":
            render(b, "side", True, f"{raw}/side.png")

    meta = {"sex": a["sex"], "target_height_m": target, "px_per_m": PX_PER_M,
            "margin": MARGIN, "guides": [{"name": n, "pct": p} for n, p in GUIDES],
            "poses": poses}
    json.dump(meta, open(f"{outdir}/ref_meta.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[ref] 元数据 {os.path.relpath(outdir, REPO)}/ref_meta.json")
    for n, p in GUIDES:
        print(f"   {n:12s} {p:5.1f}%   z = {target*p/100:7.4f} m")


if __name__ == "__main__":
    main()
