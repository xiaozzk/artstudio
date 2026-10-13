"""tools/3d/garment/probe_independent.py —— 无拓扑假设的独立判据（像素法 + 骨轴径向）

为什么需要它（Lead 裁决 2026-10-13）
----------------------------------
`Body_Female/Male` **不是单个闭合曲面**：边界边集中在**手腕/手（z≈1.32–1.47）与足部**，
且**相对质心非星形**（仅 67.2% 的面满足「面法线与面心−质心同向」）。
（**面绕向是一致的** —— 共享边反向遍历违例 0/18250；早先“绕向不一致”是误报，按 F15b 订正。）
而正好在手臂区域，"穿模率"的射线奇偶判据会被破洞"漏"影响。
Lead 明确要求：**必须有独立结论**，最推荐**像素法**。

本工具的两条判据都不依赖"内外"的拓扑假设
----------------------------------------
J1 **像素法**（Lead 推荐口径）
   把标准体**去掉"未被衣服覆盖"的部分**后染成纯红（自发光），布料染纯绿（自发光），
   多视角离屏渲染 → 红像素 / (红+绿) 像素 = **被衣服覆盖的身体表面中、顶出布料的比例**。
   为什么要先去掉未覆盖部分：标准体含头/脸，衣服不包头 → 否则永远有一大块红，数字无意义。
   "覆盖"的定义 = 身体顶点到布料表面的最近距离 < cutoff（默认 2 cm，另报 3/5 cm 做敏感性）。

J2 **骨轴径向半径**（连"内外"都不用，纯几何）
   把 `*_Arms` 按材质拆成 **皮肤面**（`MI_Regular_*`）与 **布料面**，
   分别沿上臂骨轴比较径向半径：
     · 皮肤 r_skin(t) vs 标准体 r_body(t) → 若≈相等，说明**同源手臂**（Lead 实测 60 µm）
     · 布料 r_cloth(t) vs 标准体 r_body(t) → 若 r_cloth < r_body，则**袖子确实在胳膊里**
   这比"穿模率"强的地方：完全不依赖网格闭合、绕向、内外判定。

用法
----
  Blender -b --factory-startup --python tools/3d/garment/probe_independent.py -- \
      [--garments assets/3d/rig/garments] [--body-dir assets/3d/rig/bodies] \
      [--src-outfits assets/3d/blend/outfits-gltf-per-asset/outfits] \
      [--previews assets/3d/rig/previews] [--out tmp/garment/work/probe_independent.json]
"""
import argparse
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C      # noqa: E402
import render_util as RU  # noqa: E402

CUTOFFS = (0.02, 0.03, 0.05)
VIEWS = [("front", (0.0, -3.6, 0.95)), ("back", (0.0, 3.6, 0.95)),
         ("left", (-3.6, 0.0, 0.95)), ("right", (3.6, 0.0, 0.95))]
TARGET = (0.0, 0.0, 0.95)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="probe_independent.py")
    ap.add_argument("--garments", default=C.GARMENTS)
    ap.add_argument("--body-dir", default=C.BODIES)
    ap.add_argument("--src-outfits", default=C.SRC_OUTFITS)
    ap.add_argument("--stripped", default=os.path.join(C.WORK, "stripped"))
    ap.add_argument("--previews", default=C.PREVIEWS)
    ap.add_argument("--out", default=os.path.join(C.WORK, "probe_independent.json"))
    ap.add_argument("--only", default=None)
    ap.add_argument("--res", type=int, default=520)
    return ap.parse_args(argv)


# ————————————————————————————————————————————————————————————
def load_body(body_dir, sex):
    arm_name, body_name = f"RIG_Body_{sex}_Standard", f"Body_{sex}"
    with bpy.data.libraries.load(os.path.join(body_dir, f"Body_{sex}_Standard.blend"),
                                 link=False) as (src, dst):
        dst.objects = [arm_name, body_name]
    for o in dst.objects:
        if o is not None:
            bpy.context.scene.collection.objects.link(o)
    bpy.context.view_layer.update()
    return bpy.data.objects[arm_name], bpy.data.objects[body_name]


def subset_mesh(pts, tris, keep_v):
    """取由 keep_v 里的顶点构成的面，生成新 (pts, tris)。"""
    used = sorted({i for t in tris if all(i in keep_v for i in t) for i in t})
    remap = {g: l for l, g in enumerate(used)}
    return ([pts[i] for i in used],
            [tuple(remap[i] for i in t) for t in tris if all(i in keep_v for i in t)])


def make_mesh_object(name, pts, tris):
    me = bpy.data.meshes.new(name)
    me.from_pydata([p[:] for p in pts], [], [list(t) for t in tris])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def covered_body_region(bpts, btris, garment_tris_pts, garment_tris, cutoff):
    """身体顶点中，到布料表面最近距离 < cutoff 的（= 被衣服遮住的部分）。"""
    gbvh = C.bvh_from_pts_tris(garment_tris_pts, garment_tris)
    keep = set()
    for i, p in enumerate(bpts):
        loc, nor, fi, dist = gbvh.find_nearest(p)
        if loc is not None and dist < cutoff:
            keep.add(i)
    return keep


# ————————————————————————————————————————————————————————————
def pixel_probe(sex, body_obj, garment_objs, tiers, tag_dir, res, cutoff):
    """J1：多视角渲染，返回每个 cutoff / 每档的红像素占比。"""
    bpts, btris = C.eval_mesh(body_obj, want_tris=True)
    gpts_all, gtris_all = [], []
    for o in garment_objs:
        pts, tris = C.eval_mesh(o, want_tris=True)
        base = len(gpts_all)
        gpts_all += pts
        gtris_all += [tuple(i + base for i in t) for t in tris]
    keep = covered_body_region(bpts, btris, gpts_all, gtris_all, cutoff)
    sp, st = subset_mesh(bpts, btris, keep)
    if not st:
        return None
    # 临时把布料合并成一个红/绿对照：身体红、布料绿
    red = RU.emission_material(f"__RED_{sex}_{cutoff}", (1.0, 0.0, 0.0))
    green = RU.emission_material(f"__GREEN_{sex}_{cutoff}", (0.0, 1.0, 0.0))
    body_snap = RU.swap_materials(body_obj, red)
    gsnaps = [(o, RU.swap_materials(o, green)) for o in garment_objs]
    results = {"covered_body_verts": len(sp), "cutoff_cm": round(cutoff * 100, 2),
               "views": {}}
    for vname, loc in VIEWS:
        cam = RU.add_camera(f"__PC_{vname}", loc, TARGET, lens=45.0)
        p = os.path.join(tag_dir, f"pix_{sex}_{vname}.png")
        RU.render_to(p, cam)
        arr = RU.read_pixels(p)
        op = RU.opaque_mask(arr)
        r = RU.classify(arr, 1.0, 0.0, 0.0)
        g = RU.classify(arr, 0.0, 1.0, 0.0)
        both = int((r | g).sum())
        red_n = int((r & op).sum())
        results["views"][vname] = {"red": red_n, "green": int((g & op).sum()),
                                   "union": both,
                                   "red_frac": round(red_n / both, 6) if both else 0.0,
                                   "png": C.rel(p)}
        bpy.data.objects.remove(cam, do_unlink=True)
    RU.restore_materials(body_obj, body_snap)
    for o, s in gsnaps:
        RU.restore_materials(o, s)
    vals = [v["red_frac"] for v in results["views"].values()]
    results["red_frac_mean"] = round(sum(vals) / len(vals), 6)
    results["red_frac_max"] = round(max(vals), 6)
    return results


def bone_axes(std_arm, names):
    """把骨轴拷成纯数据（open_mainfile 会作废 datablock，必须先拷出来）。"""
    out = {}
    for n in names:
        b = std_arm.data.bones.get(n)
        if b:
            out[n] = (b.head_local.copy(), b.tail_local.copy())
    return out


def radial_split(src_blend, sex, body_pts, axes, part_suffix="Arms"):
    """J2：把 *_Arms 按材质拆成皮肤面与布料面，分别算骨轴径向半径。"""
    bpy.ops.wm.open_mainfile(filepath=src_blend)
    reg = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    target = next((o for o in bpy.data.objects
                   if o.type == 'MESH' and o.name.endswith(part_suffix)
                   and not C.is_helper(o)), None)
    if target is None:
        return None
    pts, tris = C.eval_mesh(target, want_tris=True)
    # 按面材质拆
    me = target.data
    me.calc_loop_triangles()
    skin_mats = {i for i, m in enumerate(me.materials)
                 if (m.name if m else "").startswith(C.SKIN_MAT_PREFIX)}
    skin_v, cloth_v = set(), set()
    for t in me.loop_triangles:
        vs = set(t.vertices)
        (skin_v if t.material_index in skin_mats else cloth_v).update(vs)
    cloth_v -= skin_v
    out = {"part": target.name,
           "skin_faces_verts": len(skin_v), "cloth_verts": len(cloth_v),
           "bone_L": {}, "bone_R": {}}
    wm = weight_map(target, ARM_CHAIN)
    out["skin"] = radial_chain(pts, {i: wm[i] for i in skin_v if i in wm}, axes)
    out["cloth"] = radial_chain(pts, {i: wm[i] for i in cloth_v if i in wm}, axes)
    return out


def radial_body(body_pts, body_obj, axes):
    """标准体自身的臂径向（按它自己的权重选）。"""
    wm = weight_map(body_obj, ARM_CHAIN)
    return radial_chain(body_pts, wm, axes)


ARM_CHAIN = ("upperarm_l", "lowerarm_l", "hand_l",
             "upperarm_r", "lowerarm_r", "hand_r")


def weight_map(obj, chain):
    """{顶点 index: (权重最大的链上骨名, 该权重)}；只保留权重 ≥ 0.5 的顶点。"""
    names = [g.name for g in obj.vertex_groups]
    idx = {names.index(n): n for n in chain if n in names}
    out = {}
    for v in obj.data.vertices:
        best, bw = None, 0.0
        for g in v.groups:
            n = idx.get(g.group)
            if n and g.weight > bw:
                best, bw = n, g.weight
        if best and bw >= 0.5:
            out[v.index] = (best, bw)
    return out


def radial_chain(pts, sel, axes, bins=6):
    """**骨链圆柱参数化**：每个点归到权重最大的那根手臂骨，算该骨轴上的 t 与径向距离 r。

    ⚠ 为什么不用单骨 slab：上臂骨的 slab 很宽，会把躯干/另一条手臂投影进来
      （第一版把身体 r(t=0) 报成 90.8 cm 这种荒谬值）；而皮肤面全在**前臂/手**上，
      用单根上臂骨参数化会把它们整体过滤掉（报 None）。按权重归骨到链上才对。
    """
    acc = {}
    for i in sel:
        bone = sel_bone = sel[i][0] if isinstance(sel, dict) else None
        if bone is None or bone not in axes:
            continue
        h, tail = axes[bone]
        ax = tail - h
        L = ax.length
        if L < 1e-9:
            continue
        ax = ax / L
        d = pts[i] - h
        u = d.dot(ax)
        if u < -0.05 * L or u > 1.05 * L:
            continue
        r = (d - ax * u).length
        k = round(min(1.0, max(0.0, u / L)) * bins) / bins
        acc.setdefault(f"{bone}@{k}", []).append(r)
    return {k: round(100 * sum(v) / len(v), 3) for k, v in sorted(acc.items())} or None


# ————————————————————————————————————————————————————————————
def main():
    a = parse_args()
    os.makedirs(a.previews, exist_ok=True)
    work = os.path.join(C.WORK, "pixelprobe")
    os.makedirs(work, exist_ok=True)
    report = {"tool": "probe_independent.py",
              "why": "标准体不是单个闭合曲面（边界边集中在手腕/足 + 相对质心非星形；面绕向实为一致，F15b 已订正），"
                     "手臂区域的'穿模率'判据不可靠；此处用两条**无拓扑假设**的判据独立复核",
              "J1": "像素法：身体(仅被覆盖部分)染红 vs 布料染绿，多视角红像素占比",
              "J2": "骨轴径向半径：按材质拆皮肤/布料，沿上臂骨轴比半径（纯几何，不判内外）",
              "cutoffs_cm": [round(c * 100, 1) for c in CUTOFFS], "outfits": {}}

    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        C.log(f"\n{'='*100}\n[independent] {outfit}")
        # ---- J2 先从**源**服装（未剥离）拆材质算径向 ----
        C.log("  J2 骨轴径向（用源服装：未剥离，才能区分皮肤面 / 布料面）")
        bpy.ops.wm.open_mainfile(filepath=os.path.join(a.body_dir, f"Body_{sex}_Standard.blend"))
        body0 = bpy.data.objects[f"Body_{sex}"]
        std_arm0 = bpy.data.objects[f"RIG_Body_{sex}_Standard"]
        C.clear_shape_values(body0)
        bpts0, _t = C.eval_mesh(body0, want_tris=True)
        axes = bone_axes(std_arm0, ("upperarm_l", "upperarm_r", "lowerarm_l",
                                    "lowerarm_r", "hand_l", "hand_r"))
        j2 = radial_split(os.path.join(a.src_outfits, f"Outfit_{outfit}.blend"),
                          sex, bpts0, axes)
        # 身体臂径向要回到 body 文件里按权重算 → 先把源服装的结果拿到，再重开 body
        if j2:
            j2["body"] = radial_body(bpts0, body0, axes)
        rec = {"J2_radial": None, "J1_pixel": {}}
        if j2:
            bd = j2.pop("body", None)
            j2["body"] = bd
            for tag in ("skin", "cloth", "body"):
                if bd is not None or tag != "body":
                    pass
            # 差值（按同名 bucket 配对）
            for tag in ("skin", "cloth"):
                if j2.get(tag) and bd:
                    common = sorted(set(j2[tag]) & set(bd))
                    diff = {k: round(j2[tag][k] - bd[k], 3) for k in common}
                    j2[f"{tag}_minus_body_cm"] = diff
                    if diff:
                        v = sorted(diff.values())
                        C.log(f"    {tag:5s} − 身体 (cm) 中位 {v[len(v)//2]:+7.3f}  "
                              f"范围 [{v[0]:+.3f}, {v[-1]:+.3f}]  bucket 数 {len(v)}")
            rec["J2_radial"] = j2
            C.log(f"    {j2['part']}: 皮肤面顶点 {j2['skin_faces_verts']} / 布料顶点 {j2['cloth_verts']}")
            C.log(f"    skin : {j2.get('skin')}")
            C.log(f"    cloth: {j2.get('cloth')}")
            C.log(f"    body : {bd}")

        # ---- J1 像素法（交付物 + 标准体） ----
        C.log("  J1 像素法（交付服装 vs 标准体）")
        RU.setup_scene(res_x=a.res, res_y=int(a.res * 1.45))
        bpy.ops.wm.open_mainfile(filepath=os.path.join(a.garments, f"{outfit}.blend"))
        garment_objs = [o for o in bpy.data.objects
                        if o.type == 'MESH' and o.data.shape_keys is not None]
        arm, body = load_body(a.body_dir, sex)
        for cutoff in CUTOFFS:
            C.clear_shape_values(body)
            for o in garment_objs:
                C.clear_shape_values(o)
            r = pixel_probe(sex, body, garment_objs, ("rest",), work, a.res, cutoff)
            rec["J1_pixel"][f"rest_cut{int(cutoff*100)}cm"] = r
            if r:
                C.log(f"    cutoff {cutoff*100:4.1f} cm  覆盖身体顶点 {r['covered_body_verts']:5d}  "
                      f"红像素占比 mean {100*r['red_frac_mean']:6.2f}%  max {100*r['red_frac_max']:6.2f}%  "
                      f"各视角 {[round(100*v['red_frac'],2) for v in r['views'].values()]}")
        # 手臂特写（决定性问题：袖子是不是在胳膊里）
        C.clear_shape_values(body)
        for o in garment_objs:
            C.clear_shape_values(o)
        arm_cam_dir = os.path.join(work, "arms")
        os.makedirs(arm_cam_dir, exist_ok=True)
        rec["J1_arms_closeup"] = arms_closeup(sex, body, garment_objs, arm_cam_dir, a.res)
        report["outfits"][outfit] = rec

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    C.log(f"\n报告 → {C.rel(a.out)}\nDONE")


def arms_closeup(sex, body, garment_objs, out_dir, res, cutoff=0.03):
    """手臂特写：身体（**只保留被布料覆盖的部分**）红 / 布料绿。

    ⚠ 不加"被覆盖"筛选的话，手/前臂的**本该裸露的皮肤**也会算成红像素，
      把"袖子是否在胳膊里"这个问题污染掉（第一版 along 视角 19.5% 就是这么来的）。
    """
    bpts_all, btris_all = C.eval_mesh(body, want_tris=True)
    gp, gt = [], []
    for o in garment_objs:
        pts, tris = C.eval_mesh(o, want_tris=True)
        b = len(gp)
        gp += pts
        gt += [tuple(i + b for i in t) for t in tris]
    keep = covered_body_region(bpts_all, btris_all, gp, gt, cutoff)
    corps, ctris = subset_mesh(bpts_all, btris_all, keep)
    proxy = make_mesh_object(f"__CoveredBodyArms_{sex}", corps, ctris)
    red = RU.emission_material(f"__REDA_{sex}", (1.0, 0.0, 0.0))
    green = RU.emission_material(f"__GREENA_{sex}", (0.0, 1.0, 0.0))
    bs = RU.swap_materials(proxy, red)
    gs = [(o, RU.swap_materials(o, green)) for o in garment_objs]
    bpts = corps
    # 手臂区域 = z 在肩高附近、|x| > 0.12 的点
    arm_pts = [p for p in bpts if abs(p.x) > 0.12 and p.z > 1.15]
    out = {}
    if arm_pts:
        ctr = sum(arm_pts, Vector()) / len(arm_pts)
        out["center"] = [round(v, 3) for v in ctr]
        for tag, loc in (("top", (ctr.x, ctr.y - 0.05, ctr.z + 1.1)),
                         ("front", (ctr.x, ctr.y - 1.1, ctr.z + 0.05)),
                         ("along", (ctr.x + (1.4 if ctr.x > 0 else -1.4), ctr.y, ctr.z))):
            cam = RU.add_camera(f"__AC_{tag}", loc, (ctr.x, ctr.y, ctr.z), lens=85.0)
            p = os.path.join(out_dir, f"arms_{sex}_{tag}.png")
            RU.render_to(p, cam)
            arr = RU.read_pixels(p)
            op = RU.opaque_mask(arr)
            r = RU.classify(arr, 1.0, 0.0, 0.0)
            g = RU.classify(arr, 0.0, 1.0, 0.0)
            both = int((r | g).sum())
            out[tag] = {"red": int((r & op).sum()), "green": int((g & op).sum()),
                        "union": both,
                        "red_frac": round(int((r & op).sum()) / both, 6) if both else 0.0,
                        "png": C.rel(p)}
            bpy.data.objects.remove(cam, do_unlink=True)
        out["red_frac_mean"] = round(sum(v["red_frac"] for k, v in out.items()
                                         if isinstance(v, dict) and "red_frac" in v) /
                                     max(1, sum(1 for v in out.values()
                                                if isinstance(v, dict) and "red_frac" in v)), 6)
    RU.restore_materials(proxy, bs)
    for o, s in gs:
        RU.restore_materials(o, s)
    out["covered_body_verts_total"] = len(bpts_all)
    out["covered_body_verts_used"] = len(corps)
    out["cutoff_cm"] = round(cutoff * 100, 2)
    bpy.data.objects.remove(proxy, do_unlink=True)
    return out


main()