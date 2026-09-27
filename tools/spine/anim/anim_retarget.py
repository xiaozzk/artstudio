#!/usr/bin/env python3
"""anim_retarget.py — 动画迁移核心：从 B 包提取动作模板，按映射表注入 A 包。

三阶段合一（MVP 先做一个命令跑通，harness 手册里再拆步骤）：

  评估产物（mapping.json）→ 本工具 → A 包副本（带新动画）

用法：
  python3 tools/spine/anim/render_rig.py ...   # 先渲骨骼图做视觉评估
  python3 tools/spine/anim/anim_retarget.py \
      --A assets/2d/人形/男/络腮胡剑士 \
      --B assets/2d/人形/男/法袍法师 \
      --anim attack \
      --map task/002-anim-retarget/input/mapping_luosai.json \
      --out task/002-anim-retarget/output/络腮胡剑士

mapping.json 格式：
{
  "bone_map": {"arm_r1": "bone6", ...},   # B骨名 → A骨名
  "mirror": false                          # 朝向相反时 true（增量取负+平移X取负）
}

对齐规则（2026-09-25 实测结论）：
- Spine 时间轴值 = 相对 setup pose 的增量 → 同构骨骼直接搬增量
- rotate 增量符号：sign = cos(A骨setup世界朝向 - B骨setup世界朝向) ≥ 0 ? +1 : -1
  （两骨 setup 朝向相反时，同一增量在 A 身上视觉方向反了，要取负）
- translate 增量：按骨架身高比缩放（A.skeleton.height / B.skeleton.height），
  并按 (A骨世界朝向 - B骨世界朝向) 旋转增量向量
- scale 增量：原样搬（比例无维度）
- 循环校验：末帧值 ≠ 首帧值 → 报错（除非 --no-loop-check）
- 通道白名单：bones 的 rotate/translate/scale；slot/deform 等通道不迁（告警丢弃）
- curve 只许 linear（省略）/stepped；贝塞尔数组原样保留（4 值）
- 4.3 JSON：首帧省略 time 视为 0；rotate 键名 value（3.8 的 angle 不支持，报错）

产出：
- <out>/<A包名>.json        注入后的骨架（不动原包！）
- <out>/<A包名>.atlas/.png  原样拷贝（player 预览需要）
- <out>/retarget-report.json 迁移报告（映射命中/丢弃/符号翻转/缩放系数）
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path


def load_skeleton(pkg: Path) -> tuple[dict, Path]:
    if pkg.is_dir():
        for jf in sorted(pkg.glob("*.json")):
            try:
                doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(doc, dict) and "bones" in doc and "skeleton" in doc:
                return doc, jf
        raise SystemExit(f"[!] {pkg} 下找不到骨架 json")
    return json.loads(pkg.read_text(encoding="utf-8")), pkg


def world_rots(doc: dict) -> dict[str, float]:
    """骨骼名 → setup pose 世界旋转角（度）。"""
    bones = {b["name"]: b for b in doc.get("bones", [])}
    out: dict[str, float] = {}

    def resolve(n: str) -> float:
        if n in out:
            return out[n]
        b = bones[n]
        r = b.get("rotation", 0.0)
        p = b.get("parent")
        out[n] = (resolve(p) if p and p in bones else 0.0) + r
        return out[n]

    for n in bones:
        resolve(n)
    return out


def parent_world_rots(doc: dict) -> dict[str, float]:
    """骨骼名 → 其**父骨骼**的 setup 世界旋转角（度）。

    translate 时间轴的值活在父骨骼坐标系里，所以迁移位移增量要按
    「父骨骼世界朝向差」旋转，而不是按骨骼自身的朝向差——
    用自身朝向差是 2026-09-25 实测踩过的错：影子骨（父 root 0° → 父 bone 90°）
    的水平位移会被转成垂直，看着像影子没跟人走。"""
    wr = world_rots(doc)
    out: dict[str, float] = {}
    for b in doc.get("bones", []):
        p = b.get("parent")
        out[b["name"]] = wr.get(p, 0.0) if p else 0.0
    return out


def detect_facing(doc: dict) -> tuple[str | None, float, str]:
    """数据层朝向启发式（返回 (left|right|None, 置信度, 依据)）。

    原理：3/4 侧视里眼睛长在脸的**面前一侧**，所以眼骨的世界 x 相对其父骨
    （脸/头）的偏移方向 = 面向。法袍实测：eye_l/x=-30.9、eye_r/-11.2，
    父 face x=-6.6 → 平均偏移 -14.4 ⇒ 朝左 ✅（flip 后 +14.4 ⇒ 朝右 ✅）。

    局限（**必须知道**）：只有 17/105 个交付包带眼骨，其余判不了——
    那时返回 None，朝向只能靠 agent 看复原预览图确认。别用「头骨前倾方向」
    之类的代理信号：络腮胡的头骨偏向画面左，但它面朝右，代理信号会判反。"""
    bones = {b["name"]: b for b in doc.get("bones", [])}
    wr = world_rots(doc)
    eye_names = [n for n in bones if "eye" in n.lower()]
    if not eye_names:
        return None, 0.0, "无眼骨，数据层无法自动判定（需 agent 看图确认）"

    def world_x(name: str) -> float:
        b = bones[name]
        lx, ly = b.get("x", 0.0), b.get("y", 0.0)
        p = b.get("parent")
        if not p or p not in bones:
            return lx
        pr = math.radians(wr.get(p, 0.0))
        # 父骨世界位置递归求解（复用 world_x）
        return world_x(p) + lx * math.cos(pr) - ly * math.sin(pr)

    offsets = []
    for n in eye_names:
        p = bones[n].get("parent")
        if p and p in bones:
            offsets.append(world_x(n) - world_x(p))
    if not offsets:
        return None, 0.0, f"眼骨 {eye_names} 无父骨，无法比较"
    mean = sum(offsets) / len(offsets)
    same_sign = all(o > 0 for o in offsets) or all(o < 0 for o in offsets)
    if abs(mean) < 3 or not same_sign:
        return None, 0.3, f"眼骨偏移 {[round(o,1) for o in offsets]} 不明确（|均值|<3 或符号不一致）"
    facing = "right" if mean > 0 else "left"
    return facing, 0.9, f"眼骨相对父骨平均偏移 {mean:+.1f}（{eye_names}）"


def normalize_keys(keys: list[dict], channel: str) -> list[dict]:
    """规整关键帧：补 time 缺省=0、校验 curve 合法值。"""
    out = []
    for k in keys:
        kk = dict(k)
        kk.setdefault("time", 0.0)
        c = kk.get("curve")
        if c is not None and c != "stepped" and not isinstance(c, list):
            raise ValueError(f"非法 curve 值 {c!r}（只认省略/stepped/贝塞尔数组）")
        out.append(kk)
    return out


def loop_closed(keys: list[dict], channel: str) -> bool:
    """循环闭合判定：末帧值 == 首帧值。"""
    if len(keys) < 2:
        return True
    first, last = keys[0], keys[-1]
    if channel == "rotate":
        return abs(first.get("value", 0.0) - last.get("value", 0.0)) < 1e-3
    return (abs(first.get("x", 0.0) - last.get("x", 0.0)) < 1e-3
            and abs(first.get("y", 0.0) - last.get("y", 0.0)) < 1e-3)


LOOP_NAME_HINTS = ("idle", "run", "walk", "move", "loop", "stand", "wait", "breath")


def is_loop_animation(name: str) -> bool:
    """循环类动画名启发式：idle/run/walk/stand… 才校验首尾闭合；
    attack/death/jump 这类单发动作不该回环（倒地保持躺平），查了全是误报。"""
    n = name.lower()
    return any(h in n for h in LOOP_NAME_HINTS)


def retarget(B_doc: dict, A_doc: dict, anim_name: str, mapping: dict,
             *, loop_check: bool = True) -> tuple[dict, dict]:
    """核心迁移。返回 (注入到 A 的 animation 对象, 迁移报告)。"""
    anims = B_doc.get("animations", {})
    if anim_name not in anims:
        raise SystemExit(f"[!] B 包没有动画 {anim_name}（现有：{list(anims)}）")
    src = anims[anim_name]
    bone_map: dict[str, str] = mapping.get("bone_map", {})
    mirror = bool(mapping.get("mirror", False))

    # 朝向闸门（用户要求：转换前统一到朝右，且加验证）。
    # 声明来自 agent 看复原预览图的判断（facing_A / facing_B）；
    # 数据层用眼骨启发式做**反查**——声明与数据冲突就拒绝执行。
    facing_warnings: list[str] = []
    fa, fb = mapping.get("facing_A"), mapping.get("facing_B")
    if fa and fb:
        if fa != fb:
            raise SystemExit(
                f"[!] 朝向不一致：A={fa} / B={fb} —— 先用 spine_flip.py 把 "
                f"{'A' if fa != 'right' else 'B'} 统一到朝右再迁移（见 SKILL.md 阶段 0.5）")
        if fa != "right":
            facing_warnings.append(f"两包朝向一致但均为 {fa}（约定统一朝右）")
    else:
        facing_warnings.append("未声明朝向（facing_A/facing_B）——本次跳过朝向校验")

    # 数据层反查（有眼骨时置信度高；无眼骨只能依赖 agent 的视觉声明）
    for label, doc, declared in (("A", A_doc, fa), ("B", B_doc, fb)):
        det, conf, reason = detect_facing(doc)
        if det is None:
            facing_warnings.append(f"{label} 包朝向数据层判不了：{reason}")
        elif declared and det != declared:
            raise SystemExit(
                f"[!] {label} 包朝向声明与数据矛盾：声明 {declared} / 数据判为 {det}"
                f"（{reason}）—— 请核对复原预览图后修正 mapping 或先 flip")
        elif declared:
            facing_warnings.append(f"{label} 包朝向校验通过：{det}（{reason}）")

    wr_A = world_rots(A_doc)
    wr_B = world_rots(B_doc)
    pwr_A = parent_world_rots(A_doc)
    pwr_B = parent_world_rots(B_doc)
    hA = A_doc.get("skeleton", {}).get("height", 0) or 1
    hB = B_doc.get("skeleton", {}).get("height", 0) or 1
    scale_xy = hA / hB

    report = {
        "anim": anim_name, "mirror": mirror,
        "scale_translate": round(scale_xy, 4),
        "facing_A": fa, "facing_B": fb, "facing_warnings": facing_warnings,
        "tracks_mapped": [], "tracks_dropped": [], "tracks_sign_flipped": [],
        "loop_not_closed": [], "channels_skipped": [],
    }

    out_bones: dict[str, dict] = {}
    do_loop_check = loop_check and is_loop_animation(anim_name)
    for b_bone, tracks in src.get("bones", {}).items():
        a_bone = bone_map.get(b_bone)
        if a_bone is None:
            report["tracks_dropped"].append(b_bone)
            continue
        if a_bone not in wr_A:
            raise SystemExit(f"[!] 映射目标 {a_bone} 不在 A 骨骼里（{b_bone} → {a_bone}）")
        # rotate 的轴向：按**骨骼自身**世界朝向差定符号（朝向相反 ⇒ 增量取负）
        d_rot = (wr_A.get(a_bone, 0.0) - wr_B.get(b_bone, 0.0))
        sign = 1.0 if math.cos(math.radians(d_rot)) >= 0 else -1.0
        if mirror:
            sign = -sign
        if sign < 0:
            report["tracks_sign_flipped"].append(f"{b_bone}→{a_bone}")
        # translate 的坐标系：值是**父骨骼空间**的位移，故按父骨骼世界朝向差旋转
        d_par = (pwr_B.get(b_bone, 0.0) - pwr_A.get(a_bone, 0.0))
        theta_p = math.radians(d_par)
        cp, sp = math.cos(theta_p), math.sin(theta_p)

        out_tracks: dict[str, list] = {}
        for ch, keys in tracks.items():
            if ch not in ("rotate", "translate", "scale"):
                report["channels_skipped"].append(f"{b_bone}.{ch}")
                continue
            keys = normalize_keys(keys, ch)
            if do_loop_check and not loop_closed(keys, ch):
                report["loop_not_closed"].append(f"{b_bone}.{ch}")
            new_keys = []
            for k in keys:
                nk = {"time": k["time"]}
                if "curve" in k:
                    nk["curve"] = k["curve"]
                if ch == "rotate":
                    nk["value"] = round(k.get("value", 0.0) * sign, 3)
                elif ch == "translate":
                    vx, vy = k.get("x", 0.0) * scale_xy, k.get("y", 0.0) * scale_xy
                    if mirror:
                        vx = -vx
                    # 把「父骨骼空间」的位移换到目标的父骨骼空间
                    nk["x"] = round(vx * cp - vy * sp, 3)
                    nk["y"] = round(vx * sp + vy * cp, 3)
                else:  # scale
                    nk["x"] = k.get("x", 0.0)
                    nk["y"] = k.get("y", 0.0)
                # 首帧 time=0 按 4.3 惯例省略
                if abs(nk["time"]) < 1e-9:
                    del nk["time"]
                new_keys.append(nk)
            out_tracks[ch] = new_keys
        if out_tracks:
            out_bones[a_bone] = out_tracks
            report["tracks_mapped"].append(f"{b_bone}→{a_bone}({','.join(out_tracks)})")

    for top in src:
        if top != "bones":
            report["channels_skipped"].append(f"[顶层通道]{top}")

    return {"bones": out_bones}, report


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="动画迁移：B 包动作模板 → A 包")
    ap.add_argument("--A", required=True, help="A 包目录或骨架 json")
    ap.add_argument("--B", required=True, help="B 包目录或骨架 json")
    ap.add_argument("--anim", required=True, action="append",
                    help="要迁的动画名（可多次）")
    ap.add_argument("--map", required=True, help="mapping.json 路径")
    ap.add_argument("--out", required=True, help="输出目录（A 包副本，不动原包）")
    ap.add_argument("--rename", default=None,
                    help="注入后的动画名（默认沿用 B 名；重名时默认报错，--overwrite 覆盖）")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--no-loop-check", action="store_true")
    args = ap.parse_args(argv[1:])

    A_doc, A_json_path = load_skeleton(Path(args.A))
    B_doc, _ = load_skeleton(Path(args.B))
    mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    A_new = json.loads(json.dumps(A_doc))  # 深拷贝
    A_new.setdefault("animations", {})
    reports = []
    for anim in args.anim:
        target_name = args.rename or anim
        if target_name in A_new["animations"] and not args.overwrite:
            raise SystemExit(f"[!] A 包已有动画 {target_name}（--overwrite 覆盖）")
        anim_obj, report = retarget(B_doc, A_doc, anim, mapping,
                                    loop_check=not args.no_loop_check)
        A_new["animations"][target_name] = anim_obj
        reports.append(report)
        print(f"[retarget] {anim} → {target_name}: "
              f"映射 {len(report['tracks_mapped'])} 轨，"
              f"丢弃 {len(report['tracks_dropped'])}（B 有 A 无对应骨），"
              f"符号翻转 {len(report['tracks_sign_flipped'])}，"
              f"循环未闭合 {len(report['loop_not_closed'])}")
        for w in report.get("facing_warnings", []):
            print(f"           ⚠ {w}")
        if report["loop_not_closed"]:
            print(f"           ⚠ 未闭合: {report['loop_not_closed']}")
        if report["channels_skipped"]:
            print(f"           跳过通道: {report['channels_skipped']}")

    # 产物：json + atlas + 图集页
    out_json = out_dir / A_json_path.name
    out_json.write_text(json.dumps(A_new, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    for f in A_json_path.parent.glob("*.atlas"):
        shutil.copy2(f, out_dir / f.name)
    for f in A_json_path.parent.glob("*.png"):
        if f.stem != "复原预览图" and not f.name.startswith("复原预览图"):
            shutil.copy2(f, out_dir / f.name)
    (out_dir / "retarget-report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {out_json}")
    print(f"[out] {out_dir / 'retarget-report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
