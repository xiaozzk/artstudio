extends RefCounted
## 舞台：**固定尺寸** SubViewport 离屏渲染 + 环境光/方向光 + 棋盘地线 + 1 m 标尺
##     + 手写轨道相机 + 自动取景。
##
## 实测坑（踩过，写下来省一轮）：
## 1) 相机必须先 add_child 进视口，`unproject_position()` / `look_at_from_position()` 才可信；
## 2) 自动取景**不能用 `MeshInstance3D.get_aabb()`**（静止 AABB，不随 morph 变）
##    —— 传进来的是按当前 morph 解析式复算出的世界 AABB；
## 3) `var d := max(...)` 因返回 Variant 会**编译失败** → 一律写显式类型 `var d: float = maxf(...)`；
## 4) SubViewport 尺寸固定 960x900，**不跟随窗口**，这样出图分辨率完全可控。

const BG := Color(0.105, 0.11, 0.125)
const UNSHADED := BaseMaterial3D.SHADING_MODE_UNSHADED

static func make(w: int = 960, h: int = 900) -> Dictionary:
	var vp := SubViewport.new()
	vp.name = "StageViewport"
	vp.size = Vector2i(w, h)
	vp.own_world_3d = true
	vp.transparent_bg = false
	vp.msaa_3d = Viewport.MSAA_4X
	vp.screen_space_aa = Viewport.SCREEN_SPACE_AA_FXAA
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = BG
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(1, 1, 1)
	env.ambient_light_energy = 0.85
	var we := WorldEnvironment.new()
	we.environment = env
	vp.add_child(we)
	var key := DirectionalLight3D.new()
	key.rotation_degrees = Vector3(-42, -34, 0)
	key.light_energy = 1.3
	vp.add_child(key)
	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-16, 150, 0)
	fill.light_energy = 0.45
	vp.add_child(fill)
	var cam := Camera3D.new()
	cam.name = "OrbitCamera"
	cam.fov = 34.0
	vp.add_child(cam)
	cam.current = true
	var st := {"vp": vp, "cam": cam, "yaw": 0.0, "pitch": 7.0, "dist": 4.2,
		"target": Vector3(0, 0.95, 0), "helpers": [], "bg": BG, "size": Vector2i(w, h)}
	st["helpers"].append(make_ground())
	st["helpers"].append_array(make_ruler())
	for n in st["helpers"]:
		vp.add_child(n)
	place(st)
	return st

## 棋盘地线：每格 0.5 m（贴图一块 = 2 m，uv1_scale=6 → 12 m 地面共 24 格）。
static func make_ground() -> MeshInstance3D:
	var n := 64
	var img := Image.create(n, n, false, Image.FORMAT_RGB8)
	for y in n:
		for x in n:
			var c: float = 0.17 if ((x / 16) + (y / 16)) % 2 == 0 else 0.24
			img.set_pixel(x, y, Color(c, c, c))
	var mat := StandardMaterial3D.new()
	mat.albedo_texture = ImageTexture.create_from_image(img)
	mat.uv1_scale = Vector3(6, 6, 1)
	mat.roughness = 0.95
	var plane := PlaneMesh.new()
	plane.size = Vector2(12, 12)
	plane.material = mat
	var mi := MeshInstance3D.new()
	mi.name = "Ground_Checker_0p5m"
	mi.mesh = plane
	return mi

## 1 m 标尺（放在 x=+0.62 m 处；刻度 0.25/0.5/0.75/1.0）。地线与标尺都**不随 h 缩放**，是绝对参照。
static func make_ruler() -> Array:
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(1.0, 0.86, 0.35)
	mat.shading_mode = UNSHADED
	var out: Array = []
	var x := 0.62
	out.append(_bar("Ruler_1m", Vector3(0.010, 1.0, 0.010), Vector3(x, 0.5, 0), mat))
	for yv in [0.25, 0.5, 0.75, 1.0]:
		var y := float(yv)
		out.append(_bar("Ruler_tick_%d" % int(y * 100), Vector3(0.075, 0.008, 0.010),
			Vector3(x + 0.037, y, 0), mat))
	var lab := Label3D.new()
	lab.text = "1 m"
	lab.font_size = 40
	lab.pixel_size = 0.0022
	lab.position = Vector3(x + 0.20, 1.02, 0)
	lab.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	lab.no_depth_test = true
	lab.shaded = false
	lab.modulate = Color(1.0, 0.86, 0.35)
	lab.outline_size = 12
	out.append(lab)
	return out

static func _bar(nm: String, size: Vector3, pos: Vector3, mat: Material) -> MeshInstance3D:
	var bm := BoxMesh.new()
	bm.size = size
	bm.material = mat
	var mi := MeshInstance3D.new()
	mi.name = nm
	mi.mesh = bm
	mi.position = pos
	return mi

## 轨道相机：yaw 绕 Y、pitch 抬降。pitch>0 = 相机在物体上前方俯视。
static func place(st: Dictionary) -> void:
	var pitch := deg_to_rad(float(st["pitch"]))
	var yaw := deg_to_rad(float(st["yaw"]))
	var dir := Vector3(sin(yaw) * cos(pitch), sin(pitch), cos(yaw) * cos(pitch))
	var cam: Camera3D = st["cam"]
	cam.look_at_from_position((st["target"] as Vector3) + dir * float(st["dist"]),
		st["target"], Vector3.UP)

static func orbit(st: Dictionary, dx_px: float, dy_px: float) -> void:
	st["yaw"] = wrapf(float(st["yaw"]) - dx_px * 0.35, -180.0, 180.0)
	st["pitch"] = clampf(float(st["pitch"]) + dy_px * 0.25, -35.0, 80.0)
	place(st)

static func zoom(st: Dictionary, notches: float) -> void:
	st["dist"] = clampf(float(st["dist"]) * pow(1.12, -notches), 0.4, 40.0)
	place(st)

## 自动取景：把 AABB 的 8 个端点投影进固定尺寸视口，反推相机距离（迭代 26 次）。
## margin>1 = 内容最多占视口的 1/margin（**缩**目标，写反会让内容顶到边缘——实测踩过）。
## 返回几何留白（px），四边必须 >0；这是**几何**留白，不是像素统计。
static func frame(st: Dictionary, box: AABB, margin: float = 1.10) -> Dictionary:
	if box.size.length() <= 0.0:
		return {"ok": false, "error": "没有可见几何，无法取景", "margin_px": {}}
	var corners: Array = []
	for i in 8:
		corners.append(box.get_endpoint(i))
	st["target"] = box.get_center()
	var size: Vector2 = Vector2(st["size"])
	var d: float = maxf(box.size.length(), 0.6)
	var last := {"ok": false, "margin_px": {}}
	for _i in 26:
		st["dist"] = d
		place(st)
		var mn := Vector2(1e9, 1e9)
		var mx := Vector2(-1e9, -1e9)
		for p in corners:
			var s: Vector2 = (st["cam"] as Camera3D).unproject_position(p)
			mn = mn.min(s)
			mx = mx.max(s)
		var ext := mx - mn
		last = {"ok": true, "dist": snappedf(d, 0.001), "extent_px": [ext.x, ext.y],
			"viewport": [size.x, size.y], "aabb_size_m": [box.size.x, box.size.y, box.size.z],
			"margin_px": {"l": snappedf(mn.x, 0.1), "t": snappedf(mn.y, 0.1),
				"r": snappedf(size.x - mx.x, 0.1), "b": snappedf(size.y - mx.y, 0.1)}}
		var ratio: float = maxf(ext.x * margin / size.x, ext.y * margin / size.y)
		if absf(ratio - 1.0) < 0.003:
			break
		d *= ratio
	st["dist"] = d
	place(st)
	return last

static func snapshot(st: Dictionary) -> Image:
	var vp: SubViewport = st["vp"]
	return vp.get_texture().get_image()

## 出图「是不是空白」的客观判据：以左上角像素为背景基线，统计非背景占比（左显示区 / 右面板分开算）
## + 量化颜色数。用来杜绝「PNG 是均匀灰底、退出码却 0」这种静默说谎。
static func page_stats(img: Image, panel_frac := 0.36, step := 2) -> Dictionary:
	var w := img.get_width()
	var h := img.get_height()
	if w < 2 or h < 2:
		return {"size": [w, h], "colors": 0, "non_bg_pct": 0.0,
			"left_non_bg_pct": 0.0, "right_non_bg_pct": 0.0}
	var bg := img.get_pixel(0, 0)
	var split: int = int(float(w) * (1.0 - panel_frac))
	var colors := {}
	var colors_fine := {}
	var nb := 0
	var total := 0
	var ln := 0
	var lnb := 0
	var rn := 0
	var rnb := 0
	var y := 0
	while y < h:
		var x := 0
		while x < w:
			var c := img.get_pixel(x, y)
			var d: float = maxf(absf(c.r - bg.r), maxf(absf(c.g - bg.g), absf(c.b - bg.b)))
			var is_nb := d > 0.02
			colors[int(c.r * 16.0) * 4096 + int(c.g * 16.0) * 256 + int(c.b * 16.0)] = true
			colors_fine[int(c.r * 32.0) * 1024 + int(c.g * 32.0) * 32 + int(c.b * 32.0)] = true
			total += 1
			if is_nb:
				nb += 1
			if x < split:
				ln += 1
				if is_nb:
					lnb += 1
			else:
				rn += 1
				if is_nb:
					rnb += 1
			x += step
		y += step
	return {"size": [w, h], "sampled": total, "colors": colors.size(),
		"colors_fine": colors_fine.size(), "step": step,
		"non_bg_pct": snappedf(100.0 * float(nb) / maxf(float(total), 1.0), 2),
		"left_non_bg_pct": snappedf(100.0 * float(lnb) / maxf(float(ln), 1.0), 2),
		"right_non_bg_pct": snappedf(100.0 * float(rnb) / maxf(float(rn), 1.0), 2),
		"bg_corner": [snappedf(bg.r, 0.001), snappedf(bg.g, 0.001), snappedf(bg.b, 0.001)]}

## 出图**一律绝对路径**：相对路径会写进 res://，把「零素材副本」变成假话。
static func save_png_abs(img: Image, abs_path: String) -> Dictionary:
	if not abs_path.is_absolute_path():
		push_error("截图必须写绝对路径（相对路径会落进 res://）：%s" % abs_path)
		return {"ok": false, "err": "not_absolute", "path": abs_path}
	var dir := abs_path.get_base_dir()
	if dir != "" and not DirAccess.dir_exists_absolute(dir):
		DirAccess.make_dir_recursive_absolute(dir)
	var err := img.save_png(abs_path)
	return {"ok": err == OK, "err": err, "path": abs_path, "size": img.get_size()}
