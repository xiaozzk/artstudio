"""Blender 侧「模块化换装 + 体型 morph」最小可复现样例。

验证两条产出 morph target 的路线：
  A. 衣服从身体网格拷贝/派生（同拓扑）→ 天然继承同名 shape key
  B. 独立建模的衣服 → Surface Deform 跟随身体 → 把形变烘成它自己的同名 shape key
两条路线产出的 GLB 都必须在「身体」和「衣服」上各带一个同名 morph target（glTF morph target），
因为 glTF/Godot 的 morph 是 per-mesh 的，不能跨网格共享。

用法: blender --background --python make_morph_demo.py
"""
import json
import struct
import sys
from pathlib import Path

import bpy

OUT = Path(__file__).resolve().parent / "morph_demo.glb"


def only(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# ── 0. 空场景 ────────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)

# ── 1. 身体：一个封闭的方柱当躯干，加 Basis + fat 两个 shape key ────────────
bpy.ops.mesh.primitive_cube_add(size=1.0)
body = bpy.context.object
body.name = "Body"
body.data.name = "BodyMesh"
only(body)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.subdivide(number_cuts=4)
bpy.ops.object.mode_set(mode="OBJECT")

body.shape_key_add(name="Basis", from_mix=False)
fat = body.shape_key_add(name="fat", from_mix=False)
for i, v in enumerate(body.data.vertices):
    # 绝对坐标（不是增量）：横向鼓起来 + 略微增厚
    fat.data[i].co = (v.co.x * 1.30, v.co.y * 1.15, v.co.z)
body.data.shape_keys.key_blocks["fat"].value = 0.0
print(f"BODY shape keys: {[k.name for k in body.data.shape_keys.key_blocks]}")

# ── 2. 路线 A：衣服 = 身体拷贝（同拓扑 → 自动继承 shape key）────────────────
only(body)
bpy.ops.object.duplicate()
shirt = bpy.context.object
shirt.name = "Shirt_fromBody"
shirt.data.name = "ShirtMesh"
shirt.scale = (1.08, 1.08, 0.55)          # 压扁成"背心"外形
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
print(f"SHIRT shape keys (继承): {[k.name for k in shirt.data.shape_keys.key_blocks]}")

# ── 3. 路线 B：独立衣服 + Surface Deform 跟随身体 → 烘成自己的 fat shape key ──
bpy.ops.mesh.primitive_cylinder_add(radius=0.60, depth=0.7, vertices=24, location=(0, 0, 0.15))
vest = bpy.context.object
vest.name = "Vest_independent"
vest.data.name = "VestMesh"
sw = vest.modifiers.new("Shrinkwrap", "SHRINKWRAP")
sw.target = body
sw.offset = 0.02
only(vest)
bpy.ops.object.modifier_apply(modifier=sw.name)      # 无 shape key 时才能 apply

sd = vest.modifiers.new("SurfaceDeform", "SURFACE_DEFORM")
sd.target = body
bpy.ops.object.surfacedeform_bind(modifier=sd.name)  # 跟随身体的形变（含 shape key）

# 把身体的 fat 拉到 1.0 → 取衣服被带动后的顶点位置 → 写成衣服自己的 fat shape key
body.data.shape_keys.key_blocks["fat"].value = 1.0
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
ev = vest.evaluated_get(dg)
me = ev.to_mesh()
coords = [v.co.copy() for v in me.vertices]
ev.to_mesh_clear()

vest.shape_key_add(name="Basis", from_mix=False)
vest_fat = vest.shape_key_add(name="fat", from_mix=False)
for i, c in enumerate(coords):
    vest_fat.data[i].co = c
body.data.shape_keys.key_blocks["fat"].value = 0.0

# 关键：烘完就删掉修改器。glTF 导出无法在带 shape key 的网格上应用修改器，
# 而 morph target 已经承担了形变，修改器不再需要。
vest.modifiers.clear()
print(f"VEST shape keys (烘出来的): {[k.name for k in vest.data.shape_keys.key_blocks]}")

# 验证：三个网格的 fat 相对 Basis 是否真有位移（否则就是空形变）
print("\n每个网格 fat 相对 Basis 的最大顶点位移：")
for obj in (body, shirt, vest):
    kb = obj.data.shape_keys.key_blocks
    d = max((kb["fat"].data[i].co - kb["Basis"].data[i].co).length
            for i in range(len(kb["Basis"].data)))
    flag = "OK" if d > 0.01 else "!! 空形变"
    print(f"  {obj.name:18} max_delta={d:.4f}  {flag}")


# ── 4. 导出 GLB（只传当前 Blender 版本支持的参数）────────────────────────────
props = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
want = {
    "filepath": str(OUT),
    "export_format": "GLB",
    "export_morph": True,
    "export_morph_normal": True,
    "export_morph_tangent": False,
    "export_apply": False,          # 有 shape key 时不能 apply 修改器
    "export_yup": True,
    "use_selection": False,
}
kwargs = {k: v for k, v in want.items() if k in props}
print("EXPORT kwargs:", kwargs)
bpy.ops.export_scene.gltf(**kwargs)

# ── 5. 直接读回 GLB，确认每个网格真的带上了同名 morph target ─────────────────
raw = OUT.read_bytes()
length = struct.unpack_from("<I", raw, 12)[0]
doc = json.loads(raw[20:20 + length].decode("utf-8"))
print("\nGLB 里的网格与 morph target：")
for mesh in doc.get("meshes", []):
    names = (mesh.get("extras") or {}).get("targetNames")
    prims = mesh.get("primitives", [])
    n_targets = len(prims[0].get("targets", [])) if prims else 0
    verts = doc["accessors"][prims[0]["attributes"]["POSITION"]]["count"] if prims else "-"
    # 每个 morph target 是否真的带位置增量（不为空）
    deltas = []
    for t in (prims[0].get("targets", []) if prims else []):
        acc = doc["accessors"][t["POSITION"]]
        deltas.append(acc["count"])
    print(f"  mesh={mesh.get('name')!r:24} primitives={len(prims)} vertices={verts} "
          f"morph_targets={n_targets} targetNames={names} target_vert_counts={deltas}")

# 断言：两个网格都要有名为 fat 的 morph target
ok = True
for mesh in doc.get("meshes", []):
    names = (mesh.get("extras") or {}).get("targetNames") or []
    if "fat" not in names:
        ok = False
        print(f"  !! {mesh.get('name')} 缺少 fat morph target")
print("\nRESULT:", f"PASS {len(doc.get(chr(109)+chr(101)+chr(115)+chr(104)+chr(101)+chr(115), []))} 个网格全部带 fat morph target" if ok else "FAIL")
print("GLB:", OUT, OUT.stat().st_size, "bytes")