#!/usr/bin/env python3
"""
v_pixelmetric.py —— verifier **独立实现**的「像素法」穿模判据。

**为什么需要它**（我的拓扑审计结论）：标准体 `Body_Female` 有 26 个连通域、
48 条边界环、1936 条边界边（58% 在手腕/手），且 ray-parity 在破洞网格上会从
99.83% 掉到 95.83%。顶点级"点在体内"判据在**肩/臂**区域结构性不可靠，
而且**按顶点密度加权**（`*_Feet` 一件占全套 43% 顶点）会把比例稀释。

**像素法**完全没有这些假设：把标准体染成纯红 → 眼睛能看到的红色就是"身体露出来了"。

与 Lead 的 `lead/pixel_metric.py` 的**实现差异**（我全部刻意改掉，便于暴露口径敏感性）：
  1. 身体材质用 **Emission(1,0,0) strength=1**，不是 Principled BSDF
     → 像素值**与灯光/法线/粗糙度完全无关**，纯红就是 (255,0,0)，判据可以收到极紧
  2. 读回用 `colorspace_settings='Non-Color'` 直读原始值，不做色彩管理往返
  3. 判据改成 `r>0.15 且 g<0.06 且 b<0.06`（而非 `r-max(g,b)>0.10`）
     → 棕色皮革 / 皮肤 / 鲑鱼粉在 g 通道上就被排除
  4. **内建两项标定**（Lead 没有）：
     · 只渲身体不渲服装 → 红占比必须 = 100.00%
     · 只渲服装不渲身体 → 红占比必须 =   0.00%
     标定不过 → 本次数据作废（这是我自己在 exposure 指标上踩过的坑）
  5. 相机用**正交前视、按包围盒取景**（Lead 用 50mm 透视定机位），
     并额外报 **3 种取景**下的结果，量化"取景敏感性"

用法（在工作区根）：
  BL=/Applications/Blender.app/Contents/MacOS/Blender
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_pixelmetric.py -- \
      --out assets/3d/rig/reports/verify-pixelmetric.json
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402
from v_penetration import bone_space_refit, strip_skin_bmesh, weights_of  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
RIG = f"{ROOT}/assets/3d/rig"
OLD = f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits"
SHOTDIR = f"{ROOT}/task/007-morph-pipeline/verify/renders"
CLEAR, GATE = 0.008, 0.05          # 复刻 F11 的外推口径，便于对账
CASES = [("Female", "Outfit_Female_Ranger", "Body_Female"),
         ("Male", "Outfit_Male_Ranger", "Body_Male")]

# 判据：Emission 纯红只能是 (255,0,0)；g/b 只要不为零就不是身体
RED_MIN_R = 0.15
RED_MAX_GB = 0.06


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


# ---------------------------------------------------------------- 渲染

def mk_emission_red():
    m = bpy.data.materials.new("VERIFY_BODY_RED")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.0, 0.0, 1.0)
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def setup_render(res, samples=8):
    sc = bpy.context.scene
    try:
        sc.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.film_transparent = True          # alpha = 剪影
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    try:
        sc.eevee.taa_render_samples = samples
    except Exception:  # noqa: BLE001
        pass
    try:
        sc.eevee.use_raytracing = False
    except Exception:  # noqa: BLE001
        pass
    if sc.world is None:
        sc.world = bpy.data.worlds.new("W")
    sc.world.use_nodes = True
    bg = next((n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
    # 给服装一点光，保证它不透明可见
    for nm, loc, e in (("VK", (2.6, -3.2, 3.4), 3000), ("VF", (-2.6, -2.2, 1.6), 1200)):
        if nm in bpy.data.objects:
            continue
        ld = bpy.data.lights.new(nm, "AREA")
        ld.energy = e
        ld.size = 4
        lo = bpy.data.objects.new(nm, ld)
        lo.location = loc
        lo.rotation_euler = (0.8, 0.0, 0.85)
        bpy.context.scene.collection.objects.link(lo)


def make_camera(bounds, res, mode="ortho", margin=0.06):
    """按包围盒取景。mode: ortho（正交，贴合）/ lead（复刻 Lead 的 50mm 透视）/ tight。"""
    lo = np.array(bounds[0], dtype=float)
    hi = np.array(bounds[1], dtype=float)
    c = (lo + hi) / 2.0
    size = hi - lo
    cd = bpy.data.cameras.new("V_CAM")
    cam = bpy.data.objects.new("V_CAM", cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    if mode == "lead":
        cd.type = "PERSP"
        cd.lens = 50
        cam.location = (0.0, -4.6, 0.92)
        cam.rotation_euler = (math.radians(90), 0.0, 0.0)
        return cam
    cd.type = "ORTHO"
    aspect = res[0] / res[1]
    need_h = size[2] * (1 + 2 * margin)
    need_w = size[0] * (1 + 2 * margin)
    if need_w / aspect > need_h:
        need_h = need_w / aspect
    cd.ortho_scale = max(need_h, need_w / aspect) if mode == "ortho" else \
        max(need_h, need_w / aspect) * 0.72
    cam.location = (c[0], -(max(size) * 3 + 3.0), c[2])
    cam.rotation_euler = (math.radians(90), 0.0, 0.0)
    return cam


def render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def read_png_raw(path):
    """用 Blender 的 image API 读回，但走 Non-Color 直读原始值（不做色彩管理往返）。"""
    img = bpy.data.images.load(path, check_existing=False)
    try:
        img.colorspace_settings.name = "Non-Color"
    except Exception:  # noqa: BLE001
        pass
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)          # 注意：Blender 行序自下而上


def classify(rgba):
    """判据：alpha>0.5 = 剪影；r>0.15 且 g<0.06 且 b<0.06 = 身体（Emission 纯红）。"""
    a = rgba[..., 3]
    sil = a > 0.5
    r, g, b = rgba[..., 0], rgba[..., 1], rgba[..., 2]
    red = sil & (r > RED_MIN_R) & (g < RED_MAX_GB) & (b < RED_MAX_GB)
    return int(red.sum()), int(sil.sum())


def shot_stats(path):
    rgba = read_png_raw(path)
    red, sil = classify(rgba)
    return {"png": os.path.basename(path), "red_px": red, "silhouette_px": sil,
            "red_frac_pct": round(100.0 * red / sil, 4) if sil else None,
            "resolution": [int(rgba.shape[1]), int(rgba.shape[0])]}


# ---------------------------------------------------------------- 外推（我自己的实现）

def autofit_push(cloth, body, rounds=3, clear=CLEAR, gate=GATE):
    """把落在体内/贴太近的布料顶点推到体表外 clear 米。**verifier 自己实现**。"""
    def body_tree():
        m = vlib.evaluated_mesh(body)
        M = np.array(body.matrix_world)
        co = m["co"] @ M[:3, :3].T + M[:3, 3]
        tris = vlib._triangulate(m)
        return BVHTree.FromPolygons([Vector(p) for p in co],
                                    [tuple(int(x) for x in t) for t in tris],
                                    all_triangles=True)
    moved = []
    for _ in range(rounds):
        tree = body_tree()
        n_moved = 0
        for o in cloth:
            mw = np.array(o.matrix_world)
            inv = np.linalg.inv(mw)
            n = len(o.data.vertices)
            raw = np.empty(n * 3)
            o.data.vertices.foreach_get("co", raw)
            raw = raw.reshape(n, 3)
            world = raw @ mw[:3, :3].T + mw[:3, 3]
            neww = world.copy()
            for i in range(n):
                p = Vector(world[i])
                loc, nor, idx, dist = tree.find_nearest(p, 1e7)
                if loc is None:
                    continue
                if dist < gate and (p - loc).dot(nor) < clear:
                    neww[i] = np.array(loc) + np.array(nor) * clear
                    n_moved += 1
            newl = neww @ inv[:3, :3].T + inv[:3, 3]
            o.data.vertices.foreach_set("co", newl.reshape(-1).astype(np.float32))
            o.data.update()
        bpy.context.view_layer.update()
        moved.append(n_moved)
    return moved


# ---------------------------------------------------------------- 场景装配

def build_case(sex, outfit, body_obj):
    bpy.ops.wm.open_mainfile(filepath=f"{OLD}/{outfit}.blend")
    rigA = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}
    for o in list(bpy.data.objects):
        if o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o, do_unlink=True)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for o in meshes:
        strip_skin_bmesh(o)
    cloth = [o for o in meshes if len(o.data.polygons) > 0]
    W = {o.name: weights_of(o) for o in cloth}
    with bpy.data.libraries.load(f"{RIG}/bodies/Body_{sex}_Standard.blend") as (s, d):
        d.objects = [body_obj]
    for o in d.objects:
        if o:
            bpy.context.scene.collection.objects.link(o)
    body = bpy.data.objects[body_obj]
    bpy.context.view_layer.update()
    rigB = body.find_armature()
    restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}
    red = mk_emission_red()
    body.data.materials.clear()
    body.data.materials.append(red)
    return cloth, body, rigA, rigB, restA, restB, W


def scene_bounds(cloth, body):
    pts = []
    for o in cloth + [body]:
        m = vlib.evaluated_mesh(o)
        M = np.array(o.matrix_world)
        co = m["co"] @ M[:3, :3].T + M[:3, 3]
        if len(co):
            pts.append(np.array([co.min(axis=0), co.max(axis=0)]))
    P = np.vstack(pts)
    return P.min(axis=0).tolist(), P.max(axis=0).tolist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-pixelmetric.json")
    ap.add_argument("--res", nargs=2, type=int, default=[760, 1180])
    a = ap.parse_args(argv_after_ddash())
    os.makedirs(SHOTDIR, exist_ok=True)
    out = {"generated_by": "verifier/v_pixelmetric.py",
           "metric": "标准体染 Emission 纯红；像素法 = 红像素 / 剪影像素（alpha>0.5）",
           "classifier": {"r_min": RED_MIN_R, "g_max": RED_MAX_GB, "b_max": RED_MAX_GB},
           "autofit": {"rounds": 3, "clear_m": CLEAR, "gate_m": GATE},
           "cases": []}
    t0 = time.perf_counter()
    for sex, outfit, body_obj in CASES:
        rec = {"sex": sex, "outfit": outfit, "states": {}, "calibration": {},
               "framing_sensitivity": {}}
        print(f"\n{'='*90}\n### {sex} {outfit}\n{'='*90}", flush=True)
        cloth, body, rigA, rigB, restA, restB, W = build_case(sex, outfit, body_obj)

        # ---------- 标定（先做，标定不过就不采信） ----------
        bounds = scene_bounds(cloth, body)
        rec["scene_bounds"] = bounds
        res = tuple(a.res)
        setup_render(res)
        # 标定 A：只渲身体（隐藏服装）→ 应 100%
        for o in cloth:
            o.hide_render = True
        bpy.context.view_layer.update()
        cam = make_camera(bounds, res, "ortho")
        p = f"{SHOTDIR}/calib_bodyonly_{sex}.png"
        render_to(p)
        rec["calibration"]["body_only_expect_100pct"] = shot_stats(p)
        # 标定 B：只渲服装（隐藏身体）→ 应 0%
        for o in cloth:
            o.hide_render = False
        bpy.data.objects[body_obj].hide_render = True
        bpy.context.view_layer.update()
        p = f"{SHOTDIR}/calib_clothonly_{sex}.png"
        render_to(p)
        rec["calibration"]["cloth_only_expect_0pct"] = shot_stats(p)
        bpy.data.objects[body_obj].hide_render = False
        calib_ok = (rec["calibration"]["body_only_expect_100pct"]["red_frac_pct"] == 100.0
                    and rec["calibration"]["cloth_only_expect_0pct"]["red_frac_pct"] == 0.0)
        rec["calibration"]["passed"] = bool(calib_ok)
        print(f"  标定 body-only={rec['calibration']['body_only_expect_100pct']['red_frac_pct']}% "
              f"(应=100)  cloth-only={rec['calibration']['cloth_only_expect_0pct']['red_frac_pct']}% "
              f"(应=0)  → {'通过' if calib_ok else '❌ 不通过'}")

        def shoot_state(tag, mode):
            cam = make_camera(scene_bounds(cloth, body), res, mode)
            p = f"{SHOTDIR}/px_{sex}_{tag}_{mode}.png"
            render_to(p)
            st = shot_stats(p)
            st["camera_mode"] = mode
            return st

        # ---------- ③ 三种状态（用同一正交取景） ----------
        for o in cloth:
            for m in o.modifiers:
                if m.type == "ARMATURE":
                    m.object = rigA
        bpy.context.view_layer.update()
        rec["states"]["1_baseline_own_rig"] = shoot_state("1_baseline", "ortho")
        print(f"  ① 原始            {rec['states']['1_baseline_own_rig']['red_frac_pct']:6.2f}%")

        for o in cloth:
            for m in o.modifiers:
                if m.type == "ARMATURE":
                    m.object = rigB
        bpy.context.view_layer.update()
        rec["states"]["2_reattached_no_refit"] = shoot_state("2_reattach", "ortho")
        print(f"  ② 改挂标准体 rig   "
              f"{rec['states']['2_reattached_no_refit']['red_frac_pct']:6.2f}%")

        t = time.perf_counter()
        refit_stats = {o.name: bone_space_refit(o, restA, restB, W[o.name]) for o in cloth}
        bpy.context.view_layer.update()
        rec["refit_seconds"] = round(time.perf_counter() - t, 3)
        rec["refit_stats"] = refit_stats
        rec["states"]["3_bone_space_refit"] = shoot_state("3_refit", "ortho")
        print(f"  ③ 骨空间 refit     "
              f"{rec['states']['3_bone_space_refit']['red_frac_pct']:6.2f}%")

        # ---------- ④ 自动外推（我自己实现） ----------
        t = time.perf_counter()
        moved = autofit_push(cloth, body, rounds=3)
        rec["autofit_seconds"] = round(time.perf_counter() - t, 3)
        rec["autofit_moved_per_round"] = moved
        rec["states"]["4_autofit_3rounds"] = shoot_state("4_autofit", "ortho")
        print(f"  ④ refit+外推3轮    "
              f"{rec['states']['4_autofit_3rounds']['red_frac_pct']:6.2f}%   "
              f"(每轮推动 {moved} 顶点, {rec['autofit_seconds']}s)")

        # ---------- 取景敏感性 ----------
        for mode in ("lead", "tight"):
            rec["framing_sensitivity"][mode] = shoot_state(
                "4_autofit", mode)
        print(f"  取景敏感性: ortho={rec['states']['4_autofit_3rounds']['red_frac_pct']:.2f}%  "
              f"lead-cam={rec['framing_sensitivity']['lead']['red_frac_pct']:.2f}%  "
              f"tight-crop={rec['framing_sensitivity']['tight']['red_frac_pct']:.2f}%")
        out["cases"].append(rec)
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(a.out, out)
    print(f"\n[v_pixelmetric] wrote {a.out} in {out['total_seconds']}s")


if __name__ == "__main__":
    main()