# -*- coding: utf-8 -*-
"""体形 morph 的 **fixture 兜底**：当 `assets/3d/rig/bodies/*.blend` 里的
`BS_Thin`/`BS_Heavy` 还是**全零占位通道**（T1 未落地时就是这个状态）时，
按 SPEC §3.2 的「骨骼滑块」路线在内存里现场派生一份，让 T3 的预览页面不必空等。

做法（与 SPEC §3.2 一致）：
  1. 对 canonical 体形骨逐根设 `pose.bones[b].scale = (c,c,c)`；
     SPEC 已要求这些骨的**直接子骨** `inherit_scale='NONE'`（F6），所以缩放只影响自己的权重区。
  2. 走 depsgraph 求值拿到形变后的顶点（F9：shape key 不改 `mesh.vertices`）。
  3. 抄成 `BS_Thin` / `BS_Heavy` 的坐标，清 pose。
  **只在内存里改，不写回 `assets/3d/rig/bodies/`**（那是 T1/Lead 的写入范围）。

幂等：如果该 body 的 morph 已经有非零数据（T1 已落地），本函数**直接跳过**，
只把 shape key 值清零，并报告 `source = "asset"`。
"""
import json
import os

import bpy

CANON_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r"]
COEFF = {"BS_Thin": 0.86, "BS_Heavy": 1.16}
EPS = 1e-6


def find_body(path_root=None):
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.name.startswith("Body_") and ob.data.shape_keys:
            return ob
    return None


def max_delta(ob):
    kb = ob.data.shape_keys.key_blocks
    n = len(ob.data.vertices)
    out = {}
    for k in kb:
        out[k.name] = max((k.data[i].co - kb["Basis"].data[i].co).length for i in range(n))
    return out


def coeffs_from_spec(spec_path):
    """能读到 T1 的 bodyshape_spec.json 就用它的系数，否则回落到 SPEC 的 0.86 / 1.16。"""
    c = dict(COEFF)
    src = "SPEC.md 默认 0.86 / 1.16"
    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            d = json.load(f)
        tiers = d.get("tiers") or {}
        for name, key in (("BS_Thin", "thin"), ("BS_Heavy", "heavy")):
            v = None
            if isinstance(tiers, dict):
                v = tiers.get(key)
                if isinstance(v, dict):
                    v = v.get("coefficient") or v.get("scale")
            if isinstance(v, (int, float)):
                c[name] = float(v)
        tc = d.get("target_coefficient") or {}
        if isinstance(tc, dict):
            for name, key in (("BS_Thin", "thin"), ("BS_Heavy", "heavy")):
                if isinstance(tc.get(key), (int, float)):
                    c[name] = float(tc[key])
        src = spec_path
    except Exception:
        pass
    return c, src


def ensure_body_morph(ob, spec_path=None):
    """返回 {'source': 'asset'|'bone_slider_fixture', ...}；就地改 ob 的 shape key（内存）。"""
    rep = {"object": ob.name, "coeff": {}, "coeff_src": None, "max_disp_mm": {},
           "source": None, "bones_scaled": []}
    kb = ob.data.shape_keys.key_blocks
    # 值先归零（源文件里存的是 1.0/1.0）
    for k in kb:
        k.value = 0.0
    md = max_delta(ob)
    rep["max_delta_before_mm"] = {k: round(1000.0 * v, 4) for k, v in md.items()}
    if md.get("BS_Thin", 0.0) > EPS and md.get("BS_Heavy", 0.0) > EPS:
        rep["source"] = "asset"
        rep["max_disp_mm"] = {k: round(1000.0 * md[k], 2) for k in ("BS_Thin", "BS_Heavy")}
        return rep

    # ---- fixture：骨骼滑块派生 ----
    coeff, csrc = coeffs_from_spec(spec_path) if spec_path else (dict(COEFF), "SPEC.md 默认 0.86 / 1.16")
    rep["coeff"] = coeff
    rep["coeff_src"] = csrc
    arm = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
    if arm is None:
        raise RuntimeError("body 里没有骨架，无法派生 fixture morph")
    missing = [b for b in CANON_BONES if arm.pose.bones.get(b) is None]
    if missing:
        raise RuntimeError("骨架缺少 canonical 体形骨：%s（SPEC §3.2 要求逐字一致）" % missing)

    n = len(ob.data.vertices)
    basis = [kb["Basis"].data[i].co.copy() for i in range(n)]
    for name in ("BS_Thin", "BS_Heavy"):
        c = coeff[name]
        for b in CANON_BONES:
            arm.pose.bones[b].scale = (c, c, c)
        rep["bones_scaled"] = list(CANON_BONES)
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        me = ob.evaluated_get(dg).to_mesh()
        if len(me.vertices) != n:
            raise RuntimeError("求值后顶点数变了 %d != %d" % (len(me.vertices), n))
        target = kb[name]
        dmax = 0.0
        for i in range(n):
            co = me.vertices[i].co.copy()
            target.data[i].co = co
            d = (co - basis[i]).length
            if d > dmax:
                dmax = d
        ob.evaluated_get(dg).to_mesh_clear()
        rep["max_disp_mm"][name] = round(1000.0 * dmax, 2)
        for b in CANON_BONES:  # 清 pose，准备下一档
            arm.pose.bones[b].scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
    # 确认清干净了
    for b in CANON_BONES:
        arm.pose.bones[b].scale = (1.0, 1.0, 1.0)
    for k in kb:
        k.value = 0.0
    bpy.context.view_layer.update()
    rep["source"] = "bone_slider_fixture"
    rep["bones_count"] = len(arm.data.bones)
    return rep