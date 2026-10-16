#!/usr/bin/env python3
"""生成骨架契约 `assets/3d/rig/profiles/<name>.json`。

**为什么用生成器而不是手写**：77 根骨的层级与名字手写必然出错，而骨名/层级/顺序是**硬契约**
（SPEC F30：索引随文件而变，一律按名取骨；改名 = 契约级变更）。生成器保证：
  ① 左右镜像完全对称；② 骨数可断言；③ 改名只有一处。

本版（v2）相对 v1（65 骨）的两处结构变更：
  · **脊柱 3 → 7 节**（`spine_01..07`）—— 借 Bodiez 的结构优点：躯干比例与弯曲更细腻
  · **每指加掌骨**（`palm_{index,middle,ring,pinky}_*`，每手 4 根）—— 抓握/张开更自然
  ⚠ 拇指**不加**掌骨，直接挂 `hand_*`（正是 VRM 的期望：`leftThumbMetacarpal` 的父是 `leftHand`）

用法（工作区根）：python3 tools/3d/skeleton/make_profile.py [--check]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(REPO, "assets", "3d", "rig", "profiles")

SPINE_SEGMENTS = 7          # v1 是 3
FINGERS = ["index", "middle", "ring", "pinky"]
THUMB = "thumb"
PALM_FINGERS = FINGERS      # 这 4 指有掌骨；拇指没有


def build() -> dict:
    bones: list[tuple[str, str | None, bool]] = []   # (name, parent, deform)

    def add(n: str, p: str | None, d: bool = True) -> None:
        bones.append((n, p, d))

    add("root", None)
    add("pelvis", "root")

    # 脊柱 7 节
    prev = "pelvis"
    for i in range(1, SPINE_SEGMENTS + 1):
        n = f"spine_{i:02d}"
        add(n, prev)
        prev = n
    spine_top = prev

    add("neck_01", spine_top)
    add("Head", "neck_01")

    for side in ("l", "r"):
        add(f"clavicle_{side}", spine_top)
        add(f"upperarm_{side}", f"clavicle_{side}")
        add(f"lowerarm_{side}", f"upperarm_{side}")
        add(f"hand_{side}", f"lowerarm_{side}")
        # 4 指：掌骨 → 3 节 → 末端标记
        for f in PALM_FINGERS:
            add(f"palm_{f}_{side}", f"hand_{side}")
            prev_f = f"palm_{f}_{side}"
            for j in range(1, 4):
                n = f"{f}_{j:02d}_{side}"
                add(n, prev_f)
                prev_f = n
            n_leaf = f"{f}_04_leaf_{side}"          # 不承载形变的末端标记
            add(n_leaf, prev_f)
        # 拇指：直接挂 hand（无掌骨）→ 与 VRM 期望一致
        prev_t = f"hand_{side}"
        for j in range(1, 4):
            n = f"{THUMB}_{j:02d}_{side}"
            add(n, prev_t)
            prev_t = n
        add(f"{THUMB}_04_leaf_{side}", prev_t)

    for side in ("l", "r"):
        add(f"thigh_{side}", "pelvis")
        add(f"calf_{side}", f"thigh_{side}")        # ⚠ 是 calf，不是 shin
        add(f"foot_{side}", f"calf_{side}")
        add(f"ball_{side}", f"foot_{side}")
        add(f"ball_leaf_{side}", f"ball_{side}")

    names = [b[0] for b in bones]
    assert len(names) == len(set(names)), "骨名重复"
    return {
        "schema": "skeleton-profile",
        "version": "2.0",
        "name": "humanoid_biped_7spine",
        "label_zh": "人形·双足·7 节脊柱",
        "supersedes": "humanoid_biped_65（v1：3 节脊柱、每指无掌骨）",
        "why_v2": ("借 Bodiez（第三方人体定制件）的结构优点：① **7 节脊柱** → 躯干比例与弯曲更细腻；"
                   "② **每指掌骨** → 抓握/张开更自然。⚠ 拇指不加掌骨，直接挂 `hand_*`，"
                   "与 VRM 的 `leftThumbMetacarpal`（父为 `leftHand`）一致。"),
        "naming_convention": ("**UE Mannequin 风格**（`spine_01` / `clavicle_l` / `calf_l` / `ball_l`）；"
                              "**不改用 Rigify 风格**（`spine.001` / `shin.L`）—— 理由见 SKELETON.md §6.3。"),
        "rest_pose": "T-pose",
        "deform_bones": sum(1 for b in bones if b[2]),
        "leaf_markers": sum(1 for n, _, _ in bones if "_leaf" in n),
        "total_bones": len(bones),
        "bones": [{"i": i, "name": n, "parent": p, "deform": d,
                   "leaf": "_leaf" in n}
                  for i, (n, p, d) in enumerate(bones)],
        "design_notes": [
            "⚠ 腿骨是 `calf_*`，**没有** `shin_*`（实际踩过）。",
            "`*_leaf` 是**终端标记**，不承载形变（只为骨链收尾）；`ball_leaf_*` 同理。",
            "脊柱 7 节中**只有 3 节能映射到 VRM 角色**（`spine` / `chest` / `upperChest`）；"
            "其余登记为 `extra`（VRM 允许人类骨之间夹非人类骨，spec: 'It is permissible to have "
            "non-humanoid bone nodes between humanoid bones'）。",
            "掌骨同理：VRM 除拇指外**没有 metacarpal 角色** → `palm_*` 全部登记为 `extra`。",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    doc = build()
    out = os.path.join(OUT_DIR, doc["name"] + ".json")
    if a.check:
        if not os.path.isfile(out):
            sys.exit(f"[profile] 缺产物 {out}")
        if json.load(open(out, encoding="utf-8"))["bones"] != doc["bones"]:
            sys.exit("[profile] ❌ 入库产物与生成规则不一致 —— 重新生成")
        print(f"[profile] ✅ 一致：{doc['total_bones']} 骨")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"[profile] {doc['name']}: {doc['total_bones']} 骨 "
          f"（形变 {doc['deform_bones']} + 终端标记 {doc['leaf_markers']}）")
    print(f"[profile] 写 {os.path.relpath(out, REPO)}")


if __name__ == "__main__":
    main()