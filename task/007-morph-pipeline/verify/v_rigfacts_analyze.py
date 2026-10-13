#!/usr/bin/env python3
"""
v_rigfacts_analyze.py —— 对 v_rigfacts.py 的原始探针结果做独立比对，
复核 SPEC §1 的 F1 / F2（骨名顺序一致性、rest 差异、布料/皮肤面积比）。

纯 Python（不启动 Blender）。用法：
  python3 task/007-morph-pipeline/verify/v_rigfacts_analyze.py \
      --raw assets/3d/rig/reports/verify-rigfacts-raw.json \
      --out assets/3d/rig/reports/verify-rigfacts.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def norm_name(s):
    return s.replace("\\", "/").split("assets/3d/blend/")[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="assets/3d/rig/reports/verify-rigfacts-raw.json")
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-rigfacts.json")
    ap.add_argument("--tol-cm", type=float, default=0.01)
    a = ap.parse_args()
    raw = load(a.raw)
    recs = raw["records"]

    report = {"generated_by": "verifier/v_rigfacts_analyze.py",
              "source": a.raw, "n_files": len(recs),
              "rest_tolerance_cm": a.tol_cm}

    # ---------------- F1a：65 骨 + 骨名顺序 ----------------
    arm_sets = []          # (file, arm_name, tuple(bone_names), file_rel)
    for r in recs:
        for arm in r["armatures"]:
            arm_sets.append((r["rel"], arm["name"], tuple(arm["bone_names"]), arm))
    # 参考骨名取"出现次数最多的骨序列"——不预设谁是权威
    cnt = Counter(s[2] for s in arm_sets)
    top_seq, top_n = cnt.most_common(1)[0]
    ref_names = list(top_seq)
    report["F1a_bone_sequence"] = {
        "n_armatures_probed": len(arm_sets),
        "distinct_bone_sequences": len(cnt),
        "dominant_sequence_bone_count": len(ref_names),
        "dominant_sequence_armatures": top_n,
        "dominant_sequence_share": round(top_n / max(len(arm_sets), 1), 4),
        "deviating": [],
    }
    for rel, nm, names, arm in arm_sets:
        if names != top_seq:
            report["F1a_bone_sequence"]["deviating"].append({
                "file": rel, "armature": nm, "n_bones": len(names),
                "first_diff": next((i for i, (x, y) in enumerate(zip(names, ref_names)) if x != y), None),
                "only_in_file": sorted(set(names) - set(ref_names)),
                "missing": sorted(set(ref_names) - set(names)),
            })

    # 65 骨口径：所有 armature 是否都是 65
    ncount = Counter(len(s[2]) for s in arm_sets)
    report["F1a_bone_count_histogram"] = dict(sorted(ncount.items()))

    # ---------------- F1b：rest 姿态差异 ----------------
    def find_arm(patterns, exact_arm=None):
        hits = []
        for rel, nm, names, arm in arm_sets:
            if all(p in rel for p in patterns) and (exact_arm is None or nm == exact_arm):
                hits.append((rel, nm, arm))
        return hits

    def rest_delta(arm_a, arm_b, ref_names):
        ia = {n: np.array(h) for n, h in zip(arm_a["bone_names"], arm_a["bone_heads"])}
        ib = {n: np.array(h) for n, h in zip(arm_b["bone_names"], arm_b["bone_heads"])}
        rows = []
        for n in ref_names:
            if n not in ia or n not in ib:
                continue
            d = float(np.linalg.norm(ia[n] - ib[n]) * 100.0)
            rows.append((n, d))
        diffs = np.array([d for _, d in rows])
        over = [{"bone": n, "delta_cm": round(d, 4)} for n, d in rows if d > a.tol_cm]
        return {
            "n_bones_compared": len(rows),
            "n_bones_over_tol": len(over),
            "max_cm": round(float(diffs.max()), 4) if len(diffs) else None,
            "mean_cm": round(float(diffs.mean()), 4) if len(diffs) else None,
            "worst5": sorted(over, key=lambda r: -r["delta_cm"])[:5],
        }

    fem_body = find_arm(["base-characters/BaseCharacter_Superhero_Female"])[:1]
    male_body = find_arm(["base-characters/BaseCharacter_Superhero_Male"])[:1]
    pairs = {
        "female_body_vs_female_ranger": (fem_body, find_arm(["outfits-gltf/Outfit_Female_Ranger"])[:1]),
        "female_body_vs_female_peasant": (fem_body, find_arm(["outfits-gltf/Outfit_Female_Peasant"])[:1]),
        "male_body_vs_male_ranger": (male_body, find_arm(["outfits-gltf/Outfit_Male_Ranger"])[:1]),
        "male_body_vs_male_peasant": (male_body, find_arm(["outfits-gltf/Outfit_Male_Peasant"])[:1]),
        "female_body_vs_male_body": (fem_body, male_body),
    }
    f1b = {}
    for k, (A, B) in pairs.items():
        if not A or not B:
            f1b[k] = {"error": "armature not found", "A": [x[0] for x in A], "B": [x[0] for x in B]}
            continue
        f1b[k] = {"A": A[0][0], "B": B[0][0], **rest_delta(A[0][2], B[0][2], ref_names)}
    report["F1b_rest_pose_delta"] = f1b

    # ---- 容差敏感性：SPEC 写"男体↔男装 58/65 不一致"，容差取多少才复现 58？----
    tol_sweep = {}
    for k in ("female_body_vs_female_ranger", "male_body_vs_male_ranger"):
        A, B = pairs[k]
        if not A or not B:
            continue
        ia = {n: np.array(h) for n, h in zip(A[0][2]["bone_names"], A[0][2]["bone_heads"])}
        ib = {n: np.array(h) for n, h in zip(B[0][2]["bone_names"], B[0][2]["bone_heads"])}
        d = np.array([np.linalg.norm(ia[n] - ib[n]) * 100.0 for n in ref_names if n in ia and n in ib])
        tol_sweep[k] = {f"{t}": int((d > t).sum()) for t in
                        (0.0, 1e-6, 1e-4, 1e-3, 0.01, 0.05, 0.1, 0.5, 1.0)}
        tol_sweep[k]["_n"] = int(len(d))
        tol_sweep[k]["_sorted_deltas_cm"] = [round(float(x), 5) for x in np.sort(d)]
    report["F1b_tolerance_sweep"] = tol_sweep

    # ---------------- F2：布料 / 皮肤 面积比 ----------------
    targets = {
        "Female_Ranger_Arms": "outfits-gltf-per-asset/parts/Female_Ranger_Arms.blend",
        "Male_Peasant_Arms": "outfits-gltf-per-asset/parts/Male_Peasant_Arms.blend",
        "Male_Ranger_Arms": "outfits-gltf-per-asset/parts/Male_Ranger_Arms.blend",
        "Female_Peasant_Arms": "outfits-gltf-per-asset/parts/Female_Peasant_Arms.blend",
        "Female_Ranger_Body": "outfits-gltf-per-asset/parts/Female_Ranger_Body.blend",
        "Male_Peasant_Body": "outfits-gltf-per-asset/parts/Male_Peasant_Body.blend",
        "BaseCharacter_Superhero_Female": "base-characters/BaseCharacter_Superhero_Female.blend",
        "BaseCharacter_Superhero_Male": "base-characters/BaseCharacter_Superhero_Male.blend",
    }
    f2 = {}
    for label, suffix in targets.items():
        hit = next((r for r in recs if r["rel"].endswith("blend/" + suffix)), None)
        if hit is None:
            f2[label] = {"error": "file not found", "expected_suffix": suffix}
            continue
        agg = {kk: {"skin": 0.0, "other": 0.0} for kk in ("area_m2", "faces", "loops", "verts")}
        per_mesh = []
        for m in hit["meshes"]:
            for kk in agg:
                agg[kk]["skin"] += sum(v[kk] for k, v in m["materials"].items()
                                       if k.startswith("MI_Regular_"))
                agg[kk]["other"] += sum(v[kk] for k, v in m["materials"].items()
                                        if not k.startswith("MI_Regular_"))
            per_mesh.append({"mesh": m["name"], "n_verts": m["n_verts"],
                             "shape_keys": m["shape_keys"],
                             "materials": {k: {kk: v[kk] for kk in
                                               ("area_m2", "faces", "area_m2_frac", "faces_frac")}
                                           for k, v in m["materials"].items()}})
        rec = {"file": hit["rel"], "meshes": per_mesh,
               "material_names": sorted({k for m in hit["meshes"] for k in m["materials"]})}
        for kk in agg:
            tot = agg[kk]["skin"] + agg[kk]["other"]
            rec[f"skin_{kk}_frac"] = round(agg[kk]["skin"] / tot, 4) if tot else None
            rec[f"cloth_{kk}_frac"] = round(agg[kk]["other"] / tot, 4) if tot else None
        f2[label] = rec
    report["F2_cloth_vs_skin_area"] = f2

    # ---------------- 附：材质名全表（判"MI_Regular_*"这个判据是否够用） ----------------
    allmats = Counter()
    for r in recs:
        for m in r["meshes"]:
            for k in m["materials"]:
                allmats[k] += 1
    report["all_material_names"] = dict(sorted(allmats.items(), key=lambda kv: -kv[1]))
    report["regular_prefixed_materials"] = sorted(k for k in allmats if k.startswith("MI_Regular_"))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: report[k] for k in
                      ["F1a_bone_sequence", "F1a_bone_count_histogram", "F1b_rest_pose_delta"]},
                     ensure_ascii=False, indent=2))
    print(json.dumps(report["F2_cloth_vs_skin_area"], ensure_ascii=False, indent=2))
    print(f"[v_rigfacts_analyze] wrote {a.out}")


if __name__ == "__main__":
    main()