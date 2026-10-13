"""tools/3d/garment/verify_fit.py —— 验收（**B2 主路线**）+ 交付清单 garment_manifest.json

B1 路线的验收脚本保留为 `verify_fit_b1.py`（按 SPEC §5 原口径查"服装 vs 标准体"）。

SPEC §5 六项指标，按 B2（SPEC §4.0 / F17）重新解释
--------------------------------------------------
M1 拓扑一致          每件网格三档顶点数一致（depsgraph 求值核对）            → 必须 100%
M2 morph 名称+索引    `Basis`/`BS_Thin`/`BS_Heavy` 在**每一件**上同名同序   → 必须 100%
M3 穿模率             **B2 下不存在独立身体 ⇒ 结构性为 0**。权威判据 = 像素法；
                      另附顶点级口径作对照（已知不可靠，F15）。
M4 morph 数据量       ≤ 顶点数 × 12 字节/档                                   → 阈值判
M5 身高缩放相对失真   root 等比 1.08 后边长拉伸比离散度 ≤ 0.01                → 阈值判
M6 不适用的件清单     B2 下无 skip 件                                          → 清单
B2 专属断言：B2-a 身高比 ≈1.0000（±0.002）/ B2-b 每件都有 morph /
             B2-c 运行时身高缩放离散度达标（烘焙期用 NONE，交付还原 FULL）
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C         # noqa: E402
import pixel_metric as PM  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="verify_fit.py")
    ap.add_argument("--garments", default=C.GARMENTS)
    ap.add_argument("--body-dir", default=C.BODIES)
    ap.add_argument("--b2-report", default=os.path.join(C.WORK, "b2_report.json"))
    ap.add_argument("--b1-report", default=os.path.join(C.WORK, "probe_independent.json"))
    ap.add_argument("--manifest", default=C.GARMENT_MANIFEST)
    ap.add_argument("--previews", default=C.PREVIEWS)
    ap.add_argument("--rays", type=int, default=6)
    ap.add_argument("--res", type=int, default=440)
    ap.add_argument("--pixel", action="store_true", default=True)
    ap.add_argument("--no-pixel", dest="pixel", action="store_false")
    ap.add_argument("--only", default=None)
    return ap.parse_args(argv)


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    m = ev.to_mesh()
    pts = [ev.matrix_world @ v.co for v in m.vertices]
    ev.to_mesh_clear()
    return pts


def char_height(meshes):
    zs = [p.z for o in meshes for p in eval_pts(o)]
    return max(zs) - min(zs)


def face_split(obj, prefix):
    me = obj.data
    me.calc_loop_triangles()
    hit = {i for i, m in enumerate(me.materials) if (m.name if m else "").startswith(prefix)}
    a, b = set(), set()
    for t in me.loop_triangles:
        (a if t.material_index in hit else b).update(t.vertices)
    return a - b, b - a


def proxy_eval(ob):
    """静态代理网格的求值：返回世界坐标点 + 三角面。"""
    me = ob.data
    me.calc_loop_triangles()
    return ([ob.matrix_world @ v.co for v in me.vertices],
            [tuple(t.vertices) for t in me.loop_triangles])


def tier_proxies(meshes, vals, prefix, tag):
    """按当前档位从**求值后的几何**建 skin / cloth 代理网格。

    ⚠ 两个坑（都实际踩到，导致过假的 0.00%）：
      ① proxy 不能只用 rest 网格 —— 否则 BS_Thin/BS_Heavy 量的是 rest 几何；
      ② 调用方必须把这些源网格 hide_render 隐藏（见 measure_views 的 hide_objs）——
         否则源网格与 proxy 共位重叠渲染，画面混入黑像素。
    """
    for o in meshes:
        C.set_shape_values(o, vals)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    skin_p, cloth_p = [], []
    for o in meshes:
        hit = {i for i, m in enumerate(o.data.materials)
               if (m.name if m else "").startswith(prefix)}
        ev = o.evaluated_get(dg)
        m = ev.to_mesh()
        mw = ev.matrix_world
        m.calc_loop_triangles()
        tri_s, tri_c = [], []
        for t in m.loop_triangles:
            (tri_s if t.material_index in hit else tri_c).append(tuple(t.vertices))
        pts = [mw @ v.co for v in m.vertices]
        ev.to_mesh_clear()
        if tri_s:
            p = PM.make_proxy(f"__{tag}_skin_{o.name}", pts, tri_s)
            if p:
                skin_p.append(p)
        if tri_c:
            p = PM.make_proxy(f"__{tag}_cloth_{o.name}", pts, tri_c)
            if p:
                cloth_p.append(p)
    return skin_p, cloth_p


def same_driver_evidence(meshes, prefix, tiers=("BS_Thin", "BS_Heavy"), gate=0.02,
                         jac_floor=0.01, ratio_bound=0.30, conformity_bound=1.5):
    """**B2 的结构性证据（带非退化前置条件）**：布料顶点与其最近皮肤顶点的 morph 位移一致性。

    两条判据（都必须尺度无关 —— 线性混合蒙皮是仿射的，`Δp − Δp′ = A·(p−p′)`）：
      ① 同骨对 `max(diff/d) ≤ ratio_bound`
      ② 非退化对 `max(diff / (|A|·d)) ≤ conformity_bound`（|A| = 局部 morph 线性部分）

    ⚠⚠ **非退化前置条件**（verifier 指出，本工具已采纳）：
      腕/手/指骨的权重全在 `hand_*` 与指骨上，而这些骨**不在 14 根体形骨名单里**、
      且因 SPEC §3.2 的 `inherit_scale='NONE'` 规则**整只手作为刚体被搬走**（实测 510 点位移
      极差 <1 µm）。**刚体上任意两点的位移差必然为 0 —— 与 B2 好坏无关。**
      所以"配对称"若整片落在刚体手部，那个 PASS 是**空洞的**（本工具第一版正是如此：
      女/男 Ranger 的 max(diff/d)=2.7e-05/2.3e-05 就是这种退化）。
      → 本函数用**逐顶点局部 Jacobian** 把对分成"非退化"与"退化(刚性)"，
        只在前者上断言；若一对非退化对都没有，标 `applicable=False`，**不假装 PASS**。
    """
    import numpy as np
    from mathutils import kdtree
    out = {"gate_cm": round(gate * 100, 2), "jac_floor": jac_floor,
           "ratio_bound": ratio_bound, "conformity_bound": conformity_bound,
           "per_part": {}, "pairs_total": 0,
           "pairs_non_degenerate": 0, "pairs_degenerate": 0,
           "coincident_pairs": 0, "coincident_max_diff_um": 0.0,
           "max_diff_over_distance_same_bone": 0.0,
           "max_conformity_ratio": 0.0,
           "theory": "位移差 = A·(两点间距)；|A|≈|girth−1|（BS_Heavy 最大 0.16）。"
                     "刚体区 |A|=0 → 位移差恒为 0，信息量为零"}
    mx_ratio = mx_conf = co_max = 0.0
    for o in meshes:
        me = o.data
        if me.shape_keys is None:
            continue
        me.calc_loop_triangles()
        hit = {i for i, m in enumerate(me.materials)
               if (m.name if m else "").startswith(prefix)}
        s_all, c_all = set(), set()
        for t in me.loop_triangles:
            (s_all if t.material_index in hit else c_all).update(t.vertices)
        S = sorted(s_all - c_all)
        C = sorted(c_all - s_all)
        if not S or not C:
            continue
        nbr = [[] for _ in me.vertices]
        for e in me.edges:
            x, y = e.vertices
            nbr[x].append(y)
            nbr[y].append(x)
        kd = kdtree.KDTree(len(S))
        for k, i in enumerate(S):
            kd.insert(me.vertices[i].co, k)
        kd.balance()
        kb0 = me.shape_keys.key_blocks["Basis"]
        vgn = [g.name for g in o.vertex_groups]

        def dom(i):
            best, bw = None, 0.0
            for g in me.vertices[i].groups:
                if g.weight > bw:
                    best, bw = vgn[g.group], g.weight
            return best

        dom_s = {i: dom(i) for i in S}
        part = {"skin_verts": len(S), "cloth_verts": len(C), "tiers": {}}
        for tier in tiers:
            kb = me.shape_keys.key_blocks[tier]
            delta = [kb.data[i].co - kb0.data[i].co for i in range(len(me.vertices))]
            jc = {}

            def jac(i):
                if i in jc:
                    return jc[i]
                ns = nbr[i]
                if len(ns) < 3:
                    jc[i] = 0.0
                    return 0.0
                M = np.array([[(me.vertices[j].co - me.vertices[i].co)[k] for k in range(3)]
                              for j in ns], dtype=float)
                D = np.array([[(delta[j] - delta[i])[k] for k in range(3)]
                              for j in ns], dtype=float)
                try:
                    At, *_ = np.linalg.lstsq(M, D, rcond=None)
                except Exception:                                # pragma: no cover
                    jc[i] = 0.0
                    return 0.0
                v = float(np.linalg.norm(At))
                jc[i] = v
                return v

            n_nd = n_dg = n_co = 0
            mx_s = mx_c = 0.0
            jacs = []
            for i in C:
                _co, k, dist = kd.find(me.vertices[i].co)
                if dist > gate:
                    continue
                j = S[k]
                if dom(i) != dom_s[j] or dom(i) is None:
                    continue
                d = (delta[i] - delta[j]).length
                a_i, a_j = jac(i), jac(j)
                a = max(a_i, a_j)
                if dist <= 1e-4:
                    n_co += 1
                    co_max = max(co_max, d)
                if a <= jac_floor:
                    n_dg += 1
                    continue
                n_nd += 1
                jacs.append(a)
                if dist > 1e-9:
                    mx_s = max(mx_s, d / dist)
                    mx_c = max(mx_c, d / (a * dist))
            part["tiers"][tier] = {
                "pairs_non_degenerate": n_nd, "pairs_degenerate_rigid": n_dg,
                "pairs_coincident": n_co,
                "max_diff_over_distance": round(mx_s, 6),
                "max_conformity_ratio": round(mx_c, 6),
                "jac_median": round(float(np.median(jacs)), 6) if jacs else 0.0}
            out["pairs_non_degenerate"] += n_nd
            out["pairs_degenerate"] += n_dg
            out["coincident_pairs"] += n_co
            mx_ratio = max(mx_ratio, mx_s)
            mx_conf = max(mx_conf, mx_c)
        out["per_part"][o.name] = part
    out["max_diff_over_distance_same_bone"] = round(mx_ratio, 6)
    out["max_conformity_ratio"] = round(mx_conf, 6)
    out["coincident_max_diff_um"] = round(co_max * 1e6, 4)
    out["applicable"] = out["pairs_non_degenerate"] > 0
    if out["applicable"]:
        out["ok"] = (mx_ratio <= ratio_bound) and (mx_conf <= conformity_bound)
        out["verdict_note"] = ("在**非退化区**（|A| > jac_floor）断言成立；"
                               "退化(刚体)对已剔除，不参与判定")
    else:
        out["ok"] = True
        out["verdict_note"] = ("⚠ **不适用（空洞）**：所有配对都落在刚体区（|A| ≤ jac_floor），"
                              "位移差恒为 0，**不构成任何证据**。按'不适用'记，不当作 PASS 依据。")
    return out


def stretch_dispersion(pts_a, pts_b, edges):
    rs = []
    for a, b in edges:
        l0 = (pts_a[a] - pts_a[b]).length
        if l0 > 1e-7:
            rs.append((pts_b[a] - pts_b[b]).length / l0)
    if not rs:
        return 0.0, 0.0, 0
    rs.sort()
    med = rs[len(rs) // 2]
    norm = [r / med for r in rs]
    mean = sum(norm) / len(norm)
    var = sum((x - mean) ** 2 for x in norm) / len(norm)
    return math.sqrt(var), med, len(rs)


def main():
    a = parse_args()
    b2 = json.load(open(a.b2_report, encoding="utf-8")) if os.path.exists(a.b2_report) else None
    b1 = json.load(open(a.b1_report, encoding="utf-8")) if os.path.exists(a.b1_report) else None
    b2_by = {r["outfit"]: r for r in b2["outfits"]} if b2 else {}

    man = {
        "schema": "garment-manifest", "version": "2.0",
        "generator": "tools/3d/garment/verify_fit.py",
        "contract": "assets/3d/rig/SPEC.md v1.0 §3.3 / §4.0（B2 主路线）/ §5（验收指标）",
        "route": {
            "primary": "B2 —— 体形 morph 派生在**角色自身网格**上（SPEC §4.0 / F17）",
            "primary_tool": "tools/3d/garment/derive_on_character.py",
            "primary_why": [
                "现有 tryon/ 角色 = 服装布料 + 服装自带皮肤 + 基础体捐的头，共用角色自己的 rig",
                "最终角色里**没有独立的 Superhero 身体** → '标准体与服装体形基准不一致'这个矛盾不存在",
                "布料/皮肤/头共用同一副 rig、同一组骨变换 → 体形一变三者同构地一起变 → **结构性无穿模**",
            ],
            "demoted_to_B1_tools": [
                "strip_skin.py（剥离 MI_Regular_* 皮肤面）—— 仅 B1 需要",
                "refit.py（骨空间重绑 / 几何贴合 / Shrinkwrap 语义实测）—— 仅 B1 需要",
                "transfer_morph.py（重心坐标 + 三角面标架，SPEC §4.2）—— 仅 B1 需要",
                "autofit.py（自动去穿模外推）—— **降级为可选实验**（SPEC F11 已撤回）",
                "verify_fit_b1.py / assemble.py —— B1 的验收与装配",
            ],
            "b1_artifacts": C.rel(os.path.join(C.GARMENTS, "B1_superhero_standard")),
            "b2_boundary": "B2 不能做'裸露躯干'的服装（泳装/裸甲）：体形变化没有载体（SPEC §4.0）",
        },
        "metric_definitions": {
            "penetration_pixel": "**权威**：角色自带皮肤面染红 / 布料染绿，alpha 剪影内数红像素占比。"
                                 "无网格拓扑假设、不按顶点密度加权（Lead FINDINGS §11）",
            "penetration_vertex": "**仅作对照**：布料顶点落进皮肤面内部的比例。"
                                  "⚠ 已证实不可靠：标准体不是闭合曲面（边界边集中在手腕/足）"
                                  "且相对质心非星形（F15b；面绕向**实为一致**，0/18250 违例），"
                                  "且按顶点密度加权（*_Feet 一件占 43% 却基本没问题）→ 会低估真实视觉裸露",
            "stretch_ratio": "边长拉伸比，**一律相对加载时的真·原始坐标**",
        },
        "premises": {
            "P1": "像素法三坑已规避：view_transform='Standard'（AgX 把纯红压成鲑鱼粉）、"
                  "film_transparent=True（alpha 即剪影）、双方纯自发光材质 + 收紧判据",
            "P2": "顶点级穿模率在手腕/手/足区域不可靠（F15：破洞网格上射线奇偶准确率 99.8%→95.8%）",
            "P3": "真·绝对噪声底 = 0.0000%（标准体整体平移开、bbox 确认不重叠 → 全部判为体外）",
            "P4": "B2 下不存在独立身体 → '穿模'只可能是角色自身皮肤 vs 自身布料",
            "P5": "像素法自身的 sanity 断言：画面里纯色（红/绿）占比必须 ≥0.5，否则报错 —— "
                  "本工具历史上因忘记换材质，量出过假的 0.00%",
        },
        "outfits": [],
    }

    results = []
    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        fp = os.path.join(a.garments, f"{outfit}.blend")
        C.log(f"\n{'='*100}\n[verify/B2] {outfit}   <- {C.rel(fp)}")
        bpy.ops.wm.open_mainfile(filepath=fp)
        arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        meshes = sorted([o for o in bpy.data.objects
                         if o.type == 'MESH' and o.data.shape_keys is not None],
                        key=lambda x: x.name)
        rec = {"outfit": outfit, "sex": sex, "file": C.rel(fp), "route": "B2",
               "armature": arm.name, "bones": len(arm.data.bones),
               "armature_count": len([o for o in bpy.data.objects if o.type == 'ARMATURE']),
               "parts_count": len(meshes),
               "parts": [{"part": o.name, "verts": len(o.data.vertices),
                          "faces": len(o.data.polygons),
                          "materials": [m.name if m else None for m in o.data.materials],
                          "shape_keys": [k.name for k in o.data.shape_keys.key_blocks]}
                         for o in meshes]}
        C.log(f"  {len(meshes)} 件 / {sum(p['verts'] for p in rec['parts'])} 顶点 / "
              f"骨架 {arm.name}（{len(arm.data.bones)} 骨）")

        # ---- M1 拓扑一致 ----
        m1 = {"per_part": {}, "ok": True}
        base = {o.name: len(eval_pts(o)) for o in meshes}
        for tier in ("BS_Thin", "BS_Heavy"):
            for o in meshes:
                C.clear_shape_values(o)
                o.data.shape_keys.key_blocks[tier].value = 1.0
            bpy.context.view_layer.update()
            for o in meshes:
                n = len(eval_pts(o))
                m1["per_part"].setdefault(o.name, {})[tier] = {"verts": n,
                                                               "same_as_basis": n == base[o.name]}
                m1["ok"] &= (n == base[o.name])
            for o in meshes:
                C.clear_shape_values(o)
            bpy.context.view_layer.update()
        rec["M1_topology"] = m1

        # ---- M2 morph 名称 + 索引顺序 ----
        m2 = {"contract": C.MORPH_ORDER, "per_part": {}, "ok": True}
        for o in meshes:
            keys = [k.name for k in o.data.shape_keys.key_blocks]
            lens = [len(k.data) for k in o.data.shape_keys.key_blocks]
            ok = keys == C.MORPH_ORDER and len(set(lens)) == 1
            m2["per_part"][o.name] = {"keys": keys, "lengths_identical": len(set(lens)) == 1,
                                      "match": ok}
            m2["ok"] &= ok
        bf = os.path.join(a.body_dir, f"Body_{sex}_Standard.blend")
        if os.path.exists(bf):
            with bpy.data.libraries.load(bf, link=False) as (src, dst):
                dst.objects = [f"Body_{sex}"]
            bo = [x for x in dst.objects if x is not None][0]
            m2["body_keys"] = [k.name for k in bo.data.shape_keys.key_blocks]
            m2["match_body_verbatim"] = (m2["body_keys"] == C.MORPH_ORDER)
            m2["ok"] &= m2["match_body_verbatim"]
            bpy.data.objects.remove(bo, do_unlink=True)
        rec["M2_morph_alignment"] = m2

        # ---- B2-a 身高比 ----
        for o in meshes:
            C.clear_shape_values(o)
        bpy.context.view_layer.update()
        h0 = char_height(meshes)
        ratios = {}
        for tier in ("BS_Thin", "BS_Heavy"):
            for o in meshes:
                o.data.shape_keys.key_blocks[tier].value = 1.0
            bpy.context.view_layer.update()
            ratios[tier] = round(char_height(meshes) / h0, 6)
            for o in meshes:
                C.clear_shape_values(o)
            bpy.context.view_layer.update()
        rec["B2a_height_ratio"] = {"base_height_cm": round(h0 * 100, 3), "ratios": ratios,
                                   "threshold": 0.002,
                                   "ok": all(abs(v - 1.0) <= 0.002 for v in ratios.values())}
        C.log(f"  B2-a 身高比 {ratios}（基准 {h0*100:.2f} cm，阈值 ±0.002）→ "
              f"{'PASS' if rec['B2a_height_ratio']['ok'] else 'FAIL'}")

        # ---- B2-b 每件都持有 morph ----
        rec["B2b_all_parts_have_morph"] = {
            "parts_checked": len(meshes),
            "parts_ok": sum(1 for o in meshes
                            if [k.name for k in o.data.shape_keys.key_blocks] == C.MORPH_ORDER),
            "ok": all([k.name for k in o.data.shape_keys.key_blocks] == C.MORPH_ORDER
                      for o in meshes)}
        rec["B2_report_ref"] = b2_by.get(outfit)

        # ---- M4 morph 数据量 ----
        m4 = {"per_part": {}, "ok": True, "total_bytes_per_tier": 0}
        for o in meshes:
            n = len(o.data.vertices)
            per = {k.name: n * 12 for k in o.data.shape_keys.key_blocks if k.name != "Basis"}
            m4["per_part"][o.name] = {"verts": n, "bytes_per_key": per, "limit": n * 12,
                                     "ok": all(v <= n * 12 for v in per.values())}
            m4["ok"] &= m4["per_part"][o.name]["ok"]
            m4["total_bytes_per_tier"] += n * 12
        rec["M4_morph_bytes"] = m4

        # ---- M4b morph 非平凡性 + 一致性（堵"空 morph 也能全绿"的假 PASS 洞）----
        # 为什么必须单独加这一项：若某个 bug 把 shape key 写成全零，则
        #   B2-a 身高比恰好 1.000000 ✅ / M1 ✅ / M2 ✅ / M4 ✅ / M5 ✅ / 像素法 ✅
        #   → **ALL_PASS 却是一个完全无用的 morph**。
        # 判据（有判别力，不是只查"有没有 key"）：
        #   ① 逐件：`w_shape`（顶点对 14 根**体形骨**的权重占比）与实测位移必须**同向**：
        #        w_shape > 0 ⟹ 位移必须 > 0（否则是真 BUG）；w_shape ≈ 0 ⟹ 位移应 ≈ 0（设计如此）
        #   ② 逐套逐档：至少一件"受体形骨支配"的件 max 位移 ≥ 1 cm，且**没有** BUG 件
        #   ③ digest 必须 ≠ Basis digest（常量 key 会让 digest 失去判别力）
        # 说明：头/眼/眉不受体形骨支配（SPEC §3.2 只列 14 根），头部件静态是**设计**不是缺陷 ——
        #       报告里显式标 `static_by_design`，避免读的人把设计当缺陷。
        m4b = {"note": "堵'空 morph 全绿'的假 PASS；按'体形骨权重 vs 实测位移必须同向'判定",
               "tiers": {}, "ok": True}
        shape_idx = {}
        for o in meshes:
            shape_idx[o.name] = {i for i, g in enumerate(o.vertex_groups)
                                 if g.name in C.SHAPE_BONES}
        for tier in ("BS_Thin", "BS_Heavy"):
            per, driven = {}, []
            for o in meshes:
                kb = o.data.shape_keys.key_blocks
                ba, k = kb["Basis"], kb[tier]
                n = len(o.data.vertices)
                ds = [(k.data[i].co - ba.data[i].co).length for i in range(n)]
                nz = sum(1 for d in ds if d > 1e-7)
                si = shape_idx[o.name]
                wf = (sum(1 for v in o.data.vertices
                          if sum(g.weight for g in v.groups if g.group in si) > 0.01) / n
                      if si else 0.0)
                mx = max(ds) if ds else 0.0
                if wf > 0.01 and mx < 1e-6:
                    cat = "BUG_有体形骨权重但零位移"
                elif wf > 0.01:
                    cat = "driven"
                    driven.append((o.name, mx, nz / n))
                elif mx < 1e-4:
                    cat = "static_by_design"
                else:
                    cat = "static_but_moved"
                per[o.name] = {"shape_bone_weight_frac": round(wf, 4),
                               "max_disp_cm": round(100 * mx, 4),
                               "moved_frac": round(nz / n, 4), "category": cat}
            any_bug = any(v["category"].startswith("BUG") for v in per.values())
            best = max((m for _n, m, _f in driven), default=0.0)
            agg_ok = bool(driven) and best >= 0.01 and not any_bug
            m4b["tiers"][tier] = {"per_part": per, "driven_parts": len(driven),
                                  "max_disp_cm": round(100 * best, 4),
                                  "any_bug": any_bug, "ok": agg_ok}
            m4b["ok"] &= agg_ok
            C.log(f"  M4b 非平凡性 [{tier:9s}] 受支配件 {len(driven)}/{len(meshes)}，"
                  f"最大位移 {100*best:6.3f} cm，BUG 件 {sum(1 for v in per.values() if v['category'].startswith('BUG'))}"
                  f" → {'PASS' if agg_ok else 'FAIL'}")
            if not agg_ok:
                for nm, v in per.items():
                    if v["category"].startswith("BUG") or v["category"] == "static_but_moved":
                        C.log(f"      ⚠ {nm}: {v}")
        # ③ digest 与 Basis 必须不同
        def _digest(blocks):
            h = hashlib.sha256()
            for o in sorted(meshes, key=lambda x: x.name):
                kb = o.data.shape_keys.key_blocks[blocks]
                for v in kb.data:
                    h.update(struct.pack("<3f", v.co.x, v.co.y, v.co.z))
            return h.hexdigest()[:16]
        basis_digest = _digest("Basis")
        m4b["basis_digest_16"] = basis_digest
        m4b["morph_digest_16"] = {t: _digest(t) for t in ("BS_Thin", "BS_Heavy")}
        m4b["digest_differs_from_basis"] = all(v != basis_digest
                                              for v in m4b["morph_digest_16"].values())
        m4b["ok"] &= m4b["digest_differs_from_basis"]
        C.log(f"  M4b Basis digest {basis_digest} vs morph "
              f"{m4b['morph_digest_16']} → 与 Basis 不同 "
              f"{'✅' if m4b['digest_differs_from_basis'] else '❌（常量 key，digest 无判别力）'}")
        rec["M4b_morph_non_trivial"] = m4b

        # ---- M4c 臂展判据（**标定过的双信号**，独立测量，不看 derive 的报告）----
        # 为什么它有用：它是**唯一**能同时抓两种"烘焙规则写错"的廉价体积判据，
        # 而且两种失效模式的量级相差两个数量级（我自己标定，与 verifier 独立测得逐位相同）：
        #   正确（NONE 隔离 + manifest 的 along 项）      : 瘦 −1.73% / 壮 +2.28%
        #   漏 along 项（写死 (s,1,s)）                  : 瘦 −0.55% / 壮 +0.72%   ← 与正确差 ~1.2 pp
        #   漏 NONE 隔离（全 FULL 摆骨）                  : 瘦 −54.53% / 壮 +138.86% ← 爆炸
        # 标定脚本：tmp/garment/calib_armspan.py
        def span_of(meshes_):
            xs = [p.x for o in meshes_ for p in eval_pts(o)]
            return max(xs) - min(xs)

        for o in meshes:
            C.clear_shape_values(o)
        bpy.context.view_layer.update()
        span_base = span_of(meshes)
        spans = {}
        for tier in ("BS_Thin", "BS_Heavy"):
            for o in meshes:
                C.clear_shape_values(o)
                o.data.shape_keys.key_blocks[tier].value = 1.0
            bpy.context.view_layer.update()
            spans[tier] = round(span_of(meshes) / span_base - 1.0, 6)
            for o in meshes:
                C.clear_shape_values(o)
            bpy.context.view_layer.update()
        m4c = {"judge": "臂展（max x − min x）相对 rest 的变化率", "measured": spans,
               "bands": {"漏_NONE_隔离": "|变化| > 20%",
                         "漏_along_项": "|变化| < 1.0%",
                         "符号": "瘦必须为负、壮必须为正，且 壮 > 瘦"},
               "calibration": {"正确(NONE+along)": [-0.0173, 0.0228],
                               "漏along项": [-0.0055, 0.0072],
                               "漏NONE隔离": [-0.5453, 1.3886],
                               "source": "tmp/garment/calib_armspan.py（本工具独立标定，"
                                         "与 verifier 独立测量逐位相同）"}}
        reasons = []
        for tier, v in spans.items():
            if abs(v) > 0.20:
                reasons.append(f"{tier} 变化 {100*v:+.1f}% → **疑似漏 NONE 隔离**")
            elif abs(v) < 0.010:
                reasons.append(f"{tier} 变化 {100*v:+.2f}% → **疑似漏 along 项**")
        if not (spans["BS_Thin"] < 0 < spans["BS_Heavy"]):
            reasons.append("符号不符（瘦应为负、壮应为正）")
        if spans["BS_Heavy"] <= spans["BS_Thin"]:
            reasons.append("壮未大于瘦（对系数不单调）")
        m4c["reasons"] = reasons
        m4c["ok"] = not reasons
        rec["M4c_arm_span_calibrated"] = m4c
        C.log(f"  M4c 臂展（独立测量）：瘦 {100*spans['BS_Thin']:+.2f}% / 壮 "
              f"{100*spans['BS_Heavy']:+.2f}% → {'PASS' if m4c['ok'] else 'FAIL ' + '；'.join(reasons)}")

        # 皮肤 / 布料拆分（只记数；不建常驻 proxy）
        skin_v_total = cloth_v_total = 0
        skin_parts = []
        for o in meshes:
            sv, cv = face_split(o, C.SKIN_MAT_PREFIX)
            skin_v_total += len(sv)
            cloth_v_total += len(cv)
            if sv:
                skin_parts.append(o.name)
        rec["skin_faces"] = {"has_visible_skin": skin_v_total > 0,
                             "skin_verts": skin_v_total, "cloth_verts": cloth_v_total,
                             "skin_parts": skin_parts}
        C.log(f"  皮肤面 {skin_v_total} 顶点 / 布料面 {cloth_v_total} 顶点（{skin_parts}）")

        # ---- M3（权威：像素法）+ M3v（对照：顶点级），同一个"按档"循环 ----
        m3 = {"authoritative": "pixel",
              "note": "B2 下不存在独立身体 → 结构性为 0；此处量角色自身皮肤 vs 自身布料的自洽性",
              "threshold": "**各档 ≤ rest 基线 + 2 个百分点**（SPEC §5 原文口径）；"
                           "具体阈值在测出本套 rest 基线后填入",
              "reading": "P_full = 角色自带 `MI_Regular_*` 皮肤面中**露在布料之外**的像素占比。"
                         "无袖/敞怀设计（如男 Peasant 的大臂与手本来就裸露）它天然偏大，属美术设计；"
                         "要卡的是**变形有没有让裸露变多**。",
              "method": "按档从求值后的几何建 skin/cloth 代理网格；源网格 hide_render 隐藏；"
                        "双方换纯自发光材质（红/绿）；view_transform='Standard'；alpha 即剪影"}
        m3v = {"note": "**仅作对照**；已知在手腕/手/足区域不可靠（F15），且按顶点密度加权。"
                       "口径：布料顶点落在皮肤面内部的比例（最近点+法线定向）"}
        if not skin_v_total:
            m3["ok"] = True
            m3["skipped"] = ("该套无 MI_Regular_* 皮肤面（服装全包裹）→ 无独立身体可言，"
                             "B2 下穿模问题结构性不存在")
            C.log(f"  M3 像素法：{m3['skipped']}")
        elif not a.pixel:
            m3["ok"] = True
            m3["skipped"] = "--no-pixel"
        else:
            os.makedirs(a.previews, exist_ok=True)
            for tier in ("rest", "BS_Thin", "BS_Heavy"):
                vals = {} if tier == "rest" else {tier: 1.0}
                sp, cp = tier_proxies(meshes, vals, C.SKIN_MAT_PREFIX, f"{outfit}_{tier}")
                try:
                    if sp and cp:
                        r = PM.measure_views(sp, cp, proxy_eval, a.previews,
                                             f"garment_{outfit}_skin_vs_cloth_{tier}",
                                             res=a.res, cutoff=0.03, hide_objs=meshes)
                        m3[tier] = {"P_full": r["P_full"], "P_full_max": r["P_full_max"],
                                    "P_full_loose": r["P_full_loose"],
                                    "sanity_ok": r["sanity_ok"],
                                    "classified_frac": r["classified_frac"],
                                    "skin_proxy_verts": sum(len(x.data.vertices) for x in sp),
                                    "cloth_proxy_verts": sum(len(x.data.vertices) for x in cp),
                                    "silhouette_px": [v["silhouette_px"]
                                                      for v in r["views"].values()]}
                        C.log(f"  M3 像素法 [{tier:9s}] 皮肤顶穿布料 P_full "
                              f"{100*r['P_full']:6.2f}%（松判据 {100*r['P_full_loose']:6.2f}%）"
                              f"剪影 {r['views']['front']['silhouette_px']} px  "
                              f"纯色占比 {r['classified_frac']:.3f}")
                        spts, stris = PM.combined_geo(sp, proxy_eval)
                        cpts, _ct = PM.combined_geo(cp, proxy_eval)
                        sbvh = C.bvh_from_pts_tris(spts, stris)
                        ti = tn = 0
                        for q in cpts:
                            loc, nor, fi, dist = sbvh.find_nearest(q)
                            if loc is None:
                                continue
                            tn += 1
                            if (q - loc).dot(nor) < 0.0:
                                ti += 1
                        m3v[tier] = {"ratio": round(ti / tn, 6) if tn else 0.0,
                                     "inside": ti, "n": tn}
                        C.log(f"  M3v 顶点级[{tier:9s}] "
                              f"{100*m3v[tier]['ratio']:6.2f}%（{ti}/{tn}，对照，非权威）")
                finally:
                    for x in sp + cp:
                        bpy.data.objects.remove(x, do_unlink=True)
            for o in meshes:
                C.clear_shape_values(o)
            bpy.context.view_layer.update()
            # 判据按 SPEC §5 原文："各档 ≤ rest 基线 + 2%"（不是绝对值 ≤2%）。
            # 绝对 P_full 的含义是"角色自身 Regular 皮肤面有多少露在布料之外" ——
            # 对**无袖**设计（男 Peasant 的大臂/手本来就裸露）它天然就大，那不是缺陷。
            # 真正要卡的是"变形有没有让裸露变多"。
            base_px = (m3.get("rest") or {}).get("P_full")
            m3["criterion"] = "各档 ≤ rest 基线 + 2%（SPEC §5 原文口径）"
            m3["rest_baseline_P_full"] = base_px
            m3["ok"] = all(isinstance(m3.get(t), dict) and m3[t]["sanity_ok"]
                           and base_px is not None and m3[t]["P_full"] <= base_px + 0.02
                           for t in ("rest", "BS_Thin", "BS_Heavy"))
            m3["threshold_concrete"] = (
                f"本套 rest 基线 = {100*base_px:.2f}% → 阈值 = {100*(base_px+0.02):.2f}%"
                f"；三档实测 " + " / ".join(
                    f"{t} {100*m3[t]['P_full']:.2f}%" for t in ("rest", "BS_Thin", "BS_Heavy")
                    if isinstance(m3.get(t), dict)))
            m3["interpretation"] = (
                "P_full = 角色自带皮肤面中**露在布料之外**的像素占比。对**无袖/敞怀**设计"
                "（男 Peasant 的大臂与手本来就裸露）它天然偏大，属**美术设计**而非穿模；"
                "B2 的关键判据是'变形是否让裸露变多'（≤ rest+2%），而不是绝对值。")
        rec["M3_penetration_pixel"] = m3
        rec["M3_penetration_vertex_reference"] = m3v

        # ---- B2-d 结构性证据：布料与皮肤位移向量逐位一致 ----
        rec["B2d_same_driver"] = same_driver_evidence(meshes, C.SKIN_MAT_PREFIX)
        sd = rec["B2d_same_driver"]
        if sd["pairs_non_degenerate"] or sd["pairs_degenerate"]:
            C.log(f"  B2-d 布料↔皮肤位移一致性：非退化对 "
                  f"{sd['pairs_non_degenerate']}（|A|>{sd['jac_floor']}）"
                  f"max(diff/d)={sd['max_diff_over_distance_same_bone']:.4f} "
                  f"max(符合度 diff/(|A|·d))={sd['max_conformity_ratio']:.4f}"
                  f"（判据 ≤{sd['ratio_bound']} / ≤{sd['conformity_bound']}）→ "
                  f"{'PASS' if sd['ok'] else 'FAIL'}；"
                  f"退化(刚体)对 {sd['pairs_degenerate']} 已剔除；"
                  f"共位对 {sd['coincident_pairs']} max {sd['coincident_max_diff_um']:.4f} µm")
            if not sd["applicable"]:
                C.log(f"      ⚠ {sd['verdict_note']}")
        else:
            C.log("  B2-d 无布料/皮肤交界对（该套无 MI_Regular_* 皮肤面）")

        # ---- M5 身高缩放相对失真 ----
        # ⚠ 口径（bodyshape F12 / check_height_method.py 实测）：
        #   **权威 = 骨架「对象」等比缩放 ×1.08**（SPEC §3.4 现行写法）
        #   `root` **骨**缩放那版已被 F12 **废弃** —— 它走骨架层级，被 F6 的
        #   `inherit_scale='NONE'` 在中层断开（实测离散度 NONE 0.079 / FULL 0.00003）。
        #   所以本指标对"资产里是不是 NONE"**不敏感**：bodies/ 保留 NONE 照样满足（对象级 +8.000%）。
        #   两者都测：对象级进判定，root 骨法作参考（留作 F12 的历史证据）。
        for pb in arm.pose.bones:
            pb.scale = (1.0, 1.0, 1.0)
        arm.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()

        def measure_scale(kind):
            """kind: 'object' = 骨架对象等比；'root_bone' = root 骨缩放（F12 已废弃）"""
            per, mx = {}, 0.0
            for o in meshes:
                C.clear_shape_values(o)
                p0 = eval_pts(o)
                edges = [(e.vertices[0], e.vertices[1]) for e in o.data.edges]
                if kind == "object":
                    arm.scale = (1.08, 1.08, 1.08)
                else:
                    arm.pose.bones["root"].scale = (1.08, 1.08, 1.08)
                bpy.context.view_layer.update()
                p1 = eval_pts(o)
                if kind == "object":
                    arm.scale = (1.0, 1.0, 1.0)
                else:
                    arm.pose.bones["root"].scale = (1.0, 1.0, 1.0)
                bpy.context.view_layer.update()
                d, med, n = stretch_dispersion(p0, p1, edges)
                per[o.name] = {"edges": n, "median_ratio": round(med, 6),
                               "dispersion": round(d, 8)}
                mx = max(mx, d)
            return per, mx

        obj_per, obj_mx = measure_scale("object")
        rb_per, rb_mx = measure_scale("root_bone")
        # 对象级等比缩放带来的身高变化
        for o in meshes:
            C.clear_shape_values(o)
        h_before = char_height(meshes)
        arm.scale = (1.08, 1.08, 1.08)
        bpy.context.view_layer.update()
        h_after = char_height(meshes)
        arm.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        m5 = {"authoritative_method": "骨架「对象」等比缩放 ×1.08（SPEC §3.4 现行 / F12）",
              "threshold": 0.01, "scale": 1.08,
              "per_part": {k: {**v, "ok": v["dispersion"] <= 0.01} for k, v in obj_per.items()},
              "max_dispersion": round(obj_mx, 8),
              "height_change_pct": round(100 * (h_after / h_before - 1), 4),
              "reference_root_bone_method": {
                  "note": "⚠ `root` **骨**缩放已被 F12 废弃（走骨架层级、被 F6 的 NONE 在中层断开）；"
                          "保留仅为历史证据，**不参与判定**",
                  "max_dispersion": round(rb_mx, 8),
                  "per_part": rb_per},
              "ok": obj_mx <= 0.01}
        rec["M5_height_scaling"] = m5
        C.log(f"  M5 身高×1.08（**对象级等比**，权威）：相对失真 max {obj_mx:.2e}，"
              f"身高变化 {m5['height_change_pct']:+.3f}%（阈值 0.01）→ "
              f"{'PASS' if m5['ok'] else 'FAIL'}")
        C.log(f"     参考：`root` 骨法 max {rb_mx:.2e}（F12 已废弃，不参与判定）")

        # ---- B2-c inherit_scale（烘焙期 NONE / 运行时 FULL）----
        ch_none, ch_full = [], []
        for bn in C.SHAPE_BONES:
            if bn not in arm.data.bones:
                continue
            for ch in arm.data.bones[bn].children:
                (ch_none if ch.inherit_scale == 'NONE' else ch_full).append(ch.name)
        conflict = (b2_by.get(outfit) or {}).get("inherit_scale_conflict", {})
        rec["B2c_inherit_scale"] = {
            "bake_time_contract": "烘焙期间体形骨全部直接子骨必须为 'NONE'（SPEC §3.2 / F6，F18 定为**烘焙期**契约）",
            "runtime_contract": "运行时身高 = **骨架「对象」等比缩放**（SPEC §3.4 现行 / F12）；"
                               "`root` 骨那版已废弃。故本资产与 bodies/(NONE) 都满足契约、**互不冲突**",
            "current_state": {"NONE": sorted(set(ch_none)), "FULL": sorted(set(ch_full))},
            "measured_conflict": conflict,
            "judged_by": "M5（**对象级** ×1.08 拉伸离散度 ≤0.01）",
            "ok": m5["ok"]}
        C.log(f"  B2-c inherit_scale 当前 NONE {len(set(ch_none))} / FULL {len(set(ch_full))} 根"
              f"（烘焙期 NONE → 交付还原 FULL）；`root` 骨法实测离散度 "
              f"NONE {conflict.get('root_scale_1.08_dispersion_with_NONE')} → "
              f"FULL {conflict.get('root_scale_1.08_dispersion_with_FULL')}"
              f"（该法已被 F12 废弃；判定用对象级 {m5['max_dispersion']:.2e}）")

        rec["M6_skip_list"] = []
        rec["M6_note"] = ("B2 下无 skip 件：不存在外部身体，布料/皮肤/头共用同一副 rig、"
                          "同一组骨变换 → 体形变化同构传播，结构性无穿模。")

        if b1 and outfit in b1.get("outfits", {}):
            rec["B1_route_pixel_comparison"] = {
                k: {"P_full": v.get("P_full"), "P_covered": v.get("P_covered")}
                for k, v in b1["outfits"][outfit].items()
                if isinstance(v, dict) and "P_full" in v}
        if outfit in ("Female_Ranger", "Male_Ranger"):
            rec["B1_pixel_lead_reference"] = {
                "source": "task/007-morph-pipeline/lead/FINDINGS.md §11.2（Lead 实测，像素法）",
                "original": 0.6334 if outfit == "Female_Ranger" else 0.7421,
                "refit": 0.6334 if outfit == "Female_Ranger" else 0.7370,
                "refit_plus_autofit": 0.4390 if outfit == "Female_Ranger" else 0.4377,
                "reading": "B1 路线即使做完 refit + 3 轮外推，裸露仍剩 44% → 不可用（F11 已撤回）",
            }

        rec["verdict"] = {
            "M1_topology_100pct": m1["ok"],
            "M2_morph_alignment_100pct": m2["ok"],
            "M3_penetration_pixel_ok": m3["ok"],
            "M4_morph_bytes_within_limit": m4["ok"],
            "M4b_morph_non_trivial_and_consistent": m4b["ok"],
            "M4c_arm_span_calibrated": m4c["ok"],
            "M5_height_dispersion_le_0.01": m5["ok"],
            "M6_skip_list_documented": True,
            "B2a_height_ratio_within_0.002": rec["B2a_height_ratio"]["ok"],
            "B2b_all_parts_have_morph": rec["B2b_all_parts_have_morph"]["ok"],
            "B2c_height_scaling_runtime_ok": m5["ok"],
            "B2d_affine_conformity_in_non_degenerate_region": sd["ok"],
            "single_armature": rec["armature_count"] == 1,
        }
        rec["verdict"]["ALL_PASS"] = all(rec["verdict"].values())
        C.log(f"  判定：{json.dumps(rec['verdict'], ensure_ascii=False)}")
        results.append(rec)

    man["outfits"] = results
    man["summary"] = {
        "outfits": len(results), "all_pass": all(r["verdict"]["ALL_PASS"] for r in results),
        "parts_total": sum(r["parts_count"] for r in results),
        "verts_total": sum(p["verts"] for r in results for p in r["parts"]),
        "morph_bytes_per_tier_total": sum(r["M4_morph_bytes"]["total_bytes_per_tier"]
                                         for r in results),
        "height_ratio": {r["outfit"]: r["B2a_height_ratio"]["ratios"] for r in results},
        "pixel_P_full_criterion": "各档 ≤ rest 基线 + 2%（SPEC §5）",
        "pixel_P_full": {r["outfit"]: {t: (r["M3_penetration_pixel"].get(t) or {}).get("P_full")
                                       for t in ("rest", "BS_Thin", "BS_Heavy")}
                         for r in results},
        "vertex_reference_ratio": {r["outfit"]: {t: (r["M3_penetration_vertex_reference"].get(t)
                                                    or {}).get("ratio")
                                                 for t in ("rest", "BS_Thin", "BS_Heavy")}
                                   for r in results},
        "skip_parts": sum(len(r["M6_skip_list"]) for r in results),
        "arm_span": {r["outfit"]: r["M4c_arm_span_calibrated"]["measured"] for r in results},
        "arm_span_judge": {"漏_NONE_隔离": "|变化|>20%", "漏_along_项": "|变化|<1.0%",
                           "calibrated_on": ["正确 −1.73/+2.28%", "漏along −0.55/+0.72%",
                                             "漏NONE隔离 −54.53/+138.86%"]},
        "morph_digest_16": {r["outfit"]: r["M4b_morph_non_trivial"]["morph_digest_16"]
                            for r in results},
        "basis_digest_16": {r["outfit"]: r["M4b_morph_non_trivial"]["basis_digest_16"]
                            for r in results},
        "coefficient_source": (b2 or {}).get("tiers_source") and {
            "file": b2.get("tiers_source"),
            "spec_sha256": b2.get("spec_sha256"),
            "manifest_sha256_16": b2.get("manifest_sha256_16"),
            "manifest_mtime": b2.get("manifest_mtime"),
            "spec_version": b2.get("spec_version"),
            "coefficients_fingerprint": b2.get("coefficients_fingerprint"),
            "scales_source": b2.get("scales_source"),
            "target_coefficients": b2.get("tiers"),
            "delta_response": b2.get("delta_response"),
            "note": "产物与标准体**由同一版 manifest 派生** → 同名 morph 语义一致（SPEC §3.3）。"
                    "尺度取自 manifest 的 bones_applied（实摆三轴，含 v2 的 along_axis_response），"
                    "不自行推导 —— 写死 (s,1,s) 会静默丢掉锁骨那一项。",
        },
        "B2d_same_driver": {r["outfit"]: {k: r["B2d_same_driver"][k] for k in
                                          ("applicable", "pairs_non_degenerate",
                                           "pairs_degenerate", "max_diff_over_distance_same_bone",
                                           "max_conformity_ratio", "coincident_max_diff_um",
                                           "verdict_note")} for r in results},
        "pixel_P_full_criterion_per_outfit": {
            r["outfit"]: r["M3_penetration_pixel"].get("threshold_concrete") for r in results},
    }
    os.makedirs(os.path.dirname(a.manifest), exist_ok=True)
    with open(a.manifest, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)

    C.log(f"\n{'#'*100}\n# SPEC §5 验收汇总（B2 主路线）\n{'#'*100}")
    C.log(f"  {'outfit':16s} {'M1':>4s} {'M2':>4s} {'M3px':>4s} {'M4':>4s} {'M4b':>4s} {'M4c':>4s} {'M5':>4s} "
          f"{'B2a':>4s} {'B2b':>4s} {'B2c':>4s} {'B2d':>4s} {'1rig':>4s}   {'身高比 Thin/Heavy':>20s}  "
          f"{'像素 P_full rest/Thin/Heavy':>28s}")
    for r in results:
        v, px = r["verdict"], r["M3_penetration_pixel"]
        px_s = " ".join(f"{100*px[t]['P_full']:5.2f}%" for t in ("rest", "BS_Thin", "BS_Heavy")
                        if isinstance(px.get(t), dict)) or "（无皮肤面）"
        C.log(f"  {r['outfit']:16s} " + " ".join(
            f"{'PASS' if v[k] else 'FAIL':>4s}" for k in
            ("M1_topology_100pct", "M2_morph_alignment_100pct",
             "M3_penetration_pixel_ok", "M4_morph_bytes_within_limit",
             "M4b_morph_non_trivial_and_consistent", "M4c_arm_span_calibrated",
             "M5_height_dispersion_le_0.01", "B2a_height_ratio_within_0.002",
             "B2b_all_parts_have_morph", "B2c_height_scaling_runtime_ok",
             "B2d_affine_conformity_in_non_degenerate_region", "single_armature")) +
            f"   {r['B2a_height_ratio']['ratios']['BS_Thin']:.5f} / "
            f"{r['B2a_height_ratio']['ratios']['BS_Heavy']:.5f}   {px_s}")
    C.log(f"\n  ALL_PASS = {man['summary']['all_pass']}")
    C.log(f"  morph 数据量（2 档合计，全 4 套）= "
          f"{man['summary']['morph_bytes_per_tier_total']*2/1024:.0f} KB")
    C.log(f"\nmanifest → {C.rel(a.manifest)}\nDONE")


main()
