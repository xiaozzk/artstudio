#!/usr/bin/env python3
"""
v_rigfacts.py —— verifier 独立复核 SPEC §1 的 F1 / F2 事实。

**不调用 tools/3d/bodyshape 或 tools/3d/garment 的任何代码。**
全部读数走本目录 vlib.py，网格数据一律 depsgraph 求值。

用法（在工作区根）：
  BL=/Applications/Blender.app/Contents/MacOS/Blender
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_rigfacts.py -- \
      --out assets/3d/rig/reports/verify-rigfacts-raw.json
"""
import argparse
import glob
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

SCOPES = [
    "assets/3d/blend/base-characters/*.blend",
    "assets/3d/blend/outfits-gltf/*.blend",
    "assets/3d/blend/outfits-gltf-per-asset/**/*.blend",
    "assets/3d/blend/outfits-fbx/**/*.blend",
    "assets/3d/blend/tryon/*.blend",
]


def argv_after_ddash():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="assets/3d/rig/reports/verify-rigfacts-raw.json")
    p.add_argument("--globs", nargs="*", default=None)
    return p.parse_args(argv_after_ddash())


def collect_paths(args):
    paths = []
    for g in (args.globs or SCOPES):
        paths.extend(glob.glob(g, recursive=True))
    return sorted(set(os.path.abspath(p) for p in paths))


def probe(path):
    t0 = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=path)
    rec = {"path": path, "rel": os.path.relpath(path, os.getcwd()),
           "armatures": [], "meshes": [], "error": None}
    try:
        for arm in vlib.armatures():
            bones = vlib.rest_bone_table(arm)
            rec["armatures"].append({
                "name": arm.name,
                "n_bones": len(bones),
                "bone_names": [b["name"] for b in bones],
                "bone_heads": [b["head"] for b in bones],
            })
        dg = bpy.context.evaluated_depsgraph_get()
        for obj in vlib.mesh_objects():
            sig = vlib.eval_poly_signature(obj, dg)
            mats = vlib.material_face_area(obj, dg)
            nvg = len(obj.vertex_groups)
            has_arm_mod = any(m.type == "ARMATURE" for m in obj.modifiers)
            rec["meshes"].append({
                "name": obj.name,
                "n_verts": sig["n_verts"],
                "n_polys": sig["n_polys"],
                "topo_sig": sig["sig"],
                "n_vertex_groups": nvg,
                "armature_modifier": has_arm_mod,
                "shape_keys": vlib.shapekey_names(obj),
                "materials": mats,
            })
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["probe_seconds"] = round(time.perf_counter() - t0, 3)
    return rec


def main():
    args = parse()
    paths = collect_paths(args)
    print(f"[v_rigfacts] probing {len(paths)} blend files", flush=True)
    out = {"generated_by": "verifier/v_rigfacts.py", "n_files": len(paths),
           "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "records": []}
    t0 = time.perf_counter()
    for i, p in enumerate(paths, 1):
        r = probe(p)
        out["records"].append(r)
        print(f"  [{i}/{len(paths)}] {r['rel']}  bones="
              f"{[a['n_bones'] for a in r['armatures']]}  {r['probe_seconds']}s",
              flush=True)
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(args.out, out)
    print(f"[v_rigfacts] wrote {args.out} in {out['total_seconds']}s")


if __name__ == "__main__":
    main()