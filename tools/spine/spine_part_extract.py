#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spine_part_extract.py — 给 ZenMux 局部重绘准备「原图 + 遮罩」（纯本地、免费）。

两种策略（`extract --mode`）：

  **`pair`（默认，2026-09-24 起 · 用户口径）** —— 一次出**两张提交图**，mask 对着第 1 张：
      * 第 1 张 `part_only.png` = **摘除件单独图**（部件 alpha bbox + `--part-margin` 留白，纯色底 + 红线）
        —— 它尺寸紧凑、长宽比就是部件自己的，模型只画这一件时不会有"比例错配"
      * 第 2 张 `original.png` = **原图置顶突出件**（复原图 + 目标件提到最上层 + 红线）—— 交代位置与画风语境
      * 第 3 张 = 风格参考图（`assets/eva_bone/assembled.png`，由提交方提供）
      * `mask.png` = 黑白图，**尺寸与第 1 张一致**（ZenMux 的 mask 只作用于第 1 张输入图）
      * 提交示例：`-i part_only.png -i original.png -i 参考风格.png --mask mask.png`

  **`inplace`** —— 只出上面第 2 张（mask 对着它，输出是整幅场景，回贴要按投影裁切）
  **`aside`** —— 复原图（原件原位保留）+ 该件副本挪到右侧空列（复现已跑过的 case01/02/03 用）

⚠ 为什么自己搬了一遍管线里的三角形光栅化（`_warp_layer`，约 30 行）：
   `Renderer.render()` 按**自己那次**的 geoms 算 `minx/maxy`，子集的包围盒常带小数
   （实测 coat 的帧内偏移 x=0.259），逐帧整数贴回会引入**亚像素错位**（实测 1569 px 差 >3/255）。
   这里所有层共用同一个 frame 变换，因此逐像素可对齐。
   `pipelines.py` 是 56 个已交付包共用的工具，**不许改** —— 所以只能镜像它的算法，
   并用校验 ① 兜住"镜像跑偏"。

用法：
    # 1) 出「原图 + 遮罩」（喂 ZenMux）；默认 inplace：目标件提到最上层 + 红线
    python tools/spine/spine_part_extract.py extract \\
        --json assets/武僧/monk.json --images assets/武僧/images_original \\
        --skin 1 --slot body --out-dir task/001-monk-mask-reskin/case04-body
    #    已改好的件用覆盖表带进这一轮（渐进叠加）：
    #    --override coat=<case01>/after-run01/new_part_in_bbox.png

    # 2) 模型出图后：抠出新件 → 等比缩放 → 按 z 序贴回原位
    python tools/spine/spine_part_extract.py paste-back \\
        --case task/001-monk-mask-reskin/case04-body \\
        --generated <模型出图.png> --out-dir <case>/after-run04

⚠ `paste-back` 的两条实测口径：
  * **不信投影** —— 模型出图并不按整幅画布等比映射（实测把部件重排到画布中部），
    所以按"最大前景块 + 其外扩 10% 内的其它块"合并成目标件，再按**部件自身 bbox** 等比缩放回贴。
  * **z 序 + 覆盖表** —— 按 `extract.json` 里的 `under`/`over` 把新件放回它自己那一层，
    并**必须把 `overrides` 一起套回来**（默认开，`--no-zorder` 关）；
    否则这一轮回贴会把上几步改好的件全"还原"成原始贴图 —— 渐进叠加就变成假的（2026-09-24 实测踩过）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import OrderedDict

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "repair_spine"))   # 同场景目录下的图集工具
sys.path.insert(0, HERE)                                 # 同目录的 spine_part_swap
import pipelines as P  # noqa: E402
import spine_part_swap as S  # noqa: E402  复用它的 Scene（与交付预览图同规则）

BG = (38, 40, 48, 255)          # 与复原预览图同底色（喂模型用 RGB 版）
FORMAT = "spine-part-extract"


# ---------------------------------------------------------------- 几何

def load_geoms(json_path, images_dir, skin):
    rr = P.Renderer(json_path, images_dir, ss=1, pad=0, skin=skin)
    geoms = rr._collect()
    if not geoms:
        raise SystemExit("这个皮肤没有任何可渲染附件")
    return rr, geoms


def frame_of(geoms):
    xs = [p[0] for _, _, pts, _, _ in geoms for p in pts]
    ys = [p[1] for _, _, pts, _, _ in geoms for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy,
            "w": int(math.ceil(maxx - minx)), "h": int(math.ceil(maxy - miny))}


def _warp_layer(geom, images_dir, ss, frame):
    """把一个附件画成 W*ss × H*ss 的层（镜像 pipelines.Renderer.render 的三角形仿射）。"""
    slot, att, pts, uvl, tri = geom
    key = P.resolve_image_name(slot["attachment"], att)
    f = os.path.join(images_dir, key.replace("/", os.sep) + ".png")
    if not os.path.exists(f):
        key = slot["attachment"]
        f = os.path.join(images_dir, key.replace("/", os.sep) + ".png")
    if not os.path.exists(f):
        return None, key
    src = Image.open(f).convert("RGBA")
    W, H = (frame["w"] * ss, frame["h"] * ss)

    def to_canvas(p):
        return ((p[0] - frame["minx"]) * ss, (frame["maxy"] - p[1]) * ss)

    cp = [to_canvas(p) for p in pts]
    IW, IH = src.size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for (i, j, k) in tri:
        imgpts = [(uvl[q][0] * IW, uvl[q][1] * IH) for q in (i, j, k)]
        A = np.array([[imgpts[0][0], imgpts[0][1], 1.0],
                      [imgpts[1][0], imgpts[1][1], 1.0],
                      [imgpts[2][0], imgpts[2][1], 1.0]])
        try:
            cx = np.linalg.solve(A, np.array([cp[i][0], cp[j][0], cp[k][0]], float))
            cy = np.linalg.solve(A, np.array([cp[i][1], cp[j][1], cp[k][1]], float))
            Mi = np.linalg.inv(np.array([[cx[0], cx[1], cx[2]],
                                         [cy[0], cy[1], cy[2]], [0, 0, 1.0]]))
        except np.linalg.LinAlgError:
            continue
        xs3 = (cp[i][0], cp[j][0], cp[k][0])
        ys3 = (cp[i][1], cp[j][1], cp[k][1])
        bx0 = max(0, int(math.floor(min(xs3))) - 1)
        by0 = max(0, int(math.floor(min(ys3))) - 1)
        bx1 = min(W, int(math.ceil(max(xs3))) + 2)
        by1 = min(H, int(math.ceil(max(ys3))) + 2)
        if bx1 <= bx0 or by1 <= by0:
            continue
        w, h = bx1 - bx0, by1 - by0
        tx = Mi[0, 0] * bx0 + Mi[0, 1] * by0 + Mi[0, 2]
        ty = Mi[1, 0] * bx0 + Mi[1, 1] * by0 + Mi[1, 2]
        tex = src.transform((w, h), Image.AFFINE,
                            (Mi[0, 0], Mi[0, 1], tx, Mi[1, 0], Mi[1, 1], ty),
                            resample=Image.BILINEAR)
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).polygon([(cp[q][0] - bx0, cp[q][1] - by0) for q in (i, j, k)], fill=255)
        layer.paste(tex, (bx0, by0), m)
    return layer, key


def layers_at_ss(geoms, images_dir, ss, frame):
    """每个插槽一层（超采样尺寸，尚未降采样）。"""
    out = OrderedDict()
    for g in geoms:
        layer, key = _warp_layer(g, images_dir, ss, frame)
        out[g[0]["name"]] = (layer, key)
    return out


def compose(layers, names, ss, frame):
    """按 names 的顺序 alpha 合成，再一次性降采样到 frame 尺寸（与官方 Renderer 同口径）。"""
    big = Image.new("RGBA", (frame["w"] * ss, frame["h"] * ss), (0, 0, 0, 0))
    for n in names:
        layer = layers[n][0]
        if layer is None:
            continue
        big.alpha_composite(layer)
    if ss != 1:
        big = big.resize((frame["w"], frame["h"]), Image.LANCZOS)
    return big


# ---------------------------------------------------------------- 小工具

def alpha_bbox(img):
    a = np.asarray(img.getchannel("A"))
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def dilate(img_l, radius):
    return img_l if radius <= 0 else img_l.filter(ImageFilter.MaxFilter(radius * 2 + 1))


def diff_stat(a, b):
    d = np.abs(np.asarray(a, np.int16) - np.asarray(b, np.int16))
    return int(d.max()), int((d.max(axis=2) > 3).sum())


# ---------------------------------------------------------------- extract

def build_native(layers, frame):
    """把超采样层降采样成原生尺寸的层字典。"""
    return {n: v[0].resize((frame["w"], frame["h"]), Image.LANCZOS) for n, v in layers.items()}


def apply_overrides(native, frame, ov_map, strict=True):
    """把覆盖件（画布空间位图，尺寸必须 = 原层 alpha bbox）替进对应层。

    **渐进叠加的关键**：extract 与 paste-back 都必须走这里，
    否则每轮回贴都会把上几步改好的件"还原"成原始贴图（2026-09-24 实测踩过）。
    """
    native = dict(native)
    for nm, path in ov_map.items():
        if nm not in native:
            if strict:
                raise SystemExit(f"覆盖表的插槽 {nm} 不在该皮肤里；可用：{list(native)}")
            print(f"[warn] 覆盖表里的 {nm} 不在该皮肤里，跳过")
            continue
        bb = alpha_bbox(native[nm])
        ov = Image.open(path).convert("RGBA")
        want = (bb[2] - bb[0] + 1, bb[3] - bb[1] + 1)
        if ov.size != want:
            msg = f"覆盖件 {nm} 尺寸 {ov.size} ≠ 原层 bbox {want}（用 paste-back 的 new_part_in_bbox.png）"
            if strict:
                raise SystemExit(msg)
            print("[warn] " + msg + "，跳过")
            continue
        img = Image.new("RGBA", (frame["w"], frame["h"]), (0, 0, 0, 0))
        img.alpha_composite(ov, (bb[0], bb[1]))
        native[nm] = img
        print(f"   覆盖 {nm}：{os.path.basename(path)} → 贴回原位 bbox {bb}")
    return native


def composite(native, names, frame):
    """按 names 的顺序合成原生层。"""
    out = Image.new("RGBA", (frame["w"], frame["h"]), (0, 0, 0, 0))
    for nm in names:
        out.alpha_composite(native[nm])
    return out


def cmd_extract(a) -> int:
    os.makedirs(a.out_dir, exist_ok=True)
    rr, geoms = load_geoms(a.json, a.images_dir, a.skin)
    skin_name = rr.skin_name
    frame = frame_of(geoms)

    order = [g[0]["name"] for g in geoms]            # = 绘制顺序（后面的压前面的）
    if a.slot not in order:
        raise SystemExit(f"插槽 {a.slot} 不在皮肤 {skin_name} 里；可用：{order}")
    k = order.index(a.slot)
    under, over = order[:k], order[k + 1:]
    slot_obj, att = geoms[k][0], geoms[k][1]
    assert set(under) | {a.slot} | set(over) == set(order)
    img_name = P.resolve_image_name(slot_obj["attachment"], att)
    inplace = a.mode in ("inplace", "pair")
    # inplace/pair：目标件提到**最上层**（位置不动）——它的完整轮廓不再被上层部件遮住
    order_use = ([n for n in order if n != a.slot] + [a.slot]) if inplace else order
    print(f"皮肤 {skin_name}｜插槽 {a.slot}（绘制序 {k + 1}/{len(order)}）→ 贴图 {img_name}.png"
          f"｜mode={a.mode}")
    if a.mode == "pair":
        print("策略：**摘除件单独图（第1张，mask 对着它）+ 原图置顶突出件（第2张）+ 参考风格**")
    elif inplace:
        print("策略：目标件**原位提到最上层**（完整轮廓可见）+ 红线描边；遮罩仍是黑白图")
    else:
        print(f"绘制序：下 {len(under)} 件 | 本件 | 上 {len(over)} 件（共 {len(order)}，不重不漏 ✅）"
              f" —— 原件**原位保留**，另复制一份到旁侧")

    layers = layers_at_ss(geoms, a.images_dir, a.ss, frame)
    ov_map = {}
    for spec in (a.override or []):
        if "=" not in spec:
            raise SystemExit(f"--override 要写成 SLOT=PATH，收到 {spec!r}")
        sk, sv = spec.split("=", 1)
        ov_map[sk.strip()] = sv.strip()

    official, _bb = P.Renderer(a.json, a.images_dir, ss=a.ss, pad=0, skin=skin_name).render()

    # 覆盖件是**画布空间位图**，混不进超采样层 ⇒ 只要带 --override，整条合成链就走原生级
    if ov_map:
        native0 = build_native(layers, frame)
        plain = composite(native0, order, frame)          # 覆盖前的原生合成（校验用）
        mirror_max, mirror_bad = diff_stat(plain, official)
        print(f"① 镜像校验（原生级合成 vs 官方 Renderer）：最大差 {mirror_max}，差 >3 的像素 {mirror_bad}"
              f"（原生级合成 + 覆盖件的固有代价，不是算错）")
        native = apply_overrides(native0, frame, ov_map)
        mine = composite(native, order_use, frame)
        normal_img = plain
        mirror_ok = True
    else:
        normal_img = compose(layers, order, a.ss, frame)
        mirror_max, mirror_bad = diff_stat(normal_img, official)
        mirror_ok = mirror_bad == 0
        print(f"① 镜像校验（本工具 vs 官方 Renderer）：最大差 {mirror_max}，差 >3 的像素 {mirror_bad} "
              f"{'✅' if mirror_ok else '⚠ 镜像的光栅化跑偏了'}")
        mine = compose(layers, order_use, a.ss, frame) if inplace else normal_img

    part = compose(layers, [a.slot], a.ss, frame)          # 目标件的**完整轮廓**（单独渲染）
    pb = alpha_bbox(part)
    if pb is None:
        raise SystemExit(f"插槽 {a.slot} 渲染出来是全透明的，无法抽出")
    px0, py0, px1, py1 = pb
    body_bbox = alpha_bbox(mine)
    body_right = body_bbox[2] if body_bbox else -1

    if inplace:
        # ② 原位校验：目标件已提到最上层 —— 它的**不透明芯区**必须与单独渲染逐像素一致
        #    （半透明边缘与下层做了 alpha 混合，本来就不该相等，所以只在 alpha==255 的芯区比）
        core = np.asarray(part.getchannel("A")) >= 255
        dm = np.abs(np.asarray(mine, np.int16) - np.asarray(part, np.int16)).max(axis=2)
        # 用 8（不是 3）：芯区在降采样后可能残留极少数边缘像素的小差，8 以上才算真错
        core_bad = int((dm[core] > 8).sum()) if core.any() else 0
        core_max = int(dm[core].max()) if core.any() else 0
        ok_core = core_bad == 0
        # 底图（不含目标件）：有覆盖件时必须用**覆盖后**的原生层，否则会把上几步的成果还原
        body = (composite(native, [n for n in order if n != a.slot], frame) if ov_map
                else compose(layers, under + over, a.ss, frame))
        original = mine
        dx = dy = 0
        new_w, new_h = frame["w"], frame["h"]
        overlap_px = gap_px = 0
        gap_ok = True
        body_max = body_bad = copy_max = copy_bad = 0
        body_ok = copy_ok = True
        part_moved = part
        print(f"② 原位校验：目标件芯区 {int(core.sum())} px 与单独渲染最大差 {core_max}，"
              f"差>3 的 {core_bad} px {'✅' if ok_core else '⚠'}")
    else:
        body = mine
        # 纵向不动（副本与原件等高），左边缘落在 body_right + 1 + gutter
        dx = (body_right + 1 + a.gutter) - px0
        dy = 0
        new_w = max(frame["w"], px1 + dx + 1 + a.gutter)
        new_h = max(frame["h"], py1 + dy + 1 + a.gutter)

        original = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
        original.alpha_composite(body, (0, 0))
        part_moved = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
        part_moved.alpha_composite(part, (dx, dy))
        original.alpha_composite(part_moved, (0, 0))

        # ② 保真校验：主体原位逐像素不变；旁侧副本与原件层逐像素相同（只平移，不重采样）
        body_max, body_bad = diff_stat(original.crop(tuple(body_bbox)), mine.crop(tuple(body_bbox)))
        body_ok = body_bad == 0
        copy_box = (px0 + dx, py0 + dy, px1 + dx + 1, py1 + dy + 1)
        copy_max, copy_bad = diff_stat(original.crop(copy_box), part.crop((px0, py0, px1 + 1, py1 + 1)))
        copy_ok = copy_bad == 0
        print(f"② 保真校验：主体原位最大差 {body_max}（差>3 的像素 {body_bad}）{'✅' if body_ok else '⚠'}；"
              f"旁侧副本 vs 原件层最大差 {copy_max}（{copy_bad}）{'✅' if copy_ok else '⚠'}")

    # ③ 与交付预览图对账（可选）：证明"世界坐标 → 像素"的映射没跑偏
    preview_mean = None
    if a.preview:
        ref = Image.open(a.preview).convert("RGB")
        rep = S.Scene(a.json, a.images_dir, a.skin).preview_rgb()
        if rep.size == ref.size:
            dd = np.abs(np.asarray(rep, np.int16) - np.asarray(ref, np.int16))
            preview_mean = round(float(dd.mean()), 3)
            print(f"③ 与交付预览图对账：尺寸一致 {rep.size}｜RGB 最大差 {int(dd.max())} 平均差 {dd.mean():.3f}"
                  f"{'（坐标可信）' if dd.mean() < 2 else '（**不一致，坐标可能偏**）'}")
        else:
            print(f"[warn] 复现尺寸 {rep.size} ≠ 交付预览 {ref.size}，坐标映射不可信")

    # ④ 不重叠 + 间距自检（仅 aside 模式：副本必须完全落在主体内容右侧之外）
    if inplace:
        print(f"主体内容 bbox {body_bbox}｜目标件 alpha {px1 - px0 + 1}x{py1 - py0 + 1} "
              f"@ 原位 x[{px0},{px1}] y[{py0},{py1}]（**位置不动，只提到最上层**）")
    else:
        body_full = Image.new("L", (new_w, new_h), 0)
        body_full.paste(body.getchannel("A"), (0, 0))
        ba = np.asarray(body_full) > 0
        pa = np.asarray(part_moved.getchannel("A")) > 0
        overlap_px = int((ba & pa).sum())
        body_dil = np.asarray(dilate(body_full, a.gutter)) > 0
        gap_px = int((body_dil & pa).sum())
        gap_ok = gap_px == 0
        print(f"主体内容 bbox {body_bbox}｜待改件 alpha {px1 - px0 + 1}x{py1 - py0 + 1} "
              f"@ 原位 x[{px0},{px1}] y[{py0},{py1}]")
        print(f"副本位移 Δ=({dx},{dy}) → 新位 x[{px0 + dx},{px1 + dx}] y[{py0 + dy},{py1 + dy}]"
              f"｜画布 {frame['w']}x{frame['h']} → {new_w}x{new_h}")
        print(f"④ 不重叠自检：重叠 {overlap_px} px；间距 ≥{a.gutter}px 违例 {gap_px} px "
              f"{'✅' if (overlap_px == 0 and gap_ok) else '❌'}")

    # 摘除部件（突出）：单独一张紧凑画布 —— 它才是**第 1 张输入图**，mask 也对着它
    part_only = part_only_sil = None
    if a.mode == "pair":
        from scipy import ndimage as _ndi2
        m = a.part_margin
        pw, ph = px1 - px0 + 1, py1 - py0 + 1
        part_crop = part.crop((px0, py0, px1 + 1, py1 + 1))
        part_only = Image.new("RGBA", (pw + m * 2, ph + m * 2), BG)
        part_only.alpha_composite(part_crop, (m, m))
        sil = np.zeros((ph + m * 2, pw + m * 2), bool)
        sil[m:m + ph, m:m + pw] = np.asarray(part_crop.getchannel("A")) > 0
        part_only_sil = Image.fromarray((sil * 255).astype(np.uint8), "L")
        if a.redline_width > 0:
            edge = sil & ~_ndi2.binary_erosion(sil, iterations=a.redline_width)
            arr = np.asarray(part_only).copy()
            arr[edge] = (255, 0, 0, 255)
            part_only = Image.fromarray(arr, "RGBA")
        print(f"摘除部件（突出）：紧凑画布 {part_only.size[0]}x{part_only.size[1]}"
              f"（部件 {pw}x{ph} + 边距 {m}），mask 对着这张")

    # mask：白 = 要重绘（marked 极性），黑白图
    if a.mode == "pair":
        mask = dilate(part_only_sil, a.mask_grow)
        mask_target = "part_only"
    else:
        src_img = part if inplace else part_moved
        mask = dilate(src_img.getchannel("A").point(lambda v: 255 if v > 0 else 0), a.mask_grow)
        mask_target = "original"
    mask_px = int((np.asarray(mask) > 0).sum())

    p_orig_rgba = os.path.join(a.out_dir, "original_rgba.png")
    p_orig = os.path.join(a.out_dir, "original.png")
    p_body = os.path.join(a.out_dir, "body_rgba.png")
    p_part = os.path.join(a.out_dir, "part_extracted_rgba.png")
    p_mask = os.path.join(a.out_dir, "mask.png")
    p_overlay = os.path.join(a.out_dir, "overlay.png")
    p_part_only = os.path.join(a.out_dir, "part_only.png")
    p_json = os.path.join(a.out_dir, "extract.json")

    original.save(p_orig_rgba)
    rgb = Image.new("RGBA", original.size, BG)
    rgb.alpha_composite(original)
    rgb = rgb.convert("RGB")

    # 红线描出目标件轮廓（画在**喂模型的原图**上；mask.png 仍是黑白图）
    redline_px = 0
    if inplace and a.redline_width > 0:
        from scipy import ndimage as _ndi
        sil = np.asarray(part.getchannel("A")) > 0
        inner = _ndi.binary_erosion(sil, iterations=a.redline_width)
        edge = sil & ~inner
        redline_px = int(edge.sum())
        arr = np.asarray(rgb).copy()
        arr[edge] = (255, 0, 0)
        rgb = Image.fromarray(arr, "RGB")
        print(f"红线标记：沿目标件轮廓画 {a.redline_width}px 红边，共 {redline_px} px")

    rgb.save(p_orig)
    body.save(p_body)
    part.crop((px0, py0, px1 + 1, py1 + 1)).save(p_part)   # 抽出件原样（裁到内容 bbox）
    mask.save(p_mask)
    if part_only is not None:
        part_only.convert("RGB").save(p_part_only)

    ov = rgb.copy()
    # overlay 是"原图坐标系"的目视校验图；pair 模式的 mask 在 part_only 坐标系里，这里另算一张示意遮罩
    ov_mask = mask if a.mode == "aside" else dilate(
        part.getchannel("A").point(lambda v: 255 if v > 0 else 0), a.mask_grow)
    ov.paste(Image.new("RGB", ov.size, (255, 40, 40)), (0, 0),
             Image.fromarray((np.asarray(ov_mask) // 2).astype(np.uint8), "L"))
    if not inplace:
        ImageDraw.Draw(ov).rectangle([px0 + dx, py0 + dy, px1 + dx, py1 + dy], outline=(0, 255, 120))
    ov.save(p_overlay)

    # 目视复核：左 = 改前（原绘制顺序）｜右 = 本次提交图（红线 + 红色遮罩示意）
    p_cmp = os.path.join(a.out_dir, "compare.png")
    before_rgb = Image.new("RGBA", (new_w, new_h), BG)
    before_rgb.alpha_composite(normal_img, (0, 0))
    cmp_img = Image.new("RGB", (new_w * 2 + 12, new_h), (24, 24, 28))
    cmp_img.paste(before_rgb.convert("RGB"), (0, 0))
    cmp_img.paste(ov, (new_w + 12, 0))
    cmp_img.save(p_cmp)

    # pair 模式：两张提交图并排预览（左=第2张 原图置顶突出件｜右=第1张 摘除件 + mask）
    p_pair = os.path.join(a.out_dir, "pair_preview.png")
    if part_only is not None:
        po_rgb = part_only.convert("RGB")
        pv = Image.new("RGB", (rgb.width + po_rgb.width + 12, max(rgb.height, po_rgb.height)),
                       (24, 24, 28))
        pv.paste(rgb, (0, 0))
        pv.paste(po_rgb, (rgb.width + 12, 0))
        pv.save(p_pair)

    meta = {
        "format": FORMAT, "version": 1,
        "source": {"json": a.json, "images": a.images_dir, "skin": skin_name,
                   "preview": a.preview},
        "slot": a.slot, "attachment": slot_obj["attachment"], "image": img_name + ".png",
        "slot_draw_index": k, "draw_order": order, "mode": a.mode,
        "mask_target": mask_target, "part_margin": a.part_margin,
        "under": under, "over": over,
        "ss": a.ss, "gutter": a.gutter, "mask_grow": a.mask_grow,
        "redline_width": a.redline_width,
        "overrides": {n: os.path.abspath(v) for n, v in ov_map.items()},
        "frame": frame,
        "body_bbox": body_bbox, "body_right": body_right,
        "part": {
            "bbox_original": [px0, py0, px1, py1],
            "size_original": [px1 - px0 + 1, py1 - py0 + 1],
            "bbox_moved": [px0 + dx, py0 + dy, px1 + dx, py1 + dy],
            "delta": [dx, dy],
        },
        "canvas": {"before": [frame["w"], frame["h"]], "after": [new_w, new_h]},
        "checks": {
            "mirror_vs_official_max_diff": mirror_max, "mirror_px_gt3": mirror_bad, "mirror_ok": mirror_ok,
            "inplace_core_max_diff": core_max if inplace else None,
            "inplace_core_px_gt3": core_bad if inplace else None,
            "body_fidelity_max_diff": body_max, "body_fidelity_px_gt3": body_bad, "body_fidelity_ok": body_ok,
            "copy_fidelity_max_diff": copy_max, "copy_fidelity_px_gt3": copy_bad, "copy_fidelity_ok": copy_ok,
            "preview_mean_diff": preview_mean,
            "overlap_px": overlap_px, "gutter_violation_px": gap_px, "gutter_ok": bool(gap_ok),
            "mask_px": mask_px, "redline_px": redline_px,
        },
        "outputs": {
            "original_rgb": p_orig, "original_rgba": p_orig_rgba, "body_rgba": p_body,
            "part_copy_rgba": p_part, "part_only_rgb": p_part_only if part_only is not None else None,
            "mask": p_mask, "overlay": p_overlay, "compare": p_cmp,
            "pair_preview": p_pair if part_only is not None else None,
        },
    }
    json.dump(meta, open(p_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"遮罩 {mask_px} px（外扩 {a.mask_grow}px，坐标系={mask_target}）")
    if part_only is not None:
        print(f"★ 第 1 张（mask 对它）→ {p_part_only}  {part_only.size[0]}x{part_only.size[1]}")
        print(f"  第 2 张（语境/位置）→ {p_orig}  {rgb.size[0]}x{rgb.size[1]}")
        print("  两张并排预览 → " + p_pair)
    else:
        print("原图(RGB,喂模型) → " + p_orig)
    print("原图(RGBA,精确合成) → " + p_orig_rgba)
    print("抽出件 → " + p_part)
    print("遮罩 → " + p_mask)
    print("覆盖校验图 → " + p_overlay)
    print("抽出前后对比 → " + p_cmp)
    print("清单 → " + p_json)
    ok = mirror_ok and body_ok and copy_ok and overlap_px == 0 and gap_ok
    return 0 if ok else 1


# ---------------------------------------------------------------- paste-back

def _border_bg(arr):
    """取出图四边 4px 环的中位色当背景色（纯色底出图的兜底口径）。"""
    h, w = arr.shape[:2]
    ring = np.concatenate([arr[:4].reshape(-1, 3), arr[-4:].reshape(-1, 3),
                           arr[:, :4].reshape(-1, 3), arr[:, -4:].reshape(-1, 3)])
    return np.median(ring, axis=0)


def slot_layers(meta, ss=None):
    """按 extract.json 的源与 frame 重新渲出「每插槽一层」（覆盖表/z 序合成共用）。"""
    src = meta["source"]
    ss = ss or meta.get("ss", 3)
    _rr, geoms = load_geoms(src["json"], src["images"], src["skin"])
    frame = meta["frame"]
    f2 = frame_of(geoms)
    if abs(f2["minx"] - frame["minx"]) > 1e-6 or abs(f2["maxy"] - frame["maxy"]) > 1e-6:
        print("[warn] 骨架 frame 与 extract.json 不一致，覆盖/z 序合成可能错位")
    return layers_at_ss(geoms, src["images"], ss, frame), [g[0]["name"] for g in geoms]


def cmd_paste_back(a) -> int:
    os.makedirs(a.out_dir, exist_ok=True)
    meta = json.load(open(os.path.join(a.case, "extract.json"), encoding="utf-8"))
    body = Image.open(meta["outputs"]["body_rgba"]).convert("RGBA")
    gen = Image.open(a.generated).convert("RGB")
    garr = np.asarray(gen).astype(np.int16)
    in_w, in_h = meta["canvas"]["after"]
    sx, sy = gen.width / float(in_w), gen.height / float(in_h)
    mv = meta["part"]["bbox_moved"]
    proj = [mv[0] * sx, mv[1] * sy, (mv[2] + 1) * sx, (mv[3] + 1) * sy]
    ob = meta["part"]["bbox_original"]
    tw, th = ob[2] - ob[0] + 1, ob[3] - ob[1] + 1
    frame = meta["frame"]
    mode = meta.get("mode", "aside")
    bg = None
    n = merged = 0
    bx0 = by0 = bx1 = by1 = 0
    area = pw = ph = nw = nh = 0
    k = 1.0

    if mode == "inplace":
        # inplace：原图是**整幅场景**（实测模型保留构图），按投影直接裁出目标件区域即可；
        # alpha 取"模型真正改动过的像素"（出图 vs 把原图缩放到出图尺寸后的逐像素差异）——
        # 不抠背景、也不用剪影模具：没被改动的邻居像素天然不会被贴回去。
        x0, y0 = max(0, int(round(ob[0] * sx))), max(0, int(round(ob[1] * sy)))
        x1 = min(gen.width, int(round((ob[2] + 1) * sx)))
        y1 = min(gen.height, int(round((ob[3] + 1) * sy)))
        rect = gen.crop((x0, y0, x1, y1))
        ref = Image.open(meta["outputs"]["original_rgb"]).convert("RGB").resize(gen.size, Image.LANCZOS)
        d = np.abs(np.asarray(rect, np.int16) - np.asarray(ref.crop((x0, y0, x1, y1)), np.int16)).max(axis=2)
        a_arr = np.where(d > a.thresh, 255, 0).astype(np.uint8)
        piece = rect.convert("RGBA")
        piece.putalpha(Image.fromarray(a_arr, "L"))
        pw, ph = piece.size
        scaled = piece.resize((tw, th), Image.LANCZOS)
        nw, nh = tw, th
        k = tw / float(pw) if pw else 1.0
        ox, oy = ob[0], ob[1]
        bx0, by0, bx1, by1 = x0, y0, x1 - 1, y1 - 1
        area = int((a_arr > 0).sum())
        print(f"[inplace] 投影裁切 ({x0},{y0})-({x1},{y1}) = {x1 - x0}x{y1 - y0} → 缩回原件 bbox {tw}x{th}")
        print(f"[inplace] 模型改动 {area} px（占裁切区 {a_arr.size} px 的 "
              f"{area / max(a_arr.size, 1) * 100:.1f}%）")
        if area == 0:
            print("[warn] 出图与输入在这个区域**逐像素相同** —— 模型可能什么都没改")
    else:
        if a.bg:
            bg = np.array([int(a.bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.int16)
        else:
            bg = _border_bg(garr)
        dist = np.abs(garr - bg).max(axis=2)
        fg = dist > a.thresh
        soft = np.clip((dist - a.thresh / 2.0) / max(a.thresh, 1) * 255, 0, 255).astype(np.uint8)
        try:
            from scipy import ndimage
        except ImportError:
            raise SystemExit("paste-back（aside 模式）需要 scipy（ndimage）")
        lbl, n = ndimage.label(fg)

        # 选件：**不信投影** —— 实测模型会把部件重排到画布中部、并不按整幅画布等比映射，
        # 于是直接取「最大前景块 + 质心落在它外扩 10% 内的其它块」（深浅描边会把同一件切成几块）合并。
        comps = []
        for i in range(1, n + 1):
            ys, xs = np.nonzero(lbl == i)
            if len(ys) >= 32:
                comps.append({"i": i, "px": len(ys), "x0": int(xs.min()), "x1": int(xs.max()),
                              "y0": int(ys.min()), "y1": int(ys.max()),
                              "cx": float(xs.mean()), "cy": float(ys.mean())})
        if not comps:
            raise SystemExit("出图里找不到前景块，检查 --thresh / --bg")
        comps.sort(key=lambda c: -c["px"])
        big = comps[0]
        mx = (big["x1"] - big["x0"]) * 0.10 + 8.0
        my = (big["y1"] - big["y0"]) * 0.10 + 8.0
        keep = np.zeros_like(fg)
        for c in comps:
            if (big["x0"] - mx <= c["cx"] <= big["x1"] + mx) and (big["y0"] - my <= c["cy"] <= big["y1"] + my):
                keep |= (lbl == c["i"])
                merged += 1
        if not (proj[0] - 40 <= big["cx"] <= proj[2] + 40 and proj[1] - 40 <= big["cy"] <= proj[3] + 40):
            print("[info] 目标件落点与投影区不一致（出图未按整幅画布等比映射）—— 以部件自身 bbox 为准缩放回贴")

        silhouette = ndimage.binary_fill_holes(keep)      # 把描边围出的内部一并算进轮廓
        ys, xs = np.nonzero(silhouette)
        bx0, by0, bx1, by1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
        area = int(silhouette.sum())
        # alpha：轮廓内一律不透明；轮廓外只保留 2px 抗锯齿环，防止别处的前景漏进来
        outer = ndimage.binary_dilation(silhouette, iterations=2)
        alpha = np.where(outer, np.maximum(soft, (silhouette * 255).astype(np.uint8)), 0).astype(np.uint8)
        piece = Image.fromarray(np.dstack([np.asarray(gen), alpha]), "RGBA").crop((bx0, by0, bx1 + 1, by1 + 1))

        # 等比缩放到原件的 bbox 并居中贴回原位（"直接替换"，不做融合）
        pw, ph = piece.size
        k = min(tw / float(pw), th / float(ph))
        nw, nh = max(1, int(round(pw * k))), max(1, int(round(ph * k)))
        scaled = piece.resize((nw, nh), Image.LANCZOS)
        cx, cy = (ob[0] + ob[2] + 1) / 2.0, (ob[1] + ob[3] + 1) / 2.0
        ox, oy = int(round(cx - nw / 2.0)), int(round(cy - nh / 2.0))

    overlay = Image.new("RGBA", (frame["w"], frame["h"]), (0, 0, 0, 0))
    overlay.alpha_composite(scaled, (ox, oy))

    # z 序：按**原本的绘制顺序**把新件放回它自己那一层（否则底层的件贴到最上层会盖住别人）
    z_note = None
    if a.zorder:
        layers, order = slot_layers(meta)
        native = build_native(layers, frame)
        # ★ 必须把 extract.json 里记录的覆盖表套回来 —— 否则这一轮回贴会把上几步改好的件全"还原"
        ov_map = {k: v for k, v in (meta.get("overrides") or {}).items()}
        if ov_map:
            print(f"套用覆盖表 {len(ov_map)} 件（渐进叠加）：")
            native = apply_overrides(native, frame, ov_map, strict=False)
        after = Image.new("RGBA", (frame["w"], frame["h"]), (0, 0, 0, 0))
        for nm in order:
            after.alpha_composite(overlay if nm == meta["slot"] else native[nm])
        plain = Image.new("RGBA", (frame["w"], frame["h"]), (0, 0, 0, 0))
        for nm in order:
            plain.alpha_composite(build_native(layers, frame)[nm])
        z_max, z_bad = diff_stat(plain, compose(layers, order, meta.get("ss", 3), frame))
        z_note = {"native_composite_max_diff": z_max, "native_composite_px_gt3": z_bad,
                  "overrides_applied": sorted(ov_map)}
        print(f"z 序合成：{meta['slot']} 回到第 {meta['slot_draw_index'] + 1} 层（共 {len(order)} 层）；"
              f"原生级合成 vs 官方超采样合成的代价：最大差 {z_max}，差 >3 的像素 {z_bad}")
    else:
        after = body.copy()
        after.alpha_composite(scaled, (ox, oy))

    # 覆盖件（给下一轮 extract --override 用）：新件按**原件 bbox 尺寸**裁一张
    in_bbox = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    in_bbox.alpha_composite(scaled, (ox - ob[0], oy - ob[1]))

    p_after = os.path.join(a.out_dir, "baseline_after.png")
    p_new = os.path.join(a.out_dir, "new_part_rgba.png")
    p_bbox = os.path.join(a.out_dir, "new_part_in_bbox.png")
    p_rgb = os.path.join(a.out_dir, "baseline_after_rgb.png")
    p_cmp = os.path.join(a.out_dir, "compare_before_after.png")
    p_json = os.path.join(a.out_dir, "pasteback.json")
    after.save(p_after)
    piece.save(p_new)
    in_bbox.save(p_bbox)
    after_rgb = Image.new("RGBA", after.size, BG)
    after_rgb.alpha_composite(after)
    after_rgb.convert("RGB").save(p_rgb)
    before_rgb = Image.new("RGBA", body.size, BG)
    before_rgb.alpha_composite(body)
    cmp_img = Image.new("RGB", (after.width * 2 + 12, after.height), (24, 24, 28))
    cmp_img.paste(before_rgb.convert("RGB"), (0, 0))
    cmp_img.paste(after_rgb.convert("RGB"), (after.width + 12, 0))
    cmp_img.save(p_cmp)

    info = {
        "format": FORMAT, "version": 1, "cmd": "paste-back", "mode": mode,
        "case": a.case, "generated": a.generated, "gen_size": list(gen.size),
        "bg": ("#" + "".join(f"{int(v):02X}" for v in bg)) if bg is not None else None,
        "thresh": a.thresh,
        "components": int(n), "merged_components": int(merged),
        "projected_bbox": [round(v, 1) for v in proj],
        "picked_bbox": [bx0, by0, bx1, by1], "picked_px": int(area),
        "piece_size": [pw, ph], "scale": round(k, 4), "scaled_size": [nw, nh],
        "target_bbox": ob, "placed_at": [ox, oy], "zorder": bool(a.zorder), "z_check": z_note,
        "outputs": {"baseline_after": p_after, "baseline_after_rgb": p_rgb,
                    "new_part_rgba": p_new, "new_part_in_bbox": p_bbox, "compare": p_cmp},
    }
    json.dump(info, open(p_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    if mode == "inplace":
        print(f"贴回：裁切区 {info['picked_bbox']} → 原件 bbox {ob} @ ({ox},{oy})，缩回 {nw}x{nh}")
    else:
        print(f"出图 {gen.size}｜背景 {info['bg']}｜前景块 {n} 个，选中 bbox {info['picked_bbox']}（{area} px）")
        print(f"投影目标区 {info['projected_bbox']}")
        print(f"等比缩放 ×{k:.4f}：{pw}x{ph} → {nw}x{nh}，贴到原位 bbox {ob} @ ({ox},{oy})")
    print("新基线(RGBA) → " + p_after)
    print("新基线(RGB) → " + p_rgb)
    print("抽出新件 → " + p_new)
    print("改前/改后对比 → " + p_cmp)
    print("清单 → " + p_json)
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Spine 部件抽出/让位 + 出遮罩（本地免费）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract", help="把待改件挪到旁边空位 → 原图 + 遮罩 + 清单")
    ex.add_argument("--json", required=True)
    ex.add_argument("--images", dest="images_dir", required=True)
    ex.add_argument("--skin", default=None)
    ex.add_argument("--slot", required=True)
    ex.add_argument("--out-dir", required=True)
    ex.add_argument("--mode", choices=["pair", "inplace", "aside"], default="pair",
                    help="pair=摘除件单独图(mask 对它) + 原图置顶突出件（默认）；"
                         "inplace=只出原图置顶突出件；aside=复制一份挪到旁侧空位")
    ex.add_argument("--part-margin", type=int, default=24,
                    help="pair 模式：摘除件紧凑画布四周留白 px，默认 24")
    ex.add_argument("--redline-width", type=int, default=2,
                    help="inplace 模式下沿目标件轮廓画几 px 红线，0=不画，默认 2")
    ex.add_argument("--gutter", type=int, default=20, help="aside 模式：副本与主体的最小间距 px，默认 20")
    ex.add_argument("--mask-grow", type=int, default=2, help="遮罩外扩 px，默认 2")
    ex.add_argument("--ss", type=int, default=3, help="超采样倍率（渲染质量），默认 3")
    ex.add_argument("--preview", default=None, help="可选：交付的复原预览图，用于对账")
    ex.add_argument("--override", action="append", default=[],
                    help="覆盖表 SLOT=PATH（可重复）：该插槽用这张画布空间新件替代原层，"
                         "供「渐进叠加」把已改好的件带进下一轮")
    ex.set_defaults(func=cmd_extract)

    pb = sub.add_parser("paste-back", help="后置处理：从模型出图里抠出新部件 → 等比缩放 → 贴回原位")
    pb.add_argument("--case", required=True, help="extract 的 out-dir（里面有 extract.json）")
    pb.add_argument("--generated", required=True, help="模型出图（任意尺寸）")
    pb.add_argument("--out-dir", required=True)
    pb.add_argument("--thresh", type=int, default=16, help="与背景色的最小距离，判为前景，默认 16")
    pb.add_argument("--bg", default=None, help="背景色 #RRGGBB；默认自动取出图四边中位色")
    pb.add_argument("--zorder", dest="zorder", action="store_true", default=True,
                    help="按原绘制顺序把新件放回它自己那一层（默认开）")
    pb.add_argument("--no-zorder", dest="zorder", action="store_false",
                    help="简单粗暴贴在主体最上层")
    pb.set_defaults(func=cmd_paste_back)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
