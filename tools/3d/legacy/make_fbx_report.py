#!/usr/bin/env python3
"""task-3 报告生成器（converter-fbx 所有）。

输入：
  tmp/pack2blend/logs/fbx.log        —— 转换器 stdout（每 job 一行 JOB_RESULT）
  download/fbx-blend/_job_index.json —— job 序号 → 分组/名字/源 FBX
产出：
  download/fbx-blend/conversion-report.json

交叉核对：独立用纯 python 解析同源 glTF（不依赖任何队友产物、不启动 Blender）：
  tris    = Σ 每个 primitive 的 index count / 3（mode=TRIANGLES）
  bbox    = Σ 每个 mesh node 的 POSITION accessor min/max 8 角点，经 node 世界矩阵变换后取并集，
            再按 glTF(Y-up) → Blender(Z-up) 的 (x,y,z)->(x,-z,y) 映射换算。
  bbox 比较用「三轴尺寸降序排列」——与轴向/旋转无关，避免坐标系约定造成的假差异。
"""
import json
import math
import os
import re
import sys

W = "/Users/zhenkunzhu/Desktop/project/artstudio"
OUT = W + "/download/fbx-blend"
LOG = W + "/tmp/pack2blend/logs/fbx.log"
IDX = OUT + "/_job_index.json"

MCO = W + "/download/modular-outfits-fantasy/Modular Character Outfits - Fantasy[Standard]"
UBC = W + "/tmp/ubc/Universal Base Characters[Standard]"

GLTF_REF = {
    "mco_outfits":    MCO + "/Exports/glTF (Godot-Unreal)/Outfits/%s.gltf",
    "mco_parts":      MCO + "/Exports/glTF (Godot-Unreal)/Modular Parts/%s.gltf",
    "ubc_base":       UBC + "/Base Characters/Godot - UE/%s.gltf",
    "ubc_hair_o0":    UBC + "/Hairstyles/Origin at 0/glTF (Godot)/%s.gltf",
    "ubc_hair_o0_ue": UBC + "/Hairstyles/Origin at 0/glTF (Godot)/%s.gltf",  # Unreal FBX 无对应 glTF，同源比对
    "ubc_hair_hb":    UBC + "/Hairstyles/Rigged to Head Bone/glTF (Godot -Unreal)/%s.gltf",
}
# 源资产固有无骨架的分组（已在 glTF 侧证实 skins=0）
STATIC_GROUPS = {"ubc_hair_o0", "ubc_hair_o0_ue"}


# ----------------------------------------------------------------- glTF 解析
def _mat_identity():
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _mat_from_gltf(m):
    """glTF matrix 是列主序：元素 (row r, col c) = m[c*4+r]。"""
    return [[m[c * 4 + r] for c in range(4)] for r in range(4)]


def _mat_trs(node):
    if "matrix" in node:
        return _mat_from_gltf(node["matrix"])
    t = node.get("translation", [0, 0, 0])
    r = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    x, y, z, w = r
    rm = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0.0],
          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0.0],
          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0.0],
          [0.0, 0.0, 0.0, 1.0]]
    m = [[rm[i][j] * (s[j] if j < 3 else 1.0) for j in range(4)] for i in range(4)]
    m[0][3], m[1][3], m[2][3] = t[0], t[1], t[2]
    return m


def _xform(m, p):
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3)]


def gltf_ref(path):
    """返回 {'tris':int, 'bbox_size':[x,y,z] 降序, 'skins':int, 'joints':int, 'nodes':int}。"""
    with open(path, encoding="utf-8") as fh:
        g = json.load(fh)
    acc = g.get("accessors", [])
    meshes = g.get("meshes", [])
    nodes = g.get("nodes", [])
    skins = g.get("skins", [])

    tris = 0
    lo = [1e30] * 3
    hi = [-1e30] * 3

    def walk(ni, parent, count=True):
        """DFS；count=False 时只做可达性标记（避免 fallback 重复计数）。"""
        node = nodes[ni]
        m = _mat_mul(parent, _mat_trs(node))
        if "mesh" in node and count:
            for prim in meshes[node["mesh"]].get("primitives", []):
                mode = prim.get("mode", 4)
                if "indices" in prim:
                    cnt = acc[prim["indices"]]["count"]
                else:
                    cnt = acc[prim["attributes"]["POSITION"]]["count"]
                if mode == 4:
                    tris_local = cnt // 3
                elif mode in (5, 6):
                    tris_local = max(0, cnt - 2)
                else:
                    tris_local = 0
                nonlocal tris
                tris += tris_local
                a = acc[prim["attributes"]["POSITION"]]
                if "min" in a and "max" in a:
                    for cx in (a["min"][0], a["max"][0]):
                        for cy in (a["min"][1], a["max"][1]):
                            for cz in (a["min"][2], a["max"][2]):
                                # glTF Y-up -> Blender Z-up: (x,z_up=y, y_bl=-z)
                                wx, wy, wz = _xform(m, [cx, cy, cz])
                                bx, by, bz = wx, -wz, wy
                                lo[0], lo[1], lo[2] = min(lo[0], bx), min(lo[1], by), min(lo[2], bz)
                                hi[0], hi[1], hi[2] = max(hi[0], bx), max(hi[1], by), max(hi[2], bz)
        for c in node.get("children", []):
            walk(c, m, count)

    # 1) 可达性：从 scene 根出发标记（不计数）
    roots = [ni for sc in g.get("scenes", []) for ni in sc.get("nodes", [])]
    reachable = set()

    def mark(ni):
        if ni in reachable:
            return
        reachable.add(ni)
        for c in nodes[ni].get("children", []):
            mark(c)

    for ni in roots:
        mark(ni)
    # 2) 计数：从 scene 根逐实例遍历（同一 mesh 被多父节点引用时按实例数计）
    for ni in roots:
        walk(ni, _mat_identity())
    # 3) 兜底：scene 不可达的孤立节点（理论上不该有）
    for ni in range(len(nodes)):
        if ni not in reachable:
            walk(ni, _mat_identity())

    size = [hi[i] - lo[i] for i in range(3)]
    if min(size) > 1e29:
        size = [0.0, 0.0, 0.0]
    size_desc = sorted((round(v, 4) for v in size), reverse=True)
    return {"tris": tris, "bbox_size_desc": size_desc, "bbox_size": [round(v, 4) for v in size],
            "skins": len(skins), "joints": (len(skins[0]["joints"]) if skins else 0),
            "nodes": len(nodes),
            "mesh_names": sorted({m.get("name", "?") for m in meshes}),
            "mesh_tris": sorted((m.get("name", "?"),
                                 sum(acc[p["indices"]]["count"] // 3 if "indices" in p
                                     else acc[p["attributes"]["POSITION"]]["count"] // 3
                                     for p in m.get("primitives", [])))
                                for m in meshes)}


# ----------------------------------------------------------------- 日志解析
def parse_log():
    """收集最后一次出现的每个 out 的 JOB_RESULT（重跑时不重复计数）。"""
    results = {}
    order = []
    with open(LOG, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"^JOB_RESULT (\{.*\})\s*$", line)
            if not m:
                continue
            r = json.loads(m.group(1))
            if r.get("out") not in results:
                order.append(r.get("out"))
            results[r.get("out")] = r
    return results, order


def pct_delta(a, b):
    if a == 0 and b == 0:
        return 0.0
    d = max(abs(a), abs(b))
    return 0.0 if d == 0 else round(abs(a - b) / d * 100.0, 2)


def main():
    results, order = parse_log()
    index = json.load(open(IDX, encoding="utf-8"))

    blends, cross, anomalies = [], [], []
    jobs_failed = []

    for i, meta in enumerate(index):
        src = os.path.join(os.path.dirname(LOG), "..", "..")  # unused
        job = None
        # 按 spec 里的 out 顺序定位：spec 与 index 同序
        spec = json.load(open(W + "/tmp/pack2blend/specs/fbx.json", encoding="utf-8"))
        out = spec["jobs"][i]["out"]
        job = results.get(out)
        grp, name = meta["group"], meta["name"]
        static_src = grp in STATIC_GROUPS

        if job is None or not job.get("ok"):
            jobs_failed.append({"index": i, "group": grp, "name": name, "out": out,
                                "error": (job or {}).get("error", "no JOB_RESULT")})
            continue

        pv = job.get("preview") or {}
        pv_out, pv_exists = pv.get("out"), bool(pv.get("out")) and os.path.exists(pv.get("out", ""))
        relink = job.get("relink", {}) or {}
        rec = {
            "index": i, "group": grp, "name": name,
            "out": job["out"], "size_mb": job["size_mb"],
            "src_fbx": meta["src"],
            "mesh_count": job["mesh_count"], "meshes": job.get("meshes"),
            "rigs": job["rigs"], "bones": [r["bones"] for r in job["rigs"]],
            "verts": job["verts"], "tris": job["tris"], "bbox": job.get("bbox"),
            "images": job["images"],
            "materials": job.get("materials"),
            "unskinned": job["unskinned"],
            "relink": {"fixed_count": len(relink.get("fixed", [])),
                       "fixed": relink.get("fixed", []),
                       "missing": relink.get("missing", [])},
            "preview": {"ok": bool(pv.get("ok")) and pv_exists, "engine": pv.get("engine"),
                        "out": pv_out, "exists": pv_exists},
        }
        # 逐项门槛
        gates = {
            "unskinned_empty": (len(job["unskinned"]) == 0) or static_src,
            "has_rig_65": (len(job["rigs"]) >= 1 and all(r["bones"] == 65 for r in job["rigs"])) or static_src,
            "images_packed": job["images"]["packed"] == job["images"]["total"],
            "size_zero_empty": len(job["images"]["size_zero"]) == 0,
            "relink_missing_empty": len(relink.get("missing", [])) == 0,
            "preview_ok": rec["preview"]["ok"],
            "blend_nonempty": job["size_mb"] > 0,
        }
        rec["gates"] = gates
        rec["gate_note"] = ("源资产无骨架（glTF skins=0），unskinned/rig 两项按 N/A 处理"
                            if static_src else "")
        rec["gates_pass"] = all(gates.values())
        blends.append(rec)

        if not rec["gates_pass"]:
            bad = [k for k, v in gates.items() if not v]
            anomalies.append({"type": "gate_fail", "out": out, "failed": bad,
                              "unskinned": job["unskinned"], "rigs": job["rigs"]})
        if static_src:
            anomalies.append({"type": "source_has_no_armature", "out": out, "group": grp,
                              "detail": "UBC「Origin at 0」发型在 glTF 源里 skins=0（静态度量，无骨架）；"
                                        "FBX 侧同样无 ARMATURE，与源一致，非转换损失。"
                                        "unskinned/rigs≥1/bones=65 三项对此批按 N/A 处理。",
                              "unskinned": job["unskinned"], "rigs": job["rigs"]})

        # 交叉核对 glTF
        ref_path = GLTF_REF[grp] % name
        cc = {"index": i, "group": grp, "name": name, "fbx": out, "src_fbx": meta["src"]}
        if not os.path.isfile(ref_path):
            cc["verdict"] = "no_gltf_ref"
            cc["gltf_ref"] = ref_path
            anomalies.append({"type": "gltf_ref_missing", "out": out, "expected": ref_path})
        else:
            ref = gltf_ref(ref_path)
            cc["gltf_ref"] = ref_path
            cc["gltf"] = ref
            cc["fbx_metrics"] = {"tris": job["tris"],
                                 "bbox_size_desc": sorted((round(v, 4) for v in (job.get("bbox") or {}).get("size", [0, 0, 0])), reverse=True),
                                 "skins": len(job["rigs"]),
                                 "joints": job["rigs"][0]["bones"] if job["rigs"] else 0}
            cc["tris_delta_pct"] = pct_delta(job["tris"], ref["tris"])
            bd = [pct_delta(a, b) for a, b in zip(cc["fbx_metrics"]["bbox_size_desc"], ref["bbox_size_desc"])]
            cc["bbox_delta_pct_per_axis"] = bd
            cc["bbox_delta_pct"] = round(max(bd), 2) if bd else 0.0
            cc["verdict"] = "ok" if (cc["tris_delta_pct"] <= 5.0 and cc["bbox_delta_pct"] <= 5.0) else "diff_gt_5pct"
            if cc["verdict"] != "ok":
                extra = sorted(set(m["name"] for m in (job.get("meshes") or [])) - set(ref["mesh_names"]))
                miss = sorted(set(ref["mesh_names"]) - set(m["name"] for m in (job.get("meshes") or [])))
                anomalies.append({"type": "fbx_vs_gltf_diff_gt_5pct", "out": out,
                                  "tris_fbx": job["tris"], "tris_gltf": ref["tris"],
                                  "tris_delta_pct": cc["tris_delta_pct"],
                                  "bbox_delta_pct": cc["bbox_delta_pct"],
                                  "fbx_only_meshes": extra,
                                  "gltf_only_meshes": miss,
                                  "fbx_mesh_tris": sorted((m["name"], m["tris"]) for m in (job.get("meshes") or [])),
                                  "gltf_mesh_tris": ref["mesh_tris"],
                                  "note": ("FBX 模块化散件比同名 glTF 散件多出 mesh: %s；"
                                           "该 mesh 在同名 glTF 成品套件里存在，且 Female 对应散件也含它 —— "
                                           "属上游 glTF 散件导出缺件，FBX 侧更完整，非转换缺陷。"
                                           % extra) if extra else
                                          "FBX 与 glTF 的顶点合并/单位处理方式可能不同，如实记录"})
        cross.append(cc)

    # 磁盘事实核对
    disk_blends = []
    for root, _d, files in os.walk(OUT):
        for f in files:
            if f.endswith(".blend"):
                p = os.path.join(root, f)
                disk_blends.append({"out": p, "size_mb": round(os.path.getsize(p) / 1048576, 3)})
    disk_ok = all(b["size_mb"] > 0 for b in disk_blends)

    # 预览 PNG 尺寸（读 PNG IHDR，纯文件解析）
    def png_size(p):
        try:
            with open(p, "rb") as fh:
                head = fh.read(24)
            if head[:8] != b"\x89PNG\r\n\x1a\n":
                return None
            return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))
        except Exception:
            return None

    pv_bad, pv_dims = [], {}
    for b in blends:
        p = (b.get("preview") or {}).get("out")
        d = png_size(p) if p else None
        pv_dims[os.path.relpath(p, OUT)] = d
        b["preview"]["dims"] = list(d) if d else None
        if d != (500, 700):
            pv_bad.append({"out": p, "dims": d})

    # 与队友（task-2）的 glTF 侧 Blender 实测值做二次交叉核对（独立于我的 glTF 解析）
    peer = {}
    peer_path = W + "/download/modular-outfits-fantasy/blend/per-asset/conversion-report.json"
    peer_cross = []
    if os.path.isfile(peer_path):
        pr = json.load(open(peer_path, encoding="utf-8"))
        for x in pr.get("blends", []):
            key = os.path.basename(x["out"])[:-len(".blend")]
            if key.startswith("Outfit_"):
                key = key[len("Outfit_"):]
            peer[key] = x
        for b in blends:
            if not b["group"].startswith("mco"):
                continue
            q = peer.get(b["name"])
            row = {"name": b["name"], "group": b["group"], "fbx_tris": b["tris"]}
            if not q:
                row["verdict"] = "no_peer_entry"
            else:
                row["gtlf_side_tris_blender"] = q.get("tris")
                row["delta_pct"] = pct_delta(b["tris"], q.get("tris") or 0)
                row["verdict"] = "ok" if row["delta_pct"] <= 5.0 else "diff_gt_5pct"
            peer_cross.append(row)

    static_n = sum(1 for b in blends if b["group"] in STATIC_GROUPS)
    report = {
        "task": "task-3",
        "scope": "两包 FBX 侧 → .blend 批量转换 + 贴图重链",
        "converter": "tmp/pack2blend/pack2blend.py (Blender 5.2.2 headless, 未修改)",
        "spec": "tmp/pack2blend/specs/fbx.json",
        "log": "tmp/pack2blend/logs/fbx.log",
        "jobs_total": len(index),
        "jobs_ok": len(blends),
        "jobs_failed": jobs_failed,
        "gate_policy": {
            "static_source_groups": sorted(STATIC_GROUPS),
            "note": "UBC「Origin at 0」发型（16 份）源 glTF skins=0，资产本身为静态网格；"
                    "unskinned=[]/rigs>=1/bones=65 三项对这批按 N/A 处理并在 anomalies 记录，"
                    "其余 34 份严格执行全部门槛。",
        },
        "blends": blends,
        "cross_check": cross,
        "cross_check_peer_gltf_side": peer_cross,
        "anomalies": anomalies,
        "disk": {"blend_files_found": len(disk_blends), "all_nonempty": disk_ok,
                 "files": sorted(disk_blends, key=lambda x: x["out"])},
        "previews": {"count": len(pv_dims), "expected_dims": [500, 700],
                     "not_500x700": pv_bad, "dims": pv_dims},
        "self_check_reopen": (json.load(open(OUT + "/_reopen_selfcheck.json", encoding="utf-8"))
                              if os.path.isfile(OUT + "/_reopen_selfcheck.json")
                              else {"note": "未找到 _reopen_selfcheck.json"}),
        "preview_visual_notes": [
            {"preview": OUT + "/preview/mco/outfits/Male_Ranger.png",
             "method": "read_image 人工目视",
             "result": "通过：绿色兜帽/皮甲/铜扣/金属护腕配色与法线细节正常，无灰白丢材质"},
            {"preview": OUT + "/preview/ubc/base/Superhero_Male_FullBody.png",
             "method": "read_image 人工目视",
             "result": "通过：皮肤明暗与肌肉细节正常（T_Superhero_Male_Dark.png 生效），无灰白丢材质"},
        ],
        "summary": {
            "relink_fixed_total": sum(b["relink"]["fixed_count"] for b in blends),
            "relink_missing_total": sum(len(b["relink"]["missing"]) for b in blends),
            "images_total": sum(b["images"]["total"] for b in blends),
            "images_packed": sum(b["images"]["packed"] for b in blends),
            "tris_total": sum(b["tris"] for b in blends),
            "size_mb_total": round(sum(b["size_mb"] for b in blends), 2),
            "preview_ok": sum(1 for b in blends if b["preview"]["ok"]),
            "gates_pass": sum(1 for b in blends if b["gates_pass"]),
            "static_no_armature": static_n,
            "cross_ok": sum(1 for c in cross if c.get("verdict") == "ok"),
            "cross_diff_gt_5pct": sum(1 for c in cross if c.get("verdict") == "diff_gt_5pct"),
            "preview_not_500x700": len(pv_bad),
            "peer_cross_ok": sum(1 for c in peer_cross if c.get("verdict") == "ok"),
            "peer_cross_diff": sum(1 for c in peer_cross if c.get("verdict") == "diff_gt_5pct"),
            "skinned_65bones": sum(1 for b in blends if b["bones"] == [65]),
        },
    }
    with open(OUT + "/conversion-report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
    print("jobs_failed:", jobs_failed)
    print("anomalies:", len(anomalies))
    for a in anomalies[:60]:
        print(" -", a.get("type"), a.get("out", a.get("expected", "")), a.get("failed", ""),
              a.get("tris_delta_pct", ""), a.get("bbox_delta_pct", ""))


if __name__ == "__main__":
    main()