#!/usr/bin/env python3
"""
v_digest.py —— verifier 独立实现**逐档 morph 数值指纹**（`morph_digest_16`），
用于与 T2 manifest 做**逐位**对账（比统计量硬）。

口径（我按 T2 的描述独立实现，不抄他们的代码）：
  对每件网格按**名字排序**，取每个 shape key 的**顶点顺序**坐标，
  用 `struct.pack('<3f')` 打包后整体 sha256，取前 16 个 hex 字符。

⚠ 口径不确定性（我两边都算，便于对齐）：
  · 是否把**件名**也拌进哈希
  · 是否包含 `Basis`
  因此本脚本同时输出 4 个变体，取与 manifest 相符的那个再讨论。

用法（工作区根）：
  BL=/Applications/Blender.app/Contents/MacOS/Blender
  $BL -b --factory-startup --python-exit-code 1 --python \\
      task/007-morph-pipeline/verify/v_digest.py -- \\
      --out assets/3d/rig/reports/verify-digest.json
"""
import argparse
import hashlib
import json
import os
import struct
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
RIG = f"{ROOT}/assets/3d/rig"
OUTFITS = ["Female_Ranger", "Female_Peasant", "Male_Ranger", "Male_Peasant"]


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def mesh_objects():
    return [o for o in bpy.context.scene.objects
            if o.type == "MESH" and not o.name.startswith("Icosphere")]


def digest(meshes, key, include_name, include_basis):
    """返回 sha256[:16]。"""
    h = hashlib.sha256()
    keys = ["Basis", key] if include_basis else [key]
    for o in sorted(meshes, key=lambda x: x.name):
        if o.data.shape_keys is None:
            continue
        kbs = {kb.name: kb for kb in o.data.shape_keys.key_blocks}
        if key not in kbs:
            continue
        if include_name:
            h.update(o.name.encode())
        for kn in keys:
            if kn not in kbs:
                continue
            kb = kbs[kn]
            n = len(kb.data)
            arr = [0.0] * (n * 3)
            kb.data.foreach_get("co", arr)
            h.update(struct.pack(f"<{n*3}f", *arr))
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-digest.json")
    a = ap.parse_args(argv_after_ddash())
    man_path = f"{RIG}/manifests/garment_manifest.json"
    man = None
    if os.path.exists(man_path):
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f)
    t2 = {}
    for o in (man or {}).get("outfits", []):
        # 实测路径：outfits[i].B2_report_ref.tiers.<TIER>.morph_digest_16
        tiers = (((o.get("B2_report_ref") or {}).get("tiers")) or {})
        t2[o["outfit"]] = {k: v.get("morph_digest_16")
                           for k, v in tiers.items() if isinstance(v, dict)}
    out = {"generated_by": "verifier/v_digest.py",
           "spec": "对每件按名字排序，顶点顺序 pack('<3f') 后整体 sha256[:16]",
           "manifest_found": man is not None,
           "manifest_sha256_16": None,
           "cases": []}
    if man is not None:
        h = hashlib.sha256(open(man_path, "rb").read()).hexdigest()
        out["manifest_sha256_16"] = h[:16]
    for name in OUTFITS:
        path = f"{RIG}/garments/{name}.blend"
        if not os.path.exists(path):
            out["cases"].append({"outfit": name, "error": "missing"})
            continue
        bpy.ops.wm.open_mainfile(filepath=path)
        meshes = mesh_objects()
        rec = {"outfit": name, "n_meshes": len(meshes),
               "total_verts": int(sum(len(o.data.vertices) for o in meshes)),
               "variants": {}, "t2_manifest": t2.get(name, {}),
               "match": {}}
        for tier in ("BS_Thin", "BS_Heavy"):
            for inc_name in (False, True):
                for inc_basis in (False, True):
                    tag = f"{tier}|name={int(inc_name)}|basis={int(inc_basis)}"
                    rec["variants"][tag] = digest(meshes, tier, inc_name, inc_basis)
        # 与 manifest 对账（manifest 的键名我兼容几种写法）
        cand = {}
        for k, v in (rec["t2_manifest"] or {}).items():
            if isinstance(v, str):
                cand[k] = v
        if not cand:
            cand = {"BS_Thin": (rec["t2_manifest"] or {}).get("BS_Thin"),
                    "BS_Heavy": (rec["t2_manifest"] or {}).get("BS_Heavy")}
        for tier in ("BS_Thin", "BS_Heavy"):
            want = cand.get(tier)
            hits = [tag for tag, val in rec["variants"].items()
                    if tag.startswith(tier) and want and val == want]
            rec["match"][tier] = {"manifest": want,
                                  "verifier_matching_variant": hits[0] if hits else None,
                                  "agrees": bool(hits)}
        out["cases"].append(rec)
        print(f"### {name}: {rec['match']}", flush=True)
    vlib.jdump(a.out, out)
    print(f"[v_digest] wrote {a.out}")


if __name__ == "__main__":
    main()