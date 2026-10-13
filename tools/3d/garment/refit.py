"""tools/3d/garment/refit.py —— ② 贴合：骨空间重绑 与 几何贴合（分开实现、分开报数）

SPEC §4.1 ② 原本只要求骨空间重绑。Lead 的 FINDINGS.md 实测证明它**不够**
（女 Ranger 10.34%→10.34% no-op；男 Ranger 29.58%→19.49%），因为服装是按 Regular
体形剪裁的、标准体是 Superhero，形状关系不匹配。所以本工具把两件事**分开**：

  A. 骨空间重绑  bone        M_b = std.matrix_local @ reg.matrix_local⁻¹，p' = Σ w_b M_b p
                            → 只对齐骨架坐标，不改变网格形状关系
  B. 几何贴合    shrinkwrap  把布料顶点投影到标准体表面（NEAREST_SURFACEPOINT + offset）
                            → 强行改变形状关系；代价 = 布料失去厚度/褶皱（本工具量化它）

两种都跑，两种都报数（穿模率 + 代价指标）。

用法
----
  # 实测扫描：逐件 × 逐方法（含几何贴合代价）
  Blender -b --factory-startup --python tools/3d/garment/refit.py -- --sweep [--rays 3]

  # 按 policy 应用
  Blender -b --factory-startup --python tools/3d/garment/refit.py -- \
      [--in tmp/garment/work/stripped] [--out tmp/garment/work/refit] [--method auto|none|bone|shrinkwrap]
"""
import argparse
import json
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

POLICY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refit_policy.json")
SWEEP_OFFSETS = (0.0, 0.004, 0.010)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="refit.py")
    ap.add_argument("--in", dest="ind", default=os.path.join(C.WORK, "stripped"))
    ap.add_argument("--out", dest="outd", default=os.path.join(C.WORK, "refit"))
    ap.add_argument("--method", default="auto",
                    choices=["auto", "none", "bone", "shrinkwrap", "push"])
    ap.add_argument("--offset", type=float, default=0.004, help="shrinkwrap 外推量（米）")
    ap.add_argument("--sweep", action="store_true", help="只实测各方法，不落盘")
    ap.add_argument("--rays", type=int, default=5, help="ray parity 采样方向数")
    ap.add_argument("--only", default=None)
    ap.add_argument("--wrap-mode", default="OUTSIDE_SURFACE",
                    choices=["ON_SURFACE", "OUTSIDE_SURFACE", "INSIDE", "OUTSIDE"])
    return ap.parse_args(argv)


# ————————————————————————————————————————————————————————————
# 标准体加载（必须在 open_mainfile 之后调用 —— 重开文件会作废旧 datablock）
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
    arm = bpy.data.objects[arm_name]
    C.clear_shape_values(body)
    pts, tris = C.eval_mesh(body, want_tris=True)
    return arm, body, pts, tris, C.bvh_from_pts_tris(pts, tris)


# ————————————————————————————————————————————————————————————
# 度量
# ————————————————————————————————————————————————————————————
def gap_stats(g_pts, tree):
    ds = []
    for p in g_pts:
        loc, nor, fi, dist = tree.find_nearest(p)
        ds.append(dist if loc is not None else 0.0)
    if not ds:
        return {}
    ds.sort()
    return {"mean_cm": round(100 * sum(ds) / len(ds), 3),
            "median_cm": round(100 * ds[len(ds) // 2], 3),
            "p95_cm": round(100 * ds[int(0.95 * (len(ds) - 1))], 3),
            "max_cm": round(100 * ds[-1], 3)}


def measure(pts, tree, body_pts, body_tris, rays):
    pen = C.penetration(pts, tree, body_pts, body_tris, sample_rays=rays)
    return {"penetration_ray": round(pen["ray_rate"], 6),
            "penetration_nn": round(pen["nn_rate"], 6),
            "pen_ray_inside": pen["ray_inside"], "pen_n": pen["n"],
            "pen_ray_ambiguous": pen["ray_ambiguous"],
            "gap": gap_stats(pts, tree)}


def surface_cost(rest_pts, new_pts, tris):
    """几何贴合的代价指标 —— 布料是否失去厚度/褶皱。

    area_ratio        总面积比（投影到皮肤上会塌缩）
    normal_shift_deg  面法线相对 rest 的偏转（褶皱被压平的信号）
    """
    a0 = a1 = 0.0
    angs = []
    for t in tris:
        p0 = [rest_pts[i] for i in t]
        p1 = [new_pts[i] for i in t]
        a0 += (p0[1] - p0[0]).cross(p0[2] - p0[0]).length * 0.5
        a1 += (p1[1] - p1[0]).cross(p1[2] - p1[0]).length * 0.5
        n0 = (p0[1] - p0[0]).cross(p0[2] - p0[0])
        n1 = (p1[1] - p1[0]).cross(p1[2] - p1[0])
        if n0.length > 1e-12 and n1.length > 1e-12:
            angs.append(math.degrees(n0.angle(n1)))
    angs.sort()
    return {"area_ratio": round(a1 / a0, 5) if a0 > 0 else 0.0,
            "normal_shift_mean_deg": round(sum(angs) / len(angs), 3) if angs else 0.0,
            "normal_shift_p95_deg": round(angs[int(0.95 * (len(angs) - 1))], 3) if angs else 0.0,
            "normal_shift_max_deg": round(angs[-1], 3) if angs else 0.0}


def eval_tris_of(obj):
    return C.eval_mesh(obj, want_tris=True)


def shrinkwrap_points(obj, body, offset, wrap_mode='ON_SURFACE'):
    """复制对象 → 加 Shrinkwrap → depsgraph 求值取点（不动原对象）

    ⚠ 实测坑（本工具最重要的发现）：
      `NEAREST_SURFACEPOINT + offset` 在 Blender 5.2 是**有符号距离钳制**，
      不是"沿外法线推出" —— 原本在体内的顶点被推到「体内 0.4 cm」，
      内外关系原样保留 → **穿模率一点不降**（Body 8.26%→8.26%，Arms 60.32%→63.25%）。
      要真正治疗穿模必须 `wrap_mode='OUTSIDE_SURFACE'`（保证顶点在体外）。
    所以本函数同时支持两种 wrap_mode，扫描时两种都测、两种都报。
    """
    dup = obj.copy()
    dup.data = obj.data.copy()
    dup.name = obj.name + "__SW"
    bpy.context.scene.collection.objects.link(dup)
    m = dup.modifiers.new("SW", 'SHRINKWRAP')
    m.target = body
    m.wrap_method = 'NEAREST_SURFACEPOINT'
    m.wrap_mode = wrap_mode
    m.offset = offset
    bpy.context.view_layer.update()
    pts = C.eval_pts(dup)
    bpy.data.objects.remove(dup, do_unlink=True)
    return pts


def inside_flags(pts, tree, rays):
    """逐顶点判「是否落在标准体内部」——与穿刺率指标完全同一判据（ray 多数票，退化回 nn）。

    返回 (flags, stats)；stats 记录两法分歧数，便于审计。
    """
    flags = []
    amb = 0
    disagree = 0
    for p in pts:
        votes_in = votes_ok = 0
        for d in C._RAYS[:rays]:
            c = C._crossings(tree, p, d)
            if c >= 64:
                continue
            votes_ok += 1
            if c % 2 == 1:
                votes_in += 1
        loc, nor, fi, dist = tree.find_nearest(p)
        nn_in = bool(loc is not None and (p - loc).dot(nor) < 0.0)
        if votes_ok == 0:
            amb += 1
            flags.append(nn_in)
            continue
        ray_in = votes_in * 2 > votes_ok
        if ray_in != nn_in:
            disagree += 1
        flags.append(ray_in)
    return flags, {"ambiguous": amb, "ray_nn_disagree": disagree, "n": len(pts)}


def push_out_points(obj, pts, tree, delta, rays=3):
    """外科式几何贴合：**只**把落在标准体内部的顶点沿最近面法线推到体表外 delta。

    为什么不用 Blender 的 Shrinkwrap（实测过 4 种 wrap_mode，见 README「坑」）：
      · NEAREST_SURFACEPOINT + ON_SURFACE 是有符号距离钳制 → 内外关系不变 → 穿模一点不降
      · OUTSIDE_SURFACE 会把**所有**顶点（含本来悬空的）压到体表 + delta
        → 保罗护肩间隙 3.67 cm → 0.40 cm、面积比 0.58（垂坠件全废）
    本函数只动真正穿模的顶点 → 位移与面积损失都限于该修的那部分。
    """
    flags, st = inside_flags(pts, tree, rays)
    out = []
    moved = 0
    disp = []
    for p, is_in in zip(pts, flags):
        if not is_in:
            out.append(p.copy())
            continue
        loc, nor, fi, dist = tree.find_nearest(p)
        if loc is None or nor.length < 1e-9:
            out.append(p.copy())
            continue
        q = loc + nor.normalized() * delta
        out.append(q)
        moved += 1
        disp.append((q - p).length)
    st.update({"moved": moved,
               "moved_frac": round(moved / len(pts), 5) if pts else 0.0,
               "disp_mean_cm": round(100 * sum(disp) / len(disp), 4) if disp else 0.0,
               "disp_max_cm": round(100 * max(disp), 4) if disp else 0.0})
    return out, st


def load_policy():
    if os.path.exists(POLICY_FILE):
        with open(POLICY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def pick_method(policy, outfit, part, default="bone"):
    if not policy:
        return default, 0.0
    node = policy.get("method", {}).get(outfit, {}).get(part)
    if node is None:
        node = policy.get("method", {}).get("*", {}).get("*", default)
    if node.startswith("shrinkwrap"):
        return "shrinkwrap", (float(node.split(":")[1]) if ":" in node else 0.004)
    if node.startswith("push"):
        return "push", (float(node.split(":")[1]) if ":" in node else 0.004)
    return node, 0.0


# ————————————————————————————————————————————————————————————
def run_sweep(a):
    out = {"tool": "refit.py --sweep", "offsets": list(SWEEP_OFFSETS),
           "metric": "penetration_ray = 布料顶点落入标准体内部的比例（射线奇偶，多数票）", "outfits": []}
    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        C.log(f"\n{'='*106}\n[sweep] {outfit}")
        bpy.ops.wm.open_mainfile(filepath=os.path.join(a.ind, f"Outfit_{outfit}.blend"))
        reg_arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        outfit_meshes = [o.name for o in bpy.data.objects if o.type == 'MESH']
        std_arm, body, bpts, btris, bvh = load_body(sex)
        rs = C.bone_rest_stats(reg_arm, std_arm)
        C.log(f"  标准体 {body.name}: {len(bpts)} 顶点 / {len(btris)} 三角面；"
              f"边界边 {C.mesh_boundary_edges(btris)}（0 = 闭合）")
        C.log(f"  rest 差异（{reg_arm.name} vs {std_arm.name}）：{rs}")
        bmap = C.bone_rest_map(reg_arm, std_arm)
        rec = {"outfit": outfit, "sex": sex, "rest_stats": rs, "parts": [],
               "body_obj_stats": {"name": body.name, "verts": len(bpts), "tris": len(btris),
                                  "boundary_edges": C.mesh_boundary_edges(btris),
                                  "closed": C.mesh_boundary_edges(btris) == 0}}
        # parts 只取服装文件里原有的网格（排除刚追加进来的标准体本身）
        for o in sorted([bpy.data.objects[n] for n in outfit_meshes], key=lambda x: x.name):
            p0, tris = eval_tris_of(o)
            pbone, missing = C.skin_points(o, p0, bmap)
            disp = [(x - y).length for x, y in zip(pbone, p0)]
            row = {"part": o.name, "verts": len(p0),
                   "bone_disp_cm": {"mean": round(100 * sum(disp) / len(disp), 4) if disp else 0,
                                    "max": round(100 * max(disp), 4) if disp else 0,
                                    "moved_frac": round(sum(1 for d in disp if d > 1e-7) / len(disp), 4) if disp else 0},
                   "missing_bones": sorted(missing), "variants": {}}
            variants = {"none": p0, "bone": pbone}
            for off in SWEEP_OFFSETS:
                if off <= 0:
                    continue
                variants[f"sw_on:{off}"] = shrinkwrap_points(o, body, off, 'ON_SURFACE')
                variants[f"sw_out:{off}"] = shrinkwrap_points(o, body, off, 'OUTSIDE_SURFACE')
                variants[f"push:{off}"] = push_out_points(o, p0, bvh, off, a.rays)[0]
            for k, pts in variants.items():
                m = measure(pts, bvh, bpts, btris, a.rays)
                m["cost"] = surface_cost(p0, pts, tris)
                m["move_cm"] = {"mean": round(100 * sum((x - y).length for x, y in zip(pts, p0)) / len(pts), 4),
                                "max": round(100 * max((x - y).length for x, y in zip(pts, p0)), 4)}
                row["variants"][k] = m
            rec["parts"].append(row)
            C.log(f"  * {o.name:32s} v={len(p0):5d} 骨位移 mean {row['bone_disp_cm']['mean']:6.4f} "
                  f"max {row['bone_disp_cm']['max']:6.3f} cm  动过 {100*row['bone_disp_cm']['moved_frac']:5.1f}%")
            for k, m in row["variants"].items():
                C.log(f"      {k:16s} 穿模 {100*m['penetration_ray']:6.2f}% (nn {100*m['penetration_nn']:6.2f}%)  "
                      f"位移 mean {m['move_cm']['mean']:7.3f}/max {m['move_cm']['max']:7.3f} cm  "
                      f"间隙 mean {m['gap']['mean_cm']:6.2f} max {m['gap']['max_cm']:7.2f} cm  "
                      f"面积比 {m['cost']['area_ratio']:.3f}  法线偏 {m['cost']['normal_shift_mean_deg']:5.1f}°")
            if missing:
                C.log(f"      ⚠ 权重里出现标准体没有的骨：{sorted(missing)}")
        out["outfits"].append(rec)
        # 丢掉标准体，避免污染后续 outfit 的命名
        for n in (f"Body_{sex}", f"RIG_Body_{sex}_Standard"):
            if n in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
    os.makedirs(C.WORK, exist_ok=True)
    p = os.path.join(C.WORK, "refit_sweep.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    C.log(f"\n扫描结果 → {C.rel(p)}\nDONE")


def run_apply(a):
    policy = load_policy()
    if policy is None and a.method == "auto":
        C.log("  [note] 未找到 refit_policy.json → auto 退化为 bone")
    os.makedirs(a.outd, exist_ok=True)
    report = []
    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        C.log(f"\n{'='*90}\n[refit] {outfit}")
        bpy.ops.wm.open_mainfile(filepath=os.path.join(a.ind, f"Outfit_{outfit}.blend"))
        reg_arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        outfit_meshes = [o.name for o in bpy.data.objects if o.type == 'MESH']
        std_arm, body, bpts, btris, bvh = load_body(sex)
        rs = C.bone_rest_stats(reg_arm, std_arm)
        C.log(f"  rest 差异（服装骨架 vs 标准体）：{rs}")
        bmap = C.bone_rest_map(reg_arm, std_arm)
        rec = {"outfit": outfit, "sex": sex, "rest_stats": rs, "parts": []}
        for o in sorted([x for x in bpy.data.objects if x.type == 'MESH'], key=lambda x: x.name):
            if a.method == "auto":
                meth, off = pick_method(policy, outfit, o.name)
            else:
                meth, off = a.method, a.offset
            p0 = C.eval_pts(o)
            if meth == "none":
                pts = p0
            elif meth == "bone":
                pts, _ = C.skin_points(o, p0, bmap)
            elif meth == "shrinkwrap":
                pts = shrinkwrap_points(o, body, off, a.wrap_mode)
            elif meth == "push":
                pts = push_out_points(o, p0, bvh, off, a.rays)[0]
            else:
                raise ValueError(meth)
            move = [(x - y).length for x, y in zip(pts, p0)]
            before_pen = C.penetration(p0, bvh, bpts, btris, sample_rays=a.rays)
            C.apply_points(o, pts)
            after_pen = C.penetration(pts, bvh, bpts, btris, sample_rays=a.rays)
            part = {"part": o.name, "method": meth, "offset": off, "verts": len(p0),
                    "max_move_cm": round(100 * max(move), 4) if move else 0.0,
                    "pen_before_ray": round(before_pen["ray_rate"], 6),
                    "pen_after_ray": round(after_pen["ray_rate"], 6),
                    "pen_after_nn": round(after_pen["nn_rate"], 6),
                    "gap_after": gap_stats(pts, bvh)}
            rec["parts"].append(part)
            C.log(f"  * {o.name:32s} [{meth}{(':'+str(off)) if meth=='shrinkwrap' else ''}] "
                  f"移动 max {part['max_move_cm']:7.3f} cm  穿模 "
                  f"{100*before_pen['ray_rate']:6.2f}% → {100*after_pen['ray_rate']:6.2f}%")
        for n in (f"Body_{sex}", f"RIG_Body_{sex}_Standard", "Icosphere"):
            if n in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
        C.purge_orphans()
        out = os.path.join(a.outd, f"Outfit_{outfit}.blend")
        C.save_blend(out)
        rec["out"] = C.rel(out)
        report.append(rec)
    p = os.path.join(a.outd, "refit_report.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"tool": "refit.py", "method": a.method,
                   "policy_file": C.rel(POLICY_FILE) if policy else None,
                   "outfits": report}, f, ensure_ascii=False, indent=2)
    C.log(f"\n报告 → {C.rel(p)}\nDONE")


def main():
    a = parse_args()
    run_sweep(a) if a.sweep else run_apply(a)


main()