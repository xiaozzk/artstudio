#!/usr/bin/env python3
"""按种族契约（`races/<race>/race.json`）校验一具身体的比例。

**为什么需要它**：头身比一旦定下就是**全族硬参数** —— 它决定头资产的高度（8 头 vs 7 头在 1.75 m 下
差 **3 cm**），头又是**可跨件复用的独立资产**。比例错了不会让任何脚本报错，只会让"看起来怪"，
而这正是最难发现的一类错。

**测头高用的规则**：「**眼睛位于头部高度的中点**」（经典画法规则）
→ `head_height = 2 × (颅顶z − 眼中心z)`。不依赖去找下颌，且可用下颌位置**反向交叉验证**。

用法（在工作区根执行）：
    Blender -b --factory-startup --python-exit-code 1 \
        --python tools/3d/skeleton/check_proportions.py -- \
        --race assets/3d/rig/races/humanoid/race.json \
        --body assets/3d/rig/bodies/Body_Female_Standard.blend

⚠ 跑 Blender 一律加 `--python-exit-code 1`（否则脚本抛异常仍返回 exit 0）。
"""
from __future__ import annotations

import json
import os
import sys

import bpy

FAILS: list[str] = []

# 硬判据：landmark 名 → 取骨点的方式
BONE_LANDMARKS = {
    "head_bone_base": "Head",
    "neck_01_base": "neck_01",
    "shoulder_clavicle": "clavicle_l",
    "spine_03": "spine_03",
    "hip_pelvis": "pelvis",
    "knee_calf": "calf_l",
    "ankle_foot": "foot_l",
}


def parse_args() -> dict:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    out = {"race": None, "body": None}
    i = 0
    while i < len(argv):
        if argv[i] in ("--race", "--body") and i + 1 < len(argv):
            out[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    return out


def main() -> None:
    a = parse_args()
    if not a["race"] or not a["body"]:
        sys.exit("[proportions] 需要 --race <race.json> --body <body.blend>")
    spec = json.load(open(a["race"], encoding="utf-8"))
    P = spec["proportions"]
    lm = P["landmarks_pct_of_height"]
    tol = P["tolerance_pct_of_height"]
    hc_target = P["head_count"]
    hc_tol = P["head_count_tolerance"]
    rest_h = spec["skeleton"]["rest_height_m"]

    bpy.ops.wm.open_mainfile(filepath=a["body"])
    meshes = {o.name: o for o in bpy.data.objects if o.type == "MESH" and o.name != "Icosphere"}
    body = next((o for n, o in sorted(meshes.items()) if n.startswith("Body_")), None)
    eyes = meshes.get("Eyes")
    if not body:
        sys.exit(f"[proportions] 找不到主身体网格（名字以 `Body_` 开头的）：{list(meshes)}")
    if not eyes:
        sys.exit(f"[proportions] 找不到 `Eyes` 网格（头身比需要它）：{list(meshes)}")

    bz = [(body.matrix_world @ v.co).z for v in body.data.vertices]
    H = max(bz) - min(bz)
    crown = max(bz)
    ez = [(eyes.matrix_world @ v.co).z for v in eyes.data.vertices]
    eye_c = (max(ez) + min(ez)) / 2
    head_h = 2 * (crown - eye_c)
    hc = H / head_h
    chin = crown - head_h

    print(f"\n[proportions] {os.path.basename(a['body'])}   race={spec['race']}")
    print(f"  身高 H = {H:.4f} m（契约 rest 参考 {rest_h} m）")
    print(f"  颅顶 {crown:.4f} / 眼中心 {eye_c:.4f} → 头高 {head_h*100:.2f} cm → 下颌 {chin:.4f}（{chin/H*100:.1f}%H）")
    ok_hc = abs(hc - hc_target) <= hc_tol
    print(f"  头身比 = **{hc:.2f} 头**（目标 {hc_target} ± {hc_tol}）  {'✅' if ok_hc else '❌'}")
    if not ok_hc:
        FAILS.append(f"头身比 {hc:.2f} ∉ [{hc_target-hc_tol}, {hc_target+hc_tol}]")

    bones = {b.name: b for b in next(o for o in bpy.data.objects if o.type == "ARMATURE").data.bones}
    print(f"\n  {'标志点':<20}{'目标%':>8}{'实测%':>8}{'偏差':>8}")
    for key, bone in BONE_LANDMARKS.items():
        if key not in lm:
            continue
        if bone not in bones:
            FAILS.append(f"缺骨 {bone}（判据 {key} 无法验）")
            print(f"  {key:<20}{lm[key]:>8.1f}{'—':>8}   ❌ 缺骨 {bone}")
            continue
        got = bones[bone].head_local.z / H * 100
        d = got - lm[key]
        ok = abs(d) <= tol
        if not ok:
            FAILS.append(f"{key}({bone}) = {got:.1f}%H，目标 {lm[key]:.1f}%H，偏差 {d:+.1f}pp > {tol}")
        print(f"  {key:<20}{lm[key]:>8.1f}{got:>8.1f}{d:>+8.1f}   {'✅' if ok else '❌'}")

    # 派生检查：头高应与 rest_height / head_count 一致
    derived = rest_h / hc_target * 100
    print(f"\n  契约推出的头高 = rest_height/head_count = {rest_h}/{hc_target} = {derived:.2f} cm")
    print(f"  本具身体实测头高 = {head_h*100:.2f} cm（差 {abs(head_h*100-derived):.2f} cm）")

    if FAILS:
        print(f"\n[proportions] ❌ {len(FAILS)} 项不达标：")
        for f in FAILS:
            print("   ·", f)
        sys.exit(1)
    print("\n[proportions] ✅ 全部达标")


if __name__ == "__main__":
    main()