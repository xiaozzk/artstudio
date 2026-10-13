extends Control
## 右侧中文控制面板 + 左侧舞台显示（窗口交互模式与「交互页整页图」共用同一份代码）。
##
## 布局：**显式设 rect**，不靠 anchors/容器推断。实测坑：在 Node3D 父节点下与离屏 SubViewport 里，
## `set_anchors_preset()` 推出的 rect 会是 0 尺寸 → 整页图**空白**（且退出码仍是 0，属静默说谎）。
##
## 中文字形：Godot 内置 fallback 字体没有中文（会画成豆腐块），按名字取**系统字体**（SystemFont）。
## 这是读系统字体，不是往工程里拷素材，零拷贝原则不受影响。

const STAGE = preload("res://stage.gd")
const CACHE = preload("res://cache.gd")

const CJK_FONTS := ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
	"Hiragino Sans GB", "Noto Sans CJK SC", "SimHei", "Arial Unicode MS"]
const ROLE_ORDER := ["head", "skin", "cloth", "accessory", "foot"]
const ROLE_CN := {"head": "头 / 五官", "skin": "皮肤", "cloth": "布料",
	"accessory": "配件（「清凉」预设会隐藏）", "foot": "脚部"}
const PANEL_W := 540.0

signal char_selected(index: int)
signal kh_changed(k: float, h: float)
signal reset_pressed()
signal preset_pressed(preset: String)
signal part_toggled(part_name: String, visible: bool)
signal shot_pressed()

var stage: Dictionary = {}
var k := 0.0
var h := 1.0

var _display: TextureRect
var _panel: PanelContainer
var _char_opt: OptionButton
var _k_slider: HSlider
var _h_slider: HSlider
var _k_label: Label
var _h_label: Label
var _bs_label: Label
var _cache_label: Label
var _parts_box: VBoxContainer
var _checks: Dictionary = {}
var _readout: RichTextLabel
var _status: Label

## 全局字体：Label3D 与所有默认控件都吃 ThemeDB.fallback_font。
static func install_font() -> void:
	var f := SystemFont.new()
	f.font_names = PackedStringArray(CJK_FONTS)
	f.allow_system_fallback = true
	ThemeDB.fallback_font = f

static func make_theme(size := 14) -> Theme:
	install_font()
	var t := Theme.new()
	t.default_font = ThemeDB.fallback_font
	t.default_font_size = size
	return t

func _ready() -> void:
	theme = make_theme(14)
	_display = TextureRect.new()
	_display.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_display.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	_display.mouse_filter = Control.MOUSE_FILTER_STOP
	_display.gui_input.connect(_on_display_input)
	add_child(_display)
	_panel = PanelContainer.new()
	add_child(_panel)
	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_panel.add_child(scroll)
	var vb := VBoxContainer.new()
	vb.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	vb.add_theme_constant_override("separation", 6)
	scroll.add_child(vb)

	var ttl := _plain(vb, "artstudio · 身形 & 服装快预览（shape-lab）", Color(1, 1, 1), 16)
	ttl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_cache_label = _plain(vb, "", Color(0.6, 0.62, 0.68), 11)
	_char_opt = OptionButton.new()
	_char_opt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_char_opt.item_selected.connect(func(i: int): char_selected.emit(i))
	vb.add_child(_labeled("角色", _char_opt))

	var krow := HBoxContainer.new()
	_k_label = _plain(krow, "k = +0.00", Color(0.95, 0.9, 0.6), 14)
	_k_slider = _slider(krow, CACHE.K_MIN, CACHE.K_MAX, 0.01, 0.0, _on_k)
	vb.add_child(_labeled("体形 k（-1 瘦 ← → +1 壮）", krow))
	_bs_label = _plain(vb, "", Color(0.75, 0.85, 1.0), 13)

	var hrow := HBoxContainer.new()
	_h_label = _plain(hrow, "h = 1.000", Color(0.95, 0.9, 0.6), 14)
	_h_slider = _slider(hrow, CACHE.H_MIN, CACHE.H_MAX, 0.002, 1.0, _on_h)
	vb.add_child(_labeled("身高 h（0.92 – 1.08；缩放根节点，不碰骨 pose）", hrow))

	var btns := HBoxContainer.new()
	btns.add_child(_button("重置 (k=0, h=1)", func(): reset_pressed.emit()))
	for pres in ["全套", "清凉", "仅皮肤&头"]:
		btns.add_child(_button(pres, func(): preset_pressed.emit(pres)))
	vb.add_child(btns)

	_plain(vb, "逐件显隐（按 role 分组）", Color(0.75, 0.85, 1.0), 13)
	_parts_box = VBoxContainer.new()
	vb.add_child(_parts_box)
	_plain(vb, "读数 / morph 契约自检", Color(0.75, 0.85, 1.0), 13)
	_readout = RichTextLabel.new()
	_readout.bbcode_enabled = false
	_readout.scroll_active = true
	_readout.custom_minimum_size = Vector2(0, 300)
	_readout.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_readout.add_theme_font_size_override("normal_font_size", 11)
	vb.add_child(_readout)
	var srow := HBoxContainer.new()
	srow.add_child(_button("保存截图（PNG，绝对路径）", func(): shot_pressed.emit()))
	vb.add_child(srow)
	_status = _plain(vb, "", Color(0.55, 0.85, 0.6), 11)
	_refresh_kh()
	_layout()
	get_viewport().size_changed.connect(_layout)

## 显式 rect：左显示区 + 右面板（避免 anchors 在非常规父节点下算出 0 尺寸）。
func _layout() -> void:
	var vs := get_viewport_rect().size
	if vs.x < 2.0 or vs.y < 2.0:
		return
	size = vs
	var pw: float = minf(PANEL_W, vs.x * 0.5)
	_display.position = Vector2.ZERO
	_display.size = Vector2(vs.x - pw, vs.y)
	_panel.position = Vector2(vs.x - pw, 0.0)
	_panel.size = Vector2(pw, vs.y)

func bind_stage(st: Dictionary) -> void:
	stage = st
	if _display != null:
		_display.texture = (st["vp"] as SubViewport).get_texture()

## 给「整页图是不是空白」留证据：三个区域的实际 rect。
func layout_report() -> Dictionary:
	return {"page": [size.x, size.y],
		"display_rect": [_display.position.x, _display.position.y, _display.size.x, _display.size.y],
		"panel_rect": [_panel.position.x, _panel.position.y, _panel.size.x, _panel.size.y],
		"part_checkboxes": _checks.size()}

func populate(chars: Array) -> void:
	_char_opt.clear()
	for c in chars:
		_char_opt.add_item(String(c.get("label", c.get("id", "?"))))
	if not chars.is_empty():
		_char_opt.select(0)

func select_index(i: int) -> void:
	if i >= 0 and i < _char_opt.item_count:
		_char_opt.select(i)

func set_cache_info(text: String) -> void:
	_cache_label.text = text

func set_status(text: String) -> void:
	_status.text = text

func set_readout(text: String) -> void:
	_readout.text = text

func set_kh(kk: float, hh: float) -> void:
	k = kk
	h = hh
	_k_slider.set_value_no_signal(kk)
	_h_slider.set_value_no_signal(hh)
	_refresh_kh()

## 逐件显隐：按 role 分组重建勾选框；`hidden` 里的件不勾选。
func sync_parts(parts: Array, hidden: Array) -> void:
	for c in _parts_box.get_children():
		c.queue_free()
	_checks.clear()
	var sorted := parts.duplicate()
	sorted.sort_custom(func(a, b):
		return ROLE_ORDER.find(String(a["role"])) < ROLE_ORDER.find(String(b["role"])))
	var last_role := ""
	for p in sorted:
		var role := String(p["role"])
		if role != last_role:
			_parts_box.add_child(_plain(null, "— %s —" % String(ROLE_CN.get(role, role)),
				Color(0.62, 0.66, 0.72), 12))
			last_role = role
		var cb := CheckBox.new()
		cb.text = String(p["name"])
		cb.set_pressed_no_signal(not hidden.has(String(p["name"])))
		cb.toggled.connect(func(v: bool): part_toggled.emit(String(p["name"]), v))
		_parts_box.add_child(cb)
		_checks[String(p["name"])] = cb

func hidden_parts(parts: Array) -> Array:
	var out: Array = []
	for p in parts:
		var cb: CheckBox = _checks.get(String(p["name"]), null)
		if cb != null and not cb.button_pressed:
			out.append(String(p["name"]))
	return out

func _on_k(v: float) -> void:
	k = v
	_refresh_kh()
	kh_changed.emit(k, h)

func _on_h(v: float) -> void:
	h = v
	_refresh_kh()
	kh_changed.emit(k, h)

func _refresh_kh() -> void:
	_k_label.text = "k = %+.2f" % k
	_h_label.text = "h = %.3f" % h
	_bs_label.text = "BS_Thin = %.3f    BS_Heavy = %.3f" % [maxf(-k, 0.0), maxf(k, 0.0)]

func _on_display_input(ev: InputEvent) -> void:
	if stage.is_empty():
		return
	if ev is InputEventMouseMotion and (ev.button_mask & MOUSE_BUTTON_MASK_LEFT) != 0:
		STAGE.orbit(stage, ev.relative.x, ev.relative.y)
	elif ev is InputEventMouseButton and ev.pressed:
		if ev.button_index == MOUSE_BUTTON_WHEEL_UP:
			STAGE.zoom(stage, 1.0)
		elif ev.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			STAGE.zoom(stage, -1.0)

func _plain(parent: Node, text: String, col: Color, size: int) -> Label:
	var l := Label.new()
	l.text = text
	l.modulate = col
	l.add_theme_font_size_override("font_size", size)
	if parent != null:
		parent.add_child(l)
	return l

func _labeled(text: String, child: Control) -> VBoxContainer:
	var v := VBoxContainer.new()
	v.add_child(_plain(null, text, Color(0.8, 0.83, 0.88), 13))
	child.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	v.add_child(child)
	return v

func _slider(parent: Node, mn: float, mx: float, step: float, val: float, cb: Callable) -> HSlider:
	var s := HSlider.new()
	s.min_value = mn
	s.max_value = mx
	s.step = step
	s.value = val
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.custom_minimum_size = Vector2(180, 22)
	s.value_changed.connect(cb)
	if parent != null:
		parent.add_child(s)
	return s

func _button(text: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.pressed.connect(cb)
	return b
