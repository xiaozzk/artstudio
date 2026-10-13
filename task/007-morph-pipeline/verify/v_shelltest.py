#!/usr/bin/env python3
"""
v_shelltest.py —— 审查「噪声底合成壳」这个做法本身是否成立。

背景：Lead 用"标准体躯干顶点沿**顶点法线**外推 1.5 cm"造一个"必然在体外"的壳，
测出该指标误判 3.62%（女）/ 4.52%（男），并据此把穿模率下修。
**本脚本检验这个壳到底是不是"必然在体外"。**

关键怀疑：标准体网格的**面绕向不一致** → 由绕向算出的顶点法线是**乱指**的，
"沿法线外推"在相当一部分顶点上根本不是往外推，而是在体内乱走。

做法：三套法线各造一套壳，同一套射线奇偶判定，对比：
  N1 原始叉积顶点法线（绕向依赖，= 常见做法）
  N2 Blender `mesh.vertex_normals`（圆角加权，仍依赖绕向）
  N3 **绕向校正后的外向顶点法线**（逐面按"面心相对质心"翻正 → 与绕向无关）
并报告绕向不一致率。

只读，不写 .blend。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_shelltest.py -- \
      --out assets/3d/rig/reports/verify-shelltest.json
"""
import argparse
import json
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

NEW = "/Users/zhenkunzhu/Desktop/project/artstudio/assets/3d/rig"


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def face_arrays(co, tris):
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    fc = (a + b + c) / 3.0
    return fn, fc


def winding_consistent_normals(co, tris, ref=None):
    """N3：逐面按"面心相对参考点的方向"翻正 → 得到与绕向无关的外向面法线。

    ⚠ 前提：网格相对 ref 近似**星形**（人体在 T-pose 下除裆部/腋下外基本满足）。
    不满足处会被翻错 —— 这也正是本脚本要量化的一部分。
    """
    fn, fc = face_arrays(co, tris)
    ref = co.mean(axis=0) if ref is None else ref
    d = fc - ref
    flip = (fn * d).sum(axis=1) < 0
    fn2 = fn.copy()
    fn2[flip] = -fn2[flip]
    return fn2, flip, fc


def accumulate_vertex_normals(co, tris, fn, area_weight=True):
    """面法线 → 顶点法线（可选面积加权：|fn| 本身就是 2×面积）。"""
    w = fn if area_weight else fn / np.maximum(
        np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    vn = np.zeros_like(co)
    for k in range(3):
        np.add.at(vn, tris[:, k], w)
    ln = np.linalg.norm(vn, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    return vn / ln


def blender_vertex_normals(obj):
    me = obj.data
    n = len(me.vertices)
    vn = np.empty(n * 3)
    try:
        me.vertices.foreach_get("normal", vn)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    return vn.reshape(n, 3), None


def edge_winding_check(tris):
    """对每条被恰好 2 个面共享的边，检查两个面是否**反向**遍历它。

    一致绕向 ⟺ 反向遍历。违例 = 真正的绕向不一致（与星形性无关）。
    """
    from collections import defaultdict
    em = defaultdict(list)          # (min,max) -> [(face_idx, direction)]
    for fi, t in enumerate(tris):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            key = (int(a), int(b)) if a < b else (int(b), int(a))
            em[key].append(1 if a < b else -1)
    shared = {k: v for k, v in em.items() if len(v) == 2}
    bad = sum(1 for v in shared.values() if v[0] == v[1])
    boundary = sum(1 for v in em.values() if len(v) == 1)
    nonmanifold = sum(1 for v in em.values() if len(v) > 2)
    return {
        "n_edges": len(em), "n_shared_by_2": len(shared),
        "n_boundary_edges": boundary, "n_nonmanifold_edges": nonmanifold,
        "n_winding_violations": bad,
        "winding_violation_frac": round(bad / max(len(shared), 1), 5),
        "is_watertight": boundary == 0,
        "verdict": ("绕向一致" if bad == 0 else "**绕向不一致**：由绕向派生的法线不可靠"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-shelltest.json")
    a = ap.parse_args(argv_after_ddash())
    out = {"generated_by": "verifier/v_shelltest.py",
           "question": "Lead 的『噪声底合成壳』是否真的『必然在体外』？", "cases": []}
    t0 = time.perf_counter()
    for sex, body_name, zlo, zhi in (("Female", "Body_Female", 0.80, 1.50),
                                     ("Male", "Body_Male", 0.80, 1.50)):
        bpy.ops.wm.open_mainfile(filepath=f"{NEW}/bodies/{body_name}_Standard.blend")
        body = bpy.data.objects[body_name]
        bpy.context.view_layer.update()
        m = vlib.evaluated_mesh(body)
        M = np.array(body.matrix_world)
        co = m["co"] @ M[:3, :3].T + M[:3, 3]
        tris = vlib._triangulate(m)
        tree, _, _ = vlib.bvh_from_eval(body)
        rec = {"sex": sex, "body": body_name, "n_verts": len(co), "n_tris": len(tris)}

        # --- 严格的绕向一致性检验：共享边是否被两个面反向遍历 ---
        # 不依赖"星形"假设，是绕向一致性的**充要**判据（对 2-流形部分）
        rec["edge_winding_check"] = edge_winding_check(tris)

        # --- 粗略诊断（用身体质心做参考；会被凹面干扰，仅作对照） ---
        cen = co.mean(axis=0)
        fn, fc = face_arrays(co, tris)
        orient = (fn * (fc - cen)).sum(axis=1)
        rec["winding_diagnosis"] = {
            "face_centroid_centroid": [round(float(x), 4) for x in cen],
            "frac_faces_pointing_outward_by_raw_winding": round(
                float(np.mean(orient > 0)), 4),
            "frac_faces_pointing_inward_by_raw_winding": round(
                float(np.mean(orient < 0)), 4),
            "mean_abs_dot_normalised": round(float(
                np.mean(np.abs(orient) / np.maximum(
                    np.linalg.norm(fn, axis=1) * np.linalg.norm(fc - cen, axis=1), 1e-12))), 4),
            "verdict": "若两向都不接近 0/1，说明面绕向**不一致** → 由绕向算的顶点法线不可靠",
        }
        print(f"### {sex}: 绕向外向面占比="
              f"{rec['winding_diagnosis']['frac_faces_pointing_outward_by_raw_winding']:.3f}"
              f" 内向={rec['winding_diagnosis']['frac_faces_pointing_inward_by_raw_winding']:.3f}")

        # --- 三套顶点法线 ---
        n1 = accumulate_vertex_normals(co, tris, fn)               # 原始（绕向依赖）
        fn3, flip, _ = winding_consistent_normals(co, tris, cen)
        n3 = accumulate_vertex_normals(co, tris, fn3)              # 绕向校正
        n2, err = blender_vertex_normals(body)
        rec["normals_available"] = {"N1_raw_cross": True, "N3_winding_fixed": True,
                                    "N2_blender": err is None, "N2_error": err}
        rec["faces_flipped_by_winding_fix"] = round(float(np.mean(flip)), 4)

        # 法线一致率
        def agree(nx, ny):
            return round(float(np.mean((nx * ny).sum(axis=1) > 0.9)), 4)
        rec["normal_agreement"] = {
            "N1_vs_N3": agree(n1, n3),
            "N1_vs_N2": agree(n1, n2) if n2 is not None else None,
            "N2_vs_N3": agree(n2, n3) if n2 is not None else None,
        }
        print(f"  法线一致率 N1vsN3={rec['normal_agreement']['N1_vs_N3']} "
              f"N1vsN2={rec['normal_agreement']['N1_vs_N2']} "
              f"N2vsN3={rec['normal_agreement']['N2_vs_N3']}")

        tors = (co[:, 2] >= zlo) & (co[:, 2] <= zhi)
        rec["n_torso_verts"] = int(tors.sum())
        rec["shell_sweep"] = []
        for d_cm in (0.5, 1.0, 1.5, 3.0, 6.0):
            row = {"offset_cm": d_cm}
            for tag, nrm in (("N1_raw_cross", n1), ("N2_blender", n2),
                             ("N3_winding_fixed", n3)):
                if nrm is None:
                    row[tag] = None
                    continue
                pts = co[tors] + nrm[tors] * (d_cm / 100.0)
                rep = vlib.point_in_mesh_report(tree, pts, co_for_calib=co)
                row[tag] = {
                    "ray_inside_frac": round(float(rep["inside_ray"].mean()), 5),
                    "norm_inside_frac": round(float(rep["inside_norm"].mean()), 5),
                }
            rec["shell_sweep"].append(row)
            print(f"  shell δ={d_cm:>4}cm  " + "  ".join(
                f"{t}={row[t]['ray_inside_frac']*100:6.2f}%" if row[t] else f"{t}=n/a"
                for t in ("N1_raw_cross", "N2_blender", "N3_winding_fixed")))
        out["cases"].append(rec)
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(a.out, out)
    print(f"[v_shelltest] wrote {a.out}")


if __name__ == "__main__":
    main()