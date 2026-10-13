#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体形派生工具链 —— 骨骼滑块 → 烘成 BS_Thin / BS_Heavy（headless Blender CLI）

契约：assets/3d/rig/SPEC.md v1.0 §3.2 / §3.3 / §3.4
路线：标准体只生成一次；瘦/壮不重新生成，而是
  ① 按 spec 摆体形骨的 pose scale（美术所见即所得，可反复调）
  ② 把骨架形变「烘焙」成 shape key（= 逐顶点偏移表）—— 走 depsgraph 求值
  ③ 清 pose、清 morph 权重，回写标准体
产出：三档形状【顶点数完全相同】，因此天然互为 morph 目标。

用法（headless，一律在工作区根下执行）：
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \\
      --python tools/3d/bodyshape/derive.py -- --sex both

  python3 tools/3d/bodyshape/derive.py --help        # 不开 Blender 也能看帮助

常用开关：
  --sex {Female,Male,both}  选身体（默认 both）
  --no-render               只烘 + 出 manifest，不渲染预览图
  --render-only             跳过烘焙，只用文件里已有的 morph 渲染预览
  --dry-run                 全流程跑通但不写 .blend / manifest / 预览
  --fix-order               shape key 顺序不符契约时重建通道（会丢弃旧通道数据）
  --retune thin=0.80,heavy=1.25   临时改档位系数（配合 --write-spec 持久化）

★ 核心坑（SPEC F9）：shape key **不修改 mesh.vertices**，任何"烘焙/测量"都必须走
  depsgraph：bpy.context.evaluated_depsgraph_get() → obj.evaluated_get(dg) → to_mesh()。
  直接读 obj.data.vertices 只会拿到 Basis 的坐标（原样），测出来的位移永远是 0。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)                       # 让 Blender --python 也能 import 同目录模块
import bodyshape_core as core                  # noqa: E402  ← 系数展开的唯一实现
SPEC_SRC = os.path.join(HERE, "bodyshape_spec.json")                      # 工具侧（源头）
SPEC_DST = os.path.join(ROOT, "assets", "3d", "rig", "bodyshape_spec.json")  # 资产侧（同步副本）
MANIFEST_DEFAULT = os.path.join(ROOT, "assets", "3d", "rig", "manifests", "bodyshape_manifest.json")
PREVIEW_DIR_DEFAULT = os.path.join(ROOT, "assets", "3d", "rig", "previews")

# 允许继承缩放没断开的骨（SPEC F6 硬规则）——这些骨的子骨必须 inherit_scale='NONE'
INHERIT_SCALE_RULE = "体形骨的全部直接子骨必须 inherit_scale='NONE'"

# 骨骼缩放口径：pose_bone.scale 是骨骼局部轴 (x, y, z)，Y 恒为沿骨轴（head→tail）
#   girth   = X/Z 按 delta_response、Y 按 along_axis_response（默认 0）
#             → 改周长；along 只对**水平骨**（clavicle）开，改的是肩宽而不是身高（默认）
#   length  = (s, s, 1)  SPEC §1 F5 那份 demo 的口径：含沿骨轴缩放 → 骨长变、身高跟着变
#   uniform = (s, s, s)  三轴齐缩
AXIS_PROFILES = {p: p for p in core.AXIS_PROFILES}
AXIS_PROFILE_DEFAULT = core.AXIS_PROFILE_DEFAULT

try:  # 没有 bpy 也要能 --help（方便 CI / 人工查用法）
    import bpy  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False


# ────────────────────────────────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────────────────────────────────
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def eval_coords(obj):
    """★ 唯一可信的取形方式：depsgraph 求值后的网格（SPEC F9）。"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mesh = ev.to_mesh()
    co = [v.co.copy() for v in mesh.vertices]
    ev.to_mesh_clear()
    return co


def snapshot_pose(arm):
    return {
        pb.name: (tuple(pb.location), tuple(pb.rotation_quaternion),
                  tuple(pb.rotation_euler), tuple(pb.scale))
        for pb in arm.pose.bones
    }


def restore_pose(arm, snap):
    for pb in arm.pose.bones:
        loc, quat, eul, scl = snap[pb.name]
        pb.location = loc
        pb.rotation_quaternion = quat
        pb.rotation_euler = eul
        pb.scale = scl
    bpy.context.view_layer.update()


def clear_pose(arm):
    """全骨清成 rest（不只是 scale）——否则文件里残留的 pose 会被一起烘进 morph。"""
    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def zero_morph_weights(obj, keep=("Basis",)):
    """把非 Basis 的权重归零 —— 幂等的关键：第二次跑必须先归零再烘，否则会叠加。"""
    if obj.data.shape_keys is None:
        return
    for kb in obj.data.shape_keys.key_blocks:
        if kb.name not in keep:
            kb.value = 0.0
    bpy.context.view_layer.update()


def group_mask(obj, bone_names=("Head", "neck_01"), thr=0.5):
    """取「权重落在指定骨上」的顶点索引（用于看头部/颈部动没动）。"""
    gname = {g.index: g.name for g in obj.vertex_groups}
    hit = set()
    for v in obj.data.vertices:
        for ge in v.groups:
            if gname.get(ge.group) in bone_names and ge.weight > thr:
                hit.add(v.index)
                break
    return sorted(hit)


def morph_free_mask(obj, shape_bones, thr=0.05):
    """取「在 14 根体形骨上的总权重 < thr」的顶点。

    ⚠ 这个集合**不是**"不该动"的集合 —— 实测踩过：`inherit_scale='NONE'` 只断了
    **缩放**的继承，没断**位置**的继承。缩 pelvis 会把 thigh 的 head 沿世界 X 内移
    ~12.6 mm，于是脚（权重只在 foot_l/ball_l 上，一根体形骨都不沾）也会跟着动
    ~15.9 mm。那是**想要的效果**（胯变窄、腿自然内收），不是 bug。
    真正"必须一点不动"的集合要用骨骼姿态矩阵算，见 pose_invariant_indices()。"""
    gidx = {g.name: g.index for g in obj.vertex_groups}
    shape_gidx = {gidx[b] for b in shape_bones if b in gidx}
    out = []
    for v in obj.data.vertices:
        w = sum(ge.weight for ge in v.groups if ge.group in shape_gidx)
        if w < thr:
            out.append(v.index)
    return out


def vert_weights(me):
    """每顶点的 {顶点组索引: 权重}（一次算好，后面复用）。"""
    return [{ge.group: ge.weight for ge in v.groups} for v in me.vertices]


def pose_matrices(arm):
    """全骨姿态矩阵（骨架对象空间）—— 用来判定"这根骨到底动没动"。"""
    return {pb.name: pb.matrix.copy() for pb in arm.pose.bones}


def changed_bones(rest_mats, tier_mats, tol=1e-6):
    return sorted(n for n, m in rest_mats.items()
                  if max(abs(m[r][c] - tier_mats[n][r][c]) for r in range(4) for c in range(4)) > tol)


def pose_invariant_indices(weights, obj, frozen_names):
    """★ 严格不变量：一个顶点的**全部**加权骨都是"姿态矩阵没变"的骨 → 它必须一点不动。
    （位置的继承也一并算进去了，所以缩 pelvis 时脚会被正确地排除在外。）"""
    frozen = {obj.vertex_groups[n].index for n in frozen_names if n in obj.vertex_groups}
    return [i for i, w in enumerate(weights) if all(g in frozen for g in w)]


def dangling_textures():
    return [img.name for img in bpy.data.images
            if img.source == 'FILE' and not os.path.exists(bpy.path.abspath(img.filepath))]


# ────────────────────────────────────────────────────────────────────────────
# spec
# ────────────────────────────────────────────────────────────────────────────
def load_spec(path: str) -> dict:
    return core.load_spec(path)


def materialize_tiers(spec: dict, retune: dict | None = None,
                      profile: str = AXIS_PROFILE_DEFAULT) -> list:
    """系数展开走 bodyshape_core（derive 与 measure_girth 共用同一实现，杜绝公式漂移）。
    v2.1 起 `tiers[].bones` 存**实摆三轴**（y 也带 `along_axis_response`），与 `axis_profile.rule`
    一致、也与 manifest 的 `bones_applied` 一致；`profile` 只影响本次实际摆的 pose scale。"""
    return core.materialize_tiers(spec, retune, profile)


def sync_spec_copy(verbose=True):
    """工具侧 spec 是源头；资产侧只是同步副本（byte 相同，不允许漂移）。"""
    with open(SPEC_SRC, "rb") as f:
        src = f.read()
    os.makedirs(os.path.dirname(SPEC_DST), exist_ok=True)
    same = os.path.exists(SPEC_DST) and open(SPEC_DST, "rb").read() == src
    if not same:
        with open(SPEC_DST, "wb") as f:
            f.write(src)
        if verbose:
            print(f"  spec 已同步 → {os.path.relpath(SPEC_DST, ROOT)}")
    return sha256_file(SPEC_SRC)


# ────────────────────────────────────────────────────────────────────────────
# 烘焙
# ────────────────────────────────────────────────────────────────────────────
def ensure_shape_keys(obj, tiers, fix_order=False):
    me = obj.data
    order = ["Basis"] + [t["shape_key"] for t in tiers]
    if me.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
    names = [k.name for k in me.shape_keys.key_blocks]
    if fix_order:
        for kb in list(me.shape_keys.key_blocks):
            if kb.name != "Basis":
                obj.shape_key_remove(kb)
        names = [k.name for k in me.shape_keys.key_blocks]
    for n in order:
        if n not in names:
            obj.shape_key_add(name=n, from_mix=False)
            names.append(n)
    names = [k.name for k in me.shape_keys.key_blocks]
    if names[:len(order)] != order:
        raise SystemExit(
            f"shape key 顺序不符契约：实际 {names}，要求前缀 {order}\n"
            f"  （可加 --fix-order 重建非 Basis 通道；重建会丢弃旧通道数据，反正要重烘）"
        )
    return order, names[len(order):]


def check_inherit_scale(arm, spec):
    """SPEC F6 硬规则自检：14 根体形骨的全部直接子骨必须 inherit_scale='NONE'。"""
    bad = []
    for bn in spec["shape_bones"]:
        b = arm.data.bones.get(bn)
        if b is None:
            bad.append((bn, "MISSING", None))
            continue
        for c in b.children:
            if c.inherit_scale != "NONE":
                bad.append((bn, c.name, c.inherit_scale))
    return bad


def normalize_inherit_scale(arm, spec):
    """★ 按 SPEC §3.2 / F6 **自设**：体形骨的全部直接子骨 `inherit_scale='NONE'`。

    **幂等**：已经是 `NONE` 的不动，返回的 `changed` 里不会有它。

    为什么必须自设而不是"要求输入已设好"：`bodies/` 那两具标准体是
    `tools/3d/make_standard_body.py` 预先设好的，所以现在能跑通；但**Tripo 生成的新标准体
    不会带这个设置** → 原来那句 `raise SystemExit` 会在换身体的**第一个**环节就把工具挡死。
    契约应当由**工具自己保证**，而不是依赖"上一环节记得设"。

    返回 `(changed_sorted, original)`：`original` 是**本次输入原本**的值（用于进 manifest，
    让下游能看出"这具身体是被规范化过，还是本来就规范"）。
    """
    changed, original = [], {}
    for bn in spec["shape_bones"]:
        b = arm.data.bones.get(bn)
        if b is None:
            continue
        for c in b.children:
            original.setdefault(c.name, c.inherit_scale)
            if c.inherit_scale != "NONE":
                c.inherit_scale = "NONE"
                changed.append(c.name)
    return sorted(set(changed)), original


def process_body(spec, tiers, body_cfg, args) -> dict:
    sex = body_cfg["sex"]
    path = os.path.join(ROOT, body_cfg["file"])
    rel = os.path.relpath(path, ROOT)
    print(f"\n{'=' * 74}\n[{sex}] {rel}")

    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.data.objects.get(body_cfg["object"])
    arm = bpy.data.objects.get(body_cfg["armature"])
    if obj is None or obj.type != 'MESH':
        raise SystemExit(f"找不到网格对象 {body_cfg['object']!r}")
    if arm is None or arm.type != 'ARMATURE':
        raise SystemExit(f"找不到骨架对象 {body_cfg['armature']!r}")

    me = obj.data
    NV = len(me.vertices)
    print(f"  网格 {obj.name}: {NV} 顶点 / {len(me.polygons)} 面 / {len(me.materials)} 材质；"
          f"骨架 {arm.name}: {len(arm.data.bones)} 骨")
    assert NV == body_cfg["expected_vertex_count"], (
        f"顶点数不符：实际 {NV}，spec 期望 {body_cfg['expected_vertex_count']}")

    mods = [(m.name, m.type, getattr(m, "object", None).name if getattr(m, "object", None) else None)
            for m in obj.modifiers]
    if not any(m[1] == 'ARMATURE' and m[2] == arm.name for m in mods):
        raise SystemExit(f"{obj.name} 上没有指向 {arm.name} 的 Armature 修改器：{mods}")

    # ── SPEC §3.2 / F6：**自设**（幂等），再自检 ─────────────────────────────
    # 原来的写法是"输入必须已设好，否则 raise SystemExit" —— 那会让 Tripo 生成的新标准体
    # （不会带这个设置）在换身体的第一个环节就把工具挡死。契约由工具自己保证。
    changed, original = normalize_inherit_scale(arm, spec)
    bad = check_inherit_scale(arm, spec)          # 设完之后再校验，此时必须 0 违规
    if bad:
        raise SystemExit(f"{INHERIT_SCALE_RULE}——自设之后仍有 {len(bad)} 处违规：{bad}")
    n_in = len(original)
    n_in_full = sum(1 for v in original.values() if v != "NONE")
    inherit_info = {
        "rule": INHERIT_SCALE_RULE,
        "direct_children_count": n_in,
        "input_non_none_count": n_in_full,
        "input_already_normalized": len(changed) == 0,
        "set_to_none_this_run": changed,
        "n_set_this_run": len(changed),
        "post_set_violations": [],
        "delivered_state": "保持 NONE —— SPEC F18：bodies/ 的 NONE 是**烘焙期工件**，不是交付形状",
    }
    if changed:
        print(f"  inherit_scale：输入未规范化（{n_in_full}/{n_in} 根非 NONE）→ "
              f"本次自设 NONE {len(changed)} 根 ✅")
    else:
        print(f"  inherit_scale：输入已规范化（{n_in} 根直接子骨均为 'NONE'），本次无需改动 ✅")
    # 工具只被授权把 NONE 持久化进 bodies/（F18）；若指向别处要显式知道自己在做什么
    if changed and "bodies/" not in rel.replace(os.sep, "/"):
        print(f"  ⚠ 注意：本次把 {len(changed)} 根子骨设成 NONE 并会**随文件保存**，"
              f"但目标不在 bodies/ 下 —— 请对照 SPEC F18 确认该目录的契约要求。")

    order, extra = ensure_shape_keys(obj, tiers, fix_order=args.fix_order)
    print(f"  shape key 通道：{order}" + (f"（额外通道 {extra}）" if extra else ""))

    # 快照文件里原有的 pose，烘完原样还原（我们只被授权改 shape key 数值）
    snap = snapshot_pose(arm)
    clear_pose(arm)
    zero_morph_weights(obj)
    rest = eval_coords(obj)
    assert len(rest) == NV
    zs = [c.z for c in rest]
    height_rest = max(zs) - min(zs)
    rigid_idx = group_mask(obj, ("Head", "neck_01"), 0.5)
    weights = vert_weights(me)
    rest_mats = pose_matrices(arm)
    print(f"  三档基线：顶点 {len(rest)}，身高 {height_rest:.4f} m，"
          f"z∈[{min(zs):.4f}, {max(zs):.4f}]；头/颈顶点 {len(rigid_idx)}")

    tier_rows = []
    tier_mats = {}
    if not args.render_only:
        for t in tiers:
            kb = me.shape_keys.key_blocks[t["shape_key"]]
            zero_morph_weights(obj)
            clear_pose(arm)
            applied = {}
            for bn, (sx, sy, sz) in t["bones"].items():
                pb = arm.pose.bones.get(bn)
                if pb is None:
                    raise SystemExit(f"pose bone 缺失：{bn}")
                pb.scale = (sx, sy, sz)
                applied[bn] = (sx, sy, sz)
            bpy.context.view_layer.update()
            tier_mats[t["name"]] = pose_matrices(arm)
            co = eval_coords(obj)
            if len(co) != NV:
                raise SystemExit(f"{t['name']} 三档顶点数不一致：{len(co)} vs {NV}")
            for i, c in enumerate(co):
                kb.data[i].co = c
            kb.value = 0.0
            clear_pose(arm)
            moved = changed_bones(rest_mats, tier_mats[t["name"]])
            print(f"  烘焙 {t['shape_key']:9s} ← target_coefficient={t['target_coefficient']:.3f}"
                  f"，{len(applied)} 根体形骨，顶点 {len(co)}；"
                  f"姿态被牵动的骨 {len(moved)}/65（含位置继承的下游骨）")

    # ── 实测（必须走 depsgraph）───────────────────────────────────────────
    for t in tiers:
        kn = t["shape_key"]
        zero_morph_weights(obj)
        me.shape_keys.key_blocks[kn].value = 1.0
        bpy.context.view_layer.update()
        co = eval_coords(obj)
        if len(co) != NV:
            raise SystemExit(f"{kn} 求值后顶点数不一致：{len(co)} vs {NV}")
        d = [(co[i] - rest[i]).length for i in range(NV)]
        dz = [c.z for c in co]
        rigid_max = max((d[i] for i in rigid_idx), default=0.0)
        if t["name"] in tier_mats:
            moved = changed_bones(rest_mats, tier_mats[t["name"]])
            frozen = sorted(set(rest_mats) - set(moved))
            inv_idx = pose_invariant_indices(weights, obj, frozen)
        else:  # --render-only：没有姿态数据，退化成"零权重"近似
            frozen, inv_idx = [], []
        inv_max = max((d[i] for i in inv_idx), default=0.0)
        assert inv_max < 1e-5, (
            f"{kn}: 姿态完全不动的骨所支配的顶点竟然动了 {inv_max * 1000:.5f} mm —— morph 混进了"
            f"非本档的形变（很可能是上一次烘焙没归零，幂等性被破坏）")
        amax = max(range(NV), key=lambda i: d[i])
        kb = me.shape_keys.key_blocks[kn]
        digest = hashlib.sha256()
        for v in kb.data:
            digest.update(struct.pack("<3f", v.co[0], v.co[1], v.co[2]))
        row = {
            "name": t["name"],
            "label_zh": t.get("label_zh"),
            "shape_key": kn,
            "morph_target_index": t["morph_target_index"],
            "key_block_index": next(i for i, k in enumerate(me.shape_keys.key_blocks) if k.name == kn),
            "target_coefficient": t["target_coefficient"],
            "vertex_count": len(co),
            "topology_identical_to_basis": len(co) == NV,
            "polygon_count": len(me.polygons),
            "max_displacement_m": round(max(d), 6),
            "mean_displacement_m": round(sum(d) / NV, 6),
            "rms_displacement_m": round((sum(x * x for x in d) / NV) ** 0.5, 6),
            "displaced_over_1mm_count": sum(1 for x in d if x > 1e-3),
            "height_m": round(max(dz) - min(dz), 6),
            "height_ratio_vs_basis": round((max(dz) - min(dz)) / height_rest, 6),
            "rigid_region_vertex_count": len(rigid_idx),
            "rigid_region_max_displacement_m": round(rigid_max, 8),
            "bones_pose_changed": len(moved) if t["name"] in tier_mats else None,
            "bones_pose_frozen": len(frozen) if t["name"] in tier_mats else None,
            "pose_invariant_vertex_count": len(inv_idx),
            "pose_invariant_max_displacement_m": round(inv_max, 10),
            "max_displacement_vertex": {
                "index": amax,
                "basis_position": [round(x, 6) for x in rest[amax]],
                "tier_position": [round(x, 6) for x in co[amax]],
            },
            "data_bytes_per_tier": NV * 3 * 4,
            "data_bytes_formula": "vertices * 3 * 4",
            "shape_key_data_sha256": digest.hexdigest(),
            "bones": {k: list(v) for k, v in t["bones"].items()},
        }
        tier_rows.append(row)
        print(f"  实测 {kn:9s} 最大位移 {row['max_displacement_m'] * 100:6.2f} cm  "
              f"均值 {row['mean_displacement_m'] * 100:5.3f} cm  "
              f"身高比 {row['height_ratio_vs_basis']:.5f}  "
              f"头/颈 {row['rigid_region_max_displacement_m'] * 1000:.2f} mm  "
              f"姿态冻结顶点 {row['pose_invariant_vertex_count']} 个位移 "
              f"{row['pose_invariant_max_displacement_m'] * 1e9:.3f} nm")

    # ── 落盘（必须在加渲染相机/灯之前 —— 那些辅助对象绝不能进 bodies/*.blend）──
    zero_morph_weights(obj)
    restore_pose(arm, snap)
    danglers = dangling_textures()
    blend_sha = None
    if not args.dry_run:
        bpy.context.preferences.filepaths.save_version = 0   # 不产生 .blend1
        bpy.ops.wm.save_as_mainfile(filepath=path)
        blend_sha = sha256_file(path)
        print(f"  已回写 → {rel}  ({os.path.getsize(path) / 1024:.0f} KB, "
              f"sha256 {blend_sha[:16]}…)")
    else:
        print("  [dry-run] 跳过回写")
    print(f"  贴图断链：{danglers if danglers else '无 ✅'}")

    first_ns = [k.name for k in me.shape_keys.key_blocks]
    return {
        "sex": sex,
        "file": rel,
        "object": obj.name,
        "armature": arm.name,
        "armature_bone_count": len(arm.data.bones),
        "material": me.materials[0].name if me.materials and me.materials[0] else None,
        "vertex_count": NV,
        "polygon_count": len(me.polygons),
        "basis_height_m": round(height_rest, 6),
        "shape_keys": [
            {"name": k.name,
             "key_block_index": i,
             "morph_target_index": (None if k.name == "Basis" else
                                    next(t["morph_target_index"] for t in tiers if t["shape_key"] == k.name))}
            for i, k in enumerate(me.shape_keys.key_blocks)
        ],
        "key_order_ok": first_ns[:len(order)] == order,
        "inherit_scale_violations": bad,
        "inherit_scale_normalization": inherit_info,
        "dangling_textures": danglers,
        "blend_sha256": blend_sha,
        "tiers": tier_rows,
        "_med": (obj, me, arm),  # 内部：交给渲染用，不写进 manifest
    }


# ────────────────────────────────────────────────────────────────────────────
# 预览渲染（三档并排）—— 产物是真实渲染文件，辅助相机/灯只存在于内存
# ────────────────────────────────────────────────────────────────────────────
def render_preview(sex, ctx, tiers, out_path, res=(2800, 1000), spacing=1.9, ortho_scale=6.0):
    """三档并排对照图。

    ⚠ 间距必须 > 臂展（T-pose 约 1.67 m），否则相邻两档的**手臂会互相压住** ——
    T5 实测踩过：Lead 的 B2 对照图里三具角色的手臂叠在一起、且被画幅左右裁掉，
    于是"最宽的那条轮廓线"根本没法比，看图的结论直接失真（不是 morph 的错）。
    臂展 1.67 + 间距 1.9 → 相邻净空 0.23 m；画幅宽 6.0 m 容得下 2×1.9+1.67=5.47 m。
    """
    obj, me, arm = ctx
    scene = bpy.context.scene

    for kb in me.shape_keys.key_blocks:
        kb.value = 0.0
    # 只留身体本体参与渲染（Eyebrows/Eyes/Icosphere/旧相机灯全部藏掉）
    for o in bpy.data.objects:
        if o.type in {'MESH', 'ARMATURE'}:
            o.hide_render = (o is not obj)
    for o in list(bpy.data.objects):
        if o.type in {'LIGHT', 'CAMERA'}:
            o.hide_render = True

    made = []
    # 标准档直接用原对象（权重全 0），瘦/壮各复制一份（复制会带上独立的 mesh + shape key）
    obj.location = (0.0, 0.0, 0.0)
    made.append((obj, "STANDARD"))
    for name, label, x in (("thin", "THIN", -spacing), ("heavy", "HEAVY", spacing)):
        dup = obj.copy()
        dup.data = me.copy()
        scene.collection.objects.link(dup)
        dup.location = (x, 0.0, 0.0)
        key = next(t["shape_key"] for t in tiers if t["name"] == name)
        dup.data.shape_keys.key_blocks[key].value = 1.0
        made.append((dup, label))
    made.sort(key=lambda p: p[0].location.x)
    for o, label in made:
        print(f"    档位副本 {label:8s} x={o.location.x:+.2f}")

    # 标签（默认内置 Bfont，ASCII 才安全；中文会缺字形）
    coef = {t["name"]: t["target_coefficient"] for t in tiers}
    labels = {"THIN": f"THIN  {coef.get('thin', 0.86):.2f}",
              "STANDARD": "STANDARD  1.00",
              "HEAVY": f"HEAVY  {coef.get('heavy', 1.16):.2f}"}
    try:
        for o, label in made:
            bpy.ops.object.text_add(location=(o.location.x, 0.0, 1.86))
            t = bpy.context.object
            t.name = f"LBL_{label}"
            t.data.body = labels[label]
            t.data.size = 0.14
            t.data.align_x = 'CENTER'
            t.data.align_y = 'CENTER'
            t.rotation_euler = (1.5708, 0.0, 0.0)
    except Exception as e:  # 文本只是锦上添花，失败不影响证据
        print(f"  [warn] 标签添加失败（不影响渲染）：{e}")

    cam_data = bpy.data.cameras.new("BS_PREVIEW_CAM")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = ortho_scale
    cam = bpy.data.objects.new("BS_PREVIEW_CAM", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -6.0, 0.88)
    cam.rotation_euler = (1.5708, 0.0, 0.0)
    scene.camera = cam

    for nm, loc, rot, e, sz in (("BS_K", (3.2, -3.2, 4.2), (0.75, 0.0, 0.7), 3000, 5),
                                ("BS_F", (-3.2, -2.6, 1.6), (0.85, 0.0, -0.7), 1200, 5),
                                ("BS_B", (0.0, 3.2, 2.2), (-0.9, 0.0, 0.0), 800, 5)):
        ld = bpy.data.lights.new(nm, 'AREA')
        ld.energy = e
        ld.size = sz
        lo = bpy.data.objects.new(nm, ld)
        scene.collection.objects.link(lo)
        lo.location = loc
        lo.rotation_euler = rot

    sc = scene
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            continue
    if sc.world is None:
        sc.world = bpy.data.worlds.new("BS_WORLD")
    sc.world.use_nodes = True
    bg = next((n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs[0].default_value = (0.045, 0.05, 0.06, 1.0)
        bg.inputs[1].default_value = 0.6
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.filepath = out_path
    sc.render.image_settings.file_format = 'PNG'
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    t0 = time.time()
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as e:
        print(f"  [warn] {sc.render.engine} 渲染失败，退回 Workbench：{e}")
        sc.render.engine = 'BLENDER_WORKBENCH'
        sc.display.shading.light = 'STUDIO'
        sc.display.shading.color_type = 'TEXTURE'
        bpy.ops.render.render(write_still=True)
    ok = os.path.exists(out_path)
    print(f"  预览图 → {os.path.relpath(out_path, ROOT)}  "
          f"({os.path.getsize(out_path) / 1024:.0f} KB, {time.time() - t0:.1f}s, "
          f"{sc.render.engine}) {'✅' if ok else '❌'}")
    # 还原内存状态（不落盘，但保持干净）
    for kb in me.shape_keys.key_blocks:
        kb.value = 0.0
    obj.location = (0.0, 0.0, 0.0)
    return {"path": os.path.relpath(out_path, ROOT), "engine": sc.render.engine,
            "resolution": list(res), "exists": ok,
            "labels": ["瘦/THIN", "标准/STANDARD", "壮/HEAVY"],
            "sha256": sha256_file(out_path) if ok else None}


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────
def raw_args():
    argv = sys.argv[1:]
    if "--" in argv:                    # Blender: … --python derive.py -- <args>
        argv = argv[argv.index("--") + 1:]
    return argv


def build_parser():
    p = argparse.ArgumentParser(
        prog="derive.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="体形派生：按 spec 摆体形骨 → 烘成 BS_Thin / BS_Heavy（走 depsgraph），"
                    "清 pose 后回写标准体，并出 manifest + 三档并排预览图。",
        epilog="例：\n"
               "  Blender -b --factory-startup --python tools/3d/bodyshape/derive.py -- --sex both\n"
               "  Blender -b --factory-startup --python tools/3d/bodyshape/derive.py -- --sex Female --no-render\n"
               "  python3 tools/3d/bodyshape/derive.py --help",
    )
    p.add_argument("--sex", choices=["Female", "Male", "both"], default="both", help="处理哪具标准体（默认 both）")
    p.add_argument("--axis-profile", choices=sorted(AXIS_PROFILES), default=AXIS_PROFILE_DEFAULT,
                   help="骨骼缩放口径（默认 girth：只缩垂直于骨轴的两轴，身高不变；"
                        "length = SPEC §1 F5 的 demo 口径，含骨长，会改身高）")
    p.add_argument("--spec", default=SPEC_SRC, help=f"spec 路径（默认 {os.path.relpath(SPEC_SRC, ROOT)}）")
    p.add_argument("--manifest", default=MANIFEST_DEFAULT, help="manifest 输出路径")
    p.add_argument("--preview-dir", default=PREVIEW_DIR_DEFAULT, help="预览图输出目录")
    p.add_argument("--render", dest="render", action="store_true", default=True, help="渲染三档并排预览（默认开）")
    p.add_argument("--no-render", dest="render", action="store_false", help="不渲染预览")
    p.add_argument("--render-only", action="store_true", help="跳过烘焙，只用文件里已有的 morph 渲染预览")
    p.add_argument("--dry-run", action="store_true", help="跑通全流程但不写 .blend / manifest / 预览")
    p.add_argument("--fix-order", action="store_true", help="shape key 顺序不符契约时重建非 Basis 通道")
    p.add_argument("--retune", default=None, metavar="thin=0.80,heavy=1.25",
                   help="临时覆盖档位系数（默认不落盘）")
    p.add_argument("--write-spec", action="store_true", help="把 --retune 的系数持久化进 spec（两份同步）")
    p.add_argument("--quiet", action="store_true", help="少打印")
    return p


def parse_retune(s):
    if not s:
        return None
    out = {}
    for part in s.split(","):
        k, _, v = part.partition("=")
        out[k.strip()] = float(v)
    return out


def main():
    parser = build_parser()
    argv = raw_args()
    if not HAS_BPY:
        if not argv or any(a in ("-h", "--help") for a in argv):
            parser.print_help()
            print("\n注：真正执行必须在 Blender headless 下："
                  "Blender -b --factory-startup --python tools/3d/bodyshape/derive.py -- <args>")
            return 0
        parser.error("本脚本需要 bpy —— 请在 Blender headless 下运行（或只用 --help）")
    args = parser.parse_args(argv)

    t_start = time.time()
    retune = parse_retune(args.retune)
    spec = load_spec(args.spec)
    tiers = materialize_tiers(spec, retune, args.axis_profile)
    if args.write_spec and retune:
        raw = load_spec(args.spec)
        for t in raw["tiers"]:
            if t["name"] in retune:
                t["target_coefficient"] = retune[t["name"]]
                # v2.1：`bones` 存**实摆三轴**（y 也带 along_axis_response）；
                # 规范形 (s,1,s) 改名存到 `bones_canonical_girth`，明示"参考用、别拿来摆骨"。
                t["bones"] = core.spec_bones(raw, t["target_coefficient"])
                t["bones_canonical_girth"] = core.canonical_bones(raw, t["target_coefficient"])
                t["_comment_bones"] = (
                    "实摆三轴向量 = x/z 由 delta_response、y 由 along_axis_response 调制，"
                    "就是 axis_profile.rule 说的那一份；可直接摆到 pose bone 上。"
                    "规范形（不含 along）另存于 bones_canonical_girth，仅供参考，不要拿来摆骨。")
        with open(args.spec, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
            f.write("\n")
        spec = raw
        tiers = materialize_tiers(spec, None, args.axis_profile)
        print(f"--retune 已持久化进 {os.path.relpath(args.spec, ROOT)}"
              f"（tiers[].bones = 实摆三轴；规范形另存 bones_canonical_girth）")

    print(f"# 体形派生 derive.py")
    print(f"  spec       : {os.path.relpath(args.spec, ROOT)}")
    print(f"  口径       : {args.axis_profile}（X/Z×delta_response，Y×along_axis_response）")
    print(f"               along_axis_response = {spec.get('along_axis_response', {})}")
    for t in tiers:
        s = [t['canonical_bones'][b][0] for b in spec["shape_bones"]]
        print(f"  档位 {t['name']:6s} {t['shape_key']:9s} target={t['target_coefficient']:.3f} "
              f"系数范围 [{min(s):.4f}, {max(s):.4f}]")
    print(f"  Blender    : {bpy.app.version_string}")

    spec_sha = sync_spec_copy(not args.quiet)

    wanted = [c for c in spec["bodies"] if args.sex == "both" or c["sex"] == args.sex]
    bodies = []
    previews = []
    for cfg in wanted:
        row = process_body(spec, tiers, cfg, args)
        ctx = row.pop("_med")
        if args.render and not args.dry_run:
            out = os.path.join(args.preview_dir, f"bodyshape_{cfg['sex']}.png")
            try:
                previews.append({"sex": cfg["sex"], **render_preview(cfg["sex"], ctx, tiers, out)})
            except Exception as e:
                print(f"  [warn] 预览渲染失败：{e}")
                previews.append({"sex": cfg["sex"], "path": None, "error": str(e)})
        bodies.append(row)

    manifest = {
        "schema": "bodyshape-manifest",
        # version = **台账/工具的修订号**（会因加字段、改工具而变）；
        # spec_version = **系数契约的版本**（只有动系数才变）。
        # 下游判"系数有没有变"请看 coefficients_fingerprint，别看这两个 version，更别看 mtime。
        "version": "2.1",
        "spec_version": spec["version"],
        "revision_note": "2.1: (a) derive.py 改为**自设** inherit_scale='NONE'（幂等，不再硬失败，"
                         "为 Tripo 新身体铺路），manifest 新增 inherit_scale_normalization 行；"
                         "(b) 修 spec 自相矛盾：tiers[].bones 由『规范形 (s,1,s)』改为**实摆三轴**"
                         "（与 axis_profile.rule 及本 manifest 的 bones_applied 一致），"
                         "规范形改名存 tiers[].bones_canonical_girth。"
                         "**均为台账/字段语义修订，系数与 morph 数值未变**"
                         "（coefficients_fingerprint 与四位 morph digest 保持不变）。",
        "spec": os.path.relpath(SPEC_DST, ROOT),
        "spec_sha256": spec_sha,
        # ⭐ 下游（garment / godot-preview / verifier）判断版本请**只认这四行**：
        #    spec_version + coefficients + delta_response/along_axis_response + coefficients_fingerprint。
        #    只比 mtime 会被"重跑一次"误伤（几何其实逐位相同）；只比文件 sha 又太钝。
        #    系数一变，coefficients_fingerprint 必变 —— 拿它当守卫的键最稳。
        "coefficients": {t["name"]: t["target_coefficient"] for t in tiers},
        "delta_response_values": {k: v for k, v in spec["delta_response"].items()
                                  if not k.startswith("_")},
        "along_axis_response_values": {k: v for k, v in spec.get("along_axis_response", {}).items()
                                       if not k.startswith("_")},
        "coefficients_fingerprint": sha256_json({
            "spec_version": spec["version"],
            "tiers": {t["name"]: t["target_coefficient"] for t in tiers},
            "delta_response": {k: v for k, v in spec["delta_response"].items() if not k.startswith("_")},
            "along_axis_response": {k: v for k, v in spec.get("along_axis_response", {}).items()
                                    if not k.startswith("_")},
            "shape_bones": spec["shape_bones"],
        }),
        "generator": "tools/3d/bodyshape/derive.py",
        "generator_sha256": sha256_file(os.path.abspath(__file__)),
        "contract": spec["contract"],
        "axis_profile": {
            "name": args.axis_profile,
            "bone_scale_rule": "scale = (1+d·delta_response, 1+d·along_axis_response, "
                               "1+d·delta_response)，d = target_coefficient - 1；Y 为沿骨轴",
            "along_axis_response": spec.get("along_axis_response", {}),
            "available": sorted(AXIS_PROFILES),
            "rule": spec["axis_profile"]["rule"],
            "note": "v2.1 起 spec 的 tiers[].bones 存**实摆三轴**（= 本 manifest 的 bones_applied），"
                    "可直接摆到 pose bone；规范形 (s,1,s) 另存 tiers[].bones_canonical_girth，仅供参照。"
                    "换口径只改 --axis-profile，spec 不用动。`along_axis_response` 只对骨轴近乎水平的骨"
                    "（clavicle）开 —— 改的是肩宽/臂展，不改身高。",
        },
        "blender_version": bpy.app.version_string,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sex_filter": args.sex,
        "delta_response": spec["delta_response"],
        "shape_bones": spec["shape_bones"],
        "morph_channels": spec["morph_channels"],
        "tiers": [{"name": t["name"], "shape_key": t["shape_key"],
                   "morph_target_index": t["morph_target_index"],
                   "target_coefficient": t["target_coefficient"],
                   "bones_applied": t["bones"],
                   "bones_canonical_girth": t["canonical_bones"]}
                  for t in tiers],
        "bodies": bodies,
        "previews": previews,
        "reference_f5_demo_profile": {
            "_comment": "SPEC §1 F5 的『最大位移 14.00 / 13.42 cm』是**含沿骨轴缩放**的口径 "
                        "pb.scale=(s,s,1) 测出来的：那实质是【腿长变化】，代价是身高一起变 ±11%，"
                        "与 SPEC §3.4『身高交给骨架等比缩放』的正交设计冲突。"
                        "复现命令（不改盘）：derive.py --axis-profile length --dry-run。"
                        "下面是为了对账而实测的同一具身体在两种口径下的数字。",
            "pose_scale_rule": "(s, s, 1) —— 含骨长",
            "measured_on": "assets/3d/rig/bodies/Body_Female_Standard.blend / Body_Female",
            "posed_by": "derive.py --sex Female --axis-profile length --dry-run",
            "thin": {"max_displacement_m": 0.1135, "height_ratio_vs_basis": 0.89849,
                     "head_neck_max_displacement_m": 0.0730, "bones_pose_changed": 64},
            "heavy": {"max_displacement_m": 0.1297, "height_ratio_vs_basis": 1.11601,
                      "head_neck_max_displacement_m": 0.0834, "bones_pose_changed": 64},
            "girth_same_body": {
                "thin": {"max_displacement_m": 0.0290, "height_ratio_vs_basis": 1.00017,
                         "head_neck_max_displacement_m": 0.00294, "bones_pose_changed": 62},
                "heavy": {"max_displacement_m": 0.0331, "height_ratio_vs_basis": 0.99981,
                          "head_neck_max_displacement_m": 0.00336, "bones_pose_changed": 62},
            },
        },
        "elapsed_sec": None,
    }
    manifest["elapsed_sec"] = round(time.time() - t_start, 1)

    if args.dry_run:
        print("\n[dry-run] 不写 manifest")
    else:
        os.makedirs(os.path.dirname(args.manifest), exist_ok=True)
        with open(args.manifest, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\nmanifest → {os.path.relpath(args.manifest, ROOT)}  "
              f"({os.path.getsize(args.manifest) / 1024:.1f} KB)")

    print(f"\n{'#' * 74}\n# 汇总  ({manifest['elapsed_sec']}s)")
    for b in bodies:
        for t in b["tiers"]:
            print(f"  {b['sex']:6s} {t['shape_key']:9s} 顶点 {t['vertex_count']:5d} "
                  f"最大位移 {t['max_displacement_m'] * 100:6.2f} cm "
                  f"身高比 {t['height_ratio_vs_basis']:.5f} "
                  f"数据 {t['data_bytes_per_tier'] / 1024:6.1f} KB/档")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())