extends RefCounted
## 缓存管理（"一条命令"的关键）：把工程外的 `.blend` 预导出成 `.glb`，并预算穿模曲线。
##
## 为什么要有这一层：Godot 没有原生 `.blend` 解析器；走 Godot 的 `.blend` 导入管线
## 必须把 `.blend` 复制进工程、还会把贴图解包到 `res://` —— 那是 125 MB 的素材副本。
## 所以改为：**Blender headless 预导出到 `tmp/` 缓存（工程外）**，Godot 只读绝对路径。
##
## 幂等 + 增量：目标文件比所有输入（源 `.blend` + Blender 脚本）新就跳过。
## 环境变量：
##   ARTSTUDIO_PREVIEW_CACHE  缓存目录（默认 <ROOT>/tmp/godot_preview_cache）
##   ARTSTUDIO_BLENDER        Blender 可执行（默认 /Applications/Blender.app/...）
##   ARTSTUDIO_PREVIEW_NO_BAKE=1  禁止自动调用 Blender（缺缓存就报错退出，便于 CI 分离）

const CFG = preload("res://cfg.gd")

static var log_lines: Array = []

static func _log(s: String) -> void:
	log_lines.append(s)
	print("[bake] ", s)

static func cache() -> String:
	return CFG.cache_dir()

static func _mtime(p: String) -> int:
	if not FileAccess.file_exists(p):
		return -1
	return FileAccess.get_modified_time(p)

static func _ensure_dir(p: String) -> void:
	if not DirAccess.dir_exists_absolute(p):
		DirAccess.make_dir_recursive_absolute(p)

static func fresh(target: String, sources: Array) -> bool:
	var t := _mtime(target)
	if t < 0:
		return false
	for s in sources:
		if _mtime(String(s)) > t:
			return false
	return true

static func blender_scripts() -> Array:
	var d := CFG.blender_dir()
	return [d + "/export_glb.py", d + "/make_fixture_garment.py", d + "/penetration.py",
		d + "/_morphfix.py"]

## 调一次 Blender headless；日志落到缓存目录，方便回溯。
static func run_blender(tag: String, script_args: Array) -> Dictionary:
	var bin := CFG.blender_bin()
	if not FileAccess.file_exists(bin):
		return {"rc": -1, "error": "找不到 Blender：%s（用 ARTSTUDIO_BLENDER 覆盖）" % bin}
	var no_bake := OS.get_environment("ARTSTUDIO_PREVIEW_NO_BAKE") == "1"
	if no_bake:
		return {"rc": -2, "error": "ARTSTUDIO_PREVIEW_NO_BAKE=1 且缓存缺失（tag=%s）" % tag}
	var args := PackedStringArray(["--background", "--factory-startup", "--python"])
	args.append(CFG.blender_dir() + "/" + script_args[0])
	args.append("--")
	for i in range(1, script_args.size()):
		args.append(str(script_args[i]))
	var out: Array = []
	var t0 := Time.get_ticks_msec()
	var rc := OS.execute(bin, args, out, true)
	var ms := Time.get_ticks_msec() - t0
	_ensure_dir(cache() + "/logs")
	var f := FileAccess.open(cache() + "/logs/blender_" + tag + ".log", FileAccess.WRITE)
	if f:
		f.store_string("\n".join(out))
		f.close()
	var txt := "\n".join(out)
	_log("%s rc=%d %d ms" % [tag, rc, ms])
	if rc != 0:
		_log("  !! Blender 失败，尾部输出：\n" + txt.substr(maxi(0, txt.length() - 1200)))
	return {"rc": rc, "ms": ms, "out": txt, "log": cache() + "/logs/blender_" + tag + ".log"}

## 从 Blender stdout 里抠出 `KEY {json}` 那一行。
static func pick_json(txt: String, key: String) -> Dictionary:
	for line in txt.split("\n"):
		var i := line.find(key + " ")
		if i >= 0:
			var s := line.substr(i + key.length() + 1)
			var j: Variant = JSON.parse_string(s)
			if j is Dictionary:
				return j
	return {}

## ---- 标准体 ------------------------------------------------------------------
static func ensure_body(key: String) -> Dictionary:
	var src: String = CFG.BODIES[key]
	var dst := cache() + "/glb/Body_" + key + "_Standard.glb"
	if not FileAccess.file_exists(src):
		return {"ok": false, "error": "标准体不存在：%s" % src}
	var cached := fresh(dst, [src] + blender_scripts())
	var r := {"ok": true, "glb": dst, "source_blend": src, "from_cache": cached, "morph_fixture": {}}
	if cached:
		_log("body %s 命中缓存" % key)
		return r
	_ensure_dir(cache() + "/glb")
	var args: Array = [src, dst, "--body-morph"]
	if FileAccess.file_exists(CFG.BODYSHAPE_SPEC):
		args.append_array(["--spec", CFG.BODYSHAPE_SPEC])
	var br := run_blender("body_" + key, ["export_glb.py"] + args)
	r["blender"] = {"rc": br.get("rc", -1), "ms": br.get("ms", 0), "log": br.get("log", "")}
	r["morph_fixture"] = pick_json(String(br.get("out", "")), "MORPHFIX")
	r["export"] = pick_json(String(br.get("out", "")), "EXPORT_JSON")
	if not FileAccess.file_exists(dst):
		r["ok"] = false
		r["error"] = "导出失败，没有产物：%s" % dst
	return r

## ---- 发型 --------------------------------------------------------------------
static func ensure_hair(key: String) -> Dictionary:
	var src: String = CFG.HAIRS[key]
	var dst := cache() + "/glb/" + key + ".glb"
	if not FileAccess.file_exists(src):
		return {"ok": false, "error": "发型不存在：%s" % src}
	var cached := fresh(dst, [src] + blender_scripts())
	var r := {"ok": true, "glb": dst, "source_blend": src, "from_cache": cached}
	if cached:
		return r
	_ensure_dir(cache() + "/glb")
	var br := run_blender("hair_" + key, ["export_glb.py", src, dst])
	r["blender"] = {"rc": br.get("rc", -1), "ms": br.get("ms", 0), "log": br.get("log", "")}
	r["export"] = pick_json(String(br.get("out", "")), "EXPORT_JSON")
	if not FileAccess.file_exists(dst):
		r["ok"] = false
		r["error"] = "导出失败，没有产物：%s" % dst
	return r

## ---- 服装（真实资产优先，缺失则造 fixture）----------------------------------
static func ensure_garment(key: String) -> Dictionary:
	var spec := CFG.garment_source(key)
	var r := {"ok": true, "key": key, "fixture": spec.get("fixture", true),
		"source_blend": spec.get("path", ""), "real_asset": CFG.GARMENTS.get(key, "")}
	if spec.has("error"):
		return {"ok": false, "error": spec["error"], "key": key}
	var src: String = spec["path"]
	var scripts := blender_scripts()
	if spec.get("fixture", false):
		# 先造 fixture 的 .blend
		var body_src: String = spec["body"]
		var gen: Array = [body_src, src, "--offset", str(spec["offset"]), "--gain", str(spec["gain"]),
			"--zmax", str(spec["zmax"]), "--name", key, "--color", str(spec["color"])]
		if FileAccess.file_exists(CFG.BODYSHAPE_SPEC):
			gen.append_array(["--spec", CFG.BODYSHAPE_SPEC])
		if not fresh(src, [body_src] + scripts):
			_ensure_dir(cache() + "/fixture")
			var br := run_blender("fixture_" + key, ["make_fixture_garment.py"] + gen)
			r["fixture_blender"] = {"rc": br.get("rc", -1), "ms": br.get("ms", 0), "log": br.get("log", "")}
			r["fixture_report"] = pick_json(String(br.get("out", "")), "FIXTURE_JSON")
			r["fixture_morph"] = pick_json(String(br.get("out", "")), "MORPHFIX")
		else:
			_log("fixture %s 命中缓存" % key)
	var dst := cache() + "/glb/" + key + ".glb"
	if not fresh(dst, [src] + scripts):
		_ensure_dir(cache() + "/glb")
		var br2 := run_blender("garment_" + key, ["export_glb.py", src, dst])
		r["blender"] = {"rc": br2.get("rc", -1), "ms": br2.get("ms", 0), "log": br2.get("log", "")}
		r["export"] = pick_json(String(br2.get("out", "")), "EXPORT_JSON")
	else:
		_log("garment %s 命中缓存" % key)
	r["glb"] = dst
	if not FileAccess.file_exists(dst):
		r["ok"] = false
		r["error"] = "导出失败，没有产物：%s" % dst
	return r

## ---- 穿模曲线（离线预算）----------------------------------------------------
## 曲线必须与 Godot 看到的网格**同源**：所以 body 与所有 garment 都用同一套 fixture 逻辑。
static func ensure_penetration(body_key: String, garment_keys: Array) -> Dictionary:
	var dst := cache() + "/pen/pen_" + body_key + ".json"
	var sources: Array = [CFG.BODIES[body_key]]
	var gsources: Array = []
	for k in garment_keys:
		var s := ensure_garment(String(k))
		if s.get("ok", false):
			gsources.append(s["source_blend"])
		sources.append(s.get("source_blend", ""))
	var args: Array = [CFG.BODIES[body_key], dst]
	args.append_array(gsources)
	args.append("--body-morph")
	if FileAccess.file_exists(CFG.BODYSHAPE_SPEC):
		args.append_array(["--spec", CFG.BODYSHAPE_SPEC])
	var r := {"ok": true, "json": dst, "from_cache": fresh(dst, sources + blender_scripts()),
		"garment_sources": gsources}
	if r["from_cache"]:
		_log("穿模曲线 %s 命中缓存" % body_key)
	else:
		_ensure_dir(cache() + "/pen")
		var br := run_blender("pen_" + body_key, ["penetration.py"] + args)
		r["blender"] = {"rc": br.get("rc", -1), "ms": br.get("ms", 0), "log": br.get("log", "")}
		if not FileAccess.file_exists(dst):
			r["ok"] = false
			r["error"] = "穿模预算失败：%s" % dst
	r["data"] = read_json(dst)
	return r

## ---- 资产溯源（F/D-1 那类"验证的不是最终资产"的坑，用指纹堵住）--------------
static func file_sha256(path: String) -> String:
	if not FileAccess.file_exists(path):
		return ""
	return FileAccess.get_sha256(path)

static func _fp(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {"path": path, "exists": false}
	return {"path": path, "exists": true, "size": FileAccess.get_size(path),
		"mtime_unix": FileAccess.get_modified_time(path),
		"mtime_iso": Time.get_datetime_string_from_unix_time(
			FileAccess.get_modified_time(path), true),
		"sha256": file_sha256(path)}

## 深度遍历，找"value 里出现 hint"的那个字典，再在其中取第一个 *_sha256 字段。
static func _sha_near(o: Variant, hint: String, path := "") -> String:
	if o is Dictionary:
		var d := o as Dictionary
		var blob := JSON.stringify(d)
		if blob.findn(hint) >= 0 and d.has("file") and String(d["file"]).findn(hint) >= 0:
			for k in d.keys():
				if String(k).findn("sha256") >= 0:
					return String(d[k])
		for k in d.keys():
			var r := _sha_near(d[k], hint, path + "/" + String(k))
			if r != "":
				return r
	elif o is Array:
		for v in (o as Array):
			var r := _sha_near(v, hint, path)
			if r != "":
				return r
	return ""

## 汇总一份"我这次预览到底用的是哪份资产"的指纹证据。
static func provenance(body_keys: Array, garment_keys: Array) -> Dictionary:
	var bm := read_json(CFG.RIG + "/manifests/bodyshape_manifest.json")
	var gm := read_json(CFG.RIG + "/manifests/garment_manifest.json")
	var out := {"sources": {}, "checks": {}, "manifests": {}}
	for k in body_keys:
		var path: String = CFG.BODIES[k]
		var f := _fp(path)
		f["expect_sha256_from_bodyshape_manifest"] = _sha_near(bm, path.get_file())
		f["match_manifest"] = (String(f.get("sha256", "")) != ""
			and String(f.get("sha256", "")) == String(f.get("expect_sha256_from_bodyshape_manifest", "")))
		out["sources"]["body_" + String(k)] = f
	for k in garment_keys:
		var path: String = CFG.GARMENTS.get(String(k), "")
		var f := _fp(path)
		f["route_in_manifest"] = ""
		for o in (gm.get("outfits", []) as Array):
			if String((o as Dictionary).get("outfit", "")) == String(k):
				f["route_in_manifest"] = str((o as Dictionary).get("route", ""))
				# ⚠ verdict 是**字典**不是字符串：用 String() 会报
				#   "Invalid call 'String' constructor"（实测踩过）→ 一律用 str()
				f["verdict_in_manifest"] = str((o as Dictionary).get("verdict", ""))
				f["arms_in_manifest"] = int((o as Dictionary).get("armature_count", -1))
				f["parts_in_manifest"] = int((o as Dictionary).get("parts_count", -1))
		out["sources"]["garment_" + String(k)] = f
	out["manifests"]["bodyshape"] = {
		"path": CFG.RIG + "/manifests/bodyshape_manifest.json",
		"spec_version": bm.get("spec_version", ""),
		"coefficients": bm.get("coefficients", {}),
		"coefficients_fingerprint": bm.get("coefficients_fingerprint", ""),
		"spec_sha256": bm.get("spec_sha256", ""),
		"file_sha256": file_sha256(CFG.RIG + "/manifests/bodyshape_manifest.json"),
	}
	out["manifests"]["garment"] = {
		"path": CFG.RIG + "/manifests/garment_manifest.json",
		"version": gm.get("version", ""),
		"route_primary": (gm.get("route", {}) as Dictionary).get("primary", "") if gm.has("route") else "",
		"coefficients_fingerprint": ((gm.get("summary", {}) as Dictionary).get("coefficient_source", {}) as Dictionary).get("coefficients_fingerprint", "") if gm.has("summary") else "",
		"coefficients": ((gm.get("summary", {}) as Dictionary).get("coefficient_source", {}) as Dictionary).get("target_coefficients", {}) if gm.has("summary") else {},
		"file_sha256": file_sha256(CFG.RIG + "/manifests/garment_manifest.json"),
	}
	out["manifests"]["spec_md"] = _fp(CFG.RIG + "/SPEC.md")
	var a := String(out["manifests"]["bodyshape"]["coefficients_fingerprint"])
	var b := String(out["manifests"]["garment"]["coefficients_fingerprint"])
	out["checks"]["coefficients_fingerprint_bodyshape"] = a
	out["checks"]["coefficients_fingerprint_garment"] = b
	out["checks"]["coefficients_fingerprint_match"] = (a != "" and a == b)
	var all_b := true
	for k in out["sources"].keys():
		if String(k).begins_with("body_") and not bool(out["sources"][k].get("match_manifest", false)):
			all_b = false
	out["checks"]["all_bodies_match_bodyshape_manifest_sha256"] = all_b
	out["checks"]["all_ok"] = (out["checks"]["coefficients_fingerprint_match"]
		and out["checks"]["all_bodies_match_bodyshape_manifest_sha256"])
	out["note"] = ("指纹来自 assets/3d/rig/manifests/*.json；标准体按 bodyshape_manifest.bodies[].blend_sha256 "
		+ "逐份核对 sha256，服装用 garment_manifest.summary.coefficient_source.coefficients_fingerprint "
		+ "与 bodyshape_manifest.coefficients_fingerprint 对账 —— 用来堵住'验证的不是最终版资产'那类坑。")
	return out


static func read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {}
	var txt := f.get_as_text()
	f.close()
	var v: Variant = JSON.parse_string(txt)
	return v if v is Dictionary else {}

static func write_json(path: String, data: Dictionary) -> void:
	_ensure_dir(path.get_base_dir())
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		push_error("写不进去：%s" % path)
		return
	f.store_string(JSON.stringify(data, "  "))
	f.close()