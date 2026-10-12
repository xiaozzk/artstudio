extends SceneTree

func _initialize() -> void:
	for f in ["res://Superhero_Male_FullBody.gltf", "res://Hair_Long.gltf"]:
		var ps: PackedScene = load(f)
		if ps == null:
			print("LOAD FAILED: ", f)
			continue
		var root: Node = ps.instantiate()
		print("=== ", f, " -> root class=", root.get_class(), " name=", root.name)
		_walk(root, 1)
		root.free()
	quit()

func _walk(n: Node, d: int) -> void:
	var extra := ""
	if n is Skeleton3D:
		var sk := n as Skeleton3D
		extra = " bones=%d" % sk.get_bone_count()
		if sk.find_bone("Head") >= 0:
			extra += " Head_idx=%d" % sk.find_bone("Head")
	if n is MeshInstance3D:
		var mi := n as MeshInstance3D
		var aabb := mi.get_aabb()
		extra = " surf=%d aabb=%s" % [mi.mesh.get_surface_count() if mi.mesh else -1, str(aabb.size.snapped(Vector3(0.001,0.001,0.001)))]
	print("  ".repeat(d), n.get_class(), " ", n.name, extra)
	for c in n.get_children():
		_walk(c, d + 1)
