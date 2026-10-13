extends Control
## 交互预览页面（T3 主界面）。
##
## 约束（SPEC §3.3/§3.4）：
##   * 一个连续的体形滑块 `k ∈ [-1,1]` → `BS_Thin=max(-k,0)` / `BS_Heavy=max(k,0)`，
##     **同时**驱动身体与每一件服装（同名同序契约，逐件写进读数与 JSON）。
##   * 身高滑块 `h ∈ [0.92,1.08]` → 骨架 `root` 等比缩放（**不做 morph**）。
##   * 换装（Ranger/Peasant，男女各一套）+ 换发型（挂 Head 骨的 6 款）。
##   * 实时读数：逐部件的 morph 值 + 网格/骨架数 + **按名字取到的骨索引**。
##   * 穿模指示：离线预算的「穿模率 vs k」曲线 + 当前标记。
##
## 本控件可以挂在窗口视口（交互模式）或固定尺寸 SubViewport（离屏出图）—— 同一套代码。

const CFG = preload("res://cfg.gd")
const RIG = preload("res://rig.gd")
const ST = preload("res://stage.gd")
const BAKE = preload("res://bake.gd")
const UF = preload("res://uifont.gd")
const PAGE = preload("res://page.gd")
const PenGauge = preload("res://pen_gauge.gd")
const PENP = preload("res://pen_pixel.gd")

const PANEL_W := 566.0
const W_PX := PENP.W
const H_PX := PENP.H

var stage: Dictionary = {}
var avatar: Dictionary = {}
var bake_info: Dictionary = {}
var pen: Dictionary = {}          ## 主指示：Godot **像素法**实测曲线
var pen_ref: Dictionary = {}      ## 参考：Blender BVH 有符号距离（对非闭合网格不可靠，只作方法对照）
var height_uniformity: Dictionary = {}
var penp: RefCounted = null
var live_measure: Dictionary = {}
var status := ""

var family := "Female"
var style := "Ranger"
var hair := "Hair_Long"
var k := 0.0
var h := 1.0
var force_standard_body := false   ## 调试开关：故意把标准体叠上去，复现"多叠一具身体"的穿模

var _panel: PanelContainer
var _opt_family: OptionButton
var _opt_style: OptionButton
var _opt_hair: OptionButton
var _sl_k: HSlider
var _sl_h: HSlider
var _lbl_k: Label
var _lbl_h: Label
var _readout: RichTextLabel
var _gauge: PenGauge
var _src_note: Label
var _status_lbl: Label
var _viewport_size := Vector2i(1500, 960)
var _busy := false
var _suppress := false   ## configure() 期间屏蔽所有控件信号

const STYLES := ["None", "Ranger", "Peasant"]

func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	theme = UF.make_theme(15)
	_build_ui()
	if get_viewport():
		get_viewport().size_changed.connect(_on_viewport_resized)
	_on_viewport_resized()

func _exit_tree() -> void:
	if penp != null:
		penp.destroy()
		penp = null

func _on_viewport_resized() -> void:
	var vp := get_viewport()
	if vp == null:
		return
	var vs := vp.get_visible_rect().size
	_viewport_size = Vector2i(vs)
	size = vs
	if _panel:
		_panel.position = Vector2(vs.x - PANEL_W, 0)
		_panel.size = Vector2(PANEL_W, vs.y)

func _build_ui() -> void:
	_panel = PanelContainer.new()
	_panel.name = "Panel"
	_panel.add_theme_stylebox_override("panel", _panel_style())
	add_child(_panel)
	var margin := MarginContainer.new()
	for s in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + s, 12)
	_panel.add_child(margin)
	var vb := VBoxContainer.new()
	vb.add_theme_constant_override("separation", 6)
	margin.add_child(vb)

	var title := Label.new()
	title.text = UF.T("artstudio · 3D 角色管线 v2 · Godot 预览",
		"artstudio - 3D character pipeline v2 - Godot preview")
	title.add_theme_font_size_override("font_size", 17)
	vb.add_child(title)

	var sub := Label.new()
	sub.text = "SPEC v1.0  §3.3 morph(BS_Thin=0 / BS_Heavy=1 同名同序)  ·  §3.4 身高=角色根节点世界等比缩放"
	sub.add_theme_font_size_override("font_size", 11)
	sub.add_theme_color_override("font_color", Color(0.62, 0.66, 0.74))
	vb.add_child(sub)
	vb.add_child(HSeparator.new())

	_opt_family = _row_opt(vb, UF.T("角色", "Body"), ["Female", "Male"])
	_opt_family.item_selected.connect(func(i: int) -> void:
		if _suppress:
			return
		family = ["Female", "Male"][i]
		_reload())
	_opt_style = _row_opt(vb, UF.T("服装", "Outfit"), STYLES)
	_opt_style.item_selected.connect(func(i: int) -> void:
		if _suppress:
			return
		style = STYLES[i]
		_reload())
	_opt_hair = _row_opt(vb, UF.T("发型", "Hair"), ["None"] + CFG.HAIRS.keys())
	_opt_hair.item_selected.connect(func(i: int) -> void:
		if _suppress:
			return
		hair = (["None"] + CFG.HAIRS.keys())[i]
		_reload())
	var cb := CheckBox.new()
	cb.text = UF.T("叠加标准体（调试：会故意穿模，默认关）",
		"Overlay standard body (debug, off by default)")
	cb.button_pressed = false
	cb.toggled.connect(func(on: bool) -> void:
		if _suppress:
			return
		force_standard_body = on
		_reload())
	vb.add_child(cb)

	_src_note = Label.new()
	_src_note.add_theme_font_size_override("font_size", 11)
	_src_note.add_theme_color_override("font_color", Color(0.72, 0.62, 0.4))
	vb.add_child(_src_note)

	vb.add_child(HSeparator.new())
	_sl_k = _row_slider(vb, UF.T("体形 k  (-1 瘦 ←→ +1 壮)", "Body k  (-1 thin <-> +1 heavy)"),
		CFG.K_MIN, CFG.K_MAX, 0.01, k)
	_lbl_k = _last_slider_label
	_sl_k.value_changed.connect(func(v: float) -> void:
		if _suppress:
			return
		k = v
		_refresh())
	_sl_k.drag_ended.connect(func(changed: bool) -> void:
		_live_measure())
	_sl_h = _row_slider(vb, UF.T("身高 h  (0.92 ←→ 1.08) —— 角色根节点等比缩放，不做 morph",
			"Height h  (0.92 <-> 1.08) - root node uniform scale, no morph"),
		CFG.H_MIN, CFG.H_MAX, 0.002, h)
	_lbl_h = _last_slider_label
	_sl_h.value_changed.connect(func(v: float) -> void:
		if _suppress:
			return
		h = v
		_refresh())

	vb.add_child(HSeparator.new())
	var lr := Label.new()
	lr.text = UF.T("实时读数（逐部件 morph）", "Live readout (per part morph)")
	lr.add_theme_font_size_override("font_size", 13)
	vb.add_child(lr)
	_readout = RichTextLabel.new()
	_readout.bbcode_enabled = false
	_readout.scroll_active = false
	_readout.custom_minimum_size = Vector2(0, 232)
	if UF.mono() != null:
		_readout.add_theme_font_override("normal_font", UF.mono())
	_readout.add_theme_font_size_override("normal_font_size", 12)
	vb.add_child(_readout)

	var lg := Label.new()
	lg.text = UF.T("穿模指示（像素法：身体/服装各换纯色渲一遍，数「被身体盖住的服装像素」占比）",
		"Penetration gauge (pixel method: body vs garment mask)")
	lg.add_theme_font_size_override("font_size", 13)
	vb.add_child(lg)
	_gauge = PenGauge.new()
	vb.add_child(_gauge)

	var hb := HBoxContainer.new()
	vb.add_child(hb)
	var b_reset := Button.new()
	b_reset.text = UF.T("重置", "Reset")
	b_reset.pressed.connect(func() -> void:
		k = 0.0
		h = 1.0
		_sl_k.value = k
		_sl_h.value = h
		_refresh())
	hb.add_child(b_reset)
	var b_shot := Button.new()
	b_shot.text = UF.T("保存截图到 previews/", "Save screenshot")
	b_shot.pressed.connect(func() -> void:
		var p: String = CFG.OUT_DIR + "/preview_ui_manual_%d.png" % Time.get_unix_time_from_system()
		var r := save_shot(p)
		_set_status(UF.T("已保存 %s" % r.get("path", "?"), "saved %s" % r.get("path", "?"))))
	hb.add_child(b_shot)
	_status_lbl = Label.new()
	_status_lbl.add_theme_font_size_override("font_size", 11)
	_status_lbl.add_theme_color_override("font_color", Color(0.6, 0.85, 0.65))
	_status_lbl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	vb.add_child(_status_lbl)

var _last_slider_label: Label

func _row_opt(parent: Node, text: String, items: Array) -> OptionButton:
	var hb := HBoxContainer.new()
	var l := Label.new()
	l.text = text
	l.custom_minimum_size = Vector2(84, 0)
	hb.add_child(l)
	var o := OptionButton.new()
	o.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for it in items:
		o.add_item(String(it))
	hb.add_child(o)
	parent.add_child(hb)
	return o

func _row_slider(parent: Node, text: String, mn: float, mx: float, step: float, val: float) -> HSlider:
	var v := VBoxContainer.new()
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", 13)
	v.add_child(l)
	var hb := HBoxContainer.new()
	var s := HSlider.new()
	s.min_value = mn
	s.max_value = mx
	s.step = step
	s.value = val
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.custom_minimum_size = Vector2(240, 0)
	hb.add_child(s)
	_last_slider_label = Label.new()
	_last_slider_label.custom_minimum_size = Vector2(230, 0)
	_last_slider_label.add_theme_font_size_override("font_size", 12)
	_last_slider_label.add_theme_color_override("font_color", Color(1, 0.9, 0.62))
	hb.add_child(_last_slider_label)
	v.add_child(hb)
	parent.add_child(v)
	return s

func _panel_style() -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.075, 0.082, 0.098, 0.96)
	sb.border_color = Color(0.3, 0.34, 0.42)
	sb.set_border_width_all(1)
	sb.set_corner_radius_all(6)
	return sb

func _set_status(s: String) -> void:
	status = s
	if _status_lbl:
		_status_lbl.text = s

## 程序化设置（离屏批处理 / 脚本调用）。
func configure(f: String, st: String, hr: String, kk: float, hh: float) -> void:
	family = f
	style = st
	hair = hr
	k = kk
	h = hh
	# ⚠ 必须屏蔽信号：否则 `_opt_* .selected = ...` 会触发 `_reload()` 抢先开一次
	#   `rebuild_avatar()`，把 `_busy` 占住 → 调用方 `await rebuild_avatar()` 立刻返回 →
	#   截图时穿模数据/读数还没算完（实测：面板显示"无穿模数据"而 JSON 里其实有）。
	_suppress = true
	if _opt_family:
		_opt_family.selected = ["Female", "Male"].find(f)
		_opt_style.selected = STYLES.find(st)
		_opt_hair.selected = (["None"] + CFG.HAIRS.keys()).find(hr)
		_sl_k.value = kk
		_sl_h.value = hh
	_suppress = false

func _reload() -> void:
	await rebuild_avatar()
	_refresh()

## 加载/重建部件（会按需调用 Blender headless 预导出 `.glb` 到工程外缓存）。
func rebuild_avatar() -> void:
	if _busy:
		return
	_busy = true
	_set_status(UF.T("加载中…（首次会调用 Blender headless 预导出到 tmp/ 缓存）",
		"loading... (first run shells out to Blender)"))
	await get_tree().process_frame
	var t0 := Time.get_ticks_msec()
	RIG.free_avatar(avatar)
	avatar = {}
	var gkey := "" if style == "None" else family + "_" + style
	var binfo := {"body": BAKE.ensure_body(family)}
	if gkey != "":
		binfo["garment"] = BAKE.ensure_garment(gkey)
	if hair != "None":
		binfo["hair"] = BAKE.ensure_hair(hair)
	bake_info = binfo
	var body_glb: String = binfo["body"].get("glb", "") if binfo["body"].get("ok", false) else ""
	var garment_glb := ""
	if gkey != "" and binfo.has("garment") and binfo["garment"].get("ok", false):
		garment_glb = binfo["garment"].get("glb", "")
	var hair_glb := ""
	if hair != "None" and binfo.has("hair") and binfo["hair"].get("ok", false):
		hair_glb = binfo["hair"].get("glb", "")
	if body_glb == "":
		_set_status("ERROR: " + String(binfo["body"].get("error", "body load failed")))
		_busy = false
		return
	avatar = RIG.build(family, body_glb, gkey, garment_glb, hair if hair != "None" else "", hair_glb,
		true, force_standard_body)
	# ⚠ 必须把角色根节点挂进视口（面板挂在 3D 舞台同一个视口里），
	#   漏了这一步页面 3D 区就是一片空白（实测踩过）。
	avatar["root"].name = "Avatar_%d" % (Time.get_ticks_usec() % 100000)
	add_child(avatar["root"])
	RIG.on_attached(avatar)
	avatar["root"].position = Vector3.ZERO
	if stage.has("cam"):
		# 取景要对着**最坏包络**，这样滑块拉到头也不会裁切
		var fx := _focus_x()
		avatar["frame"] = PAGE.frame_single(stage["cam"], _viewport_size, fx)
	# ---- 主指示：Godot 像素法（不依赖拓扑）----
	if penp != null:
		penp.destroy()
		penp = null
	pen = {}
	live_measure = {}
	if gkey != "" and garment_glb != "":
		_set_status(UF.T("像素法测量中（%d 档 × 方位角）…" % PENP.KS.size(),
			"pixel measurement..."))
		await get_tree().process_frame
		penp = PENP.new()
		penp.build(get_tree(), family, body_glb, gkey, garment_glb,
			hair if hair != "None" else "", hair_glb, force_standard_body)
		var cal: Dictionary = await penp.calibrate()      # ★ 双向标定不过就不出数
		if penp.usable():
			pen = await penp.measure_curve(PENP.AZ_ALL)
			height_uniformity = await penp.measure_height_uniformity(CFG.H_MAX)
		else:
			pen = {"error": penp.error, "calibration": cal}
	# BVH 参考法**已从流程里摘掉**（它对非闭合/绕向不一致的网格不可靠，
	# 留着只会让人把它的数当成我的口径 —— Lead 已经因此对不上账一次）。
	# 想复现那条负面结论：ARTSTUDIO_PREVIEW_BVH_REFERENCE=1 + blender/penetration.py 手动跑。
	pen_ref = {}
	var ms := Time.get_ticks_msec() - t0
	_busy = false
	_refresh()
	_set_status(UF.T("已加载（%.0f ms）" % ms, "loaded (%.0f ms)" % ms))

## 拖动结束后做一次**实时像素测量**（同一条口径，只是不跑整条曲线）。
func _live_measure() -> void:
	if penp == null or not penp.ready:
		return
	live_measure = await penp.measure_k(k, PENP.AZ_ALL)
	_update_gauge(gkey())

## 3D 视区的水平中心（右侧被面板占了，所以角色要偏左）。
func _focus_x() -> float:
	return maxf(64.0, (_viewport_size.x - PANEL_W) * 0.5)

func _refresh() -> void:
	if avatar.is_empty():
		return
	var rep := RIG.apply(avatar, k, h)
	avatar["last"] = rep
	var st := RIG.stats(avatar)
	# ---- 文本读数 ----
	var lines: Array = []
	lines.append("Godot %s   |   ROOT %s" % [Engine.get_version_info().string, CFG.ROOT])
	lines.append("k=%+.2f  BS_Thin=%.2f  BS_Heavy=%.2f      h=%.3f  (%s, 骨架 pose 未被碰)"
		% [k, rep["bs_thin"], rep["bs_heavy"], h, rep.get("height_mode", "")])
	lines.append("morph 契约 %s  规格=[BS_Thin(0), BS_Heavy(1)] 逐件对齐=%s" % [
		"OK" if avatar["contract"]["all_ok"] else "!! 不符",
		"是" if avatar["contract"]["all_ok"] else "否"])
	lines.append("")
	lines.append("%-24s %5s %5s %6s %9s %9s" % ["部件", "网格", "骨架", "骨数", "BS_Thin", "BS_Heavy"])
	for row in rep["parts"]:
		var bones := 0
		for sk in avatar["parts"]:
			if sk["role"] == row["part"]:
				bones = sk["skeletons"][0].get_bone_count() if sk["skeletons"].size() > 0 else 0
		var tv := "--"
		var hv := "--"
		for mv in row["morph_values"]:
			if mv["name"] == "BS_Thin":
				tv = "%.3f" % mv["read_back"]
			if mv["name"] == "BS_Heavy":
				hv = "%.3f" % mv["read_back"]
		lines.append("%-24s %5d %5d %6d %9s %9s" % [
			("%s:%s" % [row["part"], String(avatar["parts"][0]["key"]) if row["part"] == "body" else _key_of(row["part"])]),
			row["mesh_instances"], 1 if bones > 0 else 0, bones, tv, hv])
	lines.append("")
	for hr in rep["height"]:
		lines.append("%s 骨架 %s: 骨数=%d  root 骨按名字取到 index=%d  实际骨名=%s  Head index=%d" % [
			hr["part"], hr["skeleton"], hr["bones"], hr["root_bone_by_name"],
			hr.get("bone_name_at_head_idx", "?"), hr["head_bone_by_name"]])
	lines.append("合计: 网格 %d / 骨架 %d / 带 morph 的网格 %d" % [
		st["mesh_instances"], st["skeletons"], st["morph_meshes"]])
	if not avatar["errors"].is_empty():
		lines.append("ERRORS: %s" % str(avatar["errors"]))
	_readout.text = "\n".join(lines)
	# ---- 滑块标签 ----
	_lbl_k.text = "k=%+.2f  BS_Thin=%.2f  BS_Heavy=%.2f" % [k, rep["bs_thin"], rep["bs_heavy"]]
	_lbl_h.text = "h=%.3f  身高 %.1f → %.1f cm" % [h, 177.0, 177.0 * h]
	# ---- 素材来源说明 ----
	if bake_info.has("garment"):
		var gi: Dictionary = bake_info["garment"]
		var real: bool = not gi.get("fixture", true)
		var srctxt := "真实资产" if real else "fixture（T2 资产未就位，自动兜底）"
		_src_note.text = UF.T("服装来源: %s ← %s" % [srctxt, gi.get("source_blend", "?")],
			"garment source: %s <- %s" % [srctxt, gi.get("source_blend", "?")])
	else:
		_src_note.text = UF.T("服装来源: 未选", "garment: none")
	# ---- 穿模指示 ----
	_update_gauge(gkey())

func gkey() -> String:
	return "" if style == "None" else family + "_" + style

func _key_of(role: String) -> String:
	for p in avatar["parts"]:
		if p["role"] == role:
			return String(p["key"])
	return "?"

func _update_gauge(gk: String) -> void:
	_gauge.marker_k = k
	var base_pct := float(pen.get("rest_baseline_pct", 0.0)) if pen.has("rest_baseline_pct") else 0.0
	_gauge.threshold = base_pct + CFG.PEN_THRESHOLD_PCT
	_gauge.threshold_note = UF.T("rest 基线 %.2f%% + 2%%" % base_pct, "rest %.2f%% + 2%%" % base_pct)
	var cal: Dictionary = pen.get("calibration", {})
	var n_az: int = int(pen.get("azimuths_deg", []).size())
	if gk == "" or pen.is_empty():
		_gauge.ks = []
		_gauge.pen = []
		_gauge.maxes = []
		_gauge.n_verts = 0
		_gauge.label = UF.T("穿模指示：未选择服装", "Penetration: no garment selected")
		_gauge.unavailable = ""
		_gauge.queue_redraw()
		return
	if not pen.has("ks") or not bool(cal.get("ok", false)):
		# ★ 双向标定不过 / 没测出来 —— 明确报错，绝不画一条看起来像样的曲线
		_gauge.ks = []
		_gauge.pen = []
		_gauge.maxes = []
		_gauge.n_verts = 0
		_gauge.label = UF.T("穿模指示：%s —— 未通过测量前置，拒绝出数" % gk,
			"Penetration: %s - measurement precondition failed" % gk)
		_gauge.unavailable = String(pen.get("error", "")) 
		if _gauge.unavailable == "":
			_gauge.unavailable = UF.T("双向标定未通过：%s" % JSON.stringify(cal),
				"calibration failed: %s" % JSON.stringify(cal))
		_gauge.queue_redraw()
		return
	_gauge.ks = pen.get("ks", [])
	_gauge.pen = pen.get("mean_pct", [])       # ← 4 个方位角的**均值**
	_gauge.maxes = pen.get("max_pct", [])      # ← 4 个方位角里最坏的那个
	_gauge.n_verts = PENP.W * PENP.H
	var nm := "fixture" if bake_info.get("garment", {}).get("fixture", true) else "真实资产"
	var lv := ""
	if not live_measure.is_empty() and live_measure.has("mean_pct"):
		lv = UF.T("  实时实测 k=%+.2f → %.2f%%" % [live_measure.get("k", k), live_measure.get("mean_pct", 0.0)],
			"  live k=%+.2f -> %.2f%%" % [live_measure.get("k", k), live_measure.get("mean_pct", 0.0)])
	_gauge.label = UF.T(
		"穿模率 vs 体形 k（像素法，%s）—— %s  单位:被身体盖住的服装像素 %% 服装像素" % [nm, gk],
		"penetration vs k (pixel, %s) - %s  unit: %% of garment px" % [nm, gk])
	_gauge.subtitle = UF.T(
		"曲线=4 方位角均值（%d 个方位：%s），点=各 k；实测标定 C1=%.2f%% C2=%.2f%%%s"
			% [n_az, str(pen.get("azimuths_deg", [])), float(cal.get("C1_solid_only_expect_100", -1)),
				float(cal.get("C2_layer_only_expect_0", -1)), lv],
		"mean of %d azimuths %s; calibration C1=%.2f C2=%.2f%s"
			% [n_az, str(pen.get("azimuths_deg", [])), float(cal.get("C1_solid_only_expect_100", -1)),
				float(cal.get("C2_layer_only_expect_0", -1)), lv])
	_gauge.unavailable = ""
	_gauge.queue_redraw()


## 把当前视口（3D + 面板）整体存成 PNG。`abs_path` 必须是**绝对路径**
## （`assets/3d/rig/previews/` 在工程外，`res://` 到不了）。
func save_shot(abs_path: String) -> Dictionary:
	var vp := get_viewport()
	var img := vp.get_texture().get_image()
	return ST.save_abs(img, abs_path)

## 供 JSON 证据用：当前状态的完整快照。
func report() -> Dictionary:
	var gk := gkey()
	return {
		"family": family, "outfit_style": style, "garment_key": gk, "hair": hair,
		"k": snappedf(k, 0.0001), "h": snappedf(h, 0.0001),
		"morph_applied": avatar.get("last", {}),
		"morph_per_mesh": avatar.get("last", {}).get("per_mesh", []),
		"morph_per_mesh_summary": avatar.get("last", {}).get("per_mesh_summary", {}),
		"compact_morph_per_part": RIG.compact(avatar, k, h) if not avatar.is_empty() else [],
		"contract": avatar.get("contract", {}),
		"stats": RIG.stats(avatar) if not avatar.is_empty() else {},
		"assets": {
			"body": bake_info.get("body", {}),
			"garment": bake_info.get("garment", {}),
			"hair": bake_info.get("hair", {}),
		},
		"penetration_pixel_method": pen,
		"penetration_live": live_measure,
		"penetration_method_note": ("本页唯一的穿模口径 = 像素法（见 penetration_pixel_method 的 "
			+ "normalization 字段）。BVH 有符号距离法已从流程摘除（非闭合网格正负号不可靠），"
			+ "不再产出任何数字，避免与像素法混用。"),
		"height_uniformity": height_uniformity,
		"route": avatar.get("route", ""),
		"force_standard_body": force_standard_body,
		"arms_down": avatar.get("arms_down", []),
		"pen_pixel_classes": pen.get("classes", []) if not pen.is_empty() else [],
		"pen_pixel_calibration": pen.get("calibration", {}) if not pen.is_empty() else {},
		"errors": avatar.get("errors", []),
	}