"""tools/3d/garment/autofit.py —— ② 贴合（A 路线主方案）：自动去穿模外推 + 失真修复

链路（SPEC §4.1 ② 的可自动化替代，见 Lead FINDINGS §9）：
   剥离皮肤面 → 骨空间 refit → 反复把落在体内的布料顶点推到体表外 → （可选）失真修复

三条方法学纪律（都来自 Lead FINDINGS §9.4 的两个"自我欺骗"，已实际踩到）
------------------------------------------------------------------------
1. **推与量必须用不同判据**（否则量出假的 0%）
     推：最近点 + 面法线定向（`(p−loc)·n < 0` ⇒ 在体内）
     量：6 方向**射线奇偶**（独立实现，见 common.penetration）
   本脚本两种都给，但报告里 `penetration_verify_ray` 才是验收口径。
2. **失真必须相对"真·原始坐标"** —— 加载时就快照 `V_orig`，
   绝不能用"修改后"的坐标当 rest（那样拉伸比恒为 1.000，是纯 bug）。
3. **凸出深度统计必须带距离闸门**（默认 5 cm），
   否则会把"脖子到护肩的距离"也算进来，p95 会飙到 60 cm 这种荒谬值。

用法
----
  Blender -b --factory-startup --python tools/3d/garment/autofit.py -- \
      [--in tmp/garment/work/stripped] [--out tmp/garment/work/autofit] \
      [--gap 0.008] [--rounds 3] [--gate 0.05] \
      [--smooth-rounds 0] [--smooth-factor 0.5] [--rays 6]

`--smooth-rounds N > 0` 打开"受限 Laplacian 平滑"：只对**被推动过**的顶点做
邻域平均，随后**重新外推**（否则会被拉回体内），如此交替 N 轮。
"""
import argparse
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
    ap = argparse.ArgumentParser(prog="autofit.py")
    ap.add_argument("--in", dest="ind", default=os.path.join(C.WORK, "stripped"))
    ap.add_argument("--out", dest="outd", default=os.path.join(C.WORK, "autofit"))
    ap.add_argument("--gap", type=float, default=0.008, help="外推后留的间隙（米）")
    ap.add_argument("--rounds", type=int, default=3, help="外推轮数")
    ap.add_argument("--gate", type=float, default=0.05, help="距离闸门（米）")
    ap.add_argument("--smooth-rounds", type=int, default=0)
    ap.add_argument("--smooth-factor", type=float, default=0.5)
    ap.add_argument("--smooth-mode", default="taubin", choices=["taubin", "laplacian"])
    ap.add_argument("--smooth-mu", type=float, default=0.53)
    ap.add_argument("--rays", type=int, default=6)
    ap.add_argument("--only", default=None)
    return ap.parse_args(argv)


# ————————————————————————————————————————————————————————————
def load_body(sex):
    path = os.path.join(C.BODIES, f"Body_{sex}_Standard.blend")
    arm_name, body_name = f"RIG_Body_{sex}_Standard", f"Body_{sex}"
    if body_name not in bpy.data.objects:
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = [arm_name, body_name]
        for o in dst.objects:
            if o is not None:
                bpy.context.scene.collection.objects.link(o)
        bpy.context.view_layer.update()
    body = bpy.data.objects[body_name]
    C.clear_shape_values(body)
    pts, tris = C.eval_mesh(body, want_tris=True)
    return bpy.data.objects[arm_name], body, pts, tris, C.bvh_from_pts_tris(pts, tris)


def nn_inside_flags(pts, tree, gate):
    """【推的判据】最近点 + 面法线定向。返回 (flags, 超出闸门的点数)。"""
    flags = []
    gated = 0
    for p in pts:
        loc, nor, fi, dist = tree.find_nearest(p)
        if loc is None:
            flags.append(False)
            continue
        if (p - loc).dot(nor) < 0.0:
            if dist > gate:
                gated += 1
                flags.append(False)      # 闸门内才推，避免被"脖子到护肩"这种远点拽飞
            else:
                flags.append(True)
        else:
            flags.append(False)
    return flags, gated


def push_round(pts, tree, gate, gap):
    """把落在体内的顶点沿最近面法线推到 `体表 + gap`。返回 (新点, 统计)。"""
    flags, gated = nn_inside_flags(pts, tree, gate)
    out = []
    moved = []
    for p, inside in zip(pts, flags):
        if not inside:
            out.append(p.copy())
            continue
        loc, nor, fi, dist = tree.find_nearest(p)
        if loc is None or nor.length < 1e-12:
            out.append(p.copy())
            continue
        q = loc + nor.normalized() * gap
        out.append(q)
        moved.append((q - p).length)
    st = {"pushed": len(moved), "gated_out": gated,
          "push_mean_cm": round(100 * sum(moved) / len(moved), 4) if moved else 0.0,
          "push_p95_cm": round(100 * sorted(moved)[int(0.95 * (len(moved) - 1))], 4) if moved else 0.0,
          "push_max_cm": round(100 * max(moved), 4) if moved else 0.0}
    return out, st, flags


def protrusion_depth(pts, tree, gate):
    """凸出深度分布（只在闸门内、且在体内的点）—— FINDINGS §9.1 的口径。"""
    ds = []
    for p in pts:
        loc, nor, fi, dist = tree.find_nearest(p)
        if loc is None or dist > gate:
            continue
        if (p - loc).dot(nor) < 0.0:
            ds.append(dist)
    if not ds:
        return {"n": 0}
    ds.sort()
    return {"n": len(ds), "median_cm": round(100 * ds[len(ds) // 2], 3),
            "p75_cm": round(100 * ds[int(0.75 * (len(ds) - 1))], 3),
            "p95_cm": round(100 * ds[int(0.95 * (len(ds) - 1))], 3),
            "max_cm": round(100 * ds[-1], 3),
            "gate_cm": round(100 * gate, 2)}


def edge_list(obj):
    return [(e.vertices[0], e.vertices[1]) for e in obj.data.edges]


def stretch_report(pts_orig, pts_new, edges):
    """边长拉伸比 —— **相对真·原始坐标**（FINDINGS §9.4 的教训）。"""
    rs = []
    for a, b in edges:
        l0 = (pts_orig[a] - pts_orig[b]).length
        if l0 > 1e-7:
            rs.append((pts_new[a] - pts_new[b]).length / l0)
    if not rs:
        return {}
    rs.sort()
    n = len(rs)
    return {"_rs": rs, "n": n,
            "p50": round(rs[n // 2], 4), "p95": round(rs[int(0.95 * (n - 1))], 4),
            "p99": round(rs[int(0.99 * (n - 1))], 4), "max": round(rs[-1], 4),
            "min": round(rs[0], 4),
            "gt1p5": sum(1 for r in rs if r > 1.5),
            "gt2": sum(1 for r in rs if r > 2.0),
            "gt3": sum(1 for r in rs if r > 3.0),
            "gt1p5_frac": round(sum(1 for r in rs if r > 1.5) / n, 6)}


def verify_pen(pts, bvh, bpts, btris, rays):
    """【量/验收的判据】射线奇偶（与推的判据相互独立）。"""
    p = C.penetration(pts, bvh, bpts, btris, sample_rays=rays, nearest_normal=True)
    return {"ray": round(p["ray_rate"], 6), "nn": round(p["nn_rate"], 6),
            "ray_inside": p["ray_inside"], "n": p["n"],
            "ambiguous": p["ray_ambiguous"], "disagree": p["disagree"]}


def neighbours(obj):
    nb = [[] for _ in obj.data.vertices]
    for e in obj.data.edges:
        a, b = e.vertices
        nb[a].append(b)
        nb[b].append(a)
    return nb


def relax_pass(pts, nb, moved_mask, factor):
    """一次受限 Laplacian 松弛（只动"被推动过"的顶点）。factor 可为负（Taubin 的 μ 步）。"""
    new = list(pts)
    for i, m in enumerate(moved_mask):
        if not m or not nb[i]:
            continue
        avg = Vector()
        for j in nb[i]:
            avg += pts[j]
        avg /= len(nb[i])
        new[i] = pts[i].lerp(avg, factor)
    return new


def taubin_pass(pts, nb, moved_mask, lam, mu):
    """Taubin λ|μ 平滑：正步 + 负步交替，抵消纯 Laplacian 的收缩。

    ⚠ 实测：纯 Laplacian（只做正步）会把顶点区域整体收缩 ——
      边长拉伸 p50 从 1.000 掉到 0.821，还会制造 max≈465× 的塌缩边（近乎压成 0 长）。
    """
    return relax_pass(relax_pass(pts, nb, moved_mask, lam), nb, moved_mask, mu)


def guard_edges(pts, prev, inc_edges, pts_orig, lo=0.70, hi=1.60):
    """边长护栏：任何松弛/外推步若使某条原始边拉伸比越界，就把该顶点退回落点。

    这是防止"平滑制造塌缩边/尖刺"的保险丝 —— 不加它会出现 465× 的荒谬拉伸比。
    """
    out = list(pts)
    reverted = 0
    bad_edge = {}
    for i, es in inc_edges.items():
        for a, b in es:
            l0 = (pts_orig[a] - pts_orig[b]).length
            if l0 < 1e-7:
                continue
            pa, pb = out[a], out[b]
            r = (pa - pb).length / l0
            if r < lo or r > hi:
                out[i] = prev[i]
                reverted += 1
                bad_edge[(a, b)] = round(r, 3)
                break
    return out, reverted, bad_edge


def incident_edges(obj, moved_mask):
    inc = {}
    for e in obj.data.edges:
        a, b = e.vertices
        if moved_mask[a]:
            inc.setdefault(a, []).append((a, b))
        if moved_mask[b]:
            inc.setdefault(b, []).append((a, b))
    return inc


# ————————————————————————————————————————————————————————————
def run(a):
    os.makedirs(a.outd, exist_ok=True)
    allrec = []
    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        src = os.path.join(a.ind, f"Outfit_{outfit}.blend")
        C.log(f"\n{'='*104}\n[autofit] {outfit}   <- {C.rel(src)}")
        bpy.ops.wm.open_mainfile(filepath=src)
        reg_arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        outfit_meshes = [o.name for o in bpy.data.objects if o.type == 'MESH']
        std_arm, body, bpts, btris, bvh = load_body(sex)
        bmap = C.bone_rest_map(reg_arm, std_arm)
        rec = {"outfit": outfit, "sex": sex, "params": {
            "gap_cm": round(100 * a.gap, 3), "rounds": a.rounds,
            "gate_cm": round(100 * a.gate, 2), "rays": a.rays,
            "smooth_rounds": a.smooth_rounds, "smooth_factor": a.smooth_factor},
            "push_criterion": "最近点+面法线定向（(p−loc)·n<0 视为体内）",
            "verify_criterion": "6 方向射线奇偶多数票（独立实现）",
            "rest_stats": C.bone_rest_stats(reg_arm, std_arm), "parts": []}

        for name in sorted(outfit_meshes):
            o = bpy.data.objects[name]
            p_orig = C.eval_pts(o)                       # ★ 真·原始坐标快照
            edges = edge_list(o)
            nb = neighbours(o)

            # 阶段 1：骨空间 refit
            p_refit, _ = C.skin_points(o, p_orig, bmap)
            # 阶段 2：N 轮外推
            stages = {"orig": p_orig, "refit": p_refit}
            pts = p_refit
            rounds = []
            for r in range(a.rounds):
                pts, st, _ = push_round(pts, bvh, a.gate, a.gap)
                st["round"] = r + 1
                st["pen_ray_after"] = verify_pen(pts, bvh, bpts, btris, a.rays)["ray"]
                rounds.append(st)
            stages["autofit"] = pts
            # 阶段 3：失真修复
            if a.smooth_rounds > 0:
                moved_mask = [False] * len(p_orig)
                for i, (x, y) in enumerate(zip(pts, p_orig)):
                    if (x - y).length > 1e-7:
                        moved_mask[i] = True
                inc = incident_edges(o, moved_mask)
                sm = {"mode": a.smooth_mode, "rounds": a.smooth_rounds,
                      "lambda": a.smooth_factor, "mu": -a.smooth_mu if a.smooth_mode == "taubin" else None,
                      "guard_lo": 0.70, "guard_hi": 1.60, "reverted": 0, "bad_edges": {}}
                for _ in range(a.smooth_rounds):
                    prev = pts
                    if a.smooth_mode == "taubin":
                        cand = taubin_pass(pts, nb, moved_mask, a.smooth_factor,
                                           -a.smooth_mu)
                    else:
                        cand = relax_pass(pts, nb, moved_mask, a.smooth_factor)
                    cand, rev, bad = guard_edges(cand, prev, inc, p_orig)
                    sm["reverted"] += rev
                    sm["bad_edges"].update({f"{a_}_{b_}": r for (a_, b_), r in
                                            list(bad.items())[:20]})
                    pts, _, _ = push_round(cand, bvh, a.gate, a.gap)
                stages["smoothed"] = pts
                rec.setdefault("smooth_info", {})[name] = sm
            final = stages["smoothed"] if "smoothed" in stages else pts

            part = {"part": name, "verts": len(p_orig), "edges": len(edges),
                    "protrusion_depth_orig": protrusion_depth(p_orig, bvh, a.gate),
                    "rounds": rounds, "stages": {}}
            for tag, sp in stages.items():
                part["stages"][tag] = {
                    "penetration": verify_pen(sp, bvh, bpts, btris, a.rays),
                    "stretch_vs_orig": stretch_report(p_orig, sp, edges),
                    "move_vs_orig_cm": {
                        "mean": round(100 * sum((x - y).length for x, y in zip(sp, p_orig)) / len(sp), 4),
                        "max": round(100 * max((x - y).length for x, y in zip(sp, p_orig)), 4)}}
            rec["parts"].append(part)
            sg = part["stages"]
            C.log(f"  * {name:32s} v={len(p_orig):5d}  凸出深度中位 "
                  f"{part['protrusion_depth_orig'].get('median_cm', 0):5.2f} cm")
            for tag in ("orig", "refit", "autofit", "smoothed"):
                if tag not in sg:
                    continue
                s = sg[tag]
                C.log(f"      {tag:9s} 穿模[射线奇偶] {100*s['penetration']['ray']:6.2f}% "
                      f"(最近点 {100*s['penetration']['nn']:6.2f}%)  "
                      f"拉伸 p50 {s['stretch_vs_orig'].get('p50', 0):.3f} "
                      f"p95 {s['stretch_vs_orig'].get('p95', 0):.3f} "
                      f"p99 {s['stretch_vs_orig'].get('p99', 0):.3f} "
                      f"max {s['stretch_vs_orig'].get('max', 0):7.3f}  "
                      f">2× 边 {s['stretch_vs_orig'].get('gt2', 0):5d}  "
                      f"位移 mean/max {s['move_vs_orig_cm']['mean']:.3f}/"
                      f"{s['move_vs_orig_cm']['max']:.3f} cm")
            # 写真（最终态）
            C.apply_points(o, final)

        # 全场（该套服装所有件的边汇总）拉伸分布 —— 与 Lead FINDINGS §9.3 口径一致
        def _pool(tag):
            acc = []
            for pt_ in rec["parts"]:
                acc += pt_["stages"].get(tag, {}).get("stretch_vs_orig", {}).get("_rs", [])
            if not acc:
                return None
            acc.sort()
            n = len(acc)
            return {"n": n, "p50": round(acc[n // 2], 4),
                    "p95": round(acc[int(0.95 * (n - 1))], 4),
                    "p99": round(acc[int(0.99 * (n - 1))], 4),
                    "max": round(acc[-1], 4),
                    "gt1p5": sum(1 for r in acc if r > 1.5),
                    "gt2": sum(1 for r in acc if r > 2.0),
                    "gt3": sum(1 for r in acc if r > 3.0)}
        rec["pooled_stretch"] = {t: _pool(t) for t in ("orig", "refit", "autofit", "smoothed")}
        for t, v in rec["pooled_stretch"].items():
            if v:
                C.log(f"  ── 全场边拉伸 [{t:9s}] n={v['n']:6d}  p50 {v['p50']:.3f}  p95 {v['p95']:.3f}  "
                      f"p99 {v['p99']:.3f}  max {v['max']:8.3f}  >1.5× {v['gt1p5']:5d}  "
                      f">2× {v['gt2']:4d}  >3× {v['gt3']:4d}")
        # 顶点加权合计
        tot = sum(p["verts"] for p in rec["parts"])
        rec["aggregate"] = {}
        for tag in ("orig", "refit", "autofit", "smoothed"):
            num = sum(p["verts"] * p["stages"][tag]["penetration"]["ray"]
                      for p in rec["parts"] if tag in p["stages"])
            den = sum(p["verts"] for p in rec["parts"] if tag in p["stages"])
            if den:
                rec["aggregate"][tag] = {"verts": den,
                                         "penetration_ray": round(num / den, 6)}
        C.log(f"  ── 合计（顶点加权，射线奇偶）：" + "  ".join(
            f"{k} {100*v['penetration_ray']:.2f}%" for k, v in rec["aggregate"].items()))
        for t, v in rec["pooled_stretch"].items():
            if v:
                C.log(f"  ── 全场边拉伸 [{t:9s}] n={v['n']:6d}  p50 {v['p50']:.3f}  p95 {v['p95']:.3f}  "
                      f"p99 {v['p99']:.3f}  max {v['max']:8.3f}  >1.5× {v['gt1p5']:5d}  "
                      f">2× {v['gt2']:4d}  >3× {v['gt3']:4d}")

        for pt_ in rec["parts"]:
            for st_ in pt_["stages"].values():
                st_.get("stretch_vs_orig", {}).pop("_rs", None)
            pt_.pop("_rs", None)
        for n in (f"Body_{sex}", f"RIG_Body_{sex}_Standard", "Icosphere"):
            if n in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
        C.purge_orphans()
        out = os.path.join(a.outd, f"Outfit_{outfit}.blend")
        C.save_blend(out)
        rec["out"] = C.rel(out)
        allrec.append(rec)

    p = os.path.join(a.outd, "autofit_report.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"tool": "autofit.py",
                   "spec": "assets/3d/rig/SPEC.md v1.0 + Lead FINDINGS §9（A 路线）",
                   "methodology": [
                       "推的判据 = 最近点+面法线定向；量的判据 = 6 方向射线奇偶（互相独立，防自我实现）",
                       "失真拉伸比一律相对加载时的真·原始坐标 V_orig",
                       "凸出深度统计带距离闸门，避免把远距离错绑点算进来"],
                   "outfits": allrec}, f, ensure_ascii=False, indent=2)
    C.log(f"\n报告 → {C.rel(p)}\nDONE")


run(parse_args())