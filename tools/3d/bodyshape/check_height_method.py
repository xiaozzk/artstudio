#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""身高缩放法 × `inherit_scale` 规则 的相容性实测（回应 garment 的 F6 澄清）。

**要回答的问题**：`bodies/` 的标准体把 F6 规则（14 根体形骨的直接子骨 = 18 根
`inherit_scale='NONE'`）留在文件里，会不会让标准体的**身高缩放**失真？

**为什么必须分清两件事**（这是上次"F6 与 §3.4 冲突"结论的来源）：
  * **root 骨**缩放：`pose.bones['root'].scale = h` —— 走**骨架层级**。
    F6 把中层断开了 → 缩放传不过去 → 部分骨段长、部分不长 → 拉伸离散度爆表。
    SPEC §3.4 的**原写法已被 F12 废弃**，正是因为这一点。
  * **骨架对象 / 角色根节点**的世界等比缩放：`armature_object.scale = (h,h,h)`。
    这是**对象级仿射变换**，整套求值结果被统一缩放 —— 与骨架层级、与 F6 **无关**。

本脚本把两种方法 × 三类资产都量一遍，用 verifier 的同一口径
`dispersion_rel = (P99(r) − P01(r)) / median(r)`（SPEC §5 阈值 ≤ 0.01）。

只读：不改任何资产。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT_DEFAULT = os.path.join(ROOT, "assets", "3d", "rig", "reports", "bodyshape_height_method.json")
SHAPE_BONES = ("pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r")

TARGETS = [
    ("Body_Female_Standard", "assets/3d/rig/bodies/Body_Female_Standard.blend"),
    ("Body_Male_Standard", "assets/3d/rig/bodies/Body_Male_Standard.blend"),
    ("TryOn_Female_Ranger", "assets/3d/blend/tryon/TryOn_Female_Ranger.blend"),
    ("TryOn_Male_Ranger", "assets/3d/blend/tryon/TryOn_Male_Ranger.blend"),
]

try:
    import bpy  # type: ignore
    import numpy as np  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    np = None  # type: ignore
    HAS_BPY = False


def world_coords(meshes):
    """每件网格的**世界空间**顶点（对象级缩放要靠 matrix_world 才看得出来）。"""
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in meshes:
        ev = o.evaluated_get(dg)
        m = ev.to_mesh()
        co = np.array([tuple(o.matrix_world @ v.co) for v in m.vertices])
        ev.to_mesh_clear()
        out.append(co)
    return out


def edge_index(meshes):
    return [np.array([tuple(e.vertices) for e in o.data.edges], dtype=np.int64) for o in meshes]


def stretch_stats(co_a, co_b, edges):
    """verifier vlib.py 的同口径：分位数离散度，对整体缩放不敏感。"""
    la, lb = [], []
    for a, b, e in zip(co_a, co_b, edges):
        if len(e) == 0:
            continue
        la.append(np.linalg.norm(a[e[:, 0]] - a[e[:, 1]], axis=1))
        lb.append(np.linalg.norm(b[e[:, 0]] - b[e[:, 1]], axis=1))
    la = np.concatenate(la)
    lb = np.concatenate(lb)
    m = la > 1e-9
    r = lb[m] / la[m]
    return {
        "n_edges": int(r.size),
        "mean": float(r.mean()),
        "p01": float(np.percentile(r, 1)),
        "p50": float(np.percentile(r, 50)),
        "p99": float(np.percentile(r, 99)),
        "std": float(r.std()),
        "dispersion_p01_p99": float(np.percentile(r, 99) - np.percentile(r, 1)),
        "dispersion_rel": float((np.percentile(r, 99) - np.percentile(r, 1)) / max(np.median(r), 1e-9)),
    }


def height_of(co_list):
    zs = np.concatenate([c[:, 2] for c in co_list if len(c)])
    return float(zs.max() - zs.min())


def reset(arm, meshes):
    # ⚠ `arm.scale` 也必须清！否则上一种方法（对象级缩放）会残留下来，
    # 下一种方法测出来的是**两个 scale 相乘**（踩过：M 行读到 1.08² = +16.64% 的假"双次应用"）。
    arm.scale = (1.0, 1.0, 1.0)
    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    for o in meshes:
        o.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def run_target(name, relpath, h):
    bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT, relpath))
    arm = next((o for o in bpy.data.objects if o.type == 'ARMATURE'
                and all(b in o.data.bones for b in SHAPE_BONES)), None)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH'
              and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)
              and o.name != "Icosphere"]
    inv = sorted((b.name, b.inherit_scale) for b in arm.data.bones)
    n_none = sum(1 for _, s in inv if s != 'FULL')
    parented = sum(1 for o in meshes if o.parent == arm)
    print(f"\n{'=' * 78}\n[{name}] {relpath}")
    print(f"  rig={arm.name}  网格 {len(meshes)} 件  顶点 {sum(len(o.data.vertices) for o in meshes)}")
    print(f"  inherit_scale 非 FULL 的骨：{n_none}/65  → {[b for b, s in inv if s != 'FULL']}")
    print(f"  网格里 parent==armature 的：{parented}/{len(meshes)}")

    reset(arm, meshes)
    base = world_coords(meshes)
    edges = edge_index(meshes)
    h0 = height_of(base)
    print(f"  基准身高 {h0:.4f} m")
    cases = {}

    def record(key, note):
        co = world_coords(meshes)
        hh = height_of(co)
        st = stretch_stats(base, co, edges)
        d = [np.linalg.norm(co[i] - base[i], axis=1).max() for i in range(len(co)) if len(co[i])]
        cases[key] = {
            "note": note,
            "height_m": round(hh, 6),
            "height_ratio": round(hh / h0, 8),
            "height_delta_pct": round((hh / h0 - 1) * 100, 4),
            "stretch_dispersion_rel": round(st["dispersion_rel"], 8),
            "stretch_std": round(st["std"], 8),
            "stretch_mean": round(st["mean"], 8),
            "n_edges": st["n_edges"],
            "max_vertex_disp_m": round(float(max(d)), 6),
            "passes_threshold_0.01": bool(st["dispersion_rel"] <= 0.01),
        }
        print(f"    {key:34s} 身高 {hh / h0:.6f}×  (+{(hh / h0 - 1) * 100:6.3f}%)  "
              f"离散度 {st['dispersion_rel']:.8f}  {'✅' if st['dispersion_rel'] <= 0.01 else '❌'}")

    # 方法 K：root 骨缩放（SPEC §3.4 的原写法，已被 F12 废弃）
    reset(arm, meshes)
    arm.pose.bones["root"].scale = (h, h, h)
    bpy.context.view_layer.update()
    record("K_root_bone_scale", "pose.bones['root'].scale —— 走骨架层级，受 inherit_scale 影响")

    # 方法 O：骨架对象世界等比缩放（SPEC §3.4 现行写法）
    reset(arm, meshes)
    arm.scale = (h, h, h)
    bpy.context.view_layer.update()
    record("O_armature_object_scale", "armature_object.scale —— 对象级仿射，与骨架层级无关")

    # 方法 M：网格对象各自缩放（"角色根节点"的等价物；证明与 F6 无关）
    reset(arm, meshes)
    for o in meshes:
        o.scale = (h, h, h)
    bpy.context.view_layer.update()
    record("M_mesh_objects_scale", "mesh_object.scale —— 同样绕开骨架层级")

    reset(arm, meshes)
    return {
        "target": name, "file": relpath, "rig": arm.name,
        "mesh_count": len(meshes), "vertex_count": int(sum(len(o.data.vertices) for o in meshes)),
        "inherit_scale_non_full_count": n_none,
        "inherit_scale_non_full_bones": [b for b, s in inv if s != 'FULL'],
        "meshes_parented_to_armature": parented,
        "base_height_m": round(h0, 6),
        "h": h,
        "methods": cases,
    }


def main():
    ap = argparse.ArgumentParser(
        prog="check_height_method.py",
        description="身高缩放法(root 骨 vs 对象级) × inherit_scale 规则的相容性实测",
        epilog="例：Blender -b --factory-startup --python tools/3d/bodyshape/check_height_method.py -- --h 1.08")
    ap.add_argument("--h", type=float, default=1.08, help="身高缩放系数（默认 1.08 = SPEC §3.4 上限）")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    if not HAS_BPY:
        if not argv or any(a in ("-h", "--help") for a in argv):
            ap.print_help()
            return 0
        ap.error("需要 bpy + numpy —— 请在 Blender headless 下运行")
    args = ap.parse_args(argv)

    t0 = time.time()
    print(f"# check_height_method.py  Blender {bpy.app.version_string}  h={args.h}")
    print("  主口径：dispersion_rel = (P99(r) − P01(r)) / median(r)，r = 边长比（verifier vlib.py 同口径）")
    print("  SPEC §5 阈值：≤ 0.01")
    rows = [run_target(n, p, args.h) for n, p in TARGETS]

    report = {
        "schema": "bodyshape-height-method",
        "question": "bodies/ 标准体保留 F6 的 inherit_scale='NONE'（18 根），会不会让标准体的身高缩放失真？",
        "metric": "dispersion_rel = (P99(r) − P01(r)) / median(r)，r = 世界空间边长比（与 verifier/vlib.py 同口径）",
        "threshold": 0.01,
        "h": args.h,
        "blender_version": bpy.app.version_string,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "targets": rows,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    if args.dry_run:
        print("\n[dry-run] 不写 JSON")
    else:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\n报告 → {os.path.relpath(args.out, ROOT)}")
    print(f"DONE  {report['elapsed_sec']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())