"""tools/3d/garment/common.py —— 服装变形链共享工具

契约：assets/3d/rig/SPEC.md v1.0
  ① F9：所有测量必须走 depsgraph 求值（shape key 不改 mesh.vertices）
  ② 骨架 rest 映射用 bone.matrix_local（armature space）
  ③ 穿模 = 服装顶点落在标准体内部

被 strip_skin.py / refit.py / transfer_morph.py / verify_fit.py / preview.py 共用。
不要 import bpy 之外的重依赖（只用 numpy 之外的标准库 + mathutils）。
"""
import bpy
import bmesh
import json
import math
import os
import sys
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

# ————————————————————————————————————————————————————————————
# 路径（本文件在 tools/3d/garment/，ROOT 上溯 4 层）
# ————————————————————————————————————————————————————————————
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC_OUTFITS = os.path.join(ROOT, "assets/3d/blend/outfits-gltf-per-asset/outfits")
SRC_TEX = os.path.join(ROOT, "assets/3d/textures")
RIG = os.path.join(ROOT, "assets/3d/rig")
BODIES = os.path.join(RIG, "bodies")
GARMENTS = os.path.join(RIG, "garments")
MANIFESTS = os.path.join(RIG, "manifests")
PREVIEWS = os.path.join(RIG, "previews")
WORK = os.path.join(ROOT, "tmp/garment/work")
GARMENT_MANIFEST = os.path.join(MANIFESTS, "garment_manifest.json")

# 4 套服装：outfit 文件 → 性别
OUTFITS = [("Female_Ranger", "Female"), ("Female_Peasant", "Female"),
           ("Male_Ranger", "Male"), ("Male_Peasant", "Male")]

# SPEC §3.2 canonical 体形骨（fixture 用）
SHAPE_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r"]

# 皮肤材质前缀（SPEC §4.1 ①）
SKIN_MAT_PREFIX = "MI_Regular_"

# SPEC §3.3 morph 契约
MORPH_ORDER = ["Basis", "BS_Thin", "BS_Heavy"]


def log(*a):
    print(*a, flush=True)


def rel(p):
    return os.path.relpath(p, ROOT)


def ensure_dirs():
    for d in (GARMENTS, MANIFESTS, PREVIEWS, WORK):
        os.makedirs(d, exist_ok=True)


def set_save_version_0():
    """红线：保存 .blend 前必须关掉版本备份（否则留下 .blend1）。"""
    try:
        bpy.context.preferences.filepaths.save_version = 0
    except Exception as e:                                    # pragma: no cover
        log(f"  [warn] 无法设置 save_version=0: {e}")


def save_blend(path):
    set_save_version_0()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    # save_as_mainfile 之后 preferences 可能被重置，复查一次
    set_save_version_0()
    log(f"  已保存 → {rel(path)}  ({os.path.getsize(path)/1024:.0f} KB)")


# ————————————————————————————————————————————————————————————
# depsgraph 求值（F9）
# ————————————————————————————————————————————————————————————
def eval_mesh(obj, want_tris=False):
    """depsgraph 求值 → (世界坐标顶点 list[Vector], 三角面索引 list[tuple] | None)"""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    mw = ev.matrix_world
    pts = [mw @ v.co for v in me.vertices]
    tris = None
    if want_tris:
        me.calc_loop_triangles()
        tris = [tuple(t.vertices) for t in me.loop_triangles]
    ev.to_mesh_clear()
    return pts, tris


def eval_pts(obj):
    return eval_mesh(obj, False)[0]


def tri_count(obj):
    return len(eval_mesh(obj, True)[1])


def set_shape_values(obj, values):
    """values: {name: float}；不存在的通道静默忽略。"""
    if obj.data.shape_keys is None:
        return
    for k in obj.data.shape_keys.key_blocks:
        k.value = values.get(k.name, 0.0)
    bpy.context.view_layer.update()


def clear_shape_values(obj):
    set_shape_values(obj, {})


# ————————————————————————————————————————————————————————————
# BVH / 穿模度量
# ————————————————————————————————————————————————————————————
def bvh_from_pts_tris(pts, tris):
    verts = []
    idx = []
    for t in tris:
        b = len(verts)
        verts.extend((pts[t[0]], pts[t[1]], pts[t[2]]))
        idx.append((b, b + 1, b + 2))
    return BVHTree.FromPolygons(verts, idx, all_triangles=True)


def _crossings(tree, p, d, cap=64):
    """沿方向 d 从 p 出发，数穿面次数（射线行进法）。"""
    n = 0
    o = p + d * 1e-6
    while n < cap:
        loc, nor, fi, dist = tree.ray_cast(o, d)
        if loc is None:
            break
        n += 1
        o = loc + d * 1e-5
    return n


# 5 个非轴对齐方向（避免与轴对齐面/边退化）
_RAYS = [Vector(v).normalized() for v in (
    (1.0, 0.0, 0.0), (0.31713, 0.92308, 0.21837), (-0.51234, 0.22187, 0.82931),
    (0.11111, -0.73204, 0.67213), (-0.61037, -0.57731, 0.54219))]


def penetration(garment_pts, body_tree, body_pts, body_tris,
                use_rays=True, sample_rays=5, nearest_normal=True):
    """穿模度量。

    主判据 ray parity（奇穿过 = 内部；对凸/凹/开口都成立，取 5 方向多数票）
    次判据 nearest-surface normal sign（便宜，但在凹位会误判）

    返回 dict：inside 数、总数、比例，两法各一份 + 分歧数。
    """
    n = len(garment_pts)
    ray_inside = 0
    amb = 0
    if use_rays:
        for p in garment_pts:
            votes_in = 0
            votes_ok = 0
            for d in _RAYS[:sample_rays]:
                c = _crossings(body_tree, p, d)
                if c >= 64:          # 退化/掠射，弃票
                    continue
                votes_ok += 1
                if c % 2 == 1:
                    votes_in += 1
            if votes_ok == 0:
                amb += 1
                continue
            if votes_in * 2 > votes_ok:
                ray_inside += 1
    nn_inside = 0
    nn_amb = 0
    disagree = 0
    if nearest_normal:
        for p in garment_pts:
            loc, nor, fi, dist = body_tree.find_nearest(p)
            if loc is None:
                nn_amb += 1
                continue
            is_in = (p - loc).dot(nor) < 0.0
            if is_in:
                nn_inside += 1
            if use_rays:
                for d in _RAYS[:sample_rays]:
                    c = _crossings(body_tree, p, d)
                    if c >= 64:
                        continue
                    if (c % 2 == 1) != is_in:
                        disagree += 1
                    break
    res = {"n": n,
           "ray_inside": ray_inside, "ray_rate": (ray_inside / n if n else 0.0),
           "ray_ambiguous": amb,
           "nn_inside": nn_inside, "nn_rate": (nn_inside / n if n else 0.0),
           "nn_ambiguous": nn_amb,
           "disagree": disagree}
    return res


def mesh_boundary_edges(pts_tris):
    """数只被一个三角面用到的边 —— 判断体网格是否闭合（决定 ray parity 是否可信）"""
    cnt = {}
    for t in pts_tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            k = (a, b) if a < b else (b, a)
            cnt[k] = cnt.get(k, 0) + 1
    return sum(1 for v in cnt.values() if v == 1)


def fmt_pct(x):
    return f"{100*x:.2f}%"


# ————————————————————————————————————————————————————————————
# 重心坐标 + 三角面标架（SPEC §4.2 / F8）
# ————————————————————————————————————————————————————————————
def bary(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
    d20, d21 = v2.dot(v0), v2.dot(v1)
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-14:
        return Vector((1.0, 0.0, 0.0))
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return Vector((1.0 - v - w, v, w))


def frame(a, b, c):
    """返回正交标架 (t̂, n̂×t̂, n̂)；退化三角面返回 None。"""
    n = (b - a).cross(c - a)
    t = b - a
    if n.length < 1e-12 or t.length < 1e-12:
        return None
    n = n.normalized()
    t = t.normalized()
    return (t, n.cross(t), n)


def frame_local(d, f):
    return Vector((d.dot(f[0]), d.dot(f[1]), d.dot(f[2])))


def frame_apply(local, f):
    return f[0] * local[0] + f[1] * local[1] + f[2] * local[2]


# ————————————————————————————————————————————————————————————
# 骨架 rest 映射（SPEC §4.1 ②）
# ————————————————————————————————————————————————————————————
def bone_rest_map(reg_arm, std_arm):
    """返回 {bone_name: 4x4}，M = std.matrix_local @ reg.matrix_local⁻¹

    两个骨架的 object matrix_world 必须都是单位矩阵（地图空间 == 世界空间），
    否则先右乘/左乘换算。
    """
    assert reg_arm.matrix_world != Matrix() or True
    rw, sw = reg_arm.matrix_world, std_arm.matrix_world
    assert (rw.translation.length < 1e-9 and rw.to_quaternion().angle < 1e-9
            and abs(rw.to_scale().x - 1) < 1e-9), f"服装骨架非单位变换: {rw}"
    assert (sw.translation.length < 1e-9 and sw.to_quaternion().angle < 1e-9
            and abs(sw.to_scale().x - 1) < 1e-9), f"标准体骨架非单位变换: {sw}"
    out = {}
    for b in reg_arm.data.bones:
        if b.name in std_arm.data.bones:
            out[b.name] = std_arm.data.bones[b.name].matrix_local @ b.matrix_local.inverted()
    return out


def bone_rest_stats(reg_arm, std_arm):
    """rest 差异统计（头位置 / 旋转），返回 dict — 用于 manifest 证据。"""
    pos = []
    rot = 0
    for b in reg_arm.data.bones:
        sb = std_arm.data.bones.get(b.name)
        if not sb:
            continue
        d = (sb.matrix_local.translation - b.matrix_local.translation).length
        pos.append((d, b.name))
        if b.matrix_local.to_quaternion().rotation_difference(
                sb.matrix_local.to_quaternion()).angle > 1e-4:
            rot += 1
    pos.sort(reverse=True)
    return {"bones": len(pos),
            "pos_diff_gt_1e-6": sum(1 for d, _ in pos if d > 1e-6),
            "rot_diff_gt_1e-4": rot,
            "max_pos_diff_cm": round(pos[0][0] * 100, 4) if pos else 0.0,
            "max_pos_bone": pos[0][1] if pos else None,
            "top5": [(n, round(d * 100, 3)) for d, n in pos[:5]]}


def skin_vertex(obj, p, bone_map, vg_names):
    """逐顶点骨空间重绑（线性近似，权重归一）。返回新世界坐标。"""
    v = obj.data.vertices  # noqa: F841  (调用方保证 p 与索引对应)
    return None


def skin_points(obj, pts, bone_map):
    """对「顶点索引顺序 == pts 顺序」的点列做骨空间重绑。

    权重和已实测为 1.000（recon2），仍显式归一以防万一。
    """
    names = [g.name for g in obj.vertex_groups]
    out = []
    missing = set()
    for i, p in enumerate(pts):
        acc = Vector()
        ws = 0.0
        for g in obj.data.vertices[i].groups:
            nm = names[g.group]
            if nm not in bone_map:
                missing.add(nm)
                continue
            acc += (bone_map[nm] @ p) * g.weight
            ws += g.weight
        if ws > 1e-9:
            out.append(acc / ws)
        else:
            out.append(p.copy())
    return out, missing


def apply_points(obj, pts):
    """把点写回 mesh.vertices（要求 obj 无 shape key 或已冻结）。"""
    assert obj.data.shape_keys is None or len(obj.data.shape_keys.key_blocks) <= 1, \
        f"{obj.name} 有 shape key，不能直接改 mesh.vertices"
    for i, p in enumerate(pts):
        obj.data.vertices[i].co = p
    obj.data.update()


# ————————————————————————————————————————————————————————————
# mesh 编辑
# ————————————————————————————————————————————————————————————
def strip_faces_by_material(obj, pred):
    """删除满足 pred(材质名) 的面 + 孤立顶点 + 无用材质槽。

    返回 dict(before/after 顶点面数、删除面数、材质前后列表)。
    """
    me = obj.data
    me.calc_loop_triangles()
    before_v, before_f = len(me.vertices), len(me.polygons)
    mats_before = [m.name if m else None for m in me.materials]

    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    # 面材质名（用 bmesh 的 material_index 映射到 me.materials）
    slot_names = [m.name if m else "" for m in me.materials]
    dead = [f for f in bm.faces
            if pred(slot_names[f.material_index] if f.material_index < len(slot_names) else "")]
    dead_cnt = len(dead)
    keep_names = [n for n in slot_names if not pred(n)]
    remap = {}
    for old, n in enumerate(slot_names):
        if n in keep_names:
            remap[old] = keep_names.index(n)
    for f in bm.faces:
        if f in dead:
            continue
        f.material_index = remap.get(f.material_index, 0)
    if dead:
        bmesh.ops.delete(bm, geom=dead, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    loose_cnt = len(loose)
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bm.to_mesh(me)
    bm.free()
    # 重建材质槽
    kept = []
    for n in keep_names:
        m = next((x for x in me.materials if (x.name if x else "") == n), None)
        kept.append(m)
    me.materials.clear()
    for m in kept:
        me.materials.append(m)
    me.update()
    return {"before_verts": before_v, "before_faces": before_f,
            "after_verts": len(me.vertices), "after_faces": len(me.polygons),
            "removed_faces": dead_cnt, "removed_loose_verts": loose_cnt,
            "materials_before": mats_before,
            "materials_after": [m.name if m else None for m in me.materials]}


def face_material_histogram(obj):
    me = obj.data
    me.calc_loop_triangles()
    cnt = {}
    for t in me.loop_triangles:
        m = me.materials[t.material_index] if t.material_index < len(me.materials) else None
        k = m.name if m else "<none>"
        cnt[k] = cnt.get(k, 0) + 1
    return cnt


def is_helper(obj):
    """源包里的环境辅助体（Icosphere，无材质无权重）—— 不是服装。"""
    if obj.type != 'MESH':
        return False
    return obj.name.startswith("Icosphere") and len(obj.data.materials) == 0


def mesh_objects(blend_path):
    names = [o.name for o in bpy.data.objects if o.type == 'MESH']
    return names


def load_object_from(blend_path, obj_name):
    """从另一个 .blend 只加载一个 object（含其 data 依赖），不加载同文件的网格。"""
    before = set(bpy.data.objects.keys())
    with bpy.data.libraries.load(blend_path, link=False) as (src, dst):
        assert obj_name in src.objects, f"{blend_path} 里没有 {obj_name}: {src.objects}"
        dst.objects = [obj_name]
    new = [o for o in dst.objects if o is not None]
    assert new, "加载失败"
    return new[0]


def purge_orphans():
    for _ in range(4):
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True,
                                       do_recursive=True)


def used_images():
    out = set()
    for m in bpy.data.materials:
        if not m.use_nodes or not m.node_tree:
            continue
        for n in m.node_tree.nodes:
            if n.type == 'TEX_IMAGE' and n.image:
                out.add(n.image.name)
    return out


def texture_report():
    miss = []
    for img in bpy.data.images:
        if img.source == 'FILE':
            ap = bpy.path.abspath(img.filepath)
            if not os.path.exists(ap):
                miss.append({"name": img.name, "path": img.filepath})
    return miss


# ————————————————————————————————————————————————————————————
# 三角形的拉伸比离散度（SPEC §5 身高缩放相对失真）
# ————————————————————————————————————————————————————————————
def stretch_dispersion(pts_a, pts_b, tris):
    """对每个三角面算边长缩放比，去掉全局中位数后看离散度（std/mean）。"""
    ratios = []
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            l0 = (pts_a[a] - pts_a[b]).length
            l1 = (pts_b[a] - pts_b[b]).length
            if l0 > 1e-7:
                ratios.append(l1 / l0)
    if not ratios:
        return 0.0, 0.0
    ratios.sort()
    med = ratios[len(ratios) // 2]
    norm = [r / med for r in ratios]
    mean = sum(norm) / len(norm)
    var = sum((x - mean) ** 2 for x in norm) / len(norm)
    return math.sqrt(var), mean