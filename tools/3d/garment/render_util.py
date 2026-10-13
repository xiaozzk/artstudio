"""tools/3d/garment/render_util.py —— 渲染/读像素的共用工具（被 preview.py 与 probe_independent.py 复用）

要点
----
· Blender {v} 的 EEVEE 引擎标识符是 `'BLENDER_EEVEE'`（读 enum 得到，不要凭记忆写 NEXT）
· 分类用**色相主导**而不是精确等值 —— 贴图/抗锯齿/色彩管理都会略微改数值
· 像素用 numpy `foreach_get` 读（纯 Python 逐像素太慢）
"""
import math
import os

import bpy
import numpy as np
from mathutils import Vector

ENGINE = 'BLENDER_EEVEE'


def setup_scene(res_x=700, res_y=1000, samples=16):
    sc = bpy.context.scene
    try:
        sc.render.engine = ENGINE
    except TypeError as e:                                   # pragma: no cover
        raise SystemExit(f"引擎标识符不对，可选：{e}")
    sc.render.resolution_x, sc.render.resolution_y = res_x, res_y
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.film_transparent = True
    try:
        sc.eevee.taa_render_samples = samples
    except Exception:
        pass
    # 世界全黑（发光材质自带亮度，不需要环境光）
    if sc.world is None:
        sc.world = bpy.data.worlds.new("W")
    sc.world.use_nodes = True
    bg = next((n for n in sc.world.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bg:
        bg.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        bg.inputs[1].default_value = 0.0
    return sc


def emission_material(name, rgb, strength=1.0):
    m = bpy.data.materials.get(name)
    if m:
        bpy.data.materials.remove(m)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs[0].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    em.inputs[1].default_value = strength
    nt.links.new(em.outputs[0], out.inputs[0])
    return m


def vertex_color_material(name, attr="Col", strength=1.0):
    """顶点色自发光材质 —— 用来把"落入标准体内部的顶点染红"可视化。"""
    m = bpy.data.materials.get(name)
    if m:
        bpy.data.materials.remove(m)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    at = nt.nodes.new("ShaderNodeVertexColor")
    at.layer_name = attr
    em.inputs[1].default_value = strength
    nt.links.new(at.outputs[0], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs[0])
    return m


def set_color_attribute(obj, per_vertex_rgba, name="Col"):
    """写 POINT 域 FLOAT_COLOR 属性；per_vertex_rgba = [(r,g,b,a), ...]"""
    me = obj.data
    if name in me.color_attributes:
        me.color_attributes.remove(me.color_attributes[name])
    ca = me.color_attributes.new(name=name, type='FLOAT_COLOR', domain='POINT')
    for i, c in enumerate(per_vertex_rgba):
        ca.data[i].color = c
    return ca


def swap_materials(obj, mat):
    """临时换材质，返回可恢复的快照。"""
    snap = [m for m in obj.data.materials]
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for p in obj.data.polygons:
        p.material_index = 0
    return snap


def restore_materials(obj, snap):
    obj.data.materials.clear()
    for m in snap:
        obj.data.materials.append(m)


def look_at_rotation(loc, target):
    d = Vector(target) - Vector(loc)
    return d.to_track_quat('-Z', 'Y').to_euler()


def add_camera(name, loc, target, lens=50.0, ortho_scale=None):
    cd = bpy.data.cameras.new(name)
    if ortho_scale:
        cd.type = 'ORTHO'
        cd.ortho_scale = ortho_scale
    else:
        cd.lens = lens
    cam = bpy.data.objects.new(name, cd)
    cam.location = loc
    cam.rotation_euler = look_at_rotation(loc, target)
    bpy.context.scene.collection.objects.link(cam)
    return cam


def render_to(path, camera):
    bpy.context.scene.camera = camera
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def read_pixels(path):
    """返回 (h, w, 4) 的 float 数组；用完要 bpy.data.images.remove。"""
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(h, w, 4)


def classify(arr, r=1.0, g=0.0, b=0.0, tol=0.25):
    """色相主导分类：返回布尔 mask（该像素是否属于指定纯色）。"""
    if r > g and r > b:
        return (arr[:, :, 0] > arr[:, :, 1] + tol) & (arr[:, :, 0] > arr[:, :, 2] + tol)
    if g > r and g > b:
        return (arr[:, :, 1] > arr[:, :, 0] + tol) & (arr[:, :, 1] > arr[:, :, 2] + tol)
    return (arr[:, :, 2] > arr[:, :, 0] + tol) & (arr[:, :, 2] > arr[:, :, 1] + tol)


def opaque_mask(arr):
    """film_transparent=True 时 alpha>0.5 即被物体覆盖。"""
    return arr[:, :, 3] > 0.5