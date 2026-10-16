#!/usr/bin/env python3
"""把基础网格的**各个体型预设**渲成同一取景的剪影，并**量化围度**（胸/腰/臀）。

**为什么要单独一个脚本**：
  · 参考图脚本按**各自包围盒**取景 → 每个预设画幅不同 → **无法叠加对比**。
    这里改用**固定取景**（以 Regular 的包围盒为基准放大一点），使各图**逐像素对齐**。
  · 用户反馈「腰部太瘦」—— 这是**围度**问题，不能靠看图，得**量**。
    量法沿用已入库的口径：**水平切片 → 2D 凸包周长 = 软尺量法**（对破洞/面绕向免疫）。

复用 `make_body_reference.py` 的 `reset / tpose / bbox / args`（**不重复实现**）。

用法：
    Blender -b --factory-startup --python-exit-code 1 \
      --python tools/3d/skeleton/compare_body_presets.py -- --out tmp/bodycmp
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_body_reference import BODIEZ, RACE, bbox, reset, tpose  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

# Bodiez `Body_Type` 的区间带（见 reference/BODIEZ-ANALYSIS.md §2.1）取带内代表值
PRESETS = [("Thin", 0.15), ("Regular", 0.05), ("Muscular", 0.27), ("Fat", 0.35)]
GIRTHS = [("chest", 75.0), ("waist", 61.8), ("hip", 52.4), ("neck", 83.6)]
PX_PER_M = 700.0
PAD = 1.08


def args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    o = {"out": "tmp/bodycmp"}
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            o["out"] = argv[i + 1]
    return o


def hull_perimeter(pts) -> float:
    """2D 凸包周长 = 软尺量法。

    ⚠ **不用 scipy**：Blender 自带的 Python **没有 scipy**（实测 `ModuleNotFoundError`）。
    所以这里用纯 python 实现（Andrew 单调链），零依赖 —— 反而更稳（numpy 也一并不用）。
    """
    ps = sorted(set(pts))
    if len(ps) < 3:
        return float("nan")

    def half(seq):
        st = []
        for p in seq:
            while len(st) >= 2 and ((st[-1][0] - st[-2][0]) * (p[1] - st[-2][1])
                                    - (st[-1][1] - st[-2][1]) * (p[0] - st[-2][0])) <= 0:
                st.pop()
            st.append(p)
        return st

    hull = half(ps)[:-1] + half(ps[::-1])[:-1]
    n = len(hull)
    return sum(math.dist(hull[i], hull[(i + 1) % n]) for i in range(n))


# 手臂/手指 顶点组（按名模式匹配，不写死两侧）
ARM_PAT = re.compile(r"upper_arm|forearm|hand|thumb|f_(index|middle|ring|pinky)|palm", re.I)


def torso_mask(body) -> list:
    """躯干顶点掩码：**权重大部分不在手臂/手指骨上**的顶点。

    ⚠ 必须要这一步：胸围（75%H）正好在手臂高度附近，不剔手臂会把两侧手臂一起算进凸包
    （实测：腰围一度量出 **317 cm**）。
    ⚠ 也**必须关掉 SUBSURF**：细分会改顶点数（5256 → 21018），索引无法与 cage 的顶点组对应。
    """
    gi = {g.index for g in body.vertex_groups if ARM_PAT.search(g.name)}
    return [v.index for v in body.data.vertices
            if sum(g.weight for g in v.groups if g.group in gi) < 0.5]


def girth(body, z: float, band: float, keep: list) -> float:
    """水平切片 → XY 投影 → 凸包周长（软尺量法，对破洞 / 面绕向免疫）。"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    me = ev.to_mesh()
    pts = [(p.x, p.y) for i, p in enumerate((ev.matrix_world @ v.co) for v in me.vertices)
           if i in keep and abs(p.z - z) < band]
    ev.to_mesh_clear()
    return hull_perimeter(pts)


def render_fixed(b: dict, frame: dict, path: str) -> None:
    """固定取景渲染（各预设逐像素对齐）。"""
    scene = bpy.context.scene
    rx, ry = frame["rx"], frame["ry"]
    scene.render.resolution_x, scene.render.resolution_y = rx, ry
    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"
    cam = bpy.data.cameras.new("c")
    cam.type = "ORTHO"
    cam.ortho_scale = max(rx, ry) / frame["ppm"]
    co = bpy.data.objects.new("c", cam)
    scene.collection.objects.link(co)
    co.location = (0, -8, frame["zc"])
    co.rotation_euler = (math.pi / 2, 0, 0)
    scene.camera = co
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "MATERIAL"
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

    result = {}
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
        for m in [m for m in body.modifiers if m.type == "SUBSURF"]:
            m.show_viewport = False          # ⚠ 细分改顶点数 → 索引对不上顶点组
        body.data.materials.clear()
        mat = bpy.data.materials.new("p")
        mat.use_nodes = True
        next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        mat.diffuse_color = (0.15, 0.15, 0.15, 1)
        body.data.materials.append(mat)

        keep = torso_mask(body)
        print(f"  躯干顶点 {len(keep)}/{len(body.data.vertices)}"
              f"（剔掉 {len(body.data.vertices)-len(keep)} 个手臂/手指顶点）")
        # 基准（Regular）定取景
        reset(arm); arm.pose.bones["Body_Type"].location = (0.05, 0, 0)
        bpy.context.view_layer.update()
        h0 = bbox(body)["z"][1] - bbox(body)["z"][0]
        k = targets[sex] / h0
        arm.scale = (k, k, k)
        bpy.context.view_layer.update()
        tpose(arm)
        b = bbox(body)
        frame = {"zc": (b["z"][0] + b["z"][1]) / 2,
                 "rx": max(2, round((b["x"][1] - b["x"][0]) * PAD * PX_PER_M)),
                 "ry": max(2, round((b["z"][1] - b["z"][0]) * PAD * PX_PER_M)),
                 "ppm": PX_PER_M}
        result[sex] = {"target_height_m": targets[sex], "frame": frame, "presets": {}}
        print(f"\n### {sex}  目标身高 {targets[sex]} m  取景 {frame['rx']}x{frame['ry']}")

        for name, t in PRESETS:
            reset(arm)
            arm.pose.bones["Body_Type"].location = (t, 0, 0)
            arm.scale = (k, k, k)
            bpy.context.view_layer.update()
            tpose(arm)
            b = bbox(body)
            h = b["z"][1] - b["z"][0]
            band = h * 0.004
            g = {n: girth(body, h * p / 100.0, band, keep) for n, p in GIRTHS}
            result[sex]["presets"][name] = {
                "body_type_value": t, "height_m": h,
                "span_over_height": (b["x"][1] - b["x"][0]) / h,
                "girth_m": g,
                "girth_over_height": {n: v / h for n, v in g.items()},
            }
            p = f"{raw}/preset_{sex}_{name}.png"
            render_fixed(b, frame, p)
            gs = "  ".join(f"{n}={v*100:5.1f}cm" for n, v in g.items())
            print(f"  {name:9s} t={t:.2f}  高 {h:.4f}  {gs}")

    json.dump(result, open(f"{outdir}/presets.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n[presets] 写 {os.path.relpath(outdir, REPO)}/presets.json")

    # 汇总表：围度/身高
    for sex in ("female", "male"):
        print(f"\n### {sex} 围度/身高（软尺量法）")
        print("  预设      " + "".join(f"{n:>12s}" for n, _ in GIRTHS))
        base = result[sex]["presets"]["Regular"]["girth_over_height"]
        for name, _ in PRESETS:
            r = result[sex]["presets"][name]["girth_over_height"]
            row = "".join(f"{r[n]:12.4f}" for n, _ in GIRTHS)
            d = "".join(f"{100*(r[n]/base[n]-1):+11.1f}%" for n, _ in GIRTHS)
            print(f"  {name:9s} {row}   相对Regular {d}")


if __name__ == "__main__":
    main()
