"""tools/3d/garment/probe_metric.py —— 度量本身的体检（噪声底 + 闭合性 + 独立判据）

为什么必须先做这一步
--------------------
"穿模率"是本次全部结论的基石。若度量本身有 3–5% 的噪声、或标准体网格不闭合
导致射线奇偶漏判，那么 10.34% / 29.58% / 0.14% 这些数字都无法解释。
Lead 的 FINDINGS §7/§8.4 明确要求：报绝对数字必须带噪声底与口径。

本工具做 4 件事
--------------
① 标准体网格体检：边界边（= 不闭合 → 射线奇偶会漏）、非流形边，并给出边界边 z 分布，
   定位"漏"发生在哪个部位。
② 噪声底：造一个"必然在体外"的合成壳（躯干面片沿顶点法线外推 1.5 cm），量误判率；
   另加"在体表上（外推 0）"与"体表自身顶点"两个退化对照。
③ 判据独立性：最近点+法线 vs 射线奇偶（6 方向）交叉表 + 分歧率。
④ **Arms 薄壳疑点**（Lead FINDINGS §8.3 未决）：袖子 60% 是不是薄壳/漏判伪影？
   两个独立检验：
     (a) 把标准体的洞补上（holes_fill）再测 —— 若数值不变，说明不是"漏"造成的；
     (b) 与任何内外判据无关的「骨轴径向半径」检验 —— 在上臂骨轴上按轴向参数 t 比较
         布料半径 r_cloth(t) 与身体半径 r_body(t)。r_cloth < r_body ⇒ 袖子确实在胳膊里。

用法
----
  Blender -b --factory-startup --python tools/3d/garment/probe_metric.py -- \
      [--out tmp/garment/work/probe_metric.json] [--only Female_Ranger] [--shell-out 0.015]
"""
import argparse
import bmesh
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="probe_metric.py")
    ap.add_argument("--out", default=os.path.join(C.WORK, "probe_metric.json"))
    ap.add_argument("--only", default=None)
    ap.add_argument("--shell-out", type=float, default=0.015)
    ap.add_argument("--stripped", default=os.path.join(C.WORK, "stripped"))
    return ap.parse_args(argv)


# ————————————————————————————————————————————————————————————
def mesh_health(pts, tris):
    ecnt = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            k = (a, b) if a < b else (b, a)
            ecnt[k] = ecnt.get(k, 0) + 1
    bnd = [k for k, v in ecnt.items() if v == 1]
    nonman = [k for k, v in ecnt.items() if v > 2]
    hist = {}
    for a, b in bnd:
        z = 0.5 * (pts[a].z + pts[b].z)
        k = round(math.floor(z * 10) / 10, 1)
        hist[k] = hist.get(k, 0) + 1
    return {"edges": len(ecnt), "boundary_edges": len(bnd),
            "nonmanifold_edges": len(nonman), "closed": len(bnd) == 0,
            "boundary_z_hist": {str(k): v for k, v in sorted(hist.items())}}


def vertex_normals(pts, tris):
    acc = [Vector() for _ in pts]
    for t in tris:
        a, b, c = (pts[t[0]], pts[t[1]], pts[t[2]])
        n = (b - a).cross(c - a)
        for i in t:
            acc[i] = acc[i] + n
    return [n.normalized() if n.length > 1e-12 else Vector((0, 0, 1)) for n in acc]


def shell_from_faces(pts, tris, z0, z1, gap, vn):
    keep = [t for t in tris if all(z0 <= pts[i].z <= z1 for i in t)]
    used = sorted({i for t in keep for i in t})
    remap = {g: l for l, g in enumerate(used)}
    return ([pts[i] + vn[i] * gap for i in used],
            [tuple(remap[i] for i in t) for t in keep])


def full_pen(pts, bvh, bpts, btris, rays=6):
    p = C.penetration(pts, bvh, bpts, btris, sample_rays=rays)
    return {"ray": round(p["ray_rate"], 6), "nn": round(p["nn_rate"], 6),
            "ray_inside": p["ray_inside"], "n": p["n"],
            "ambiguous": p["ray_ambiguous"], "disagree": p["disagree"]}


def closed_body(bpts, btris):
    """把标准体的洞补上 → "闭合版"身体，用来判断 60% 是不是"漏"造成的。"""
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in bpts]
    bm.verts.ensure_lookup_table()
    for t in btris:
        try:
            bm.faces.new([verts[t[0]], verts[t[1]], verts[t[2]]])
        except ValueError:
            pass
    bm.edges.ensure_lookup_table()
    holes = [e for e in bm.edges if len(e.link_faces) == 1]
    filled = 0
    if holes:
        try:
            filled = len(bmesh.ops.holes_fill(bm, edges=holes).get("faces", []))
        except Exception as e:                                  # pragma: no cover
            C.log(f"    holes_fill 失败：{e}")
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    npts = [v.co.copy() for v in bm.verts]
    tris, ngons = [], 0
    for f in bm.faces:
        vs = [v.index for v in f.verts]
        if len(vs) == 3:
            tris.append(tuple(vs))
        else:
            ngons += 1
            for k in range(1, len(vs) - 1):      # 扇形三角化
                tris.append((vs[0], vs[k], vs[k + 1]))
    bm.free()
    return npts, tris, {"holes_edges": len(holes), "filled_faces": filled,
                        "ngons_triangulated": ngons}


def weight_select(obj, groups, thresh=0.5):
    """按顶点组权重选点 —— 只取"确实属于这条手臂"的网格点。

    ⚠ 第一版直接用"投影落在骨轴 slab 内"筛点，把躯干和另一条手臂也算进来了
      （身体 r(t=0) 报出 90.8 cm 这种荒谬值）。必须用权重筛。
    """
    names = [g.name for g in obj.vertex_groups]
    idx = {names.index(n) for n in groups if n in names}
    if not idx:
        return []
    out = []
    for v in obj.data.vertices:
        w = sum(g.weight for g in v.groups if g.group in idx)
        if w >= thresh:
            out.append(v.index)
    return out


def radial_profile(pts, arm, bone_name, sel=None, bins=10):
    """完全独立的检验：沿骨轴比较径向半径（与任何内外判据无关）。

    sel 给定时只统计这些顶点 index（= 按权重选出的"这条手臂"的点）。
    """
    b = arm.data.bones[bone_name]
    h = b.head_local
    ax = b.tail_local - h
    L = ax.length
    if L < 1e-9:
        return None
    ax = ax / L
    acc = {}
    rng = sel if sel is not None else range(len(pts))
    for i in rng:
        p = pts[i]
        d = p - h
        u = d.dot(ax)
        if u < -0.02 * L or u > 1.02 * L:
            continue
        r = (d - ax * u).length
        k = round(min(1.0, max(0.0, u / L)) * bins) / bins
        acc.setdefault(k, []).append(r)
    return {str(k): round(100 * sum(v) / len(v), 3) for k, v in sorted(acc.items())}


# ————————————————————————————————————————————————————————————
def main():
    a = parse_args()
    out = {"tool": "probe_metric.py",
           "metrics": {"ray": "射线奇偶（6 方向多数票）：穿过次数为奇数 = 体内",
                       "nn": "最近点 + 面法线定向：(p−loc)·n < 0 = 体内"},
           "bodies": {}, "noise_floor": {}, "arms_thin_shell": {}}

    for sex in ("Female", "Male"):
        C.log(f"\n{'='*104}\n[体检] 标准体 {sex}")
        bpy.ops.wm.open_mainfile(filepath=os.path.join(C.BODIES, f"Body_{sex}_Standard.blend"))
        body = bpy.data.objects[f"Body_{sex}"]
        bpts, btris = C.eval_mesh(body, want_tris=True)
        bvh = C.bvh_from_pts_tris(bpts, btris)
        health = mesh_health(bpts, btris)
        vn = vertex_normals(bpts, btris)
        C.log(f"  {body.name}: {len(bpts)} 顶点 / {len(btris)} 三角面")
        C.log(f"  边 {health['edges']}  边界边 {health['boundary_edges']}  非流形边 "
              f"{health['nonmanifold_edges']}  闭合={health['closed']}")
        C.log(f"  边界边 z 分布（每 0.1 m）：{health['boundary_z_hist']}")

        # ② 噪声底
        nf = {}
        for tag, gap in (("shell_out_1p5cm", a.shell_out), ("shell_on_surface_0cm", 0.0)):
            spts, stris = shell_from_faces(bpts, btris, 0.60, 1.50, gap, vn)
            if not spts:
                continue
            row = full_pen(spts, bvh, bpts, btris)
            row.update({"shell_verts": len(spts), "gap_cm": round(gap * 100, 2)})
            nf[tag] = row
            C.log(f"  噪声底 [{tag:22s}] {len(spts):5d} 点  射线奇偶 {100*row['ray']:6.2f}%  "
                  f"最近点 {100*row['nn']:6.2f}%  分歧 {row['disagree']:5d}  歧义 {row['ambiguous']}")
        # 两个"构造上必然在体外"的对照（检验判据本身有没有系统性偏差）
        far = [p + Vector((0, 0, 10.0)) for p in bpts]
        nf["body_translated_10m"] = full_pen(far, bvh, bpts, btris)
        C.log(f"  对照 [整体平移 +10 m，必然在体外]  射线奇偶 "
              f"{100*nf['body_translated_10m']['ray']:6.2f}%  最近点 "
              f"{100*nf['body_translated_10m']['nn']:6.2f}%  ← 应为 0.00%")
        ctr = Vector((0, 0, 0.9))
        sph = []
        for i in range(0, 360, 12):
            for j in range(10, 171, 12):
                a1, a2 = math.radians(i), math.radians(j)
                sph.append(ctr + Vector((5 * math.sin(a2) * math.cos(a1),
                                         5 * math.sin(a2) * math.sin(a1),
                                         5 * math.cos(a2))))
        nf["sphere_r5m"] = full_pen(sph, bvh, bpts, btris)
        C.log(f"  对照 [半径 5 m 球面，必然在体外]  射线奇偶 "
              f"{100*nf['sphere_r5m']['ray']:6.2f}%  最近点 "
              f"{100*nf['sphere_r5m']['nn']:6.2f}%  ← 应为 0.00%")
        nf["body_own_vertices"] = full_pen(bpts, bvh, bpts, btris)
        C.log(f"  退化对照 [体表自身顶点]          射线奇偶 "
              f"{100*nf['body_own_vertices']['ray']:6.2f}%  最近点 "
              f"{100*nf['body_own_vertices']['nn']:6.2f}%  ← 贴面点的判据噪声")
        out["noise_floor"][sex] = nf

        # ④ 闭合版身体
        cpts, ctris, cinfo = closed_body(bpts, btris)
        cbvh = C.bvh_from_pts_tris(cpts, ctris)
        ch = mesh_health(cpts, ctris)
        C.log(f"  闭合版身体：补 {cinfo['holes_edges']} 条边界边 → 新增 {cinfo['filled_faces']} 面"
              f"（三角化 {cinfo['ngons_triangulated']} 个多边形），边界边 "
              f"{health['boundary_edges']} → {ch['boundary_edges']}")
        out["bodies"][sex] = {"health": health,
                              "closed_version": {**cinfo, "boundary_edges_after": ch["boundary_edges"]}}

        # ④ 把该性别的服装追加进来，做 Arms 薄壳检验
        for outfit, osex in C.OUTFITS:
            if osex != sex or (a.only and a.only != outfit):
                continue
            stripped = os.path.join(a.stripped, f"Outfit_{outfit}.blend")
            if not os.path.exists(stripped):
                C.log(f"  [skip] 缺 {C.rel(stripped)}（先跑 strip_skin.py）")
                continue
            C.log(f"\n  ---- Arms 薄壳检验：{outfit} ----")
            with bpy.data.libraries.load(stripped, link=False) as (src, dst):
                wanted = [n for n in src.objects]
                dst.objects = wanted
            appended = [o for o in dst.objects if o is not None]
            for o in appended:
                bpy.context.scene.collection.objects.link(o)
            bpy.context.view_layer.update()
            reg_arm = next(o for o in appended if o.type == 'ARMATURE')
            std_arm = bpy.data.objects[f"RIG_Body_{sex}_Standard"]
            bmap = C.bone_rest_map(reg_arm, std_arm)
            meshes = sorted([o for o in appended if o.type == 'MESH'], key=lambda x: x.name)
            rec = {"parts": {}}
            for o in meshes:
                if C.is_helper(o):
                    continue
                p0 = C.eval_pts(o)
                pbone, _ = C.skin_points(o, p0, bmap)
                r_open = full_pen(pbone, bvh, bpts, btris)
                r_closed = full_pen(pbone, cbvh, cpts, ctris)
                entry = {"open_body": r_open, "closed_body": r_closed}
                if o.name.endswith("Arms"):
                    # 按权重筛出"这条手臂"的点，再比径向半径
                    sel_c = weight_select(o, ("upperarm_l", "lowerarm_l", "hand_l"))
                    sel_c_r = weight_select(o, ("upperarm_r", "lowerarm_r", "hand_r"))
                    sel_b = weight_select(body, ("upperarm_l", "lowerarm_l", "hand_l"))
                    sel_b_r = weight_select(body, ("upperarm_r", "lowerarm_r", "hand_r"))
                    entry["radial_upperarm"] = {
                        "cloth_L": radial_profile(pbone, std_arm, "upperarm_l", sel_c),
                        "body_L": radial_profile(bpts, std_arm, "upperarm_l", sel_b),
                        "cloth_R": radial_profile(pbone, std_arm, "upperarm_r", sel_c_r),
                        "body_R": radial_profile(bpts, std_arm, "upperarm_r", sel_b_r),
                        "sel_counts": [len(sel_c), len(sel_b), len(sel_c_r), len(sel_b_r)]}
                rec["parts"][o.name] = entry
                C.log(f"    {o.name:32s} 开口身体 射线 {100*r_open['ray']:6.2f}% / 最近点 "
                      f"{100*r_open['nn']:6.2f}%  →  补洞后 射线 {100*r_closed['ray']:6.2f}% / "
                      f"最近点 {100*r_closed['nn']:6.2f}%")
                if "radial_upperarm" in entry:
                    rp = entry["radial_upperarm"]
                    C.log(f"        骨轴径向（按 arm 权重筛选，点数 布料/身体 L,R = "
                          f"{rp['sel_counts']}）")
                    C.log(f"          L 布料 r(t) cm: {rp['cloth_L']}")
                    C.log(f"          L 身体 r(t) cm: {rp['body_L']}")
            out["arms_thin_shell"][outfit] = rec
            # 清掉追加的对象，避免下次冲突
            for o in appended:
                if o.name in bpy.data.objects:
                    bpy.data.objects.remove(o, do_unlink=True)
            C.purge_orphans()

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    C.log(f"\n报告 → {C.rel(a.out)}\nDONE")


main()