#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体形档位「强度」客观测量 —— 回答「0.86/1.16 到底对应多少围度变化？够不够？」

不用"看起来明显吗"当判据，全部用可复现的数字：

  ① **关键围度**（主判据）胸围 / 腰围 / 臀围 / 上臂围 / 大腿围 / 小腿围
     —— 用「切片 + 投影 + 凸包周长」算，等价于拿软尺量（凸包会跨过凹处，和软尺一致）。
     网格不是闭合曲面（SPEC F15：26 个连通域 / 48 条边界环）→ **绝不能用"边界环求周长"**，
     凸包对破洞与面绕向完全免疫。
  ② **系数响应曲线**：扫一串 target_coefficient，给出「系数 → 围度变化 %」的对应关系，
     这样要多少视觉强度就选多少系数，不用猜。
  ③ **网格健康度**：面法线翻转数 / 面积塌陷数 / **左右腿最小间隙** —— 回答"能从 0.86 再往下压多少"。
  ④ `--check-interp`：**线性插值精确性**验证（morph 档间插值会不会出现"不像人"的中间态）。

★ 测量一律走 depsgraph 求值（SPEC F9：shape key 不改 mesh.vertices）。
  本工具 **只读**，绝不写 .blend。

用法（工作区根下执行）：
  Blender -b --factory-startup --python tools/3d/bodyshape/measure_girth.py -- \\
      [--sex both] [--coefficients 0.75,0.80,0.86,0.95,1.05,1.16,1.25,1.35] \\
      [--out assets/3d/rig/reports/bodyshape_strength.json] [--check-interp]

  python3 tools/3d/bodyshape/measure_girth.py --help     # 不开 Blender 也能看帮助
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)                       # 让 Blender --python 也能 import 同目录模块
import bodyshape_core as core                  # noqa: E402  ← 系数展开的唯一实现
SPEC = os.path.join(ROOT, "assets", "3d", "rig", "bodyshape_spec.json")
OUT_DEFAULT = os.path.join(ROOT, "assets", "3d", "rig", "reports", "bodyshape_strength.json")

try:
    import bpy  # type: ignore
    import numpy as np  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    np = None  # type: ignore
    HAS_BPY = False

SLAB = 0.02       # 切片半厚（米）：以 z（躯干）或沿骨轴 t（四肢）为中心取 ±SLAB
GRID = 0.004      # 扫描步长（米）
TORSO_BONES = ("pelvis", "spine_01", "spine_02", "spine_03")
REGION_W = 0.5    # 某区域的总权重阈值

# 测站定义：window 用骨几何表达（自文档、可复现），不写死绝对 z
STATIONS = [
    {"name": "bust", "unit": "m", "kind": "torso", "pick": "max",
     "window": ("spine_02.tail", "spine_03.tail"),
     "note": "胸围：spine_02 尾 → spine_03 尾 区间的最大周长"},
    {"name": "waist", "unit": "m", "kind": "torso", "pick": "min",
     "window": ("spine_01.head", "spine_02.head"),
     "note": "腰围：spine_01 头 → spine_02 头 区间的最小周长（最细处）"},
    {"name": "hip", "unit": "m", "kind": "torso", "pick": "max",
     "window": ("thigh_l.head-0.02", "pelvis.tail+0.01"),
     "note": "臀围：大腿根下 2 cm → 骨盆尾 区间的最大周长"},
    {"name": "upperarm_l", "unit": "m", "kind": "limb", "bone": "upperarm_l",
     "t": (0.25, 0.80), "pick": "max", "note": "左上臂围：沿骨长 25%–80% 区间的最大周长"},
    {"name": "thigh_l", "unit": "m", "kind": "limb", "bone": "thigh_l",
     "t": (0.12, 0.55), "pick": "max", "note": "左大腿围：沿骨长 12%–55% 区间的最大周长"},
    {"name": "calf_l", "unit": "m", "kind": "limb", "bone": "calf_l",
     "t": (0.15, 0.60), "pick": "max", "note": "左小腿围：沿骨长 15%–60% 区间的最大周长"},
]


# ────────────────────────────────────────────────────────────────────────────
def eval_coords(obj):
    """depsgraph 求值后的顶点坐标（SPEC F9）。"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    m = ev.to_mesh()
    co = np.array([tuple(v.co) for v in m.vertices], dtype=np.float64)
    ev.to_mesh_clear()
    return co


def clear_pose(arm):
    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def measure_linears(co, arm, height_base):
    """**线性**量：正视图剪影里最抢眼的维度其实是「臂展 / 肩宽」，不是围度。
    企鹅式 T-pose 下臂展 ≈ 1.67 m，而髋宽只有 ~0.2 m —— 所以围度改 14% 也救不回"看起来没变"。
    这两个量必须一起看。"""
    span = float(co[:, 0].max() - co[:, 0].min())
    sh = float(abs(arm.pose.bones["upperarm_l"].head.x) * 2.0)   # 肩关节间距（双臂骨根 x 距）
    h = float(co[:, 2].max() - co[:, 2].min())
    return {
        "arm_span_m": round(span, 6),
        "arm_span_ratio_vs_basis": round(span / span_base[0], 6),
        "shoulder_joint_span_m": round(sh, 6),
        "shoulder_joint_span_ratio_vs_basis": round(sh / span_base[1], 6),
        "height_m": round(h, 6),
        "height_ratio_vs_basis": round(h / height_base, 6),
    }


span_base = [None, None]


def zero_keys(me):
    """★ 把 shape key 权重清零。**每次用 pose 测形之前必须调用** ——
    踩过的坑：pose 与 shape key 是**两套独立**的形变来源，会叠加。只清 pose 不清权重，
    量到的就是「pose + 当前 weight 的 morph」，静默给出错值（我在这里读到过 33 mm 的假差）。
    配套的廉价保险：同一个状态量两次，两条结果必须逐顶点相同。"""
    if me.shape_keys is None:
        return
    for kb in me.shape_keys.key_blocks:
        kb.value = 0.0
    bpy.context.view_layer.update()


def apply_coefficient(arm, spec, coef, profile="girth"):  # noqa: D401
    """展开成 14 根体形骨的 pose scale（公式走 bodyshape_core，与 derive.py 同一实现）。"""
    clear_pose(arm)
    scales = core.bone_scales_for(spec, coef, profile)
    for bn, (sx, sy, sz) in scales.items():
        pb = arm.pose.bones.get(bn)
        if pb is None:
            raise SystemExit(f"pose bone 缺失：{bn}")
        pb.scale = (sx, sy, sz)
    bpy.context.view_layer.update()
    return scales


def assert_stable(obj, label, tol_m=1e-6):
    """自一致性守卫：同一状态连测两次必须一致（捕捉 depsgraph 未刷新 / 状态污染）。"""
    a = eval_coords(obj)
    b = eval_coords(obj)
    d = float(np.abs(a - b).max())
    if d > tol_m:
        raise SystemExit(f"[{label}] 同一状态两次求值不一致：{d * 1000:.4f} mm —— "
                         f"depsgraph 没刷新或状态被污染，结果不可信")
    return d


def hull_perimeter(pts):
    """2D 凸包周长（Andrew monotone chain）—— 自实现，不依赖 scipy，确定性好。"""
    p = np.unique(pts, axis=0)
    if len(p) < 3:
        return None
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in p[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    h = np.array(lower[:-1] + upper[:-1])
    if len(h) < 3:
        return None
    return float(np.linalg.norm(np.roll(h, -1, axis=0) - h, axis=1).sum())


def region_mask(obj, names, thr=REGION_W):
    """总权重 ≥ thr 落在 names 这些骨上的顶点掩码。"""
    idx = {obj.vertex_groups[n].index for n in names if n in obj.vertex_groups}
    mask = np.zeros(len(obj.data.vertices), dtype=bool)
    for i, v in enumerate(obj.data.vertices):
        mask[i] = sum(ge.weight for ge in v.groups if ge.group in idx) >= thr
    return mask


def bone_windows(arm):
    """把 STATIONS 里的骨几何表达式解析成绝对窗口。支持 `bone.head` / `bone.tail` 与 `±0.02` 偏移。"""
    import re
    B = arm.data.bones

    def pt(expr):
        m = re.fullmatch(r"\s*([A-Za-z0-9_]+)\.(head|tail)\s*([+-]\s*[0-9.]+)?\s*", expr)
        if not m:
            raise SystemExit(f"窗口表达式无法解析：{expr!r}")
        name, attr, off = m.group(1), m.group(2), m.group(3)
        if name not in B:
            raise SystemExit(f"骨架里没有骨 {name!r}")
        return getattr(B[name], attr + "_local").z + (float(off.replace(" ", "")) if off else 0.0)

    win = {}
    for st in STATIONS:
        if st["kind"] == "torso":
            lo, hi = (pt(st["window"][0]), pt(st["window"][1]))
            win[st["name"]] = (min(lo, hi), max(lo, hi))
    return win


def measure(co, mask_torso, arm, win):
    """返回每站的周长（米）。"""
    out = {}
    for st in STATIONS:
        if st["kind"] == "torso":
            sel = mask_torso
            axis = co[sel][:, 2]
            lo, hi = win[st["name"]]
            best, best_at = None, None
            z = lo
            while z <= hi + 1e-9:
                m = sel & (np.abs(co[:, 2] - z) <= SLAB)
                if m.sum() >= 8:
                    per = hull_perimeter(co[m][:, [0, 1]])
                    if per is not None:
                        if best is None or (st["pick"] == "max" and per > best) \
                                or (st["pick"] == "min" and per < best):
                            best, best_at = per, z
                z += GRID
            out[st["name"]] = {"perimeter_m": best, "at_z_m": best_at}
        else:
            b = arm.data.bones[st["bone"]]
            head = np.array(tuple(b.head_local))
            tail = np.array(tuple(b.tail_local))
            d = tail - head
            L = float(np.linalg.norm(d))
            d = d / L
            # 垂直平面上的两个基向量
            a = np.array([1.0, 0.0, 0.0])
            if abs(float(np.dot(a, d))) > 0.9:
                a = np.array([0.0, 1.0, 0.0])
            u = np.cross(d, a)
            u /= np.linalg.norm(u)
            v = np.cross(d, u)
            rel = co - head
            t = rel @ d
            mask = region_mask_cache[st["bone"]]
            lo, hi = st["t"][0] * L, st["t"][1] * L
            best, best_at = None, None
            tt = lo
            while tt <= hi + 1e-9:
                m = mask & (np.abs(t - tt) <= SLAB)
                if m.sum() >= 8:
                    pts = np.stack([rel[m] @ u, rel[m] @ v], axis=1)
                    per = hull_perimeter(pts)
                    if per is not None and (best is None or per > best):
                        best, best_at = per, tt / L
                tt += GRID
            out[st["name"]] = {"perimeter_m": best, "at_t_frac": best_at}
    return out


region_mask_cache = {}


def mesh_health(co_base, co_cur, faces, areas_base):
    """面法线翻转 / 面积塌陷 / 左右腿最小间隙 —— "还能再压多少"的边界。"""
    def normals(co):
        a = co[faces[:, 0]]
        b = co[faces[:, 1]]
        c = co[faces[:, 2]]
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        return n / ln

    n0, n1 = normals(co_base), normals(co_cur)
    d = (n0 * n1).sum(axis=1)
    area1 = 0.5 * np.linalg.norm(
        np.cross(co_cur[faces[:, 1]] - co_cur[faces[:, 0]],
                 co_cur[faces[:, 2]] - co_cur[faces[:, 0]]), axis=1)
    return {
        "faces_flipped": int((d < 0).sum()),
        "faces_with_dot_lt_0_5": int((d < 0.5).sum()),
        "faces_area_collapsed_90pct": int((area1 < 0.1 * areas_base).sum()),
        "min_face_area_ratio": float((area1 / np.maximum(areas_base, 1e-12)).min()),
    }


def leg_gap(co, mask_l, mask_r):
    """左右腿在每一层 z 上的最小水平间隙；<0 = 两腿互相穿插。"""
    zl, zr = co[mask_l], co[mask_r]
    zs = np.arange(min(zl[:, 2].min(), zr[:, 2].min()) + 0.05,
                   min(zl[:, 2].max(), zr[:, 2].max()) - 0.05, 0.01)
    worst, at = None, None
    for z in zs:
        a = zl[np.abs(zl[:, 2] - z) <= SLAB]
        b = zr[np.abs(zr[:, 2] - z) <= SLAB]
        if len(a) < 5 or len(b) < 5:
            continue
        # a 是左腿(+X)，b 是右腿(-X)：间隙 = a.min_x - b.max_x
        g = float(a[:, 0].min() - b[:, 0].max())
        if worst is None or g < worst:
            worst, at = g, float(z)
    return {"min_gap_m": worst, "at_z_m": at}


# ────────────────────────────────────────────────────────────────────────────
def process(spec, cfg, coefficients, check_interp):
    sex = cfg["sex"]
    path = os.path.join(ROOT, cfg["file"])
    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.data.objects[cfg["object"]]
    arm = bpy.data.objects[cfg["armature"]]
    me = obj.data
    print(f"\n{'=' * 74}\n[{sex}] {os.path.relpath(path, ROOT)}  {len(me.vertices)} 顶点")

    clear_pose(arm)
    zero_keys(me)
    co0 = eval_coords(obj)
    assert_stable(obj, f"{sex} Basis")
    NV = len(co0)
    span_base[0] = float(co0[:, 0].max() - co0[:, 0].min())
    span_base[1] = float(abs(arm.pose.bones["upperarm_l"].head.x) * 2.0)
    height_base = float(co0[:, 2].max() - co0[:, 2].min())
    faces = np.array([tuple(p.vertices) for p in me.polygons if len(p.vertices) == 3], dtype=np.int64)
    areas_base = 0.5 * np.linalg.norm(
        np.cross(co0[faces[:, 1]] - co0[faces[:, 0]], co0[faces[:, 2]] - co0[faces[:, 0]]), axis=1)
    print(f"  三角面 {len(faces)}（共 {len(me.polygons)} 面）")

    global region_mask_cache
    region_mask_cache = {}
    region_mask_cache["torso"] = region_mask(obj, TORSO_BONES)
    for st in STATIONS:
        if st["kind"] == "limb":
            region_mask_cache[st["bone"]] = region_mask(obj, (st["bone"],))
    mask_l = region_mask(obj, ("thigh_l", "calf_l"))
    mask_r = region_mask(obj, ("thigh_r", "calf_r"))
    m_torso = region_mask_cache["torso"]
    print(f"  区域顶点数：躯干 {int(m_torso.sum())} / 左腿 {int(mask_l.sum())} / 右腿 {int(mask_r.sum())}")

    win = bone_windows(arm)
    base = measure(co0, m_torso, arm, win)
    print("  基准（Basis 1.00）：" + "  ".join(
        f"{k}={v['perimeter_m'] * 100:.1f}cm" for k, v in base.items() if v["perimeter_m"]))

    rows = []
    for coef in coefficients:
        zero_keys(me)                       # ★ 先清权重：pose 与 shape key 会叠加
        scales = apply_coefficient(arm, spec, coef)
        co = eval_coords(obj)
        assert_stable(obj, f"{sex} coef={coef}")
        m = measure(co, m_torso, arm, win)
        lin = measure_linears(co, arm, height_base)
        health = mesh_health(co0, co, faces, areas_base)
        gap = leg_gap(co, mask_l, mask_r)
        clear_pose(arm)
        row = {
            "target_coefficient": coef,
            "bone_scale_range": [round(min(v[0] for v in scales.values()), 6),
                                 round(max(v[0] for v in scales.values()), 6)],
            "girths": {k: {"perimeter_m": (None if v["perimeter_m"] is None else round(v["perimeter_m"], 6)),
                           "pct_vs_basis": (None if v["perimeter_m"] is None else
                                            round((v["perimeter_m"] / base[k]["perimeter_m"] - 1.0) * 100, 3))}
                       for k, v in m.items()},
            "linears": lin,
            "max_displacement_cm": round(float(np.linalg.norm(co - co0, axis=1).max()) * 100, 4),
            "mesh_health": health,
            "leg_gap": gap,
        }
        rows.append(row)
        g = row["girths"]
        print(f"  coef={coef:.3f}  臀 {g['hip']['pct_vs_basis']:+6.2f}%  腰 {g['waist']['pct_vs_basis']:+6.2f}%  "
              f"胸 {g['bust']['pct_vs_basis']:+6.2f}%  上臂 {g['upperarm_l']['pct_vs_basis']:+6.2f}%  "
              f"大腿 {g['thigh_l']['pct_vs_basis']:+6.2f}%  | 臂展 {(lin['arm_span_ratio_vs_basis'] - 1) * 100:+6.2f}%  "
              f"肩距 {(lin['shoulder_joint_span_ratio_vs_basis'] - 1) * 100:+6.2f}%  "
              f"身高比 {lin['height_ratio_vs_basis']:.5f}  | 最大位移 {row['max_displacement_cm']:5.2f}cm  "
              f"翻转面 {health['faces_flipped']:3d}  腿间隙 "
              f"{(gap['min_gap_m'] * 100 if gap['min_gap_m'] is not None else float('nan')):+6.2f}cm")

    interp = None
    if check_interp:
        interp = check_interpolation(obj, arm, spec, co0, m_torso, win)

    return {
        "sex": sex, "file": cfg["file"], "vertex_count": NV, "triangle_count": int(len(faces)),
        "station_windows_m": {k: [round(v[0], 4), round(v[1], 4)] for k, v in win.items()},
        "region_vertex_counts": {"torso": int(m_torso.sum()), "thigh_l": int(mask_l.sum()),
                                 "thigh_r": int(mask_r.sum())},
        "stations": [{k: v for k, v in st.items()} for st in STATIONS],
        "basis_girths_m": {k: (None if v["perimeter_m"] is None else round(v["perimeter_m"], 6))
                           for k, v in base.items()},
        "basis_at": {k: {kk: (None if vv is None else round(vv, 4)) for kk, vv in v.items()
                         if kk.startswith("at_")} for k, v in base.items()},
        "coefficient_sweep": rows,
        "interpolation_check": interp,
    }


def check_interpolation(obj, arm, spec, co0, m_torso, win):
    """线性插值精确性：morph 在 w 处的线性混合，是否 == 把 scale 取同样线性插值后重摆骨？
    LBS 对"每骨缩放"是**仿射线性**的 → 理论上应逐顶点相等（只差 float32 舍入）。
    只要这条成立，「加第 3 档」就不会因插值产生"不像人"的中间态。"""
    me = obj.data
    names = ["Basis"] + [t["shape_key"] for t in spec["tiers"]]
    if me.shape_keys is None or any(n not in [k.name for k in me.shape_keys.key_blocks] for n in names):
        return {"skipped": "shape key 不全"}
    thin = next(t for t in spec["tiers"] if t["name"] == "thin")
    heavy = next(t for t in spec["tiers"] if t["name"] == "heavy")
    # 必须用**实际摆上去的**三轴向量。v2.1 起 spec 的 `tiers[].bones` 已经是实摆三轴，
    # 但仍统一走 core.applied_bones() —— 别直接读 spec 字段（历史坑：v2.0 时它存的是
    # 规范形 (s,1,s)，clavicle 的 Y 恒为 1，会丢掉沿骨轴那一项 → 假差 11.6 mm）。
    tb = core.applied_bones(spec, thin["target_coefficient"])
    hb = core.applied_bones(spec, heavy["target_coefficient"])
    res = []
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        for kb in me.shape_keys.key_blocks:
            kb.value = 0.0
        me.shape_keys.key_blocks[thin["shape_key"]].value = 1.0 - w
        me.shape_keys.key_blocks[heavy["shape_key"]].value = w
        bpy.context.view_layer.update()
        co_blend = eval_coords(obj)
        assert_stable(obj, f"blend w={w}")
        # 等价 pose：每根骨的 scale 按同样权重插值
        # ★ 必须先清 shape key 权重，否则量到的是 pose+morph 的叠加（踩过，假差 33 mm）
        clear_pose(arm)
        zero_keys(me)
        for b in spec["shape_bones"]:
            # ★ 必须插值**完整的三轴向量**：v2 起 clavicle 的 Y（沿骨轴）不为 1，
            # 只取 [0] 再摆 (s,1,s) 会把沿骨轴那一项丢掉（踩过：假差 2.7 mm）。
            st, sh = tb[b], hb[b]
            arm.pose.bones[b].scale = tuple((1 - w) * st[i] + w * sh[i] for i in range(3))
        bpy.context.view_layer.update()
        co_pose = eval_coords(obj)
        assert_stable(obj, f"pose w={w}")
        clear_pose(arm)
        zero_keys(me)
        d = np.linalg.norm(co_blend - co_pose, axis=1)
        res.append({"w": w, "max_diff_mm": round(float(d.max()) * 1000, 6),
                    "mean_diff_mm": round(float(d.mean()) * 1000, 6),
                    "equivalent_coefficient": round(
                        (1 - w) * thin["target_coefficient"] + w * heavy["target_coefficient"], 6)})
        print(f"  插值检查 w={w}: 与等价 pose 的逐顶点最大差 {res[-1]['max_diff_mm']:.6f} mm "
              f"（等价系数 {res[-1]['equivalent_coefficient']:.3f}）")
    return {"note": "morph 线性混合 vs 等价 pose 缩放；LBS 对每骨缩放仿射线性 ⇒ 理论差应为 0",
            "samples": res, "max_diff_mm": max(r["max_diff_mm"] for r in res)}


def main():
    ap = argparse.ArgumentParser(
        prog="measure_girth.py",
        description="体形档位强度客观测量：关键围度 % + 系数响应曲线 + 网格健康度 + 插值精确性",
        epilog="例：Blender -b --factory-startup --python tools/3d/bodyshape/measure_girth.py -- --sex both --check-interp")
    ap.add_argument("--sex", choices=["Female", "Male", "both"], default="both")
    ap.add_argument("--spec", default=SPEC)
    ap.add_argument("--coefficients", default=None,
                    help="逗号分隔的 target_coefficient 扫描点（默认取 spec 档位 + 0.72,0.78,0.92,1.06,1.25,1.35）")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--check-interp", action="store_true", help="验证 morph 线性插值的精确性")
    ap.add_argument("--delta", default=None, metavar="spine_03=1.0,clavicle=0.8",
                    help="临时覆盖 spec 的 delta_response（只影响本次测量，不落盘）—— 用来试"
                         "『把上半身放开』这类方案，不必改 spec")
    ap.add_argument("--along", default=None, metavar="clavicle=1.0",
                    help="临时覆盖 spec 的 along_axis_response（沿骨轴，只对水平骨有意义）"
                         "—— 直接改肩宽/臂展")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写 JSON")
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    if not HAS_BPY:
        if not argv or any(a in ("-h", "--help") for a in argv):
            ap.print_help()
            return 0
        ap.error("需要 bpy + numpy —— 请在 Blender headless 下运行")
    args = ap.parse_args(argv)

    spec = json.load(open(args.spec, encoding="utf-8"))
    if args.delta:
        ov = {}
        for part in args.delta.split(","):
            k, _, v = part.partition("=")
            ov[k.strip()] = float(v)
        bad = [k for k in ov if k not in spec["delta_response"]]
        if bad:
            raise SystemExit(f"--delta 里有 spec 不认识的组：{bad}")
        spec["delta_response"] = {**spec["delta_response"], **ov}
        print(f"  ⚠ delta_response 临时覆盖：{ov}（不落盘）")
    if args.along:
        ov = {}
        for part in args.along.split(","):
            k, _, v = part.partition("=")
            ov[k.strip()] = float(v)
        bad = [k for k in ov if k not in spec["groups"]]
        if bad:
            raise SystemExit(f"--along 里有 spec 不认识的组：{bad}")
        spec["along_axis_response"] = {**spec.get("along_axis_response", {}), **ov}
        print(f"  ⚠ along_axis_response 临时覆盖：{ov}（不落盘）")
    if args.coefficients:
        coefs = sorted({float(x) for x in args.coefficients.split(",")})
    else:
        coefs = sorted({0.72, 0.78, 0.92, 1.06, 1.25, 1.35}
                       | {round(t["target_coefficient"], 6) for t in spec["tiers"]})
    t0 = time.time()
    print(f"# measure_girth.py  Blender {bpy.app.version_string}")
    print(f"  口径 = {spec['axis_profile']['name']}  切片半厚 {SLAB * 100:.0f} cm  步长 {GRID * 100:.1f} cm")
    print(f"  扫描系数：{coefs}")

    bodies = []
    for cfg in spec["bodies"]:
        if args.sex in ("both", cfg["sex"]):
            bodies.append(process(spec, cfg, coefs, args.check_interp))

    report = {
        "schema": "bodyshape-strength",
        "method": {
            "girth": "切片(z 或沿骨轴 t) → 投影到垂直平面 → 2D 凸包周长。"
                     "凸包等价于软尺量法（跨过凹处），且对破洞/面绕向免疫（标准体非闭合，SPEC F15）",
            "region": f"顶点的区域总权重 ≥ {REGION_W}（躯干 = pelvis+spine_01..03；四肢 = 对应骨）",
            "slab_m": SLAB, "grid_m": GRID,
            "measurement": "全部走 depsgraph 求值（SPEC F9）",
        },
        "axis_profile": spec["axis_profile"],
        "delta_response": spec["delta_response"],
        "blender_version": bpy.app.version_string,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "swept_coefficients": coefs,
        "bodies": bodies,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    if args.dry_run:
        print("\n[dry-run] 不写 JSON")
    else:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\n报告 → {os.path.relpath(args.out, ROOT)}  ({os.path.getsize(args.out) / 1024:.1f} KB)")
    print(f"DONE  {report['elapsed_sec']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())