#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨成员 morph digest 约定 —— 让两个独立实现能互相复算同一份数据。

**背景**：`bodyshape`（标准体）与 `garment`（B2 角色）各自独立实现了"morph 数据指纹"。
各自的报告要能互相复算，就必须把**打包口径**钉死成可执行的东西 —— 否则"指纹一致"只是一句话。

**约定（canonical morph digest）**
```
对某个 .blend：
  1. 取所有【带 shape key】的 MESH 对象，按对象名**字典序排序**（不是 Blender 的创建顺序）
  2. 对每个目标 shape key K（如 BS_Thin）：
       顺序遍历每件网格的顶点 i = 0..N-1（按 mesh 顶点索引）
       每个顶点取 `key_blocks[K].data[i].co` 的**绝对坐标**（⚠ 不是相对 Basis 的偏移）
       按 struct.pack("<3f", x, y, z) 追加进哈希
  3. digest = sha256(字节流)，报告里通常取十六进制前 16 位
```
⚠ **两个易错点**（本工具都验过）：
  * **绝对坐标 vs 偏移**：用 `co` 相减（delta）会得到**完全不同**的 digest。
    实测 Female_Ranger `BS_Thin`：abs = `e5346f1cf12a6dbe`，delta = `4176e0edb5713f1f`。必须写清楚。
  * **件序必须先排序**：按 `bpy.data.objects` 遍历顺序在不同文件/不同 Blender 版本下可能不同。

**互操作已验证（2026-10-13）**：用本工具从 `assets/3d/rig/garments/*.blend` 复算 `garment` 公布的
4 套 × 2 档 digest，**8/8 逐位相同**。→ 两套独立实现口径一致，跨成员对账可信。

另附一项**廉价护栏**：同档的 `nonzero_vertex_count`（有多少顶点的偏移真的非零）。
全 0 = "空 morph"，会让任何"通过"的判定变成假 PASS。

用法：
  Blender -b --factory-startup --python tools/3d/bodyshape/check_digest_convention.py -- \\
      [--glob "assets/3d/rig/garments/*.blend"] [--expect <json>] [--json <out>] [--quiet]
  python3 tools/3d/bodyshape/check_digest_convention.py --help     # 不开 Blender

`--expect` 的 JSON 形状（缺项不报错，只校验提供的）：
  {"<file stem>": {"BS_Thin": "e5346f1cf12a6dbe", "BS_Heavy": "6d87cac343fd772d"}, ...}
退出码：0 = 全部匹配（或未提供 --expect），1 = 有不匹配。
"""
from __future__ import annotations

import argparse
import glob as globmod
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

try:
    import bpy  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False

DEFAULT_GLOB = os.path.join(ROOT, "assets", "3d", "rig", "garments", "*.blend")
SKIP_KEYS = ("Basis",)


def digest_of(objs, key_name, mode="abs"):
    """canonical morph digest。`mode='abs'` 是约定口径；`'delta'` 只用于对照演示。"""
    h = hashlib.sha256()
    n_vert = 0
    n_nonzero = 0
    for o in objs:
        kb = o.data.shape_keys.key_blocks.get(key_name)
        if kb is None:
            continue
        basis = o.data.shape_keys.key_blocks.get("Basis")
        for i in range(len(o.data.vertices)):
            c = kb.data[i].co
            if mode == "delta" and basis is not None:
                b = basis.data[i].co
                c = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
            h.update(struct.pack("<3f", c[0], c[1], c[2]))
            n_vert += 1
            if mode == "abs" and basis is not None:
                b = basis.data[i].co
                if (abs(c[0] - b[0]) + abs(c[1] - b[1]) + abs(c[2] - b[2])) > 1e-9:
                    n_nonzero += 1
    return h.hexdigest(), n_vert, n_nonzero


def process(path):
    bpy.ops.wm.open_mainfile(filepath=path)
    objs = sorted([o for o in bpy.data.objects if o.type == 'MESH' and o.data.shape_keys],
                  key=lambda o: o.name)          # ★ 必须先按名排序（约定第 1 条）
    if not objs:
        return None
    key_names = sorted({k.name for o in objs for k in o.data.shape_keys.key_blocks
                        if k.name not in SKIP_KEYS})
    tiers = {}
    for kn in key_names:
        full, nv, nz = digest_of(objs, kn, "abs")
        # ★ 负对照：同一份数据用"相对 Basis 的偏移"打包会得到**完全不同**的 digest。
        #   把它一起记下来 —— 以后谁的口径算错了，一比对就知道是**口径问题**而不是数据问题。
        d_full, _, _ = digest_of(objs, kn, "delta")
        tiers[kn] = {"sha256": full, "digest16": full[:16],
                     "vertex_total": nv, "nonzero_vertex_count": nz,
                     "empty_morph": nz == 0,
                     "negative_control": {
                         "wrong_convention": "相对 Basis 的偏移 (co − basis.co)",
                         "digest16": d_full[:16],
                         "differs_from_canonical": d_full != full,
                     }}
    return {
        "file": os.path.relpath(path, ROOT),
        "stem": os.path.splitext(os.path.basename(path))[0],
        "mesh_count": len(objs),
        "piece_names": [o.name for o in objs],
        "vertex_total": int(sum(len(o.data.vertices) for o in objs)),
        "key_names": key_names,
        "tiers": tiers,
    }


def main():
    ap = argparse.ArgumentParser(
        prog="check_digest_convention.py",
        description="canonical morph digest 跨成员复算（约定见文件头 docstring）",
        epilog='例：Blender -b --factory-startup --python tools/3d/bodyshape/check_digest_convention.py -- '
               '--glob "assets/3d/rig/garments/*.blend"')
    ap.add_argument("--glob", default=DEFAULT_GLOB, help="要复算的 .blend（支持通配，需加引号）")
    ap.add_argument("--expect", default=None, help="期望值 JSON（见文件头形状）")
    ap.add_argument("--json", default=None, help="把结果写成 JSON")
    ap.add_argument("--quiet", action="store_true")
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    if not HAS_BPY:
        if not argv or any(a in ("-h", "--help") for a in argv):
            ap.print_help()
            return 0
        ap.error("需要 bpy —— 请在 Blender headless 下运行")
    args = ap.parse_args(argv)

    paths = sorted(globmod.glob(args.glob))
    if not paths:
        raise SystemExit(f"没匹配到文件：{args.glob}")
    expect = json.load(open(args.expect, encoding="utf-8")) if args.expect else {}
    print(f"# check_digest_convention.py  Blender {bpy.app.version_string}")
    print(f"  口径：按件名排序 → 逐顶点 key_blocks[K].data[i].co 的**绝对坐标** → struct.pack('<3f')")
    print(f"  文件：{len(paths)} 份\n")

    rows, n_fail, n_check = [], 0, 0
    for p in paths:
        r = process(p)
        if r is None:
            print(f"  [skip] {os.path.relpath(p, ROOT)}：没有带 shape key 的网格")
            continue
        exp = expect.get(r["stem"], {})
        line = []
        for kn, v in r["tiers"].items():
            tag = ""
            if kn in exp:
                n_check += 1
                ok = (v["digest16"] == exp[kn])
                if not ok:
                    n_fail += 1
                tag = f" [{'✅' if ok else '❌ 期望 ' + exp[kn]}]"
            line.append(f"{kn}={v['digest16']}{tag}")
            if v["empty_morph"]:
                line.append(f"⚠{kn} 是空 morph(全 0)")
            if not v["negative_control"]["differs_from_canonical"]:
                line.append(f"⚠{kn} 负对照与正口径相同（该 shape key 可能是常量！）")
        print(f"  {r['stem']:22s} {r['mesh_count']:2d} 件 / {r['vertex_total']:6d} 顶点  "
              + "  ".join(line))
        rows.append(r)

    print(f"\n{'#' * 74}")
    if n_check:
        print(f"# 期望值校验：{n_check - n_fail}/{n_check} 匹配  "
              f"{'✅ 跨成员口径一致' if n_fail == 0 else f'❌ {n_fail} 项不匹配'}")
    else:
        print("# 未提供 --expect，仅打印 digest")
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"schema": "morph-digest-canonical",
                       "convention": "pieces sorted by name; key_blocks[K].data[i].co **absolute** (not delta vs Basis); "
                                     "struct.pack('<3f')",
                       "blender_version": bpy.app.version_string,
                       "files": rows}, f, ensure_ascii=False, indent=2)
        print(f"  → {args.json}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())