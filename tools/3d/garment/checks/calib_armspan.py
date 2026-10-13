"""标定"臂展"判据的两种失效模式（verifier 报 −54.53%/+138.86% 与 ±0.46%，我自己复测确认）。

A 正确：NONE 隔离 + manifest 的 bones_applied（含 along）
B 漏 NONE 隔离：全 FULL + bones_applied
C 漏 along 项：NONE 隔离 + 只用 (s,1,s)（忽略 along_axis_response）
"""
import json, os, sys
import bpy
sys.path.insert(0, "tools/3d/garment")
import common as C

SHAPE = C.SHAPE_BONES
man = json.load(open("assets/3d/rig/manifests/bodyshape_manifest.json"))
tiers = {t["shape_key"]: t for t in man["tiers"]}
resp = {k: v for k, v in man["delta_response"].items() if not k.startswith("_")}


def resp_of(bn):
    for k, v in resp.items():
        if bn.startswith(k):
            return v
    return 1.0


def span(meshes):
    xs = [p.x for o in meshes for p in _ev(o)]
    return max(xs) - min(xs)


def _ev(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


print(f"{'模式':34s} {'BS_Thin':>10s} {'BS_Heavy':>10s}  期望")
for mode in ("A_正确(NONE+along)", "B_漏NONE隔离", "C_漏along项"):
    bpy.ops.wm.open_mainfile(filepath="assets/3d/blend/tryon/TryOn_Female_Ranger.blend")
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    meshes = sorted([o for o in bpy.data.objects
                     if o.type == 'MESH' and not C.is_helper(o)], key=lambda x: x.name)
    # 只加通道（不烘，仅量姿态下的几何）
    for o in meshes:
        if o.data.shape_keys is None:
            o.shape_key_add(name="Basis", from_mix=False)
    if mode != "B_漏NONE隔离":
        for bn in SHAPE:
            if bn in arm.data.bones:
                for ch in arm.data.bones[bn].children:
                    ch.inherit_scale = 'NONE'
    base = span(meshes)
    out = {}
    for tier, coef in (("BS_Thin", 0.84), ("BS_Heavy", 1.21)):
        for pb in arm.pose.bones:
            pb.scale = (1.0, 1.0, 1.0)
        ba = tiers[tier]["bones_applied"]
        for bn in SHAPE:
            if bn not in arm.pose.bones:
                continue
            if mode == "C_漏along项":
                s = 1.0 + (coef - 1.0) * resp_of(bn)
                arm.pose.bones[bn].scale = (s, 1.0, s)
            else:
                arm.pose.bones[bn].scale = ba[bn]
        bpy.context.view_layer.update()
        out[tier] = 100 * (span(meshes) / base - 1.0)
    exp = {"A_正确(NONE+along)": "≈ −1.7 / +2.3", "B_漏NONE隔离": "≈ −55 / +139",
           "C_漏along项": "≈ ±0.5"}[mode]
    print(f"{mode:34s} {out['BS_Thin']:+9.2f}% {out['BS_Heavy']:+9.2f}%  {exp}")
