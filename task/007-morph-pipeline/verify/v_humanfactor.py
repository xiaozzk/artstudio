#!/usr/bin/env python3
"""
v_humanfactor.py —— 把「人工介入」量化：哪些步骤的**结果**取决于人调出来的参数？

三个可测的介入点：
  H1 **体形档位系数**：T1 的 manifest 里有 9 个手调 `delta_response`
     （pelvis 1.0 / spine_02 0.92 / spine_03 0.85 / clavicle 0.5 …），
     **SPEC §3.3 里没有这些数**。→ 把它们全设 1.0（= SPEC 的字面口径）再派生一次，
     与 T1 实际烘出来的 BS_Thin/BS_Heavy 比，差多少 = 这一步的人调份量。
  H2 **哪些件该标 skip**（SPEC §4.4）：用绑定距离分位数给客观代理。
  H3 **剥离判据的覆盖率**：`MI_Regular_*` 在 4 套服装上的实际覆盖情况。

只读，不写 .blend。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_humanfactor.py -- \
      --out assets/3d/rig/reports/verify-humanfactor.json
"""
import argparse
import json
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402
from v_transfer import (Bind, bind_garment_to_body, eval_transfer,
                        tri_normals_array, CASES)  # noqa: E402
from v_penetration import eval_points, strip_skin_bmesh  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
RIG = f"{ROOT}/assets/3d/rig"
OLD = f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits"
SHAPE_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r"]


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def eval_co(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    return vlib.evaluated_mesh(obj, dg)["co"].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-humanfactor.json")
    a = ap.parse_args(argv_after_ddash())
    out = {"generated_by": "verifier/v_humanfactor.py", "H1_morph_coefficients": {},
           "H2_skip_proxy": [], "H3_strip_coverage": []}
    t0 = time.perf_counter()

    # ================= H1 =================
    for sex in ("Female", "Male"):
        bpy.ops.wm.open_mainfile(filepath=f"{RIG}/bodies/Body_{sex}_Standard.blend")
        body = bpy.data.objects[f"Body_{sex}"]
        arm = body.find_armature()
        sk = body.data.shape_keys
        rec = {}

        def collect(values):
            for kb in sk.key_blocks:
                kb.value = float(values.get(kb.name, 0.0))
            bpy.context.view_layer.update()
            return eval_co(body)

        t1_thin = collect({"BS_Thin": 1.0})
        t1_heavy = collect({"BS_Heavy": 1.0})
        basis = collect({})

        # 字面 SPEC 口径：14 根体形骨统一 (s,1,s)
        canon = {}
        for tier, s in (("thin", 0.86), ("heavy", 1.16)):
            for pb in arm.pose.bones:
                pb.scale = (1.0, 1.0, 1.0)
            for nm in SHAPE_BONES:
                pb = arm.pose.bones.get(nm)
                if pb:
                    pb.scale = (s, 1.0, s)
            bpy.context.view_layer.update()
            canon[tier] = eval_co(body)
            for pb in arm.pose.bones:
                pb.scale = (1.0, 1.0, 1.0)
            bpy.context.view_layer.update()

        # 字面 SPEC 口径下的骨骼被禁掉的传播：T1 用的是 manifest 里那些值，
        # 这里看「系数取 1.0」与「取 manifest 值」差多少
        dr = {"pelvis": 1.0, "spine_01": 1.0, "spine_02": 0.92, "spine_03": 0.85,
              "thigh": 0.95, "calf": 0.85, "upperarm": 1.05, "lowerarm": 0.95,
              "clavicle": 0.5}
        tuned = {}
        for tier, s in (("thin", 0.86), ("heavy", 1.16)):
            for pb in arm.pose.bones:
                pb.scale = (1.0, 1.0, 1.0)
            for nm in SHAPE_BONES:
                base = nm.split("_")[0] if nm.split("_")[0] in dr else nm
                if base not in dr:
                    base = nm.rsplit("_", 1)[0]
                r = dr.get(base, 1.0)
                val = 1.0 + (s - 1.0) * r
                pb = arm.pose.bones.get(nm)
                if pb:
                    pb.scale = (val, 1.0, val)
            bpy.context.view_layer.update()
            tuned[tier] = eval_co(body)
            for pb in arm.pose.bones:
                pb.scale = (1.0, 1.0, 1.0)
            bpy.context.view_layer.update()

        for tier, baked in (("thin", t1_thin), ("heavy", t1_heavy)):
            d_canon = np.linalg.norm(canon[tier] - baked, axis=1) * 100
            d_tuned = np.linalg.norm(tuned[tier] - baked, axis=1) * 100
            rec[tier] = {
                "baked_morph_vs_literal_SPEC_canonical": {
                    "max_cm": float(d_canon.max()), "mean_cm": float(d_canon.mean()),
                    "p95_cm": float(np.percentile(d_canon, 95)),
                },
                "baked_morph_vs_tuned_coefficients": {
                    "max_cm": float(d_tuned.max()), "mean_cm": float(d_tuned.mean()),
                    "p95_cm": float(np.percentile(d_tuned, 95)),
                },
                "baked_morph_vs_basis_max_cm": float(
                    np.linalg.norm(baked - basis, axis=1).max() * 100),
            }
        out["H1_morph_coefficients"][sex] = rec
        print(f"### H1 {sex}: thin 手调系数 vs 字面SPEC 最大差 "
              f"{rec['thin']['baked_morph_vs_literal_SPEC_canonical']['max_cm']:.3f} cm / "
              f"均值 {rec['thin']['baked_morph_vs_literal_SPEC_canonical']['mean_cm']:.3f} cm")

    # ================= H2 + H3 =================
    for sex, outfit, body_obj in CASES:
        bpy.ops.wm.open_mainfile(filepath=f"{OLD}/{outfit}.blend")
        meshes = [o for o in bpy.data.objects
                  if o.type == "MESH" and not o.name.startswith("Icosphere")]
        strip_rec = {}
        for o in meshes:
            strip_rec[o.name] = strip_skin_bmesh(o)
        cloth = [o for o in meshes if len(o.data.polygons) > 0]
        with bpy.data.libraries.load(f"{RIG}/bodies/Body_{sex}_Standard.blend") as (s, d):
            d.objects = [body_obj]
        for o in d.objects:
            if o:
                bpy.context.scene.collection.objects.link(o)
        body = bpy.data.objects[body_obj]
        bpy.context.view_layer.update()
        dm = vlib.evaluated_mesh(body)
        bc = dm["co"].copy()
        bt = vlib._triangulate(dm)
        tn = tri_normals_array(bc, bt)
        for o in cloth:
            pts = eval_points(o)
            binds, bstat = bind_garment_to_body(pts, bc, bt, tn)
            dd = np.array(bstat["dist_list"])
            sr = strip_rec[o.name]
            out["H2_skip_proxy"].append({
                "sex": sex, "outfit": outfit, "piece": o.name, "n_verts": int(len(pts)),
                "bind_max_cm": round(float(dd.max() * 100), 3),
                "bind_p50_cm": round(float(np.percentile(dd, 50) * 100), 3),
                "bind_p95_cm": round(float(np.percentile(dd, 95) * 100), 3),
                "bind_p99_cm": round(float(np.percentile(dd, 99) * 100), 3),
                "frac_bind_gt_3cm": round(float((dd > 0.03).mean()), 4),
                "frac_bind_gt_5cm": round(float((dd > 0.05).mean()), 4),
                "frac_bind_gt_10cm": round(float((dd > 0.10).mean()), 4),
                "verdict_skip_candidate": bool((dd > 0.05).mean() > 0.05),
                "faces_before": sr["faces_before"], "faces_removed": sr["faces_removed"],
                "face_removal_frac": round(sr.get("face_removal_frac", 0.0), 4),
                "had_regular_material": sr.get("stripped", False),
            })
            out["H3_strip_coverage"].append({
                "sex": sex, "outfit": outfit, "piece": o.name,
                "stripped": sr.get("stripped", False),
                "kill_materials": sr.get("kill_materials", []),
                "face_removal_frac": round(sr.get("face_removal_frac", 0.0), 4),
            })
        print(f"### H2/H3 {sex} {outfit}: "
              f"skip候选件={[r['piece'] for r in out['H2_skip_proxy'][-len(cloth):] if r['verdict_skip_candidate']]} "
              f"剥离命中件={sum(1 for r in out['H3_strip_coverage'][-len(cloth):] if r['stripped'])}/{len(cloth)}")

    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(a.out, out)
    print(f"[v_humanfactor] wrote {a.out}")


if __name__ == "__main__":
    main()