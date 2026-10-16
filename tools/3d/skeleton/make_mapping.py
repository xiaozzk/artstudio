#!/usr/bin/env python3
"""生成本仓库骨架 → VRM 1.0 角色词表 的映射表（`assets/3d/rig/skeleton_mapping.json`）。

**骨表来源 = 我们自己的契约**（`profiles/humanoid_biped_7spine.json`），**不再依赖第三方 glTF**
（第三方件只是参考，不该成为契约的上游）。

**为什么需要它**：VRM 角色词表只覆盖 52 个角色名，覆盖不了生产骨架的全部
（没有 `root`、没有 IK/twist 骨、没有叶子标记、7 节脊柱只映射 3 节、掌骨没有对应角色）。
所以映射必须**显式声明"哪些是额外骨"**，否则会留下静默的孤儿骨 —— 而"孤儿"正是最难发现的错。

本脚本的硬约束（自检，不通过就报错退出）：
  ① 每根骨**要么**映射到 VRM 角色，**要么**被显式登记为额外骨 —— 不允许两头都不占；
  ② 不出现重复的 VRM 角色（一个角色只能被一根骨扮演）；
  ③ ⭐ **覆盖数 + 额外数 == 骨架总骨数**，且**各自的期望值也要断言**。
     ⚠ ③ 的后半句是**补出来的**：最初没有"期望规模与构成"时，**删掉 12 根叶子骨照样通过**（53 = 52 + 1）
     → 门禁会静默接受另一副骨架。这正是"它在什么退化输入下也会通过？"要拦的东西。

用法（在工作区根执行）：
    python3 tools/3d/skeleton/make_mapping.py            # 生成 + 自检
    python3 tools/3d/skeleton/make_mapping.py --check     # 只校验已入库的产物是否与规则一致
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROFILE = os.path.join(REPO, "assets", "3d", "rig", "profiles", "humanoid_biped_7spine.json")
OUT = os.path.join(REPO, "assets", "3d", "rig", "skeleton_mapping.json")

# ── 规则 1：躯干直映 ────────────────────────────────────────────────────────
# ⚠ 脊柱有 7 节，而 VRM 只有 3 个角色（spine / chest / upperChest）
#   → 取【链上首、中、末】三节映射，其余登记为额外骨。
#   VRM spec 明确允许："It is permissible to have non-humanoid bone nodes between humanoid bones."
DIRECT = {
    "pelvis": "hips",
    "spine_01": "spine",
    "spine_04": "chest",
    "spine_07": "upperChest",
    "neck_01": "neck",
    "Head": "head",
}
SPINE_EXTRA = {"spine_02", "spine_03", "spine_05", "spine_06"}

# ── 规则 2：左右镜像的骨干（`{key}_{l|r}` → `{side}{Role}`）──────────────────
#    注意 `calf` → VRM 叫 `LowerLeg`；`ball` → VRM 叫 `Toes`
LIMB = {
    "clavicle": "Shoulder",
    "upperarm": "UpperArm",
    "lowerarm": "LowerArm",
    "hand": "Hand",
    "thigh": "UpperLeg",
    "calf": "LowerLeg",
    "foot": "Foot",
    "ball": "Toes",
}
# ── 规则 3：掌骨 —— VRM 除拇指外**没有** metacarpal 角色 → 全部额外骨 ─────────
PALM_PREFIX = "palm_"

# ── 规则 4：手指（`{finger}_{01|02|03}_{l|r}` → 三段名）──────────────────────
#    拇指在 VRM 里是 Metacarpal→Proximal→Distal；其余四指是 Proximal→Intermediate→Distal
FINGERS = {
    "thumb": ["ThumbMetacarpal", "ThumbProximal", "ThumbDistal"],
    "index": ["IndexProximal", "IndexIntermediate", "IndexDistal"],
    "middle": ["MiddleProximal", "MiddleIntermediate", "MiddleDistal"],
    "ring": ["RingProximal", "RingIntermediate", "RingDistal"],
    "pinky": ["LittleProximal", "LittleIntermediate", "LittleDistal"],  # pinky → Little
}
SIDES = {"l": "left", "r": "right"}

EXTRA_KIND = {"root": "root"}
# 终端标记骨：形如 `index_04_leaf_l` / `ball_leaf_l`
# ⚠ 注意 `_leaf` **后面还有左右后缀**，所以必须用 "包含" 判定，不能用 endswith
LEAF_MARK = "_leaf"

# VRM 1.0 必需角色
VRM_REQUIRED = {
    "hips", "spine", "head",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
}

# ── 规则 5：期望的规模与构成（**必须有**，见文件头 ③）────────────────────────
EXPECTED_TOTAL = 77
EXPECTED_MAPPED = 52
EXPECTED_KINDS = {"root": 1, "spine_extra": 4, "palm": 8, "leaf_marker": 12}


def load_bones(path: str) -> list[str]:
    if not os.path.isfile(path):
        sys.exit(f"[mapping] 找不到骨架契约：{path}\n"
                 f"          先用 tools/3d/skeleton/make_profile.py 生成。")
    return [b["name"] for b in json.load(open(path, encoding="utf-8"))["bones"]]


def role_of(name: str) -> tuple[str | None, str | None]:
    """返回 (vrm_role, kind)；两者恰有一个非空。"""
    if name in DIRECT:
        return DIRECT[name], None
    if name in SPINE_EXTRA:
        return None, "spine_extra"
    if name in EXTRA_KIND:
        return None, EXTRA_KIND[name]
    if name.startswith(PALM_PREFIX):
        return None, "palm"                     # VRM 无（非拇指）metacarpal 角色
    if LEAF_MARK in name:
        return None, "leaf_marker"              # 终端标记：只为骨链收尾，不承载形变
    for finger, segs in FINGERS.items():
        for idx, seg in enumerate(segs, start=1):
            for s, side in SIDES.items():
                if name == f"{finger}_{idx:02d}_{s}":
                    return f"{side}{seg}", None
    for base, role in LIMB.items():
        for s, side in SIDES.items():
            if name == f"{base}_{s}":
                return f"{side}{role}", None
    return None, None


def build(bones: list[str]) -> dict:
    rows, seen, unmapped = [], {}, []
    kinds: dict[str, int] = {}
    for b in bones:
        role, kind = role_of(b)
        if role and kind:
            sys.exit(f"[mapping] 规则冲突：{b} 同时命中角色与额外骨")
        if not role and not kind:
            unmapped.append(b)
            continue
        if role:
            if role in seen:
                sys.exit(f"[mapping] 角色重复：{role} 被 {seen[role]} 与 {b} 同时扮演")
            seen[role] = b
        else:
            kinds[kind] = kinds.get(kind, 0) + 1
        rows.append({"bone": b, "vrm_role": role, "kind": kind,
                     "vrm_required": (role in VRM_REQUIRED) if role else None})
    if unmapped:
        sys.exit(f"[mapping] 以下骨既未映射到 VRM 角色、也未登记为额外骨（不许留孤儿）：{unmapped}")

    # ── 规模与构成断言（防"少了几根骨也照样通过"）──
    if len(bones) != EXPECTED_TOTAL:
        sys.exit(f"[mapping] ❌ 骨数 {len(bones)} ≠ 期望 {EXPECTED_TOTAL}"
                 f"（换骨架必须显式改期望值，别让门禁静默接受另一副骨架）")
    if len(seen) != EXPECTED_MAPPED:
        sys.exit(f"[mapping] ❌ 映射到角色的骨数 {len(seen)} ≠ 期望 {EXPECTED_MAPPED}")
    if kinds != EXPECTED_KINDS:
        sys.exit(f"[mapping] ❌ 额外骨构成 {kinds} ≠ 期望 {EXPECTED_KINDS}")
    if not VRM_REQUIRED.issubset(seen):
        sys.exit(f"[mapping] ❌ VRM 必需角色未覆盖：{sorted(VRM_REQUIRED - set(seen))}")

    return {
        "schema": "skeleton-mapping",
        "version": "2.0",
        "skeleton": "humanoid_biped_7spine",
        "profile": "profiles/humanoid_biped_7spine.json",
        "total_bones": len(bones),
        "vrm_spec": "VRMC_vrm-1.0/humanoid.md（VRM 1.0）",
        "basis": ("VRM 角色词表定为**语义层标准**；本仓库**骨名保持 UE Mannequin 风格**、不改名 ——"
                  "理由见 SKELETON.md §6.3。"),
        "consumer_note": ("Godot 4.6 的 `SkeletonProfileHumanoid` 用的是**同一套角色词表**"
                          "（56 骨，骨名即 VRM 角色名），故本表可同时喂给："
                          "Godot `RetargetModifier3D` / VRM `humanBones` / Unity Humanoid 映射 / Mixamo 对照。"),
        "mapping_notes": [
            "脊柱 7 节 → 只映射链上**首、中、末**三节（`spine_01→spine` / `spine_04→chest` / `spine_07→upperChest`），"
            "其余 4 节登记为 `spine_extra`。VRM spec 明确允许在人类骨之间夹非人类骨。",
            "`palm_*`（每手 4 根掌骨）→ 全部 `palm` 额外骨：VRM 除**拇指**外没有 metacarpal 角色。",
            "拇指**不加掌骨**，直接挂 `hand_*` → 与 VRM 的 `leftThumbMetacarpal`（父为 `leftHand`）一致。",
            "⚠ Godot 4.6 把 `LeftShoulder`/`RightShoulder` 标为 `required=true`，而 VRM 里是**可选** → **Godot 略严于 VRM**。",
        ],
        "counts": {"mapped_to_vrm_role": len(seen), "extra": len(rows) - len(seen),
                   "vrm_roles_total_in_spec": 56, "by_kind": kinds},
        "bones": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验已入库产物与规则是否一致")
    ap.add_argument("--bones", nargs="*", help="显式指定骨名清单（默认读 profile）")
    a = ap.parse_args()

    bones = a.bones or load_bones(PROFILE)
    doc = build(bones)

    if a.check:
        if not os.path.isfile(OUT):
            sys.exit(f"[mapping] 缺少产物：{OUT}")
        if json.load(open(OUT, encoding="utf-8"))["bones"] != doc["bones"]:
            sys.exit("[mapping] ❌ 入库产物与规则不一致（骨名变了或规则改了）—— 重新生成")
        print(f"[mapping] ✅ 产物与规则一致：{doc['counts']['mapped_to_vrm_role']} 映射 + "
              f"{doc['counts']['extra']} 额外 = {doc['total_bones']} 骨")
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")

    c = doc["counts"]
    print(f"[mapping] 骨数 {doc['total_bones']} = 映射 {c['mapped_to_vrm_role']} + 额外 {c['extra']}")
    print(f"[mapping] 写 {os.path.relpath(OUT, REPO)}")
    for k, v in sorted(c["by_kind"].items()):
        print(f"  额外骨 · {k}: {v}")
    req = [r["bone"] for r in doc["bones"] if r["vrm_required"]]
    print(f"  VRM 必需角色已覆盖 {len(req)}/15：{req}")


if __name__ == "__main__":
    main()