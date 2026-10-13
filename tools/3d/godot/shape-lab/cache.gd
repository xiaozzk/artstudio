extends RefCounted
## 缓存目录 / manifest 解析 / 无缓存时的演示 fixture（契约 v1，见 task/008-godot-shape-lab/TASK.md）。
##
## 零素材副本：本工程只**读**缓存目录里的 .glb（绝对路径），从不把资产写进 res://。
## 缓存根：`ARTSTUDIO_SHAPELAB_CACHE` 优先，否则 <仓库根>/tmp/shape-lab（由 bake.py 产出）。

const CACHE_ENV := "ARTSTUDIO_SHAPELAB_CACHE"

## 契约 v1：这两个名字与索引 0/1 都是硬契约，不许改。
const MORPH_CONTRACT: Array = ["BS_Thin", "BS_Heavy"]
const K_MIN := -1.0
const K_MAX := 1.0
const H_MIN := 0.92
const H_MAX := 1.08

static func _clean(p: String) -> String:
	var s := p.strip_edges().replace("\\", "/")
	while s.ends_with("/"):
		s = s.substr(0, s.length() - 1)
	return s

## res:// = <仓库根>/tools/3d/godot/shape-lab/ → 上溯 4 级 = 仓库根。
static func repo_root() -> String:
	var d := _clean(ProjectSettings.globalize_path("res://"))
	for _i in 4:
		d = d.get_base_dir()
	return d

static func cache_root() -> String:
	var e := _clean(OS.get_environment(CACHE_ENV))
	return e if e != "" else repo_root() + "/tmp/shape-lab"

static func shots_dir() -> String:
	return cache_root() + "/shots"

## 读 manifest.json → {ok, root, chars, error, generated_at, blender_version}
static func load() -> Dictionary:
	var mp := cache_root() + "/manifest.json"
	if not FileAccess.file_exists(mp):
		return {"ok": false, "root": cache_root(),
			"error": "找不到缓存索引：%s\n  先跑 tools/3d/godot/shape-lab/run.cmd（需要时会自动调 bake.py 烘焙）。" % mp}
	var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(mp))
	if typeof(data) != TYPE_DICTIONARY:
		return {"ok": false, "root": cache_root(),
			"error": "manifest.json 不是合法 JSON 对象：%s" % mp}
	var d: Dictionary = data
	var raw: Array = d.get("characters", [])
	if raw.is_empty():
		return {"ok": false, "root": cache_root(), "error": "manifest.characters 为空：%s" % mp}
	var chars: Array = []
	var rules := String(d.get("role_rules", ""))
	for c in raw:
		chars.append(_normalize(c, rules))
	return {"ok": true, "root": cache_root(), "manifest": d, "chars": chars,
		"role_rules": rules,
		"generated_at": String(d.get("generated_at", "")),
		"blender_version": String(d.get("blender_version", ""))}

static func _part(p: Dictionary, role_rules: String) -> Dictionary:
	# role 口径 v1.1：manifest 还没升到 v1.1 时，**丢掉**它的旧 role，交给 avatar.gd 的
	# role_of() 按 v1.1 规则重算（否则「仅皮肤&头」在裸模上会一件不剩）。
	var role := String(p.get("role", ""))
	if role_rules != "v1.1":
		role = ""
	return {"name": String(p.get("name", "")), "role": role,
		"has_morph": bool(p.get("has_morph", false)), "morph_names": p.get("morph_names", []),
		"verts": int(p.get("verts", 0)), "faces": int(p.get("faces", 0)),
		"materials": p.get("materials", [])}

static func _normalize(c: Dictionary, role_rules := "") -> Dictionary:
	var id := String(c.get("id", "?"))
	var glb := ""
	var cand := cache_root() + "/glb/" + id + ".glb"
	if FileAccess.file_exists(cand):
		glb = cand
	else:
		glb = _clean(String(c.get("glb", "")))
		if glb != "" and not glb.is_absolute_path():
			glb = repo_root() + "/" + glb
	var parts: Array = []
	for p in c.get("parts", []):
		parts.append(_part(p, role_rules))
	var label := String(c.get("label", id))
	if String(c.get("kind", "")) == "body" and not label.contains("裸模"):
		label = "裸模 · 身形基准（%s）" % ("女" if String(c.get("sex", "")) == "Female" else "男")
	return {"id": id, "label": label, "kind": String(c.get("kind", "")),
		"sex": String(c.get("sex", "")), "style": String(c.get("style", "")),
		"armature": String(c.get("armature", "")), "bones": int(c.get("bones", 0)),
		"base_height_m": float(c.get("base_height_m", 0.0)), "glb": glb, "parts": parts,
		"fixture": false}

## 离线降级：没有缓存时用**纯内存**的自造角色把 UI/流程跑通（不写盘、不进 res://）。
## 注意：fixture 没有 morph 通道（GDScript 无法给 ArrayMesh 塞 blend shape），
## 所以它只验证「界面 / 换角色 / 显隐 / 预设 / 截图管线」，morph 真值必须用真缓存验。
static func fixture_cache() -> Dictionary:
	var mk := func(id: String, label: String, sex: String) -> Dictionary:
		return {"id": id, "label": label, "kind": "body", "sex": sex, "style": "",
			"armature": "RIG_TryOn_Fixture", "bones": 3, "base_height_m": 1.75, "glb": "",
			"fixture": true, "parts": [
				{"name": "Fixture_Torso", "role": "cloth", "has_morph": false, "morph_names": [],
					"verts": 8, "faces": 12, "materials": ["Fixture"]},
				{"name": "Fixture_Head", "role": "head", "has_morph": false, "morph_names": [],
					"verts": 8, "faces": 12, "materials": ["Fixture"]},
				{"name": "Fixture_Acc_Belt", "role": "accessory", "has_morph": false, "morph_names": [],
					"verts": 8, "faces": 12, "materials": ["Fixture"]}]}
	return {"ok": true, "root": cache_root(), "fixture": true, "generated_at": "(fixture)",
		"blender_version": "-", "chars": [mk.call("Fixture_Female", "演示 · 女（离线 fixture）", "Female"),
			mk.call("Fixture_Male", "演示 · 男（离线 fixture）", "Male")]}
