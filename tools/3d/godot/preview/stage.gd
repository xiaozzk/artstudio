extends RefCounted
## 渲染舞台（改写自 `tools/3d/godot/stage.gd`，口径一致）+ 绝对路径存图。
##
## 两个实测坑（沿用上游注释）：
## 1) 相机必须 `look_at_from_position()`（`look_at()` 在节点未入树/无父视口时不可靠），
##    且必须先入视口 `unproject_position()` 才有正确视口尺寸。
## 2) 直接渲染 root 视口时窗口尺寸会被屏幕限制（2560 只能得到 2446），
##    所以固定尺寸 `SubViewport` 离屏渲染，分辨率完全可控。
##
## 本页新增：`save_abs()` —— 截图要落到 `assets/3d/rig/previews/`（**工程目录之外**），
## 不能用 `res://`（`res://` 跳不出工程根）。

const LDR = preload("res://loader.gd")

static func make_viewport(tree: SceneTree, w: int, h: int) -> SubViewport:
	var vp := SubViewport.new()
	vp.size = Vector2i(w, h)
	vp.own_world_3d = true
	vp.transparent_bg = false
	vp.msaa_3d = Viewport.MSAA_4X
	vp.screen_space_aa = Viewport.SCREEN_SPACE_AA_FXAA
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	tree.root.add_child(vp)
	return vp

static func make_env(vp: Node, bg := Color(0.105, 0.11, 0.125)) -> void:
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = bg
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(1, 1, 1)
	e.ambient_light_energy = 0.85
	var we := WorldEnvironment.new()
	we.environment = e
	vp.add_child(we)
	var key := DirectionalLight3D.new()
	key.rotation_degrees = Vector3(-42, -34, 0)
	key.light_energy = 1.35
	vp.add_child(key)
	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-16, 150, 0)
	fill.light_energy = 0.5
	vp.add_child(fill)

## ⚠ 不要用"铺满画面的大地面"：它会让**每一像素都不是背景色**，
## 于是 `image_stats` 的"非背景包围盒"变成整张图 → 四边留白全 0，被判成裁切（实测踩过）。
## 改用**短地线 + 1m 标尺**：既有"站在地上"与身高参照，又不会碰到画面边缘。
static func _flat_box(host: Node, name: String, size_v: Vector3, pos: Vector3, col: Color) -> MeshInstance3D:
	var box := BoxMesh.new()
	box.size = size_v
	var mi := MeshInstance3D.new()
	mi.name = name
	mi.mesh = box
	mi.position = pos
	var mat := StandardMaterial3D.new()
	mat.albedo_color = col
	mat.roughness = 1.0
	mi.material_override = mat
	host.add_child(mi)
	return mi

static func make_ground_bar(host: Node, w := 1.15, d := 0.55, y := -0.012, x := 0.0) -> MeshInstance3D:
	return _flat_box(host, "GroundBar", Vector3(w, 0.024, d), Vector3(x, y, 0),
		Color(0.30, 0.32, 0.36))

## 1 米标尺：身高滑块拉 ±8% 时，肉眼对着它一眼就能读出来。
static func make_scale_bar(host: Node, height_m := 1.0, x := 0.52, col := Color(0.72, 0.76, 0.84)) -> Array:
	var out: Array = []
	out.append(_flat_box(host, "ScaleBar", Vector3(0.016, height_m, 0.016),
		Vector3(x, height_m * 0.5, 0.0), col))
	out.append(_flat_box(host, "ScaleCap", Vector3(0.10, 0.014, 0.016),
		Vector3(x - 0.042, height_m, 0.0), col))
	out.append(_flat_box(host, "ScaleCap0", Vector3(0.10, 0.014, 0.016),
		Vector3(x - 0.042, 0.0, 0.0), col))
	return out

## 收集一个实例的全部网格 AABB 端点（世界坐标）。
static func corners_of(inst: Node) -> Array:
	var tx := LDR.taxonomy(inst)
	var out: Array = []
	if tx["meshes"] == 0:
		return out
	var lo: Vector3 = tx["aabb_min"]
	var hi: Vector3 = tx["aabb_max"]
	for i in 8:
		out.append(Vector3(lo.x if (i & 1) == 0 else hi.x,
			lo.y if (i & 2) == 0 else hi.y,
			lo.z if (i & 4) == 0 else hi.z))
	return out

## 迭代式自动取景：corners 全部投影到屏幕，按需要比例反推相机距离。
## margin 必须"缩"目标而不是"放"：内容最多占视口的 1/margin。
static func auto_frame(cam: Camera3D, corners: Array, fov_deg: float, pitch_deg: float,
		margin := 1.06, size_override := Vector2.ZERO) -> Dictionary:
	var lo := Vector3(1e9, 1e9, 1e9)
	var hi := Vector3(-1e9, -1e9, -1e9)
	for p in corners:
		lo = lo.min(p)
		hi = hi.max(p)
	var center := (lo + hi) * 0.5
	var size := size_override
	if size == Vector2.ZERO:
		var vp := cam.get_viewport()
		if vp == null:
			return {"error": "camera 不在任何视口内，无法取景"}
		size = vp.get_visible_rect().size
	var pitch := deg_to_rad(pitch_deg)
	var dir := Vector3(0, sin(pitch), cos(pitch))
	var d: float = maxf((hi - lo).length(), 1.0)
	var last := {}
	for i in 32:
		cam.fov = fov_deg
		cam.look_at_from_position(center + dir * d, center, Vector3.UP)
		var mn := Vector2(1e9, 1e9)
		var mx := Vector2(-1e9, -1e9)
		for p in corners:
			var s: Vector2 = cam.unproject_position(p)
			mn = mn.min(s)
			mx = mx.max(s)
		var ext := mx - mn
		last = {"screen_min": mn, "screen_max": mx, "extent": ext, "viewport": size,
			"dist": d, "center": center}
		var ratio: float = maxf(ext.x * margin / size.x, ext.y * margin / size.y)
		if absf(ratio - 1.0) < 0.004:
			break
		d *= ratio
	return last

## 存到**绝对路径**（工程外，例如 assets/3d/rig/previews/）。
static func save_abs(img: Image, abs_path: String) -> Dictionary:
	var d := DirAccess.open(abs_path.get_base_dir())
	if d == null:
		DirAccess.make_dir_recursive_absolute(abs_path.get_base_dir())
	var err := img.save_png(abs_path)
	print("SAVED ", abs_path, " err=", err, " size=", img.get_size())
	return {"path": abs_path, "err": err, "size": [img.get_width(), img.get_height()]}

## 非背景像素包围盒（判裁切/空图）+ "彩色度"（排除灰白丢材质）。
## region 非空时只在这个矩形内统计（页面截图要把右侧 UI 面板排除掉，否则面板顶到右边缘 → 假阳性）。
## ⚠ 背景里**不要**放会铺满画面的地面：那样"非背景"= 整张图，留白恒为 0（实测踩过）。
static func image_stats(img: Image, bg: Color, tol := 0.06, region := Rect2i()) -> Dictionary:
	var w := img.get_width()
	var h := img.get_height()
	var rt := region if region.size.x > 0 and region.size.y > 0 else Rect2i(0, 0, w, h)
	var x0 := maxi(0, rt.position.x)
	var y0 := maxi(0, rt.position.y)
	var x1 := mini(w - 1, rt.position.x + rt.size.x - 1)
	var y1 := mini(h - 1, rt.position.y + rt.size.y - 1)
	var mn := Vector2i(x1 + 1, y1 + 1)
	var mx := Vector2i(x0 - 1, y0 - 1)
	var count := 0
	var sat_sum := 0.0
	var rsum := 0.0
	var gsum := 0.0
	var bsum := 0.0
	for y in range(y0, y1 + 1):
		for x in range(x0, x1 + 1):
			var c := img.get_pixel(x, y)
			if absf(c.r - bg.r) > tol or absf(c.g - bg.g) > tol or absf(c.b - bg.b) > tol:
				count += 1
				mn.x = mini(mn.x, x)
				mn.y = mini(mn.y, y)
				mx.x = maxi(mx.x, x)
				mx.y = maxi(mx.y, y)
				var m: float = maxf(c.r, maxf(c.g, c.b))
				var n: float = minf(c.r, minf(c.g, c.b))
				sat_sum += (m - n) / maxf(m, 0.001)
				rsum += c.r
				gsum += c.g
				bsum += c.b
	if count == 0:
		return {"count": 0, "margin_px": {"l": 0, "t": 0, "r": 0, "b": 0}, "cropped": true,
			"region": [x0, y0, x1 - x0 + 1, y1 - y0 + 1]}
	var margins := {"l": mn.x - x0, "t": mn.y - y0, "r": x1 - mx.x, "b": y1 - mx.y}
	var min_margin := mini(mini(margins["l"], margins["t"]), mini(margins["r"], margins["b"]))
	return {"count": count, "min": [mn.x, mn.y], "max": [mx.x, mx.y],
		"region": [x0, y0, x1 - x0 + 1, y1 - y0 + 1],
		"bbox_px": [mx.x - mn.x + 1, mx.y - mn.y + 1], "margin_px": margins,
		"min_margin_px": min_margin, "cropped": min_margin <= 0,
		"mean_rgb": [snappedf(rsum / count, 0.001), snappedf(gsum / count, 0.001), snappedf(bsum / count, 0.001)],
		"mean_saturation": snappedf(sat_sum / count, 0.001),
		"fill_pct": snappedf(100.0 * count / float(w * h), 2)}