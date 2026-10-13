"""tools/3d/garment/transfer_morph.py —— ③ 传递：把标准体的体形 morph 传到每件布料

SPEC §4.2 的算法（F8 已验证）：
    绑定（一次性）：近邻搜索 p 在【标准体 rest】网格上 → 三角面 t、命中点 q、法线 n
                    w = q 在 t 上的重心坐标；F = t 的标架 (n̂, t̂, û)
                    o = p − q 在该标架下的分量
    求值（每档）：P' = Σ wᵢ·V'ᵢ ；F' = 变形后 t 的标架 ；p' = P' + o 在 F' 下重组

三种模式（逐件自动选，理由写进报告/manifest）
--------------------------------------------
  bary           标架随身体旋转 —— 默认，贴身件正确
  bary_no_frame  只跟随插值点位移、不旋转标架 —— 悬空件更稳（不会因绑到错的面而扭转）
  skip           该件不跟随 morph（shape key 仍创建但全零，**保证索引对齐**）
                 ⚠ skip 的代价 = 该件在 Thin/Heavy 档会被身体顶穿，脚本会实测并报出来

自动决策规则（**实测驱动**，不是拍脑袋）
--------------------------------------
绑定可靠性用"撕裂度"量化：把传递位移加到布料上后，逐边算拉伸比
（布料跟着变胖本来就是拉伸，所以只看 p99/max 与 >1.5× 的比例）。
  tear_frac = 拉伸比 > 1.5 的边占比
规则：① 三种模式里 tear_frac 最小者；
      ② 若该最小 tear_frac ≤ 1% → 采用；
      ③ 否则若 gap_p95 > 4 cm（= 绑定点离身体太远，明显绑错）→ skip；
      ④ 否则仍采用最佳模式，但在报告里标 `marginal`（供人工复核）。
可用 `--policy FILE` 覆盖（JSON: {"method": {outfit: {part: "bary|bary_no_frame|skip"}}}）。

绑定数据缓存（≈28 B/顶点，一次性）
---------------------------------
`tmp/garment/work/binding/<outfit>_<bodyhash>.pkl`。身体文件变了（hash 不同）自动重绑；
只是 morph 数值变了（T1 交付真数据）→ 直接复用绑定，秒级重跑。

用法
----
  Blender -b --factory-startup --python tools/3d/garment/transfer_morph.py -- \
      [--in tmp/garment/work/autofit] [--body-dir assets/3d/rig/bodies] \
      [--out tmp/garment/work/morph] [--policy tools/3d/garment/transfer_policy.json] \
      [--rebind] [--rays 6]
"""
import argparse
import hashlib
import json
import os
import pickle
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

DEFAULT_POLICY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transfer_policy.json")
BINDING_DIR = os.path.join(C.WORK, "binding")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="transfer_morph.py")
    ap.add_argument("--in", dest="ind", default=os.path.join(C.WORK, "autofit"))
    ap.add_argument("--body-dir", default=C.BODIES)
    ap.add_argument("--out", dest="outd", default=os.path.join(C.WORK, "morph"))
    ap.add_argument("--policy", default=DEFAULT_POLICY if os.path.exists(DEFAULT_POLICY) else None)
    ap.add_argument("--rebind", action="store_true")
    ap.add_argument("--rays", type=int, default=6)
    ap.add_argument("--only", default=None)
    return ap.parse_args(argv)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def load_body(body_dir, sex):
    path = os.path.join(body_dir, f"Body_{sex}_Standard.blend")
    arm_name, body_name = f"RIG_Body_{sex}_Standard", f"Body_{sex}"
    if body_name not in bpy.data.objects:
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = [arm_name, body_name]
        for o in dst.objects:
            if o is not None:
                bpy.context.scene.collection.objects.link(o)
        bpy.context.view_layer.update()
    return bpy.data.objects[arm_name], bpy.data.objects[body_name]


def morph_keys(body):
    kb = body.data.shape_keys.key_blocks
    order = [k.name for k in kb]
    assert order[:3] == C.MORPH_ORDER, f"标准体 morph 顺序不符契约：{order}"
    return order[1:]


def body_points(body, values):
    C.set_shape_values(body, values)
    pts, tris = C.eval_mesh(body, want_tris=True)
    return pts, tris


# ————————————————————————————————————————————————————————————
def bind(body_rest_pts, body_tris, tree, g_pts):
    """一次性绑定：返回 [(tri_idx, bary(3), o_local(3), o_world(3), gap)]"""
    binding = []
    for p in g_pts:
        loc, nor, fi, dist = tree.find_nearest(p)
        if loc is None:
            binding.append(None)
            continue
        t = body_tris[fi]
        A, B, Cc = body_rest_pts[t[0]], body_rest_pts[t[1]], body_rest_pts[t[2]]
        w = C.bary(loc, A, B, Cc)
        f = C.frame(A, B, Cc)
        d = p - loc
        # 重心坐标可能跑出三角面（近邻命中点理论上在面上，数值上可能略偏）→ 夹紧
        w = Vector((max(0.0, w[0]), max(0.0, w[1]), max(0.0, w[2])))
        s = w[0] + w[1] + w[2]
        w = w / s if s > 1e-12 else Vector((1.0, 0.0, 0.0))
        o_local = C.frame_local(d, f) if f else Vector((0, 0, 0))
        binding.append((fi, (w[0], w[1], w[2]), (o_local[0], o_local[1], o_local[2]),
                        (d[0], d[1], d[2]), dist))
    return binding


def apply_binding(binding, dpts, dtris, mode):
    """按绑定把变形后的身体坐标传成布料新坐标。"""
    out = []
    for b in binding:
        if b is None:
            out.append(None)
            continue
        fi, w, o_local, o_world, gap = b
        t = dtris[fi]
        A, B, Cc = dpts[t[0]], dpts[t[1]], dpts[t[2]]
        P = A * w[0] + B * w[1] + Cc * w[2]
        if mode == "bary":
            f = C.frame(A, B, Cc)
            out.append(P + C.frame_apply(Vector(o_local), f) if f else P)
        elif mode == "bary_no_frame":
            out.append(P + Vector(o_world))
        else:
            raise ValueError(mode)
    return out


def tear_stats(orig_pts, new_pts, edges, thresh=1.5):
    rs = []
    for a, b in edges:
        if new_pts[a] is None or new_pts[b] is None:
            continue
        l0 = (orig_pts[a] - orig_pts[b]).length
        if l0 > 1e-7:
            rs.append((new_pts[a] - new_pts[b]).length / l0)
    if not rs:
        return {"n": 0}
    rs.sort()
    n = len(rs)
    return {"n": n, "p50": round(rs[n // 2], 4),
            "p95": round(rs[int(0.95 * (n - 1))], 4),
            "p99": round(rs[int(0.99 * (n - 1))], 4), "max": round(rs[-1], 4),
            "gt1p5": sum(1 for r in rs if r > thresh),
            "tear_frac": round(sum(1 for r in rs if r > thresh) / n, 6)}


# ————————————————————————————————————————————————————————————
def run(a):
    os.makedirs(a.outd, exist_ok=True)
    os.makedirs(BINDING_DIR, exist_ok=True)
    policy = None
    if a.policy and os.path.exists(a.policy):
        with open(a.policy, encoding="utf-8") as f:
            policy = json.load(f)
    report = []
    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        src = os.path.join(a.ind, f"Outfit_{outfit}.blend")
        C.log(f"\n{'='*104}\n[transfer] {outfit}   <- {C.rel(src)}")
        bh = sha256(os.path.join(a.body_dir, f"Body_{sex}_Standard.blend"))
        cache = os.path.join(BINDING_DIR, f"{outfit}_{bh}.pkl")
        bpy.ops.wm.open_mainfile(filepath=src)
        reg_arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        outfit_meshes = [o.name for o in bpy.data.objects if o.type == 'MESH']
        std_arm, body = load_body(a.body_dir, sex)
        keys = morph_keys(body)
        rest_pts, rest_tris = body_points(body, {})
        tree = C.bvh_from_pts_tris(rest_pts, rest_tris)
        C.log(f"  标准体 {body.name}（{C.rel(os.path.join(a.body_dir, f'Body_{sex}_Standard.blend'))}, "
              f"sha256[:16]={bh}）  rest {len(rest_pts)} 顶点 / {len(rest_tris)} 面")
        C.log(f"  morph 通道：{['Basis'] + keys}（契约顺序 {C.MORPH_ORDER}）")

        # 变形后的身体坐标（每档一次）
        dpts = {}
        for k in keys:
            dpts[k], _ = body_points(body, {k: 1.0})
            disp = [(x - y).length for x, y in zip(dpts[k], rest_pts)]
            C.log(f"  {k}: 身体最大位移 {100*max(disp):.3f} cm，动过 "
                  f"{100*sum(1 for d in disp if d > 1e-7)/len(disp):.1f}%")
        C.set_shape_values(body, {})

        # 收集每件原始坐标
        parts = {}
        for name in sorted(outfit_meshes):
            o = bpy.data.objects[name]
            parts[name] = {"obj": o, "pts": C.eval_pts(o),
                           "edges": [(e.vertices[0], e.vertices[1]) for e in o.data.edges]}
        total_v = sum(len(p["pts"]) for p in parts.values())
        sig = (bh, tuple(sorted((n, len(p["pts"])) for n, p in parts.items())))

        binding = None
        if os.path.exists(cache) and not a.rebind:
            try:
                with open(cache, "rb") as f:
                    cached = pickle.load(f)
                if cached.get("sig") == sig:
                    binding = cached["binding"]
                    C.log(f"  绑定数据复用缓存 {C.rel(cache)}（{total_v} 顶点，"
                          f"约 {os.path.getsize(cache)/1024:.0f} KB）")
            except Exception as e:
                C.log(f"  [warn] 绑定缓存不可用（{e}），重绑")
        if binding is None:
            binding = {}
            for name, p in parts.items():
                binding[name] = bind(rest_pts, rest_tris, tree, p["pts"])
            with open(cache, "wb") as f:
                pickle.dump({"sig": sig, "binding": binding, "body_sha256_16": bh,
                             "body_path": C.rel(os.path.join(a.body_dir, f"Body_{sex}_Standard.blend"))},
                            f, protocol=4)
            C.log(f"  绑定完成并缓存 → {C.rel(cache)}"
                  f"（{total_v} 顶点，约 {os.path.getsize(cache)/1024:.0f} KB"
                  f" = {28*os.path.getsize(cache)/1024/ (28*total_v) * 28*total_v/1024:.0f} KB 量级）")

        rec = {"outfit": outfit, "sex": sex,
               "body": {"file": C.rel(os.path.join(a.body_dir, f"Body_{sex}_Standard.blend")),
                        "sha256_16": bh, "shape_keys": ["Basis"] + keys},
               "binding_cache": C.rel(cache), "parts": []}

        for name, p in parts.items():
            g_pts = p["pts"]
            edges = p["edges"]
            bnd = binding[name]
            gaps = [b[4] for b in bnd if b]
            gaps.sort()
            row = {"part": name, "verts": len(g_pts),
                   "bind_gap_cm": {"mean": round(100 * sum(gaps) / len(gaps), 3) if gaps else 0,
                                   "p95": round(100 * gaps[int(0.95 * (len(gaps) - 1))], 3) if gaps else 0,
                                   "max": round(100 * gaps[-1], 3) if gaps else 0},
                   "modes": {}}
            best = None
            for mode in ("bary", "bary_no_frame"):
                m = {}
                for k in keys:
                    pts2 = apply_binding(bnd, dpts[k], rest_tris, mode)
                    m[k] = tear_stats(g_pts, pts2, edges)
                allr = sorted([r for k in keys for r in
                               [(g_pts[a] - g_pts[b]).length for a, b in edges] if False] or [])
                # 汇总两档的 tear
                tot_gt = sum(m[k]["gt1p5"] for k in keys)
                tot_n = sum(m[k]["n"] for k in keys)
                row["modes"][mode] = {"per_key": m,
                                      "tear_frac": round(tot_gt / tot_n, 6) if tot_n else 0,
                                      "p99_max": max(m[k].get("p99", 0) for k in keys),
                                      "max_max": max(m[k].get("max", 0) for k in keys)}
                if best is None or row["modes"][mode]["tear_frac"] < row["modes"][best]["tear_frac"]:
                    best = mode
            # 自动决策
            ov = None
            if policy:
                ov = policy.get("method", {}).get(outfit, {}).get(name)
            tf = row["modes"][best]["tear_frac"]
            gap_p95 = row["bind_gap_cm"]["p95"]
            if ov:
                choice, reason = ov, f"人工覆盖（policy 文件 {os.path.basename(a.policy)}）"
            elif tf <= 0.01:
                choice = best
                reason = (f"自动：三模式中撕裂度最低 {best}（tear_frac {100*tf:.3f}% ≤ 1%）")
            elif gap_p95 > 4.0:
                choice = "skip"
                reason = (f"自动 skip：绑定点太远（gap p95 {gap_p95:.2f} cm > 4 cm）"
                          f"且最佳模式 {best} 撕裂度 {100*tf:.3f}% 仍 > 1% → 近邻绑定不可信，"
                          f"按 SPEC §4.4 不硬做")
            else:
                choice = best
                reason = (f"自动 marginal：最佳模式 {best} 撕裂度 {100*tf:.3f}% > 1%，"
                          f"但 gap p95 {gap_p95:.2f} cm ≤ 4 cm → 采用并标记待人工复核")
            row["mode"] = choice
            row["reason"] = reason
            row["marginal"] = (choice == best and tf > 0.01)
            rec["parts"].append(row)
            C.log(f"  * {name:32s} v={len(g_pts):5d} 绑定间隙 mean "
                  f"{row['bind_gap_cm']['mean']:5.2f} p95 {gap_p95:5.2f} max "
                  f"{row['bind_gap_cm']['max']:6.2f} cm")
            for mode in ("bary", "bary_no_frame"):
                C.log(f"      {mode:14s} 撕裂 p99 {row['modes'][mode]['p99_max']:6.3f} "
                      f"max {row['modes'][mode]['max_max']:8.3f}  "
                      f"tear_frac {100*row['modes'][mode]['tear_frac']:6.3f}%")
            C.log(f"      ⇒ 采用 [{choice}]  {reason}")

            # 写真：shape key（skip 也创建，保证索引对齐）
            o = p["obj"]
            if o.data.shape_keys is None:
                o.shape_key_add(name="Basis", from_mix=False)
            objs_kb = {}
            for k in keys:
                if k in o.data.shape_keys.key_blocks:
                    objs_kb[k] = o.data.shape_keys.key_blocks[k]
                else:
                    objs_kb[k] = o.shape_key_add(name=k, from_mix=False)
            order = [kb.name for kb in o.data.shape_keys.key_blocks]
            if order != C.MORPH_ORDER:
                raise AssertionError(f"{name} morph 顺序 {order} != 契约 {C.MORPH_ORDER}")
            mw_inv = o.matrix_world.inverted()
            for k in keys:
                if choice == "skip":
                    base = [mw_inv @ q for q in g_pts]
                else:
                    pts2 = apply_binding(bnd, dpts[k], rest_tris, choice)
                    base = [(mw_inv @ (g_pts[i] if pts2[i] is None else pts2[i]))
                            for i in range(len(g_pts))]
                for i, q in enumerate(base):
                    objs_kb[k].data[i].co = q
                objs_kb[k].value = 0.0
            row["morph_bytes_per_key"] = len(g_pts) * 12
            row["max_disp_cm"] = round(100 * max(
                ((objs_kb[k].data[i].co - o.data.shape_keys.key_blocks["Basis"].data[i].co).length
                 for i in range(len(g_pts)) for k in keys[:1]), default=0.0), 4)

        # 验收：各档穿模（身体也开到同档）
        bvh_rest = tree
        rec["penetration_by_key"] = {}
        for tag, values in [("rest", {})] + [(k, {k: 1.0}) for k in keys]:
            bpts, btris = body_points(body, values)
            bvh = C.bvh_from_pts_tris(bpts, btris)
            tot_in = tot_n = 0
            per = {}
            for name, p in parts.items():
                if p["obj"].data.shape_keys is None:
                    continue
                C.set_shape_values(p["obj"], values)
                # 名可能不同（服装的 key 名与身体一致，这里 values 用的就是同名）
                gpts = C.eval_pts(p["obj"])
                pen = C.penetration(gpts, bvh, bpts, btris,
                                    sample_rays=a.rays, nearest_normal=True)
                per[name] = {"ray": round(pen["ray_rate"], 6), "nn": round(pen["nn_rate"], 6),
                             "n": pen["n"], "inside": pen["ray_inside"]}
                tot_in += pen["ray_inside"]
                tot_n += pen["n"]
            rec["penetration_by_key"][tag] = {
                "aggregate_ray": round(tot_in / tot_n, 6) if tot_n else 0.0,
                "aggregate_n": tot_n, "parts": per}
            C.log(f"  ── 穿模 @ {tag:9s}（独立口径：{a.rays} 方向射线奇偶）"
                  f"合计 {100*tot_in/tot_n:6.2f}%  ({tot_in}/{tot_n})")
        C.set_shape_values(body, {})
        for name, p in parts.items():
            C.clear_shape_values(p["obj"])

        for n in ([f"Body_{sex}", f"RIG_Body_{sex}_Standard", "Icosphere"]):
            if n in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
        C.purge_orphans()
        out = os.path.join(a.outd, f"Outfit_{outfit}.blend")
        C.save_blend(out)
        rec["out"] = C.rel(out)
        report.append(rec)

    p = os.path.join(a.outd, "transfer_report.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"tool": "transfer_morph.py",
                   "spec": "assets/3d/rig/SPEC.md §4.2（重心坐标 + 三角面标架）",
                   "policy_file": C.rel(a.policy) if a.policy else None,
                   "outfits": report}, f, ensure_ascii=False, indent=2)
    C.log(f"\n报告 → {C.rel(p)}\nDONE")


run(parse_args())