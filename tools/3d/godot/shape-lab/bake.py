# -*- coding: utf-8 -*-
"""shape-lab 资产烘焙器 · 驱动（**纯 python3，不 import bpy**）。

把 6 份 rig 资产（4 套服装 + 2 具标准体）导成 Godot 4 可运行时零拷贝加载的 `.glb`，
并生成索引 `manifest.json` 与自检报告 `reports/bake-report.json`。

一条命令跑完（工作区根下执行）：

    python tools/3d/godot/shape-lab/bake.py

可选参数：

    --force               忽略增量缓存，全部重烘
    --only A,B            只强制重烘指定角色（其余照常走增量）
    --cache DIR           缓存根（默认 tmp/shape-lab；等价环境变量 ARTSTUDIO_SHAPELAB_CACHE）
    --blender PATH        Blender 可执行文件（默认 C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe）
    --timeout SEC         单角色 Blender 超时（默认 600）

缓存布局（契约 v1，见 task-1）：

    tmp/shape-lab/glb/<id>.glb      每角色一个，贴图内嵌、无相机/灯、导出前 shape key 清零
    tmp/shape-lab/manifest.json     索引
    tmp/shape-lab/logs/<id>.log      该角色 Blender 调用的原样 stdout/stderr
    tmp/shape-lab/reports/bake-report.json      自检报告（非契约硬性要求，DoD 要求）
    tmp/shape-lab/reports/roles/<id>.json      该角色的原始证据（Blender 打印的 EXPORT_JSON 全文：
                                                逐件顶点/面/材质/shape key、剔除对象、量测高度）——
                                                热缓存跳过时从这里补证据，保证报告不因命中缓存而丢数据

增量判断（契约 v1）：目标 glb 比源 .blend 新 **且** 源 sha256 与上次 manifest 记录一致 → 跳过。
（额外的安全条件：导出器脚本自身 mtime 比 glb 新时也重烘，避免改了导出配方却命中旧缓存；
 这是**更严格**的跳过条件，不会让热缓存失效。）

自检（真跑真出数，任一不绿则进程 exit 1，报告写进 reports/bake-report.json）：

    a. 纯标准库解析每个 glb 容器：1 个 skin / joints=65、有 morph 的件每个 primitive 都有
       targets 且 extras.targetNames 顺序 == ["BS_Thin","BS_Heavy"]、默认 morph 权重全 0；
       —— 契约里 parts[].has_morph 字段本身允许"无 morph 件"存在（标准体的 Eyebrows/Eyes
          没有 shape key），因此该断言按 has_morph 分档：有 morph 的件必须有 targets，
          无 morph 的件必须**没有** targets。
    b. 4 套服装逐件 verts/faces/materials 与 assets/3d/rig/manifests/garment_manifest.json 交叉核对
    c. characters == 6、id 唯一、glb 存在且 glb_bytes 与实际文件大小一致
    d. 每角色耗时与 glb 字节数记录在案

角色分类规则（契约 **v1.1**，优先级从上到下、命中即止；v1.1 只加宽匹配条件，优先级不变）：
    1 head      名称以 "Head_" 开头，或匹配 ^(Eyebrows|Eyes)$
                ，或以 "_Eyebrows"/"_Eyes" 结尾，或以 "Hair_" 开头
    2 skin      任一材质名含 "MI_Regular_"，或名称以 "Body_" 开头
    3 foot      名称以 "_Feet" 结尾，或名称含 "Boots"
    4 accessory 名称含 "Acc_" / "_Belt" / "_Bracer" / "_Hood"
    5 cloth     其余

    v1 → v1.1 共 4 类放宽：`*_Feet_Boots`→foot、裸模 `Body_*`→skin、
    裸模 `Eyebrows`/`Eyes`→head、`Hair_*`→head（9 件变化；总账 46 件
    = accessory 10 / skin 5 / foot 4 / head 18 / cloth 9，已由
    tmp/shape-lab/review_role_v11.py 独立复算并与 lead 期望逐项一致）。
    role 只影响 manifest 组装、**不触发重烘** —— 热缓存复用时会按新规则**重算** role。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]               # D:\artstudio
TOOLS_DIR = HERE / "tools"
EXPORTER = TOOLS_DIR / "export_role.py"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
from glb_probe import parse_glb, container_facts, target_proxy_disp  # noqa: E402

SCHEMA = "shape-lab-cache"
SCHEMA_VERSION = 1
ROLE_RULES = "v1.1"
MORPH_CONTRACT = ["BS_Thin", "BS_Heavy"]
K_RANGE = [-1.0, 1.0]
H_RANGE = [0.92, 1.08]
BONES_EXPECTED = 65
GARMENT_MANIFEST = "assets/3d/rig/manifests/garment_manifest.json"
BODYSHAPE_MANIFEST = "assets/3d/rig/manifests/bodyshape_manifest.json"
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
_HEAD_EXACT = re.compile(r"^(Eyebrows|Eyes)$")

# 6 个角色（契约 v1）。id 用文件主干，保证唯一且与 glb 文件名一致。
CHARACTERS = [
    {"id": "Female_Ranger", "label": "女 · Ranger 游侠（全套）", "kind": "garment",
     "sex": "Female", "style": "Ranger", "src": "assets/3d/rig/garments/Female_Ranger.blend"},
    {"id": "Male_Ranger", "label": "男 · Ranger 游侠（全套）", "kind": "garment",
     "sex": "Male", "style": "Ranger", "src": "assets/3d/rig/garments/Male_Ranger.blend"},
    {"id": "Female_Peasant", "label": "女 · Peasant 平民（全套）", "kind": "garment",
     "sex": "Female", "style": "Peasant", "src": "assets/3d/rig/garments/Female_Peasant.blend"},
    {"id": "Male_Peasant", "label": "男 · Peasant 平民（全套）", "kind": "garment",
     "sex": "Male", "style": "Peasant", "src": "assets/3d/rig/garments/Male_Peasant.blend"},
    {"id": "Body_Female_Standard", "label": "裸模 · 身形基准（女）", "kind": "body",
     "sex": "Female", "style": "Standard", "src": "assets/3d/rig/bodies/Body_Female_Standard.blend"},
    {"id": "Body_Male_Standard", "label": "裸模 · 身形基准（男）", "kind": "body",
     "sex": "Male", "style": "Standard", "src": "assets/3d/rig/bodies/Body_Male_Standard.blend"},
]
BY_ID = {c["id"]: c for c in CHARACTERS}


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    p = Path(path)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, doc, indent=1):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=indent)
        f.write("\n")


def repo_rel(p):
    """仓库根下的相对 POSIX 路径；不在仓库内则给绝对 POSIX 路径。"""
    rp = Path(p).resolve()
    try:
        return rp.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return rp.as_posix()


def classify_role(name, materials):
    """契约 v1.1 的 role 规则（优先级从上到下、命中即止；v1.1 只加宽条件）。"""
    if (name.startswith("Head_") or _HEAD_EXACT.match(name)
            or name.endswith("_Eyebrows") or name.endswith("_Eyes")
            or name.startswith("Hair_")):
        return "head"
    for m in materials:
        if m and "MI_Regular_" in m:
            return "skin"
    if name.startswith("Body_"):
        return "skin"
    if name.endswith("_Feet") or "Boots" in name:
        return "foot"
    for token in ("Acc_", "_Belt", "_Bracer", "_Hood"):
        if token in name:
            return "accessory"
    return "cloth"


# --------------------------------------------------------------------------- #
# 权威高度来源（manifest 的 base_height_m）
# --------------------------------------------------------------------------- #
def height_sources():
    """id → (base_height_m, 来源字符串)。服装取 garment_manifest 的 base_height_cm/100，
    裸模取 bodyshape_manifest 的 basis_height_m（按文件路径匹配，不靠猜 id）。"""
    out = {}
    gm = load_json(REPO_ROOT / GARMENT_MANIFEST)
    if gm:
        for o in gm.get("outfits", []):
            ratio = (o.get("B2a_height_ratio") or {}).get("base_height_cm")
            if ratio is None:
                continue
            f = o.get("file")
            if not f:
                continue
            out[Path(f).as_posix()] = (
                round(float(ratio) / 100.0, 6),
                "%s#outfits[%s].B2a_height_ratio.base_height_cm=%s" % (
                    GARMENT_MANIFEST, o.get("outfit"), ratio))
    bm = load_json(REPO_ROOT / BODYSHAPE_MANIFEST)
    if bm:
        for b in bm.get("bodies", []):
            h = b.get("basis_height_m")
            f = b.get("file")
            if h is None or not f:
                continue
            out[Path(f).as_posix()] = (
                round(float(h), 6),
                "%s#bodies[%s].basis_height_m=%s" % (BODYSHAPE_MANIFEST, b.get("sex"), h))
    return out


# --------------------------------------------------------------------------- #
# Blender 调用
# --------------------------------------------------------------------------- #
def run_blender(blender, src, dst, log_path, timeout):
    cmd = [blender, "--background", "--factory-startup", "--python-exit-code", "1",
           "--python", str(EXPORTER), "--", "--src", str(src), "--dst", str(dst)]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                              timeout=timeout, env=os.environ.copy())
        rc, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        rc, stdout, stderr, timed_out = -1, exc.stdout or b"", exc.stderr or b"", True
    sec = time.time() - t0

    text = (stdout + b"\n----- STDERR -----\n" + stderr).decode("utf-8", errors="replace")
    header = ("# cmd: %s\n# exit: %s%s\n# seconds: %.3f\n" %
              (" ".join(cmd), rc, " (TIMEOUT)" if timed_out else "", sec))
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + text)

    rep = None
    for line in text.splitlines():
        if line.startswith("EXPORT_JSON "):
            rep = json.loads(line[len("EXPORT_JSON "):])
    if timed_out:
        return None, sec, "Blender 超时（%ss），见 %s" % (timeout, repo_rel(log_path))
    if rc != 0:
        return None, sec, "Blender 退出码 %s，见 %s" % (rc, repo_rel(log_path))
    if rep is None:
        return None, sec, "日志里没有 EXPORT_JSON 行，见 %s" % repo_rel(log_path)
    if not Path(dst).exists():
        return None, sec, "Blender 退出码 0 但没有产出 %s" % dst
    return rep, sec, None


# --------------------------------------------------------------------------- #
# manifest 条目
# --------------------------------------------------------------------------- #
def build_entry(role, src, src_sha, glb_path, glb_bytes, rep, base_height, height_src):
    parts = []
    for name in sorted(rep["meshes"].keys()):
        m = rep["meshes"][name]
        has_morph = all(k in m["shape_keys"] for k in MORPH_CONTRACT)
        parts.append({
            "name": name,
            "role": classify_role(name, m["materials"]),
            "has_morph": has_morph,
            "morph_names": [k for k in MORPH_CONTRACT if k in m["shape_keys"]],
            "verts": m["verts"],
            "faces": m["faces"],
            "materials": m["materials"],
        })
    arm = rep["armatures"][0] if rep["armatures"] else {}
    kind = role["kind"]
    return {
        "id": role["id"],
        "label": role["label"],
        "kind": kind,
        "sex": role["sex"],
        "style": role["style"],
        "src_blend": repo_rel(src),
        "src_sha256": src_sha,
        "glb": repo_rel(glb_path),
        "glb_bytes": glb_bytes,
        "armature": arm.get("name"),
        "bones": arm.get("bones"),
        "base_height_m": base_height,
        "parts": parts,
        # —— 以下为报告用附加信息，不进 manifest
        "_height_source": height_src,
    }


def evidence_private(rep_like):
    """从"Blender 原始 rep"或"证据文件"里抽出报告的私有字段（两条路径共用，热缓存也不丢数据）。"""
    meshes = rep_like.get("meshes") or {}
    arms = rep_like.get("armatures") or []
    return {
        "_verts_referenced": {n: m.get("verts_referenced") for n, m in meshes.items()},
        "_loose_geometry": {n: {"verts_loose": m.get("verts_loose"), "loose_edges": m.get("loose_edges")}
                            for n, m in meshes.items()
                            if (m.get("verts_loose") or 0) or (m.get("loose_edges") or 0)},
        "_measured_mesh_z_range_m": rep_like.get("mesh_z_range_all"),
        "_measured_armature_z_range_m": (rep_like.get("armature_z_range")
                                        or (arms[0].get("z_range") if arms else None)),
        "_removed": rep_like.get("removed", []),
        "_blender_version": rep_like.get("blender_version") or rep_like.get("blender_version_string"),
    }


def strip_private(entry):
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def evidence_from_rep(rep):
    """把 Blender 侧原始事实存成证据文件（热缓存复用时也读它，保证报告数据不因跳过而丢失）。"""
    arm = rep["armatures"][0] if rep.get("armatures") else {}
    return {
        "schema": "shape-lab-role-evidence",
        "version": 1,
        "src": rep.get("src"),
        "dst": rep.get("dst"),
        "blender_version": rep.get("blender_version_string"),
        "blender_version_cycle": rep.get("blender_version_cycle"),
        "export_kw_applied": rep.get("export_kw_applied"),
        "export_kw_missing": rep.get("export_kw_missing"),
        "zeroed_shape_key_objects": rep.get("zeroed_shape_key_objects"),
        "removed": rep.get("removed", []),
        "meshes": rep.get("meshes", {}),
        "mesh_z_all": rep.get("mesh_z_all"),
        "mesh_z_range_all": rep.get("mesh_z_range_all"),
        "armatures": rep.get("armatures", []),
        "armature_z_range": arm.get("z_range"),
        "images": rep.get("images", []),
    }


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def morph_proxies(mesh):
    """每个 morph 通道的位移逐轴下界（米），跨 primitive 取最大。"""
    out = []
    for ti in range(len(MORPH_CONTRACT)):
        vals = [target_proxy_disp(p, ti) for p in mesh["primitives"] if p["targets"] > ti]
        vals = [v for v in vals if v is not None]
        out.append(max(vals) if vals else None)
    return out


def check_a_container(entries):
    """a. GLB 容器：skin/joints/targets/targetNames/默认权重。"""
    per = {}
    ok_all = True
    for e in entries:
        cid = e["id"]
        glb = REPO_ROOT / e["glb"] if not Path(e["glb"]).is_absolute() else Path(e["glb"])
        item = {"glb": e["glb"], "problems": [], "facts": {}}
        try:
            facts = container_facts(parse_glb(glb))
        except Exception as exc:  # noqa: BLE001
            item["problems"].append("解析失败：%s" % exc)
            item["ok"] = False
            ok_all = False
            per[cid] = item
            continue

        expected_parts = {p["name"]: p for p in e["parts"]}
        # 按 **节点名** 索引（node.name = Blender 物体名 = manifest parts[].name）；
        # glTF mesh 名是 Blender 的 mesh data 名，可能是 `Plane.002` 之类，不能当键用。
        node_to_meshidx = {pair["node"]: pair["mesh_index"] for pair in facts["node_mesh_pairs"]}
        skins = facts["skins"]
        if len(skins) != 1:
            item["problems"].append("skin 数 = %d（要求 1）" % len(skins))
        elif skins[0]["joints"] != BONES_EXPECTED:
            item["problems"].append("skin joints = %d（要求 %d）" % (skins[0]["joints"], BONES_EXPECTED))

        missing_nodes = sorted(set(expected_parts) - set(facts["node_names"]))
        if missing_nodes:
            item["problems"].append("manifest parts 在 glb 节点里找不到：%s" % missing_nodes)

        morph_checked = 0
        positions_by_mesh = {}
        morph_proxy_m_by_mesh = {}
        for name, part in sorted(expected_parts.items()):
            midx = node_to_meshidx.get(name)
            mesh = facts["meshes"][midx] if midx is not None else None
            if mesh is None:
                item["problems"].append("%s：glb 里没有对应节点/网格" % name)
                continue
            positions_by_mesh[name] = mesh["position_count"]
            ref = (e.get("_verts_referenced") or {}).get(name)
            if ref is not None and mesh["position_count"] < ref:
                item["problems"].append(
                    "%s：glb POSITION 数 %d < Blender 被面引用顶点数 %d（真丢顶点）" % (
                        name, mesh["position_count"], ref))
            if part["has_morph"]:
                problems_before = len(item["problems"])
                if mesh["morph_prim_count"] != mesh["prim_count"]:
                    item["problems"].append(
                        "%s：%d/%d 个 primitive 有 targets（要求全部）" % (
                            name, mesh["morph_prim_count"], mesh["prim_count"]))
                for i, prim in enumerate(mesh["primitives"]):
                    if prim["targets"] != len(MORPH_CONTRACT):
                        item["problems"].append(
                            "%s prim%d：targets=%s（要求 %d）" % (name, i, prim["targets"], len(MORPH_CONTRACT)))
                if mesh["resolved_target_names"] != MORPH_CONTRACT:
                    item["problems"].append(
                        "%s：morph 名 = %s（来源 %s；要求 %s，顺序也要对）" % (
                            name, mesh["resolved_target_names"], mesh["target_names_source"],
                            MORPH_CONTRACT))
                proxies = morph_proxies(mesh)
                morph_proxy_m_by_mesh[name] = proxies
                if any(v is None for v in proxies):
                    item["problems"].append(
                        "%s：morph target 的 POSITION accessor 缺 min/max，无法证明非空" % name)
                if len(item["problems"]) == problems_before:
                    morph_checked += 1
                if mesh["weights"] and any(abs(v) > 0.0 for v in mesh["weights"]):
                    item["problems"].append("%s：默认 mesh.weights=%s（要求全 0）" % (name, mesh["weights"]))
            else:
                if mesh["morph_prim_count"] != 0 or any(p["targets"] for p in mesh["primitives"]):
                    item["problems"].append("%s：manifest has_morph=false 但 glb 带 targets" % name)

        nonzero_nodes = [nw for nw in facts["node_weights"]
                         if isinstance(nw.get("weights"), list) and any(abs(v) > 0.0 for v in nw["weights"])]
        if nonzero_nodes:
            item["problems"].append("node.weights 非 0：%s" % nonzero_nodes)

        item["facts"] = {
            "file_size": facts["file_size"],
            "counts": facts["counts"],
            "skins": skins,
            "parts_with_morph_checked": morph_checked,
            "parts_without_morph": sorted(n for n, p in expected_parts.items() if not p["has_morph"]),
            "morph_proxy_m_by_mesh": morph_proxy_m_by_mesh,
            "morph_proxy_rule": ("target_proxy_disp = max_axis max(|min|,|max|)（位移 accessor 的逐轴下界，"
                                 "≤ 真实最大位移模长）"),
            "mesh_weights": {m["name"]: m["weights"] for m in facts["meshes"]},
            "node_weights": facts["node_weights"],
            "target_names_by_mesh": {m["name"]: m["resolved_target_names"] for m in facts["meshes"]},
            "target_names_source": {m["name"]: m["target_names_source"] for m in facts["meshes"]},
            "positions_by_mesh": positions_by_mesh,
            "verts_by_mesh_manifest": {n: p["verts"] for n, p in expected_parts.items()},
            "verts_referenced_by_mesh": dict(e.get("_verts_referenced") or {}),
            "glb_positions_total": sum(positions_by_mesh.values()),
            "manifest_verts_total": sum(p["verts"] for p in expected_parts.values()),
            "loose_geometry": dict(e.get("_loose_geometry") or {}),
            "triangles_total": sum(m["triangles"] or 0 for m in facts["meshes"]),
            "missing_nodes": missing_nodes,
            "morph_prim_total": sum(m["morph_prim_count"] for m in facts["meshes"]),
            "position_count_total": sum(m["position_count"] for m in facts["meshes"]),
            "images": facts["images"],
            "image_bytes_total": sum(i["bufferView_bytes"] or 0 for i in facts["images"]),
            "materials": facts["materials"],
            "node_names": facts["node_names"],
            "mesh_names": facts["mesh_names"],
            "extensions_used": facts["extensions_used"],
            "asset": facts["asset"],
        }
        item["ok"] = not item["problems"]
        ok_all = ok_all and item["ok"]
        per[cid] = item
    return {"ok": ok_all, "per_character": per,
            "rule_reading": ("契约 parts[].has_morph 允许无 morph 件 → 有 morph 件必须每个 primitive "
                             "都有 2 个 targets 且 morph 名顺序为 ['BS_Thin','BS_Heavy']"
                             "（实测 Blender 5.2 把名字写在 **mesh 层 extras.targetNames**，"
                             "primitive 层没有；两种位置都接受，来源记在 target_names_source）；"
                             "无 morph 件必须没有 targets；mesh/node 默认权重必须全 0")}


def check_b_garment_manifest(entries):
    """b. 4 套服装逐件与 garment_manifest.json 交叉核对。"""
    gm = load_json(REPO_ROOT / GARMENT_MANIFEST)
    per = {}
    ok_all = gm is not None
    if gm is None:
        return {"ok": False, "error": "%s 读不到" % GARMENT_MANIFEST, "per_outfit": {}}
    outfits = {o.get("outfit"): o for o in gm.get("outfits", [])}
    for e in entries:
        if e["kind"] != "garment":
            continue
        o = outfits.get(e["id"])
        item = {"problems": [], "parts_compared": 0}
        if o is None:
            item["problems"].append("garment_manifest 里没有 outfit=%s" % e["id"])
            item["ok"] = False
            ok_all = False
            per[e["id"]] = item
            continue
        if o.get("parts_count") != len(e["parts"]):
            item["problems"].append("parts_count: manifest=%s vs garment_manifest=%s" % (
                len(e["parts"]), o.get("parts_count")))
        if o.get("armature") != e["armature"]:
            item["problems"].append("armature: %s vs %s" % (e["armature"], o.get("armature")))
        if o.get("bones") != e["bones"]:
            item["problems"].append("bones: %s vs %s" % (e["bones"], o.get("bones")))
        gparts = {p["part"]: p for p in o.get("parts", [])}
        if set(gparts) != {p["name"] for p in e["parts"]}:
            item["problems"].append("part 名单不一致：only_in_ours=%s only_in_garment_manifest=%s" % (
                sorted({p["name"] for p in e["parts"]} - set(gparts)),
                sorted(set(gparts) - {p["name"] for p in e["parts"]})))
        for p in e["parts"]:
            gp = gparts.get(p["name"])
            if gp is None:
                continue
            item["parts_compared"] += 1
            if gp.get("verts") != p["verts"]:
                item["problems"].append("%s verts: %s vs %s" % (p["name"], p["verts"], gp.get("verts")))
            if gp.get("faces") != p["faces"]:
                item["problems"].append("%s faces: %s vs %s" % (p["name"], p["faces"], gp.get("faces")))
            if sorted(gp.get("materials", [])) != sorted(p["materials"]):
                item["problems"].append("%s materials: %s vs %s" % (
                    p["name"], p["materials"], gp.get("materials")))
            gsk = [k for k in gp.get("shape_keys", []) if k != "Basis"]
            if gsk != p["morph_names"]:
                item["problems"].append("%s shape_keys: %s vs %s" % (p["name"], p["morph_names"], gsk))
        item["ok"] = not item["problems"]
        ok_all = ok_all and item["ok"]
        per[e["id"]] = item
    return {"ok": ok_all, "source": GARMENT_MANIFEST, "per_outfit": per}


def check_c_inventory(entries):
    """c. 角色数 / id 唯一 / glb 存在且字节数一致 / 源 .blend 未被改动。"""
    ids = [e["id"] for e in entries]
    problems = []
    if len(entries) != len(CHARACTERS):
        problems.append("characters 数 = %d（要求 %d）" % (len(entries), len(CHARACTERS)))
    if len(set(ids)) != len(ids):
        problems.append("id 重复：%s" % ids)
    if set(ids) != set(BY_ID):
        problems.append("id 集合与契约不符：%s" % sorted(ids))
    # 上游记录了 blend_sha256 的资产（裸模）：对账能证明"源 .blend 只读、没被写过"
    bm = load_json(REPO_ROOT / BODYSHAPE_MANIFEST) or {}
    upstream_sha = {b.get("file"): b.get("blend_sha256") for b in bm.get("bodies", [])
                    if b.get("blend_sha256")}
    per = {}
    for e in entries:
        glb = REPO_ROOT / e["glb"] if not Path(e["glb"]).is_absolute() else Path(e["glb"])
        up = upstream_sha.get(e["src_blend"])
        item = {"exists": glb.exists(), "glb_bytes": e["glb_bytes"],
                "actual_bytes": glb.stat().st_size if glb.exists() else None,
                "parts": len(e["parts"]),
                "src_sha256_matches_upstream": (None if up is None else up == e["src_sha256"]),
                "upstream_sha256": up}
        item["ok"] = (item["exists"] and item["glb_bytes"] == item["actual_bytes"]
                      and e["glb_bytes"] > 0 and len(e["parts"]) > 0
                      and item["src_sha256_matches_upstream"] is not False)
        if not item["ok"]:
            problems.append("%s：exists=%s bytes %s vs %s parts=%s src_sha_match=%s" % (
                e["id"], item["exists"], item["glb_bytes"], item["actual_bytes"], len(e["parts"]),
                item["src_sha256_matches_upstream"]))
        per[e["id"]] = item
    return {"ok": not problems, "characters": len(entries), "ids": ids,
            "ids_unique": len(set(ids)) == len(ids), "per_character": per,
            "src_sha256_upstream_source": (BODYSHAPE_MANIFEST + "#bodies[].blend_sha256"
                                           if upstream_sha else None),
            "problems": problems}


def check_d_timing(entries, timings):
    """d. 每角色耗时与字节数在案。"""
    per = {}
    problems = []
    for e in entries:
        t = timings.get(e["id"], {})
        item = {"sec": t.get("sec"), "skipped": t.get("skipped"), "glb_bytes": e["glb_bytes"]}
        item["ok"] = (item["sec"] is not None and item["glb_bytes"] > 0)
        if not item["ok"]:
            problems.append("%s：sec=%s bytes=%s" % (e["id"], item["sec"], item["glb_bytes"]))
        per[e["id"]] = item
    cold = round(sum(t["sec"] for t in timings.values() if not t.get("skipped")), 3)
    warm = round(sum(t["sec"] for t in timings.values() if t.get("skipped")), 3)
    return {"ok": not problems, "per_character": per, "cold_sec": cold, "warm_sec": warm,
            "problems": problems}


def check_e_morph_displacement(entries, a_result):
    """e. 导出后的 morph 位移与上游 manifest 对账（证明 target 不是空的、也没有凭空多出来）。

    对账量：glb 里 morph target POSITION accessor 的逐轴下界 proxy（米）
      · proxy 必须 ≤ 上游实测的最大位移（数学上必然成立，越界=打包/坐标出了错）
      · 上游说该件该档有位移（max_disp > 0）→ proxy 必须 > 0（否则是"空 morph 全绿"的假 PASS）
      · 上游说该件是 static_by_design（max_disp = 0）→ proxy 必须 ≈ 0
    上游来源：garment_manifest 的 M4b_morph_non_trivial（服装，逐件逐档 cm）；
             bodyshape_manifest 的 bodies[].tiers[]（裸模，整具 m）。
    """
    gm = load_json(REPO_ROOT / GARMENT_MANIFEST) or {}
    bm = load_json(REPO_ROOT / BODYSHAPE_MANIFEST) or {}
    g_outfits = {o.get("outfit"): o for o in gm.get("outfits", [])}
    b_bodies = {b.get("sex"): b for b in bm.get("bodies", [])}
    per = {}
    ok_all = True

    for e in entries:
        facts = (a_result["per_character"].get(e["id"], {}) or {}).get("facts") or {}
        proxy_by_mesh = facts.get("morph_proxy_m_by_mesh") or {}
        expected = {}
        source = None
        if e["kind"] == "garment":
            o = g_outfits.get(e["id"]) or {}
            m4b = (o.get("M4b_morph_non_trivial") or {}).get("tiers") or {}
            for tier in MORPH_CONTRACT:
                for pname, item in ((m4b.get(tier) or {}).get("per_part") or {}).items():
                    cm = item.get("max_disp_cm")
                    if cm is not None:
                        expected.setdefault(pname, {})[tier] = cm / 100.0
            source = "%s#outfits[%s].M4b_morph_non_trivial.tiers[*].per_part[*].max_disp_cm" % (
                GARMENT_MANIFEST, e["id"])
        else:
            b = b_bodies.get(e["sex"]) or {}
            for tier in b.get("tiers", []):
                if tier.get("shape_key") in MORPH_CONTRACT:
                    expected.setdefault("__body__", {})[tier["shape_key"]] = tier.get("max_displacement_m")
            source = "%s#bodies[%s].tiers[*].max_displacement_m" % (BODYSHAPE_MANIFEST, e["sex"])

        item = {"source": source, "problems": [], "per_part": {}, "expected_available": bool(expected)}
        for name, part in sorted({p["name"]: p for p in e["parts"]}.items()):
            if not part["has_morph"]:
                continue
            proxies = proxy_by_mesh.get(name)
            if not proxies:
                continue
            key = name if name in expected else ("__body__" if "__body__" in expected else None)
            row = {}
            for ti, tier in enumerate(MORPH_CONTRACT):
                px = proxies[ti]
                exp = (expected.get(key) or {}).get(tier) if key else None
                row[tier] = {"glb_proxy_m": px, "upstream_max_disp_m": exp}
                if px is None or exp is None:
                    continue
                if px > exp + 1e-6:
                    item["problems"].append(
                        "%s/%s：proxy %.6f m > 上游最大位移 %.6f m（不可能，打包出错）" % (name, tier, px, exp))
                elif exp > 0.0 and px <= 1e-9:
                    item["problems"].append(
                        "%s/%s：上游实测有位移 %.6f m，但 glb 的 morph 是空的" % (name, tier, exp))
                elif exp == 0.0 and px > 1e-6:
                    item["problems"].append(
                        "%s/%s：上游记 static_by_design（0），但 glb 有位移 %.6f m" % (name, tier, px))
            item["per_part"][name] = row
        item["ok"] = not item["problems"]
        ok_all = ok_all and item["ok"]
        per[e["id"]] = item

    return {"ok": ok_all, "per_character": per,
            "rule": ("proxy ≤ 上游 max_disp；上游 >0 ⇒ proxy >0；上游 =0 ⇒ proxy ≈0。"
                     "proxy = morph 位移 accessor 的逐轴下界")}


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="shape-lab .blend→.glb 烘焙器（契约 v1）")
    ap.add_argument("--force", action="store_true", help="忽略增量缓存，全部重烘")
    ap.add_argument("--only", default="", help="逗号分隔的 id：只强制重烘这些（其余照常增量）")
    ap.add_argument("--cache", default="", help="缓存根（默认 tmp/shape-lab）")
    ap.add_argument("--blender", default="", help="Blender 可执行文件路径")
    ap.add_argument("--timeout", type=float, default=600.0, help="单角色超时（秒）")
    args = ap.parse_args()

    cache_root = (args.cache or os.environ.get("ARTSTUDIO_SHAPELAB_CACHE") or "tmp/shape-lab")
    cache = Path(cache_root)
    if not cache.is_absolute():
        cache = REPO_ROOT / cache
    cache = cache.resolve()
    glb_dir = cache / "glb"
    log_dir = cache / "logs"
    report_dir = cache / "reports"
    manifest_path = cache / "manifest.json"
    report_path = report_dir / "bake-report.json"
    for d in (glb_dir, log_dir, report_dir):
        d.mkdir(parents=True, exist_ok=True)

    blender = args.blender or os.environ.get("ARTSTUDIO_BLENDER") or DEFAULT_BLENDER
    if not Path(blender).exists():
        print("[FATAL] 找不到 Blender：%s" % blender, file=sys.stderr)
        return 2
    if not EXPORTER.exists():
        print("[FATAL] 找不到导出器：%s" % EXPORTER, file=sys.stderr)
        return 2

    force_ids = {s.strip() for s in args.only.split(",") if s.strip()}
    unknown = force_ids - set(BY_ID)
    if unknown:
        print("[FATAL] --only 里有未知 id：%s" % sorted(unknown), file=sys.stderr)
        return 2

    exporter_mtime = EXPORTER.stat().st_mtime
    exporter_sha = sha256_file(EXPORTER)
    prev_doc = load_json(manifest_path)
    prev = {}
    prev_blender_version = None
    if isinstance(prev_doc, dict) and prev_doc.get("schema") == SCHEMA \
            and prev_doc.get("version") == SCHEMA_VERSION:
        prev = {c.get("id"): c for c in prev_doc.get("characters", [])}
        prev_blender_version = prev_doc.get("blender_version")
        print("[cache] 读到旧 manifest：%s（%d 个角色）" % (repo_rel(manifest_path), len(prev)))
    elif prev_doc is not None:
        print("[cache] 旧 manifest 的 schema/version 不匹配（%s/%s）→ 忽略，全部重烘"
              % (prev_doc.get("schema"), prev_doc.get("version")))

    heights = height_sources()
    t_start = time.time()
    entries = []
    timings = {}
    errors = []
    evidence_missing = []
    print("[bake] 仓库根 %s" % REPO_ROOT)
    print("[bake] 缓存根 %s" % cache)
    print("[bake] Blender %s" % blender)
    print("[bake] 导出器 %s (sha256 %s)" % (repo_rel(EXPORTER), exporter_sha[:16]))
    print("")

    for i, role in enumerate(CHARACTERS, 1):
        cid = role["id"]
        src = REPO_ROOT / role["src"]
        glb = glb_dir / ("%s.glb" % cid)
        tag = "[%d/%d] %s" % (i, len(CHARACTERS), cid)
        if not src.exists():
            errors.append("%s：源文件不存在 %s" % (cid, src))
            print("%s  源文件不存在 → 跳过" % tag)
            timings[cid] = {"sec": 0.0, "skipped": False}
            continue
        src_sha = sha256_file(src)
        base_height, height_src = heights.get(role["src"], (None, "UNRESOLVED"))

        forced = args.force or cid in force_ids
        reuse = None
        if not forced:
            pe = prev.get(cid)
            if (glb.exists() and pe and pe.get("src_sha256") == src_sha
                    and glb.stat().st_mtime >= src.stat().st_mtime
                    and glb.stat().st_mtime >= exporter_mtime):
                reuse = dict(pe)
        if reuse is not None:
            reuse["glb"] = repo_rel(glb)
            reuse["glb_bytes"] = glb.stat().st_size
            if base_height is not None:
                reuse["base_height_m"] = base_height
            # 复用旧 manifest 条目时必须把"证据"补回来，否则报告会因热缓存而丢数据
            ev = load_json(report_dir / "roles" / ("%s.json" % cid))
            if ev is None:
                evidence_missing.append(cid)
                ev = {}
            reuse["_height_source"] = height_src
            reuse.update(evidence_private(ev))
            # role 规则（v1.1）只依赖 name+materials，二者都在 manifest 里 → 热缓存复用也按
            # 当前规则**重算** role，改规则不必重烘 Blender（glb 字节不动）。
            for p in reuse.get("parts", []):
                p["role"] = classify_role(p.get("name", ""), p.get("materials", []))
            entries.append(reuse)
            timings[cid] = {"sec": 0.0, "skipped": True, "bytes": reuse["glb_bytes"]}
            print("%s  热缓存命中（src_sha256 未变）→ 跳过，%.1f MB" % (tag, reuse["glb_bytes"] / 1048576.0))
            continue

        why = "forced" if forced else ("无旧记录" if not prev.get(cid)
                                      else ("glb 缺失" if not glb.exists()
                                            else ("src 变了" if prev[cid].get("src_sha256") != src_sha
                                                  else "glb 比 src/导出器旧")))
        print("%s  导出中…（%s）" % (tag, why))
        rep, sec, err = run_blender(blender, src, glb, log_dir / ("%s.log" % cid), args.timeout)
        if err:
            errors.append("%s：%s" % (cid, err))
            timings[cid] = {"sec": round(sec, 3), "skipped": False}
            print("%s  ✗ %s（%.1fs）" % (tag, err, sec))
            continue
        if base_height is None:
            base_height = rep.get("mesh_z_range_all")
            height_src = "FALLBACK:Blender 量测 mesh_z_range_all（权威 manifest 里没有该文件）"
        save_json(report_dir / "roles" / ("%s.json" % cid), evidence_from_rep(rep))
        entry = build_entry(role, src, src_sha, glb, rep["bytes"], rep, base_height, height_src)
        entry.update(evidence_private(rep))
        entries.append(entry)
        timings[cid] = {"sec": round(sec, 3), "skipped": False, "bytes": rep["bytes"]}
        print("%s  ✓ %.1f MB / %.1fs%s" % (
            tag, rep["bytes"] / 1048576.0, sec,
            ("，剔除 %d 个杂散对象" % len(rep.get("removed", []))) if rep.get("removed") else ""))

    elapsed = round(time.time() - t_start, 3)

    # ---- manifest（契约字段，无私有键） ----
    blender_version = next((e["_blender_version"] for e in entries if e.get("_blender_version")),
                           prev_blender_version)
    manifest = {
        "schema": SCHEMA,
        "version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "blender_version": blender_version,
        "morph_contract": MORPH_CONTRACT,
        "k_range": K_RANGE,
        "h_range": H_RANGE,
        "role_rules": ROLE_RULES,
        "characters": [strip_private(e) for e in entries],
    }
    if errors:
        print("\n[bake] %d 个角色失败，仍写出 manifest（不完整的缓存，见 errors）" % len(errors))
    save_json(manifest_path, manifest)

    # ---- 自检 ----
    a_res = check_a_container(entries)
    checks = {
        "a_glb_container": a_res,
        "b_garment_manifest_crosscheck": check_b_garment_manifest(entries),
        "c_inventory": check_c_inventory(entries),
        "d_timing_bytes": check_d_timing(entries, timings),
        "e_morph_displacement_vs_upstream": check_e_morph_displacement(entries, a_res),
    }
    all_ok = all(c["ok"] for c in checks.values()) and not errors

    # ---- 角色分类统计与显式提示 ----
    role_tally = {}
    notable = []
    for e in entries:
        for p in e["parts"]:
            role_tally[p["role"]] = role_tally.get(p["role"], 0) + 1
    for e in entries:
        for p in e["parts"]:
            n = p["name"]
            if p["role"] == "cloth" and ("Feet" in n or n in ("Eyebrows", "Eyes")):
                notable.append({"character": e["id"], "part": n, "role": p["role"],
                                "why": "契约规则命中即止的直接后果（名称不等于 _Feet 结尾 / 无 Head_ 前缀）"})

    height_check = {}
    for e in entries:
        measured = e.get("_measured_mesh_z_range_m")
        height_check[e["id"]] = {
            "base_height_m": e["base_height_m"],
            "source": e.get("_height_source"),
            "measured_mesh_z_range_m": measured,
            "delta_m": (round(measured - e["base_height_m"], 6)
                        if measured is not None and e["base_height_m"] is not None else None),
            "measured_armature_z_range_m": e.get("_measured_armature_z_range_m"),
            "removed": e.get("_removed", []),
        }

    mode = ("cold" if all(not t["skipped"] for t in timings.values())
            else "warm" if all(t["skipped"] for t in timings.values()) else "mixed")
    report = {
        "schema": "shape-lab-bake-report",
        "version": 1,
        "generated_at": now_iso(),
        "ok": all_ok,
        "mode": mode,
        "elapsed_sec": elapsed,
        "repo_root": str(REPO_ROOT),
        "cache_root": str(cache),
        "manifest": repo_rel(manifest_path),
        "run_history": repo_rel(report_dir / "run-history.json"),
        "blender": {"path": blender, "version": blender_version},
        "exporter": {"path": repo_rel(EXPORTER), "sha256": exporter_sha},
        "timings": timings,
        "characters": [{
            "id": e["id"], "kind": e["kind"], "label": e["label"],
            "glb": e["glb"], "glb_bytes": e["glb_bytes"],
            "glb_mb": round(e["glb_bytes"] / 1048576.0, 3),
            "sec": timings.get(e["id"], {}).get("sec"),
            "skipped": timings.get(e["id"], {}).get("skipped"),
            "parts": len(e["parts"]), "bones": e["bones"], "armature": e["armature"],
            "base_height_m": e["base_height_m"],
            "evidence": repo_rel(report_dir / "roles" / ("%s.json" % e["id"])),
        } for e in entries],
        "evidence_missing": sorted(evidence_missing),
        "checks": checks,
        "height_source_crosscheck": height_check,
        "loose_geometry": {e["id"]: e.get("_loose_geometry") for e in entries if e.get("_loose_geometry")},
        "role_rules": ROLE_RULES,
        "role_tally": role_tally,
        "role_tally_note": ("契约 v1.1 下 46 件应为 accessory 10 / skin 5 / foot 4 / head 18 / cloth 9；"
                            "独立复算脚本 tmp/shape-lab/review_role_v11.py"),
        "notable_role_classifications": notable,
        "notable_note": ("v1.1 下这张表应为空 —— 它列出的是'名称像 head/foot 族却被判 cloth'的件，"
                         "而 v1.1 的放宽条件正好把这 9 件收进了 head/skin/foot"),
        "errors": errors,
    }
    save_json(report_path, report)

    # ---- 运行历史（每次运行追加一行：冷/热耗时都留档，不因为"最后一次是热跑"而丢掉冷跑数字）----
    hist_path = report_dir / "run-history.json"
    hist = load_json(hist_path)
    if not isinstance(hist, dict) or hist.get("schema") != "shape-lab-run-history":
        hist = {"schema": "shape-lab-run-history", "version": 1, "runs": []}
    hist["runs"].append({
        "generated_at": report["generated_at"],
        "mode": mode,
        "elapsed_sec": elapsed,
        "cold_sec": checks["d_timing_bytes"]["cold_sec"],
        "warm_sec": checks["d_timing_bytes"]["warm_sec"],
        "force": bool(args.force),
        "only": sorted(force_ids),
        "ok": all_ok,
        "total_glb_bytes": sum(e["glb_bytes"] for e in entries),
        "per_character_sec": {cid: t.get("sec") for cid, t in timings.items()},
        "per_character_skipped": {cid: t.get("skipped") for cid, t in timings.items()},
    })
    hist["runs"] = hist["runs"][-50:]
    save_json(hist_path, hist)

    # ---- 控制台汇总 ----
    print("\n===== 自检 =====")
    for name, chk in checks.items():
        print("  %-32s %s" % (name, "OK" if chk["ok"] else "FAIL"))
    if evidence_missing:
        print("  ⚠ 缺证据文件（报告里对应角色的量测字段为空）：%s" % sorted(evidence_missing))
    if errors:
        for e in errors:
            print("  ERROR %s" % e)
    print("\n===== 角色 =====")
    for e in entries:
        t = timings.get(e["id"], {})
        print("  %-22s %7.2f MB  %6.2fs  %s  parts=%d bones=%s" % (
            e["id"], e["glb_bytes"] / 1048576.0, t.get("sec", 0.0),
            "跳过" if t.get("skipped") else "导出", len(e["parts"]), e["bones"]))
    print("\n  mode=%s  总耗时 %.1fs（本次实际导出 %.1fs）" % (
        mode, elapsed, checks["d_timing_bytes"]["cold_sec"]))
    print("  manifest  %s" % repo_rel(manifest_path))
    print("  report    %s" % repo_rel(report_path))
    print("  %s" % ("全部自检通过" if all_ok else "★ 自检未全绿 ★"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
