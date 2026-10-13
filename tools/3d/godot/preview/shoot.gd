extends SceneTree
## 离屏批量出图 + JSON 证据（`-s res://shoot.gd`）。
##
## 一条命令跑完全部证据，不需要点任何东西：
##   <Godot> --path tools/3d/godot/preview -s res://shoot.gd --resolution 640x480
## 冷缓存时会自动调 Blender headless 把 `.blend` 预导出成 `.glb`（工程外 tmp 缓存）。
##
## 出图（全部落到 `assets/3d/rig/previews/preview_*.png`）：
##   1-3  三档各一张（BS_Thin=1 / 标准 / BS_Heavy=1）
##   4-5  女/男 三档并排
##   6    身高扫描（0.92 / 1.00 / 1.08）
##   7    4 套服装
##   8    4 款发型
##   9    交互页面整页（含实时读数与穿模曲线面板）

const CFG = preload("res://cfg.gd")
const RIG = preload("res://rig.gd")
const ST = preload("res://stage.gd")
const BAKE = preload("res://bake.gd")
const UF = preload("res://uifont.gd")
const PAGE = preload("res://page.gd")
const PreviewPanel = preload("res://preview_panel.gd")
const PENP = preload("res://pen_pixel.gd")

const BG := Color(0.105, 0.11, 0.125)
const OUT := CFG.OUT_DIR

var shots: Array = []
var assets: Dictionary = {}
var t_start := 0
var penp: RefCounted = null
var pen_key := ""
var pen_summary: Dictionary = {}

## 像素法测量器：同一时刻只留一份（每份都要复制一具角色，省显存）。
func _pen_for(family: String, gkey: String, hair: String) -> RefCounted:
	var key := "%s|%s|%s" % [family, gkey, hair]
	if penp != null and pen_key == key:
		return penp
	_pen_free()
	if gkey == "":
		return null
	penp = PENP.new()
	penp.build(self, family, _body(family), gkey, _garment(gkey), hair, _hair(hair))
	pen_key = key
	await penp.calibrate()          # ★ 双向标定（SPEC F21）
	return penp if penp.usable() else null

func _pen_free() -> void:
	if penp != null:
		penp.destroy()
	penp = null
	pen_key = ""

func _initialize() -> void:
	_run()

func _slim(r: Dictionary) -> Dictionary:
	var keep := ["ok", "glb", "source_blend", "real_asset", "fixture", "from_cache",
		"morph_fixture", "fixture_morph", "fixture_report", "error"]
	var o := {}
	for k in keep:
		if r.has(k):
			o[k] = r[k]
	if r.has("blender"):
		o["blender"] = r["blender"]
	if r.has("fixture_blender"):
		o["fixture_blender"] = r["fixture_blender"]
	return o

func _body(fam: String) -> String:
	if not assets.has("body_" + fam):
		assets["body_" + fam] = _slim(BAKE.ensure_body(fam))
	var r: Dictionary = assets["body_" + fam]
	return String(r.get("glb", "")) if r.get("ok", false) else ""

func _garment(gkey: String) -> String:
	if gkey == "":
		return ""
	if not assets.has("garment_" + gkey):
		assets["garment_" + gkey] = _slim(BAKE.ensure_garment(gkey))
	var r: Dictionary = assets["garment_" + gkey]
	return String(r.get("glb", "")) if r.get("ok", false) else ""

func _hair(hkey: String) -> String:
	if hkey == "" or hkey == "None":
		return ""
	if not assets.has("hair_" + hkey):
		assets["hair_" + hkey] = _slim(BAKE.ensure_hair(hkey))
	var r: Dictionary = assets["hair_" + hkey]
	return String(r.get("glb", "")) if r.get("ok", false) else ""

func _frames(n: int) -> void:
	for i in n:
		await process_frame

## ---- 单人一张 ---------------------------------------------------------------
func _shot_solo(name: String, fam: String, style: String, hair: String, k: float, h: float,
		w: int, hh: int, caption: String) -> void:
	var vp := ST.make_viewport(self, w, hh)
	var stage := PAGE.make_stage(vp, BG)
	var gkey := "" if style == "None" else fam + "_" + style
	var a := RIG.build(fam, _body(fam), gkey, _garment(gkey), hair if hair != "None" else "", _hair(hair))
	vp.add_child(a["root"])
	RIG.on_attached(a)
	var lab := PAGE.label3d(caption, Vector3(0, 1.93, 0.25), 40, 0.0034)
	vp.add_child(lab)
	var lc := PAGE.label_corners(lab.position, caption, 40, 0.0034)
	var fit := PAGE.frame_single(stage["cam"], Vector2i(w, hh), float(w) * 0.5, lc, 1.10)
	var applied := RIG.apply(a, k, h)
	var pen_here: Dictionary = {}
	if gkey != "":
		var pm: RefCounted = await _pen_for(fam, gkey, hair)
		if pm != null:
			pen_here = await pm.measure_k(k, PENP.AZ_ALL)
	await _frames(6)
	# 量留白：先把地线/标尺藏掉，只留角色（否则地板颜色被当成"非背景" → 假阳性）
	PAGE.set_helpers_visible(stage, false)
	await _frames(2)
	var img_geo := vp.get_texture().get_image()
	var stats := ST.image_stats(img_geo, BG)
	PAGE.set_helpers_visible(stage, true)
	await _frames(2)
	var img := vp.get_texture().get_image()
	var path := OUT + "/preview_" + name + ".png"
	var saved := ST.save_abs(img, path)
	shots.append({"name": name, "kind": "solo", "png": path, "resolution": [w, hh],
		"family": fam, "outfit_style": style, "garment_key": gkey, "hair": hair,
		"k": applied["k"], "h": applied["h"], "bs_thin": applied["bs_thin"],
		"bs_heavy": applied["bs_heavy"], "height_readout": applied["height"],
		"morph_per_part": applied["parts"], "morph_per_part_compact": RIG.compact(a, k, h),
		"morph_per_mesh": applied.get("per_mesh", []),
		"morph_per_mesh_summary": applied.get("per_mesh_summary", {}),
		"contract": a["contract"], "stats": RIG.stats(a), "fit": fit, "image": saved,
		"image_stats": stats, "errors": a["errors"], "route": a.get("route", ""),
		"arms_down": a.get("arms_down", []),
		"height_mode": applied.get("height_mode", ""),
		"avatar_root_scale": applied.get("avatar_root_scale", []),
		"penetration_at_k_pixel_method": pen_here})
	print("SHOT ", name, " margin=", stats.get("min_margin_px", -1), " cropped=", stats.get("cropped", true))
	vp.queue_free()
	await _frames(2)

## ---- 多人并排拼图 -----------------------------------------------------------
func _shot_montage(name: String, figs: Array, w: int, hh: int, caption: String,
		pitch := 7.0, margin := 1.07) -> void:
	var vp := ST.make_viewport(self, w, hh)
	var stage := PAGE.make_stage(vp, BG)
	var dx := 1.18
	var corners: Array = []
	var rows: Array = []
	var n := figs.size()
	for i in n:
		var f: Dictionary = figs[i]
		var x := (float(i) - (float(n) - 1) * 0.5) * dx
		var gkey: String = "" if f["style"] == "None" else String(f["family"]) + "_" + String(f["style"])
		var a := RIG.build(String(f["family"]), _body(String(f["family"])), gkey, _garment(gkey),
			String(f.get("hair", "None")) if f.get("hair", "None") != "None" else "",
			_hair(String(f.get("hair", "None"))))
		a["root"].position = Vector3(x, 0, 0)
		vp.add_child(a["root"])
		RIG.on_attached(a)
		var applied := RIG.apply(a, float(f["k"]), float(f.get("h", 1.0)))
		var cap := String(f["caption"])
		var lab := PAGE.label3d(cap, Vector3(x, -0.17, 0.25), 38, 0.0030)
		vp.add_child(lab)
		# 取景用 **A-pose 包络**而不是 `MeshInstance3D.get_aabb()`：
		# 后者返回的是**静止(T-pose)网格**的 AABB（蒙皮/姿态不改它，实测确认），
		# 拿它取景会把画面按 3.3 m 的臂展留白 → 放下手臂后角色显得很小。
		for c in PAGE.worst_corners():
			corners.append(c + Vector3(x, 0, 0))
		corners.append_array(PAGE.label_corners(lab.position, cap, 38, 0.0030))
		stage["helpers"].append(ST.make_ground_bar(vp, 1.05, 0.5, -0.012, x))
		if f.has("bar") and f["bar"]:
			stage["helpers"].append_array(ST.make_scale_bar(vp, 1.0, x + 0.56))
		rows.append({"family": f["family"], "outfit_style": f["style"], "garment_key": gkey,
			"hair": f.get("hair", "None"), "k": applied["k"], "h": applied["h"],
			"bs_thin": applied["bs_thin"], "bs_heavy": applied["bs_heavy"],
			"morph_per_part": applied["parts"], "morph_per_part_compact": RIG.compact(a, float(f["k"]), float(f.get("h", 1.0))),
			"morph_per_mesh": applied.get("per_mesh", []),
			"morph_per_mesh_summary": applied.get("per_mesh_summary", {}),
			"stats": RIG.stats(a), "route": a.get("route", ""), "arms_down": a.get("arms_down", []),
			"contract_all_ok": a["contract"]["all_ok"],
			"errors": a["errors"], "x": x})
	var title := PAGE.label3d(caption, Vector3(0, PAGE.ENV_TOP + 0.14, 0.25), 42, 0.0035)
	title.modulate = Color(1.0, 0.93, 0.6)
	vp.add_child(title)
	corners.append_array(PAGE.label_corners(title.position, caption, 42, 0.0035))
	var fit := PAGE.frame_points(stage["cam"], corners, Vector2i(w, hh), 34.0, pitch, margin)
	await _frames(6)
	PAGE.set_helpers_visible(stage, false)
	await _frames(2)
	var stats := ST.image_stats(vp.get_texture().get_image(), BG)
	PAGE.set_helpers_visible(stage, true)
	await _frames(2)
	var img := vp.get_texture().get_image()
	var path := OUT + "/preview_" + name + ".png"
	var saved := ST.save_abs(img, path)
	shots.append({"name": name, "kind": "montage", "png": path, "resolution": [w, hh],
		"figures": rows, "fit": fit, "image": saved, "image_stats": stats})
	print("SHOT ", name, " margin=", stats.get("min_margin_px", -1), " cropped=", stats.get("cropped", true))
	vp.queue_free()
	await _frames(2)

## ---- 交互页面整页（3D + 面板 + 穿模曲线）----------------------------------
func _shot_page(name: String, fam: String, style: String, hair: String, k: float, h: float,
		w: int, hh: int) -> void:
	var vp := ST.make_viewport(self, w, hh)
	var stage := PAGE.make_stage(vp, BG)
	var p: Control = PreviewPanel.new()
	p.stage = stage
	vp.add_child(p)
	await _frames(2)
	p.configure(fam, style, hair, k, h)
	await p.rebuild_avatar()
	await _frames(10)
	var img := vp.get_texture().get_image()
	var path := OUT + "/preview_" + name + ".png"
	var saved := ST.save_abs(img, path)
	# 整页截图右侧是 UI 面板，会顶到右边缘 → 留白只在左侧 3D 视区里量
	var region := Rect2i(0, 0, maxi(1, w - int(PreviewPanel.PANEL_W)), hh)
	var stats := ST.image_stats(img, BG, 0.06, region)
	var rep: Dictionary = p.report()
	print("PAGE gauge label=", p._gauge.label, " | ks=", p._gauge.ks, " | pen=", p._gauge.pen,
		" | unavailable=", p._gauge.unavailable)
	shots.append({"name": name, "kind": "page", "png": path, "resolution": [w, hh],
		"page": rep, "image": saved, "image_stats": stats,
		"ui_text": _readout_text(p), "gauge": {"ks": p._gauge.ks, "pen": p._gauge.pen,
			"gaps": p._gauge.gaps, "marker_k": p._gauge.marker_k,
			"threshold": p._gauge.threshold, "label": p._gauge.label}})
	print("SHOT ", name, " margin=", stats.get("min_margin_px", -1), " cropped=", stats.get("cropped", true))
	vp.queue_free()
	await _frames(2)

## ---- 复现 verifier 的 P1 vs P3 对照（只装 B2 角色 / 再叠一具标准体）----------
## 这是"腿上橙色斑块到底是谁的锅"的**决定性对照**：同一相机、同一 k，
## 只差"有没有多叠那具标准体"，然后量两次渲染的像素差。
func _shot_p1_vs_p3(name: String, family: String, style: String, hair: String, k: float,
		w: int, hh: int) -> void:
	var gkey := family + "_" + style
	var imgs: Array = []
	var routes: Array = []
	for force in [false, true]:
		var vp := ST.make_viewport(self, w, hh)
		var stage := PAGE.make_stage(vp, BG, false)
		var a := RIG.build(family, _body(family), gkey, _garment(gkey),
			"", "", true, force)
		vp.add_child(a["root"])
		RIG.on_attached(a)
		var applied_p1v3 := RIG.apply(a, k, 1.0)
		var lab := PAGE.label3d(("P3  B2 + extra body  (force)" if force else "P1  B2 only"),
			Vector3(0, 1.93, 0.25), 40, 0.0034)
		vp.add_child(lab)
		# 两图用**同一个**标签宽估算取景，否则两边的相机会不一样、没法逐像素比
		var lc := PAGE.label_corners(Vector3(0, 1.93, 0.25), "P3  B2 + extra body  (force)", 40, 0.0034)
		PAGE.frame_single(stage["cam"], Vector2i(w, hh), float(w) * 0.5, lc, 1.10)
		await _frames(6)
		var shot_img := vp.get_texture().get_image()
		shot_img.convert(Image.FORMAT_RGBA8)   # ⚠ 非透明视口出的是 RGB8(3B/px)，不转就会越界
		imgs.append(shot_img.duplicate())
		routes.append({"force_overlay": force, "route": a.get("route", ""),
			"stats": RIG.stats(a), "errors": a["errors"],
			"morph_per_mesh": applied_p1v3.get("per_mesh", []),
			"morph_per_mesh_summary": applied_p1v3.get("per_mesh_summary", {})})
		vp.queue_free()
		await _frames(2)
	# 拼左右对照图
	var cmp := Image.create(w * 2, hh, false, imgs[0].get_format())
	cmp.blit_rect(imgs[0], Rect2i(0, 0, w, hh), Vector2i(0, 0))
	cmp.blit_rect(imgs[1], Rect2i(0, 0, w, hh), Vector2i(w, 0))
	var path := OUT + "/preview_" + name + ".png"
	var saved := ST.save_abs(cmp, path)
	# 像素差：只在 P1 的非背景像素上算（这一条就是 verifier 的 P1_vs_P3）
	var i0: Image = imgs[0]
	var i1: Image = imgs[1]
	var d1: PackedByteArray = i0.get_data()
	var d2: PackedByteArray = i1.get_data()
	var n_bg := 0
	var n_diff := 0
	for i in w * hh:
		var o := i * 4
		var is_bg: bool = absf(d1[o] / 255.0 - BG.r) <= 0.06 and absf(d1[o + 1] / 255.0 - BG.g) <= 0.06 and absf(d1[o + 2] / 255.0 - BG.b) <= 0.06
		if is_bg:
			continue
		n_bg += 1
		if absi(int(d1[o]) - int(d2[o])) + absi(int(d1[o + 1]) - int(d2[o + 1])) + absi(int(d1[o + 2]) - int(d2[o + 2])) > 24:
			n_diff += 1
	var stats := ST.image_stats(imgs[0], BG)
	shots.append({"name": name, "kind": "p1_vs_p3", "png": path, "resolution": [w * 2, hh],
		"k": k, "family": family, "garment_key": gkey,
		"routes": routes, "image": saved, "image_stats_p1": stats,
		"pixel_diff_pct_of_p1_fg": snappedf(100.0 * float(n_diff) / maxf(1.0, float(n_bg)), 1),
		"pixel_diff_note": "P1(只装 B2 角色) 与 P3(再叠一具标准体) 的逐像素差，只在 P1 前景像素上统计"})
	print("SHOT ", name, " P1_vs_P3 diff%=", snappedf(100.0 * float(n_diff) / maxf(1.0, float(n_bg)), 1))
	await _frames(2)

## ★ 「逐 mesh 的 morph 读回」到底在哪一层 —— 机器可核查，免得读者/验收方去猜。
## 口径（刻意如此，不是遗漏）：**每次渲染一个"被 morph 驱动的角色"，就在该角色所在层级留一份逐 mesh 行**。
##   solo       → shots[i].morph_per_mesh                    （1 个角色；12 或 8 行）
##   montage    → shots[i].figures[j].morph_per_mesh          （每个 figure 一份）
##   page       → shots[i].page.morph_per_mesh                （面板当前角色一份）
##   p1_vs_p3   → shots[i].routes[k].morph_per_mesh           （P1 / P3 各一份）
## **shot 级** `morph_per_mesh` 只有 solo 镜头有（montage/page/p1_vs_p3 的数据在各自的嵌套层级）。
func _per_mesh_coverage(list: Array) -> Dictionary:
	var per_shot: Array = []
	var total := 0
	var shot_level: Array = []
	for s in list:
		var entries: Array = []
		if s.has("morph_per_mesh"):
			entries.append({"where": "shots[%s].morph_per_mesh" % s["name"],
				"characters": 1, "rows": (s["morph_per_mesh"] as Array).size(),
				"summary": s.get("morph_per_mesh_summary", {})})
			shot_level.append(s["name"])
		if s.has("figures"):
			for j in (s["figures"] as Array).size():
				var f: Dictionary = s["figures"][j]
				if f.has("morph_per_mesh"):
					entries.append({"where": "shots[%s].figures[%d].morph_per_mesh" % [s["name"], j],
						"characters": 1, "rows": (f["morph_per_mesh"] as Array).size(),
						"figure": "%s/%s" % [f.get("family", ""), f.get("outfit_style", "")],
						"summary": f.get("morph_per_mesh_summary", {})})
		if s.has("routes"):
			for j in (s["routes"] as Array).size():
				var rt: Dictionary = s["routes"][j]
				if rt.has("morph_per_mesh"):
					entries.append({"where": "shots[%s].routes[%d].morph_per_mesh" % [s["name"], j],
						"characters": 1, "rows": (rt["morph_per_mesh"] as Array).size(),
						"force_overlay": rt.get("force_overlay", null),
						"summary": rt.get("morph_per_mesh_summary", {})})
		if s.has("page") and (s["page"] as Dictionary).has("morph_per_mesh"):
			entries.append({"where": "shots[%s].page.morph_per_mesh" % s["name"],
				"characters": 1, "rows": ((s["page"] as Dictionary)["morph_per_mesh"] as Array).size(),
				"summary": (s["page"] as Dictionary).get("morph_per_mesh_summary", {})})
		var rows := 0
		for e in entries:
			rows += int(e["rows"])
		total += rows
		per_shot.append({"shot": s["name"], "kind": s["kind"], "where": entries,
			"rows": rows, "shot_level_key": s.has("morph_per_mesh")})
	var all_ok := true
	for s in per_shot:
		if int(s["rows"]) == 0:
			all_ok = false
	return {"definition": ("每次渲染一个被 morph 驱动的角色，就在该角色所在层级留一份逐 mesh 行；"
		+ "shot 级 morph_per_mesh 只有 solo 镜头有，montage/page/p1_vs_p3 分别在 "
		+ "figures[j] / page / routes[k] 里"),
		"rows_total": total, "every_shot_has_rows": all_ok,
		"shots_with_shot_level_key": shot_level, "per_shot": per_shot}


func _readout_text(p) -> String:
	return p._readout.text if p._readout != null else ""

func _run() -> void:
	await process_frame
	t_start = Time.get_ticks_msec()
	print("== artstudio T3 Godot preview shots ==")
	print("Godot ", Engine.get_version_info().string, "  ROOT ", CFG.ROOT)
	print("cache ", CFG.cache_dir(), "  blender ", CFG.blender_bin())
	print("CJK font: ", UF.font_path(), "  mono: ", UF.mono().resource_path if UF.mono() != null else "<none>")

	# 1-3 三档
	await _shot_solo("female_thin", "Female", "Ranger", "Hair_Long", -1.0, 1.0, 820, 1180,
		"BS_Thin=1.0  k=-1.00")
	await _shot_solo("female_standard", "Female", "Ranger", "Hair_Long", 0.0, 1.0, 820, 1180,
		"Basis  k=0.00")
	await _shot_solo("female_heavy", "Female", "Ranger", "Hair_Long", 1.0, 1.0, 820, 1180,
		"BS_Heavy=1.0  k=+1.00")

	# 4-5 三档并排
	await _shot_montage("bodyshape_female_3tiers", [
		{"family": "Female", "style": "Ranger", "hair": "Hair_Long", "k": -1.0, "caption": "BS_Thin=1"},
		{"family": "Female", "style": "Ranger", "hair": "Hair_Long", "k": 0.0, "caption": "Basis"},
		{"family": "Female", "style": "Ranger", "hair": "Hair_Long", "k": 1.0, "caption": "BS_Heavy=1"},
	], 2280, 1180, "Female_Ranger  BS_Thin / Basis / BS_Heavy  (h=1.00)")
	await _shot_montage("bodyshape_male_3tiers", [
		{"family": "Male", "style": "Peasant", "hair": "Hair_Buzzed", "k": -1.0, "caption": "BS_Thin=1"},
		{"family": "Male", "style": "Peasant", "hair": "Hair_Buzzed", "k": 0.0, "caption": "Basis"},
		{"family": "Male", "style": "Peasant", "hair": "Hair_Buzzed", "k": 1.0, "caption": "BS_Heavy=1"},
	], 2280, 1180, "Male_Peasant  BS_Thin / Basis / BS_Heavy  (h=1.00)")

	# 6 身高扫描
	await _shot_montage("height_sweep", [
		{"family": "Female", "style": "Ranger", "hair": "Hair_Long", "k": 0.0, "h": 0.92, "caption": "h=0.92", "bar": true},
		{"family": "Female", "style": "Ranger", "hair": "Hair_Long", "k": 0.0, "h": 1.00, "caption": "h=1.00", "bar": true},
		{"family": "Female", "style": "Ranger", "hair": "Hair_Long", "k": 0.0, "h": 1.08, "caption": "h=1.08", "bar": true},
	], 2280, 1180, "Height = root bone uniform scale (no morph)  k=0.00")

	# 7 四套服装
	await _shot_montage("outfits_4", [
		{"family": "Female", "style": "Ranger", "k": 0.0, "caption": "F_Ranger"},
		{"family": "Female", "style": "Peasant", "k": 0.0, "caption": "F_Peasant"},
		{"family": "Male", "style": "Ranger", "k": 0.0, "caption": "M_Ranger"},
		{"family": "Male", "style": "Peasant", "k": 0.0, "caption": "M_Peasant"},
	], 2760, 1180, "Outfit swap  (k=0.00)")

	# 8 四款发型
	await _shot_montage("hair_4", [
		{"family": "Female", "style": "Ranger", "hair": "Hair_Buzzed", "k": 0.0, "caption": "Buzzed"},
		{"family": "Female", "style": "Ranger", "hair": "Hair_SimpleParted", "k": 0.0, "caption": "SimpleParted"},
		{"family": "Female", "style": "Ranger", "hair": "Hair_Buns", "k": 0.0, "caption": "Buns"},
		{"family": "Female", "style": "Ranger", "hair": "Hair_Long", "k": 0.0, "caption": "Long"},
	], 2760, 1180, "Hairstyle swap  (k=0.00)")

	# 8.5 P1 vs P3 对照（复现 verifier 的诊断：橙斑是不是"多叠了一具身体"造成的）
	_pen_free()
	await _shot_p1_vs_p3("debug_p1_vs_p3", "Female", "Ranger", "Hair_Long", -1.0, 760, 1080)

	# 9 页面整页：k=-0.85 时穿模指示应已越过 rest 基线 + 2%
	_pen_free()
	await _shot_page("ui_page", "Female", "Peasant", "Hair_Long", -0.85, 1.02, 1560, 1010)

	# ---- 像素法完整曲线 + 身高一致性（**4 套服装全部**）----
	_pen_free()
	for f in [["Female", "Female_Ranger", "Hair_Long"], ["Female", "Female_Peasant", "Hair_Long"],
			["Male", "Male_Ranger", "Hair_Buzzed"], ["Male", "Male_Peasant", "Hair_Buzzed"]]:
		var fam: String = f[0]
		var gk: String = f[1]
		var hk: String = f[2]
		var pm: RefCounted = await _pen_for(fam, gk, hk)
		if pm == null:
			pen_summary[gk] = {"error": "测量器不可用或双向标定未通过"}
			continue
		var curve: Dictionary = await pm.measure_curve(PENP.AZ_ALL)
		var hu: Dictionary = await pm.measure_height_uniformity(CFG.H_MAX)
		pen_summary[gk] = {"curve_pixel_method": curve, "height_uniformity": hu,
			"calibration": pm.calibration, "route": pm.route,
			"assets": {"body": fam, "garment": gk, "hair": hk}}
		print("PEN ", gk, " calib=", JSON.stringify(pm.calibration), " baseline=",
			curve.get("rest_baseline_pct"), " first_k=",
			curve.get("first_k_over_baseline_plus_2pct"),
			" mean=", curve.get("mean_pct"), " union=",
			curve.get("rows", [{}])[0].get("per_azimuth", [{}])[0].get("penetration_pct_of_union"))
		print("HEIGHT ", gk, " node_disp=",
			hu["modes"]["node_scale"]["dispersion"], " bone_disp=",
			hu["modes"]["bone_root_scale"]["dispersion"])
	_pen_free()

	# ---- 穿模曲线汇总：**4 套服装全部**（像素法，唯一的口径）----
	# BVH 参考法已从流程摘除（见 README §3）：对非闭合网格正负号不可靠，
	# 留着只会让人把它的数当成本页口径 —— 已实测导致过一次"两个数对不上账"。
	var pends: Dictionary = {}
	for fam in ["Female", "Male"]:
		var keys: Array = []
		for st in ["Ranger", "Peasant"]:
			keys.append(fam + "_" + st)
		pends[fam] = {"note": "已被像素法取代，本页不再产出 BVH 数字", "keys": keys}

	var prov := BAKE.provenance(["Female", "Male"],
		["Female_Ranger", "Female_Peasant", "Male_Ranger", "Male_Peasant"])
	print("PROVENANCE ", JSON.stringify(prov["checks"]), " bodyshape=",
		prov["manifests"]["bodyshape"]["coefficients_fingerprint"].substr(0, 12),
		" garment=", prov["manifests"]["garment"]["coefficients_fingerprint"].substr(0, 12),
		" coefficients=", JSON.stringify(prov["manifests"]["bodyshape"]["coefficients"]))
	var report := {
		"tool": "tools/3d/godot/preview",
		"task": "T3 Godot 4 交互预览页面（task/007-morph-pipeline）",
		"generated_at": Time.get_datetime_string_from_system(true),
		"godot": Engine.get_version_info().string,
		"blender_bin": CFG.blender_bin(),
		"root": CFG.ROOT,
		"cache_dir": CFG.cache_dir(),
		"fonts": {"cjk": UF.font_path(), "mono": UF.mono().resource_path if UF.mono() != null else ""},
		"one_command": "%s --path tools/3d/godot/preview -s res://shoot.gd --resolution 640x480" % CFG.GODOT_DEFAULT,
		"elapsed_ms": Time.get_ticks_msec() - t_start,
		"bake_log": BAKE.log_lines,
		"assets": assets,
		"penetration_pixel_method_curves": pen_summary,
		"penetration_method_note": ("本页**唯一**的穿模口径 = 像素法（见 penetration_pixel_method_curves[gk]"
			+ ".curve_pixel_method.normalization）。标准体不是闭合曲面（26 连通域 / 48 边界环 / 面绕向不一致），"
			+ "BVH 有符号距离法正负号不可靠 → 已从流程摘除，不再产出任何数字，"
			+ "以免与像素法混用（实测踩过：同一件东西出现两个差一倍以上的数）。"),
		"penetration_deprecated_bvh": pends,
		"shots": shots,
		"asset_provenance": prov,
		"zero_copy": {"assets_copied_into_project": 0,
			"note": "所有 .blend 由 Blender headless 预导出为 .glb 到 tmp/ 缓存（工程外），Godot 运行时用 GLTFDocument 读绝对路径；工程目录内只有代码与 project.godot。"},
	}
	report["morph_per_mesh_coverage"] = _per_mesh_coverage(shots)
	BAKE.write_json(OUT + "/preview_report.json", report)
	# 逐件 morph 的紧凑表也单独落一份，方便人直接看
	var per_shot := {}
	for s in shots:
		var rows: Array = []
		if s.has("morph_per_part_compact"):
			rows = s["morph_per_part_compact"]
		elif s.has("figures"):
			for f in s["figures"]:
				rows.append({"figure": "%s/%s" % [f["family"], f["outfit_style"]],
					"parts": f.get("morph_per_part_compact", [])})
		elif s.has("page"):
			rows = s["page"].get("compact_morph_per_part", [])
		per_shot[s["name"]] = {"png": s["png"], "k": s.get("k", null), "h": s.get("h", null),
			"garment_key": s.get("garment_key", s.get("page", {}).get("garment_key", "")),
			"morph_per_part": rows}
	BAKE.write_json(OUT + "/preview_morph_receipt.json", {
		"note": ("逐 **mesh** 一行的实测读回（件级证据，不只按角色聚合）："
			+ "morph_per_mesh 每行含 {part, part_key, mesh, path, blend_shape_names, thin_index, heavy_index, "
			+ "thin_value_set/read_back, heavy_value_set/read_back, contract_ok, read_back_ok}"),
		"contract": "SPEC §3.3  [BS_Thin(index 0), BS_Heavy(index 1)]",
		"shots": per_shot})
	print("REPORT ", OUT, "/preview_report.json  shots=", shots.size(),
		" elapsed_ms=", report["elapsed_ms"])
	for s in shots:
		var st: Dictionary = s.get("image_stats", s.get("image_stats_p1", {}))
		print("  - %s  min_margin=%d px  cropped=%s" % [s["name"],
			int(st.get("min_margin_px", -1)), str(st.get("cropped", true))])
	quit()