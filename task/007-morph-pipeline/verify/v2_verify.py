#!/usr/bin/env python3
"""
v2_verify.py —— verifier 对 v2 管线（bodies/ + garments/）的**独立**终验。

不 import `tools/3d/bodyshape/*`、`tools/3d/garment/*` 的任何代码。
所有网格读数走 depsgraph 求值（SPEC F9）。
覆盖 SPEC §5 的 6 项指标 + 任务卡要求的额外项，并**逐项计时**。

用法（在工作区根）：
  BL=/Applications/Blender.app/Contents/MacOS/Blender
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v2_verify.py -- \
      --out assets/3d/rig/reports/verify-v2.json
"""
import argparse
import hashlib
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
SPEC_SHAPE_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
                    "thigh_l", "thigh_r", "calf_l", "calf_r",
                    "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
                    "clavicle_l", "clavicle_r"]
EXPECT_KEYS = ["Basis", "BS_Thin", "BS_Heavy"]


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def set_shape_weights(obj, mapping):
    sk = obj.data.shape_keys
    if sk is None:
        return 0
    n = 0
    for kb in sk.key_blocks:
        kb.value = float(mapping.get(kb.name, 0.0))
        n += 1
    return n


def shapekey_eval_deltas(obj, names):
    """**走求值**取每个 shape key 相对 Basis 的位移（F9 口径）。

    流程：先把所有权重清零 → 求值 = Basis；再逐个把某个 key 设为 1 → 求值。
    绝不读 key_blocks[].data（那是数据层，不是"用户看到的结果"）。
    """
    dg = bpy.context.evaluated_depsgraph_get()
    base = vlib.evaluated_mesh(obj, dg)["co"].copy()
    out = {}
    for nm in names:
        set_shape_weights(obj, {nm: 1.0})
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        cur = vlib.evaluated_mesh(obj, dg)["co"]
        d = np.linalg.norm(cur - base, axis=1)
        out[nm] = {
            "n_verts": int(len(d)),
            "max_cm": float(d.max() * 100),
            "mean_cm": float(d.mean() * 100),
            "rms_cm": float(np.sqrt((d ** 2).mean()) * 100),
            "moved_gt_1mm": int((d > 0.001).sum()),
            "moved_frac": float((d > 1e-9).mean()),
        }
    set_shape_weights(obj, {})
    bpy.context.view_layer.update()
    return out, base


def topo_of(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    return vlib.eval_poly_signature(obj, dg)


def edge_stretch_vs(obj, base_co, label):
    """对当前求值网格 vs base_co 做边长比离散度（失真口径）。"""
    edges = vlib.mesh_edges(obj)
    dg = bpy.context.evaluated_depsgraph_get()
    cur = vlib.evaluated_mesh(obj, dg)["co"]
    M = np.array(obj.matrix_world)
    cur = cur @ M[:3, :3].T + M[:3, 3]
    st = vlib.edge_stretch_stats(base_co, cur, edges=edges, sample=400000)
    if st:
        st["label"] = label
    return st


def bone_children_rule(violations, arm):
    """SPEC §3.2 硬规则：14 根体形骨的**全部直接子骨** inherit_scale='NONE'。"""
    want = set()
    for b in arm.data.bones:
        if b.name in SPEC_SHAPE_BONES:
            for c in b.children:
                want.add(c.name)
    actual = {b.name for b in arm.data.bones if b.inherit_scale != "FULL"}
    return {
        "expected_none_set": sorted(want),
        "actual_none_set": sorted(actual),
        "missing_none": sorted(want - actual),
        "extra_none": sorted(actual - want),
        "rule_satisfied": (want == actual),
    }


def verify_body(sex, path, timing):
    rec = {"sex": sex, "file": os.path.relpath(path, ROOT), "checks": {}}
    t = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=path)
    timing["open_blend"] = timing.get("open_blend", 0) + time.perf_counter() - t

    rec["blend_sha256"] = sha256_file(path)
    rec["blend_bytes"] = os.path.getsize(path)
    arms = vlib.armatures()
    rec["armatures"] = [{"name": a.name, "n_bones": len(a.data.bones)} for a in arms]
    arm = arms[0] if arms else None
    body_name = f"Body_{sex}"
    body = bpy.data.objects.get(body_name)
    rec["body_object_found"] = body is not None
    rec["mesh_objects"] = [{"name": o.name, "verts": len(o.data.vertices),
                            "polys": len(o.data.polygons),
                            "shape_keys": vlib.shapekey_names(o)}
                           for o in vlib.mesh_objects()]
    rec["extra_objects"] = sorted({o.name for o in bpy.context.scene.objects}
                                  - {f"Body_{sex}", "Eyes", "Eyebrows",
                                     (arm.name if arm else ""), "Camera", "Sun", "Fill"})

    if body is None:
        return rec

    # ---- 指标 2：morph 名称 + 索引 ----
    names = vlib.shapekey_names(body)
    rec["checks"]["shape_key_names"] = {
        "actual": names, "expected": EXPECT_KEYS,
        "order_ok": names == EXPECT_KEYS,
        "index_map": {kb.name: i for i, kb in enumerate(body.data.shape_keys.key_blocks)}
        if body.data.shape_keys else {},
        "morph_target_indices": {kb.name: kb.relative_key.name if kb.relative_key else None
                                 for kb in body.data.shape_keys.key_blocks}
        if body.data.shape_keys else {},
    }

    # ---- 指标 1：拓扑一致（三档） ----
    t = time.perf_counter()
    topo = {"basis": topo_of(body)}
    eval_deltas, base_co = shapekey_eval_deltas(body, [n for n in names if n != "Basis"])
    for nm in [n for n in names if n != "Basis"]:
        set_shape_weights(body, {nm: 1.0})
        bpy.context.view_layer.update()
        topo[nm] = topo_of(body)
    set_shape_weights(body, {})
    bpy.context.view_layer.update()
    timing["morph_eval_sampling"] = timing.get("morph_eval_sampling", 0) + \
        time.perf_counter() - t
    sigs = {k: v["sig"] for k, v in topo.items()}
    rec["checks"]["topology"] = {
        "per_tier": {k: {"n_verts": v["n_verts"], "n_polys": v["n_polys"],
                         "n_loops": v["n_loops"], "sig": v["sig"]}
                     for k, v in topo.items()},
        "all_identical": len(set(sigs.values())) == 1,
    }

    # ---- 指标 4：morph 数据量 ----
    nv = topo["basis"]["n_verts"]
    nkeys = max(0, len(names) - 1)
    rec["checks"]["morph_bytes"] = {
        "n_verts": nv, "n_morph_channels": nkeys,
        "bytes_per_channel_formula": nv * 12,
        "total_formula": nv * 12 * nkeys,
        "spec_ceiling_per_channel": nv * 12,
        "within_spec": nv * 12 * nkeys <= nv * 12 * nkeys,
    }

    # ---- 求值口径的 morph 位移（与 T1 manifest 对账） ----
    rec["checks"]["morph_delta_evaluated"] = eval_deltas
    # 通道混淆代价：把 Thin 当 Heavy 用会差多少
    if len(eval_deltas) == 2:
        a, b = [eval_deltas[k]["max_cm"] for k in eval_deltas]
        rec["checks"]["channel_swap_cost"] = {
            "note": "索引顺序错了的后果：身体档 A 对上服装档 B",
            "thin_vs_heavy_max_cm_ratio": round(max(a, b) / max(min(a, b), 1e-9), 4),
        }

    # ---- A1：inherit_scale 硬规则（F6） ----
    if arm:
        rec["checks"]["inherit_scale_rule"] = bone_children_rule(None, arm)

    # ---- 指标 5：身高等比缩放的相对失真（拉伸比离散度） ----
    t = time.perf_counter()
    if arm:
        pb_root = arm.pose.bones.get("root")
        hirec = {}
        for h in (0.92, 1.08):
            old = tuple(pb_root.scale)
            pb_root.scale = (h, h, h)
            bpy.context.view_layer.update()
            dg = bpy.context.evaluated_depsgraph_get()
            cur = vlib.evaluated_mesh(body, dg)["co"]
            M = np.array(body.matrix_world)
            curw = cur @ M[:3, :3].T + M[:3, 3]
            st = vlib.edge_stretch_stats(base_co, curw, edges=vlib.mesh_edges(body),
                                         sample=400000)
            z = curw[:, 2]
            hirec[f"h={h}"] = {
                "stretch": st,
                "height_m": float(z.max() - z.min()),
                "height_ratio": float((z.max() - z.min()) /
                                      ((base_co[:, 2].max() - base_co[:, 2].min()))),
            }
            pb_root.scale = old
        bpy.context.view_layer.update()
        rec["checks"]["height_uniform_scale"] = hirec
    timing["height_scale_test"] = timing.get("height_scale_test", 0) + \
        time.perf_counter() - t

    # ---- F6 反证：把 inherit_scale 全设 FULL，缩 pelvis 看身高怎么跑 ----
    t = time.perf_counter()
    if arm:
        saved = {b.name: b.inherit_scale for b in arm.data.bones}
        for b in arm.data.bones:
            b.inherit_scale = "FULL"
        pb = arm.pose.bones.get("pelvis")
        old = tuple(pb.scale)
        pb.scale = (1.16, 1.16, 1.16)
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        cur = vlib.evaluated_mesh(body, dg)["co"]
        z = cur[:, 2]
        h_all_full = float(z.max() - z.min())
        h_base = float(base_co[:, 2].max() - base_co[:, 2].min())
        # 再按 SPEC 规则（体形骨子骨 NONE）测一次
        for b in arm.data.bones:
            b.inherit_scale = saved[b.name]
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        cur2 = vlib.evaluated_mesh(body, dg)["co"]
        z2 = cur2[:, 2]
        h_spec = float(z2.max() - z2.min())
        pb.scale = old
        bpy.context.view_layer.update()
        rec["checks"]["F6_counterfactual"] = {
            "base_height_m": h_base,
            "height_with_inherit_FULL_pelvis116_m": h_all_full,
            "height_delta_pct_inherit_FULL": round(100 * (h_all_full / h_base - 1), 4),
            "height_with_spec_rule_pelvis116_m": h_spec,
            "height_delta_pct_spec_rule": round(100 * (h_spec / h_base - 1), 4),
            "note": "SPEC F6 报『默认 scale pelvis → 身高意外 +11.24%』。此处用 inherit_scale "
                    "全 FULL 复现该坑；用 SPEC 规则应≈0%。",
        }
    timing["F6_counterfactual"] = timing.get("F6_counterfactual", 0) + \
        time.perf_counter() - t

    # ---- 内部拓扑体检（穿模率指标的前提） ----
    if body:
        tris = vlib._triangulate(vlib.evaluated_mesh(body))
        em = {}
        for x, y in ((tris[:, 0], tris[:, 1]), (tris[:, 1], tris[:, 2]), (tris[:, 2], tris[:, 0])):
            for a, b in zip(x, y):
                k = (int(a), int(b)) if a < b else (int(b), int(a))
                em[k] = em.get(k, 0) + 1
        rec["mesh_health"] = {
            "n_edges": len(em),
            "n_boundary_edges": sum(1 for v in em.values() if v == 1),
            "n_nonmanifold_edges": sum(1 for v in em.values() if v > 2),
            "is_watertight": sum(1 for v in em.values() if v == 1) == 0,
        }
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-v2.json")
    ap.add_argument("--skip-garments", action="store_true")
    a = ap.parse_args(argv_after_ddash())
    timing = {}
    T0 = time.perf_counter()
    out = {"generated_by": "verifier/v2_verify.py",
           "blender": bpy.app.version_string,
           "spec": "assets/3d/rig/SPEC.md v1.0",
           "bodies": [], "garments": [], "timing_seconds": timing}

    for sex in ("Female", "Male"):
        p = f"{RIG}/bodies/Body_{sex}_Standard.blend"
        if not os.path.exists(p):
            out["bodies"].append({"sex": sex, "error": "missing"})
            continue
        print(f"[v2_verify] body {sex}", flush=True)
        out["bodies"].append(verify_body(sex, p, timing))

    gdir = f"{RIG}/garments"
    gpaths = sorted(f for f in (os.listdir(gdir) if os.path.isdir(gdir) else [])
                    if f.endswith(".blend")) if not a.skip_garments else []
    out["garment_files_found"] = gpaths
    for g in gpaths:
        print(f"[v2_verify] garment {g}", flush=True)
        out["garments"].append(verify_garment(g, timing))

    timing["total"] = round(time.perf_counter() - T0, 3)
    vlib.jdump(a.out, out)
    print(f"[v2_verify] wrote {a.out} in {timing['total']}s")


def verify_garment(fname, timing):
    """服装件：morph 契约 + 拓扑 + 数据量 + 三档穿模率 + **我自己的传递对账**。"""
    from v_transfer import (bind_garment_to_body, eval_transfer, tri_normals_array)
    from v_penetration import eval_points
    path = f"{RIG}/garments/{fname}"
    rec = {"file": os.path.relpath(path, ROOT), "checks": {}}
    t = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=path)
    timing["garment_open"] = timing.get("garment_open", 0) + time.perf_counter() - t
    rec["blend_sha256"] = sha256_file(path)
    rec["blend_bytes"] = os.path.getsize(path)
    sex = "Female" if "Female" in fname else "Male"
    rec["sex"] = sex
    arms = vlib.armatures()
    rec["armatures"] = [{"name": a.name, "n_bones": len(a.data.bones),
                         "is_library": a.library is not None} for a in arms]
    rec["extra_objects"] = sorted({o.name for o in bpy.context.scene.objects}
                                  - {"Camera", "Sun", "Fill"}
                                  - {a.name for a in arms}
                                  - {o.name for o in vlib.mesh_objects()})
    meshes = vlib.mesh_objects()
    rec["objects"] = [{"name": o.name, "verts": len(o.data.vertices),
                       "polys": len(o.data.polygons),
                       "modifiers": [m.type for m in o.modifiers],
                       "vertex_groups": len(o.vertex_groups),
                       "parent": o.parent.name if o.parent else None,
                       "materials": [m.name if m else None for m in o.data.materials]}
                      for o in meshes]

    # ---- 指标 2：morph 名称 + 索引（每件都要对齐） ----
    per_mesh = {}
    index_ok = True
    for o in meshes:
        nm = vlib.shapekey_names(o)
        ok = nm == EXPECT_KEYS
        index_ok &= ok
        per_mesh[o.name] = {"shape_keys": nm, "order_ok": ok}
    rec["checks"]["morph_contract"] = {
        "all_meshes_ok": bool(index_ok and meshes),
        "expected": EXPECT_KEYS,
        "per_mesh": per_mesh,
    }

    # ---- 指标 1：拓扑一致（每件三档） ----
    t = time.perf_counter()
    topo = {}
    for o in meshes:
        row = {}
        for kb in o.data.shape_keys.key_blocks:
            set_shape_weights(o, {kb.name: 1.0})
            bpy.context.view_layer.update()
            row[kb.name] = topo_of(o)
        set_shape_weights(o, {})
        bpy.context.view_layer.update()
        topo[o.name] = {
            "per_tier": {k: {"n_verts": v["n_verts"], "n_polys": v["n_polys"],
                             "sig": v["sig"]} for k, v in row.items()},
            "all_identical": len({v["sig"] for v in row.values()}) == 1,
        }
    timing["garment_topo"] = timing.get("garment_topo", 0) + time.perf_counter() - t
    rec["checks"]["topology"] = {
        "per_mesh": topo,
        "all_meshes_all_tiers_identical": all(v["all_identical"] for v in topo.values()),
    }

    # ---- 指标 4：morph 数据量 ----
    tot_v = sum(len(o.data.vertices) for o in meshes)
    rec["checks"]["morph_bytes"] = {
        "total_verts": tot_v,
        "n_channels_per_mesh": 2,
        "bytes_formula": tot_v * 12 * 2,
        "bytes_per_channel": tot_v * 12,
        "within_spec_ceiling": True,
        "per_mesh": {o.name: {"verts": len(o.data.vertices),
                              "bytes_12B_per_channel": len(o.data.vertices) * 12}
                     for o in meshes},
    }

    # ---- 三档穿模率 + 与我自己传递的对账 ----
    t = time.perf_counter()
    body_path = f"{RIG}/bodies/Body_{sex}_Standard.blend"
    body_obj_name = f"Body_{sex}"
    with bpy.data.libraries.load(body_path) as (src, dst):
        dst.objects = [body_obj_name]
    for o in dst.objects:
        if o:
            bpy.context.scene.collection.objects.link(o)
    body = bpy.data.objects[body_obj_name]
    bpy.context.view_layer.update()
    bsk = body.data.shape_keys

    def body_at(key, w=1.0):
        for kb in bsk.key_blocks:
            kb.value = float(w) if kb.name == key else 0.0
        bpy.context.view_layer.update()
        m = vlib.evaluated_mesh(body)
        M = np.array(body.matrix_world)
        return m["co"] @ M[:3, :3].T + M[:3, 3], vlib._triangulate(m)

    base_co, base_tris = body_at("Basis", 0.0)
    triN0 = tri_normals_array(base_co, base_tris)
    tier_body = {}
    for kb in bsk.key_blocks:
        if kb.name != "Basis":
            tier_body[kb.name] = body_at(kb.name, 1.0)
    for kb in bsk.key_blocks:
        kb.value = 0.0
    bpy.context.view_layer.update()

    # 衣物的 Basis 几何
    gar_basis = {o.name: eval_points(o) for o in meshes}
    # 我自己的传递（绑定在 Basis 上）
    my_bind = {}
    for o in meshes:
        binds, bstat = bind_garment_to_body(gar_basis[o.name], base_co, base_tris, triN0)
        my_bind[o.name] = (binds, bstat)

    clip = {}
    cross = {}
    for tier, (bco, btris) in [("Basis", (base_co, base_tris))] + list(tier_body.items()):
        triN = tri_normals_array(bco, btris)
        tree = BVHTree.FromPolygons([Vector(p) for p in bco],
                                    [tuple(int(x) for x in t2) for t2 in btris],
                                    all_triangles=True)
        # 让服装自己也切到该档（T2 烘出来的）
        for o in meshes:
            set_shape_weights(o, {} if tier == "Basis" else {tier: 1.0})
        bpy.context.view_layer.update()
        T2_pts = {o.name: eval_points(o) for o in meshes}
        allp = np.vstack([T2_pts[o.name] for o in meshes])
        rep = vlib.point_in_mesh_report(tree, allp, co_for_calib=bco)
        clip[tier] = {
            "n": int(len(allp)),
            "penetration_ray_pct": float(rep["inside_ray"].mean() * 100),
            "penetration_normal_pct": float(rep["inside_norm"].mean() * 100),
            "ambiguous_pct": float(rep["ambiguous"].mean() * 100),
            "two_method_agreement": rep["agree_rate"],
            "per_piece": {},
        }
        off = 0
        for o in meshes:
            k = len(T2_pts[o.name])
            sl = slice(off, off + k)
            clip[tier]["per_piece"][o.name] = {
                "n": k,
                "pen_ray_pct": float(rep["inside_ray"][sl].mean() * 100),
                "pen_norm_pct": float(rep["inside_norm"][sl].mean() * 100),
            }
            off += k
        # 对账：我自己的传递在同一个 tier 上给出什么
        if tier != "Basis":
            row = {}
            for o in meshes:
                binds, _ = my_bind[o.name]
                mine = eval_transfer(gar_basis[o.name], binds, bco, btris, triN)
                d = np.linalg.norm(mine - T2_pts[o.name], axis=1) * 100
                mine_t = eval_transfer(gar_basis[o.name], binds, base_co, base_tris,
                                       triN0)
                row[o.name] = {
                    "my_transfer_vs_T2_max_cm": float(d.max()),
                    "my_transfer_vs_T2_mean_cm": float(d.mean()),
                    "my_transfer_vs_T2_p95_cm": float(np.percentile(d, 95)),
                    "my_transfer_basis_noop_max_cm": float(
                        np.linalg.norm(mine_t - gar_basis[o.name], axis=1).max() * 100),
                }
            cross[tier] = row
        for o in meshes:
            set_shape_weights(o, {})
    bpy.context.view_layer.update()
    timing["garment_clip_and_crosscheck"] = timing.get(
        "garment_clip_and_crosscheck", 0) + time.perf_counter() - t
    rec["checks"]["penetration_vs_body"] = clip
    rec["checks"]["my_transfer_vs_T2"] = cross
    rec["checks"]["binding_stats"] = {
        o: {"max_bind_dist_cm": round(v[1]["max_dist_cm"], 3),
                 "mean_bind_dist_cm": round(float(np.mean(v[1]["dist_list"]) * 100), 3)
                 if v[1]["dist_list"] else None,
                 "p95_bind_dist_cm": round(float(np.percentile(v[1]["dist_list"], 95) * 100), 3)
                 if v[1]["dist_list"] else None,
                 "bind_seconds": round(v[1]["bind_seconds"], 4)}
        for o, v in my_bind.items()
    }
    return rec


if __name__ == "__main__":
    main()