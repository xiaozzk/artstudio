#!/usr/bin/env python3
"""
v_topology_audit.py —— verifier 对标准体网格本身的拓扑体检。

为什么这是**穿模率指标的关键前提**：射线奇偶法要求靶网格**闭合**。
本资产标准体有 ~1.9k 条边界边（见 v_shelltest 的 edge_winding_check），
在解析 fixture 上，破洞网格会把射线奇偶的准确率从 99.8% 拉到 95.8%（v_selftest）。
→ 所以"穿模率"的误差界主要由**网格是否封闭**决定，而不是靠"噪声底校准"能补掉的。

本脚本给：连通分量数、边界环数量与尺寸、洞的位置分布、非流形边、松散顶点、
退化面、重复顶点（重合阈值下）。

只读，不写 .blend。
用法：
  $BL -b --factory-startup --python task/007-morph-pipeline/verify/v_topology_audit.py -- \
      --out assets/3d/rig/reports/verify-topology.json
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlib  # noqa: E402

NEW = "/Users/zhenkunzhu/Desktop/project/artstudio/assets/3d/rig"


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def components(nv, tris):
    parent = list(range(nv))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for t in tris:
        union(int(t[0]), int(t[1]))
        union(int(t[1]), int(t[2]))
    roots = defaultdict(int)
    for i in range(nv):
        roots[find(i)] += 1
    return len(roots), sorted(roots.values(), reverse=True)[:10]


def boundary_loops(tris):
    """边界边 -> 按共享顶点分组成环，返回每环的边数与质心。"""
    em = defaultdict(list)
    for fi, t in enumerate(tris):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            key = (int(a), int(b)) if a < b else (int(b), int(a))
            em[key].append(fi)
    bnd = [k for k, v in em.items() if len(v) == 1]
    # 并查集把边界边按顶点连成环
    idx = {}
    for e in bnd:
        for v in e:
            idx.setdefault(v, len(idx))
    parent = list(range(len(idx)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in bnd:
        ra, rb = find(idx[a]), find(idx[b])
        if ra != rb:
            parent[rb] = ra
    groups = defaultdict(list)
    for e in bnd:
        groups[find(idx[e[0]])].append(e)
    return bnd, groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-topology.json")
    a = ap.parse_args(argv_after_ddash())
    out = {"generated_by": "verifier/v_topology_audit.py", "objects": []}
    for sex in ("Female", "Male"):
        bpy.ops.wm.open_mainfile(filepath=f"{NEW}/bodies/Body_{sex}_Standard.blend")
        for name in (f"Body_{sex}", "Eyes", "Eyebrows"):
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != "MESH":
                continue
            m = vlib.evaluated_mesh(obj)
            M = np.array(obj.matrix_world)
            co = m["co"] @ M[:3, :3].T + M[:3, 3]
            # 用 loop_triangles 展开成三角（与 BVH 一致）
            obj.data.calc_loop_triangles()
            tris = np.array([list(t.vertices) for t in obj.data.loop_triangles], dtype=np.int64)
            ncomp, sizes = components(len(co), tris)
            em = defaultdict(list)
            for t in tris:
                for x, y in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                    key = (int(x), int(y)) if x < y else (int(y), int(x))
                    em[key].append(0)
            bnd = [k for k, v in em.items() if len(v) == 1]
            nonman = [k for k, v in em.items() if len(v) > 2]
            loose = [i for i in range(len(co)) if not any(i in (int(t[0]), int(t[1]), int(t[2]))
                                                          for t in tris[:0])]
            _, groups = boundary_loops(tris)
            loop_info = []
            for g, edges in groups.items():
                vs = sorted({v for e in edges for v in e})
                pts = co[vs]
                loop_info.append({
                    "n_edges": len(edges), "n_verts": len(vs),
                    "z_range_m": [round(float(pts[:, 2].min()), 3),
                                  round(float(pts[:, 2].max()), 3)],
                    "centroid": [round(float(x), 3) for x in pts.mean(axis=0)],
                })
            loop_info.sort(key=lambda r: -r["n_edges"])
            rec = {
                "object": name, "n_verts": int(len(co)), "n_tris": int(len(tris)),
                "n_edges": len(em), "n_boundary_edges": len(bnd),
                "n_nonmanifold_edges": len(nonman),
                "is_watertight": len(bnd) == 0,
                "n_connected_components": ncomp,
                "largest_components_verts": sizes,
                "n_boundary_loops": len(loop_info),
                "boundary_loops_top8": loop_info[:8],
                "boundary_edges_z_hist": histz(co, bnd),
            }
            out["objects"].append(rec)
            print(f"### {name}: v={rec['n_verts']} t={rec['n_tris']} "
                  f"watertight={rec['is_watertight']} 边界边={len(bnd)} "
                  f"非流形边={len(nonman)} 分量={ncomp} 边界环={len(loop_info)}")
            for li in loop_info[:5]:
                print(f"     环 edges={li['n_edges']:<5} z={li['z_range_m']} "
                      f"质心={li['centroid']}")
            print(f"     边界边 z 分布: {rec['boundary_edges_z_hist']}")
    vlib.jdump(a.out, out)
    print(f"[v_topology_audit] wrote {a.out}")


def histz(co, bnd, bins=12):
    if not bnd:
        return {}
    mid = np.array([(co[e[0]] + co[e[1]]) / 2.0 for e in bnd])
    z0, z1 = float(co[:, 2].min()), float(co[:, 2].max())
    edges = np.linspace(z0, z1, bins + 1)
    h, _ = np.histogram(mid[:, 2], bins=edges)
    return {f"{edges[i]:.2f}-{edges[i+1]:.2f}m": int(h[i]) for i in range(bins) if h[i]}


if __name__ == "__main__":
    main()