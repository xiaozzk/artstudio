# shape-lab 应用层独立验收（task-4）

- 生成时间：2026-10-14T02:53:43+08:00
- 生成器：`tmp/shape-lab-verify/verify_app.py` + 独立 Godot 探针工程 `tmp/shape-lab-verify/probe/`
- 结论：**PASS** —— 共 33 条，PASS 33 / FAIL 0 / 未能证实 0

> 独立性：**不读 T2 的读数面板**、不 import 它的脚本；数值来自我自己的探针（引擎 API 直取）
> 与我自己的像素取证（numpy/PIL）。凡是它给过的数字（如 `UI_PAGE_STATS`）我都重算并并列对照。

## 1. 总结论表

| 组 | PASS | FAIL | 未能证实 |
|---|---|---|---|
| analytic | 3 | 0 | 0 |
| api | 3 | 0 | 0 |
| app | 12 | 0 | 0 |
| bones | 5 | 0 | 0 |
| engine | 3 | 0 | 0 |
| preset | 4 | 0 | 0 |
| probe | 2 | 0 | 0 |
| render | 1 | 0 | 0 |

## 2. 逐条判据

### 组：probe

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `P-00` | probe-report.json | 探针跑完 6 个角色且每角色 ok | `chars=6 ok=6` | 6/6 | **PASS** |
| `P-00b` | probe-report.json | 逐角色关键字段齐全（防『GDScript 中途崩但退出码 0』的静默失败） | `缺字段 0 条` | 0 条 | **PASS** |
### 组：bones

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `P-01` | 6 角色 × Skeleton3D | 逐角色量 get_bone_count / find_bone('Head') / find_bone('root') | `骨数集合=[65]；Head 索引集合=[54]；root 索引集合=[0]` | 骨数=65；Head/root 索引逐角色报出 | **PASS** |
| `P-02` | Head 索引跨资产一致性 | Head 的骨索引是否 6/6 一致 | `Head ∈ [54]（6/6 相同）` | 记录（非判据，但决定『索引可否跨资产复用』这句话的强弱） | **PASS** |
| `P-03` | 6 个真 glb | Godot 骨顺序 == 层级 DFS 顺序？== skin.joints 顺序？== nodes 数组顺序？ | `6/6：godot==层级DFS=True；godot==skin.joints=True；godot==nodes数组=False；skin.joints==层级DFS=True` | godot == 层级 DFS（65/65 逐位） | **PASS** |
| `P-04` | 真 glb 副本（joints 数组倒序） | 决定性实验：把 skin.joints **倒序**（nodes 数组/层级完全不动），Godot 的骨顺序变不变？ | `asis: Head 在 joints 里 idx=54、Godot 里 idx=54；revjoints: Head 在 joints 里 idx=10、Godot 里 idx=54；原样与倒序后 Godot 骨序相同=True（⇒ Godot **不读** skin.joints 数组顺序）` | 倒序后 Godot 骨序**不变**（说明它按层级建骨，不按 joints 数组） | **PASS** |
| `P-04b` | 结论句 | 写清『这批 glb 上 Head 的索引是多少、与上游 glTF 口径的差异来源是什么』 | `6 角色 Head 索引=[54]；root 索引=[0]` | 一句可核对的话（见 evidence） | **PASS** |
### 组：api

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `P-05` | BoxMesh | 独立复核：get_blend_shape_count 只在 ArrayMesh 上是实体（BoxMesh 上会报错并中断调用函数） | `BoxMesh.has_method('get_blend_shape_count')=False；真调=调用被中断(aborted_at_call=True)；Mesh 方法表含 _get_blend_shape_count=True / 含 public get=False；ArrayMesh 方法表含 public get=True` | BoxMesh 无该方法；Mesh 基类只有虚函数 _get_blend_shape_count；ArrayMesh 才有 public get | **PASS** |
| `P-06` | 6 角色 × 全部件 | 三 API 一致：get_blend_shape_count()==2 ↔ name(0)==BS_Thin & name(1)==BS_Heavy ↔ find_blend_shape_by_name 命中 0/1 | `blend_shape_count 分布={2: 42, 0: 4}；不一致 0 条` | 不一致 0 条 | **PASS** |
| `P-07` | has_morph=false 的件 | 无 morph 的件在三 API 上的表现（不得被误当契约违规） | `4 件：blend_shape_count=0 且 find_by_name=-1 ↔ ['Body_Female_Standard/Eyebrows', 'Body_Female_Standard/Eyes', 'Body_Male_Standard/Eyebrows', 'Body_Male_Standard/Eyes']` | count=0 / find=-1，且不参与 targets==2 判据 | **PASS** |
### 组：engine

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `P-08` | 全部件×3 档 | morph read-back：设定值 vs get_blend_shape_value() 逐件一致（容差 1e-5） | `不符 0 条` | 0 条 | **PASS** |
| `P-09` | 全部 6 角色 × 3 档 | MeshInstance3D.get_aabb() **不随 k 变化**（静止 AABB）——给出 k=-1/0/+1 的原始读数 | `6 角色全部不变=True` | 全部不变（3 次读数逐位相同） | **PASS** |
| `P-10` | 全部 6 角色 | 身高走『场景根节点 world scale』时**骨 pose 一个都没碰**，且骨架世界缩放 == h | `违例 0 条` | 0 条 | **PASS** |
### 组：analytic

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `P-11` | 6 角色 | 解析式复算 v(k)=basis+max(-k,0)·d0+max(k,0)·d1：k=-1/0/+1 的围度代用指标与 X/Z span 严格单调递增 | `违例 0 条` | 0 条 | **PASS** |
| `P-12` | 6 角色 × 3 档 × 全部件 | 引擎自己烘的混合网格（bake_mesh_from_current_blend_shape_mix）== 我的解析式复算（逐顶点 ≤1e-5 m） | `最大 \|Δ\| = 0.000e+00 m（）` | ≤ 1e-5 m | **PASS** |
| `P-13` | 4 套服装全部件 | Godot 侧量的 BS_Thin max 位移 vs garment_manifest M4b 的 max_disp_cm（同量级） | `比对 40 件；最大 \|Δ\| = 0.0000 cm（4.958e-07 m）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
### 组：render

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `P-14` | 6 角色 × 3 档（我自己的探针渲图） | 像素级：剪影『中段最大宽度』随 k 严格单调递增（thin < standard < heavy） | `达标 6/6；违例 0 条` | 6/6 | **PASS** |
### 组：app

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-01` | run.cmd --shots | 退出码 0、SHOTS_TOTAL ≥ 19、failed_chars=0、无 ERROR 行 | `SHOTS_TOTAL=25 failed_chars=0 Godot exit=0 ERROR 行=0` | TOTAL≥19 / failed=0 / exit=0 / ERROR=0 | **PASS** |
| `A-02` | tmp/shape-lab/shots | PNG 落在 shots 目录（**不在** res:// 工程目录内） | `shots/*.png = 26 张；工程目录内 PNG = 0 张` | 工程内 0 张 | **PASS** |
| `A-03` | tools/3d/godot/shape-lab | 零素材副本审计：无 .png/.glb/.gltf/.blend/.pyc | `命中 0 个` | 0 个 | **PASS** |
| `A-04` | tools/3d/godot/shape-lab/*.gd | 取骨一律按名字：无硬编码骨索引（get_bone_pose* 传数字字面量 / bones[i] / joints[i]） | `硬编码 0 处；按名字取骨 1 处` | 硬编码 0 处 | **PASS** |
| `A-05` | 我自己的 18 张透明剪影（6 角色 × 3 档） | **不裁切**的硬证据：角色剪影（transparent_bg，只有角色、无地面/天空）四边留白全部 > 0 | `违例 0/18；留白范围 l=23–68 t=38–40 r=23–68 b=39–39` | 全部 > 0 | **PASS** |
| `A-05b` | app 的 shots（25 张） | 口径说明：为什么不能拿『非背景 bbox 四边留白 > 0』去判 app 的图 | `样例：shape_Body_Female_Standard_heavy.png: corner基线 non_bg=56.90% bbox={'x0': 0, 'y0': 48, 'x1': 959, 'y1': 899}；双基线(天空+地面) non_bg=31.33% bbox={'x0': 0, 'y0': 48, 'x1': 959, 'y1': 899} ｜ shape_Body_Female_Standard_sheet_3tiers.png: corner基线 non_bg=56.22% bbox={'x0': 0, 'y0': 0, 'x1': 1931, 'y1': 599}；双基线(天空+地面) non_bg=30.49% bbox={'x0': 0, 'y0': 0, 'x1': 1931, 'y1': 599}` | 记录（非判据） | **PASS** |
| `A-05c` | app 自报的 margin_px（18 条 SHOT 行） | app 自己算的『角色投影 bbox 到画幅四边的留白』全部 > 0（交叉核对，注明来源是 app） | `最小留白 = 34.3 px；样例 [{"b": 44.1, "l": 91.1, "r": 91.1, "t": 36.6}, {"b": 43.8, "l": 84.7, "r": 84.7, "t": 36.9}, {"b": 42.4, "l": 76.0, "r": 76.0, "t": 38.0}]` | 全部 > 0 | **PASS** |
| `A-06` | 25 张角色图（全部） | 不是全灰白：非背景像素平均饱和度 ≥ 0.02（纯灰白≈0） | `违例 0 张；饱和度范围 0.0858–0.1368` | 全部 ≥ 0.02 | **PASS** |
### 组：preset

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-10` | 6 角色（真按 Button，读 MeshInstance3D.visible） | 「清凉」隐藏的 part 集合 == 按 v1.1 role 规则算出的 role==accessory 集合 | `不符 0 个角色` | 0 个 | **PASS** |
| `A-11` | 6 角色 | 「仅皮肤&头」可见集合 == role ∈ {skin, head} | `不符 0 个角色` | 0 个 | **PASS** |
| `A-12` | 6 角色 | 「全套」→ 全部件可见 | `不符 0 个角色` | 0 个 | **PASS** |
| `A-13` | appcopy 的 UI | 面板上确实有 3 个预设 Button（且按下去真的会改可见性） | `buttons=['女 · Ranger 游侠（全套）', '重置 (k=0, h=1)', '全套', '清凉', '仅皮肤&头', 'Head_Eyebrows', 'Head_Eyes', 'Head_Superhero_Female', 'Female_Ranger_Arms', 'Female_Ranger_Body', 'Female_Ranger_Legs', 'Female_Ranger_Acc_Pauldrons', 'Female_Ranger_Arms_Bracer', 'Female_Ranger_Body_Belt_1', 'Female_Ranger_Body_Belt_2', 'Female_Ranger_Head_Hood', 'Female_Ranger_Feet', '保存截图（PNG，绝对路径）']` | 含 '全套' / '清凉' / '仅皮肤&头' | **PASS** |
### 组：app

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-14` | 6 角色加载（我的探针） | 逐角色：网格数 == manifest.parts 数；骨架数 == 1；带 morph 的件数 == manifest 里 has_morph 的件数 | `不符 0 个角色` | 0 个 | **PASS** |
| `A-07` | shape_lab_ui_page.png + 空白对照 | 空白守卫：真图必须绿、真空白必须红（用我自己造的空白对照证明判据非空洞） | `真图被判红 0 个：[]；空白对照被判红 4 个：['ui_page(0.0001%)', 'fixture_page(0.0001%)', 'fixture_tier(0.0001%)', 'body_standard(0.0001%)']` | 真图 0 个红；空白对照全部红 | **PASS** |
| `A-08` | 同上 | 若改用『颜色数 > 500』当门槛，会不会把非空白页误判为空白 | `真图 colors_fine = [1768, 362, 146, 874]（最小 146）` | 记录（评估 app 改用非背景占比的理由是否成立） | **PASS** |
| `A-09` | shape_lab_ui_page.png | app 自报的 UI_PAGE_STATS vs 我独立算的像素统计（口径对照） | `app: non_bg=72.00% right=100.00% colors_fine=1374；我: non_bg=66.38%（边框中位数基线）right=8.57% colors_fine=1768` | 两者应同量级（口径细节不同：app 用左上角像素当基线） | **PASS** |

## 3. 会变红的条件（逐条 fail_condition）

- **`P-00`** 有角色加载失败或探针中途崩 → 该角色结论不可得
- **`P-00b`** 任一角色的 parts/skeletons/per_k/geom_dump/camera/height_check 缺失 → 报告会以『通过』呈现实际未测的项（这是我自己的探针犯过的错，故设为硬门禁）
- **`P-01`** 骨数不是 65 或骨架数不是 6 → 65 骨契约被破
- **`P-02`** 本条不会红（记录用）。若索引互不相同 → 『索引不可跨资产复用』比既有口径更强；若全部相同 → 只能说『本批资产恰好相同』，仍不能硬编码
- **`P-03`** 若 Godot 骨顺序既不是层级 DFS 也不是 joints 顺序 → 机制解释错，必须重查。⚠ 真 glb 上 skin.joints 顺序与层级 DFS 顺序**恰好相同**，光看它们**分不出机制**，所以下面用『把 joints 数组倒序』的决定性实验
- **`P-04`** 若倒序后 Godot 骨序跟着变成 joints 数组的顺序 → 机制是『按 skin.joints 建骨』，我的解释要改；若连层级 DFS 都不符 → 三个假设全错，机制未明（不许含糊放过）
- **`P-04b`** 本条不会红（记录用）
- **`P-05`** 若 BoxMesh 上该方法可用 → app 那条注释是错的；若 Mesh 基类连虚函数都没有 → 说法要改。⚠ 另一个静默坑：`ClassDB.class_has_method('Mesh','_get_blend_shape_count')` 返回 **False**，而 `ClassDB.class_get_method_list('Mesh')` 里**有** `_get_blend_shape_count` —— has_method 看不见 GDVIRTUAL。所以我的判据改用方法表（更权威），并把 has_method 的这个结果一并记下来（别拿 has_method 当『方法不存在』的证据）
- **`P-06`** 任一件三 API 互相矛盾 → 面板按名字取、引擎按索引取，两边会读到不同的通道
- **`P-07`** 无 morph 件若被要求 2 个通道 → 假 FAIL（我 task-3 已按件分档处理）
- **`P-08`** 读回值与设定值不符 → 面板显示与引擎实际不符（最典型的静默错）
- **`P-09`** get_aabb 随 k 变了 → 说明引擎把 morph 烘进了 mesh AABB，那么 app 的注释（与 SPEC F30/A3）就错了
- **`P-10`** 骨 pose 随 h 变了 → 身高把骨头也缩了（= 破坏 rest pose，与 SPEC §3.4『绝不碰骨 pose』冲突）
- **`P-11`** 非严格单调 → 滑块方向错或 morph 通道错（例如名字/索引反了）；身高随体形变 → morph 里混进了沿轴缩放（SPEC F5 那类）
- **`P-12`** 两者不一致 → 要么我的公式错、要么引擎的 morph 应用不是『basis+Σw·delta』。这是**唯一**能证明『滑块真的驱动了顶点』的引擎侧证据（不经过任何 UI 读数）
- **`P-13`** Godot 读到的 morph 位移与 Blender 侧台账不符 → glTF 里的 morph 通道被改过
- **`P-14`** 剪影宽度非单调 → 渲染出来的形状与解析式不一致（视口/材质/相机或 morph 未生效）
- **`A-01`** 退出码非 0 / 出图少于 19 张 / 有角色失败 / 有 ERROR → 截图流水线不达标
- **`A-02`** 任何 PNG 落进工程目录 → 『零素材副本』变假，且会被 git 提交
- **`A-03`** 工程里出现素材副本 → 零拷贝这句话变假
- **`A-04`** 任何硬编码骨索引 → 跨路线（.blend/glTF/上游源）索引一变就静默取错骨
- **`A-05`** 任一角色的剪影贴到画幅边缘 → 内容被裁切（取景公式反了，本工作区历史上踩过）
- **`A-05b`** 本条不会红（记录用）。原因：舞台含**灰色棋盘地面**，它有意铺到画幅下/左/右边缘，且天空是**渐变**色 → 任何单一背景色基线都会把地面或天空之一判成『内容』，bbox 必然贴边（实测 25/25 张 l=r=b=0，与是否裁切无关）。所以『不裁切』只在**纯角色剪影**上可判（见 A-05a）
- **`A-05c`** app 自报留白 ≤ 0 → 与它自己的取景公式矛盾（注意：这是**它的**数字，我只用它交叉核对，不作为我的独立证据）
- **`A-06`** 饱和度≈0 → 贴图/材质全丢（图能出但没内容）
- **`A-10`** 集合不符 → 预设摘错件或漏摘（用户点『清凉』看到的不是清凉）。判据的判别力：见 evidence 里两个『看似合理但错』的规则对照
- **`A-11`** 可见集合不符 → 该预设的语义与命名不一致（裸模上尤其明显：v1.0 的 role 会把 Eyebrows/Eyes/Body_* 全判成 cloth，于是『仅皮肤&头』一件不剩）
- **`A-12`** 有件在『全套』下仍不可见 → 显隐状态没被正确重置（先点清凉再点全套会残留）
- **`A-13`** 按钮缺失 → 该功能不可达（哪怕 apply_preset 函数是对的）
- **`A-14`** 计数不符 → 加载漏件/多件，或 morph 通道没被识别（面板逐件读数会与实际不符）
- **`A-07`** 真图被误判为空白（假红，会把好页判成失败）或空白对照不被判红（判据空洞、静默放过）
- **`A-08`** 本条不会红（记录用）
- **`A-09`** 两边差 >15 个百分点 → 至少一方的背景基线选得不对（左上角像素当基线就是这个风险）。⚠ 口径差说明：整页图上 app 的 right_non_bg=100% 而我的『border_median』基线只有 8.57% —— 原因是**这两个数字的背景定义不同**：该图边缘同时含天空(暗)、棋盘地面(灰)、右侧面板(灰)，我的『边框中位数』落在灰上 → 面板被判成背景；app 用左上角天空当基线 → 面板算内容。在**这张图**上 app 的基线更合理（面板背景色与天空不同），我的 border_median 在这类『边缘多模态』图上不可靠 —— 这正是我另设 A-05b 说明『不能用单一背景色判这些图』的原因。本条只判整页 non_bg 是否同量级（差 5.62 pp），不做逐区域硬判。

## 4. 陷阱实测小节

### P-01（6 角色 × Skeleton3D）

- 判据：逐角色量 get_bone_count / find_bone('Head') / find_bone('root')
- 实测：`骨数集合=[65]；Head 索引集合=[54]；root 索引集合=[0]`
- 证据：Female_Ranger: bones=65 Head=54 root=0; Male_Ranger: bones=65 Head=54 root=0; Female_Peasant: bones=65 Head=54 root=0; Male_Peasant: bones=65 Head=54 root=0; Body_Female_Standard: bones=65 Head=54 root=0; Body_Male_Standard: bones=65 Head=54 root=0
- 会红的条件：骨数不是 65 或骨架数不是 6 → 65 骨契约被破

### P-02（Head 索引跨资产一致性）

- 判据：Head 的骨索引是否 6/6 一致
- 实测：`Head ∈ [54]（6/6 相同）`
- 证据：本工作区既有口径：取骨一律 find_bone(name)
- 会红的条件：本条不会红（记录用）。若索引互不相同 → 『索引不可跨资产复用』比既有口径更强；若全部相同 → 只能说『本批资产恰好相同』，仍不能硬编码

### P-03（6 个真 glb）

- 判据：Godot 骨顺序 == 层级 DFS 顺序？== skin.joints 顺序？== nodes 数组顺序？
- 实测：`6/6：godot==层级DFS=True；godot==skin.joints=True；godot==nodes数组=False；skin.joints==层级DFS=True`
- 证据：层级 DFS 的口径：从『在 skin.joints 里且其父节点不在 joints 里』的根开始，按 nodes[].children 顺序深度优先；见 check_boneorder_mechanism.py
- 会红的条件：若 Godot 骨顺序既不是层级 DFS 也不是 joints 顺序 → 机制解释错，必须重查。⚠ 真 glb 上 skin.joints 顺序与层级 DFS 顺序**恰好相同**，光看它们**分不出机制**，所以下面用『把 joints 数组倒序』的决定性实验

### P-04（真 glb 副本（joints 数组倒序））

- 判据：决定性实验：把 skin.joints **倒序**（nodes 数组/层级完全不动），Godot 的骨顺序变不变？
- 实测：`asis: Head 在 joints 里 idx=54、Godot 里 idx=54；revjoints: Head 在 joints 里 idx=10、Godot 里 idx=54；原样与倒序后 Godot 骨序相同=True（⇒ Godot **不读** skin.joints 数组顺序）`
- 证据：实验文件：D:\artstudio\tmp\shape-lab-verify\boneorder_real（asis.glb / revjoints.glb，均由真 glb 复制 + mutate_glb 改 JSON 写出）；Godot 实得 asis[0:6]=['root', 'pelvis', 'spine_01', 'spine_02', 'spine_03', 'clavicle_l'] rev[0:6]=['root', 'pelvis', 'spine_01', 'spine_02', 'spine_03', 'clavicle_l']
- 会红的条件：若倒序后 Godot 骨序跟着变成 joints 数组的顺序 → 机制是『按 skin.joints 建骨』，我的解释要改；若连层级 DFS 都不符 → 三个假设全错，机制未明（不许含糊放过）

### P-05（BoxMesh）

- 判据：独立复核：get_blend_shape_count 只在 ArrayMesh 上是实体（BoxMesh 上会报错并中断调用函数）
- 实测：`BoxMesh.has_method('get_blend_shape_count')=False；真调=调用被中断(aborted_at_call=True)；Mesh 方法表含 _get_blend_shape_count=True / 含 public get=False；ArrayMesh 方法表含 public get=True`
- 证据：实测注意：错误会**中断当前函数**（不是只打个 warning）—— 调用方继续执行，所以『崩了一半但退出码 0』是真实风险，我为此加了 P-00b 字段齐全门禁
- 会红的条件：若 BoxMesh 上该方法可用 → app 那条注释是错的；若 Mesh 基类连虚函数都没有 → 说法要改。⚠ 另一个静默坑：`ClassDB.class_has_method('Mesh','_get_blend_shape_count')` 返回 **False**，而 `ClassDB.class_get_method_list('Mesh')` 里**有** `_get_blend_shape_count` —— has_method 看不见 GDVIRTUAL。所以我的判据改用方法表（更权威），并把 has_method 的这个结果一并记下来（别拿 has_method 当『方法不存在』的证据）

### P-07（has_morph=false 的件）

- 判据：无 morph 的件在三 API 上的表现（不得被误当契约违规）
- 实测：`4 件：blend_shape_count=0 且 find_by_name=-1 ↔ ['Body_Female_Standard/Eyebrows', 'Body_Female_Standard/Eyes', 'Body_Male_Standard/Eyebrows', 'Body_Male_Standard/Eyes']`
- 证据：对应资产的源 .blend 里 Eyebrows/Eyes 确实没有 shape key（我的 blender 审计已确认）
- 会红的条件：无 morph 件若被要求 2 个通道 → 假 FAIL（我 task-3 已按件分档处理）

### P-09（全部 6 角色 × 3 档）

- 判据：MeshInstance3D.get_aabb() **不随 k 变化**（静止 AABB）——给出 k=-1/0/+1 的原始读数
- 实测：`6 角色全部不变=True`
- 证据：原始值样例（Female_Ranger 前 3 件）：k=-1 ['Female_Ranger_Acc_Pauldrons|0.101680,1.394538,-0.185693|0.243882,0.151122,0.231110', 'Female_Ranger_Arms|-0.850886,1.334193,-0.115464|1.701771,0.158042,0.140806', 'Female_Ranger_Arms_Bracer|-0.708149,1.341122,-0.123049|1.416299,0.143672,0.159970'] ｜ k=0 ['Female_Ranger_Acc_Pauldrons|0.101680,1.394538,-0.185693|0.243882,0.151122,0.231110', 'Female_Ranger_Arms|-0.850886,1.334193,-0.115464|1.701771,0.158042,0.140806', 'Female_Ranger_Arms_Bracer|-0.708149,1.341122,-0.123049|1.416299,0.143672,0.159970'] ｜ k=+1 ['Female_Ranger_Acc_Pauldrons|0.101680,1.394538,-0.185693|0.243882,0.151122,0.231110', 'Female_Ranger_Arms|-0.850886,1.334193,-0.115464|1.701771,0.158042,0.140806', 'Female_Ranger_Arms_Bracer|-0.708149,1.341122,-0.123049|1.416299,0.143672,0.159970']
- 会红的条件：get_aabb 随 k 变了 → 说明引擎把 morph 烘进了 mesh AABB，那么 app 的注释（与 SPEC F30/A3）就错了

### P-10（全部 6 角色）

- 判据：身高走『场景根节点 world scale』时**骨 pose 一个都没碰**，且骨架世界缩放 == h
- 实测：`违例 0 条`
- 证据：6/6 角色的 pose_position/rotation/scale 在 h=0.92/1.00/1.08 下逐值相同
- 会红的条件：骨 pose 随 h 变了 → 身高把骨头也缩了（= 破坏 rest pose，与 SPEC §3.4『绝不碰骨 pose』冲突）

### A-07（shape_lab_ui_page.png + 空白对照）

- 判据：空白守卫：真图必须绿、真空白必须红（用我自己造的空白对照证明判据非空洞）
- 实测：`真图被判红 0 个：[]；空白对照被判红 4 个：['ui_page(0.0001%)', 'fixture_page(0.0001%)', 'fixture_tier(0.0001%)', 'body_standard(0.0001%)']`
- 证据：ui_page: 真图 non_bg=66.38%（阈值 3.0%→绿），我的空白对照=0.0001%（→红）；colors_fine 真图=1768 / 对照=2；右上角口径 right_non_bg=95.25% ｜ fixture_page: 真图 non_bg=67.55%（阈值 3.0%→绿），我的空白对照=0.0001%（→红）；colors_fine 真图=362 / 对照=2；右上角口径 right_non_bg=94.79% ｜ fixture_tier: 真图 non_bg=50.63%（阈值 1.0%→绿），我的空白对照=0.0001%（→红）；colors_fine 真图=146 / 对照=2；右上角口径 right_non_bg=39.78% ｜ body_standard: 真图 non_bg=55.74%（阈值 1.0%→绿），我的空白对照=0.0001%（→红）；colors_fine 真图=874 / 对照=2；右上角口径 right_non_bg=50.44%
- 会红的条件：真图被误判为空白（假红，会把好页判成失败）或空白对照不被判红（判据空洞、静默放过）

### A-08（同上）

- 判据：若改用『颜色数 > 500』当门槛，会不会把非空白页误判为空白
- 实测：`真图 colors_fine = [1768, 362, 146, 874]（最小 146）`
- 证据：实测最小 146 < 500 → 说明 app 把颜色数门槛换掉是有事实依据的（不是随手改的）
- 会红的条件：本条不会红（记录用）

### A-09（shape_lab_ui_page.png）

- 判据：app 自报的 UI_PAGE_STATS vs 我独立算的像素统计（口径对照）
- 实测：`app: non_bg=72.00% right=100.00% colors_fine=1374；我: non_bg=66.38%（边框中位数基线）right=8.57% colors_fine=1768`
- 证据：app 的 bg_corner=[0.106, 0.11, 0.125]；我的三个基线：corner=[27, 28, 32] border_median=[45, 45, 45] mode=[45, 45, 45]
- 会红的条件：两边差 >15 个百分点 → 至少一方的背景基线选得不对（左上角像素当基线就是这个风险）。⚠ 口径差说明：整页图上 app 的 right_non_bg=100% 而我的『border_median』基线只有 8.57% —— 原因是**这两个数字的背景定义不同**：该图边缘同时含天空(暗)、棋盘地面(灰)、右侧面板(灰)，我的『边框中位数』落在灰上 → 面板被判成背景；app 用左上角天空当基线 → 面板算内容。在**这张图**上 app 的基线更合理（面板背景色与天空不同），我的 border_median 在这类『边缘多模态』图上不可靠 —— 这正是我另设 A-05b 说明『不能用单一背景色判这些图』的原因。本条只判整页 non_bg 是否同量级（差 5.62 pp），不做逐区域硬判。

### 剪影单调性明细（像素级）

- Female_Ranger: 中段宽 [114, 136, 164] px；整体宽 [584, 594, 608] px；剪影占比 13.21/15.14/17.70%
- Male_Ranger: 中段宽 [135, 244, 455] px；整体宽 [606, 618, 634] px；剪影占比 13.31/15.23/17.76%
- Female_Peasant: 中段宽 [110, 132, 158] px；整体宽 [588, 600, 612] px；剪影占比 12.00/13.71/15.98%
- Male_Peasant: 中段宽 [132, 216, 327] px；整体宽 [614, 626, 642] px；剪影占比 13.14/15.06/17.59%
- Body_Female_Standard: 中段宽 [124, 147, 178] px；整体宽 [594, 604, 618] px；剪影占比 11.42/13.16/15.43%
- Body_Male_Standard: 中段宽 [120, 142, 280] px；整体宽 [642, 656, 674] px；剪影占比 12.76/14.69/17.23%

## 4b. 破坏性复现（证明应用层判据真的会变红）

做法：在 app 的**副本**上改坏（`appcopy_mut/`），或把 task-3 造的 `mutants/swap_deltas.glb` 喂给我的探针；真工程与真缓存**未改**。

| mutant | 改坏了什么 | 期望红的判据 | 实际红的判据 | 命中 |
|---|---|---|---|---|
| `preset_rule_cloth` | 把「清凉」的规则从 role != "accessory" 改成 role != "cloth"（只改了 app 副本） | `A-10` | `A-10` | ✅ |
| `swap_deltas_glb` | 把 BS_Thin/BS_Heavy 的位移向量整段对调（task-3 的 swap_deltas.glb），名字/顺序/顶点数全对、只有数值反 | `P-13`, `P-14` | `P-00`, `P-13`, `P-14` | ✅ |

**2/2 命中**。其中 M2 的关键对照：`swap_deltas`（数值整段对调）让 **P-13（与台账比数值）与 P-14（剪影单调性）变红，而 P-12（引擎烘的网格 vs 我的解析式）仍然绿** —— 这精确刻画了分层：P-12 只验『引擎与公式一致』，P-13 才验『数值本身正确』。若只做 P-12，这个 mutant 会全绿通过。

## 5. 诚实声明与口径差异

- **陷阱 1（我自己踩的，代价是 analytic 全错）**：`Mesh.surface_get_blend_shape_arrays(s)` 返回的是**「该面上每个 blend shape 的 arrays」**，**Basis 不在里面** —— Basis 要从 `surface_get_arrays(s)` 取。而且 Godot 4.6 对 glTF 导入的 morph 用 **absolute 模式**：`shapes[i]` 里是**绝对坐标**，位移 = `shapes[i] − basis`。我第一版把 `shapes[0]` 当 Basis、把 `shapes[1]` 当 thin 位移 → 症状是『k=-1 的 bbox ≈ 2 倍、k=+1 完全不变』（thin 13.99 m / standard 6.86 m / heavy 6.86 m）——**不报错、不崩，只是数全错**。靠 P-12（引擎烘的网格 vs 我的复算）才暴露。app 的 `blend_mode_of()` 正是为这件事写的经验判据（它实测也报 absolute）。
- **陷阱 2**：`ClassDB.class_has_method('Mesh','_get_blend_shape_count')` 返回 **False**，而 `ClassDB.class_get_method_list('Mesh')` 里**确实有** `_get_blend_shape_count` —— has_method 看不见 GDVIRTUAL。所以『has_method 为假』**不能**作为『方法不存在』的证据；我的判据改用方法表（更权威）。实测方法表：Mesh = [_get_blend_shape_count, _get_blend_shape_name, _set_blend_shape_name, _surface_get_blend_shape_arrays, surface_get_blend_shape_arrays]；ArrayMesh 才有 public get/set_blend_shape_count/name/mode；MeshInstance3D = [bake_mesh_from_current_blend_shape_mix, find_blend_shape_by_name, get/set_blend_shape_value]。
- **陷阱 3（GDScript 的 invalid call 会中断函数但进程仍退 0）**：`BoxMesh.get_blend_shape_count()` 报 `Nonexistent function ... in base 'BoxMesh'`，**当前函数被中断**、调用方继续执行。我在自己的探针上真实踩了两次（一次 `Mesh` 是 Resource 没有 `.name`、一次写盘写在墓碑变量之前），两次都是『退出码 0 + 报告缺字段』。为此加了硬门禁 P-00b：逐角色断言 parts/skeletons/per_k/geom_dump/camera/height_check 齐全。
- **骨索引结论（领导点名要查的『两个实现互相矛盾』）**：这批 glb 上 `find_bone("Head")` = **54**（6/6 一致）、`find_bone("root")` = **0**。机制不是『glTF 路线按 skin.joints 数组』：我把真 glb 的 `skin.joints` **倒序**（nodes 数组与层级完全不动），Godot 的骨顺序**一位都没变**（Head 仍是 54，而 joints 数组里 Head 的索引变成 10）⇒ Godot **不读** `skin.joints` 数组顺序，**也不读** nodes 数组顺序（两例都不符）。真正相符的是**骨层级 DFS**（从 joints 里的根节点按 `children` 顺序深度优先）—— 65/65 逐位相同，原样与倒序两份文件都成立。所以工作区既有的『.blend 路线 54 / glTF 路线 6』**不是矛盾，而是两个不同的文件**：『6』量的是**上游 Quaternius 原始 glTF**（其骨层级顺序不同），本工程的 glb 由 Blender 5.2 re-export，骨层级 == .blend 骨序 → 落回 54。⚠ **我无法在本机复测那个 6**：全仓库搜 `*.gltf,*.glb` 只剩 `tools/3d/legacy/morph-demo/` 两个无骨架演示件，`download/` 里已无上游 glTF。建议把文档口径改成『索引取决于**文件里的骨层级顺序**，跨文件不可复用』——比『某路线 = 某索引』更强也更准。
- **硬编码骨索引：无**。grep 全部 *.gd（跳过注释行）：无 `get_bone_pose*(<数字>)`、无 `bones[i]`/`joints[i]`，取骨只有 `find_bone("Head")` / `find_bone("root")`（main.gd:253）与 `find_bone` 按名字的用法。口径合规。
- **空白守卫的独立判断（含真空白阴性对照）**：我自己造了 4 张『纯背景 + 1 个白像素』的空白图（分别模仿整页图/裸模图/fixture 图），用 app 的阈值（单图 1%、整页 3%）跑：真图 **0 个被判红**（non_bg 50.63%–67.55%），空白对照 **4/4 被判红**（non_bg 0.0001%）⇒ 判据**非空洞**、且阈值有 17–22 倍的余量，不会把非空白页误判成空白。另外实测 `colors_fine`：整页真图 1768、fixture 整页 **362**、fixture 单图 **146** —— 都 < 500，**证实 app 把『颜色数 > 500』换成非背景占比是有事实依据的**（旧门槛会把 fixture 页误杀）。
- **为什么不能用『非背景 bbox 四边留白 > 0』判 app 的图**：舞台含**灰色棋盘地面**（有意铺到画幅下/左/右边缘）且天空是**渐变**色 → 任何单一背景色基线都会把地面或天空之一算成『内容』，bbox 必然贴边（实测 25/25 张 l=r=b=0，与『是否裁切』无关）。所以『不裁切』这条我只在**纯角色透明剪影**上判（我自己的 18 张 sil_*.png，四边留白全部 > 0），并用 app 自报的 margin_px 做交叉核对（4 边最小 36.6 px）。我也因此在自写的 img_forensics 里修掉两个 bug：众数色的 key 有碰撞、bbox 的 y1 误用了 xs.max()。
- **fixture 的三档图逐位相同 —— 预期行为，不是缺陷**：`_fixture_cache/shots/` 里 thin/standard/heavy 三张 SHA256 完全相同（5502D996…），男女也相同。原因写在 app 源码里：fixture 是 3 个 `BoxMesh` 且 `has_morph: false`（GDScript 无法给 ArrayMesh 塞 blend shape）。所以它是**阴性对照**（无 morph → 无视觉变化），恰好用来验证空白守卫；它**不能**用来证明 morph 管线可用（那要靠 6 个真角色，实测三档 SHA256 各不相同）。
- **截图流水线可复现**：我独立跑 `run.cmd --shots` 一次（退出码 0、SHOTS_TOTAL=25、failed_chars=0、无 ERROR 行），产出的 26 张 PNG 与 app 之前那次的 **SHA256 逐位相同（26/26）**。⚠ 说明：这次运行会**重写** `tmp/shape-lab/shots/`（那是 app 自己的输出目录，我的卡要求我跑它）；内容逐位相同，故无实质改动。
- **未能证实（诚实声明）**：① 工作区文档里『glTF 路线 Head=6』**无法在本机复测**（上游 glTF 已不在盘上），我只能给机制与结论、不能给那 6 的实测。② 我自造的合成 glb（`glb_fixture.py`）能被**我的标准库解析器**读通，但 **Godot 拒绝解析**（`_parse_meshes: size == 0`），且其中手写 PNG 我『嗅 magic』通过、Godot 真解码报 `ERR_FILE_CORRUPT`（我后来修了 PNG 写入）。教训：**嗅 magic 比真解码弱得多**；因此骨顺序的决定性实验我改用了**真 glb 的副本**而不是自造 fixture。③ 我的探针渲染是**白色无光照 override** 的剪影，不用来评价观感（观感看 app 的 3 档图）。

## 6. 证据命令

```powershell
cd D:\artstudio
D:\godot\Godot_v4.6.2-stable_win64_console.exe --path tmp/shape-lab-verify/probe -- --cache D:\artstudio\tmp\shape-lab --out D:\artstudio\tmp\shape-lab-verify\renders
python tmp/shape-lab-verify/make_boneorder_fixture.py
python tmp/shape-lab-verify/render_boneorder_probe.py    # 骨顺序决定性实验
tools\3d\godot\shape-lab\run.cmd --shots
python tmp/shape-lab-verify/verify_app.py
```
