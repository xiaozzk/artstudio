extends RefCounted
## 角色组装 + morph/身高驱动（T3 的核心）。
##
## 契约（SPEC §3.3 / §3.4）：
##   * 体形：`k ∈ [-1,1]` → `BS_Thin = max(-k,0)`、`BS_Heavy = max(k,0)`，
##     **身体与每一件服装都要收到同一组值**（同名同序，索引 0/1）。
##   * 身高：`root` 骨等比 `scale = (h,h,h)`，`h ∈ [0.92, 1.08]`，**不做 morph**。
##
## 红线：**禁止硬编码 bone index** —— 一律 `Skeleton3D.find_bone("Head"/"root")`。
## （跨路线索引会变：本页 glTF 路线的 `Head` 是 54，而 UBC 源包 glTF 路线是 6。）

const CFG = preload("res://cfg.gd")
const LDR = preload("res://loader.gd")

const MORPH_ORDER: Array = ["BS_Thin", "BS_Heavy"]   ## 契约索引顺序，不许改

## 判定一个部件是不是"自包含角色"：出现眼睛/眉毛件，或出现基础体/皮肤的材质名。
static func _is_self_contained(p: Dictionary) -> bool:
	if p.get("node", null) == null:
		return false
	for mi in p["meshes"]:
		var nm := String(mi.name).to_lower()
		if nm.findn("eyes") >= 0 or nm.findn("eyebrow") >= 0:
			return true
		if looks_like_skin(mesh_material_names(mi)):
			return true
	return false


## 加载一个部件（.glb 绝对路径）并把它挂到 root 下。
static func _add_part(root: Node3D, role: String, key: String, glb: String) -> Dictionary:
	var p := {"role": role, "key": key, "glb": glb, "node": null, "skeletons": [],
		"meshes": [], "morphs": [], "errors": []}
	if glb == "":
		return p
	var n := LDR.load_scene(glb)
	if n == null:
		p["errors"].append("加载失败：%s" % glb)
		return p
	n.name = role + "_" + key
	root.add_child(n)
	p["node"] = n
	var sk := LDR.first_skeleton(n)
	if sk != null:
		p["skeletons"].append(sk)
	var mi := mesh_instances(n)
	p["meshes"] = mi
	for m in mi:
		if m.mesh == null or m.mesh.get_blend_shape_count() == 0:
			continue
		var names: Array = []
		var idx := {}
		for i in m.mesh.get_blend_shape_count():
			var nm := String(m.mesh.get_blend_shape_name(i))
			names.append(nm)
			idx[nm] = i
		p["morphs"].append({"node": m, "names": names, "idx": idx, "values": {}})
	return p

## ⚠ 实测坑（证据等级见 README 的表）：
## 1. **`set_bone_pose_rotation()` 只在骨架【已入树】之后设才有效**（A1，双实现一致 + 机制已定位）：
##    入树前设的值**不会**在入树后追溯生效；入树后设**当帧**即生效。
##    → `on_attached()` 是**必需**的，不是防御性的。
##    ⚠ 两个测量陷阱（我在这里翻过一次车，把结论误撤回过）：
##      (a) **不要用 `Basis.get_euler()` 比较姿态** —— 该骨 rest 在 Z 轴 -90°，**万向节锁**下差别很大的
##          旋转会打印出几乎相同的欧拉角（两个方向都会骗人）；
##      (b) **不要在入树前读 `get_bone_global_pose()`** —— 从未 priming 的缓存会返回一个"看起来像姿态"
##          但并非生效值的矩阵，而且入树后也不会刷新（实测 V1 == V2）。要比就比 basis 矩阵/方向向量。
## 2. **`set_bone_pose_rotation` 在 glTF 骨架上推出的 pose 空间与预期不符**：我在骨架空间里
##    想"把手臂方向转到 DOWN"，用 `pose_local = rest⁻¹·R·rest` 的共轭写法，实测手臂是朝**前**转
##    （dir_after=(0.894,0,0.447)，离目标 60°），不是朝下。改用
##    **`Skeleton3D.set_bone_global_pose_override()`**（直接给"想要的全局 pose"）→ 误差 1.4e-5 度，
##    两端都精确命中。所以这里一律走 global override。
## 3. `set_bone_global_pose_override` 是**绝对**的：父骨 pose 缩放不会自动传进来，
##    所以身高诊断里的 bone_root_scale 模式要按比例重摆一次（见 `apply_arm_pose(a, s)`）。
static func pose_arms_down(a: Dictionary, t := 0.62) -> Array:
	var entries: Array = []
	var log: Array = []
	for p in a["parts"]:
		for sk in p["skeletons"]:
			var s3 := sk as Skeleton3D
			for bn in ["upperarm_l", "upperarm_r"]:
				var bi := s3.find_bone(bn)
				if bi < 0:
					continue
				var head := s3.get_bone_global_rest(bi).origin
				var dir := Vector3.ZERO
				for c in s3.get_bone_children(bi):
					var d := s3.get_bone_global_rest(c).origin - head
					if d.length() > 0.05:
						dir = d.normalized()
						break
				if dir == Vector3.ZERO:
					continue
				var target: Vector3 = dir.slerp(Vector3.DOWN, t).normalized()
				var axis: Vector3 = dir.cross(target)
				if axis.length() < 1e-5:
					continue
				var ang := dir.angle_to(target)
				var rest := s3.get_bone_global_rest(bi)
				entries.append({"sk": s3, "bone": bn, "bi": bi, "axis": axis.normalized(),
					"ang": ang, "rest_basis": rest.basis, "rest_origin": rest.origin})
				log.append({"part": String(p["role"]), "bone": bn,
					"angle_deg": snappedf(rad_to_deg(ang), 0.1)})
	a["arms_pose"] = entries
	a["arms_down_t"] = t
	apply_arm_pose(a, 1.0)
	return log


## 入树之后再摆一次 —— **这一步是必需的**（A1：入树前设的 pose 不会生效，见文件头）。
static func on_attached(a: Dictionary) -> Array:
	var log: Array = []
	for p in a["parts"]:
		for sk in p["skeletons"]:
			for bn in ["upperarm_l", "upperarm_r"]:
				log.append({"part": String(p["role"]), "bone": bn})
	if a.get("arms_pose", []).is_empty():
		return pose_arms_down(a, float(a.get("arms_down_t", 0.62)))
	apply_arm_pose(a, 1.0)
	return a.get("arms_down", log)


## 按 s（身高倍率）重摆手臂的全局 pose override。
## s=1 → A-pose 本体；s=h → 身高走 bone 缩放时同步放大，两条路线才可比。
static func apply_arm_pose(a: Dictionary, s := 1.0) -> void:
	for e in a.get("arms_pose", []):
		var want := Transform3D(Basis(e["axis"], e["ang"])
			* (e["rest_basis"] as Basis).scaled(Vector3(s, s, s)),
			(e["rest_origin"] as Vector3) * s)
		(e["sk"] as Skeleton3D).set_bone_global_pose_override(e["bi"], want, 1.0, true)


static func mesh_material_names(mi: MeshInstance3D) -> Array:
	var out: Array = []
	if mi.mesh == null:
		return out
	for s in mi.mesh.get_surface_count():
		var m := mi.get_active_material(s)
		if m == null:
			out.append("<null>")
		elif m.resource_name != null and String(m.resource_name) != "":
			out.append(String(m.resource_name))
		else:
			out.append(m.get_class())
	return out


## 单个表面的材质名（B2 的 `Female_Ranger_Arms` 一件里同时有布料面与皮肤面，必须细分到 surface）。
static func surface_material_name(mi: MeshInstance3D, s: int) -> String:
	var m := mi.get_active_material(s)
	if m == null:
		return "<null>"
	if m.resource_name != null and String(m.resource_name) != "":
		return String(m.resource_name)
	return m.get_class()


## 皮肤判据（F2：服装自带的皮肤用 `MI_Regular_*`；基础体的头/眼用 `MI_Superhero_*`/`MI_Eyes`/`MI_Hair_*`）。
## 其余材质一律当布料。B2 自包含角色里就是用它把 12 件分成「基准面(皮肤)」与「覆盖层(布料)」。
static func looks_like_skin(mats: Array) -> bool:
	for m in mats:
		var s := String(m)
		for k in ["Regular", "Superhero", "SuperHero", "Eyes", "Hair", "BaseCharacter"]:
			if s.findn(k) >= 0:
				return true
	return false


static func mesh_instances(n: Node, acc: Array = []) -> Array:
	if n is MeshInstance3D:
		acc.append(n)
	for c in n.get_children():
		mesh_instances(c, acc)
	return acc

## 组装一个角色。`*_glb` 为空字符串表示该槽位不放东西。
static func build(body_key: String, body_glb: String, garment_key: String, garment_glb: String,
		hair_key: String, hair_glb: String, arms_down := true, force_overlay := false) -> Dictionary:
	var root := Node3D.new()
	root.name = "Avatar"
	var a := {"ok": true, "root": root, "family": body_key, "garment": garment_key,
		"hair": hair_key, "parts": [], "errors": [], "contract": {}}
	# 先挂服装：B2 路线的「服装」文件其实是**自包含角色**（布料 9 件 + 自带皮肤 + 基础体的头 3 件，
	# 共用服装自己的 rig，里面**根本没有 Superhero 身体** —— SPEC §4.0 / F17）。
	# 这种文件必须**单独当角色用**，再叠基础体就会双重叠模。
	var parts: Array = []
	var gpart := {}
	if garment_key != "":
		gpart = _add_part(root, "garment", garment_key, garment_glb)
		if _is_self_contained(gpart) and not force_overlay:
			a["route"] = "B2_self_contained"
			gpart["role"] = "character"
			parts.append(gpart)
		else:
			a["route"] = "overlay(body+garment)"
			parts.append(_add_part(root, "body", body_key, body_glb))
			parts.append(gpart)
	else:
		a["route"] = "body_only"
		parts.append(_add_part(root, "body", body_key, body_glb))
	if hair_key != "":
		parts.append(_add_part(root, "hair", hair_key, hair_glb))
	a["parts"] = parts
	for p in parts:
		a["errors"].append_array(p["errors"])
	# 契约自检：每个带 morph 的网格都必须是 ["BS_Thin"(0), "BS_Heavy"(1)]
	var chk: Array = []
	for p in parts:
		for m in p["morphs"]:
			var names: Array = m["names"]
			var ok: bool = names.size() >= 2 and String(names[0]) == String(MORPH_ORDER[0]) and String(names[1]) == String(MORPH_ORDER[1])
			chk.append({"part": String(p["role"]) + ":" + String(p["key"]), "mesh": String(m["node"].name),
				"names": names, "thin_index": m["idx"].get(MORPH_ORDER[0], -1),
				"heavy_index": m["idx"].get(MORPH_ORDER[1], -1), "contract_ok": ok})
	a["contract"] = {"expected": MORPH_ORDER, "rows": chk,
		"all_ok": chk.all(func(r): return r["contract_ok"]), "count": chk.size()}
	a["arms_down"] = pose_arms_down(a) if arms_down else []
	a["force_overlay"] = force_overlay
	a["ok"] = a["errors"].is_empty()
	return a

## 按 k 驱动体形、按 h 驱动身高。返回"**逐件**实测到的 morph 值"（验收要的就是这个）。
##
## ⚠ 身高 **不是** 缩 `Skeleton3D` 里的 `root` 骨（Lead 裁决 + verifier 实测
## `assets/3d/rig/reports/verify-heightbug.json`）：
## Blender 侧 SPEC §3.2 把体形骨的直接子骨设成 `inherit_scale='NONE'`，
## 所以 `root` 的缩放**传不过 pelvis**，只有骨盆那一圈被拉伸
## （拉伸比离散度 0.0841，阈值 0.01 → 超标 8.4 倍；身高只涨 0.5%）。
## 正确写法 = 缩放**角色根节点**的世界 scale（三轴同值）→ 实测 +8.00%、离散度 ~3e-5。
## 见 `probe_height_impl()`：两种写法都能在 Godot 里当场量出来。
static func apply(a: Dictionary, k: float, h: float) -> Dictionary:
	var thin: float = maxf(-k, 0.0)
	var heavy: float = maxf(k, 0.0)
	var rows: Array = []
	var per_mesh: Array = []      ## ★ 逐 **mesh** 一行（件级证据，不只按角色聚合）
	for p in a["parts"]:
		var n_morph := 0
		var vals: Array = []
		for m in p["morphs"]:
			var mi: MeshInstance3D = m["node"]
			var idx: Dictionary = m["idx"]
			var row := {"part": String(p["role"]), "part_key": String(p["key"]),
				"mesh": String(mi.name), "path": String(mi.get_path()),
				"blend_shape_names": m["names"],
				"thin_index": int(idx.get(MORPH_ORDER[0], -1)),
				"heavy_index": int(idx.get(MORPH_ORDER[1], -1)),
				"thin_value_set": null, "thin_value_read_back": null,
				"heavy_value_set": null, "heavy_value_read_back": null,
				"read_back_ok": false, "contract_ok": false}
			for want in MORPH_ORDER:
				if idx.has(want):
					var wi: int = idx[want]
					var v: float = thin if want == MORPH_ORDER[0] else heavy
					mi.set_blend_shape_value(wi, v)
					var back: float = mi.get_blend_shape_value(wi)
					vals.append({"name": want, "index": wi, "set": snappedf(v, 0.0001),
						"read_back": snappedf(back, 0.0001)})
					if want == MORPH_ORDER[0]:
						row["thin_value_set"] = snappedf(v, 0.0001)
						row["thin_value_read_back"] = snappedf(back, 0.0001)
					else:
						row["heavy_value_set"] = snappedf(v, 0.0001)
						row["heavy_value_read_back"] = snappedf(back, 0.0001)
					n_morph += 1
			# 逐件自证：索引必须是 0/1、读回必须等于设定值
			row["contract_ok"] = (int(row["thin_index"]) == 0 and int(row["heavy_index"]) == 1)
			row["read_back_ok"] = (row["thin_value_read_back"] != null
				and row["heavy_value_read_back"] != null
				and absf(float(row["thin_value_read_back"]) - float(row["thin_value_set"])) < 1e-4
				and absf(float(row["heavy_value_read_back"]) - float(row["heavy_value_set"])) < 1e-4)
			per_mesh.append(row)
		rows.append({"part": p["role"], "key": p["key"], "mesh_instances": p["meshes"].size(),
			"morph_channels_set": n_morph, "morph_values": vals,
			"has_morph": p["morphs"].size() > 0})
	# 身高：**角色根节点**等比 scale（不碰任何骨 pose）
	var hrows: Array = []
	for p in a["parts"]:
		for sk in p["skeletons"]:
			var s3 := sk as Skeleton3D
			hrows.append({"part": p["role"], "skeleton": String(s3.name),
				"bones": s3.get_bone_count(),
				"head_bone_by_name": s3.find_bone("Head"),
				"root_bone_by_name": s3.find_bone("root"),
				"bone_pose_scale_touched": false,
				"bone_name_at_head_idx": String(s3.get_bone_name(s3.find_bone("Head"))) if s3.find_bone("Head") >= 0 else ""})
	(a["root"] as Node3D).scale = Vector3(h, h, h)
	return {"k": snappedf(k, 0.0001), "h": snappedf(h, 0.0001),
		"bs_thin": snappedf(thin, 0.0001), "bs_heavy": snappedf(heavy, 0.0001),
		"height_mode": "avatar_root_node_uniform_scale",
		"avatar_root_scale": [(a["root"] as Node3D).scale.x, (a["root"] as Node3D).scale.y,
			(a["root"] as Node3D).scale.z],
		"parts": rows, "per_mesh": per_mesh, "height": hrows,
		"per_mesh_summary": {"n_meshes_with_morph": per_mesh.size(),
			"all_thin_index_zero": per_mesh.all(func(r): return int(r["thin_index"]) == 0),
			"all_heavy_index_one": per_mesh.all(func(r): return int(r["heavy_index"]) == 1),
			"all_read_back_ok": per_mesh.all(func(r): return bool(r["read_back_ok"]))}}


## 诊断：把两种身高写法**都在 Godot 里量出来**，用同一套"逐骨拉伸比离散度"口径。
## 返回 {mode: {dispersion, mean, min, max, n_bones, note}}。
## 离散度 = std(逐骨线性缩放) / mean(逐骨线性缩放)（阈值 ≤0.01，SPEC §5）。
static func probe_height_impl(a: Dictionary, h: float) -> Dictionary:
	var out := {}
	for mode in ["node_scale", "bone_root_scale"]:
		_apply_height_mode(a, mode, h)
		out[mode] = _bone_scale_dispersion(a)
		_apply_height_mode(a, mode, 1.0)
	out["note"] = ("bone_root_scale 在 Godot 里按骨层级继承（Godot 的 Skeleton3D 没有 Blender 的 "
		+ "inherit_scale 标志），所以它与 Blender 侧的行为**不一定一致** —— 本诊断就是用来当场对账的。")
	return out

## 逐骨段的世界长度（把**角色根节点 scale** 也算进去）—— 身高一致性度量的原始观测。
## 键 = 骨架名/父骨>子骨，值 = 世界空间段长（米）。
static func bone_world_segments(a: Dictionary) -> Dictionary:
	var out := {}
	for p in a["parts"]:
		for sk in p["skeletons"]:
			var s3 := sk as Skeleton3D
			var gt := s3.global_transform
			for i in s3.get_bone_count():
				var ch := s3.get_bone_children(i)
				if ch.is_empty():
					continue
				var c: int = ch[0]
				var l: float = ((gt * s3.get_bone_global_pose(c).origin)
					- (gt * s3.get_bone_global_pose(i).origin)).length()
				if l > 1e-6:
					out["%s/%s>%s" % [String(s3.name), s3.get_bone_name(i), s3.get_bone_name(c)]] = l
	return out


## ★ 身高"拉伸比离散度"的**主口径**（与 verifier 在 Blender 侧同一把尺子，且不带像素噪声）：
##   对每根"父→子"骨段，量 h=1 与 h=h 的**世界空间段长比**；理想等比缩放下每个比都等于 h
##   → 归一化后离散度 = std(ratio/h)/mean(ratio/h) ≈ 浮点噪声（1e-7 量级）。
## 注意：这里必须把**角色根节点的 scale** 算进去（`sk.global_transform` 已含），
##   否则 node_scale 模式会恒等于 0 —— 那样这个数就没有验证力了。
static func bone_stretch_ratios(base: Dictionary, now: Dictionary, h: float) -> Dictionary:
	var ratios: Array = []
	for k in base.keys():
		if now.has(k) and float(base[k]) > 1e-6:
			ratios.append(float(now[k]) / float(base[k]))
	if ratios.is_empty():
		return {"n_segments": 0, "dispersion": -1.0}
	var mean := 0.0
	for r in ratios:
		mean += r
	mean /= float(ratios.size())
	var var_ := 0.0
	for r in ratios:
		var d: float = r - mean
		var_ += d * d
	var_ /= float(ratios.size())
	var sd := sqrt(var_)
	var mn: float = ratios[0]
	var mx: float = ratios[0]
	for r in ratios:
		mn = minf(mn, r)
		mx = maxf(mx, r)
	return {"n_segments": ratios.size(), "mean_ratio": snappedf(mean, 0.000001),
		"height_gain_pct": snappedf(100.0 * (mean - 1.0), 0.01),
		"min_ratio": snappedf(mn, 0.000001), "max_ratio": snappedf(mx, 0.000001),
		"dispersion": snappedf(sd / maxf(mean, 1e-9), 0.000001),
		"expected_ratio": h}


static func _apply_height_mode(a: Dictionary, mode: String, h: float) -> void:
	if mode == "node_scale":
		(a["root"] as Node3D).scale = Vector3(h, h, h)
		apply_arm_pose(a, 1.0)          # 节点缩放是外层的，手臂 override 不用改
		return
	(a["root"] as Node3D).scale = Vector3.ONE
	for p in a["parts"]:
		for sk in p["skeletons"]:
			var s3 := sk as Skeleton3D
			var ri := s3.find_bone("root")
			if ri >= 0:
				s3.set_bone_pose_scale(ri, Vector3(h, h, h))
	apply_arm_pose(a, h)                # override 是绝对的 → 按 h 重摆

## 逐骨线性缩放的离散度：posed_global_rest⁻¹ 的 scale 相对 1 的离散程度。
static func _bone_scale_dispersion(a: Dictionary) -> Dictionary:
	var scales: Array = []
	for p in a["parts"]:
		for sk in p["skeletons"]:
			var s3 := sk as Skeleton3D
			for i in s3.get_bone_count():
				var posed := s3.get_bone_global_pose(i)
				var rest := s3.get_bone_global_rest(i)
				var m: Basis = posed.basis * rest.basis.inverse()
				var s := (m.get_scale().x + m.get_scale().y + m.get_scale().z) / 3.0
				scales.append(s)
	if scales.is_empty():
		return {"dispersion": -1.0, "n_bones": 0}
	var mean := 0.0
	for s in scales:
		mean += s
	mean /= float(scales.size())
	var var_ := 0.0
	for s in scales:
		var_ += (s - mean) * (s - mean)
	var_ /= float(scales.size())
	var sd := sqrt(var_)
	var mn: float = scales[0]
	var mx: float = scales[0]
	for s in scales:
		mn = minf(mn, s)
		mx = maxf(mx, s)
	return {"dispersion": snappedf(sd / maxf(mean, 1e-9), 0.00001), "mean": snappedf(mean, 0.00001),
		"min": snappedf(mn, 0.00001), "max": snappedf(mx, 0.00001), "n_bones": scales.size()}

## 一个角色里"每个部件各收到多少 morph"的紧凑读数（屏幕上直接显示）。
static func compact(a: Dictionary, k: float, h: float) -> Array:
	var thin: float = maxf(-k, 0.0)
	var heavy: float = maxf(k, 0.0)
	var out: Array = []
	for p in a["parts"]:
		var ok: bool = (p["morphs"] as Array).size() > 0
		out.append({"part": "%s:%s" % [p["role"], p["key"]],
			"meshes": p["meshes"].size(),
			"thin": snappedf(thin, 0.0001) if ok else null,
			"heavy": snappedf(heavy, 0.0001) if ok else null,
			"note": "已驱动" if ok else "无 morph 通道"})
	return out

static func stats(a: Dictionary) -> Dictionary:
	var n_mesh := 0
	var n_sk := 0
	var n_morph_mesh := 0
	var bones: Array = []
	for p in a["parts"]:
		n_mesh += p["meshes"].size()
		n_sk += p["skeletons"].size()
		for m in p["morphs"]:
			n_morph_mesh += 1
		for sk in p["skeletons"]:
			bones.append({"part": p["role"], "name": String(sk.name),
				"bone_count": sk.get_bone_count()})
	return {"mesh_instances": n_mesh, "skeletons": n_sk, "morph_meshes": n_morph_mesh,
		"bone_sets": bones}

static func free_avatar(a: Dictionary) -> void:
	if a.get("root") != null and is_instance_valid(a["root"]):
		(a["root"] as Node).queue_free()