extends SceneTree
## 第 2 步：把 Godot 从 .blend 导入出来的 PackedScene 真正实例化，并给出可核对的数字。
## 这一步不依赖编辑器（.scn 已在导入期生成），等价于游戏运行时 load() 一个 .blend 资源。
## 用法：
##   1) 先跑导入：_sc_harness/Godot.app/Contents/MacOS/Godot --headless --path . --import
##   2) 再跑本脚本：/Applications/Godot.app/Contents/MacOS/Godot --path . -s res://blend_check.gd

const LDR = preload("res://loader.gd")
const RES := "res://assets/BaseCharacter_Superhero_Male.blend"

func _initialize() -> void:
	print("GODOT_VERSION=", Engine.get_version_info().string)
	var ps: PackedScene = load(RES)
	if ps == null:
		print("BLEND_LOAD FAILED res=", RES)
		quit(1)
		return
	print("BLEND_LOAD ok res=", RES, " class=", ps.get_class(), " state=", ps.get_state().get_node_count(), " nodes")
	var inst: Node = ps.instantiate()
	if inst == null:
		print("BLEND_INSTANTIATE FAILED")
		quit(1)
		return
	print("BLEND_INSTANTIATE ok root=", inst.get_class(), " name=", inst.name)
	_trace(inst, 0)
	var tx := LDR.taxonomy(inst)
	print("BLEND_TAXONOMY skeletons=", tx["skeletons"], " meshes=", tx["meshes"], " surfaces=", tx["surfaces"],
		" tris=", tx["tris"], " untextured=", tx["untextured"], " mats=", tx["materials"])
	# 同一素材再走 glTF 运行时路线，做路线间对照
	var CFG = preload("res://cfg.gd")
	var g := LDR.load_scene(CFG.BODIES["Male_Superhero"])
	if g != null:
		var tg := LDR.taxonomy(g)
		print("GLTF_TAXONOMY  meshes=", tg["meshes"], " surfaces=", tg["surfaces"], " tris=", tg["tris"],
			" bones=", tg["skeletons"][0]["bones"], " head_idx=", tg["skeletons"][0]["head_idx"],
			" head_idx_blend=", tx["skeletons"][0]["head_idx"],
			" untextured=", tg["untextured"])
		var bn_blend := []
		for c in inst.find_children("*", "Skeleton3D", true, false):
			for b in (c as Skeleton3D).get_bone_count():
				bn_blend.append((c as Skeleton3D).get_bone_name(b))
		var bn_gltf := []
		for c in g.find_children("*", "Skeleton3D", true, false):
			for b in (c as Skeleton3D).get_bone_count():
				bn_gltf.append((c as Skeleton3D).get_bone_name(b))
		bn_blend.sort()
		bn_gltf.sort()
		print("BONE_NAME_SETS identical=", bn_blend == bn_gltf, " n_blend=", bn_blend.size(), " n_gltf=", bn_gltf.size())
		if bn_blend != bn_gltf:
			print("  only_in_blend=", bn_blend.filter(func(x): return not bn_gltf.has(x)))
			print("  only_in_gltf=", bn_gltf.filter(func(x): return not bn_blend.has(x)))
		g.free()
	var anims := []
	for c in inst.find_children("*", "AnimationPlayer", true, false):
		for a in (c as AnimationPlayer).get_animation_list():
			anims.append(String(a))
	print("BLEND_ANIMATIONS n=", anims.size(), " first=", anims.slice(0, 6))
	inst.free()
	quit()

func _trace(n: Node, d: int) -> void:
	var extra := ""
	if n is Skeleton3D:
		extra = " bones=%d Head=%d" % [(n as Skeleton3D).get_bone_count(), (n as Skeleton3D).find_bone("Head")]
	if n is MeshInstance3D:
		var mi := n as MeshInstance3D
		extra = " surf=%d skinned=%s aabb=%s" % [mi.mesh.get_surface_count() if mi.mesh else -1,
			str(mi.skin != null), str(mi.get_aabb().size.snapped(Vector3(0.01, 0.01, 0.01)))]
	print("  ".repeat(d), n.get_class(), " ", n.name, extra)
	for c in n.get_children():
		_trace(c, d + 1)