#!/usr/bin/env python3
"""run_check.py —— 批量 .blend 终验驱动：收集 → Blender 逐份断言 → 汇总报告 + 联系表

用法（在工作区根执行）：
  python3 tools/3d/run_check.py                        # 默认扫 assets/3d/blend/ 下 5 个分片
  python3 tools/3d/run_check.py --globs 'download/ubc-blend/*.blend'
  python3 tools/3d/run_check.py --out tmp/my-check

产出（默认写到 tmp/3d-check/，不进库）：
  manifest.json / check-raw.log / check-report.json / contact_<scope>.png

断言口径来自 check_blends.py：
  · A 蒙皮件：≥1 个 ARMATURE 且 bones==65；每个 mesh 有 ARMATURE modifier + vertex_groups>0
  · B 静态件：源资产本身就无骨架（Origin at 0 发型、*_ALL* 混装件、含 origin0 的目录）
              → 无 armature modifier 且 vertex_groups==0 才算合格
  · 共同：image 全部 packed 且 size≠(0,0)；辅助集合 glTF_not_exported 不渲染；材质含贴图节点
"""
import argparse
import glob
import json
import os
import subprocess
import sys

DEFAULT_SCOPES = {
    "base-characters": "assets/3d/blend/base-characters/*.blend",
    "outfits-gltf": "assets/3d/blend/outfits-gltf/*.blend",
    "outfits-gltf-per-asset": "assets/3d/blend/outfits-gltf-per-asset/**/*.blend",
    "outfits-fbx": "assets/3d/blend/outfits-fbx/**/*.blend",
    "tryon": "assets/3d/blend/tryon/*.blend",
}
DEFAULT_PREVIEWS = {
    "base-characters": "assets/3d/blend/base-characters/preview",
    "outfits-gltf-per-asset": "assets/3d/blend/outfits-gltf-per-asset/preview",
    "outfits-fbx": "assets/3d/blend/outfits-fbx/preview",
    "tryon": "assets/3d/blend/tryon/preview",
}
BLENDER = os.environ.get("BLENDER_BIN", "/Applications/Blender.app/Contents/MacOS/Blender")


def contact_sheet(scope, pngs, out_path, cols=8, cell=(150, 200)):
    from PIL import Image, ImageDraw
    pngs = sorted(pngs)
    if not pngs:
        return None
    rows = (len(pngs) + cols - 1) // cols
    label_h = 16
    sheet = Image.new("RGB", (cols * cell[0], rows * (cell[1] + label_h)), (22, 23, 27))
    draw = ImageDraw.Draw(sheet)
    for i, p in enumerate(pngs):
        r, c = divmod(i, cols)
        try:
            im = Image.open(p).convert("RGB")
            im.thumbnail(cell)
        except Exception:
            continue
        sheet.paste(im, (c * cell[0] + (cell[0] - im.width) // 2,
                         r * (cell[1] + label_h) + (cell[1] - im.height) // 2))
        name = os.path.basename(p)[:-4]
        draw.text((c * cell[0] + 3, r * (cell[1] + label_h) + cell[1] + 2),
                  name if len(name) <= 24 else name[:22] + "..", fill=(210, 210, 120))
    sheet.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("--out", default=None, help="报告目录（默认 <root>/tmp/3d-check）")
    ap.add_argument("--globs", nargs="*", default=None, help="自定义 .blend glob（相对 root），替代默认分片")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    out = os.path.abspath(args.out or os.path.join(root, "tmp/3d-check"))
    os.makedirs(out, exist_ok=True)

    scopes = ({s: [p] for s, p in zip(["custom"], [args.globs])} if args.globs
              else {k: [v] for k, v in DEFAULT_SCOPES.items()})
    if args.globs:
        scopes = {"custom": list(args.globs)}

    found = {}
    for scope, pats in scopes.items():
        files = []
        for p in pats:
            files += glob.glob(os.path.join(root, p), recursive=True)
        found[scope] = sorted(set(files))
    all_files = sorted({f for v in found.values() for f in v})
    print("收集到 .blend：")
    for s, v in found.items():
        print("  %-24s %3d 份" % (s, len(v)))
    print("  合计 %d 份" % len(all_files))
    if not all_files:
        return 1

    manifest = os.path.join(out, "manifest.json")
    json.dump({"blends": all_files}, open(manifest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    checker = os.path.join(root, "tools/3d/check_blends.py")
    proc = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", checker, "--", manifest],
                          capture_output=True, text=True, cwd=root)
    open(os.path.join(out, "check-raw.log"), "w", encoding="utf-8").write(
        proc.stdout + "\n==== STDERR ====\n" + proc.stderr)
    results = [json.loads(l[len("ACCEPT_RESULT "):]) for l in proc.stdout.splitlines()
               if l.startswith("ACCEPT_RESULT ")]
    by_path = {r["path"]: r for r in results}
    report = {"total": len(all_files), "checked": len(results),
              "ok": len([r for r in results if r.get("ok")]),
              "failed": [r for r in results if not r.get("ok")],
              "by_scope": {}}
    for scope, files in found.items():
        rs = [by_path[f] for f in files if f in by_path]
        report["by_scope"][scope] = {
            "count": len(files), "ok": len([r for r in rs if r.get("ok")]),
            "tris_total": sum(r.get("tris", 0) for r in rs),
            "size_mb_total": round(sum(r.get("size_mb", 0) for r in rs), 1),
        }
    sheets = {}
    for scope, rel in DEFAULT_PREVIEWS.items():
        d = os.path.join(root, rel)
        pngs = [p for p in glob.glob(os.path.join(d, "*.png"), recursive=True)
                if not os.path.basename(p).startswith("_")]
        dest = os.path.join(out, "contact_%s.png" % scope)
        if contact_sheet(scope, pngs, dest):
            sheets[scope] = {"sheet": dest, "previews": len(pngs)}
    report["contact_sheets"] = sheets
    json.dump(report, open(os.path.join(out, "check-report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n验收：%d/%d 通过" % (report["ok"], report["total"]))
    for s, d in report["by_scope"].items():
        print("  %-24s %3d 份 | ok %3d | tris %8d | %8.1f MB"
              % (s, d["count"], d["ok"], d["tris_total"], d["size_mb_total"]))
    for r in report["failed"]:
        print("  ✗", r["path"], r.get("error") or r.get("checks"))
    return 0 if not report["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())