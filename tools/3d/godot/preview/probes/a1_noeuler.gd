## verifier 修正版 A1 探针：**不用 euler 比较**，改用
##   ① basis 矩阵逐元素差  ② 一个探针方向向量被 basis 变换后的夹角
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

func basis_maxdiff(a: Basis, b: Basis) -> float:
	var m := 0.0
	for i in 3:
		m = maxf(m, maxf(maxf(absf(a[i].x-b[i].x), absf(a[i].y-b[i].y)), absf(a[i].z-b[i].z)))
	return m

func dir_after(b: Basis, d: Vector3) -> Vector3:
	return (b * d).normalized()

func report(tag: String, b: Basis, ref: Basis) -> void:
	var md := basis_maxdiff(b, ref)
	var probe := Vector3(0, 0, 1)
	var ang := rad_to_deg(dir_after(b, probe).angle_to(dir_after(ref, probe)))
	print("  %-28s basis_maxdiff=%.6f  probe_dir_angle=%.4f°  euler=%s" % [
		tag, md, ang, str(b.get_euler()*180.0/PI).substr(0,42)])

func _initialize() -> void:
	print("=== A1 修正探针（不比较 euler）===")
	var r := load_root()
	var sk := find_sk(r)
	var b := sk.find_bone("upperarm_l")
	print("bone=", b, " 父链存在=", sk.get_bone_parent(b))
	var rest := sk.get_bone_global_pose(b).basis
	report("rest（未入树）", rest, rest)

	# 入树**前** set
	sk.set_bone_pose_rotation(b, Quaternion(Vector3(0,0,1), deg_to_rad(90.0)))
	var before_tree := sk.get_bone_global_pose(b).basis
	report("入树前 set 后（同帧）", before_tree, rest)
	print("   → 入树前生效? basis_maxdiff>1e-5 =", basis_maxdiff(before_tree, rest) > 1e-5)

	# 入树
	get_root().add_child(r)
	for i in range(1, 5):
		await process_frame
		report("入树后 +%d 帧" % i, sk.get_bone_global_pose(b).basis, rest)

	# 入树后再 set 另一个值 → 再设回
	sk.set_bone_pose_rotation(b, Quaternion(Vector3(0,0,1), deg_to_rad(0.0)))
	report("入树后 set 0°（同帧）", sk.get_bone_global_pose(b).basis, rest)
	sk.set_bone_pose_rotation(b, Quaternion(Vector3(0,0,1), deg_to_rad(90.0)))
	report("入树后 set 90°（同帧）", sk.get_bone_global_pose(b).basis, rest)

	# 干净场景：入树后 set
	print("--- 干净场景（先入树再 set）---")
	var r2 := load_root(); var sk2 := find_sk(r2); get_root().add_child(r2)
	await process_frame
	var b2 := sk2.find_bone("upperarm_l")
	var rest2 := sk2.get_bone_global_pose(b2).basis
	report("rest（已入树）", rest2, rest2)
	sk2.set_bone_pose_rotation(b2, Quaternion(Vector3(0,0,1), deg_to_rad(90.0)))
	report("入树后 set 90°（同帧）", sk2.get_bone_global_pose(b2).basis, rest2)
	quit()
