## verifier 独立探针 2：精确复算 T3 的断言 #1（入树前 set_bone_pose_rotation 无效）
## 与断言 #2（pose_local = rest⁻¹·R·rest 共轭写法推不出骨架空间旋转）
extends SceneTree
const GLB := "/Users/zhenkunzhu/Desktop/project/artstudio/tmp/godot_preview_cache/glb/Female_Ranger.glb"

func load_root() -> Node:
	var doc := GLTFDocument.new(); var st := GLTFState.new()
	doc.append_from_file(GLB, st)
	return doc.generate_scene(st)

func find_sk(n: Node) -> Skeleton3D:
	var stack: Array = [n]
	while stack.size() > 0:
		var x: Node = stack.pop_back()
		if x is Skeleton3D: return x
		for c in x.get_children(): stack.append(c)
	return null

func _initialize() -> void:
	print("=== 断言 #1：入树前 set_bone_pose_rotation 是否生效 ===")
	var r1 := load_root()
	var sk1 := find_sk(r1)
	var b := sk1.find_bone("upperarm_l")
	print("bone upperarm_l idx=", b)
	var rest_gp := sk1.get_bone_global_pose(b)
	print("  入树前 rest global basis euler = ", rest_gp.basis.get_euler() * 180.0/PI)
	sk1.set_bone_pose_rotation(b, Quaternion(Vector3(1,0,0), deg_to_rad(90.0)))
	var after_gp := sk1.get_bone_global_pose(b)
	print("  入树前 set 后 global basis euler = ", after_gp.basis.get_euler() * 180.0/PI)
	print("  → 入树前是否生效 = ", not after_gp.basis.is_equal_approx(rest_gp.basis))
	print("  pose_rotation 存下来了? = ", sk1.get_bone_pose_rotation(b))
	get_root().add_child(r1)
	await process_frame
	await process_frame
	var tree_gp := sk1.get_bone_global_pose(b)
	print("  入树后 global basis euler = ", tree_gp.basis.get_euler() * 180.0/PI)
	print("  → 入树后才生效 = ", not tree_gp.basis.is_equal_approx(rest_gp.basis))

	print("")
	print("=== 断言 #2：pose_local = rest⁻¹·R·rest 共轭写法 ===")
	var r2 := load_root()
	var sk2 := find_sk(r2)
	get_root().add_child(r2)
	await process_frame
	await process_frame
	var b2 := sk2.find_bone("upperarm_l")
	var r3 := sk2.get_bone_rest(b2)            # 骨在**骨架空间**的 rest 变换
	var rest_basis := r3.basis
	var target := Basis(Vector3(1,0,0), deg_to_rad(90.0))   # 想要：骨架空间绕 X 转 90°
	sk2.set_bone_pose_rotation(b2, Quaternion(rest_basis.inverse() * target * rest_basis))
	await process_frame
	var got := sk2.get_bone_global_pose(b2).basis
	# 与目标比：global_pose = rest * pose（Godot 约定），所以期望 rest_basis * target
	var want := rest_basis * target
	print("  目标(骨架空间绕X 90° basis) euler = ", target.get_euler() * 180.0/PI)
	print("  实测 global basis euler          = ", got.get_euler() * 180.0/PI)
	print("  期望(rest*target) euler          = ", want.get_euler() * 180.0/PI)
	var ang := rad_to_deg(got.get_rotation_quaternion().angle_to(want.get_rotation_quaternion()))
	print("  → 与期望的夹角偏差 = ", snappedf(ang, 0.001), " 度")
	# 对照：用 global_pose_override
	var r4 := load_root(); var sk4 := find_sk(r4); get_root().add_child(r4)
	await process_frame
	var b4 := sk4.find_bone("upperarm_l")
	var g4 := sk4.get_bone_rest(b4).basis * target
	sk4.set_bone_global_pose_override(b4, Transform3D(g4, sk4.get_bone_global_pose(b4).origin), 1.0, true)
	await process_frame
	var got4 := sk4.get_bone_global_pose(b4).basis
	var ang4 := rad_to_deg(got4.get_rotation_quaternion().angle_to(g4.get_rotation_quaternion()))
	print("  对照 set_bone_global_pose_override 偏差 = ", snappedf(ang4, 0.000001), " 度")
	quit()
