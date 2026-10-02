#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task/005-generic-skeleton —— 骨骼/插槽/附件图三类命名统一（2026-10-02）

口径（用户拍板）：
  - 不用缩写：l→left、r→right、seg→级别后缀；
  - 侧别（left/right）放在类型 token 之前；
  - 骨骼名以 _bone 结尾，插槽名以 _slot 结尾（倒数第二位区分类型）；
  - 多级骨骼以 _1.._N 结尾（如 tail_bone_1..7、hair_back_drop_right_bone_1..3）。

做法（数据级，不改几何 / 不改图集像素 / 不改绘制顺序）：
  1. 校验映射完备性（34 骨 / 26 槽全覆盖、新名唯一、骨骼名与插槽名不相交）
  2. 改 JSON：bones[].name/parent、slots[].name/bone/attachment、
     constraints(name/bone)、skins 顶层槽 key + 内层附件 key + 槽默认 attachment
  3. 改 .atlas：区域名与附件名同步（bounds 不动，页 png 不动）
  4. 改 images_original/*.png 文件名与附件名同步
  5. 自检：全名集与图集区域双射 / 引用全有效 / 旧名零残留 / 槽序不变
  6. 输出紧凑 JSON + 报告

用法（工作区根运行）：
  python task/005-generic-skeleton/scripts/unify_names.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # 工作区根
PKG = ROOT / "task/005-generic-skeleton/output"
JSON_PATH = PKG / "Unit_Spine_EmpirePaladinSpe1Skin1.json"
ATLAS_PATH = PKG / "Unit_Spine_EmpirePaladinSpe1Skin1.atlas"
IMAGES_DIR = PKG / "images_original"
REPORT_PATH = ROOT / "tmp/005-unify/report.json"

# ---------------- 映射表 ----------------

BONES = {
    # 主干
    "root": "root_bone",
    "hip": "hip_bone",
    "upper_body": "upper_body_bone",
    "chest": "chest_bone",
    "head": "head_bone",
    "face": "face_bone",
    "lower_body": "lower_body_bone",
    # 腿
    "leg_r_thigh": "leg_thigh_right_bone",
    "leg_r_shin": "leg_shin_right_bone",
    "leg_l_thigh": "leg_thigh_left_bone",
    "leg_l_shin": "leg_shin_left_bone",
    # 臂
    "arm_l_upper": "arm_upper_left_bone",
    "arm_l_hand": "arm_hand_left_bone",
    "arm_r_upper": "arm_upper_right_bone",
    "arm_r_hand": "arm_hand_right_bone",
    # 武器 / 盾
    "weapon_grip": "weapon_grip_bone",
    "weapon_shaft": "weapon_shaft_bone",
    "shield": "shield_bone",
    # 后发下垂发束（3 级链 × 左右）
    "hair_back_drop_right_1": "hair_back_drop_right_bone_1",
    "hair_back_drop_right_2": "hair_back_drop_right_bone_2",
    "hair_back_drop_right_3": "hair_back_drop_right_bone_3",
    "hair_back_drop_left_1": "hair_back_drop_left_bone_1",
    "hair_back_drop_left_2": "hair_back_drop_left_bone_2",
    "hair_back_drop_left_3": "hair_back_drop_left_bone_3",
    # 下装
    "bottoms_wear": "bottoms_wear_bone",
    "skirt_flap_a": "skirt_flap_a_bone",
    "skirt_flap_b": "skirt_flap_b_bone",
    # 尾（7 级链）
    "tail_seg_1": "tail_bone_1",
    "tail_seg_2": "tail_bone_2",
    "tail_seg_3": "tail_bone_3",
    "tail_seg_4": "tail_bone_4",
    "tail_seg_5": "tail_bone_5",
    "tail_seg_6": "tail_bone_6",
    "tail_seg_7": "tail_bone_7",
}

SLOTS = {
    "hair_back": "hair_back_slot",
    "hair_front": "hair_front_slot",
    "hair_template_left": "hair_template_left_slot",
    "hair_template_right": "hair_template_right_slot",
    "ear_left": "ear_left_slot",
    "ear_right": "ear_right_slot",
    "ear_rings_left": "ear_rings_left_slot",
    "ear_rings_right": "ear_rings_right_slot",
    "horn": "horn_slot",
    "horn_left": "horn_left_slot",
    "horn_right": "horn_right_slot",
    "no": "face_slot",                      # 脸部三态槽（原 no/by/attack）
    "body": "body_slot",
    "skirt": "skirt_slot",
    "wb": "tail_slot",                      # wb=尾巴拼音
    "wq2": "weapon_shaft_slot",             # wq=武器拼音，空槽备用位
    "Lhand": "hand_left_slot",
    "Lhand2": "arm_upper_left_slot",        # 挂在左上臂骨
    "Rhand": "hand_right_slot",
    "Rhand2": "arm_upper_right_slot",       # 挂在右上臂骨
    "leg_r_thigh": "leg_thigh_right_slot",
    "leg_r_shin": "leg_shin_right_slot",
    "leg_l_thigh": "leg_thigh_left_slot",
    "leg_l_shin.png": "leg_shin_left_slot",  # 槽名混入 .png，一并清理
    "Rtui3": "leg_shin_left_slot_2",        # 左小腿空备用槽（同骨第二槽）
    "shield": "shield_slot",
}

# 附件名 = 图集区域名 = images_original 文件名（不含扩展名）
ATTACH = {
    "Lhand": "hand_left",
    "Lhand2": "arm_upper_left",
    "Rhand": "hand_right",
    "Rhand2": "arm_upper_right",
    "no": "face_open",          # 睁眼
    "by": "face_blink",         # 闭眼眨眼
    "attack": "face_attack",    # 攻击表情
    "leg_l_shin": "leg_shin_left",
    "leg_r_shin": "leg_shin_right",
    "leg_l_thigh": "leg_thigh_left",
    "leg_r_thigh": "leg_thigh_right",
    "wb": "tail",
}


def parse_atlas(text: str):
    """返回 (按出现顺序的 [行号, 区域名])，页名行跳过。"""
    regions = []
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if not s or ":" in s or line[:1] in (" ", "\t"):
            continue
        if s.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        regions.append((i, s))
    return regions


def main() -> int:
    problems: list[str] = []
    doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    atlas_text = ATLAS_PATH.read_text(encoding="utf-8")

    src_bones = [b["name"] for b in doc["bones"]]
    src_slots = [s["name"] for s in doc["slots"]]
    atlas_regions = [name for _, name in parse_atlas(atlas_text)]

    # 附件名全集 = 槽默认 attachment + 皮肤内层 key
    skin = doc["skins"][0]["attachments"]
    att_names: set[str] = set()
    for s in doc["slots"]:
        if "attachment" in s:
            att_names.add(s["attachment"])
    for slot_key, atts in skin.items():
        att_names.update(atts.keys())

    # ---- 完备性 ----
    miss_b = [n for n in src_bones if n not in BONES]
    miss_s = [n for n in src_slots if n not in SLOTS]
    extra_b = sorted(set(BONES) - set(src_bones))
    extra_s = sorted(set(SLOTS) - set(src_slots))
    extra_a = sorted(set(ATTACH) - att_names)   # ATTACH 是部分映射（缺省=保持原名）
    if miss_b:
        problems.append(f"映射缺骨骼: {miss_b}")
    if miss_s:
        problems.append(f"映射缺插槽: {miss_s}")
    if extra_b:
        problems.append(f"映射多出骨骼: {extra_b}")
    if extra_s:
        problems.append(f"映射多出插槽: {extra_s}")
    if extra_a:
        problems.append(f"映射多出附件: {extra_a}")
    # 附件新名唯一
    att_full = {a: ATTACH.get(a, a) for a in att_names}
    vals = list(att_full.values())
    dup = sorted({v for v in vals if vals.count(v) > 1})
    if dup:
        problems.append(f"附件新名重复: {dup}")
    for label, m in (("骨骼", BONES), ("插槽", SLOTS), ("附件", ATTACH)):
        vals = list(m.values())
        dup = sorted({v for v in vals if vals.count(v) > 1})
        if dup:
            problems.append(f"{label}新名重复: {dup}")
    collide = (set(BONES.values()) & set(SLOTS.values())
               | set(BONES.values()) & set(ATTACH.values())
               | set(SLOTS.values()) & set(ATTACH.values()))
    if collide:
        problems.append(f"三类新名互相冲突: {sorted(collide)}")
    if problems:
        for p in problems:
            print("   -", p)
        return 1

    # ---- 应用改名 ----
    for b in doc["bones"]:
        b["name"] = BONES[b["name"]]
        if "parent" in b:
            b["parent"] = BONES[b["parent"]]
    for s in doc["slots"]:
        s["name"] = SLOTS[s["name"]]
        s["bone"] = BONES[s["bone"]]
        if "attachment" in s:
            s["attachment"] = ATTACH.get(s["attachment"], s["attachment"])
    for c in doc.get("constraints", []):
        if "name" in c and c["name"] in BONES:
            c["name"] = BONES[c["name"]]
        if "bone" in c:
            c["bone"] = BONES[c["bone"]]
    new_skin = {}
    for slot_key, atts in skin.items():
        new_skin[SLOTS[slot_key]] = {ATTACH.get(k, k): v for k, v in atts.items()}
    doc["skins"][0]["attachments"] = new_skin

    # ---- 自检 ----
    valid_b = {b["name"] for b in doc["bones"]}
    valid_s = {s["name"] for s in doc["slots"]}
    new_att = [ATTACH.get(a, a) for a in sorted(att_names)]

    bad_parent = [b["name"] for b in doc["bones"]
                  if b.get("parent") and b["parent"] not in valid_b]
    bad_sb = [(s["name"], s["bone"]) for s in doc["slots"] if s["bone"] not in valid_b]
    bad_sa = [(s["name"], s["attachment"]) for s in doc["slots"]
              if "attachment" in s and s["attachment"] not in new_att]
    bad_sk = [k for k in doc["skins"][0]["attachments"] if k not in valid_s]
    bad_sk_att = [k for atts in doc["skins"][0]["attachments"].values()
                  for k in atts if k not in new_att]
    bad_cb = [c["name"] for c in doc.get("constraints", []) if c.get("bone") not in valid_b]
    for label, bad in (("parent", bad_parent), ("slot.bone", bad_sb),
                       ("slot.attachment", bad_sa), ("皮肤槽key", bad_sk),
                       ("皮肤附件key", bad_sk_att), ("constraint.bone", bad_cb)):
        if bad:
            problems.append(f"{label} 指向不存在/未改名项: {bad[:10]}")

    # 旧名残留（骨骼旧名做全文档精确匹配深扫；槽/附件旧名做结构化集合检查）
    residue = []
    def scan(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                scan(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                scan(v, f"{path}[{i}]")
        elif isinstance(node, str) and node in BONES:
            residue.append(f"{path}={node!r}")
    scan(doc)
    if residue:
        problems.append(f"旧骨名残留 {len(residue)} 处: {residue[:10]}")
    old_att_names = {a: ATTACH.get(a, a) for a in att_names}
    if sorted(new_att) != sorted(old_att_names.values()):
        problems.append("附件名集合与预期不一致")

    # 图集区域（过映射后）↔ 附件名 双射
    atlas_after = [ATTACH.get(n, n) for n in atlas_regions]
    if sorted(atlas_after) != sorted(set(new_att)):
        problems.append(f"图集区域与附件名不双射: atlas={sorted(atlas_after)} att={sorted(set(new_att))}")

    # 父链无环
    by_name = {b["name"]: b for b in doc["bones"]}
    for b in doc["bones"]:
        seen, n = set(), b["name"]
        while n is not None:
            if n in seen:
                problems.append(f"父链成环: {b['name']}")
                break
            seen.add(n)
            n = by_name[n].get("parent")

    if problems:
        print("[unify] 失败：")
        for p in problems:
            print("   -", p)
        return 1

    # 图片改名目标预检（写盘前拦截冲突）
    for f in sorted(IMAGES_DIR.glob("*.png")):
        if f.stem in ATTACH and f.with_name(ATTACH[f.stem] + ".png").exists():
            problems.append(f"目标图片已存在: {ATTACH[f.stem]}.png")
    if problems:
        print("[unify] 预检失败：")
        for p in problems:
            print("   -", p)
        return 1

    # ---- 写 JSON ----
    JSON_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- 写 atlas（仅替换区域名行）----
    lines = atlas_text.splitlines()
    for i, name in parse_atlas(atlas_text):
        lines[i] = ATTACH.get(name, name)
    ATLAS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- 改图片文件名 ----
    moved = []
    for f in sorted(IMAGES_DIR.glob("*.png")):
        if f.stem in ATTACH:
            target = f.with_name(ATTACH[f.stem] + ".png")
            if target.exists():
                problems.append(f"目标图片已存在: {target.name}")
                continue
            f.rename(target)
            moved.append((f.name, target.name))

    report = {
        "bones": len(doc["bones"]), "slots": len(doc["slots"]),
        "attachments": len(set(new_att)), "images_moved": moved,
        "atlas_regions": len(atlas_after),
        "draw_order_slots": [s["name"] for s in doc["slots"]],
        "ok": not problems, "problems": problems,
    }
    out = ROOT / "tmp/005-unify"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[unify] OK：{len(doc['bones'])} 骨 / {len(doc['slots'])} 槽 / "
          f"{len(set(new_att))} 附件已统一；图片改名 {len(moved)} 张；旧名残留 0")
    print(f"[report] {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
