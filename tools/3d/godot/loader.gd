extends RefCounted
## 运行时加载器：用 GLTFDocument 直接读磁盘绝对路径的 .gltf，绕过 Godot 导入管线。
## 好处：工程里不需要复制任何 .bin/贴图（素材包贴图合计 ~125MB）。

static func load_scene(abs_path: String) -> Node:
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	var err := doc.append_from_file(abs_path, state)
	if err != OK:
		push_error("GLTF append_from_file 失败 %s err=%d" % [abs_path, err])
		return null
	return doc.generate_scene(state)


## 递归统计：骨架数/骨数/网格数/表面数/材质贴图缺失情况。
## 注意：节点未入场景树时 global_transform 不可用（会报 "!is_inside_tree()"），
## 所以这里手工自顶向下累积变换，而不是取 global_transform。
static func taxonomy(n: Node, acc: Dictionary = {}, xf: Transform3D = Transform3D()) -> Dictionary:
	if acc.is_empty():
		acc = {"skeletons": [], "meshes": 0, "surfaces": 0, "tris": 0, "materials": {}, "untextured": [],
			"aabb_min": Vector3(1e9, 1e9, 1e9), "aabb_max": Vector3(-1e9, -1e9, -1e9)}
	if n is Node3D:
		xf = xf * (n as Node3D).transform
	if n is Skeleton3D:
		var sk := n as Skeleton3D
		acc["skeletons"].append({"name": String(sk.name), "bones": sk.get_bone_count(),
			"head_idx": sk.find_bone("Head")})
	if n is MeshInstance3D:
		var mi := n as MeshInstance3D
		acc["meshes"] += 1
		if mi.mesh:
			acc["surfaces"] += mi.mesh.get_surface_count()
			acc["tris"] += mi.mesh.get_faces().size() / 3
			var bb := mi.get_aabb()
			for i in 8:
				var p: Vector3 = xf * bb.get_endpoint(i)
				acc["aabb_min"] = acc["aabb_min"].min(p)
				acc["aabb_max"] = acc["aabb_max"].max(p)
			for s in mi.mesh.get_surface_count():
				var m := mi.get_active_material(s)
				var mname := "<null>" if m == null else String(m.resource_name) if m.resource_name else m.get_class()
				var has_tex := false
				if m is BaseMaterial3D:
					has_tex = (m as BaseMaterial3D).albedo_texture != null
				acc["materials"][mname] = has_tex
				if not has_tex:
					acc["untextured"].append("%s/surf%d" % [mi.name, s])
	for c in n.get_children():
		taxonomy(c, acc, xf)
	return acc