"""造两个"M4c 应当变红"的对照角色（用于证明判据有判别力）：
  ctrlB  漏 NONE 隔离（全 FULL + manifest 的 bones_applied）
  ctrlC  漏 along 项（NONE 隔离 + 只用 (s,1,s)）
正面件仍从 assets/3d/rig/garments/ 读，不动。
"""
import json, os, sys
import bpy
sys.path.insert(0, "tools/3d/garment")
import common as C

man = json.load(open("assets/3d/rig/manifests/bodyshape_manifest.json"))
tiers = {t["shape_key"]: t for t in man["tiers"]}
resp = {k: v for k, v in man["delta_response"].items() if not k.startswith("_")}


def resp_of(bn):
    for k, v in resp.items():
        if bn.startswith(k):
            return v
    return 1.0


def _ev(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


for tag, mode in (("ctrlB", "no_none"), ("ctrlC", "no_along")):
    out = f"tmp/garment/{tag}"
    os.makedirs(out, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath="assets/3d/blend/tryon/TryOn_Female_Ranger.blend")
    bpy.context.preferences.filepaths.save_version = 0
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    meshes = sorted([o for o in bpy.data.objects if o.type == 'MESH' and not C.is_helper(o)],
                    key=lambda x: x.name)
    for n in [o.name for o in bpy.data.objects if C.is_helper(o)]:
        bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
    if mode == "no_along":                       # 只这一支设 NONE 隔离
        for bn in C.SHAPE_BONES:
            if bn in arm.data.bones:
                for ch in arm.data.bones[bn].children:
                    ch.inherit_scale = 'NONE'
    for o in meshes:
        if o.data.shape_keys is None:
            o.shape_key_add(name="Basis", from_mix=False)
        for nm in ("BS_Thin", "BS_Heavy"):
            if nm not in o.data.shape_keys.key_blocks:
                o.shape_key_add(name=nm, from_mix=False)
    for tier, coef in (("BS_Thin", 0.84), ("BS_Heavy", 1.21)):
        for pb in arm.pose.bones:
            pb.scale = (1.0, 1.0, 1.0)
        ba = tiers[tier]["bones_applied"]
        for bn in C.SHAPE_BONES:
            if bn not in arm.pose.bones:
                continue
            if mode == "no_along":
                s_ = 1.0 + (coef - 1.0) * resp_of(bn)
                arm.pose.bones[bn].scale = (s_, 1.0, s_)
            else:
                arm.pose.bones[bn].scale = ba[bn]
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        for o in meshes:
            ev = o.evaluated_get(dg)
            m = ev.to_mesh()
            kb = o.data.shape_keys.key_blocks[tier]
            for i, v in enumerate(m.vertices):
                kb.data[i].co = v.co
            ev.to_mesh_clear()
            kb.value = 0.0
    for pb in arm.pose.bones:
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=f"{out}/Female_Ranger.blend")
    print(f"已造 {tag}（{mode}）→ {out}/Female_Ranger.blend")
