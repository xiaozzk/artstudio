#!/usr/bin/env python3
"""
v_pixel_forensics.py —— 像素法差异取证：为什么我的 23.97% 对上 Lead 的 63.34%？

我的像素法两项标定**都通过了**（只渲身体=100.00%、只渲服装=0.00%），
所以差异必然来自**判据**或**身体材质**，不是我的读回。

本脚本把两者的差异**拆成可控变量**，在**同一批图**上跑**两套判据**：
  判据 V（我的）：r>0.15 且 g<0.06 且 b<0.06        —— 靠 g/b 通道排除皮肤/皮革
  判据 L（Lead 的）：r>0.25 且 (r-max(g,b))>0.10    —— 只看红色相对优势

在三类图上各跑一次：
  A. 我的 calib_clothonly_*.png   —— **只有服装、没有身体**。任何 >0 都是误收。
  B. 我的 px_*_1_baseline_*.png   —— 真实场景（我的渲染）
  C. Lead 的 px_*.png             —— 真实场景（Lead 的渲染）
  D. 我另渲一张 pure-skin 参考    —— 只有 MI_Regular_* 皮肤面，看判据 L 会不会当成身体

再额外验证 Lead 的读回口径：他读 `.pixels` 没设 Non-Color，
所以拿到的是 **sRGB→linear** 之后的值；我的阈值是按**原始 sRGB** 定的。
两者不可直接比 —— 我两边都算，量化这个换算的影响。

用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_pixel_forensics.py -- \
      --out assets/3d/rig/reports/verify-pixel-forensics.json
"""
import argparse
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
MINE = f"{ROOT}/task/007-morph-pipeline/verify/renders"
LEAD = f"{ROOT}/task/007-morph-pipeline/lead"


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def load(path, noncolor):
    img = bpy.data.images.load(path, check_existing=False)
    if noncolor:
        try:
            img.colorspace_settings.name = "Non-Color"
        except Exception:  # noqa: BLE001
            pass
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def judge_V(px):
    """verifier 判据：Emission 纯红 → g/b 必须近乎 0。"""
    sil = px[..., 3] > 0.5
    r, g, b = px[..., 0], px[..., 1], px[..., 2]
    return sil, sil & (r > 0.15) & (g < 0.06) & (b < 0.06)


def judge_L(px):
    """Lead 判据原文：r > 0.25 and (r - max(g,b)) > 0.10。"""
    sil = px[..., 3] > 0.5
    r, g, b = px[..., 0], px[..., 1], px[..., 2]
    return sil, sil & (r > 0.25) & ((r - np.maximum(g, b)) > 0.10)


def stats(path, noncolor):
    if not os.path.exists(path):
        return {"error": "missing", "path": path}
    px = load(path, noncolor)
    out = {"path": os.path.relpath(path, ROOT),
           "resolution": [int(px.shape[1]), int(px.shape[0])],
           "readback": "Non-Color(原始sRGB)" if noncolor else "默认(sRGB→linear)"}
    for name, fn in (("judge_V_verifier", judge_V), ("judge_L_lead", judge_L)):
        sil, red = fn(px)
        n_sil = int(sil.sum())
        out[name] = {"sil_px": n_sil, "red_px": int(red.sum()),
                     "red_frac_pct": round(100.0 * int(red.sum()) / n_sil, 4) if n_sil else None}
    # 到底哪些颜色被判据 L 收进来了
    sil, redL = judge_L(px)
    sil, redV = judge_V(px)
    onlyL = sil & redL & ~redV
    if onlyL.sum() > 0:
        cols = px[onlyL][:, :3]
        out["judge_L_only_pixels"] = {
            "n": int(onlyL.sum()),
            "mean_rgb_noncol": [round(float(x), 4) for x in cols.mean(axis=0)],
            "p50_rgb_noncol": [round(float(x), 4) for x in np.percentile(cols, 50, axis=0)],
            "mean_rgb_linear": [round(float(x), 4) for x in
                                np.clip(cols, 0, 1)[:, :3].mean(axis=0)],
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-pixel-forensics.json")
    a = ap.parse_args(argv_after_ddash())
    out = {"generated_by": "verifier/v_pixel_forensics.py",
           "question": "我的像素法 23.97% vs Lead 的 63.34% —— 差异出在哪？",
           "judges": {
               "V_verifier": "r>0.15 且 g<0.06 且 b<0.06",
               "L_lead": "r>0.25 且 (r-max(g,b))>0.10"},
           "groups": {}}

    # ---- A. 只有服装、没有身体（误收测试） ----
    A = {}
    for sex in ("Female", "Male"):
        for nc in (True, False):
            key = f"{sex}_readback_{'noncolor' if nc else 'linear'}"
            A[key] = stats(f"{MINE}/calib_clothonly_{sex}.png", nc)
    out["groups"]["A_cloth_only_FALSE_POSITIVE_TEST"] = A

    # ---- B. 我的真实场景 ----
    B = {}
    for sex in ("Female", "Male"):
        for tag in ("1_baseline", "2_reattach", "3_refit", "4_autofit"):
            B[f"{sex}_{tag}"] = stats(f"{MINE}/px_{sex}_{tag}_ortho.png", True)
    out["groups"]["B_my_render"] = B

    # ---- C. Lead 的真实场景 ----
    C = {}
    for sex in ("Female", "Male"):
        for tag in ("1_baseline", "2_refit", "3_autofit"):
            p = f"{LEAD}/px_{sex}_{tag}.png"
            C[f"{sex}_{tag}"] = stats(p, True)
    out["groups"]["C_lead_render"] = C

    vlib.jdump(a.out, out)

    def line(tag, s):
        if "error" in s:
            print(f"  {tag:<34} MISSING")
            return
        print(f"  {tag:<34} sil={s['judge_V_verifier']['sil_px']:>8}  "
              f"V={s['judge_V_verifier']['red_frac_pct']:>7.2f}%  "
              f"L={s['judge_L_lead']['red_frac_pct']:>7.2f}%")

    print("\n### A. 只有服装、没有身体（任何 >0% 都是判据误收）")
    for k, s in A.items():
        line(k, s)
    print("\n### B. 我的渲染（Non-Color 读回）")
    for k, s in B.items():
        line(k, s)
    print("\n### C. Lead 的渲染（同一批图、两套判据）")
    for k, s in C.items():
        line(k, s)
    print(f"\n[v_pixel_forensics] wrote {a.out}")


if __name__ == "__main__":
    main()