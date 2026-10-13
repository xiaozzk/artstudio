#!/usr/bin/env python3
"""
v_transfer.py —— verifier **自己实现** SPEC §4.2 的 morph 传递，用来
  (a) 独立计时「传递」这一步；
  (b) T2 的 `garments/*.blend` 落地后，逐顶点对账他们传出来的 morph；
  (c) 量化 SPEC §4.4 的"自由垂坠件绑错"到底长什么样。

算法（逐字按 SPEC §4.2，但代码独立）：
  绑定（一次性）：p 在【标准体 rest】上最近三角面 t / 命中点 q / 面法线 n
                 w = q 在 t 的重心坐标；F=(n,t̂,û)；o = p−q 在 F 下的分量
  求值：           P' = Σ wᵢV'ᵢ ；F' = 变形后 t 的标架 ；p' = P' + o 在 F' 下重组

只读，不写 .blend（`--apply` 时也只改内存）。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_transfer.py -- \
      --out assets/3d/rig/reports/verify-transfer.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
RIG = f"{ROOT}/assets/3d/rig"
OLD = f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits"


def frame_from_tri(a, b, c, n):
    """三角面标架 (n, t̂, û)。t̂ 取 AB 方向去 n 分量；û = n × t̂。"""
    e = b - a
    e = e - n * float(np.dot(e, n))
    ln = np.linalg.norm(e)
    if ln < 1e-9:
        e = np.array([1.0, 0.0, 0.0]) - n * n[0]
        ln = np.linalg.norm(e)
        if ln < 1e-9:
            e = np.array([0.0, 1.0, 0.0]) - n * n[1]
            ln = np.linalg.norm(e)
    t_hat = e / max(ln, 1e-12)
    u_hat = np.cross(n, t_hat)
    return np.stack([n, t_hat, u_hat], axis=0)   # (3,3) 行向量基


def barycentric(q, a, b, c):
    v0, v1, v2 = b - a, c - a, q - a
    d00 = v0 @ v0
    d01 = v0 @ v1
    d11 = v1 @ v1
    d20 = v2 @ v0
    d21 = v2 @ v1
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-20:
        return np.array([1.0, 0.0, 0.0])
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1.0 - v - w
    return np.array([u, v, w])


class Bind:
    """一次性绑定数据。SPEC 声称 ≈28 字节/顶点。"""

    __slots__ = ("tri", "bary", "offset", "dist", "rest_q", "rest_F")

    def __init__(self, tri, bary, offset, dist, rest_q, rest_F):
        self.tri = tri
        self.bary = bary
        self.offset = offset
        self.dist = dist
        self.rest_q = rest_q
        self.rest_F = rest_F


def bind_garment_to_body(gar_pts, body_co, body_tris, tri_normals, max_dist=None):
    """近邻绑定。返回 (list[Bind], 统计)。"""
    bvh = BVHTree.FromPolygons([Vector(p) for p in body_co],
                               [tuple(int(x) for x in t) for t in body_tris],
                               all_triangles=True)
    binds = []
    stats = {"max_dist_cm": 0.0, "dist_list": []}
    t0 = time.perf_counter()
    for p in gar_pts:
        loc, nor, idx, dist = bvh.find_nearest(Vector(p), 1e7)
        if loc is None or idx is None:
            binds.append(None)
            continue
        ti = int(idx)
        tri = body_tris[ti]
        a, b, c = body_co[tri[0]], body_co[tri[1]], body_co[tri[2]]
        q = np.array(loc)
        bary = barycentric(q, a, b, c)
        n = tri_normals[ti]
        F = frame_from_tri(a, b, c, n)
        off = F @ (np.array(p) - q)
        binds.append(Bind(tri, bary, off, float(dist), q, F))
        stats["dist_list"].append(float(dist))
    stats["bind_seconds"] = time.perf_counter() - t0
    dl = np.array(stats["dist_list"]) if stats["dist_list"] else np.zeros(1)
    stats["max_dist_cm"] = float(dl.max() * 100)
    stats["mesh_bytes_if_28B_per_vert"] = 28 * len(gar_pts)
    return binds, stats


def eval_transfer(gar_pts, binds, body_eval_co, body_tris, tri_normals_eval):
    """求值：把绑定数据应用到变形后的标准体上。"""
    out = np.array(gar_pts, dtype=np.float64, copy=True)
    tri_normals_eval = tri_normals_eval
    for i, bd in enumerate(binds):
        if bd is None:
            continue
        tri = bd.tri
        V = body_eval_co[tri]                     # (3,3)
        P = bd.bary @ V
        a, b, c = V[0], V[1], V[2]
        n = tri_normals_eval[int(bd.tri[0])] if False else None
        # 变形后法线 = 三角形绕向法线（比顶点法线稳，且与 rest 同一算法）
        fn = np.cross(b - a, c - a)
        ln = np.linalg.norm(fn)
        if ln < 1e-12:
            fn = np.array([0.0, 0.0, 1.0])
        else:
            fn = fn / ln
        Fp = frame_from_tri(a, b, c, fn)
        out[i] = P + Fp.T @ bd.offset
    return out


def tri_normals_array(co, tris):
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    ln = np.linalg.norm(fn, axis=1, keepdims=True)
    ln[ln < 1e-12] = 1.0
    return fn / ln


def argc_parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-transfer.json")
    ap.add_argument("--body", default=None, help="指定标准体，默认按 sex 取")
    return ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


CASES = [("Female", "Outfit_Female_Ranger", "Body_Female"),
         ("Male", "Outfit_Male_Ranger", "Body_Male"),
         ("Female", "Outfit_Female_Peasant", "Body_Female"),
         ("Male", "Outfit_Male_Peasant", "Body_Male")]


def main():
    """独立计时「剥离 → 贴合 → 传递 → 验收」四步（用旧资产 + 新标准体）。"""
    a = argc_parse()
    from v_penetration import bone_space_refit, eval_points, strip_skin_bmesh, weights_of
    out = {"generated_by": "verifier/v_transfer.py",
           "note": "verifier 自己实现的 SPEC §4.2 传递；用于计时 + 与 T2 对账。",
           "cases": []}
    for sex, outfit, body_obj in CASES:
        rec = {"sex": sex, "outfit": outfit, "phases_s": {}}
        t_all = time.perf_counter()
        bpy.ops.wm.open_mainfile(filepath=f"{OLD}/{outfit}.blend")
        rigA = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
        restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}
        meshes = [o for o in bpy.data.objects
                  if o.type == "MESH" and not o.name.startswith("Icosphere")]

        # ---- ① 剥离 ----
        t = time.perf_counter()
        strip = {}
        for o in meshes:
            strip[o.name] = strip_skin_bmesh(o)
        cloth = [o for o in meshes if len(o.data.polygons) > 0]
        rec["phases_s"]["1_strip"] = round(time.perf_counter() - t, 4)
        rec["strip_removed_faces"] = sum(v.get("faces_removed", 0) for v in strip.values())

        # ---- 载入标准体 ----
        t = time.perf_counter()
        with bpy.data.libraries.load(f"{RIG}/bodies/Body_{sex}_Standard.blend") as (s, d):
            d.objects = [body_obj]
        for o in d.objects:
            if o:
                bpy.context.scene.collection.objects.link(o)
        body = bpy.data.objects[body_obj]
        bpy.context.view_layer.update()
        W = {o.name: weights_of(o) for o in cloth}
        rigB = body.find_armature()
        restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}
        rec["phases_s"]["load_body"] = round(time.perf_counter() - t, 4)

        # ---- ② 贴合（骨空间） ----
        t = time.perf_counter()
        refit = {}
        for o in cloth:
            for m in o.modifiers:
                if m.type == "ARMATURE":
                    m.object = rigB
        for o in cloth:
            refit[o.name] = bone_space_refit(o, restA, restB, W[o.name])
        bpy.context.view_layer.update()
        rec["phases_s"]["2_refit_bone_space"] = round(time.perf_counter() - t, 4)

        # ---- ③ 传递 ----
        t = time.perf_counter()
        dm = vlib.evaluated_mesh(body)
        body_co0 = dm["co"].copy()
        body_tris = vlib._triangulate(dm)
        body_bvh = BVHTree.FromPolygons(
            [Vector(p) for p in body_co0],
            [tuple(int(x) for x in t_) for t_ in body_tris], all_triangles=True)
        triN0 = tri_normals_array(body_co0, body_tris)

        # 三档的标准体几何（走 shape key 求值）
        sk = body.data.shape_keys
        tiers = {"Basis": None}
        for kb in sk.key_blocks[1:]:
            tiers[kb.name] = None
        def body_at(key, w):
            for kb in sk.key_blocks:
                kb.value = float(w) if kb.name == key else 0.0
            bpy.context.view_layer.update()
            return vlib.evaluated_mesh(body)["co"].copy()
        tier_co = {"Basis": body_at("Basis", 0.0)}
        for kb in sk.key_blocks[1:]:
            tier_co[kb.name] = body_at(kb.name, 1.0)
        for kb in sk.key_blocks:
            kb.value = 0.0
        bpy.context.view_layer.update()
        t_bind = time.perf_counter()
        per_piece = {}
        cache = {}
        for o in cloth:
            pts = eval_points(o)
            binds, bstat = bind_garment_to_body(pts, body_co0, body_tris, triN0)
            cache[o.name] = (pts, binds)
            per_piece[o.name] = {
                "n_verts": int(len(pts)),
                "bind_seconds": round(bstat["bind_seconds"], 4),
                "max_bind_dist_cm": round(bstat["max_dist_cm"], 3),
                "mean_bind_dist_cm": round(float(np.mean(bstat["dist_list"]) * 100), 3)
                if bstat["dist_list"] else None,
                "p95_bind_dist_cm": round(float(np.percentile(bstat["dist_list"], 95) * 100), 3)
                if bstat["dist_list"] else None,
                "bind_bytes_28B_per_vert": bstat["mesh_bytes_if_28B_per_vert"],
            }
        rec["phases_s"]["3a_bind"] = round(time.perf_counter() - t_bind, 4)

        t_eval = time.perf_counter()
        for tier, bco in tier_co.items():
            triN = tri_normals_array(bco, body_tris)
            for o in cloth:
                pts, binds = cache[o.name]
                moved = eval_transfer(pts, binds, bco, body_tris, triN)
                if tier == "Basis":
                    per_piece[o.name]["transfer_noop_max_cm"] = float(
                        np.linalg.norm(moved - pts, axis=1).max() * 100)
                else:
                    d = np.linalg.norm(moved - pts, axis=1)
                    per_piece[o.name][f"{tier}_max_cm"] = float(d.max() * 100)
                    per_piece[o.name][f"{tier}_mean_cm"] = float(d.mean() * 100)
        rec["phases_s"]["3b_transfer_eval"] = round(time.perf_counter() - t_eval, 4)
        rec["phases_s"]["3_transfer_total"] = round(
            rec["phases_s"]["3a_bind"] + rec["phases_s"]["3b_transfer_eval"], 4)
        rec["per_piece"] = per_piece
        rec["n_cloth_verts"] = int(sum(len(cache[o.name][0]) for o in cloth))
        rec["phases_s"]["total"] = round(time.perf_counter() - t_all, 3)
        out["cases"].append(rec)
        print(f"### {sex} {outfit}: strip={rec['phases_s']['1_strip']}s "
              f"refit={rec['phases_s']['2_refit_bone_space']}s "
              f"bind={rec['phases_s']['3a_bind']}s eval={rec['phases_s']['3b_transfer_eval']}s "
              f"verts={rec['n_cloth_verts']}", flush=True)
        for k, v in sorted(per_piece.items(),
                           key=lambda kv: -(kv[1].get("BS_Heavy_max_cm") or 0))[:4]:
            print(f"    {k:<32} bindMax={v['max_bind_dist_cm']:7.2f}cm "
                  f"thin={v.get('BS_Thin_max_cm', 0):6.3f} heavy={v.get('BS_Heavy_max_cm', 0):6.3f} "
                  f"noop={v.get('transfer_noop_max_cm', 0):.2e}cm")
    vlib.jdump(a.out, out)
    print(f"[v_transfer] wrote {a.out}")


if __name__ == "__main__":
    main()