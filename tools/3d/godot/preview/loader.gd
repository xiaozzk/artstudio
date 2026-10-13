extends RefCounted
## 运行时加载器（改写自 `tools/3d/godot/loader.gd`，口径一致）。
##
## 用 `GLTFDocument.append_from_file(<磁盘绝对路径>)` 直接读工程外的 `.glb`，
## 绕过 Godot 导入管线 —— 工程里因此**没有任何素材副本**（这套素材贴图合计 ~125 MB）。

static func load_scene(abs_path: String) -> Node:
	if not FileAccess.file_exists(abs_path):
		push_error("素材不存在：%s" % abs_path)
		return null
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	var err := doc.append_from_file(abs_path, state)
	if err != OK:
		push_error("GLTFDocument.append_from_file 失败 %s err=%d" % [abs_path, err])
		return null
	return doc.generate_scene(state)


## 递归找第一个 Skeleton3D（**按类型找，不硬编码 bone index**）。
static func first_skeleton(n: Node) -> Skeleton3D:
	if n is Skeleton3D:
		return n as Skeleton3D
	for c in n.get_children():
		var s := first_skeleton(c)
		if s != null:
			return s
	return null


static func all_skeletons(n: Node, acc: Array = []) -> Array:
	if n is Skeleton3D:
		acc.append(n)
	for c in n.get_children():
		all_skeletons(c, acc)
	return acc


## 递归统计：骨架数/骨数/网格数/三角面/贴图缺失。
## 注意：节点未入场景树时 `global_transform` 不可用，所以手工自顶向下累积变换。
static func taxonomy(n: Node, acc: Dictionary = {}, xf: Transform3D = Transform3D()) -> Dictionary:
	if acc.is_empty():
		acc = {"skeletons": [], "meshes": 0, "surfaces": 0, "tris": 0, "materials": {},
			"untextured": [], "morph_meshes": 0,
			"aabb_min": Vector3(1e9, 1e9, 1e9), "aabb_max": Vector3(-1e9, -1e9, -1e9)}
	if n is Node3D:
		xf = xf * (n as Node3D).transform
	if n is Skeleton3D:
		var sk := n as Skeleton3D
		acc["skeletons"].append({"name": String(sk.name), "bones": sk.get_bone_count(),
			"head_idx": sk.find_bone("Head"), "root_idx": sk.find_bone("root")})
	if n is MeshInstance3D:
		var mi := n as MeshInstance3D
		acc["meshes"] += 1
		if mi.mesh:
			acc["surfaces"] += mi.mesh.get_surface_count()
			acc["tris"] += mi.mesh.get_faces().size() / 3
			if mi.mesh.get_blend_shape_count() > 0:
				acc["morph_meshes"] += 1
			var bb := mi.get_aabb()
			for i in 8:
				var p: Vector3 = xf * bb.get_endpoint(i)
				acc["aabb_min"] = acc["aabb_min"].min(p)
				acc["aabb_max"] = acc["aabb_max"].max(p)
			for s in mi.mesh.get_surface_count():
				var m := mi.get_active_material(s)
				var mname := ""
				if m == null:
					mname = "<null>"
				elif m.resource_name:
					mname = String(m.resource_name)
				else:
					mname = m.get_class()
				var has_tex := false
				if m is BaseMaterial3D:
					has_tex = (m as BaseMaterial3D).albedo_texture != null
				acc["materials"][mname] = has_tex
				if not has_tex:
					acc["untextured"].append("%s/surf%d" % [mi.name, s])
	for c in n.get_children():
		taxonomy(c, acc, xf)
	return acc