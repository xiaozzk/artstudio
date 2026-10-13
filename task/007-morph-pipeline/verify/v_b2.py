#!/usr/bin/env python3
"""
v_b2.py —— verifier **独立实现并验证 B2 路线**（体形 morph 直接烘在角色自身网格上）。

B2 = 用 `tryon/TryOn_{sex}_Ranger.blend`（= 服装布料 + 服装自带皮肤 + 基础体的头，共 12 件网格，
     共用服装自己的 65 骨 rig）**自己的 rig** 摆 14 根体形骨 → 逐件烘 shape key。
     **不剥离、不贴合、不从身体传递**。

verifier 与 Lead 的 `b2_feasibility.py` 的差异（本脚本刻意多做的验证）：
  V1 自己实现（独立写），复现 8 个数字
  V2 **两种 `inherit_scale` 制度**对照（旧 tryon rig 默认 / 加 SPEC §3.2 规则）
  V3 **非平凡的结构性验证**：Lead 说"B2 下结构性无穿模"。
     但"没有独立身体所以测不出穿模"是**同义反复**，不是证据。
     本脚本改成测**真实存在的两个接缝**：
       (a) `*_Arms` 网格内部：**布料面 vs 皮肤面**（同网格内的 MI_Regular_* 组）
           —— 皮肤当"身体代理"，布料扎进去就是真穿模
       (b) **头 ↔ 服装领口**：Head_Superhero_* 与躯干/兜帽的接缝在 morph 下是否张开
     两处都随 morph 档变化 = 有问题；不变 = 结构性成立。
  V4 **像素法在 B2 下是否还有判别力**（Lead 预期"结构性为 0"）
  V5 规模外推：N 套服装 → N 个自包含角色，数据/rig 复制成本怎么长

只读 `assets/3d/blend/tryon/`；产物只写 verifier 的写入范围。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_b2.py -- \
      --out assets/3d/rig/reports/verify-b2.json
"""
import argparse
import copy
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
from v_pixelmetric import (RED_MAX_GB, RED_MIN_R, make_camera, mk_emission_red,
                           read_png_raw, scene_bounds, setup_render, shot_stats)  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
TRYON = f"{ROOT}/assets/3d/blend/tryon"
SHOTDIR = f"{ROOT}/task/007-morph-pipeline/verify/renders"
TIERS = [("BS_Thin", 0.84), ("BS_Heavy", 1.21)]   # v2 系数；实际以 spec 推导为准
SHAPE_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r"]
# v2：**从 bodyshape_spec.json 自己推导**骨缩放矩阵（不抄 manifest 的 bones_applied），
#     然后与 manifest 交叉对账。规则见 spec.axis_profile.rule：
#       x = z = 1 + (coef-1)*delta_response[group]
#       y     = 1 + (coef-1)*along_axis_response[group]   (默认 0)
SPEC_PATH = "/Users/zhenkunzhu/Desktop/project/artstudio/assets/3d/rig/bodyshape_spec.json"
MANIFEST_PATH = "/Users/zhenkunzhu/Desktop/project/artstudio/assets/3d/rig/manifests/bodyshape_manifest.json"


def load_spec():
    import json as _j
    with open(SPEC_PATH, encoding="utf-8") as f:
        spec = _j.load(f)
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        man = _j.load(f)
    return spec, man


def derive_matrix(spec):
    """verifier 自己按 spec 的 rule 推导 (tier_name -> {bone: (x,y,z)})。"""
    dr = {k: v for k, v in spec["delta_response"].items() if not k.startswith("_")}
    ar = {k: v for k, v in spec["along_axis_response"].items() if not k.startswith("_")}
    out = {}
    for t in spec["tiers"]:
        c = t["target_coefficient"]
        m = {}
        for grp, bones in spec["groups"].items():
            xz = 1.0 + (c - 1.0) * dr.get(grp, 1.0)
            y = 1.0 + (c - 1.0) * ar.get(grp, 0.0)
            for b in bones:
                m[b] = (xz, y, xz)
        out[t["name"]] = {"coefficient": c, "bones": m}
    return out


def crosscheck(spec, man, derived):
    """我推导的矩阵 vs spec.tiers[].bones vs manifest.bones_applied。"""
    applied = {x["name"]: x["bones_applied"] for x in man["tiers"]}
    res = {"mismatch_vs_spec_tiers": [], "mismatch_vs_manifest_applied": []}
    for t in spec["tiers"]:
        nm = t["name"]
        for b, mine in derived[nm]["bones"].items():
            if b in t.get("bones", {}):
                sp = tuple(round(v, 6) for v in t["bones"][b])
                if sp != tuple(round(v, 6) for v in mine):
                    res["mismatch_vs_spec_tiers"].append(
                        {"tier": nm, "bone": b, "derived": [round(v, 6) for v in mine],
                         "spec_tiers": list(sp)})
            if b in applied:
                mp = tuple(round(v, 6) for v in applied[b])
                if mp != tuple(round(v, 6) for v in mine):
                    res["mismatch_vs_manifest_applied"].append(
                        {"tier": nm, "bone": b, "derived": [round(v, 6) for v in mine],
                         "manifest": list(mp)})
    res["n_mismatch_spec_tiers"] = len(res["mismatch_vs_spec_tiers"])
    res["n_mismatch_manifest_applied"] = len(res["mismatch_vs_manifest_applied"])
    res["verdict"] = ("spec.tiers[].bones 与 spec 自身的 axis_profile.rule **不一致**"
                      if res["n_mismatch_spec_tiers"] else "spec.tiers[].bones 与 rule 一致")
    return res


TIERS_SPEC = None   # 运行时填


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def resp_of(bn):
    for k, v in RESP.items():
        if bn.startswith(k):
            return v
    return 1.0


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    m = ev.to_mesh()
    n = len(m.vertices)
    co = np.empty(n * 3)
    m.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    M = np.array(ev.matrix_world)
    ev.to_mesh_clear()
    return co @ M[:3, :3].T + M[:3, 3]


def all_mesh_objects():
    return [o for o in bpy.context.scene.objects
            if o.type == "MESH" and not o.name.startswith("Icosphere")]


def char_height(meshes):
    zs = [eval_pts(o)[:, 2] for o in meshes if len(o.data.vertices)]
    return float(max(z.max() for z in zs) - min(z.min() for z in zs))


def char_armspan(meshes):
    """臂展 = 全角色 x 跨度（正视图里最宽的维度；T2 用它当"漏了 along 项"的信号）。"""
    xs = [eval_pts(o)[:, 0] for o in meshes if len(o.data.vertices)]
    return float(max(x.max() for x in xs) - min(x.min() for x in xs))


def pose_tier(arm, s, matrix=None):
    """摆体形骨。matrix 给出 {bone: (x,y,z)}；不给则退回旧的单轴 girth 口径。"""
    for pb in arm.pose.bones:
        pb.scale = (1.0, 1.0, 1.0)
    for bn in SHAPE_BONES:
        pb = arm.pose.bones.get(bn)
        if pb is None:
            continue
        if matrix is not None and bn in matrix:
            pb.scale = matrix[bn]
        else:
            v = 1.0 + (s - 1.0) * resp_of(bn)
            pb.scale = (v, 1.0, v)
    bpy.context.view_layer.update()


def clear_pose(arm):
    for pb in arm.pose.bones:
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def bake_shape_keys(meshes, arm, tier_mats):
    """逐件建 Basis/BS_Thin/BS_Heavy 并烘 depsgraph 求值结果。

    ⚠ **踩过的坑（本脚本第一版就中了）**：
      如果按「摆姿态 → 读某件 → 写该件的 shape key data → 再摆下一档 → 读同一件」的顺序做，
      写入 mesh data 之后**该对象的求值缓存会失效**，下一次 `to_mesh()` 可能返回
      **写入前那一档的姿态**（表现为 BS_Heavy 位移突然掉到 0.03 cm，而身高又是对的 → 极难发现）。
      正确做法：**先把所有档 × 所有件的求值坐标全部读进内存，再统一写 shape key data**。
      （这是 SPEC F9「shape key 不改 mesh.vertices、必须走求值」的姊妹坑。）
    """
    for o in meshes:
        if o.data.shape_keys is None:
            o.shape_key_add(name="Basis", from_mix=False)
        for nm, _ in TIERS:
            if nm not in o.data.shape_keys.key_blocks:
                o.shape_key_add(name=nm, from_mix=False)
    clear_pose(arm)
    bpy.context.view_layer.update()
    basis = {o.name: eval_pts(o) for o in meshes}
    # —— 阶段 1：只读，把每一档的求值结果全部抓到内存 ——
    captured = {}
    for nm, coef in TIERS:
        pose_tier(arm, coef, tier_mats.get(nm))
        captured[nm] = {o.name: eval_pts(o) for o in meshes}
    clear_pose(arm)
    bpy.context.view_layer.update()
    # —— 阶段 2：只写，不再读 ——
    for o in meshes:
        o.data.shape_keys.key_blocks["Basis"].data.foreach_set(
            "co", basis[o.name].reshape(-1))
    deltas = {}
    for nm, _ in TIERS:
        for o in meshes:
            o.data.shape_keys.key_blocks[nm].data.foreach_set(
                "co", captured[nm][o.name].reshape(-1))
            d = np.linalg.norm(captured[nm][o.name] - basis[o.name], axis=1)
            deltas.setdefault(o.name, {})[nm] = {
                "max_cm": float(d.max() * 100), "mean_cm": float(d.mean() * 100)}
        for o in meshes:
            o.data.update()
    return basis, deltas


def mat_split(obj):
    """按材质把面分成 skin（MI_Regular_*）/ cloth。返回 (skin_tris, cloth_tris)（顶点索引）。"""
    me = obj.data
    names = [m.name if m else "" for m in me.materials]
    skin_idx = {i for i, n in enumerate(names) if n.startswith("MI_Regular_")}
    if not skin_idx:
        return None, None, names
    nf = len(me.polygons)
    mi = np.empty(nf, dtype=np.int32)
    me.polygons.foreach_get("material_index", mi)
    me.calc_loop_triangles()
    lt = np.array([list(t.vertices) for t in me.loop_triangles], dtype=np.int64)
    # loop_triangle -> polygon 映射
    tri_poly = np.array([t.polygon_index for t in me.loop_triangles], dtype=np.int64)
    skin_mask = np.isin(mi[tri_poly], list(skin_idx))
    return lt[skin_mask], lt[~skin_mask], names


def cloth_in_skin_metric(obj, skin_tris, cloth_verts_idx, co):
    """布料顶点落在【同网格的皮肤面】内部的比例（皮肤当身体代理）。

    半径/朝向口径与我 vlib 里的 7 向射线一致；皮肤面**不闭合**（是袖口的一块），
    所以这里报的是「射线奇偶」与「最近点法线」两个数，并附不一致率。
    """
    if skin_tris is None or len(skin_tris) == 0 or len(cloth_verts_idx) == 0:
        return None
    verts = [Vector(p) for p in co]
    tree = BVHTree.FromPolygons(verts, [tuple(int(x) for x in t) for t in skin_tris],
                                all_triangles=True)
    pts = co[cloth_verts_idx]
    rep = vlib.point_in_mesh_report(tree, pts, co_for_calib=co)
    return {
        "n_tested": int(len(pts)),
        "n_skin_tris": int(len(skin_tris)),
        "pen_ray_pct": float(rep["inside_ray"].mean() * 100),
        "pen_norm_pct": float(rep["inside_norm"].mean() * 100),
        "ambiguous_pct": float(rep["ambiguous"].mean() * 100),
        "agreement": rep["agree_rate"],
        "calib": rep["calib"],
    }


def seam_metric(head_obj, collar_obj, band=None):
    """头 ↔ 领口接缝：头的顶点到服装网格表面的最近距离分布（负=扎进去）。

    ⚠ `band` 必须用 **Basis 时算出的固定 z 带** —— 若按当前档的
    `hc[:,2].min()` 现算，顶点集合会随档漂移，指标就不可比（第一版踩过）。
    """
    if head_obj is None or collar_obj is None:
        return None
    hc = eval_pts(head_obj)
    cc = eval_pts(collar_obj)
    all_head = hc.copy()
    m = vlib.evaluated_mesh(collar_obj)
    tris = vlib._triangulate(m)
    tree = BVHTree.FromPolygons([Vector(p) for p in cc],
                                [tuple(int(x) for x in t) for t in tris],
                                all_triangles=True)
    # 只看头部的下半（颈部区域），否则会被脸/兜帽里外的正常重叠淹没
    if band is None:
        zlo, zhi = hc[:, 2].min(), hc[:, 2].min() + 0.25
    else:
        zlo, zhi = band
    sel = (hc[:, 2] >= zlo) & (hc[:, 2] <= zhi)
    if sel.sum() == 0:
        return None
    d = []
    for p in hc[sel]:
        loc, nor, _, dist = tree.find_nearest(Vector(p), 1e7)
        if loc is None:
            continue
        d.append(float((Vector(p) - loc).dot(nor)))
    d = np.array(d)
    # 全头范围的最小间隙 —— 用来判断"头部与服装有没有张开一条缝"
    dall = []
    for p in all_head:
        loc, nor, _, _dist = tree.find_nearest(Vector(p), 1e7)
        if loc is not None:
            dall.append(float(_dist))
    dall = np.array(dall) if dall else np.array([0.0])
    return {"n": int(len(d)), "z_band_m": [round(float(zlo), 4), round(float(zhi), 4)],
            "head_to_cloth_min_gap_cm": round(float(dall.min() * 100), 4),
            "head_to_cloth_median_gap_cm": round(float(np.median(dall) * 100), 4),
            "min_cm": round(float(d.min() * 100), 3),
            "p05_cm": round(float(np.percentile(d, 5) * 100), 3),
            "median_cm": round(float(np.median(d) * 100), 3),
            "inside_frac": round(float((d < 0).mean()), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-b2.json")
    ap.add_argument("--res", nargs=2, type=int, default=[760, 1180])
    a = ap.parse_args(argv_after_ddash())
    os.makedirs(SHOTDIR, exist_ok=True)
    out = {"generated_by": "verifier/v_b2.py",
           "route": "B2 = 在角色自身 rig 上摆体形骨 → 逐件烘 shape key（不剥离/不贴合/不传递）",
           "girth_rule": "(s,1,s) 只缩垂直于骨轴的两轴；resp 系数沿用 bodyshape 的手调值",
           "cases": []}
    t0 = time.perf_counter()
    spec, man = load_spec()
    derived = derive_matrix(spec)
    tier_mats = {("BS_Thin" if n == "thin" else "BS_Heavy"): d["bones"]
                 for n, d in derived.items()}
    out["coefficient_source"] = {
        "spec": os.path.relpath(SPEC_PATH, ROOT),
        "spec_version": spec.get("version"),
        "manifest": os.path.relpath(MANIFEST_PATH, ROOT),
        "manifest_spec_version": man.get("spec_version"),
        "coefficients": {n: d["coefficient"] for n, d in derived.items()},
        "matrix_derived_by": "verifier（按 spec.axis_profile.rule 自己推导，未抄 bones_applied）",
        "crosscheck": crosscheck(spec, man, derived),
    }
    cc = out["coefficient_source"]["crosscheck"]
    print(f"[系数源] spec v{spec.get('version')} / manifest v{man.get('spec_version')} "
          f"系数 {out['coefficient_source']['coefficients']}")
    print(f"[系数对账] 我推导 vs spec.tiers[].bones 不符 {cc['n_mismatch_spec_tiers']} 条；"
          f"vs manifest.bones_applied 不符 {cc['n_mismatch_manifest_applied']} 条")
    for row in cc["mismatch_vs_spec_tiers"]:
        print(f"    ⚠ spec.tiers 错: {row['tier']} {row['bone']} "
              f"rule={row['derived']} spec={row['spec_tiers']}")
    for sex in ("Female", "Male"):
        path = f"{TRYON}/TryOn_{sex}_Ranger.blend"
        rec = {"sex": sex, "source": os.path.relpath(path, ROOT)}
        print(f"\n{'='*90}\n### B2 {sex}  {os.path.basename(path)}\n{'='*90}", flush=True)
        bpy.ops.wm.open_mainfile(filepath=path)
        for o in list(bpy.data.objects):
            if o.name.startswith("Icosphere"):
                bpy.data.objects.remove(o, do_unlink=True)
        arm = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"][0]
        meshes = all_mesh_objects()
        total_v = sum(len(o.data.vertices) for o in meshes)
        rec["structure"] = {
            "armature": arm.name, "n_bones": len(arm.data.bones),
            "n_meshes": len(meshes), "total_verts": total_v,
            "meshes": sorted(({"name": o.name, "verts": len(o.data.vertices),
                               "polys": len(o.data.polygons),
                               "materials": [m.name if m else None for m in o.data.materials],
                               "vertex_groups": len(o.vertex_groups),
                               "shape_keys_before": vlib.shapekey_names(o)}
                              for o in meshes), key=lambda r: r["name"]),
            "no_full_superhero_body": not any(
                o.name.startswith("Body_") for o in meshes),
        }
        print(f"  {len(meshes)} 件网格 / {total_v} 顶点 / 骨架 {arm.name} "
              f"({len(arm.data.bones)} 骨)")

        # --- inherit_scale 现状 ---
        before = {b.name: b.inherit_scale for b in arm.data.bones}
        rec["inherit_scale_before"] = {"n_non_full": sum(1 for v in before.values() if v != "FULL"),
                                       "non_full": sorted(k for k, v in before.items() if v != "FULL")}

        # --- V2：两种制度下的体形/身高 ---
        clear_pose(arm)
        h0 = char_height(meshes)
        a0 = char_armspan(meshes)
        rec["height_basis_m"] = round(h0, 6)
        rec["armspan_basis_m"] = round(a0, 6)
        regimes = {}
        for label, apply_rule in (("as_is_old_tryon_rig", False),
                                  ("with_SPEC_3.2_rule", True)):
            for b in arm.data.bones:
                b.inherit_scale = before[b.name]
            if apply_rule:
                for bn in SHAPE_BONES:
                    if bn in arm.data.bones:
                        for ch in arm.data.bones[bn].children:
                            ch.inherit_scale = "NONE"
            row = {}
            for tier, coef in TIERS:
                pose_tier(arm, coef, tier_mats.get(tier))
                hh = char_height(meshes)
                aa = char_armspan(meshes)
                row[tier] = {"height_m": round(hh, 6),
                             "height_ratio": round(hh / h0, 6),
                             "armspan_m": round(aa, 6),
                             "armspan_ratio": round(aa / a0, 6),
                             "armspan_delta_pct": round(100 * (aa / a0 - 1), 4)}
            clear_pose(arm)
            regimes[label] = row
            print(f"  制度 {label:<24} thin H比={row['BS_Thin']['height_ratio']:.5f} "
                  f"臂展{row['BS_Thin']['armspan_delta_pct']:+.2f}%  |  "
                  f"heavy H比={row['BS_Heavy']['height_ratio']:.5f} "
                  f"臂展{row['BS_Heavy']['armspan_delta_pct']:+.2f}%")
        rec["inherit_scale_regimes"] = regimes
        # 采用 SPEC §3.2 规则
        for bn in SHAPE_BONES:
            if bn in arm.data.bones:
                for ch in arm.data.bones[bn].children:
                    ch.inherit_scale = "NONE"
        rec["inherit_scale_after_rule"] = {
            "n_non_full": sum(1 for b in arm.data.bones if b.inherit_scale != "FULL"),
            "added": sorted(b.name for b in arm.data.bones
                            if before[b.name] == "FULL" and b.inherit_scale != "FULL")}

        # --- V1：烘 shape key ---
        t = time.perf_counter()
        basis, deltas = bake_shape_keys(meshes, arm, tier_mats)
        rec["bake_seconds"] = round(time.perf_counter() - t, 3)
        rec["shape_keys_after"] = {o.name: vlib.shapekey_names(o) for o in meshes}
        rec["per_mesh_delta"] = deltas
        mx = max(v[nm]["max_cm"] for v in deltas.values() for nm, _ in TIERS)
        rec["max_displacement_cm"] = round(mx, 4)
        rec["morph_bytes_total"] = total_v * 12 * 2
        rec["morph_bytes_per_tier"] = total_v * 12
        rec["armspan"] = {
            "basis_m": round(a0, 6),
            "ratios": {nm: regimes["with_SPEC_3.2_rule"][nm]["armspan_ratio"] for nm, _ in TIERS},
            "delta_pct": {nm: regimes["with_SPEC_3.2_rule"][nm]["armspan_delta_pct"]
                          for nm, _ in TIERS},
        }
        print(f"  烘档 {rec['bake_seconds']}s  最大位移 {mx:.3f} cm  "
              f"morph 数据量 {rec['morph_bytes_total']/1024:.1f} KB (2 档)  "
              f"臂展 {rec['armspan']['delta_pct']}")

        # --- 拓扑不变 ---
        set_all = lambda o, w: [kb.data and setattr(kb, "value", w) for kb in []]
        topo_ok = True
        for o in meshes:
            sigs = set()
            for kb in o.data.shape_keys.key_blocks:
                for k2 in o.data.shape_keys.key_blocks:
                    k2.value = 1.0 if k2.name == kb.name else 0.0
                bpy.context.view_layer.update()
                sigs.add(vlib.eval_poly_signature(o)["sig"])
            for k2 in o.data.shape_keys.key_blocks:
                k2.value = 0.0
            bpy.context.view_layer.update()
            topo_ok &= len(sigs) == 1
        rec["topology_identical_all_tiers"] = bool(topo_ok)

        # --- V3a：布料 vs 皮肤（同网格内） ---
        arms_obj = next((o for o in meshes if o.name.endswith("_Arms")), None)
        v3a = {}
        if arms_obj is not None:
            skin_tris, cloth_tris, names = mat_split(arms_obj)
            if skin_tris is not None:
                n_skin_v = len(np.unique(skin_tris))
                n_cloth_v = len(np.unique(cloth_tris))
                # 布料顶点里，排除同时属于皮肤的
                cloth_only = np.setdiff1d(np.unique(cloth_tris), np.unique(skin_tris))
                for tier in [None] + [nm for nm, _ in TIERS]:
                    for kb in arms_obj.data.shape_keys.key_blocks:
                        kb.value = 1.0 if kb.name == tier else 0.0
                    bpy.context.view_layer.update()
                    co = eval_pts(arms_obj)
                    v3a[tier or "Basis"] = cloth_in_skin_metric(
                        arms_obj, skin_tris, cloth_only, co)
                v3a["_counts"] = {"skin_verts": int(n_skin_v), "cloth_verts": int(n_cloth_v),
                                  "cloth_only_verts": int(len(cloth_only)),
                                  "materials": names}
                for k in ("Basis", "BS_Thin", "BS_Heavy"):
                    v = v3a.get(k)
                    if v:
                        print(f"  V3a 布料扎进皮肤 [{k:<8}] ray={v['pen_ray_pct']:.2f}% "
                              f"norm={v['pen_norm_pct']:.2f}% 一致={v['agreement']:.3f}")
        rec["V3a_cloth_vs_garment_own_skin"] = v3a

        # --- V3b：头 ↔ 领口接缝 ---
        head = next((o for o in meshes if o.name.startswith("Head_")
                     and "Eyes" not in o.name and "Eyebrows" not in o.name), None)
        collar = next((o for o in meshes if o.name.endswith("_Body")), None) or \
            next((o for o in meshes if "Hood" in o.name), None)
        v3b = {}
        # 用 Basis 位置定死 z 带（0→0.25 m 的颈区），三档共用同一批顶点
        hc_basis = eval_pts(head) if head is not None else None
        band = ((float(hc_basis[:, 2].min()), float(hc_basis[:, 2].min()) + 0.25)
                if hc_basis is not None else None)
        for tier in [None] + [nm for nm, _ in TIERS]:
            for o in meshes:
                if o.data.shape_keys:
                    for kb in o.data.shape_keys.key_blocks:
                        kb.value = 1.0 if kb.name == tier else 0.0
            bpy.context.view_layer.update()
            v3b[tier or "Basis"] = seam_metric(head, collar, band)
        rec["V3b_head_vs_collar_seam"] = v3b
        # V3c：**权重一致性**（比"判内外"稳得多的结构性判据）——
        # 布料顶点与最近的皮肤顶点在 Basis 上相距 <2cm 时，比较它们各自的
        # BS_Heavy 位移向量。位移一致 = 同一组骨变换驱动 = 结构性不会分离。
        v3c = {}
        if arms_obj is not None:
            skin_tris, cloth_tris, _ = mat_split(arms_obj)
            if skin_tris is not None:
                skin_v = np.unique(skin_tris)
                cloth_v = np.setdiff1d(np.unique(cloth_tris), skin_v)
                for tier in ("BS_Thin", "BS_Heavy"):
                    for kb in arms_obj.data.shape_keys.key_blocks:
                        kb.value = 0.0
                    bpy.context.view_layer.update()
                    b0 = eval_pts(arms_obj)
                    for kb in arms_obj.data.shape_keys.key_blocks:
                        kb.value = 1.0 if kb.name == tier else 0.0
                    bpy.context.view_layer.update()
                    b1 = eval_pts(arms_obj)
                    d = b1 - b0
                    # 距离 <2cm 的 (布料, 皮肤) 对
                    sp = b0[skin_v]
                    cp = b0[cloth_v]
                    dd = np.linalg.norm(cp[:, None, :] - sp[None, :, :], axis=2)
                    j = dd.argmin(axis=1)
                    near = dd[np.arange(len(cp)), j] < 0.02
                    if near.sum() > 0:
                        ddiff = np.linalg.norm(d[cloth_v][near] - d[skin_v][j[near]], axis=1)
                        v3c[tier] = {
                            "n_pairs": int(near.sum()),
                            "max_disp_diff_cm": round(float(ddiff.max() * 100), 4),
                            "mean_disp_diff_cm": round(float(ddiff.mean() * 100), 4),
                            "p95_disp_diff_cm": round(float(np.percentile(ddiff, 95) * 100), 4),
                        }
                rec["V3c_cloth_vs_skin_displacement_agreement"] = v3c
                for k, v in v3c.items():
                    print(f"  V3c 布料/皮肤位移差 [{k:<8}] 配对 {v['n_pairs']:>4} "
                          f"max={v['max_disp_diff_cm']:.3f}cm 均值={v['mean_disp_diff_cm']:.3f}cm")
        for k, v in v3b.items():
            if v:
                print(f"  V3b 头↔领口 [{k:<8}] 颈区 n={v['n']:>4} 中位={v['median_cm']:+7.3f}cm "
                      f"p05={v['p05_cm']:+7.3f}  内侧占比={v['inside_frac']*100:5.1f}%")

        # --- V4：像素法在 B2 下的判别力 ---
        for o in meshes:
            if o.data.shape_keys:
                for kb in o.data.shape_keys.key_blocks:
                    kb.value = 0.0
        bpy.context.view_layer.update()
        res = tuple(a.res)
        setup_render(res)
        red = mk_emission_red()
        # 把「服装自带皮肤面」+ 头 染红 = 角色本来就露出来的部位
        painted = []
        for o in meshes:
            names = [m.name if m else "" for m in o.data.materials]
            is_skin = any(n.startswith("MI_Regular_") for n in names)
            is_head = o.name.startswith("Head_") and "Hair" not in "".join(names)
            if is_skin or is_head:
                o.data.materials.clear()
                o.data.materials.append(red)
                painted.append(o.name)
        rec["V4_painted_objects"] = painted
        bd = scene_bounds(meshes, meshes[0])
        v4 = {}
        for tier in [None] + [nm for nm, _ in TIERS]:
            for o in meshes:
                if o.data.shape_keys:
                    for kb in o.data.shape_keys.key_blocks:
                        kb.value = 1.0 if kb.name == tier else 0.0
            bpy.context.view_layer.update()
            make_camera(bd, res, "ortho")
            p = f"{SHOTDIR}/b2_{sex}_{tier or 'Basis'}.png"
            bpy.context.scene.render.filepath = p
            bpy.ops.render.render(write_still=True)
            v4[tier or "Basis"] = shot_stats(p)
        rec["V4_pixel_designed_exposure"] = v4
        for k, v in v4.items():
            print(f"  V4 像素法（染'自带皮肤+头'）[{k:<8}] 红={v['red_frac_pct']:.3f}%  "
                  f"剪影={v['silhouette_px']}")
        for o in meshes:
            if o.data.shape_keys:
                for kb in o.data.shape_keys.key_blocks:
                    kb.value = 0.0
        out["cases"].append(rec)
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(a.out, out)
    print(f"\n[v_b2] wrote {a.out} in {out['total_seconds']}s")


if __name__ == "__main__":
    main()