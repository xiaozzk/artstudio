# -*- coding: utf-8 -*-
"""Spine 图集修复 / 升版 一体化流水线（由原 5 个模块合并而成）。

阶段严格分开、互不覆盖：

    <proj>/prepare/   prepare 产物：源版本三件套 + images_original/ + 预览
    <proj>/convert/   convert 产物：目标版本三件套 + 预览
    <proj>/*.json     顶层：apply 之后的交付件

一条命令跑完：  python pipelines.py build <源zip> -o <工程目录>
"""

import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage


# ==========================================================================
# 来源: spine_atlas.py
# ==========================================================================
# -*- coding: utf-8 -*-
"""Spine .atlas 文本解析 / 写出。

要点（全部实测踩过）：
* 块头判定靠冒号：带冒号的行是属性，不带冒号的非空行是「页名」或「区域名」。
* 空行表示**换页**，不是换区域。因此写出时，页属性之后**绝不能有空行**，
  否则官方解析器会把第一个区域名当成新页名。
* 两套键名都要认：新式 `bounds` / `offsets`，旧式 `xy`+`size` / `offset`+`orig`。
* 旋转区域的页内占位矩形是**宽高互换**的（deg 90/270）。
* y 是**从页图上边缘向下**量的（实测穷举 8 种约定后确认）。
"""


_ROT = {'true': 90, '90': 90, '180': 180, '270': 270, 'false': 0, '0': 0}

IMG_EXTS = ('.png', '.webp', '.jpg', '.jpeg', '.tga', '.bmp')


def resolve_page_image(atlas_path, page):
    """找页图文件，**容忍页名后缀与实际文件不符**。

    实测踩过：atlas 页名写成 `Kimchul.webp`，但压缩包里只给了 `Kimchul.png`。
    按页名硬拼路径会找不到文件，调用方若静默跳过，体检就直接漏掉整个页。
    """
    d = os.path.dirname(atlas_path)
    exact = os.path.join(d, page['name'])
    if os.path.isfile(exact):
        return exact
    stem = os.path.splitext(page['name'])[0]
    for e in IMG_EXTS:
        c = os.path.join(d, stem + e)
        if os.path.isfile(c):
            return c
    try:                                    # 再试大小写不敏感
        low = {f.lower(): f for f in os.listdir(d)}
    except OSError:
        return None
    f = low.get(page['name'].lower()) or low.get((stem + '.png').lower())
    return os.path.join(d, f) if f else None


def rewrite_page_names(path, mapping):
    """只在**页头**位置改页名（区域名同样不带冒号，不能误伤）。"""
    lines = open(path, encoding='utf-8').read().split('\n')
    i, n = 0, len(lines)
    while i < n:                            # 跳过文件头属性行
        s = lines[i].strip()
        if s and ':' not in s:
            break
        i += 1
    in_page = False
    while i < n:
        s = lines[i].strip()
        if s == '':
            in_page = False
        elif ':' not in s:
            if not in_page and s in mapping:
                lines[i] = mapping[s]
            in_page = True
        i += 1
    open(path, 'w', encoding='utf-8').write('\n'.join(lines))


def set_page_size(path, page_name, w, h):
    """改某页的 `size:` —— **只改页头那一条**。

    ⚠️ 老式（3.8）atlas 里**每个区域也有 `size:`**（该区域的打包尺寸），格式是
    缩进的 `  size: 88, 121`。原实现用 `cur`/`in_page` 追踪"当前页"，但老式 atlas
    的结构是「页名 → 页属性 → 区域名 → 区域属性 → 区域名 …」且**区域之间没有空行**，
    于是 `in_page` 永远不回 False、`cur` 也永远停在页名 —— 结果**每个区域的
    `size:` 都被改成了页尺寸**（实测 axe：29 条 size 行改了 28 条区域行），
    区域矩形随之全部越界/重叠，去污染与网格体检全盘失效。

    修法：状态机改成"页名字段之后、第一个区域名之前的属性行才属于页头"。
    """
    lines = open(path, encoding='utf-8').read().split('\n')
    n = len(lines)
    i = 0
    while i < n:                            # 跳过文件头属性行
        s = lines[i].strip()
        if s and ':' not in s:
            break
        i += 1
    cur = None                              # 当前页名
    in_page_props = False                   # 正处在"页头属性"段
    while i < n:
        s = lines[i].strip()
        if s == '':
            cur, in_page_props = None, False
        elif ':' in s:
            if in_page_props and cur == page_name:
                if s.split(':', 1)[0].strip() == 'size':
                    lines[i] = 'size:%d,%d' % (w, h)
        else:
            if cur is None:
                cur, in_page_props = s, True    # 页名 -> 其后是页头属性
            else:
                in_page_props = False           # 区域名 -> 其后是区域属性
        i += 1
    open(path, 'w', encoding='utf-8').write('\n'.join(lines))


def parse_atlas(path):
    """-> [ {name, props:{}, regions:[{...}]} ]"""
    lines = open(path, encoding='utf-8').read().split('\n')
    i, n = 0, len(lines)
    while i < n:                       # 文件头：带冒号的行忽略
        s = lines[i].strip()
        if s and ':' not in s:
            break
        i += 1
    pages, page, region = [], None, None
    while i < n:
        s = lines[i].strip()
        i += 1
        if s == '':
            page, region = None, None
            continue
        if ':' in s:
            k, v = s.split(':', 1)
            k, v = k.strip(), v.strip()
            if region is not None:
                region[k] = v
            elif page is not None:
                page['props'][k] = v
            continue
        if page is None:
            page = {'name': s, 'props': {}, 'regions': []}
            pages.append(page)
            region = None
        else:
            region = {'name': s}
            page['regions'].append(region)

    for p in pages:
        sz = p['props'].get('size', '0,0')
        p['width'], p['height'] = [int(float(t)) for t in sz.split(',')]
        for r in p['regions']:
            if 'bounds' in r:
                r['x'], r['y'], r['w'], r['h'] = [int(float(t)) for t in r['bounds'].split(',')]
            elif 'xy' in r:
                r['x'], r['y'] = [int(float(t)) for t in r['xy'].split(',')]
                r['w'], r['h'] = [int(float(t)) for t in r['size'].split(',')]
            else:
                raise ValueError('区域 %s 缺 bounds/xy' % r['name'])
            if 'offsets' in r:
                r['ox'], r['oy'], r['ow'], r['oh'] = [int(float(t)) for t in r['offsets'].split(',')]
            elif 'offset' in r:
                r['ox'], r['oy'] = [int(float(t)) for t in r['offset'].split(',')]
                r['ow'], r['oh'] = [int(float(t)) for t in r['orig'].split(',')]
            else:
                r['ox'] = r['oy'] = 0
                r['ow'], r['oh'] = r['w'], r['h']
            r['deg'] = _ROT.get(str(r.get('rotate', 'false')).strip().lower(), 0)
            r['index'] = int(r.get('index', -1))
    return pages


def footprint(r):
    """页内实际占位矩形 (x, y, w, h)；deg 90/270 时宽高互换。"""
    if r['deg'] in (90, 270):
        return r['x'], r['y'], r['h'], r['w']
    return r['x'], r['y'], r['w'], r['h']


def crop_trimmed(page_img, r):
    """从页图裁出**裁白后**的区域图（已把逆时针旋转还原成顺时针），尺寸 (w, h)。"""
    x, y, w, h = footprint(r)
    c = page_img.crop((x, y, x + w, y + h))
    if r['deg'] == 90:
        c = c.transpose(Image.ROTATE_270)      # 存进去是逆时针 90 -> 还原顺时针 90
    elif r['deg'] == 270:
        c = c.transpose(Image.ROTATE_90)
    elif r['deg'] == 180:
        c = c.transpose(Image.ROTATE_180)
    return c


def unpack_region(page_img, r):
    """裁白图按 offsets 贴回**未裁白原画布** (ow, oh)。编辑器用的单图就是它。"""
    t = crop_trimmed(page_img, r)
    canvas = Image.new('RGBA', (r['ow'], r['oh']), (0, 0, 0, 0))
    canvas.paste(t, (r['ox'], r['oh'] - r['oy'] - t.size[1]))   # oy 从下边缘量
    return canvas


def write_atlas(path, page_name, page_w, page_h, entries,
                page_props=('pma: false', 'filter:Linear,Linear')):
    """写出 atlas。entries = [ (name, x, y, w, h, offsets_or_None, deg_or_0) ]，按给定顺序。

    注意：页属性之后不能有空行。
    """
    lines = [page_name] + list(page_props) + ['size:%d,%d' % (page_w, page_h)]
    for (name, x, y, w, h, offs, deg) in entries:
        lines.append(name)
        lines.append('bounds:%d,%d,%d,%d' % (x, y, w, h))
        if deg in (90, 180, 270):
            lines.append('rotate: %d' % deg)
        if offs is not None:
            lines.append('offsets:%d,%d,%d,%d' % tuple(offs))
    open(path, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')

# ==========================================================================
# 来源: spine_render.py
# ==========================================================================
# -*- coding: utf-8 -*-
"""独立 Spine setup-pose 渲染器（只用 JSON + 单图，不依赖 atlas）。

数学严格照 spine-ts 4.2：Bone.ts / RegionAttachment.ts / MeshAttachment.ts / VertexAttachment.ts。
用途：
  * 当「裁判」——用渲染包围盒去对 `skeleton.width/height`，一致就说明位置数据自洽；
  * 产出验收基准图。

已实测确认的约定：
  * region 附件的 (x, y) 是**区域中心**（穷举 center/bl/br/tl/tr 五种锚点，center 最贴合编辑器）；
  * 加权网格 vertices 格式：`骨数, [骨索引, x, y, 权重] * 骨数, ...`，骨索引是**全局骨骼序号**；
  * 网格 regionUVs 归一化在**未裁白原尺寸**上，(0,0) = 左上。
"""


DEG = math.pi / 180.0
Image.MAX_IMAGE_PIXELS = None


class Bone:
    __slots__ = ('name', 'parent', 'children', 'x', 'y', 'rotation', 'scaleX', 'scaleY',
                 'shearX', 'shearY', 'inherit', 'a', 'b', 'c', 'd', 'wx', 'wy', 'length')

    def __init__(self, bd):
        self.name = bd['name']
        self.parent = None
        self.children = []
        self.x = bd.get('x', 0.0)
        self.y = bd.get('y', 0.0)
        self.rotation = bd.get('rotation', 0.0)
        self.scaleX = bd.get('scaleX', 1.0)
        self.scaleY = bd.get('scaleY', 1.0)
        self.shearX = bd.get('shearX', 0.0)
        self.shearY = bd.get('shearY', 0.0)
        self.length = bd.get('length', 0.0)
        # Spine 3.8 叫 `transform`，4.x 改名为 `inherit`；取值字符串相同
        self.inherit = bd.get('inherit', bd.get('transform', 'normal'))
        self.a = self.b = self.c = self.d = self.wx = self.wy = 0.0


def build_skeleton(data):
    bones = {}
    order = []
    for bd in data['bones']:
        b = Bone(bd)
        bones[b.name] = b
        order.append(b)
    for bd in data['bones']:
        if 'parent' in bd:
            b = bones[bd['name']]
            b.parent = bones[bd['parent']]
            b.parent.children.append(b)
    return bones, order


def _descendants(b, out):
    """父先于子的后代列表。IK 改完骨骼后要按这个顺序重算世界变换。"""
    for c in b.children:
        out.append(c)
        _descendants(c, out)
    return out


def update_world(b, sk_scale_x=1.0, sk_scale_y=1.0, sk_x=0.0, sk_y=0.0):
    p = b.parent
    if p is None:
        rx = (b.rotation + b.shearX) * DEG
        ry = (b.rotation + 90 + b.shearY) * DEG
        b.a = math.cos(rx) * b.scaleX * sk_scale_x
        b.b = math.cos(ry) * b.scaleY * sk_scale_x
        b.c = math.sin(rx) * b.scaleX * sk_scale_y
        b.d = math.sin(ry) * b.scaleY * sk_scale_y
        b.wx = b.x * sk_scale_x + sk_x
        b.wy = b.y * sk_scale_y + sk_y
        return
    pa, pb, pc, pd = p.a, p.b, p.c, p.d
    b.wx = pa * b.x + pb * b.y + p.wx
    b.wy = pc * b.x + pd * b.y + p.wy

    if b.inherit == 'normal':
        rx = (b.rotation + b.shearX) * DEG
        ry = (b.rotation + 90 + b.shearY) * DEG
        la, lb = math.cos(rx) * b.scaleX, math.cos(ry) * b.scaleY
        lc, ld = math.sin(rx) * b.scaleX, math.sin(ry) * b.scaleY
        b.a, b.b = pa * la + pb * lc, pa * lb + pb * ld
        b.c, b.d = pc * la + pd * lc, pc * lb + pd * ld
        return
    if b.inherit == 'onlyTranslation':
        rx = (b.rotation + b.shearX) * DEG
        ry = (b.rotation + 90 + b.shearY) * DEG
        b.a, b.b = math.cos(rx) * b.scaleX, math.cos(ry) * b.scaleY
        b.c, b.d = math.sin(rx) * b.scaleX, math.sin(ry) * b.scaleY
    elif b.inherit == 'noRotationOrReflection':
        sx, sy = 1.0 / sk_scale_x, 1.0 / sk_scale_y
        pa *= sx
        pc *= sy
        s = pa * pa + pc * pc
        if s > 0.0001:
            s = abs(pa * pd * sy - pb * sx * pc) / s
            pb, pd = pc * s, pa * s
            prx = math.degrees(math.atan2(pc, pa))
        else:
            pa = pc = 0.0
            prx = 90 - math.degrees(math.atan2(pd, pb))
        rx = (b.rotation + b.shearX - prx) * DEG
        ry = (b.rotation + b.shearY - prx + 90) * DEG
        la, lb = math.cos(rx) * b.scaleX, math.cos(ry) * b.scaleY
        lc, ld = math.sin(rx) * b.scaleX, math.sin(ry) * b.scaleY
        b.a, b.b = pa * la - pb * lc, pa * lb - pb * ld
        b.c, b.d = pc * la + pd * lc, pc * lb + pd * ld
    elif b.inherit in ('noScale', 'noScaleOrReflection'):
        # 逐行对齐官方 spine-libgdx 4.2 Bone.updateWorldTransform 的 noScale 分支
        r = b.rotation * DEG
        cs, sn = math.cos(r), math.sin(r)
        za = (pa * cs + pb * sn) / sk_scale_x
        zc = (pc * cs + pd * sn) / sk_scale_y
        s = math.sqrt(za * za + zc * zc)
        if s > 0.00001:
            s = 1.0 / s
        za *= s
        zc *= s
        s = math.sqrt(za * za + zc * zc)
        if b.inherit == 'noScale' and ((pa * pd - pb * pc < 0) !=
                                       ((sk_scale_x < 0) != (sk_scale_y < 0))):
            s = -s
        r2 = math.pi / 2 + math.atan2(zc, za)
        zb = math.cos(r2) * s
        zd = math.sin(r2) * s
        shx = b.shearX * DEG
        shy = (90 + b.shearY) * DEG
        la, lb = math.cos(shx) * b.scaleX, math.cos(shy) * b.scaleY
        lc, ld = math.sin(shx) * b.scaleX, math.sin(shy) * b.scaleY
        b.a, b.b = za * la + zb * lc, za * lb + zb * ld
        b.c, b.d = zc * la + zd * lc, zc * lb + zd * ld
    else:
        raise NotImplementedError('inherit=' + b.inherit)
    b.a *= sk_scale_x
    b.b *= sk_scale_x
    b.c *= sk_scale_y
    b.d *= sk_scale_y


def _norm180(a):
    if a > 180.0:
        return a - 360.0
    if a < -180.0:
        return a + 360.0
    return a


def _ik1(b, target_x, target_y, compress, stretch, uniform, alpha, sk):
    """1 骨 IK —— 逐行照抄官方 spine-libgdx 4.2 `IkConstraint.apply(Bone, ...)`。"""
    sk_scale_x, sk_scale_y, sk_x, sk_y = sk
    p = b.parent
    if p is None:
        return
    pa, pb, pc, pd = p.a, p.b, p.c, p.d
    rot = -b.shearX - b.rotation
    if b.inherit == 'onlyTranslation':
        tx = (target_x - b.wx) * (1.0 if sk_scale_x >= 0 else -1.0)
        ty = (target_y - b.wy) * (1.0 if sk_scale_y >= 0 else -1.0)
    else:
        if b.inherit == 'noRotationOrReflection':
            s = abs(pa * pd - pb * pc) / max(0.0001, pa * pa + pc * pc)
            sa = pa / sk_scale_x
            sc = pc / sk_scale_y
            pb = -sc * s * sk_scale_x
            pd = sa * s * sk_scale_y
            rot += math.degrees(math.atan2(sc, sa))
        x, y = target_x - p.wx, target_y - p.wy
        d = pa * pd - pb * pc
        if abs(d) <= 0.0001:
            tx = ty = 0.0
        else:
            tx = (x * pd - y * pb) / d - b.x
            ty = (y * pa - x * pc) / d - b.y
    rot += math.degrees(math.atan2(ty, tx))
    if b.scaleX < 0:
        rot += 180
    rot = _norm180(rot)
    sx, sy = b.scaleX, b.scaleY
    if compress or stretch:
        if b.inherit in ('noScale', 'noScaleOrReflection'):
            tx, ty = target_x - b.wx, target_y - b.wy
        ln = b.length * sx
        if ln > 0.0001:
            dd = tx * tx + ty * ty
            if (compress and dd < ln * ln) or (stretch and dd > ln * ln):
                s = (math.sqrt(dd) / ln - 1) * alpha + 1
                sx *= s
                if uniform:
                    sy *= s
    b.rotation = b.rotation + rot * alpha
    b.scaleX, b.scaleY = sx, sy
    update_world(b, sk_scale_x, sk_scale_y, sk_x, sk_y)


def _ik2(parent, child, target_x, target_y, bend_dir, stretch, uniform,
          softness, alpha, sk):
    """2 骨 IK —— 逐行照抄官方 `IkConstraint.apply(Bone, Bone, ...)`。"""
    update = lambda b: update_world(b, *sk)          # noqa: E731
    if parent.inherit != 'normal' or child.inherit != 'normal':
        return
    px, py = parent.x, parent.y
    psx, psy = parent.scaleX, parent.scaleY
    sx, sy = psx, psy
    csx = child.scaleX
    if psx < 0:
        psx, os1, s2 = -psx, 180, -1
    else:
        os1, s2 = 0, 1
    if psy < 0:
        psy = -psy
        s2 = -s2
    if csx < 0:
        csx, os2 = -csx, 180
    else:
        os2 = 0
    cx = child.x
    a, b, c, d = parent.a, parent.b, parent.c, parent.d
    u = abs(psx - psy) <= 0.0001
    if not u or stretch:
        cy = 0.0
        cwx = a * cx + parent.wx
        cwy = c * cx + parent.wy
    else:
        cy = child.y
        cwx = a * cx + b * cy + parent.wx
        cwy = c * cx + d * cy + parent.wy
    pp = parent.parent
    if pp is None:
        return
    a, b, c, d = pp.a, pp.b, pp.c, pp.d
    det = a * d - b * c
    x, y = cwx - pp.wx, cwy - pp.wy
    det = 0.0 if abs(det) <= 0.0001 else 1.0 / det
    dx = (x * d - y * b) * det - px
    dy = (y * a - x * c) * det - py
    l1 = math.sqrt(dx * dx + dy * dy)
    l2 = child.length * csx
    if l1 < 0.0001:
        _ik1(parent, target_x, target_y, False, stretch, False, alpha, sk)
        child.rotation = 0.0
        update(child)
        return
    x, y = target_x - pp.wx, target_y - pp.wy
    tx = (x * d - y * b) * det - px
    ty = (y * a - x * c) * det - py
    dd = tx * tx + ty * ty
    if softness != 0:
        softness *= psx * (csx + 1) * 0.5
        td = math.sqrt(dd)
        sd = td - l1 - l2 * psx + softness
        if sd > 0:
            p = min(1.0, sd / (softness * 2)) - 1
            p = (sd - softness * (1 - p * p)) / td
            tx -= p * tx
            ty -= p * ty
            dd = tx * tx + ty * ty
    a1 = a2 = 0.0
    if u:
        l2 *= psx
        cos = (dd - l1 * l1 - l2 * l2) / (2 * l1 * l2)
        if cos < -1:
            cos = -1.0
            a2 = math.pi * bend_dir
        elif cos > 1:
            cos = 1.0
            a2 = 0.0
            if stretch:
                a = (math.sqrt(dd) / (l1 + l2) - 1) * alpha + 1
                sx *= a
                if uniform:
                    sy *= a
        else:
            a2 = math.acos(cos) * bend_dir
        a = l1 + l2 * cos
        b = l2 * math.sin(a2)
        a1 = math.atan2(ty * a - tx * b, tx * a + ty * b)
    else:
        a = psx * l2
        b = psy * l2
        aa, bb = a * a, b * b
        ta = math.atan2(ty, tx)
        c = bb * l1 * l1 + aa * dd - aa * bb
        c1 = -2 * bb * l1
        c2 = bb - aa
        d2 = c1 * c1 - 4 * c2 * c
        if d2 >= 0:
            q = math.sqrt(d2)
            if c1 < 0:
                q = -q
            q = -(c1 + q) * 0.5
            r0 = q / c2
            r1 = c / q if q != 0 else 0.0
            r = r0 if abs(r0) < abs(r1) else r1
            r0 = dd - r * r
            if r0 >= 0:
                yy = math.sqrt(r0) * bend_dir
                a1 = ta - math.atan2(yy, r)
                a2 = math.atan2(yy / psy, (r - l1) / psx)
                # 命中精确解
                os = math.atan2(cy, cx) * s2
                rot = parent.rotation
                a1 = _norm180((a1 - os) * (180.0 / math.pi) + os1 - rot)
                parent.rotation = rot + a1 * alpha
                parent.scaleX, parent.scaleY = sx, sy
                parent.shearX = parent.shearY = 0.0
                update(parent)
                rot = child.rotation
                a2 = _norm180(((a2 + os) * (180.0 / math.pi) - child.shearX) * s2
                              + os2 - rot)
                child.x, child.y = cx, cy
                child.rotation = rot + a2 * alpha
                update(child)
                return
        min_angle, min_x = math.pi, l1 - a
        min_dist, min_y = min_x * min_x, 0.0
        max_angle, max_x = 0.0, l1 + a
        max_dist, max_y = max_x * max_x, 0.0
        c = -a * l1 / (aa - bb) if (aa - bb) != 0 else 2.0
        if -1 <= c <= 1:
            c = math.acos(c)
            x = a * math.cos(c) + l1
            y = b * math.sin(c)
            d3 = x * x + y * y
            if d3 < min_dist:
                min_angle, min_dist, min_x, min_y = c, d3, x, y
            if d3 > max_dist:
                max_angle, max_dist, max_x, max_y = c, d3, x, y
        if dd <= (min_dist + max_dist) * 0.5:
            a1 = ta - math.atan2(min_y * bend_dir, min_x)
            a2 = min_angle * bend_dir
        else:
            a1 = ta - math.atan2(max_y * bend_dir, max_x)
            a2 = max_angle * bend_dir
    os = math.atan2(cy, cx) * s2
    rot = parent.rotation
    a1 = _norm180((a1 - os) * (180.0 / math.pi) + os1 - rot)
    parent.rotation = rot + a1 * alpha
    parent.scaleX, parent.scaleY = sx, sy
    parent.shearX = parent.shearY = 0.0
    update_world(parent)
    rot = child.rotation
    a2 = _norm180(((a2 + os) * (180.0 / math.pi) - child.shearX) * s2
                  + os2 - rot)
    child.x, child.y = cx, cy
    child.rotation = rot + a2 * alpha
    update_world(child)


def solve_constraints(data, bones, sk_scale_x=1.0, sk_scale_y=1.0,
                      sk_x=0.0, sk_y=0.0):
    """按 `order` 应用 IK 约束。

    这一步不能省：**Spine 的 setup pose 本身就解 IK**。实测 Nomad 有 6 个 IK，
    不解的话四肢会散在画布各处（看着像素材坏了，其实几何全对）。

    ⚠️ **两套键名都要认**（2026-09 修）：3.8 写 `ik:[...]`，**4.3 搬到了
    `constraints:[{type:"ik",...}]`**。只读旧键的后果是 37/56 个已交付 4.x 包的 IK
    **被静默跳过**（实测金发双剑的 calf 位移 123.6px），交付的 `复原预览图` 与编辑器
    见到的不是同一个姿势，`apply` 的渲染比对也因此左（3.8 已解 IK）右（4.3 未解）
    地比，差的是工具自己的 bug。
    """
    legacy = list(data.get('ik') or [])
    modern = [c for c in (data.get('constraints') or [])
              if str(c.get('type', '')).lower() == 'ik']
    iks = sorted(legacy + modern, key=lambda c: c.get('order', 0))
    sk = (sk_scale_x, sk_scale_y, sk_x, sk_y)
    n = 0
    for c in iks:
        mix = c.get('mix', 1.0)
        tgt = bones.get(c.get('target'))
        bs = [bones[nm] for nm in (c.get('bones') or []) if nm in bones]
        if mix == 0 or tgt is None or not bs:
            continue
        bend = 1 if c.get('bendPositive', True) else -1
        stretch = bool(c.get('stretch', False))
        uniform = bool(c.get('uniform', True))
        if len(bs) == 1:
            _ik1(bs[0], tgt.wx, tgt.wy, bool(c.get('compress', False)),
                 stretch, uniform, mix, sk)
        elif len(bs) == 2:
            _ik2(bs[0], bs[1], tgt.wx, tgt.wy, bend, stretch, uniform,
                 c.get('softness', 0.0), mix, sk)
        else:
            continue
        n += 1
        for b in bs:                       # 受约束骨骼的后代要重算
            for ch in _descendants(b, []):
                update_world(ch, sk_scale_x, sk_scale_y, sk_x, sk_y)
    return n


def region_quad(att, bone):
    """region 附件 -> (4 世界点, 4 图像 uv, 三角形索引)。uv (0,0)=左上。"""
    w, h = att.get('width', 0.0), att.get('height', 0.0)
    sx, sy = att.get('scaleX', 1.0), att.get('scaleY', 1.0)
    rot = att.get('rotation', 0.0) * DEG
    cos, sin = math.cos(rot), math.sin(rot)
    x, y = att.get('x', 0.0), att.get('y', 0.0)
    lx, ly = -w / 2 * sx, -h / 2 * sy              # (x,y) 是区域中心
    lx2, ly2 = w / 2 * sx, h / 2 * sy
    lxc, lxs = lx * cos + x, lx * sin
    lyc, lys = ly * cos + y, ly * sin
    lx2c, lx2s = lx2 * cos + x, lx2 * sin
    ly2c, ly2s = ly2 * cos + y, ly2 * sin
    off = [(lxc - lys, lyc + lxs), (lxc - ly2s, ly2c + lxs),
           (lx2c - ly2s, ly2c + lx2s), (lx2c - lys, lyc + lx2s)]
    world = [(ox * bone.a + oy * bone.b + bone.wx, ox * bone.c + oy * bone.d + bone.wy)
             for ox, oy in off]
    return world, [(0.0, 1.0), (0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], [(0, 1, 2), (2, 3, 0)]


def deref_linkedmesh(data, a):
    """`linkedmesh` 自身没有顶点，顺父指针找到真正带网格的那个。

    ⚠️ **父指针的键名在 3.8 与 4.x 之间改过**（实测同一份素材转换前后）：

        3.8.95   {"type":"linkedmesh", "parent":"legL1", "skin":"normal"}
        4.3.26   {"type":"linkedmesh", "source":"legL1", "skin":"normal"}

    两个都要认，否则 4.x 数据上找不到父网格，附件会被当成普通区域四边形画 ——
    那会画成一个**以骨骼原点为中心的横平竖直大矩形**（实测 `elite/legL1` 大腿就是这样错的，
    表现为"裙子横过来 + 大腿缺失"）。
    """
    seen = 0
    while a is not None and a.get('type') == 'linkedmesh' and seen < 8:
        seen += 1
        pn = a.get('parent') or a.get('source')      # 4.x 用 source
        ps = a.get('skin') or 'default'
        nxt = None
        for s in data.get('skins', []):
            if s.get('name') != ps:
                continue
            for _slot, atts in (s.get('attachments') or {}).items():
                if pn in atts:
                    nxt = atts[pn]
                    break
        a = nxt
    return a


def mesh_geometry(att, bone, order):
    """网格附件 -> (世界点, uv, 三角形)。自动区分加权/非加权。"""
    v, uv, tris = att['vertices'], att['uvs'], att['triangles']
    pts = []
    if len(v) != len(uv):                          # 加权：骨数, [骨索引,x,y,权重]*
        i = 0
        while i < len(v):
            n = int(v[i])
            i += 1
            wx = wy = 0.0
            for _ in range(n):
                bi = int(v[i])
                vx, vy, wt = v[i + 1], v[i + 2], v[i + 3]
                i += 4
                b = order[bi]                      # 全局骨骼序号
                wx += (vx * b.a + vy * b.b + b.wx) * wt
                wy += (vx * b.c + vy * b.d + b.wy) * wt
            pts.append((wx, wy))
    else:                                          # 非加权：绑定到 slot 骨骼
        for k in range(0, len(v), 2):
            vx, vy = v[k], v[k + 1]
            pts.append((vx * bone.a + vy * bone.b + bone.wx,
                        vx * bone.c + vy * bone.d + bone.wy))
    tri = [(tris[k], tris[k + 1], tris[k + 2]) for k in range(0, len(tris), 3)]
    uvl = [(uv[k], uv[k + 1]) for k in range(0, len(uv), 2)]
    return pts, uvl, tri


def pick_skin(data):
    """挑一个「部件最多」的皮肤来出预览图。

    Spine 的多皮肤资源里，`default` 可能只是个空壳（实测 Nomad：default 只有 6 项，
    真正的美术在 `normal`/`elite` 各 20 项）。按 `default` 出图会只渲染出两只脚。
    """
    skins = data.get('skins') or []
    if not skins:
        return None
    best, bestn = skins[0], -1
    for s in skins:
        n = sum(len(v) for v in (s.get('attachments') or {}).values())
        if n > bestn:
            best, bestn = s, n
    return best


def resolve_image_name(att_name, att):
    """附件对应的图片名（= `images/` 下的相对路径）。

    Spine 的解析顺序是 **`path` > `name` > 附件键名**，实测自 Nomad 的原始 JSON：

        "armR2":{"armR2":{"name":"nomad_normal/armR2", ...}}          -> nomad_normal/armR2
        "blade2":{"blade2":{"name":"blade2","path":"blade1", ...}}    -> blade1（path 优先）

    ⚠️ 踩过的坑：只看 `path` 会让 `nomad_normal/*` 这类**只写了 `name`** 的附件
    全部找不到图（表现为图上只剩两只脚），而图集里明明有这些区。
    """
    return att.get('path') or att.get('name') or att_name


def render_previews(json_path, images_dir, out_dir, ss=3, pad=20,
                    prefix='复原预览图', bg=(38, 40, 48, 255), max_long=2600):
    """**按皮肤逐套出预览图**，返回 {皮肤名: 文件路径}。

    多皮肤资源一套皮肤一张图：Spine 的 `default` 是基底，选中命名皮肤时是**叠加**在它上面
    （实测 `RogueSekaniFlamebringer` 的 default 有 83 个附件=整套角色，
    elite/normal 各 7 个只是替换掉衣服那几件）。所以每张图渲染的是
    「default + 该皮肤」，而不是「只有该皮肤」——否则命名皮肤那几张会缺胳膊少腿。

    单皮肤时文件名保持 `复原预览图.png`（向后兼容）；多皮肤时是
    `复原预览图_<皮肤名>.png`，子目录名带 `/` 的皮肤会换成 `_`。

    `max_long` 是**输出长边上限**（默认 2600）：大角色按 ×2 放大能顶到近万像素、
    单张 PNG 几十 MB，所以超了就只放大到上限。
    """
    data = json.load(open(json_path, encoding='utf-8'))
    names = [s.get('name', 'default') for s in (data.get('skins') or [])] or ['default']
    out = {}
    skipped = []
    for nm in names:
        rr = Renderer(json_path, images_dir, ss=ss, pad=pad, skin=nm)
        try:
            ren, bb = rr.render()
        except ValueError as e:
            # 多皮肤资源里 default 经常只是个空壳（只有 path 约束 / 少数配件），
            # 没有可渲染附件时跳过这层皮肤，不要让整条流水线挂掉。
            # 实测 RogueNoyakinBlade 的 default 只有 pelvis_Path（type=path），其余
            # 美术全在 elite / normal 里。
            print('  ! 皮肤 %s 跳过: %s' % (nm, e))
            skipped.append(nm)
            continue
        f = 2.0
        if max(ren.size) * f > max_long:
            f = max(1.0, max_long / float(max(ren.size)))
        if f != 1.0:
            ren = ren.resize((max(1, int(ren.width * f)), max(1, int(ren.height * f))),
                             Image.LANCZOS)
        canvas = Image.new('RGBA', ren.size, bg)
        canvas.alpha_composite(ren)
        # 文件名兜底：跳过空壳皮肤后，单皮肤素材仍能用旧的「复原预览图.png」向后兼容
        safe = nm.replace('/', '_').replace('\\', '_')
        fn = (prefix + '.png') if (len(names) - len(skipped)) == 1 else ('%s_%s.png' % (prefix, safe))
        path = os.path.join(out_dir, fn)
        canvas.convert('RGB').save(path)
        out[nm] = {'path': path, 'bbox': [round(bb[4], 2), round(bb[5], 2)],
                   'ik': getattr(rr, 'ik_applied', 0), 'ss': rr.ss_used,
                   'size': list(canvas.size)}
    if not out:
        raise ValueError('所有皮肤都没可渲染附件（%s 全是空壳）' % names)
    return out


class Renderer:
    """渲染 setup pose。images_dir 里按图片名找 `<name>.png`（含皮肤前缀）。

    `max_px` 是**光栅画布像素上限**：每个三角形都要对整张画布做一次仿射变换，
    开销 ≈ 画布像素 × 三角形数。大角色按 `ss=3` 会把画布顶到上千万像素
    （实测 1263×1835 的角色 ss=3 是 3909×5625 = 2200 万像素，×3 套皮肤直接跑不完），
    所以超预算就自动降 `ss`。实际用到的倍率记在 `ss_used`。
    """

    def __init__(self, json_path, images_dir, ss=3, pad=12, skin=None,
                 max_px=4_000_000, sk_offset=None):
        self.data = json.load(open(json_path, encoding='utf-8'))
        self.images_dir = images_dir
        self.ss = ss
        self.ss_used = ss
        self.pad = pad
        self.skin = skin
        self.max_px = max_px
        # 覆盖 skeleton.x/y。**比对 3.8 与 4.x 的渲染时必须用**：
        # 4.x 移除了 skeleton.x/y，整只骨架会平移 (x, y)，
        # 与 3.8 的渲染直接比会整体错位（实测错 595px，差异被夸大 200 倍）。
        self.sk_offset = sk_offset

    def _collect(self):
        d = self.data
        bones, order = build_skeleton(d)
        sk = d['skeleton']
        skx, sky = sk.get('scaleX', 1.0), sk.get('scaleY', 1.0)
        if self.sk_offset is not None:
            skpx, skpy = self.sk_offset
        else:
            skpx, skpy = sk.get('x', 0.0), sk.get('y', 0.0)
        for b in order:
            update_world(b, skx, sky, skpx, skpy)
        self.ik_applied = solve_constraints(d, bones, skx, sky, skpx, skpy)
        if self.skin:
            sd = next((s for s in d['skins'] if s.get('name') == self.skin), None)
            if sd is None:
                raise ValueError('没有皮肤 %s' % self.skin)
        else:
            sd = pick_skin(d)
        self.skin_name = sd.get('name', 'default')
        # Spine 里 `default` 皮肤是基底，选中某套皮肤时是**叠加**在它上面的
        by_slot = {}
        for s in d['skins']:
            if s.get('name') == 'default' or s is sd:
                for k, v in (s.get('attachments') or {}).items():
                    by_slot.setdefault(k, {}).update(v)
        geoms = []
        for slot in d['slots']:
            nm = slot.get('attachment')
            if not nm:
                continue
            a = by_slot.get(slot['name'], {}).get(nm)
            if a is None or a.get('type') in ('boundingbox', 'path', 'point', 'clipping'):
                continue
            bone = bones[slot['bone']]
            geo = deref_linkedmesh(d, a)
            if geo is not None and 'mesh' in str(geo.get('type')) and geo.get('uvs'):
                pts, uvl, tri = mesh_geometry(geo, bone, order)
            else:
                pts, uvl, tri = region_quad(a, bone)
            geoms.append((slot, a, pts, uvl, tri))
        return geoms

    def render(self):
        geoms = self._collect()
        xs = [p[0] for _, _, pts, _, _ in geoms for p in pts]
        ys = [p[1] for _, _, pts, _, _ in geoms for p in pts]
        if not xs:
            raise ValueError('没有任何可渲染附件')
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        pad = self.pad
        W = int(math.ceil(maxx - minx)) + pad * 2
        H = int(math.ceil(maxy - miny)) + pad * 2
        ss = self.ss
        while ss > 1 and (W * ss) * (H * ss) > self.max_px:
            ss -= 1
        self.ss_used = ss
        canvas = Image.new('RGBA', (W * ss, H * ss), (0, 0, 0, 0))

        def to_canvas(p):
            return ((p[0] - minx + pad) * ss, (maxy - p[1] + pad) * ss)

        for slot, a, pts, uvl, tri in geoms:
            key = resolve_image_name(slot['attachment'], a)
            f = os.path.join(self.images_dir, key.replace('/', os.sep) + '.png')
            if not os.path.exists(f):          # 兜底：退回附件键名
                key = slot['attachment']
                f = os.path.join(self.images_dir, key.replace('/', os.sep) + '.png')
            if not os.path.exists(f):
                continue
            src = Image.open(f).convert('RGBA')
            cp = [to_canvas(p) for p in pts]
            IW, IH = src.size
            # 关键：先把**这一个附件**的所有三角形画进一层，再整层做 alpha 合成。
            # 绝不能用 canvas.paste(tex, mask=三角形) —— 那是"替换"语义，
            # 附件在自身透明像素处会把下层擦掉（表现为下层部件凭空消失）。
            layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
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
                # **只在三角形的画布包围盒里做仿射变换**，不要整张画布 ——
                # 原来每个三角形都对 W×H 全图 transform 一次，一个角色几百个三角形
                # 就是几百次全图运算，这是预览渲染最贵的地方。
                xs3 = (cp[i][0], cp[j][0], cp[k][0])
                ys3 = (cp[i][1], cp[j][1], cp[k][1])
                bx0 = max(0, int(math.floor(min(xs3))) - 1)
                by0 = max(0, int(math.floor(min(ys3))) - 1)
                bx1 = min(canvas.width, int(math.ceil(max(xs3))) + 2)
                by1 = min(canvas.height, int(math.ceil(max(ys3))) + 2)
                if bx1 <= bx0 or by1 <= by0:
                    continue
                w, h = bx1 - bx0, by1 - by0
                # 矩阵平移到局部坐标：input = Mi · (local + bbox 原点)
                tx = Mi[0, 0] * bx0 + Mi[0, 1] * by0 + Mi[0, 2]
                ty = Mi[1, 0] * bx0 + Mi[1, 1] * by0 + Mi[1, 2]
                tex = src.transform((w, h), Image.AFFINE,
                                    (Mi[0, 0], Mi[0, 1], tx,
                                     Mi[1, 0], Mi[1, 1], ty),
                                    resample=Image.BILINEAR)
                m = Image.new('L', (w, h), 0)
                ImageDraw.Draw(m).polygon([(cp[q][0] - bx0, cp[q][1] - by0)
                                           for q in (i, j, k)], fill=255)
                # 同一附件内三角形互不重叠，这里用 paste 是安全的
                layer.paste(tex, (bx0, by0), m)
            canvas.alpha_composite(layer)
        return canvas.resize((W, H), Image.LANCZOS), (minx, miny, maxx, maxy,
                                                      maxx - minx, maxy - miny)

    def render_bones(self, world_to_px, draw, color=(0, 255, 255), r=2):
        """把骨骼画到外部画布上（world_to_px: (wx,wy)->(px,py)）。"""
        d = self.data
        lens = {b['name']: b.get('length', 0.0) for b in d['bones']}
        bones, order = build_skeleton(d)
        sk = d['skeleton']
        for b in order:
            update_world(b, sk.get('scaleX', 1.0), sk.get('scaleY', 1.0),
                         sk.get('x', 0.0), sk.get('y', 0.0))
        for b in order:
            if b.parent is None:
                continue
            p0 = world_to_px((b.wx, b.wy))
            p1 = world_to_px((b.wx + b.a * lens.get(b.name, 0.0),
                              b.wy + b.c * lens.get(b.name, 0.0)))
            draw.line([p0, p1], fill=color, width=2)
            draw.ellipse([p0[0] - r, p0[1] - r, p0[0] + r, p0[1] + r], fill=(255, 255, 0))

# ==========================================================================
# 来源: spine_repair.py
# ==========================================================================
# -*- coding: utf-8 -*-
"""体检 / 去污染 / 重打包。纯本地确定性，不消耗任何额度。"""




# ------------------------------------------------------------------ 体检
def diagnose(atlas_path, json_path=None):
    """返回结构化体检报告。"""
    pages = parse_atlas(atlas_path)
    rep = {'atlas': os.path.basename(atlas_path), 'pages': []}
    for p in pages:
        img_path = resolve_page_image(atlas_path, p)
        info = {'page': p['name'], 'props': dict(p['props']),
                'declared_size': [p['width'], p['height']],
                'regions': len(p['regions'])}
        if img_path is None:
            info['ERROR'] = '页图不存在: ' + p['name']
            rep['pages'].append(info)
            continue
        img = Image.open(img_path).convert('RGBA')
        info['page_file'] = os.path.basename(img_path)
        info['actual_size'] = list(img.size)
        info['page_name_matches_file'] = (p['name'] == os.path.basename(img_path))
        info['page_size_mismatch'] = list(img.size) != [p['width'], p['height']]

        a = np.asarray(img)[:, :, 3] > 0
        # ⚠️ 覆盖计数必须按**别名组**算：几何完全相同的区域是同一张图的两个名字
        # （Spine 对多皮肤/重名附件会这样写 atlas），它们共享像素不是重叠。
        # 按原始区域计数会把 `l_foot_4` / `l_foot_4 _a` 这类误报成"重叠对"。
        gid = region_groups(p['regions'])
        grects = []
        for r, g in zip(p['regions'], gid):
            if g == len(grects):
                grects.append(footprint(r))
        cover = np.zeros(a.shape, np.int32)
        outside = 0
        for (x, y, w, h) in grects:
            if x < 0 or y < 0 or x + w > p['width'] or y + h > p['height']:
                outside += 1
            cover[max(0, y):y + h, max(0, x):x + w] += 1
        info['alias_groups'] = len(grects)
        info['total_opaque'] = int(a.sum())
        info['multi_covered'] = int(((cover > 1) & a).sum())
        info['uncovered'] = int(((cover == 0) & a).sum())
        info['out_of_bounds_regions'] = outside
        info['rects_partition_page'] = bool(info['multi_covered'] == 0 and
                                            info['uncovered'] == 0 and outside == 0)
        # 矩形两两重叠对（同样按组）
        ov = 0
        for i in range(len(grects)):
            for j in range(i + 1, len(grects)):
                x1, y1, w1, h1 = grects[i]
                x2, y2, w2, h2 = grects[j]
                if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                    ov += 1
        info['overlapping_rect_pairs'] = ov
        rep['pages'].append(info)

        if json_path:
            info.update(_cross_check(json_path, p))
    return rep


def size_scale_report(atlas_path, json_path):
    """附件**声明尺寸** vs 图集**未裁白尺寸**（`ow/oh`）—— 抓「图集被打包成别的倍率」。

    这是**必须在步骤 1 就发现**的缺陷，因为它会伪装成"没问题"：

    * Spine 3.8 按 JSON 声明的 `width/height` 画四边形，纹理拉伸填充 ——
      声明是全尺寸、图集是 0.5 倍时，3.8 渲染出来**只是糊，几何是对的**；
    * 一旦转到 4.x，导出会用**图集尺寸重写附件尺寸**，于是精灵各自缩水、彼此错位。
      实测 NPC2：15/19 个附件是 0.5 倍，转 4.3.26 后头变大、四肢脱落。

    ⚠️ **倍率只能由「非网格」附件推**（2026-09 修，见 `mesh_explained`）：
    网格附件的 `width/height` 可能是**占位值**（实测 S041 的 5 个网格全写 `32x32`），
    它混进候选集会污染投票 —— 打平时 `if hit > best_hit` 保留"先遇到的"（候选升序），
    占位网格那个更小的因子就会赢（合成用例：真值 0.5 被算成 0.25 → 单图按 ×4 放大再裁切）。

    返回字段：
      * `checked` / `mismatch` / `sample`：全部附件（含网格）的对账
      * `scale` / `scale_fit` / `ratio`：**只由非网格附件**推出的倍率（推不出则 `scale=None`）
      * `mesh_mismatch`：声明尺寸与图集不符的网格名
      * `mesh_explained`：**与包内倍率自洽**的网格名（声明值是真尺寸 -> 应跟着放大）
      * `mesh_placeholder`：对不上倍率的网格名（占位值 -> 保持图集 orig 尺寸，不放大）
      * `placeholder_suspect`：有网格属于占位值
    """
    d = json.load(open(json_path, encoding='utf-8'))
    page = parse_atlas(atlas_path)[0]
    byname = {r['name']: r for r in page['regions']}
    bad, n = [], 0
    mesh_seen, mesh_bad = 0, []
    for s in d.get('skins', []):
        for slot, atts in (s.get('attachments') or {}).items():
            for nm, a in atts.items():
                if a.get('type') in ('boundingbox', 'path', 'point', 'clipping'):
                    continue
                key = resolve_image_name(nm, a)
                r = byname.get(key)
                w, h = a.get('width'), a.get('height')
                is_mesh = 'mesh' in str(a.get('type'))
                if r is not None and w and h and r['ow']:
                    n += 1
                    if is_mesh:
                        mesh_seen += 1
                if r is None or not w or not h or not r['ow']:
                    continue
                if (r['ow'], r['oh']) != (w, h):
                    bad.append((key, [w, h], [r['ow'], r['oh']], round(w / float(r['ow']), 4),
                                is_mesh))
                    if is_mesh:
                        mesh_bad.append(key)
    out = {'checked': n, 'mismatch': len(bad), 'ratio': None, 'scale': None,
           'scale_fit': None, 'sample': [b[:4] for b in bad[:6]],
           'mesh_total': mesh_seen, 'mesh_mismatch': mesh_bad,
           'mesh_explained': [], 'mesh_placeholder': [], 'region_mismatch': 0}

    # ---- 倍率只用**非网格**附件推：网格不参与对账（它们不跟着放大）
    region_bad = [b for b in bad if not b[4]]
    out['region_mismatch'] = len(region_bad)
    if region_bad:
        rs = sorted(b[3] for b in region_bad)
        out['ratio'] = rs[len(rs) // 2]
        # 各附件倍率会有取整抖动（91/77 vs 93/79）—— 搜一个最优缩放因子 s，
        # 看 `round(声明 * s) == 图集` 能解释多少项，从而判定是不是**一次干净的等比缩放**
        cand = sorted({b[2][0] / float(b[1][0]) for b in region_bad if b[1][0]})
        best_s, best_hit = None, -1
        for s in cand:
            hit = sum(1 for _, (w, h), (ow, oh), _r, _m in region_bad
                      if abs(round(w * s) - ow) <= 1 and abs(round(h * s) - oh) <= 1)
            if hit > best_hit:
                best_s, best_hit = s, hit

        out['scale'] = round(best_s, 6) if best_s else None
        out['scale_fit'] = '%d/%d' % (best_hit, len(region_bad))

    # 网格：声明尺寸能不能被**包内倍率**解释？
    #   解释得了 -> 声明值是真尺寸，跟着放大（否则真 0.5 倍包会白白丢掉一半分辨率）
    #   解释不了（或根本没有非网格缓冲）-> 判为占位值，保持图集 orig 尺寸
    if mesh_bad and out['scale']:
        s = out['scale']
        for key, (w, h), (ow, oh), _r, _m in bad:
            if key not in mesh_bad:
                continue
            if abs(round(w * s) - ow) <= 1 and abs(round(h * s) - oh) <= 1:
                out['mesh_explained'].append(key)
            else:
                out['mesh_placeholder'].append(key)
    else:
        out['mesh_placeholder'] = list(mesh_bad)
    out['placeholder_suspect'] = bool(out['mesh_placeholder'])
    return out


def fit_singles_to_declared(img_dir, atlas_path, json_path, factor, mesh_ok=()):
    """把解包出来的单图放大到 **JSON 声明的尺寸**。

    返回 `(放大张数, 裁切张数, 裁切明细)`。

    起因：源图集被按 s 倍打包（实测 NPC2/qiaofeng 的 s=0.500、Kimchul 的 s=0.847）。
    Spine 3.8 按 JSON 声明的 `width/height` 画四边形、纹理拉伸填充，所以 3.8 里只是糊、
    几何全对；**一转 4.x，导出会用图集尺寸重写附件尺寸** → 精灵各自缩水、彼此错位。

    ⚠️ **不能把整页统一放大**：实测 NPC2 的 19 个附件里 **15 个是 0.5 倍、4 个本来就 1:1**
    （`body` / `qz` / `qz2` / `wq2`）—— 整页 ×2 会把那 4 个弄坏、且让它们的打包矩形成
    未裁白画布的两倍。所以必须**逐图**按声明尺寸对齐。
    改 JSON 也不行：那 4 个本来就是对的，改了就轮到它们错。

    ⚠️ **网格附件的声明尺寸默认不可信**（`S041_skin6` 的 5 个网格全写 `32x32`，真实形状由
    `vertices` 决定、图尺寸由图集 `orig` 决定）—— 拿 32x32 当目标尺寸会把这 5 张缩成
    32x32、再被网格拉伸成大块矩形残影。
    但**也不能一律跳过**：真 0.5 倍包里网格的声明值是真的（实测 `兽人双刀剑客` 64/64、
    `光头打手` 29/29、`火把女战士` 14/14 都与包内倍率自洽），一律跳过会让它们白白丢掉一半
    分辨率。所以只对 `mesh_ok`（= `size_scale_report()['mesh_explained']`）里的网格做对齐。

    第三个返回值专治"静默裁切"：`paste` 到**更小**的 `want` 画布时就是裁切（丢美术），
    以前这种情况也报"仍不符 0 张"，等于把"图被切了"伪装成"没问题"。
    """
    d = json.load(open(json_path, encoding='utf-8'))
    declared = {}
    for s in d.get('skins', []):
        for slot, atts in (s.get('attachments') or {}).items():
            for nm, a in atts.items():
                if 'mesh' in str(a.get('type')) and resolve_image_name(nm, a) not in set(mesh_ok):
                    continue
                if a.get('width') and a.get('height'):
                    declared[resolve_image_name(nm, a)] = (int(a['width']),
                                                          int(a['height']))
    fixed, cropped = 0, []
    for r in parse_atlas(atlas_path)[0]['regions']:
        want = declared.get(r['name'])
        f = os.path.join(img_dir, r['name'].replace('/', os.sep) + '.png')
        if not want or not os.path.exists(f):
            continue
        im = Image.open(f).convert('RGBA')
        if im.size != want:                       # 与声明不符 -> 按全局因子放大后对齐画布
            big = im.resize((max(1, int(round(im.width * factor))),
                             max(1, int(round(im.height * factor)))), Image.LANCZOS)
            out = Image.new('RGBA', want, (0, 0, 0, 0))
            out.paste(big, (0, 0))
            # `paste` 到**更小**的画布就是裁切（丢美术）。但取整误差（≤2px）是正常的
            # （实测 `兽人双刀剑客` 44 张、`火把女战士` 20 张全是 1px），所以给 2px 容差，
            # 只报真正会丢内容的那种。以前这里既不算裁切、也不报，等于把"图被切了"
            # 伪装成"没问题"（第二个返回值恒为 0）。
            over = max(big.width - want[0], big.height - want[1])
            if over > 2:
                cropped.append((r['name'], im.size, (big.width, big.height), want, over))
            out.save(f)
            fixed += 1
    return fixed, cropped


def _collect_needed(data):
    """JSON 里所有会引用图片的地方 -> {图片名: 附件dict}

    三个实测坑：
    * **要遍历所有皮肤**。只看 `skins[0]` 会把多皮肤资源的附件全判成"图集里没有"
      （实测 Nomad 有 default/elite/normal 三套，误报 40 项）。
    * **图片名解析顺序是 `path` > `name` > 附件键名**。只看 `path` 会漏掉
      `{"name":"nomad_normal/armR2"}` 这类只写 `name` 的附件（实测 39 项误报）。
    * `type` 为 `boundingbox` / `path` / `point` / `clipping` 的附件**不带图片**，
      必须跳过，否则 `armL_path` 这类路径约束会被当成缺图。
    """
    need = {}
    for skin in data.get('skins', []):
        for slot, atts in (skin.get('attachments') or {}).items():
            for nm, a in atts.items():
                if a.get('type') in ('boundingbox', 'path', 'point', 'clipping'):
                    continue
                need.setdefault(resolve_image_name(nm, a), a)
    return need


def _single_image_path(json_path, name):
    """单图在哪 —— **必须覆盖 `images_original/`**，否则这项检查永远是"没测"。

    实测踩过（2026-09 审查）：原来只在 JSON **同级目录**找 `<name>.png`，
    而交付件/工程里的单图在 `images_original/`（`prepare` 写 `images:'./images_original/'`）。
    结果 `declared_size_mismatch` 恒为空，`cmd_diagnose` 却把它当成"通过"的必要条件 ——
    又一次"没测伪装成通过"（§9.1）。这里按 顺序 试：skeleton.images 指的相对目录 ->
    JSON 同级 -> `images_original/`。
    """
    base = os.path.dirname(os.path.abspath(json_path))
    rel = name.replace('/', os.sep) + '.png'
    cands = []
    try:
        d = json.load(open(json_path, encoding='utf-8'))
        img_field = ((d.get('skeleton') or {}).get('images') or '').strip()
        if img_field:
            cands.append(os.path.normpath(os.path.join(base, img_field, rel)))
    except Exception:
        pass
    cands.append(os.path.join(base, rel))
    cands.append(os.path.join(base, 'images_original', rel))
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def _cross_check(json_path, page):
    d = json.load(open(json_path, encoding='utf-8'))
    need = _collect_needed(d)
    atlas_names = {r['name'] for r in page['regions']}
    out = {'json_images': len(need),
           'json_not_in_atlas': sorted(set(need) - atlas_names),
           'atlas_not_in_json': sorted(atlas_names - set(need))}
    # 声明尺寸 vs 磁盘单图（找不到就计入 unchecked，**不装作通过**）
    bad, checked, unchecked = [], 0, []
    for name, a in need.items():
        w, h = a.get('width'), a.get('height')
        if not w or not h:
            continue
        f = _single_image_path(json_path, name)
        if not f:
            unchecked.append(name)
            continue
        checked += 1
        im = Image.open(f)
        if (im.width, im.height) != (w, h):
            bad.append((name, im.size, (w, h)))
    out['declared_size_mismatch'] = bad
    out['declared_size_checked'] = checked
    out['declared_size_unchecked'] = unchecked
    # 网格附件 width/height 是否等于图集未裁白尺寸（`'mesh' in type` 才能覆盖 linkedmesh）
    byname = {r['name']: r for r in page['regions']}
    mesh_bad = []
    for name, a in need.items():
        if 'mesh' not in str(a.get('type')) or name not in byname:
            continue
        if not a.get('width') or not a.get('height'):
            continue
        r = byname[name]
        if (a.get('width'), a.get('height')) != (r['ow'], r['oh']):
            mesh_bad.append((name, (a.get('width'), a.get('height')), (r['ow'], r['oh'])))
    out['mesh_size_mismatch'] = mesh_bad
    out['skeleton'] = d['skeleton']
    return out


# ------------------------------------------------------------------ 页图规范化
def page_coverage(page, alpha):
    """不透明像素落在区域矩形内的比例（%）。atlas 与页图吻合时应接近 100。"""
    h, w = alpha.shape
    cover = np.zeros((h, w), bool)
    for r in page['regions']:
        x, y, bw, bh = footprint(r)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + bw), min(h, y + bh)
        if x1 > x0 and y1 > y0:
            cover[y0:y1, x0:x1] = True
    tot = int(alpha.sum())
    return 100.0 * float((alpha & cover).sum()) / tot if tot else 0.0


def fix_page(atlas_path, margin=2.0, size_tol=2, rel_tol=0.005):
    """就地修复「页名后缀不符」与「页图尺寸不符」，返回报告。

    尺寸不符有两种成因，用**可复算的**指标二选一（谁的不透明覆盖率更高取谁）：

    * H1 页图被重新采样过 -> 把页图缩回 atlas 声明的尺寸。
      实测 Nomad 属此类：atlas 声明 1985x284、给的 PNG 是 2048x256；
      缩回后 `blade1` 恰好 294x50，与 atlas 的 `size:` 完全一致；覆盖率 93.26% -> 99.90%。
    * H2 只是 `size:` 行过期、区域坐标本来就对 -> 只改 `size:` 行，不动页图。

    **H3（新增，覆盖率的"说不清"档）**：两边覆盖率差距在 `margin` 之内、**且尺寸只差
    几像素**（绝对值 <= `size_tol` 或相对 <= `rel_tol`）时，判定为"`size:` 行过期"，
    只改 `size:` 行、**不重采样页图**，并记进 `ambiguous` 供交付说明提示。

    为什么是"不重采样"而不是"报错"：这两种解释在视觉上不可分，但代价**极不对称** ——
    改 `size:` 行不动像素，最多多/少一圈空白；缩图会让**全部**像素重采样一次，
    且不可逆。实测 `30501_sanjiaotou`（声明 1462、实际 1463，差 1px，覆盖率 99.93/99.94）
    与 `nanzhu_manianchunjie`（984 / 985）就是被原来的直接报错挡住整条流水线的。

    尺寸差得**大**且两边都说不通时，仍然**报错而不是猜**。
    """
    out = {'renamed': [], 'resized': [], 'size_line_fixed': [],
           'ambiguous': [], 'checked': []}

    mapping = {}
    for p in parse_atlas(atlas_path):
        f = resolve_page_image(atlas_path, p)
        if f is None:
            raise FileNotFoundError('页图不存在: %s' % p['name'])
        b = os.path.basename(f)
        if b != p['name']:
            mapping[p['name']] = b
    if mapping:
        rewrite_page_names(atlas_path, mapping)
        out['renamed'] = sorted(mapping.items())

    for p in parse_atlas(atlas_path):
        f = resolve_page_image(atlas_path, p)
        img = Image.open(f).convert('RGBA')
        want = (p['width'], p['height'])
        if img.size == want:
            out['checked'].append((p['name'], '尺寸一致', list(img.size), None, None))
            continue
        a0 = np.asarray(img)[:, :, 3] > 0
        c0 = page_coverage(p, a0)                                  # H2：不动页图
        c1 = page_coverage(p, np.asarray(
            img.resize(want, Image.LANCZOS))[:, :, 3] > 0)         # H1：缩回声明尺寸
        out['checked'].append((p['name'], '尺寸不符', list(img.size), c0, c1))
        if c1 > c0 + margin:
            img.resize(want, Image.LANCZOS).save(f)
            out['resized'].append((p['name'], list(img.size), list(want), round(c1, 2)))
        elif c0 > c1 + margin:
            set_page_size(atlas_path, p['name'], img.width, img.height)
            out['size_line_fixed'].append((p['name'], list(want), list(img.size), round(c0, 2)))
        else:
            # H3：覆盖率说不清、但尺寸只差几像素 -> 按"声明过期"处理，不改像素。
            # 选它的理由见 docstring：改 size 行无损，缩图会全图重采样。
            #
            # ⚠️ 唯一的拒绝条件：**原本放得下、改完反而放不下**。
            #    H3 把声明改成"实际图尺寸"，若页图比声明**小**，原本按大画布打包的
            #    区域就会越界 —— 这才是这步可能造成的真实损害，必须挡住。
            #    反过来，源图集本来就有区域越界（实测 30501 的 `yanchen` 超出 2px），
            #    那是源缺陷，不该因此拒绝修复。
            #    （首版守卫写成"改完必须全部放得下"，把 30501 挡回去了 —— 全量回归抓到的。）
            dw, dh = abs(img.width - want[0]), abs(img.height - want[1])
            rel = max(dw / max(img.width, 1), dh / max(img.height, 1))

            def _fits(pw_, ph_):
                return all(footprint(r)[0] + footprint(r)[2] <= pw_
                           and footprint(r)[1] + footprint(r)[3] <= ph_
                           for r in p['regions'])

            fits_new = _fits(img.width, img.height)
            fits_old = _fits(want[0], want[1])
            if (max(dw, dh) <= size_tol or rel <= rel_tol) and (fits_new or not fits_old):
                set_page_size(atlas_path, p['name'], img.width, img.height)
                out['ambiguous'].append(
                    (p['name'], list(want), list(img.size), round(c0, 2)))
            else:
                raise RuntimeError(
                    '页 %s 尺寸不符（声明 %s，实际 %s）但两种假设都说不通（覆盖率 %.2f / %.2f），'
                    '需人工判断' % (p['name'], want, img.size, c0, c1))
    return out


def region_groups(regions):
    """把**几何完全相同的区域**归成一组（别名组），返回 [组索引]。

    实测依据：Spine 的多皮肤会共用同一张图，atlas 里于是出现名字不同、
    但 `xy/size/orig/offset/rotate` 逐字段一模一样的条目 ——
    例如 Nomad 的 `nomad_normal/torso` 与 `nomad_elite/torso`，
    cha_4205 的 `weapon` 与 `weapon_09`。它们是**同一张图的两个名字**，
    必须共享同一份像素；当成"互相污染"处理会把其中一个清空。
    """
    key2g, gid = {}, []
    for r in regions:
        k = (footprint(r), r['deg'], r['ox'], r['oy'], r['ow'], r['oh'])
        if k not in key2g:
            key2g[k] = len(key2g)
        gid.append(key2g[k])
    return gid


# ------------------------------------------------------ 网格几何（判"哪些像素是自己要的"）
def _raster_uv_tris(a, ow, oh):
    """把网格的三角形在**未裁白画布空间**光栅化。

    `uvs` 是归一化到未裁白原尺寸的，所以 `uv * (ow, oh)` 就是画布像素坐标。
    返回 (oh, ow) 的 bool 掩码 = 这个附件**真正会采样**的范围。
    """
    uv, tr = a.get('uvs'), a.get('triangles')
    if not uv or not tr:
        return None
    n = len(uv) // 2
    pts = [(uv[2 * i] * ow, uv[2 * i + 1] * oh) for i in range(n)]
    im = Image.new('1', (max(1, ow), max(1, oh)), 0)
    dr = ImageDraw.Draw(im)
    for k in range(0, len(tr) - 2, 3):
        i, j, m = int(tr[k]), int(tr[k + 1]), int(tr[k + 2])
        if max(i, j, m) >= n:
            continue
        dr.polygon([pts[i], pts[j], pts[m]], fill=1)
    return np.asarray(im, bool)


def mesh_coverage(json_path, regions):
    """每个区域**实际会被网格采样**的画布范围 -> {区域名: (oh,ow) bool 掩码}。

    这是"重叠区到底该归谁"的**唯一可靠判据**：连通域归属在精灵彼此粘连时完全失效
    （实测某素材整页 1200×865 就是一个连通域，面积 428103），
    而网格顶点是美术自己画的，精确描述了该附件用到画布的哪一块。

    返回 `None` 表示该区域没有网格信息（`region` 类型附件 = 整个四边形都采样），
    调用方应退回原来的判据。
    """
    if not json_path:
        return {}
    d = json.load(open(json_path, encoding='utf-8'))
    refs = {}
    for s in d.get('skins', []):
        for _slot, atts in (s.get('attachments') or {}).items():
            for nm, a in atts.items():
                refs.setdefault(resolve_image_name(nm, a), []).append(a)
    out = {}
    for r in regions:
        m = None
        for a in refs.get(r['name'], []):
            f = deref_linkedmesh(d, a)
            if not f or 'mesh' not in str(f.get('type', '')):
                continue
            mm = _raster_uv_tris(f, r['ow'], r['oh'])
            if mm is not None:
                m = mm if m is None else (m | mm)
        out[r['name']] = m
    return out


def _canvas_mask_to_page(m, r):
    """画布空间掩码 -> **页内矩形空间**掩码（与 `crop_trimmed` 的结果同朝向同尺寸）。

    ⚠️ 切画布必须用**区域自己的** `r['w']` / `r['h']`，**不能**用 `footprint()` 的返回值 ——
    后者对 `deg 90/270` 做过宽高互换（那是"页内矩形"的尺寸），拿去切画布会切错位置。
    实测踩过：`armR2`（deg=90）用 `footprint` 切出 `(77,77)`（画布是 `(122,77)`），
    触发补零分支 -> 掩码整块错位 -> 交付单图只有 4305 像素（正确应为 4539）。
    """
    cw, ch = r['w'], r['h']
    top = max(0, r['oh'] - r['oy'] - ch)
    left = max(0, r['ox'])
    sub = m[top:top + ch, left:left + cw]
    if sub.shape != (ch, cw):
        pad = np.zeros((ch, cw), bool)
        pad[:min(ch, sub.shape[0]), :min(cw, sub.shape[1])] = sub[:ch, :cw]
        sub = pad
    t = Image.fromarray((sub * 255).astype(np.uint8), 'L')
    if r['deg'] == 90:                      # crop_trimmed 的反变换
        t = t.transpose(Image.ROTATE_90)
    elif r['deg'] == 270:
        t = t.transpose(Image.ROTATE_270)
    elif r['deg'] == 180:
        t = t.transpose(Image.ROTATE_180)
    return np.asarray(t) > 127


# ------------------------------------------------------------------ 去污染
# ------------------------------------------------------------------ 收紧重打包
def _used_box(img, mesh):
    """区域「实际用到的范围」的裁剪框 (l, t, r, b)。

    有网格 -> 网格覆盖的 bbox（网格顶点是美术画的，精确描述用到画布哪一块）；
    没网格（`region` 类型，四边形采样整张画布）-> 图像不透明内容的 bbox。
    """
    if mesh is not None and mesh.any():
        ys, xs = np.nonzero(mesh)
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    a = np.asarray(img)[:, :, 3] > 0
    if not a.any():
        return None
    ys, xs = np.nonzero(a)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def tight_pack(proj_dir, json_path=None, page_w=2048, spacing=2, pad_px=2):
    """**把所有区域统一收紧到"实际用到"的范围**，重写 atlas 的 `offsets` 并重打包。

    动机：源图集的区域大多是**未裁白**的（`orig == size`、`offset 0,0`），
    于是编辑器里区域边界比美术大一圈。这里统一按同一套规则收紧：

      * 有网格 -> 网格覆盖 bbox（`mesh_coverage`）
      * 无网格 -> 图像内容 bbox
      * 再外扩 `pad_px` 像素，避免削掉抗锯齿边

    **JSON 不用改** —— 网格的 `uvs` 本来就归一化在未裁白画布上，
    atlas 的 `offsets = (l, oh - b, ow, oh)`（y 从下边缘量）已把"从哪儿裁的"讲清楚。
    `images_original/` 保持未裁白原样不动，只重写顶层 atlas + 页图。
    """
    proj_dir = os.path.abspath(proj_dir)
    # ⚠️ 取候选文件必须**排除 `_` 开头**（`_replaced_*` 备份等）。
    # 实测踩过：`sorted(glob('*.atlas'))[0]` 会把 `_replaced_leega.atlas` 排在
    # `leega.atlas` 前面（`_` = 0x5F < `l` = 0x6C），于是**把收紧后的 atlas 写进了备份**，
    # 而真正的 atlas 还留着旧尺寸、页图却已换成新的 -> 交付件自相矛盾
    # （`分区=False`、反解回环 0/125）。2026-09 修。
    js = json_path or sorted(_triplet_files(proj_dir, 'json'),
                             key=os.path.getsize, reverse=True)[0]
    at = sorted(_triplet_files(proj_dir, 'atlas'))[0]
    img_dir = os.path.join(proj_dir, 'images_original')
    pages = parse_atlas(at)
    if len(pages) != 1:
        raise ValueError('tight_pack 只支持单页图集，本图集 %d 页' % len(pages))
    p = pages[0]
    cov = mesh_coverage(js, p['regions'])

    items = []
    for r in p['regions']:
        f = os.path.join(img_dir, r['name'].replace('/', os.sep) + '.png')
        img = Image.open(f).convert('RGBA')
        if (img.width, img.height) != (r['ow'], r['oh']):
            r['ow'], r['oh'] = img.width, img.height
        box = _used_box(img, cov.get(r['name']))
        if box is None:
            items.append((r, img, (0, 0, img.width, img.height)))
            continue
        left, top, right, bot = box
        left = max(0, left - pad_px)
        top = max(0, top - pad_px)
        right = min(img.width, right + pad_px)
        bot = min(img.height, bot + pad_px)
        items.append((r, img, (left, top, right, bot)))

    # 货架式摆放（按高度降序），页宽固定、页高自动
    # ⚠️ 页宽必须先容纳**最宽的区域**，否则 `page.paste` 越界被 PIL 静默裁掉，
    #    而 atlas 仍声明完整宽度 -> 交付件静默缺内容（2026-09 修）
    widest = max(((right - left) + spacing * 2) for (_, _, (left, top, right, bot)) in items) \
        if items else page_w
    if widest > page_w:
        page_w = int(widest)
    order = sorted(range(len(items)), key=lambda i: -(items[i][2][3] - items[i][2][1]))
    place, x, y, shelf = {}, 0, 0, 0
    for i in order:
        left, top, right, bot = items[i][2]
        bw, bh = (right - left) + spacing * 2, (bot - top) + spacing * 2
        if x + bw > page_w and x > 0:
            x, y, shelf = 0, y + shelf, 0
        place[i] = (x, y)
        x += bw
        shelf = max(shelf, bh)
    page_h = int(np.ceil((y + shelf) / 4.0) * 4)
    page_h = max(page_h, 4)
    page = Image.new('RGBA', (page_w, page_h), (0, 0, 0, 0))

    entries, stats = [], {'regions': 0, 'before_px': 0, 'after_px': 0, 'trimmed': 0}
    for i, (r, img, (left, top, right, bot)) in enumerate(items):
        px, py = place[i]
        crop = img.crop((left, top, right, bot))
        page.paste(crop, (px + spacing, py + spacing))
        ow, oh = img.width, img.height
        offs = None
        if (left, top, right - left, bot - top) != (0, 0, ow, oh):
            offs = (left, oh - bot, ow, oh)          # y 从下边缘量
            stats['trimmed'] += 1
        entries.append((r['name'], px + spacing, py + spacing,
                        crop.width, crop.height, offs, 0))
        stats['regions'] += 1
        stats['before_px'] += ow * oh
        stats['after_px'] += crop.width * crop.height
    # pma 一致性：atlas 写了 `pma:true` 就必须交**预乘**像素（我们的单图是直通 alpha）。
    # 否则运行时会按预乘解读，半透明边缘发暗/发白。
    pma = any('pma' in str(k).lower() and 'true' in str(v).lower()
              for k, v in p['props'].items())
    if pma:
        arr = np.asarray(page).astype(np.float32)
        arr[:, :, :3] *= (arr[:, :, 3:4] / 255.0)
        page = Image.fromarray(arr.round().clip(0, 255).astype(np.uint8), 'RGBA')
        stats['premultiplied'] = True
    page.save(os.path.join(proj_dir, p['name']))
    props = ['%s:%s' % (k, v) for k, v in p['props'].items() if k != 'size']
    if not any(s.lower().startswith('pma') for s in props):
        props.insert(0, 'pma:false')
    write_atlas(at, p['name'], page_w, page_h, entries, props)
    stats['page'] = [page_w, page_h]
    stats['saved_ratio'] = round(1.0 - stats['after_px'] / float(stats['before_px']), 4) \
        if stats['before_px'] else 0.0
    return stats


def decontaminate(atlas_path, out_dir, json_path=None, verbose=True,
                  min_private=0.01, min_keep=0.5, overlap='mesh'):
    """把每个区域里**邻居的像素**摘掉，导出未裁白原尺寸单图。

    判据（`overlap='mesh'`，默认）：

    1. **有网格的 -> 按网格裁**。网格顶点是美术画的，`uvs × (ow, oh)` 光栅化出的三角形
       就是该附件真正会采样的范围，网格外一律置透明。**不做外扩**：实测 `armR2` 在
       pad=0 时本体已完整，外扩反而会把邻居的边放回来。

       ⚠️ 网格精度因附件而异（`armR2` 贴合、`handR1` 偏小、`armL2` 偏大）——
       统一按网格切，削到本体的属于源数据问题，交人工复核。

    2. **没有网格的**（`region` 类型附件 —— 整个四边形都采样）-> 连通域仲裁：
       像素只被一个别名组覆盖就无条件保留；只有落在多组重叠区的才靠
       「连通域 IoU 最大」裁决。

    `overlap='keep'` 是逃生开关：重叠区一律保留，绝不削本体（代价是带邻居碎片）。

    保守兜底**只对"没有网格"的第 2 条路径生效**：私有区占比 < `min_private` 且判据要
    拿走一半以上 -> 回退原始裁切。按网格裁的一律不回退，否则 `hair` 这类
    "矩形完全落在别人矩形里"（private = 0）的区域永远清不干净。
    """
    pages = parse_atlas(atlas_path)
    os.makedirs(out_dir, exist_ok=True)
    report = {'regions': 0, 'cleaned_pixels': 0, 'affected': [],
              'multi_covered': 0, 'alias_groups': 0,
              'fallback': [], 'mesh_kept': 0, 'mesh_cut': 0, 'out_of_bounds': []}
    for p in pages:
        img = Image.open(resolve_page_image(atlas_path, p)).convert('RGBA')
        P = np.asarray(img)
        H, W = P.shape[:2]
        alpha = P[:, :, 3] > 0
        gid = region_groups(p['regions'])
        ng = max(gid) + 1 if gid else 0
        report['alias_groups'] += len(set(gid))
        grects = [None] * ng
        for r, g in zip(p['regions'], gid):
            grects[g] = footprint(r)

        # 覆盖计数按**组**计：别名之间不算重叠
        cover = np.zeros((H, W), np.int16)
        for (x, y, w, h) in grects:
            cover[max(0, y):y + h, max(0, x):x + w] += 1
        report['multi_covered'] += int(((cover > 1) & alpha).sum())

        # 算每个区域真正会被网格采样到的范围（画布空间）
        cov = mesh_coverage(json_path, p['regions']) if json_path else {}

        # 连通域仲裁**只服务"没有网格"的区域**，没必要白算 —— 它是全程最贵的一步
        # （整页 ndimage.label + 每个连通域对所有组算 IoU）。全部区域都有网格时跳过。
        best_map = None
        if any(cov.get(r['name']) is None for r in p['regions']):
            lab, nlab = ndimage.label(alpha, structure=np.ones((3, 3)))
            lut = np.zeros(nlab + 1, np.int32)      # 连通域 -> 组索引+1
            for i, sl in enumerate(ndimage.find_objects(lab)):
                lbl = i + 1
                m = (lab[sl] == lbl)
                area = int(m.sum())
                if area < 8:
                    continue
                best, bestkey = 0, None
                ys, xs = sl
                for g, (x, y, w, h) in enumerate(grects):
                    y0, y1 = max(ys.start, y), min(ys.stop, y + h)
                    x0, x1 = max(xs.start, x), min(xs.stop, x + w)
                    if x1 <= x0 or y1 <= y0:
                        continue
                    ia = int(m[y0 - ys.start:y1 - ys.start,
                               x0 - xs.start:x1 - xs.start].sum())
                    if ia == 0:
                        continue
                    iou = ia / float(area + w * h - ia)
                    key = (round(iou, 6), round(ia / float(area), 6))
                    if bestkey is None or key > bestkey:
                        bestkey, best = key, g + 1
                lut[lbl] = best
            best_map = lut[lab]

        for r, g in zip(p['regions'], gid):
            x, y, w, h = footprint(r)
            # ⚠️ 区域越出页图时，numpy 的负索引会**静默绕回**（或让 keep/sub 形状对不上，
            # 抛一句看不懂的 broadcast ValueError）。这里显式走 PIL 的越界裁切
            # （越界部分补透明），并且**不做去污染**（保留原样 = 保守），记进报告。
            if x < 0 or y < 0 or x + w > W or y + h > H:
                t0 = Image.fromarray(P).crop((x, y, x + w, y + h))
                t0 = t0.transpose(Image.ROTATE_270) if r['deg'] == 90 else \
                    t0.transpose(Image.ROTATE_90) if r['deg'] == 270 else \
                    t0.transpose(Image.ROTATE_180) if r['deg'] == 180 else t0
                canvas = Image.new('RGBA', (r['ow'], r['oh']), (0, 0, 0, 0))
                canvas.paste(t0, (r['ox'], r['oh'] - r['oy'] - t0.size[1]))
                dst = os.path.join(out_dir, r['name'] + '.png')
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                canvas.save(dst)
                report['regions'] += 1
                report.setdefault('out_of_bounds', []).append((r['name'], x, y, w, h))
                continue
            cv = cover[y:y + h, x:x + w]
            opaque = P[y:y + h, x:x + w, 3] > 0
            mesh_keep = None
            mm = cov.get(r['name'])
            if mm is not None:
                pm = _canvas_mask_to_page(mm, r)
                if pm.shape == (h, w):
                    mesh_keep = pm
            if overlap == 'keep':
                # 逃生开关：重叠区一律保留（绝不削本体，代价是带邻居碎片）
                keep = np.ones_like(cv, bool)
            elif mesh_keep is not None:
                # **按网格裁剪**：网格覆盖到哪就留哪，网格外一律置透明。
                # 曾有过一道"网格可信度"闸门（网格漏掉私有区内容就不切），已按用户要求去掉：
                # 网格精度因附件而异（`armR2` 贴合、`handR1` 偏小、`armL2` 偏大），
                # 统一按网格切，削到本体的属于源数据问题，交人工复核。
                keep = mesh_keep
                report['mesh_kept'] += 1
            else:
                # 没有网格（`region` 类型附件：整个四边形都采样）-> 退回连通域仲裁
                keep = (cv == 1) | (best_map[y:y + h, x:x + w] == g + 1)
            sub = P[y:y + h, x:x + w].copy()
            before = int((sub[:, :, 3] > 0).sum())
            sub[..., 3] = np.where(keep, sub[..., 3], 0)
            after = int((sub[:, :, 3] > 0).sum())
            private = (int(((cv == 1) & opaque).sum()) / float(before)) if before else 1.0
            # 保守回退**只对"没有网格"的兜底路径**生效 —— 按网格裁的区域一律不回退，
            # 否则 `hair` 这类"矩形完全落在别人矩形里"（private = 0）的区域永远清不干净。
            if mesh_keep is None and before and private < min_private \
                    and after < before * min_keep:
                sub[..., 3] = P[y:y + h, x:x + w, 3]
                report['fallback'].append((r['name'], round(private, 4), before, after))
                after = before
            elif mesh_keep is not None:
                report['mesh_cut'] += before - after
            # 还原旋转 + 贴回未裁白画布
            t = Image.fromarray(sub, 'RGBA')
            if r['deg'] == 90:
                t = t.transpose(Image.ROTATE_270)
            elif r['deg'] == 270:
                t = t.transpose(Image.ROTATE_90)
            elif r['deg'] == 180:
                t = t.transpose(Image.ROTATE_180)
            canvas = Image.new('RGBA', (r['ow'], r['oh']), (0, 0, 0, 0))
            canvas.paste(t, (r['ox'], r['oh'] - r['oy'] - t.size[1]))
            # 区域名可以带 `/`（= Spine 里图片的子目录），要建出父目录
            dst = os.path.join(out_dir, r['name'] + '.png')
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            canvas.save(dst)
            report['regions'] += 1
            if before != after:
                report['cleaned_pixels'] += before - after
                report['affected'].append((r['name'], before - after, before, after))
    report['affected'].sort(key=lambda z: -z[1])
    if verbose:
        print('去污染：%d 个区域（%d 个别名组），清掉外来像素 %d，受影响 %d 个'
              '（重叠区共 %d 像素；其中 %d 个区域按**网格**裁剪，共切掉 %d 像素）'
              % (report['regions'], report['alias_groups'], report['cleaned_pixels'],
                 len(report['affected']), report['multi_covered'],
                 report['mesh_kept'], report['mesh_cut']))
        if report['fallback']:
            print('  ⚠ %d 个区域无私有区、去污染结果不可信，已回退为原始裁切（需人工复核）：'
                  % len(report['fallback']))
            for nm, pv, b0, b1 in report['fallback']:
                print('      %-28s private %.2f%%  %d -> %d' % (nm, 100 * pv, b0, b1))
        if report['out_of_bounds']:
            print('  ⚠ %d 个区域越出页图，已按 PIL 越界裁切（**未做去污染**）：%s'
                  % (len(report['out_of_bounds']),
                     [o[0] for o in report['out_of_bounds'][:4]]))
    return report


# ------------------------------------------------------------------ 重打包
def _bleed(img):
    """把边缘 RGB 向外扩散到透明像素，避免 Linear 过滤出现暗边。"""
    a = np.asarray(img).copy()
    solid = a[:, :, 3] > 0
    if not solid.any():
        return img
    idx = ndimage.distance_transform_edt(~solid, return_indices=True)[1]
    a[:, :, :3] = a[:, :, :3][idx[0], idx[1]]
    return Image.fromarray(a, 'RGBA')


def repack(atlas_path, clean_dir, out_dir, page_w=1024, pad=2):
    """用去污染后的单图重新打包成**无重叠**的 atlas（json 无需改动）。

    `offsets` / 裁白后尺寸 / 区域名全部保持不变，只重算 bounds 与页图。
    """
    pages = parse_atlas(atlas_path)
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    for p in pages:
        regions = list(p['regions'])
        imgs = {}
        for r in regions:
            f = os.path.join(clean_dir, r['name'] + '.png')
            full = Image.open(f).convert('RGBA')
            # 从「未裁白画布」取出「裁白后」的那块
            top = r['oh'] - r['oy'] - r['h']
            imgs[r['name']] = full.crop((r['ox'], top, r['ox'] + r['w'], top + r['h']))
        # 摆放按高度降序（shelf 更省），但**写出时用原始区域顺序**
        # ⚠️ 页宽要先容纳最宽的区域，否则 paste 越界被静默裁（2026-09 修）
        widest = max((r['w'] + pad * 2) for r in regions) if regions else page_w
        if widest > page_w:
            page_w = int(widest)
        order = sorted(regions, key=lambda r: -r['h'])
        x = y = shelf = 0
        place = {}
        for r in order:
            bw, bh = r['w'] + pad * 2, r['h'] + pad * 2
            if x + bw > page_w:
                x, y, shelf = 0, y + shelf, 0
            place[r['name']] = (x, y)
            x += bw
            shelf = max(shelf, bh)
        page_h = int(np.ceil((y + shelf) / 4.0) * 4)
        page = Image.new('RGBA', (page_w, page_h), (0, 0, 0, 0))
        for r in order:
            px, py = place[r['name']]
            t = imgs[r['name']]
            buf = Image.new('RGBA', (t.width + pad * 2, t.height + pad * 2), (0, 0, 0, 0))
            buf.paste(t, (pad, pad))
            page.paste(_bleed(buf), (px, py))            # padding 归本区域独占
        page.save(os.path.join(out_dir, p['name']))
        entries = []
        for r in regions:                                # 保持原有区域顺序
            px, py = place[r['name']]
            offs = None
            if (r['ox'], r['oy'], r['ow'], r['oh']) != (0, 0, r['w'], r['h']):
                offs = (r['ox'], r['oy'], r['ow'], r['oh'])
            entries.append((r['name'], px + pad, py + pad, r['w'], r['h'], offs, 0))
        props = ['pma: false', 'filter:Linear,Linear']
        write_atlas(os.path.join(out_dir, atlas_path.split(os.sep)[-1].rsplit('.', 1)[0] + '.atlas'),
                    p['name'], page_w, page_h, entries, props)
        out[p['name']] = dict(page_size=(page_w, page_h), regions=len(entries))
    return out


# ------------------------------------------------------------------ 校验
def verify_roundtrip(atlas_path, images_dir, rgb_tol=None, alpha_tol=0):
    """用 atlas 反解出的图 必须与 images_dir 里的单图一致。

    返回 (区域总数, 异常列表, RGB最大差, alpha最大差)。

    * RGB：若该页声明 `pma: true`（预乘 alpha，Spine 4.x 默认），**把单图预乘后**再比
      （比"反预乘"紧得多，误差只来自一次 0.5 级舍入），默认容差 1；否则逐字节比，容差 0。
    * alpha：默认逐字节比。⚠️ 经 Spine 重打包的图集会被它的**裁白阈值**削掉最外圈
      极淡的边（alpha 1~3），这时把 alpha_tol 放到 4 即可 —— 差异只在 1px 边上，视觉不可见。
    """
    pages = parse_atlas(atlas_path)
    bad, total, w_rgb, w_alpha = [], 0, 0, 0
    for p in pages:
        pma = str(p['props'].get('pma', 'false')).strip().lower() == 'true'
        tol = (1 if pma else 0) if rgb_tol is None else rgb_tol
        img = Image.open(resolve_page_image(atlas_path, p)).convert('RGBA')
        for r in p['regions']:
            total += 1
            got = np.asarray(unpack_region(img, r)).astype(np.int32)
            f = os.path.join(images_dir, r['name'] + '.png')
            if not os.path.exists(f):
                bad.append((r['name'], '缺单图'))
                continue
            ref = np.asarray(Image.open(f).convert('RGBA')).astype(np.int32)
            if got.shape != ref.shape:
                bad.append((r['name'], '尺寸 %s vs %s' % (got.shape, ref.shape)))
                continue
            da = np.abs(got[:, :, 3] - ref[:, :, 3])
            amax = int(da.max()) if da.size else 0
            w_alpha = max(w_alpha, amax)
            if amax > alpha_tol:
                bad.append((r['name'], 'alpha 最大差 %d > 容差 %d' % (amax, alpha_tol)))
                continue
            a = ref[:, :, 3]
            vis = a > 0
            if pma:
                cmp_ref = np.rint(ref[:, :, :3].astype(np.float64) * a[..., None] / 255.0).astype(np.int32)
            else:
                cmp_ref = ref[:, :, :3]
            d = np.abs(got[:, :, :3][vis] - cmp_ref[vis])
            mx = int(d.max()) if d.size else 0
            w_rgb = max(w_rgb, mx)
            if mx > tol:
                bad.append((r['name'], 'RGB 最大差 %d > 容差 %d%s'
                            % (mx, tol, '（预乘域）' if pma else '')))
    return total, bad, w_rgb, w_alpha


def mesh_fit_score(json_path, images_dir, return_skips=False):
    """网格三角形按 UV<->顶点 仿射投影回图像空间，与实际画面求 IoU。
    分数越高说明「图」和「JSON 的网格」越吻合 —— 可用来判断该用哪套图。

    返回 `[(图片名, sqrt|det|, IoU), ...]`；`return_skips=True` 时返回
    `(结果, 跳过明细)`，明细形如 `(名字, 原因)`。

    ⚠️ 2026-09 修的四个缺陷（原先它**直接崩**或**一个都不评估**，还报"检查 --images"）：
    1. `W,H` 原来取 JSON 的 `width/height` —— 4.x 里是 **float**，`np.zeros((h,w))`
       直接 `TypeError`；而且网格的声明值可能是**占位值**（S041 全写 32x32）。
       改成**用单图自己的尺寸**（单图就是未裁白画布，UV 也归一化在它上面）。
    2. 原来只读 `skins[0]`（§9.5 明令禁止）—— 多皮肤资源里 `default` 常是空壳，
       于是"没有可评估的网格"。改成遍历**所有皮肤**、按图片名并集。
    3. 原来判 `type != 'mesh'`，漏掉 `linkedmesh`；改成 `'mesh' in type` + `deref_linkedmesh`。
    4. 原来 `key = path or 附件键名`，**忽略 `name`**（§9.5 的解析顺序是 path > name > 键名），
       于是 `skin6/body` 去找 `body.png`。改用 `resolve_image_name`。
    另外统一用 `_raster_uv_tris`（与 `mesh_coverage` 同一个光栅化器），
    不再留第二套像素约定的实现。
    """
    d = json.load(open(json_path, encoding='utf-8'))
    bones, order = build_skeleton(d)
    sk = d['skeleton']
    for b in order:
        update_world(b, sk.get('scaleX', 1.0), sk.get('scaleY', 1.0),
                     sk.get('x', 0.0), sk.get('y', 0.0))
    slotbone = {s['name']: s['bone'] for s in d['slots']}
    # 所有皮肤里"会引用图片"的附件，按图片名归并（同一张图可能被多个附件/皮肤引用）
    refs = {}
    for s in d.get('skins', []):
        for slot, atts in (s.get('attachments') or {}).items():
            if slot not in slotbone:
                continue
            for nm, a in atts.items():
                refs.setdefault(resolve_image_name(nm, a), []).append((slot, a))

    res, skips = [], []
    for key, items in sorted(refs.items()):
        f = os.path.join(images_dir, key.replace('/', os.sep) + '.png')
        if not os.path.exists(f):
            skips.append((key, '单图不存在: %s' % os.path.basename(f)))
            continue
        art = np.asarray(Image.open(f).convert('RGBA'))[:, :, 3] > 0
        H, W = art.shape
        mask = None
        dets = []
        for slot, a in items:
            geo = deref_linkedmesh(d, a)
            if geo is None or 'mesh' not in str(geo.get('type')) or not geo.get('uvs'):
                continue
            bone = bones.get(slotbone[slot])
            if bone is None:
                continue
            pts, uvl, tris = mesh_geometry(geo, bone, order)
            if len(uvl) != len(pts) or not tris:
                continue
            Q = np.array([[u[0] * W, u[1] * H] for u in uvl], float)
            A = np.hstack([Q, np.ones((len(Q), 1))])
            sol, *_ = np.linalg.lstsq(A, np.array(pts, float), rcond=None)
            det = abs(np.linalg.det(sol[:2, :].T))
            M = np.array([[sol[0, 0], sol[1, 0], sol[2, 0]],
                          [sol[0, 1], sol[1, 1], sol[2, 1]], [0, 0, 1.0]])
            try:
                Mi = np.linalg.inv(M)
            except np.linalg.LinAlgError:
                continue
            # 顶点 -> 图像空间（未裁白画布 = 单图尺寸），在画布上光栅化
            Pi = (Mi @ np.hstack([np.array(pts, float),
                                  np.ones((len(pts), 1))]).T).T[:, :2]
            mm = _raster_canvas_tris(Pi, tris, W, H)
            if mm is None:
                continue
            mask = mm if mask is None else (mask | mm)
            dets.append(det)
        if mask is None:
            skips.append((key, '没有可用的网格附件（region 类型 / 未解引用成功）'))
            continue
        inter = int((mask & art).sum())
        union = int((mask | art).sum())
        # 同一张图被多个网格引用时取均值（与原实现一致的口径）
        sq = (sum(d ** 0.5 for d in dets) / len(dets)) if dets else float('nan')
        res.append((key, sq, inter / union if union else 0.0))
    return (res, skips) if return_skips else res


def _raster_canvas_tris(P, tri, w, h):
    """在 (h, w) 画布上光栅化三角形，P 是各顶点的画布坐标。

    与 `_raster_uv_tris`（PIL polygon）**语义一致**，只是用重心坐标实现、
    便于处理"顶点已经投影回画布空间"的情形。像素判定用 ±0.002 容差补抗锯齿边。
    """
    m = np.zeros((h, w), bool)
    for (i, j, k) in tri:
        if max(i, j, k) >= len(P):
            continue
        p0, p1, p2 = P[i], P[j], P[k]
        x0 = max(0, int(math.floor(min(p0[0], p1[0], p2[0]))))
        x1 = min(w, int(math.ceil(max(p0[0], p1[0], p2[0]))) + 1)
        y0 = max(0, int(math.floor(min(p0[1], p1[1], p2[1]))))
        y1 = min(h, int(math.ceil(max(p0[1], p1[1], p2[1]))) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        v0, v1 = p1 - p0, p2 - p0
        den = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(den) < 1e-9:
            continue
        px, py = xs - p0[0], ys - p0[1]
        u = (px * v1[1] - v1[0] * py) / den
        v = (v0[0] * py - px * v0[1]) / den
        m[y0:y1, x0:x1] |= (u >= -0.002) & (v >= -0.002) & (u + v <= 1.002)
    return m


# ==========================================================================
# 来源: spine_pipeline.py
# ==========================================================================
# -*- coding: utf-8 -*-
"""Spine 资源修复的**三步流水线**（沉淀自 cha_1114 实战）：

  步骤 1  prepare : 解压 zip -> 解包图集(去污染) -> 出预览图，产物落 <proj>/prepare/
步骤 2  convert : 官方两步法转成目标版本（默认 4.3.26）-> 保真度校验，产物落 <proj>/convert/
步骤 3  apply   : 先比 prepare/ 与 convert/ 的渲染，一致才替换顶层；不一致则两份都留 + 出对比图
步骤 4  file    : 由 agent 看预览图定分类与目录名，归档到 assets/2d/

* 步骤 1/2 只写自己那一层的文件，**顶层只在 apply 里被动**；
* 每一步都产出可复算的校验数据（分区性 / 反解回环 / 渲染逐像素比对）；
* 转换走 **Spine 官方链路**，不手写格式转换器：
  4.x 拒绝直读 3.8 导出数据，必须先用**匹配版本**把 JSON 导入成 `.spine` 工程，
  再用目标版本打开工程（自动升级）导出。
"""


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


DEFAULT_SPINE = r'C:\Program Files\Spine\Spine.com'
DEFAULT_DST = '4.3.26'


# ------------------------------------------------------------------ 通用
def find_spine(explicit=None):
    cand = [explicit, os.environ.get('SPINE_COM'), DEFAULT_SPINE,
            r'C:\Program Files (x86)\Spine\Spine.com']
    for c in cand:
        if c and os.path.exists(c):
            return c
    raise FileNotFoundError('找不到 Spine.com，请用 --spine 指定')


def local_versions():
    """Spine 启动器本地已下载的版本号列表（%USERPROFILE%\\Spine\\updates）。"""
    d = os.path.join(os.path.expanduser('~'), 'Spine', 'updates')
    if not os.path.isdir(d):
        return []
    out = []
    for f in os.listdir(d):
        if re.fullmatch(r'\d+\.\d+\.\d+', f):
            out.append(f)
    def key(v):
        return tuple(int(x) for x in v.split('.'))
    return sorted(out, key=key)


def pick_version(want, avail):
    """want='3.8.95' 时优先取完全相同的，否则取同 major.minor 里最高的小版本。"""
    if want in avail:
        return want
    mm = '.'.join(want.split('.')[:2])
    same = [v for v in avail if v.startswith(mm + '.')]
    if same:
        return same[-1]
    return None


def _triplet_files(folder, ext):
    """目录下的 `<ext>` 候选文件，**排除 `_` 开头的**。

    `_replaced_*`（`apply --backup` 的备份）、`_prepare_report.json` 这类文件
    **不是交付件**。不排除的话 `find_triplet` 会按大小把**备份**当成当前三件套
    （实测合成用例：第二次 `apply --backup` 把 atlas 命名成
    `_replaced__replaced_x.atlas`；真项目里则可能拿 3.8 的备份去对账/归档）。
    """
    return [f for f in glob.glob(os.path.join(folder, '*.' + ext))
            if not os.path.basename(f).startswith('_')]


def find_triplet(folder):
    """找 json + atlas + 页图。**页图后缀不限** —— 可能是 .webp/.jpg 等，
    也可能后缀与 atlas 的页名不一致（实测 `.webp` 页名配 `.png` 文件）。

    ⚠️ `_` 开头的文件一律不算（见 `_triplet_files`）。
    """
    js = _triplet_files(folder, 'json')
    at = _triplet_files(folder, 'atlas')
    if not js or not at:
        raise FileNotFoundError('目录里找不到 json + atlas: %s' % folder)
    js.sort(key=lambda p: os.path.getsize(p), reverse=True)   # 骨架 JSON 通常最大
    at.sort()
    atlas = at[0]
    png = None
    try:
        png = resolve_page_image(atlas, parse_atlas(atlas)[0])
    except Exception:
        png = None
    if png is None:
        raise FileNotFoundError('找不到页图（atlas=%s）' % os.path.basename(atlas))
    return js[0], atlas, png


def _run(cmd, log):
    """跑一条 Spine CLI，返回 (退出码, **本步**的输出)。

    ⚠️ 日志是追加的（两步写同一个文件），所以返回的是**本次新增的那一段** ——
    否则步骤 B 的告警统计会把步骤 A 的同一批告警再算一遍（实测翻倍），
    "步骤B失败"的摘录也会带出步骤 A 的内容（2026-09 修）。
    """
    before = os.path.getsize(log) if os.path.exists(log) else 0
    with open(log, 'a', encoding='utf-8', errors='replace') as f:
        f.write('\n$ ' + ' '.join(cmd) + '\n')
        f.flush()
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    with open(log, encoding='utf-8', errors='replace') as f:
        f.seek(before)
        txt = f.read()
    return p.returncode, txt


# ------------------------------------------------------------------ 步骤 1
def prepare(src, proj_dir, render_preview=True, check=False, overlap='mesh'):
    """步骤 1：**解压 → 解包图集成单图 → 根据 JSON 出预览图**。产物全部落在 `prepare/`。

    * `src` 可以是 zip，也可以是已经解开的目录（含 json/atlas/png）。
    * `proj_dir` 是**工程根**；实际写入 `proj_dir/prepare/`（与 `convert/` 严格分开）。
    * 默认**不输出三方对账大表** —— 那是 `diagnose` 的活，要就传 `check=True`。
    * `overlap` 默认 `'mesh'`：有网格的区域按网格裁、网格外置透明；
      传 `'keep'` 则重叠区一律保留（逃生开关）。
    """
    proj_dir = os.path.abspath(proj_dir)
    # `prepare/` 是**中间态**：源一变就必须重做。
    # 原实现靠 `if not os.path.exists(dst)` 保护已生成的文件，于是"改了源 zip 再跑
    # build"会**静默沿用旧 atlas**（实测 30501_sanjiaotou：修好源后再跑，报错里
    # 仍是旧的 `声明 (1462, 1462)`，必须手工删掉整个工程目录才能重跑）。
    # 与 `convert` 的口径统一（`convert` 总是清空 convert/ 重做）。
    # ⚠️ 只清 `prepare/`；`原始资源_*.zip` 在工程根，属于"源归档"，**永不动**。
    out = stage_dir(proj_dir, STAGE_PREPARE)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)
    rep = {'project': proj_dir, 'stage_dir': out, 'fixed': []}

    # 1) 取到三件套（zip 就地解压；目录直接用）
    work = None
    if os.path.isdir(src):
        src_json, src_atlas, src_png = find_triplet(src)
    else:
        work = tempfile.mkdtemp(prefix='spine_prep_')
        with zipfile.ZipFile(src) as z:
            z.extractall(work)
        src_json, src_atlas, src_png = find_triplet(work)
    base = os.path.basename(src_atlas)[:-6]

    # **多页图集**：atlas 可以引用多张页图，必须**全部**搬过来。
    # 原实现只复制 `find_triplet()` 返回的第一页，于是 `fix_page()` 遍历到第二页时
    # `FileNotFoundError`（实测 zhizunnvwu222：`31801_zhizunnvwu_2.png`）。
    # `find_triplet` 保留"第一页可解析"这句守卫，这里补齐其余页。
    src_pages = []
    for pg in parse_atlas(src_atlas):
        f = resolve_page_image(src_atlas, pg)
        if f and f not in src_pages:
            src_pages.append(f)
    if not src_pages:                      # 理论上到不了（find_triplet 已保证第一页）
        src_pages = [src_png]

    atlas = os.path.join(out, base + '.atlas')
    jsonp = os.path.join(out, base + '.json')
    for p in [src_atlas] + src_pages:
        shutil.copy2(p, os.path.join(out, os.path.basename(p)))
    shutil.copy2(src_json, jsonp)          # JSON 必须用源覆盖（下面要改 images 字段）

    # 归档原始三件套（apply 交付前要用它兜底）—— 放工程根，不属于任何阶段。
    # ⚠️ **多页图集要全部收进归档**，否则回退重建时同样会缺页。
    arch = os.path.join(proj_dir, '原始资源_%s.zip' % base)
    if not os.path.exists(arch):
        with zipfile.ZipFile(arch, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in [src_json, src_atlas] + src_pages:
                z.write(p, os.path.basename(p))

    # 页图规范化：页名后缀、页图尺寸（不做这步后面全盘错位）
    fx = fix_page(atlas)
    for pg, new in fx['renamed']:
        rep['fixed'].append('页名 %s -> %s' % (pg, new))
    for pg, old, new, cov in fx['resized']:
        rep['fixed'].append('页图缩回声明尺寸 %s -> %s' % (old, new))
    for pg, old, new, cov in fx['size_line_fixed']:
        rep['fixed'].append('size 行 %s -> %s' % (old, new))
    for pg, old, new, cov in fx['ambiguous']:
        rep['fixed'].append(
            '⚠ 页 `size:` 行过期（声明 %s 实际 %s 只差几像素、覆盖率 %.2f 无法区分）'
            '—— 已按**实际图**改 `size:` 行、**不重采样**（改声明无损，缩图会让全图重采样）'
            % (old, new, cov))

    # 打包倍率自检（先看一眼，下面解包后按声明尺寸对齐）
    sc = size_scale_report(atlas, jsonp)
    rep['scale'] = sc
    # **网格体检**：图集重叠时只有网格能判归属，网格不准就没救 -> 必须提前查
    try:
        mh = mesh_health(atlas, jsonp)
        rep['mesh_health'] = mh
        badm = [(k, v) for k, v in mh.items() if not v['ok']]
        if badm:
            badm.sort(key=lambda z: z[1]['cover_ratio'])
            rep['fixed'].append(
                '⚠ 有 %d/%d 个网格**不可信**（按网格裁会削本体）：%s'
                % (len(badm), len(mh),
                   '、'.join('%s(%s)' % (k, v['why']) for k, v in badm[:4])))
    except Exception as e:                       # 体检失败不该挡住主流程
        rep['mesh_health_error'] = str(e)

    if sc.get('placeholder_suspect'):
        rep['fixed'].append(
            '⚠ 网格附件的声明尺寸疑为**占位值**（%d 个网格中 %d 个与图集不符、且对不上'
            '包内倍率，如 %s）—— 这些不做尺寸对齐；若按声明值缩会把网格图缩成占位尺寸'
            '（实测 32x32），再被网格拉伸成大块矩形残影'
            % (sc['mesh_total'], len(sc['mesh_placeholder']),
               sc['mesh_placeholder'][0] if sc['mesh_placeholder'] else '?'))

    # 解包图集（去污染）。把 JSON 传进去 —— 网格几何是判定"重叠区归谁"的首选判据
    img_dir = os.path.join(out, 'images_original')
    d = decontaminate(atlas, img_dir, json_path=jsonp, verbose=False, overlap=overlap)
    rep['images'] = d['regions']
    rep['cleaned_pixels'] = d['cleaned_pixels']
    if d['fallback']:
        rep['fixed'].append('⚠ %d 个区域无私有区，已回退原始裁切：%s'
                            % (len(d['fallback']), [f[0] for f in d['fallback']]))

    # 图集被打包成小尺寸时，把单图放大回声明尺寸（不做这步转 4.x 必散架）
    if sc['mismatch'] and sc['scale']:
        f = 1.0 / sc['scale']
        n, cropped = fit_singles_to_declared(img_dir, atlas, jsonp, f,
                                             mesh_ok=sc['mesh_explained'])
        rep['upscaled'] = round(f, 6)
        rep['upscaled_n'] = n
        rep['fixed'].append('单图按声明尺寸放大 ×%.4f：%d 张（源图集 = 声明尺寸 × %.3f）'
                            % (f, n, sc['scale']))
        if sc['mesh_explained']:
            rep['fixed'].append('网格附件里 %d 个的声明尺寸与包内倍率自洽，一并还原'
                                % len(sc['mesh_explained']))
        if cropped:
            rep['fixed'].append(
                '⚠ **%d 张放大后超量裁切**（>2px，会丢美术）：%s'
                % (len(cropped), ['%s(+%dpx)' % (c[0], c[4]) for c in cropped[:5]]))

    j = json.load(open(jsonp, encoding='utf-8'))
    j['skeleton']['images'] = './images_original/'      # 编辑器/引擎用相对路径
    json.dump(j, open(jsonp, 'w', encoding='utf-8'), ensure_ascii=False,
              separators=(',', ':'))

    # 3) 根据 JSON 出预览图（**每套皮肤一张**）
    if render_preview:
        rep['previews'] = render_previews(jsonp, img_dir, out)
        rep['skin'] = list(rep['previews'])

    if check:
        rep['diagnose'] = diagnose(atlas, jsonp)['pages'][0]

    if work:
        shutil.rmtree(work, ignore_errors=True)

    # 动作清单**落盘**：`apply` 是唯一动顶层的阶段，`prepare`/`convert`/`apply` 分开跑时
    # 它手里没有本函数的返回值，而 `apply` 收尾还会把 `prepare/` 删掉 —— 结果
    # `交付说明.md` 的「处理动作」只剩一条从归档反推的倍率行（实测 S041_skin6：
    # "单图放大 0 张"和"网格声明尺寸是占位值"这两条关键事实全丢了）。
    try:
        with open(os.path.join(out, PREPARE_REPORT), 'w', encoding='utf-8') as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1, default=str)
    except Exception:                       # 报告落盘失败不该挡住主流程
        pass
    return rep


def read_prepare_fixes(proj_dir):
    """取回步骤 1 落盘的动作清单（`prepare/_prepare_report.json`），没有就返回空。"""
    p = os.path.join(os.path.abspath(proj_dir), STAGE_PREPARE, PREPARE_REPORT)
    if not os.path.exists(p):
        return []
    try:
        return list(json.load(open(p, encoding='utf-8')).get('fixed') or [])
    except Exception:
        return []


# ------------------------------------------------------------------ 交付说明
def _archive_version(proj_dir):
    """从 `原始资源_*.zip` 里读源版本号。"""
    for z0 in glob.glob(os.path.join(proj_dir, '原始资源_*.zip')):
        with zipfile.ZipFile(z0) as z:
            for n in z.namelist():
                if n.endswith('.json'):
                    j = json.loads(z.read(n).decode('utf-8'))
                    return j.get('skeleton', {}).get('spine')
    return None


def _archive_scale(proj_dir):
    """从归档里核对**源图集的打包倍率** —— 交付说明要如实写清楚做过什么修复。"""
    zs = glob.glob(os.path.join(proj_dir, '原始资源_*.zip'))
    if not zs:
        return None
    work = tempfile.mkdtemp(prefix='spine_doc_')
    try:
        with zipfile.ZipFile(zs[0]) as z:
            z.extractall(work)
        js = sorted(_triplet_files(work, 'json'), key=os.path.getsize, reverse=True)
        at = _triplet_files(work, 'atlas')
        if not js or not at:
            return None
        fix_page(at[0])              # 页名可能写成 .webp，先规范化再对账
        return size_scale_report(at[0], js[0])
    except Exception:
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_delivery_doc(proj_dir, fixes=(), notes=()):
    """生成 `交付说明.md`。自给自足：版本号、校验数字、文件清单都现场采集。"""
    proj_dir = os.path.abspath(proj_dir)
    base = os.path.splitext(os.path.basename(find_triplet(proj_dir)[0]))[0]
    top_json, top_atlas, top_png = find_triplet(proj_dir)
    dst_ver = json.load(open(top_json, encoding='utf-8'))['skeleton'].get('spine')
    src_ver = _archive_version(proj_dir)
    d = diagnose(top_atlas, top_json)['pages'][0]
    img_dir = os.path.join(proj_dir, 'images_original')
    n, bad, w_rgb, w_alpha = verify_roundtrip(top_atlas, img_dir, alpha_tol=4)
    j = json.load(open(top_json, encoding='utf-8'))
    nimg = sum(len(v) for s in j.get('skins', [])
               for v in (s.get('attachments') or {}).values())

    L = ['# 交付说明 —— %s' % base, '',
         '## 版本', '',
         '| 项 | 值 |', '|---|---|',
         '| 源版本 | Spine **%s** |' % (src_ver or '?'),
         '| 交付版本 | Spine **%s** |' % (dst_ver or '?'),
         '| 骨骼 / 插槽 / 皮肤 | %d / %d / %s |' % (
             len(j['bones']), len(j['slots']), [s.get('name') for s in j.get('skins', [])]),
         '| 附件总数 | %d（图集区域 %d） |' % (nimg, d.get('regions')),
         '| 动画 | %d 个：%s |' % (len(j.get('animations', {})),
                                   ', '.join(list(j.get('animations', {}))[:8]) or '无'),
         '', '## 交付物', '']
    replaced = []
    for p in sorted(os.listdir(proj_dir)):
        fp = os.path.join(proj_dir, p)
        if p.startswith('_replaced_'):
            replaced.append(p)          # 被替换掉的旧三件套（备份），不是交付物
            continue
        if p.lower() == 'desktop.ini':  # Windows 目录残留
            continue
        if os.path.isfile(fp):
            L.append('* `%s`  (%d 字节)' % (p, os.path.getsize(fp)))
        elif p == 'images_original':
            n_img = sum(len(fs) for _, _, fs in os.walk(fp))   # 区域名可带 `/`，要递归数
            L.append('* `images_original/`  (%d 张单图)' % n_img)
    if replaced:
        L.append('* 备份（**非交付物**）：%s —— 本次被替换掉的旧三件套，'
                 '确认新版无误后可自行清理' % ', '.join('`%s`' % x for x in replaced))
    L += ['', '## 处理动作', '']
    # 分开跑 prepare/convert/apply 时，apply 手里没有步骤 1 的动作清单 ->
    # 回读 `prepare/_prepare_report.json`（build 一条龙则直接用传进来的）
    fixes = list(fixes) or read_prepare_fixes(proj_dir)
    sc = _archive_scale(proj_dir)
    if sc and sc['mismatch'] and sc.get('placeholder_suspect'):
        # 网格的 width/height 是占位值，**没有**按它缩放任何单图 —— 这行必须
        # 如实说，否则交付说明会记下一次根本没发生的"还原"（实测 S041_skin6）。
        fixes.append('**源图集尺寸自检**：%d/%d 个附件的声明尺寸与图集 `orig` 不符，'
                     '其中 %d 个是网格附件**占位值**（共 %d 个网格）—— 真实形状由 '
                     '`vertices` 决定，**未按它缩放这些单图**'
                     % (sc['mismatch'], sc['checked'],
                        len(sc['mesh_placeholder']), sc['mesh_total']))
    elif sc and sc['mismatch'] and sc.get('scale'):
        fixes.append('**源图集尺寸自检**：源图集 = 声明尺寸 × %.3f'
                     '（%d/%d 个附件不符，一次等比缩放可解释 %s）'
                     % (sc['scale'], sc['mismatch'], sc['checked'], sc['scale_fit']))
    elif sc and sc['mismatch']:
        fixes.append('**源图集尺寸自检**：%d/%d 个附件不符，但**推不出包内倍率**，'
                     '未做尺寸对齐（需人工看）' % (sc['mismatch'], sc['checked']))
    if fixes:
        for f in fixes:
            L.append('* %s' % f)
    else:
        L.append('* 解包图集 → 去污染 → 转 %s' % dst_ver)
    L += ['', '## 校验（可复算）', '',
          '| 指标 | 结果 |', '|---|---|',
          '| 图集区域数 | %s |' % d.get('regions'),
          '| 矩形构成页图精确分区 | **%s**（多重覆盖 %s，未覆盖 %s，重叠对 %s） |'
          % (d.get('rects_partition_page'), d.get('multi_covered'),
             d.get('uncovered'), d.get('overlapping_rect_pairs')),
          '| 三方对账（JSON↔atlas↔磁盘） | 缺 %s / 多 %s |'
          % (d.get('json_not_in_atlas') or '无', d.get('atlas_not_in_json') or '无'),
          '| 反解回环（atlas → 单图） | %d/%d 一致（RGB 最大差 %d，alpha 最大差 %d） |'
          % (n - len(bad), n, w_rgb, w_alpha),
          '| 附件尺寸 vs 图集 `orig` | 不符 %d 处 |'
          % (size_scale_report(top_atlas, top_json)['mismatch']),
          '', '## 回退', '',
          '原始三件套完整保存在 `原始资源_%s.zip` 里，随时可回退：' % base, '',
          '```bash',
          'python tools/spine/repair_spine/pipelines.py build 原始资源_%s.zip -o <空目录>' % base,
          '```', '']
    if notes:
        L += ['## 备注', ''] + ['* %s' % t for t in notes] + ['']
    path = os.path.join(proj_dir, '交付说明.md')
    open(path, 'w', encoding='utf-8').write('\n'.join(L))
    return path


# ------------------------------------------------------------------ 一条命令
def build(src, proj_dir, dst_ver=DEFAULT_DST, spine_com=None, name=None, doc=True,
          tight=True, min_iou=0.70, max_diff_ratio=0.40, overlap='mesh'):
    """**一条命令走完全流程**：prepare -> convert -> apply（含渲染一致性判定）。

    产物按阶段分开落盘，互不覆盖：

        <proj>/prepare/   源版本三件套 + images_original/ + 预览
        <proj>/convert/   目标版本三件套 + 预览
        <proj>/*.json     顶层：apply 之后的交付件（+ images_original/ + 预览 + 交付说明）

    `apply` 判定"不一致"时就**停在那里**：顶层保持源版本、`convert/` 与 `prepare/`
    两份都保留、写 `失败_需人工复核.md`，`rep['ok'] = False`（CLI 给非零退出码）。

    用户**只看顶层那份 <目标版本> 三件套 + 复原预览图**就够了；原始三件套始终归档在
    `原始资源_<项目>.zip`，随时可回退。
    """
    rep = {'project': os.path.abspath(proj_dir)}
    rep['prepare'] = prepare(src, proj_dir, check=False, overlap=overlap)
    rep['convert'] = convert(proj_dir, spine_com=spine_com, dst_ver=dst_ver, name=name)
    rep['apply'] = apply_converted(proj_dir, min_iou=min_iou,
                                   max_diff_ratio=max_diff_ratio)
    rep['ok'] = rep['apply']['ok']
    if not rep['ok']:
        return rep                      # 判定不一致 -> 停在"两阶段并存"的状态
    # 统一收紧：把所有区域裁到"实际用到"的范围并重写 offsets（见 tight_pack 注释）
    # 多页图集暂不支持（Spine 4.x 重打包后会出现），跳过不报错。
    if tight:
        try:
            rep['tight'] = tight_pack(proj_dir)
        except ValueError as e:
            rep['tight'] = {'skipped': str(e)}
    if doc:
        rep['doc'] = write_delivery_doc(proj_dir, fixes=rep['prepare']['fixed'],
                                        notes=rep['convert'].get('notes', ()))
    return rep


# ------------------------------------------------------------------ 步骤 2
# ------------------------------------------------------------- 阶段目录
# 三段产物严格分开，互不覆盖：
#
#   <proj>/prepare/   prepare 产物：源版本三件套（页图已修复）+ images_original/ + 预览
#   <proj>/convert/   convert 产物：目标版本三件套 + 预览
#   <proj>/*.json     顶层：apply 之后的交付件（拷贝自 convert/）
#
STAGE_PREPARE = 'prepare'
STAGE_CONVERT = 'convert'
PREPARE_REPORT = '_prepare_report.json'      # 步骤 1 的动作清单（apply 生成交付说明时回读）


def stage_dir(proj_dir, stage, create=True):
    d = os.path.join(os.path.abspath(proj_dir), stage)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def images_dir(proj_dir):
    """单图目录：优先 `prepare/images_original/`，兼容旧布局的顶层 `images_original/`。"""
    proj_dir = os.path.abspath(proj_dir)
    for d in (os.path.join(proj_dir, STAGE_PREPARE, 'images_original'),
              os.path.join(proj_dir, 'images_original')):
        if os.path.isdir(d):
            return d
    return os.path.join(proj_dir, STAGE_PREPARE, 'images_original')


def find_triplet_or_json(folder):
    """有些项目目录顶层没有 atlas/png（只在归档 zip 里），只要 JSON 就够导入。

    ⚠️ 排除 `_` 开头（`_replaced_*` 备份、`prepare/_prepare_report.json`）——
    否则"按大小取最大"可能挑到备份或报告，把源 JSON 认错。
    """
    js = _triplet_files(folder, 'json')
    if not js:
        raise FileNotFoundError('目录里找不到 JSON: %s' % folder)
    js.sort(key=lambda p: os.path.getsize(p), reverse=True)
    return js[0], None, None


def _align_render_pair(i0, b0, i1, b1):
    """按**世界坐标**把两张渲染图放到同一张画布上，返回两个同尺寸的 RGBA 数组。

    不能像原来那样 `resize` 到较小尺寸再比 —— 包围盒尺寸一变就是整体拉伸，
    差异全是假的（实测同一只角色只因包围盒差 1.9%，指标就从 12px 跳到 28 万 px）。
    图像 pixel(0,0) 对应世界 `(bb[0], bb[3])`，所以把世界原点放到画布固定位置即可。
    """
    px0 = max(0, -int(min(b0[0], b1[0]))) + 1
    py0 = max(0, int(max(b0[3], b1[3]))) + 1
    W = px0 + int(max(b0[2], b1[2])) + 2
    H = py0 + abs(int(min(b0[1], b1[1]))) + 2
    A = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    B = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    A.paste(i0, (px0 + int(round(b0[0])), py0 - int(round(b0[3]))))
    B.paste(i1, (px0 + int(round(b1[0])), py0 - int(round(b1[3]))))
    return np.asarray(A).astype(np.int16), np.asarray(B).astype(np.int16)


def mesh_health(atlas_path, json_path, min_cover=0.75):
    """逐网格体检：**这个网格能解释它所在区域的内容吗**？—— 提前发现"无效网格"。

    背景：图集里两两重叠时，**只有网格能判"这块像素归谁"**（连通域在这种素材上
    几乎必然失效，实测 `RogueSekaniFlamebringer` 整页 1200x865 就是一个连通域）。
    所以网格一旦不准，那个场景就没有别的判据可退 —— 必须**提前**查出来。

    判据（都在**画布空间**算，即未裁白原尺寸）：

        content_px  = 本区域内容的不透明像素数
        mesh_px     = 网格掩码像素数
        covered_px  = |网格 ∩ 内容|
        cover_ratio = covered_px / content_px     # 网格解释了本区域多少内容
        fill_ratio  = covered_px / mesh_px        # 网格自己有多少落在内容上

    * `cover_ratio ≈ 1` -> 网格精确覆盖本体，**可信**
    * `cover_ratio << 1` -> 网格明显**小于**本体，漏掉的那些是本体，
      按它切会**削掉美术** -> **不可信**（实测 `RogueSekaniFlamebringer` 的 `armR2` 只有
      35%、`legR2` 15%）
    * `fill_ratio << 1` -> 网格大部分落在空白上，网格**位置/形状不对** -> 不可信

    返回 {区域名: {...}}，只看有网格的区域。**只报告，不改行为** —— "不可信"的
    区域按网格裁会削本体，是否改用 `overlap='keep'` 由人/agent 决定。
    """
    pages = parse_atlas(atlas_path)
    p = pages[0]
    page = Image.open(resolve_page_image(atlas_path, p)).convert('RGBA')
    cov = mesh_coverage(json_path, p['regions'])
    out = {}
    for r in p['regions']:
        m = cov.get(r['name'])
        if m is None:
            continue
        x, y, w, h = footprint(r)
        crop = page.crop((x, y, x + w, y + h))
        if r['deg'] == 90:
            crop = crop.transpose(Image.ROTATE_270)
        elif r['deg'] == 270:
            crop = crop.transpose(Image.ROTATE_90)
        elif r['deg'] == 180:
            crop = crop.transpose(Image.ROTATE_180)
        canvas = Image.new('RGBA', (r['ow'], r['oh']), (0, 0, 0, 0))
        canvas.paste(crop, (r['ox'], r['oh'] - r['oy'] - crop.size[1]))
        al = np.asarray(canvas)[:, :, 3] > 0
        mesh_px = int(m.sum())
        content_px = int(al.sum())
        covered = int((m & al).sum())
        cr = (covered / float(content_px)) if content_px else 1.0
        fr = (covered / float(mesh_px)) if mesh_px else 0.0
        bad = []
        if cr < min_cover:
            bad.append('网格偏小（只解释 %.0f%% 的本体）' % (100 * cr))
        if fr < 0.5:
            bad.append('网格多半落在空白上（%.0f%% 命中内容）' % (100 * fr))
        out[r['name']] = {'mesh_px': mesh_px, 'content_px': content_px,
                          'covered_px': covered, 'cover_ratio': round(cr, 4),
                          'fill_ratio': round(fr, 4),
                          'ok': not bad, 'why': '；'.join(bad)}
    return out


def diff_images(src_json, dst_json, img_dir, out_dir, tol_rgb=24, panel_w=700):
    """生成逐皮肤的「prepare vs convert」对比图：prepare | convert | 差异染色。

    配色：**红**=只有源有（目标丢了）；**绿**=只有目标有；**蓝**=两边都有但 RGB 差 >
    `tol_rgb`；**灰白**=两边一致。人工复核时直接看图，不用猜。

    返回 {皮肤: 文件路径}。⚠️ 对"空壳皮肤"**没有守卫**，调用方用 `_safe_diff_images`。
    """
    d = json.load(open(src_json, encoding='utf-8'))
    off = (d['skeleton'].get('x', 0.0), d['skeleton'].get('y', 0.0))
    out = {}
    for sn in [x.get('name', 'default') for x in (d.get('skins') or [])] or ['default']:
        i0, b0 = Renderer(src_json, img_dir, ss=2, pad=0, skin=sn).render()
        i1, b1 = Renderer(dst_json, img_dir, ss=2, pad=0, skin=sn,
                          sk_offset=off).render()
        A, B = _align_render_pair(i0, b0, i1, b1)
        ma, mb = A[:, :, 3] > 0, B[:, :, 3] > 0
        rgbd = np.abs(A[:, :, :3].astype(int) - B[:, :, :3].astype(int)).max(axis=2)
        both = ma & mb
        vis = np.zeros((A.shape[0], A.shape[1], 3), np.uint8)
        vis[both] = (200, 200, 205)
        vis[both & (rgbd > tol_rgb)] = (60, 130, 255)
        vis[ma & ~mb] = (235, 50, 50)
        vis[~ma & mb] = (40, 215, 70)

        def fit(im):
            c = im.convert('RGBA')
            bg = Image.new('RGBA', c.size, (32, 34, 40, 255))
            bg.alpha_composite(c)
            bg = bg.convert('RGB')
            return bg.resize((panel_w, max(1, int(bg.height * panel_w / bg.width))))

        p0, p1, pd = fit(i0), fit(i1), fit(Image.fromarray(vis))
        H = max(p0.height, p1.height, pd.height)
        sh = Image.new('RGB', (panel_w * 3 + 30, H + 34), (22, 24, 30))
        dr = ImageDraw.Draw(sh)
        for k, (im, tag) in enumerate(((p0, 'prepare（源）'), (p1, 'convert（目标）'),
                                       (pd, '差异染色'))):
            sh.paste(im, (k * (panel_w + 15), 30))
            dr.text((k * (panel_w + 15), 12), '%s  %s' % (sn, tag),
                    fill=(255, 220, 120))
        fp = os.path.join(out_dir, '对比图_%s.png' % sn.replace('/', '_'))
        sh.save(fp)
        out[sn] = fp
    return out


def _safe_diff_images(src_json, dst_json, img_dir, out_dir):
    """`diff_images` 的容错调用：**失败路径本身不能再抛异常**。

    判定"不一致"时会调它出对比图。但 `diff_images` 对"空壳皮肤"没有守卫
    （`render_compare` 有），会把同样的 `ValueError` 重新抛出来 ——
    本该写 `失败_需人工复核.md` 并返回 ok=False 的分支变成 traceback，
    文档承诺的退出码 2 也不会出现（2026-09 修）。这里兜住，只报告。
    """
    if not src_json:
        return {}
    try:
        return diff_images(src_json, dst_json, img_dir, out_dir)
    except (ValueError, OSError) as e:            # 空壳皮肤 / 缺图等
        print('  ! 对比图生成不完整：%s' % e)
        return {}


def render_compare(src_json, dst_json, img_dir, skins=None, ss=2, tol_px=1):
    """逐皮肤渲染比对：源 JSON vs 目标 JSON。返回 (每皮肤指标, 用的骨架偏移)。

    ⚠️ **必须把源骨架的 `skeleton.x/y` 补到目标渲染上再比**：4.x 移除了这两个字段，
    整只骨架会平移 (x, y)（实测本素材平移 595.77px），不补就整体错位，
    差异会被夸大成"几乎完全不同"。

    ⚠️ **必须每套皮肤都比**：多皮肤资源只比一套会漏掉皮肤专属部件。
    """
    sksrc = json.load(open(src_json, encoding='utf-8'))['skeleton']
    sk_off = (sksrc.get('x', 0.0), sksrc.get('y', 0.0))
    d = json.load(open(dst_json, encoding='utf-8'))
    if skins is None:
        skins = [s.get('name', 'default') for s in (d.get('skins') or [])] or ['default']
    per = {}
    for sn in skins:
        try:
            i0, b0 = Renderer(src_json, img_dir, ss=ss, pad=0, skin=sn).render()
            i1, b1 = Renderer(dst_json, img_dir, ss=ss, pad=0, skin=sn,
                              sk_offset=sk_off).render()
        except ValueError as e:
            # 多皮肤资源里 default 经常只是个空壳（只有 path 约束 / 少数配件），
            # 没有可渲染附件时跳过这层皮肤 —— 与 render_previews 行为一致。
            print('  ! 比对跳过 %s: %s' % (sn, e))
            continue
        A, B = _align_render_pair(i0, b0, i1, b1)
        ma, mb = A[:, :, 3] > 0, B[:, :, 3] > 0
        union = int((ma | mb).sum())
        src_px = int(ma.sum())
        diff = int((ma ^ mb).sum())
        # **带容差的硬差异**：先把两侧掩码各膨胀 tol_px 再比 ——
        # 剪影平移 1px 会把 alpha XOR 抬到二三十个百分点（一条 2px 轮廓挪 1px，
        # 两侧各翻出一片像素），但肉眼完全一样。带容差后只剩"真正多出/丢失的形状"。
        ma_d = ndimage.binary_dilation(ma, iterations=tol_px) if tol_px else ma
        mb_d = ndimage.binary_dilation(mb, iterations=tol_px) if tol_px else mb
        hard = int(((ma & ~mb_d) | (mb & ~ma_d)).sum())
        per[sn] = {'bbox': {'src': [round(b0[4], 2), round(b0[5], 2)],
                            'dst': [round(b1[4], 2), round(b1[5], 2)]},
                   'origin_shift': [round(b1[0] - b0[0], 2), round(b1[1] - b0[1], 2)],
                   'alpha_diff_px': diff,
                   'alpha_diff_ratio': round(diff / float(src_px), 4) if src_px else 0.0,
                   'hard_diff_px': hard,
                   'hard_diff_ratio': round(hard / float(src_px), 4) if src_px else 0.0,
                   'alpha_iou': round(int((ma & mb).sum()) / union, 4) if union else 1.0,
                   'rgb_max_diff': int(np.abs(A[:, :, :3] - B[:, :, :3])[ma & mb].max())
                   if (ma & mb).any() else 0}
    return per, [round(sk_off[0], 2), round(sk_off[1], 2)]


def judge_render(per, min_iou=0.70, max_diff_ratio=0.40):
    """把逐皮肤渲染指标判成"一致 / 不一致"。返回 (是否一致, 逐皮肤结论列表)。

    判定只看**带容差的硬差异占比**（默认容差 1px，见 `render_compare.tol_px`）：
    剪影整体平移 1px 属于"网格重建的正常后果"，肉眼无差别，不该判失败。
    原始 XOR 占比与 IoU 一起返回，供打印参考。

    ⚠️ **空比对 = 不一致**（2026-09 修）：全皮肤都被跳过时以前返回 `(True, [])`，
    于是"一次都没比"被判成"一致"并替换顶层。
    """
    if not per:
        return False, []
    rows, ok = [], True
    for sn, m in per.items():
        # 主判据 = **带容差的硬差异占比**；`min_iou` 只当"剪影大体重叠"的兜底下限
        # （不能拿原始 IoU 当主判据：整体平移 1px 就会把它压到 0.7x）
        good = (m.get('hard_diff_ratio', m['alpha_diff_ratio']) <= max_diff_ratio
                and m['alpha_iou'] >= min_iou)
        ok = ok and good
        rows.append((sn, m['alpha_iou'], m.get('hard_diff_px', m['alpha_diff_px']),
                     m.get('hard_diff_ratio', m['alpha_diff_ratio']), good,
                     m['alpha_diff_ratio']))
    return ok, rows


# ------------------------------------------------------------------ 步骤 4
# ★ **归档根目录（硬性）**：所有修复完成的交付件一律归档到 `assets/2d/` 下，
#   形如 `assets/2d/<分类>/<目录名>/`（如 `assets/2d/人形/女/火把女战士/`）。
#   分类与目录名由 agent 看预览图判定，见 `file_delivery`。
ASSETS_2D = r'D:\artstudio\assets\2d'


def file_delivery(proj_dir, category, as_name=None, assets_root=ASSETS_2D,
                  overwrite=True, dry_run=False):
    """步骤 4：把**顶层交付件**按分类归档到 `D:\artstudio\assets\2d\<分类>\<目录名>\`。

    ★ **归档根目录固定为 `assets/2d/`**（`ASSETS_2D`），不要往别处放。

    ⚠️ **分类和目录名都不是脚本能算出来的** —— 必须由 **agent（大模型）**
    看 `复原预览图_*.png` 判断"这是什么东西、长什么样"，再作为 `category`
    与 `as_name` 传进来。脚本只负责：确认顶层确实是交付件 -> 原样搬运 -> 报告覆盖了什么。
    **这是流程里属于 agent 的一环，不是"待人工处理"的可选项。**

    * `category`：分类路径，单层（`'特效'`）或多层（`'人形/女'`）
    * `as_name`：目标**目录名**，用**纯中文人物特征**（`'兽人狂战士'`、`'斗笠剑客'`）。
      不传则退回按顶层 JSON 名（会出现英文/源文件名，不推荐）。
      **只改目录名，包内文件名一律不动** —— atlas 基名决定图集名，JSON 引用也指着它。
    """
    proj_dir = os.path.abspath(proj_dir)
    top_json, top_atlas, top_png = find_triplet(proj_dir)
    ver = json.load(open(top_json, encoding='utf-8'))['skeleton'].get('spine')
    if not ver:
        raise RuntimeError('顶层 JSON 读不到 skeleton.spine，不像是交付件')
    # ⚠️ 两道闸：**不能把"转换失败"的工程当交付件搬走**（2026-09 修）。
    # `apply` 判定不一致时顶层仍是**源版本**（3.8.x），而且会留一份
    # `失败_需人工复核.md`；原先只检查"skeleton.spine 读得到"，于是会把
    # 未转换的源版本连同失败说明一起归档进 assets/2d/。
    if os.path.exists(os.path.join(proj_dir, '失败_需人工复核.md')):
        raise RuntimeError('工程里有 `失败_需人工复核.md` —— 这是"转换未通过"的状态，'
                           '不能当交付件归档。先看对比图解决它，或删掉说明重跑 '
                           'prepare/convert/apply')
    if str(ver).split('.')[0].isdigit() and int(str(ver).split('.')[0]) < 4:
        raise RuntimeError('顶层是 Spine %s（< 4.x）= 还没转版本（`apply` 没成功过），'
                           '不能当交付件归档；先跑 prepare/convert/apply' % ver)
    name = as_name or os.path.splitext(os.path.basename(top_json))[0]
    dest = os.path.join(assets_root, *category.split('/'), name)
    items = [os.path.basename(p) for p in (top_json, top_atlas, top_png)]
    # 多页图集：Spine 4.x 重打包可能按页尺寸切多页，find_triplet 只返第一页，
    # 其余页图要补上，否则运行期找不到页图（atlas 引用了但目录里没有）。
    for p in parse_atlas(top_atlas):
        extra = resolve_page_image(top_atlas, p)
        if extra and os.path.basename(extra) not in items:
            items.append(os.path.basename(extra))
    img = os.path.join(proj_dir, 'images_original')
    if os.path.isdir(img):
        items.append('images_original')
    items += [x for x in sorted(os.listdir(proj_dir))
              if x.startswith('复原预览图') and x.endswith('.png')]
    # `失败_需人工复核.md` **不进交付件**（上面已闸住它的存在）；只搬交付说明。
    for extra in ('交付说明.md',):
        if os.path.exists(os.path.join(proj_dir, extra)):
            items.append(extra)
    items += [x for x in sorted(os.listdir(proj_dir)) if x.startswith('原始资源_')]

    rep = {'dest': dest, 'copied': items, 'replaced': None, 'version': ver,
           'category': category, 'as_name': name,
           'auto_named': as_name is None, 'dry_run': dry_run}
    if dry_run:
        return rep
    replaced = []
    if os.path.isdir(dest):
        replaced = sorted(os.listdir(dest))
        if not overwrite:
            raise FileExistsError('目标已存在：%s（默认会覆盖；是 `--no-overwrite` 让它报错的）'
                                  % dest)
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)
    for it in items:
        src = os.path.join(proj_dir, it)
        dst = os.path.join(dest, it)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    rep['replaced'] = replaced
    return rep


def convert(proj_dir, spine_com=None, dst_ver=DEFAULT_DST, src_ver=None, force=False, name=None):
    """官方两步法转换。产物写到 `<proj>/convert/`，**不动顶层三件套**。

    name: 骨架 / 工程名（决定导出文件名）。默认取 JSON 文件名并去掉 `_fullsize` 后缀 ——
          工程必须命名成 `<骨架名>.spine`，导出名才会是 `<骨架名>.*`。
    """
    proj_dir = os.path.abspath(proj_dir)
    spine = find_spine(spine_com)
    avail = local_versions()
    if not avail:
        raise RuntimeError('Spine 本地没有已下载的版本（%s），先用启动器下载一个'
                           % os.path.join(os.path.expanduser('~'), 'Spine', 'updates'))
    pdir = stage_dir(proj_dir, STAGE_PREPARE, create=False)
    src_json, _atlas, _png = find_triplet_or_json(pdir if os.path.isdir(pdir) else proj_dir)
    j = json.load(open(src_json, encoding='utf-8'))
    cur = j['skeleton'].get('spine', '')
    want_src = src_ver or cur
    src = pick_version(want_src, avail)
    dst = pick_version(dst_ver, avail)
    if src is None:
        raise RuntimeError('本地没有 %s 系列版本可用（现有 %s）' % (want_src, avail))
    if dst is None:
        raise RuntimeError('本地没有 %s 系列版本可用（现有 %s）' % (dst_ver, avail))

    img_dir = images_dir(proj_dir)
    if not os.path.isdir(img_dir):
        raise FileNotFoundError('缺 images_original/，请先跑 prepare')

    base = name or os.path.splitext(os.path.basename(src_json))[0]
    if base.endswith('_fullsize'):
        base = base[:-len('_fullsize')]
    out_dir = stage_dir(proj_dir, STAGE_CONVERT)
    # `convert` 的定义就是"产出一份**新鲜**的目标版本转换" —— 所以总是清干净重做。
    # （原条件写成 `and not force`，于是**不传 --force 才清**、传了反而保留旧产物
    #   再叠加新产物：convert/ 里新旧两套并存，`find_triplet` 按大小取 JSON
    #   可能挑到**旧**的那套交付出去。2026-09 修）
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    rep = {'from': cur, 'src_ver': src, 'dst_ver': dst, 'name': base, 'steps': [],
           'spine': spine, 'force_ignored': bool(force)}
    if force:
        rep.setdefault('notes', []).append(
            '`--force` 已无意义（现在总是重新转换），留着只为兼容旧命令行')
    work = tempfile.mkdtemp(prefix='spine_conv_')
    log = os.path.join(work, 'spine.log')

    # 工作副本：把 skeleton.images 指到单图目录的绝对路径（不改用户原文件）
    work_json = os.path.join(work, base + '.json')
    jj = dict(j)
    jj['skeleton'] = dict(j['skeleton'])
    jj['skeleton']['images'] = img_dir.replace('\\', '/') + '/'
    json.dump(jj, open(work_json, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

    # 步骤 A：匹配版本导入成工程
    proj = os.path.join(work, base + '.spine')
    rc, txt = _run([spine, '-u', src, '-i', work_json, '-o', proj, '-r'], log)
    rep['steps'].append('A. Spine %s 导入 JSON -> %s（退出码 %d）' % (src, base + '.spine', rc))
    if not os.path.exists(proj):
        raise RuntimeError('步骤A失败（Spine %s 导入 JSON，退出码 %d）：\n%s'
                           % (src, rc, txt[-1500:]))
    if rc != 0:                     # 退出码非 0 但产物在 -> 记账，不静默
        rep.setdefault('notes', []).append('步骤A 退出码 %d（产物已生成，按成功继续）' % rc)

    # 步骤 B：目标版本打开工程（自动升级）导出 + 重打包图集
    rc, txt = _run([spine, '-u', dst, '-i', proj, '-o', work + os.sep + 'out', '-e', 'json+pack'], log)
    got = glob.glob(os.path.join(work, 'out', '*.json'))
    if not got:
        raise RuntimeError('步骤B失败（Spine %s 导出，退出码 %d）：\n%s'
                           % (dst, rc, txt[-1500:]))
    rep['steps'].append('B. Spine %s 打开工程并导出 json+pack（退出码 %d）' % (dst, rc))
    if rc != 0:
        rep.setdefault('notes', []).append('步骤B 退出码 %d（产物已生成，按成功继续）' % rc)
    rep['spine_log_warnings'] = {
        'slash_renamed': len(re.findall(r'Slot forward slash disallowed', txt)),
        'reset_edges': len(re.findall(r'Reset invalid edges', txt)),
    }
    if rep['spine_log_warnings']['slash_renamed']:
        rep.setdefault('notes', []).append(
            '含斜杠的插槽名被 Spine 重命名 %d 处（4.x 不允许插槽名带 `/`）'
            % rep['spine_log_warnings']['slash_renamed'])
    if rep['spine_log_warnings']['reset_edges']:
        rep.setdefault('notes', []).append(
            'Spine 重置无效边 %d 处（源数据的网格边索引不完整，Spine 自动修正；'
            '该素材家族的常见告警）' % rep['spine_log_warnings']['reset_edges'])

    for f in os.listdir(os.path.join(work, 'out')):
        shutil.copy2(os.path.join(work, 'out', f), os.path.join(out_dir, f))

    # images 字段：与 3.8 共用同一套单图
    nj = os.path.join(out_dir, base + '.json')
    jj = json.load(open(nj, encoding='utf-8'))
    jj['skeleton']['images'] = '../prepare/images_original/'
    json.dump(jj, open(nj, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

    # 校验
    nat = os.path.join(out_dir, base + '.atlas')
    drep = diagnose(nat, nj)['pages'][0]
    rep['atlas_check'] = {k: drep.get(k) for k in
                          ('regions', 'multi_covered', 'uncovered', 'out_of_bounds_regions',
                           'overlapping_rect_pairs', 'rects_partition_page',
                           'json_not_in_atlas', 'atlas_not_in_json')}
    # alpha_tol=4：Spine 重打包时会按 alpha 阈值削掉最外圈 alpha 1~3 的边，
    # 那是「裁剪舍入」不是「真错」（见 README 验收纪律）
    n, bad, w_rgb, w_alpha = verify_roundtrip(nat, img_dir, alpha_tol=4)
    rep['roundtrip_alpha'] = '%d/%d' % (n - len(bad), n)
    rep['roundtrip_rgb_tol_note'] = 'RGB 在预乘域比，容差 1（pma:true）'

    # 渲染逐像素比对：**每套皮肤都比一遍**（多皮肤资源只比一套会漏掉皮肤专属部件）
    per, sk_off = render_compare(src_json, nj, img_dir, ss=2)
    rep['render_sk_offset'] = sk_off
    rep['render_per_skin'] = per
    if per:                       # 全空时不要在这里崩（apply 的判定才是裁决者）
        rep['worst_skin'] = max(per, key=lambda k: per[k]['alpha_diff_px'])
    else:
        rep.setdefault('notes', []).append(
            '⚠ 一套皮肤都没比成（全部无可渲染附件）—— 渲染校验实际**没做**')

    # 预览（每套皮肤一张）
    prevs = render_previews(nj, img_dir, out_dir)
    rep['previews'] = prevs
    rep['preview'] = (prevs.get('default') or list(prevs.values())[0])['path']

    shutil.rmtree(work, ignore_errors=True)
    rep['out_dir'] = out_dir
    rep['steps'].append('阶段2 完成 -> convert/；下一步 apply（它会自动比对渲染并据此落盘）')
    return rep


# ------------------------------------------------------------------ 步骤 3
def apply_converted(proj_dir, keep_version_dir=False, backup=False,
                    min_iou=0.70, max_diff_ratio=0.40):
    """步骤 3：**先比对 prepare/ 与 convert/ 的渲染是否一致，再决定怎么落盘**。

    比对 = 逐皮肤渲染比对（`render_compare` + `judge_render`）：
    对同一套 `prepare/images_original/`，分别用 `prepare/<name>.json`（源）
    和 `convert/<name>.json`（目标）渲染，比 alpha 的 IoU 与差异像素占比。

    * **一致** -> 顶层三件套替换成 `convert/` 的产物，`prepare/images_original/`
      与预览图一并搬到顶层（顶层就是交付件）；`convert/` 删掉（内容已搬走）；
      原始三件套保留在 `原始资源_*.zip` 里。
    * **不一致** -> **顶层不动**、`convert/` 与 `prepare/` 两份都保留，
      写一份 `失败_需人工复核.md` 说明差在哪，交人工判断。

    返回的 `rep['ok']` 就是判定结果；CLI 据此给非零退出码。
    """
    proj_dir = os.path.abspath(proj_dir)
    sub = stage_dir(proj_dir, STAGE_CONVERT, create=False)
    if not os.path.isdir(sub):
        raise FileNotFoundError('没有 convert/ 目录，请先跑 convert')
    pdir = stage_dir(proj_dir, STAGE_PREPARE, create=False)

    f = find_triplet(sub)
    base = os.path.splitext(os.path.basename(f[0]))[0]
    img_dir = images_dir(proj_dir)
    rep = {'replaced': [], 'old_version': None, 'source_dir': sub, 'ok': None}

    # 顶层现有三件套（有些项目本来就没有 atlas/png，如狂战士）
    old = None
    try:
        old = find_triplet(proj_dir)
    except FileNotFoundError:
        pass
    # 比对的源：优先 prepare/ 里的 JSON（它就是这段工程的口径）
    src_json = os.path.join(pdir, base + '.json') if os.path.isdir(pdir) else None
    if src_json and not os.path.exists(src_json):
        src_json = old[0] if old else None
    if not src_json:
        src_json = old[0] if old else None

    # ---- ① 校验：prepare 预览（prepare/ JSON）vs convert 预览（convert/ JSON）
    if not src_json:
        rep['ok'] = True
        rep['verdict'] = '没有可比的源 JSON，跳过渲染比对（**这次比对没做**）'
        rep['render_rows'] = []
    else:
        per, sk_off = render_compare(src_json, f[0], img_dir, ss=2)
        rep['render_sk_offset'] = sk_off
        rep['render_per_skin'] = per
        ok, rows = judge_render(per, min_iou=min_iou, max_diff_ratio=max_diff_ratio)
        rep['ok'] = ok
        rep['render_rows'] = rows
        rep['threshold'] = {'min_iou': min_iou, 'max_diff_ratio': max_diff_ratio}
        if not per:
            rep['verdict'] = ('**一套皮肤都没比成**（全部无可渲染附件）—— '
                              '不能当作"一致"，需人工确认')
        else:
            rep['verdict'] = ('一致（逐皮肤 IoU >= %.2f 且差异像素 <= %.0f%%）'
                              % (min_iou, 100 * max_diff_ratio) if ok else
                              '不一致：转换后的渲染与源不一致，需人工复核')

    # ---- ② 不一致 -> 顶层不动，两份都留，写失败说明
    if not rep['ok']:
        rep['kept'] = ['convert/', 'prepare/']
        rep['diff_images'] = _safe_diff_images(src_json, f[0], img_dir, proj_dir)
        rep['doc'] = _write_fail_doc(proj_dir, rep)
        return rep

    # ---- ③ 一致 -> 替换顶层
    if old:
        rep['old_version'] = json.load(open(old[0], encoding='utf-8'))['skeleton'].get('spine')
        if backup:
            # ⚠️ **绝不能覆盖已有的 `_replaced_*`**（2026-09 修）：第二次 `apply --backup`
            # （正是 §14.5 的复诊工作流）会把"真·原始备份"换成上一次运行的产物，
            # 而交付说明仍称它"本次被替换掉的旧三件套"。已存在就换编号，把老的留住。
            numbered = False
            for p in old:
                bn = os.path.basename(p)
                dst = os.path.join(proj_dir, '_replaced_' + bn)
                if os.path.exists(dst):
                    n = 2
                    while os.path.exists(os.path.join(proj_dir, '_replaced_%d_%s' % (n, bn))):
                        n += 1
                    dst = os.path.join(proj_dir, '_replaced_%d_%s' % (n, bn))
                    numbered = True
                shutil.copy2(p, dst)
                rep.setdefault('backup', []).append(os.path.basename(dst))
            if numbered:
                rep.setdefault('notes', []).append(
                    '_replaced_* 已存在，本次另存为编号副本（老的备份没有被覆盖）')

    for src in f:
        shutil.copy2(src, os.path.join(proj_dir, os.path.basename(src)))
        rep['replaced'].append(os.path.basename(src))

    # 多页图集：atlas 可能引用多个页图（如 Spine 4.x 重打包按页尺寸切分）。
    # find_triplet 只返回第一个页图，其余要补回来；否则 verify_roundtrip 会读不到。
    # 直接从 convert/ 解析 atlas，再用 resolve_page_image 找每一页（它会逐个试常见后缀 + 大小写）。
    for p in parse_atlas(f[1]):
        extra = resolve_page_image(f[1], p)
        if extra and os.path.dirname(os.path.abspath(extra)) != os.path.abspath(proj_dir):
            dst = os.path.join(proj_dir, os.path.basename(extra))
            if not os.path.exists(dst):
                shutil.copy2(extra, dst)
                rep['replaced'].append(os.path.basename(extra))

    # 单图目录搬到顶层（交付件里要有）
    top_img = os.path.join(proj_dir, 'images_original')
    if os.path.abspath(img_dir) != os.path.abspath(top_img):
        if os.path.isdir(top_img):
            shutil.rmtree(top_img)
        shutil.copytree(img_dir, top_img)
        rep['replaced'].append('images_original/')

    # 顶层 json 的 images 指回 ./images_original/
    top_json = os.path.join(proj_dir, base + '.json')
    j = json.load(open(top_json, encoding='utf-8'))
    j['skeleton']['images'] = './images_original/'
    json.dump(j, open(top_json, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

    # 预览图（可能多张，按皮肤命名）
    for f2 in sorted(os.listdir(sub)):
        if f2.startswith('复原预览图') and f2.endswith('.png'):
            shutil.copy2(os.path.join(sub, f2), os.path.join(proj_dir, f2))
            rep['replaced'].append(f2)

    if not keep_version_dir:
        # 交付说明要自带完整履历 —— `prepare/` 下面马上就删了，先把它的动作清单取出来
        rep['prepare_fixes'] = read_prepare_fixes(proj_dir)
        shutil.rmtree(sub)
        rep['removed'] = ['convert/']
        # 交付件里不需要 prepare/ —— 源三件套已在 原始资源_*.zip，
        # 单图已搬到顶层 images_original/，其余都是中间态。
        if os.path.isdir(pdir):
            shutil.rmtree(pdir)
            rep['removed'].append('prepare/')

    # 复检（在顶层重跑，文件名/路径刚被搬动过）
    nj, nat, _ = find_triplet(proj_dir)
    drep = diagnose(nat, nj)['pages'][0]
    rep['final_check'] = {k: drep.get(k) for k in
                          ('regions', 'multi_covered', 'uncovered',
                           'overlapping_rect_pairs', 'rects_partition_page')}
    n, bad, w_rgb, w_alpha = verify_roundtrip(nat, top_img, alpha_tol=4)
    rep['final_roundtrip_alpha'] = '%d/%d' % (n - len(bad), n)
    rep['archive'] = '原始资源_%s.zip' % base
    return rep


def _write_fail_doc(proj_dir, rep):
    """apply 判定"不一致"时写的人工复核说明。"""
    lines = ['# ⚠ 转换校验未通过 —— 需人工复核', '',
             '## 结论', '',
             '`convert` 的产物与 `prepare` 的源**渲染不一致**，因此：', '',
             '* 顶层三件套**保持源版本未动**',
             '* `%s/` **原样保留**' % os.path.basename(rep['source_dir']),
             '* 两份都留着，交人工判断：是**转换真的失真**，还是**阈值定得太严**', '',
             '## 逐皮肤差异', '',
             '| 皮肤 | alpha IoU | 硬差异像素 | 原始XOR占比 | 硬差异占比 | 判定 |',
             '|---|---|---|---|---|---|']
    for row in rep.get('render_rows', []):
        sn, iou, diff, ratio, good = row[:5]
        raw = row[5] if len(row) > 5 else ratio
        lines.append('| %s | %.4f | %d | %.2f%% | %.2f%% | %s |'
                     % (sn, iou, diff, 100 * raw, 100 * ratio,
                        '通过' if good else '**不通过**'))
    th = rep.get('threshold', {})
    lines += ['', '阈值：IoU ≥ %.2f，差异占比 ≤ %.0f%%' %
              (th.get('min_iou', 0), 100 * th.get('max_diff_ratio', 0)),
              '（已补偿源骨架 skeleton.x/y = %s）' % rep.get('render_sk_offset'), '',
              '## 怎么办', '',
              '1. 看两边的 `复原预览图_*.png`，肉眼确认差在哪',
              '2. 若差异可接受（如网格重算导致的细节变化），**放宽阈值**重跑：',
              '   `apply <dir> --min-iou 0.60 --max-diff 0.55`'
              '（默认 0.70 / 0.40，**数值要比默认宽松**才放得进来）',
              '3. 若确实失真，回退源版本重做 `prepare`/`convert`', '',
              '## 对比图（人工复核直接看这个）', '']
    for sn, fp in (rep.get('diff_images') or {}).items():
        lines.append('* `%s`  —— 左 prepare / 中 convert / 右 差异染色'
                     '（红=源独有，绿=目标独有，蓝=RGB 不同）' % os.path.basename(fp))
    lines += ['', '## 文件', '',
              '* 源：`prepare/`',
              '* 转换：`%s/`' % os.path.basename(rep['source_dir'])]
    p = os.path.join(proj_dir, '失败_需人工复核.md')
    open(p, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return p

# ==========================================================================
# 来源: repair_spine.py
# ==========================================================================
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""repair_spine —— Spine 图集资源体检 / 修复 CLI（纯本地，不联网、不消耗额度）

**主流程一条命令**（用户只需要确认最后那份交付件 + 预览图）：

  python pipelines.py build <zip|目录> -o assets/类目/性别/<项目>
      # 解压 → 页名/页尺寸修复 → 打包倍率还原 → 解包去污染 → 转目标版本(默认4.3.26)
      # → 交付顶层三件套 + 复原预览图.png + 交付说明.md
      # 原始三件套归档在 原始资源_<项目>.zip，随时可回退

需要分步排查时，上面每一步都能单独跑：

  python pipelines.py prepare <zip|目录> -o <项目目录>   # 只解压+解包+出预览
  python pipelines.py convert <项目目录>                    # 只转版本（产出 convert/）
  python pipelines.py apply   <项目目录>                 # 只做顶层替换

单项工具（按需）：

  python pipelines.py diagnose  <dir>                    # 体检：页名/对账/尺寸/重叠/分区性
  python pipelines.py pagefix   <dir>                    # 修复页名后缀 / 页图尺寸不符（就地）
  python pipelines.py unpack    <dir> -o out_images      # 去污染，导出未裁白原尺寸单图
  python pipelines.py repack    <dir> -o out_atlas --from out_images
  python pipelines.py render    <dir> -o preview.png     # 独立渲染 setup pose
  python pipelines.py verify    <dir> [--images IMG]     # 反解回环 + 渲染包围盒
  python pipelines.py meshfit   <dir> --images IMG       # 网格 vs 图 IoU

约定：<dir> 下第一个 .atlas 与第一个 .json 会被自动选中。
"""

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))



def find(d, ext):
    """目录下第一个 `*.<ext>`，**排除 `_` 开头的**（备份/报告不是交付件）。"""
    fs = sorted(_triplet_files(d, ext))
    if not fs:
        sys.exit('目录 %s 下找不到 *.%s' % (d, ext))
    return fs[0]


def cmd_diagnose(a):
    atlas = a.atlas or find(a.dir, 'atlas')
    js = a.json or (sorted(_triplet_files(a.dir, 'json'))
                    or [None])[0]
    rep = diagnose(atlas, js)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    # ⚠️ ERROR 页**不能**被过滤掉：全页皆 ERROR 时生成器为空 -> all() 为真 ->
    # 打印"体检结论: 通过"。那正是 §9.1 禁止的"把没测伪装成通过"（2026-09 修）。
    err = [p.get('page') for p in rep['pages'] if 'ERROR' in p]
    pages = [p for p in rep['pages'] if 'ERROR' not in p]
    checked = sum(p.get('declared_size_checked', 0) for p in pages)
    ok = bool(pages) and not err and all(
        p.get('rects_partition_page') and p.get('page_name_matches_file')
        and not p.get('page_size_mismatch')
        and not p.get('json_not_in_atlas') and not p.get('declared_size_mismatch')
        and not p.get('mesh_size_mismatch')
        and not p.get('declared_size_unchecked')
        for p in pages)
    if err:
        print('\n!! 有 %d 页读不到页图（这些页**完全没测**）：%s'
              % (len(err), ', '.join(str(x) for x in err)))
    if pages and not checked:
        print('\n!! 单图目录里一张图都没找到，**"声明尺寸 vs 磁盘"这项没测**')
    print('\n>>> 体检结论: %s' % ('通过（矩形构成页图精确分区，三方对账无误）' if ok
                                 else '发现问题，见上面 ERROR / multi_covered / '
                                      'overlapping_rect_pairs / *_mismatch / unchecked'))


def cmd_pagefix(a):
    info = fix_page(a.atlas or find(a.dir, 'atlas'), margin=a.margin)
    for pg, new in info['renamed']:
        print('页名规范化      %s -> %s' % (pg, new))
    for pg, old, new, cov in info['resized']:
        print('页图缩回声明尺寸 %s  %s -> %s   覆盖率 %.2f%%' % (pg, old, new, cov))
    for pg, old, new, cov in info['size_line_fixed']:
        print('size 行修正     %s  %s -> %s   覆盖率 %.2f%%' % (pg, old, new, cov))
    for pg, old, new, cov in info['ambiguous']:
        print('size 行修正*    %s  %s -> %s   覆盖率 %.2f%%'
              '（两假设覆盖率差 < margin，按"声明过期"处理；**未重采样**）'
              % (pg, old, new, cov))
    for pg, tag, size, c0, c1 in info['checked']:
        print('  %-28s %-8s %-12s %s' % (pg, tag, size,
                                         '' if c0 is None else 'H2 %.2f%% / H1 %.2f%%' % (c0, c1)))
    if not any(info[k] for k in ('renamed', 'resized', 'size_line_fixed', 'ambiguous')):
        print('无需修复。')


def cmd_unpack(a):
    atlas = a.atlas or find(a.dir, 'atlas')
    js = a.json or (sorted(_triplet_files(a.dir, 'json')) or [None])[0]
    out = a.out or os.path.join(a.dir, 'images_original')
    rep = decontaminate(atlas, out, json_path=js, overlap=a.overlap,
                        min_private=a.min_private, min_keep=a.min_keep)
    print('-> %s' % out)
    if rep.get('out_of_bounds'):
        print('⚠ %d 个区域越界（未做去污染）' % len(rep['out_of_bounds']))


def cmd_repack(a):
    atlas = a.atlas or find(a.dir, 'atlas')
    src = a.__dict__['from'] or os.path.join(a.dir, 'images_original')
    out = a.out or os.path.join(a.dir, 'repacked')
    info = repack(atlas, src, out, page_w=a.page_width, pad=a.padding)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    n, bad, w_rgb, w_alpha = verify_roundtrip(os.path.join(out, os.path.basename(atlas)), src)
    print('反解回环校验：%d/%d 一致%s' % (n - len(bad), n, '' if not bad else '  异常: %s' % bad[:5]))
    rep = diagnose(os.path.join(out, os.path.basename(atlas)))
    for p in rep['pages']:
        print('新 atlas: %s  重叠像素=%d  未覆盖=%d  矩形重叠对=%d'
              % (p['page'], p['multi_covered'], p['uncovered'], p['overlapping_rect_pairs']))


def _decl(sk):
    """4.x 起 skeleton 不再导出 x/y/width/height，缺失时返回 '—'。"""
    def g(k):
        v = sk.get(k)
        return '—' if v is None else ('%.2f' % v)
    return g('width'), g('height')


def cmd_render(a):
    js = a.json or find(a.dir, 'json')
    images = a.images or os.path.join(a.dir, 'images_original')
    if not os.path.isdir(images):
        images = a.dir
    pad = a.padding
    rr = Renderer(js, images, ss=a.ss, pad=pad, skin=a.skin)
    img, bb = rr.render()
    d = json.load(open(js, encoding='utf-8'))
    sk = d['skeleton']
    w, h = _decl(sk)
    print('皮肤 = %s（共 %s 套）' % (rr.skin_name, [s.get('name') for s in d['skins']]))
    print('渲染世界包围盒 = %.2f x %.2f ; JSON 声明 = %s x %s  (spine %s)'
          % (bb[4], bb[5], w, h, sk.get('spine')))
    if sk.get('x') is not None:
        print('包围盒左下 = (%.2f, %.2f) ; skeleton.x/y = (%.2f, %.2f)'
              % (bb[0], bb[1], sk.get('x', 0), sk.get('y', 0)))
    else:
        print('包围盒左下 = (%.2f, %.2f) ; skeleton 无 x/y（4.x 起移除，运行期默认 0）'
              % (bb[0], bb[1]))
    if a.bones:
        # 把骨骼叠到渲染图上：与 render() 内部同一套 world->画布 映射
        minx, maxy = bb[0], bb[3]
        d0 = ImageDraw.Draw(img)
        Renderer(js, images).render_bones(
            lambda p: ((p[0] - minx) + pad, (maxy - p[1]) + pad), d0)
        print('已叠加骨骼')
    if a.background:
        c = img.convert('RGBA')
        canvas = Image.new('RGBA', c.size, tuple(a.background))
        canvas.alpha_composite(c)
        img = canvas
    img.save(a.out)
    print('-> %s' % a.out)


def cmd_verify(a):
    atlas = a.atlas or find(a.dir, 'atlas')
    images = a.images or os.path.join(a.dir, 'images_original')
    n, bad, w_rgb, w_alpha = verify_roundtrip(atlas, images)
    print('反解回环（atlas -> 单图）：%d/%d 一致   RGB最大差 %d  alpha最大差 %d'
          % (n - len(bad), n, w_rgb, w_alpha))
    for b in bad[:20]:
        print('   !!', b)
    js = a.json or find(a.dir, 'json')
    try:
        img, bb = Renderer(js, images, ss=1, pad=0).render()
        sk = json.load(open(js, encoding='utf-8'))['skeleton']
        w, h = _decl(sk)
        print('渲染包围盒 = %.2f x %.2f ; 声明 = %s x %s  (spine %s)'
              % (bb[4], bb[5], w, h, sk.get('spine')))
    except Exception as e:
        print('渲染失败:', e)


def cmd_meshfit(a):
    js = a.json or find(a.dir, 'json')
    res, skips = mesh_fit_score(js, a.images, return_skips=True)
    if not res:
        print('没有可评估的网格。跳过明细：')
        for k, why in skips[:20]:
            print('   %-28s %s' % (k, why))
        if not skips:
            print('   （这份 JSON 里没有任何网格附件）')
        sys.exit(1)
    print('%-14s %-10s %s' % ('mesh', 'sqrt|det|', 'IoU(网格 vs 图)'))
    for key, sc, iou in sorted(res):
        print('%-14s %-10.4f %.4f' % (key, sc, iou))
    if skips:
        print('\n未参与评估的 %d 项：' % len(skips))
        for k, why in skips[:10]:
            print('   %-28s %s' % (k, why))
    print('\n平均 IoU = %.4f ；平均 sqrt|det| = %.4f'
          % (np.mean([r[2] for r in res]), np.mean([r[1] for r in res])))
    print('提示：sqrt|det| 应≈骨骼的 scale（本例 all=0.95）；明显偏离说明图集被降采样过。')


def _fmt_previews(rep):
    """预览图一行文案：单皮肤就是文件名，多皮肤列全（每套一张）。"""
    pv = rep.get('previews') or {}
    if not pv:
        return '—'
    if len(pv) == 1:
        k = list(pv)[0]
        return '%s（皮肤 %s）' % (os.path.basename(pv[k]['path']), k)
    return '%d 张（每套皮肤一张）' % len(pv)


def _print_previews(rep, indent='          '):
    for k, v in (rep.get('previews') or {}).items():
        print('%s%s  →  %s' % (indent, k, os.path.basename(v['path'])))


def cmd_prepare(a):
    rep = prepare(a.src, a.out, check=a.check, render_preview=not a.no_preview,
                    overlap=a.overlap)
    print('项目      %s' % rep['project'])
    print('单图      images_original/  %d 张' % rep['images'])
    if rep['cleaned_pixels']:
        print('去污染    清掉重叠区外来像素 %d' % rep['cleaned_pixels'])
    print('预览      %s' % _fmt_previews(rep))
    _print_previews(rep)
    sc = rep.get('scale') or {}
    if sc.get('mismatch'):
        if sc.get('scale'):
            print('打包倍率  源图集 = 声明 × %.3f   %d/%d 个附件不符%s'
                  % (sc['scale'], sc['mismatch'], sc['checked'],
                     '' if not rep.get('upscaled_n')
                     else '，已放大单图 %d 张（×%.4f）'
                          % (rep['upscaled_n'], rep['upscaled'])))
        else:
            print('打包倍率  源图集不符 %d/%d 个附件，但**全在网格上、推不出包内倍率**'
                  '（网格声明尺寸疑为占位值），未做尺寸对齐'
                  % (sc['mismatch'], sc['checked']))
    for f in rep['fixed']:
        print('修复      %s' % f)
    if a.check:
        d = rep.get('diagnose') or {}
        print('体检      区域 %s  多重覆盖 %s  未覆盖 %s  重叠对 %s  分区 %s'
              % (d.get('regions'), d.get('multi_covered'), d.get('uncovered'),
                 d.get('overlapping_rect_pairs'), d.get('rects_partition_page')))
    print('\n★ 阶段1 完成 -> prepare/；下一步 convert（或直接用 build 一条命令跑完 1-3，阶段之间无需人工确认）')


def cmd_convert(a):
    rep = convert(a.dir, spine_com=a.spine, dst_ver=a.to, src_ver=a.src,
                    force=a.force, name=a.name)
    c = rep['atlas_check']
    print('版本      %s -> %s（匹配版本 %s）' % (rep['from'], rep['dst_ver'], rep['src_ver']))
    print('产物      %s/' % os.path.basename(rep['out_dir']))
    print('图集      区域 %s  多重覆盖 %s  未覆盖 %s  重叠对 %s  分区 %s'
          % (c['regions'], c['multi_covered'], c['uncovered'],
             c['overlapping_rect_pairs'], c['rects_partition_page']))
    print('反解回环  %s 一致' % rep['roundtrip_alpha'])
    per = rep.get('render_per_skin') or {}
    if len(per) > 1:
        print('渲染对比  （每套皮肤各比一遍；已把源骨架 x/y 补到目标上，按世界坐标对齐）')
        for sn, v in per.items():
            print('            %-14s 包围盒 %s -> %s  IoU %.3f  差异 %s px'
                  % (sn, v['bbox']['src'], v['bbox']['dst'], v['alpha_iou'],
                     v['alpha_diff_px']))
    elif per:
        only = list(per.values())[0]
        print('渲染对比  包围盒 %s -> %s   IoU %.3f  差异 %s px'
              % (only['bbox']['src'], only['bbox']['dst'], only['alpha_iou'],
                 only['alpha_diff_px']))
    w = rep.get('spine_log_warnings') or {}
    if w.get('slash_renamed'):
        print('提示      含斜杠的插槽名被 Spine 重命名 %d 处' % w['slash_renamed'])
    if w.get('reset_edges'):
        print('提示      Spine 重置无效边 %d 处（该素材家族的常见告警）' % w['reset_edges'])
    print('\n★ 阶段2 完成 -> %s/；下一步 apply（它会**自动**逐皮肤比对 prepare/ 与 convert/ 的渲染，一致才替换顶层）' % os.path.basename(rep['out_dir']))


def cmd_apply(a):
    rep = apply_converted(a.dir, keep_version_dir=a.keep_version_dir,
                            backup=a.backup, min_iou=a.min_iou,
                            max_diff_ratio=a.max_diff)
    print('校验      prepare 预览 vs convert 预览（逐皮肤渲染比对）')
    for row in rep.get('render_rows', []):
        sn, iou, diff, ratio, good = row[:5]
        raw = row[5] if len(row) > 5 else ratio
        print('            %-10s 硬差异 %7d px (%.2f%%)  原始XOR %.2f%%  IoU %.4f  %s'
              % (sn, diff, 100 * ratio, 100 * raw, iou,
                 '通过' if good else '**不通过**'))
    if not rep.get('render_rows'):
        print('            （**一套皮肤都没比成** —— 不能当作"一致"）')
    print('判定      %s' % rep.get('verdict', ''))
    if not rep['ok']:
        print('\n✗ 判定      不一致 —— 顶层保持源版本未动，两份都保留')
        print('  保留      %s' % ', '.join(rep.get('kept', [])))
        print('  说明      %s' % os.path.basename(rep['doc']))
        print('\n★ 需人工接入：先看两边的 复原预览图_*.png；'
              '差异可接受就放宽阈值重跑（--min-iou / --max-diff）')
        raise SystemExit(2)
    print('  判定      一致 -> 替换顶层，保留原始归档')
    print('替换      %s' % ', '.join(rep['replaced']))
    if rep.get('old_version'):
        print('原版本    %s（保留在 %s 里可回退）' % (rep['old_version'], rep.get('archive')))
    if rep.get('backup'):
        print('另存      %s' % ', '.join(rep['backup']))
    if rep.get('removed'):
        print('清理      %s/' % rep['removed'])
    f = rep['final_check']
    print('复检      区域 %s  多重覆盖 %s  未覆盖 %s  重叠对 %s  分区 %s'
          % (f['regions'], f['multi_covered'], f['uncovered'],
             f['overlapping_rect_pairs'], f['rects_partition_page']))
    print('反解回环  %s 一致' % rep['final_roundtrip_alpha'])
    if not a.no_doc:
        doc = write_delivery_doc(a.dir, fixes=rep.get('prepare_fixes') or ())
        print('说明      %s' % os.path.basename(doc))
    print('\n★ 判定通过，顶层已是交付件；'
          '原始三件套在 原始资源_*.zip 里可回退')


def cmd_file(a):
    rep = file_delivery(a.dir, a.category, as_name=a.name,
                        overwrite=not a.no_overwrite, dry_run=a.dry_run)
    if rep['dry_run']:
        print('试运行    将归档到 %s' % rep['dest'])
        for x in rep['copied']:
            print('            %s' % x)
        return
    print('分类      %s（agent 看预览图判定）' % rep['category'])
    print('目录名    %s%s' % (rep['as_name'],
                              '  ⚠ 未指定 --as，按 JSON 名兜底（含英文/源文件名）'
                              if rep['auto_named'] else ''))
    print('版本      %s' % rep['version'])
    print('归档      %s' % rep['dest'])
    print('内容      %s' % ', '.join(rep['copied']))
    if rep['replaced']:
        print('覆盖      原有 %d 项：%s' % (len(rep['replaced']),
                                           ', '.join(rep['replaced'][:6])))


def cmd_build(a):
    rep = build(a.src, a.out, dst_ver=a.to, spine_com=a.spine, name=a.name,
                  doc=not a.no_doc, tight=not a.no_tight,
                  min_iou=a.min_iou, max_diff_ratio=a.max_diff, overlap=a.overlap)
    pr, cv = rep['prepare'], rep['convert']
    print('工程      %s' % rep['project'])
    print('阶段目录  prepare/  convert/%s' % ('（已搬走）' if rep['ok'] else '（保留）'))
    print('版本      %s -> %s（匹配版本 %s）' % (_archive_version(rep['project']),
                                                cv['dst_ver'], cv['src_ver']))
    print('单图      prepare/images_original/  %d 张' % pr['images'])
    if pr.get('cleaned_pixels'):
        print('去污染    清掉外来像素 %d' % pr['cleaned_pixels'])
    for x in pr['fixed']:
        print('修复      %s' % x)
    d = cv['atlas_check']
    print('图集      区域 %s  多重覆盖 %s  未覆盖 %s  重叠对 %s  分区 %s'
          % (d['regions'], d['multi_covered'], d['uncovered'],
             d['overlapping_rect_pairs'], d['rects_partition_page']))
    print('反解回环  %s 一致' % cv['roundtrip_alpha'])
    if cv.get('notes'):
        for x in cv['notes']:
            print('提示      %s' % x)
    print('渲染对比  （prepare 预览 vs convert 预览，逐皮肤）')
    for row in rep['apply'].get('render_rows', []):
        sn, iou, diff, ratio, good = row[:5]
        raw = row[5] if len(row) > 5 else ratio
        print('            %-10s 硬差异 %7d px (%.2f%%)  原始XOR %.2f%%  IoU %.4f  %s'
              % (sn, diff, 100 * ratio, 100 * raw, iou,
                 '通过' if good else '**不通过**'))
    if not rep['ok']:
        print('\n✗ 判定      不一致 —— 顶层保持源版本未动，两份都保留')
        print('  保留      prepare/  convert/')
        print('  说明      %s' % os.path.basename(rep['apply']['doc']))
        print('\n★ 需人工接入：看两边的 复原预览图_*.png；'
              '差异可接受就放宽阈值重跑（--min-iou / --max-diff）')
        raise SystemExit(2)
    ap = rep['apply']
    print('  判定      一致 -> 顶层已是交付件')
    print('交付      %s' % ', '.join(ap['replaced']))
    if rep.get('tight'):
        tg = rep['tight']
        if 'skipped' in tg:
            print('收紧      跳过：%s' % tg['skipped'])
        else:
            print('收紧      %d/%d 个区域被裁（省 %.1f%%）-> 页 %sx%s'
                  % (tg['trimmed'], tg['regions'], 100 * tg['saved_ratio'],
                     tg['page'][0], tg['page'][1]))
    print('复检      区域 %s  多重覆盖 %s  未覆盖 %s  重叠对 %s  分区 %s'
          % (ap['final_check']['regions'], ap['final_check']['multi_covered'],
             ap['final_check']['uncovered'], ap['final_check']['overlapping_rect_pairs'],
             ap['final_check']['rects_partition_page']))
    print('反解回环  %s 一致' % ap['final_roundtrip_alpha'])
    if rep.get('doc'):
        print('说明      %s' % os.path.basename(rep['doc']))
    print('\n★ 判定通过，顶层三件套已是交付件；'
          '原始三件套在 原始资源_*.zip 里可回退')


def main():
    ap = argparse.ArgumentParser(description='Spine 图集资源体检/修复')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def common(p):
        p.add_argument('dir', help='包含 json/atlas/png 的目录')
        p.add_argument('--atlas', default=None)
        p.add_argument('--json', default=None)

    p = sub.add_parser('file', help='步骤4：按【大模型看预览图判定的分类】归档到 assets/2d')
    p.add_argument('dir', help='工程目录（交付完成的）')
    p.add_argument('--category', required=True,
                   help='分类路径，如 人形/女、人形/男、特效（agent 看图判定）')
    p.add_argument('--as', dest='name', default=None,
                   help='目标目录名，用纯中文人物特征（如 兽人狂战士、斗笠剑客）；'
                        '不传则按顶层 JSON 名兜底')
    p.add_argument('--dry-run', action='store_true', help='只看会搬什么，不真搬')
    p.add_argument('--no-overwrite', action='store_true', help='目标已存在时报错')
    p.set_defaults(func=cmd_file)
    p = sub.add_parser('build', help='一条命令：解压→修复→解包→转版本→交付'
                                     '（只看最后的交付件+预览图）')
    p.add_argument('src', help='原始 zip，或已解开的目录（含 json/atlas/png）')
    p.add_argument('-o', '--out', required=True, help='项目目录（assets/类目/性别/项目）')
    p.add_argument('--to', default='4.3.26', help='目标版本')
    p.add_argument('--spine', default=None, help='Spine.com 路径')
    p.add_argument('--name', default=None, help='骨架/工程名，默认取 JSON 名去掉 _fullsize')
    p.add_argument('--no-doc', action='store_true', help='不生成 交付说明.md')
    p.add_argument('--no-tight', action='store_true',
                   help='不收紧区域（保留 Spine 原样打包）')
    p.add_argument('--min-iou', type=float, default=0.70,
                   help='剪影重叠的兜底下限（默认 0.70；主判据是带 1px 容差的硬差异占比）')
    p.add_argument('--max-diff', type=float, default=0.40,
                   help='apply 判定用的逐皮肤硬差异占比上限（默认 0.40）')
    p.add_argument('--overlap', choices=('mesh', 'keep'), default='mesh',
                   help='透传给 prepare：mesh=按网格裁剪（默认）；'
                        'keep=重叠区一律保留（逃生开关，绝不削本体但会带邻居碎片）')
    p.set_defaults(func=cmd_build)

    p = sub.add_parser('prepare', help='步骤1：解压 → 解包图集成单图 → 出预览图')
    p.add_argument('src', help='原始 zip，或已解开的目录（含 json/atlas/png）')
    p.add_argument('-o', '--out', required=True, help='工程目录（建议 assets/类目/性别/项目）')
    p.add_argument('--check', action='store_true', help='顺带打印三方对账体检（默认不打印）')
    p.add_argument('--no-preview', action='store_true',
                   help='跳过预览渲染（纯 Python 软件渲染，大角色每套皮肤要几十秒）')
    p.add_argument('--overlap', choices=('mesh', 'keep'), default='mesh',
                   help='重叠区怎么处理：mesh=按网格裁剪，网格外置透明（默认）；'
                        'keep=重叠区一律保留（逃生开关，绝不削本体但会带邻居碎片）')
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser('convert', help='步骤2：官方链路转成目标 Spine 版本（默认 4.3.26）')
    p.add_argument('dir', help='工程目录（步骤1 的 -o）')
    p.add_argument('--spine', default=None, help='Spine.com 路径')
    p.add_argument('--to', default='4.3.26', help='目标版本')
    p.add_argument('--src', default=None, help='源版本（默认取 JSON 里 skeleton.spine）')
    p.add_argument('--name', default=None, help='骨架/工程名（决定导出文件名），默认取 JSON 名去掉 _fullsize')
    p.add_argument('--force', action='store_true',
                   help='已废弃：现在总是重新转换（留着只为兼容旧命令行）')
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser('apply', help='步骤3：校验 prepare 与 convert 的渲染是否一致，据此落盘')
    p.add_argument('dir', help='工程目录')
    p.add_argument('--keep-version-dir', action='store_true', help='保留 convert/ 目录（默认交付后清掉）')
    p.add_argument('--backup', action='store_true', help='把被替换的旧三件套另存为 _replaced_*')
    p.add_argument('--min-iou', type=float, default=0.70,
                   help='剪影重叠的兜底下限（默认 0.70；主判据是带 1px 容差的硬差异占比）')
    p.add_argument('--max-diff', type=float, default=0.40,
                   help='逐皮肤硬差异像素占比上限（默认 0.40 = 40%%）')
    p.add_argument('--no-doc', action='store_true', help='不生成 交付说明.md')
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser('diagnose')

    common(p); p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser('pagefix', help='规范化页名后缀 / 修复页图尺寸不符（就地）')
    common(p)
    p.add_argument('--margin', type=float, default=2.0,
                   help='两种假设覆盖率之差超过它才动手，默认 2.0 个百分点')
    p.set_defaults(func=cmd_pagefix)

    p = sub.add_parser('unpack')

    common(p)
    p.add_argument('-o', '--out', default=None, help='输出单图目录（默认 <dir>/images_original）')
    p.add_argument('--overlap', choices=('mesh', 'keep'), default='mesh',
                   help='重叠区怎么处理：mesh=按网格裁剪（默认）；keep=一律保留（逃生开关）')
    p.add_argument('--min-private', type=float, default=0.01,
                   help='私有区占比低于它才考虑回退原始裁切（默认 0.01）')
    p.add_argument('--min-keep', type=float, default=0.5,
                   help='仲裁拿走一半以上才回退（默认 0.5）')
    p.set_defaults(func=cmd_unpack)

    p = sub.add_parser('repack')

    common(p)
    p.add_argument('-o', '--out', default=None, help='输出目录（默认 <dir>/repacked）')
    p.add_argument('--from', dest='from', default=None, help='干净单图目录')
    p.add_argument('--page-width', type=int, default=1024)
    p.add_argument('--padding', type=int, default=2)
    p.set_defaults(func=cmd_repack)

    p = sub.add_parser('render')

    common(p)
    p.add_argument('-o', '--out', default='preview.png')
    p.add_argument('--images', default=None)
    p.add_argument('--ss', type=int, default=3, help='超采样倍数')
    p.add_argument('--padding', type=int, default=12)
    p.add_argument('--background', type=int, nargs=4, default=[40, 42, 50, 255],
                   metavar=('R', 'G', 'B', 'A'))
    p.add_argument('--bones', action='store_true', help='把骨骼叠到预览图上（排查部件位置用）')
    p.add_argument('--skin', default=None,
                   help='指定皮肤；默认挑部件最多的那套（多皮肤资源 default 常是空壳）')
    p.set_defaults(func=cmd_render)

    p = sub.add_parser('verify')

    common(p)
    p.add_argument('--images', default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('meshfit')

    common(p)
    p.add_argument('--images', required=True)
    p.set_defaults(func=cmd_meshfit)

    a = ap.parse_args()
    a.func(a)




if __name__ == '__main__':
    main()
