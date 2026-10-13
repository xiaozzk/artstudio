#!/usr/bin/env python3
"""
v_selftest.py —— verifier 自测：**先证明我自己的"点在网格内部"判定是对的**，
再拿它去量别人的资产。

对三种**解析已知真值**的网格做盲测：
  1. 闭合球（icosphere, r=1）      —— 凸、闭合、无退化
  2. 环面（torus R=1, r=0.4）      —— 凹、闭合、解析内外
  3. 破洞球（球挖掉一块 cap）      —— 闭合性缺失，量我的方法在**非封闭网格**上怎么坏
另外测：
  4. 顶点恰好落在表面上（|d|≈0）    —— 歧义区
  5. 双法一致率 vs 半径             —— 误差随"离表面距离"的变化

产出：assets/3d/rig/reports/verify-selftest.json
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_selftest.py -- \
      --out assets/3d/rig/reports/verify-selftest.json
"""
import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def make_bvh_from_arrays(verts, tris):
    return BVHTree.FromPolygons([Vector(v) for v in verts],
                                [tuple(int(x) for x in t) for t in tris],
                                all_triangles=True)


def icosphere(subdiv=4, radius=1.0):
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    bm.verts.ensure_lookup_table()
    verts = np.array([v.co[:] for v in bm.verts])
    tris = np.array([[v.index for v in f.verts] for f in bm.faces], dtype=np.int32)
    bm.free()
    return verts, tris


def torus(nu=96, nv=48, R=1.0, r=0.4):
    us = np.linspace(0, 2 * math.pi, nu, endpoint=False)
    vs = np.linspace(0, 2 * math.pi, nv, endpoint=False)
    verts = []
    for u in us:
        for v in vs:
            verts.append([(R + r * math.cos(v)) * math.cos(u),
                          (R + r * math.cos(v)) * math.sin(u),
                          r * math.sin(v)])
    verts = np.array(verts)
    tris = []
    for i in range(nu):
        for j in range(nv):
            a = i * nv + j
            b = ((i + 1) % nu) * nv + j
            c = ((i + 1) % nu) * nv + (j + 1) % nv
            d = i * nv + (j + 1) % nv
            tris += [[a, b, c], [a, c, d]]
    return verts, np.array(tris, dtype=np.int32)


def drop_cap(verts, tris, zmin=-0.2):
    """删除所有顶点 z < zmin 的面（制造边界洞）。"""
    keep_v = np.ones(len(verts), dtype=bool)
    keep_v[verts[:, 2] < zmin] = False
    keep_t = keep_v[tris].all(axis=1)
    tris = tris[keep_t]
    used = np.unique(tris)
    remap = -np.ones(len(verts), dtype=np.int32)
    remap[used] = np.arange(len(used))
    return verts[used], remap[tris]


def eval_points(bvh_pts, tris, pts, tol=1e-4, min_votes=4):
    bvh = make_bvh_from_arrays(bvh_pts, tris)
    return vlib.point_in_mesh_report(bvh, pts, tol=tol, min_votes=min_votes)


def run_case(name, verts, tris, pts, truth, tol=1e-4, note=""):
    bvh = make_bvh_from_arrays(verts, tris)
    rep = vlib.point_in_mesh_report(bvh, pts, tol=tol)
    ray, nrm, amb = rep["inside_ray"], rep["inside_norm"], rep["ambiguous"]
    signed = rep["signed"]
    out = {
        "case": name, "note": note,
        "n_points": int(len(pts)),
        "n_faces": int(len(tris)),
        "closed_assumed": True,
        "ray_accuracy": float(np.mean(ray == truth)),
        "normal_accuracy": float(np.mean(nrm == truth)),
        "two_method_agreement": float(rep["agree_rate"]),
        "ambiguous_frac": float(np.mean(amb)),
        "combined_accuracy": float(np.mean(np.where(amb, ~truth, ray) == truth)),
    }
    # 按"离表面距离"分桶看误差
    d = np.abs(signed)
    buckets = []
    edges = [0, 1e-4, 1e-3, 1e-2, 0.1, 1e9]
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (d >= lo) & (d < hi)
        if m.sum() == 0:
            continue
        buckets.append({
            "dist_range": [lo, hi], "n": int(m.sum()),
            "ray_acc": float(np.mean(ray[m] == truth[m])),
            "normal_acc": float(np.mean(nrm[m] == truth[m])),
            "agree": float(np.mean(ray[m] == nrm[m])),
        })
    out["by_distance"] = buckets
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-selftest.json")
    a = ap.parse_args(argv_after_ddash())
    rng = np.random.default_rng(7)
    cases = []

    # --- 1. 球真值 ---
    sv, st = icosphere(4, 1.0)
    p = rng.normal(size=(3000, 3))
    p /= np.linalg.norm(p, axis=1, keepdims=True)
    rr = rng.uniform(0.15, 1.35, size=(3000, 1))
    pts = p * rr
    truth_sphere = (rr[:, 0] < 1.0)
    cases.append(run_case("closed_icosphere_r1", sv, st, pts, truth_sphere,
                          note="凸闭合；真值 = |p|<1"))

    # --- 2. 环面真值（凹面，最像人体腋下/裆部） ---
    tv, tt = torus()
    pts = np.column_stack([rng.uniform(-1.6, 1.6, 2000),
                           rng.uniform(-1.6, 1.6, 2000),
                           rng.uniform(-0.7, 0.7, 2000)])
    R, r = 1.0, 0.4
    q = np.sqrt(pts[:, 0] ** 2 + pts[:, 1] ** 2) - R
    truth_torus = (q ** 2 + pts[:, 2] ** 2) < r ** 2
    cases.append(run_case("closed_torus_R1_r0.4", tv, tt, pts, truth_torus,
                          note="凹闭合；解析真值 (√(x²+y²)−R)²+z² < r²"))

    # --- 3. 破洞球（量非封闭网格的退化） ---
    dv, dt = drop_cap(sv, st, zmin=-0.3)
    pts_open = p * rr
    cases.append(run_case("open_icosphere_missing_cap", dv, dt, pts_open, truth_sphere,
                          note="球缺一块 cap（z<-0.3 的面删掉）→ 有边界洞；"
                               "真值仍是 |p|<1。这里量的是**我的方法在非封闭网格上的坏法**"))

    # --- 4. 表面点（|d|≈0，歧义区） ---
    surf = sv[rng.integers(0, len(sv), 500)]
    truth4 = np.zeros(500, dtype=bool)
    cases.append(run_case("on_surface_points", sv, st, surf, truth4,
                          note="点直接取球面原顶点 → 真值应为'表面'，"
                               "这里把 truth 记为 False（不内部）来量两法在退化点的行为"))

    # --- 5. 球：真值 vs 半径细扫 ---
    sweep = []
    for radius in (0.30, 0.50, 0.70, 0.85, 0.95, 0.99, 1.01, 1.05, 1.15, 1.30):
        p2 = rng.normal(size=(600, 3))
        p2 /= np.linalg.norm(p2, axis=1, keepdims=True)
        pts2 = p2 * radius
        rep = eval_points(sv, st, pts2)
        eq = (radius < 1.0)
        sweep.append({
            "radius": radius, "truth": bool(eq),
            "ray_acc": float(np.mean(rep["inside_ray"] == eq)),
            "normal_acc": float(np.mean(rep["inside_norm"] == eq)),
            "agree": float(rep["agree_rate"]),
            "signed_mean": float(np.nanmean(rep["signed"])),
        })
    cases.append({"case": "sphere_radius_sweep", "sweep": sweep,
                  "note": "离表面越远越可靠；越近越容易翻边"})

    out = {
        "generated_by": "verifier/v_selftest.py",
        "blender": bpy.app.version_string,
        "purpose": "在解析真值网格上标定 verifier 自己的 inside/outside 判定误差，"
                   "再拿同一套代码去量 body/garment。",
        "min_votes_default": 4, "tol_default": 1e-4,
        "cases": cases,
    }
    vlib.jdump(a.out, out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[v_selftest] wrote {a.out}")


if __name__ == "__main__":
    main()