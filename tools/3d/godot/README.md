# task-5 — Godot 4.6 落地验证（.blend 直读 + glTF 换装组装 + 渲染验收）

## 0. 结论速览

| 问题 | 结论 |
|---|---|
| **Godot 4.6 直读 .blend：支持/不支持？** | **支持（但要先在 Editor Settings 里配好 Blender 路径）** —— 实测导入并实例化成功，65 骨、3 个蒙皮网格、贴图齐全 |
| 配置方式 | `filesystem/import/blender/blender_path` 是 **Editor Setting，不是 Project Setting**；写进 `project.godot` 无效 |
| headless / CI | 未配置时 Godot **直接拒绝**（`Cannot configure blender path in headless mode`）；配好后 headless 可正常导入 |
| glTF 路线 | **支持，且无需导入管线/零素材副本** —— 运行时 `GLTFDocument.append_from_file(绝对路径)` 读 24/24 全部资产 |
| 换装组装 | 2 形体 × 8 发型 = **16/16 实例**，body 与 hair 各 65 骨、骨名一致、直接同级叠放即对齐 |
| 4 套服装 | 4/4 加载并渲染，骨架 65 骨、贴图齐全 |
| Godot ↔ Blender 数字 | **24/24 逐项一致**（mesh 数 + 三角面完全相同） |

* Godot 版本：**4.6.2.stable.official.71f334935**
  * 出处①：`/Applications/Godot.app/Contents/MacOS/Godot --version`
  * 出处②：脚本内 `Engine.get_version_info().string` → `4.6.2-stable (official) hash=71f334935c000924d403448e698df4441130df18`（见 `logs/probe.log` 首行）
  * 渲染后端：`Metal 3.2 - Forward+ - Apple M2`

---

## 1. 三条线的结论与证据

### ① `.blend` 直读 —— 支持 ✅

**机制（Godot 没有原生 .blend 解析器）**：`EditorSceneFormatImporterBlend` 先**调用 Blender 导出 glTF**
（`export_format=GLTF_SEPARATE`、`export_yup=true`、`export_skins=true`），再用 `GLTFDocument` 读回那份 glTF。

**证据链（全部原始日志在 `logs/`）**：

1. **未配置时直接失败**（`logs/blend_import_sc1.log:18`）：
   ```
   ERROR: Blender path is invalid or not set, check your Editor Settings. Cannot configure blender path in headless mode.
   ```
   → 且**没有任何产物**（`assets/` 下无 `.blend.import`，`.godot/imported/` 为空）。
   源码依据：`editor_scene_importer_blend.cpp` 的 `EditorFileSystemImportFormatSupportQueryBlend::query()`
   开头就是 `ERR_FAIL_COND_V_MSG(DisplayServer::get_singleton()->get_name() == "headless", true, ...)`。

2. **路径只能来自 Editor Settings**：`editor_settings.cpp:679` 用 `EDITOR_SETTING_USAGE(...)` 注册
   `filesystem/import/blender/blender_path`。我先按常规写进 `project.godot` 的 `[filesystem]` → **完全无效**（Godot 照样报上面那条错）。

3. **绕开全局配置的做法（本任务采用）**：本机 `~/Library/Application Support/Godot/editor_settings-4.6.tres` 里
   blender 路径为空，而该文件在写作用域之外。于是用 Godot 的 **self-contained 模式**：
   把 `Godot.app` 克隆到工程内、在 `Contents/MacOS/` 放一个 `_sc_`，editor 配置即落到
   `_sc_harness/editor_data/editor_settings-4.6.tres`（**在工程内**）。在那里写入 Blender 路径后：

4. **导入成功**（`logs/blend_import_sc2.log`）：
   ```
   reimport | BaseCharacter_Superhero_Male.blend
   ```
   产物：
   * `assets/BaseCharacter_Superhero_Male.blend.import`（`importer="scene"`, `type="PackedScene"`）
   * `.godot/imported/BaseCharacter_Superhero_Male.blend-0e08e27b….scn` —— **26,320,891 字节**
   * `assets/textures/` 下解包出 7 张贴图（`blender/materials/unpack_enabled=true` 默认开启）

5. **RPC 失败会自动回退**（不影响结论）：
   ```
   ERROR: Unexpected status during RPC connection: 4
   Failed to connect to Blender via RPC, switching to direct imports of .blend files.
   ```
   即 Godot 4.6 想常驻一个 Blender 进程走 RPC（快），连不上就退回"每个文件起一次 Blender"，**回退后照样成功**。

6. **实例化成功**（`logs/blend_check.log`）：
   ```
   BLEND_LOAD ok res=res://assets/BaseCharacter_Superhero_Male.blend class=PackedScene state=9 nodes
   BLEND_INSTANTIATE ok root=Node3D name=UBC Superhero_Male
     Node3D UBC Superhero_Male
       Camera3D Camera            <- .blend 里带着 task-1 生成的预览相机
       Node3D Fill / DirectionalLight3D Sun
       Node3D RIG_Superhero_Male_FullBody
         Skeleton3D Skeleton3D bones=65 Head=54
           MeshInstance3D Eyebrows  surf=1 skinned=true
           MeshInstance3D Eyes      surf=1 skinned=true
           MeshInstance3D SuperHero_Male surf=1 skinned=true
   BLEND_TAXONOMY meshes=3 surfaces=3 tris=14318 untextured=[]
   ```
   运行时的用法就是普通一行 `load("res://assets/xxx.blend")` —— **不需要 Blender 在运行时存在**。

**代价 / 限制**
* 每次 `.blend` 变更要重跑导入；单个文件 Blender 侧约 8 s。
* 导入产物不小（本例 `.scn` 26 MB，`.godot/` 共 26 MB）。
* `.blend` 里的预览相机会被一并导入；不要把 `.blend` 实例直接塞进视口而不清理相机（会顶掉你的取景相机）。
* headless/CI 必须先准备好可用的 `editor_settings`（见上面第 3 点），否则第一步就卡住。

**对照图**：`render_blend_vs_gltf.png` —— 同一素材两条路线并排，肉眼完全一致。

---

### ② glTF 路线组装 —— 支持 ✅（且零素材副本）

**做法**：运行时 `GLTFDocument.append_from_file(<磁盘绝对路径>)` + `generate_scene()`。
**因此工程里没有复制任何素材**（这套素材贴图合计 ~125 MB，全部留在原处）。

* **2 形体 × 8 发型 = 16 组合**，发型全部用 `Rigged to Head Bone` 变体
  （`Eyebrows_Regular / Eyebrows_Female / Hair_Beard / Hair_Buzzed / Hair_BuzzedFemale / Hair_SimpleParted / Hair_Buns / Hair_Long`），
  **未使用 `Origin at 0` 的静态件**。
* 组装方式：发型场景直接作为形体的**同级节点**叠在同一位置 —— 两者都是 65 骨同名 rig，rest pose 相同，无需任何重定向/绑定。
  实测 16/16 组合：`body_bones=65`、`hair_bones=65`、两边 `Head` 骨都在（`logs/render_hair.json`）。
* **4 套服装** `Outfits/{Male_Peasant, Female_Peasant, Male_Ranger, Female_Ranger}.gltf` 全部加载成功，
  各 65 骨；`untextured=[]`（见 `logs/render_outfits.json`）。
  成品套装自带 body 部件，所以**单独渲染就是完整角色**，再叠基础体反而会穿模。

*一处刻意的处理*：基础体自带的 `Eyebrows` 网格与 `Eyebrows_*` 发型件完全重合（同 rig 同位置），
同时显示会 **z-fighting**，所以换装总览里隐藏了基础体那一件（代码里有注释）。

---

### ③ 渲染验收 ✅

| 图 | 尺寸 | 内容 | 非背景像素包围盒留白 | 平均饱和度 |
|---|---|---|---|---|
| `render_hair_swap_2x8.png` | 3200×1250 | 2 形体 × 8 发型 = **16 个实例** | l65 t199 r111 b227 px | 0.381 |
| `render_hair_swap_2x8_tinted.png` | 3200×1250 | 同上 + 发型着色变体 | 同上 | 0.389 |
| `render_outfits_4.png` | 2400×820 | 4 套服装同框 | l120 t137 r119 b144 px | 0.348 |
| `render_blend_vs_gltf.png` | 1800×900 | .blend 路线 vs glTF 路线对照 | l126 t44 r125 b41 px | 0.286 |

* **不裁切**：4 张图的四边留白都 **> 0**（客观度量，非目视）。取景用迭代式自动构图：
  把所有网格 AABB 端点投影到屏幕、按需要比例反推相机距离（`stage.gd: auto_frame`）。
* **不灰白丢材质**：24/24 资产 `albedo_texture != null`（`untextured=[]`），
  四张图平均饱和度 0.29–0.39（纯灰白会接近 0）。
* **发型的"灰白"是设计如此**：`T_Hair_*_BaseColor` 是作者留的**中性命底色**（供运行时染发）；
  附带的 tinted 变体把 8 列染成棕/金/红/黑/银/蓝/粉/绿，证明贴图与材质都在。

---

## 2. 交叉核对：Godot ↔ Blender **24/24 逐项一致**

用 Godot 运行时读 glTF 量到的数字，与 task-2 在 Blender 里量到的 `.blend` 数字逐项对比：

* **mesh 数一致、三角面完全相等**（24/24，0 处不符），骨数皆 65，`untextured` 皆 0。
* 抽样：`Outfit_Male_Peasant` 4 meshes / 12894 tris；`Outfit_Male_Ranger` 9 / 26982；
  `Female_Ranger_Arms` 2 / 8508；`Male_Ranger_Feet_Boots` 1 / 9172 …… 全部与 task-2 报告相同。
* 三方闭合（同一素材）：Blender 侧 3 meshes/14318 tris ←→ Godot `.blend` 路线 3/14318 ←→ Godot glTF 路线 3/14318。

完整表格见 `report.json` 的 `crosscheck_godot_vs_blender.table`（24 行）。

**⚠ 取骨不要硬编码索引**：索引取决于**「该文件里的骨层级 DFS 顺序」**，**跨文件不可复用**。
008 的决定性实验：把真 glb 的 `skin.joints` **整段倒序**（nodes 与层级不动）→ Godot 骨顺序**一位没变**（`Head` 仍 54）⇒ **它既不读 `skin.joints` 数组、也不读 `nodes` 数组顺序，只读骨层级**。而 65 个**骨名集合完全一致**。
实测：**Blender 打开 `.blend` → `Head = 6`**；**本项目的 glb 在 Godot 里 → `Head = 54`**（6/6 一致）。

> ⚠ **本文件早期版本写的是"`.blend` 路线是 index 54、glTF 路线是 index 6"** —— 那句量的是**上游 Quaternius 原始 glTF**（另一份文件，现已不在盘上），**不是矛盾，是两个不同文件**；但旧措辞容易被读成"路线决定索引"，已订正。
> 一律用 `Skeleton3D.find_bone("Head")`。

---

## 3. 踩到的坑（都已在代码里规避并注释）

1. **`.blend` 路径写进 `project.godot` 无效** —— 它是 Editor Setting。headless 下还会直接报错，
   必须先有可用的 `editor_settings`。
2. **headless 下 `query()` 硬门**：`display server == headless` 就 `return true`（当作不支持该格式），
   连"自动探测 Blender 路径"都不会走。
3. **Godot 4.6 把 `inference_on_variant` 警告当错误**：`var d := max(...)` 直接编译失败
   （`max()` 返回 Variant）。要写成 `var d: float = maxf(...)`。
4. **`-s` 脚本编译失败时会永久空转**：脚本加载失败 → `_initialize()` 不执行 → `quit()` 不被调用 → 进程不退出。
   本任务加了 `run.sh` 看门狗（超时强杀）。
5. **`SceneTree._initialize()` 期间 `add_child` 的节点还没真正入树**：此时 `cam.get_viewport()` 返回 `null`，
   `unproject_position` 不可用。解法：先 `await process_frame` 再建场景，或显式传视口尺寸。
6. **相机取景**：用 `look_at_from_position()`；`look_at()` 在未入树时不可靠。取景边距公式要"缩"不能"放"
   （写反成 `ext/(size*margin)` 会让目标比视口大，内容直接顶到边缘 —— 实测第一版就被裁了）。
7. **窗口分辨率会被屏幕限制**：`--resolution 2560x1440` 渲染 root 视口时实际只得到 2446×1440。
   改用**固定尺寸 `SubViewport`** 离屏渲染后分辨率完全可控。
8. **源包贴图名不一致**（属素材问题，非 Godot）：UBC 基础体 glTF 的 `images[].uri` 写的是
   `T_Hair_1_Normal_png.png` / `T_Eye_Normal_png.png`，而磁盘上只有 `T_Hair_1_Normal.png` / `T_Eye_Normal.png`。
   影响 normal map（头发/眼睛），albedo 正常。
   *glTF 路线*会打 warning 并跳过该图；*.blend 路线不受影响*（Blender 导出时把图片按正确名字重新落盘）。
9. **RPC 模式连不上会自动回退**（见上），不是致命错误。

---

## 4. 复现命令

```bash
cd /Users/zhenkunzhu/Desktop/project/artstudio
G=/Applications/Godot.app/Contents/MacOS/Godot
SC=tools/3d/godot/_sc_harness/Godot.app/Contents/MacOS/Godot   # self-contained 克隆（内含 Blender 路径配置）

# 0) 版本
"$G" --version

# 1) 探针：24 份 glTF 运行时加载（骨数/网格/贴图检查）
./tools/3d/godot/run.sh "$G" 900 --path tools/3d/godot -s res://probe.gd           --resolution 640x480

# 2) .blend 直读：导入（用 self-contained 克隆，editor 配置在工程内）
./tools/3d/godot/run.sh "$SC" 900 --headless --path tools/3d/godot --import
./tools/3d/godot/run.sh "$G"  600 --path tools/3d/godot -s res://blend_check.gd    --resolution 640x480

# 3) 渲染三张（+发型着色变体）
./tools/3d/godot/run.sh "$G" 900 --path tools/3d/godot -s res://render_hair.gd     --resolution 640x480
./tools/3d/godot/run.sh "$G" 900 --path tools/3d/godot -s res://render_hair.gd     --resolution 640x480 -- tint
./tools/3d/godot/run.sh "$G" 900 --path tools/3d/godot -s res://render_outfits.gd  --resolution 640x480
./tools/3d/godot/run.sh "$G" 900 --path tools/3d/godot -s res://render_blend_vs_gltf.gd --resolution 640x480

# 4) 24 份全量交叉核对
./tools/3d/godot/run.sh "$G" 900 --path tools/3d/godot -s res://crosscheck.gd      --resolution 640x480
```

> 说明：渲染用 `SubViewport` 离屏出图，所以 `--resolution` 给个小窗口即可，成图尺寸由脚本里的常量决定。

---

## 5. 产物清单

```
tools/3d/godot/
├── project.godot                      Godot 4.6 工程
├── cfg.gd                             素材绝对路径清单（2 形体 / 8 发型 / 4 服装）
├── loader.gd                          运行时 GLTFDocument 加载 + 分类统计
├── stage.gd                           SubViewport 舞台 / 自动取景 / 图像度量
├── run.sh                             带看门狗的 Godot 运行器
├── probe.gd                           ① 24 份 glTF 探针
├── blend_check.gd                     ② .blend 导入 → 实例化 → 分类统计（含两路线对照）
├── render_hair.gd                     ③ 2×8 换装总览（-- tint 出着色变体）
├── render_outfits.gd                  ④ 4 套服装同框
├── render_blend_vs_gltf.gd            ⑤ 两条路线对照图
├── crosscheck.gd                      ⑥ 24 份全量交叉核对
├── render_hair_swap_2x8.png           ★ 换装总览（16 实例）
├── render_hair_swap_2x8_tinted.png    ★ 同上的着色变体（证明材质在）
├── render_outfits_4.png               ★ 4 套服装同框
├── render_blend_vs_gltf.png           ★ .blend vs glTF 对照
├── report.json                        机器可读结论
├── logs/                              全部原始 stdout/stderr 日志
└── _sc_harness/                       Godot.app 的 APFS 克隆 + _sc_ + editor_data/
                                       （仅为复现 .blend 导入，可随时整体删除）
```

**写作用域**：只在 `tools/3d/godot/` 内写入。`download/`（含 task-1/task-2 产物）与 `tmp/pack2blend/` 未改动；
本机全局 Godot editor settings（`~/Library/Application Support/Godot/`）**未被修改**（用 self-contained 克隆替代）。