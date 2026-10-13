#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体形档位的**剪影可分辨性**测量 —— 把"看起来明显吗"换成可复现的像素数。

判据（全部可复算）：
  ① **剪影面积**与**逐行宽度剖面**（正视图、正交、透明胶片 alpha = 剪影）
  ② 两态之间的 **XOR 差异率** = |A⊕B| / |A∪B|（"有多少剪影像素不一样"）
  ③ ⭐ **换算成"等效身高变化"**：同一套渲染里，把标准体做对象级等比缩放
     h ∈ {1.00,1.02,1.04,1.06,1.08}，量出 h 与 XOR 的响应曲线；再用它把
     「瘦↔壮」的 XOR 反查成一个等效的身高变化百分比。
     身高滑块（SPEC §3.4，h∈[0.92,1.08]）是项目里**已被认可"看得出来"**的对照物，
     于是体形档位的强度就有了一个共同单位的标尺。

⚠ 诚实的边界：身高变化与围度变化的**差异分布不同**（一个沿纵向铺开、一个沿横向铺开），
  所以"等效身高变化"是**可复现的量级标尺**，不是严格的心理物理等价。报告里两个量都给。

用法：
  Blender -b --factory-startup --python tools/3d/bodyshape/silhouette_metric.py -- \\
      [--sex both] [--target {body,tryon}] [--res 700,1000] [--out <json>] [--keep-png DIR]

只读：只渲染，不改任何资产（临时相机/灯只存在于内存，且渲染后不再保存）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import bodyshape_core as core  # noqa: E402

SPEC = os.path.join(ROOT, "assets", "3d", "rig", "bodyshape_spec.json")
OUT_DEFAULT = os.path.join(ROOT, "assets", "3d", "rig", "reports", "bodyshape_silhouette.json")
TMP_DIR = os.path.join(ROOT, "tmp", "bs_silhouette")

HEIGHT_CAL = [1.00, 1.02, 1.04, 1.06, 1.08]

try:
    import bpy  # type: ignore
    import numpy as np  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    np = None  # type: ignore
    HAS_BPY = False


# ────────────────────────────────────────────────────────────────────────────
def find_rig_and_meshes(shape_bones):
    arm = None
    for o in bpy.data.objects:
        if o.type == 'ARMATURE' and all(b in o.data.bones for b in shape_bones):
            arm = o
            break
    if arm is None:
        raise SystemExit("找不到含 14 根体形骨的骨架")
    meshes = [o for o in bpy.data.objects
              if o.type == 'MESH' and any(m.type == 'ARMATURE' and m.object == arm
                                          for m in o.modifiers)]
    return arm, meshes


def clear_pose(arm):
    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def apply_inherit_scale_rule(arm, shape_bones):
    """★ SPEC §3.2 / F6 硬规则：体形骨的**全部直接子骨**设 inherit_scale='NONE'。

    为什么这必须在工具里现做：`bodies/` 那两具标准体已经把这条**烘进文件**了，但
    `assets/3d/blend/tryon/` 的角色**没有**（Lead 的 B2 是在内存里设的）。不设就摆骨 →
    缩放会沿骨架链一路传下去 → 剪影直接炸掉（实测：瘦档宽度 −44%，而正确值应是个位数）。
    这是个**静默失败**：不报错，只是数字全错。所以本工具对任何 target 都先设一遍，
    并把改动条数记进报告。"""
    n = 0
    for bn in shape_bones:
        b = arm.data.bones.get(bn)
        if b is None:
            continue
        for c in b.children:
            if c.inherit_scale != 'NONE':
                c.inherit_scale = 'NONE'
                n += 1
    return n


def zero_keys(meshes):
    for o in meshes:
        if o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks:
                kb.value = 0.0
    bpy.context.view_layer.update()


def scene_bbox(meshes):
    dg = bpy.context.evaluated_depsgraph_get()
    lo = np.array([1e9] * 3)
    hi = np.array([-1e9] * 3)
    for o in meshes:
        ev = o.evaluated_get(dg)
        m = ev.to_mesh()
        co = np.array([tuple(o.matrix_world @ v.co) for v in m.vertices])
        ev.to_mesh_clear()
        if len(co):
            lo = np.minimum(lo, co.min(axis=0))
            hi = np.maximum(hi, co.max(axis=0))
    return lo, hi


def setup_scene(meshes, res, bbox):
    sc = bpy.context.scene
    for o in bpy.data.objects:
        if o.type in {'MESH', 'ARMATURE'}:
            o.hide_render = (o not in meshes)
        elif o.type in {'LIGHT', 'CAMERA'}:
            o.hide_render = True
    lo, hi = bbox
    h = float(hi[2] - lo[2])
    w = float(hi[0] - lo[0])
    cz = float((hi[2] + lo[2]) / 2.0)
    # ⚠ Blender 的 ortho_scale 是**较长那条传感器边**的长度：竖构图时它对应"竖向"。
    # 踩过：按宽度算 ortho_scale 会把 T-pose 的手臂裁掉（max_row_width 恒等于图宽，指标失效）。
    if res[1] >= res[0]:                      # 竖构图
        ortho = max(h, w * res[1] / res[0])
    else:                                     # 横构图
        ortho = max(w, h * res[0] / res[1])
    ortho *= 1.04
    cam_data = bpy.data.cameras.new("SIL_CAM")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = ortho
    cam = bpy.data.objects.new("SIL_CAM", cam_data)
    sc.collection.objects.link(cam)
    cam.location = (0.0, -8.0, cz)
    cam.rotation_euler = (1.5708, 0.0, 0.0)
    sc.camera = cam
    for nm, loc, e, sz in (("SIL_K", (2.5, -3.0, 3.5), 3000, 5), ("SIL_F", (-2.5, -2.5, 1.5), 1500, 5)):
        ld = bpy.data.lights.new(nm, 'AREA')
        ld.energy = e
        ld.size = sz
        lo_ = bpy.data.objects.new(nm, ld)
        sc.collection.objects.link(lo_)
        lo_.location = loc
        lo_.rotation_euler = (0.8, 0.0, 0.7)
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            continue
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = True      # ← 剪影 = alpha 通道，别用颜色阈值（F16 的坑）
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    if sc.world is None:
        sc.world = bpy.data.worlds.new("SIL_WORLD")
    return sc


def render_alpha(sc, path):
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path + ".png" if not path.endswith(".png") else path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return (px[:, :, 3] > 0.5)          # 剪影掩码


def silhouette_metrics(mask):
    h, w = mask.shape
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    widths = {}
    if len(rows):
        for frac in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            r = int(round(rows.min() + frac * (rows.max() - rows.min())))
            xs = np.where(mask[r])[0]
            widths[f"{frac:.1f}"] = int(xs.max() - xs.min() + 1) if len(xs) else 0
    prof = []
    for r in range(rows.min(), rows.max() + 1) if len(rows) else []:
        xs = np.where(mask[r])[0]
        prof.append(int(xs.max() - xs.min() + 1) if len(xs) else 0)
    return {
        "area_px": int(mask.sum()),
        "bbox_w_px": int(cols.max() - cols.min() + 1) if len(cols) else 0,
        "bbox_h_px": int(rows.max() - rows.min() + 1) if len(rows) else 0,
        "max_row_width_px": int(max(prof)) if prof else 0,
        "widths_at_frac": widths,
    }


def xor_pct(a, b):
    inter = np.logical_and(a, b).sum()
    uni = np.logical_or(a, b).sum()
    return float((uni - inter) / uni * 100.0) if uni else 0.0


# ────────────────────────────────────────────────────────────────────────────
def run_target(spec, sex, target, res, keep_dir, coeffs):
    if target == "body":
        path = os.path.join(ROOT, f"assets/3d/rig/bodies/Body_{sex}_Standard.blend")
    else:
        path = os.path.join(ROOT, f"assets/3d/blend/tryon/TryOn_{sex}_Ranger.blend")
    bpy.ops.wm.open_mainfile(filepath=path)
    arm, meshes = find_rig_and_meshes(spec["shape_bones"])
    meshes = [o for o in meshes if o.name != "Icosphere"]
    NV = sum(len(o.data.vertices) for o in meshes)
    n_inherit = apply_inherit_scale_rule(arm, spec["shape_bones"])
    print(f"\n{'=' * 74}\n[{sex}/{target}] {os.path.relpath(path, ROOT)}  "
          f"{len(meshes)} 件 / {NV} 顶点 / rig={arm.name}")
    print(f"  F6 规则：本次新设 inherit_scale='NONE' 的骨 {n_inherit} 根"
          f"{'（文件里已经设好）' if n_inherit == 0 else '（⚠ 文件里没设，是现做的，否则剪影会炸）'}")

    clear_pose(arm)
    zero_keys(meshes)
    # 相机取所有状态的外包（含身高 1.08 那一档）→ 全程固定，比较才有意义
    lo, hi = scene_bbox(meshes)
    lo2, hi2 = lo.copy(), hi.copy()
    hi2[2] = lo[2] + (hi[2] - lo[2]) * 1.08
    sc = setup_scene(meshes, res, (lo2, hi2))
    os.makedirs(keep_dir, exist_ok=True)

    masks = {}
    meta = {}
    # 体形三档（摆骨，不用 shape key → 对 B2 角色同样适用）
    states = [("basis", 1.0)] + [(t["name"], t["target_coefficient"]) for t in spec["tiers"]]
    for name, coef in states:
        clear_pose(arm)
        zero_keys(meshes)
        for bn, (sx, sy, sz) in core.bone_scales_for(spec, coef).items():
            arm.pose.bones[bn].scale = (sx, sy, sz)
        for o in meshes:
            o.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        p = os.path.join(keep_dir, f"{sex}_{target}_{name}.png")
        masks[name] = render_alpha(sc, p)
        meta[name] = {"coefficient": coef, "png": os.path.relpath(p, ROOT),
                      **silhouette_metrics(masks[name])}
        print(f"  渲染 {name:10s} coef={coef:.3f}  面积 {meta[name]['area_px']:7d} px  "
              f"最大行宽 {meta[name]['max_row_width_px']:4d} px")
    # 身高标尺（对象级等比缩放 = SPEC §3.4 的正确做法）
    for h in HEIGHT_CAL:
        clear_pose(arm)
        zero_keys(meshes)
        for o in meshes:
            o.scale = (h, h, h)
        bpy.context.view_layer.update()
        name = f"h{h:.2f}"
        p = os.path.join(keep_dir, f"{sex}_{target}_{name}.png")
        masks[name] = render_alpha(sc, p)
        meta[name] = {"object_scale": h, "png": os.path.relpath(p, ROOT),
                      **silhouette_metrics(masks[name])}
        print(f"  渲染 {name:10s} scale={h:.2f}  面积 {meta[name]['area_px']:7d} px  "
              f"最大行宽 {meta[name]['max_row_width_px']:4d} px")

    for o in meshes:
        o.scale = (1.0, 1.0, 1.0)
    clear_pose(arm)

    thin = next(t["name"] for t in spec["tiers"] if t["target_coefficient"] < 1.0)
    heavy = next(t["name"] for t in spec["tiers"] if t["target_coefficient"] > 1.0)
    cal = [{"height_pct": round((h - 1.0) * 100, 3),
            "xor_vs_basis_pct": round(xor_pct(masks["basis"], masks[f"h{h:.2f}"]), 4)}
           for h in HEIGHT_CAL]
    # 用身高标尺把「瘦↔壮」的 XOR 反查成等效身高变化。
    # ⚠ 必须**在实测的标尺曲线内做分段线性插值**，不能拿 8% 那一点线性折算 ——
    # 这条曲线是**凹的**（差异率随身高增大而饱和），直接 x/43.45*8 会系统性高估
    # （实测 6.82% vs 正确 5.45%）。踩过。
    x_tier = xor_pct(masks[thin], masks[heavy])
    ladder = [(c["height_pct"], c["xor_vs_basis_pct"]) for c in cal]
    equiv, how = None, "outside_ladder_extrapolated"
    for (h0, x0), (h1, x1) in zip(ladder, ladder[1:]):
        if x0 <= x_tier <= x1 and x1 > x0:
            equiv = round(h0 + (h1 - h0) * (x_tier - x0) / (x1 - x0), 3)
            how = "piecewise_linear_on_measured_ladder"
            break
    if equiv is None:                     # 超出标尺顶端 → 用最后两点外推，并如实标注
        (h0, x0), (h1, x1) = ladder[-2], ladder[-1]
        if x1 > x0:
            equiv = round(h0 + (h1 - h0) * (x_tier - x0) / (x1 - x0), 3)
    x_hi = xor_pct(masks["basis"], masks["h1.08"])
    return {
        "sex": sex, "target": target, "file": os.path.relpath(path, ROOT),
        "mesh_count": len(meshes), "vertex_count": NV, "rig": arm.name,
        "inherit_scale_none_set_in_memory": n_inherit,
        "resolution": list(res),
        "states": meta,
        "xor_pct": {
            f"{thin}_vs_{heavy}": round(x_tier, 4),
            f"basis_vs_{thin}": round(xor_pct(masks["basis"], masks[thin]), 4),
            f"basis_vs_{heavy}": round(xor_pct(masks["basis"], masks[heavy]), 4),
            "basis_vs_h1.04": round(xor_pct(masks["basis"], masks["h1.04"]), 4),
            "basis_vs_h1.08": round(xor_pct(masks["basis"], masks["h1.08"]), 4),
        },
        "height_calibration": cal,
        "thin_vs_heavy_equivalent_height_pct": equiv,
        "equivalent_height_method": how,
        "area_pct": {
            f"{thin}_vs_basis": round((meta[thin]["area_px"] / meta["basis"]["area_px"] - 1) * 100, 3),
            f"{heavy}_vs_basis": round((meta["heavy"]["area_px"] / meta["basis"]["area_px"] - 1) * 100, 3),
        },
        "max_row_width_pct": {
            f"{thin}_vs_basis": round((meta[thin]["max_row_width_px"] / meta["basis"]["max_row_width_px"] - 1) * 100, 3),
            f"{heavy}_vs_basis": round((meta["heavy"]["max_row_width_px"] / meta["basis"]["max_row_width_px"] - 1) * 100, 3),
        },
    }


def main():
    ap = argparse.ArgumentParser(
        prog="silhouette_metric.py",
        description="体形档位的剪影可分辨性：剪影面积/宽度剖面 + XOR 差异率 + 换算成等效身高变化",
        epilog="例：Blender -b --factory-startup --python tools/3d/bodyshape/silhouette_metric.py -- "
               "--sex Female --target body")
    ap.add_argument("--sex", choices=["Female", "Male", "both"], default="both")
    ap.add_argument("--target", choices=["body", "tryon", "both"], default="body",
                    help="body=标准体；tryon=B2 角色（只读，不改动）")
    ap.add_argument("--spec", default=SPEC)
    ap.add_argument("--res", default="900,1100")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--keep-png", default=TMP_DIR, help="中间剪影 PNG 落盘目录（默认 tmp/，可清）")
    ap.add_argument("--delta", default=None, help="临时覆盖 delta_response（不落盘）")
    ap.add_argument("--along", default=None, help="临时覆盖 along_axis_response（不落盘）")
    ap.add_argument("--label", default=None, help="本次测量的标签（写进 JSON，便于对比 v1/v2）")
    ap.add_argument("--thin", type=float, default=None, help="临时覆盖 thin 档系数（不落盘）")
    ap.add_argument("--heavy", type=float, default=None, help="临时覆盖 heavy 档系数（不落盘）")
    ap.add_argument("--dry-run", action="store_true")
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    if not HAS_BPY:
        if not argv or any(a in ("-h", "--help") for a in argv):
            ap.print_help()
            return 0
        ap.error("需要 bpy + numpy —— 请在 Blender headless 下运行")
    args = ap.parse_args(argv)

    spec = core.load_spec(args.spec)
    cov = {}
    if args.thin is not None:
        cov["thin"] = args.thin
    if args.heavy is not None:
        cov["heavy"] = args.heavy
    if cov:
        for t in spec["tiers"]:
            if t["name"] in cov:
                t["target_coefficient"] = cov[t["name"]]
        print(f"  ⚠ 档位系数临时覆盖：{cov}（不落盘）")
    for flag, key, valid_keys, base in (
            ("delta", "delta_response", spec["delta_response"], spec["delta_response"]),
            ("along", "along_axis_response", spec["groups"],
             spec.get("along_axis_response", {}))):
        raw = getattr(args, flag)
        if raw:
            ov = {}
            for part in raw.split(","):
                k, _, v = part.partition("=")
                ov[k.strip()] = float(v)
            bad = [k for k in ov if k not in valid_keys]
            if bad:
                raise SystemExit(f"--{flag} 里有不认识的键：{bad}")
            spec[key] = {**base, **ov}
            print(f"  ⚠ {key} 临时覆盖：{ov}（不落盘）")

    res = tuple(int(x) for x in args.res.split(","))
    t0 = time.time()
    print(f"# silhouette_metric.py  Blender {bpy.app.version_string}  res={res}")
    print(f"  档位：{[ (t['name'], t['target_coefficient']) for t in spec['tiers'] ]}")
    print(f"  身高标尺：{[round((h-1)*100,1) for h in HEIGHT_CAL]} %（SPEC §3.4 的对象级等比缩放）")

    rows = []
    for sex in (["Female", "Male"] if args.sex == "both" else [args.sex]):
        for tgt in (["body", "tryon"] if args.target == "both" else [args.target]):
            rows.append(run_target(spec, sex, tgt, res, args.keep_png, None))

    report = {
        "schema": "bodyshape-silhouette", "label": args.label,
        "method": {
            "render": "正交前视 + film_transparent；剪影 = alpha>0.5（F16 的教训：不用颜色阈值）",
            "diff": "XOR 差异率 = |A⊕B| / |A∪B|",
            "anchor": "身高滑块（对象级等比缩放 1.00–1.08，SPEC §3.4）—— 项目里已被认可"
                      "'看得出来'的对照物；用它把体形档位差换算成等效身高变化",
            "caveat": "身高与围度的差异分布不同（纵向 vs 横向），等效身高是**量级标尺**，"
                      "不是严格的心理物理等价",
        },
        "coefficients": {t["name"]: t["target_coefficient"] for t in spec["tiers"]},
        "delta_response": spec["delta_response"],
        "along_axis_response": spec.get("along_axis_response", {}),
        "height_scale_ladder": HEIGHT_CAL,
        "blender_version": bpy.app.version_string,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "targets": rows,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    if args.dry_run:
        print("\n[dry-run] 不写 JSON")
    else:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\n报告 → {os.path.relpath(args.out, ROOT)}")
    for r in rows:
        print(f"  {r['sex']:6s}/{r['target']:5s} 瘦↔壮 XOR {r['xor_pct'][list(r['xor_pct'])[0]]:5.2f}%  "
              f"≈ 等效身高变化 {r['thin_vs_heavy_equivalent_height_pct']}%  "
              f"| 面积 瘦 {r['area_pct'][list(r['area_pct'])[0]]:+.2f}% / 壮 "
              f"{r['area_pct'][list(r['area_pct'])[1]]:+.2f}%  "
              f"| 最大行宽 瘦 {r['max_row_width_pct'][list(r['max_row_width_pct'])[0]]:+.2f}% / 壮 "
              f"{r['max_row_width_pct'][list(r['max_row_width_pct'])[1]]:+.2f}%")
    print(f"DONE  {report['elapsed_sec']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())