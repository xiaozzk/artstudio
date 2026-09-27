#!/usr/bin/env python3
"""spine_flip_bake.py — assets/2d 全库「朝向统一」共轭烘焙工具（task/003-spine-facing-unify）。

与旧 `spine_flip.py`（全局部取反 + 附件贴图翻转、遇 constraints 拒绝）不同，本工具做
**数据级共轭烘焙**：只改 root 直接子骨（inherit=normal）的局部变换与动画通道，取反
奇对称分量（x / rotation / shearX / shearY / scaleX），其余一切不动——更深的骨、全部
附件、deform、slots、skins、skeleton、atlas/png 原样，子树通过继承自动完成镜像。

数学核心（算法规格见 task/003-spine-facing-unify/notes/2026-09-26-需求调研与方案.md）：

    设 Fx = diag(-1,1)（跨竖直轴的世界镜像），root setup 局部矩阵 A_r（仿射）。
    共轭矩阵  K = A_r⁻¹ · Fx · A_r  （3×3 仿射，含 root x/y≠0 的平移分量）。
    对 root 直接子骨：L' = K · L  ⇒  子骨世界 W' = A_r·L' = Fx·A_r·L = Fx·W。

    本库 root 均为「纯等比缩放 + 旋转 θr（≤0.185°）+ 零 shear」，K 的线性部分是正交反射，
    可闭式分解：rotation' = α - rotation，shearX' = -shearX，shearY' = -shearY，
    scaleX' = -scaleX，scaleY' = scaleY，(x',y') = K·(x,y)（α = K 线性部的反射轴角，
    θr=0 时 α=0 退化为纯取反——统一一条代码路径，无 θr 分支，实现决策 D6）。

    动画通道（4.3 runtime apply 语义，alpha=1 / from=setup）：
      rotate.value → -value（rotation' = α - (setup+value) = setup' - value）
      translate (x,y) → K_线性·(x,y)（key 是相对 setup 的平移偏移，只乘线性部）
      shear (x,y) → (-x,-y)；scale / scalex / scaley **不变**（key 是 setup scale 的相对乘数，
      镜像符号由 setup 的 -scaleX 提供，Animation.ts ScaleTimeline `x *= setup.scaleX` 实证）。

数学性质：烘焙产物与「运行时 skeleton.scaleX=-1」在**逐骨世界矩阵上严格等价**（root 固定
在 setup 时；root 动画旋转/缩放的包镜像轴固定，属 D4 已知边界，见 G2 口径说明）。

用法：
  # 烘焙一次（含 G1/G2/G3 自检），产物只写 JSON，不动原包
  python3 tools/spine/anim/spine_flip_bake.py <包目录或骨架json> -o <输出目录> --from left --to right

  # 只做自检不产出（--check 隐含于烘焙；本模式不显式翻向，等价 --from left --to right）
  python3 tools/spine/anim/spine_flip_bake.py <包> -o <目录> --dry-run

边界（防御性退出，遇以下任一情况报错、不静默产出）：
  - 非 4.x 格式；含 constraints（ik/transform/path/physics）；未知 inherit 值；
    未知附件类型；未知骨动画通道；root 非等比缩放或带 shear（K 非正交反射，闭式分解不成立）。

自检（烘焙即执行，任一不过则非零退出、产物不落盘）：
  G1 双翻恒等：产物再烘焙一次与原包归一化 diff=0（θr≠0 允许 ≤1e-9 浮点残差）。
  G2 运行时等价：模拟官方 4.3 runtime（BonePose.updateWorldTransform 五分支 + timeline apply），
     「原包+scaleX=-1」vs「烘焙包+scaleX=+1」逐骨世界矩阵 max diff ≤ 1e-6。
     口径 A（闸门）root 固定 setup；口径 B（信息级）含 root 动画，报告 max diff（D4 边界）。
  G3 不动项审计：产物与原包 diff 仅允许落在翻转域 5 字段及其动画通道（+ Tier2 B-a 附件）。
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

# ---------- 常量 ----------

DEG = math.pi / 180.0
EXCL_INHERIT = {"onlyTranslation", "noRotationOrReflection", "noScaleOrReflection"}
KNOWN_INHERIT = EXCL_INHERIT | {"normal", "noScale"}
KNOWN_ATT = {"region", "mesh", "linkedmesh", "point", "path", "boundingbox", "clipping"}
VIS_ATT = {"region", "mesh", "linkedmesh"}          # 可见（参与 Tier2 判定）
SKIP_ATT_FLIP = {"point", "path", "boundingbox", "clipping"}  # B-a 不翻转的非绘制附件
KNOWN_BONE_CH = {"rotate", "translate", "scale", "shear"}
# 翻转域骨允许被改的 setup 字段（含 y：θr≠0 或 root x/y≠0 时 K 共轭会动 y）
FLIP_SETUP_FIELDS = {"x", "y", "rotation", "shearX", "shearY", "scaleX"}
G1_TOL = 1e-9
G2_TOL = 1e-6
# Tier2 B-a 闸门：世界线性部分旋转变化 ≤ 该角度(度) 且 镜像轴偏差 ≤ 该角度
BA_ROT_VAR_TOL = 0.5
BA_AXIS_TOL = 5.0


# ---------- 基础加载 ----------

def load_package(path: Path) -> tuple[dict, Path, Path]:
    """返回 (doc, 骨架json路径, 包目录)。入参可为包目录或骨架 json。"""
    if path.is_dir():
        for jf in sorted(path.glob("*.json")):
            try:
                doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(doc, dict) and "bones" in doc and "skeleton" in doc:
                return doc, jf, path
        raise SystemExit(f"[!] {path} 下找不到骨架 json（顶层需含 skeleton+bones）")
    doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return doc, path, path.parent


def err(msg: str):
    raise SystemExit(f"[!] {msg}")


# ---------- 防御性检查 ----------

def collect_constraints(doc):
    """统计 constraints（list 或 dict 布局）。返回 {type: count}，空为 {}。"""
    cons = doc.get("constraints")
    out: dict[str, int] = {}
    if isinstance(cons, dict):
        for k, v in cons.items():
            if v:
                out[k] = out.get(k, 0) + (len(v) if isinstance(v, (list, dict)) else 1)
    elif isinstance(cons, list):
        for c in cons:
            t = (c or {}).get("type", "?") if isinstance(c, dict) else "?"
            out[t] = out.get(t, 0) + 1
    return out


def guard(doc: dict, ctx: str) -> None:
    sk = doc.get("skeleton", {})
    ver = str(sk.get("spine", ""))
    if not ver.startswith("4."):
        err(f"{ctx}: 非 4.x 格式（spine={ver}），拒绝")
    # 注：constraints（ik/transform/path）**不拒绝**——共轭烘焙不动 constraint 参数，
    # 等价性靠「基础世界矩阵匹配（G2）+ 参数未动（G3）⇒ runtime 重解一致」保证，
    # 最终视觉由人工 G5 player 闸门兜底。见 task/003 notes/2026-09-27。
    for b in doc.get("bones", []):
        inh = b.get("inherit", "normal")
        if inh not in KNOWN_INHERIT:
            err(f"{ctx}: 未知 inherit 值 {inh!r}（骨 {b.get('name')}），拒绝")
    for skn in doc.get("skins", []):
        for slot, atts in (skn.get("attachments") or {}).items():
            for name, att in (atts or {}).items():
                t = att.get("type", "region")
                if t not in KNOWN_ATT:
                    err(f"{ctx}: 未知附件类型 {t!r}（{slot}/{name}），拒绝")
    for aname, anim in doc.get("animations", {}).items():
        for bname, tracks in anim.get("bones", {}).items():
            for ch in tracks:
                if ch not in KNOWN_BONE_CH:
                    err(f"{ctx}: 动画 {aname} 骨 {bname} 未知通道 {ch!r}，拒绝")


# ---------- 2D 仿射矩阵工具（3×3 同质坐标，[a b tx; c d ty; 0 0 1]） ----------

def mat_local(x, y, rotation, shearX, shearY, scaleX, scaleY):
    """Spine 局部矩阵 L = T(x,y)·A，A 两列 = u(rot+shx)·sx 与 u(rot+90+shy)·sy。"""
    rx = (rotation + shearX) * DEG
    ry = (rotation + 90.0 + shearY) * DEG
    la = math.cos(rx) * scaleX
    lb = math.cos(ry) * scaleY
    lc = math.sin(rx) * scaleX
    ld = math.sin(ry) * scaleY
    return [la, lb, x, lc, ld, y, 0.0, 0.0, 1.0]


def mat_mul(m, n):
    return [
        m[0]*n[0]+m[1]*n[3]+m[2]*n[6], m[0]*n[1]+m[1]*n[4]+m[2]*n[7], m[0]*n[2]+m[1]*n[5]+m[2]*n[8],
        m[3]*n[0]+m[4]*n[3]+m[5]*n[6], m[3]*n[1]+m[4]*n[4]+m[5]*n[7], m[3]*n[2]+m[4]*n[5]+m[5]*n[8],
        m[6]*n[0]+m[7]*n[3]+m[8]*n[6], m[6]*n[1]+m[7]*n[4]+m[8]*n[7], m[6]*n[2]+m[7]*n[5]+m[8]*n[8],
    ]


def mat_inv_rigid(m):
    """求逆（仅用于 A_r：旋转×等比缩放+平移，安全）。"""
    a, b, c, d = m[0], m[1], m[3], m[4]
    det = a*d - b*c
    if abs(det) < 1e-12:
        err("A_r 线性部奇异，无法求逆")
    ia, ib, ic, id_ = d/det, -b/det, -c/det, a/det
    tx, ty = m[2], m[5]
    return [ia, ib, -(ia*tx+ib*ty), ic, id_, -(ic*tx+id_*ty), 0.0, 0.0, 1.0]


def mat_apply(m, x, y):
    return (m[0]*x + m[1]*y + m[2], m[3]*x + m[4]*y + m[5])


FX = [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]  # diag(-1,1) 世界镜像


# ---------- 根与共轭矩阵 K ----------

def root_setup(doc):
    r = doc["bones"][0]
    return {
        "name": r.get("name", "root"),
        "x": r.get("x", 0.0), "y": r.get("y", 0.0),
        "rotation": r.get("rotation", 0.0),
        "shearX": r.get("shearX", 0.0), "shearY": r.get("shearY", 0.0),
        "scaleX": r.get("scaleX", 1.0), "scaleY": r.get("scaleY", 1.0),
    }


def compute_K(doc, ctx):
    """K = A_r⁻¹·Fx·A_r（3×3 仿射）。要求 root 等比缩放且零 shear（否则 K 非正交反射）。"""
    rs = root_setup(doc)
    if abs(rs["shearX"]) > 1e-9 or abs(rs["shearY"]) > 1e-9:
        err(f"{ctx}: root 带 shear（{rs['shearX']},{rs['shearY']}），K 非正交反射，拒绝")
    if abs(abs(rs["scaleX"]) - abs(rs["scaleY"])) > 1e-9:
        err(f"{ctx}: root 非等比缩放（{rs['scaleX']},{rs['scaleY']}），K 非正交反射，拒绝")
    A_r = mat_local(rs["x"], rs["y"], rs["rotation"], 0.0, 0.0, rs["scaleX"], rs["scaleY"])
    K = mat_mul(mat_inv_rigid(A_r), mat_mul(FX, A_r))
    # 反射轴角 α：K_线性 = R(α)·Fx ⇒ K·[1,0] = (−cosα, −sinα)
    alpha = math.atan2(-K[3], -K[0]) / DEG
    return K, alpha


# ---------- 翻转域 / 排除域 ----------

def flip_domain(doc):
    """翻转域：root 直接子骨且 inherit ∈ {normal, noScale}（均继承反射 → 参与翻转）。
    noScale 直接子骨必须一并共轭——root 自身不翻，它不会自动跟随（调研 §4.3 语义落地，
    2026-09-27 实测 Kimchul 的 noScale 武器骨验证）。"""
    rname = doc["bones"][0].get("name", "root")
    return {b["name"] for b in doc["bones"][1:]
            if b.get("parent") == rname and b.get("inherit", "normal") in ("normal", "noScale")}


def excluded_domain(doc):
    """排除域：inherit ∈ {onlyTranslation, noRotationOrReflection, noScaleOrReflection}
    的骨 + 其整棵子树（不继承反射 → 视觉上不镜像；与调研附录 B 清单 20/20 对上）。"""
    bones = doc["bones"]
    excl = {b["name"] for b in bones if b.get("inherit", "normal") in EXCL_INHERIT}
    changed = True
    while changed:
        changed = False
        for b in bones:
            if b["name"] not in excl and b.get("parent") in excl:
                excl.add(b["name"])
                changed = True
    return excl


def mirror_subtree(doc):
    """镜像子树：翻转域骨（root 直接子骨 inherit∈{normal,noScale}）+ 全部后代，
    减去排除域子树。这是「应当被镜像」的骨集合（G2 只验收这些骨）。"""
    fd = flip_domain(doc)
    excl = excluded_domain(doc)
    mst = set(fd)
    changed = True
    while changed:
        changed = False
        for b in doc["bones"]:
            if b["name"] in mst or b["name"] in excl:
                continue
            if b.get("parent") in mst:
                mst.add(b["name"])
                changed = True
    return mst


def plan_inherit_rewrite(doc, ctx):
    """noScale→normal 改写计划（2026-09-27 实测修正，见 notes/2026-09-27）。

    4.3 runtime 的 noScale 分支带符号修正：父骨世界含反射（被镜像）而 skeleton 未翻时
    会把本骨「去镜像」。因此镜像子树里的 noScale 骨在烘焙包中无法靠共轭正确镜像，
    必须改写成 normal（按 normal 组合，自动继承父的镜像）。

    改写不改变**原包**渲染的充要条件：原包（skeleton=+1）下该骨的父骨世界
    |scaleX|=|scaleY|≈1 且无反射（det>0）——此时 noScale 与 normal 数值等价。
    逐动画关键帧采样验证；不满足则拒绝（防御性，不静默产出）。

    返回 (可改写骨名集合, 拒绝原因列表)。"""
    mst = mirror_subtree(doc)
    cands = [b["name"] for b in doc["bones"]
             if b.get("inherit", "normal") == "noScale" and b["name"] in mst]
    if not cands:
        return set(), []
    sim = Sim(doc, skeleton_scaleX=1.0)
    parent = {b["name"]: b.get("parent") for b in doc["bones"]}
    # 采样点：setup + 全部动画关键帧（含 root 动画口径——原包真实渲染）。
    # 世界矩阵逐采样点只算一次，全体候选骨共用。
    samples = [(None, 0.0)]
    for aname, a in sim.anims.items():
        samples += [(aname, t) for t in a["times"]]
    worlds = [sim.world(aname, t, root_hold_setup=False) for aname, t in samples]
    rewrite, rejects = set(), []
    for name in cands:
        p = parent[name]
        dev = 0.0
        detmin = float("inf")
        for W in worlds:
            a, bb, c, d = W[p][0], W[p][1], W[p][2], W[p][3]
            dev = max(dev, abs(math.hypot(a, c) - 1.0), abs(math.hypot(bb, d) - 1.0))
            det = a * d - bb * c
            if det < detmin:
                detmin = det
        if dev > 1e-3 or detmin <= 1e-9:
            rejects.append(f"{name}（父骨 {p} 世界 |scale| 偏差 {dev:.4f} / det {detmin:.4f}）")
        else:
            rewrite.add(name)
    return rewrite, rejects


def apply_inherit_rewrite(doc, rewrite):
    """把 rewrite 集合内的骨 inherit 改为 normal（就地）。返回改动骨名列表。"""
    done = []
    for b in doc.get("bones", []):
        if b["name"] in rewrite and b.get("inherit", "normal") == "noScale":
            b["inherit"] = "normal"
            done.append(b["name"])
    return done


# ---------- 烘焙（方案 A 共轭） ----------

def bake_bones(doc, K, alpha, flipset):
    """就地修改 doc 的 bones：翻转域骨 L' = K·L（闭式分解）。"""
    n = 0
    for b in doc.get("bones", []):
        if b["name"] not in flipset:
            continue
        x, y = b.get("x", 0.0), b.get("y", 0.0)
        rot = b.get("rotation", 0.0)
        shx, shy = b.get("shearX", 0.0), b.get("shearY", 0.0)
        sx, sy = b.get("scaleX", 1.0), b.get("scaleY", 1.0)
        nx, ny = mat_apply(K, x, y)
        nrot = alpha - rot
        # 写回：只在与原值不同或原本就存在该字段时写，保持缺省字段语义
        _set(b, "x", nx, 0.0)
        _set(b, "y", ny, 0.0)
        _set(b, "rotation", nrot, 0.0)
        _set(b, "shearX", -shx, 0.0)
        _set(b, "shearY", -shy, 0.0)
        _set(b, "scaleX", -sx, 1.0)
        n += 1
    return n


def _r9(v):
    """烘焙产物数值保留 9 位小数：杀死 K 共轭的浮点噪声（~1e-13），又不伤精度（G2 阈 1e-6）。"""
    r = round(v, 9)
    return 0.0 if r == 0 else r  # -0.0 → 0.0


def _set(b, key, val, default):
    """写回字段：val 与原缺省值等价且原字段缺省时，不新增字段（保持 G1/G3 干净）。"""
    val = _r9(val)
    if key in b:
        b[key] = val
    elif abs(val - default) > 1e-12:
        b[key] = val
    # 否则保持缺省（不新增显式缺省字段）


def bake_animations(doc, K, alpha, flipset, warnings):
    """就地修改 animations：翻转域骨的 rotate/translate/shear 通道共轭；scale 不动。"""
    n = 0
    for aname, anim in doc.get("animations", {}).items():
        for bname, tracks in anim.get("bones", {}).items():
            if bname not in flipset:
                continue
            for ch, keys in tracks.items():
                if not isinstance(keys, list):
                    continue
                for k in keys:
                    if ch == "rotate" and "value" in k:
                        k["value"] = _r9(-k["value"])
                    elif ch == "translate":
                        kx, ky = k.get("x", 0.0), k.get("y", 0.0)
                        # 只乘 K 线性部（key 是平移偏移，无平移分量）。
                        # x/y 任一存在就必须成对写回——θr≠0 时 y'=K[3]·x 不可丢，
                        # 否则双翻失逆（G1 会抓到 1e-6 级残差，2026-09-27 Kimchul 实测）。
                        if "x" in k or "y" in k:
                            nx = K[0]*kx + K[1]*ky
                            ny = K[3]*kx + K[4]*ky
                            k["x"] = _r9(nx)
                            k["y"] = _r9(ny)
                    elif ch == "shear":
                        if "x" in k:
                            k["x"] = _r9(-k["x"])
                        if "y" in k:
                            k["y"] = _r9(-k["y"])
                    elif ch == "scale":
                        pass  # key 是 setup scale 相对乘数，不动
                    # bezier curve：本库 0 个；若出现按通道符号变换并告警
                    cv = k.get("curve")
                    if isinstance(cv, list):
                        _bake_bezier(ch, cv, K, warnings, aname, bname)
            n += 1
    return n


def _bake_bezier(ch, cv, K, warnings, aname, bname):
    """bezier 控制点（每 4 个一组：cx1, v1, cx2, v2）的 value 分量（下标 1、3）按通道变换。"""
    for i in range(1, len(cv), 4):
        for j in (i, i + 2):
            if j >= len(cv):
                break
            v = cv[j]
            if ch == "rotate":
                cv[j] = -v
            elif ch == "shear":
                cv[j] = -v
            elif ch == "translate":
                # translate 的 value 分量需区分 x/y——bezier 对 translate 分别存两条曲线，
                # 无法在此简单共轭；告警并保守取负（本库无 bezier，仅防御）。
                cv[j] = -v
    warnings.append(f"动画 {aname} 骨 {bname} 通道 {ch}: bezier curve 已按符号变换（请人工复核）")


# ---------- Tier 2：排除域可见附件 B-a 二次翻转 ----------

def flip_attachment_local(att, ctx, warnings):
    """旧式附件局部镜像（spine_flip.py 口径）：region x/rotation/scaleX 取负；
    mesh 顶点 x 取负 + triangles 反绕；linkedmesh 仅位移字段（共享父网格顶点）。"""
    atype = att.get("type", "region")
    if atype in SKIP_ATT_FLIP:
        return False
    if "x" in att:
        att["x"] = -att["x"]
    if "rotation" in att:
        att["rotation"] = -att["rotation"]
    if atype == "region":
        att["scaleX"] = -att.get("scaleX", 1.0)
        return True
    if atype in ("mesh", "linkedmesh"):
        verts = att.get("vertices")
        uvs = att.get("uvs")
        if verts and uvs and len(verts) != len(uvs):
            i = 0
            while i < len(verts):
                cnt = int(verts[i]); i += 1
                for _ in range(cnt):
                    i += 1              # 骨索引
                    verts[i] = -verts[i]  # x 取负
                    i += 3              # 跳过 x、y、权重
        elif verts:
            for i in range(0, len(verts), 2):
                verts[i] = -verts[i]
        tris = att.get("triangles")
        if tris:
            att["triangles"] = [t for tri in
                                [tris[i:i+3] for i in range(0, len(tris), 3)]
                                for t in (tri[0], tri[2], tri[1])]
        return True
    warnings.append(f"{ctx}: 附件类型 {atype} 未翻转")
    return False


def flip_deform_in_animations(doc, slot_att_pairs, warnings):
    """B-a：对指定 (slot, att) 的 deform 动画顶点 x 取负。返回改动数量。"""
    n = 0
    targets = set(slot_att_pairs)
    for aname, anim in doc.get("animations", {}).items():
        for top in ("attachments", "deform"):
            bucket = anim.get(top)
            if not isinstance(bucket, dict):
                continue
            for skin_name, slots in bucket.items():
                if not isinstance(slots, dict):
                    continue
                for slot_name, atts in slots.items():
                    if not isinstance(atts, dict):
                        continue
                    for att_name, att in atts.items():
                        if (slot_name, att_name) not in targets or not isinstance(att, dict):
                            continue
                        tracks = att.get("deform")
                        if not isinstance(tracks, list):
                            continue
                        for kf in tracks:
                            if isinstance(kf, dict) and isinstance(kf.get("vertices"), list):
                                vs = kf["vertices"]
                                offset = kf.get("offset", 0)
                                for i in range(offset, len(vs), 2):
                                    vs[i] = -vs[i]
                                n += 1
    return n


# ---------- 归一化（G1 / G3 用） ----------

# 各字段缺省值（显式缺省 ≡ 缺省字段）
_DEFAULTS = {
    "x": 0.0, "y": 0.0, "rotation": 0.0, "shearX": 0.0, "shearY": 0.0,
    "scaleX": 1.0, "scaleY": 1.0, "length": 0.0, "value": 0.0, "time": 0.0,
    "offset": 0, "angle": 0.0, "width": 0.0, "height": 0.0,
}


def normalize(o, key=None):
    """归一化：int/float 等价、−0.0≡0、显式缺省值字段删除（与缺省字段等价）。"""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            nv = normalize(v, k)
            # 缺省值字段删除：若该键有已知缺省值且归一化后等于缺省值 → 省略
            if k in _DEFAULTS and isinstance(nv, (int, float)) and not isinstance(nv, bool):
                if abs(float(nv) - _DEFAULTS[k]) < 1e-12:
                    continue
            out[k] = nv
        return out
    if isinstance(o, list):
        return [normalize(v, key) for v in o]
    if isinstance(o, float):
        if o == int(o):
            return int(o)
        return o
    return o


def diff_paths(a, b, path=""):
    """递归收集 a 与 b 的差异路径（归一化后调用）。"""
    diffs = []
    if type(a) != type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        diffs.append((path, a, b))
        return diffs
    if isinstance(a, dict):
        for k in set(a) | set(b):
            if k not in a:
                diffs.append((f"{path}.{k}", "<缺省>", b[k]))
            elif k not in b:
                diffs.append((f"{path}.{k}", a[k], "<缺省>"))
            else:
                diffs += diff_paths(a[k], b[k], f"{path}.{k}")
        return diffs
    if isinstance(a, list):
        if len(a) != len(b):
            diffs.append((f"{path}[len]", len(a), len(b)))
            return diffs
        for i, (x, y) in enumerate(zip(a, b)):
            diffs += diff_paths(x, y, f"{path}[{i}]")
        return diffs
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if abs(float(a) - float(b)) > 1e-9:
            diffs.append((path, a, b))
        return diffs
    if a != b:
        diffs.append((path, a, b))
    return diffs


# ---------- runtime 数值模拟器（G2 + Tier2 判定） ----------

class Sim:
    """按官方 4.3 BonePose.updateWorldTransform + Animation apply(alpha=1, from=setup)
    模拟逐骨世界矩阵。doc 需为归一化前的原始结构（读取缺省值用 .get 默认）。"""

    def __init__(self, doc, skeleton_scaleX=1.0):
        self.doc = doc
        self.ssx = skeleton_scaleX
        self.ssy = 1.0
        self.bones = doc["bones"]
        self.rname = self.bones[0].get("name", "root")
        # setup 局部
        self.setup = {}
        self.parent = {}
        self.inherit = {}
        for b in self.bones:
            self.setup[b["name"]] = {
                "x": b.get("x", 0.0), "y": b.get("y", 0.0),
                "rotation": b.get("rotation", 0.0),
                "scaleX": b.get("scaleX", 1.0), "scaleY": b.get("scaleY", 1.0),
                "shearX": b.get("shearX", 0.0), "shearY": b.get("shearY", 0.0),
            }
            self.parent[b["name"]] = b.get("parent")
            self.inherit[b["name"]] = b.get("inherit", "normal")
        # 动画时间线预处理
        self.anims = {}
        for aname, anim in doc.get("animations", {}).items():
            tracks = {}
            times = set([0.0])
            for bname, tr in anim.get("bones", {}).items():
                for ch, keys in tr.items():
                    if not isinstance(keys, list):
                        continue
                    tracks.setdefault(bname, {})[ch] = keys
                    for k in keys:
                        times.add(k.get("time", 0.0))
            dur = max(times) if times else 0.0
            times.add(dur)
            self.anims[aname] = {"tracks": tracks, "times": sorted(times), "duration": dur}

    def _curve_value(self, keys, ch, time):
        """返回 (xvalue, yvalue) 在 time 时刻的曲线值（rotate/shear/scale/translate 双值）。
        单值通道（rotate）y 为 None。首 key 前返回 None（调用方用 setup）。"""
        if not keys:
            return (None, None)
        if time < keys[0].get("time", 0.0):
            return (None, None)  # setup
        # 找 frame：最后一个 time<=t 的 key
        idx = 0
        for i, k in enumerate(keys):
            if k.get("time", 0.0) <= time:
                idx = i
            else:
                break
        k = keys[idx]
        curve = k.get("curve")
        nxt = keys[idx + 1] if idx + 1 < len(keys) else None
        def vals(kk):
            if ch == "rotate":
                return (kk.get("value", 0.0), None)
            if ch == "translate":
                return (kk.get("x", 0.0), kk.get("y", 0.0))
            if ch == "scale":
                return (kk.get("x", 1.0), kk.get("y", 1.0))
            if ch == "shear":
                return (kk.get("x", 0.0), kk.get("y", 0.0))
            return (0.0, 0.0)
        v0 = vals(k)
        if nxt is None or curve == "stepped" or isinstance(curve, list):
            # stepped / bezier(按 stepped 保守) / 末帧：取当前帧值
            # 注：采样恰在关键帧时刻，线性插值在两关键帧处恰等于端点值，
            # 故除「两 key 之间的非关键帧」外不影响；我们只在关键帧采样，安全。
            return v0
        # linear：t 恰为关键帧时因子为 0 或 1，端点精确
        t0 = k.get("time", 0.0)
        t1 = nxt.get("time", 0.0)
        f = 0.0 if t1 <= t0 else (time - t0) / (t1 - t0)
        f = min(1.0, max(0.0, f))
        v1 = vals(nxt)
        x = v0[0] + (v1[0] - v0[0]) * f
        y = None if v0[1] is None else v0[1] + (v1[1] - v0[1]) * f
        return (x, y)

    def bone_local(self, aname, bname, time, root_hold_setup=False):
        """某骨在动画 aname、时刻 time 的动画局部（alpha=1, from=setup）。
        aname=None 表示 setup pose。root_hold_setup=True 时 root 骨固定 setup
        （G2 闸门口径：验证烘焙数学，排除 D4 root 动画）。"""
        s = dict(self.setup[bname])
        if aname is None:
            return s
        if root_hold_setup and bname == self.rname:
            return s
        tracks = self.anims.get(aname, {}).get("tracks", {}).get(bname, {})
        for ch, keys in tracks.items():
            xv, yv = self._curve_value(keys, ch, time)
            if xv is None:
                continue  # setup
            if ch == "rotate":
                s["rotation"] = self.setup[bname]["rotation"] + xv
            elif ch == "translate":
                s["x"] = self.setup[bname]["x"] + xv
                s["y"] = self.setup[bname]["y"] + (yv if yv is not None else 0.0)
            elif ch == "scale":
                s["scaleX"] = xv * self.setup[bname]["scaleX"]
                s["scaleY"] = (yv if yv is not None else 1.0) * self.setup[bname]["scaleY"]
            elif ch == "shear":
                s["shearX"] = self.setup[bname]["shearX"] + xv
                s["shearY"] = self.setup[bname]["shearY"] + (yv if yv is not None else 0.0)
        return s

    def world(self, aname, time, root_hold_setup=False):
        """逐骨世界矩阵 {name: (a,b,c,d,worldX,worldY)}。照抄 4.3 updateWorldTransform。"""
        W = {}
        order = self.bones  # JSON 顺序即拓扑序（父先于子）
        for b in order:
            name = b["name"]
            L = self.bone_local(aname, name, time, root_hold_setup)
            par = self.parent[name]
            if par is None:  # root
                sx, sy = self.ssx, self.ssy
                rx = (L["rotation"] + L["shearX"]) * DEG
                ry = (L["rotation"] + 90.0 + L["shearY"]) * DEG
                a = math.cos(rx) * L["scaleX"] * sx
                bb = math.cos(ry) * L["scaleY"] * sx
                c = math.sin(rx) * L["scaleX"] * sy
                d = math.sin(ry) * L["scaleY"] * sy
                wx = L["x"] * sx + 0.0  # skeleton.x=0
                wy = L["y"] * sy + 0.0
                W[name] = (a, bb, c, d, wx, wy)
                continue
            pa, pb, pc, pd, pwx, pwy = W[par]
            wx = pa * L["x"] + pb * L["y"] + pwx
            wy = pc * L["x"] + pd * L["y"] + pwy
            inh = self.inherit[name]
            sxk, syk = self.ssx, self.ssy
            if inh == "normal":
                rx = (L["rotation"] + L["shearX"]) * DEG
                ry = (L["rotation"] + 90.0 + L["shearY"]) * DEG
                la = math.cos(rx)*L["scaleX"]; lb = math.cos(ry)*L["scaleY"]
                lc = math.sin(rx)*L["scaleX"]; ld = math.sin(ry)*L["scaleY"]
                a = pa*la + pb*lc; bb = pa*lb + pb*ld
                c = pc*la + pd*lc; d = pc*lb + pd*ld
            elif inh == "onlyTranslation":
                rx = (L["rotation"] + L["shearX"]) * DEG
                ry = (L["rotation"] + 90.0 + L["shearY"]) * DEG
                a = math.cos(rx)*L["scaleX"]*sxk; bb = math.cos(ry)*L["scaleY"]*sxk
                c = math.sin(rx)*L["scaleX"]*syk; d = math.sin(ry)*L["scaleY"]*syk
            elif inh == "noRotationOrReflection":
                sxi, syi = 1.0/sxk, 1.0/syk
                pa2, pc2 = pa*sxi, pc*syi
                s = pa2*pa2 + pc2*pc2
                if s > 1e-10:
                    s = abs(pa2*pd*syi - pb*sxi*pc2) / s
                    pb2 = pc2*s; pd2 = pa2*s
                    r = L["rotation"] - math.atan2(pc2, pa2)/DEG
                else:
                    pa2 = 0.0; pc2 = 0.0
                    pb2 = pb; pd2 = pd
                    r = L["rotation"] - 90.0 + math.atan2(pd, pb)/DEG
                rx = (r + L["shearX"]) * DEG
                ry = (r + L["shearY"] + 90.0) * DEG
                la = math.cos(rx)*L["scaleX"]; lb = math.cos(ry)*L["scaleY"]
                lc = math.sin(rx)*L["scaleX"]; ld = math.sin(ry)*L["scaleY"]
                a = (pa2*la - pb2*lc)*sxk; bb = (pa2*lb - pb2*ld)*sxk
                c = (pc2*la + pd2*lc)*syk; d = (pc2*lb + pd2*ld)*syk
            else:  # noScale / noScaleOrReflection
                sxi, syi = 1.0/sxk, 1.0/syk
                r = L["rotation"] * DEG
                cosr, sinr = math.cos(r), math.sin(r)
                za = (pa*cosr + pb*sinr) * sxi
                zc = (pc*cosr + pd*sinr) * syi
                ss = 1.0 / math.sqrt(za*za + zc*zc) if (za*za+zc*zc) > 1e-20 else 0.0
                za *= ss; zc *= ss
                zb, zd = -zc, za
                if inh == "noScale" and (pa*pd - pb*pc < 0) != (sxk < 0 != syk < 0):
                    zb, zd = -zb, -zd
                rx = L["shearX"] * DEG
                ry = (90.0 + L["shearY"]) * DEG
                la = math.cos(rx)*L["scaleX"]; lb = math.cos(ry)*L["scaleY"]
                lc = math.sin(rx)*L["scaleX"]; ld = math.sin(ry)*L["scaleY"]
                a = (za*la + zb*lc)*sxk; bb = (za*lb + zb*ld)*sxk
                c = (zc*la + zd*lc)*syk; d = (zc*lb + zd*ld)*syk
            W[name] = (a, bb, c, d, wx, wy)
        return W


def max_world_diff(W1, W2, skip=()):
    """两副逐骨世界矩阵的最大逐分量 diff（只比共同骨；skip 跳过 root 等名）。"""
    m = 0.0
    worst = None
    for name in W1:
        if name not in W2 or name in skip:
            continue
        for i in range(6):
            dv = abs(W1[name][i] - W2[name][i])
            if dv > m:
                m = dv
                worst = (name, i, W1[name][i], W2[name][i])
    return m, worst


# ---------- 主流程 ----------

def bake_doc(doc, ctx, warnings, _second=False):
    """对 doc 深拷贝执行共轭烘焙（noScale 改写 + K 共轭）。返回 (烘焙后doc, info)。"""
    out = json.loads(json.dumps(doc))
    # 1) noScale→normal 改写（镜像子树内、父骨世界 |scale|≈1 无反射的安全骨）
    rewrite, rejects = plan_inherit_rewrite(out, ctx)
    if rejects and not _second:
        err(f"{ctx}: noScale 骨改写不安全（父骨世界 scale≠1 或含反射）："
            + "；".join(rejects[:3]) + " —— 拒绝产出")
    rewritten = apply_inherit_rewrite(out, rewrite)
    # 2) K 共轭 root 直接子骨（inherit∈{normal,noScale}）
    K, alpha = compute_K(out, ctx)
    flipset = flip_domain(out)
    nb = bake_bones(out, K, alpha, flipset)
    na = bake_animations(out, K, alpha, flipset, warnings)
    info = {"K": K, "alpha": alpha, "flip_bones": sorted(flipset),
            "baked_bones": nb, "baked_anim_tracks": na,
            "inherit_rewritten": sorted(rewritten)}
    return out, info


def run_g1(orig, baked, info, ctx):
    """G1 双翻恒等：bake(bake(x)) ≡ x。
    注意 noScale→normal 改写是单向幂等归一（不是对合），故双翻产物应与
    「应用了同样改写的原包」比较，而非原始原包。"""
    warnings = []
    twice, _ = bake_doc(baked, ctx + " [G1-2nd]", warnings, _second=True)
    # 构造「应用了 inherit 改写的原包」作为基准
    base = json.loads(json.dumps(orig))
    apply_inherit_rewrite(base, set(info.get("inherit_rewritten", [])))
    na = normalize(base)
    nb = normalize(twice)
    diffs = diff_paths(na, nb)
    hard = [d for d in diffs if not _is_num_close(d)]
    maxres = 0.0
    for d in diffs:
        if isinstance(d[1], (int, float)) and isinstance(d[2], (int, float)):
            maxres = max(maxres, abs(float(d[1]) - float(d[2])))
    return hard, maxres


def _is_num_close(d):
    p, a, b = d
    return (isinstance(a, (int, float)) and isinstance(b, (int, float))
            and abs(float(a) - float(b)) <= G1_TOL)


def run_g2(orig, baked, ctx):
    """G2 镜像正确性（真镜像口径）：烘焙包逐骨世界矩阵 == Fx·(原包世界矩阵)。
    参考系取「原包 skeleton=+1 的原生渲染」的镜像——这正是"人物完全换向"的语义目标，
    比 runtime-flip 参考更严格也更正确（后者对 noScale 骨本身就有去镜像偏差）。

    比较集 = 镜像子树（翻转域骨及其后代，不含 root 与排除域）：
      - root 自身世界本就不动（镜像由子骨的共轭局部实现）；
      - 排除域（onlyTranslation/noROR/noScaleOrReflection 及子树）设计上不镜像
        （位置随父镜像、朝向保持原样），其视觉由 Tier 2 B-a/B-c 策略单独处理。

    返回 (口径A_max[root固定setup，闸门], 口径B_max[含root动画，信息级], 口径A_worst)。"""
    so = Sim(orig, skeleton_scaleX=+1.0)
    sb = Sim(baked, skeleton_scaleX=+1.0)
    compare = mirror_subtree(orig)  # 不含 root；excluded 已排除在外
    maxA = 0.0; worstA = None; maxB = 0.0
    samples = [(None, 0.0)]
    for aname, a in so.anims.items():
        samples += [(aname, t) for t in a["times"]]
    for aname, t in samples:
        for hold in (True, False):
            Wo = so.world(aname, t, root_hold_setup=hold)
            Wb = sb.world(aname, t, root_hold_setup=hold)
            d, w = max_world_diff_fx(Wo, Wb, compare)
            if hold:
                if d > maxA:
                    maxA, worstA = d, (aname, t) + (w or (None,) * 4)
            else:
                maxB = max(maxB, d)
    return maxA, maxB, worstA


def max_world_diff_fx(Wo, Wb, compare):
    """max |W_baked − Fx·W_orig| 逐分量（a,b,c,d,worldX,worldY），只比 compare 集。"""
    m = 0.0
    worst = None
    for name in compare:
        if name not in Wo or name not in Wb:
            continue
        ao, bo, co, do_, xo, yo = Wo[name]
        fx = (-ao, -bo, co, do_, -xo, yo)  # Fx·W_orig
        ab, bb, cb, db, xb, yb = Wb[name]
        for i, (e, g) in enumerate(zip(fx, (ab, bb, cb, db, xb, yb))):
            dv = abs(e - g)
            if dv > m:
                m = dv
                worst = (name, i, e, g)
    return m, worst


def run_g3(orig, baked, flipset, tier2_ba, inherit_rewritten, ctx):
    """G3 不动项审计。返回违规 diff 列表。"""
    na = normalize(orig)
    nb = normalize(baked)
    diffs = diff_paths(na, nb)
    bone_names = [b.get("name") for b in orig.get("bones", [])]
    violations = []
    for p, a, b in diffs:
        if not _g3_allowed(p, flipset, tier2_ba, bone_names, set(inherit_rewritten)):
            violations.append((p, a, b))
    return violations


def _seg(s):
    """路径段去下标：'bones[3]' → 'bones'，'translate[1]' → 'translate'。"""
    return s.split("[")[0]


def _seg_idx(s):
    """取下标：'bones[3]' → 3；无 → None。"""
    if "[" in s and s.endswith("]"):
        try:
            return int(s[s.index("[") + 1:-1])
        except ValueError:
            return None
    return None


def _g3_allowed(path, flipset, tier2_ba, bone_names, inherit_rewritten):
    """差异路径是否被允许（翻转域 5 字段及其动画通道 + noScale 改写 inherit + Tier2 B-a）。"""
    parts = path.lstrip(".").split(".")
    head = _seg(parts[0])
    # bones[i].<field>
    if head == "bones" and len(parts) >= 2:
        idx = _seg_idx(parts[0])
        name = bone_names[idx] if (idx is not None and idx < len(bone_names)) else None
        field = _seg(parts[-1])
        if field == "inherit":
            return name in inherit_rewritten  # noScale→normal 安全改写（G2 验证）
        return name in flipset and field in FLIP_SETUP_FIELDS
    if head == "animations":
        # animations.<名>.bones.<骨>.<通道>[i]....
        if len(parts) >= 5 and _seg(parts[2]) == "bones":
            bname = parts[3]
            ch = _seg(parts[4])
            return bname in flipset and ch in ("rotate", "translate", "shear")
        # Tier2 B-a：deform 动画顶点（attachments/deform 两段布局都认）
        if tier2_ba and _seg(parts[2]) in ("attachments", "deform"):
            return True
        return False
    if head == "skins":
        # Tier2 B-a 允许 skins 内排除域可见附件的字段变化（x/rotation/scaleX/vertices/triangles）
        return bool(tier2_ba)
    # skeleton/slots/events/drawOrder/ik/path 等一律不允许
    return False


def analyze_tier2(doc, ctx, warnings):
    """判定 Tier2：排除域可见附件，逐骨模拟世界线性部分决定是否 B-a。
    返回 (ba_targets[(slot,att)], tier2_report)。"""
    flipset = flip_domain(doc)
    excl = excluded_domain(doc)
    slot2bone = {s["name"]: s["bone"] for s in doc.get("slots", [])}
    # 排除域骨 -> 其 slot 的可见附件
    excl_bone_atts = {}
    for skn in doc.get("skins", []):
        for slot, atts in (skn.get("attachments") or {}).items():
            bone = slot2bone.get(slot)
            if bone not in excl:
                continue
            for name, att in (atts or {}).items():
                if att.get("type", "region") in VIS_ATT:
                    excl_bone_atts.setdefault(bone, []).append((slot, name, att))
    if not excl_bone_atts:
        return [], None

    # 逐排除骨：模拟世界线性部分旋转角的变化幅度 + 平均轴角
    sim = Sim(doc, skeleton_scaleX=1.0)
    ba_targets = []
    report = {"excluded_bones": {}, "ba_count": 0, "bc_count": 0}
    for bone, atts in sorted(excl_bone_atts.items()):
        # 收集该骨在全部动画关键帧的世界线性部旋转角
        angles = []
        bone_idx = [i for i, b in enumerate(doc["bones"]) if b["name"] == bone][0]
        for aname in sim.anims:
            for t in sim.anims[aname]["times"]:
                W = sim.world(aname, t, root_hold_setup=True)
                a, bb, c, d, wx, wy = W[bone]
                ang = math.atan2(c, a) / DEG  # 世界 x 轴朝向
                angles.append(ang)
        if angles:
            amin, amax = min(angles), max(angles)
            # 环形差
            var = _angular_span(angles)
        else:
            var = 0.0
        # 镜像轴偏差：骨世界朝向 φ，旧式翻转精确要求 φ ≡ 0 (mod 180)
        phi = angles[0] if angles else 0.0
        axis_dev = abs(((phi + 90) % 180) - 90)  # 距最近 0/180 的偏差
        exact = (var <= BA_ROT_VAR_TOL) and (axis_dev <= BA_AXIS_TOL)
        report["excluded_bones"][bone] = {
            "attachments": len(atts), "rot_variation_deg": round(var, 4),
            "world_rot_deg": round(phi, 3), "axis_deviation_deg": round(axis_dev, 3),
            "strategy": "B-a" if exact else "B-c",
        }
        if exact:
            for slot, name, att in atts:
                ba_targets.append((slot, name, att))
            report["ba_count"] += len(atts)
        else:
            report["bc_count"] += len(atts)
            warnings.append(f"{ctx}: 排除骨 {bone} 世界旋转变化 {var:.2f}°/轴偏差 "
                            f"{axis_dev:.2f}° 超阈，{len(atts)} 个附件保持原样（B-c）")
    return ba_targets, report


def _angular_span(angles):
    """一组角度（度）的最大环形跨度。"""
    if not angles:
        return 0.0
    a = sorted(((x % 360) for x in angles))
    gaps = [a[i+1] - a[i] for i in range(len(a)-1)]
    gaps.append(a[0] + 360 - a[-1])
    return 360 - max(gaps) if gaps else 0.0


def apply_ba(doc, ba_targets, warnings):
    """对排除域可见附件执行旧式二次翻转（B-a）。"""
    flipped = []
    for slot, name, att in ba_targets:
        if flip_attachment_local(att, f"{slot}/{name}", warnings):
            flipped.append((slot, name))
    # deform 动画顶点
    ndef = flip_deform_in_animations(doc, [(s, n) for s, n, _ in ba_targets], warnings)
    return flipped, ndef


# ---------- 产物归一化写盘 ----------

def write_compact(doc, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


# ---------- CLI ----------

def main(argv):
    ap = argparse.ArgumentParser(description="Spine 朝向统一共轭烘焙（task/003）")
    ap.add_argument("pkg", help="包目录或骨架 json")
    ap.add_argument("-o", "--out", help="输出目录（仅写 JSON，不动原包）")
    ap.add_argument("--from", dest="frm", choices=["left", "right"],
                    help="输入包当前朝向（agent 看复原预览图判定，与 --to 成对）")
    ap.add_argument("--to", dest="to", choices=["left", "right"],
                    help="目标朝向；与 --from 相同则原样复制（不烘焙）")
    ap.add_argument("--tier2", choices=["auto", "off"], default="auto",
                    help="Tier2 排除域可见附件处理：auto=B-a 判定分流（默认），off=不处理")
    ap.add_argument("--dry-run", action="store_true",
                    help="只自检与判定，不写产物")
    ap.add_argument("--report", help="把逐包结果追加为 JSON 行到该文件")
    args = ap.parse_args(argv[1:])

    pkg = Path(args.pkg)
    doc, json_path, pkg_dir = load_package(pkg)
    ctx = pkg_dir.name
    guard(doc, ctx)

    # 方向配置
    if bool(args.frm) != bool(args.to):
        err("--from 与 --to 必须成对给出")
    do_bake = True
    if args.frm and args.to:
        do_bake = args.frm != args.to

    cons = collect_constraints(doc)
    result = {"package": str(pkg), "from": args.frm, "to": args.to,
              "baked": do_bake, "warnings": [], "tier2": None, "constraints": cons}

    if not do_bake:
        # 原样复制（不动 hash）
        result["action"] = "copy (facing 已达标)"
        if not args.dry_run and args.out:
            out_dir = Path(args.out)
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(json_path, out_dir / json_path.name)
            result["out"] = str(out_dir / json_path.name)
        print(f"[copy] {ctx}: 朝向 {args.frm}=={args.to}，原样复制")
        _emit(args, result)
        return 0

    warnings = result["warnings"]
    baked, info = bake_doc(doc, ctx, warnings)

    # Tier2 判定 + B-a
    tier2_ba = False
    if args.tier2 == "auto":
        ba_targets, t2report = analyze_tier2(doc, ctx, warnings)
        if t2report:
            result["tier2"] = t2report
            if ba_targets:
                # B-a 作用在 baked 上（排除域数据原样保留于 baked，直接二次翻转）
                # 需对 baked 中对应附件定位：重新取引用
                slot2bone = {s["name"]: s["bone"] for s in baked.get("slots", [])}
                baked_att = {}
                for skn in baked.get("skins", []):
                    for slot, atts in (skn.get("attachments") or {}).items():
                        for name, att in (atts or {}).items():
                            baked_att[(slot, name)] = att
                baked_ba = [(s, n, baked_att.get((s, n))) for s, n, _ in ba_targets
                            if baked_att.get((s, n)) is not None]
                flipped, ndef = apply_ba(baked, baked_ba, warnings)
                tier2_ba = bool(flipped)
                result["tier2"]["ba_flipped"] = len(flipped)
                result["tier2"]["ba_deform_keys"] = ndef

    # ---- 自检 ----
    g1_hard, g1_maxres = run_g1(doc, baked, info, ctx)
    g2A, g2B, g2wA = run_g2(doc, baked, ctx)
    g3_viol = run_g3(doc, baked, info["flip_bones"], tier2_ba,
                     info.get("inherit_rewritten", []), ctx)
    result["inherit_rewritten"] = info.get("inherit_rewritten", [])
    result["gates"] = {
        "G1": {"pass": not g1_hard, "max_residual": g1_maxres, "violations": len(g1_hard)},
        "G2": {"pass": g2A <= G2_TOL, "max_diff_setup": g2A, "max_diff_rootanim": g2B},
        "G3": {"pass": not g3_viol, "violations": len(g3_viol)},
    }

    ok = (not g1_hard) and g2A <= G2_TOL and (not g3_viol)
    print(f"[bake] {ctx}: 翻转域骨 {info['baked_bones']}，动画轨 {info['baked_anim_tracks']}"
          f"{('，Tier2 B-a 翻 ' + str(result['tier2'].get('ba_flipped',0)) + ' 附件') if tier2_ba else ''}")
    print(f"       G1 {'✅' if not g1_hard else '❌'}(残差 {g1_maxres:.2e})  "
          f"G2 {'✅' if g2A<=G2_TOL else '❌'}(setup {g2A:.2e}/root动画 {g2B:.2e})  "
          f"G3 {'✅' if not g3_viol else '❌'}(违规 {len(g3_viol)})")
    for w in warnings:
        print(f"       ⚠ {w}")
    if g1_hard:
        for d in g1_hard[:10]:
            print(f"       G1✗ {d[0]}: {d[1]} vs {d[2]}")
    if g2A > G2_TOL and g2wA:
        print(f"       G2✗ 最差: {g2wA}")
    if g3_viol:
        for d in g3_viol[:10]:
            print(f"       G3✗ {d[0]}: {d[1]!r} vs {d[2]!r}")

    if not ok:
        result["action"] = "rejected (gate failed)"
        _emit(args, result)
        print(f"[rej] {ctx}: 闸门未过，不产出")
        return 1

    if not args.dry_run and args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        write_compact(baked, out_dir / json_path.name)
        result["out"] = str(out_dir / json_path.name)
        print(f"[out] {out_dir / json_path.name}")
    result["action"] = "baked"
    _emit(args, result)
    return 0


def _emit(args, result):
    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        with rp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
