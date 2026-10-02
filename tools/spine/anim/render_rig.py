#!/usr/bin/env python3
"""render_rig.py — Spine JSON 骨骼拓扑渲染器（评估/对齐/校验的共用基建）。

把交付包的 setup pose 渲染成图，供 agent 视觉评估骨骼语义：
  - rig_pose.png    纯拼合图（region + mesh 附件都画；mesh 按蒙皮三角形投影贴图）
  - rig_overlay.png 拼合图 + 骨骼点/父子连线/骨骼名标注（按层级着色）+ mesh 附件框
  - rig.json        骨骼清单（层级/世界坐标/朝向/深度）+ 槽名表 + 附件计数

口径（2026-10-02 起与 `tools/spine/repair_spine/pipelines.py render` 对齐，实测同尺寸
逐像素比对：超差(>8) **0.00%**、最大差 2）：
  1. **世界变换同口径**：含 scale/shear 继承、skeleton.x/y 根部偏移，与
     normal / onlyTranslation / noRotationOrReflection / noScale / noScaleOrReflection
     五种 inherit；**镜像域（负 scale）也正确**（此前只累乘旋转，hip 带 scaleX=-1 的包
     会整条子树镜像）。
  2. **region 与 mesh 都画**：region 按四角四边形 2 三角形投影；mesh 按加权顶点 +
     JSON triangles 逐三角形投影。二者共用同一条贴图投影路径，
     镜像/负 scale/shear 都由几何自然处理。缺贴图时在 overlay 留 bbox 框 + 槽名。
  3. 仍存的差异：**约束（IK / path / transform）未解算**——含这类约束的包（如蓝衣术士、
     武僧、火把女战士）骨骼 setup 姿态会与 pipelines 不同（实测像素差 15%~44%）。
     其余已知项：clipping/boundingbox/path 附件不画；skeleton 级 scale 未套用（x/y 已套用）。
     已支持：`linkedmesh` 解引用、多皮肤（default + 附件最多那套）、图集 `rotate/offsets`；
     实测对照（pipelines，ss=1/pad=40）：005 包 0.00%、旋风勇者（14 个 linkedmesh）0.00%、
     鬼面武士（多皮肤）1.54%。

用法：
  python3 tools/spine/anim/render_rig.py <包目录或骨架json路径> [-o 输出目录]

算法口径（参照 docs/Spine-AI-Generator/web/renderer.js 的 Canvas 版移植为 PIL）：
  - 骨骼世界矩阵：x 轴角 = rotation+shearX、y 轴角 = rotation+90+shearY，各乘 scaleX/scaleY，
    再与父矩阵相乘（口径同 pipelines.update_world）
  - region 附件：世界矩阵 = 骨骼世界矩阵 ∘ T(x,y) ∘ R(附件rotation) ∘ S(附件scaleX/scaleY)，
    取四角（±w/2, ±h/2）为世界顶点，贴图按对应 uv 做 2 三角形仿射投影
  - mesh 附件：顶点世界点（加权混合）→ 按 JSON triangles 三角形仿射投影贴图
  - slots 数组序 = 绘制顺序（先画的在后）
  - Spine 坐标 Y-up → PIL 坐标 Y-down，输出时统一翻转

坐标陷阱（renderer.js 注释踩过，下列已在本实现规避）：
  - 骨骼的 x/y 是相对父骨骼的；渲染 attachment 必须用骨骼的**世界**变换
  - 不要用「等比缩放 + rotate + 翻面」拼镜像域：应统一走四边形/三角形投影，
    镜像与负 scale 由几何自然处理（此前该启发式在手臂链上放错位置，已改）
  - Spine 旋转逆时针为正；PIL Image.rotate 也是逆时针为正，但图像坐标 Y 向下，
    所以贴图时用 rotate(-spine_angle)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    import numpy as np
except ImportError:  # numpy 仅在渲染 mesh 附件时需要
    np = None


# ---------- Spine 数据加载 ----------

def load_package(path: Path) -> tuple[dict, Path]:
    """入参可以是包目录或骨架 json 路径。返回 (doc, 包目录)。"""
    if path.is_dir():
        for jf in sorted(path.glob("*.json")):
            try:
                doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(doc, dict) and "bones" in doc and "skeleton" in doc:
                return doc, path
        raise SystemExit(f"[!] {path} 下找不到骨架 json（顶层需有 skeleton+bones 键）")
    doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return doc, path.parent


def parse_atlas(atlas_path: Path) -> dict[str, tuple]:
    """解析 .atlas → {区域名: (页文件名, (x,y,w,h), rotate, offsets)}。支持新旧字段序。

    `rotate`（打包时旋转 90/180/270）与 `offsets`（区域从更大的未裁白画布裁下）都会记录，
    裁图时据此还原；不还原会把旋转/裁白过的包画歪。
    """
    regions: dict[str, tuple] = {}
    lines = atlas_path.read_text(encoding="utf-8", errors="replace").splitlines()
    cur_page = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if not line.startswith((" ", "\t")) and ":" not in s:
            # 页名行 or 区域名行：页名以图片扩展名结尾
            if s.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                cur_page = s
                i += 1
                continue
            # 区域名行：往下找 bounds/xy+size/rotate/offsets
            name = s
            x = y = w = h = None
            rotate, offsets = 0, None
            props = {}
            # 逐行扫属性直到下一个区域名/页名
            j = i + 1
            while j < n:
                l2 = lines[j]
                if ":" not in l2:
                    break
                if not l2.startswith((" ", "\t")) and l2.strip().lower().endswith(
                        (".png", ".jpg", ".jpeg", ".webp")):
                    break
                k, _, v = l2.partition(":")
                props[k.strip()] = v.strip()
                j += 1
            if "bounds" in props:
                vals = [int(float(t)) for t in props["bounds"].split(",")[:4]]
                x, y, w, h = vals
            elif "xy" in props and "size" in props:
                x, y = [int(float(t)) for t in props["xy"].split(",")[:2]]
                w, h = [int(float(t)) for t in props["size"].split(",")[:2]]
            if "rotate" in props:
                rotate = int(float(props["rotate"]))
            if "offsets" in props:
                offsets = tuple(int(float(t)) for t in props["offsets"].split(",")[:4])
            if x is not None and cur_page:
                regions[name] = (cur_page, (x, y, w, h), rotate, offsets)
            i = j
            continue
        i += 1
    return regions


def load_atlas_images(pkg_dir: Path) -> dict[str, Image.Image]:
    """从图集页裁出区域（还原 rotate/offsets）。返回 {区域名: PIL图}。"""
    atlas_files = sorted(pkg_dir.glob("*.atlas"))
    if not atlas_files:
        return {}
    regions = parse_atlas(atlas_files[0])
    pages: dict[str, Image.Image] = {}
    out: dict[str, Image.Image] = {}
    for name, (page, (x, y, w, h), rotate, offsets) in regions.items():
        if page not in pages:
            p = pkg_dir / page
            if not p.is_file():
                continue
            pages[page] = Image.open(p).convert("RGBA")
        img = pages[page]
        # atlas 的 y 从页顶算起，PIL crop 同样左上原点，直接用
        crop = img.crop((x, y, x + w, y + h))
        if rotate == 90:
            crop = crop.transpose(Image.ROTATE_90)
        elif rotate == 180:
            crop = crop.transpose(Image.ROTATE_180)
        elif rotate == 270:
            crop = crop.transpose(Image.ROTATE_270)
        if offsets:                       # 贴回未裁白画布，uv 才对应得上
            ox, oy, ow, oh = offsets
            canvas = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
            canvas.paste(crop, (ox, oy))
            crop = canvas
        out[name] = crop
    return out


# ---------- 骨骼世界变换 ----------

def compute_world(doc: dict) -> dict[str, dict]:
    """骨骼名 → {x, y, rot, a, b, c, d, length, parent, depth}（世界坐标，Y-up）。

    世界矩阵**线性部分** (a,b,c,d) 为行主序，与
    `tools/spine/repair_spine/pipelines.py::update_world` 完全同口径：
      x 轴角 = rotation + shearX，y 轴角 = rotation + 90 + shearY，各自乘 scaleX/scaleY，
      并支持 inherit 的 normal / onlyTranslation / noRotationOrReflection /
      noScale / noScaleOrReflection（2026-10-02 补齐：此前只累乘旋转，含镜像域
      （负 scale）的骨架会整条子树错位）。
    `rot` = 世界 x 轴角度（atan2(c,a)，度），供骨骼朝向/排序使用。
    """
    bones = doc.get("bones", [])
    world: dict[str, dict] = {}
    DEG = math.pi / 180.0
    sk = doc.get("skeleton") or {}
    sk_x, sk_y = sk.get("x", 0.0) or 0.0, sk.get("y", 0.0) or 0.0  # 根部偏移，同 pipelines

    for b in bones:  # Spine 要求父先于子，按数组序即可
        name = b["name"]
        pname = b.get("parent")
        p = world.get(pname) if pname else None
        lx, ly = b.get("x", 0.0), b.get("y", 0.0)
        rot = b.get("rotation", 0.0)
        shx, shy = b.get("shearX", 0.0), b.get("shearY", 0.0)
        sx, sy = b.get("scaleX", 1.0), b.get("scaleY", 1.0)
        inherit = b.get("inherit", b.get("transform", "normal"))  # 3.8 叫 transform

        if p is None:
            rx, ry = (rot + shx) * DEG, (rot + 90 + shy) * DEG
            a, bb = math.cos(rx) * sx, math.cos(ry) * sy
            c, d = math.sin(rx) * sx, math.sin(ry) * sy
            wx, wy = lx + sk_x, ly + sk_y
        else:
            pa, pb, pc, pd = p["a"], p["b"], p["c"], p["d"]
            wx = pa * lx + pb * ly + p["x"]
            wy = pc * lx + pd * ly + p["y"]
            if inherit == "normal":
                rx, ry = (rot + shx) * DEG, (rot + 90 + shy) * DEG
                la, lb = math.cos(rx) * sx, math.cos(ry) * sy
                lc, ld = math.sin(rx) * sx, math.sin(ry) * sy
                a, bb = pa * la + pb * lc, pa * lb + pb * ld
                c, d = pc * la + pd * lc, pc * lb + pd * ld
            elif inherit == "onlyTranslation":
                rx, ry = (rot + shx) * DEG, (rot + 90 + shy) * DEG
                a, bb = math.cos(rx) * sx, math.cos(ry) * sy
                c, d = math.sin(rx) * sx, math.sin(ry) * sy
            elif inherit == "noRotationOrReflection":
                qa, qc = pa, pc
                s = qa * qa + qc * qc
                if s > 0.0001:
                    s = abs(qa * pd - pb * qc) / s
                    pb, pd = qc * s, qa * s
                    prx = math.degrees(math.atan2(qc, qa))
                else:
                    qa = qc = 0.0
                    prx = 90 - math.degrees(math.atan2(pd, pb))
                rx, ry = (rot + shx - prx) * DEG, (rot + shy - prx + 90) * DEG
                la, lb = math.cos(rx) * sx, math.cos(ry) * sy
                lc, ld = math.sin(rx) * sx, math.sin(ry) * sy
                a, bb = qa * la - pb * lc, qa * lb - pb * ld
                c, d = qc * la + pd * lc, qc * lb + pd * ld
            elif inherit in ("noScale", "noScaleOrReflection"):
                r = rot * DEG
                cs, sn = math.cos(r), math.sin(r)
                za, zc = pa * cs + pb * sn, pc * cs + pd * sn
                s = math.sqrt(za * za + zc * zc)
                if s > 0.00001:
                    s = 1.0 / s
                za *= s
                zc *= s
                s = math.sqrt(za * za + zc * zc)
                if inherit == "noScale" and (pa * pd - pb * pc) < 0:
                    s = -s
                r2 = math.pi / 2 + math.atan2(zc, za)
                zb, zd = math.cos(r2) * s, math.sin(r2) * s
                shx_r, shy_r = shx * DEG, (90 + shy) * DEG
                la, lb = math.cos(shx_r) * sx, math.cos(shy_r) * sy
                lc, ld = math.sin(shx_r) * sx, math.sin(shy_r) * sy
                a, bb = za * la + zb * lc, za * lb + zb * ld
                c, d = zc * la + zd * lc, zc * lb + zd * ld
            else:
                raise NotImplementedError("inherit=" + str(inherit))

        world[name] = {
            "x": wx, "y": wy, "rot": math.degrees(math.atan2(c, a)),
            "a": a, "b": bb, "c": c, "d": d,
            "length": b.get("length", 0.0),
            "parent": pname, "depth": (p["depth"] + 1) if p else 0,
        }
    return world


# ---------- mesh 附件（蒙皮投影） ----------

LINKEDMESH_MAX_DEPTH = 8


def deref_linkedmesh(doc: dict, att: dict) -> dict:
    """`linkedmesh` 自身没有顶点：顺父指针找到真正带网格的那个附件。

    ⚠ 父指针键名 3.8 用 `parent`、4.x 用 `source`，两代都要认；否则 4.x 数据上
    会把 linkedmesh 当成普通区域四边形，画成「以骨骼原点为中心的大矩形」。
    最多顺 8 层；找不到目标时原样返回（调用方按 `type` 走 region 分支）。
    """
    seen = 0
    cur = att
    while ("linkedmesh" in str(cur.get("type"))
           and seen < LINKEDMESH_MAX_DEPTH):
        seen += 1
        pn = cur.get("parent") or cur.get("source")
        ps = cur.get("skin") or "default"
        nxt = None
        for s in doc.get("skins", []):
            if s.get("name") != ps:
                continue
            for atts in (s.get("attachments") or {}).values():
                if pn in atts:
                    nxt = atts[pn]
                    break
            if nxt is not None:
                break
        if nxt is None:
            return cur
        cur = nxt
    return cur


def mesh_world_points(world: dict, bone_names: list, att: dict,
                      bound: dict) -> list[tuple[float, float]]:
    """mesh 顶点 → 世界点。

    Spine 的 mesh `vertices` 有两种编码：
      - 非加权（len == len(uvs)）：xy 对，绑定槽所挂骨骼；
      - 加权（逐顶点：骨数, [骨索引, x, y, 权重]*）：按权重混合各骨的世界矩阵。
    """
    v, uvs = att["vertices"], att["uvs"]
    pts: list[tuple[float, float]] = []
    if len(v) == len(uvs):
        m = bound
        for k in range(0, len(v), 2):
            pts.append((m["a"] * v[k] + m["b"] * v[k + 1] + m["x"],
                        m["c"] * v[k] + m["d"] * v[k + 1] + m["y"]))
        return pts
    i = 0
    while i < len(v):
        n = int(v[i])
        i += 1
        wx = wy = 0.0
        for _ in range(n):
            bi = int(v[i])
            x, y, wt = v[i + 1], v[i + 2], v[i + 3]
            i += 4
            m = world[bone_names[bi]]
            wx += (m["a"] * x + m["b"] * y + m["x"]) * wt
            wy += (m["c"] * x + m["d"] * y + m["y"]) * wt
        pts.append((wx, wy))
    return pts


def draw_mesh(size: tuple[int, int], to_px, pts, uvpx, tris,
              tex: Image.Image) -> Image.Image:
    """把 mesh 贴图按三角形投影到画布，返回整画布 RGBA 层（口径同 pipelines.render）。

    做法：对每个三角形求「贴图像素 → 画布像素」的仿射，取其画布包围盒做局部
    transform，再用三角形 mask 贴进本层；整个附件画完再一次性 alpha 合成，
    避免用 paste 的替换语义擦掉下层部件。
    """
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    if np is None:
        return layer
    for (i, j, k) in tris:
        cp = [to_px(pts[q][0], pts[q][1]) for q in (i, j, k)]
        A = np.array([[uvpx[i][0], uvpx[i][1], 1.0],
                      [uvpx[j][0], uvpx[j][1], 1.0],
                      [uvpx[k][0], uvpx[k][1], 1.0]])
        try:
            cx = np.linalg.solve(A, np.array([cp[0][0], cp[1][0], cp[2][0]], float))
            cy = np.linalg.solve(A, np.array([cp[0][1], cp[1][1], cp[2][1]], float))
            Mi = np.linalg.inv(np.array([[cx[0], cx[1], cx[2]],
                                         [cy[0], cy[1], cy[2]], [0, 0, 1.0]]))
        except np.linalg.LinAlgError:
            continue
        xs3 = (cp[0][0], cp[1][0], cp[2][0])
        ys3 = (cp[0][1], cp[1][1], cp[2][1])
        bx0 = max(0, int(math.floor(min(xs3))) - 1)
        by0 = max(0, int(math.floor(min(ys3))) - 1)
        bx1 = min(size[0], int(math.ceil(max(xs3))) + 2)
        by1 = min(size[1], int(math.ceil(max(ys3))) + 2)
        if bx1 <= bx0 or by1 <= by0:
            continue
        w, h = bx1 - bx0, by1 - by0
        tx = Mi[0, 0] * bx0 + Mi[0, 1] * by0 + Mi[0, 2]
        ty = Mi[1, 0] * bx0 + Mi[1, 1] * by0 + Mi[1, 2]
        piece = tex.transform((w, h), Image.AFFINE,
                              (Mi[0, 0], Mi[0, 1], tx, Mi[1, 0], Mi[1, 1], ty),
                              resample=Image.BILINEAR)
        mask = Image.new("L", (w, h), 0)
        # 掩膜用**浮点**坐标：四舍五入会在相邻三角形之间留 1px 缝，把细亮部件削掉
        ImageDraw.Draw(mask).polygon(
            [(cp[q][0] - bx0, cp[q][1] - by0) for q in (0, 1, 2)], fill=255)
        layer.paste(piece, (bx0, by0), mask)
    return layer


# ---------- 渲染 ----------

DEPTH_COLORS = ["#ffd479", "#6ea8fe", "#7ee787", "#ff9c9c", "#d2a8ff",
                "#79c0ff", "#ffa657", "#a5d6ff", "#ff7b72", "#56d4dd"]


def pick_skin(doc: dict) -> dict | None:
    """挑「附件最多」的皮肤（口径同 pipelines.pick_skin）。

    多皮肤资源里 `default` 可能只是空壳（如鬼面武士 default 仅 1 项、skin '1' 有 21 项），
    只画第一套皮肤会漏掉几乎全部部件。
    """
    best, best_n = None, -1
    for s in doc.get("skins", []):
        n = sum(len(v) for v in (s.get("attachments") or {}).values())
        if n > best_n:
            best, best_n = s, n
    return best


def render(doc: dict, pkg_dir: Path, out_dir: Path) -> dict:
    world = compute_world(doc)
    slots = doc.get("slots", [])
    # 皮肤口径同 pipelines：`default` 是基底，叠加 pick_skin 选中的那套
    skins = doc.get("skins", [])
    chosen = pick_skin(doc)
    att_map: dict[str, dict] = {}
    for s in skins:
        if s.get("name") == "default" or s is chosen:
            for k, v in (s.get("attachments") or {}).items():
                att_map.setdefault(k, {}).update(v)
    skin_name = (chosen or {}).get("name", "default")

    # 贴图：优先 images_original/ 单图（与 pipelines.render 一致），图集裁剪仅兜底
    region_imgs: dict[str, Image.Image] = {}
    orig_dir = pkg_dir / "images_original"
    if orig_dir.is_dir():
        for f in sorted(orig_dir.glob("*.png")):
            region_imgs[f.stem] = Image.open(f).convert("RGBA")
    for k, v in load_atlas_images(pkg_dir).items():
        region_imgs.setdefault(k, v)

    # 画布范围：所有骨骼世界坐标 + 附件贴图的世界顶点
    xs, ys = [], []
    # 统一为一个形状：("proj", 槽名, 附件名, 世界顶点, uv像素, 三角形, img, kind)
    #   region：四角四边形按 2 三角形投影；mesh：蒙皮顶点按 JSON triangles 投影
    bone_names = [b["name"] for b in doc.get("bones", [])]
    placements = []
    n_mesh_drawn = n_region_drawn = 0
    n_skipped_img = n_skipped_type = 0
    for slot in slots:
        sname = slot["name"]
        aname = slot.get("attachment")
        if not aname:
            continue
        att = att_map.get(sname, {}).get(aname)
        if att is None:
            continue
        bw = world.get(slot["bone"])
        if bw is None:
            continue
        # linkedmesh → 真正带网格的附件（几何沿用源网格，摆放仍按本槽骨骼）
        geo = deref_linkedmesh(doc, att)
        atype = (geo or att).get("type", "region")
        img = None
        for key in (aname, (geo or {}).get("name"), sname):   # 兼容 linkedmesh 换名
            if key and key in region_imgs:
                img = region_imgs[key]
                break

        if "mesh" in str(atype) and geo.get("vertices") and geo.get("uvs"):
            pts = mesh_world_points(world, bone_names, geo, bw)
            tw, th = (img.size if img else (geo.get("width", 0.0), geo.get("height", 0.0)))
            uvpx = [(geo["uvs"][2 * i] * tw, geo["uvs"][2 * i + 1] * th)
                    for i in range(len(geo["uvs"]) // 2)]
            tris = [(geo["triangles"][k], geo["triangles"][k + 1], geo["triangles"][k + 2])
                    for k in range(0, len(geo["triangles"]), 3)]
            n_mesh_drawn += img is not None
            n_skipped_img += img is None          # 缺贴图 → 只在 overlay 留 bbox 框
            placements.append(("proj", sname, aname, pts, uvpx, tris, img, "mesh"))
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
            continue

        if atype != "region":
            n_skipped_type += 1                   # boundingbox/path/point/clipping 不画
            continue

        w, h = att.get("width", 0.0), att.get("height", 0.0)
        if img is None or w <= 0 or h <= 0:
            n_skipped_img += 1
            continue
        # 附件世界矩阵 = 骨骼世界矩阵 ∘ T(x,y) ∘ R(att_rotation) ∘ S(att_scale)
        ox, oy = att.get("x", 0.0), att.get("y", 0.0)
        orot = att.get("rotation", 0.0)
        sx, sy = att.get("scaleX", 1.0), att.get("scaleY", 1.0)
        la, lb = math.cos(math.radians(orot)) * sx, math.cos(math.radians(orot + 90)) * sy
        lc, ld = math.sin(math.radians(orot)) * sx, math.sin(math.radians(orot + 90)) * sy
        ba, bb_, bc, bd = bw["a"], bw["b"], bw["c"], bw["d"]
        ma = ba * la + bb_ * lc
        mb = ba * lb + bb_ * ld
        mc = bc * la + bd * lc
        md = bc * lb + bd * ld
        wx = ba * ox + bb_ * oy + bw["x"]
        wy = bc * ox + bd * oy + bw["y"]
        hw, hh = w / 2.0, h / 2.0
        # 局部 y-up 四角（(-hw,+hh)=贴图左上）；世界点 = M·corner + 骨位
        pts = [(ma * u + mb * v + wx, mc * u + md * v + wy)
               for u, v in ((-hw, hh), (hw, hh), (hw, -hh), (-hw, -hh))]
        tw, th = img.size
        uvpx = [(0.0, 0.0), (tw, 0.0), (tw, th), (0.0, th)]
        placements.append(("proj", sname, aname, pts, uvpx, [(0, 1, 2), (2, 3, 0)],
                           img, "region"))
        n_region_drawn += 1
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]

    for b in world.values():
        xs.append(b["x"]); ys.append(b["y"])
    if not xs:
        raise SystemExit("[!] 没有可渲染的内容")
    pad = 40
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    W, H = int(max_x - min_x), int(max_y - min_y)

    def to_px(wx, wy):
        return (wx - min_x, max_y - wy)  # Y 翻转

    pose = Image.new("RGBA", (W, H), (22, 26, 34, 255))
    overlay_extra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    font = None
    for fpath in ("/System/Library/Fonts/Hiragino Sans GB.ttc",
                  "/System/Library/Fonts/STHeiti Light.ttc",
                  "/System/Library/Fonts/Supplemental/Songti.ttc",
                  "/System/Library/Fonts/PingFang.ttc",
                  "C:/Windows/Fonts/msyh.ttc",
                  "C:/Windows/Fonts/arial.ttf"):
        try:
            font = ImageFont.truetype(fpath, 11)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    for pl in placements:
        _, sname, aname, pts, uvpx, tris, img, kind = pl
        if img is not None:
            pose.alpha_composite(draw_mesh(pose.size, to_px, pts, uvpx, tris, img))
        if kind == "mesh" or img is None:
            # overlay 上给 mesh（或缺贴图件）画 bbox 框 + 槽名，位置取实际范围中心
            cxs, cys = [p[0] for p in pts], [p[1] for p in pts]
            x0, y0 = to_px(min(cxs), max(cys))
            x1, y1 = to_px(max(cxs), min(cys))
            d = ImageDraw.Draw(overlay_extra)
            d.rectangle([x0, y0, x1, y1], outline=(255, 120, 120, 160), width=1)
            d.text(((x0 + x1) / 2, (y0 + y1) / 2 - 6),
                   f"{sname}[{aname}]", fill=(255, 140, 140, 230), font=font)

    # 骨骼叠加层
    d = ImageDraw.Draw(overlay_extra)
    for name, b in world.items():
        x, y = to_px(b["x"], b["y"])
        color = DEPTH_COLORS[b["depth"] % len(DEPTH_COLORS)]
        if b["parent"] and b["parent"] in world:
            px, py = to_px(world[b["parent"]]["x"], world[b["parent"]]["y"])
            d.line([px, py, x, y], fill=color, width=1)
        # 骨骼方向线（length）
        if b["length"] > 0:
            rad = math.radians(b["rot"])
            ex, ey = to_px(b["x"] + b["length"] * math.cos(rad),
                           b["y"] + b["length"] * math.sin(rad))
            d.line([x, y, ex, ey], fill=color, width=2)
        r = 3
        d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=2)
        d.text((x + 5, y - 6), name, fill=color, font=font)

    overlay = pose.copy()
    overlay.alpha_composite(overlay_extra)

    out_dir.mkdir(parents=True, exist_ok=True)
    pose_path = out_dir / "rig_pose.png"
    overlay_path = out_dir / "rig_overlay.png"
    pose.save(pose_path)
    overlay.save(overlay_path)

    rig = {
        "package": str(pkg_dir),
        "version": doc.get("skeleton", {}).get("spine"),
        "skin": skin_name,
        "bones": [
            {"name": n,
             "x": round(b["x"], 2), "y": round(b["y"], 2), "rot": round(b["rot"], 2),
             "length": b["length"], "parent": b["parent"], "depth": b["depth"]}
            for n, b in sorted(world.items(), key=lambda kv: kv[1]["depth"])
        ],
        "slots": [s["name"] for s in slots],
        "attachments_region": n_region_drawn,
        "attachments_mesh_drawn": n_mesh_drawn,
        "attachments_skipped_no_image": n_skipped_img,
        "attachments_skipped_type": n_skipped_type,
        # 兼容旧字段名（= 未绘制的附件总数）
        "attachments_mesh_degraded": n_skipped_img + n_skipped_type,
        "canvas": [W, H],
        # 世界坐标包围盒（不含 pad）：与 pipelines.Renderer.render() 返回的 bb 可直接对照
        "world_bbox": [round(min_x + pad, 4), round(min_y + pad, 4),
                       round(max_x - pad, 4), round(max_y - pad, 4)],
        # 逐附件世界 bbox（对账用：可与 pipelines.Renderer._collect() 的顶点逐项比）
        "drawn": [
            {"slot": sname, "attachment": aname, "kind": kind,
             "bbox": [round(min(p[0] for p in pts), 3), round(min(p[1] for p in pts), 3),
                      round(max(p[0] for p in pts), 3), round(max(p[1] for p in pts), 3)]}
            for _, sname, aname, pts, _, _, _, kind in placements
        ],
    }
    (out_dir / "rig.json").write_text(
        json.dumps(rig, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "pose": str(pose_path), "overlay": str(overlay_path),
        "rig": str(out_dir / "rig.json"),
        "mesh_drawn": n_mesh_drawn, "region_drawn": n_region_drawn,
        "skipped_img": n_skipped_img, "skipped_type": n_skipped_type,
        "skin": skin_name, "canvas": [W, H],
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    target = Path(argv[1])
    out = (Path(argv[argv.index("-o") + 1])
           if "-o" in argv and argv.index("-o") + 1 < len(argv)
           else Path("tmp/rig") / target.name)
    doc, pkg_dir = load_package(target)
    res = render(doc, pkg_dir, out)
    msg = (f"[rig] {pkg_dir.name}: 画布 {res['canvas'][0]}x{res['canvas'][1]}"
           f"，皮肤 {res['skin']}，region {res['region_drawn']} 件 / mesh {res['mesh_drawn']} 件")
    if res["skipped_img"]:
        msg += f"，缺贴图 {res['skipped_img']} 件"
    if res["skipped_type"]:
        msg += f"，不支持的附件类型 {res['skipped_type']} 件"
    print(msg)
    print(f"      pose    → {res['pose']}")
    print(f"      overlay → {res['overlay']}")
    print(f"      rig     → {res['rig']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
