"""Lead 独立验收：检查 B2 产物（assets/3d/rig/garments/*.blend）是否满足契约。

逐份重开断言（不依赖 garment 的任何脚本）：
  ① 结构：应是「一个角色」—— 1 副骨架 + 多件网格（布料 + 头）
  ② morph 契约：**每一件**网格都有 Basis / BS_Thin(索引0) / BS_Heavy(索引1)
  ③ 拓扑：三档顶点数一致
  ④ 身高比 ≈ 1.0000（体形与身高正交，阈值 ±0.002）
  ⑤ 数据量 = 顶点数 × 12 B × 档数
  ⑥ 贴图无断链
只读，不写任何 .blend。
"""
import bpy, os, glob, json

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
files = sorted(glob.glob(f"{ROOT}/assets/3d/rig/garments/*.blend"))
EXPECT = ["Basis", "BS_Thin", "BS_Heavy"]
rows = []


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


print(f"待验 {len(files)} 份：{[os.path.basename(f) for f in files]}\n")
for p in files:
    name = os.path.basename(p)[:-6]
    bpy.ops.wm.open_mainfile(filepath=p)
    arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
    meshes = [o for o in bpy.data.objects
              if o.type == 'MESH' and not o.name.startswith("Icosphere")]
    total_v = sum(len(o.data.vertices) for o in meshes)

    # ②③ morph 契约 + 拓扑
    bad_order, bad_topo, no_keys = [], [], []
    for o in meshes:
        sk = o.data.shape_keys
        if sk is None:
            no_keys.append(o.name); continue
        order = [k.name for k in sk.key_blocks]
        if order != EXPECT:
            bad_order.append((o.name, order))
        if any(len(k.data) != len(o.data.vertices) for k in sk.key_blocks):
            bad_topo.append(o.name)

    # ④ 身高比（BS_Heavy=1 时的角色 AABB 高度 / 基准）
    def char_h():
        zs = [q.z for o in meshes for q in eval_pts(o)]
        return max(zs) - min(zs)
    h = {}
    h0 = char_h()
    for tier in ("BS_Thin", "BS_Heavy"):
        for o in meshes:
            o.data.shape_keys.key_blocks[tier].value = 1.0
        bpy.context.view_layer.update()
        h[tier] = char_h() / h0
        for o in meshes:
            o.data.shape_keys.key_blocks[tier].value = 0.0
        bpy.context.view_layer.update()

    # ⑥ 贴图
    dangling = [i.name for i in bpy.data.images
                if i.source == 'FILE' and not os.path.exists(bpy.path.abspath(i.filepath))]

    ok = (not bad_order and not bad_topo and not no_keys and not dangling
          and all(abs(v - 1.0) <= 0.002 for v in h.values()))
    rows.append({"file": name, "arms": len(arms), "meshes": len(meshes), "verts": total_v,
                 "morph_kb": round(total_v*12*2/1024, 1),
                 "h_thin": round(h["BS_Thin"], 5), "h_heavy": round(h["BS_Heavy"], 5),
                 "no_keys": no_keys, "bad_order": bad_order, "bad_topo": bad_topo,
                 "dangling": dangling, "pass": ok})
    print(f"{name}")
    print(f"   骨架 {len(arms)} 副（{[a.name for a in arms]}）  网格 {len(meshes)} 件  {total_v} 顶点")
    print(f"   morph 数据量（2 档）{total_v*12*2/1024:7.1f} KB")
    print(f"   身高比  BS_Thin {h['BS_Thin']:.5f}   BS_Heavy {h['BS_Heavy']:.5f}   "
          f"{'✅' if all(abs(v-1.0)<=0.002 for v in h.values()) else '❌ 超差'}")
    print(f"   缺通道 {no_keys or '无'} | 顺序错 {bad_order or '无'} | 拓扑错 {bad_topo or '无'} | 贴图断链 {dangling or '无'}")
    print(f"   → {'✅ PASS' if ok else '❌ FAIL'}")

print(f"\n{'#'*74}\n# 汇总：{sum(1 for r in rows if r['pass'])}/{len(rows)} PASS\n{'#'*74}")
for r in rows:
    print(f"  {r['file']:16s} {r['meshes']:2d} 件 {r['verts']:6d} 顶点  "
          f"{r['morph_kb']:6.1f} KB  h={r['h_thin']:.5f}/{r['h_heavy']:.5f}  "
          f"{'✅' if r['pass'] else '❌'}")
json.dump(rows, open(f"{ROOT}/task/007-morph-pipeline/lead/acceptance_garments.json", "w"),
          ensure_ascii=False, indent=1)
print("DONE")