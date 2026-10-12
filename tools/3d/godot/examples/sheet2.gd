extends SceneTree

const HAIRS := ["Eyebrows_Regular", "Eyebrows_Female", "Hair_Beard", "Hair_Buzzed",
	"Hair_BuzzedFemale", "Hair_SimpleParted", "Hair_Buns", "Hair_Long"]
const TINTS := [Color(0.25, 0.15, 0.08), Color(0.95, 0.80, 0.40), Color(0.55, 0.18, 0.08), Color(0.06, 0.06, 0.07),
	Color(0.80, 0.82, 0.88), Color(0.20, 0.35, 0.80), Color(0.90, 0.45, 0.70), Color(0.22, 0.55, 0.30)]

func _initialize() -> void:
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.12, 0.12, 0.14)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_energy = 0.85
	var we := WorldEnvironment.new()
	we.environment = e
	root.add_child(we)
	var l := DirectionalLight3D.new()
	l.rotation_degrees = Vector3(-38, -30, 0)
	l.light_energy = 1.3
	root.add_child(l)
	var cam := Camera3D.new()
	cam.fov = 42.0
	root.add_child(cam)
	cam.look_at_from_position(Vector3(0, 1.25, 6.2), Vector3(0, 1.0, 1.05), Vector3.UP)
	_place("Superhero_Male_FullBody", 0.0)
	_place("Superhero_Female_FullBody", 1.6)
	_run()

func _place(body: String, z: float) -> void:
	var n := HAIRS.size()
	for i in n:
		var x := (float(i) - (n - 1) / 2.0) * 1.05
		var b: Node3D = (load("res://%s.gltf" % body) as PackedScene).instantiate()
		b.position = Vector3(x, 0, z)
		root.add_child(b)
		var h: Node3D = (load("res://%s.gltf" % HAIRS[i]) as PackedScene).instantiate()
		h.position = Vector3(x, 0, z)
		_tint(h, TINTS[i])
		root.add_child(h)
		var lab := Label3D.new()
		lab.text = HAIRS[i].replace("Hair_", "").replace("Eyebrows_", "Br_")
		lab.font_size = 42
		lab.pixel_size = 0.0022
		lab.position = Vector3(x, 0.03, z - 0.35)
		lab.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		lab.no_depth_test = true
		root.add_child(lab)

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

func _run() -> void:
	for i in 8:
		await process_frame
	var p := ProjectSettings.globalize_path("res://sheet_tinted.png")
	print("saved err=", root.get_texture().get_image().save_png(p), " -> ", p)
	quit()
