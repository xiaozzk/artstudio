#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task/005-generic-skeleton —— Spine 骨骼批量重命名（英文语义名）

做法（数据级，不改几何，不改渲染）：
  1. 读映射表 JSON（renames: 旧名→{new, role, evidence,…}）
  2. 校验：映射覆盖全部骨骼 / 新名唯一 / 新名不与未改名冲突
  3. 改写引用点：bones[].name、bones[].parent、slots[].bone、animations[*]["bones"] 的键
     （皮肤 mesh 为刚性绑定、无 bones/weights 数组；本库零 constraints，均无名字引用）
  4. 自检：
     A2 完整性 —— 全文档深度扫描不得残留任何旧骨名（dict 键或独立字符串值，精确匹配）
     A2 引用 —— parent/slot.bone/动画骨轨道 key 全部指向新名；父链无环
     A3 等价 —— 逐动画的骨骼轨道集合在改名前后一一对应，轨道/关键帧数量不变
  5. 输出紧凑 JSON + 报告

用法：
  python3 rename_bones.py <骨架json> <rename-map.json> <输出.json> [--report 报告.json]
"""
import json
import sys
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compact(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def deep_scan(doc, changed_old: set, _path="$"):
    """只扫字符串**值**（dict 键是字段名/轨道容器，单独由显式检查覆盖），
    报告仍等于「已被改名」旧骨名的取值位置。"""
    hits = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            hits += deep_scan(v, changed_old, f"{_path}.{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            hits += deep_scan(v, changed_old, f"{_path}[{i}]")
    elif isinstance(doc, str):
        if doc in changed_old:
            hits.append(f"{_path} = {doc!r}")
    return hits


def main(argv) -> int:
    report_path = None
    rest = argv[1:]
    if "--report" in rest:
        i = rest.index("--report")
        report_path = Path(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    if len(rest) != 3:
        print(__doc__)
        return 2
    src_path, map_path, out_path = map(Path, rest)

    doc = load(str(src_path))
    rmap = load(str(map_path))["renames"]
    old2new = {old: spec["new"] for old, spec in rmap.items()}
    old_names = set(old2new)
    new_names = list(old2new.values())

    bones = doc["bones"]
    src_order = [b["name"] for b in bones]
    problems: list[str] = []

    # ---- 映射完备性 ----
    missing = [n for n in src_order if n not in old2new]
    extra = [n for n in old_names if n not in set(src_order)]
    dup_new = sorted({n for n in new_names if new_names.count(n) > 1})
    if missing:
        problems.append(f"映射缺骨骼: {missing}")
    if extra:
        problems.append(f"映射含未知骨骼: {extra}")
    if dup_new:
        problems.append(f"新名重复: {dup_new}")
    kept = {n for n in src_order if n not in old2new}
    collide = kept & set(new_names)
    if collide:
        problems.append(f"新名与未改名骨骼冲突: {collide}")
    if problems:
        print("[rename] 映射校验失败：")
        for p in problems:
            print("   -", p)
        return 1

    # ---- 改名前快照（供 A3 等价校验）----
    def tracks(a):
        tracks_bones = a.get("bones", {})
        return {bn: sum(len(v.get(k, [])) for k in ("rotate", "translate", "scale", "shear"))
                for bn, v in tracks_bones.items()}

    anim_tracks_before = {an: tracks(a) for an, a in doc.get("animations", {}).items()}

    # ---- 改名 ----
    for b in bones:
        b["name"] = old2new.get(b["name"], b["name"])
        if "parent" in b:
            b["parent"] = old2new.get(b["parent"], b["parent"])
    for s in doc.get("slots", []):
        if "bone" in s:
            s["bone"] = old2new.get(s["bone"], s["bone"])
    for an, a in doc.get("animations", {}).items():
        if "bones" in a:
            a["bones"] = {old2new.get(k, k): v for k, v in a["bones"].items()}

    # ---- A2 完整性：残留旧名（只计真正被改名的）/ parent 引用 / 无环 ----
    valid = {b["name"] for b in bones}
    changed_old = {o for o, n in old2new.items() if o != n}
    residue = deep_scan(doc, changed_old)
    if residue:
        problems.append(f"残留旧骨名 {len(residue)} 处: {residue[:20]}")
    bad_parent = [b["name"] for b in bones if b.get("parent") and b["parent"] not in valid]
    if bad_parent:
        problems.append(f"parent 指向不存在骨骼: {bad_parent}")
    bad_slot = [(s["name"], s["bone"]) for s in doc["slots"] if s.get("bone") and s["bone"] not in valid]
    if bad_slot:
        problems.append(f"slot.bone 指向不存在骨骼: {bad_slot}")
    bad_anim = [f"{an}:{bn}" for an, a in doc.get("animations", {}).items()
                for bn in a.get("bones", {}) if bn not in valid]
    if bad_anim:
        problems.append(f"动画骨轨道指向不存在骨骼: {bad_anim[:10]}")
    by_name = {b["name"]: b for b in bones}
    for b in bones:
        seen, n = set(), b["name"]
        while n is not None:
            if n in seen:
                problems.append(f"父链成环: {b['name']}")
                break
            seen.add(n)
            n = by_name[n].get("parent")

    # ---- A3 等价：轨道集合 + 关键帧数一致 ----
    anim_tracks_after = {an: tracks(a) for an, a in doc.get("animations", {}).items()}
    if set(anim_tracks_before) != set(anim_tracks_after):
        problems.append("动画集合不一致")
    else:
        for an, tb in anim_tracks_before.items():
            ta = anim_tracks_after[an]
            expect = {old2new.get(k, k): v for k, v in tb.items()}
            if expect != ta:
                problems.append(f"动画 {an} 轨道/关键帧不等价: {expect} != {ta}")

    # ---- 报告 ----
    report = {
        "source": str(src_path),
        "map": str(map_path),
        "bones_total": len(bones),
        "renamed": sum(1 for b in bones if old2new.get(b["name"], b["name"]) != b["name"]),
        "animations": list(doc.get("animations", {})),
        "checks": {
            "A2_no_residue": not any("残留旧骨名" in p for p in problems),
            "A2_refs_valid": not any("指向不存在" in p or "成环" in p for p in problems),
            "A3_anim_equivalent": not any("不等价" in p or "动画集合" in p for p in problems),
        },
        "old2new": old2new,
        "problems": problems,
        "ok": not problems,
    }
    if report_path:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if problems:
        print("[rename] 失败：")
        for p in problems:
            print("   -", p)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(compact(doc), encoding="utf-8")
    renamed = sum(1 for b in bones if b["name"] in new_names)
    print(f"[rename] OK：{renamed}/{len(bones)} 骨已重命名；残留旧名 0；"
          f"动画 {len(anim_tracks_after)} 个轨道集合等价")
    print(f"[out] {out_path}")
    if report_path:
        print(f"[report] {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
