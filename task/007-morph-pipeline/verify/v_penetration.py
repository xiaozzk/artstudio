#!/usr/bin/env python3
"""
v_penetration.py —— verifier **独立**重测「服装 ↔ 标准体」穿模率。

与 Lead 的 `lead/refit_necessity_v2.py` **零共享代码**，本文件：
  · 分开实现内外判定（7 方向射线奇偶 + 最近点法线定向，符号自动标定）
  · 分开实现骨空间 refit（自己写 LBS 式加权变换）
  · 分开实现「剥离 MI_Regular_* 皮肤面」（用 bmesh，不用 ops）
  · 自己造**三类噪声底**，而不是直接采信你说的 3.62%/4.52%

跑出来的东西写 assets/3d/rig/reports/verify-penetration.json + 控制台表格。

只读资产，绝不写 .blend。
用法：
  BL=/Applications/Blender.app/Contents/MacOS/Blender
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_penetration.py -- \
      --out assets/3d/rig/reports/verify-penetration.json
"""
import argparse
import json
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OLD = f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits"
NEW = f"{ROOT}/assets/3d/rig"

CASES = [
    ("Female", "Outfit_Female_Ranger", "Body_Female"),
    ("Male", "Outfit_Male_Ranger", "Body_Male"),
    ("Female", "Outfit_Female_Peasant", "Body_Female"),
    ("Male", "Outfit_Male_Peasant", "Body_Male"),
]


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


# ---------------------------------------------------------------- 基础工具

def eval_points(obj):
    """求值后世界坐标顶点（N,3）—— shape key / armature 全在内。"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    M = np.array(ev.matrix_world)
    co = co @ M[:3, :3].T + M[:3, 3]
    ev.to_mesh_clear()
    return co


def bvh_of_points(co, tris):
    verts = [Vector(v) for v in co]
    return BVHTree.FromPolygons(verts, [tuple(int(x) for x in t) for t in tris],
                                all_triangles=True)


def body_bvh(body):
    m = vlib.evaluated_mesh(body)
    M = np.array(body.matrix_world)
    co = m["co"] @ M[:3, :3].T + M[:3, 3]
    tris = vlib._triangulate(m)
    return bvh_of_points(co, tris), co, tris


def bone_space_refit(obj, restA, restB, weights):
    """骨空间重绑（verifier 自己实现）。

    对每个顶点：p' = Σ_b w_b · (M_b^B · (M_b^A)⁻¹ · p)，w 归一化。
    这就是标准的 LBS 重绑；**不含任何几何贴合/包裹**。
    返回 (max_disp_m, mean_disp_m, moved_frac, p95_disp_m)
    """
    mw = np.array(obj.matrix_world)
    inv = np.linalg.inv(mw)
    n = len(obj.data.vertices)
    raw = np.empty(n * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", raw)
    raw = raw.reshape(n, 3)
    world = raw @ mw[:3, :3].T + mw[:3, 3]
    out = world.copy()
    # 预先把每根骨的 4x4 变换算成 numpy
    T = {}
    for bn, MA in restA.items():
        MB = restB.get(bn)
        if MB is None:
            continue
        T[bn] = np.array(MB @ MA.inverted())
    for vi in range(n):
        ws = weights[vi]
        if not ws:
            continue
        acc = np.zeros(3)
        tot = 0.0
        p4 = np.array([world[vi][0], world[vi][1], world[vi][2], 1.0])
        for bn, w in ws:
            M = T.get(bn)
            if M is None:
                continue
            acc += w * (M @ p4)[:3]
            tot += w
        if tot <= 0:
            continue
        out[vi] = acc / tot
    newlocal = out @ inv[:3, :3].T + inv[:3, 3]
    obj.data.vertices.foreach_set("co", newlocal.reshape(-1).astype(np.float32))
    obj.data.update()
    d = np.linalg.norm(out - world, axis=1)
    return {
        "max_cm": float(d.max() * 100), "mean_cm": float(d.mean() * 100),
        "p95_cm": float(np.percentile(d, 95) * 100),
        "moved_frac": float(np.mean(d > 1e-7)),
        "moved_verts": int((d > 1e-7).sum()), "n_verts": int(n),
    }


def weights_of(obj, eps=1e-6):
    gn = {vg.index: vg.name for vg in obj.vertex_groups}
    me = obj.data
    n = len(me.vertices)
    dv = me.vertices
    out = []
    for v in dv:
        gs = [(gn[g.group], g.weight) for g in v.groups
              if g.weight > eps and g.group in gn]
        s = sum(w for _, w in gs)
        out.append([(nm, w / s) for nm, w in gs] if s > 0 else [])
    return out


def strip_skin_bmesh(obj):
    """按材质名以 MI_Regular_ 开头的面 → 删除。用 bmesh，不依赖 ops/选择态。"""
    names = [m.name if m else "" for m in obj.data.materials]
    kill = {i for i, nm in enumerate(names) if nm.startswith("MI_Regular_")}
    before_f = len(obj.data.polygons)
    before_v = len(obj.data.vertices)
    if not kill:
        return {"stripped": False, "faces_before": before_f, "faces_after": before_f,
                "faces_removed": 0, "verts_before": before_v, "verts_after": before_v}
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    faces = [f for f in bm.faces if f.material_index in kill]
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    # 清掉孤立顶点（皮肤面删完后留下没人用的顶点）
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    after_f = len(obj.data.polygons)
    after_v = len(obj.data.vertices)
    return {"stripped": True, "faces_before": before_f, "faces_after": after_f,
            "faces_removed": before_f - after_f,
            "face_removal_frac": (before_f - after_f) / before_f if before_f else 0.0,
            "verts_before": before_v, "verts_after": after_v,
            "kill_materials": sorted(names[i] for i in kill)}


# ---------------------------------------------------------------- 噪声底

def noise_floors(body_bvh_tree, body_co, body_tris, log):
    """三类独立噪声底。"""
    res = {}

    # (1) 远场：把标准体整体平移 5 m（z 方向，人体高 ≈1.8 m）—— 100% 必然在体外
    #     ⚠ 上一版用 +1 m x 位移是**错的**：T-pose 手臂跨度 ±0.9 m，
    #       平移后右臂正好落进原身体左臂里 → 假"内部" 12.6%。这是测试设计缺陷，不是度量误差。
    for shift, tag in ((np.array([0.0, 0.0, 5.0]), "z+5m"),
                       (np.array([5.0, 0.0, 0.0]), "x+5m")):
        far = body_co + shift
        rep = vlib.point_in_mesh_report(body_bvh_tree, far, co_for_calib=body_co)
        ov = bbox_overlap(body_co, far)
        res[f"farfield_body_shifted_{tag}"] = {
            "n": int(len(far)),
            "ray_inside_frac": float(rep["inside_ray"].mean()),
            "norm_inside_frac": float(rep["inside_norm"].mean()),
            "ambiguous_frac": float(rep["ambiguous"].mean()),
            "agree": rep["agree_rate"],
            "bbox_overlap": ov,
            "expected_inside_frac": 0.0,
            "note": "绝对噪声底：位移 5 m 的点不可能在体内，任何 >0 都是度量误差。"
                    "bbox_overlap 必须为 False 才算有效实验。",
        }

    # (2) 复刻 Lead 的合成壳：躯干顶点沿顶点法线外推 δ —— 但做 δ 扫描
    me = None
    # 顶点法线从求值网格取
    vn = vertex_normals(body_co, body_tris)
    tors = (body_co[:, 2] >= 0.80) & (body_co[:, 2] <= 1.50)
    res["lead_style_normal_shell_sweep"] = {"n_torso_verts": int(tors.sum()), "sweeps": []}
    for d_cm in (0.5, 1.0, 1.5, 3.0, 6.0, 10.0):
        pts = body_co[tors] + vn[tors] * (d_cm / 100.0)
        rep = vlib.point_in_mesh_report(body_bvh_tree, pts, co_for_calib=body_co)
        s = np.abs(np.nan_to_num(rep["signed"], nan=0.0))
        res["lead_style_normal_shell_sweep"]["sweeps"].append({
            "offset_cm": d_cm,
            "ray_inside_frac": float(rep["inside_ray"].mean()),
            "norm_inside_frac": float(rep["inside_norm"].mean()),
            "ambiguous_frac": float(rep["ambiguous"].mean()),
            "agree": rep["agree_rate"],
            "median_abs_signed_cm": float(np.median(s) * 100),
        })
    res["lead_style_normal_shell_sweep"]["note"] = (
        "Lead 报 1.5 cm 壳误判 3.62%/4.52%。本扫描看的是：该数字随外推距离怎么变。"
        "若 δ 变大到 6-10 cm 后趋近 0，则 1.5 cm 时的数字主要是**壳构造伪影**"
        "（凹面处沿法线外推反而推进体内），不是度量本身的噪声底。")
    log("noise floors done")
    return res


def bbox_overlap(a, b, pad=0.0):
    lo1, hi1 = a.min(axis=0), a.max(axis=0)
    lo2, hi2 = b.min(axis=0), b.max(axis=0)
    return bool(np.all(lo1 - pad <= hi2) and np.all(lo2 - pad <= hi1))


def vertex_normals(co, tris):
    """按面积加权的顶点法线（自己算，不依赖 Blender 的 normal 缓存）。"""
    vn = np.zeros_like(co)
    a = co[tris[:, 0]]
    b = co[tris[:, 1]]
    c = co[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    for k in range(3):
        np.add.at(vn, tris[:, k], fn)
    ln = np.linalg.norm(vn, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    return vn / ln


# ---------------------------------------------------------------- 主流程

def run_case(sex, outfit_name, body_obj_name, out_rec, log):
    t_case = time.perf_counter()
    outfit_path = f"{OLD}/{outfit_name}.blend"
    body_path = f"{NEW}/bodies/Body_{body_obj_name.replace('Body_', '')}_Standard.blend"
    if not os.path.exists(body_path):
        body_path = f"{NEW}/bodies/Body_{sex}_Standard.blend"
    rec = {"sex": sex, "outfit": outfit_name, "outfit_path": outfit_path,
           "body_path": body_path, "phases": {}, "states": {},
           "per_piece": {}, "strip": {}, "check_3_1_equals_2": {}}

    # ---- ① 打开服装 + 记录骨架 rest ----
    t = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=outfit_path)
    rigs = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    rigA = rigs[0]
    restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}
    rec["rig_A"] = {"name": rigA.name, "n_bones": len(rigA.data.bones),
                    "n_armatures_in_file": len(rigs)}
    meshes = [o for o in bpy.data.objects
              if o.type == "MESH" and not o.name.startswith("Icosphere")]
    rec["meshes_in_file"] = [{"name": o.name, "verts": len(o.data.vertices),
                              "faces": len(o.data.polygons),
                              "materials": [m.name if m else None for m in o.data.materials]}
                             for o in meshes]
    rec["phases"]["open_outfit_s"] = round(time.perf_counter() - t, 3)

    # ---- ② 剥离皮肤面 ----
    t = time.perf_counter()
    strip_recs = {}
    for o in meshes:
        strip_recs[o.name] = strip_skin_bmesh(o)
    cloth = [o for o in meshes if len(o.data.polygons) > 0]
    rec["strip"] = strip_recs
    rec["phases"]["strip_skin_s"] = round(time.perf_counter() - t, 3)

    # ---- ③ 状态① 基线（服装挂自带 rig） ----
    t = time.perf_counter()
    bpy.context.view_layer.update()
    pts1 = {o.name: eval_points(o) for o in cloth}
    W = {o.name: weights_of(o) for o in cloth}
    rec["phases"]["eval_state1_s"] = round(time.perf_counter() - t, 3)

    # ---- ④ 载入标准体 + 建 BVH ----
    t = time.perf_counter()
    with bpy.data.libraries.load(body_path) as (src, dst):
        dst.objects = [body_obj_name]
    for o in dst.objects:
        if o:
            bpy.context.scene.collection.objects.link(o)
    body = bpy.data.objects[body_obj_name]
    bpy.context.view_layer.update()
    tree, body_co, body_tris = body_bvh(body)
    rigB = body.find_armature() or [o for o in bpy.data.objects
                                    if o.type == "ARMATURE"][-1]
    restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}
    rec["rig_B"] = {"name": rigB.name, "n_bones": len(rigB.data.bones)}
    rec["body_obj"] = body_obj_name
    rec["phases"]["load_body_and_bvh_s"] = round(time.perf_counter() - t, 3)

    # ---- ⑤ 噪声底 ----
    t = time.perf_counter()
    rec["noise_floor"] = noise_floors(tree, body_co, body_tris, log)
    rec["phases"]["noise_floor_s"] = round(time.perf_counter() - t, 3)

    # ---- ⑥ 状态② 不贴合（只改挂骨架） ----
    t = time.perf_counter()
    for o in cloth:
        for m in o.modifiers:
            if m.type == "ARMATURE":
                m.object = rigB
    bpy.context.view_layer.update()
    pts2 = {o.name: eval_points(o) for o in cloth}
    rec["phases"]["eval_state2_s"] = round(time.perf_counter() - t, 3)

    # ---- ⑦ 状态③ 骨空间 refit ----
    t = time.perf_counter()
    refit_stats = {}
    for o in cloth:
        refit_stats[o.name] = bone_space_refit(o, restA, restB, W[o.name])
    bpy.context.view_layer.update()
    pts3 = {o.name: eval_points(o) for o in cloth}
    rec["phases"]["bone_space_refit_s"] = round(time.perf_counter() - t, 3)

    # ---- ⑧ 度量三态 ----
    def measure(state_name, pts):
        allp = np.vstack([pts[o.name] for o in cloth]) if cloth else np.zeros((0, 3))
        t0 = time.perf_counter()
        rep = vlib.point_in_mesh_report(tree, allp, co_for_calib=body_co)
        dt0 = time.perf_counter() - t0
        n = len(allp)
        # —— 射线方向集敏感性：三套方向集并报，给出口径区间 ——
        variants = {}
        for tag, dirs, mv in (("ray7_default", vlib.RAY_DIRS, 4),
                              ("ray6_axis_lead_style", vlib.RAY_DIRS_6AXIS, 4),
                              ("ray13_axis+diag", vlib.RAY_DIRS_13, 7)):
            t1 = time.perf_counter()
            v_in, v_all = vlib.inside_ray_parity(tree, allp, dirs=dirs)
            variants[tag] = {
                "n_dirs": len(dirs), "min_votes": mv,
                "penetration_pct": float((v_in >= mv).mean() * 100),
                "seconds": round(time.perf_counter() - t1, 3),
            }
        dt = time.perf_counter() - t0
        s = {
            "n_points": int(n),
            "penetration_ray_pct": float(rep["inside_ray"].mean() * 100),
            "penetration_normal_pct": float(rep["inside_norm"].mean() * 100),
            "ambiguous_pct": float(rep["ambiguous"].mean() * 100),
            "two_method_agreement": rep["agree_rate"],
            "calib": rep["calib"],
            "ray_direction_variants": variants,
            "measure_seconds": round(dt, 3),
        }
        pov = [v["penetration_pct"] for v in variants.values()]
        pov.append(s["penetration_normal_pct"])
        s["penetration_band_pct"] = [round(min(pov), 4), round(max(pov), 4)]
        s["penetration_consensus_pct"] = float(
            (rep["inside_ray"] & rep["inside_norm"]).mean() * 100)
        s["penetration_either_pct"] = float(
            (rep["inside_ray"] | rep["inside_norm"]).mean() * 100)
        rec["states"][state_name] = s
        return rep, allp

    t = time.perf_counter()
    rep1, p1 = measure("1_baseline_own_rig", pts1)
    rep2, p2 = measure("2_reattached_standard_rig_no_refit", pts2)
    rep3, p3 = measure("3_bone_space_refit", pts3)
    rec["phases"]["measure_3_states_s"] = round(time.perf_counter() - t, 3)

    # ---- ⑨ 交叉断言 ----
    d12 = float(np.abs(p1 - p2).max() * 100) if len(p1) else 0.0
    # rigA / rigB 的物体变换与 pose 是否一致（解释 ① 与 ② 的亚微米差）
    mwA = np.array(rigA.matrix_world)
    mwB = np.array(rigB.matrix_world)
    pose_delta = 0.0
    for pb in rigA.pose.bones:
        if pb.name in rigB.pose.bones:
            a = np.array(pb.matrix_basis)
            b = np.array(rigB.pose.bones[pb.name].matrix_basis)
            pose_delta = max(pose_delta, float(np.abs(a - b).max()))
    rec["check_3_1_equals_2"] = {
        "max_vertex_delta_cm_state1_vs_state2": d12,
        "bit_identical": bool(d12 == 0.0),
        "rig_matrix_world_max_elem_delta": float(np.abs(mwA - mwB).max()),
        "pose_matrix_basis_max_elem_delta": pose_delta,
        "mesh_float32_eps_cm": 1e-7 * 100,
        "verdict": ("①与②在**几何/拓扑/权重意义上必须同值**：静止态下把 Armature "
                    "修改器从自带 rig 改挂标准体 rig 不改变顶点。实测亚微米差 "
                    f"{d12:.2e} cm 来自 to_mesh() 的 float32 往返，"
                    "不是位移（rig matrix/pose 差见上两行）。"
                    "所以『不贴合 vs 基线』的区别只在**动画时**才体现 —— "
                    "静止测不出差别，容易被误读为『改挂骨架没用』。"),
    }

    d13 = {o.name: float(np.linalg.norm(pts3[o.name] - pts1[o.name], axis=1).max() * 100)
           for o in cloth}
    # rigA/rigB rest 逐骨比对（解释"女侧 no-op"）
    diff = []
    for bn in restA:
        if bn not in restB:
            diff.append({"bone": bn, "missing_in_B": True})
            continue
        d = float(np.abs(np.array(restA[bn]) - np.array(restB[bn])).max())
        diff.append({"bone": bn, "max_elem_delta": d})
    nz = [x for x in diff if x.get("max_elem_delta", 0) > 0]
    rec["rest_matrix_compare"] = {
        "n_bones": len(restA), "n_bones_differing": len(nz),
        "max_elem_delta": max([x.get("max_elem_delta", 0) for x in diff] or [0]),
        "worst": sorted(nz, key=lambda x: -x["max_elem_delta"])[:8],
    }
    rec["refit_displacement_cm"] = {
        "per_piece_max": d13,
        "overall_max_cm": max(d13.values()) if d13 else 0.0,
        "stats": refit_stats,
        "transform_is_exact_identity": bool(
            rec["rest_matrix_compare"]["max_elem_delta"] == 0.0),
        "noop_within_float32_eps": bool(all(v < 1e-4 for v in d13.values())) if d13 else None,
        "note": "refit 位移的**下界**受 mesh 顶点 float32 存储限制：即使变换严格是恒等，写入-读回也会产生 ~1e-5 cm 量级的往返噪声。判定 no-op 的阈值取 1e-4 cm。",
    }

    # ---- ⑩ 逐件穿模（用状态①/③） ----
    t = time.perf_counter()
    per = {}
    for o in cloth:
        nm = o.name
        rec_p = {"n_verts": int(len(pts1[nm]))}
        for tag, rep in (("state1", None), ("state3", None)):
            pass
        # 逐件重算（数量小，直接复用全量 rep 的分段）
        per[nm] = rec_p
    # 全量 concat 顺序与 cloth 顺序一致 → 切段即可
    off = 0
    for o in cloth:
        nm = o.name
        k = len(pts1[nm])
        sl = slice(off, off + k)
        per[nm].update({
            "penetration_ray_pct_state1": float(rep1["inside_ray"][sl].mean() * 100),
            "penetration_ray_pct_state3": float(rep3["inside_ray"][sl].mean() * 100),
            "penetration_normal_pct_state1": float(rep1["inside_norm"][sl].mean() * 100),
            "penetration_normal_pct_state3": float(rep3["inside_norm"][sl].mean() * 100),
            "ambiguous_pct_state3": float(rep3["ambiguous"][sl].mean() * 100),
            "max_refit_disp_cm": d13.get(nm, 0.0),
            "z_range_m": [float(pts1[nm][:, 2].min()), float(pts1[nm][:, 2].max())],
        })
        off += k
    rec["per_piece"] = per
    rec["phases"]["per_piece_s"] = round(time.perf_counter() - t, 3)

    rec["phases"]["total_s"] = round(time.perf_counter() - t_case, 3)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-penetration.json")
    ap.add_argument("--cases", nargs="*", default=None)
    a = ap.parse_args(argv_after_ddash())

    def log(msg):
        print(f"[v_penetration] {msg}", flush=True)

    cases = CASES
    if a.cases:
        cases = [c for c in CASES if c[1] in a.cases]
    out = {"generated_by": "verifier/v_penetration.py",
           "blender": bpy.app.version_string,
           "method": {
               "ray": "7 方向（3 轴 + 4 对角）射线奇偶，>=4 判内；起点 p+1e-6·d",
               "normal": "BVHTree.find_nearest 的有符号距离，符号由顶点质心自动标定",
               "ambiguous": "两法不一致 或 |signed|<1e-4 m → 不计入任何一侧",
           },
           "cases": []}
    t0 = time.perf_counter()
    for sex, outfit, body in cases:
        log(f"=== {sex} {outfit} ===")
        rec = run_case(sex, outfit, body, out, log)
        out["cases"].append(rec)
        log(f"  state1 pen(ray)={rec['states']['1_baseline_own_rig']['penetration_ray_pct']:.2f}% "
            f"state3={rec['states']['3_bone_space_refit']['penetration_ray_pct']:.2f}% "
            f"noop={rec['refit_displacement_cm']['noop_within_float32_eps']}")
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(a.out, out)
    log(f"wrote {a.out} in {out['total_seconds']}s")


if __name__ == "__main__":
    main()