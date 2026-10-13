# shape-lab —— 身形 & 服装快预览（Godot 4.6）

把「换个身形，看这套衣服跟不跟得上」压成**一条命令 + 拖一个滑块**：窗口里拖 `k`，身体与身上每一件
布料/皮肤/头同时形变；再拖 `h` 改身高、下拉换角色、逐件显隐（含「清凉」预设）、逐件看 morph 读数。

## 定位（别混用）

**这是日常快预览器，不是 task-007 的验收证据页** —— 后者在 `tools/3d/godot/preview/`，
承载穿模像素法与双向标定，是当时的验收证据链，**不要拿它当快预览器、也不要拿本工程当验收证据页**。
两者并存、各司其职：本工程 6 个 `.gd` = **1351 行 / 53.2 KB**（**含注释与空行**），
`preview/` 12 个 `.gd` = 2740 行 / 127 KB → 本工程**行数 49%、体积 42%**（口径可核对）。

## 一条命令

```bat
tools\3d\godot\shape-lab\run.cmd              :: 开窗：左舞台 + 右中文面板
tools\3d\godot\shape-lab\run.cmd --shots      :: 出图到 tmp\shape-lab\shots\（25 张）
tools\3d\godot\shape-lab\run.cmd --selftest   :: 交互链路自检（37 项，退出码 0 = 全绿）
tools\3d\godot\shape-lab\run.cmd --fixtures   :: 缓存缺失时的离线演示（无 morph）
```

`run.cmd` 是 Windows 主入口且**本机实测通过**；macOS / Linux 用 `./run.sh`，口径与 run.cmd 一致
（含同样的看门狗与按需烘焙），但 **⚠ `run.sh` 未在本机实测**（交付机是 Windows，无 macOS 环境）。
缓存缺失或 `assets/3d/rig/**/*.blend` 比 manifest 新时，`run.cmd` 会先调 `bake.py`（冷烘 16.1 s / 热烘 0.51 s）。

## 界面

| 区域 | 控件 | 说明 |
|---|---|---|
| 左 | 960×900 离屏舞台 | 方向光 + 环境光、**棋盘地线（每格 0.5 m）**、**1 m 标尺（x=+0.62 m）**；左键拖拽环绕、滚轮缩放 |
| 右 | 角色下拉（6 项） | 4 套自包含服装 + 2 具裸模标准体（label 前缀「裸模 · 身形基准」） |
| 右 | 体形 `k` 滑块 | `[-1,1]` 步长 0.01；旁显 `BS_Thin`/`BS_Heavy` 数值 |
| 右 | 身高 `h` 滑块 | `[0.92,1.08]` 步长 0.002 |
| 右 | 重置 / 全套 / **清凉** / **仅皮肤&头** | 见下「预设语义」 |
| 右 | 逐件显隐 | 每个 part 一个勾选框，按 `role` 分组 |
| 右 | 读数区 | `k`、`h`、网格/骨架/带 morph 网格数、**逐件 morph 名+索引+read-back**、位移、契约自检、几何留白 |
| 右 | 保存截图 | 截**当前整页**（左舞台 + 右面板）到 `tmp\shape-lab\shots\`，绝对路径 |

## 口径（冻结契约 v1，role 规则 v1.1）

- **体形**：`k ∈ [-1,1]` → `BS_Thin = max(-k,0)`、`BS_Heavy = max(k,0)`，**同时驱动场景里每一件**带该
  morph 的网格；索引 `0 = BS_Thin`、`1 = BS_Heavy` 是硬契约，**名字优先、名字对不上才回落索引**。
  实测：`find_blend_shape_by_name("BS_Thin")` 在 Godot 4.6 里**成立**（6 角色全部命中 100%）。
- **身高**：`h ∈ [0.92,1.08]` → 缩放**加载出来的角色根节点** `scale=(h,h,h)`，
  **绝不缩放 `root` 骨、绝不碰任何骨 pose**（Blender 侧 `inherit_scale='NONE'`，缩 `root` 骨身高只涨 0.5%）。
- **取骨按名字**：`find_bone("Head")` / `find_bone("root")`。**骨索引取决于「该文件里的骨层级 DFS 顺序」，跨文件不可复用** ——
  本工程这 6 个 glb 实测 `Head=54`、`root=0`（6/6 一致）。独立验收做过决定性实验：把真 glb 的 `skin.joints`
  **整段倒序**（nodes 与层级不动）→ Godot 的骨顺序**一位没变**（`Head` 仍 54）→ 它既不读 `skin.joints` 数组、
  也不读 `nodes` 数组顺序，只读骨层级。工作区既有那句「glTF 路线 `Head=6`」量的是**上游 Quaternius 原始 glTF**
  （另一份文件，现已不在盘上）——**不是矛盾，是两个不同文件**。证据：`task/008-godot-shape-lab/verify/app-verify.md`。
  > 本条由 Lead 按独立验收结论改写（原措辞是"本工程走 glTF 路线实测 Head=54"，容易被读成"路线决定索引"）。
- **零素材副本**：工程内**没有**任何 `.glb/.png/.blend`；资产由 `bake.py` 导出到 `tmp/shape-lab/`
  （6 个 glb 合计 ≈ 222 MB，单个服装 42–53 MB、裸模 13 MB，贴图全内嵌），Godot 运行时用
  `GLTFDocument.append_from_file(<绝对路径>)` 直接读。工程内 `.gitignore` 还额外挡了这些后缀。
- **`role` 规则 v1.1**（命中即止）：`head`（`Head_` / `Hair_` 前缀、`^(Eyebrows|Eyes)$`、`_Eyebrows`/`_Eyes` 结尾）
  → `skin`（材质含 `MI_Regular_`，或 `Body_` 前缀）→ `foot`（`_Feet` 结尾或含 `Boots`）
  → `accessory`（含 `Acc_`/`_Belt`/`_Bracer`/`_Hood`）→ `cloth`。
  manifest 未声明 `role_rules=v1.1` 时，app 侧会**丢掉**它的旧 role 并按上面规则重算。
- **预设语义**：
  - **全套** = 全可见；
  - **清凉** = 隐藏 `role=="accessory"`（护肩/腰带/护腕/兜帽），**不动** foot/cloth/skin/head。
    实测：女/男 Ranger 各隐藏 5 件；两套 Peasant 与两具裸模**没有 accessory 件**，所以隐藏 0 件；
  - **仅皮肤&头** = 只留 `role ∈ {skin, head}`。⚠ 在**服装角色**上会看到内腔（布料一藏，底下没有皮肤，
    B2 自包含角色不叠裸体），这**属预期不是 bug**；在**裸模**上它就是「完整体形」视图。
- **裸模自带内衣**：两具标准体不是全裸（`Body_Female/Male` 就是自带内衣的 `skin` 件），
  正好当「身形基准（清凉）」看体形变化而不被布料遮挡。

## 出图（`run.cmd --shots`）

`schema`：6 角色 × 3 档（thin `k=-1` / standard `k=0` / heavy `k=+1`）单图 + 每角色三档并排**联系表**
+ 1 张交互页整页图 = **25 张**，全部落在 `tmp/shape-lab/shots/`（绝对路径）。

- 每张单图后打 `STATS <id> <档> non_bg=..% colors=../..`；
- 整页图后打 `UI_LAYOUT {...}` 与 `UI_PAGE_STATS {...}`，并有**空白守卫**：
  面板区或整页的**非背景占比 < 3%** → 记失败、**退出码 3**（不允许「空白图 + 退出码 0」的静默说谎）。
- 实测（`tmp/shape-lab/shots/run_shots.log`）：`UI_LAYOUT` = 显示区 `960x900@(0,0)`、面板 `540x900@(960,0)`、
  勾选框 12 个；`UI_PAGE_STATS` = `non_bg 72%`、`left 58%`、`right 100%`、`colors 403 / colors_fine 1374`。
  单图 `non_bg` 54–66%。
- **为什么守卫用「非背景占比」而不是「颜色数」**：颜色数随内容多少浮动（裸模页 `colors_fine` 只有 385、
  fixture 页 169），拿它当门槛会误杀非空白页；占比才是「面板到底画没画」的直接判据。颜色数只作参考打印。
- 开窗模式（`run.cmd`）**不偷偷写文件**，但 2 秒后自动打一次 `UI_LAYOUT` / `UI_PAGE_STATS` 自证面板真在
  （实测开窗：`panel_rect 540x900`、`part_checkboxes 12`、`non_bg 72% / right 100%`）。
- `--fixtures` 离线降级也实测过：无缓存时 2 个内存自造角色 → 9 张图（6 单图 + 2 联系表 + 1 整页图），退出码 0。

## 环境变量

| 变量 | 默认 | 用途 |
|---|---|---|
| `ARTSTUDIO_GODOT` | `D:\godot\Godot_v4.6.2-stable_win64_console.exe` → PATH | Godot 4.6 可执行文件 |
| `ARTSTUDIO_BLENDER` | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` | 烘焙用 |
| `ARTSTUDIO_SHAPELAB_CACHE` | `<仓库根>/tmp/shape-lab` | 缓存根（manifest.json + glb/ + shots/） |
| `ARTSTUDIO_SHAPELAB_TIMEOUT` | 900 | `--shots` 看门狗秒数 |

## 实测坑（都在本机踩过，写下来省一轮返工）

1. **`--headless` 出不了图**：dummy 渲染器下 `ViewportTexture.get_image()` 返回 null
   （报 `Parameter "t" is null ... dummy/storage/texture_storage.h`）。所以**截图模式必须开真窗口**，
   成图分辨率由固定尺寸的离屏 SubViewport 决定，与窗口大小无关。
2. **看门狗是必需的**：GDScript 一旦**编译失败**，Godot 进程会永久空转、不退出（实测卡到超时）。
   `run.cmd --shots` 走 `System.Diagnostics.Process` + `WaitForExit(ms)`，超时 `Kill(true)` 并退出码 4。
3. **`Start-Process -PassThru` 的 `ExitCode` 在这里是空值**（长跑进程实测 `code=[]`，还配 rc=0）——
   必须用 `System.Diagnostics.Process` + `ProcessStartInfo` 才拿得到真退出码。
4. **UTF-8 的 `.cmd` 在中文（GBK）控制台会乱码甚至吞掉换行**，cmd 于是把正文当命令执行（实测：
   `rem` 行被拆开报 `'*…' is not recognized`）。所以 `run.cmd` **故意只写 ASCII**；中文提示由
   Godot 侧与 `bake.py` 给（它们按 UTF-8 处理，正常）。
5. **anchors 会算出 0 尺寸**：Control 的父节点是 `Node3D` 或离屏 `SubViewport` 时，
   `set_anchors_preset(PRESET_FULL_RECT)` 推出的 rect 可能是 0×0 → 整页图**全灰底**（曾实测 6 KB 空白图）。
   本工程改成**显式设 rect**（`_layout()` 用 `get_viewport_rect()` 算左显示区/右面板），并随
   `size_changed` 重算。
6. **`Mesh.surface_get_blend_shape_arrays(surf_idx)` 只吃一个参数**（返回该面上每个 blend shape 的
   arrays）；按老文档写两参数会 `Parse Error`。
7. **Godot 的 blend shape 数组是「绝对位置」**（不是 glTF 那种 delta）：本工程按
   `base + (bs-base)*w` 复算。判定=采样比 `|bs|` 与 `|bs-base|` 的量级（厘米级 vs 米级），
   6 角色实测均为 `absolute`（见读数区 `blend shape 存储语义实测判定`）。
8. **`MeshInstance3D.get_aabb()` 是静止 AABB**（不随 morph/pose 变）→ 取景与变形证据一律用
   `avatar.world_aabb()`（按当前 morph 解析式复算顶点，再乘 `global_transform`）。
9. `var d := max(...)` 因返回 Variant 会**编译失败** → 写显式类型 `var d: float = maxf(...)`；
   `var t := 某返回 Variant 的函数()` 同理（实测 `find_blend_shape_by_name` 要写 `var t: int = ...`）。
10. **截图/探针一律绝对路径**：相对路径会落进 `res://`，「零素材副本」这句话会静默变假。
    `stage.save_png_abs()` 对非绝对路径直接 `push_error` 并拒写。
11. **中文字形**：Godot 内置 fallback 字体没有中文（画成豆腐块）→ 用 `SystemFont` 按名字取系统字体
    （`Microsoft YaHei UI` …），并挂到 `ThemeDB.fallback_font`。这是读系统字体，不算素材副本。
12. **裸模的 `Eyebrows`/`Eyes` 源 .blend 里就没有 shape key**（不是导出丢的）：契约自检按
    `has_morph` 分档 —— 有 morph 的件必须 `["BS_Thin"(0),"BS_Heavy"(1)]`，没有的件**不算 FAIL**。
13. **`get_blend_shape_count()` / `get_blend_shape_name()` 只在 `ArrayMesh` 上**；`Mesh` 基类只有虚函数
    `_get_blend_shape_count()`。对 `BoxMesh` 之类直接调会报
    `Nonexistent function 'get_blend_shape_count' in base 'BoxMesh'`（函数出错返回空串 → 读数区那栏变空白）。
    GLTF 出来的都是 `ArrayMesh`，所以**真数据会掩盖这个坑**，是 `--fixtures` 的 BoxMesh 把它顶出来的。
    本工程统一走 `avatar.shape_count()/shape_name()`（只认 `ArrayMesh`，其余返回 0/""）。

## 扩展：加自己的角色

1. 准备 `.blend`：**65 骨 rig**（含按名字可取的 `Head`/`root`）+ 每个要形变的网格带
   `BS_Thin` / `BS_Heavy` 两个 shape key；放进 `assets/3d/rig/garments/`（服装）或 `assets/3d/rig/bodies/`（裸模）。
2. 在 `bake.py` 的 `CHARACTERS` 列表加一行（`id` / `label` / `kind` / `sex` / `style` / `src`）——
   注意它是**固定清单**，不是目录扫描。
3. 重跑 `python tools/3d/godot/shape-lab/bake.py`（只烘新增/变化的那份），重开 `run.cmd`，
   新角色就会出现在下拉里；`role` 由 manifest 按 v1.1 规则给出。

## 文件

| 文件 | 作用 |
|---|---|
| `main.gd` / `main.tscn` | 入口：参数解析、角色装载、读数生成、`--selftest`、整页截图 |
| `cache.gd` | 缓存根/仓库根解析、manifest 解析、`--fixtures` 离线降级 |
| `avatar.gd` | `GLTFDocument` 装载、role 分类、morph/身高驱动与逐件 read-back、解析式 AABB |
| `stage.gd` | 固定尺寸 SubViewport 舞台、灯光、棋盘地线、1 m 标尺、轨道相机、自动取景、`page_stats` |
| `ui.gd` | 右侧中文面板 + 左侧显示（窗口与离屏共用）、显式 rect 布局 |
| `shots.gd` | 出图流水线（3 档单图 + 联系表 + 整页图 + 空白守卫） |
| `run.cmd` / `run.sh` | 一条命令入口（找 Godot/Blender、按需烘焙、看门狗） |
| `bake.py` | **T1（baker）产物**：`.blend → .glb` + manifest |
