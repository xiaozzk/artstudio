#!/usr/bin/env python3
"""make_manifest.py —— 为「不入库的大件」生成可校验清单（sha256 + 体积）

动机：`assets/3d/blend/`（103 份 .blend，约 2.1 GB）与 `assets/3d/packs/`（源包 zip）**不入库**
（见 `.gitignore`），仓库只留脚本 + 预览 + 报告。清单把"能不能复现"落成可验证的证据：
重跑一遍转换后，用本清单逐文件比 sha256 即可证明产物一致。

用法：
  python3 tools/3d/make_manifest.py                                  # 默认扫 assets/3d
  python3 tools/3d/make_manifest.py --root assets/3d --out assets/3d/manifests/blend-manifest.json
"""
import argparse
import glob
import hashlib
import json
import os
import time

PACK_SOURCES = {
    "Universal Base Characters[Standard].zip":
        "https://quaternius.com/packs/universalbasecharacters.html",
    "Modular Character Outfits - Fantasy[Standard].zip":
        "https://quaternius.com/packs/modularcharacteroutfitsfantasy.html",
}


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def collect(root, patterns):
    files = []
    for pat in patterns:
        files += glob.glob(os.path.join(root, pat), recursive=True)
    return sorted(set(files))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="assets/3d")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    out = os.path.abspath(args.out or os.path.join(root, "manifests/blend-manifest.json"))
    os.makedirs(os.path.dirname(out), exist_ok=True)

    blends = collect(root, ["blend/**/*.blend"])
    packs = collect(root, ["packs/*.zip"])
    textures = collect(root, ["textures/*.png", "textures/**/*.png"])
    entries = []
    for p in blends + packs + textures:
        st = os.stat(p)
        entries.append({
            "path": os.path.relpath(p, os.path.dirname(root.rstrip("/"))),
            "bytes": st.st_size,
            "mb": round(st.st_size / 1048576, 2),
            "sha256": sha256(p),
            "kind": ("blend" if p.endswith(".blend") else "pack" if p.endswith(".zip") else "texture"),
            "source": PACK_SOURCES.get(os.path.basename(p)) if p.endswith(".zip") else None,
        })
    # 合并已有校验报告里的分片统计（如果存在），便于一眼看规模
    shard_totals = {}
    for rep in glob.glob(os.path.join(root, "reports", "lead-check-report-*.json")):
        try:
            d = json.load(open(rep, encoding="utf-8"))
            shard_totals = {k: {"count": v["count"], "ok": v["ok"], "tris_total": v.get("tris_total")}
                            for k, v in d.get("by_scope", {}).items()}
        except Exception:
            pass
    doc = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": os.path.relpath(root, os.getcwd()),
        "note": "blend/ 只存网格 + 指向共享 textures/ 的相对路径（2026-10 去重改造：2.1 GB → 44 MB）；"
                "packs/ 不入库（官方页可重下，见 source 列）。本清单入库，用于重出后逐文件校验；"
                "校验命令见 assets/3d/README.md「清单与复现」。",
        "count": len(entries),
        "blend_count": len(blends),
        "pack_count": len(packs),
        "texture_count": len(textures),
        "total_mb": round(sum(e["bytes"] for e in entries) / 1048576, 1),
        "shard_totals": shard_totals,
        "entries": entries,
    }
    json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("manifest=%s files=%d (blend %d / pack %d) total=%.1f MB"
          % (out, doc["count"], doc["blend_count"], doc["pack_count"], doc["total_mb"]))


if __name__ == "__main__":
    main()