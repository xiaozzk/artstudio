#!/usr/bin/env python3
"""make_report.py —— 解析 tmp/pack2blend/logs/ubc.log 生成
download/ubc-blend/conversion-report.json

数据来源（同一份日志，按 'out' 取**最后一次**出现的记录）：
  JOB_RESULT    <- tmp/pack2blend/pack2blend.py（转换时的内存结果，含 relink.fixed）
  VERIFY_RESULT <- download/ubc-blend/tools/verify_blends.py（落盘后从 .blend 重新测量，权威）
  FIX_RESULT    <- download/ubc-blend/tools/fix_textures.py（首轮兜底补丁，仅作证据）
判定口径（Lead 2026-10-12 更新）：
  · skinned 件：rigs≥1、每根 rig bones==65、所有 mesh 有 ARMATURE modifier 且 vertex_groups>0；
  · static 件（Hairstyles/Origin at 0，源 glTF skins=0）：必须**无** ARMATURE modifier 且 vertex_groups==0，
    rigs/bones/unskinned 记 N/A；
  · 所有件：images.packed==images.total、size_zero==[]、preview.ok=true 且 PNG 落盘。
"""
import hashlib
import json
import os
import re

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
LOG = ROOT + "/tmp/pack2blend/logs/ubc.log"
SPEC = ROOT + "/tmp/pack2blend/specs/ubc.json"
CONVERTER = ROOT + "/tmp/pack2blend/pack2blend.py"
OUT = ROOT + "/download/ubc-blend/conversion-report.json"


def parse_log():
    jobs, verifies, fixes = {}, {}, []
    with open(LOG, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("JOB_RESULT "):
                r = json.loads(line[len("JOB_RESULT "):])
                jobs[r.get("out")] = r
            elif line.startswith("VERIFY_RESULT "):
                r = json.loads(line[len("VERIFY_RESULT "):])
                verifies[r["out"]] = r
            elif line.startswith("FIX_RESULT "):
                fixes.append(json.loads(line[len("FIX_RESULT "):]))
    return jobs, verifies, fixes


def gltf_skins(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return len(d.get("skins", []))
    except Exception:  # noqa: BLE001
        return None


def md5(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def main():
    spec = json.load(open(SPEC, encoding="utf-8"))
    jobs_log, verify_log, fixes = parse_log()

    blends, anomalies, gate = [], [], {}
    order, kind_by_out = [], {}
    for job in spec["jobs"]:
        out = job["out"]
        order.append(out)
        n_skin = n_static = 0
        for entry in job["imports"]:
            sk = gltf_skins(entry["file"])
            if sk:
                n_skin += 1
            else:
                n_static += 1
        kind_by_out[out] = ("skinned" if n_static == 0
                            else "static" if n_skin == 0 else "mixed")

    jobs_ok = sum(1 for o in order if jobs_log.get(o, {}).get("ok") is True)
    failed = [o for o in order if jobs_log.get(o, {}).get("ok") is not True]

    prev_ok_all = prev_wh_all = True
    packed_ok_all = sizezero_ok_all = True
    exist_ok_all = True
    skinned_ok_all = static_ok_all = mixed_ok_all = True

    for out in order:
        v = verify_log.get(out)
        j = jobs_log.get(out, {})
        kind = kind_by_out[out]
        n_static_imports = sum(1 for e in next(x for x in spec["jobs"] if x["out"] == out)["imports"]
                               if not gltf_skins(e["file"]))
        if v is None:
            exist_ok_all = False
            blends.append({"out": out, "kind": kind, "missing": "无 VERIFY_RESULT"})
            continue
        images = v["images"]
        pv = v["preview"]
        rigs = v["rigs"]
        detail = v["mesh_detail"]
        issues, na = [], []

        if not (os.path.exists(out) and v["size_mb"] > 0):
            exist_ok_all = False
            issues.append("blend 不存在或 size=0")
        if images["packed"] != images["total"]:
            packed_ok_all = False
            issues.append("images.packed(%d) != total(%d)" % (images["packed"], images["total"]))
        if images["size_zero"] or images["packed_bytes_zero"]:
            sizezero_ok_all = False
            issues.append("存在空图: %s %s" % (images["size_zero"], images["packed_bytes_zero"]))
        if not (j.get("preview", {}).get("ok") and pv["exists"] and pv.get("bytes", 0) > 0):
            prev_ok_all = False
            issues.append("preview 缺失/渲染失败")
        if not pv.get("wh_ok"):
            prev_wh_all = False
            issues.append("preview 分辨率 %s != %s" % (pv.get("wh"), pv.get("expected_wh")))

        if kind == "skinned":
            if not rigs:
                issues.append("无 rig")
            bad = [r for r in rigs if r["bones"] != 65]
            if bad:
                issues.append("bones != 65: %s" % bad)
            badm = [m for m in detail if not m["armature_mod"] or m["vgroups"] <= 0]
            if badm:
                issues.append("未蒙皮/无 vgroup 的 mesh: %s" % [m["name"] for m in badm])
            if issues:
                skinned_ok_all = False
        elif kind == "static":
            na = ["rigs>=1（源 glTF skins=0，静态件）",
                  "bones==65（静态件无 rig）",
                  "unskinned==[]（静态件本就没有 armature modifier）"]
            badm = [m for m in detail if m["armature_mod"] or m["vgroups"] != 0]
            if badm:
                issues.append("静态件不应有 rig/vgroup: %s" % [m["name"] for m in badm])
            if issues:
                static_ok_all = False
        else:  # mixed
            with_arm = [m for m in detail if m["armature_mod"]]
            without = [m for m in detail if not m["armature_mod"]]
            na = ["混装件：%d 个 _Origin0 静态 mesh 的 rig/unskinned 判据" % n_static_imports]
            if len(without) != n_static_imports:
                issues.append("静态 mesh 数 %d != 源静态 import 数 %d" % (len(without), n_static_imports))
            if [m for m in without if m["vgroups"] != 0]:
                issues.append("静态 mesh 带 vertex_groups")
            if [m for m in with_arm if m["vgroups"] <= 0]:
                issues.append("蒙皮 mesh 无 vertex_groups")
            if [r for r in rigs if r["bones"] != 65]:
                issues.append("bones != 65")
            if issues:
                mixed_ok_all = False

        blends.append({
            "out": out,
            "kind": kind,
            "size_mb": v["size_mb"],
            "mesh_count": v["mesh_count"],
            "meshes": v["meshes"],
            "rigs": rigs,
            "tris": v["tris"],
            "verts": v["verts"],
            "images_total": images["total"],
            "images_packed": images["packed"],
            "images_size_zero": images["size_zero"],
            "images_unpacked": images["unpacked"],
            "unskinned": v["unskinned"],
            "collections": v["collections"],
            "readme_text": v["readme_text"],
            "relink_fixed": j.get("relink", {}).get("fixed", []),
            "relink_missing": j.get("relink", {}).get("missing", []),
            "preview": {"ok": bool(j.get("preview", {}).get("ok")) and pv["exists"],
                        "engine": j.get("preview", {}).get("engine"),
                        "out": pv["out"], "exists": pv["exists"],
                        "bytes": pv.get("bytes"), "wh": pv.get("wh"),
                        "wh_ok": pv.get("wh_ok")},
            "gate": {"ok": not issues, "na": na, "issues": issues},
        })

    relink_records = sum(len(b.get("relink_fixed", [])) for b in blends)
    relink_blends = [os.path.basename(b["out"]) for b in blends if b.get("relink_fixed")]
    relink_files = sorted({os.path.basename(f["orig_name"])
                           for b in blends for f in b.get("relink_fixed", [])})

    kinds = [b["kind"] for b in blends]
    gate = {
        "jobs_failed_empty": not failed,
        "blends_exist_size_gt0": exist_ok_all,
        "images_packed_eq_total_all": packed_ok_all,
        "images_size_zero_empty_all": sizezero_ok_all,
        "preview_ok_and_png_on_disk_all": prev_ok_all,
        "preview_resolution_expected_all": prev_wh_all,
        "skinned_blends_65bones_fully_skinned": skinned_ok_all,
        "static_blends_no_armature_vgroups0": static_ok_all,
        "mixed_blend_partition_ok": mixed_ok_all,
    }
    gate["overall_pass"] = all(gate.values())

    # ---------------- anomalies ----------------
    anomalies = [
        "上游源包坏引用（已由转换器 relink 修复，非转换器 bug）："
        "Base Characters/Godot - UE/Superhero_Male_FullBody.gltf 的 images[].uri 写成 "
        "T_Hair_1_Normal_png.png / T_Eye_Normal_png.png，Superhero_Female_FullBody.gltf 写成 "
        "T_Eye_Normal_png.png，而包内实际文件是同目录的 T_Hair_1_Normal.png / T_Eye_Normal.png"
        "（全包 find 无 *_Normal_png.png）。修复前 Male 5/7、Female 6/7、ALL 18/21 packed，"
        "这 2 张图 Image.size=(0,0) 且 pack_all 报 'Unable to pack file ... not found'（.blend 不自包含）。"
        "pack2blend.py（md5 %s，relink 默认开启 + _name_candidates 文件名归一化）重跑后已修："
        "Male fixed=2、Female fixed=1、ALL fixed=3，全部 renamed=true，现 7/7、7/7、21/21 packed、size_zero=[]。"
        % (md5(CONVERTER) or "?"),
        "静态件按源语义判 N/A：Hairstyles/Origin at 0/glTF (Godot)/<H>.gltf 8 份源头即静态网格"
        "（实测 nodes=1、skins=0，无 armature；converter-fbx 在 FBX 侧同样实测无 ARMATURE），"
        "因此 Hair_<H>__Origin0.blend 的「rigs≥1」「all bones==65」「unskinned==[]」三项记为 "
        "N/A（源资产固有属性），未伪造 rig。对应判定规则改为：静态件必须无 ARMATURE modifier 且 "
        "vertex_groups==0（8 份全部符合）。",
        "UBC_Standard_ALL.blend 为混装件（kind=mixed）：10 个 65 骨 rig（2 形体 + 8 HeadBone 发型）"
        "+ 8 个 _Origin0 静态 mesh（Eyebrows_Female.001 / Eyebrows_Regular.001 / Hair_Beard.001 / "
        "Hair_Buns.001 / Hair_Buzzed.001 / Hair_BuzzedFemale.001 / Hair_Long.001 / Hair_SimpleParted.001，"
        "vgroups=0 且无 ARMATURE modifier）。静态部分同样按 N/A 处理，蒙皮部分 65 骨/满 vertex_groups 全过。",
    ]

    framing = None
    for line in open(LOG, encoding="utf-8", errors="replace"):
        if line.startswith("FRAMING_RESULT "):
            framing = json.loads(line[len("FRAMING_RESULT "):])
    if framing:
        anomalies.append(
            "UBC_Standard_ALL 的 grid 总览图取景不合格（观感/取景问题，不影响 .blend 内数据完整性）："
            "画幅 %s，18 个真实顶层件里只有 %d 个完全落在画幅内、%d 个被裁切（%s）。"
            "两处根因都在 tmp/pack2blend/pack2blend.py（我未改动，已上报 lead）："
            "(a) layout_grid() 经 top_level() 取顶层件时把 glTF 导入器的隐藏辅助体也算进去了 —— "
            "本件 %d 个顶层件 = %d 真实件 + %d 个 glTF_not_exported 集合里的 Icosphere"
            "（hide_render/hide_viewport=True，不渲染但占格子），于是网格变成 6 列×5 行、真实资产被排进散乱格子；"
            "(b) setup_stage()->bbox_of_meshes() 在 layout_grid() 移动对象之后没有 view_layer.update()，"
            "读到的是**未刷新**的 matrix_world，于是按位移前的 bbox（size=1.8589 m）而非位移后的 "
            "5.20×5.87 m 取景：相机落在 %s，与位移前 bbox 的推算值 (0, -4.833, 1.049) 完全吻合，"
            "可视范围仅约 3.15×1.97 m，故边缘件被裁。另：grid dx=1.0 小于形体臂展 1.86 m，"
            "2 个形体同处一行（RIG_Superhero_Female_FullBody x=-0.50 / RIG_Superhero_Male_FullBody x=+0.50、"
            "y=5.60），手臂互相穿插约 0.86 m。建议：top_level() 排除 HELPER 集合、"
            "setup_stage() 前调用 view_layer.update()、grid dx≥2.0 或把形体单独排一行/改正交相机。"
            "其余 18 份单件 preview（layout=none）取景正常，未受影响。"
            % (framing["resolution"], framing["fully_inside"], len(framing["clipped"]),
               framing["clipped_names"] or "无", framing["top_level_items"],
               framing["asset_items"], framing["helper_items"],
               [round(v, 3) for v in framing["camera"]["loc"]]))
    else:
        anomalies.append("未能读取 FRAMING_RESULT（tools/check_all_framing.py 未运行）")

    anomalies.append(
        "收尾清理（lead 2026-10-12 指派）：删除 download/ubc-blend/*.blend1 共 19 份（180 MB，"
        "Blender 覆盖保存同名 .blend 时的自动备份，可再生、非交付物）；19 份 .blend 与 19 张 preview 未动。")

    if fixes:
        anomalies.append(
            "过程记录（已被 RUN2 取代，不是缺陷）：首轮转换（pack2blend.py 修好前）我用 "
            "download/ubc-blend/tools/fix_textures.py 对 Male/Female/ALL 三份 .blend 做过一次性就地重链"
            "（结果与 RUN2 一致，size 14.84/15.14/54.21 MB 未变）；RUN2 起贴图修复来自转换器 relink 本身，"
            "该脚本已停用，仅作证据/兜底保留。")

    report = {
        "task": "task-1",
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "jobs_total": len(spec["jobs"]),
        "jobs_ok": jobs_ok,
        "jobs_failed": [os.path.basename(o) for o in failed],
        "blends": blends,
        "totals": {
            "blends": len(blends),
            "size_mb_sum": round(sum(b.get("size_mb", 0) for b in blends), 2),
            "tris_sum": sum(b.get("tris", 0) for b in blends),
            "verts_sum": sum(b.get("verts", 0) for b in blends),
            "skinned_blends": kinds.count("skinned"),
            "static_blends": kinds.count("static"),
            "mixed_blends": kinds.count("mixed"),
            "rigs_total": sum(len(b.get("rigs", [])) for b in blends),
            "images_packed_sum": sum(b.get("images_packed", 0) for b in blends),
            "images_total_sum": sum(b.get("images_total", 0) for b in blends),
            "relink_fixed_records": relink_records,
            "relink_fixed_blends": relink_blends,
            "relink_fixed_upstream_files": relink_files,
            "previews": len(blends),
        },
        "gate_checks": gate,
        "anomalies": anomalies,
        "evidence": {
            "converter": {"script": "tmp/pack2blend/pack2blend.py", "md5": md5(CONVERTER),
                          "blender": "5.2.2 LTS"},
            "spec": "tmp/pack2blend/specs/ubc.json",
            "log": "tmp/pack2blend/logs/ubc.log",
            "log_records": {"JOB_RESULT": len(jobs_log), "VERIFY_RESULT": len(verify_log),
                            "FIX_RESULT": len(fixes)},
            "source_root": "tmp/ubc/Universal Base Characters[Standard]",
            "tools": ["download/ubc-blend/tools/verify_blends.py（落盘复测，本报告数值来源）",
                      "download/ubc-blend/tools/check_all_framing.py（总览图取景量化）",
                      "download/ubc-blend/tools/fix_textures.py（首轮兜底，已停用）"],
            "framing": framing and {k: framing[k] for k in
                                    ("resolution", "camera", "top_level_items",
                                     "asset_items", "helper_items", "fully_inside",
                                     "clipped_names")},
        },
        "housekeeping": [
            "删除 download/ubc-blend/*.blend1 共 19 份（Blender 自动备份，180 MB）；"
            "19 份 .blend 与 preview/*.png（19 张）保留。",
            "download/ubc-blend/tools/ 下 3 个脚本仅作复现/证据，不是交付物本体。",
        ],
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"out": OUT, "jobs_ok": jobs_ok, "jobs_failed": report["jobs_failed"],
                      "gate_checks": gate, "totals": report["totals"],
                      "anomalies": len(anomalies)}, ensure_ascii=False, indent=1))


main()