## verifier 独立探针：在**独立工程**里复算 T3 的三条 Godot 断言。
extends SceneTree

const GLB := "/Users/zhenkunzhu/Desktop/project/artstudio/tmp/godot_preview_cache/glb/Female_Ranger.glb"

func _initialize() -> void:
	print("=== verifier Godot 探针 ===")
	print("godot ", Engine.get_version_info().string)
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	var err := doc.append_from_file(GLB, st)
	print("load err=", err)
	var root := doc.generate_scene(st)
	print("root=", root.name if root else "<null>")

	# 找第一个带 blend shape 的 MeshInstance3D，以及骨架
	var mi: MeshInstance3D = null
	var sk: Skeleton3D = null
	var stack: Array = [root]
	while stack.size() > 0:
		var n: Node = stack.pop_back()
		if n is MeshInstance3D and mi == null:
			var m: Mesh = (n as MeshInstance3D).mesh
			if m != null and m.get_blend_shape_count() > 0:
				mi = n
		if n is Skeleton3D and sk == null:
			sk = n
		for c in n.get_children():
			stack.append(c)
	print("mi=", mi.name if mi else "<null>", " sk=", sk.name if sk else "<null>",
		" blendshapes=", (mi.mesh.get_blend_shape_count() if mi else -1),
		" names=", (mi.mesh.get_blend_shape_name(0) if mi else "-"))

	# ---- 断言 3：get_aabb() 是静止(rest)网格 AABB ----
	root.process_mode = Node.PROCESS_MODE_DISABLED
	get_root().add_child(root)
	await process_frame
	await process_frame
	var a0 := mi.get_aabb()
	print("[A3] aabb@rest      = ", a0)
	if sk != null and sk.find_bone("upperarm_l") >= 0:
		var b := sk.find_bone("upperarm_l")
		sk.set_bone_pose_rotation(b, Quaternion(Vector3(1,0,0), deg_to_rad(90.0)))
		await process_frame
		await process_frame
		var a1 := mi.get_aabb()
		print("[A3] aabb@bone90    = ", a1, "  逐位相同=", a1 == a0)
		var gp := sk.get_bone_global_pose(b)
		print("[A3] bone_global_pose=", gp.origin, " basis_euler=", gp.basis.get_euler() * 180.0 / PI)
	if mi.mesh.get_blend_shape_count() > 0:
		mi.set_blend_shape_value(0, 1.0)
		await process_frame
		await process_frame
		print("[A3] aabb@BS_Thin=1 = ", mi.get_aabb(),
			"  逐位相同=", mi.get_aabb() == a0)
		print("[A3] read_back      = ", mi.get_blend_shape_value(0))
	# 反证：mesh 的 AABB 到底有没有随 blend shape 变？（用 Mesh 自身 API 对照）
	print("[A3] mesh.get_aabb()=", mi.mesh.get_aabb(), " surface_count=", mi.mesh.get_surface_count())
	quit()
