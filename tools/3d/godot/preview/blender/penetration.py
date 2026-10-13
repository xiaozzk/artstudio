# -*- coding: utf-8 -*-
"""离线预算「**穿模率 vs 体形滑块**」曲线 —— T3 的穿模指示数据源。

口径（必须写清，验收要看误差来源）：
  * 对每个 `k ∈ [-1, +1]`（默认 9 档，步长 0.25）：
      `BS_Thin = max(-k,0)`、`BS_Heavy = max(k,0)`（SPEC §3.3）
  * 身体与服装**都**按同一组值走 depsgraph 求值（SPEC F9：shape key 不改 `mesh.vertices`）。
  * 用身体的**变形后**网格建 `BVHTree`，对服装的**每一个**变形后顶点做 `find_nearest`，
    得到最近点 `q` 与最近面的法线 `n`。
  * 有符号间隙 `s = (p - q) · n`（米）。`s > 0` = 在身体外（正常），`s < 0` = 钻进身体里（穿模）。
  * **穿模率** = `s < -tol` 的顶点占比 × 100%，`tol` 默认 2 mm（皮肤/布料本来就贴在一起，
    留 2 mm 容差避免把"贴住"误判为"穿进去"）。
  * 附带 `body_max_disp_mm`：各档身体相对标准体的最大位移 —— 自证"形态键真的生效"，
    防止出现"曲线恒定不变"这种假数据（第一版就踩过）。

误差来源（诚实声明）：
  1. 最近面法线是**面法线**，不是真"伪法线"，在棱角/腋下/胯部会偏高估或低估；
  2. 只对**服装顶点**采样，不检测"身体穿出服装"；
  3. 未做自穿透检测（布料自己叠自己不算）；
  4. 服装的开放边界（袖口/领口/下摆）附近，最近面可能落在身体另一侧。

用法：
  Blender --background --factory-startup --python penetration.py -- \
      <body.blend> <out.json> <garment1.blend> [garment2.blend ...] [--tol 0.002]
"""
import json
import os
import sys

import bpy
from mathutils.bvhtree import BVHTree

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import _morphfix  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
body_path, out_json = argv[0], argv[1]
garments = list(argv[2:])
tol = 0.002
if "--tol" in garments:
    ti = garments.index("--tol")
    tol = float(garments[ti + 1])
    del garments[ti:ti + 2]
body_morph = "--body-morph" in garments
if body_morph:
    garments.remove("--body-morph")
spec_path = None
if "--spec" in garments:
    si = garments.index("--spec")
    spec_path = garments[si + 1]
    del garments[si:si + 2]

KS = [-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0]


def set_k(objs, k):
    thin = max(-k, 0.0)
    heavy = max(k, 0.0)
    for ob in objs:
        if ob.data.shape_keys:
            for kb in ob.data.shape_keys.key_blocks:
                if kb.name == "BS_Thin":
                    kb.value = thin
                elif kb.name == "BS_Heavy":
                    kb.value = heavy
                elif kb.name == "Basis":
                    kb.value = 1.0


def evaluated(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    m = ev.to_mesh()
    mw = ob.matrix_world
    verts = [mw @ v.co for v in m.vertices]
    polys = [list(p.vertices) for p in m.polygons]
    ev.to_mesh_clear()
    return verts, polys


result = {"body": body_path, "tol_m": tol, "ks": KS, "garments": {},
          "method": "BVHTree.find_nearest + 最近面法线有符号距离；穿模 = s < -tol"}

# 先把标准体读进来（否则当前文件是 factory 启动场景，根本没有 Body_*）
bpy.ops.wm.open_mainfile(filepath=body_path)
_body = _morphfix.find_body()
if _body is None:
    raise SystemExit("body 里找不到 Body_* + shape key：%s" % body_path)
if body_morph:  # 必须与 export_glb.py 用**同一份**处理，否则曲线与 Godot 看到的不是一回事
    result["body_morph"] = _morphfix.ensure_body_morph(_body, spec_path)
    print("MORPHFIX " + json.dumps(result["body_morph"], ensure_ascii=False))
else:
    for _k in _body.data.shape_keys.key_blocks:
        _k.value = 0.0

for gpath in garments:
    gname = os.path.splitext(os.path.basename(gpath))[0]
    before = set(bpy.data.objects.keys())
    with bpy.data.libraries.load(gpath, link=False) as (src, dst):
        dst.objects = [n for n in src.objects]
    added = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    gmeshes = [o for o in added if o.type == 'MESH']
    if not gmeshes:
        result["garments"][gname] = {"error": "服装里没有网格", "path": gpath}
        continue
    for o in added:  # 让库对象进入当前 view layer，否则不进 depsgraph
        if o.name not in bpy.context.scene.collection.objects:
            try:
                bpy.context.scene.collection.objects.link(o)
            except RuntimeError:
                pass

    body = next(o for o in bpy.data.objects
                if o.type == 'MESH' and o.name.startswith("Body_") and o.data.shape_keys)
    allobjs = [body] + gmeshes
    curves = {"path": gpath, "parts": [o.name for o in gmeshes], "n_verts": 0,
              "penetration_pct": [], "min_gap_mm": [], "mean_gap_mm": [],
              "body_max_disp_mm": [], "morph_names": {}}
    for o in gmeshes:
        curves["morph_names"][o.name] = ([k.name for k in o.data.shape_keys.key_blocks]
                                         if o.data.shape_keys else None)
    base_bv = None
    # 第一遍：把各档的求值结果快照下来（先全存，才能拿 k=0 当位移基准，与遍历顺序无关）
    snap = []
    for k in KS:
        set_k(allobjs, k)
        bpy.context.view_layer.update()
        bv, bp = evaluated(body)
        gvs = [evaluated(gm)[0] for gm in gmeshes]
        snap.append({"k": k, "bv": bv, "bp": bp, "gv": gvs})
        if k == 0.0:
            base_bv = list(bv)
    # 第二遍：算有符号距离 / 穿模率
    for s in snap:
        k, bv, bp, gvs = s["k"], s["bv"], s["bp"], s["gv"]
        tree = BVHTree.FromPolygons([tuple(v) for v in bv], bp, all_triangles=False)
        n_pen = 0
        n_tot = 0
        gaps = []
        for gv in gvs:
            for p in gv:
                loc, n, idx, dist = tree.find_nearest(p, 1.0)
                if loc is None:
                    continue
                d = (p - loc).dot(n)
                gaps.append(d)
                n_tot += 1
                if d < -tol:
                    n_pen += 1
        dmax = 0.0
        if base_bv is not None and len(base_bv) == len(bv):
            dmax = max((bv[i] - base_bv[i]).length for i in range(len(bv)))
        curves["penetration_pct"].append(round(100.0 * n_pen / max(n_tot, 1), 3))
        curves["min_gap_mm"].append(round(1000.0 * min(gaps), 2) if gaps else 0.0)
        curves["mean_gap_mm"].append(round(1000.0 * sum(gaps) / max(len(gaps), 1), 2))
        curves["body_max_disp_mm"].append(round(1000.0 * dmax, 2))
        curves["n_verts"] = n_tot
        print("  k=%+.2f pen=%.2f%% min=%.1fmm bodydisp=%.1fmm"
              % (k, curves["penetration_pct"][-1], curves["min_gap_mm"][-1],
                 curves["body_max_disp_mm"][-1]))

    first = None
    for i, k in enumerate(KS):
        if curves["penetration_pct"][i] > 0.5:
            first = k
            break
    curves["first_penetration_k"] = first
    result["garments"][gname] = curves

    for o in added:  # 清理，避免下一件服装串味
        bpy.data.objects.remove(o, do_unlink=True)

os.makedirs(os.path.dirname(out_json), exist_ok=True)
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
print("PEN_JSON " + json.dumps(
    {"out": out_json,
     "garments": {k: {"pen": v.get("penetration_pct"), "disp": v.get("body_max_disp_mm")}
                  for k, v in result["garments"].items()}}, ensure_ascii=False))