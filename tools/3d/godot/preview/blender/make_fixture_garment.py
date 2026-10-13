# -*- coding: utf-8 -*-
"""自造 **fixture 服装**：从标准体派生一件"带同名 morph 的布料壳"。

为什么需要：
  T2（`garment`）的最终 `assets/3d/rig/garments/*.blend` 可能还没好，而本预览页面
  必须**先能跑**。所以这里按 SPEC §3.3/§4.3 的契约造一件**结构完全合规**的临时服装：
  * 纯布料件（不含头脸，z ≤ `--zmax`），
  * 共用标准体的骨架（`arm.data` 直接复用，与 SPEC §4.3「Skeleton 指向标准体」一致），
  * shape key **同名同序**：`Basis` / `BS_Thin`(0) / `BS_Heavy`(1)，
  * 顶点顺序与标准体**逐点可映射**（子集，保持原顺序），因此 morph 逐点复制 ——
    这正是 `garment` 的"重心坐标+标架传递"在**理想无误差**时的结果。

`--gain` 用来人为模拟"传递精度不足"：
  * `gain < 1`：服装形变**跟不上**身体 → 瘦档时布料浮在皮肤外（间隙）；
  * `gain > 1`：服装形变**超过**身体 → 瘦档时布料钻进身体里（**穿模**）。
  这样 T3 的"穿模指示"才有东西可看；换成 T2 的真实资产后这个 fixture 自动退场。

只在 `tmp/` 缓存目录落盘，**不写 `assets/3d/rig/garments/`**（那是 T2 的写入范围）。

用法：
  Blender --background --factory-startup --python make_fixture_garment.py -- \
      <body.blend> <dst.blend> --offset 0.012 --gain 1.35 --zmax 1.55 \
      --name Female_Ranger --color 0.16,0.45,0.42
"""
import json
import os
import sys

import bpy
from mathutils import Matrix

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import _morphfix  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
body_path, dst = argv[0], argv[1]
opt = {"offset": 0.012, "gain": 1.0, "zmax": 1.55, "name": "Fixture_Garment",
       "color": "0.16,0.45,0.42", "spec": ""}
i = 2
while i < len(argv):
    if argv[i].startswith("--"):
        opt[argv[i][2:]] = argv[i + 1]
        i += 2
    else:
        i += 1
offset = float(opt["offset"])
gain = float(opt["gain"])
zmax = float(opt["zmax"])
gname = str(opt["name"])
color = [float(c) for c in str(opt["color"]).split(",")]
spec_path = str(opt["spec"]) or None

bpy.ops.wm.open_mainfile(filepath=body_path)

# ---- 找标准体自己的网格与骨架 -------------------------------------------------
body = _morphfix.find_body()
if body is None:
    raise SystemExit("找不到带 shape key 的 Body_* 网格：%s" % body_path)
# T1 未落地时 BS_Thin/BS_Heavy 还是全零占位 → 现场派生 fixture morph（与 body 的 glb 同源）
morph_rep = _morphfix.ensure_body_morph(body, spec_path)
print("MORPHFIX " + json.dumps(morph_rep, ensure_ascii=False))
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
me = body.data
kbs = me.shape_keys.key_blocks
for kb in kbs:
    kb.value = 0.0
names = [k.name for k in kbs]
assert names[:3] == ["Basis", "BS_Thin", "BS_Heavy"], "morph 契约不符：%s" % names

NV = len(me.vertices)
basis = [v.co.copy() for v in me.vertices]
nrm = [v.normal.copy() for v in me.vertices]
d_thin = [kbs["BS_Thin"].data[i].co - basis[i] for i in range(NV)]
d_heavy = [kbs["BS_Heavy"].data[i].co - basis[i] for i in range(NV)]

# ---- 选面：所有顶点 z <= zmax（把头和脸留出来，方便肉眼看脸/发型）------------
keep = [i for i in range(NV) if basis[i].z <= zmax]
keepset = set(keep)
remap = {old: j for j, old in enumerate(keep)}
faces = []
for p in me.polygons:
    vs = list(p.vertices)
    if all(v in keepset for v in vs):
        faces.append([remap[v] for v in vs])

new_verts = [basis[o] + nrm[o] * offset for o in keep]  # 沿静止法线外扩 = 布料壳

gme = bpy.data.meshes.new(gname + "_mesh")
gme.from_pydata([tuple(v) for v in new_verts], [], faces)
gme.update()
gme.validate()

gob = bpy.data.objects.new(gname, gme)
bpy.context.scene.collection.objects.link(gob)
# 平滑着色（布料壳最好是平滑的，否则棱角明显）
for p in gme.polygons:
    p.use_smooth = True

# ---- 蒙皮：共用标准体的 Armature 数据（SPEC §4.3）+ 复制顶点组权重 -----------
garm = bpy.data.objects.new("RIG_" + arm.name, arm.data)  # 共用同一份骨骼数据
bpy.context.scene.collection.objects.link(garm)
gob.parent = garm
gob.matrix_parent_inverse = Matrix.Identity(4)
mod = gob.modifiers.new(name="Armature", type='ARMATURE')
mod.object = garm

vgs = {}
for g in body.vertex_groups:
    vgs[g.index] = gob.vertex_groups.new(name=g.name)
for o in keep:
    j = remap[o]
    for ge in me.vertices[o].groups:
        vgs[ge.group].add([j], ge.weight, 'REPLACE')

# ---- 材质：纯色（fixture 不需要贴图，避免把 125MB 贴图卷进来）---------------
mat = bpy.data.materials.new(name="MI_Fixture_" + gname)
mat.use_nodes = True
bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
bsdf.inputs["Roughness"].default_value = 0.55
gme.materials.append(mat)

# ---- shape key：同名同序 + 逐点 morph（gain 控制"传递精度"）------------------
gob.shape_key_add(name="Basis", from_mix=False)
for skname, delta in (("BS_Thin", d_thin), ("BS_Heavy", d_heavy)):
    kb = gob.shape_key_add(name=skname, from_mix=False)
    for j, o in enumerate(keep):
        kb.data[j].co = new_verts[j] + delta[o] * gain

for kb in gob.data.shape_keys.key_blocks:  # 落盘时值为 0
    kb.value = 0.0

# ---- 瘦身：fixture 文件里只留「布料 + 它共用的那副骨架」---------------------
# 不清理的话 save_as_mainfile 会把源标准体整份（body/眉毛/眼睛/相机/灯）一起写进去，
# 文件白胖 40 倍，而且下游（penetration / glTF 导出）会看到两份 Body_* 造成歧义。
for ob in list(bpy.data.objects):
    if ob in (gob, garm):
        continue
    bpy.data.objects.remove(ob, do_unlink=True)
for im in list(bpy.data.images):
    if not im.packed_file:
        bpy.data.images.remove(im)

os.makedirs(os.path.dirname(dst), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=dst)

rep = {"body": body_path, "dst": dst, "name": gname, "offset": offset, "gain": gain,
       "zmax": zmax, "body_verts": NV, "garment_verts": len(keep), "faces": len(faces),
       "shape_keys": [k.name for k in gob.data.shape_keys.key_blocks],
       "vgroups": len(gob.vertex_groups), "bones": len(garm.data.bones),
       "body_morph": morph_rep,
       "color": color}
print("FIXTURE_JSON " + json.dumps(rep, ensure_ascii=False))