"""tools/3d/garment/strip_skin.py —— ① 剥离：按材质剔除 MI_Regular_* 皮肤面

SPEC §4.1 ①：判据 = 面所属材质名以 `MI_Regular_` 开头 → 删除该面。
为什么必须做（D2/F2）：服装长在「Regular」身体上，标准体是「Superhero」，
保留皮肤面 = 与标准体双重叠模。

用法
----
  Blender -b --factory-startup --python tools/3d/garment/strip_skin.py -- \
      [--out tmp/garment/work/stripped] [--only Female_Ranger] [--keep-loose]

输出
----
  <out>/Outfit_<Name>.blend    纯布料件（骨架保持原样，供 refit 用）
  <out>/strip_report.json      每件剥离前后顶点/面数、皮肤占比、材质前后

幂等：每次从 `assets/3d/blend/...` 原件重读，可随意重跑。
"""
import argparse
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="strip_skin.py")
    ap.add_argument("--out", default=os.path.join(C.WORK, "stripped"))
    ap.add_argument("--only", default=None, help="只处理一套（如 Female_Ranger）")
    ap.add_argument("--keep-loose", action="store_true",
                    help="不删孤立顶点（默认删：皮肤面的顶点会变成孤立点）")
    return ap.parse_args(argv)


def strip_one(outfit, sex, out_dir, keep_loose):
    src = os.path.join(C.SRC_OUTFITS, f"Outfit_{outfit}.blend")
    C.log(f"\n{'='*78}\n[strip] {outfit}   <- {C.rel(src)}")
    bpy.ops.wm.open_mainfile(filepath=src)

    # 丢掉源包的环境辅助体（Icosphere：42 顶点、无材质、无权重）
    helpers = [o.name for o in bpy.data.objects if C.is_helper(o)]
    for n in helpers:
        bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
    if helpers:
        C.log(f"  移除辅助体：{helpers}")

    def pred(mat_name):
        return mat_name.startswith(C.SKIN_MAT_PREFIX)

    rec = {"outfit": outfit, "sex": sex, "src": C.rel(src), "helpers_removed": helpers,
           "parts": [], "skin_mat_prefix": C.SKIN_MAT_PREFIX}
    tot_before = tot_after = tot_removed = 0
    for o in sorted([x for x in bpy.data.objects if x.type == 'MESH'], key=lambda x: x.name):
        hist_before = C.face_material_histogram(o)
        f_before = sum(hist_before.values())
        skin_faces = sum(v for k, v in hist_before.items() if pred(k))
        res = C.strip_faces_by_material(o, pred)
        if not keep_loose:
            res["removed_loose_verts"] = res["removed_loose_verts"]
        p = {"part": o.name,
             "faces_before": res["before_faces"], "faces_after": res["after_faces"],
             "verts_before": res["before_verts"], "verts_after": res["after_verts"],
             "skin_faces_removed": res["removed_faces"],
             "skin_face_share": round(skin_faces / f_before, 6) if f_before else 0.0,
             "loose_verts_removed": res["removed_loose_verts"],
             "materials_before": res["materials_before"],
             "materials_after": res["materials_after"],
             "faces_by_material_before": hist_before}
        rec["parts"].append(p)
        tot_before += res["before_faces"]
        tot_after += res["after_faces"]
        tot_removed += res["removed_faces"]
        C.log(f"  * {o.name:32s} 面 {res['before_faces']:5d} → {res['after_faces']:5d} "
              f"(剥 {res['removed_faces']:5d} = {100*p['skin_face_share']:5.1f}%)  "
              f"顶点 {res['before_verts']:5d} → {res['after_verts']:5d} "
              f"(孤立 {res['removed_loose_verts']})  材质 {res['materials_before']} → {res['materials_after']}")
        if res["after_faces"] == 0:
            C.log(f"    ⚠ {o.name} 剥空了 —— 整件都是皮肤面，将被删除")

    # 整件被剥空的：删掉（当前 4 套里没有，保险）
    emptied = [p["part"] for p in rec["parts"] if p["faces_after"] == 0]
    for n in emptied:
        bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
    rec["parts_emptied_removed"] = emptied

    rec["faces_before"] = tot_before
    rec["faces_after"] = tot_after
    rec["skin_faces_removed"] = tot_removed
    rec["outfit_skin_face_share"] = round(tot_removed / tot_before, 6) if tot_before else 0.0
    rec["verts_before"] = sum(p["verts_before"] for p in rec["parts"])
    rec["verts_after"] = sum(p["verts_after"] for p in rec["parts"])
    C.log(f"  ── 合计：面 {tot_before} → {tot_after}，剥离 {tot_removed} "
          f"= {100*rec['outfit_skin_face_share']:.2f}% 皮肤面")

    # 皮肤贴图不再被引用 → 清掉（体积 + 避免误导）
    C.purge_orphans()
    rec["textures"] = sorted(i.name for i in bpy.data.images if i.source == 'FILE')
    rec["materials"] = sorted(m.name for m in bpy.data.materials)
    C.log(f"  贴图：{rec['textures']}")
    C.log(f"  材质：{rec['materials']}")

    out = os.path.join(out_dir, f"Outfit_{outfit}.blend")
    C.save_blend(out)
    rec["out"] = C.rel(out)
    return rec


def main():
    a = parse_args()
    C.ensure_dirs()
    os.makedirs(a.out, exist_ok=True)
    jobs = [(o, s) for o, s in C.OUTFITS if a.only in (None, o)]
    assert jobs, f"--only {a.only} 不匹配任何服装"
    report = [strip_one(o, s, a.out, a.keep_loose) for o, s in jobs]
    rp = os.path.join(a.out, "strip_report.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"tool": "strip_skin.py", "spec": "assets/3d/rig/SPEC.md v1.0",
                   "skin_mat_prefix": C.SKIN_MAT_PREFIX, "outfits": report},
                  f, ensure_ascii=False, indent=2)
    C.log(f"\n{'#'*78}\n# 剥离汇总（口径：面数）\n{'#'*78}")
    for r in report:
        C.log(f"  {r['outfit']:16s} 面 {r['faces_before']:6d} → {r['faces_after']:6d}  "
              f"皮肤面占比 {100*r['outfit_skin_face_share']:5.2f}%  "
              f"顶点 {r['verts_before']:6d} → {r['verts_after']:6d}")
    C.log(f"\n报告 → {C.rel(rp)}\nDONE")


main()