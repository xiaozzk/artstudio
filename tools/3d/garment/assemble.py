"""tools/3d/garment/assemble.py —— ④ 组装交付物：assets/3d/rig/garments/*.blend

按 SPEC §4.3 / §6 把传递完的中间件组装成正式交付物：
  · 网格：纯布料件（皮肤面已剥离），原点对齐世界 (0,0,0)（所有 object matrix 为单位矩阵）
  · 骨架：**共用标准体那副**（`RIG_Body_{sex}_Standard`，从 bodies/ 追加），不做"每件一份 rig"
  · 网格 parent + Armature 修改器都指向标准体骨架；顶点组名与骨架 65 骨逐字一致
  · morph：`Basis` + `BS_Thin`(0) + `BS_Heavy`(1)，与标准体同名同序（**脚本 assert**）
  · 贴图：相对路径 `//../../textures/...`（本目录与 bodies/ 同深度，路径仍可解析）
  · 内嵌中文 `README_转换说明`

用法
----
  Blender -b --factory-startup --python tools/3d/garment/assemble.py -- \
      [--in tmp/garment/work/morph] [--body-dir assets/3d/rig/bodies] \
      [--out assets/3d/rig/garments] [--report tmp/garment/work/assemble_report.json]
"""
import argparse
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

README_TMPL = """{outfit} —— 角色管线 v2 服装件（纯布料 + 体形 morph）
============================================================

来源：assets/3d/blend/outfits-gltf-per-asset/outfits/Outfit_{outfit}.blend
      （Quaternius "Modular Character Outfits - Fantasy"[Standard]，CC0 / 见源包 License）
加工：tools/3d/garment/ 三步链路（headless Blender {blender}）
契约：assets/3d/rig/SPEC.md v1.0（§4 服装契约）

处理链路
--------
① 剥离 strip_skin.py   按材质删除 `MI_Regular_*` 皮肤面
                         （服装长在「Regular」身体上，标准体是「Superhero」，
                          保留会与标准体双重叠模 —— SPEC D2）
② 贴合 autofit.py      骨空间 refit + 自动去穿模外推（最近点+法线，3 轮，留 0.8 cm）
                         验收用**独立**判据（6 方向射线奇偶）
③ 传递 transfer_morph.py 重心坐标 + 三角面标架（SPEC §4.2），把标准体的
                         BS_Thin / BS_Heavy 传到每件布料
④ 组装 assemble.py     换挂标准体骨架、改名、内嵌本说明

内容
----
· 网格对象：{parts}
  —— **纯布料**（皮肤面已剥离），原点在世界 (0,0,0)
· 骨架：`RIG_Body_{sex}_Standard`（**与标准体共用同一副**，65 骨，骨名+顺序一致）
· morph 通道（与标准体同名同序，索引即契约）：
      hint 0 = BS_Thin   瘦   （标准体侧目标系数 0.86）
      hint 1 = BS_Heavy  壮   （标准体侧目标系数 1.16）
  运行时权重 ∈ [0,1]，默认 0（= 标准体）。身高不走 morph，用骨架 root 等比缩放。
· 贴图：相对路径 `//../../textures/<名>`（共享贴图库，已去重）

注意
----
· 本文件**不含**标准体网格，也不含头部/眼睛；换装时与 bodies/Body_{sex}_Standard.blend 一起用。
· 服装是按「Regular」体形剪裁的，而标准体是「Superhero」——②那步外推是**事后修补**，
  会把被身体顶穿的布料压到体表外 0.8 cm，**代价是局部边长拉伸**（见 garment_manifest.json 的
  `stretch_after_autofit` 与 tools/3d/garment/README.md）。根治法见 SPEC/Lead FINDINGS §9.5 的 B 路线。
"""


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="assemble.py")
    ap.add_argument("--in", dest="ind", default=os.path.join(C.WORK, "morph"))
    ap.add_argument("--body-dir", default=C.BODIES)
    ap.add_argument("--out", dest="outd", default=C.GARMENTS)
    ap.add_argument("--report", default=os.path.join(C.WORK, "assemble_report.json"))
    ap.add_argument("--only", default=None)
    return ap.parse_args(argv)


def main():
    a = parse_args()
    os.makedirs(a.outd, exist_ok=True)
    report = []
    for outfit, sex in C.OUTFITS:
        if a.only and a.only != outfit:
            continue
        src = os.path.join(a.ind, f"Outfit_{outfit}.blend")
        C.log(f"\n{'='*96}\n[assemble] {outfit}   <- {C.rel(src)}")
        bpy.ops.wm.open_mainfile(filepath=src)

        # 丢掉旧的每件 rig
        old = [o for o in bpy.data.objects if o.type == 'ARMATURE']
        old_names = [o.name for o in old]
        for o in old:
            bpy.data.objects.remove(o, do_unlink=True)
        # 清掉源包带来的环境辅助体 / 相机 / 灯光（交付物只留布料 + 共用骨架）
        junk = []
        for n in list(bpy.data.objects.keys()):
            o = bpy.data.objects[n]
            if o.type in ('CAMERA', 'LIGHT') or C.is_helper(o):
                junk.append((n, o.type))
                bpy.data.objects.remove(o, do_unlink=True)
        C.log(f"  清理辅助对象：{junk}")
        meshes = sorted([o for o in bpy.data.objects if o.type == 'MESH'], key=lambda x: x.name)
        C.log(f"  移除旧 rig：{old_names}")

        # 追加标准体骨架（只追加骨架对象，不追加身体网格）
        arm_name = f"RIG_Body_{sex}_Standard"
        with bpy.data.libraries.load(os.path.join(a.body_dir, f"Body_{sex}_Standard.blend"),
                                     link=False) as (src_lib, dst_lib):
            dst_lib.objects = [arm_name]
        std_arm = [o for o in dst_lib.objects if o is not None][0]
        bpy.context.scene.collection.objects.link(std_arm)
        bpy.context.view_layer.update()
        C.log(f"  追加共用骨架：{std_arm.name}（{len(std_arm.data.bones)} 骨）")
        # ⚠ 实测坑：`bpy.data.libraries.load` 追加标准体骨架时，会**连带把标准体文件里的
        #    Icosphere（及可能的相机/灯光）一起拉进来**（它俩在源文件里有父子/依赖关系）。
        #    所以清理必须放在**加载之后**，否则交付物里会残留辅助对象。
        late_junk = []
        for n in list(bpy.data.objects.keys()):
            o = bpy.data.objects[n]
            if o is std_arm:
                continue
            if o.type in ('CAMERA', 'LIGHT') or C.is_helper(o):
                late_junk.append((n, o.type))
                bpy.data.objects.remove(o, do_unlink=True)
        if std_arm.parent is not None:
            C.log(f"  解除骨架 parent：{std_arm.parent.name}")
            pw = std_arm.matrix_world.copy()
            std_arm.parent = None
            std_arm.matrix_world = pw
        bpy.context.view_layer.update()
        if late_junk:
            C.log(f"  加载后清理（libraries.load 连带拉进来的）：{late_junk}")
        assert abs(std_arm.matrix_world.translation.length) < 1e-9, "骨架原点被移动了"

        # 顶点组名 ↔ 骨架骨名 逐字核对
        bones = {b.name for b in std_arm.data.bones}
        rec = {"outfit": outfit, "sex": sex, "src": C.rel(src), "armature": arm_name,
               "bones": len(std_arm.data.bones), "parts": [], "removed_rigs": old_names}

        for o in meshes:
            vg = {g.name for g in o.vertex_groups}
            unknown = sorted(vg - bones)
            missing = sorted(bones - vg)
            o.parent = std_arm
            o.parent_type = 'OBJECT'
            o.matrix_parent_inverse = std_arm.matrix_world.inverted()
            mods = [m for m in o.modifiers if m.type == 'ARMATURE']
            if not mods:
                mods = [o.modifiers.new("Armature", 'ARMATURE')]
            for m in mods:
                m.object = std_arm
                m.use_vertex_groups = True
            sk = [k.name for k in o.data.shape_keys.key_blocks] if o.data.shape_keys else None
            assert sk == C.MORPH_ORDER, f"{o.name} morph 顺序 {sk} != 契约 {C.MORPH_ORDER}"
            assert unknown == [], f"{o.name} 顶点组里有标准体没有的骨：{unknown}"
            assert o.matrix_world.translation.length < 1e-9, f"{o.name} 原点不在世界 0"
            rec["parts"].append({
                "part": o.name, "verts": len(o.data.vertices), "faces": len(o.data.polygons),
                "materials": [m.name if m else None for m in o.data.materials],
                "vertex_groups": len(vg), "unknown_groups": unknown,
                "bones_without_group": len(missing), "shape_keys": sk,
                "parent": o.parent.name,
                "modifiers": [(m.type, getattr(m, "object", None).name if getattr(m, "object", None) else None)
                              for m in o.modifiers],
                "origin_world": [round(v, 9) for v in o.matrix_world.translation]})
            C.log(f"  * {o.name:32s} v={len(o.data.vertices):5d} 面={len(o.data.polygons):5d} "
                  f"morph={sk[1:]} vg={len(vg)}(未知 {len(unknown)}) 材质={[m.name if m else None for m in o.data.materials]}")

        # 内嵌中文说明
        tn = "README_转换说明"
        if tn in bpy.data.texts:
            bpy.data.texts.remove(bpy.data.texts[tn])
        bpy.data.texts.new(tn).write(README_TMPL.format(
            outfit=outfit, sex=sex, blender=bpy.app.version_string,
            parts=", ".join(p["part"] for p in rec["parts"])))

        left = [o.name for o in bpy.data.objects
                if o.type in ('CAMERA', 'LIGHT') or C.is_helper(o)]
        assert left == [], f"交付物仍残留辅助对象：{left}"
        C.purge_orphans()
        rec["textures"] = sorted(i.name for i in bpy.data.images if i.source == 'FILE')
        rec["materials"] = sorted(m.name for m in bpy.data.materials)
        miss = C.texture_report()
        rec["texture_missing"] = miss
        assert not miss, f"{outfit} 贴图断链：{miss}"
        C.log(f"  贴图（相对路径已解析）：{rec['textures']}")
        C.log(f"  材质：{rec['materials']}")

        out = os.path.join(a.outd, f"{outfit}.blend")
        C.save_blend(out)
        rec["out"] = C.rel(out)
        rec["size_kb"] = round(os.path.getsize(out) / 1024)
        report.append(rec)

    os.makedirs(os.path.dirname(a.report), exist_ok=True)
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump({"tool": "assemble.py", "spec": "assets/3d/rig/SPEC.md v1.0 §4.3/§6",
                   "outfits": report}, f, ensure_ascii=False, indent=2)
    C.log(f"\n{'#'*96}\n# 组装汇总\n{'#'*96}")
    for r in report:
        C.log(f"  {r['outfit']:16s} → {r['out']:44s} {r['size_kb']:5d} KB  "
              f"{len(r['parts'])} 件  {r['bones']} 骨")
    C.log(f"\n报告 → {C.rel(a.report)}\nDONE")


main()