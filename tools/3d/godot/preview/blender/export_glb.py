# -*- coding: utf-8 -*-
"""`.blend` → `.glb`（贴图内嵌）—— 为 Godot 运行时零拷贝加载做预导出。

为什么要这一步：
  * Godot 没有原生 `.blend` 解析器；走 Godot 的 `.blend` 导入管线必须先把 `.blend`
    复制进工程（`res://`），而且 Godot 还会把贴图解包到 `res://assets/textures/`
    —— 那正是我们要避免的"素材副本"（贴图合计 ~125 MB）。
  * 所以：由 Blender headless 预导出 `.glb` 到 **`tmp/` 缓存**（工程外），
    Godot 侧用 `GLTFDocument.append_from_file(<绝对路径>)` 读它。工程里零素材副本。

两个必须做的处理（否则 Godot 侧一开始就是错的形状）：
  1. **导出前把所有 shape key 值清零** —— 标准体 `.blend` 里存的值是 1.0/1.0
     （Lead 落盘时的状态），不清零的话 glTF 的默认 morph 权重就是 (1,1) = 瘦壮同时拉满。
     只在内存里改，**不写回源文件**。
  2. 关掉相机/灯光导出（`.blend` 里带着 task-1 留下的预览相机与灯，会顶掉我们的取景）。

用法：
  Blender --background --factory-startup --python export_glb.py -- <src.blend> <dst.glb> \
      [--body-morph] [--spec <bodyshape_spec.json>] [--report <extra.json>]

`--body-morph`：导出前先跑 `_morphfix.ensure_body_morph()` —— 当标准体里的
`BS_Thin`/`BS_Heavy` 还是全零占位（T1 未落地）时，按 SPEC §3.2 骨骼滑块现场派生一份
fixture morph；T1 落地后该函数自动跳过（`source=asset`）。
"""
import json
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import _morphfix  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
want_body_morph = "--body-morph" in argv
spec_path = None
if "--spec" in argv:
    spec_path = argv[argv.index("--spec") + 1]
extra_report = None
if "--report" in argv:
    extra_report = argv[argv.index("--report") + 1]

bpy.ops.wm.open_mainfile(filepath=src)

morph_report = None
if want_body_morph:
    body = _morphfix.find_body()
    if body is None:
        raise SystemExit("--body-morph 但找不到带 shape key 的 Body_* 网格：%s" % src)
    morph_report = _morphfix.ensure_body_morph(body, spec_path)
    print("MORPHFIX " + json.dumps(morph_report, ensure_ascii=False))

# ① shape key 值清零（只在内存里，不 save）
for ob in bpy.data.objects:
    if ob.type == 'MESH' and ob.data.shape_keys:
        for kb in ob.data.shape_keys.key_blocks:
            kb.value = 0.0

# ② 稳妥起见把这些容易污染场景的东西从内存里删掉（不 save，不影响源文件）
for name in ("Camera", "Sun", "Fill", "Key", "Rim"):
    ob = bpy.data.objects.get(name)
    if ob is not None and ob.type in {'CAMERA', 'LIGHT'}:
        bpy.data.objects.remove(ob, do_unlink=True)

# glTF 导出的参数名跨版本变过，按 RNA 里实际存在的键逐项设置，避免 TypeError。
props = bpy.ops.export_scene.gltf.get_rna_type().properties
kw = {"filepath": dst, "export_format": "GLB"}
wanted = {
    "export_apply": False,          # 千万不能 True：会把 Armature 修改器烘掉
    "export_morph": True,           # shape key → glTF morph target
    "export_morph_normal": True,
    "export_skins": True,
    "export_yup": True,
    "export_cameras": False,
    "export_lights": False,
    "use_selection": False,
    "export_animations": False,     # 本预览只做静态三档，不需要动画
    "export_def_bones": False,
    "export_tangents": False,
    "export_materials": "EXPORT",
    "export_image_format": "AUTO",
    "export_extras": False,
    "export_reset_pose_bones": False,
    "export_all_influences": False,
    "export_hierarchy_full_collections": False,
}
for k, v in wanted.items():
    if k in props:
        kw[k] = v

os.makedirs(os.path.dirname(dst), exist_ok=True)
bpy.ops.export_scene.gltf(**kw)

rep = {
    "src": src, "dst": dst, "bytes": os.path.getsize(dst),
    "meshes": {}, "morphs": {}, "armatures": [], "morph_fixture": morph_report,
}
for ob in bpy.data.objects:
    if ob.type == 'MESH':
        rep["meshes"][ob.name] = {"verts": len(ob.data.vertices),
                                  "polys": len(ob.data.polygons)}
        if ob.data.shape_keys:
            rep["morphs"][ob.name] = [k.name for k in ob.data.shape_keys.key_blocks]
    elif ob.type == 'ARMATURE':
        rep["armatures"].append({"name": ob.name, "bones": len(ob.data.bones)})
print("EXPORT_JSON " + json.dumps(rep, ensure_ascii=False))
if extra_report:
    os.makedirs(os.path.dirname(extra_report), exist_ok=True)
    with open(extra_report, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)