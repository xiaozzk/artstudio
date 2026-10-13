#!/usr/bin/env python3
"""
v_rootcause.py —— verifier 独立定位穿模根因（不采信任何人的结论）。

回答四个问题，全部用自己的测量：
  Q1 每套服装的「布料网格」里，到底有没有**没被 MI_Regular_* 标出来的身体皮肤**？
     （剥离判据漏判 → 把"身体基准不匹配"混进"穿模率"）
  Q2 各件顶点相对标准体的**有符号距离分布**长什么样？（负=嵌入体内）
  Q3 男侧 3.4 cm 的 rest 差**具体差在哪些骨**？为什么 refit 对靴子有效、对腰带无效？
  Q4 4 套服装的材质清单 + 剥离覆盖率。

只读，不写 .blend。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_rootcause.py -- \
      --out assets/3d/rig/reports/verify-rootcause.json
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OLD = f"{ROOT}/assets/3d/blend/outfits-gltf-per-asset/outfits"
NEW = f"{ROOT}/assets/3d/rig"
CASES = [("Female", "Outfit_Female_Ranger", "Body_Female"),
         ("Male", "Outfit_Male_Ranger", "Body_Male"),
         ("Female", "Outfit_Female_Peasant", "Body_Female"),
         ("Male", "Outfit_Male_Peasant", "Body_Male")]


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def eval_world(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    M = np.array(ev.matrix_world)
    ev.to_mesh_clear()
    return co @ M[:3, :3].T + M[:3, 3]


def signed_dist(tree, pts):
    out = np.full(len(pts), np.nan)
    for i, p in enumerate(pts):
        loc, nor, _, _ = tree.find_nearest(Vector(p), 1e7)
        if loc is not None:
            out[i] = (Vector(p) - loc).dot(nor)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-rootcause.json")
    a = ap.parse_args(argv_after_ddash())
    out = {"generated_by": "verifier/v_rootcause.py", "cases": []}
    t0 = time.perf_counter()
    for sex, outfit, body_obj in CASES:
        rec = {"sex": sex, "outfit": outfit}
        print(f"\n{'#'*88}\n# {sex} {outfit}\n{'#'*88}", flush=True)

        # ---------- Q4 材质清单 + 网格清单 ----------
        bpy.ops.wm.open_mainfile(filepath=f"{OLD}/{outfit}.blend")
        rigA = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
        restA = {b.name: b.matrix_local.copy() for b in rigA.data.bones}
        meshes = [o for o in bpy.data.objects
                  if o.type == "MESH" and not o.name.startswith("Icosphere")]
        inv = []
        for o in meshes:
            names = [m.name if m else "" for m in o.data.materials]
            nf = len(o.data.polygons)
            mi = np.empty(nf, dtype=np.int32)
            o.data.polygons.foreach_get("material_index", mi)
            per = {}
            for i, nm in enumerate(names):
                sel = mi == i
                if sel.sum():
                    per[nm] = int(sel.sum())
            inv.append({"name": o.name, "verts": len(o.data.vertices), "faces": nf,
                        "materials": per,
                        "has_regular_mat": any(n.startswith("MI_Regular_") for n in names)})
        rec["inventory"] = inv
        print("  网格清单:")
        for e in inv:
            print(f"    {e['name']:<34} v={e['verts']:<6} f={e['faces']:<6} "
                  f"regular={e['has_regular_mat']}  {e['materials']}")

        # ---------- 载入标准体 ----------
        with bpy.data.libraries.load(f"{NEW}/bodies/Body_{sex}_Standard.blend") as (s, d):
            d.objects = [body_obj]
        for o in d.objects:
            if o:
                bpy.context.scene.collection.objects.link(o)
        body = bpy.data.objects[body_obj]
        bpy.context.view_layer.update()
        tree, body_co, body_tris = vlib.bvh_from_eval(body)

        # ---------- Q1+Q2 逐件有符号距离（按材质分组） ----------
        pieces = []
        for e in inv:
            o = bpy.data.objects[e["name"]]
            if len(o.data.polygons) == 0:
                continue
            pts = eval_world(o)
            sd = signed_dist(tree, pts)
            ok = ~np.isnan(sd)
            # 按材质分组统计
            names = [m.name if m else "" for m in o.data.materials]
            nf = len(o.data.polygons)
            mi = np.empty(nf, dtype=np.int32)
            o.data.polygons.foreach_get("material_index", mi)
            # 顶点 -> 材质集合
            vmat = {}
            for p in o.data.polygons:
                for vi in p.vertices:
                    vmat.setdefault(vi, set()).add(names[p.material_index])
            grp = {}
            for tag in ("MI_Regular_* (判据内)", "其他材质 (判据外)"):
                sel = np.array([(any(n.startswith("MI_Regular_") for n in vmat.get(i, ()))
                                 if tag.startswith("MI_Regular") else
                                 not any(n.startswith("MI_Regular_") for n in vmat.get(i, ())))
                                for i in range(len(pts))])
                s = sd[sel & ok]
                if s.size == 0:
                    continue
                grp[tag] = {
                    "n": int(s.size),
                    "inside_frac": float(np.mean(s < 0)),
                    "median_cm": float(np.median(s) * 100),
                    "p05_cm": float(np.percentile(s, 5) * 100),
                    "p95_cm": float(np.percentile(s, 95) * 100),
                }
            p = {"piece": e["name"], "n_verts": int(ok.sum()),
                 "inside_frac_all": float(np.mean(sd[ok] < 0)),
                 "median_cm_all": float(np.median(sd[ok]) * 100),
                 "p05_cm": float(np.percentile(sd[ok], 5) * 100),
                 "p95_cm": float(np.percentile(sd[ok], 95) * 100),
                 "by_material_group": grp,
                 "materials": e["materials"]}
            pieces.append(p)
            it = p["inside_frac_all"] * 100
            md = p["median_cm_all"]
            print(f"  {e['name']:<34} n={p['n_verts']:<6} inside={it:6.2f}%  "
                  f"median_sd={md:+7.3f} cm  p05={p['p05_cm']:+7.2f} p95={p['p95_cm']:+7.2f}")
            for tag, g in grp.items():
                print(f"      {tag:<28} n={g['n']:<6} inside={g['inside_frac']*100:6.2f}%  "
                      f"median={g['median_cm']:+7.3f} cm")
        rec["pieces"] = pieces

        # ---------- Q3 男侧 rest 差在哪些骨 ----------
        rigB = body.find_armature()
        restB = {b.name: b.matrix_local.copy() for b in rigB.data.bones}
        rows = []
        for bn, MA in restA.items():
            MB = restB.get(bn)
            if MB is None:
                continue
            hA = np.array(MA)[:3, 3]
            hB = np.array(MB)[:3, 3]
            rows.append({"bone": bn, "head_delta_cm": float(np.linalg.norm(hA - hB) * 100),
                         "matrix_max_elem_delta": float(
                             np.abs(np.array(MA) - np.array(MB)).max())})
        rows.sort(key=lambda r: -r["head_delta_cm"])
        rec["rest_delta_by_bone"] = {
            "n_bones": len(rows),
            "n_over_0.01cm": sum(1 for r in rows if r["head_delta_cm"] > 0.01),
            "max_cm": rows[0]["head_delta_cm"] if rows else 0.0,
            "top10": rows[:10],
            "by_region": region_summary(rows),
        }
        print("  rest 差 top5:", [(r["bone"], round(r["head_delta_cm"], 3)) for r in rows[:5]])
        print("  按区域:", json.dumps(rec["rest_delta_by_bone"]["by_region"], ensure_ascii=False))

        # ---------- 权重分布：为什么靴子动、腰带不动 ----------
        wsum = {}
        for e in inv:
            o = bpy.data.objects[e["name"]]
            if len(o.data.polygons) == 0:
                continue
            gn = {vg.index: vg.name for vg in o.vertex_groups}
            cnt = {}
            for v in o.data.vertices:
                for g in v.groups:
                    if g.weight > 1e-4 and g.group in gn:
                        cnt[gn[g.group]] = cnt.get(gn[g.group], 0) + 1
            head = {r["bone"]: r["head_delta_cm"] for r in rows}
            tot = sum(cnt.values()) or 1
            # 顶点加权平均 rest 位移（预测 refit 位移）
            pred = sum(c * head.get(b, 0.0) for b, c in cnt.items()) / tot
            wsum[e["name"]] = {"n_weight_entries": tot,
                               "predicted_mean_refit_cm": round(pred, 4),
                               "top_groups": sorted(cnt.items(), key=lambda kv: -kv[1])[:6]}
        rec["weight_groups"] = wsum
        for k, v in wsum.items():
            print(f"  权重 {k:<34} 预测refit均值={v['predicted_mean_refit_cm']:7.4f} cm  "
                  f"主力骨={[g for g,_ in v['top_groups'][:3]]}")

        out["cases"].append(rec)
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    vlib.jdump(a.out, out)
    print(f"\n[v_rootcause] wrote {a.out} in {out['total_seconds']}s")


REGIONS = {
    "手/指": ("hand", "index", "middle", "pinky", "ring", "thumb"),
    "臂": ("upperarm", "lowerarm", "clavicle"),
    "躯干": ("spine", "pelvis", "neck", "root"),
    "头": ("Head",),
    "腿": ("thigh", "calf", "foot", "ball"),
}


def region_summary(rows):
    agg = {}
    for r in rows:
        for reg, keys in REGIONS.items():
            if any(k in r["bone"] for k in keys):
                a = agg.setdefault(reg, {"n": 0, "n_over_0.01cm": 0, "max_cm": 0.0})
                a["n"] += 1
                if r["head_delta_cm"] > 0.01:
                    a["n_over_0.01cm"] += 1
                a["max_cm"] = max(a["max_cm"], r["head_delta_cm"])
                break
    for a in agg.values():
        a["max_cm"] = round(a["max_cm"], 4)
    return agg


if __name__ == "__main__":
    main()