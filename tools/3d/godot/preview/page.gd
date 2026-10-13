extends RefCounted
## 舞台与取景（页面版）。3D 内容可以直接挂在**窗口视口**（交互模式）
## 或挂在**固定尺寸 SubViewport**（离屏出图），两种模式共用同一套代码。
##
## 取景的关键：**按最坏情况**（最高 1.08×、最宽的发型/张开的服装）算相机距离，
## 这样滑块拉到任何值都**不会裁切**（四边留白 > 0 是硬验收项）。

const CFG = preload("res://cfg.gd")
const ST = preload("res://stage.gd")
const UF = preload("res://uifont.gd")

## 页面里角色的最坏包络（米）：标准体静止 z 上限 ~1.79，×1.08 + 头发余量。
## 半宽 0.62 是**放下手臂(A-pose)之后**的值，同时要容下 0.52 处的 1 m 标尺。
const ENV_TOP := 2.02
const ENV_HALF_X := 0.62
const ENV_HALF_Z := 0.55

static func make_stage(host: Node, bg := Color(0.105, 0.11, 0.125), helpers := true) -> Dictionary:
	ST.make_env(host, bg)
	var cam := Camera3D.new()
	cam.name = "PreviewCamera"
	cam.fov = 34.0
	host.add_child(cam)
	cam.current = true
	var hs: Array = []
	if helpers:
		hs.append(ST.make_ground_bar(host))
		hs.append_array(ST.make_scale_bar(host, 1.0, 0.52))
	return {"cam": cam, "helpers": hs, "bg": bg}

## 量"四边留白"时先把辅助几何（地线/标尺）藏掉：
## 它们虽然小，但只要碰到画面下边缘就会把 min_margin 打成 0（假阳性）。
static func set_helpers_visible(stage: Dictionary, v: bool) -> void:
	for h in stage.get("helpers", []):
		if h != null and is_instance_valid(h):
			(h as Node3D).visible = v

static func worst_corners() -> Array:
	var out: Array = []
	for sx in [-1.0, 1.0]:
		for sz in [-1.0, 1.0]:
			for y in [0.0, ENV_TOP]:
				out.append(Vector3(sx * ENV_HALF_X, y, sz * ENV_HALF_Z))
	return out

## 单角色取景：自动缩放到"最坏包络（+ 标签角点）"刚好装下，再横向平移让角色落在 focus_x_px。
## 返回取景报告（供 JSON 证据）。
static func frame_single(cam: Camera3D, size: Vector2i, focus_x_px: float,
		extra_pts: Array = [], margin := 1.14) -> Dictionary:
	var corners := worst_corners()
	corners.append_array(extra_pts)
	var fit := ST.auto_frame(cam, corners, cam.fov, 7.0, margin, Vector2(size))
	if fit.has("error"):
		return fit
	# 横向对齐：迭代几次把"角色中轴"投到 focus_x_px
	for _i in 4:
		var s: Vector2 = cam.unproject_position(Vector3(0, ENV_TOP * 0.5, 0))
		var dx_px := s.x - focus_x_px
		if absf(dx_px) < 1.0:
			break
		var d: float = cam.global_position.distance_to(Vector3(0, ENV_TOP * 0.5, 0))
		var world_per_px: float = 2.0 * d * tan(deg_to_rad(cam.fov) * 0.5) / float(size.y)
		var right: Vector3 = cam.global_transform.basis.x.normalized()
		var shift: Vector3 = right * (dx_px * world_per_px)
		cam.global_position = cam.global_position + shift
		var target: Vector3 = Vector3(0, ENV_TOP * 0.5, 0) + shift
		cam.look_at(target, Vector3.UP)
	fit["focus_x_px"] = focus_x_px
	fit["envelope"] = {"top": ENV_TOP, "half_x": ENV_HALF_X, "half_z": ENV_HALF_Z}
	fit["extra_pts"] = extra_pts
	return fit

## Label3D 的世界占位估算（billboard 文字没有可信 AABB，得手算，用来参与取景）。
static func label_corners(pos: Vector3, text: String, fsize: int, pix: float) -> Array:
	var w: float = maxf(0.4, float(text.length()) * 0.5 * float(fsize) * pix)
	var hh: float = 0.8 * float(fsize) * pix
	return [pos + Vector3(-w * 0.5, -hh * 0.5, 0.0), pos + Vector3(w * 0.5, hh * 0.5, 0.0)]

## 多角色拼图取景：把给出的世界点全部框进去。
static func frame_points(cam: Camera3D, pts: Array, size: Vector2i, fov := 34.0,
		pitch := 7.0, margin := 1.09) -> Dictionary:
	return ST.auto_frame(cam, pts, fov, pitch, margin, Vector2(size))

static func label3d(text: String, pos: Vector3, fsize: int, pix: float, col := Color(1, 0.94, 0.6)) -> Label3D:
	var l := Label3D.new()
	l.text = text
	l.font_size = fsize
	l.pixel_size = pix
	l.position = pos
	l.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	l.no_depth_test = true
	l.outline_size = 16
	l.shaded = false
	l.modulate = col
	return l

## 给一个角色部件整体换 albedo 颜色（发型"着色变体"用，证明贴图/材质在）。
static func tint(n: Node, col: Color) -> void:
	if n is MeshInstance3D:
		var mi := n as MeshInstance3D
		if mi.mesh:
			for s in mi.mesh.get_surface_count():
				var m := mi.get_active_material(s)
				if m is StandardMaterial3D:
					var mm: StandardMaterial3D = (m as StandardMaterial3D).duplicate()
					mm.albedo_color = col
					mi.set_surface_override_material(s, mm)
	for c in n.get_children():
		tint(c, col)