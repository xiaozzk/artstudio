extends RefCounted
## 素材路径清单 + 缓存目录（T3 交互预览页）。
##
## 零拷贝原则：**不往工程里复制任何素材**。做法是
##   ① Blender headless 把 `.blend` 预导出成 `.glb`（贴图内嵌）到 **`tmp/` 缓存**（工程外）；
##   ② Godot 运行时用 `GLTFDocument.append_from_file(<磁盘绝对路径>)` 读那份 `.glb`。
## 换机器 / 换目录：只改下面的 `ROOT`（或用环境变量覆盖）。

const ROOT := "/Users/zhenkunzhu/Desktop/project/artstudio"
const BLENDER_DEFAULT := "/Applications/Blender.app/Contents/MacOS/Blender"
const GODOT_DEFAULT := "/Applications/Godot.app/Contents/MacOS/Godot"

## ---- v2 资产（SPEC §2 / §6 约定的路径；T1/T2 的最终产物）----------------------
const RIG := ROOT + "/assets/3d/rig"
const BODIES := {
	"Female": RIG + "/bodies/Body_Female_Standard.blend",
	"Male": RIG + "/bodies/Body_Male_Standard.blend",
}
const GARMENTS := {
	"Female_Ranger": RIG + "/garments/Female_Ranger.blend",
	"Female_Peasant": RIG + "/garments/Female_Peasant.blend",
	"Male_Ranger": RIG + "/garments/Male_Ranger.blend",
	"Male_Peasant": RIG + "/garments/Male_Peasant.blend",
}
const BODYSHAPE_SPEC := RIG + "/bodyshape_spec.json"
const OUT_DIR := RIG + "/previews"          ## 截图/JSON 落这里（写入范围：preview_*）

## ---- 发型（SPEC/task-3 指定复用旧资产的 HeadBone 变体）-----------------------
const HAIRS := {
	"Hair_Buzzed": ROOT + "/assets/3d/blend/base-characters/Hair_Hair_Buzzed__HeadBone.blend",
	"Hair_BuzzedFemale": ROOT + "/assets/3d/blend/base-characters/Hair_Hair_BuzzedFemale__HeadBone.blend",
	"Hair_SimpleParted": ROOT + "/assets/3d/blend/base-characters/Hair_Hair_SimpleParted__HeadBone.blend",
	"Hair_Buns": ROOT + "/assets/3d/blend/base-characters/Hair_Hair_Buns__HeadBone.blend",
	"Hair_Long": ROOT + "/assets/3d/blend/base-characters/Hair_Hair_Long__HeadBone.blend",
	"Hair_Beard": ROOT + "/assets/3d/blend/base-characters/Hair_Hair_Beard__HeadBone.blend",
}

## ---- fixture 服装参数（T2 资产未就位时的兜底；见 blender/make_fixture_garment.py）
## gain<1 = 服装形变跟不上身体（浮起）；gain>1 = 形变超过身体（穿模）。
## 这两个值不是"猜的美术参数"，而是**故意**制造的"传递精度不足"场景，用来验证穿模指示真的会亮。
const FIXTURES := {
	"Female_Ranger": {"body": "Female", "offset": 0.012, "gain": 0.65, "zmax": 1.55, "color": "0.16,0.45,0.42"},
	"Female_Peasant": {"body": "Female", "offset": 0.028, "gain": 1.35, "zmax": 1.50, "color": "0.72,0.42,0.14"},
	"Male_Ranger": {"body": "Male", "offset": 0.012, "gain": 0.65, "zmax": 1.62, "color": "0.16,0.45,0.42"},
	"Male_Peasant": {"body": "Male", "offset": 0.028, "gain": 1.35, "zmax": 1.58, "color": "0.72,0.42,0.14"},
}

## ---- 体形/身高滑块口径（SPEC §3.3 / §3.4）-----------------------------------
const MORPH_THIN := "BS_Thin"          ## 索引 0（契约）
const MORPH_HEAVY := "BS_Heavy"        ## 索引 1（契约）
const K_MIN := -1.0
const K_MAX := 1.0
const H_MIN := 0.92
const H_MAX := 1.08
const PEN_THRESHOLD_PCT := 2.0         ## 穿模指示的"开始穿"阈值（%）

static func cache_dir() -> String:
	var e := OS.get_environment("ARTSTUDIO_PREVIEW_CACHE")
	if e != "":
		return e
	return ROOT + "/tmp/godot_preview_cache"

static func blender_bin() -> String:
	var e := OS.get_environment("ARTSTUDIO_BLENDER")
	if e != "":
		return e
	return BLENDER_DEFAULT

static func blender_dir() -> String:
	return ROOT + "/tools/3d/godot/preview/blender"

static func sex_of(garment_key: String) -> String:
	return "Female" if garment_key.begins_with("Female") else "Male"

## 服装最终用哪份源文件：T2 的真实资产优先，缺失才回落到 fixture。
static func garment_source(key: String) -> Dictionary:
	var real: String = GARMENTS.get(key, "")
	if real != "" and FileAccess.file_exists(real):
		return {"path": real, "fixture": false, "key": key}
	var f: Dictionary = FIXTURES.get(key, {})
	if f.is_empty():
		return {"path": "", "fixture": true, "key": key, "error": "既没有真实资产也没有 fixture 参数"}
	return {"path": cache_dir() + "/fixture/" + key + ".blend", "fixture": true, "key": key,
		"body": BODIES[f["body"]], "offset": f["offset"], "gain": f["gain"],
		"zmax": f["zmax"], "color": f["color"]}