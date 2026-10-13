extends RefCounted
## **像素法**穿模指示（不依赖任何网格拓扑假设）。
##
## 为什么不走 BVH 有符号距离：标准体网格**不是闭合曲面**（26 连通域 / 48 边界环 /
## 面绕向不一致），"最近面法线"的正负号会随机翻，在手臂/手部区域完全不可靠
## （我第一版就是这么翻车的：一件**向外偏移 12 mm** 的布料壳，rest 档竟然算出 2.73% 穿模）。
## 本文件只看**渲染结果**，对拓扑零假设。
##
## 度量口径（每个方位角 3 遍离屏渲染；材质换成纯色 unshaded，`transparent_bg = true`
## → **alpha 通道就是剪影**，不用背景色阈值 → 不受 tonemap / 光照影响）：
##   P1 只显示「基准面」（overlay 路线 = 身体；B2 自包含路线 = 皮肤）
##   P2 只显示「覆盖层」（服装 / 布料）
##   P3 两者都显示 → 逐像素看谁在前（红=基准面，绿=覆盖层，判据 `r > g`）
##   穿模率 = |{p ∈ P2 剪影 : P3 里 p 是基准面}| / |P2 剪影| × 100%
## 含义：覆盖层本来挡在那里的像素被基准面盖住了 → 布料沉到身体/皮肤里面去了。
## 已知偏差（诚实声明）：**反面的布料**（远侧手臂的袖子被躯干挡住）也会被计入，
## 所以要看**相对变化**（各档 vs rest 基线），4 个方位角取均值可削弱它。
##
## 身高一致性（同一块测量视口 + 纯白剪影）：
##   在 h=1.00 与 h=1.08 各渲染剪影，按**相对高度**切 8 条横带，逐带算横向放大率 s_x、
##   整体纵向放大率 s_y；理想等比缩放时 r = s_x/s_y 恒为 1 → 报告 std(r)/mean(r)
##   作为"拉伸比离散度"（SPEC §5 阈值 ≤0.01）。

const CFG = preload("res://cfg.gd")
const RIG = preload("res://rig.gd")
const ST = preload("res://stage.gd")
const PAGE = preload("res://page.gd")

const W := 224
const H := 312
const KS := [-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0]
const AZ_ALL := [0.0, 90.0, 180.0, 270.0]
const N_BANDS := 8

var vp: SubViewport
var cam: Camera3D
var avatar: Dictionary = {}
var ready := false
var error := ""
var route := ""
var solid_surfaces: Array = []   ## [[MeshInstance3D, surface_idx], ...] 基准面（身体 / B2 的皮肤件）
var layer_surfaces: Array = []   ## 覆盖层（服装 / B2 的布料件）
var classes: Array = []          ## 逐网格/逐表面的分类（证据用）
var calibration: Dictionary = {}  ## ★ 双向标定（SPEC F21）：不过就**不出数**

static func make_unshaded(c: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = c
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	return m

func build(tree: SceneTree, family: String, body_glb: String, gkey: String, garment_glb: String,
		hair_key: String, hair_glb: String, force_overlay := false) -> void:
	destroy()
	vp = SubViewport.new()
	vp.name = "PenMeasure"
	vp.size = Vector2i(W, H)
	vp.transparent_bg = true                       # ★ alpha = 剪影，不用背景色阈值
	vp.msaa_3d = Viewport.MSAA_DISABLED
	vp.screen_space_aa = Viewport.SCREEN_SPACE_AA_DISABLED
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	vp.use_hdr_2d = false          # 不要在 HDR→LDR 之间做额外映射，纯色要可测
	# ⚠ `own_world_3d = true` 之后 `vp.world_3d` 在**入树前是 null**
	#   （实测报 "assignment ... on a base object of type 'null instance'"），所以显式建 World3D 再赋值。
	var env := Environment.new()
	env.background_mode = Environment.BG_CLEAR_COLOR
	env.background_color = Color(0, 0, 0, 0)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR   # 等价于 Blender 的 view_transform='Standard'
	env.adjustment_enabled = false
	env.glow_enabled = false
	env.fog_enabled = false
	env.ssao_enabled = false
	env.ssil_enabled = false
	env.sdfgi_enabled = false
	var w3 := World3D.new()
	w3.environment = env
	vp.world_3d = w3
	vp.own_world_3d = true
	tree.root.add_child(vp)
	cam = Camera3D.new()
	cam.fov = 34.0
	vp.add_child(cam)
	cam.current = true

	avatar = RIG.build(family, body_glb, gkey, garment_glb,
		hair_key if hair_key != "" and hair_key != "None" else "", hair_glb, true, force_overlay)
	route = String(avatar.get("route", "overlay"))
	if avatar.get("root", null) == null:
		error = "角色构建失败"
		return
	vp.add_child(avatar["root"])
	RIG.on_attached(avatar)
	ST.auto_frame(cam, PAGE.worst_corners(), cam.fov, 7.0, 1.10, Vector2(W, H))
	_classify()
	_masks_on()
	ready = solid_surfaces.size() > 0 and layer_surfaces.size() > 0
	if not ready:
		error = "分类后没有可比的「基准面/覆盖层」（solid_surfaces=%d layer_surfaces=%d）" % [solid_surfaces.size(), layer_surfaces.size()]

## ★ 双向标定（SPEC F21）——**强制前置断言**：
##   C1「只渲基准面」：把基准面自己的像素当作覆盖层掩膜 → 判据必须 **100.00%**
##   C2「只渲覆盖层」：基准面完全不在场 → 判据必须 **0.00%**
## 不过就 `ready = false`，一条数都不出（宁可报错，也不要一个看起来像样但错的数）。
func calibrate() -> Dictionary:
	calibration = {"C1_solid_only_expect_100": null, "C2_layer_only_expect_0": null, "ok": false}
	if vp == null or not ready:
		calibration["error"] = error if error != "" else "测量器未就绪"
		ready = false
		return calibration
	var ds := await _pass_data(true, false, false, 0.0)
	var dl := await _pass_data(false, true, false, 0.0)
	var n := W * H
	var n1 := 0
	var ok1 := 0
	var n2 := 0
	var pen2 := 0
	for i in n:
		var o := i * 4
		if ds[o + 3] > 128:
			n1 += 1
			if ds[o] > ds[o + 1]:
				ok1 += 1
		if dl[o + 3] > 128:
			n2 += 1
			if dl[o] > dl[o + 1]:
				pen2 += 1
	var c1 := 100.0 * float(ok1) / maxf(1.0, float(n1))
	var c2 := 100.0 * float(pen2) / maxf(1.0, float(n2))
	calibration["C1_solid_only_expect_100"] = snappedf(c1, 0.01)
	calibration["C2_layer_only_expect_0"] = snappedf(c2, 0.01)
	calibration["solid_px_calibration"] = n1
	calibration["layer_px_calibration"] = n2
	calibration["ok"] = (n1 > 0 and n2 > 0 and absf(c1 - 100.0) <= 0.01 and c2 <= 0.01)
	if not calibration["ok"]:
		error = ("双向标定未通过（C1 只渲基准面应 100.00%%、实测 %.2f%%；"
			% c1 + "C2 只渲覆盖层应 0.00%%、实测 %.2f%%）→ 拒绝出数" % c2)
		ready = false
	return calibration

func usable() -> bool:
	return ready and bool(calibration.get("ok", false))

## 把每个网格分到「基准面(solid)」或「覆盖层(layer)」。
## overlay 路线：身体 = solid，服装 = layer。
## B2 自包含路线：皮肤材质件 = solid，布料件 = layer。
func _classify() -> void:
	solid_surfaces = []
	layer_surfaces = []
	classes = []
	for p in avatar["parts"]:
		for mi in RIG.mesh_instances(p["node"]):
			var role := String(p["role"])
			if role == "hair":
				continue
			for s in mi.mesh.get_surface_count() if mi.mesh != null else 0:
				var nm := RIG.surface_material_name(mi, s)
				var cls := ""
				if route == "overlay":
					cls = "solid(body)" if role == "body" else "layer(garment)"
				else:
					cls = "solid(skin)" if RIG.looks_like_skin([nm]) else "layer(cloth)"
				classes.append({"part": String(p["key"]), "mesh": String(mi.name), "surface": s,
					"material": nm, "class": cls})
				if cls.begins_with("solid"):
					solid_surfaces.append([mi, s])
				else:
					layer_surfaces.append([mi, s])

## 逐**表面**涂色：`Female_Ranger_Arms` 这一件同时含布料(MI_Ranger)与皮肤(MI_Regular_Female)，
## 按整件分类会把 62% 的布料误判成皮肤 —— 所以必须细分到 surface。
func _set_masks(solid_vis: bool, layer_vis: bool) -> void:
	for e in solid_surfaces:
		(e[0] as MeshInstance3D).set_surface_override_material(e[1],
			make_unshaded(Color(1, 0, 0)) if solid_vis else _invisible())
	for e in layer_surfaces:
		(e[0] as MeshInstance3D).set_surface_override_material(e[1],
			make_unshaded(Color(0, 1, 0)) if layer_vis else _invisible())

static func _invisible() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.albedo_color = Color(0, 0, 0, 0)      # alpha=0 + 透明通道 → 对 alpha 掩膜零贡献
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	return m

func _masks_on() -> void:
	_set_masks(true, true)

func _white_all() -> void:
	for e in solid_surfaces + layer_surfaces:
		(e[0] as MeshInstance3D).set_surface_override_material(e[1], make_unshaded(Color(1, 1, 1)))

func destroy() -> void:
	ready = false
	avatar = {}
	if vp != null and is_instance_valid(vp):
		vp.queue_free()
	vp = null
	cam = null

func _vis(_solid: bool, _layer: bool, hair: bool) -> void:
	for p in avatar.get("parts", []):
		if String(p["role"]) == "hair" and p["node"] != null:
			(p["node"] as Node3D).visible = hair

## 身高一致性必须用**正交相机**测：透视投影下"把角色整体放大 8%"并不是"图像等比放大 8%"
## （近处放得多、远处放得少）→ 会把纯投影误差算成"拉伸比离散度"。
## 实测：透视下 0.0098~0.0157（男 Ranger 已超 0.01 阈值），正交下回到量化噪声量级。
func set_ortho(on: bool) -> void:
	if cam == null:
		return
	if on:
		cam.projection = Camera3D.PROJECTION_ORTHOGONAL
		cam.size = PAGE.ENV_TOP * 1.14
		cam.near = 0.05
		cam.far = 100.0
		var dir := Vector3(0, sin(deg_to_rad(7.0)), cos(deg_to_rad(7.0)))
		var center := Vector3(0, PAGE.ENV_TOP * 0.5, 0)
		cam.look_at_from_position(center + dir * 6.0, center, Vector3.UP)
	else:
		cam.projection = Camera3D.PROJECTION_PERSPECTIVE
		cam.fov = 34.0
		ST.auto_frame(cam, PAGE.worst_corners(), cam.fov, 7.0, 1.10, Vector2(W, H))

func _cam_at(az_deg: float) -> void:
	var a := deg_to_rad(az_deg)
	var dir := Vector3(sin(a), 0.12, cos(a)).normalized()
	var center := Vector3(0, PAGE.ENV_TOP * 0.5, 0)
	cam.look_at_from_position(center + dir * 4.2, center, Vector3.UP)

func _pass_data(solid: bool, layer: bool, hair: bool, az: float) -> PackedByteArray:
	_set_masks(solid, layer)
	_vis(solid, layer, hair)
	_cam_at(az)
	await vp.get_tree().process_frame
	await vp.get_tree().process_frame
	var im := vp.get_texture().get_image()
	if im.get_format() != Image.FORMAT_RGBA8:
		im.convert(Image.FORMAT_RGBA8)
	return im.get_data()

func _pen_one(k: float, az: float) -> Dictionary:
	RIG.apply(avatar, k, 1.0)
	var ds := await _pass_data(true, false, false, az)     # P1 只有基准面
	var dl := await _pass_data(false, true, false, az)     # P2 只有覆盖层
	var db := await _pass_data(true, true, false, az)      # P3 两者都在
	var n := W * H
	var n_layer := 0
	var n_pen := 0
	var n_solid := 0
	var n_union := 0
	var n_solid_front := 0
	for i in n:
		var o := i * 4
		if ds[o + 3] > 128:                                # alpha = 剪影
			n_solid += 1
		if db[o + 3] > 128:
			n_union += 1
			if db[o] > db[o + 1]:                          # 基准面在前
				n_solid_front += 1
		if dl[o + 3] > 128:
			n_layer += 1
			# P3 里 `r > g` = 基准面在前 → 覆盖层被盖住 = 沉进去了
			# （纯色 unshaded + Linear tonemap；用**相对大小**而不是绝对阈值，抗任何单调映射）
			if db[o + 3] > 128 and db[o] > db[o + 1]:
				n_pen += 1
	return {"k": snappedf(k, 0.0001), "azimuth_deg": az, "solid_px": n_solid,
		"layer_px": n_layer, "occluded_px": n_pen, "union_px": n_union,
		"solid_visible_share_pct": snappedf(100.0 * float(n_solid_front) / maxf(1.0, float(n_union)), 0.01),
		"penetration_pct": snappedf(100.0 * float(n_pen) / maxf(1.0, float(n_layer)), 0.01),
		"penetration_pct_of_union": snappedf(100.0 * float(n_pen) / maxf(1.0, float(n_union)), 0.01)}

func measure_k(k: float, azimuths: Array = AZ_ALL) -> Dictionary:
	if not usable():
		return {"error": error, "route": route, "calibration": calibration}
	var rows: Array = []
	for az in azimuths:
		rows.append(await _pen_one(k, az))
	var vals: Array = []
	for r in rows:
		vals.append(float(r["penetration_pct"]))
	var mean := 0.0
	var mx := 0.0
	for v in vals:
		mean += v
		mx = maxf(mx, v)
	mean /= maxf(1.0, float(vals.size()))
	var share := 0.0
	for r in rows:
		share += float(r.get("solid_visible_share_pct", 0.0))
	share /= maxf(1.0, float(rows.size()))
	return {"k": snappedf(k, 0.0001), "per_azimuth": rows, "mean_pct": snappedf(mean, 0.01),
		"max_pct": snappedf(mx, 0.01), "n_azimuths": vals.size(), "route": route,
		"solid_visible_share_pct": snappedf(share, 0.01)}

func measure_curve(azimuths: Array = AZ_ALL) -> Dictionary:
	if not usable():
		return {"error": error, "route": route, "classes": classes, "calibration": calibration}
	var rows: Array = []
	var ks: Array = []
	var means: Array = []
	var maxes: Array = []
	for k in KS:
		var r := await measure_k(k, azimuths)
		rows.append(r)
		ks.append(k)
		means.append(r.get("mean_pct", 0.0))
		maxes.append(r.get("max_pct", 0.0))
	var base: float = float(means[KS.find(0.0)]) if KS.find(0.0) >= 0 else 0.0
	var first: Variant = null
	for i in means.size():
		if float(means[i]) > base + CFG.PEN_THRESHOLD_PCT:
			first = ks[i]
			break
	return {"ks": ks, "mean_pct": means, "max_pct": maxes, "rest_baseline_pct": base,
		"first_k_over_baseline_plus_2pct": first, "rows": rows,
		"method": ("pixel: P1 solid-only / P2 layer-only / P3 both; alpha=mask; "
			+ "pen = |layer px hidden behind solid| / |layer px|"),
		"route": route, "classes": classes, "calibration": calibration,
		"normalization": ("penetration_pct = occluded_px / layer_px（**归一化到覆盖层/服装**）；"
			+ "同时给 penetration_pct_of_union = occluded_px / union_px（归一化到剪影）以便与 garment 的 P_full 对账 —— 两者都对，但不是同一个数"),
		"azimuths_deg": azimuths, "resolution": [W, H]}

## ---- 身高一致性（拉伸比离散度）----------------------------------------------
func _silhouette(ortho := false) -> PackedByteArray:
	_white_all()
	_set_masks(false, false)
	for e in solid_surfaces + layer_surfaces:
		(e[0] as MeshInstance3D).set_surface_override_material(e[1], make_unshaded(Color(1, 1, 1)))
	_vis(true, true, true)
	if ortho:
		set_ortho(true)
	else:
		_cam_at(0.0)
	await vp.get_tree().process_frame
	await vp.get_tree().process_frame
	var im := vp.get_texture().get_image()
	if im.get_format() != Image.FORMAT_RGBA8:
		im.convert(Image.FORMAT_RGBA8)
	var d := im.get_data()
	_masks_on()
	return d

## 剪影的**累积面积剖面**（从下往上，按相对高度取 17 个采样点） + 总面积 + 像素高度。
## 为什么不用"逐带宽度"：横带宽度只有几十像素，整数取整的量化误差会被放大
## （实测出现过 band_ratio 0.889 这种纯量化噪声，把离散度从 ~0 抬到 0.039）。
## 累积面积在几百到几万像素上求和，量化误差被平均掉；等比缩放下剖面形状**不变**：
##   cum2(t)/area2 ≡ cum1(t)/area1   → 比值恒为 1；非等比缩放（例如 Blender 侧"只缩 pelvis 一圈"）则明显偏离 1。
func _profile(data: PackedByteArray) -> Dictionary:
	var n := W * H
	var ymin := H
	var ymax := -1
	var area := 0
	for i in n:
		if data[i * 4 + 3] > 128:
			var y := i / W
			ymin = mini(ymin, y)
			ymax = maxi(ymax, y)
			area += 1
	if ymax < 0:
		return {"ok": false}
	var hgt := ymax - ymin + 1
	var rows := PackedInt32Array()
	rows.resize(hgt)
	for y in range(ymin, ymax + 1):
		var c := 0
		for x in W:
			if data[(y * W + x) * 4 + 3] > 128:
				c += 1
		rows[y - ymin] = c
	# cum(t) = 从底部往上 t 比例高度内的像素数
	var cum := PackedFloat32Array()
	var acc := 0
	var next_t := 0.0
	for y in range(hgt - 1, -1, -1):
		acc += rows[y]
		var t := float(hgt - y) / float(hgt)
		if t >= next_t - 1e-6:
			cum.append(float(acc))
			next_t += 1.0 / float(N_BANDS)
	if cum.size() == 0 or cum[cum.size() - 1] <= 0.0:
		return {"ok": false}
	return {"ok": true, "ymin": ymin, "ymax": ymax, "height_px": hgt, "area_px": area,
		"cum_profile": cum}

func measure_height_uniformity(h: float = CFG.H_MAX) -> Dictionary:
	if not usable():
		return {"error": error, "calibration": calibration}
	var out := {"h": h, "metric": "累积面积剖面（17 点，归一化）相对偏差的离散度 —— 等比缩放下应≈0",
		"threshold": 0.01, "modes": {}, "route": route}
	for mode in ["node_scale", "bone_root_scale"]:
		# ---- 主口径：逐骨段世界长度比（无像素噪声）----
		RIG._apply_height_mode(avatar, mode, 1.0)
		await vp.get_tree().process_frame
		var seg1 := RIG.bone_world_segments(avatar)
		RIG._apply_height_mode(avatar, mode, h)
		await vp.get_tree().process_frame
		var seg2 := RIG.bone_world_segments(avatar)
		var stretch := RIG.bone_stretch_ratios(seg1, seg2, h)
		# ---- 副口径：正交剪影的累积面积剖面（有量化噪声，只作旁证）----
		RIG._apply_height_mode(avatar, mode, 1.0)
		var b1 := _profile(await _silhouette(true))     # ★ 正交
		RIG._apply_height_mode(avatar, mode, h)
		var b2 := _profile(await _silhouette(true))
		RIG._apply_height_mode(avatar, mode, 1.0)
		if not b1.get("ok", false) or not b2.get("ok", false):
			out["modes"][mode] = {"error": "剪影为空"}
			continue
		var sy_px := float(b2["height_px"]) / maxf(1.0, float(b1["height_px"]))
		# 面积口径的 sy 精度高一个数量级（几万像素求和，量化误差 ~0.1%）
		var sy_area: float = sqrt(maxf(1e-9, float(b2["area_px"]) / maxf(1.0, float(b1["area_px"]))))
		var c1: PackedFloat32Array = b1["cum_profile"]
		var c2: PackedFloat32Array = b2["cum_profile"]
		var a1: float = float(b1["area_px"])
		var a2: float = float(b2["area_px"])
		var ratios: Array = []
		var m := mini(c1.size(), c2.size())
		for i in range(1, m):   # 跳过 t=0 那个恒为 0 的点
			var p1: float = float(c1[i]) / a1
			var p2: float = float(c2[i]) / a2
			ratios.append(snappedf(p2 / maxf(p1, 1e-9) - 1.0, 0.00001))   # 相对偏差，理想 = 0
		var mean := 0.0
		for r in ratios:
			mean += r
		mean /= maxf(1.0, float(ratios.size()))
		var var_ := 0.0
		for r in ratios:
			var_ += (r - mean) * (r - mean)
		var_ /= maxf(1.0, float(ratios.size()))
		var sd := sqrt(var_)
		out["modes"][mode] = {"bone_stretch": stretch,
			"bone_stretch_dispersion": stretch.get("dispersion", -1.0),
			"bone_stretch_height_gain_pct": stretch.get("height_gain_pct", 0.0),
			"pass_le_0.01_bone_stretch": float(stretch.get("dispersion", 9.0)) <= 0.01,
			"silhouette_note": "以下为**像素副口径**（正交剪影 + 累积面积剖面），噪声底 ~0.006（224x312 分辨率下的行量化）",
			"height_ratio_sy_px": snappedf(sy_px, 0.00001),
			"height_ratio_sy_area": snappedf(sy_area, 0.00001),
			"height_gain_pct_area": snappedf(100.0 * (sy_area - 1.0), 0.01),
			"profile_rel_dev": ratios, "profile_mean_rel_dev": snappedf(mean, 0.00001),
			"dispersion": snappedf(sd, 0.00001),
			"dispersion_definition": "std(累积面积剖面相对偏差)", "pass_le_0.01": sd <= 0.01,
			"profile_h1": b1, "profile_h2": b2}
	set_ortho(false)                                   # 还原透视，别影响后续测量
	out["camera"] = "PROJECTION_ORTHOGONAL（只用于身高一致性；穿模计数仍是透视）"
	out["bone_matrix_dispersion"] = RIG.probe_height_impl(avatar, h)
	out["bone_matrix_dispersion"]["note"] = ("逐骨线性缩放离散度（纯矩阵，与 verifier 的 Blender 口径同义）："
		+ "node_scale 模式下骨骼 pose 完全没动 → 逐骨缩放恒为 1；"
		+ "bone_root_scale 模式在 Godot 里按骨层级继承（Godot 的 Skeleton3D **没有** Blender 的 "
		+ "inherit_scale 标志），所以它与 Blender 侧行为不一定一致 —— 这两列就是用来当场对账的。")
	return out