"""标准体规范化 → assets/3d/rig/bodies/Body_{Female,Male}_Standard.blend

规范化的 5 件事（按 assets/3d/rig/SPEC.md §3）：
  ① 骨架改名 RIG_Body_{Female,Male}_Standard；物名 Body_{Female,Male}
  ② 体形骨（canonical 14 根）的**全部直接子骨**设 inherit_scale='NONE'
     —— 否则骨缩放会沿骨架链传递（实测：scale pelvis 会让身高意外 +11.24%）
  ③ 建立 morph 占位通道：BS_Thin(index 0) / BS_Heavy(index 1)，值为 0
  ④ 内嵌中文 README_转换说明
  ⑤ 贴图保持相对路径 //../../textures/...（新位置仍可解析）

用法：Blender -b --factory-startup --python tools/3d/make_standard_body.py
"""
import bpy, os, sys

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
SRC = f"{ROOT}/assets/3d/blend/base-characters"
DST = f"{ROOT}/assets/3d/rig/bodies"

# SPEC §3.2 canonical 体形骨
SHAPE_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r"]

JOBS = [("Female", "BaseCharacter_Superhero_Female.blend", "Superhero_Female"),
        ("Male", "BaseCharacter_Superhero_Male.blend", "SuperHero_Male")]

README_TMPL = """Body_{sex} Standard —— 角色管线 v2 标准体
==========================================

来源：assets/3d/blend/base-characters/BaseCharacter_Superhero_{Super}.blend（Quaternius UBC，CC0 1.0）
加工：tools/3d/make_standard_body.py（headless Blender 5.2.2）
契约：assets/3d/rig/SPEC.md（v1.0）

规范化的 5 件事
---------------
1. 骨架改名 RIG_Body_{sex}_Standard；网格改名 Body_{sex}
2. 体形骨（canonical 14 根）的全部直接子骨设 inherit_scale='NONE'
   —— 目的：让每根体形骨各管一段，缩放不沿骨架链传递。
   实测教训：默认继承下 scale pelvis 会让身高意外 +11.24%。
   体形骨：pelvis / spine_01..03 / thigh_l,r / shin_l,r / upperarm_l,r / lowerarm_l,r / clavicle_l,r
3. morph 通道（同名同序，服装必须一致）：
      index 0 = BS_Thin   瘦   （目标系数 0.86）
      index 1 = BS_Heavy  壮   （目标系数 1.16）
   本文件交付时两通道均为 0（= 标准体）；数值由 tools/3d/bodyshape/ 派生填入。
4. 身高不做 morph，用骨架 root 等比缩放（h ∈ [0.92, 1.08]）
5. 贴图相对路径 //../../textures/<名>（与共享贴图库一致）

单位：米制，1u = 1m。rest 为 T-pose，原点在世界 (0,0,0)。
"""

os.makedirs(DST, exist_ok=True)
report = []

for sex, src_file, src_obj in JOBS:
    src = f"{SRC}/{src_file}"
    print(f"\n{'='*70}\n{sex}  <-  {src_file}")
    bpy.ops.wm.open_mainfile(filepath=src)

    obj = bpy.data.objects[src_obj]
    arm = obj.find_armature()
    assert arm is not None, "找不到骨架"
    print(f"  源：{obj.name} {len(obj.data.vertices)} 顶点 / {len(obj.data.polygons)} 面；"
          f"骨架 {arm.name} {len(arm.data.bones)} 骨")

    # ① 改名
    obj.name = f"Body_{sex}"
    obj.data.name = f"Body_{sex}_mesh"
    arm.name = f"RIG_Body_{sex}_Standard"
    arm.data.name = f"RIG_Body_{sex}_Standard"

    # ② 体形骨的直接子骨 → inherit_scale = 'NONE'
    changed = []
    missing = [b for b in SHAPE_BONES if b not in arm.data.bones]
    for bn in SHAPE_BONES:
        if bn not in arm.data.bones:
            continue
        for child in arm.data.bones[bn].children:
            if child.inherit_scale != 'NONE':
                child.inherit_scale = 'NONE'
                changed.append(child.name)
    print(f"  体形骨 {len(SHAPE_BONES) - len(missing)}/{len(SHAPE_BONES)} 命中"
          + (f"；缺失 {missing}" if missing else ""))
    print(f"  设 inherit_scale='NONE' 的子骨 {len(set(changed))} 根：{sorted(set(changed))}")

    # ③ morph 占位通道（顺序即契约）
    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)
    for nm in ("BS_Thin", "BS_Heavy"):
        obj.shape_key_add(name=nm, from_mix=False)
    order = [k.name for k in obj.data.shape_keys.key_blocks]
    assert order == ["Basis", "BS_Thin", "BS_Heavy"], f"morph 顺序错：{order}"
    print(f"  morph 通道：{order}  (BS_Thin=0, BS_Heavy=1) ✅")

    # ④ 内嵌 README
    txt_name = "README_转换说明"
    if txt_name in bpy.data.texts:
        bpy.data.texts.remove(bpy.data.texts[txt_name])
    t = bpy.data.texts.new(txt_name)
    t.write(README_TMPL.format(sex=sex, Super="Female" if sex == "Female" else "Male"))

    # ⑤ 贴图相对路径自检
    danglers = []
    for img in bpy.data.images:
        if img.source == 'FILE':
            if not os.path.exists(bpy.path.abspath(img.filepath)):
                danglers.append(img.name)
    print(f"  贴图断链：{danglers if danglers else '无 ✅'}")

    out = f"{DST}/Body_{sex}_Standard.blend"
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"  已保存 → {out}  ({os.path.getsize(out)/1024:.0f} KB)")
    report.append({"sex": sex, "file": out, "verts": len(obj.data.vertices),
                   "tris": len(obj.data.loop_triangles) or len(obj.data.polygons),
                   "bones": len(arm.data.bones), "shape_keys": order,
                   "inherit_none_count": len(set(changed)), "danglers": danglers})

print(f"\n{'#'*70}\n# 汇总\n{'#'*70}")
for r in report:
    print(f"  {r['sex']:7s} {os.path.basename(r['file']):32s} {r['verts']:5d} 顶点  "
          f"{r['bones']} 骨  {r['inherit_none_count']:2d} 子骨断开继承  morph={r['shape_keys'][1:]}")
print("DONE")