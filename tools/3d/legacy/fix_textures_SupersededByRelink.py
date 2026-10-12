#!/usr/bin/env python3
"""fix_textures.py —— 由 Blender 执行：修补 UBC 源包 glTF 里 2 条失效贴图 URI

背景（源包缺陷，非转换器 bug）：
  UBC[Standard]/Base Characters/Godot - UE/Superhero_{Male,Female}_FullBody.gltf
  的 images[].uri 写成 `T_Eye_Normal_png.png` / `T_Hair_1_Normal_png.png`
  （多了 `_png` 中缀），而目录里实际只有 `T_Eye_Normal.png` / `T_Hair_1_Normal.png`。
  于是导入后这 2 张图的 Image datablock 无数据（size=(0,0)）、pack_all 报
  "Unable to pack file, source path ... not found"，.blend 不再自包含。

本脚本对受影响的 3 份 .blend 就地修补：按 `_png.png` -> `.png` 规则把 Image.filepath
指回真实文件 -> reload -> pack_all -> 重新保存，并原子重渲对应 preview PNG。
只写 download/ubc-blend/ 下的 3 份 .blend 与其 preview。

用法：
  "/Applications/Blender.app/Contents/MacOS/Blender" -b --factory-startup \
      --python download/ubc-blend/tools/fix_textures.py
"""
import bpy
import json
import os

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
OUT = ROOT + "/download/ubc-blend"
UBC = ROOT + "/tmp/ubc/Universal Base Characters[Standard]"

EXTRA = [
    UBC + "/Base Characters/Textures",
    UBC + "/Base Characters/Textures/Normals Unity - Godot",
    UBC + "/Base Characters/Godot - UE",
]

TARGETS = [
    {"blend": OUT + "/BaseCharacter_Superhero_Male.blend",
     "preview": OUT + "/preview/BaseCharacter_Superhero_Male.png", "w": 600, "h": 800},
    {"blend": OUT + "/BaseCharacter_Superhero_Female.blend",
     "preview": OUT + "/preview/BaseCharacter_Superhero_Female.png", "w": 600, "h": 800},
    {"blend": OUT + "/UBC_Standard_ALL.blend",
     "preview": OUT + "/preview/UBC_Standard_ALL.png", "w": 1600, "h": 1000},
]


def candidates(cur, base):
    out = []
    for base_dir in [os.path.dirname(cur)] + EXTRA:
        if base.endswith("_png.png"):
            out.append(os.path.join(base_dir, base[:-8] + ".png"))
        out.append(os.path.join(base_dir, base))
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def main():
    summary = []
    for t in TARGETS:
        bpy.ops.wm.open_mainfile(filepath=t["blend"])
        sc = bpy.context.scene
        fixed, missing, already = [], [], []
        for img in bpy.data.images:
            if img.name == 'Render Result' or img.packed_file is not None:
                continue
            cur = bpy.path.abspath(img.filepath) if img.filepath else ""
            if cur and os.path.exists(cur):
                already.append(img.name)
                continue
            base = os.path.basename(cur.replace("\\", "/"))
            hit = next((c for c in candidates(cur, base) if os.path.exists(c)), None)
            if hit:
                img.filepath = hit
                img.filepath_raw = hit
                try:
                    img.reload()
                except Exception as exc:  # noqa: BLE001
                    print("WARN reload %s: %s" % (img.name, exc))
                fixed.append({"image": img.name, "orig": cur, "now": hit,
                              "size": list(img.size)})
            else:
                missing.append({"image": img.name, "orig": cur})
        try:
            pack_result = str(bpy.ops.file.pack_all())
        except Exception as exc:  # noqa: BLE001
            pack_result = "ERROR " + str(exc)
        imgs = [i for i in bpy.data.images if i.name != 'Render Result']
        stats = {"total": len(imgs),
                 "packed": len([i for i in imgs if i.packed_file is not None]),
                 "size_zero": [i.name for i in imgs if tuple(i.size) == (0, 0)]}
        bpy.ops.wm.save_as_mainfile(filepath=t["blend"], compress=True)

        # 原子重渲预览：先写 .tmp.png，成功后再替换，避免坏图覆盖好图
        pv, tmp = t["preview"], t["preview"] + ".tmp.png"
        sc.render.resolution_x, sc.render.resolution_y = t["w"], t["h"]
        sc.render.image_settings.file_format = 'PNG'
        sc.render.filepath = tmp
        try:
            bpy.ops.render.render(write_still=True)
            os.replace(tmp, pv)
            preview = {"ok": True, "engine": sc.render.engine, "out": pv}
        except Exception as exc:  # noqa: BLE001
            if os.path.exists(tmp):
                os.remove(tmp)
            preview = {"ok": False, "error": str(exc), "out": pv}

        summary.append({"blend": t["blend"], "fixed": fixed, "missing": missing,
                        "unpacked_ok": already, "pack_all": pack_result,
                        "images": stats, "preview": preview,
                        "size_mb": round(os.path.getsize(t["blend"]) / 1048576, 2)})
        print("FIX_RESULT " + json.dumps(summary[-1], ensure_ascii=False), flush=True)
    print("FIX_DONE %d" % len(summary), flush=True)


main()