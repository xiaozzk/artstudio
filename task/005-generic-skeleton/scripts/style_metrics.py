# -*- coding: utf-8 -*-
"""美术风格量化：头身比标尺 / 复杂度 / 归一化并排对比。

用法（工作区根运行）::

    python task/005-generic-skeleton/scripts/style_metrics.py measure <img> [<img> ...] \
        [--ruler-dir DIR] [--hair teal|light]
    python task/005-generic-skeleton/scripts/style_metrics.py compare <out.png> <img> [<img> ...]

口径
----
**头身比** = (脚底 − 发顶) / (下巴 − 发顶)，与 `refs/proportion-6.7head.json` 同口径：

* 发顶 = 头部区域内**头发**掩码的最高点（角 / 发饰不算）
  `teal` = 青色系（g > r+15，龙娘青发）；`light` = 浅色低饱和（min>150 且 max−min<60，白发/银发）
* 下巴 = 头部区域内**肤色**掩码的最低点（r>150 且 35<r−b<130）
* 脚底 = 前景最低点

**复杂度**（都先把人物按身高归一化到同一画布再测，越低越简单）：

* `edge`    Canny(60,160) 边缘像素 / 身高 —— 每单位身高的线条量
* `colors`  占人物 ≥0.2% 面积的 16 级量化色数
* `patches` 量化色连通块数（≥0.1% 面积）—— ≈「要切出来的色块量」

⚠ 前景判定用「alpha>16 且与四角底色距离>60」。深色**渐晕底**的老图会被多算一点，
读数偏保守；透明底（本流水线生成物）精确。

⚠ 头身比对「头发在头顶上方挑得很高」的角色会偏小（发顶被抬高），跨图比较时留意。
"""
import argparse
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw

TARGET_H = 900


# ---------------------------------------------------------------- 前景 / 掩码

def figure_mask(a, close=7):
    """前景 = alpha>16 且离四角底色足够远；取最大连通域。"""
    al = a[..., 3]
    corners = np.concatenate([a[0:8, 0:8].reshape(-1, 4), a[0:8, -8:].reshape(-1, 4),
                              a[-8:, 0:8].reshape(-1, 4), a[-8:, -8:].reshape(-1, 4)])
    bgc = np.median(corners[:, :3], axis=0)
    d = np.abs(a[..., :3].astype(np.int16) - bgc).sum(axis=2)
    fg = ((al > 16) & (d > 60)).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((close, close), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if n > 1:
        fg = (lab == 1 + int(np.argmax(stats[1:, 4]))).astype(np.uint8)
    return fg.astype(bool)


def hair_mask(a, fg, head, kind):
    r, g, b = (a[..., i].astype(np.int16) for i in range(3))
    if kind == "light":
        mn, mx = a[..., :3].min(axis=2).astype(np.int16), a[..., :3].max(axis=2).astype(np.int16)
        return fg & head & (mn > 150) & ((mx - mn) < 60)
    # teal：阈值故意偏严（g−r>40），否则「青色渐晕底」的老图会被当成头发把发顶抬高
    return fg & head & (g > r + 40) & (g > 80)


def skin_mask(a, fg, head):
    r, g, b = (a[..., i].astype(np.int16) for i in range(3))
    return fg & head & (r > 150) & ((r - b) > 35) & ((r - b) < 130) & (g > r - 100) & (g < r - 5)


def face_chin(skin, min_area):
    """取「最靠上」的显著肤色块（= 脸），返回 (x, y, w, h, area)，h 到下巴为止。

    比「取最大块」稳：大块常常是胸/手臂的皮肤，会把头高撑大、头身比压小。
    若该块把脖子/胸也连进来了（下半段先收窄再变宽），在**下半段找宽度极小处**
    = 脖子，作为下巴的代理；脸是独立块时极小处就是底边，等价。
    """
    n, lab, stats, _ = cv2.connectedComponentsWithStats(skin.astype(np.uint8), connectivity=8)
    cand = [i for i in range(1, n) if stats[i, 4] >= min_area]
    if not cand:
        return None
    i = min(cand, key=lambda k: stats[k, 1])            # 最靠上 = 脸
    x, y, w, h, area = (int(v) for v in stats[i])
    rows = (lab[y:y + h] == i).sum(axis=1)
    lo = int(0.45 * h)
    if lo < h - 1:
        chin = y + lo + int(np.argmin(rows[lo:]))
    else:
        chin = y + h
    return np.array([x, y, w, max(1, chin - y), area])


def landmarks(path, hair_kind="teal"):
    a = np.array(Image.open(path).convert("RGBA"))
    fg = figure_mask(a)
    ys, _ = np.nonzero(fg)
    top, bot = int(ys.min()), int(ys.max())
    head = np.zeros_like(fg)
    head[top:top + int(0.45 * (bot - top + 1))] = True

    hair = hair_mask(a, fg, head, hair_kind)
    if not hair.any() and hair_kind != "light":          # 兜底：青发没找到就试浅色
        hair = hair_mask(a, fg, head, "light")
    skin = skin_mask(a, fg, head)
    hys = np.nonzero(hair)[0]
    hair_top = int(hys.min()) if len(hys) else top
    ss = face_chin(skin, min_area=max(150, 0.002 * fg.sum()))
    chin = int(ss[1] + ss[3]) if ss is not None else top
    sole = bot
    head_h = chin - hair_top
    ratio = (sole - hair_top) / head_h if head_h > 0 else float("nan")
    return dict(a=a, fg=fg, hair_top=hair_top, chin=chin, sole=sole,
                head_h=head_h, ratio=ratio,
                hair_box=box(hair), skin_box=ss)


def biggest(m):
    n, _, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n <= 1:
        return None
    return stats[1 + int(np.argmax(stats[1:, 4]))]


def box(m):
    ys, xs = np.nonzero(m)
    if not len(ys):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


# ---------------------------------------------------------------- 复杂度

def complexity(path):
    a = np.array(Image.open(path).convert("RGBA"))
    fg = figure_mask(a)
    ys, xs = np.nonzero(fg)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    h = y1 - y0
    s = TARGET_H / h
    crop = Image.fromarray(a[y0:y1, x0:x1])
    crop = crop.resize((max(1, int(crop.width * s)), TARGET_H), Image.LANCZOS)
    canvas = Image.new("RGBA", (crop.width + 40, TARGET_H + 40), (30, 34, 42, 255))
    canvas.alpha_composite(crop, (20, 20))
    b = np.array(canvas.convert("RGB"))
    cm = np.array(canvas)[..., 3] > 16

    edges = cv2.Canny(cv2.cvtColor(b, cv2.COLOR_RGB2GRAY), 60, 160) > 0
    qq = b[cm].astype(np.int32) // 16
    uniq, cnt = np.unique(qq, axis=0, return_counts=True)
    colors = int((cnt >= 0.002 * cm.sum()).sum())

    qmap = np.zeros(b.shape[:2], np.int32) - 1
    qmap[cm] = qq[:, 0] * 10000 + qq[:, 1] * 100 + qq[:, 2]
    patches = 0
    for v in np.unique(qmap[cm]):
        m = (qmap == v).astype(np.uint8)
        n2, _, st2, _ = cv2.connectedComponentsWithStats(m, connectivity=4)
        if n2 > 1:
            patches += int((st2[1:, 4] >= 0.001 * cm.sum()).sum())

    return dict(w=int(crop.width), h=TARGET_H, edge=edges.sum() / TARGET_H,
                colors=colors, patches=patches)


# ---------------------------------------------------------------- 输出

def draw_ruler(info, path, outdir):
    a, hair_top, chin, sole, head_h = (info["a"], info["hair_top"], info["chin"],
                                       info["sole"], info["head_h"])
    im = Image.fromarray(a).convert("RGB")
    if head_h <= 10:
        im.save(os.path.join(outdir, "ruler-" + os.path.basename(path)))
        return None
    d = ImageDraw.Draw(im)
    for y, c in ((hair_top, (255, 80, 80)), (chin, (80, 200, 255)), (sole, (120, 255, 120))):
        d.line([(0, y), (im.width, y)], fill=c, width=3)
    k = 1
    while hair_top + k * head_h <= sole:
        y = hair_top + k * head_h
        d.line([(0, y), (28, y)], fill=(255, 255, 0), width=2)
        d.text((32, y - 6), str(k), fill=(255, 255, 0))
        k += 1
    out = os.path.join(outdir, "ruler-" + os.path.splitext(os.path.basename(path))[0] + ".png")
    im.save(out)
    return out


def cmd_measure(args):
    for p in args.images:
        info = landmarks(p, args.hair)
        cx = complexity(p)
        print(f"{os.path.basename(p)}")
        print(f"  头身比 {info['ratio']:.2f}  (发顶={info['hair_top']} 下巴={info['chin']} "
              f"脚底={info['sole']} 头高={info['head_h']})")
        print(f"  复杂度 edge/身高={cx['edge']:.2f} colors={cx['colors']} patches={cx['patches']}")
        if args.ruler_dir:
            os.makedirs(args.ruler_dir, exist_ok=True)
            out = draw_ruler(info, p, args.ruler_dir)
            if out:
                print(f"  标尺图 {out}")


def cmd_compare(args):
    ims = []
    for p in args.images:
        a = np.array(Image.open(p).convert("RGBA"))
        fg = figure_mask(a)
        ys, xs = np.nonzero(fg)
        c = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
        c[..., 3] = np.where(fg[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 255, 0)
        im = Image.fromarray(c)
        s = 780 / im.height
        ims.append(im.resize((max(1, int(im.width * s)), 780), Image.LANCZOS))
    pad, gap = 36, 56
    W = pad * 2 + sum(i.width for i in ims) + gap * (len(ims) - 1)
    canvas = Image.new("RGBA", (W, pad * 2 + 780), (34, 38, 46, 255))
    x = pad
    for im in ims:
        canvas.alpha_composite(im, (x, pad))
        x += im.width + gap
    canvas.convert("RGB").save(args.out)
    print("saved", args.out, canvas.size)


def main():
    ap = argparse.ArgumentParser(description="美术风格量化（头身比 / 复杂度 / 并排对比）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="量头身比与复杂度")
    m.add_argument("images", nargs="+")
    m.add_argument("--hair", choices=["teal", "light"], default="teal", help="发色口径（默认 teal）")
    m.add_argument("--ruler-dir", default=None, help="输出标尺核对图的目录")
    m.set_defaults(func=cmd_measure)
    c = sub.add_parser("compare", help="按身高归一化并排拼图")
    c.add_argument("out")
    c.add_argument("images", nargs="+")
    c.set_defaults(func=cmd_compare)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
