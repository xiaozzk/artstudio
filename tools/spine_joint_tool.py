#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spine_joint_tool.py — 关节边缘精修：一体化工具（持续迭代都在这个文件里）

把原先散落的 20+ 个一次性脚本合并成一条流水线：

    analyze  →  cut  →  prep  →  prompt / gen  →  verify  →  apply  →  report

子命令
    analyze   量用户手绘套索带（两条边界、宽度、端点）
    cut       确定性椭圆切件（腿/躯干，含"缝隙中线分腿"与"避开内裤"判据）
    prep      生成 Meowa 任务输入图（灰底、统一比例）
    prompt    打印/写出标准 prompt（legs | arms）
    gen       调 Meowa CLI 发任务（默认一次 2 张）
    verify    对齐候选图并统计"允许区域内外"的改动量
    apply     只把允许区域从候选图合成回原图
    report    出预览图（贴图/差异图/放大图）

Prompt 经验（血泪版）
    1) 给局部特写当输入 → 模型会把零件粘成一个整体身体
    2) 给整张拼图 + 明说每块是独立图层 → 布局能保住
    3) 必须显式写 "each leg is ONE single piece - do not split it at the knee"
    4) prompt 里不能出现引号字符（PowerShell 包装层会拆碎参数），
       用  key = value; key = [a, b]  的结构化写法代替 JSON 引号
    5) 去背：image-edit-run --mode hd --remove-bg-method standard
       （HD 只支持 none/standard；--strict 只在 pixel 模式可用）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFile, ImageFilter

ImageFile.LOAD_TRUNCATED_IMAGES = True

# --------------------------------------------------------------------------- 路径与常量
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # D:\spine
SHEET = os.path.join(BASE, "meowa", "split_base_skin", "refs", "merged_sheet.png")
WORK = os.path.join(BASE, "meowa", "split_base_skin", "joints")
MEOWA = os.path.join(os.path.expanduser("~"), ".agents", "skills", "game-assets", "meowart_api.py")
GREY = 205
SS = 4                      # 切件栅格化超采样倍数
X_CROTCH = 257.0            # 两腿分界参考 x

# 允许改动的区域（y0, y1, x0, x1）
REGIONS = {
    "legs": (1430, 2520, 290, 1020),
    "arms": (900, 1720, 40, 400),        # 左臂列；右臂列由 mirror_region 推出
    "hip":  (1430, 1760, 300, 1010),
}

# --------------------------------------------------------------------------- 标准 prompt
PROMPTS = {
    "legs": (
        "Character parts sheet for a 2D skeletal animation rig. Every visible piece is a "
        "separate layer and the pieces must stay separate. Edit ONLY the top cut edge of the "
        "two legs. Each leg is ONE single piece from hip to ankle - do not split it at the knee "
        "and do not add any new seam or cut anywhere. Today each leg ends at the top with a "
        "straight angled cut that has a sharp corner and a dark outline. Replace only that top "
        "straight cut with a smooth shallow convex arc, like a shallow ball cap, so the leg can "
        "tuck under the pelvis. The new edge must be a clean flat cel-shaded edge: no dark "
        "outline, no shading, no bevel, no cross-section. Constraints: canvas = keep the input "
        "size and layout exactly; background = flat grey; edit = [top cut edge of the left leg "
        "becomes a smooth shallow convex arc, top cut edge of the right leg becomes a smooth "
        "shallow convex arc]; must_not_change = [hair, head, face, eyes, mouth, ear, torso, "
        "bikini, arms, hands, feet, knee, shin, ankle, everything below the top edge of each "
        "leg]; forbidden = [splitting a leg into two pieces, adding any new seam or cut, joining "
        "pieces together, closing the gaps between pieces, moving or resizing any piece, adding "
        "an outline on the new edge, adding shading on the new edge]."
    ),
    "arms": (
        "Character parts sheet for a 2D skeletal animation rig. Every visible piece is a "
        "separate layer and the pieces must stay separate. Edit ONLY the two arms. Each arm is "
        "ONE single piece from shoulder to wrist - do not split it anywhere and do not add any "
        "new seam or cut. The second reference image shows the refined hip and thigh joint, "
        "where the thigh ends in a smooth shallow convex arc with no dark outline. Apply that "
        "same joint style to each arm: reshape the shoulder end and the wrist end of each arm "
        "into the same kind of smooth shallow convex arc, so the arm can tuck under the torso "
        "shoulder and under the hand. The new edges must be clean flat cel-shaded edges: no dark "
        "outline, no shading, no bevel, no cross-section. Every piece must stay at exactly the "
        "same pixel position and size as the input - keep both arm bounding boxes identical. "
        "Constraints: canvas = keep the input size and layout exactly; background = flat grey; "
        "must_not_change = [hair, head, face, eyes, mouth, ear, torso, bikini, hands, legs, "
        "feet]; forbidden = [splitting an arm into two pieces, adding any new seam or cut, "
        "joining pieces together, closing the gaps between pieces, moving or resizing any piece, "
        "adding an outline on a new edge, adding shading on a new edge]."
    ),
}


# --------------------------------------------------------------------------- 基础工具
def load_rgba(path):
    return np.array(Image.open(path).convert("RGBA"))


def on_grey(box, arr, canvas=None, margin=0.0):
    """裁一块并合成到纯灰底（Meowa 的 image-2 需要不透明输入）。"""
    x0, y0, x1, y1 = box
    crop = arr[y0:y1, x0:x1].astype(float)
    al = crop[:, :, 3:4] / 255.0
    rgb = (crop[:, :, :3] * al + GREY * (1 - al)).astype(np.uint8)
    im = Image.fromarray(rgb)
    if canvas:
        cw, ch = canvas
        out = Image.new("RGB", (cw, ch), (GREY, GREY, GREY))
        out.paste(im, ((cw - im.width) // 2, (ch - im.height) // 2))
        return out
    px, py = int(im.width * margin), int(im.height * margin)
    out = Image.new("RGB", (im.width + 2 * px, im.height + 2 * py), (GREY, GREY, GREY))
    out.paste(im, (px, py))
    return out


def erode(mask, r):
    return np.array(Image.fromarray((mask * 255).astype(np.uint8))
                    .filter(ImageFilter.MinFilter(2 * r + 1))) > 128


def dilate(mask, r):
    return np.array(Image.fromarray((mask * 255).astype(np.uint8))
                    .filter(ImageFilter.MaxFilter(2 * r + 1))) > 128


def label(mask, min_area=200, cap=4000):
    """连通域（PIL 膨胀 BFS；够用且不依赖 scipy）。"""
    out, rem, n = [], mask.copy(), 0
    while rem.any() and n < cap:
        n += 1
        seed = np.argwhere(rem)[0]
        comp = np.zeros_like(mask)
        comp[seed[0], seed[1]] = True
        while True:
            grown = dilate(comp, 1) & rem
            if grown.sum() == comp.sum():
                break
            comp = grown
        rem &= ~comp
        if comp.sum() >= min_area:
            out.append(comp)
    return out


def bbox(m):
    ys, xs = np.where(m)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def hflip_region(reg, W):
    y0, y1, x0, x1 = reg
    return (y0, y1, W - x1, W - x0)


def build_region_mask(shape, regions):
    m = np.zeros(shape, bool)
    for y0, y1, x0, x1 in regions:
        m[y0:y1, x0:x1] = True
    return m


def align_candidate(orig, cand, search=2):
    """找最佳整数位移，返回 (对齐后的候选, dy, dx)。"""
    H, W = orig.shape[:2]
    best = None
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            c = np.zeros_like(orig)
            ys0, ys1 = max(0, dy), min(H, H + dy)
            xs0, xs1 = max(0, dx), min(W, W + dx)
            c[ys0:ys1, xs0:xs1] = cand[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
            d = np.abs(orig[:, :, 3].astype(int) - c[:, :, 3].astype(int))
            s = int((d > 32).sum())
            if best is None or s < best[0]:
                best = (s, dy, dx, c)
    return best[3], best[1], best[2]


def find_candidate(tag):
    hits = glob.glob(os.path.join(WORK, tag, "**", "remove_bg.png"), recursive=True)
    if not hits:
        hits = glob.glob(os.path.join(WORK, tag, "**", "*.png"), recursive=True)
    return hits[0] if hits else None


# --------------------------------------------------------------------------- 几何：确定性切件
def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def point_seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return dist(p, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5


def split_chains(poly):
    n = len(poly)
    best = (0, 0, -1.0)
    for a in range(n):
        for c in range(a + 1, n):
            dd = dist(poly[a], poly[c])
            if dd > best[2]:
                best = (a, c, dd)
    a, c, span = best
    fwd, k = [], a
    while k != c:
        fwd.append(poly[k])
        k = (k + 1) % n
    fwd.append(poly[c])
    bwd, k = [], a
    while k != c:
        bwd.append(poly[k])
        k = (k - 1) % n
    bwd.append(poly[c])
    return fwd, bwd, poly[a], poly[c], span


def max_chord_dev(chain):
    a, b = chain[0], chain[-1]
    return max(point_seg_dist(p, a, b) for p in chain)


def raster(polygon, W, H):
    m = Image.new("L", (W * SS, H * SS), 0)
    ImageDraw.Draw(m).polygon([(x * SS, y * SS) for x, y in polygon], fill=255)
    m = m.resize((W, H), Image.BOX)
    return np.asarray(m).astype(np.float32) / 255.0


# --------------------------------------------------------------------------- 子命令
def cmd_analyze(a):
    arr = load_rgba(a.sheet)
    W, H = arr.shape[1], arr.shape[0]
    body = arr[:, :, 3] > 8
    polys = [[tuple(q) for q in p] for p in json.load(open(a.selection, encoding="utf-8"))["subpaths"]]
    print("sheet %dx%d  body px=%d" % (W, H, int(body.sum())))
    for i, poly in enumerate(polys):
        fwd, bwd, p_a, p_c, span = split_chains(poly)
        dev = (max_chord_dev(fwd), max_chord_dev(bwd))
        side = "L" if min(q[0] for q in poly) < 250 else "R"
        print("  band %s: n=%d ends %s -> %s span=%.1f  chain dev=%.1f/%.1f"
              % (side, len(poly), p_a, p_c, span, dev[0], dev[1]))
    return 0


def cmd_prep(a):
    arr = load_rgba(a.sheet)
    H, W = arr.shape[:2]
    os.makedirs(a.out_dir, exist_ok=True)
    full = on_grey((0, 0, W, H), arr)
    full.save(os.path.join(a.out_dir, "sheet_grey.png"))
    print("sheet_grey.png", full.size)
    for name, box in (("leg_joint_in", (318, 1380, 1022, 1776)),
                      ("arm_joint_in", (90, 860, 1263, 1520))):
        im = on_grey(box, arr)
        im.save(os.path.join(a.out_dir, name + ".png"))
        print("%s.png %s" % (name, im.size))
    return 0


def cmd_prompt(a):
    txt = PROMPTS[a.part]
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt + "\n")
        print("wrote", a.out)
    print(txt)
    return 0


def cmd_gen(a):
    prompt = PROMPTS[a.part]
    refs = ["--reference-image", os.path.join(WORK, "sheet_grey.png")]
    if a.part == "arms":
        ref = os.path.join(WORK, "joint_ref_legs.png")
        if os.path.exists(ref):
            refs += ["--reference-image", ref]
    for i in range(a.runs):
        out = os.path.join(WORK, "job_%s_%s%d" % (a.part, a.tag, i + 1))
        cmd = [sys.executable, MEOWA, "image-edit-run", "--mode", "hd",
               "--generation-model", a.model, "--resolution", a.resolution,
               "--quality", a.quality, "--remove-bg-method", a.remove_bg] + refs + \
              ["--prompt", prompt, "--output-dir", out]
        print("[run %d/%d] -> %s" % (i + 1, a.runs, out))
        subprocess.run(cmd, check=False)
    return 0


def cmd_verify(a):
    orig = load_rgba(a.sheet)
    H, W = orig.shape[:2]
    cand = load_rgba(a.candidate)
    if cand.shape[0] != H or cand.shape[1] != W:
        t = np.zeros_like(orig)
        h, w = min(H, cand.shape[0]), min(W, cand.shape[1])
        t[:h, :w] = cand[:h, :w]
        cand = t
    cand, dy, dx = align_candidate(orig, cand)
    regs = [REGIONS[r] if r in REGIONS else tuple(int(v) for v in r.split(",")) for r in a.region]
    if a.part == "arms":
        regs.append(hflip_region(REGIONS["arms"], W))
    mask = build_region_mask((H, W), regs)
    d = np.abs(orig[:, :, 3].astype(int) - cand[:, :, 3].astype(int))
    ch = d > a.thresh
    info = {"aligned": [dy, dx], "changed_total": int(ch.sum()),
            "changed_inside": int((ch & mask).sum()),
            "changed_outside": int((ch & ~mask).sum())}
    print(json.dumps(info, indent=2))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
    return 0


def cmd_apply(a):
    orig = load_rgba(a.sheet)
    H, W = orig.shape[:2]
    cand = load_rgba(a.candidate)
    if cand.shape[0] != H or cand.shape[1] != W:
        t = np.zeros_like(orig)
        h, w = min(H, cand.shape[0]), min(W, cand.shape[1])
        t[:h, :w] = cand[:h, :w]
        cand = t
    cand, dy, dx = align_candidate(orig, cand)
    regs = [tuple(int(v) for v in r.split(",")) if r not in REGIONS else REGIONS[r] for r in a.region]
    if a.part == "arms":
        regs.append(hflip_region(REGIONS["arms"], W))
    mask = build_region_mask((H, W), regs)
    out = orig.copy()
    out[mask] = cand[mask]
    Image.fromarray(out, "RGBA").save(a.out)
    print("wrote %s   (aligned dy=%d dx=%d, replaced %d px)"
          % (a.out, dy, dx, int(mask.sum())))
    return 0


def cmd_report(a):
    orig = load_rgba(a.sheet)
    H, W = orig.shape[:2]
    os.makedirs(a.out_dir, exist_ok=True)
    cand = load_rgba(a.candidate)
    if cand.shape[0] != H or cand.shape[1] != W:
        t = np.zeros_like(orig)
        h, w = min(H, cand.shape[0]), min(W, cand.shape[1])
        t[:h, :w] = cand[:h, :w]
        cand = t
    cand, dy, dx = align_candidate(orig, cand)
    y0, y1, x0, x1 = (tuple(int(v) for v in a.box.split(",")))
    z = a.zoom

    def flat(x):
        al = x[:, :, 3:4] / 255.0
        return (x[:, :, :3] * al + 255 * (1 - al)).astype(np.uint8)

    panels = [(a.box, flat(orig)), (a.box, flat(cand))]
    ims = []
    for _, f in panels:
        img = Image.fromarray(f[y0:y1, x0:x1]).resize(((x1 - x0) * z, (y1 - y0) * z), Image.LANCZOS)
        ims.append(img)
    d = np.abs(orig[:, :, 3].astype(int) - cand[:, :, 3].astype(int)) > 32
    df = flat(orig).copy()
    df[d] = [255, 0, 0]
    ims.append(Image.fromarray(df[y0:y1, x0:x1]).resize(((x1 - x0) * z, (y1 - y0) * z), Image.LANCZOS))
    cw = sum(i.width for i in ims) + 20 * (len(ims) - 1)
    canvas = Image.new("RGB", (cw, ims[0].height), (255, 255, 255))
    x = 0
    for i in ims:
        canvas.paste(i, (x, 0))
        x += i.width + 20
    p = os.path.join(a.out_dir, "report_%s.png" % os.path.splitext(os.path.basename(a.candidate))[0])
    canvas.save(p)
    print("wrote", p, canvas.size, " (original | candidate | red = changed)")
    return 0


def keep_large(mask, min_area):
    out = np.zeros_like(mask)
    for c in label(mask, min_area=min_area):
        out |= c
    return out


def extend_outward(p_end, p_next, body, W, H, margin=18.0, cap=400.0):
    dx, dy = p_end[0] - p_next[0], p_end[1] - p_next[1]
    L = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / L, dy / L
    t = 0.0
    while t < cap:
        x, y = int(round(p_end[0] + ux * t)), int(round(p_end[1] + uy * t))
        if not (0 <= x < W and 0 <= y < H) or not body[y, x]:
            break
        t += 2.0
    t += margin
    return (p_end[0] + ux * t, p_end[1] + uy * t)


def build_split_line(body, H, W, y_start, x_hint):
    """两腿分界 = 大腿缝隙的中线（先腐蚀让贴合处分开，再逐行取缝隙中心）。"""
    er = erode(body, 4)
    pts, last = [], float(x_hint)
    for y in range(y_start, H):
        row, runs, x = er[y], [], 20
        while x < W - 20:
            if not row[x]:
                s = x
                while x < W - 20 and not row[x]:
                    x += 1
                runs.append((s, x - 1))
            else:
                x += 1
        if runs:
            best = min(runs, key=lambda r: abs(0.5 * (r[0] + r[1]) - last))
            c = 0.5 * (best[0] + best[1])
            if abs(c - last) < 40.0:
                last = c
        pts.append((last, float(y)))
    xs = np.array([p[0] for p in pts], float)
    if len(xs) > 9:
        xs = np.convolve(np.pad(xs, (4, 4), mode="edge"), np.ones(9) / 9.0, mode="valid")
    return [(float(p), float(q[1])) for p, q in zip(xs, pts)]


def legside_polygon(arc, side, axis_point, split, body, W, H):
    ext = extend_outward(arc[0], axis_point, body, W, H)
    bot = H + 30
    tail = [p for p in split if p[1] >= arc[-1][1] - 0.5]
    sx = tail[-1][0] if tail else X_CROTCH
    if side == "L":
        tail = tail + [(sx, bot), (-80.0, bot), (-80.0, ext[1] - 80.0)]
    else:
        tail = tail + [(sx, bot), (W + 80.0, bot), (W + 80.0, ext[1] - 80.0)]
    return [ext] + list(arc) + tail


def arc_points(c, aa, bb, v1, n, which, npts=96):
    ts = np.linspace(np.pi, 0.0, npts) if which == "upper" else np.linspace(np.pi, 2 * np.pi, npts)
    return [tuple(c + aa * np.cos(t) * v1 + bb * np.sin(t) * n) for t in ts]


def cmd_cut(a):
    arr = load_rgba(a.sheet)
    H, W = arr.shape[:2]
    body = arr[:, :, 3] > 8
    polys = [[tuple(q) for q in p] for p in
             json.load(open(a.selection, encoding="utf-8"))["subpaths"]]

    ri, bi = arr[:, :, 0].astype(np.int16), arr[:, :, 2].astype(np.int16)
    skin = body & (ri - bi > 10) & (ri > 190)
    hip = np.zeros_like(body)
    hip[525:830, :] = True
    forbd = erode(body, 3) & (~skin) & hip
    raw = int(forbd.sum())
    forbd = keep_large(forbd, 150)                 # 丢掉软阴影抗锯齿杂点
    print("underwear mask: raw=%d  kept=%d" % (raw, int(forbd.sum())))
    forbd = dilate(forbd, a.clear)

    bands = {}
    for poly in polys:
        fwd, bwd, p_a, p_c, span = split_chains(poly)
        dev_f, dev_b = max_chord_dev(fwd), max_chord_dev(bwd)
        A = fwd if dev_f >= dev_b else bwd
        side = "L" if min(q[0] for q in poly) < 250 else "R"
        hp, cp = (p_a, p_c) if p_a[1] <= p_c[1] else (p_c, p_a)
        v1 = np.array([cp[0] - hp[0], cp[1] - hp[1]], float)
        L = float(np.linalg.norm(v1)); v1 /= L
        n = np.array([-v1[1], v1[0]])
        if n[1] > 0:
            n = -n
        wmax = max(abs((p[0] - hp[0]) * n[0] + (p[1] - hp[1]) * n[1]) for p in A)
        bands[side] = dict(side=side, v1=v1, n=n, a=L / 2.0, b=wmax / 2.0 * a.b_scale,
                           base_centre=(np.array(hp, float) + np.array(cp, float)) / 2.0)
        print("band %s  chord %s -> %s  a=%.1f b=%.1f (drawn width %.1f)"
              % (side, hp, cp, L / 2.0, bands[side]["b"], wmax))

    split = build_split_line(body, H, W, 690, X_CROTCH)

    deltas = {}
    for side, bd in bands.items():
        e = -bd["n"]
        chosen = None
        for d in range(0, 121):
            c = bd["base_centre"] + d * e
            up = arc_points(c, bd["a"], bd["b"], bd["v1"], bd["n"], "upper")
            m = raster(legside_polygon(up, side, c, split, body, W, H), W, H) > 0.5
            if int((body & m & forbd).sum()) == 0:
                chosen = d
                break
        deltas[side] = 120 if chosen is None else chosen
        print("band %s pushed %d px toward the leg (clear of underwear)" % (side, deltas[side]))

    centres = {s: bands[s]["base_centre"] + deltas[s] * (-bands[s]["n"]) for s in bands}
    arcs = {}
    for s, bd in bands.items():
        arcs[s] = (arc_points(centres[s], bd["a"], bd["b"], bd["v1"], bd["n"], "upper"),
                   arc_points(centres[s], bd["a"], bd["b"], bd["v1"], bd["n"], "lower"))

    def legside(arc, side):
        return raster(legside_polygon(arc, side, centres[side], split, body, W, H), W, H) > 0.5

    legL = body & legside(arcs["L"][0], "L")
    legR = body & legside(arcs["R"][0], "R")
    torso = body & ~(legside(arcs["L"][1], "L") | legside(arcs["R"][1], "R"))
    union = torso | legL | legR
    print("\ntorso=%d  leg_L=%d  leg_R=%d  overlap=%d"
          % (torso.sum(), legL.sum(), legR.sum(), int(((torso & legL) | (torso & legR)).sum())))
    print("union missing=%d   underwear px inside legs=%d   (both must be 0)"
          % (int((body & ~union).sum()), int(((legL | legR) & forbd).sum())))

    os.makedirs(a.out_dir, exist_ok=True)
    for name, m in (("torso", torso), ("leg_L", legL), ("leg_R", legR)):
        alpha = arr[:, :, 3].astype(np.float32) * m.astype(np.float32)
        Image.fromarray(np.dstack([arr[:, :, :3], alpha.astype(np.uint8)]), "RGBA") \
             .save(os.path.join(a.out_dir, "body_%s.png" % name))
    parts = []
    for side, (up, lo) in arcs.items():
        ring = up + list(reversed(lo))
        parts.append("%s:[%s]" % (side, ",".join("[%.2f,%.2f]" % (p[0], p[1]) for p in ring)))
    with open(os.path.join(a.out_dir, "ellipse_data.jsx"), "w", encoding="utf-8") as f:
        f.write("({" + ",".join(parts) + "})")
    print("wrote body_torso/body_leg_L/body_leg_R + ellipse_data.jsx ->", a.out_dir)
    return 0


def cmd_diff(a):
    """诊断两张图的差异性质：真改动 / 预乘 alpha / 编码差异 / 整体位移。"""
    A = load_rgba(a.a).astype(np.int16)
    B = load_rgba(a.b).astype(np.int16)
    if A.shape != B.shape:
        print("尺寸不同 %s vs %s，按左上对齐比较公共区域" % (A.shape[:2], B.shape[:2]))
    h, w = min(A.shape[0], B.shape[0]), min(A.shape[1], B.shape[1])
    A, B = A[:h, :w], B[:h, :w]
    da = np.abs(A[:, :, 3] - B[:, :, 3])
    drgb = np.abs(A[:, :, :3] - B[:, :, :3]).max(2)
    opaque = (A[:, :, 3] > 250) & (B[:, :, 3] > 250)
    both_t = (A[:, :, 3] == 0) & (B[:, :, 3] == 0)
    print("alpha 不同 px       : %d (max %d, >128: %d)" % (int((da > 0).sum()), int(da.max()), int((da > 128).sum())))
    mo = int(opaque.sum())
    print("共同不透明区 px     : %d" % mo)
    if mo:
        print("  其中 RGB 差 > 8   : %d" % int((drgb[opaque] > 8).sum()))
        print("  其中 RGB 差 > 32  : %d" % int((drgb[opaque] > 32).sum()))
        print("  平均 RGB 差       : %.2f" % float(drgb[opaque].mean()))
    tt = int((drgb[both_t] > 0).sum())
    print("共同透明区 RGB 差异 : %d  （预乘 alpha / 元数据差异，不影响视觉）" % tt)
    best = None
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            sh = np.roll(np.roll(B, dy, 0), dx, 1)
            m = (A[:, :, 3] > 250) & (sh[:, :, 3] > 250)
            if not m.any():
                continue
            d = float(np.abs(A[:, :, :3] - sh[:, :, :3]).max(2)[m].mean())
            if best is None or d < best[0]:
                best = (d, dy, dx)
    if best:
        print("最佳整体位移        : dy=%d dx=%d  → 平移后平均 RGB 差 %.2f" % (best[1], best[2], best[0]))
    big = int((drgb[opaque] > 32).sum()) if mo else 0
    print("判定                : %s" % ("只有编码/预乘/位移级差异" if big < 500 else "存在真实内容改动"))
    return 0


def cmd_overview(a):
    """把一轮的多个候选拼成带标注的总览图，便于挑选。"""
    cands = []
    for pat in a.candidates:
        cands += sorted(glob.glob(pat, recursive=True))
    cands = [c for c in cands if os.path.isfile(c)]
    if not cands:
        print("没有匹配到候选图")
        return 1
    cell = a.cell
    cols = a.cols
    rows_n = (len(cands) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell + 8 * (cols + 1), rows_n * (cell + 34) + 8), (24, 24, 28))
    d = ImageDraw.Draw(canvas)
    for i, p in enumerate(cands):
        cx = 8 + (i % cols) * (cell + 8)
        cy = 8 + (i // cols) * (cell + 34)
        im = load_rgba(p)
        al = im[:, :, 3:4] / 255.0
        flat = Image.fromarray((im[:, :, :3] * al + 245 * (1 - al)).astype(np.uint8))
        flat.thumbnail((cell, cell), Image.LANCZOS)
        canvas.paste(flat, (cx + (cell - flat.width) // 2, cy + 26))
        tag = os.path.basename(os.path.dirname(p)) or os.path.basename(p)
        d.text((cx + 4, cy + 6), "%d) %s" % (i + 1, tag[:44]), fill=(140, 220, 255))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    canvas.save(a.out)
    print("wrote %s  (%d candidates) %s" % (a.out, len(cands), canvas.size))
    return 0


# --------------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="Spine joint-edge refinement tool (one-stop)")
    ap.add_argument("--sheet", default=SHEET)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("analyze", help="量套索带")
    s.add_argument("--selection", required=True)
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("prep", help="生成任务输入图（灰底）")
    s.add_argument("--out-dir", default=WORK)
    s.set_defaults(func=cmd_prep)

    s = sub.add_parser("cut", help="确定性椭圆切件（腿/躯干）")
    s.add_argument("--selection", required=True, help="套索带 polygon json")
    s.add_argument("--out-dir", required=True)
    s.add_argument("--b-scale", type=float, default=1.0, help="椭圆短半轴缩放")
    s.add_argument("--clear", type=int, default=3, help="避开内裤的余量 px")
    s.set_defaults(func=cmd_cut)

    s = sub.add_parser("prompt", help="打印标准 prompt")
    s.add_argument("--part", choices=list(PROMPTS), default="legs")
    s.add_argument("--out")
    s.set_defaults(func=cmd_prompt)

    s = sub.add_parser("gen", help="发 Meowa 任务")
    s.add_argument("--part", choices=list(PROMPTS), default="legs")
    s.add_argument("--runs", type=int, default=2)
    s.add_argument("--tag", default="r1")
    s.add_argument("--model", default="image-2")
    s.add_argument("--resolution", default="2K")
    s.add_argument("--quality", default="ultimate")
    s.add_argument("--remove-bg", default="standard")
    s.set_defaults(func=cmd_gen)

    s = sub.add_parser("verify", help="对齐并统计改动量")
    s.add_argument("--candidate", required=True)
    s.add_argument("--region", nargs="+", default=["legs"],
                   help="内置名 legs/arms/hip，或 y0,y1,x0,x1")
    s.add_argument("--part", default="legs")
    s.add_argument("--thresh", type=int, default=32)
    s.add_argument("--json")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("apply", help="只把允许区域合成回原图")
    s.add_argument("--candidate", required=True)
    s.add_argument("--region", nargs="+", default=["legs"])
    s.add_argument("--part", default="legs")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("report", help="出预览图")
    s.add_argument("--candidate", required=True)
    s.add_argument("--box", required=True, help="y0,y1,x0,x1")
    s.add_argument("--zoom", type=int, default=2)
    s.add_argument("--out-dir", default=WORK)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("diff", help="诊断两图差异性质（真改动/预乘/位移）")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("overview", help="多样本总览图")
    s.add_argument("--candidates", nargs="+", required=True, help="glob 模式，可多个")
    s.add_argument("--out", required=True)
    s.add_argument("--cell", type=int, default=430)
    s.add_argument("--cols", type=int, default=4)
    s.set_defaults(func=cmd_overview)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
