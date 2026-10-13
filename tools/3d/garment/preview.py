"""tools/3d/garment/preview.py —— 视觉证据：三态并排渲染 + 穿模可视化

产出（全部落在 `assets/3d/rig/previews/`，文件名前缀 `garment_`）
--------------------------------------------------------------
1. `garment_<outfit>_tiers.png` —— **rest / BS_Thin=1 / BS_Heavy=1 三态并排**
   做法：把角色复制三份沿 X 平移摆开，各挂一档 shape key 值，一台相机一次成像。
   （比渲三张再拼更省事，也不会因相机不一致造成视差误读。）
2. `garment_<outfit>_penetration.png` —— **穿模可视化**：
   角色自带的皮肤面顶点里，落在**布料内部**的染红、其余染灰绿，布料本身半透明白。
   B2 下预期**几乎全绿**（不存在独立身体）。
3. `garment_<outfit>_skin_vs_cloth_*.png` —— 像素法对照图（由 verify_fit.py 产出：
   皮肤纯红 / 布料纯绿 + alpha 剪影）。

用法
----
  Blender -b --factory-startup --python tools/3d/garment/preview.py -- \
      [--garments assets/3d/rig/garments] [--previews assets/3d/rig/previews] [--only Female_Ranger]
"""
import argparse
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C        # noqa: E402
import render_util as RU  # noqa: E402

TIERS = ("rest", "BS_Thin", "BS_Heavy")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="preview.py")
    ap.add_argument("--garments", default=C.GARMENTS)
    ap.add_argument("--previews", default=C.PREVIEWS)
    ap.add_argument("--only", default=None)
    ap.add_argument("--width", type=int, default=1500)
    ap.add_argument("--height", type=int, default=760)
    ap.add_argument("--spacing", type=float, default=1.15)
    return ap.parse_args(argv)


def mesh_objs():
    return sorted([o for o in bpy.data.objects
                   if o.type == 'MESH' and o.data.shape_keys is not None],
                  key=lambda x: x.name)


def duplicate_character(meshes, arm, dx, tier):
    """把角色整体复制一份沿 X 平移 dx，并挂上指定档的 shape key。"""
    new_arm = arm.copy()
    new_arm.data = arm.data.copy()
    new_arm.name = f"{arm.name}__{tier}"
    new_arm.animation_data_clear()
    bpy.context.scene.collection.objects.link(new_arm)
    new_arm.location.x += dx
    for o in meshes:
        d = o.copy()
        d.data = o.data.copy()
        d.name = f"{o.name}__{tier}"
        bpy.context.scene.collection.objects.link(d)
        d.parent = new_arm
        d.matrix_parent_inverse = new_arm.matrix_world.inverted()
        for m in d.modifiers:
            if m.type == 'ARMATURE':
                m.object = new_arm
        if tier != "rest":
            d.data.shape_keys.key_blocks[tier].value = 1.0
        C.clear_shape_values(d) if tier == "rest" else None
        if tier != "rest":
            d.data.shape_keys.key_blocks[tier].value = 1.0
    bpy.context.view_layer.update()
    return new_arm


def render_tiers(outfit, meshes, arm, a):
    for o in meshes:
        C.clear_shape_values(o)
    tmp_objs = []
    for i, tier in enumerate(TIERS):
        dup = duplicate_character(meshes, arm, i * a.spacing, tier)
        tmp_objs.append(dup)
    RU.setup_scene(res_x=a.width, res_y=a.height, samples=24)
    sc = bpy.context.scene
    sc.view_settings.view_transform = 'Standard'
    sc.render.film_transparent = False
    # 灰底 + 三盏面光
    sc.world.use_nodes = True
    bg = next(n for n in sc.world.node_tree.nodes if n.type == 'BACKGROUND')
    bg.inputs[0].default_value = (0.05, 0.055, 0.07, 1.0)
    bg.inputs[1].default_value = 1.0
    lights = []
    for nm, loc, e in (("K", (2.6, -3.2, 3.2), 900), ("F", (-3.0, -2.4, 1.6), 420),
                       ("B", (0.0, 3.0, 2.4), 380)):
        ld = bpy.data.lights.new(nm, 'AREA')
        ld.energy = e
        ld.size = 3.0
        lo = bpy.data.objects.new(nm, ld)
        lo.location = loc
        lo.rotation_euler = RU.look_at_rotation(loc, (0, 0, 0.95))
        sc.collection.objects.link(lo)
        lights.append(lo)
    cx = (len(TIERS) - 1) * a.spacing / 2.0
    cam = RU.add_camera("__tiers_cam", (cx, -4.6, 1.05), (cx, 0.0, 0.95), lens=52.0)
    p = os.path.join(a.previews, f"garment_{outfit}_tiers.png")
    RU.render_to(p, cam)
    C.log(f"  三态并排 → {C.rel(p)}")
    for o in tmp_objs:
        bpy.data.objects.remove(o, do_unlink=True)
    for lo in lights:
        bpy.data.objects.remove(lo, do_unlink=True)
    bpy.data.objects.remove(cam, do_unlink=True)
    return p


def proxy_from(obj, verts, name):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    kill = [f for f in bm.faces if not all(v.index in verts for v in f.verts)]
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    if len(bm.verts) == 0:
        bm.free()
        return None
    nm = bpy.data.meshes.new(name)
    bm.to_mesh(nm)
    bm.free()
    ob = bpy.data.objects.new(name, nm)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def render_penetration(outfit, meshes, arm, a, gate=0.03):
    """穿模可视化（与 M3v 同向、同闸门）：**布料顶点陷进皮肤面内部**的染红。

    ⚠ 方向很重要：`皮肤顶点落在布料外部` 是**正常现象**（前臂/手本来就裸露），
      把它当"穿模"会把 30% 的正常裸露渲染成红色 —— 这正是"顶点级口径不可靠"
      的直观表现（Lead FINDINGS §11.1）。有意义的方向是**布料陷进身体**。
    ⚠ 距离闸门：只在皮肤面 3 cm 内的布料顶点上判定，避免远场 find_nearest 乱指。
    """
    skin_pts, skin_tris = [], []
    for o in meshes:
        me = o.data
        me.calc_loop_triangles()
        hit = {i for i, m in enumerate(me.materials)
               if (m.name if m else "").startswith(C.SKIN_MAT_PREFIX)}
        sv = set()
        other = set()
        for t in me.loop_triangles:
            (sv if t.material_index in hit else other).update(t.vertices)
        sv -= other
        if sv:
            po = proxy_from(o, sv, f"__prevskin_{o.name}")
            if po:
                p, tr = C.eval_mesh(po, want_tris=True)
                b = len(skin_pts)
                skin_pts += p
                skin_tris += [tuple(i + b for i in t) for t in tr]
    if not skin_pts:
        C.log(f"  [skip] {outfit} 无 MI_Regular_* 皮肤面（服装全包裹）→ 无穿模可视化")
        return None
    sbvh = C.bvh_from_pts_tris(skin_pts, skin_tris)

    inside_total = gated_total = 0
    for o in meshes:
        me = o.data
        me.calc_loop_triangles()
        hit = {i for i, m in enumerate(me.materials)
               if (m.name if m else "").startswith(C.SKIN_MAT_PREFIX)}
        cv = set()
        for t in me.loop_triangles:
            if t.material_index not in hit:
                cv.update(t.vertices)
        cols = []
        for v in o.data.vertices:
            if v.index not in cv:
                cols.append((0.0, 0.0, 0.0, 1.0))     # 非布料（皮肤）→ 纯黑，不参与
                continue
            world = o.matrix_world @ v.co
            loc, nor, fi, dist = sbvh.find_nearest(world)
            if loc is not None and dist <= gate:
                gated_total += 1
                if (world - loc).dot(nor) < 0.0:
                    inside_total += 1
                    cols.append((1.0, 0.06, 0.06, 1.0))   # 陷进身体 → 红
                    continue
                cols.append((0.30, 0.34, 0.38, 1.0))       # 正常布料 → 灰
            else:
                cols.append((0.18, 0.22, 0.28, 1.0))       # 离身体太远（悬空件）→ 暗蓝
        RU.set_color_attribute(o, cols)
        RU.swap_materials(o, RU.vertex_color_material(f"__VC_{o.name}"))
    RU.setup_scene(res_x=a.width // 2, res_y=a.height, samples=24)
    sc = bpy.context.scene
    sc.view_settings.view_transform = 'Standard'
    sc.render.film_transparent = False
    bg = next(n for n in sc.world.node_tree.nodes if n.type == 'BACKGROUND')
    bg.inputs[0].default_value = (0.02, 0.022, 0.03, 1.0)
    bg.inputs[1].default_value = 1.0
    cam = RU.add_camera("__pen_cam", (0.0, -3.4, 1.0), (0, 0, 0.95), lens=55.0)
    p = os.path.join(a.previews, f"garment_{outfit}_penetration.png")
    RU.render_to(p, cam)
    frac = inside_total / gated_total if gated_total else 0.0
    C.log(f"  穿模可视化 → {C.rel(p)}   闸门内布料顶点 {gated_total}，陷进皮肤 "
          f"{inside_total} = {100*frac:.2f}%（红=陷进身体，灰=正常，暗蓝=离身体>3cm）")
    bpy.data.objects.remove(cam, do_unlink=True)
    return {"png": C.rel(p), "gated_cloth_verts": gated_total, "inside": inside_total,
            "inside_frac": round(frac, 6), "gate_cm": round(gate * 100, 1),
            "direction": "cloth_inside_skin（布料陷进身体）"}


def main():
    a = parse_args()
    os.makedirs(a.previews, exist_ok=True)
    out = []
    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        fp = os.path.join(a.garments, f"{outfit}.blend")
        C.log(f"\n{'='*96}\n[preview] {outfit}")
        bpy.ops.wm.open_mainfile(filepath=fp)
        arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        meshes = mesh_objs()
        t = render_tiers(outfit, meshes, arm, a)
        bpy.ops.wm.open_mainfile(filepath=fp)
        arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        meshes = mesh_objs()
        pen = render_penetration(outfit, meshes, arm, a)
        out.append({"outfit": outfit, "tiers_png": C.rel(t), "penetration": pen})
    import json
    rp = os.path.join(C.WORK, "preview_report.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"tool": "preview.py",
                   "note": "三态并排 = 角色复制三份沿 X 摆开，各挂一档 shape key；"
                           "穿模可视化 = 皮肤面顶点落在布料内部的染红",
                   "outfits": out}, f, ensure_ascii=False, indent=2)
    C.log(f"\n报告 → {C.rel(rp)}\nDONE")


main()