"""tryon_fix_readme.py —— 修正试穿件内嵌说明里的一条错误论断（只改文本块，不碰几何/材质/贴图）

背景：原稿写「两套 rig 差异只在 upperarm_l / thigh_l」——那是 Lead 只抽查 12 根骨的**平移**
得出的错误结论。独立验收实测：
  · 男侧 58/65 关节不一致（手臂链含 clavicle 旋转 2.55°、手指/拇指最高 13.37°、
    整条腿链 X 偏移 23.7mm、上臂/前臂/手 20–23mm）；
  · 女侧 65/65 完全一致（差 = 0）；
  · 两侧都相同的只有 root/pelvis/spine_01..03/neck_01/Head 这 7 根。
结论不变：Head / neck_01 世界矩阵差 = 0，所以头部直接绑到服装 rig 位置正确。

用法：
  Blender -b --factory-startup --python tryon_fix_readme.py -- check   # 打印几何/贴图哈希
  Blender -b --factory-startup --python tryon_fix_readme.py -- fix     # 改写文本块并保存
"""
import bpy
import hashlib
import json
import os
import sys

ROOT = os.environ.get("ARTSTUDIO_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.environ.get("BLEND_DIR") or (ROOT + "/assets/3d/blend/tryon")
FILES = sorted(f for f in os.listdir(OUT) if f.endswith(".blend")) if os.path.isdir(OUT) else []
MODE = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "check"

NEW_TEXT = """试穿合成：{title}
==============================================

来源：Modular Character Outfits - Fantasy[Standard] 的 {outfit} 套装
      + Universal Base Characters[Standard] 的 {head} 头部
      + 发型 {hair}

做法：按 Readme「服装只需头部」裁剪 Base Characters 身体 mesh —— 只保留顶点组
      Head / neck_01 权重和 > 0.5 的顶点（实测 7281→1562 / 7376→1644），其余删除；
      再把头部 3 个 mesh（body 残件 + Eyes + Eyebrows）与发型重新挂到**服装自带的 rig** 上
      （不删服装骨架、不复用 UBC 骨架），因此本文件只有一根 65 骨 rig，可直接做动画。

两套骨架的真实差异（2026-10-12 依据独立验收实测更正，原稿「差异只在 upperarm_l / thigh_l」有误）：
  · 男侧 58/65 关节不一致：手臂链（含 clavicle 旋转 2.55°）、手指/拇指最高旋转 13.37°、
    整条腿链 X 偏移 23.7mm、上臂/前臂/手 20–23mm；
  · 女侧 65/65 完全一致（差 = 0）；
  · 两侧完全一致的只有 root / pelvis / spine_01..03 / neck_01 / Head 这 7 根。
  关键点：Head 与 neck_01 的世界矩阵差 = 0（局部平移 0.08285235 / 0.21509314 两侧逐位相同），
  所以头部 mesh 直接绑到服装 rig 上位置正确；其余差异落在服装件自己不涉及的骨头上，
  且服装件使用的是服装自带 rig，不受影响。
  服装是 Regular 体型，UBC 标准版只有 Superhero 体型 —— 颈/肩处细小差异属上游体型差异。

许可：两包均为 CC0 1.0（商用免署名），作者 Quaternius。
注意：本文件是 glTF→Blender 反向生成 + 脚本合成的结果，不是作者原始 .blend。
      本说明文本于验收后更正过一次（几何/材质/贴图未变）。
"""


def geom_hash():
    """几何 + 贴图内容的稳定哈希（与文本块无关）。"""
    h = hashlib.sha256()
    for o in sorted([x for x in bpy.data.objects if x.type == 'MESH' and x.data], key=lambda x: x.name):
        h.update(o.name.encode())
        h.update(str(len(o.data.vertices)).encode())
        for v in o.data.vertices:
            h.update(("%.6f,%.6f,%.6f;" % (v.co.x, v.co.y, v.co.z)).encode())
        h.update(str(len(o.vertex_groups)).encode())
        for m in o.modifiers:
            h.update((m.type + (m.object.name if m.type == 'ARMATURE' and m.object else "")).encode())
    for i in sorted([x for x in bpy.data.images if x.name != 'Render Result'], key=lambda x: x.name):
        h.update(i.name.encode())
        h.update(str(tuple(i.size)).encode())
        h.update(str(i.packed_file.size if i.packed_file else -1).encode())
    for a in sorted([x for x in bpy.data.objects if x.type == 'ARMATURE'], key=lambda x: x.name):
        h.update(a.name.encode())
        for b in a.data.bones:
            h.update((b.name + "|" + "%.6f,%.6f,%.6f" % tuple(b.head_local)).encode())
    return h.hexdigest()


report = {}
for fn in FILES:
    path = os.path.join(OUT, fn)
    bpy.ops.wm.open_mainfile(filepath=path)
    before = geom_hash()
    entry = {"geom_sha256": before,
             "texts": [t.name for t in bpy.data.texts],
             "text_len": {t.name: len(t.as_string()) for t in bpy.data.texts}}
    if MODE == "fix":
        title = fn[:-6]
        job = {"Male_Peasant": ("Male_Peasant", "Superhero_Male_FullBody", "Hair_SimpleParted"),
               "Female_Peasant": ("Female_Peasant", "Superhero_Female_FullBody", "Hair_Long"),
               "Male_Ranger": ("Male_Ranger", "Superhero_Male_FullBody", "（Ranger 有兜帽，未加发型）"),
               "Female_Ranger": ("Female_Ranger", "Superhero_Female_FullBody", "（Ranger 有兜帽，未加发型）")}
        for key, (outfit, head, hair) in job.items():
            if key in title:
                txt = NEW_TEXT.format(title=title, outfit=outfit, head=head, hair=hair)
                break
        old = bpy.data.texts.get("README_试穿说明")
        if old:
            new = bpy.data.texts.new("README_试穿说明_new")
            new.write(txt)
            bpy.data.texts.remove(old)
            new.name = "README_试穿说明"
        else:
            t = bpy.data.texts.new("README_试穿说明")
            t.write(txt)
        bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
        bpy.ops.wm.open_mainfile(filepath=path)
        entry["geom_sha256_after"] = geom_hash()
        entry["geom_unchanged"] = entry["geom_sha256_after"] == before
        entry["text_len_after"] = {t.name: len(t.as_string()) for t in bpy.data.texts}
    report[fn] = entry
    print("TRYONFIX " + json.dumps({fn: entry}, ensure_ascii=False), flush=True)

with open(os.path.join(OUT, "readme-fix-report.json"), "w", encoding="utf-8") as fh:
    json.dump({"mode": MODE, "files": report}, fh, ensure_ascii=False, indent=1)
print("TRYONFIX_DONE mode=" + MODE)