#!/usr/bin/env python3
"""
v_t3_integration.py —— verifier 独立定位 T3 预览里"腿上橙色斑块"的来源。

**怀疑**：T2 已于 18:02 把 `assets/3d/rig/garments/*.blend` **换成了 B2 产物**
（= 自包含角色：12 件网格 / 自带 rig / 自带皮肤 / 自带头，共 27,920 顶点），
但 T3 的 `tools/3d/godot/preview/cfg.gd` **仍然同时加载**
`bodies/Body_{sex}_Standard.blend`（完整 Superhero 身体，7376 顶点）。
→ 场景里 = B2 完整角色 **＋** 一具独立 Superhero 身体 → 身体顶穿 B2 的服装。

本脚本用**同一套材质/灯光/相机**渲染三种装配，逐像素比较：
  P1 只装 B2 角色（`garments/Female_Ranger.blend`）
  P2 只装男女标准体（`bodies/Body_Female_Standard.blend`）
  P3 **B2 角色 + 标准体**（= 我推断的 T3 现状）
  P4 B1 角色（`garments/B1_superhero_standard/Female_Ranger.blend`）+ 标准体
     （= B1 时代的设计装配，作为对照）

判据："腿上橙色斑块" = 腿部区域的**皮肤色像素**。用像素分类计数，不靠肉眼。

只读资产；产物写 verifier 的写入范围。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_t3_integration.py -- \
      --out assets/3d/rig/reports/verify-t3-integration.json
"""
import argparse
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402
from v_pixelmetric import (make_camera, read_png_raw, scene_bounds, setup_render)  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
RIG = f"{ROOT}/assets/3d/rig"
SHOTDIR = f"{ROOT}/task/007-morph-pipeline/verify/renders"
SEX = "Female"


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def load_into(path, suffix=""):
    """把 path 里的对象 append 进当前场景（不替换场景）。"""
    with bpy.data.libraries.load(path) as (src, dst):
        dst.objects = list(src.objects)
    added = []
    for o in dst.objects:
        if o is None:
            continue
        if o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o, do_unlink=True)
            continue
        try:
            bpy.context.scene.collection.objects.link(o)
        except RuntimeError:
            pass
        added.append(o.name)
    return added


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def set_tier(meshes, tier):
    for o in meshes:
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks:
                kb.value = 1.0 if kb.name == tier else 0.0
    bpy.context.view_layer.update()


def leg_skin_stats(rgba, bounds):
    """腿部区域的"皮肤色"像素：暖色且明显亮于同区域的绿色布料。

    皮肤色判据（原始 sRGB，0..1）：r>0.35 且 r>g>b 且 (r-b)>0.12 且 g>0.15。
    绿色布料 (r<g) 天然被排除；棕色皮革 g/b 比更接近、且更暗 → 用亮度下界剔除。
    误差来源：靴子的浅棕 (MI_Ranger 皮革) 可能落入 → 所以**同一装配内部做相对比较**，
    不做绝对断言。
    """
    h, w = rgba.shape[:2]
    r, g, b, a = rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3]
    sil = a > 0.5
    skin = sil & (r > 0.35) & (r > g) & (g > b) & ((r - b) > 0.12) & (g > 0.15)
    return {"n_sil": int(sil.sum()), "n_skin": int(skin.sum()),
            "skin_pct": round(100.0 * float(skin.sum()) / max(int(sil.sum()), 1), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-t3-integration.json")
    ap.add_argument("--res", nargs=2, type=int, default=[760, 1180])
    a = ap.parse_args(argv_after_ddash())
    os.makedirs(SHOTDIR, exist_ok=True)
    res = tuple(a.res)
    out = {"generated_by": "verifier/v_t3_integration.py",
           "question": "T3 预览腿上橙色斑块 —— 是 B2 资产的问题，还是 T3 多装了一具身体？",
           "assemblies": {}}
    B2 = f"{RIG}/garments/{SEX}_Ranger.blend"
    B1 = f"{RIG}/garments/B1_superhero_standard/{SEX}_Ranger.blend"
    BODY = f"{RIG}/bodies/Body_{SEX}_Standard.blend"

    plans = [
        ("P1_b2_character_only", [(B2, "b2")]),
        ("P2_standard_body_only", [(BODY, "body")]),
        ("P3_b2_plus_standard_body", [(B2, "b2"), (BODY, "body")]),
        ("P4_b1_garment_plus_standard_body", [(B1, "b1"), (BODY, "body")]),
    ]
    for name, parts in plans:
        fresh_scene()
        added = []
        for p, tag in parts:
            added += load_into(p)
        meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        bpy.context.view_layer.update()
        setup_render(res)
        row = {"parts": [p for p, _ in parts],
               "objects": sorted(o.name for o in meshes),
               "n_objects": len(meshes),
               "total_verts": int(sum(len(o.data.vertices) for o in meshes)),
               "tiers": {}}
        for tier in (None, "BS_Thin", "BS_Heavy"):
            set_tier(meshes, tier)
            bd = scene_bounds(meshes, meshes[0])
            make_camera(bd, res, "ortho")
            p = f"{SHOTDIR}/t3int_{name}_{tier or 'Basis'}.png"
            bpy.context.scene.render.filepath = p
            bpy.ops.render.render(write_still=True)
            rgba = read_png_raw(p)
            st = leg_skin_stats(rgba, bd)
            st["png"] = os.path.basename(p)
            row["tiers"][tier or "Basis"] = st
        prev = row["tiers"]["Basis"]["skin_pct"]
        row["deltas"] = {k: round(v["skin_pct"] - prev, 4)
                         for k, v in row["tiers"].items()}
        out["assemblies"][name] = row
        print(f"  {name:<34} objs={row['n_objects']:<3} verts={row['total_verts']:<6} "
              + "  ".join(f"{k}={v['skin_pct']:.2f}%" for k, v in row["tiers"].items()))

    # 逐像素比较 P1 vs P3，量化"多装一具身体"带来的差异
    d = {}
    for tier in ("Basis", "BS_Thin", "BS_Heavy"):
        p1 = read_png_raw(f"{SHOTDIR}/t3int_P1_b2_character_only_{tier}.png")
        p3 = read_png_raw(f"{SHOTDIR}/t3int_P3_b2_plus_standard_body_{tier}.png")
        h = min(p1.shape[0], p3.shape[0])
        w = min(p1.shape[1], p3.shape[1])
        a1, a3 = p1[:h, :w], p3[:h, :w]
        sil3 = a3[..., 3] > 0.5
        diff = np.abs(a1[..., :3] - a3[..., :3]).max(axis=2)
        changed = sil3 & (diff > 0.08)
        d[tier] = {"n_sil_P3": int(sil3.sum()), "n_pixels_changed": int(changed.sum()),
                   "changed_pct_of_P3_silhouette": round(
                       100.0 * float(changed.sum()) / max(int(sil3.sum()), 1), 4)}
    out["P1_vs_P3_pixel_diff"] = d
    # 免分类器版：**大腿带**（画面高度 40%–62%）内 P1→P3 变了的像素 —— 直接量"斑块"
    band = {}
    for tier in ("Basis", "BS_Thin", "BS_Heavy"):
        p1 = read_png_raw(f"{SHOTDIR}/t3int_P1_b2_character_only_{tier}.png")
        p3 = read_png_raw(f"{SHOTDIR}/t3int_P3_b2_plus_standard_body_{tier}.png")
        h = min(p1.shape[0], p3.shape[0]); w = min(p1.shape[1], p3.shape[1])
        y0, y1 = int(h * 0.62), int(h * 0.40)      # 图像行序自下而上
        a1, a3 = p1[y1:y0, :w], p3[y1:y0, :w]
        sil3 = a3[..., 3] > 0.5
        diff = np.abs(a1[..., :3] - a3[..., :3]).max(axis=2)
        ch = sil3 & (diff > 0.08)
        band[tier] = {"n_sil_in_band_P3": int(sil3.sum()),
                      "n_changed": int(ch.sum()),
                      "changed_pct_in_band": round(
                          100.0 * float(ch.sum()) / max(int(sil3.sum()), 1), 4)}
    out["thigh_band_P1_vs_P3"] = band
    print("  大腿带 P1/P3 差异:", json.dumps(band, ensure_ascii=False))
    vlib.jdump(a.out, out)
    print("  P1 vs P3 像素差:", json.dumps(d, ensure_ascii=False))
    print(f"[v_t3_integration] wrote {a.out}")


if __name__ == "__main__":
    main()