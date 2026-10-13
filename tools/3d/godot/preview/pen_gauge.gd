extends Control
## 穿模指示器：把**离线预算**的「穿模率 vs 体形 k」曲线画出来，并标出当前滑块位置。
##
## 这不是"看起来像穿模"，而是一条可复算的客观曲线：
## `blender/penetration.py` 在每个 k 上用身体的变形网格建 BVH，
## 对服装每个顶点算「最近点 + 最近面法线」的有符号间隙，间隙 < -2mm 记为穿模。

const CFG = preload("res://cfg.gd")
const UF = preload("res://uifont.gd")

var ks: Array = []                 ## 曲线的 k 采样点
var pen: Array = []                ## 对应的穿模率（%）
var gaps: Array = []               ## 对应的最小间隙（mm，负 = 穿进去了）
var marker_k: float = 0.0
var label: String = ""
var subtitle: String = ""
var threshold: float = CFG.PEN_THRESHOLD_PCT
var threshold_note := ""
var maxes: Array = []                ## 对应的最坏方位角穿模率（%）
var n_verts: int = 0
var unavailable: String = ""

func _ready() -> void:
	custom_minimum_size = Vector2(0, 214)
	mouse_filter = Control.MOUSE_FILTER_IGNORE

static func pen_at(ks_arr: Array, pen_arr: Array, k: float) -> float:
	if ks_arr.is_empty() or pen_arr.is_empty():
		return 0.0
	if k <= float(ks_arr[0]):
		return float(pen_arr[0])
	if k >= float(ks_arr[ks_arr.size() - 1]):
		return float(pen_arr[pen_arr.size() - 1])
	for i in range(ks_arr.size() - 1):
		var a := float(ks_arr[i])
		var b := float(ks_arr[i + 1])
		if k >= a and k <= b:
			var t: float = 0.0 if b == a else (k - a) / (b - a)
			return lerpf(float(pen_arr[i]), float(pen_arr[i + 1]), t)
	return 0.0

static func first_k(ks_arr: Array, pen_arr: Array, thr: float) -> Variant:
	for i in ks_arr.size():
		if float(pen_arr[i]) > thr:
			return float(ks_arr[i])
	return null

func _draw() -> void:
	var font: Font = UF.cjk()
	if font == null:
		font = ThemeDB.fallback_font  # 没有中文字体时至少不崩；标签会回落英文
	var fs := 13
	var pad := 10.0
	var gutter_l := 42.0      # 左侧留给 % 刻度
	var gutter_b := 30.0      # 底部留给 k 刻度 + 脚注
	var header := 58.0        # 顶部留给标题 + "当前值"那行
	var r := Rect2(Vector2(pad + gutter_l, header),
		Vector2(maxf(10.0, size.x - pad * 2 - gutter_l), maxf(10.0, size.y - header - gutter_b)))
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.09, 0.10, 0.12, 0.92), true)
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.35, 0.38, 0.45), false, 1.0)
	draw_string(font, Vector2(pad, 18), label, HORIZONTAL_ALIGNMENT_LEFT, -1, fs + 1,
		Color(0.95, 0.95, 0.98))
	if unavailable != "":
		draw_string(font, Vector2(pad, 52), unavailable, HORIZONTAL_ALIGNMENT_LEFT, -1, fs,
			Color(0.85, 0.6, 0.35))
		return
	if ks.is_empty() or pen.is_empty():
		draw_string(font, Vector2(pad, 52), UF.T("（无服装，无穿模数据）", "(no garment)"),
			HORIZONTAL_ALIGNMENT_LEFT, -1, fs, Color(0.7, 0.7, 0.75))
		return
	# y 轴上限：至少让阈值线在图上可见
	var mx := threshold * 2.0
	for v in pen:
		mx = maxf(mx, float(v))
	mx = maxf(mx, 1.0)
	mx *= 1.15
	var x_of := func(k: float) -> float:
		return r.position.x + r.size.x * (k - CFG.K_MIN) / (CFG.K_MAX - CFG.K_MIN)
	var y_of := func(p: float) -> float:
		return r.position.y + r.size.y * (1.0 - p / mx)
	# 网格 + 轴刻度
	for i in 5:
		var pv: float = mx * float(i) / 4.0
		var y: float = y_of.call(pv)
		draw_line(Vector2(r.position.x, y), Vector2(r.position.x + r.size.x, y),
			Color(0.22, 0.24, 0.28), 1.0)
		draw_string(font, Vector2(pad, y + 4), "%.1f%%" % pv, HORIZONTAL_ALIGNMENT_LEFT, -1, 10,
			Color(0.55, 0.58, 0.64))
	for kk in [-1.0, -0.5, 0.0, 0.5, 1.0]:
		var x: float = x_of.call(kk)
		draw_line(Vector2(x, r.position.y), Vector2(x, r.position.y + r.size.y),
			Color(0.20, 0.22, 0.26), 1.0)
		draw_string(font, Vector2(x - 10, r.position.y + r.size.y + 14), "%+.1f" % kk,
			HORIZONTAL_ALIGNMENT_LEFT, -1, 10, Color(0.55, 0.58, 0.64))
	# 阈值线（虚线）
	var yt: float = y_of.call(threshold)
	var xd := r.position.x
	while xd < r.position.x + r.size.x:
		draw_line(Vector2(xd, yt), Vector2(minf(xd + 7.0, r.position.x + r.size.x), yt),
			Color(0.95, 0.72, 0.25, 0.9), 1.5)
		xd += 12.0
	var thr_txt := UF.T("阈值 %.1f%%" % threshold, "thr %.1f%%" % threshold)
	if threshold_note != "":
		thr_txt += "  (" + threshold_note + ")"
	draw_string(font, Vector2(r.position.x + r.size.x - 118, yt - 4), thr_txt,
		HORIZONTAL_ALIGNMENT_LEFT, -1, 10, Color(0.95, 0.72, 0.25))
	# 曲线本体：阈值以上涂红
	var pts := PackedVector2Array()
	for i in ks.size():
		pts.append(Vector2(x_of.call(float(ks[i])), y_of.call(float(pen[i]))))
	var warn := false
	for i in pen.size():
		if float(pen[i]) > threshold:
			warn = true
	draw_polyline(pts, Color(0.35, 0.85, 0.85) if not warn else Color(0.95, 0.45, 0.35), 2.5, true)
	for p in pts:
		draw_circle(p, 3.0, Color(0.95, 0.95, 0.98))
	# 当前 k 的标记
	var xm: float = x_of.call(clampf(marker_k, CFG.K_MIN, CFG.K_MAX))
	draw_line(Vector2(xm, r.position.y), Vector2(xm, r.position.y + r.size.y),
		Color(0.55, 0.85, 1.0), 2.0)
	var cur := pen_at(ks, pen, marker_k)
	draw_circle(Vector2(xm, y_of.call(cur)), 5.0, Color(0.55, 0.85, 1.0))
	var g := 0.0
	if maxes.size() == pen.size() and not maxes.is_empty():
		g = pen_at(ks, maxes, marker_k)
	var fk: Variant = first_k(ks, pen, threshold)
	var tail := ""
	if fk != null:
		tail = UF.T("  起始穿模 k=%+.2f" % float(fk), "  first pen k=%+.2f" % float(fk))
	else:
		tail = UF.T("  全程未超阈值", "  below threshold all the way")
	draw_string(font, Vector2(pad, 38),
		UF.T("当前 k=%+.2f → 穿模率 %.2f%%（最坏方位 %.2f%%）%s"
			% [marker_k, cur, g, tail],
			"k=%+.2f -> pen %.2f%% (worst azimuth %.2f%%)%s" % [marker_k, cur, g, tail]),
		HORIZONTAL_ALIGNMENT_LEFT, -1, fs, Color(1, 0.85, 0.55) if cur > threshold else Color(0.75, 0.95, 0.8))
	if subtitle != "":
		draw_string(font, Vector2(pad, size.y - 4), subtitle, HORIZONTAL_ALIGNMENT_LEFT, -1, 10,
			Color(0.6, 0.63, 0.7))