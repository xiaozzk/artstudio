extends SceneTree
## 渲染①：2 形体 × 8 发型 = 16 个换装实例总览。
## 发型用 Rigged to Head Bone 变体（65 骨同名 rig），直接作为形体的同级节点叠在同一位置即可对齐。
## 注意：SceneTree._initialize() 里不能 await，所以用「_initialize 起协程 + await process_frame」的写法。

const CFG = preload("res://cfg.gd")
const LDR = preload("res://loader.gd")
const ST = preload("res://stage.gd")

const HAIR_ORDER := ["Eyebrows_Regular", "Eyebrows_Female", "Hair_Beard", "Hair_Buzzed",
	"Hair_BuzzedFemale", "Hair_SimpleParted", "Hair_Buns", "Hair_Long"]
const BODY_ORDER := ["Male_Superhero", "Female_Superhero"]
const DX := 2.05
const DY := 2.95
const W := 3200
const H := 1250
## 包的 T_Hair_*_BaseColor 是"可着色的中性底色"（作者留给运行时染发的 mask），
## 所以原样渲染时头发偏灰白。加 -- tint 用户参数可上一轮色调，用来证明材质/贴图是在的。
const TINTS := [Color(0.25, 0.15, 0.08), Color(0.95, 0.80, 0.40), Color(0.55, 0.18, 0.08),
	Color(0.06, 0.06, 0.07), Color(0.80, 0.82, 0.88), Color(0.20, 0.35, 0.80),
	Color(0.90, 0.45, 0.70), Color(0.22, 0.55, 0.30)]

func _initialize() -> void:
	_run()

func _run() -> void:
	# 先等一帧：SceneTree._initialize() 期间 root 尚未完全入树，
	# 此时 add_child 进去的相机 cam.get_viewport() 会是 null（实测踩过）。
	await process_frame
	var want_tint := OS.get_cmdline_user_args().has("tint")
	var png_name := "render_hair_swap_2x8_tinted.png" if want_tint else "render_hair_swap_2x8.png"
	var out := {"instances": 0, "bodies": BODY_ORDER, "hairs": HAIR_ORDER, "skeletons": [],
		"untextured": [], "labels": [], "render": png_name, "resolution": [W, H], "tinted": want_tint}
	var vp := ST.make_viewport(self, W, H)
	var bg := Color(0.105, 0.11, 0.125)
	ST.make_env(vp, bg)
	var cam := Camera3D.new()
	vp.add_child(cam)
	cam.current = true
	var corners: Array = []

	for r in BODY_ORDER.size():
		var body_key: String = BODY_ORDER[r]
		var y_base := float(r) * DY
		var row_lab := _label(body_key, Vector3(-(HAIR_ORDER.size() - 1) * 0.5 * DX - 1.5, y_base + 0.95, 0.0), 52, 0.0050)
		row_lab.modulate = Color(1.0, 0.92, 0.55)
		vp.add_child(row_lab)
		corners.append(row_lab.position + Vector3(-0.95, -0.16, 0))
		corners.append(row_lab.position + Vector3(0.95, 0.16, 0))
		out["labels"].append(body_key)

		for c in HAIR_ORDER.size():
			var hair_key: String = HAIR_ORDER[c]
			var x := (float(c) - (HAIR_ORDER.size() - 1) / 2.0) * DX
			var pos := Vector3(x, y_base, 0.0)
			var b := LDR.load_scene(CFG.BODIES[body_key])
			if b == null:
				out["untextured"].append("BODY_LOAD_FAIL:" + body_key)
				continue
			b.position = pos
			vp.add_child(b)
			# 基础体自带的 Eyebrows 与 Eyebrows_* 发型件完全重合（同 rig 同位置），
			# 同时显示会 z-fighting，所以换装演示里隐藏基础体那一件。
			_hide_named(b, "Eyebrows")
			var h := LDR.load_scene(CFG.HAIRS[hair_key])
			if h == null:
				out["untextured"].append("HAIR_LOAD_FAIL:" + hair_key)
				continue
			h.position = pos
			vp.add_child(h)
			if want_tint:
				_tint(h, TINTS[c])

			for inst in [b, h]:
				for p in ST.corners_of(inst):
					corners.append(p)

			var txb := LDR.taxonomy(b)
			var txh := LDR.taxonomy(h)
			out["skeletons"].append({"body": body_key, "hair": hair_key,
				"body_bones": txb["skeletons"][0]["bones"] if txb["skeletons"].size() > 0 else -1,
				"hair_bones": txh["skeletons"][0]["bones"] if txh["skeletons"].size() > 0 else -1,
				"body_head_idx": txb["skeletons"][0]["head_idx"] if txb["skeletons"].size() > 0 else -1,
				"hair_head_idx": txh["skeletons"][0]["head_idx"] if txh["skeletons"].size() > 0 else -1})
			out["untextured"] += txb["untextured"] + txh["untextured"]

			var lab := _label(hair_key.replace("Hair_", "").replace("Eyebrows_", "Br_"), Vector3(x, y_base - 0.10, 0.0), 44, 0.0044)
			vp.add_child(lab)
			corners.append(lab.position + Vector3(-0.55, -0.13, 0))
			corners.append(lab.position + Vector3(0.55, 0.13, 0))
			out["instances"] += 1

	var fit := ST.auto_frame(cam, corners, 38.0, 9.0, 1.06, Vector2(W, H))
	print("FIT ", fit)
	out["fit"] = fit
	for i in 16:
		await process_frame
	var px := ST.save(vp, png_name)
	out["image"] = px
	var stats := ST.image_stats(vp.get_texture().get_image(), bg)
	out["image_stats"] = stats
	out["bg"] = bg.to_html()
	_write("res://logs/render_hair_tinted.json" if want_tint else "res://logs/render_hair.json", out)
	print("HAIR_SWAP instances=", out["instances"], " skeletons=", out["skeletons"].size(),
		" untextured=", out["untextured"])
	print("HAIR_SWAP stats=", stats)
	quit()

func _label(text: String, pos: Vector3, fsize: int, pix: float) -> Label3D:
	var l := Label3D.new()
	l.text = text
	l.font_size = fsize
	l.pixel_size = pix
	l.position = pos
	l.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	l.no_depth_test = true
	l.outline_size = 14
	l.shaded = false
	return l

func _tint(n: Node, col: Color) -> void:
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
		_tint(c, col)

func _hide_named(n: Node, want: String) -> void:
	if n is MeshInstance3D and String(n.name) == want:
		(n as MeshInstance3D).visible = false
	for c in n.get_children():
		_hide_named(c, want)

func _write(path: String, data: Dictionary) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(data, "  "))
		f.close()