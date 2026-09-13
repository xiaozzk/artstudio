#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fit_parts.py — 把 AI 拆出来的部件按 spec 的原始比例缩放, 并拼回原画布验收。

流程: alpha_split.py 拆件 -> 本工具测量比例偏差 -> 统一缩放 -> 按 spec 位置拼回原图 -> 看效果

用法:

  python tools/fit_parts.py out_demo_a --spec spec_head_plan.json -o fitted

  # 同时把整张画布放大到目标分辨率(内容高度 = 2048)
  python tools/fit_parts.py out_demo_a --spec spec_head_plan.json -o fitted --target-height 2048

  # 用指定的部件估计统一缩放(默认用所有匹配部件的尺寸比中位数)
  python tools/fit_parts.py out_demo_a --spec spec_head_plan.json -o fitted --anchor head_base

  # 每个部件各自缩放到 spec 尺寸(会掩盖比例误差, 仅用于"只看拼合观感")
  python tools/fit_parts.py out_demo_a --spec spec_head_plan.json -o fitted --per-part

输出:
  <out>/parts_scaled/<name>.png   缩放后的部件(与输出画布同尺寸, 可直接进 Spine)
  <out>/composite.png             拼回原画布的结果
  <out>/compare.png               左=原图 / 右=拼合结果 对比图
  <out>/fit_report.json           每个部件的比例偏差报告
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover
        return ImageFont.load_default()


def load_manifest(parts_dir: Path) -> dict:
    mp = parts_dir / "manifest.json"
    if not mp.is_file():
        raise SystemExit(f"[ERROR] 找不到 {mp}, 请先跑 alpha_split.py")
    return json.loads(mp.read_text(encoding="utf-8"))


def load_spec(spec_path: Path, canvas=None) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if isinstance(spec, dict) and "parts" in spec and "canvas" in spec:
        return spec
    if isinstance(spec, dict) and "bbox_ref" in spec:
        return spec["bbox_ref"]
    raise SystemExit(f"[ERROR] spec 格式不对: {spec_path}")


def auto_match(spec_parts: dict, ai_parts: dict, verbose=True) -> dict:
    """AI 每次摆位/命名都不同, 用「长宽比 + 面积」代价矩阵贪心配对。

    代价 = |ln(宽高比之比)| + 0.5*|ln(面积之比)|
    配对完再做 _L/_R 修正: 同一对里的两个, x 小的算 _L。
    """
    import math

    ai_names = list(ai_parts)
    sp_names = list(spec_parts)

    def size_of(rec):
        if "size" in rec:
            return rec["size"]
        x0, y0, x1, y1 = rec["bbox"]
        return [x1 - x0, y1 - y0]

    def aspect(rec):
        w, h = size_of(rec)
        return w / h if h else 1.0

    # 面积必须用「占比」而不是绝对值: AI 那套部件可能整体是 1.5x/2x 画出来的,
    # 绝对面积差一个全局常数, 会把配对带偏(实测 hair 与 head_base 配反)。
    tot_a = sum((ai_parts[a].get("area") or 1) for a in ai_names) or 1
    tot_s = sum((spec_parts[s].get("area") or 1) for s in sp_names) or 1

    cost = {}
    for a in ai_names:
        for s in sp_names:
            ca = abs(math.log(max(1e-6, aspect(ai_parts[a]) / aspect(spec_parts[s]))))
            ra = (ai_parts[a].get("area") or 1) / tot_a
            rs = (spec_parts[s].get("area") or 1) / tot_s
            ca += 0.5 * abs(math.log(max(1e-6, ra / rs)))
            cost[(a, s)] = ca

    pairs, used_a, used_s = [], set(), set()
    for (a, s), c in sorted(cost.items(), key=lambda kv: kv[1]):
        if a in used_a or s in used_s:
            continue
        used_a.add(a)
        used_s.add(s)
        pairs.append((a, s, c))

    mapping = {a: s for a, s, _ in pairs}

    # --- _L/_R 修正: 成对的部件按 x 中心排序重新分配左右
    by_family: dict[str, list[str]] = {}
    for s in sp_names:
        if s.endswith("_L") or s.endswith("_R"):
            by_family.setdefault(s[:-2], []).append(s)
    for fam, names in by_family.items():
        if len(names) != 2:
            continue
        assigned = [a for a, s in mapping.items() if s in names]
        if len(assigned) != 2:
            continue
        assigned.sort(key=lambda a: ai_parts[a]["centroid"][0])
        mapping[assigned[0]] = fam + "_L"
        mapping[assigned[1]] = fam + "_R"

    if verbose:
        print("[i] 自动配对(长宽比 + 面积):")
        for a, s, c in sorted(pairs, key=lambda p: mapping[p[0]]):
            print(f"      {a:<14} -> {mapping[a]:<12} cost={c:.3f}")
    return mapping


def main() -> int:
    ap = argparse.ArgumentParser(description="按 spec 比例缩放 AI 拆出的部件并拼回原画布")
    ap.add_argument("parts_dir", type=Path, help="alpha_split.py 的输出目录")
    ap.add_argument("--spec", type=Path, required=True, help="比例 spec (bbox_ref 风格)")
    ap.add_argument("-o", "--out-dir", type=Path, required=True)
    ap.add_argument("--anchor", default=None,
                    help="只用这个部件估计统一缩放(默认: 所有匹配部件的中位数)")
    ap.add_argument("--per-part", action="store_true",
                    help="等价于 --scale-mode per-part (每件各自拉成 spec 尺寸, 会变形)")
    ap.add_argument("--scale-mode", choices=["aspect", "blend", "per-part", "uniform"],
                    default="aspect",
                    help="aspect: 每件等比缩放不变形(默认)+ 整体锁定; "
                         "blend: 贴合/不变形之间插值; per-part: 完全贴合(会变形); "
                         "uniform: 全部共用一个缩放")
    ap.add_argument("--aspect-weight", type=float, default=0.7,
                    help="blend 模式的权重 t, 0=完全贴合 spec(会变形) 1=完全不变形 "
                         "(默认 0.7; 可在 spec 里逐件写 aspect_weight 覆盖)")
    ap.add_argument("--aspect-by", choices=["h", "w", "area"], default="area",
                    help="aspect 模式下每件按什么对齐 spec: 高 / 宽 / 面积(默认)")
    ap.add_argument("--lock-overall", choices=["geom", "h", "w", "off"], default="geom",
                    help="整体锁定: 用全局系数把拼合后的并集 bbox 拉到 spec 整体 bbox 上。"
                         "geom=宽高折中(默认), h=对齐高, w=对齐宽, off=不锁")
    ap.add_argument("--target-height", type=int, default=None,
                    help="整张画布放大到该内容高度")
    ap.add_argument("--align", choices=["center", "top", "bottom", "left", "right"],
                    default="center", help="部件与 spec bbox 的对齐方式")
    ap.add_argument("--base-image", default=None,
                    help="对比图左侧的原图, 默认取 spec 的 base_image")
    ap.add_argument("--composite-base", action="store_true",
                    help="拼合时保留原图作为底(否则只放部件)")
    ap.add_argument("--auto-match", action="store_true",
                    help="AI 部件名与 spec 对不上时, 按长宽比+面积自动配对(含 _L/_R 修正)")
    args = ap.parse_args()
    if args.per_part:
        args.scale_mode = "per-part"

    man = load_manifest(args.parts_dir)
    spec = load_spec(args.spec)
    canvas = spec.get("canvas")
    if not canvas:
        raise SystemExit("[ERROR] spec 缺少 canvas")
    cw, ch = int(canvas[0]), int(canvas[1])
    if man.get("canvas") and list(man["canvas"]) == [cw, ch]:
        pass

    spec_parts = {p["name"]: p for p in spec["parts"]}
    spec_order = {p["name"]: i for i, p in enumerate(spec["parts"])}
    ai_parts = {p["name"]: p for p in man["parts"]}

    if args.auto_match:
        free_spec = {k: v for k, v in spec_parts.items() if k not in ai_parts}
        free_ai = {k: v for k, v in ai_parts.items() if k not in spec_parts}
        if free_ai and free_spec:
            mapping = auto_match(free_spec, free_ai)
            for p in man["parts"]:
                if p["name"] in mapping:
                    p["name"] = mapping[p["name"]]
            ai_parts = {p["name"]: p for p in man["parts"]}
            print(f"[i] --auto-match 生效, 重命名 {len(mapping)} 件")
        elif free_ai:
            print(f"[w] 有 {len(free_ai)} 件 AI 部件在 spec 里找不到对应: "
                  f"{sorted(free_ai)}")

    matched = sorted(set(spec_parts) & set(ai_parts),
                     key=lambda n: (spec_parts[n].get("z", 0), spec_order[n]))
    only_spec = sorted(set(spec_parts) - set(ai_parts))
    only_ai = sorted(set(ai_parts) - set(spec_parts))

    print(f"[i] 画布 {cw}x{ch}   spec {len(spec_parts)} 件   AI {len(ai_parts)} 件   "
          f"匹配 {len(matched)} 件")
    if only_spec:
        print(f"[w] 只有 spec 有: {only_spec}")
    if only_ai:
        print(f"[w] 只有 AI 有:  {only_ai}")
    if not matched:
        print("[ERROR] 没有任何匹配的部件名")
        return 2

    # ---- 载入 AI 部件(裁剪到实际内容)
    sprites: dict[str, Image.Image] = {}
    for name in matched:
        rec = ai_parts[name]
        f = args.parts_dir / (rec.get("file_full") or rec["file"])
        im = Image.open(f).convert("RGBA")
        bb = im.getbbox()
        if bb is None:
            print(f"[w] {name} 全透明, 跳过")
            continue
        sprites[name] = im.crop(bb)

    matched = [n for n in matched if n in sprites]

    # ---- 比例报告
    rows = []
    for name in matched:
        sw, sh = sprites[name].size
        _, _, _, _ = 0, 0, 0, 0
        x0, y0, x1, y1 = spec_parts[name]["bbox"]
        tw, th = x1 - x0, y1 - y0
        rows.append(dict(name=name, spec_size=[tw, th], ai_size=[sw, sh],
                         sx=tw / sw, sy=th / sh, spec_bbox=spec_parts[name]["bbox"]))

    pool = []
    if args.anchor and args.anchor in {r["name"] for r in rows}:
        r = next(r for r in rows if r["name"] == args.anchor)
        pool = [r["sx"], r["sy"]]
        print(f"[i] 统一缩放取自 anchor={args.anchor}")
    else:
        if args.anchor:
            print(f"[w] anchor={args.anchor} 不在匹配列表里, 退回中位数")
        pool = [v for r in rows for v in (r["sx"], r["sy"])]
    scale = float(np.median(pool))

    print("")
    print(f"{'name':<12} {'spec w x h':<14} {'ai w x h':<14} "
          f"{'need sx':>8} {'need sy':>8} {'sy/sx':>7}  dev%")
    print("-" * 74)
    for r in rows:
        ratio = r["sy"] / r["sx"] if r["sx"] else 0
        dev = 100.0 * max(r["sx"], r["sy"]) / min(r["sx"], r["sy"]) - 100.0 if r["sx"] and r["sy"] else 0
        r["aspect_dev_pct"] = round(dev, 2)
        r["need_scale"] = [round(r["sx"], 4), round(r["sy"], 4)]
        print(f"{r['name']:<12} "
              f"{str(r['spec_size'][0]) + 'x' + str(r['spec_size'][1]):<14} "
              f"{str(r['ai_size'][0]) + 'x' + str(r['ai_size'][1]):<14} "
              f"{r['sx']:>8.4f} {r['sy']:>8.4f} {ratio:>7.4f}  {dev:>5.1f}%")
    print("-" * 74)
    worst = max(rows, key=lambda r: r["aspect_dev_pct"])
    print(f"[i] 统一缩放 = {scale:.4f} (中位数)")
    print(f"[i] 长宽比偏差最大: {worst['name']} {worst['aspect_dev_pct']:.1f}%")

    # ---- 分辨率系数
    res = 1.0
    if args.target_height:
        res = args.target_height / ch
        print(f"[i] 目标分辨率系数 = {res:.4f} -> "
              f"{int(round(cw * res))}x{int(round(ch * res))}")

    out_cw, out_ch = max(1, int(round(cw * res))), max(1, int(round(ch * res)))
    out_dir: Path = args.out_dir
    (out_dir / "parts_scaled").mkdir(parents=True, exist_ok=True)

    base_img = None
    bp = args.base_image or spec.get("base_image")
    if bp and Path(bp).is_file():
        base_img = Image.open(bp).convert("RGBA")
        if args.composite_base:
            canvas_im = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
            canvas_im.alpha_composite(base_img)
        else:
            canvas_im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    else:
        canvas_im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    # ---- 缩放模式: 在「贴合 spec 尺寸」与「保持部件自身长宽比(五官不变形)」之间取舍
    #   per-part : sx/sy 各自独立 -> 完全贴合 spec, 但会拉伸变形
    #   uniform  : 全部部件共用一个缩放 -> 不变形, 但整体尺寸未必贴合
    #   aspect   : 每件各自等比缩放(不变形), 比例由 --aspect-by 决定
    #   blend    : 对数空间插值, t=0 完全贴合 spec, t=1 完全不变形
    def solve_scale(r, ai_size):
        aw, ah = ai_size
        tw, th = r["spec_size"]
        sx_need, sy_need = tw / aw, th / ah
        if args.scale_mode == "uniform":
            s = scale
            return s, s
        t = spec_parts[r["name"]].get("aspect_weight", args.aspect_weight)
        if args.scale_mode == "per-part":
            t = 0.0
        elif args.scale_mode == "aspect":
            t = 1.0
        s_geo = (sx_need * sy_need) ** 0.5
        if args.scale_mode == "aspect" and args.aspect_by != "area":
            s_geo = {"h": sy_need, "w": sx_need}[args.aspect_by]
        sx = (sx_need ** (1 - t)) * (s_geo ** t)
        sy = (sy_need ** (1 - t)) * (s_geo ** t)
        return sx, sy

    # ---- 各件先算缩放(未乘分辨率), 再算「整体锁定」系数
    pre = {}
    for r in rows:
        pre[r["name"]] = solve_scale(r, sprites[r["name"]].size)

    def union_box(g):
        """把整体乘 g 后, 所有部件按 spec 中心摆放, 得到的并集 bbox。"""
        bx0 = by0 = 1e18
        bx1 = by1 = -1e18
        for r in rows:
            name = r["name"]
            aw, ah = sprites[name].size
            sx, sy = pre[name][0] * g, pre[name][1] * g
            nw, nh = aw * sx, ah * sy
            x0, y0, x1, y1 = r["spec_bbox"]
            al = spec_parts[name].get("align", args.align)
            tcx, tcy = (x0 + x1) / 2, (y0 + y1) / 2
            if al == "bottom":
                px, py = tcx - nw / 2, y1 - nh
            elif al == "top":
                px, py = tcx - nw / 2, y0
            elif al == "left":
                px, py = x0, tcy - nh / 2
            elif al == "right":
                px, py = x1 - nw, tcy - nh / 2
            else:
                px, py = tcx - nw / 2, tcy - nh / 2
            bx0, by0 = min(bx0, px), min(by0, py)
            bx1, by1 = max(bx1, px + nw), max(by1, py + nh)
        return bx0, by0, bx1, by1

    # spec 自身的整体 bbox
    sx0 = min(p["bbox"][0] for p in spec["parts"])
    sy0 = min(p["bbox"][1] for p in spec["parts"])
    sx1 = max(p["bbox"][2] for p in spec["parts"])
    sy1 = max(p["bbox"][3] for p in spec["parts"])

    lock = 1.0
    if args.lock_overall != "off":
        ux0, uy0, ux1, uy1 = union_box(1.0)
        uw, uh = ux1 - ux0, uy1 - uy0
        tw_, th_ = sx1 - sx0, sy1 - sy0
        gh, gw = th_ / uh, tw_ / uw
        if args.lock_overall == "h":
            lock = gh
        elif args.lock_overall == "w":
            lock = gw
        else:
            lock = (gh * gw) ** 0.5
        print(f"[i] 整体锁定: 拼合并集 {uw:.0f}x{uh:.0f} vs spec 整体 {tw_}x{th_} "
              f"-> g={lock:.4f} (mode={args.lock_overall})")
        ux0, uy0, ux1, uy1 = union_box(lock)
        print(f"[i] 锁定后并集 = {ux1-ux0:.0f}x{uy1-uy0:.0f}  "
              f"(spec {tw_}x{th_})")

    for r in rows:
        r["applied_scale"] = [round(pre[r["name"]][0] * lock * res, 4),
                              round(pre[r["name"]][1] * lock * res, 4)]

    placed = []
    for r in rows:
        name = r["name"]
        sp = sprites[name]
        sx = pre[name][0] * lock * res
        sy = pre[name][1] * lock * res
        nw = max(1, int(round(sp.width * sx)))
        nh = max(1, int(round(sp.height * sy)))
        r["aspect_weight"] = (None if args.scale_mode in ("uniform", "per-part")
                              else spec_parts[name].get("aspect_weight",
                                                         args.aspect_weight))
        sp2 = sp.resize((nw, nh), Image.LANCZOS)

        x0, y0, x1, y1 = [v * res for v in r["spec_bbox"]]
        tcx, tcy = (x0 + x1) / 2, (y0 + y1) / 2
        al = spec_parts[name].get("align", args.align)
        if al == "center":
            px, py = tcx - nw / 2, tcy - nh / 2
        elif al == "top":
            px, py = tcx - nw / 2, y0
        elif al == "bottom":
            px, py = tcx - nw / 2, y1 - nh
        elif al == "left":
            px, py = x0, tcy - nh / 2
        else:
            px, py = x1 - nw, tcy - nh / 2
        canvas_im.alpha_composite(sp2, (int(round(px)), int(round(py))))

        full = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        full.alpha_composite(sp2, (int(round(px)), int(round(py))))
        full = full.resize((out_cw, out_ch), Image.LANCZOS)
        full.save(out_dir / "parts_scaled" / f"{name}.png")
        placed.append(dict(name=name, size=[nw, nh], pos=[int(round(px)), int(round(py))],
                           scale=r["applied_scale"]))

    print("")
    print(f"{'name':<12} {'ai w x h':<14} {'placed w x h':<15} {'scale x':>8} "
          f"{'scale y':>8} {'xy比':>7} {'变形%':>7}")
    print("-" * 78)
    for r in sorted(rows, key=lambda q: spec_order[q["name"]]):
        p = next(q for q in placed if q["name"] == r["name"])
        scx, scy = r["applied_scale"]
        xy = scy / scx if scx else 0
        print(f"{r['name']:<12} "
              f"{str(r['ai_size'][0]) + 'x' + str(r['ai_size'][1]):<14} "
              f"{str(p['size'][0]) + 'x' + str(p['size'][1]):<15} "
              f"{scx:>8.4f} {scy:>8.4f} {xy:>7.4f} {abs(xy-1)*100:>6.1f}%")
    print("-" * 78)

    canvas_im = canvas_im.resize((out_cw, out_ch), Image.LANCZOS)
    canvas_im.save(out_dir / "composite.png")

    # ---- 拼合质量分(与原图逐像素比对, 用于多轮生成之间做客观对比)
    score = None
    if base_img is not None:
        ref = np.array(base_img.convert("RGBA").resize((out_cw, out_ch), Image.LANCZOS))
        got = np.array(canvas_im.convert("RGBA"))
        ra, ga = ref[:, :, 3] > 8, got[:, :, 3] > 8
        inter = int((ra & ga).sum())
        union = int((ra | ga).sum())
        score = dict(
            alpha_iou=round(inter / union, 4) if union else 0.0,
            coverage=round(inter / int(ra.sum()), 4) if ra.any() else 0.0,   # 原图被覆盖比例
            spill=round((int(ga.sum()) - inter) / int(ga.sum()), 4) if ga.any() else 0.0,
        )
        if inter:
            d = np.abs(ref[:, :, :3].astype(np.int16) - got[:, :, :3].astype(np.int16))
            score["color_mae"] = round(float(d[ra & ga].mean()), 2)
        print(f"[i] 拼合质量: alpha IoU={score['alpha_iou']:.4f}  "
              f"原图覆盖率={score['coverage']*100:.1f}%  "
              f"多出={score['spill']*100:.1f}%  "
              f"重叠区色差 MAE={score.get('color_mae', 'n/a')}")

    # ---- 对比图
    if base_img is not None:
        left = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
        left.alpha_composite(base_img)
        left = left.resize((out_cw, out_ch), Image.LANCZOS)
        right = Image.new("RGBA", (out_cw, out_ch), (255, 255, 255, 255))
        right.alpha_composite(canvas_im)
        gap = 12
        cmp_im = Image.new("RGB", (out_cw * 2 + gap, out_ch), (40, 40, 40))
        cmp_im.paste(left.convert("RGB"), (0, 0))
        cmp_im.paste(right.convert("RGB"), (out_cw + gap, 0))
        d = ImageDraw.Draw(cmp_im)
        f = font(max(14, out_cw // 22))
        d.rectangle([0, 0, 200, 30], fill=(0, 0, 0))
        d.text((8, 6), "original", fill=(255, 255, 255), font=f)
        d.rectangle([out_cw + gap, 0, out_cw + gap + 200, 30], fill=(0, 0, 0))
        d.text((out_cw + gap + 8, 6), "composite", fill=(255, 255, 255), font=f)
        cmp_im.save(out_dir / "compare.png")

    report = dict(
        parts_dir=str(args.parts_dir), spec=str(args.spec),
        canvas=[cw, ch], out_canvas=[out_cw, out_ch],
        global_scale=round(scale, 6), per_part=bool(args.per_part),
        anchor=args.anchor, target_height=args.target_height,
        align=args.align,
        matched=matched, only_spec=only_spec, only_ai=only_ai,
        score=score,
        parts=rows, placed=placed,
        worst_aspect_dev=dict(name=worst["name"], pct=worst["aspect_dev_pct"]),
        worst_aspect_dev_pct=worst["aspect_dev_pct"],
        mean_aspect_dev_pct=round(float(np.mean([r["aspect_dev_pct"] for r in rows])), 2),
    )
    (out_dir / "fit_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {out_dir}\\composite.png  compare.png  parts_scaled\\  fit_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
