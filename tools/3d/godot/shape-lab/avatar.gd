extends RefCounted
## 角色装载与驱动（契约 v1）。
##
## 零拷贝：`GLTFDocument.append_from_file(<绝对路径>)` 直接读缓存里的 .glb，工程内没有任何副本。
## 口径：
##   * 体形 k ∈ [-1,1] → BS_Thin = max(-k,0)、BS_Heavy = max(k,0)，驱动场景里**每一件**带该 morph 的网格；
##   * 身高 h ∈ [0.92,1.08] → 缩放**角色根节点** scale=(h,h,h)，**绝不碰任何骨 pose**；
##   * 取骨一律 `find_bone("Head")` **按名字**（跨路线索引会变：.blend 路线 54 / glTF 路线 6）。
##
## 环境光/材质与网格无关；`get_aabb()` 是**静止 AABB**（不随 morph/pose 变），
## 所以取景与变形证据都用 `world_aabb()` —— 按当前 morph 解析式复算顶点。

const CACHE = preload("res://cache.gd")

## role 分类（契约 v1.1，命中即止；manifest 里已给 role 时以 manifest 为准，这里是兜底）：
##   1 head      "Head_" 前缀 / ^(Eyebrows|Eyes)$ / "_Eyebrows"|"_Eyes" 结尾 / "Hair_" 前缀
##   2 skin      任一材质名含 "MI_Regular_" / "Body_" 前缀
##   3 foot      "_Feet" 结尾 / 含 "Boots"
##   4 accessory 含 "Acc_" | "_Belt" | "_Bracer" | "_Hood"
##   5 cloth     其余
const ACC_HINTS := ["Acc_", "_Belt", "_Bracer", "_Hood"]

## **只有 `ArrayMesh` 有 blend shape 通道**：`Mesh` 基类上只有虚函数 `_get_blend_shape_count()`，
## 对 `BoxMesh` 之类直接调具体方法会报 "Nonexistent function 'get_blend_shape_count' in base 'BoxMesh'"
## （GLTF 出来的都是 ArrayMesh，所以真数据掩盖了这个坑，是 `--fixtures` 的 BoxMesh 把它顶出来的）。
static func shape_count(m: Mesh) -> int:
	if m is ArrayMesh:
		return (m as ArrayMesh).get_blend_shape_count()
	return 0

static func shape_name(m: Mesh, i: int) -> String:
	if m is ArrayMesh:
		return String((m as ArrayMesh).get_blend_shape_name(i))
	return ""

static func role_of(mesh_name: String, mi: MeshInstance3D) -> String:
	if mesh_name.begins_with("Head_") or mesh_name.begins_with("Hair_"):
		return "head"
	if mesh_name == "Eyebrows" or mesh_name == "Eyes":
		return "head"
	if mesh_name.ends_with("_Eyebrows") or mesh_name.ends_with("_Eyes"):
		return "head"
	for s in (mi.mesh.get_surface_count() if mi.mesh != null else 0):
		var m := mi.get_active_material(s)
		if m != null and String(m.resource_name).contains("MI_Regular_"):
			return "skin"
	if mesh_name.begins_with("Body_"):
		return "skin"
	if mesh_name.ends_with("_Feet") or mesh_name.contains("Boots"):
		return "foot"
	for h in ACC_HINTS:
		if mesh_name.contains(h):
			return "accessory"
	return "cloth"

static func _load_glb(abs_path: String) -> Node:
	if not abs_path.is_absolute_path():
		push_error("资产路径必须是绝对路径（相对路径会落进 res://）：%s" % abs_path)
		return null
	if not FileAccess.file_exists(abs_path):
		push_error("资产不存在：%s" % abs_path)
		return null
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	var err := doc.append_from_file(abs_path, st)
	if err != OK:
		push_error("GLTFDocument.append_from_file 失败：%s err=%d" % [abs_path, err])
		return null
	return doc.generate_scene(st)

## 装载一个角色 → 组装字典。返回的 root 由调用方 add_child 到舞台上。
static func build(char: Dictionary) -> Dictionary:
	var a := {"char": char, "root": null, "meshes": [], "skeletons": [], "parts": [],
		"errors": [], "warnings": [], "blend_mode": "none",
		"fixture": bool(char.get("fixture", false))}
	var root := Node3D.new()
	root.name = "Avatar_" + String(char.get("id", "?"))
	if a["fixture"]:
		root.add_child(_fixture_body())
	else:
		var glb := String(char.get("glb", ""))
		var scene := _load_glb(glb)
		if scene == null:
			a["errors"].append("加载失败：%s" % glb)
		else:
			root.add_child(scene)
	a["root"] = root
	_collect(root, a)
	_bind_parts(a)
	a["blend_mode"] = blend_mode(a)
	return a

static func _collect(n: Node, a: Dictionary) -> void:
	if n is MeshInstance3D:
		a["meshes"].append(n)
	if n is Skeleton3D:
		a["skeletons"].append(n)
	for c in n.get_children():
		_collect(c, a)

## 把 manifest 的 parts[]（**节点名**）绑到实际 MeshInstance3D；未登记的网格也各算一件。
static func _bind_parts(a: Dictionary) -> void:
	var by_name := {}
	for mi in a["meshes"]:
		by_name[String(mi.name)] = mi
	var used := {}
	for p in (a["char"] as Dictionary).get("parts", []):
		var nm := String(p.get("name", ""))
		var mi: MeshInstance3D = by_name.get(nm, null)
		if mi == null:                                  # 名字没对上：退化成「包含」匹配
			for k in by_name:
				if String(k).contains(nm) or nm.contains(String(k)):
					mi = by_name[k]
					break
		if mi == null:
			a["warnings"].append("manifest 部件在 glb 里找不到对应节点：%s" % nm)
			continue
		var role := String(p.get("role", ""))
		if role == "":
			role = role_of(String(mi.name), mi)
		used[String(mi.name)] = true
		a["parts"].append({"name": String(mi.name), "role": role, "meshes": [mi],
			"from_manifest": true, "has_morph": bool(p.get("has_morph", false))})
	for mi in a["meshes"]:
		if used.has(String(mi.name)):
			continue
		a["parts"].append({"name": String(mi.name), "role": role_of(String(mi.name), mi),
			"meshes": [mi], "from_manifest": false,
			"has_morph": mi.mesh != null and shape_count(mi.mesh) > 0})
	for p in a["parts"]:
		if p["meshes"].is_empty():
			continue
		var mi2: MeshInstance3D = p["meshes"][0]
		p["has_morph"] = mi2.mesh != null and shape_count(mi2.mesh) > 0

## 契约：名字优先（BS_Thin/BS_Heavy），名字对不上再按索引 0/1 回落。
static func morph_index(mi: MeshInstance3D, want: String, fallback: int) -> int:
	if mi.mesh == null:
		return -1
	var i := mi.find_blend_shape_by_name(want)
	if i >= 0:
		return i
	if shape_count(mi.mesh) > fallback:
		return fallback
	return -1

## 索引驱动：设置 + **逐件回读**（验收要的就是逐件 read-back 证据）。
static func apply(a: Dictionary, k: float, h: float) -> Dictionary:
	var thin: float = maxf(-k, 0.0)
	var heavy: float = maxf(k, 0.0)
	var rows: Array = []
	var n_morph := 0
	for p in a["parts"]:
		var prows: Array = []
		for mi in p["meshes"]:
			if mi.mesh == null or shape_count(mi.mesh) == 0:
				continue
			var it := morph_index(mi, CACHE.MORPH_CONTRACT[0], 0)
			var ih := morph_index(mi, CACHE.MORPH_CONTRACT[1], 1)
			var nt: int = mi.find_blend_shape_by_name(CACHE.MORPH_CONTRACT[0])
			var nh: int = mi.find_blend_shape_by_name(CACHE.MORPH_CONTRACT[1])
			var bt := -1.0
			var bh := -1.0
			if it >= 0:
				mi.set_blend_shape_value(it, thin)
				bt = mi.get_blend_shape_value(it)
			if ih >= 0:
				mi.set_blend_shape_value(ih, heavy)
				bh = mi.get_blend_shape_value(ih)
			var disp := displacement(mi)
			prows.append({"mesh": String(mi.name), "thin_index": it, "heavy_index": ih,
				"names": shape_names(mi), "set_thin": snappedf(thin, 0.0001),
				"read_thin": snappedf(bt, 0.0001), "set_heavy": snappedf(heavy, 0.0001),
				"read_heavy": snappedf(bh, 0.0001), "disp_m": snappedf(disp, 0.000001),
				"name_lookup_ok": nt == 0 and nh == 1,
				"contract_ok": it == 0 and ih == 1,
				"read_back_ok": it >= 0 and ih >= 0 and absf(bt - thin) < 1e-4 and absf(bh - heavy) < 1e-4})
			n_morph += 1
		p["morph_rows"] = prows
		rows.append({"name": String(p["name"]), "role": String(p["role"]), "rows": prows})
	(a["root"] as Node3D).scale = Vector3(h, h, h)
	var all_ok := rows.all(func(r): return (r["rows"] as Array).all(func(x): return bool(x["contract_ok"])))
	return {"k": snappedf(k, 0.0001), "h": snappedf(h, 0.0001), "bs_thin": snappedf(thin, 0.0001),
		"bs_heavy": snappedf(heavy, 0.0001), "height_mode": "avatar_root_uniform_scale",
		"root_scale": (a["root"] as Node3D).scale, "parts": rows, "morph_meshes": n_morph,
		"contract_all_ok": all_ok}

static func shape_names(mi: MeshInstance3D) -> Array:
	var out: Array = []
	if mi.mesh == null:
		return out
	for i in shape_count(mi.mesh):
		out.append(shape_name(mi.mesh, i))
	return out

## Godot 的 blend shape 数组是「绝对位置」还是「相对 delta」？实测判定（口径见 README）。
## 判据：delta 的量级 ≈ 厘米；绝对位置的量级 ≈ 模型尺寸（米）。
static func blend_mode_of(mi: MeshInstance3D) -> String:
	if mi.mesh == null or shape_count(mi.mesh) == 0:
		return "none"
	var base := _verts(mi, -1)
	if base.is_empty():
		return "none"
	var s_abs := 0.0
	var s_del := 0.0
	var n := 0
	for bi in shape_count(mi.mesh):
		var bv := _verts(mi, bi)
		if bv.size() != base.size():
			continue
		var step: int = maxi(1, base.size() / 200)
		var j := 0
		while j < base.size():
			s_abs += bv[j].length()
			s_del += (bv[j] - base[j]).length()
			n += 1
			j += step
	if n == 0:
		return "none"
	return "relative" if s_abs / float(n) < s_del / float(n) else "absolute"

static func blend_mode(a: Dictionary) -> String:
	for mi in a["meshes"]:
		var m := blend_mode_of(mi)
		if m != "none":
			return m
	return "none"

## Godot 4.6 实测签名：`Mesh.surface_get_blend_shape_arrays(surf_idx)` **只吃一个参数**
## （返回「该面上每个 blend shape 的 arrays」数组）；旧文档里的两参数写法会 Parse Error。
static func _verts(mi: MeshInstance3D, blend_idx: int) -> PackedVector3Array:
	var out := PackedVector3Array()
	for s in mi.mesh.get_surface_count():
		var arr: Array = mi.mesh.surface_get_arrays(s)
		if blend_idx >= 0:
			var shapes: Array = mi.mesh.surface_get_blend_shape_arrays(s)
			if blend_idx >= shapes.size() or typeof(shapes[blend_idx]) != TYPE_ARRAY:
				continue
			arr = shapes[blend_idx]
		if arr.size() > Mesh.ARRAY_VERTEX and typeof(arr[Mesh.ARRAY_VERTEX]) == TYPE_PACKED_VECTOR3_ARRAY:
			out.append_array(arr[Mesh.ARRAY_VERTEX])
	return out

## 某网格在当前 morph 值下的**最大单点位移**（米）——「变形真的发生」的直接证据。
static func displacement(mi: MeshInstance3D) -> float:
	if mi.mesh == null or shape_count(mi.mesh) == 0:
		return 0.0
	var base := _verts(mi, -1)
	var mx := 0.0
	for bi in shape_count(mi.mesh):
		var v: float = mi.get_blend_shape_value(bi)
		if absf(v) < 1e-6:
			continue
		var bv := _verts(mi, bi)
		if bv.size() != base.size():
			continue
		var step: int = maxi(1, base.size() / 400)
		var j := 0
		while j < base.size():
			mx = maxf(mx, absf(v) * (bv[j] - base[j]).length())
			j += step
	return mx

## 按当前 morph 解析式复算顶点的**世界 AABB**（`get_aabb()` 做不到这件事）。
static func world_aabb(a: Dictionary) -> AABB:
	var lo := Vector3(1e9, 1e9, 1e9)
	var hi := Vector3(-1e9, -1e9, -1e9)
	var any := false
	for mi in a["meshes"]:
		if not mi.visible or mi.mesh == null:
			continue
		var bb := local_aabb(mi)
		if bb.size.length() <= 0.0:
			continue
		var xf: Transform3D = mi.global_transform
		for i in 8:
			var p: Vector3 = xf * bb.get_endpoint(i)
			lo = lo.min(p)
			hi = hi.max(p)
		any = true
	if not any:
		return AABB()
	return AABB(lo, hi - lo)

static func local_aabb(mi: MeshInstance3D) -> AABB:
	var base := _verts(mi, -1)
	if base.is_empty():
		return AABB()
	var mode := blend_mode_of(mi)
	var lo := Vector3(1e9, 1e9, 1e9)
	var hi := Vector3(-1e9, -1e9, -1e9)
	var shapes: Array = []
	for bi in shape_count(mi.mesh):
		var bv := _verts(mi, bi)
		if bv.size() == base.size() and bv.size() > 0:
			shapes.append({"v": mi.get_blend_shape_value(bi), "bv": bv})
	for i in base.size():
		var p: Vector3 = base[i]
		for sh in shapes:
			var bv2: PackedVector3Array = sh["bv"]
			var v: float = sh["v"]
			var dv: Vector3 = ((bv2[i] - base[i]) * v) if mode == "absolute" else (bv2[i] * v)
			p += dv
		lo = lo.min(p)
		hi = hi.max(p)
	return AABB(lo, hi - lo)

## 逐件显隐（按 role 分组展示在右侧面板）。
static func set_part_visible(p: Dictionary, v: bool) -> void:
	for mi in p["meshes"]:
		mi.visible = v

static func apply_preset(a: Dictionary, preset: String) -> Array:
	var hidden: Array = []
	for p in a["parts"]:
		var role := String(p["role"])
		var vis := true
		if preset == "清凉":
			vis = role != "accessory"
		elif preset == "仅皮肤&头":
			vis = role == "skin" or role == "head"
		set_part_visible(p, vis)
		if not vis:
			hidden.append(String(p["name"]))
	return hidden

static func visible_count(a: Dictionary) -> int:
	var n := 0
	for p in a["parts"]:
		if not (p["meshes"] as Array).is_empty() and (p["meshes"][0] as MeshInstance3D).visible:
			n += 1
	return n

## 离线降级 fixture：纯内存自造角色（无 morph），只用来把界面/流程跑通。
static func _fixture_body() -> Node3D:
	var n := Node3D.new()
	var sk := Skeleton3D.new()
	sk.name = "RIG_TryOn_Fixture"
	sk.add_bone("root")
	sk.add_bone("pelvis")
	sk.add_bone("Head")
	n.add_child(sk)
	var specs := [["Fixture_Torso", Vector3(0, 1.05, 0), Vector3(0.34, 0.62, 0.22)],
		["Fixture_Head", Vector3(0, 1.62, 0), Vector3(0.22, 0.26, 0.24)],
		["Fixture_Acc_Belt", Vector3(0, 1.00, 0), Vector3(0.36, 0.05, 0.24)]]
	for s in specs:
		var mi := MeshInstance3D.new()
		mi.name = String(s[0])
		var bm := BoxMesh.new()
		bm.size = s[2]
		mi.mesh = bm
		mi.position = s[1]
		n.add_child(mi)
	return n
