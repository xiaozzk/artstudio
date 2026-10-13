"""tools/3d/garment/pixel_metric.py —— **权威判据**：像素法裸露率（无网格拓扑假设）

为什么它取代顶点级"穿模率"（Lead FINDINGS §11.1，SPEC F16）
----------------------------------------------------------
顶点级判据有两处致命问题：
  ① 标准体不是闭合曲面（26 连通域 / 48 边界环）且**相对质心非星形**（F15b；
     面绕向**是一致的**，0/18250 违例 —— 早先“绕向不一致”是误报，已订正）→ 射线奇偶在
     **近表面 1 cm 带**（正是穿模发生处）准确率从 99.8% 掉到 95.8%
  ② 按顶点密度加权：`*_Feet` 一件 10174 顶点（占 43%）却基本没问题 → 把总比例拉低
     **顶点占比 ≠ 视觉占比**

像素法不依赖网格拓扑、不按顶点密度加权，直接回答"**眼睛看到多少裸露身体**"。

Lead 踩过的 3 个坑（本模块全部规避，见 §11.6）
--------------------------------------------
1. **AgX 色调映射把纯红压成鲑鱼粉**（r/g≈1.5）→ 基于"红占优"的判据全废
   → 本模块**显式设 `scene.view_settings.view_transform = 'Standard'`**
2. **背景不能用颜色阈值判**（sRGB 编码会把 0.09 线性变成 ~0.33）
   → 本模块用 `film_transparent = True`，**alpha 通道即剪影**
3. **红色判据太松会把棕色皮革/皮肤一起收进来**（虚高一倍）
   → 本模块不用贴图渲染，而是**把双方都换成纯自发光材质**（红 / 绿），
     判据收紧到 `r − max(g,b) > 0.5`，从机制上消除该失效模式

两种口径都报
----------
  P_full     红 / (红+绿)  —— 身体**全部**（含头/手等本来就该裸露的部分）
             ⇒ 与 Lead 的 63.34% / 74.21% 同口径
  P_covered  先用"到布料最近距离 < cutoff"筛掉身体上**衣服本来就不覆盖**的部分，
             再算红 / (红+绿)
             ⇒ 隔离出"**衣服盖着却被身体顶穿**"这一件事，不受头/手干扰
"""
import math
import os

import bpy
import numpy as np
from mathutils import Vector

import render_util as RU

VIEWS = (("front", (0.0, -3.6, 0.95)), ("back", (0.0, 3.6, 0.95)),
         ("left", (-3.6, 0.0, 0.95)), ("right", (3.6, 0.0, 0.95)))
TARGET = (0.0, 0.0, 0.95)

# 收紧的纯色判据（自发光材质 + Standard 变换下，纯红就是 (1,0,0)）
RED_STRICT = 0.5
RED_LOOSE = 0.10


def setup(res=520, samples=16):
    sc = RU.setup_scene(res_x=res, res_y=int(res * 1.45), samples=samples)
    # ★ 坑 1：必须 Standard，否则 AgX 会把纯红压成鲑鱼粉
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    sc.render.film_transparent = True      # ★ 坑 2：alpha 通道即剪影
    return sc


def tri_pts(obj):
    return [v.co.copy() for v in obj.data.vertices]


def make_proxy(name, pts, tris):
    me = bpy.data.meshes.new(name)
    me.from_pydata([p[:] for p in pts], [], [list(t) for t in tris])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def subset(pts, tris, keep_v):
    used = sorted({i for t in tris if all(i in keep_v for i in t) for i in t})
    remap = {g: l for l, g in enumerate(used)}
    return ([pts[i] for i in used],
            [tuple(remap[i] for i in t) for t in tris if all(i in keep_v for i in t)])


def combined_geo(objs, depsgraph_eval):
    """把多个对象的求值几何合并成 (pts, tris)。depsgraph_eval(obj) -> (pts, tris)"""
    allp, allt = [], []
    for o in objs:
        pts, tris = depsgraph_eval(o)
        b = len(allp)
        allp += pts
        allt += [tuple(i + b for i in t) for t in tris]
    return allp, allt


def covered_mask(red_pts, red_tris, green_pts, green_tris, cutoff):
    """红的顶点里，到绿表面最近距离 < cutoff 的（= 被绿遮住/贴近绿的部分）。"""
    import common as C
    gbvh = C.bvh_from_pts_tris(green_pts, green_tris)
    keep = set()
    for i, p in enumerate(red_pts):
        loc, nor, fi, dist = gbvh.find_nearest(p)
        if loc is not None and dist < cutoff:
            keep.add(i)
    return keep


def _assign(objs, mat):
    """换材质并返回快照（用于还原）。"""
    snaps = []
    for o in objs:
        snaps.append((o, RU.swap_materials(o, mat)))
    return snaps


def _restore(snaps):
    for o, s in snaps:
        RU.restore_materials(o, s)


def measure_views(red_objs, green_objs, eval_fn, out_dir, tag, res=520,
                  cutoff=0.03, both_ways=False, hide_objs=None):
    """渲染 4 视角，返回 {P_full, P_covered, views...}

    ⚠ 本函数**自己负责**把双方换成纯自发光材质（红 / 绿）——
      第一版忘了这一步，网格用原材质在无灯环境里渲成**纯黑**：
      剪影 alpha 正常、红像素恒为 0 → 量出假的 "P_full = 0.00%"。
      现加了 sanity 断言：画面里必须有一半以上像素落在两种纯色里，否则报错。
    """
    setup(res)
    red_mat = RU.emission_material(f"__PM_RED_{tag}", (1.0, 0.0, 0.0))
    green_mat = RU.emission_material(f"__PM_GREEN_{tag}", (0.0, 1.0, 0.0))
    rs = _assign(red_objs, red_mat)
    gs = _assign(green_objs, green_mat)
    # ⚠ 源网格必须隐藏：否则它们与 proxy **共位重叠**渲染，
    #   画面里混进原材质的黑像素 → 纯色占比暴跌（历史上造成过假的 0.00%）
    hid = []
    for o in (hide_objs or []):
        hid.append((o, o.hide_render))
        o.hide_render = True
    bpy.context.view_layer.update()
    red_pts, red_tris = combined_geo(red_objs, eval_fn)
    green_pts, green_tris = combined_geo(green_objs, eval_fn)
    res_out = {"red_verts": len(red_pts), "green_verts": len(green_pts),
               "criterion": {"strict": RED_STRICT, "loose": RED_LOOSE,
                             "note": "纯自发光材质 + Standard 视图变换 + alpha 剪影"},
               "views": {}}
    variants = [("full", red_pts, red_tris)]
    if both_ways:
        keep = covered_mask(red_pts, red_tris, green_pts, green_tris, cutoff)
        sp, st = subset(red_pts, red_tris, keep)
        if st:
            variants.append(("covered", sp, st))
            res_out["covered_red_verts"] = len(sp)
            res_out["cutoff_cm"] = round(cutoff * 100, 2)
    for vname, loc in VIEWS:
        cam = RU.add_camera(f"__cam_{tag}_{vname}", loc, TARGET, lens=45.0)
        p = os.path.join(out_dir, f"{tag}_{vname}.png")
        RU.render_to(p, cam)
        arr = RU.read_pixels(p)
        alpha = arr[:, :, 3] > 0.5
        sil = int(alpha.sum())
        # 剪影内、按色相分类
        red_s = arr[:, :, 0] - np.maximum(arr[:, :, 1], arr[:, :, 2])
        is_red_strict = (red_s > RED_STRICT) & alpha
        is_red_loose = (red_s > RED_LOOSE) & alpha
        is_green = ((arr[:, :, 1] - np.maximum(arr[:, :, 0], arr[:, :, 2])) > RED_STRICT) & alpha
        row = {"png": os.path.relpath(p, os.path.dirname(out_dir)) if out_dir else p,
               "silhouette_px": sil,
               "red_strict_px": int(is_red_strict.sum()),
               "red_loose_px": int(is_red_loose.sum()),
               "green_px": int(is_green.sum())}
        row["uncovered_strict"] = round(row["red_strict_px"] / sil, 6) if sil else 0.0
        row["uncovered_loose"] = round(row["red_loose_px"] / sil, 6) if sil else 0.0
        res_out["views"][vname] = row
        bpy.data.objects.remove(cam, do_unlink=True)
    vals = [v["uncovered_strict"] for v in res_out["views"].values()]
    res_out["P_full"] = round(sum(vals) / len(vals), 6) if vals else 0.0
    res_out["P_full_max"] = round(max(vals), 6) if vals else 0.0
    res_out["P_full_loose"] = round(sum(v["uncovered_loose"] for v in res_out["views"].values())
                                    / len(vals), 6) if vals else 0.0
    # ★ sanity：画面必须由两种纯色主导，否则说明材质没换上（历史上造成过假的 0.00%）
    ratios = []
    for v in res_out["views"].values():
        if v["silhouette_px"]:
            ratios.append((v["red_strict_px"] + v["green_px"]) / v["silhouette_px"])
    res_out["classified_frac"] = round(min(ratios), 4) if ratios else 0.0
    res_out["sanity_ok"] = bool(ratios) and min(ratios) >= 0.5
    if not res_out["sanity_ok"]:
        raise AssertionError(
            f"[pixel_metric] sanity 失败：{tag} 画面里纯色占比仅 "
            f"{res_out['classified_frac']:.3f}（<0.5）——材质很可能没换上，数字不可用")
    _restore(rs)
    _restore(gs)
    for o, h in hid:
        o.hide_render = h
    bpy.context.view_layer.update()
    return res_out