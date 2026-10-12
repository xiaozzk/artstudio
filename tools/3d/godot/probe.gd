extends SceneTree
## 第 1 步探针：运行时 GLTFDocument 能否直接读磁盘上的 .gltf（2 形体 / 8 发型 / 4 服装）。

const CFG = preload("res://cfg.gd")
const LDR = preload("res://loader.gd")

func _initialize() -> void:
	print("GODOT_VERSION=", Engine.get_version_info().string, " hash=", Engine.get_version_info().hash)
	_check("BODY", CFG.BODIES)
	_check("HAIR", CFG.HAIRS)
	_check("OUTFIT", CFG.OUTFITS)
	quit()

func _check(kind: String, table: Dictionary) -> void:
	for key in table:
		var path: String = table[key]
		var t0 := Time.get_ticks_msec()
		var scene := LDR.load_scene(path)
		var ms := Time.get_ticks_msec() - t0
		if scene == null:
			print("PROBE %s %s FAILED path=%s" % [kind, key, path])
			continue
		var tx := LDR.taxonomy(scene)
		var bones := []
		for s in tx["skeletons"]:
			bones.append(s["bones"])
		var mats := {}
		for m in tx["materials"]:
			mats[m] = tx["materials"][m]
		print("PROBE %s %s ms=%d skeletons=%s bones=%s meshes=%d surfaces=%d untextured=%s mats=%s aabb_size=%s" % [
			kind, key, ms, str(tx["skeletons"].size()), str(bones), tx["meshes"], tx["surfaces"],
			str(tx["untextured"]), str(mats),
			str((tx["aabb_max"] - tx["aabb_min"]).snapped(Vector3(0.01, 0.01, 0.01)))])
		scene.free()