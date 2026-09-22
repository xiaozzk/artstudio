#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spine_part_swap.py — Spine 部件的"定位 / 换皮验证"两件事（纯本地，不花钱）。

子命令
    locate  在复原预览图上定位某个插槽（部件）的**可见区域** → 精确 mask + 尺寸 + 附件四边形坐标
    verify  把新部件当附件换进去重渲预览 → 量化"改了哪、有没有波及别处"（远处应为 0px）

为什么不用模板匹配：本仓库的 `tools/repair_spine/pipelines.py` 自带 Renderer，
能按同一套 ss/pad/缩放规则**逐像素复现** 复原预览图。于是：
    * 定位 = 把目标插槽的贴图换成"哨兵色（保留 alpha）"再渲一次，两次渲染的差异像素
      **就是该部件的可见区域**（被其它部件压住的像素天然排除，正是要替换的范围）
    * 坐标 = 世界坐标 → 预览像素：px = (wx - minx + pad) * f，py = (maxy - wy + pad) * f
      附件region的 uv (0,0)→左上，四边形在预览里的位置就是"贴回附件画布"的映射
    * 验证 = 换图重渲，和原预览比差异：远处 0px 才说明尺寸/挂点对

用法
    python tools/spine_part_swap.py locate --json assets/武僧/monk.json \\
        --images assets/武僧/images_original --preview assets/武僧/复原预览图_1.png \\
        --skin 1 --slot weapon_1 --out-dir tmp/swap
    python tools/spine_part_swap.py verify --json assets/武僧/monk.json \\
        --images assets/武僧/images_original --preview assets/武僧/复原预览图_1.png \\
        --skin 1 --part weapon_11=tmp/out/weapon_11_new.png --out-dir tmp/swap
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from collections import OrderedDict

import numpy as np
from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PIPE = os.path.join(BASE, "tools", "repair_spine")
if _PIPE not in sys.path:
    sys.path.insert(0, _PIPE)
import pipelines as P  # noqa: E402

BG = (38, 40, 48, 255)
SS, PAD, MAX_LONG = 3, 20, 2600


class Scene:
    """一次皮肤渲染的几何 + 到预览像素的映射（与 render_previews 同规则）。"""

    def __init__(self, json_path, images_dir, skin=None, ss=SS, pad=PAD, max_long=MAX_LONG):
        self.json_path, self.images_dir = json_path, images_dir
        self.rr = P.Renderer(json_path, images_dir, ss=ss, pad=pad, skin=skin)
        self.geoms = self.rr._collect()
        xs = [p[0] for _, _, pts, _, _ in self.geoms for p in pts]
        ys = [p[1] for _, _, pts, _, _ in self.geoms for p in pts]
        if not xs:
            raise SystemExit("这个皮肤没有任何可渲染附件")
        self.minx, self.maxx, self.miny, self.maxy = min(xs), max(xs), min(ys), max(ys)
        self.W = int(math.ceil(self.maxx - self.minx)) + pad * 2
        self.H = int(math.ceil(self.maxy - self.miny)) + pad * 2
        self.pad, self.ss = pad, ss
        self.f = 2.0 if max(self.W, self.H) * 2.0 <= max_long else max(1.0, max_long / float(max(self.W, self.H)))

    def to_px(self, p):
        return ((p[0] - self.minx + self.pad) * self.f, (self.maxy - p[1] + self.pad) * self.f)

    def preview_rgb(self):
        ren, _ = self.rr.render()
        if self.f != 1.0:
            ren = ren.resize((max(1, int(ren.width * self.f)), max(1, int(ren.height * self.f))), Image.LANCZOS)
        canvas = Image.new("RGBA", ren.size, BG)
        canvas.alpha_composite(ren)
        return canvas.convert("RGB")

    def slots(self) -> OrderedDict:
        return OrderedDict((g[0]["name"], P.resolve_image_name(g[0]["attachment"], g[1])) for g in self.geoms)


def sentinel_images(images_dir, targets, out_dir, color=(255, 0, 255)):
    """复制一份 images 目录，把 targets（文件名带 .png）改成"保留 alpha、RGB 换哨兵色"。"""
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(images_dir):
        if not f.endswith(".png"):
            continue
        dst = os.path.join(out_dir, f)
        if os.path.exists(dst):
            continue
        if f in targets:
            im = Image.open(os.path.join(images_dir, f)).convert("RGBA")
            a = im.getchannel("A")
            im = Image.merge("RGBA", tuple(Image.new("L", im.size, c) for c in color) + (a,))
            im.save(dst)
        else:
            Image.open(os.path.join(images_dir, f)).convert("RGBA").save(dst)
    return out_dir


def clusters_of(mask: np.ndarray, min_px=100):
    try:
        from scipy import ndimage
        lbl, n = ndimage.label(mask)
        out = []
        for i in range(1, n + 1):
            ys, xs = np.nonzero(lbl == i)
            if len(ys) >= min_px:
                out.append({"px": int(len(ys)), "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]})
        out.sort(key=lambda c: -c["px"])
        return out
    except ImportError:
        ys, xs = np.nonzero(mask)
        if len(ys) == 0:
            return []
        return [{"px": int(len(ys)), "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]}]


def cmd_locate(a) -> int:
    os.makedirs(a.out_dir, exist_ok=True)
    ref = Image.open(a.preview).convert("RGB")
    sc = Scene(a.json, a.images_dir, a.skin)
    rep = sc.preview_rgb()
    if rep.size == ref.size:
        d = np.abs(np.asarray(rep, np.int16) - np.asarray(ref, np.int16))
        print(f"复现预览：尺寸一致 {rep.size}，RGB 最大差 {d.max()} 平均差 {d.mean():.3f}"
              f"{'（几何可信）' if d.mean() < 2 else '（**注意：与交付预览不一致，坐标可能偏**）'}")
    else:
        print(f"[warn] 复现尺寸 {rep.size} ≠ 交付预览 {ref.size}，坐标映射不可信")

    names = sc.slots()
    if a.slot not in names:
        raise SystemExit(f"插槽 {a.slot} 不在该皮肤里；可用：{list(names)}")
    target_img = names[a.slot] + ".png"
    print(f"插槽 {a.slot} → 贴图 {target_img}")

    sent = sentinel_images(a.images_dir, {target_img}, os.path.join(a.out_dir, "_sentinel"))
    alt = Scene(a.json, sent, a.skin).preview_rgb()
    diff = np.abs(np.asarray(rep, np.int16) - np.asarray(alt, np.int16)).max(axis=2)
    mask = (diff > 8).astype(np.uint8) * 255
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    bw, bh = x1 - x0 + 1, y1 - y0 + 1

    part_img = os.path.join(a.images_dir, target_img)
    part = Image.open(part_img).convert("RGBA")
    pa = np.asarray(part.getchannel("A"))
    pys, pxs = np.nonzero(pa)
    pw, ph = (int(pxs.max() - pxs.min() + 1), int(pys.max() - pys.min() + 1)) if len(pxs) else part.size

    quads = {}
    for slot, att, pts, uvl, _tri in [g for g in sc.geoms if g[0]["name"] == a.slot]:
        quads[P.resolve_image_name(slot["attachment"], att)] = [list(sc.to_px(p)) for p in pts]

    print(f"可见区域 {int((mask > 0).sum())} px（占画面 {mask.mean() / 255 * 100:.2f}%），"
          f"包围盒 {bw}x{bh} @ x[{x0},{x1}] y[{y0},{y1}]")
    print(f"原附件 {part.size[0]}x{part.size[1]}，alpha 实际占用 {pw}x{ph}；预览/附件 线性缩放 ≈ {sc.f:.3f}")
    for k, v in quads.items():
        print(f"附件四边形 {k}（预览像素）: " + "  ".join(f"({x:.1f},{y:.1f})" for x, y in v))

    mask_p = os.path.join(a.out_dir, f"mask_{a.slot}_visible.png")
    Image.fromarray(mask, "L").save(mask_p)
    ov = ref.copy()
    ov.paste(Image.new("RGB", ref.size, (255, 40, 40)), (0, 0), Image.fromarray((mask // 2), "L"))
    dr = ImageDraw.Draw(ov)
    for v in quads.values():
        dr.polygon([tuple(p) for p in v], outline=(0, 255, 120))
    ov_p = os.path.join(a.out_dir, f"debug_{a.slot}_overlay.png")
    ov.save(ov_p)

    geo = {"json": a.json, "skin": a.skin, "slot": a.slot, "image": target_img,
           "preview": a.preview, "preview_size": list(ref.size), "f": sc.f, "ss": sc.ss, "pad": sc.pad,
           "bbox": [x0, y0, x1, y1], "bbox_size": [bw, bh], "visible_px": int((mask > 0).sum()),
           "part_canvas": list(part.size), "part_alpha_xy": [pw, ph],
           "ratio_preview_over_part": round(sc.f, 4), "quads": quads}
    geo_p = os.path.join(a.out_dir, f"geometry_{a.slot}.json")
    json.dump(geo, open(geo_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"mask → {mask_p}\n覆盖校验图 → {ov_p}\n几何 → {geo_p}")
    return 0


def cmd_verify(a) -> int:
    os.makedirs(a.out_dir, exist_ok=True)
    overrides = {}
    for spec in a.part or []:
        if "=" not in spec:
            raise SystemExit(f"--part 要写成 NAME=PATH，收到 {spec!r}")
        k, v = spec.split("=", 1)
        overrides[k.strip()] = v.strip()

    tmp_images = os.path.join(a.out_dir, "_swapped_images")
    os.makedirs(tmp_images, exist_ok=True)
    for f in os.listdir(a.images_dir):
        if f.endswith(".png"):
            shutil.copy(os.path.join(a.images_dir, f), os.path.join(tmp_images, f))
    for name, path in overrides.items():
        shutil.copy(path, os.path.join(tmp_images, name if name.endswith(".png") else name + ".png"))

    ref = Image.open(a.preview).convert("RGB")
    before = Scene(a.json, a.images_dir, a.skin).preview_rgb()
    after = Scene(a.json, tmp_images, a.skin).preview_rgb()
    if before.size != after.size:
        raise SystemExit("两次渲染尺寸不一致，无法比较")
    d = np.abs(np.asarray(before, np.int16) - np.asarray(after, np.int16)).max(axis=2)
    changed = d >= a.thresh
    cs = clusters_of(changed, min_px=a.min_cluster)
    print(f"替换 {list(overrides)} 后：改动 {int(changed.sum())} px（阈值 {a.thresh}）")
    if cs:
        main = cs[0]
        print(f"主簇 {main['px']} px @ bbox {main['bbox']}；共 {len(cs)} 个 ≥{a.min_cluster}px 的簇")
        for c in cs[1:6]:
            print(f"   次簇 {c['px']} px @ bbox {c['bbox']}")
    h, w = changed.shape
    if cs:
        x0, y0, x1, y1 = cs[0]["bbox"]
        far = changed.copy()
        far[max(0, y0 - a.margin):min(h, y1 + a.margin), max(0, x0 - a.margin):min(w, x1 + a.margin)] = False
        print(f"主簇外（含 {a.margin}px 余量）仍有 {int(far.sum())} px 改动"
              f"{'  ← 有问题：装配尺寸/挂点可能不对' if far.sum() > 0 else '  ✅ 只在目标部件附近变化'}")

    cmp_p = os.path.join(a.out_dir, "swap_render_compare.png")
    out = Image.new("RGB", (before.width * 2 + 10, before.height), (24, 24, 28))
    out.paste(before, (0, 0))
    out.paste(after, (before.width + 10, 0))
    out.save(cmp_p)
    json.dump({"parts": overrides, "changed_px": int(changed.sum()), "clusters": cs,
               "compare": cmp_p, "thresh": a.thresh},
              open(os.path.join(a.out_dir, "verify.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"对比图 → {cmp_p}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Spine 部件定位 / 换皮验证（本地免费）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    lo = sub.add_parser("locate", help="定位插槽在预览图里的可见区域 → mask + 尺寸 + 四边形")
    lo.add_argument("--json", required=True)
    lo.add_argument("--images", dest="images_dir", required=True)
    lo.add_argument("--preview", required=True)
    lo.add_argument("--skin", default=None)
    lo.add_argument("--slot", required=True)
    lo.add_argument("--out-dir", required=True)
    lo.set_defaults(func=cmd_locate)

    ve = sub.add_parser("verify", help="换图重渲 → 量化改动范围（远处应为 0px）")
    ve.add_argument("--json", required=True)
    ve.add_argument("--images", dest="images_dir", required=True)
    ve.add_argument("--preview", required=True)
    ve.add_argument("--skin", default=None)
    ve.add_argument("--part", action="append", default=[], help="NAME=PATH，可重复")
    ve.add_argument("--out-dir", required=True)
    ve.add_argument("--thresh", type=int, default=30, help="判定「改动了」的单通道差，默认 30")
    ve.add_argument("--margin", type=int, default=40, help="主簇外扩余量，默认 40px")
    ve.add_argument("--min-cluster", type=int, default=100, help="报告的最小簇面积，默认 100px")
    ve.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
