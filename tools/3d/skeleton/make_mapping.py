#!/usr/bin/env python3
"""生成本仓库 65 骨 → VRM 1.0 角色词表 的映射表（`assets/3d/rig/skeleton_mapping.json`）。

**为什么需要它**：VRM 角色词表只覆盖 52 个角色名，覆盖不了生产骨架的全部
（没有 `root`、没有 IK/twist 骨、没有叶子标记）。所以映射必须**显式声明"哪些是额外骨"**，
否则会留下静默的孤儿骨 —— 而"孤儿"正是最难发现的错。

本脚本的硬约束（自检，不通过就报错退出）：
  ① 每根骨**要么**映射到 VRM 角色，**要么**被显式登记为额外骨（`kind` 非 null）—— 不允许两头都不占；
  ② 不出现重复的 VRM 角色（一个角色只能被一根骨扮演）；
  ③ 覆盖数 + 额外数 == 骨架总骨数。

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
SRC_GLTF = os.path.join(
    REPO, "download", "ubc", "Universal Base Characters[Standard]",
    "Base Characters", "Godot - UE", "Superhero_Female_FullBody.gltf",
)
OUT = os.path.join(REPO, "assets", "3d", "rig", "skeleton_mapping.json")

# ── 规则 1：单骨直映（VRM 1.0 角色名，注意大小写按 VRM spec 原样）────────────
DIRECT = {
    "pelvis": "hips",
    "spine_01": "spine",
    "spine_02": "chest",
    "spine_03": "upperChest",
    "neck_01": "neck",
    "Head": "head",
}
# ── 规则 2：左右镜像的骨干（`{key}_{l|r}` → `{side}{Role}`）──────────────────
#    注意 `pinky` → VRM 叫 `Little`；`ball` → VRM 叫 `Toes`
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
# ── 规则 3：手指（`{finger}_{01|02|03}_{l|r}` → 三段名）──────────────────────
#    拇指在 VRM 里是 Metacarpal→Proximal→Distal；其余四指是 Proximal→Intermediate→Distal
FINGERS = {
    "thumb": ["ThumbMetacarpal", "ThumbProximal", "ThumbDistal"],
    "index": ["IndexProximal", "IndexIntermediate", "IndexDistal"],
    "middle": ["MiddleProximal", "MiddleIntermediate", "MiddleDistal"],
    "ring": ["RingProximal", "RingIntermediate", "RingDistal"],
    "pinky": ["LittleProximal", "LittleIntermediate", "LittleDistal"],  # pinky → Little
}
SIDES = {"l": "left", "r": "right"}

# ── 规则 4：显式额外骨（VRM 覆盖不到的）────────────────────────────────────
#    `root`：VRM spec 明说 root "not a humanoid bone, origin"
#    `*_leaf`：终端标记，只为骨链收尾，不承载形变（源 glTF 里就叫这个名）
EXTRA_KIND = {
    "root": "root",
}
# 终端标记骨：源文件里形如 `index_04_leaf_l` / `ball_leaf_l`
# ⚠ 注意 `_leaf` **后面还有左右后缀**，所以必须用 "包含" 判定，不能用 endswith
LEAF_MARK = "_leaf"

# VRM 1.0 必需角色（spec 表格里 Required=Required 的那些）
VRM_REQUIRED = {
    "hips", "spine", "head",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
}

# ── 规则 5：期望的规模与构成（**必须有**）──────────────────────────────────
#   没有这一条时，删掉 12 根 leaf 骨仍会通过（53 = 52 + 1）——
#   门禁会静默接受"另一副骨架"。这正是"它在什么退化输入下也会通过？"要拦的东西。
EXPECTED_TOTAL = 65
EXPECTED_KINDS = {"root": 1, "leaf_marker": 12}
EXPECTED_MAPPED = 52


def load_bones(path: str) -> list[str]:
    if not os.path.isfile(path):
        sys.exit(f"[mapping] 找不到骨架源：{path}\n"
                 f"          它是本机 download/ 解压树里的源 glTF（不入库）。\n"
                 f"          没有它时请用 --bones 指定骨名清单。")
    d = json.load(open(path, encoding="utf-8"))
    nodes = [n.get("name", "") for n in d["nodes"]]
    joints = d["skins"][0]["joints"]
    return [nodes[i] for i in joints]


def role_of(name: str) -> tuple[str | None, str | None]:
    """返回 (vrm_role, kind)；两者恰有一个非空。"""
    if name in DIRECT:
        return DIRECT[name], None
    if name in EXTRA_KIND:
        return None, EXTRA_KIND[name]
    if LEAF_MARK in name:
        return None, "leaf_marker"          # 终端标记：只为骨链收尾，不承载形变
    # 手指
    for finger, segs in FINGERS.items():
        for idx, seg in enumerate(segs, start=1):
            for s, side in SIDES.items():
                if name == f"{finger}_{idx:02d}_{s}":
                    return f"{side}{seg}", None
    # 骨干
    for base, role in LIMB.items():
        for s, side in SIDES.items():
            if name == f"{base}_{s}":
                return f"{side}{role}", None
    return None, None                        # 两头都不占 → 下面会报错


def build(bones: list[str]) -> dict:
    rows, seen, unmapped = [], {}, []
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
        rows.append({
            "bone": b,
            "vrm_role": role,
            "kind": kind,
            "vrm_required": (role in VRM_REQUIRED) if role else None,
        })
    if unmapped:
        sys.exit(f"[mapping] 以下骨既未映射到 VRM 角色、也未登记为额外骨（不许留孤儿）：{unmapped}")

    # 规模与构成断言（防"少了几根骨也照样通过"）
    kinds: dict[str, int] = {}
    for r in rows:
        if r["kind"]:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    if len(bones) != EXPECTED_TOTAL:
        sys.exit(f"[mapping] ❌ 骨数 {len(bones)} ≠ 期望 {EXPECTED_TOTAL}"
                 f"（本表只对 `humanoid_biped_65` 有效；换骨架必须显式改期望值）")
    if len(seen) != EXPECTED_MAPPED:
        sys.exit(f"[mapping] ❌ 映射到角色的骨数 {len(seen)} ≠ 期望 {EXPECTED_MAPPED}")
    if kinds != EXPECTED_KINDS:
        sys.exit(f"[mapping] ❌ 额外骨构成 {kinds} ≠ 期望 {EXPECTED_KINDS}")
    if not VRM_REQUIRED.issubset(seen):
        sys.exit(f"[mapping] ❌ VRM 必需角色未覆盖：{sorted(VRM_REQUIRED - set(seen))}")

    return {
        "schema": "skeleton-mapping",
        "version": "1.0",
        "skeleton": "humanoid_biped_65",
        "total_bones": len(bones),
        "vrm_spec": "VRMC_vrm-1.0/humanoid.md（VRM 1.0）",
        "basis": ("VRM 角色词表定为**语义层标准**；本仓库**骨名保持现状**（UE Mannequin 风格），"
                  "不改名 —— 理由见 assets/3d/rig/SKELETON.md §5。"),
        "consumer_note": ("Godot 4.6 的 `SkeletonProfileHumanoid` 用的是**同一套角色词表**"
                          "（56 骨，骨名即 VRM 角色名），故本表可同时喂给："
                          "Godot `RetargetModifier3D` / VRM `humanBones` / Unity Humanoid 映射 / Mixamo 对照。"),
        "counts": {
            "mapped_to_vrm_role": len(seen),
            "extra": len(rows) - len(seen),
            "vrm_roles_total_in_spec": 56,
        },
        "bones": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验已入库产物与规则是否一致")
    ap.add_argument("--bones", nargs="*", help="显式指定骨名清单（默认从源 glTF 读）")
    a = ap.parse_args()

    bones = a.bones or load_bones(SRC_GLTF)
    doc = build(bones)

    if a.check:
        if not os.path.isfile(OUT):
            sys.exit(f"[mapping] 缺少产物：{OUT}")
        old = json.load(open(OUT, encoding="utf-8"))
        if old.get("bones") != doc["bones"]:
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
    by_kind: dict[str, list[str]] = {}
    for r in doc["bones"]:
        if r["kind"]:
            by_kind.setdefault(r["kind"], []).append(r["bone"])
    for k, v in sorted(by_kind.items()):
        print(f"  额外骨 · {k}: {len(v)} 根 {v[:4]}{' …' if len(v) > 4 else ''}")
    req = [r["bone"] for r in doc["bones"] if r["vrm_required"]]
    print(f"  VRM 必需角色已覆盖 {len(req)}/15：{req}")


if __name__ == "__main__":
    main()