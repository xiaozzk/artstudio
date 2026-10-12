extends SceneTree

const HAIRS := ["Eyebrows_Regular", "Eyebrows_Female", "Hair_Beard", "Hair_Buzzed",
	"Hair_BuzzedFemale", "Hair_SimpleParted", "Hair_Buns", "Hair_Long"]

func _initialize() -> void:
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.11, 0.11, 0.13)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(1, 1, 1)
	e.ambient_light_energy = 0.75
	var we := WorldEnvironment.new()
	we.environment = e
	root.add_child(we)
	var l := DirectionalLight3D.new()
	l.rotation_degrees = Vector3(-40, -35, 0)
	l.light_energy = 1.5
	root.add_child(l)
	var cam := Camera3D.new()
	cam.fov = 46.0
	cam.position = Vector3(0, 1.15, 7.0)
	root.add_child(cam)
	cam.look_at(Vector3(0, 1.02, 0.8))
	_place("Superhero_Male_FullBody", 0.0)
	_place("Superhero_Female_FullBody", 1.55)
	_run()

func _place(body: String, z: float) -> void:
	var n := HAIRS.size()
	for i in n:
		var x := (float(i) - (n - 1) / 2.0) * 0.95
		var b: Node3D = (load("res://%s.gltf" % body) as PackedScene).instantiate()
		b.position = Vector3(x, 0, z)
		root.add_child(b)
		var h: Node3D = (load("res://%s.gltf" % HAIRS[i]) as PackedScene).instantiate()
		h.position = Vector3(x, 0, z)
		root.add_child(h)
		var lab := Label3D.new()
		lab.text = HAIRS[i]
		lab.font_size = 96
		lab.pixel_size = 0.0016
		lab.modulate = Color(1, 0.95, 0.6)
		lab.position = Vector3(x, 0.02, z - 0.25)
		lab.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		lab.no_depth_test = true
		root.add_child(lab)

func _run() -> void:
	for i in 8:
		await process_frame
	var img := root.get_texture().get_image()
	var p := ProjectSettings.globalize_path("res://sheet.png")
	var err := img.save_png(p)
	print("saved=", p, " err=", err, " size=", img.get_size())
	quit()
