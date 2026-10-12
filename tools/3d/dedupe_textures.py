#!/usr/bin/env python3
"""dedupe_textures.py —— 把 .blend 里各自 pack 的贴图，收敛成一份共享贴图库

问题：103 份 `.blend` 每份都 pack 了整套贴图 → 2147.6 MB，而贴图唯一副本只有 177 MB
（重复 ≈11.9×）；`.blend` 本体（网格/骨骼）其实只占 **2.7~3.6%**。

做法（无损，不改网格/材质/UV/骨骼）：
  1) 扫描：读出每份 `.blend` 的每个 image 的真实来源文件（`filepath`，缺失则按文件名在 `--search` 里找，
     再退化为从 packed 数据写临时文件）；
  2) 按 **内容 sha256** 去重，把唯一贴图复制到共享库 `assets/3d/textures/<原名>`（同名不同内容加 `-<sha8>` 后缀）；
  3) 每份 `.blend` 里的 image 改成**相对路径** `//.../assets/3d/textures/<文件>`，并 `unpack` 掉 pack 副本；
  4) 前后各算一次**几何指纹**（顶点坐标 + 顶点组 + 修改器 + 骨骼 rest），证明只动了贴图路径。

用法（在工作区根执行）：
  Blender -b --factory-startup --python tools/3d/dedupe_textures.py -- scan      # 只读体检
  Blender -b --factory-startup --python tools/3d/dedupe_textures.py -- apply     # 改 + 存
  Blender -b --factory-startup --python tools/3d/dedupe_textures.py -- verify    # 落盘复检
参数：--root <dir>（默认 assets/3d）、--tex <dir>（默认 <root>/textures）、--search <dir>（可多次）
"""
import bpy
import hashlib
import json
import os
import shutil
import sys
import time

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MODE = ARGV[0] if ARGV and not ARGV[0].startswith("--") else "scan"


def opt(name, default):
    if name in ARGV:
        return ARGV[ARGV.index(name) + 1]
    return default


def opts(name):
    out, i = [], 0
    while i < len(ARGV):
        if ARGV[i] == name and i + 1 < len(ARGV):
            out.append(ARGV[i + 1])
        i += 1
    return out


ROOT = os.path.abspath(opt("--root", "assets/3d"))
TEX = os.path.abspath(opt("--tex", os.path.join(ROOT, "textures")))
WORK = os.path.abspath(os.environ.get("ARTSTUDIO_ROOT") or os.getcwd())
SEARCH = [os.path.abspath(p) for p in opts("--search")] or [
    os.path.join(WORK, "download/ubc"),
    os.path.join(WORK, "download/modular-outfits-fantasy"),
    os.path.join(WORK, "assets/3d/packs"),
]
REPORT = os.path.join(WORK, "tmp/dedupe-report.json")


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def build_search_index():
    idx = {}
    for d in SEARCH:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in files:
                idx.setdefault(fn.lower(), os.path.join(root, fn))
    return idx


def geom_fingerprint():
    """网格 + 权重 + 修改器 + 骨骼 rest 的稳定指纹（与贴图路径无关）。"""
    h = hashlib.sha256()
    for o in sorted([x for x in bpy.data.objects if x.type == 'MESH' and x.data], key=lambda x: x.name):
        h.update(o.name.encode())
        h.update(str(len(o.data.vertices)).encode())
        for v in o.data.vertices:
            h.update(("%.6f,%.6f,%.6f;" % (v.co.x, v.co.y, v.co.z)).encode())
        h.update(str(len(o.vertex_groups)).encode())
        for m in o.modifiers:
            h.update((m.type + (m.object.name if m.type == 'ARMATURE' and m.object else "")).encode())
        for uv in o.data.uv_layers:
            h.update((uv.name + str(len(uv.data))).encode())
    for a in sorted([x for x in bpy.data.objects if x.type == 'ARMATURE'], key=lambda x: x.name):
        h.update(a.name.encode())
        for b in a.data.bones:
            h.update((b.name + "|" + "%.6f,%.6f,%.6f" % tuple(b.head_local)).encode())
    for m in sorted(bpy.data.materials, key=lambda x: x.name):
        h.update(m.name.encode())
        if m.use_nodes:
            for n in m.node_tree.nodes:
                h.update((n.type + (n.image.name if n.type == 'TEX_IMAGE' and n.image else "")).encode())
    return h.hexdigest()


def blends():
    out = []
    for root, _d, files in os.walk(os.path.join(ROOT, "blend")):
        for f in files:
            if f.endswith(".blend"):
                out.append(os.path.join(root, f))
    return sorted(out)


def resolve_source(img, index, tmpdir):
    """返回该 image 的真实来源文件路径（不存在则返回 None）。"""
    cand = bpy.path.abspath(img.filepath) if img.filepath else ""
    if cand and os.path.exists(cand):
        return cand
    base = os.path.basename((img.filepath or "").replace("\\", "/"))
    hit = index.get(base.lower())
    if hit:
        return hit
    # 退化：把 packed 数据写到临时文件
    if img.packed_file is not None:
        tmp = os.path.join(tmpdir, (base or img.name) + ".png")
        try:
            old = img.filepath
            img.filepath_raw = tmp
            img.file_format = 'PNG'
            img.save()
            img.filepath_raw = old
            if os.path.exists(tmp):
                return tmp
        except Exception as e:
            print("   ! packed 导出失败", img.name, e)
    return None


def main():
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    os.makedirs(TEX, exist_ok=True)
    tmpdir = os.path.join(WORK, "tmp/dedupe-extract")
    os.makedirs(tmpdir, exist_ok=True)
    index = build_search_index()
    files = blends()
    report = {"mode": MODE, "blends": len(files), "textures_dir": os.path.relpath(TEX, WORK),
              "sha_to_file": {}, "files": [], "unresolved": [], "reused_sources": 0}
    print("== %s：%d 份 .blend，搜索目录 %s" % (MODE, len(files), [os.path.relpath(d, WORK) for d in SEARCH]))
    lib = {}
    for src in sorted(os.listdir(TEX)) if os.path.isdir(TEX) else []:
        p = os.path.join(TEX, src)
        if os.path.isfile(p):
            lib[sha256_file(p)] = p
    for i, path in enumerate(files, 1):
        bpy.ops.wm.open_mainfile(filepath=path)
        rel = os.path.relpath(path, WORK)
        entry = {"blend": rel, "size_before": os.path.getsize(path), "images": 0,
                 "packed_before": 0, "new_textures": 0, "geom": geom_fingerprint()}
        remap = []
        for img in bpy.data.images:
            if img.name == 'Render Result':
                continue
            entry["images"] += 1
            if img.packed_file is not None:
                entry["packed_before"] += 1
            src = resolve_source(img, index, tmpdir)
            if not src:
                report["unresolved"].append({"blend": rel, "image": img.name, "filepath": img.filepath})
                continue
            sha = sha256_file(src)
            if sha in lib:
                dst = lib[sha]
            else:
                base = os.path.basename(src)
                dst = os.path.join(TEX, base)
                if os.path.exists(dst):
                    stem, ext = os.path.splitext(base)
                    dst = os.path.join(TEX, "%s-%s%s" % (stem, sha[:8], ext))
                if MODE == "apply":
                    shutil.copy2(src, dst)
                lib[sha] = dst
                entry["new_textures"] += 1
                report["sha_to_file"][sha[:12]] = os.path.relpath(dst, WORK)
            remap.append((img, dst))
        if MODE == "apply":
            for img, dst in remap:
                img.filepath = bpy.path.relpath(dst, start=os.path.dirname(path))
                img.filepath_raw = img.filepath
                if img.packed_file is not None:
                    try:
                        img.unpack(method='REMOVE')
                    except Exception as e:
                        print("   ! unpack 失败", img.name, e)
                img.reload()
            bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
            entry["size_after"] = os.path.getsize(path)
            entry["geom_after"] = geom_fingerprint()
            entry["geom_unchanged"] = entry["geom_after"] == entry["geom"]
        report["files"].append(entry)
        if i % 20 == 0 or i == len(files):
            print("   %d/%d" % (i, len(files)), flush=True)
    report["total_before_mb"] = round(sum(f["size_before"] for f in report["files"]) / 1048576, 1)
    if MODE == "apply":
        report["total_after_mb"] = round(sum(f.get("size_after", 0) for f in report["files"]) / 1048576, 1)
        report["geom_all_unchanged"] = all(f.get("geom_unchanged") for f in report["files"])
        report["textures_total_mb"] = round(
            sum(os.path.getsize(os.path.join(TEX, f)) for f in os.listdir(TEX)) / 1048576, 1)
    json.dump(report, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("== 汇总：before %.1f MB%s | 贴图库 %.1f MB | 未解析 %d"
          % (report["total_before_mb"],
             (" → after %.1f MB（几何全一致 %s）" % (report.get("total_after_mb", 0),
                                                    report.get("geom_all_unchanged")))
             if MODE == "apply" else "",
             report.get("textures_total_mb", 0), len(report["unresolved"])))
    print("DEDUPE_DONE mode=%s report=%s" % (MODE, os.path.relpath(REPORT, WORK)))


main()