#!/usr/bin/env python3
"""
v_fitdepth.py —— verifier 对「穿模率」这个指标本身的独立审查 + 更稳的替代度量。

动机：v_penetration.py 复现出「女 Peasant 紧身裤 63.8% 在体内」这种数字，
但预览图显示那只是一条**贴身 legging**。所以怀疑：
  **当布料表面与身体表面在同一量级距离内交错时，"落在体内比例"趋近 50%，
    与视觉上是否真的"穿模爆炸"无关 —— 该指标在紧身衣上退化。**

本脚本用两件事把这件事量化：
  A. **有符号距离剖面**：sd 分位数 + 阈值分段（骑跨 / 真·嵌入 / 真·浮空）
     → 给出"这到底是贴身交错，还是身体真的顶出去"
  B. **身体外露率（body exposure）**：从每个身体顶点沿法线往外打射线，
     在 X cm 内打不到任何服装面 → 该处身体是**露出来的**（= 视觉里的红色）
     → 这才是"肉眼可见穿模"的直接代理指标；对①②③三态各测一次

只读，不写 .blend。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_fitdepth.py -- \
      --out assets/3d/rig/reports/verify-fitdepth.json
"""
import argparse
import json
import os
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402
from v_penetration import (bone_space_refit, eval_points, strip_skin_bmesh,
                           weights_of)  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OLD = f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits"
NEW = f"{ROOT}/assets/3d/rig"
CASES = [("Female", "Outfit_Female_Ranger", "Body_Female"),
         ("Male", "Outfit_Male_Ranger", "Body_Male"),
         ("Female", "Outfit_Female_Peasant", "Body_Female"),
         ("Male", "Outfit_Male_Peasant", "Body_Male")]
# 阈值以 cm 表述，内部统一用 m（sd 原始单位）
THRESH_CM = [-20.0, -10.0, -5.0, -2.0, -1.0, -0.5, -0.2, 0.0, 0.2, 0.5, 1.0, 2.0]


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def sd_profile(tree, pts, body_co):
    """有符号距离剖面（内部单位 m，输出 cm）。约定：**负 = 在体内**。

    符号标定用 **body_co 的质心**（闭合身体网格质心必在体内），
    **不用服装点** —— 服装质心贴着身体表面，拿它标定会翻号（我踩过）。
    """
    sign, calib = vlib.calibrate_normal_sign(tree, body_co) if len(body_co) else (1.0, {})
    sd = np.full(len(pts), np.nan)
    for i, p in enumerate(pts):
        loc, nor, _, _ = tree.find_nearest(Vector(p), 1e7)
        if loc is not None:
            sd[i] = (Vector(p) - loc).dot(nor)
    # calibrate 返回 sign_inside 满足 sign*sd > tol => 内部；想要 sd<0 => 内部
    sd = sd * (-sign)
    ok = ~np.isnan(sd)
    s = sd[ok]
    out = {"n": int(s.size), "calib": calib, "units": "cm"}
    if s.size == 0:
        return out, sd
    qs = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    out["percentiles_cm"] = {f"p{q}": round(float(np.percentile(s, q)) * 100, 4) for q in qs}
    out["mean_cm"] = round(float(s.mean()) * 100, 4)
    out["frac_below_cm"] = {f"{t:+.2f}": round(float(np.mean(s * 100 < t)), 4) for t in THRESH_CM}
    out["frac_above_cm"] = {f"{t:+.2f}": round(float(np.mean(s * 100 > t)), 4) for t in THRESH_CM}
    out["degenerate_straddle_frac"] = round(float(np.mean(np.abs(s) * 100 < 0.1)), 4)
    out["deep_inside_frac_lt_-0.5cm"] = round(float(np.mean(s * 100 < -0.5)), 4)
    out["clearly_outside_frac_gt_+0.5cm"] = round(float(np.mean(s * 100 > 0.5)), 4)
    return out, sd


def build_garment_bvh(pt_arrays):
    """把多件服装的点云各自三角化后合成一个 BVH。"""
    verts, tris = [], []
    off = 0
    for pts, tri in pt_arrays:
        verts.extend(Vector(p) for p in pts)
        tris.extend((int(t[0]) + off, int(t[1]) + off, int(t[2]) + off) for t in tri)
        off += len(pts)
    if not tris:
        return None
    return BVHTree.FromPolygons(verts, tris, all_triangles=True)


def bone_outward_dirs(body, body_co):
    """**不依赖面绕向**的外向方向：取每根骨段上离顶点最近的点 → 由骨指向顶点。

    这是对「顶点法线」的替代，因为本资产的标准体网格**面绕向不一致**
    （实测仅 67% 的面按绕向朝外），任何绕向派生的法线都不可靠。
    误差源：骨在体内但不是中线（如手指骨），凹处（裆/腋）方向可能偏。
    """
    arm = body.find_armature()
    if arm is None:
        return None, "no armature"
    M = np.array(arm.matrix_world)
    segs = []
    for b in arm.data.bones:
        h = M[:3, :3] @ np.array(b.head_local) + M[:3, 3]
        t = M[:3, :3] @ np.array(b.tail_local) + M[:3, 3]
        segs.append((h, t))
    segs = np.array(segs)  # (B,2,3)
    H, T = segs[:, 0, :], segs[:, 1, :]          # (B,3)
    D = T - H                                     # (B,3)
    L2 = (D * D).sum(axis=1)                      # (B,)
    L2[L2 < 1e-12] = 1e-12
    out = np.zeros_like(body_co)
    # 分块算，避免 (N,B) 爆内存
    step = 4096
    for i0 in range(0, len(body_co), step):
        P = body_co[i0:i0 + step]                 # (n,3)
        v = P[:, None, :] - H[None, :, :]         # (n,B,3)
        t = (v * D[None, :, :]).sum(axis=2) / L2[None, :]
        t = np.clip(t, 0.0, 1.0)
        cp = H[None, :, :] + t[:, :, None] * D[None, :, :]
        dv = P[:, None, :] - cp
        dist = np.linalg.norm(dv, axis=2)
        j = dist.argmin(axis=1)
        rows = np.arange(len(P))
        out[i0:i0 + step] = dv[rows, j]
    ln = np.linalg.norm(out, axis=1, keepdims=True)
    ln[ln < 1e-9] = 1.0
    return out / ln, None


def exposure_rate(body_co, body_vn, band_sel, gbvh, reach):
    if gbvh is None:
        return {"n": int(band_sel.sum()), "exposed_frac": 1.0}
    idx = np.where(band_sel)[0]
    exposed = 0
    for i in idx:
        p = Vector(body_co[i])
        d = Vector(body_vn[i])
        hit = gbvh.ray_cast(p + d * 1e-5, d, reach)
        if hit[0] is None:
            exposed += 1
    return {"n": int(len(idx)), "exposed_frac": float(exposed / max(len(idx), 1))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-fitdepth.json")
    a = ap.parse_args(argv_after_ddash())
    out = {"generated_by": "verifier/v_fitdepth.py",
           "sd_convention": "sd = 点到标准体表面的最近点有符号距离；**负 = 在体内**",
           "cases": []}
    t0 = time.perf_counter()
    for sex, outfit, body_obj in CASES:
        rec = {"sex": sex, "outfit": outfit, "pieces": {}}
        print(f"\n{'='*100}\n### {sex} {outfit}\n{'='*100}", flush=True)
        bpy.ops.wm.open_mainfile(filepath=f"{OLD}/{outfit}.blend")
        rigA = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
        restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}
        meshes = [o for o in bpy.data.objects
                  if o.type == "MESH" and not o.name.startswith("Icosphere")]
        for o in meshes:
            strip_skin_bmesh(o)
        cloth = [o for o in meshes if len(o.data.polygons) > 0]
        W = {o.name: weights_of(o) for o in cloth}

        with bpy.data.libraries.load(f"{NEW}/bodies/Body_{sex}_Standard.blend") as (s, d):
            d.objects = [body_obj]
        for o in d.objects:
            if o:
                bpy.context.scene.collection.objects.link(o)
        body = bpy.data.objects[body_obj]
        bpy.context.view_layer.update()
        tree, body_co, body_tris = vlib.bvh_from_eval(body)
        rigB = body.find_armature()
        restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}

        # 身体外向方向：**两套**并报（绕向派生的顶点法线 / 骨段方向）
        vn_wind = np.zeros_like(body_co)
        aa, bb, cc = body_co[body_tris[:, 0]], body_co[body_tris[:, 1]], body_co[body_tris[:, 2]]
        fn = np.cross(bb - aa, cc - aa)
        for k in range(3):
            np.add.at(vn_wind, body_tris[:, k], fn)
        ln = np.linalg.norm(vn_wind, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        vn_wind = vn_wind / ln
        vn_bone, bone_err = bone_outward_dirs(body, body_co)
        rec["outward_dir_methods"] = {
            "winding_derived_available": True,
            "bone_derived_available": vn_bone is not None,
            "bone_error": bone_err,
            "note": "标准体网格面绕向不一致 → 绕向派生法线不可靠；骨段方向与绕向无关。",
        }
        body_vn = vn_bone if vn_bone is not None else vn_wind
        zmax = float(body_co[:, 2].max())
        zmin = float(body_co[:, 2].min())
        rec["body_z_range_m"] = [round(zmin, 4), round(zmax, 4)]
        # 躯干带：Lead 的视觉证据里最刺眼的区域
        torso = (body_co[:, 2] >= 0.95) & (body_co[:, 2] <= 1.45)
        whole = np.ones(len(body_co), dtype=bool)
        rec["exposure_bands"] = {"torso_0.95_1.45m": int(torso.sum()),
                                 "whole_body": int(whole.sum())}

        states = {}
        for label, target, do_refit in (
                ("1_baseline_own_rig", "A", False),
                ("2_reattached_standard_rig_no_refit", "B", False),
                ("3_bone_space_refit", "B", True)):
            for o in cloth:
                for m in o.modifiers:
                    if m.type == "ARMATURE":
                        m.object = rigA if target == "A" else rigB
            if do_refit:
                for o in cloth:
                    bone_space_refit(o, restA, restB, W[o.name])
            bpy.context.view_layer.update()
            pts = {o.name: eval_points(o) for o in cloth}
            st = {}
            # A. sd 剖面
            for o in cloth:
                p = pts[o.name]
                prof, _ = sd_profile(tree, p, body_co)
                st[o.name] = prof
                print(f"  [{label}] {o.name:<32} n={prof['n']:<6} "
                      f"p50={prof['percentiles_cm']['p50']:+7.3f} "
                      f"p05={prof['percentiles_cm']['p5']:+7.3f} "
                      f"p95={prof['percentiles_cm']['p95']:+7.3f} "
                      f"骑跨(|sd|<1mm)={prof['degenerate_straddle_frac']*100:5.1f}% "
                      f"深嵌(<-5mm)={prof['deep_inside_frac_lt_-0.5cm']*100:5.1f}% "
                      f"浮空(>5mm)={prof['clearly_outside_frac_gt_+0.5cm']*100:5.1f}%")
            # B. 身体外露率
            trilist = []
            for o in cloth:
                mm = vlib.evaluated_mesh(o)
                Mw = np.array(o.matrix_world)
                c2 = mm["co"] @ Mw[:3, :3].T + Mw[:3, 3]
                trilist.append((c2, vlib._triangulate(mm)))
            gbvh = build_garment_bvh(trilist)
            # —— 外露率指标的标定：服装=身体自身(必然遮挡) / 无服装(必然外露) ——
            # 标定：把"服装"设成**沿可靠方向外推 δ 的身体壳**。
            # δ=2cm / reach=5cm → 应≈0%（射线能打到）；δ=10cm / reach=5cm → 应≈100%（够不着）。
            # ⚠ 不能用"服装=身体自身"来标定：向外射线从表面出发就**离开**身体，
            #   本来就不该打到任何面（我第一版就是这么错的，测出 0.93 的假告警）。
            dir_src = body_vn  # 骨段方向（与绕向无关）
            exp = {"_calibration": {
                "shell_2cm_reach5cm_torso": exposure_rate(
                    body_co, dir_src, torso,
                    build_garment_bvh([(body_co + dir_src * 0.02, body_tris)]), 0.05),
                "shell_10cm_reach5cm_torso": exposure_rate(
                    body_co, dir_src, torso,
                    build_garment_bvh([(body_co + dir_src * 0.10, body_tris)]), 0.05),
                "no_garment_reach20mm_torso": exposure_rate(
                    body_co, dir_src, torso, None, 0.02),
                "note": "期望：shell_2cm ≈ 0%，shell_10cm ≈ 100%，no_garment = 100%。"
                        "偏离则说明方向集或 reach 不合适，数据不可采信。",
            }}
            for reach in (0.005, 0.02, 0.05):
                exp[f"reach_{int(reach*1000)}mm"] = {
                    "torso": exposure_rate(body_co, body_vn, torso, gbvh, reach),
                    "whole": exposure_rate(body_co, body_vn, whole, gbvh, reach),
                }
            st["_body_exposure"] = exp
            print(f"  [{label}] 身体外露率  躯干带 reach20mm="
                  f"{exp['reach_20mm']['torso']['exposed_frac']*100:.2f}%  "
                  f"全身 reach20mm={exp['reach_20mm']['whole']['exposed_frac']*100:.2f}%")
            states[label] = st
        rec["pieces"] = states
        out["cases"].append(rec)
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(a.out, out)
    print(f"\n[v_fitdepth] wrote {a.out} in {out['total_seconds']}s")


if __name__ == "__main__":
    main()