# T3 — Godot 4 交互预览页面（体形 morph / 身高 / 换装 / 换发型）

> 任务卡：`team_task_get task-3`（`task/007-morph-pipeline/TASK.md` 的 A7）
> 接口契约：`assets/3d/rig/SPEC.md`（§3.3 morph、§3.4 身高、§5 指标、§4.0 B2 路线）
> 上游 harness：`tools/3d/godot/`（本页复用了它的 `GLTFDocument` 运行时加载与 `SubViewport` 离屏渲染口径）

一句话：**一个 Godot 4.6 工程，用来肉眼 + 数字验收 v2 的体形 morph 体系** ——
拖一个连续滑块同时驱动身体与每一件服装的 `BS_Thin`/`BS_Heavy`，另一个滑块驱身高，
下拉换装/换发型，屏幕上实时列出**逐件**收到的 morph 值，并画出**穿模率随滑块变化的曲线**。

---

## 0. 一条命令

```bash
cd /Users/zhenkunzhu/Desktop/project/artstudio
tools/3d/godot/preview/run.sh                 # 离屏出图 + JSON（全部证据，无需点任何东西）
tools/3d/godot/preview/run.sh --interactive   # 开交互页面（拖滑块 / 换装 / 换发型）
```

等价的手写命令（`run.sh` 只是包了个看门狗）：

```bash
/Applications/Godot.app/Contents/MacOS/Godot \
  --path tools/3d/godot/preview -s res://shoot.gd --resolution 640x480
```

> `--resolution` 给个小窗口就行：成图分辨率由脚本里的常量决定（固定尺寸 `SubViewport` 离屏渲染）。

### 前置条件（重要）

Godot **没有**原生 `.blend` 解析器。走 Godot 自带的 `.blend` 导入管线有两条代价：
必须把 `.blend` 复制进工程（`res://`），而且 Godot 还会把贴图解包到 `res://assets/textures/` ——
那正是本任务禁止的"素材副本"（这套素材贴图合计 ~125 MB）。

所以本页的做法是：**Blender headless 预导出 `.glb`（贴图内嵌）到工程外的 `tmp/` 缓存**，
Godot 运行时用 `GLTFDocument.append_from_file(<磁盘绝对路径>)` 读它。

* 缓存目录：`tmp/godot_preview_cache/`（可用 `ARTSTUDIO_PREVIEW_CACHE` 覆盖）
  * `glb/` 预导出的 glb（贴图内嵌，整目录 ~170 MB）
  * `fixture/` 自造 fixture 服装（真实资产存在时不会用到）
  * `pen/` Blender 侧 BVH 参考曲线（见 §3，UI 不用它）
  * `logs/` 每次 Blender 调用的完整 stdout/stderr
* **缓存是可清的**：删掉 `tmp/godot_preview_cache/` 后下次运行会自动重烘
  （冷缓存实测 **约 51 秒**：2 具标准体 + 4 件服装 + 若干发型，逐个起 Blender headless）。
* 增量判断：目标 glb 比「源 `.blend` + `blender/*.py`」都新就跳过。
* 需要 Blender：`/Applications/Blender.app/Contents/MacOS/Blender`（用 `ARTSTUDIO_BLENDER` 覆盖）。
* 只想用已有缓存、绝不调 Blender：`ARTSTUDIO_PREVIEW_NO_BAKE=1 tools/3d/godot/preview/run.sh`。

**零拷贝**：工程目录 `tools/3d/godot/preview/` 里只有代码与 `project.godot`
（当前 **22 个文件 / 236 KB**，其中不含任何 `.png/.glb/.gltf/.blend/.pyc`），
`assets/` 下一个素材副本都没有（JSON 里 `zero_copy.assets_copied_into_project = 0`）。

> ⚠ **给改这个工程的人（也包括我自己）**：**所有探针/临时脚本存图一律用绝对路径**。
> 我踩过：探针里写了相对路径 `tmp/gp_exp/apose_probe.png`，Godot 的工作目录就是工程根，
> 于是**图被存进了工程内部**，还在工程里留下 `_probe.gd` 与 Blender 的 `__pycache__` ——
> 三处都会跟着代码一起被提交，也会让"零拷贝"这句话变成假的。
> 现已清理，并加 `blender/.gitignore`（`__pycache__/`）防复发。
> 自查一行：`find tools/3d/godot/preview -type f \( -name '*.png' -o -name '*.glb' -o -name '*.pyc' \)` → 必须为空。
>
> **方法学备忘（本轮与 `verifier` 共同确认，两边报告都记了）**
> 1. **探针/临时脚本存图一律绝对路径**；交付前跑一次上面的自查命令。
>    这条与三条骨架规则并列 —— 它的性质不是"数字算错"，而是**一句交付声明在无人察觉时变成假的**
>    （我这次是**自查**发现的：`tmp/gp_exp/apose_probe.png` 落进了工程内部，"零拷贝"差点变成假话）。
> 2. **对账不只对数，也包括对"谁说的"**：`verifier` 的坑清单里曾把一条（门禁 `--python-exit-code` 静默说谎）
>    记在我名下，我逐条核后否掉了 —— 首现位置在 `tools/3d/garment/`、由 Lead 转发，本目录一次都没出现过。
>    他已改正。**归属列与数字列同等重要**：归属错会把经验记在错的人身上，下次没人认领；
>    核法是 **grep 首现位置 + 看谁的原话**，不凭记忆。
> 3. **凡"两个独立实现给出不同答案"的地方，都是坑的所在**；逐位（digest 级）对账是最省事的探针。
>    本轮 A1 的"未 priming 缓存"就是靠这条暴露的：一个坑同时让双方各错一次，且**两次都不报错**。

---

## 1. 操作说明（交互模式）

`run.sh --interactive` 打开窗口：左边是 3D 舞台（角色 + 短地线 + 1 m 标尺），右边是控制面板。

| 控件 | 作用 | 口径 |
|---|---|---|
| **角色** 下拉 | Female / Male | 切标准体 |
| **服装** 下拉 | None / Ranger / Peasant | 切 `{Sex}_{Style}`；自动识别 B2 自包含角色 |
| **发型** 下拉 | None / 6 款 | `assets/3d/blend/base-characters/Hair_*__HeadBone.blend`（挂 `Head` 骨的 65 骨同名 rig） |
| **体形 k** 滑块 | `k ∈ [-1, 1]`，步长 0.01 | `BS_Thin = max(-k, 0)`、`BS_Heavy = max(k, 0)`（SPEC §3.3）—— **同时**驱动身体与**每一件**服装 |
| **身高 h** 滑块 | `h ∈ [0.92, 1.08]`，步长 0.002 | 缩放**角色根节点**的世界 `scale=(h,h,h)`；**不做 morph**，**不碰任何骨 pose**（SPEC §3.4） |
| **重置** | k=0 / h=1 | |
| **保存截图** | 把整页存到 `assets/3d/rig/previews/preview_ui_manual_*.png` | |

面板上还会实时显示：

* **逐件的 morph 值**（`BS_Thin`/`BS_Heavy` 的 index 与 read-back 值）+ 网格数 / 骨架数 / 带 morph 的网格数；
* 每副骨架 `find_bone("Head")` / `find_bone("root")` **按名字**取到的 index（跨路线索引会变，见 §4）；
* **穿模指示**：像素法实测的「穿模率 vs k」曲线 + 当前 k 标记 + "从哪个 k 开始超过 rest 基线 + 2%"。

> 拖完滑块（松手）会在当前 k 上再实测一次，读数里会出现 `实时实测 k=... → ...%`。

---

## 2. 出图证据（`run.sh` 默认动作）

全部落在 `assets/3d/rig/previews/`：

| PNG | 内容 |
|---|---|
| `preview_female_thin.png` | 女 Ranger，`BS_Thin=1`（k=-1） |
| `preview_female_standard.png` | 女 Ranger，`Basis`（k=0） |
| `preview_female_heavy.png` | 女 Ranger，`BS_Heavy=1`（k=+1） |
| `preview_bodyshape_female_3tiers.png` | 女 Ranger 三档并排（+ 子标题） |
| `preview_bodyshape_male_3tiers.png` | 男 Peasant 三档并排 |
| `preview_height_sweep.png` | 身高扫描 h = 0.92 / 1.00 / 1.08（**每人一条 1 m 标尺**） |
| `preview_outfits_4.png` | 4 套服装同框 |
| `preview_hair_4.png` | 4 款发型同框 |
| `preview_ui_page.png` | **交互页面整页**（3D + 实时读数 + 穿模曲线面板） |
| `preview_debug_p1_vs_p3.png` | **P1 vs P3 对照**：左 = 只装 B2 自包含角色，右 = 再叠一具标准体（调试开关强制） |

外加两份 JSON：

* `preview_report.json` —— 全部机器可读证据（**4 套服装全部**有穿模曲线 + 双向标定结果）：每个镜头的 k/h/`BS_Thin`/`BS_Heavy`、
  **逐件** morph 值、morph 契约自检、网格/骨架数、按名字取到的骨 index、图像留白统计、
  像素法穿模曲线、身高一致性测量、资产来源（真实资产 / fixture）、冷/热缓存与耗时。
* `preview_morph_receipt.json` —— 紧凑版"**每一件**服装收到的 morph 值"，直接给人看。

---

## 3. 验收口径：穿模用**像素法**，不用顶点级穿模率

SPEC §5 的"穿模率"在 Blender 侧可以由 T2 的工具算。**但本页不用那类方法**，理由是实测的：

* 标准体网格**不是闭合曲面**（26 个连通域 / 48 条边界环 / 面绕向不一致）。
  于是"最近点 + 最近面法线"的有符号距离**正负号会随机翻**。
  本仓库确实留了一版 `blender/penetration.py`（BVH 有符号距离），
  它算出的结果是**自相矛盾**的：一件**沿法线向外偏移 12 mm** 的布料壳，在 rest 档竟报 **2.73% 穿模**。
  → 该脚本与它的 JSON 只作为**方法对照/踩坑记录**保留，**UI 与验收都不用它**。

**本页的口径（`pen_pixel.gd`）完全不含拓扑假设，只看渲染结果**：

```
每个方位角（0°/90°/180°/270°）做 3 遍离屏渲染，材质换成纯色 unshaded，
且测量视口 transparent_bg = true → alpha 通道就是剪影（不用背景色阈值，不受 tonemap/光照影响）

P1  只显示「基准面」   （overlay 路线 = 身体；B2 自包含路线 = 皮肤件）
P2  只显示「覆盖层」   （服装 / 布料）
P3  两者都显示         （红=基准面，绿=覆盖层）

穿模率 = |{p ∈ P2 剪影 : P3 在 p 处是基准面在前}| / |P2 剪影| × 100%
```

含义：覆盖层本来挡在那儿的像素被基准面盖住了 → 布料沉到身体/皮肤里面去了。
`k ∈ {-1, -0.75, …, +1}` 共 9 档跑一条曲线，阈值线画在 **rest 基线 + 2%**（SPEC §5）。

**已知偏差（诚实声明）**：反面的布料（远侧手臂的袖子被躯干挡住）也会被计入，
所以看**相对变化**（各档 vs rest 基线）比看绝对值可靠；4 个方位角取均值可削弱它。

### ★ 双向标定（SPEC F21）——**强制前置断言，不过就不出数**

`pen_pixel.calibrate()` 在任何测量之前跑，两条都必须过（容差 0.01%）：

| 标定 | 做法 | 期望 |
|---|---|---|
| **C1** | 只渲染基准面，并把它自己的像素当作"覆盖层掩膜" | **100.00%** |
| **C2** | 只渲染覆盖层（基准面完全不在场） | **0.00%** |

**不过就把 `ready` 置 false 并写进 `error`，`measure_*()` 一律返回错误字典，面板直接显示"未通过测量前置，拒绝出数"**
—— **宁可报错，也不出一个看起来像样而错的数**（SPEC F21 的强制前置）
（verifier 的实测：不带标定的判据在"没有身体"的那张图上会**误报 37.3%**）。
实测 4 套全部 `C1 = 100.00 / C2 = 0.00`，结果在每个 `penetration_pixel_method_curves[gkey].calibration` 里。

### 逐 **mesh** 的 morph 读回（件级证据）

**口径（刻意如此，不是遗漏）**：**每次渲染一个"被 morph 驱动的角色"，就在该角色所在层级留一份逐 mesh 行**。
所以 `morph_per_mesh` 的**位置随镜头类型而变**，报告根的 `morph_per_mesh_coverage` 会把"哪个镜头、多少行、在哪一层"逐条列出来：

| 镜头类型 | 逐 mesh 行的位置 | 行数 |
|---|---|---|
| `solo`（3 个：thin/standard/heavy） | `shots[i].morph_per_mesh` | 各 12 行 |
| `montage`（5 个） | `shots[i].figures[j].morph_per_mesh` | 每图 8 或 12 行 |
| `page`（`ui_page`） | `shots[i].page.morph_per_mesh` | 8 行 |
| `p1_vs_p3` | `shots[i].routes[k].morph_per_mesh` | P1 12 行 / P3 15 行 |

⚠ **`shots[i].morph_per_mesh` 这个"镜头级"键只有 3 个 solo 镜头有** —— montage / page / p1_vs_p3 的数据
在各自的**嵌套层级**（`figures[j]` / `page` / `routes[k]`）。这是**刻意口径**：不为了"看起来整齐"把同一份
逐件数据在镜头级再复制一遍。机器可核查：`morph_per_mesh_coverage.every_shot_has_rows = true`。

每行字段：

```
{part, part_key, mesh, path, blend_shape_names,
 thin_index, heavy_index,
 thin_value_set, thin_value_read_back,
 heavy_value_set, heavy_value_read_back,
 contract_ok, read_back_ok}
```

`contract_ok` = 索引必须是 `BS_Thin=0 / BS_Heavy=1`；`read_back_ok` = `get_blend_shape_value()`
读回必须等于设定值（容差 1e-4）。**这一层是为了让"morph 确实到了每一件"有字段级证据，
而不只是"件数 = 12"这种计数证据。**

自检一行命令：
```bash
python3 -c "
import json;r=json.load(open('assets/3d/rig/previews/preview_report.json'))
c=r['morph_per_mesh_coverage']; print(c['every_shot_has_rows'], c['rows_total'], c['shots_with_shot_level_key'])
for s in c['per_shot']: print(s['shot'], s['kind'], s['rows'], [e['where'] for e in s['where']])
"
```

### ⚠ 归一化口径（**写死在这里，别猜**）

本页**唯一**的穿模口径（字段 `penetration_pixel_method_curves[gkey].curve_pixel_method`）：

```
每个 k 上，对 4 个方位角（azimuths_deg = [0, 90, 180, 270]）各算一次
    penetration_pct(方位角) = occluded_px / layer_px × 100
        occluded_px = 「覆盖层（服装/布料）像素中，P3 里被基准面（身体/皮肤）盖住」的数量
        layer_px    = 「P2 只渲覆盖层」时的剪影像素数
        → **归一化到"覆盖层像素"**（不是剪影！）

聚合：mean_pct[k] = 4 个方位角的**均值**；max_pct[k] = 4 个方位角里**最坏**的那个。
      面板画的曲线用 mean_pct，面板同时给出 marker 处的最坏方位角数值。
另给 penetration_pct_of_union(方位角) = occluded_px / union_px（归一化到剪影）
      —— **要跟 `garment` 的 `P_full` 对账就用这一个**。
```

`garment` 的 `P_full = 服装自带皮肤面中露在布料之外的像素占比 / 剪影`（女 Ranger ≈ 0.71–0.82%），
**定义不同**：他量的是"**皮肤**露出来"，本页量的是"**服装**被盖住"。两者都对，**不能混用**。

> **BVH 有符号距离法（`blender/penetration.py`）已从流程里摘除**，不再产出任何数字
> （它对非闭合/绕向不一致的网格正负号不可靠：一件向外偏移 12 mm 的布料壳在 rest 档被算出 2.73% 穿模）。
> 留下它当且仅当作为"负面结论"存档；脚本还在 `blender/`，但 `run.sh` 不会调它。
> 摘除的直接原因：同一件东西一度同时存在"像素法 6.15%"与"BVH 14.7%"两个数，口径对不上账。

### 纯色判据为什么不靠绝对阈值

用 `r > g`（谁在前）而不是 `r > 0.5` 这类绝对阈值 —— 对任何**单调**的色彩映射都成立，
不会被 tonemap（例如 AgX 把纯红压成鲑鱼粉、r/g≈1.5）搞废。测量视口里另外显式设了
`tonemap_mode = LINEAR`、`adjustment_enabled = false`、`MSAA/SSAA 全关`。

### 身高一致性（拉伸比离散度，SPEC §5 阈值 ≤0.01）

**主口径（无像素噪声，与 verifier 的 Blender 口径同一把尺子）**：
对每根"父骨→子骨"的骨段，量 h=1 与 h=h 的**世界空间段长比**
（`rig.bone_world_segments()` —— 用 `Skeleton3D.global_transform`，**把角色根节点的 scale 也算进去**，
否则 node 模式会恒等于 0、失去验证力）。
理想等比缩放下每个比都等于 h → `std(ratio)/mean(ratio)` ≈ 浮点噪声（1e-7 量级）。
报告字段：`modes[mode].bone_stretch.{n_segments, mean_ratio, height_gain_pct, dispersion}`。

**副口径（旁证）**：同一块测量视口 + 纯白剪影，在 h=1.00 与 h=1.08 各渲染一次，
按相对高度取 17 点**累积面积剖面**，比对两条归一化剖面。
⚠ 必须用**正交相机**：透视下"把角色整体放大 8%"并不是"图像等比放大 8%"
（近处放得多、远处放得少），实测会把纯投影误差算成 0.0098~0.0157 的"失真"。
即使正交，224×312 分辨率下的**行量化噪声底 ≈ 0.006**，所以副口径只当旁证。
（第一版用的是"逐带横向宽度"，量化噪声把离散度抬到 0.039 —— 已废弃。）

JSON 里**两种身高实现都测**（`node_scale` 与 `bone_root_scale`），用来当场对账：

* **本页实测发现**：在 **Godot 运行时**里两种写法**都**是等比缩放（段长比离散度都 ≈ 0，中位数比 = 1.08/1.0）。
  原因是 **Godot 的 `Skeleton3D` 没有 Blender 的 `inherit_scale` 标志**，骨缩放一律沿层级继承；
  Blender 侧那个"root 的缩放传不过 pelvis（子骨 NONE）→ 离散度 0.0841 / 身高只 +0.5%"的缺陷
  **在 glTF 运行时路线上不复现**。
* 尽管如此，**交付实现仍按 Lead 裁决走 `node_scale`（缩放角色根节点）** —— 它与路线无关、
  与 F6 天然正交，也是唯一在两条路线下都成立的写法。
* 顺带一个 **Godot 实测坑（已被我自己的逐帧探针撤回，见 §5 已知限制第 3 条 A1）**：
  我一度断定"`set_bone_pose_rotation()` 在骨架入树前不生效"，**那是错的** ——
  入树前/后都生效、当帧即可读回。当时看错是因为用 `Basis.get_euler()` 比较，
  而那根骨 rest 在 Z 轴是 -90°（**万向节锁**），差别很大的旋转会打印出几乎相同的欧拉三元组。

### 「四边留白 > 0」怎么量才有效

`image_stats()` 统计**非背景像素的包围盒**，留白 = 包围盒到画面四边的像素数。
两个假阳性陷阱（都实测踩过，已在代码里规避）：

1. **背景里不要放会铺满画面的地面** —— 那样"非背景"= 整张图，留白恒为 0。
   本页改用**短地线 + 1 m 标尺**（小几何，不会碰到画面边缘）。
2. 量留白时**先把地线/标尺藏掉**（`PAGE.set_helpers_visible(stage, false)`），
   只对**角色几何**算包围盒；出图时再把辅助几何显示回来。
   页面整页截图则只在**左侧 3D 视区**（`Rect2i(0,0,w-PANEL_W,h)`）里量，排除右侧 UI 面板。

---

## 4. 路线识别（A/B1 overlay 与 B2 自包含）

SPEC §4.0：**主路线是 B2** —— `assets/3d/rig/garments/*.blend` 每一份都是**一个自包含角色**
（布料若干件 + 服装自带皮肤 + 基础体捐的头/眼，共用服装自己的 rig，里面**根本没有 Superhero 身体**）。
这种文件必须**单独当角色用**；再叠基础体就会双重叠模。

`rig.gd` 自动识别（`_is_self_contained`）：加载后若出现 `Eyes`/`Eyebrows` 件，
或出现 `MI_Regular_*` / `MI_Superhero_*` / `MI_Eyes` / `MI_Hair_*` 这类材质，
就判为 B2 自包含 → `route = "B2_self_contained"`，骨架数 **1**；
否则按 `overlay(body+garment)` 组装（旧 A 路线 / fixture 走这条），骨架数 2~3。
JSON 里每个镜头都记了 `route`。**换资产不需要改路径**。

BVH 参考脚本还会输出 `blender/_morphfix.py` 的 `source`：
* `asset` = 标准体的 `BS_Thin`/`BS_Heavy` 已有真实数据（T1 已交付）；
* `bone_slider_fixture` = 还是全零占位通道时，按 SPEC §3.2 现场摆 14 根体形骨派生一份，
  让页面**不必空等上游**（只在内存里做，不写回 `bodies/`）。

---

## 4.5 一个实测结论：腿上"橙色斑块"是谁的锅

`preview_female_thin.png` 早期版本的小腿上有橙色斑块（皮肤从裤子里顶出来）。
用 `preview_debug_p1_vs_p3.png` 做了决定性对照（同一相机、同一 k，只差"有没有多叠一具标准体"）：

| 装配 | 内容 | 像素差（只在 P1 前景上统计） |
|---|---|---|
| **P1** | 只装 `garments/Female_Ranger.blend`（自包含角色，12 件 / 1 副骨架） | — |
| **P3** | P1 + 再叠一具 `bodies/Body_Female_Standard.blend` | **24.0%** |

→ **橙斑不是资产的问题，是"多叠了一具身体"**。B2 角色里的布料/皮肤/头共用同一组骨变换，
体形一变三者同构地一起变，**结构性地不存在"身体与服装不一致"**。
这也正是台账里那句"成品套装自带 body 部件，再叠基础体反而会穿模"的同一个坑。
本页因此把"叠加标准体"做成**默认关闭的调试开关**（`force_standard_body`）。

## 5. 已知限制

1. **`.blend` 不能直接读** —— 必须先用 Blender headless 预烘成 `.glb`到 `tmp/` 缓存；
   冷缓存约 51 s，清了缓存要重烘。工程里刻意不放素材副本（零拷贝）。
2. **中文字体依赖 macOS**：UI 用 `FontFile.load_dynamic_font()` 依次尝试
   `PingFang.ttc` → `Hiragino Sans GB.ttc` → `STHeiti Medium.ttc` → `Songti.ttc`。
   本机落到 `Hiragino Sans GB.ttc`。**都找不到时 UI 会自动回落成英文标签**（不会出现豆腐块）。
3. **A-pose 是预览用的姿态**：T-pose 的臂展 ~1.7 m，取景被迫拉远，几厘米的 morph 差异几乎看不出来。
   本页加载后把两条 `upperarm_*` 朝 `DOWN` 方向转 0.62（`RIG.pose_arms_down()`，
   按"骨→子骨方向"通用推算，不猜轴向、不硬编码 bone index）。这是**显示姿态**，不改任何资产文件。

   ⚠ 这里踩过的 Godot 坑 —— **证据等级不一样，别一律当已证结论**（与 SPEC F30 的等级声明一致）：

   | # | 结论 | 证据等级 |
   |---|---|---|
   | **A2** | **glTF 骨架的 pose 空间与"我以为的"不一致**：`pose_local = rest⁻¹·R·rest` 的共轭写法想在骨架空间里把手转向 DOWN，实际偏离很远；改 `Skeleton3D.set_bone_global_pose_override()` 精确命中 | **双实现实测**（我 60.1°；verifier 独立探针 165.9°，目标轴不同；override 后 0.0° / 1.4e-5°） |
   | **A3** | `MeshInstance3D.get_aabb()` 是**静止(rest)网格** AABB：转骨 90° 与设 `BS_Thin=1` 后都**逐位不变** → **取景/剔除/包围盒一律不能拿它当"形变+姿态之后"的结果** | **双实现实测**（我 + verifier 独立探针，三次读数逐位相同） |
   | **A4** | **不要凭"绕某轴转 N 度"的直觉写骨骼旋转**：这套 glTF 骨架的骨局部轴不与世界轴对齐（verifier 探针：绕骨轴 X 90° → global euler 偏 **60.76°**，与我 A2 的 60.1° 同族）。本页一律**从子骨位置反推方向**再下达 | 由 A2 直接推出（verifier 建议提升为头等警告） |
   | **A1** | **`set_bone_pose_rotation()` 只在骨架「已入树」之后设才有效**：入树前设的值**不会**在入树后生效；入树后设**当帧**即生效 | **双实现实测（逐位一致）**：verifier 独立工程 `verify/godot_probe/a1_v1v4.gd` 复算 V1–V4，四个数与我**逐位相同**（见下表） |

   #### A1 的完整过程（我断言 → 我误撤回 → 双实现确认），含机制

   > **这一小节刻意保留全过程，它比结论本身更有价值** —— 它记录的是
   > **两个不同的人被同一个"静默缓存"骗了各一次，而且两次都不报错、不崩溃**。
   > verifier 把它归档为测量坑 **M4**（与 M1 读数时机 / M2 判据退化 / M3 门禁不响同级），
   > 并评价它是"最难的一类"：**它只是安静地给你一个错的数**。

   我最初断言"入树前设不生效"；verifier 复算时只复现一半（他也是用 euler 比较，**同踩万向节锁**）；
   我做了探针后**误以为我错了并撤回**（踩了未 priming 缓存）；verifier 改用
   **不依赖 euler** 的比较（`basis` 矩阵逐元素最大差 + 探针方向夹角）后复现出**两半都成立**；
   我于是做了决定性实验 —— **verifier 是对的，我的撤回才是错的**。
   最后 verifier 在**自己的工程里独立复算 V1–V4，四个数与我逐位相同**，冲突正式收口
   （`verify-godot-claims.json` 的 `independent_conflicts` 已从"未裁定"改为 **RESOLVED**）。

   四个变体（同一份 glb、同一根 `upperarm_l`、同一个 `Quaternion(Z, 90°)`）：

   | 变体 | 步骤 | `basis` 最大差 | 方向夹角 | 结论 |
   |---|---|---|---|---|
   | **V3** | 不入树 → **先读一次 rest** → set → 立刻读 | 0.000000 | 0.0° | ❌ **入树前设，无效** |
   | （前探针） | 不入树 set → 入树 +1…+4 帧 | 0.000000 | 0.0° | ❌ 入树也不会**追溯**生效 |
   | **V4** | 入树 → 先读 rest → set → **同帧**读 | **1.488280** | **90.0114°** | ✅ 入树后设，**当帧生效** |
   | **V1** | 不入树 → **从不读 rest** → set → 立刻读 | *1.000373 vs 单位阵* | euler 显示 `(-89.95, 117.41, -88.17)`（**骗人的**） | ⚠ **假象**：读到的是**从未被 priming 的缓存** |
   | **V2** | 接 V1，把那颗骨入树 +3 帧再读 | **与 V1 逐位相同** | 同上 | ⚠ 缓存里那个"看起来像姿态"的值**一直没变** |

   **verifier 在独立工程里的复算（`verify/godot_probe/a1_v1v4.gd`，逐位相同）**：
   V1 `md(vs 单位阵)=1.000373` + 同一条 euler；V2 `md(V2,V1)=0.000000`；
   V3 `md(vs rest)=0.000000`、方向 0.0°（且入树 +4 帧仍逐位不变）；
   V4 `md(vs rest)=1.488280`、方向 **90.0114°**。`mechanism_verdict = true`。

   **我当初为什么会撤错**：我复刻 V1 的读法 —— **在入树前 `get_bone_global_pose()` 且此前从没读过 rest**。
   未 priming 的缓存会返回一个**看起来非常合理但并非生效姿态**的矩阵（V1），而且**入树后它也不会被刷新**（V2），
   于是看起来"入树前设也生效"。而 V3（先读一次 rest 再 set）暴露出真相：**差值恰好为 0**。

   **三条硬规则（本页代码就是这么写的）**：
   1. **pose 只能在骨架入树之后设**，设完再断言一次 → `RIG.on_attached()` 是**必需**的，不是防御性的；
   2. **比较骨骼姿态不要用 `Basis.get_euler()`** —— 该骨 rest 在 Z 轴 −90°，**万向节锁**下差别很大的旋转会打印出
      几乎相同的欧拉角（V1/V2 的 euler 显示得"像姿态"，实际生效值却是 rest —— **两个方向都会骗人**）；
   3. **不要在入树前读 `get_bone_global_pose()`** —— 未 priming 的缓存会给出貌似合理但错的矩阵，
      还会"粘住"（V1 == V2）。要比就比 `basis` 矩阵或方向向量。

   **A3 的实用含义**（verifier 指出我把这条说轻了）：任何取景/视锥剔除/包围盒逻辑都**不能**用
   `MeshInstance3D.get_aabb()` 当"形变与姿态之后"的结果；本页因此改用固定包络
   `page.worst_corners()`。

4. **像素法穿模是屏幕空间的代理**，不是几何真值（见 §3 的已知偏差）。
5. **SVG/曲线面板用 `_draw()` 手绘**，`draw_string` 依赖上面那个字体；字体缺失时标签回落英文。
6. **面板是代码构建的**（无 `.tscn` 布局），窗口尺寸变化时按 `Control` 锚点重排；
   3D 取景按"最坏包络"（高 2.02 m、半宽 0.62 m）一次算定，滑块拉到任何值都**不会裁切**。
7. **穿模指示是"屏幕空间代理"**：它归一化到服装像素，
   与 `garment` 的 `P_full`（归一化到剪影）**不是同一个数** —— 对账请用同一份 JSON 里的
   `penetration_pct_of_union`。四方位角取均值可削弱"远侧布料被躯干挡住"的偏差。
   另：**`Male_Peasant` 的 ~5-6% 是美术设计**（无袖装，前臂与手本来就裸露），不是缺陷。
8. **穿模数值随"姿态"变**：A-pose 下 `Male_Peasant` 的基准从 T-pose 的 1.84% 变为 5.94% ——
   无袖装的**前臂与手**在 A-pose 下更多地出现在画面前方，这就是 Lead 说的"~5.3% 是美术设计"。
   所以**同一套资产在不同姿态下的像素值不可直接比**，只有"同一姿态下各 k 之间"才可比。
9. **发型是外挂件**：`Hair_*__HeadBone.blend` 自带一副 65 骨 rig，作为角色的**同级节点**叠在同一位置
   （两副 rig 都按名字缩 `root`… 不，是按名字找 `Head` 做核对，身高统一缩**角色根节点**，
   所以发型与角色始终一起缩放）。

---

## 6. 文件清单

```
tools/3d/godot/preview/
├── README.md              本文件
├── project.godot          Godot 4.6 工程（零素材）
├── main.tscn / main.gd    交互模式入口（对着窗口视口搭舞台 + 面板）
├── shoot.gd               离屏批量出图 + JSON 证据（-s res://shoot.gd）
├── run.sh                 一条命令的包装（--shots / --interactive，带看门狗）
├── cfg.gd                 素材绝对路径清单 + 滑块口径常量 + 缓存目录
├── bake.gd                缓存管理：按需调 Blender headless 预导出 glb + 增量判断
├── loader.gd              运行时 GLTFDocument 加载（改写自 tools/3d/godot/loader.gd）
├── stage.gd               SubViewport 离屏渲染 / 自动取景 / 图像度量 / 地线标尺
├── page.gd                舞台与取景（A-pose 最坏包络、横向对位、Label3D 角点估算）
├── rig.gd                 角色组装（B2 自动识别）+ morph/身高驱动 + 身高实现诊断
├── pen_pixel.gd           ★ 像素法穿模指示 + 身高一致性测量
├── pen_gauge.gd           穿模曲线面板（Control._draw 手绘）
├── preview_panel.gd       交互面板（下拉 + 双滑块 + 实时读数 + 穿模曲线 + 存图）
├── uifont.gd              CJK/等宽字体加载（失败回落英文标签）
└── blender/               Blender headless 脚本（.gdignore，Godot 完全忽略）
    ├── export_glb.py         .blend → .glb（贴图内嵌、morph/skin 保留、导出前 shape key 归零）
    ├── _morphfix.py          体形 morph 的 fixture 兜底（T1 未落地时按 SPEC §3.2 现场派生）
    ├── make_fixture_garment.py  自造 fixture 服装（真实资产缺失时才用；见下）
    └── penetration.py        BVH 有符号距离法（**仅方法对照**，见 §3）
```

## 7. 自造 fixture 服装（`blender/make_fixture_garment.py`）

T2 的真实资产可能还没好，而页面必须**先能跑**。该脚本按 SPEC §3.3/§4.3 的契约造一件结构合规的临时服装：

* 从标准体派生一件布料壳（沿静止法线外扩 `--offset`），保留 `z <= --zmax`（把脸留出来）；
* 顶点顺序与标准体**逐点可映射**（子集、保序）→ morph 逐点复制（= 传递在"无误差"时的理想结果）；
* 共用标准体的骨架数据 + 复制顶点组权重；`Basis / BS_Thin(0) / BS_Heavy(1)` 同名同序；
* `--gain` 故意模拟"传递精度不足"（`<1` 布料浮起、`>1` 布料钻进身体），
  让穿模指示有东西可看。**真实资产到位后 fixture 自动退场**（`cfg.gd: garment_source()`），
  落盘只在 `tmp/godot_preview_cache/fixture/`，绝不写 `assets/3d/rig/garments/`（那是 T2 的写入范围）。

---

## 8. 复现命令（完整）

```bash
cd /Users/zhenkunzhu/Desktop/project/artstudio
G=/Applications/Godot.app/Contents/MacOS/Godot

# 0) 版本
"$G" --version                       # 4.6.2.stable.official.71f334935

# 1) 全部证据（一条命令；冷缓存会自动调 Blender headless 预烘 glb）
tools/3d/godot/preview/run.sh

# 2) 交互页面
tools/3d/godot/preview/run.sh --interactive

# 3) 只用已有缓存（CI 友好，缺缓存直接报错，不调 Blender）
ARTSTUDIO_PREVIEW_NO_BAKE=1 tools/3d/godot/preview/run.sh

# 4) 单独重烘某个资产（缓存目录里的日志可回溯每次 Blender 调用）
rm -f tmp/godot_preview_cache/glb/Female_Ranger.glb
tools/3d/godot/preview/run.sh

# 5) 换缓存目录（例如放到更快的盘）
ARTSTUDIO_PREVIEW_CACHE=/tmp/gpv tools/3d/godot/preview/run.sh
```