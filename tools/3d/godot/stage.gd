extends RefCounted
## 渲染舞台工具：SubViewport 离屏渲染 + 环境光 + 相机自动取景（迭代式防裁切）。
##
## 两个实测坑：
## 1) 相机必须用 look_at_from_position()（look_at 在节点未入树/无父视口时不可靠），
##    且必须先 add_child 进视口，unproject_position 才有正确的视口尺寸。
## 2) 直接渲染 root 视口时，「窗口尺寸」会被 macOS 屏幕限制（实测 2560 只能得到 2446），
##    所以改用固定尺寸的 SubViewport 离屏渲染，分辨率完全可控。

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
	e.ambient_light_energy = 0.8
	var we := WorldEnvironment.new()
	we.environment = e
	vp.add_child(we)
	var key := DirectionalLight3D.new()
	key.rotation_degrees = Vector3(-42, -34, 0)
	key.light_energy = 1.35
	vp.add_child(key)
	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-16, 150, 0)
	fill.light_energy = 0.45
	vp.add_child(fill)


## 收集一个已加入场景树的实例的全部网格 AABB 端点（世界坐标）。
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


## 迭代式自动取景：把 corners 全部投影到屏幕，按需要的比例反推相机距离。
## pitch_deg > 0 = 相机在物体的上前方俯视；= 0 = 正视图。
## size_override：显式给视口尺寸。坑：在 SceneTree._initialize() 里刚 add_child 的节点
## 还没真正入树，cam.get_viewport() 会返回 null（实测），所以要么先 await 一帧，要么显式传尺寸。
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
			return {"error": "camera 不在任何视口内，无法取景（先 await 一帧再建场景）"}
		size = vp.get_visible_rect().size
	var pitch := deg_to_rad(pitch_deg)
	var dir := Vector3(0, sin(pitch), cos(pitch))
	var d: float = maxf((hi - lo).length(), 1.0)
	var last := {}
	for i in 24:
		cam.fov = fov_deg
		cam.look_at_from_position(center + dir * d, center, Vector3.UP)
		var mn := Vector2(1e9, 1e9)
		var mx := Vector2(-1e9, -1e9)
		for p in corners:
			var s: Vector2 = cam.unproject_position(p)
			mn = mn.min(s)
			mx = mx.max(s)
		var ext := mx - mn
		last = {"screen_min": mn, "screen_max": mx, "extent": ext, "viewport": size, "dist": d,
			"center": center}
		# margin 必须“缩”目标而不是“放”：内容最多占视口的 1/margin。
		# 写反成 ext/(size*margin) 会让目标比视口还大 → 内容顶到边缘（实测踩过）。
		var ratio: float = maxf(ext.x * margin / size.x, ext.y * margin / size.y)
		if absf(ratio - 1.0) < 0.004:
			break
		d *= ratio
	return last


static func save(vp: SubViewport, name: String) -> Dictionary:
	var img := vp.get_texture().get_image()
	var p := ProjectSettings.globalize_path("res://" + name)
	var err := img.save_png(p)
	var d := {"size": img.get_size(), "err": err, "path": p}
	print("SAVED ", name, " ", d)
	return d


## 非背景像素的包围盒（判断有没有被裁切 / 是不是空图），并统计“彩色度”以排除灰白丢材质。
static func image_stats(img: Image, bg: Color, tol := 0.06) -> Dictionary:
	var w := img.get_width()
	var h := img.get_height()
	var mn := Vector2i(w, h)
	var mx := Vector2i(-1, -1)
	var count := 0
	var sat_sum := 0.0
	var rsum := 0.0
	var gsum := 0.0
	var bsum := 0.0
	for y in h:
		for x in w:
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
		return {"count": 0}
	return {"count": count, "min": mn, "max": mx,
		"bbox_px": [mx.x - mn.x + 1, mx.y - mn.y + 1],
		"margin_px": {"l": mn.x, "t": mn.y, "r": w - 1 - mx.x, "b": h - 1 - mx.y},
		"mean_rgb": [snappedf(rsum / count, 0.001), snappedf(gsum / count, 0.001), snappedf(bsum / count, 0.001)],
		"mean_saturation": snappedf(sat_sum / count, 0.001),
		"fill_pct": snappedf(100.0 * count / float(w * h), 2)}