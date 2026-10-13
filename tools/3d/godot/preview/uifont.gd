extends RefCounted
## 字体助手：Godot 内置的 fallback 字体**没有中文字形**（会画成豆腐块）。
## 这里从 macOS 系统字体里动态加载一个中文字体给 UI 用；失败就回落成英文标签。
## 注意：这是**读系统字体**，不是往工程里拷素材（零拷贝原则不受影响）。

const CANDIDATES := [
	"/System/Library/Fonts/PingFang.ttc",
	"/System/Library/Fonts/Hiragino Sans GB.ttc",
	"/System/Library/Fonts/STHeiti Medium.ttc",
	"/System/Library/Fonts/Supplemental/Songti.ttc",
	"/System/Library/Fonts/Helvetica.ttc",
]

static var _font: FontFile = null
static var _tried: bool = false
static var _path: String = ""
static var _mono: FontFile = null
static var _mono_tried: bool = false
static var _mono_path: String = ""

const MONO_CANDIDATES := [
	"/System/Library/Fonts/Menlo.ttc",
	"/System/Library/Fonts/SFNSMono.ttf",
	"/System/Library/Fonts/Courier.ttc",
]

static func mono() -> FontFile:
	if _mono_tried:
		return _mono
	_mono_tried = true
	for p in MONO_CANDIDATES:
		if not FileAccess.file_exists(p):
			continue
		var f := FontFile.new()
		if f.load_dynamic_font(p) == OK:
			_mono = f
			_mono_path = p
			return _mono
	return null

static func cjk() -> FontFile:
	if _tried:
		return _font
	_tried = true
	for p in CANDIDATES:
		if not FileAccess.file_exists(p):
			continue
		var f := FontFile.new()
		if f.load_dynamic_font(p) == OK:
			_font = f
			_path = p
			return _font
	return null

static func font_path() -> String:
	cjk()
	return _path

static func has_cjk() -> bool:
	return cjk() != null

## 双语标签：有中文字体就用中文，否则回落英文（避免屏幕上出现豆腐块）。
static func T(zh: String, en: String) -> String:
	return zh if has_cjk() else en

static func make_theme(size := 15) -> Theme:
	var t := Theme.new()
	var f := cjk()
	if f != null:
		t.default_font = f
	t.default_font_size = size
	return t