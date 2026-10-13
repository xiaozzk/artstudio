## verifier：复算 T3 的 V1–V4 四变体，验证「未 priming 的缓存」这个机制
## V1 不入树 + 从不读 rest  → set → 立刻读        （T3 称：假象）
## V2 接 V1，入树 +3 帧再读                        （T3 称：假象粘住）
## V3 不入树 + 先读 rest → set → 同帧读            （真相：不生效）
## V4 入树 + 先读 rest → set → 同帧读              （真相：当帧生效）
extends SceneTree
const GLB := "/Users/zhenkunzhu/Desktop/project/artstudio/tmp/godot_preview_cache/glb/Female_Ranger.glb"
const Q90 := Quaternion(Vector3(0,0,1), deg_to_rad(90.0))

func load_root() -> Node:
	var doc := GLTFDocument.new(); var st := GLTFState.new()
	doc.append_from_file(GLB, st); return doc.generate_scene(st)
func find_sk(n: Node) -> Skeleton3D:
	var st: Array = [n]
	while st.size() > 0:
		var x: Node = st.pop_back()
		if x is Skeleton3D: return x
		for c in x.get_children(): st.append(c)
	return null
func md(a: Basis, b: Basis) -> float:
	var m := 0.0
	for i in 3:
		m = maxf(m, maxf(maxf(absf(a[i].x-b[i].x), absf(a[i].y-b[i].y)), absf(a[i].z-b[i].z)))
	return m
func da(b: Basis, ref: Basis) -> float:
	return rad_to_deg((b * Vector3(0,0,1)).normalized().angle_to((ref * Vector3(0,0,1)).normalized()))

func _initialize() -> void:
	print("=== V1–V4 复算（verifier 独立工程）===")
	# ---- V1：不入树，从不读 rest ----
	var r1 := load_root(); var s1 := find_sk(r1); var b1 := s1.find_bone("upperarm_l")
	s1.set_bone_pose_rotation(b1, Q90)
	var v1 := s1.get_bone_global_pose(b1).basis
	print("[V1] 不入树/未读rest → basis vs 单位阵 md=%.6f  euler=%s" % [md(v1, Basis()), str(v1.get_euler()*180.0/PI).substr(0,40)])
	# ---- V2：接 V1，入树 +3 帧 ----
	get_root().add_child(r1)
	for i in 3: await process_frame
	var v2 := s1.get_bone_global_pose(b1).basis
	print("[V2] V1 后入树+3帧 → md(V2,V1)=%.6f  逐位相同=%s" % [md(v2, v1), v2 == v1])
	# ---- V3：不入树，先读 rest ----
	var r3 := load_root(); var s3 := find_sk(r3); var b3 := s3.find_bone("upperarm_l")
	var rest3 := s3.get_bone_global_pose(b3).basis        # ← priming
	s3.set_bone_pose_rotation(b3, Q90)
	var v3 := s3.get_bone_global_pose(b3).basis
	print("[V3] 不入树/先读rest → md(vs rest)=%.6f  方向夹角=%.4f°  → 生效? %s" % [md(v3, rest3), da(v3, rest3), md(v3, rest3) > 1e-5])
	get_root().add_child(r3)
	for i in 4: await process_frame
	var v3b := s3.get_bone_global_pose(b3).basis
	print("[V3] 再入树+4帧 → md(vs rest)=%.6f  逐位不变=%s" % [md(v3b, rest3), v3b == v3])
	# ---- V4：入树，先读 rest ----
	var r4 := load_root(); get_root().add_child(r4); await process_frame
	var s4 := find_sk(r4); var b4 := s4.find_bone("upperarm_l")
	var rest4 := s4.get_bone_global_pose(b4).basis
	s4.set_bone_pose_rotation(b4, Q90)
	var v4 := s4.get_bone_global_pose(b4).basis        # 同帧，不 await
	print("[V4] 入树/先读rest/同帧 → md(vs rest)=%.6f  方向夹角=%.4f°  → 生效? %s" % [md(v4, rest4), da(v4, rest4), md(v4, rest4) > 1e-5])
	print("")
	print("=== 判读 ===")
	print("V1/V2 是同一个矩阵且 ≠ 任何真实姿态? V1==V2 =", v2 == v1)
	print("V3 的'不生效'= md==0 =", md(v3, rest3) == 0.0, " 且入树后仍不变 =", v3b == v3)
	print("V4 的'生效'  = md≈1.488 =", snappedf(md(v4, rest4), 0.000001), " 方向", snappedf(da(v4, rest4), 0.0001), "°")
	print("→ T3 的机制解释（未 priming 的缓存给假象、且会粘住）成立 =", (v2 == v1) and md(v3, rest3) == 0.0 and md(v4, rest4) > 1.0)
	quit()
