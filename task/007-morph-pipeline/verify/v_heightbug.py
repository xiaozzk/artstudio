#!/usr/bin/env python3
"""
v_heightbug.py —— verifier 发现的一个**设计级冲突**，独立复核：

  SPEC §3.4：身高用 `root` 的等比缩放 `scale=(h,h,h)`，h∈[0.92,1.08]（引 F7：0% 失真）
  SPEC §3.2：对 14 根体形骨 B 的**全部直接子骨**设 `inherit_scale='NONE'`（引 F6）

两条规则叠在同一副骨架上时：`root` 的子骨是 `pelvis`(FULL)，但 `pelvis` 的子骨
（`spine_01` / `thigh_l` / `thigh_r`）被设成了 **NONE** →
root 的缩放**传不到躯干与腿**，身高几乎不变，且薄薄一层骨盆被拉伸 → 失真爆表。

本脚本用三种配置实测同一动作（root.scale=1.08）：
  C1 现状（SPEC 两规则同时生效）
  C2 inherit_scale 全 FULL（= F7 的原始实验条件）
  C3 只把 14 根体形骨**自己**设 NONE、子骨保持 FULL（另一种可能的意图）
并逐区域报告位移/身高/拉伸比离散度。

只读，不写 .blend。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_heightbug.py -- \
      --out assets/3d/rig/reports/verify-heightbug.json
"""
import argparse
import json
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

RIG = "/Users/zhenkunzhu/Desktop/project/artstudio/assets/3d/rig"
SHAPE_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r"]


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def eval_co(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    c = vlib.evaluated_mesh(obj, dg)["co"]
    M = np.array(obj.matrix_world)
    return c @ M[:3, :3].T + M[:3, 3]


def region_masks(co):
    z = co[:, 2]
    return {
        "头颈 (z>1.55)": z > 1.55,
        "躯干 (0.95-1.55)": (z >= 0.95) & (z <= 1.55),
        "腿 (z<0.95)": z < 0.95,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-heightbug.json")
    a = ap.parse_args(argv_after_ddash())
    out = {"generated_by": "verifier/v_heightbug.py",
           "question": "SPEC §3.4 的身高缩放，在 §3.2 的 inherit_scale 规则生效时还成立吗？",
           "cases": []}
    t0 = time.perf_counter()
    for sex in ("Female", "Male"):
        bpy.ops.wm.open_mainfile(filepath=f"{RIG}/bodies/Body_{sex}_Standard.blend")
        body = bpy.data.objects[f"Body_{sex}"]
        arm = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"][0]
        bpy.context.view_layer.update()
        base = eval_co(body)
        H0 = float(base[:, 2].max() - base[:, 2].min())
        regs = region_masks(base)
        saved = {b.name: b.inherit_scale for b in arm.data.bones}
        rec = {"sex": sex, "base_height_m": H0,
               "inherit_none_actual": sorted(k for k, v in saved.items() if v != "FULL"),
               "configs": {}}
        print(f"\n### {sex}  base_height={H0:.5f} m  "
              f"NONE 骨数={len(rec['inherit_none_actual'])}")

        def run(tag, setter, h=1.08):
            for b in arm.data.bones:
                b.inherit_scale = saved[b.name]
            setter()
            pb = arm.pose.bones["root"]
            old = tuple(pb.scale)
            pb.scale = (h, h, h)
            bpy.context.view_layer.update()
            cur = eval_co(body)
            pb.scale = old
            for b in arm.data.bones:
                b.inherit_scale = saved[b.name]
            bpy.context.view_layer.update()
            H = float(cur[:, 2].max() - cur[:, 2].min())
            d = np.linalg.norm(cur - base, axis=1) * 100
            st = vlib.edge_stretch_stats(base, cur, edges=vlib.mesh_edges(body),
                                         sample=400000)
            row = {
                "height_m": H, "height_ratio": H / H0,
                "height_delta_pct": 100 * (H / H0 - 1),
                "max_disp_cm": float(d.max()), "mean_disp_cm": float(d.mean()),
                "moved_gt_1mm_frac": float((d > 0.1).mean()),
                "stretch_dispersion_rel": st["dispersion_rel"] if st else None,
                "stretch_std": st["std"] if st else None,
                "per_region_mean_disp_cm": {
                    k: round(float(d[m].mean()), 4) for k, m in regs.items()},
                "per_region_max_disp_cm": {
                    k: round(float(d[m].max()), 4) for k, m in regs.items()},
            }
            rec["configs"][tag] = row
            print(f"  {tag:<52} H={H:.4f} ({row['height_delta_pct']:+6.2f}%)  "
                  f"maxDisp={row['max_disp_cm']:6.2f}cm  "
                  f"拉伸离散={row['stretch_dispersion_rel']:.4f}  "
                  f"区域均值={row['per_region_mean_disp_cm']}")
            return row

        def c1():
            pass  # 现状

        def c2():
            for b in arm.data.bones:
                b.inherit_scale = "FULL"

        def c3():
            # 只把 14 根体形骨**自己**设 NONE（缩放不传给它们的子骨），
            # 其余保持 FULL —— 这样 root 的缩放能沿 pelvis→spine/thigh 传下去吗？
            for b in arm.data.bones:
                b.inherit_scale = "FULL"
            for nm in SHAPE_BONES:
                if nm in arm.data.bones:
                    arm.data.bones[nm].inherit_scale = "NONE"

        run("C1_spec_both_rules_asis", c1)
        run("C2_all_inherit_FULL", c2)
        run("C3_shape_bones_themselves_NONE", c3)
        # 额外：C1 下用 body 分档看骨盆区域是不是唯一被拉伸的
        out["cases"].append(rec)
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(a.out, out)
    print(f"\n[v_heightbug] wrote {a.out}")


if __name__ == "__main__":
    main()