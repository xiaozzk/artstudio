#!/usr/bin/env python3
"""render_rig.py — Spine JSON 骨骼拓扑渲染器（评估/对齐/校验的共用基建）。

把交付包的 setup pose 渲染成图，供 agent 视觉评估骨骼语义：
  - rig_pose.png    纯拼合图（对照复原预览图验证渲染正确性）
  - rig_overlay.png 拼合图 + 骨骼点/父子连线/骨骼名标注（按层级着色）
  - rig.json        骨骼清单（层级、世界坐标、长度、挂的槽位/附件）

用法：
  python3 tools/spine/anim/render_rig.py <包目录或骨架json路径> [-o 输出目录]

算法口径（参照 docs/Spine-AI-Generator/web/renderer.js 的 Canvas 版移植为 PIL）：
  - 骨骼世界变换递归组合：world_pos = parent_pos + R(parent_world_rot)·local_pos
    world_rot = parent_world_rot + local_rot（setup pose 忽略 scale/shear 继承细节，
    105 个交付包实测够用；不准时对照复原预览图会发现）
  - region 附件：x/y 是相对骨骼原点的偏移（随骨骼世界旋转转到世界方向），
    图片中心对位，rotation 叠加骨骼世界旋转，scaleX/Y 缩放
  - slots 数组序 = 绘制顺序（先画的在后）
  - Spine 坐标 Y-up → PIL 坐标 Y-down，输出时统一翻转
  - mesh/linkedmesh 降级为 hull 线框 + 计数警告（MVP 选包优先全 region 包）

坐标陷阱（renderer.js 注释踩过，本实现已规避）：
  - 骨骼的 x/y 是相对父骨骼的；渲染 attachment 必须用骨骼的**世界**变换
  - Spine 旋转逆时针为正；PIL Image.rotate 也是逆时针为正，但图像坐标 Y 向下，
    所以贴图时用 rotate(-spine_angle)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


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


def parse_atlas(atlas_path: Path) -> dict[str, tuple[str, tuple[int, int, int, int]]]:
    """解析 .atlas → {region名: (页文件名, (x, y, w, h))}。支持新旧字段序。"""
    regions: dict[str, tuple[str, tuple[int, int, int, int]]] = {}
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
            # 区域名行：往下找 bounds/xy+size
            name = s
            x = y = w = h = None
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
                k = k.strip(); v = v.strip()
                props[k] = v
                # bounds 可能是 "x,y,w,h"（新格式）
                j += 1
            if "bounds" in props:
                vals = [int(float(t)) for t in props["bounds"].split(",")[:4]]
                x, y, w, h = vals
            elif "xy" in props and "size" in props:
                x, y = [int(float(t)) for t in props["xy"].split(",")[:2]]
                w, h = [int(float(t)) for t in props["size"].split(",")[:2]]
            if x is not None and cur_page:
                regions[name] = (cur_page, (x, y, w, h))
            i = j
            continue
        i += 1
    return regions


def load_atlas_images(pkg_dir: Path, doc: dict) -> tuple[dict[str, Image.Image], dict]:
    """加载图集页 + 区域裁剪。返回 ({槽位名: PIL图}, region_meta)。"""
    atlas_files = sorted(pkg_dir.glob("*.atlas"))
    if not atlas_files:
        return {}, {}
    regions = parse_atlas(atlas_files[0])
    pages: dict[str, Image.Image] = {}
    out: dict[str, Image.Image] = {}
    meta: dict[str, dict] = {}
    for name, (page, (x, y, w, h)) in regions.items():
        if page not in pages:
            p = pkg_dir / page
            if not p.is_file():
                continue
            pages[page] = Image.open(p).convert("RGBA")
        img = pages[page]
        # atlas 的 y 从页顶算起，PIL crop 同样左上原点，直接用
        crop = img.crop((x, y, x + w, y + h))
        out[name] = crop
        meta[name] = {"page": page, "rect": (x, y, w, h)}
    return out, meta


# ---------- 骨骼世界变换 ----------

def compute_world(doc: dict) -> dict[str, dict]:
    """骨骼名 → {x, y, rot, length, parent, depth}（世界坐标，Y-up）。"""
    bones = doc.get("bones", [])
    by_name = {b["name"]: b for b in bones}
    world: dict[str, dict] = {}

    def resolve(name: str, depth: int = 0) -> dict:
        if name in world:
            return world[name]
        b = by_name[name]
        lx, ly = b.get("x", 0.0), b.get("y", 0.0)
        lrot = b.get("rotation", 0.0)
        pname = b.get("parent")
        if pname and pname in by_name:
            p = resolve(pname, depth + 1)
            rad = math.radians(p["rot"])
            c, s = math.cos(rad), math.sin(rad)
            wx = p["x"] + lx * c - ly * s
            wy = p["y"] + lx * s + ly * c
            wrot = p["rot"] + lrot
        else:
            wx, wy, wrot = lx, ly, lrot
        world[name] = {
            "x": wx, "y": wy, "rot": wrot,
            "length": b.get("length", 0.0),
            "parent": pname, "depth": depth,
        }
        return world[name]

    for b in bones:
        resolve(b["name"])
    return world


# ---------- 渲染 ----------

DEPTH_COLORS = ["#ffd479", "#6ea8fe", "#7ee787", "#ff9c9c", "#d2a8ff",
                "#79c0ff", "#ffa657", "#a5d6ff", "#ff7b72", "#56d4dd"]


def render(doc: dict, pkg_dir: Path, out_dir: Path) -> dict:
    world = compute_world(doc)
    slots = doc.get("slots", [])
    skins = doc.get("skins", [])
    default_skin = skins[0] if skins else {"attachments": {}}
    att_map = default_skin.get("attachments", {})

    # 图集区域图
    region_imgs, region_meta = load_atlas_images(pkg_dir, doc)

    # 先用 images_original/ 兜底（比图集裁剪更干净，法袍法师这类包有）
    orig_dir = pkg_dir / "images_original"
    if orig_dir.is_dir():
        for f in orig_dir.glob("*.png"):
            region_imgs.setdefault(f.stem, Image.open(f).convert("RGBA"))

    # 画布范围：所有骨骼世界坐标 + 附件尺寸的 bbox
    xs, ys = [], []
    placements = []  # (slot名, 附件名, 世界x, 世界y, 世界rot, sx, sy, img或None, type)
    n_mesh = 0
    for slot in slots:
        sname = slot["name"]
        bname = slot["bone"]
        aname = slot.get("attachment")
        if not aname:
            continue
        att = att_map.get(sname, {}).get(aname)
        if att is None:
            continue
        atype = att.get("type", "region")
        bw = world.get(bname)
        if bw is None:
            continue
        if atype != "region":
            n_mesh += 1
            # mesh 降级：画 hull 框（vertices 若无权重是骨骼空间 xy 对）
            placements.append((sname, aname, bw, att, atype))
            continue
        ox, oy = att.get("x", 0.0), att.get("y", 0.0)
        orot = att.get("rotation", 0.0)
        sx, sy = att.get("scaleX", 1.0), att.get("scaleY", 1.0)
        w, h = att.get("width", 0.0), att.get("height", 0.0)
        rad = math.radians(bw["rot"])
        c, s = math.cos(rad), math.sin(rad)
        wx = bw["x"] + ox * c - oy * s
        wy = bw["y"] + ox * s + oy * c
        wrot = bw["rot"] + orot
        img = region_imgs.get(aname) or region_imgs.get(sname)
        placements.append((sname, aname, wx, wy, wrot, sx, sy, w, h, img, atype))
        xs += [wx - w * abs(sx) / 2, wx + w * abs(sx) / 2]
        ys += [wy - h * abs(sy) / 2, wy + h * abs(sy) / 2]

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

    for pl in placements:
        if pl[-1] != "region":
            sname, aname, bw, att, atype = pl
            x0, y0 = to_px(bw["x"], bw["y"])
            d = ImageDraw.Draw(overlay_extra)
            d.rectangle([x0 - 12, y0 - 12, x0 + 12, y0 + 12],
                        outline=(255, 120, 120, 200), width=1)
            d.text((x0 + 14, y0 - 6), f"{sname}({atype})", fill=(255, 120, 120, 220))
            continue
        sname, aname, wx, wy, wrot, sx, sy, w, h, img, _ = pl
        if img is None:
            continue
        sw, sh = max(1, int(img.width * abs(sx))), max(1, int(img.height * abs(sy)))
        simg = img.resize((sw, sh), Image.LANCZOS) if (sw, sh) != img.size else img
        if sx < 0:
            simg = simg.transpose(Image.FLIP_LEFT_RIGHT)
        if sy < 0:
            simg = simg.transpose(Image.FLIP_TOP_BOTTOM)
        # PIL rotate 逆时针为正、图像坐标 Y 向下 → 取负
        rimg = simg.rotate(-wrot, expand=True, resample=Image.BICUBIC)
        cx, cy = to_px(wx, wy)
        pose.alpha_composite(rimg, (int(cx - rimg.width / 2), int(cy - rimg.height / 2)))

    # 骨骼叠加层
    d = ImageDraw.Draw(overlay_extra)
    font = None
    for fpath in ("/System/Library/Fonts/Hiragino Sans GB.ttc",
                  "/System/Library/Fonts/STHeiti Light.ttc",
                  "/System/Library/Fonts/Supplemental/Songti.ttc",
                  "/System/Library/Fonts/PingFang.ttc",
                  "C:/Windows/Fonts/msyh.ttc"):
        try:
            font = ImageFont.truetype(fpath, 11)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
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
        "bones": [
            {"name": n, **{k: (round(v, 2) if isinstance(v, float) else v)
                           for k, v in b.items()}}
            for n, b in sorted(world.items(), key=lambda kv: kv[1]["depth"])
        ],
        "slots": [s["name"] for s in slots],
        "attachments_region": sum(1 for pl in placements if pl[-1] == "region"),
        "attachments_mesh_degraded": n_mesh,
        "canvas": [W, H],
    }
    (out_dir / "rig.json").write_text(
        json.dumps(rig, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "pose": str(pose_path), "overlay": str(overlay_path),
        "rig": str(out_dir / "rig.json"), "mesh_degraded": n_mesh,
        "canvas": [W, H],
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    target = Path(argv[1])
    out = Path(argv[argv.index("-o") + 1]) if "-o" in argv else Path("tmp/rig") / target.name
    doc, pkg_dir = load_package(target)
    res = render(doc, pkg_dir, out)
    print(f"[rig] {pkg_dir.name}: 画布 {res['canvas'][0]}x{res['canvas'][1]}"
          f"，mesh 降级 {res['mesh_degraded']} 件")
    print(f"      pose    → {res['pose']}")
    print(f"      overlay → {res['overlay']}")
    print(f"      rig     → {res['rig']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
