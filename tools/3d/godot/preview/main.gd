extends Node3D
## 交互模式入口（`Godot --path tools/3d/godot/preview`）。
##
## 把 3D 舞台挂在**窗口视口**上，右侧叠一层面板（`preview_panel.gd`）。
## 离屏出图（`shoot.gd`）用的是同一套 page/panel 代码，只是挂到 SubViewport 上。

const CFG = preload("res://cfg.gd")
const PAGE = preload("res://page.gd")
const PreviewPanel = preload("res://preview_panel.gd")

var panel: Control

func _ready() -> void:
	print("artstudio T3 Godot preview  Godot=", Engine.get_version_info().string)
	print("ROOT=", CFG.ROOT, "  cache=", CFG.cache_dir())
	var stage := PAGE.make_stage(self)
	panel = PreviewPanel.new()
	panel.stage = stage
	add_child(panel)
	await get_tree().process_frame
	await panel.rebuild_avatar()
	print("READY  操作：拖右侧滑块改体形/身高，OptionButton 换装/换发型；"
		+ "面板下方「保存截图」把整页存到 assets/3d/rig/previews/")
	print("READY  assets loaded: ", JSON.stringify(panel.bake_info).substr(0, 600))