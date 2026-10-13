#!/usr/bin/env python3
"""
v_nontrivial.py —— verifier 独立复算 T2 新增的 **M4b「morph 非平凡」** 判据。

**为什么这个判据重要**（T2 报的洞）：若 bug 把 shape key 写成全零，
`B2-a 身高比 = 1.000000 → PASS`，而 M1/M2/M4/M5/像素法**也全 PASS** → **ALL_PASS**。
**→ 需要一个"morph 真的动了、而且该动的地方动了"的判据。**

verifier 的复算口径（不抄 T2 的实现）：
  对每件网格、每档：
    · `w_shape(vertex)` = 该顶点在 **14 根体形骨** 顶点组上的权重之和
    · `disp(vertex)`    = BS_Heavy 求值位移（**depsgraph 口径**，不是读 key data）
  分类（我自己的阈值）：
    · `moved`        : max|disp| > 1e-4 cm                 → 动了
    · `BUG_suspect`  : max(w_shape) > 1e-4 且 max|disp| <= 1e-4 cm
                       （体形骨有权重却零位移 = 真 BUG）
    · `static_by_design` : max(w_shape) <= 1e-4 且 max|disp| <= 1e-4 cm
                       （不受体形骨支配且不动 = 设计，如头/眼/眉）
    · `moves_but_unweighted` : max(w_shape) <= 1e-4 但 max|disp| > 1e-4 cm
                       （**不动却能位移** = 位置继承而非缩放继承，SPEC F14）

另外做 **Basis 负对照**：morph digest 必须 ≠ Basis digest（否则说明 morph 是空的）。

用法：
  BL=/Applications/Blender.app/Contents/MacOS/Blender
  $BL -b --factory-startup --python-exit-code 1 --python \\
      task/007-morph-pipeline/verify/v_nontrivial.py -- \\
      --out assets/3d/rig/reports/verify-nontrivial.json
"""
import argparse
import hashlib
import json
import os
import struct
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
RIG = f"{ROOT}/assets/3d/rig"
OUTFITS = ["Female_Ranger", "Female_Peasant", "Male_Ranger", "Male_Peasant"]
SHAPE_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r"]
EPS_CM = 1e-4


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def eval_co(o):
    dg = bpy.context.evaluated_depsgraph_get()
    m = vlib.evaluated_mesh(o, dg)["co"].copy()
    M = np.array(o.matrix_world)
    return m @ M[:3, :3].T + M[:3, 3]


def w_shape_per_vertex(o):
    """每个顶点在 14 根体形骨上的权重之和。"""
    idx = {vg.index for vg in o.vertex_groups if vg.name in SHAPE_BONES}
    n = len(o.data.vertices)
    w = np.zeros(n)
    for v in o.data.vertices:
        s = 0.0
        for g in v.groups:
            if g.group in idx:
                s += g.weight
        w[v.index] = s
    return w


def digest(meshes, key):
    """与 SPEC 约定一致：按 object.name 排序 → 逐件 → 逐顶点 → 绝对坐标 pack('<3f')。"""
    h = hashlib.sha256()
    for o in sorted(meshes, key=lambda x: x.name):
        if o.data.shape_keys is None or key not in o.data.shape_keys.key_blocks:
            continue
        kb = o.data.shape_keys.key_blocks[key]
        n = len(kb.data)
        arr = [0.0] * (n * 3)
        kb.data.foreach_get("co", arr)
        h.update(struct.pack(f"<{n*3}f", *arr))
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-nontrivial.json")
    a = ap.parse_args(argv_after_ddash())
    man_path = f"{RIG}/manifests/garment_manifest.json"
    man = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    t2 = {}
    for o in man.get("outfits", []):
        ref = (o.get("B2_report_ref") or {})
        dig = {k: v.get("morph_digest_16") for k, v in (ref.get("tiers") or {}).items()
               if isinstance(v, dict)}
        m4b = o.get("M4b_morph_non_trivial") or {}
        t2[o["outfit"]] = {"digest": dig, "m4b": m4b,
                           "arm_span": o.get("arm_span"), "arm_span_judge": o.get("arm_span_judge")}
    out = {"generated_by": "verifier/v_nontrivial.py",
           "classified": {"moved": "max|disp| > 1e-4 cm",
                          "BUG_suspect": "体形骨有权重却零位移",
                          "static_by_design": "无权重且零位移",
                          "moves_but_unweighted": "无权重却有位移（位置继承, SPEC F14)"},
           "cases": []}
    for name in OUTFITS:
        path = f"{RIG}/garments/{name}.blend"
        if not os.path.exists(path):
            out["cases"].append({"outfit": name, "error": "missing"})
            continue
        bpy.ops.wm.open_mainfile(filepath=path)
        meshes = [o for o in bpy.context.scene.objects
                  if o.type == "MESH" and not o.name.startswith("Icosphere")]
        rec = {"outfit": name, "per_part": {},
               "digests": {}, "t2": t2.get(name, {}), "verdict": {}}
        # Basis 位置
        for o in meshes:
            if o.data.shape_keys:
                for kb in o.data.shape_keys.key_blocks:
                    kb.value = 0.0
        bpy.context.view_layer.update()
        base = {o.name: eval_co(o) for o in meshes}
        rec["digests"]["Basis"] = digest(meshes, "Basis")
        for tier in ("BS_Thin", "BS_Heavy"):
            for o in meshes:
                if o.data.shape_keys:
                    for kb in o.data.shape_keys.key_blocks:
                        kb.value = 1.0 if kb.name == tier else 0.0
            bpy.context.view_layer.update()
            rec["digests"][tier] = digest(meshes, tier)
            for o in meshes:
                if len(o.data.vertices) == 0:
                    continue
                disp = np.linalg.norm(eval_co(o) - base[o.name], axis=1) * 100
                w = w_shape_per_vertex(o)
                mx_d, mx_w = float(disp.max()), float(w.max())
                if mx_d > EPS_CM and mx_w <= EPS_CM:
                    cls = "moves_but_unweighted"
                elif mx_d > EPS_CM:
                    cls = "moved"
                elif mx_w > EPS_CM:
                    cls = "BUG_suspect"
                else:
                    cls = "static_by_design"
                rec["per_part"].setdefault(o.name, {})[tier] = {
                    "max_disp_cm": round(mx_d, 5), "max_w_shape": round(mx_w, 5),
                    "mean_w_shape": round(float(w.mean()), 5), "class": cls}
        for o in meshes:
            if o.data.shape_keys:
                for kb in o.data.shape_keys.key_blocks:
                    kb.value = 0.0
        bpy.context.view_layer.update()
        # verdict
        cls_all = [v["class"] for t in rec["per_part"].values() for v in t.values()]
        rec["verdict"] = {
            "n_parts": len(rec["per_part"]),
            "counts": {c: cls_all.count(c) for c in set(cls_all)},
            "any_BUG_suspect": any(c == "BUG_suspect" for c in cls_all),
            "any_moves_but_unweighted": any(c == "moves_but_unweighted" for c in cls_all),
            "morph_digest_differs_from_basis":
                {t: rec["digests"][t] != rec["digests"]["Basis"] for t in ("BS_Thin", "BS_Heavy")},
        }
        # 与 manifest 对账
        for t in ("BS_Thin", "BS_Heavy"):
            want = (t2.get(name, {}).get("digest") or {}).get(t)
            rec["verdict"].setdefault("digest_match_t2", {})[t] = (
                None if not want else want == rec["digests"][t])
        out["cases"].append(rec)
        print(f"### {name}: {rec['verdict']['counts']} "
              f"BUG={rec['verdict']['any_BUG_suspect']} "
              f"digest≠Basis={rec['verdict']['morph_digest_differs_from_basis']} "
              f"T2吻合={rec['verdict'].get('digest_match_t2')}", flush=True)
    vlib.jdump(a.out, out)
    print(f"[v_nontrivial] wrote {a.out}")


if __name__ == "__main__":
    main()