#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bodyshape 核心公式 —— derive.py 与 measure_girth.py 共用的**唯一**系数展开实现。

单独成模块的原因：这个公式是**接口契约**（garment 的 B2 morph 必须用同一套系数才能对上账）。
公式散在两处就一定会漂移，所以只留一份。

骨骼局部轴约定（Blender）：`pose_bone.scale = (x, y, z)`，**Y 恒为沿骨轴**（head→tail）。

    x = z = 1 + (coef - 1) * delta_response[group]        垂直于骨轴 → 改「周长」
    y     = 1 + (coef - 1) * along_axis_response[group]   沿骨轴     → 改「骨长」

`along_axis_response` 默认 0（= 老的纯 girth 口径）。只有**骨轴近乎水平**的骨才适合开它：
改骨长会改「宽度」而不是「身高」。目前只有 `clavicle`（左右锁骨，两端 z 相同 → 纯水平）
开了这一项 —— 它直接决定**肩宽/臂展**，而肩宽是正视图剪影里最宽、最抢眼的维度。
`pelvis`/`spine_*`/`thigh`/`calf` 的骨轴是竖直的，开它等于改身高 → 必须保持 0。
（实测：`clavicle` 开 1.0、系数 0.86/1.16 时臂展 ±2.5%/±2.8%，而身高比不变。）
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

AXIS_PROFILES = ("girth", "length", "uniform")
AXIS_PROFILE_DEFAULT = "girth"


def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def group_scale(spec: dict, group: str, coef: float):
    """→ (sx, sy, sz)：沿骨轴 Y 由 along_axis_response 控制，X/Z 由 delta_response 控制。"""
    d = coef - 1.0
    resp = float(spec["delta_response"][group])
    along = float(spec.get("along_axis_response", {}).get(group, 0.0))
    return [round(1.0 + d * resp, 6), round(1.0 + d * along, 6), round(1.0 + d * resp, 6)]


def canonical_bones(spec: dict, coef: float) -> dict:
    """**规范形** `(s, 1, s)`：只含 `delta_response` 的垂直轴调制，**不含** `along_axis_response`。
    它**不是**要摆到 pose bone 上的东西 —— 只作为"与口径无关的参考形"留档
    （spec 里存为 `tiers[].bones_canonical_girth`）。换口径不改它。"""
    d = coef - 1.0
    out = {}
    for group, members in spec["groups"].items():
        s = round(1.0 + d * float(spec["delta_response"][group]), 6)
        for bn in members:
            out[bn] = [s, 1.0, s]
    return out


def applied_bones(spec: dict, coef: float, profile: str = AXIS_PROFILE_DEFAULT) -> dict:
    """实际要摆到 pose bone 上的 scale —— **spec 的 `axis_profile.rule` 说的就是这个**：
    `x = z = 1+(coef-1)·delta_response[group]`，`y = 1+(coef-1)·along_axis_response[group]`。"""
    if profile not in AXIS_PROFILES:
        raise SystemExit(f"未知 axis_profile：{profile}（可选 {AXIS_PROFILES}）")
    if profile == "girth":
        out = {}
        for group, members in spec["groups"].items():
            v = group_scale(spec, group, coef)
            for bn in members:
                out[bn] = list(v)
        return out
    canon = canonical_bones(spec, coef)
    if profile == "length":       # SPEC §1 F5 的旧 demo 口径：含骨长（会改身高）
        return {bn: [v[0], v[0], 1.0] for bn, v in canon.items()}
    return {bn: [v[0], v[0], v[0]] for bn, v in canon.items()}   # uniform


def spec_bones(spec: dict, coef: float) -> dict:
    """写进 `spec.tiers[].bones` 的那一份 —— **默认口径(girth)的实摆三轴**。

    ⚠ 历史：v2.0 时这里存的是"规范形 `(s,1,s)`"，于是 spec 出现了**自相矛盾** ——
    `axis_profile.rule` 说 y 要带 `along_axis_response`，而 `tiers[].bones` 的 y 恒为 1。
    消费方最自然就是读 `tiers[].bones` 去摆骨/烘 morph，于是**照 spec 读反而丢掉肩宽项，
    且不报错**（garment 实际踩到）。v2.1 起改为存**实摆三轴**，让"最自然读到的那一块就是对的"。
    规范形仍在，但改名为 `bones_canonical_girth`，明示"参考用、别拿来摆骨"。"""
    return applied_bones(spec, coef, AXIS_PROFILE_DEFAULT)


def materialize_tiers(spec: dict, retune: dict | None = None,
                      profile: str = AXIS_PROFILE_DEFAULT) -> list:
    """展开 spec.tiers，并与 spec 里物化好的 `tiers[].bones` 对账（防 spec 两边漂移）。

    v2.1 起对账基准是 **`spec_bones()`（默认口径的实摆三轴）**，不再是规范形 ——
    也就是说 spec 里存的那一份必须**等于实际会摆上去的那一份**。
    `--retune` 覆盖的那一档是有意偏离声明值，不做对账。"""
    tiers = []
    for t in spec["tiers"]:
        coef = float(t["target_coefficient"])
        overridden = bool(retune) and t["name"] in retune
        if overridden:
            coef = float(retune[t["name"]])
        expected = spec_bones(spec, coef)
        canon = canonical_bones(spec, coef)
        declared = t.get("bones")
        if declared and not overridden:
            drift = []
            for bn in sorted(set(expected) | set(declared)):
                a, b = expected.get(bn), declared.get(bn)
                if a is None or b is None or max(abs(x - y) for x, y in zip(a, b)) > 1e-9:
                    drift.append((bn, a, b))
            if drift:
                raise SystemExit(
                    "spec 的 tiers[].bones 与 delta_response/along_axis_response 推导结果不一致"
                    "（spec 漂移）—— 注意 v2.1 起 tiers[].bones 必须存**实摆三轴**"
                    "（y 也带 along_axis_response），不再是规范形 (s,1,s)：\n  "
                    + "\n  ".join(f"{bn}: 按规则推导={a} spec 声明={b}" for bn, a, b in drift)
                    + "\n  修法：derive.py --sex … --retune thin=..,heavy=.. --write-spec"
                )
        tiers.append({**t, "target_coefficient": coef, "canonical_bones": canon,
                      "bones": applied_bones(spec, coef, profile)})
    return tiers


def bone_scales_for(spec: dict, coef: float, profile: str = AXIS_PROFILE_DEFAULT) -> dict:
    return applied_bones(spec, coef, profile)