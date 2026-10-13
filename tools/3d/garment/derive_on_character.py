"""tools/3d/garment/derive_on_character.py —— **B2 主实现**：体形 morph 派生在「角色自身网格」上

B2 的核心洞察（Lead FINDINGS §11.4 / §12，SPEC F17）
--------------------------------------------------
现有 `assets/3d/blend/tryon/TryOn_{sex}_{Outfit}.blend` **就是最终角色**：
  服装布料 + 服装自带皮肤（`MI_Regular_*`）+ 基础体的头（3 件），**共用服装自己的 rig**。
→ **最终角色里没有独立的 Superhero 身体**（它只捐一个头）。
→ 那么"标准体与服装体形基准不一致"这个问题**本来就不该存在**：
   体形 morph 应当用**角色自己的 rig**摆骨、**逐件**烘在**这个角色**的网格上。

因此本工具**不需要** `strip_skin.py` / `refit.py` / `transfer_morph.py`（那三个是 B1 路线专用）：
没有外部身体 → 布料/皮肤/头共用同一副 rig、同一组骨变换 → 体形一变，三者**同构地一起变**，
**结构性不存在穿模**。

口径（与 T1 `bodyshape` 一致，SPEC F13）
--------------------------------------
体形骨 `pose_bone.scale = (s, 1.0, s)` —— **girth**：只缩垂直于骨轴的两轴，**骨长不变**
→ 体形与身高正交（身高交给骨架 root 等比缩放，SPEC §3.4）。
`s = 1 + (target_coefficient − 1) × delta_response[骨]`，系数与响应从
`assets/3d/rig/bodyshape_spec.json` / `bodyshape_manifest.json` 读（单一事实来源），读不到才退回默认。
每根体形骨的**全部直接子骨**设 `inherit_scale='NONE'`（SPEC §3.2 / F6，**在 `arm.data.bones` 上设**）。

⚠ 边界（必须写进 README，SPEC §4.0）
-----------------------------------
B2 下**不能做"裸露躯干"的服装**（泳装、裸露护甲）：那时体形变化没有载体
（布料太少、皮肤被剥离），morph 无处表达。

用法
----
  Blender -b --factory-startup --python tools/3d/garment/derive_on_character.py -- \
      [--tryon assets/3d/blend/tryon] [--out assets/3d/rig/garments] \
      [--report tmp/garment/work/b2_report.json] [--only Female_Ranger]
"""
import argparse
import hashlib
import struct
import json
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

BODYSHAPE_SPEC = os.path.join(C.RIG, "bodyshape_spec.json")
BODYSHAPE_MANIFEST = os.path.join(C.MANIFESTS, "bodyshape_manifest.json")

# 兜底（读不到 T1 产物时用；实测值与 T1 交付一致）
DEFAULT_TIERS = {"BS_Thin": 0.86, "BS_Heavy": 1.16}
DEFAULT_RESP = {"pelvis": 1.0, "spine_01": 1.0, "spine_02": 0.92, "spine_03": 0.85,
                "thigh": 0.95, "calf": 0.85, "upperarm": 1.05, "lowerarm": 0.95,
                "clavicle": 0.5}

README_TMPL = """{outfit}（{sex}）—— 角色管线 v2 / **B2 路线**：体形 morph 派生在角色自身网格上
================================================================================

来源：assets/3d/blend/tryon/TryOn_{sex}_{outfit}.blend（Quaternius UBC + Modular Character
      Outfits - Fantasy [Standard]，CC0 / 见源包 License）
加工：tools/3d/garment/derive_on_character.py（headless Blender {blender}）
契约：assets/3d/rig/SPEC.md v1.0 §3.3 / §4.0（B2）/ §5

为什么是 B2（Lead FINDINGS §11.4 / §12，SPEC F17）
-------------------------------------------------
这个文件**就是最终角色**：服装布料 + 服装自带皮肤（`MI_Regular_*`，即同源的 Regular 身体可见部分）
+ 基础体捐的头。**里面没有独立的 Superhero 标准体。**
→ 所以"标准体与服装体形基准不一致"这个矛盾**不存在**：
  布料 / 皮肤 / 头**共用同一副 rig、同一组骨变换** → 体形一变三者**同构地一起变**，
  **结构性不存在穿模**。
→ 也因此**不需要** B1 路线的三步（剥离皮肤面 / 贴合标准体 / 从身体传递 morph）。

内容
----
· {nmesh} 件网格，共 {nverts} 顶点（**每件都持有同名同序 morph**）
· 骨架：`{arm}`（**角色自己的 rig**，B2 下不新建、也不共用外部骨架）
· morph 通道（索引即契约，SPEC §3.3）：index 0 = `BS_Thin`（瘦）、index 1 = `BS_Heavy`（壮）
  口径 = **girth** `pose_scale=(s,1,s)`：只缩垂直于骨轴的两轴，**骨长不变** → 与身高正交
  运行时权重 ∈ [0,1]，默认 0。身高不走 morph，用骨架 `root` 等比缩放（h ∈ [0.92, 1.08]）。
· 体形骨 {nbones} 根的直接子骨已设 `inherit_scale='NONE'`（SPEC §3.2 / F6），缩放不沿骨架链传递

⚠ 已知边界（SPEC §4.0）
-----------------------
B2 **不能做"裸露躯干"的服装**（泳装 / 裸甲）：那时体形变化没有载体
（布料太少、又没有独立身体可参照）。若将来要这类资产，需回到 B1（同源标准体 + 传递）。

统计
----
· 身高比（体形与身高正交的判据，要 ≈1.0000）：BS_Thin {r_thin} / BS_Heavy {r_heavy}
· morph 数据量：{nverts} 顶点 × 12 B × 2 档 = {kb} KB
"""


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="derive_on_character.py")
    ap.add_argument("--tryon", default=os.path.join(ROOT_TRYON :=
                                                   os.path.join(C.ROOT, "assets/3d/blend/tryon")))
    ap.add_argument("--out", dest="outd", default=C.GARMENTS)
    ap.add_argument("--report", default=os.path.join(C.WORK, "b2_report.json"))
    ap.add_argument("--only", default=None)
    return ap.parse_args(argv)


def source_fingerprint(path):
    """系数源指纹：内容 sha256 + mtime + size（用于偏斜守卫与人眼对账）。"""
    if not path or not os.path.exists(path):
        return None
    b = open(path, "rb").read()
    out = {"file": C.rel(path),
           "sha256": hashlib.sha256(b).hexdigest(),
           "sha256_16": hashlib.sha256(b).hexdigest()[:16],
           "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path))),
           "size": len(b)}
    # 顺手带上**语义指纹** —— 守卫要靠它区分"语义变化"与"仅台账变化"，
    # 不能让调用方负责注入（否则调用方一忘，诊断就退化成"无法判定"）。
    try:
        j = json.loads(b)
        out["coefficients_fingerprint"] = j.get("coefficients_fingerprint")
        out["spec_version"] = j.get("spec_version")
        out["version"] = j.get("version")
    except Exception:
        pass
    return out


def _semantic_key(path):
    """系数源的**语义指纹**（bodyshape 提供的 coefficients_fingerprint）：系数一变它必变。"""
    try:
        return json.loads(open(path, "rb").read()).get("coefficients_fingerprint")
    except Exception:                                            # pragma: no cover
        return None


def assert_source_unchanged(fp, where):
    """⭐ 偏斜守卫：系数源在「我读取之后、写产物之前」被改动 → 直接报错退出。

    为什么必须做：2026-10-13 实际发生过一次 —— 我在 18:20:20 读到 bodyshape 的 **v1**
    manifest（thin 0.86 / heavy 1.16），而它在 18:20:43 才落盘 **v2**（0.84 / 1.21）。
    结果：`BS_Heavy=1` 在标准体上代表"v2 壮"、在我的角色上代表"v1 壮" → **同名 morph 语义不一致**。
    静默用旧值是这类事故最坏的形态，所以这里宁可硬失败。
    """
    if fp is None:
        return
    ap = os.path.join(C.ROOT, fp["file"])
    now = source_fingerprint(ap)
    if now is None or now["sha256"] != fp["sha256"]:
        got = now["sha256_16"] if now else "<文件消失>"
        sem_old, sem_new = fp.get("coefficients_fingerprint"), _semantic_key(ap)
        if sem_old and sem_new and sem_old == sem_new:
            kind = ("仅**台账/格式**变化（coefficients_fingerprint **未变** → 系数与 morph 数值应逐位相同）"
                    "→ 重跑刷新溯源即可，不必重新设计任何东西")
        elif sem_old and sem_new:
            kind = ("**语义变化**（coefficients_fingerprint 也变了）"
                    "→ 产物与标准体的 morph 语义将不一致，**必须重跑**")
        else:
            kind = "无法判定语义指纹（旧/新文件缺字段）→ 按语义变化处理"
        raise SystemExit(
            f"\n[偏斜守卫] ❌ 系数源 {fp['file']} 在我读取之后被改动（{where}）\n"
            f"           读取时 sha256[:16] = {fp['sha256_16']} (mtime {fp['mtime']})\n"
            f"           现在   sha256[:16] = {got}\n"
            f"           判定：{kind}\n"
            f"           → **拒绝写出**（静默用旧值是这类事故最坏的形态）。请重跑本工具。")


def tier_settings():
    """从 T1 产物读档位（单一事实来源），返回 (tiers, resp, src, spec_sha, fp, scales, prov)。

    ⭐ **尺度一律取 manifest 的 `tiers[].bones_applied`** —— 那是 bodyshape 实际摆上去的
    **三轴向量**，不是我自己推的。为什么必须这样：
      v2 新增 `along_axis_response`（**只有 clavicle = 0.5**），锁骨骨的 scale 是
      `(s, 1+(coef−1)·0.5, s)` 而**不是** `(s, 1, s)`（实测 BS_Heavy: `[1.168, 1.105, 1.168]`）。
      自己写死 `(s,1,s)` 会**静默丢掉肩宽/臂展那一项**（约 2%）。
    ⚠ 别拿 `bones_canonical_girth` 去摆骨 —— 那是 spec 里存的规范形 `(s,1,s)`，
      bodyshape 自己在这里踩过 11.6 mm 的假差。
    """
    tiers, resp = dict(DEFAULT_TIERS), dict(DEFAULT_RESP)
    src, spec_sha, scales = "内置默认（未找到 bodyshape_manifest.json）", None, {}
    prov = {"scales_source": "内置默认 (s,1,s)（降级）", "spec_version": None,
            "coefficients_fingerprint": None}
    fp = source_fingerprint(BODYSHAPE_MANIFEST)
    if fp:
        try:
            m = json.load(open(BODYSHAPE_MANIFEST, encoding="utf-8"))
            for t in m.get("tiers", []):
                if t.get("shape_key") and t.get("target_coefficient"):
                    tiers[t["shape_key"]] = float(t["target_coefficient"])
                ba = t.get("bones_applied") or {}
                if t.get("shape_key") and ba:
                    scales[t["shape_key"]] = {b: tuple(float(x) for x in v)
                                              for b, v in ba.items()}
            resp = {k: float(v) for k, v in m.get("delta_response", {}).items()
                    if not k.startswith("_")} or resp
            spec_sha = m.get("spec_sha256")
            src = fp["file"]
            prov["spec_version"] = m.get("spec_version")
            prov["coefficients_fingerprint"] = m.get("coefficients_fingerprint")
            prov["scales_source"] = ("manifest.tiers[].bones_applied（实摆三轴向量）"
                                     if scales else "manifest 无 bones_applied → 降级为 (s,1,s)")
        except Exception as e:                                   # pragma: no cover
            C.log(f"  [warn] 读 {fp['file']} 失败（{e}），用默认档位")
    return tiers, resp, src, spec_sha, fp, scales, prov


def resp_of(bn, resp):
    for k, v in resp.items():
        if bn.startswith(k):
            return v
    return 1.0


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    m = ev.to_mesh()
    pts = [ev.matrix_world @ v.co for v in m.vertices]
    ev.to_mesh_clear()
    return pts


def one(outfit, sex, tryon_dir, out_dir, tiers, resp, src, spec_sha=None, fp=None,
        scales=None, prov=None):
    src_blend = os.path.join(tryon_dir, f"TryOn_{outfit}.blend")   # outfit 已含性别前缀
    C.log(f"\n{'='*100}\n[B2] {outfit}（{sex}）   <- {C.rel(src_blend)}")
    bpy.ops.wm.open_mainfile(filepath=src_blend)

    # 丢辅助体（Icosphere），并记录被丢掉的非网格对象
    junk = [(o.name, o.type) for o in bpy.data.objects
            if o.type in ('CAMERA', 'LIGHT') or C.is_helper(o)]
    for n, _t in junk:
        bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    meshes = sorted([o for o in bpy.data.objects if o.type == 'MESH'], key=lambda x: x.name)
    total_v = sum(len(o.data.vertices) for o in meshes)
    C.log(f"  角色：{len(meshes)} 件网格 / {total_v} 顶点 / 骨架 {arm.name}"
          f"（{len(arm.data.bones)} 骨）  丢弃辅助对象 {junk}")
    C.log(f"  件：{', '.join(o.name for o in meshes)}")

    # ① 体形骨的直接子骨 inherit_scale='NONE'（在 arm.data.bones 上设，不是 PoseBone）
    changed = set()
    missing = [b for b in C.SHAPE_BONES if b not in arm.data.bones]
    for bn in C.SHAPE_BONES:
        if bn not in arm.data.bones:
            continue
        for ch in arm.data.bones[bn].children:
            if ch.inherit_scale != 'NONE':
                ch.inherit_scale = 'NONE'
                changed.add(ch.name)
    C.log(f"  体形骨 {len(C.SHAPE_BONES) - len(missing)}/{len(C.SHAPE_BONES)} 命中"
          + (f"；缺失 {missing}" if missing else "")
          + f"；设 inherit_scale='NONE' 的子骨 {len(changed)} 根")

    # ② 每件先建好通道（**顺序即契约**：Basis / BS_Thin / BS_Heavy）
    for o in meshes:
        if o.data.shape_keys is None:
            o.shape_key_add(name="Basis", from_mix=False)
        for nm in C.MORPH_ORDER[1:]:
            if nm not in o.data.shape_keys.key_blocks:
                o.shape_key_add(name=nm, from_mix=False)
        order = [k.name for k in o.data.shape_keys.key_blocks]
        assert order == C.MORPH_ORDER, f"{o.name} 通道顺序 {order} != 契约 {C.MORPH_ORDER}"

    def clear_pose():
        for pb in arm.pose.bones:
            pb.scale = (1.0, 1.0, 1.0)
            pb.location = (0.0, 0.0, 0.0)
            pb.rotation_mode = 'XYZ'
            pb.rotation_euler = (0.0, 0.0, 0.0)
        bpy.context.view_layer.update()

    clear_pose()
    for o in meshes:
        C.clear_shape_values(o)
    base_h = (lambda zs: max(zs) - min(zs))([p.z for o in meshes for p in eval_pts(o)])
    _xs0 = [p.x for o in meshes for p in eval_pts(o)]
    span_base = max(_xs0) - min(_xs0)
    C.log(f"  角色身高基准 {base_h*100:.2f} cm")

    rec = {"outfit": outfit, "sex": sex, "src": C.rel(src_blend),
           "armature": arm.name, "bones": len(arm.data.bones),
           "junk_removed": junk, "missing_shape_bones": missing,
           "inherit_none_bones": sorted(changed),
           "height_base_cm": round(base_h * 100, 3),
           "coefficient_source": {
               "file": src,
               "spec_sha256": spec_sha,
               "manifest_sha256_16": fp["sha256_16"] if fp else None,
               "manifest_mtime": fp["mtime"] if fp else None,
               "target_coefficients": dict(tiers),
               "delta_response": dict(resp),
               "spec_version": (prov or {}).get("spec_version"),
               "coefficients_fingerprint": (prov or {}).get("coefficients_fingerprint"),
               "scales_source": (prov or {}).get("scales_source"),
               "girth_rule": "x=z=1+(coef−1)·delta_response；y=1+(coef−1)·along_axis_response"
                             "（v2 只有 clavicle=0.5，改肩宽/臂展不改身高）",
               "note": "尺度**直接取 manifest 的 bones_applied（实摆三轴）**，不自行推导；"
                       "该 manifest 同时是标准体的来源 → 同名 morph 语义一致"},
           "tiers_source": src, "tiers": {}, "parts": []}

    # ③ 逐档摆骨 → 逐件烘
    for tier, coef in tiers.items():
        clear_pose()
        applied = {}
        tsc = (scales or {}).get(tier) or {}
        for bn in C.SHAPE_BONES:
            if bn not in arm.pose.bones:
                continue
            v = tsc.get(bn)
            if v is None:                                    # 降级：自己算 (s,1,s)
                s_ = 1.0 + (coef - 1.0) * resp_of(bn, resp)
                v = (s_, 1.0, s_)
            arm.pose.bones[bn].scale = v                     # ← 实摆三轴（含沿骨轴项）
            applied[bn] = [round(x, 6) for x in v]
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        disp_all = []
        for o in meshes:
            ev = o.evaluated_get(dg)
            m = ev.to_mesh()
            kb = o.data.shape_keys.key_blocks[tier]
            for i, v in enumerate(m.vertices):
                kb.data[i].co = v.co
            ev.to_mesh_clear()
            kb.value = 0.0
            d = [(kb.data[i].co - o.data.vertices[i].co).length
                 for i in range(len(o.data.vertices))]
            disp_all += d
        disp_all.sort()
        rec["tiers"][tier] = {
            "target_coefficient": coef,
            "bones_applied": applied,
            "disp_mean_cm": round(100 * sum(disp_all) / len(disp_all), 4),
            "disp_p95_cm": round(100 * disp_all[int(0.95 * (len(disp_all) - 1))], 4),
            "disp_max_cm": round(100 * disp_all[-1], 4),
            "moved_frac": round(sum(1 for d in disp_all if d > 1e-7) / len(disp_all), 5)}
        C.log(f"  烘 {tier}（系数 {coef}）：位移 mean {rec['tiers'][tier]['disp_mean_cm']:6.3f} "
              f"p95 {rec['tiers'][tier]['disp_p95_cm']:6.3f} "
              f"max {rec['tiers'][tier]['disp_max_cm']:6.3f} cm  动过 "
              f"{100*rec['tiers'][tier]['moved_frac']:.1f}%")
    clear_pose()

    # ④ 判据：身高比（体形要与身高正交）
    def char_height():
        return (lambda zs: max(zs) - min(zs))([p.z for o in meshes for p in eval_pts(o)])

    ratios = {}
    for tier in tiers:
        for o in meshes:
            C.clear_shape_values(o)
            o.data.shape_keys.key_blocks[tier].value = 1.0
        bpy.context.view_layer.update()
        ratios[tier] = round(char_height() / base_h, 6)
        for o in meshes:
            o.data.shape_keys.key_blocks[tier].value = 0.0
        bpy.context.view_layer.update()
    rec["height_ratio"] = ratios

    # 臂展（max x − min x）—— bodyshape 的交叉校验项：
    # 瘦应 −1.85%、壮应 +2.08%(女)/+2.78%(男)；**若≈0 说明漏了 along_axis_response**
    def arm_span():
        xs = [p.x for o in meshes for p in eval_pts(o)]
        return max(xs) - min(xs)

    span = {}
    for tier in tiers:
        for o in meshes:
            C.clear_shape_values(o)
            o.data.shape_keys.key_blocks[tier].value = 1.0
        bpy.context.view_layer.update()
        span[tier] = round(arm_span() / span_base - 1.0, 6)
        for o in meshes:
            C.clear_shape_values(o)
        bpy.context.view_layer.update()
    rec["arm_span_change"] = span
    C.log(f"  ★ 臂展变化（交叉校验 bodyshape：瘦 −1.85% / 壮 +2.08%(女) +2.78%(男)）："
          f"{ {k: f'{100*v:+.2f}%' for k, v in span.items()} }")
    C.log(f"  ★ 身高比：{[f'{k} {v:.5f}' for k, v in ratios.items()]}  （判据 ≈1.0000，阈值 ±0.002）")

    # ④b ⚠ 实测冲突（本工具发现）：`inherit_scale='NONE'` 与「身高用 root 等比缩放」**不相容**
    #     'NONE' 让子骨不继承父骨的 scale → root 放大时只有部分骨段跟着长 → 拉伸比离散度爆掉。
    #     但 'NONE' 只在**烘焙期间**需要（防止体形骨缩放沿骨架链外传）；
    #     烘完、清 pose 之后它就是历史包袱 → **必须还原成 'FULL'**，否则运行时身高缩放失真。
    def root_scale_dispersion():
        for o in meshes:
            C.clear_shape_values(o)
        for pb in arm.pose.bones:
            pb.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        arm.pose.bones["root"].scale = (1.08, 1.08, 1.08)
        bpy.context.view_layer.update()
        disp = 0.0
        for o in meshes:
            p0 = [(v.co.copy()) for v in o.data.vertices]
            dg = bpy.context.evaluated_depsgraph_get()
            ev = o.evaluated_get(dg)
            m = ev.to_mesh()
            p1 = [ev.matrix_world @ v.co for v in m.vertices]
            ev.to_mesh_clear()
            # 用世界坐标的 rest 做基准
            rr = [o.matrix_world @ v.co for v in o.data.vertices]
            rs = []
            for e in o.data.edges:
                a, b = e.vertices
                l0 = (rr[a] - rr[b]).length
                if l0 > 1e-7:
                    rs.append((p1[a] - p1[b]).length / l0)
            if rs:
                rs.sort()
                med = rs[len(rs) // 2]
                norm = [r / med for r in rs]
                mean = sum(norm) / len(norm)
                var = sum((x - mean) ** 2 for x in norm) / len(norm)
                disp = max(disp, var ** 0.5)
        arm.pose.bones["root"].scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        return disp

    disp_none = root_scale_dispersion()
    for bn in C.SHAPE_BONES:
        if bn not in arm.data.bones:
            continue
        for ch in arm.data.bones[bn].children:
            ch.inherit_scale = 'FULL'
    disp_full = root_scale_dispersion()
    rec["inherit_scale_conflict"] = {
        "root_scale_1.08_dispersion_with_NONE": round(disp_none, 6),
        "root_scale_1.08_dispersion_with_FULL": round(disp_full, 6),
        "decision": "烘焙期间用 NONE（防体形骨缩放沿链外传）；烘完还原 FULL（否则身高缩放失真）",
        "threshold": 0.01}
    C.log(f"  ★ inherit_scale 冲突实测：root×1.08 拉伸离散度 NONE {disp_none:.4f} → "
          f"FULL {disp_full:.4f}（阈值 0.01）→ 已还原 FULL")

    # ④c morph 数值指纹（逐档）—— **约定必须钉死，否则两个人都算得出数字却对不上**：
    #     ① 作用域：该角色**全部件网格**，按 **object.name 排序**
    #     ② 取值：`key_blocks[tier].data[i].co` —— **绝对（物体空间）坐标**，
    #        **不是**相对 Basis 的偏移量（两种口径算出来完全不同！）
    #     ③ 打包：逐顶点 `struct.pack("<3f", x, y, z)`，按 vertex 顺序
    #     ④ 取 sha256 前 16 位十六进制
    #     实测反例（Female_Ranger BS_Thin）：abs = e5346f1cf12a6dbe ✅ / delta = 4176e0edb5713f1f ❌
    #     （bodyshape 用 check_digest_convention.py 独立复算 8/8 逐位相同，并补上了②这条）
    def morph_digest(tier):
        h = hashlib.sha256()
        for o in sorted(meshes, key=lambda x: x.name):
            kb = o.data.shape_keys.key_blocks[tier]
            for v in kb.data:
                h.update(struct.pack("<3f", v.co.x, v.co.y, v.co.z))
        return h.hexdigest()[:16]

    for tier in tiers:
        rec["tiers"][tier]["morph_digest_16"] = morph_digest(tier)
        C.log(f"  morph digest {tier} = {rec['tiers'][tier]['morph_digest_16']}")

    # ⑤ 每件自检
    ok_all = True
    for o in meshes:
        kb = o.data.shape_keys.key_blocks
        order = [k.name for k in kb]
        same = all(len(k.data) == len(o.data.vertices) for k in kb)
        ok = (order == C.MORPH_ORDER) and same
        ok_all &= ok
        rec["parts"].append({
            "part": o.name, "verts": len(o.data.vertices), "faces": len(o.data.polygons),
            "shape_keys": order, "key_len_ok": same,
            "materials": [m.name if m else None for m in o.data.materials],
            "vertex_groups": len(o.vertex_groups),
            "morph_bytes_per_key": len(o.data.vertices) * 12})
    assert ok_all, f"{outfit} 有件未通过 morph 契约自检"
    rec["morph_bytes_total"] = sum(p["morph_bytes_per_key"] for p in rec["parts"]) * len(tiers)
    rec["total_verts"] = total_v
    rec["parts_count"] = len(meshes)

    # ⑥ 内嵌中文说明 + 保存
    tn = "README_转换说明"
    if tn in bpy.data.texts:
        bpy.data.texts.remove(bpy.data.texts[tn])
    bpy.data.texts.new(tn).write(README_TMPL.format(
        outfit=outfit, sex=sex, blender=bpy.app.version_string, nmesh=len(meshes),
        nverts=total_v, arm=arm.name, nbones=len(C.SHAPE_BONES) - len(missing),
        r_thin=ratios.get("BS_Thin", 0), r_heavy=ratios.get("BS_Heavy", 0),
        kb=round(rec["morph_bytes_total"] / 1024)))

    miss_tx = C.texture_report()
    rec["texture_missing"] = miss_tx
    C.purge_orphans()
    out = os.path.join(out_dir, f"{outfit}.blend")   # outfit 已含性别前缀
    assert_source_unchanged(fp, f"写 {outfit}.blend 之前")     # ⭐ 偏斜守卫
    C.save_blend(out)
    rec["out"] = C.rel(out)
    rec["size_kb"] = round(os.path.getsize(out) / 1024)
    return rec


def main():
    a = parse_args()
    os.makedirs(a.outd, exist_ok=True)
    tiers, resp, src, spec_sha, fp, scales, prov = tier_settings()
    C.log(f"档位系数 {tiers}（来源：{src}）")
    C.log(f"delta_response {resp}")
    if fp:
        C.log(f"  系数源指纹：manifest sha256[:16]={fp['sha256_16']}  mtime={fp['mtime']}"
              f"  size={fp['size']}")
        C.log(f"  spec_version={prov['spec_version']}  spec_sha256[:16]={str(spec_sha)[:16]}")
        C.log(f"  ⭐ coefficients_fingerprint={prov['coefficients_fingerprint']}")
        C.log(f"  ⭐ 尺度来源：{prov['scales_source']}"
              + (f"（tiers 有 bones_applied：{sorted(scales)}）" if scales else ""))
    else:
        C.log("  ⚠ 未找到系数源，使用内置默认档位（产物可能与其他成员不一致）")
    recs = []
    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        recs.append(one(outfit, sex, a.tryon, a.outd, tiers, resp, src, spec_sha, fp,
                        scales, prov))
    os.makedirs(os.path.dirname(a.report), exist_ok=True)
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump({"tool": "derive_on_character.py",
                   "route": "B2（SPEC §4.0 / F17）：体形 morph 派生在角色自身网格上",
                   "girth_rule": "pose_scale=(s,1,s)，骨长不变 → 体形与身高正交",
                   "tiers_source": src,
                   "spec_version": prov["spec_version"],
                   "coefficients_fingerprint": prov["coefficients_fingerprint"],
                   "scales_source": prov["scales_source"],
                   "spec_sha256": spec_sha,
                   "manifest_sha256_16": fp["sha256_16"] if fp else None,
                   "manifest_mtime": fp["mtime"] if fp else None,
                   "manifest_version": (fp or {}).get("version"),
                   "tiers": tiers, "delta_response": resp,
                   "boundary": "B2 不能做'裸露躯干'的服装（泳装/裸甲）：体形变化没有载体",
                   "outfits": recs}, f, ensure_ascii=False, indent=2)
    C.log(f"\n{'#'*100}\n# B2 汇总\n{'#'*100}")
    C.log(f"  {'outfit':16s} {'件':>3s} {'顶点':>7s} {'Thin 身高比':>12s} {'Heavy 身高比':>13s} "
          f"{'morph KB':>9s} {'max 位移 cm':>12s} {'文件 KB':>8s}")
    for r in recs:
        mx = max(r["tiers"][t]["disp_max_cm"] for t in r["tiers"])
        C.log(f"  {r['outfit']:16s} {r['parts_count']:3d} {r['total_verts']:7d} "
              f"{r['height_ratio']['BS_Thin']:12.5f} {r['height_ratio']['BS_Heavy']:13.5f} "
              f"{r['morph_bytes_total']/1024:9.0f} {mx:12.3f} {r['size_kb']:8d}")
    assert_source_unchanged(fp, "写 b2_report.json 之前")          # ⭐ 偏斜守卫
    C.log(f"\n报告 → {C.rel(a.report)}\nDONE")


main()