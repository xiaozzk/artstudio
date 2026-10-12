extends RefCounted
## 素材绝对路径清单。全部走运行时 GLTFDocument 加载，工程内不留素材副本。
## 换机器/换目录：只改这一行 ROOT（或把这三个 const 指到你自己的解压位置）。

const ROOT := "/Users/zhenkunzhu/Desktop/project/artstudio"
const MCO := ROOT + "/download/modular-outfits-fantasy/Modular Character Outfits - Fantasy[Standard]"
const MCO_GLTF := MCO + "/Exports/glTF (Godot-Unreal)"
const UBC := ROOT + "/download/ubc/Universal Base Characters[Standard]"
const UBC_BASE := UBC + "/Base Characters/Godot - UE"
const UBC_HAIR := UBC + "/Hairstyles/Rigged to Head Bone/glTF (Godot -Unreal)"

## 2 形体
const BODIES := {
	"Male_Superhero": UBC_BASE + "/Superhero_Male_FullBody.gltf",
	"Female_Superhero": UBC_BASE + "/Superhero_Female_FullBody.gltf",
}

## 8 发型（Rigged to Head Bone，65 骨同名 rig；不要用 Origin at 0 的静态件）
const HAIRS := {
	"Eyebrows_Regular": UBC_HAIR + "/Eyebrows_Regular.gltf",
	"Eyebrows_Female": UBC_HAIR + "/Eyebrows_Female.gltf",
	"Hair_Beard": UBC_HAIR + "/Hair_Beard.gltf",
	"Hair_Buzzed": UBC_HAIR + "/Hair_Buzzed.gltf",
	"Hair_BuzzedFemale": UBC_HAIR + "/Hair_BuzzedFemale.gltf",
	"Hair_SimpleParted": UBC_HAIR + "/Hair_SimpleParted.gltf",
	"Hair_Buns": UBC_HAIR + "/Hair_Buns.gltf",
	"Hair_Long": UBC_HAIR + "/Hair_Long.gltf",
}

## 4 套服装（成品套装，自带 body 部件，含 65 骨 rig）
const OUTFITS := {
	"Male_Peasant": MCO_GLTF + "/Outfits/Male_Peasant.gltf",
	"Female_Peasant": MCO_GLTF + "/Outfits/Female_Peasant.gltf",
	"Male_Ranger": MCO_GLTF + "/Outfits/Male_Ranger.gltf",
	"Female_Ranger": MCO_GLTF + "/Outfits/Female_Ranger.gltf",
}

## .blend 直读测试素材（拷进本工程 assets/ 才会走 Godot 的导入管线）
const BLEND_TEST_SRC := ROOT + "/assets/3d/blend/base-characters/BaseCharacter_Superhero_Male.blend"
const BLEND_TEST_RES := "res://assets/BaseCharacter_Superhero_Male.blend"