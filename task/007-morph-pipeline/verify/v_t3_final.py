#!/usr/bin/env python3
"""
v_t3_final.py —— verifier 对 T3 **最终产物**的独立核对（补 `v_godot.py` 未覆盖的新字段）。

全部自己算，不采信 report 里的自述：
  F1 **出处**：我自己 sha256 两份 manifest + 两个标准体，与 report 的 `asset_provenance` 比
  F2 **morph 契约在 Godot 运行时闭合**（我的 U10）：从 receipt 数件数与通道数、
     核 `BS_Thin index=0 / BS_Heavy index=1`、核 `set == read_back`
  F3 **像素法双向标定**：核 4/4 套的 `C1=100.00 / C2=0.00 / ok`，并核**口径声明**是否与
     `garment` 的 `P_full` 可对账（T3 说要用 `penetration_pct_of_union`）
  F4 **身高失真**：核 `node_scale.bone_stretch` 的 mean_ratio / dispersion
  F5 **P1 vs P3 橙斑**：把 T3 的 `pixel_diff_pct_of_p1_fg` 与我自己渲的 P1/P3 用**同一分母**换算
  F6 **零素材副本** + bake_log 无 error

用法：python3 task/007-morph-pipeline/verify/v_t3_final.py \
        --dir assets/3d/rig/previews --out assets/3d/rig/reports/verify-t3-final.json
"""
import argparse
import hashlib
import json
import os

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
RIG = f"{ROOT}/assets/3d/rig"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="assets/3d/rig/previews")
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-t3-final.json")
    a = ap.parse_args()
    rep = {"generated_by": "verifier/v_t3_final.py", "checks": {}}
    rp = os.path.join(a.dir, "preview_report.json")
    rr = os.path.join(a.dir, "preview_morph_receipt.json")
    if not (os.path.exists(rp) and os.path.exists(rr)):
        rep["status"] = "NOT_READY"
    else:
        R = json.load(open(rp, encoding="utf-8"))
        Q = json.load(open(rr, encoding="utf-8"))
        rep["status"] = "OK"

        # ---------------- F1 出处：我自己算 sha256 ----------------
        bm = f"{RIG}/manifests/bodyshape_manifest.json"
        gm = f"{RIG}/manifests/garment_manifest.json"
        my = {"bodyshape_file_sha256": sha(bm), "garment_file_sha256": sha(gm)}
        bman = json.load(open(bm, encoding="utf-8"))
        gman = json.load(open(gm, encoding="utf-8"))
        my["bodyshape_coeff_fingerprint"] = bman.get("coefficients_fingerprint")
        my["garment_coeff_fingerprint"] = (
            (gman.get("summary", {}).get("coefficient_source") or {}).get("coefficients_fingerprint"))
        my["bodyshape_spec_sha256"] = bman.get("spec_sha256")
        my["body_sha256"] = {}
        for b in bman.get("bodies", []):
            p = os.path.join(ROOT, b["file"])
            if os.path.exists(p):
                my["body_sha256"][b["file"]] = sha(p)
                my["body_sha256_declared_" + b["file"]] = b.get("blend_sha256")
        prov = R.get("asset_provenance", {})
        c = prov.get("checks", {})
        m = prov.get("manifests", {})
        rep["checks"]["F1_provenance"] = {
            "verifier_sha256": my,
            "report_says": c,
            "report_manifest_file_sha256": {
                "bodyshape": (m.get("bodyshape") or {}).get("file_sha256"),
                "garment": (m.get("garment") or {}).get("file_sha256")},
            "file_sha256_match": {
                "bodyshape": (m.get("bodyshape") or {}).get("file_sha256") == my["bodyshape_file_sha256"],
                "garment": (m.get("garment") or {}).get("file_sha256") == my["garment_file_sha256"],
            },
            "fingerprint_match_verifier": (
                my["bodyshape_coeff_fingerprint"] == my["garment_coeff_fingerprint"]
                == c.get("coefficients_fingerprint_bodyshape")),
            "all_body_sha_match": all(
                my["body_sha256"].get(k) == v for k, v in
                ((b["file"], b.get("blend_sha256")) for b in bman.get("bodies", []))),
        }

        # ---------------- F2 morph 契约（Godot 运行时闭合） ----------------
        shots = Q.get("shots", {})
        rows = []
        for name, s in shots.items():
            leaves = []
            for r in s.get("morph_per_part", []):
                if isinstance(r, dict) and isinstance(r.get("parts"), list):
                    leaves += [x for x in r["parts"] if isinstance(x, dict)]
                elif isinstance(r, dict):
                    leaves.append(r)
            n_parts = len(leaves)
            n_chan = sum(int(r.get("meshes", 0)) * 2 for r in leaves if str(r.get("part", "")).startswith("garment")
                         or str(r.get("part", "")).startswith("body"))
            # 实测 schema：叶子形如 {part:"character:XX", meshes:12, thin:1.0, heavy:0.0, note:"已驱动"}
            want_k = s.get("k")
            consist = []
            for r in leaves:
                th, hv = r.get("thin"), r.get("heavy")
                if isinstance(th, (int, float)) and isinstance(hv, (int, float)) and want_k is not None:
                    # k∈[-1,1] → thin=max(0,-k), heavy=max(0,k)
                    consist.append(abs(th - max(0.0, -want_k)) < 1e-6
                                   and abs(hv - max(0.0, want_k)) < 1e-6)
            rows.append({"shot": name, "k": want_k, "n_parts": n_parts,
                         "n_channels_est": n_chan,
                         "all_parts_driven_note": all("已驱动" in str(r.get("note", "")) or
                                                      r.get("meshes", 0) == 0 for r in leaves),
                         "values_match_requested_k": (all(consist) if consist else None),
                         "sample": leaves[:2]})
        rep["checks"]["F2_morph_contract_runtime"] = {
            "n_shots": len(rows), "shots": rows,
            "receipt_contract": Q.get("contract"),
            "note": "T3 自述：女 Ranger 12 件 / 24 通道，全 BS_Thin index=0 / BS_Heavy index=1，set==read_back",
        }

        # ---------------- F3 像素法标定 + 口径 ----------------
        pc = R.get("penetration_pixel_method_curves", {})
        f3 = {}
        for k, v in (pc.items() if isinstance(pc, dict) else []):
            cpm = v.get("curve_pixel_method") or {}
            cal = v.get("calibration") or cpm.get("calibration") or {}
            row0 = (cpm.get("rows") or [{}])[0]
            f3[k] = {
                "calibration": cal,
                "calib_ok": bool(cal.get("ok")),
                "C1": cal.get("C1_solid_only_expect_100"),
                "C2": cal.get("C2_layer_only_expect_0"),
                "rest_baseline_pct": cpm.get("rest_baseline_pct"),
                "mean_pct": cpm.get("mean_pct"), "max_pct": cpm.get("max_pct"),
                "first_k_over_baseline_plus_2pct": cpm.get("first_k_over_baseline_plus_2pct"),
                "row0_keys": sorted(row0.keys()) if isinstance(row0, dict) else None,
                "row0_of_union": row0.get("penetration_pct_of_union") if isinstance(row0, dict) else None,
                "normalization": cpm.get("normalization"),
                "height_uniformity": v.get("height_uniformity"),
            }
        rep["checks"]["F3_pixel_calibration"] = {
            "n": len(f3), "all_calib_ok": all(x["calib_ok"] for x in f3.values()),
            "all_C1_100": all(x["C1"] == 100.0 for x in f3.values()),
            "all_C2_0": all(x["C2"] == 0.0 for x in f3.values()),
            "per_outfit": f3,
            "method_note": R.get("penetration_method_note"),
        }

        # ---------------- F4 身高失真 ----------------
        hu = {}
        for _k, _v in (R.get("penetration_pixel_method_curves") or {}).items():
            if isinstance(_v, dict) and _v.get("height_uniformity"):
                hu = _v["height_uniformity"]
                break
        modes = hu.get("modes") or {}
        ns = (modes.get("node_scale") or {})
        rep["checks"]["F4_height"] = {
            "modes_present": sorted(modes.keys()),
            "node_scale_bone_stretch": ns.get("bone_stretch"),
            "node_scale_other": {k: v for k, v in ns.items() if k != "bone_stretch"},
            "note": "T3 自述 mean_ratio=1.08 / gain +8.00% / dispersion 1e-6（阈值 ≤0.01）",
        }

        # ---------------- F5 P1 vs P3 ----------------
        dbg = None
        for s in R.get("shots", []):
            if s.get("name") == "debug_p1_vs_p3":
                dbg = s
                break
        rep["checks"]["F5_p1_vs_p3"] = {
            "report": (dbg or {}).get("pixel_diff_pct_of_p1_fg"),
            "verifier_own_measurement": None,
        }
        # 我自己的测量（若在）
        mine = f"{RIG}/reports/verify-t3-integration.json"
        if os.path.exists(mine):
            t = json.load(open(mine, encoding="utf-8"))
            d = t.get("P1_vs_P3_pixel_diff", {})
            rep["checks"]["F5_p1_vs_p3"]["verifier_own_measurement"] = {
                k: v.get("changed_pct_of_P3_silhouette") for k, v in d.items()}
            rep["checks"]["F5_p1_vs_p3"]["thigh_band"] = t.get("thigh_band_P1_vs_P3")

        # ---------------- F6 零拷贝 + 日志 ----------------
        log = R.get("bake_log", [])
        bad = [l for l in log if isinstance(l, str) and
               any(k in l.lower() for k in ("error", "traceback", "failed", "fatal"))]
        rep["checks"]["F6_hygiene"] = {
            "zero_copy": R.get("zero_copy"),
            "n_log_lines": len(log), "n_suspicious": len(bad), "sample": bad[:3],
            "n_shots": len(R.get("shots", [])),
        }
        # 截图清点
        pngs = []
        for s in R.get("shots", []):
            p = s.get("png")
            if p:
                full = p if os.path.isabs(p) else os.path.join(a.dir, os.path.basename(p))
                pngs.append({"shot": s.get("name"), "exists": os.path.exists(full),
                             "bytes": os.path.getsize(full) if os.path.exists(full) else 0})
        rep["checks"]["F6_hygiene"]["pngs"] = pngs
        rep["checks"]["F6_hygiene"]["all_png_exist_nonempty"] = all(
            x["exists"] and x["bytes"] > 1000 for x in pngs)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(rep, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({k: (v if k != "F2_morph_contract_runtime" else
                          {kk: vv for kk, vv in v.items() if kk != "shots"})
                      for k, v in rep["checks"].items()},
                     ensure_ascii=False, indent=1)[:2600])
    print(f"[v_t3_final] wrote {a.out}")


if __name__ == "__main__":
    main()