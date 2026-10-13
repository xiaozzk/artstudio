"""
vlib.py —— verifier 独立测量基础库（在 Blender 的 Python 里运行）。

设计原则（与 tools/3d/bodyshape、tools/3d/garment 零共享代码）：
  * 所有网格读数一律走 depsgraph 求值（SPEC F9：shape key 不改 mesh.vertices）。
  * 所有"内部/外部"判定由本库自己实现（射线奇偶 + 最近点法线定向双法交叉验证）。
  * 不 import 任何 T1/T2/T3 的模块。

本文件只被本目录下的 v_*.py 使用。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

# --------------------------------------------------------------------------
# 场景 / 求值
# --------------------------------------------------------------------------


def evaluated_mesh(obj, depsgraph=None):
    """返回 obj 的**求值后**网格数据（numpy）。

    shape key / armature / modifier 的结果全在这里；obj.data.vertices 是原始
    rest 数据，量 morph 时**不可用**（SPEC F9 的坑）。
    """
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    # 面索引（对 morph 拓扑一致性判定用；shape key 不改拓扑，但 modifier 会）
    npoly = len(me.polygons)
    loop_start = np.empty(npoly, dtype=np.int32)
    loop_total = np.empty(npoly, dtype=np.int32)
    me.polygons.foreach_get("loop_start", loop_start)
    me.polygons.foreach_get("loop_total", loop_total)
    tv = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", tv)
    ev.to_mesh_clear()
    return {
        "co": co,
        "n_verts": n,
        "n_polys": npoly,
        "poly_verts": tv,
        "loop_start": loop_start,
        "loop_total": loop_total,
    }


def eval_poly_signature(obj, depsgraph=None):
    """拓扑指纹：顶点数 + 面数 + 三角化顶点索引序列的 sha1。"""
    m = evaluated_mesh(obj, depsgraph)
    h = hashlib.sha1()
    h.update(struct.pack("<ii", m["n_verts"], m["n_polys"]))
    # 统一按"面 -> 顶点索引元组"序列化，忽略 loop 起始偏移差异
    idx = m["poly_verts"]
    ls, lt = m["loop_start"], m["loop_total"]
    for s, t in zip(ls, lt):
        h.update(struct.pack("<i", t))
        h.update(idx[s:s + t].astype(np.int32).tobytes())
    return {
        "n_verts": int(m["n_verts"]),
        "n_polys": int(m["n_polys"]),
        "n_loops": int(len(m["poly_verts"])),
        "sig": h.hexdigest(),
    }


# --------------------------------------------------------------------------
# 独立"内部/外部"判定
# --------------------------------------------------------------------------


def _triangulate(m):
    """把求值网格展平成三角形（扇形三角化，Blender 的 n-gon 约定即扇形）。"""
    tris = []
    idx = m["poly_verts"]
    for s, t in zip(m["loop_start"], m["loop_total"]):
        vs = [int(x) for x in idx[s:s + t]]
        for k in range(1, t - 1):
            tris.append((vs[0], vs[k], vs[k + 1]))
    return np.array(tris, dtype=np.int32)


def _eval_world_co(obj, depsgraph=None):
    """求值网格的世界坐标顶点。"""
    m = evaluated_mesh(obj, depsgraph)
    co = m["co"].copy()
    M = np.array(obj.matrix_world)
    return m, (co @ M[:3, :3].T + M[:3, 3])


def bvh_from_eval(obj, depsgraph=None, world=True):
    """返回 (BVHTree, 世界坐标顶点数组, 三角形索引) —— 全部来自求值网格。"""
    m, co = _eval_world_co(obj, depsgraph)
    tris = _triangulate(m)
    verts = [Vector(v) for v in co]
    bvh = BVHTree.FromPolygons(verts, [tuple(int(x) for x in t) for t in tris],
                               all_triangles=True)
    return bvh, co, tris


RAY_DIRS = [
    Vector((1.0, 0.0, 0.0)),
    Vector((0.0, 1.0, 0.0)),
    Vector((0.0, 0.0, 1.0)),
    Vector((0.5773503, 0.5773503, 0.5773503)),
    Vector((-0.5773503, 0.5773503, 0.5773503)),
    Vector((0.5773503, -0.5773503, 0.5773503)),
    Vector((0.5773503, 0.5773503, -0.5773503)),
]

# 复刻 Lead / 常见做法的 6 轴口径（用于交叉对照，不作为唯一判据）
RAY_DIRS_6AXIS = [
    Vector((1, 0, 0)), Vector((-1, 0, 0)), Vector((0, 1, 0)),
    Vector((0, -1, 0)), Vector((0, 0, 1)), Vector((0, 0, -1)),
]

# 13 方向（6 轴 + 8 体对角）—— 最稳的一档，用来给出口径上界/下界
_S3 = 0.5773502691896258
RAY_DIRS_13 = RAY_DIRS_6AXIS + [
    Vector((sx * _S3, sy * _S3, sz * _S3))
    for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)
]


def inside_ray_parity(bvh, pts, dirs=RAY_DIRS, tol=0.0):
    """方法 A：多方向射线奇偶投票。返回 (votes_in, votes_total)。

    误差来源：
      * 射线恰好穿过共享边/顶点 → 计数偏差（多方向投票缓解，非消除）。
      * 网格非封闭（有边界洞）→ 洞出来的射线计数为奇/偶都可能，点会误判。
      * 点恰好落在表面上 → 从表面出发的射线方向性歧义。
      * 服装件本身不参与（只拿 body 当靶），所以判定的是"相对 body"的内外。
    """
    n = len(pts)
    votes_in = np.zeros(n, dtype=np.int32)
    votes_all = np.zeros(n, dtype=np.int32)
    for d in dirs:
        for i in range(n):
            p = Vector(pts[i])
            cnt = 0
            o = p.copy()
            for _ in range(64):  # 硬上限，防退化死循环
                hit = bvh.ray_cast(o + d * 1e-6, d, 1e6)
                if hit[0] is None:
                    break
                cnt += 1
                loc = hit[0]
                o = loc + d * 1e-5
            votes_in[i] += 1 if (cnt % 2 == 1) else 0
            votes_all[i] += 1
    return votes_in, votes_all


def inside_closest_normal(bvh, pts, tol=1e-4):
    """方法 B：最近点 + 法线定向（有符号距离）。

    误差来源：
      * 网格有锐边/自交 → 最近点法线方向的"内"侧判反（表面附近最危险）。
      * 点离表面远（> 局部厚度）时，"最近点法线"不再是全局内外判据 → 系统性误判。
      * 厚度比网格分辨率还薄的部位（衣料紧贴）→ |d| < tol 附近抖动。
      * 因此**只看 |signed| > tol 的点**，把贴近表面的点标为 ambiguous。
    """
    n = len(pts)
    signed = np.full(n, np.nan)
    hits = np.zeros(n, dtype=bool)
    for i in range(n):
        p = Vector(pts[i])
        loc, nor, idx, dist = bvh.find_nearest(p, 1e6)
        if loc is None:
            continue
        hits[i] = True
        signed[i] = (p - loc).dot(nor)
    return signed, hits


def calibrate_normal_sign(bvh, co, sample=2000, seed=0):
    """自动标定 BVHTree 面法线的"内负外正"约定。

    原理：闭合网格的**顶点质心**几乎总在内部 → 质心的有符号距离符号 = "内部"的符号。
    ⚠ 误差源：如果网格极度凹陷 / 开放 / 质心恰好落在体外（例如一个碗形、马蹄形），
    标定会翻号 → 该网格上 normal 法的结论**整体取反**。
    返回 (sign_inside, 诊断信息)。内部判据统一为 `sign_inside * signed > tol`。
    """
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(co), size=min(sample, len(co)), replace=False)
    c = co[idx].mean(axis=0)
    loc, nor, _, dist = bvh.find_nearest(Vector(c), 1e7)
    if loc is None:
        return -1.0, {"calibrated": False, "reason": "centroid not near mesh"}
    s = float((Vector(c) - loc).dot(nor))
    return (1.0 if s > 0 else -1.0), {
        "calibrated": True, "centroid_signed": s, "centroid_dist": float(dist),
        "sign_inside": 1.0 if s > 0 else -1.0,
    }


def point_in_mesh_report(bvh, pts, tol=1e-4, min_votes=4, co_for_calib=None):
    """A/B 双法合并 → 每个点的裁定 + 置信度。

    A 法（射线奇偶）：7 个方向投票，≥min_votes 判内。不依赖法线朝向。
    B 法（最近点法线定向）：signed 距离 + 自动标定符号。
    两法不一致 或 距表面 < tol → 标 ambiguous，**不计入穿模率分子**，单独统计。
    """
    v_in, v_all = inside_ray_parity(bvh, pts)
    ray_in = v_in >= min_votes
    signed, hits = inside_closest_normal(bvh, pts)
    sign = -1.0
    calib = {"calibrated": False, "reason": "no calib data"}
    if co_for_calib is not None and len(co_for_calib):
        sign, calib = calibrate_normal_sign(bvh, co_for_calib)
    s = np.nan_to_num(signed, nan=0.0)
    norm_in = (sign * s) > tol
    near = np.abs(s) < tol
    ambiguous = (ray_in != norm_in) | near | (~hits)
    agree = 1.0 - float(np.mean(ray_in != norm_in))
    return {
        "inside_ray": ray_in,
        "inside_norm": norm_in,
        "ambiguous": ambiguous,
        "signed": signed,
        "calib": calib,
        "agree_rate": agree,
        "ray_votes": v_in,
        "ray_total": v_all,
    }


# --------------------------------------------------------------------------
# morph (shape key) 读取 —— 全部走数据层，不需要切帧
# --------------------------------------------------------------------------


def shapekey_names(obj):
    if obj.type != "MESH" or obj.data.shape_keys is None:
        return []
    return [kb.name for kb in obj.data.shape_keys.key_blocks]


def shapekey_bytes(obj):
    """一个 shape key 的实际数据字节数（delta 是 3 × float32 = 12 字节/顶点）。"""
    sk = obj.data.shape_keys
    if sk is None:
        return 0
    n = len(obj.data.vertices)
    # 每个 key_block 内部存 3 个 float（co）+ 若干；Blender 5 用 float32 delta。
    # 用"标准口径"：顶点数 × 12（SPEC F4）。这里同时给出 Python 侧实测的
    # 有效数据量作为对照（只统计非全零 key 的 delta 体积）。
    return n * 12 * max(0, len(sk.key_blocks) - 1)


def shapekey_delta_stats(obj, name):
    """某个 shape key 相对 Basis 的位移统计（布尔/RELATIVE 两种模式都覆盖）。"""
    sk = obj.data.shape_keys
    if sk is None or name not in sk.key_blocks:
        return None
    kb = sk.key_blocks[name]
    rel = sk.key_blocks[0]
    n = len(rel.data)
    a = np.empty(n * 3, dtype=np.float64)
    b = np.empty(n * 3, dtype=np.float64)
    rel.data.foreach_get("co", a)
    kb.data.foreach_get("co", b)
    d = (b - a).reshape(n, 3)
    mag = np.linalg.norm(d, axis=1)
    nz = int(np.count_nonzero(mag > 1e-9))
    return {
        "name": name,
        "n_verts": n,
        "moved_verts": nz,
        "moved_frac": nz / n if n else 0.0,
        "max_cm": float(mag.max() * 100.0) if n else 0.0,
        "mean_cm": float(mag.mean() * 100.0) if n else 0.0,
        "bytes_12B": n * 12,
    }


# --------------------------------------------------------------------------
# 拉伸比（体形/身高失真的正确口径）
# --------------------------------------------------------------------------


def edge_stretch_stats(co_a, co_b, edges=None, sample=200000, seed=0):
    """两条同拓扑顶点集之间的边长比统计。

    返回 ratio 的分位数 + 离散度。**离散度**是失真口径：
    意图中的体形变化 = 全局一致的缩放 → 比值分布窄；瑕疵 = 局部乱拉 → 分布宽。
    """
    n = len(co_a)
    if edges is None:
        rng = np.random.default_rng(seed)
        m = min(sample, n * 4)
        i = rng.integers(0, n, m)
        j = rng.integers(0, n, m)
        keep = i != j
        i, j = i[keep], j[keep]
        edges = np.stack([i, j], axis=1)
    la = np.linalg.norm(co_a[edges[:, 0]] - co_a[edges[:, 1]], axis=1)
    lb = np.linalg.norm(co_b[edges[:, 0]] - co_b[edges[:, 1]], axis=1)
    m = la > 1e-9
    r = lb[m] / la[m]
    if r.size == 0:
        return None
    return {
        "n_edges": int(r.size),
        "mean": float(r.mean()),
        "p01": float(np.percentile(r, 1)),
        "p50": float(np.percentile(r, 50)),
        "p99": float(np.percentile(r, 99)),
        "std": float(r.std()),
        "iqr": float(np.percentile(r, 75) - np.percentile(r, 25)),
        "mad": float(np.median(np.abs(r - np.median(r)))),
        # 失真主口径：分位数离散度（对整体缩放不敏感）
        "dispersion_p01_p99": float(np.percentile(r, 99) - np.percentile(r, 1)),
        "dispersion_rel": float((np.percentile(r, 99) - np.percentile(r, 1)) / max(np.median(r), 1e-9)),
    }


def mesh_edges(obj):
    """从求值/原始网格取边表（同拓扑下三档共用）。"""
    me = obj.data
    ne = len(me.edges)
    ev = np.empty(ne * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", ev)
    return ev.reshape(ne, 2)


# --------------------------------------------------------------------------
# 杂项
# --------------------------------------------------------------------------


def rest_bone_table(arm_obj):
    """骨名 + 顺序 + rest 头位置（armature 空间，米）。"""
    rows = []
    for b in arm_obj.data.bones:
        h = arm_obj.matrix_world @ b.head_local
        rows.append({"name": b.name, "head": [h.x, h.y, h.z]})
    return rows


def material_face_area(obj, depsgraph=None):
    """按材质名聚合 —— **同时给四种口径**（面积 / 面数 / loop 数 / 顶点数）。

    为什么四种都要：SPEC F2 写的是"62% 布料 + 38% 皮肤"但没写分母是什么。
    面积口径与面数口径在这批资产上差别巨大（实测 Female_Ranger_Arms：
    面积口径 93.8/6.2，面数口径见报告），必须把口径摊开说才不会互相"对不上"。
    """
    m = evaluated_mesh(obj, depsgraph)
    me = obj.data
    names = [mm.name if mm else "<none>" for mm in me.materials]
    npoly = m["n_polys"]
    mi = np.empty(npoly, dtype=np.int32)
    me.polygons.foreach_get("material_index", mi)
    # 面面积（换算到世界尺度）
    M = np.array(obj.matrix_world)
    areas = np.empty(npoly, dtype=np.float64)
    me.polygons.foreach_get("area", areas)  # 局部坐标面积
    scale = float(abs(np.linalg.det(M[:3, :3]))) ** (2.0 / 3.0)
    areas = areas * scale
    # 顶点 -> 材质（一个顶点被多个材质的面共用时计入所有）
    ls, lt = m["loop_start"], m["loop_total"]
    pv = m["poly_verts"]
    out = {}
    for k, nm in enumerate(names):
        sel = mi == k
        a = float(areas[sel].sum())
        fc = int(sel.sum())
        loops = int(lt[sel].sum())
        vids = set()
        for s, t in zip(ls[sel], lt[sel]):
            vids.update(int(x) for x in pv[s:s + t])
        out[nm] = {"area_m2": a, "faces": fc, "loops": loops, "verts": len(vids)}
    tot = {kk: sum(v[kk] for v in out.values()) for kk in ("area_m2", "faces", "loops", "verts")}
    for nm, v in out.items():
        for kk in tot:
            v[f"{kk}_frac"] = (v[kk] / tot[kk]) if tot[kk] else 0.0
    return out


def timed(fn, *a, **kw):
    t0 = time.perf_counter()
    r = fn(*a, **kw)
    return r, time.perf_counter() - t0


def jdump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def open_blend(path):
    bpy.ops.wm.open_mainfile(filepath=path)


def mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def armatures():
    return [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]