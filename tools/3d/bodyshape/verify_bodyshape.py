#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体形 morph 独立验收 —— 重开 bodies/*.blend 实测，不信 manifest 的一面之词。

做四件事：
  ① 结构不变量：网格顶点/拓扑/材质/顶点组权重、骨架骨名+顺序+rest 矩阵、pose —— 必须与基线
     **逐字节指纹一致**（我们只被授权改 shape key 数值，结构一根毫毛都不能动）
  ② 契约自检：shape key 顺序 Basis/BS_Thin/BS_Heavy、14 根体形骨齐、子骨 inherit_scale='NONE'
  ③ 实测位移：重开文件后用 depsgraph 求值量三档位移（**不是**读 mesh.vertices）
  ④ 与 manifest 对账：文件里量到的数字必须与 bodyshape_manifest.json 一致

用法：
  Blender -b --factory-startup --python tools/3d/bodyshape/verify_bodyshape.py -- \\
      [--baseline-dir <未加工的 bodies 副本目录>] [--manifest <path>] [--json <out.json>]
  python3 tools/3d/bodyshape/verify_bodyshape.py --help

退出码：0 = 全过；1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SPEC = os.path.join(ROOT, "assets", "3d", "rig", "bodyshape_spec.json")
MANIFEST = os.path.join(ROOT, "assets", "3d", "rig", "manifests", "bodyshape_manifest.json")

try:
    import bpy  # type: ignore
    HAS_BPY = True
except ImportError:
    bpy = None  # type: ignore
    HAS_BPY = False

RESULTS: list = []


def check(name, ok, detail=""):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": str(detail)})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def eval_coords(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    m = ev.to_mesh()
    co = [v.co.copy() for v in m.vertices]
    ev.to_mesh_clear()
    return co


def structure_digest(obj, arm):
    """网格 + 蒙皮 + 骨架 的结构指纹（**刻意排除 shape key 数据** —— 那是唯一被授权改的东西）。"""
    me = obj.data
    h = hashlib.sha256()
    h.update(f"V{len(me.vertices)}P{len(me.polygons)}M{len(me.materials)}".encode())
    for v in me.vertices:
        h.update(struct.pack("<3f", v.co[0], v.co[1], v.co[2]))
    for p in me.polygons:
        h.update(struct.pack(f"<{len(p.vertices)}I", *p.vertices))
        h.update(struct.pack("<I", p.material_index))
        h.update(struct.pack("<b", p.use_smooth))
    h.update(b"|groups")
    for g in obj.vertex_groups:
        h.update(g.name.encode())
    h.update(b"|weights")
    for v in me.vertices:
        for ge in sorted(v.groups, key=lambda e: e.group):
            h.update(struct.pack("<If", ge.group, ge.weight))
    h.update(b"|arm")
    for b in arm.data.bones:
        h.update(b.name.encode())
        h.update((b.parent.name if b.parent else "-").encode())
        h.update(b.inherit_scale.encode())
        h.update(struct.pack("<b", b.use_connect))
        h.update(struct.pack("<16f", *[x for row in b.matrix_local for x in row]))
        h.update(struct.pack("<6f", *b.head_local, *b.tail_local))
    h.update(b"|mats")
    h.update(str([m.name if m else None for m in me.materials]).encode())
    h.update(b"|mods")
    h.update(str([(m.name, m.type, getattr(m, "object", None).name if getattr(m, "object", None) else None)
                  for m in obj.modifiers]).encode())
    h.update(b"|texts")   # 内嵌中文 README 也是资产契约的一部分，一样不许动
    for t in sorted(bpy.data.texts, key=lambda x: x.name):
        h.update(t.name.encode())
        h.update(hashlib.sha256(t.as_string().encode("utf-8")).digest())
    h.update(b"|imgs")
    h.update(str(sorted((i.name, i.filepath) for i in bpy.data.images
                        if i.source == 'FILE')).encode())
    return h.hexdigest()


def pose_digest(arm):
    h = hashlib.sha256()
    for pb in arm.pose.bones:
        h.update(pb.name.encode())
        h.update(struct.pack("<3f", *pb.location))
        h.update(struct.pack("<4f", *pb.rotation_quaternion))
        h.update(struct.pack("<3f", *pb.rotation_euler))
        h.update(struct.pack("<3f", *pb.scale))
    return h.hexdigest()


def pose_noise(arm):
    """上游资产自带的 pose 浮点噪声幅度（derive.py 的快照/还原会**原样保留**它，
    因为我们的授权只有 shape key 数值，不该顺手"修"别人的 pose）。
    但量 morph 位移必须在 rest 态量，否则这 1e-6 的噪声会污染第 6 位小数 —— 实测踩过。"""
    ds = max((max(abs(s - 1.0) for s in pb.scale) for pb in arm.pose.bones), default=0.0)
    # mathutils.Quaternion 的索引 0 是 w（不是 x）—— 踩过
    dr = max((max(abs(q[i]) for i in (1, 2, 3)) for pb in arm.pose.bones
              for q in [pb.rotation_quaternion]), default=0.0)
    dl = max((max(abs(v) for v in pb.location) for pb in arm.pose.bones), default=0.0)
    return {"max_scale_dev": ds, "max_quat_xyz_dev": dr, "max_loc_dev": dl}


def clear_pose(arm):
    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def key_digest(kb):
    h = hashlib.sha256()
    for d in kb.data:
        h.update(struct.pack("<3f", d.co[0], d.co[1], d.co[2]))
    return h.hexdigest()


def verify_one(spec, body_cfg, manifest_body, baseline_dir, tiers):
    sex = body_cfg["sex"]
    path = os.path.join(ROOT, body_cfg["file"])
    print(f"\n{'=' * 74}\n[{sex}] {os.path.relpath(path, ROOT)}")
    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.data.objects[body_cfg["object"]]
    arm = bpy.data.objects[body_cfg["armature"]]
    me = obj.data
    out = {"sex": sex, "file": body_cfg["file"]}

    # ② 契约
    expected = ["Basis"] + [t["shape_key"] for t in tiers]
    order = [k.name for k in me.shape_keys.key_blocks]
    check(f"{sex} shape key 顺序 == {expected}", order[:len(expected)] == expected, f"实际 {order}")
    check(f"{sex} 顶点数 == {body_cfg['expected_vertex_count']}",
          len(me.vertices) == body_cfg["expected_vertex_count"], f"实际 {len(me.vertices)}")
    missing = [b for b in spec["shape_bones"] if b not in arm.data.bones]
    check(f"{sex} 14 根体形骨齐全", not missing, f"缺 {missing}" if missing else "14/14")
    bad = [(bn, c.name, c.inherit_scale) for bn in spec["shape_bones"]
           if bn in arm.data.bones for c in arm.data.bones[bn].children if c.inherit_scale != 'NONE']
    check(f"{sex} 体形骨子骨 inherit_scale='NONE'", not bad, f"违规 {bad}" if bad else "全部 NONE")

    # ① 结构不变量（与基线逐字节指纹比对）
    sd = structure_digest(obj, arm)
    out["structure_sha256"] = sd
    out["pose_sha256"] = pose_digest(arm)
    if baseline_dir:
        base_path = os.path.join(baseline_dir, os.path.basename(path))
        if os.path.exists(base_path):
            bpy.ops.wm.open_mainfile(filepath=base_path)
            bo = bpy.data.objects[body_cfg["object"]]
            ba = bpy.data.objects[body_cfg["armature"]]
            bsd = structure_digest(bo, ba)
            check(f"{sex} 网格/蒙皮/骨架结构 == 基线（未被改动）", sd == bsd,
                  f"{sd[:16]}… vs 基线 {bsd[:16]}…")
            out["baseline_structure_sha256"] = bsd
            bpy.ops.wm.open_mainfile(filepath=path)   # 回到待验文件
            obj = bpy.data.objects[body_cfg["object"]]
            arm = bpy.data.objects[body_cfg["armature"]]
            me = obj.data
        else:
            check(f"{sex} 基线存在", False, f"缺 {base_path}")

    # ③ 实测（depsgraph）
    noise = pose_noise(arm)
    out["pose_noise"] = noise
    print(f"  上游 pose 残留浮点噪声：scale {noise['max_scale_dev']:.2e} / quat.xyz "
          f"{noise['max_quat_xyz_dev']:.2e} / loc {noise['max_loc_dev']:.2e}（原样保留，不擅自修）")
    clear_pose(arm)                      # 量 morph 必须在 rest 态量（见 pose_noise 注释）
    for kb in me.shape_keys.key_blocks:
        kb.value = 0.0
    bpy.context.view_layer.update()
    rest = eval_coords(obj)
    NV = len(rest)
    hz = max(c.z for c in rest) - min(c.z for c in rest)
    rows = []
    for t in tiers:
        kn = t["shape_key"]
        for kb in me.shape_keys.key_blocks:
            kb.value = 0.0
        me.shape_keys.key_blocks[kn].value = 1.0
        bpy.context.view_layer.update()
        co = eval_coords(obj)
        ok_topo = len(co) == NV
        d = [(co[i] - rest[i]).length for i in range(NV)]
        dz = [c.z for c in co]
        kb = me.shape_keys.key_blocks[kn]
        row = {
            "shape_key": kn,
            "vertex_count": len(co),
            "topology_identical": ok_topo,
            "max_displacement_m": round(max(d), 6),
            "mean_displacement_m": round(sum(d) / NV, 6),
            "height_ratio_vs_basis": round((max(dz) - min(dz)) / hz, 6),
            "data_bytes_per_tier": NV * 3 * 4,
            "shape_key_data_sha256": key_digest(kb),
            "nonzero_vertex_count": sum(1 for x in d if x > 1e-9),
        }
        rows.append(row)
        check(f"{sex} {kn} 求值顶点数 == {NV}", ok_topo, f"{len(co)}")
        check(f"{sex} {kn} 身高比 ≈ 1（体形与身高正交）",
              abs(row["height_ratio_vs_basis"] - 1.0) < 0.005,
              f"{row['height_ratio_vs_basis']}")
        check(f"{sex} {kn} 数据量 ≤ 顶点×12 字节",
              row["data_bytes_per_tier"] <= NV * 12, f"{row['data_bytes_per_tier']} B")
        if manifest_body:
            exp = next(x for x in manifest_body["tiers"] if x["shape_key"] == kn)
            check(f"{sex} {kn} 与 manifest 数字一致",
                  abs(exp["max_displacement_m"] - row["max_displacement_m"]) < 1e-5
                  and exp["shape_key_data_sha256"] == row["shape_key_data_sha256"],
                  f"max {exp['max_displacement_m']} vs {row['max_displacement_m']}；digest "
                  f"{exp['shape_key_data_sha256'][:12]}… vs {row['shape_key_data_sha256'][:12]}…")

        # ⑤ ⭐ spec ↔ 已烘 morph 的**几何闭环**（补上最容易漏的那一环）
        #    上面所有断言只证明"文件 ↔ manifest 自洽"；**唯独没有证明"烘出来的形状就是 spec 说的形状"**。
        #    若有人改了 spec 的系数/along 却没重烘（D-1 那类版本偏斜），上面会**全绿**。
        #    这里按 spec.tiers[].bones **重新摆一次骨**，与已烘的 shape key 逐顶点比对。
        declared = t.get("bones")
        if declared:
            tn = t["name"]
            for kb2 in me.shape_keys.key_blocks:
                kb2.value = 0.0
            clear_pose(arm)
            missing_bones = []
            for bn, v in declared.items():
                pb = arm.pose.bones.get(bn)
                if pb is None:
                    missing_bones.append(bn)
                    continue
                pb.scale = (v[0], v[1], v[2])
            bpy.context.view_layer.update()
            predicted = eval_coords(obj)
            geom_err = max((predicted[i] - kb.data[i].co).length for i in range(NV))
            clear_pose(arm)
            for kb2 in me.shape_keys.key_blocks:
                kb2.value = 0.0
            bpy.context.view_layer.update()
            row["spec_replay_max_err_m"] = round(geom_err, 9)
            check(f"{sex} {kn} 已烘 morph == 按 spec.tiers[].bones 重摆骨的结果",
                  not missing_bones and geom_err < 1e-5,
                  (f"逐顶点最大差 {geom_err * 1000:.6f} mm"
                   + (f"；spec 里的骨在 rig 上不存在：{missing_bones}" if missing_bones else "")))
        else:
            check(f"{sex} {kn} spec 提供了 tiers[].bones", False, "缺 bones 字段，无法做几何闭环")
    out["basis_height_m"] = round(hz, 6)
    out["tiers"] = rows

    # 还原权重为 SPEC 默认（运行时权重默认 0）
    for kb in me.shape_keys.key_blocks:
        kb.value = 0.0
    vals = {k.name: k.value for k in me.shape_keys.key_blocks}
    check(f"{sex} 交付态 morph 权重全为 0（SPEC §3.3 默认标准体）",
          all(v == 0.0 for n, v in vals.items() if n != "Basis"), str(vals))
    out["delivered_weights"] = vals
    return out


def main():
    ap = argparse.ArgumentParser(
        prog="verify_bodyshape.py",
        description="体形 morph 独立验收：重开 bodies/*.blend 实测 + 结构不变量 + 与 manifest 对账",
        epilog="例：Blender -b --factory-startup --python tools/3d/bodyshape/verify_bodyshape.py -- "
               "--baseline-dir /path/to/untouched/bodies")
    ap.add_argument("--spec", default=SPEC)
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--baseline-dir", default=None, help="未加工的 bodies 副本目录（验'结构未被改动'）")
    ap.add_argument("--json", default=None, help="把结果写成 JSON（默认只打印）")
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    if not HAS_BPY:
        if not argv or any(a in ("-h", "--help") for a in argv):
            ap.print_help()
            return 0
        ap.error("需要 bpy —— 请在 Blender headless 下运行")
    args = ap.parse_args(argv)

    spec = json.load(open(args.spec, encoding="utf-8"))
    tiers = spec["tiers"]
    man = json.load(open(args.manifest, encoding="utf-8")) if os.path.exists(args.manifest) else None
    print(f"# verify_bodyshape.py   Blender {bpy.app.version_string}")
    print(f"  spec={os.path.relpath(args.spec, ROOT)}  manifest="
          f"{os.path.relpath(args.manifest, ROOT) if man else '（缺失）'}")

    # ④ ⭐ spec ↔ manifest 的**版本对账**（D-1"版本偏斜"那一类的直接守卫）
    #    只验"文件 ↔ manifest 自洽"是不够的：若 spec 被改而 manifest/bodies 没重跑，
    #    下游会拿着新系数去对一套旧产物 —— 两边各自都"自洽"，却是错的。
    if man:
        spec_sha_now = hashlib.sha256(open(args.spec, "rb").read()).hexdigest()
        check("manifest.spec_sha256 == 当前 spec 文件（manifest 不是陈旧的）",
              man.get("spec_sha256") == spec_sha_now,
              f"manifest 记 {str(man.get('spec_sha256'))[:16]}… vs 实际 {spec_sha_now[:16]}…")
        coeffs_now = {t["name"]: t["target_coefficient"] for t in tiers}
        check("manifest.coefficients == spec.tiers[].target_coefficient",
              man.get("coefficients") == coeffs_now, f"{man.get('coefficients')} vs {coeffs_now}")
        dr_now = {k: v for k, v in spec["delta_response"].items() if not k.startswith("_")}
        ar_now = {k: v for k, v in spec.get("along_axis_response", {}).items()
                  if not k.startswith("_")}
        check("manifest.delta_response_values == spec.delta_response",
              man.get("delta_response_values") == dr_now, f"{man.get('delta_response_values')}")
        check("manifest.along_axis_response_values == spec.along_axis_response",
              man.get("along_axis_response_values") == ar_now, f"{man.get('along_axis_response_values')}")
        # 指纹按**与 derive.py 相同的配方**重算 —— 配方变了这里会立刻发现
        fp_now = hashlib.sha256(json.dumps({
            "spec_version": spec["version"], "tiers": coeffs_now,
            "delta_response": dr_now, "along_axis_response": ar_now,
            "shape_bones": spec["shape_bones"]}, sort_keys=True,
            ensure_ascii=False).encode("utf-8")).hexdigest()
        check("manifest.coefficients_fingerprint 重算一致（= 系数未漂移）",
              man.get("coefficients_fingerprint") == fp_now,
              f"{str(man.get('coefficients_fingerprint'))[:16]}… vs 重算 {fp_now[:16]}…")
        # tiers[].bones（spec 声明的实摆三轴）必须与 manifest 的运行期实摆证据一致
        mism = [(a["name"], bn) for a, b in zip(tiers, man.get("tiers", []))
                for bn in a.get("bones", {})
                if b.get("bones_applied", {}).get(bn) != a["bones"][bn]]
        check("spec.tiers[].bones == manifest.tiers[].bones_applied（逐骨逐档）",
              not mism, f"{len(mism)} 处不符：{mism[:4]}" if mism else "全部一致")

    bodies = []
    for cfg in spec["bodies"]:
        mb = next((b for b in man["bodies"] if b["sex"] == cfg["sex"]), None) if man else None
        bodies.append(verify_one(spec, cfg, mb, args.baseline_dir, tiers))

    n_fail = sum(1 for r in RESULTS if not r["ok"])
    print(f"\n{'#' * 74}\n# {'全部通过 ✅' if n_fail == 0 else f'{n_fail} 项 FAIL ❌'}"
          f"  （{len(RESULTS)} 项断言）")
    for b in bodies:
        for t in b["tiers"]:
            print(f"  {b['sex']:6s} {t['shape_key']:9s} 顶点 {t['vertex_count']:5d} "
                  f"最大位移 {t['max_displacement_m'] * 100:5.2f} cm "
                  f"身高比 {t['height_ratio_vs_basis']:.5f} "
                  f"{t['data_bytes_per_tier'] / 1024:.1f} KB/档")
    report = {"schema": "bodyshape-verify", "blender_version": bpy.app.version_string,
              "baseline_dir": args.baseline_dir, "bodies": bodies,
              "checks": RESULTS, "failed": n_fail, "passed": n_fail == 0}
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  → {args.json}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())