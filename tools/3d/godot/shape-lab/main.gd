extends Node3D
## shape-lab 入口。两种模式：
##   ① 交互（`run.cmd`）：窗口 1500x900，左边固定尺寸离屏舞台，右边中文面板；拖滑块即可看身形/服装变形。
##   ② 出图（`run.cmd --shots`）：6 角色 × 3 档（thin/standard/heavy）单图 + 每角色联系表 + 交互页整页图。
##
## 实测坑：`_ready()` 里刚 add_child 的节点当帧还没真入树（`get_viewport()` 为 null、
## `global_transform` 不可用）→ 先 `await process_frame` 再建房 / 取景 / 求 AABB。
##
## 注意：`ui` 故意**不加静态类型**（Control 基类上没有这些方法，静态类型会编译报错）。

const CACHE = preload("res://cache.gd")
const STAGE = preload("res://stage.gd")
const AVATAR = preload("res://avatar.gd")
const UI = preload("res://ui.gd")
const SHOTS = preload("res://shots.gd")

var cache: Dictionary = {}
var stage: Dictionary = {}
var avatar: Dictionary = {}
var ui = null
var app_args: PackedStringArray = []
var shots_mode := false
var pending_apply := false
var cur_k := 0.0
var cur_h := 1.0
var last_info: Dictionary = {}
var last_fit: Dictionary = {}

func _ready() -> void:
	app_args = OS.get_cmdline_user_args()
	shots_mode = "--shots" in app_args
	UI.install_font()
	print("artstudio shape-lab   Godot=", Engine.get_version_info().string, "  args=", app_args)
	print("repo_root=", CACHE.repo_root(), "  cache_root=", CACHE.cache_root())
	cache = CACHE.load()
	if not cache["ok"] and "--fixtures" in app_args:
		cache = CACHE.fixture_cache()
		print("WARN  缓存不可用，已切到 --fixtures 离线演示（无 morph 通道）")
	if not cache["ok"]:
		push_error(cache["error"])
		print("ERROR ", cache["error"])
		get_tree().quit(2)
		return
	stage = STAGE.make()
	add_child(stage["vp"])
	await get_tree().process_frame                     # ← 先等一帧：节点才真入树
	if shots_mode:
		get_tree().quit(await SHOTS.run(self))
		return
	make_ui(self)
	await load_character(0)
	if "--selftest" in app_args:
		get_tree().quit(await selftest())
		return
	print("READY  左键拖拽环绕 / 滚轮缩放；右侧拖 k 看身形、拖 h 看身高；「清凉」一键摘配件。")
	report_page_later(2.0)

func make_ui(host: Node):
	ui = UI.new()
	host.add_child(ui)          # ← 必须先入树：_ready() 建完控件后 bind_stage 才拿得到 _display
	ui.bind_stage(stage)
	ui.char_selected.connect(func(i: int): load_character(i))
	ui.kh_changed.connect(func(kk: float, hh: float): _mark_apply(kk, hh))
	ui.reset_pressed.connect(func():
		cur_k = 0.0
		cur_h = 1.0
		ui.set_kh(cur_k, cur_h)
		_apply_now())
	ui.preset_pressed.connect(func(p: String): apply_preset(p))
	ui.part_toggled.connect(func(n: String, v: bool): set_part_visible(n, v))
	ui.shot_pressed.connect(func(): save_page_shot())
	ui.populate(cache["chars"])
	var rr := String(cache.get("role_rules", ""))
	ui.set_cache_info("缓存 %s\nblender=%s  generated_at=%s\nrole_rules=%s%s" % [String(cache["root"]),
		String(cache.get("blender_version", "-")), String(cache.get("generated_at", "-")),
		rr if rr != "" else "(未声明)", "" if rr == "v1.1" else "  ← 旧口径，app 侧按 v1.1 重算 role"])
	return ui

## 滑杆拖动会连发信号：合并到下一帧，一次应用（拖起来不卡）。
func _mark_apply(kk: float, hh: float) -> void:
	cur_k = kk
	cur_h = hh
	pending_apply = true

func _process(_delta: float) -> void:
	if pending_apply and not avatar.is_empty():
		pending_apply = false
		_apply_now()

func load_character(i: int) -> void:
	if not avatar.is_empty() and is_instance_valid(avatar.get("root")):
		(avatar["root"] as Node3D).queue_free()
		await get_tree().process_frame
	avatar = AVATAR.build(cache["chars"][i])
	stage["vp"].add_child(avatar["root"])
	await get_tree().process_frame                     # 入树后才能 global_transform / unproject
	for e in avatar["errors"]:
		print("ERROR ", e)
	_apply_now()
	if ui != null:
		ui.select_index(i)
		ui.sync_parts(avatar["parts"], [])
	var c: Dictionary = avatar["char"]
	print("LOAD  %s  meshes=%d skeletons=%d morph_meshes=%d blend_mode=%s  warnings=%s"
		% [String(c.get("id", "?")), avatar["meshes"].size(), avatar["skeletons"].size(),
			last_info.get("morph_meshes", 0), String(avatar["blend_mode"]), str(avatar["warnings"])])

func _apply_now() -> void:
	if avatar.is_empty():
		return
	last_info = AVATAR.apply(avatar, cur_k, cur_h)
	last_fit = STAGE.frame(stage, AVATAR.world_aabb(avatar))
	if ui != null:
		ui.set_readout(readout_text())

## 出图流程用：直接摆到指定 k/h 并立刻生效（不走 _process 合并）。
func set_state(kk: float, hh: float) -> void:
	cur_k = kk
	cur_h = hh
	if ui != null:
		ui.set_kh(kk, hh)
	_apply_now()

func settle(frames: int) -> void:
	for _i in frames:
		await get_tree().process_frame
	await RenderingServer.frame_post_draw

func apply_preset(preset: String) -> void:
	var hidden: Array = AVATAR.apply_preset(avatar, preset)
	if ui != null:
		ui.sync_parts(avatar["parts"], hidden)
	_apply_now()
	print("PRESET %s → 隐藏 %d 件：%s" % [preset, hidden.size(), str(hidden)])

func set_part_visible(part_name: String, vis: bool) -> void:
	for p in avatar["parts"]:
		if String(p["name"]) == part_name:
			AVATAR.set_part_visible(p, vis)
	_apply_now()
	print("PART %s visible=%s（当前可见件 %d）" % [part_name, str(vis), AVATAR.visible_count(avatar)])

## 面板「保存截图」：截**当前整个页面**（本节点所在视口 = 左舞台 + 右面板），绝对路径。
## 返回 {path, stats, ...}；stats 是空白判据（见 stage.page_stats）。
func save_page_shot(tag := "") -> Dictionary:
	var suffix := tag if tag != "" else Time.get_datetime_string_from_system().replace(":", "").replace("-", "").replace("T", "_")
	var path := "%s/shape_lab_page_%s.png" % [CACHE.shots_dir(), suffix]
	var img: Image = get_viewport().get_texture().get_image()
	var stats: Dictionary = STAGE.page_stats(img)
	var res: Dictionary = STAGE.save_png_abs(img, path)
	res["stats"] = stats
	print("SHOT_PAGE ", JSON.stringify(res))
	if ui != null:
		ui.set_status("已保存截图：%s（非背景 %.1f%%）" % [path, float(stats.get("non_bg_pct", 0.0))])
	return res

## 开窗模式不偷偷出图（会往 tmp 写文件），只打统计：证明「面板真在、不是空白」。
func report_page_later(delay := 2.0) -> void:
	var t := Timer.new()
	t.wait_time = delay
	t.one_shot = true
	add_child(t)
	t.timeout.connect(func():
		await settle(1)
		var img: Image = get_viewport().get_texture().get_image()
		print("UI_LAYOUT ", JSON.stringify(ui.layout_report()))
		print("UI_PAGE_STATS ", JSON.stringify(STAGE.page_stats(img))))
	t.start()

## 自检（`--selftest`，一条命令跑完）：把「选角色 → 拖滑块 → 驱动 → 逐件 read-back → 契约 →
## 清凉预设 → 逐件勾选 → 轨道相机 → 面板截图」整条**交互链路**真跑一遍。返回进程退出码（0=全绿）。
func selftest() -> int:
	var fails: Array = []
	var checks := 0
	for i in cache["chars"].size():
		var cid := String(cache["chars"][i]["id"])
		await load_character(i)
		for t in [[-1.0, "thin"], [0.0, "standard"], [1.0, "heavy"]]:
			set_state(float(t[0]), 1.0)
			await settle(2)
			checks += 1
			var want_t: float = maxf(-float(t[0]), 0.0)
			var want_h: float = maxf(float(t[0]), 0.0)
			if absf(float(last_info["bs_thin"]) - want_t) > 1e-4 or absf(float(last_info["bs_heavy"]) - want_h) > 1e-4:
				fails.append("%s/%s BS 值不符" % [cid, String(t[1])])
			for p in last_info["parts"]:
				for r in p["rows"]:
					if not bool(r["read_back_ok"]) or not bool(r["contract_ok"]):
						fails.append("%s/%s %s 回读或契约失败" % [cid, String(t[1]), String(r["mesh"])])
		ui._k_slider.value = 0.6            # 走真实滑杆信号链路
		ui._h_slider.value = 1.04
		await settle(3)
		checks += 1
		if absf(cur_k - 0.6) > 1e-6 or absf(cur_h - 1.04) > 1e-6 or absf(float(last_info["bs_heavy"]) - 0.6) > 1e-4:
			fails.append("滑杆信号没走到应用（k=%.3f h=%.3f heavy=%.3f）" % [cur_k, cur_h, float(last_info["bs_heavy"])])
		apply_preset("清凉")
		await settle(1)
		checks += 1
		var want: Array = []
		for p in avatar["parts"]:
			var is_acc := String(p["role"]) == "accessory"
			if is_acc:
				want.append(String(p["name"]))
			if (p["meshes"][0] as MeshInstance3D).visible == is_acc:
				fails.append("%s 件 %s 的可见性与 role 规则不符" % [cid, String(p["name"])])
		var got: Array = ui.hidden_parts(avatar["parts"])
		want.sort()
		got.sort()
		if want != got:
			fails.append("%s 清凉预设隐藏集合不符 want=%s got=%s" % [cid, str(want), str(got)])
		apply_preset("全套")
		var cb: CheckBox = ui._checks[String(avatar["parts"][0]["name"])]
		cb.button_pressed = false
		await settle(1)
		checks += 1
		if (avatar["parts"][0]["meshes"][0] as MeshInstance3D).visible:
			fails.append("%s 取消勾选后网格仍可见" % cid)
		cb.button_pressed = true
		await settle(1)
	STAGE.orbit(stage, 30.0, 8.0)
	STAGE.zoom(stage, 1.0)
	STAGE.orbit(stage, -30.0, -8.0)
	await settle(2)
	checks += 1
	var shot: Dictionary = save_page_shot("selftest")
	if not FileAccess.file_exists(String(shot.get("path", ""))):
		fails.append("面板截图没落盘：%s" % String(shot.get("path", "")))
	var pst: Dictionary = shot.get("stats", {})
	if float(pst.get("non_bg_pct", 0.0)) < 3.0:
		fails.append("面板截图疑似空白（非背景 %.2f%%，细颜色数 %d）"
			% [float(pst.get("non_bg_pct", 0.0)), int(pst.get("colors_fine", 0))])
	print("SELFTEST checks=%d fails=%d" % [checks, fails.size()])
	for f in fails:
		print("SELFTEST_FAIL ", f)
	print("SELFTEST_RESULT ", "PASS" if fails.is_empty() else "FAIL")
	return 0 if fails.is_empty() else 5

func readout_text() -> String:
	var c: Dictionary = avatar["char"]
	var L: Array = []
	L.append("角色：%s  [%s / %s]" % [String(c.get("label", "")), String(c.get("id", "")),
		String(c.get("kind", ""))])
	L.append("glb：%s" % String(c.get("glb", "(fixture 内存自造)")))
	L.append("体形 k=%+.2f → BS_Thin=%.3f  BS_Heavy=%.3f（驱动场景里每一件带该 morph 的网格）"
		% [float(last_info.get("k", 0.0)), float(last_info.get("bs_thin", 0.0)),
			float(last_info.get("bs_heavy", 0.0))])
	var sc: Vector3 = last_info.get("root_scale", Vector3.ONE)
	L.append("身高 h=%.3f → 角色根节点 scale=(%.3f,%.3f,%.3f)；骨 pose 一个都没碰（find_bone 按名字取）"
		% [float(last_info.get("h", 1.0)), sc.x, sc.y, sc.z])
	var skl: Array = []
	for sk in avatar["skeletons"]:
		skl.append("%s: %d 骨, find_bone(\"Head\")=%d, root=%d" % [String(sk.name),
			sk.get_bone_count(), sk.find_bone("Head"), sk.find_bone("root")])
	L.append("网格=%d  骨架=%d%s  带 morph 网格=%d  可见件=%d/%d" % [avatar["meshes"].size(),
		avatar["skeletons"].size(), (" [" + ", ".join(skl) + "]") if not skl.is_empty() else "",
		int(last_info.get("morph_meshes", 0)), AVATAR.visible_count(avatar), avatar["parts"].size()])
	var bb: AABB = AVATAR.world_aabb(avatar)
	L.append("解析式复算 AABB（随 morph 变，get_aabb() 做不到）：X=%.3f Y=%.3f Z=%.3f m"
		% [bb.size.x, bb.size.y, bb.size.z])
	L.append("blend shape 存储语义实测判定=%s（取景/复算按它算，见 README）" % String(avatar["blend_mode"]))
	if last_fit.has("margin_px"):
		L.append("自动取景几何留白 px：%s（dist=%.2f m）" % [JSON.stringify(last_fit["margin_px"]),
			float(last_fit.get("dist", 0.0))])
	var n_rows := 0
	var n_static := 0
	var n_name_ok := 0
	var sample_names: Array = []
	var bad: Array = []
	var detail: Array = []
	for part in last_info.get("parts", []):
		if (part["rows"] as Array).is_empty():
			n_static += 1
			detail.append("  [%s] %s —— 无 morph（源 .blend 里就没有 shape key，非导出丢失）"
				% [String(part["role"]), String(part["name"])])
			continue
		for r in part["rows"]:
			n_rows += 1
			if bool(r["name_lookup_ok"]):
				n_name_ok += 1
			if sample_names.is_empty():
				sample_names = r["names"]
			var ok: bool = bool(r["contract_ok"]) and bool(r["read_back_ok"])
			if not ok:
				bad.append("%s/%s" % [String(part["name"]), String(r["mesh"])])
			detail.append("  [%s] %s  BS_Thin#%d %.3f→%.3f  BS_Heavy#%d %.3f→%.3f  位移max=%.4f m  %s"
				% [String(part["role"]), String(r["mesh"]), int(r["thin_index"]),
					float(r["set_thin"]), float(r["read_thin"]), int(r["heavy_index"]),
					float(r["set_heavy"]), float(r["read_heavy"]), float(r["disp_m"]),
					"✔" if ok else "✘"])
	if n_rows == 0:
		L.append("morph 契约自检：⚠ 本角色没有带 morph 的网格（离线 fixture 或纯静态件）")
	else:
		L.append("morph 契约自检：%s 带 morph 的 %d/%d 件都是 [\"BS_Thin\"(0), \"BS_Heavy\"(1)] 且 read-back 全一致%s；另有 %d 件源即无 morph（按契约不计 FAIL）"
			% ["✔" if bad.is_empty() else "✘", n_rows - bad.size(), n_rows,
				"（违规：%s）" % str(bad) if not bad.is_empty() else "", n_static])
	L.append("逐件读数（index = blend shape 索引；read-back = 设置后当场读回的值）：")
	L.append("  实测 shape 名：%s；find_blend_shape_by_name 命中 %d/%d 件（命中即按名字取，未命中回落索引 0/1）"
		% [str(sample_names), n_name_ok, n_rows])
	L.append_array(detail)
	for w in avatar["warnings"]:
		L.append("⚠ %s" % String(w))
	return "\n".join(L)
