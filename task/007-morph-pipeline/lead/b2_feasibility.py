"""Lead 关键路径：**B2 路线可行性验证** —— 体形 morph 派生在「角色自身网格」上。

B2 的核心洞察（FINDINGS §11.4）：
  现有 `tryon/` 的最终角色 = 服装布料 + 服装自带皮肤 + 基础体的头，**共用服装自己的 rig**。
  也就是说最终角色里**没有独立的 Superhero 身体** —— 它只捐一个头。
  → 那么"身体与服装不一致"这个问题**本来就不该存在**：
    体形 morph 应当用**角色自己的 rig** 摆骨、直接烘在**这个角色的每一件网格**上。

本脚本：对 TryOn_{Male,Female}_Ranger
  ① 按 `girth` 口径（(s,1,s)，只缩垂直于骨轴的两轴）把 14 根体形骨摆成 瘦/壮
  ② 用 depsgraph 取形 → 烘成 BS_Thin / BS_Heavy 两个 shape key（**每一件网格都烘**）
  ③ 清 pose；导出统计 + 三态并排渲染

判据：身高比 ≈ 1.0000（体形与身高正交）、拓扑不变、视觉连贯。
只读旧资产（`assets/3d/blend/tryon/`），产物只写 lead/ 目录。
"""
import bpy, os, math, json
from mathutils import Vector

ROOT = "/Users/zhenkunzhu/Desktop/project/artstudio"
TMPL = f"{ROOT}/assets/3d/blend/tryon/TryOn_{{sex}}_Ranger.blend"
OUTDIR = f"{ROOT}/task/007-morph-pipeline/lead"
SHAPE_BONES = ["pelvis", "spine_01", "spine_02", "spine_03",
               "thigh_l", "thigh_r", "calf_l", "calf_r",
               "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r",
               "clavicle_l", "clavicle_r"]
# 与 bodyshape 的 delta_response 同构：靠脊柱/远端更保守
RESP = {"pelvis": 1.0, "spine_01": 1.0, "spine_02": 0.92, "spine_03": 0.85,
        "thigh": 0.95, "calf": 0.85, "upperarm": 1.05, "lowerarm": 0.95, "clavicle": 0.5}
TIERS = {"BS_Thin": 0.86, "BS_Heavy": 1.16}


def resp(bn):
    for k, v in RESP.items():
        if bn.startswith(k):
            return v
    return 1.0


def eval_pts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    pts = [e.matrix_world @ v.co for v in m.vertices]
    e.to_mesh_clear()
    return pts


report = {}
for sex in ("Male", "Female"):
    print(f"\n{'#'*78}\n# B2 验证：TryOn_{sex}_Ranger\n{'#'*78}")
    bpy.ops.wm.open_mainfile(filepath=TMPL.format(sex=sex))
    arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
    meshes = [o for o in bpy.data.objects
              if o.type == 'MESH' and not o.name.startswith("Icosphere")]
    for o in list(bpy.data.objects):
        if o.name.startswith("Icosphere"):
            bpy.data.objects.remove(o, do_unlink=True)
    total_v = sum(len(o.data.vertices) for o in meshes)
    print(f"角色：{len(meshes)} 件网格 / {total_v} 顶点 / 骨架 {arm.name} ({len(arm.data.bones)} 骨)")
    print(f"  件：{', '.join(o.name for o in sorted(meshes, key=lambda x: x.name))}")

    # 体形骨规则：全部直接子骨 → 缩放不继承
    changed = set()
    for bn in SHAPE_BONES:
        if bn not in arm.data.bones:
            continue
        for ch in arm.data.bones[bn].children:
            if ch.inherit_scale != 'NONE':
                ch.inherit_scale = 'NONE'
                changed.add(ch.name)
    print(f"  设 inherit_scale='NONE' 的子骨 {len(changed)} 根")

    basis_h = max(p.z for p in eval_pts(meshes[0])) if False else None
    # 用全部网格的 AABB 高度当"角色身高"
    def char_height():
        zs = [p.z for o in meshes for p in eval_pts(o)]
        return max(zs) - min(zs)

    # 建通道：每件都建 Basis + BS_Thin + BS_Heavy（顺序即契约）
    for o in meshes:
        if o.data.shape_keys is None:
            o.shape_key_add(name="Basis", from_mix=False)
        for nm in ("BS_Thin", "BS_Heavy"):
            o.shape_key_add(name=nm, from_mix=False)

    # 逐档摆骨 → 烘
    for tier_name, coef in TIERS.items():
        for pb in arm.pose.bones:
            pb.scale = (1, 1, 1)
        for bn in SHAPE_BONES:
            if bn in arm.pose.bones:
                s = 1.0 + (coef - 1.0) * resp(bn)
                arm.pose.bones[bn].scale = (s, 1.0, s)      # ← girth 口径
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        for o in meshes:
            ev = o.evaluated_get(dg)
            m = ev.to_mesh()
            key = o.data.shape_keys.key_blocks[tier_name]
            for i, v in enumerate(m.vertices):
                key.data[i].co = v.co
            ev.to_mesh_clear()
            key.value = 0.0
        print(f"  烘 {tier_name}（系数 {coef}）完成")

    for pb in arm.pose.bones:
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()

    h0 = char_height()
    stats = {}
    for o in meshes:
        kb = o.data.shape_keys.key_blocks
        assert [k.name for k in kb] == ["Basis", "BS_Thin", "BS_Heavy"], [k.name for k in kb]
        assert len(kb["Basis"].data) == len(o.data.vertices)
        per = {}
        for tier in ("BS_Thin", "BS_Heavy"):
            d = [(kb[tier].data[i].co - o.data.vertices[i].co).length
                 for i in range(len(o.data.vertices))]
            per[tier] = {"max_cm": max(d) * 100, "mean_cm": sum(d) / len(d) * 100}
        stats[o.name] = {"verts": len(o.data.vertices), "per_tier": per}

    # 身高比（把 BS_Heavy=1 打开后量）
    ratio = {}
    for tier in ("BS_Thin", "BS_Heavy"):
        for o in meshes:
            o.data.shape_keys.key_blocks[tier].value = 1.0
        bpy.context.view_layer.update()
        ratio[tier] = char_height() / h0
        for o in meshes:
            o.data.shape_keys.key_blocks[tier].value = 0.0
        bpy.context.view_layer.update()

    dm = max(v["per_tier"][t]["max_cm"] for v in stats.values() for t in ("BS_Thin", "BS_Heavy"))
    print(f"\n  ★ 拓扑：每件 {list(stats.values())[0]['verts']} 顶点量级，三档顶点数一致 ✅（脚本内 assert）")
    print(f"  ★ 身高比：BS_Thin {ratio['BS_Thin']:.5f}  BS_Heavy {ratio['BS_Heavy']:.5f}  （要 ≈1.0000）")
    print(f"  ★ 最大位移（全部件中最大）：{dm:.2f} cm")
    print(f"  ★ morph 数据量：{total_v} 顶点 × 12 B × 2 档 = {total_v*12*2/1024:.0f} KB")

    report[sex] = {"meshes": len(meshes), "verts": total_v,
                   "height_ratio": {k: round(v, 5) for k, v in ratio.items()},
                   "max_disp_cm": round(dm, 2),
                   "morph_kb": round(total_v * 12 * 2 / 1024, 1),
                   "per_piece": {k: {t: {kk: round(vv, 3) for kk, vv in v2.items()}
                                     for t, v2 in v["per_tier"].items()}
                                 for k, v in stats.items()}}

    # ── 三态并排渲染 ──
    panels = [("瘦 Thin", "BS_Thin", -1.02), ("标准", None, 0.0), ("壮 Heavy", "BS_Heavy", 1.02)]
    base_x = [o.location.x for o in meshes]          # ← 先记原位置，否则副本会叠加（踩过的坑）
    for pi, (lab, tier, xoff) in enumerate(panels):
        if pi == 0:
            group = list(meshes)
        else:
            group = []
            for o in meshes:
                c = o.copy(); c.data = o.data.copy()
                bpy.context.scene.collection.objects.link(c)
                group.append(c)
        for i, o in enumerate(group):
            o.location.x = base_x[i] + xoff
            if tier:
                o.data.shape_keys.key_blocks[tier].value = 1.0
    arm.hide_render = True

    cd = bpy.data.cameras.new("C"); cam = bpy.data.objects.new("C", cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (0, -5.7, 0.95); cam.rotation_euler = (1.5708, 0, 0); cd.lens = 50
    bpy.context.scene.camera = cam
    for nm, loc, e in (("K", (3, -3.5, 4), 2800), ("F", (-3, -2.5, 2), 1000)):
        ld = bpy.data.lights.new(nm, 'AREA'); ld.energy = e; ld.size = 5
        lo = bpy.data.objects.new(nm, ld); lo.location = loc; lo.rotation_euler = (0.8, 0, 0.85)
        bpy.context.scene.collection.objects.link(lo)
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x, sc.render.resolution_y = 1700, 1000
    out = f"{OUTDIR}/b2_{sex}_three_tiers.png"
    sc.render.filepath = out
    sc.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(write_still=True)
    print(f"  渲染 → {out}  exists={os.path.exists(out)}")

json.dump(report, open(f"{OUTDIR}/b2_report.json", "w"), ensure_ascii=False, indent=1)
print("\n汇总:")
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "per_piece"}
                  for k, v in report.items()}, ensure_ascii=False, indent=1))
print("DONE")