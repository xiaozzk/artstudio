extends SceneTree

func _initialize() -> void:
	var ps: PackedScene = load("res://morph_demo.glb")
	if ps == null:
		print("FAIL: 无法加载 GLB"); quit(1); return
	var root: Node = ps.instantiate()

	# 1) 权威核实：MeshInstance3D 上与骨架相关的属性/方法到底叫什么
	print("--- MeshInstance3D 的 skeleton 相关属性 ---")
	for p in (root.get_child(0) as MeshInstance3D).get_property_list():
		var n: String = str(p.get("name", ""))
		if n.contains("skeleton") or n.contains("skin"):
			print("    property: ", n, "  type=", p.get("type"))

	# 2) morph target 是否带过来了
	print("--- morph target ---")
	var meshes := 0
	var with_fat := 0
	for child in root.get_children():
		if child is MeshInstance3D:
			meshes += 1
			var mi: MeshInstance3D = child
			var m: Mesh = mi.mesh
			print("node=", mi.name, " mesh=", m.resource_name,
				" blend_shape_count=", mi.get_blend_shape_count(),
				" has_skin=", mi.skin != null,
				" skeleton=", mi.get_skeleton_path())
			for i in mi.get_blend_shape_count():
				print("    [", i, "] name=", m.get_blend_shape_name(i), " value=", mi.get_blend_shape_value(i))
			var idx := mi.find_blend_shape_by_name(&"fat")
			if idx >= 0:
				with_fat += 1
				mi.set_blend_shape_value(idx, 1.0)
				print("    -> 设 fat=1.0 后读回: ", mi.get_blend_shape_value(idx))
	print("SUMMARY meshes=", meshes, " with_fat=", with_fat, " -> ",
		"PASS" if meshes > 0 and with_fat == meshes else "FAIL")
	quit(0)
