# 008 — Godot 身形&服装预览工坊（shape-lab）

| 项 | 值 |
|----|-----|
| 编号 | 008 |
| 目录 | `task/008-godot-shape-lab/` |
| 状态 | 已完成 |
| 创建 | 2026-10-14 |
| 更新 | 2026-10-14 |

## 目标

把「**换个身形，看这套衣服跟不跟得上**」从「开 Blender、重烘一遍、再渲图」压缩成**一条命令 + 拖一个滑块**：
在 Godot 窗口里拖 `k`，**身体与身上每一件布料/皮肤/头同时形变**（同一副 65 骨 rig、同名 morph），
再拖 `h` 改身高、下拉换装、逐件显隐（含「清凉」预设）、逐件看 morph 读数。

## 需求拆解（用户原话）

> 「有办法直接在 tools 里面增加要给预览的小型 gd 项目吗？我素材里面有些 3d 资源，需要快速预览换装与身形的效果，
> 创建一个精简的 gd 身形&服装预览项目，要求足够精简和清凉级别，支持预览不同身形+滑块+服装变形的效果」

| 用户要求 | 本任务的处置 |
|---|---|
| 「在 tools 里增加一个**小型** gd 项目」 | 新建 `tools/3d/godot/shape-lab/`（**不改**现有重型 `tools/3d/godot/preview/`）；**实测** GDScript **1351 行 / 53 KB**、README **146 行**（软目标 ≤900 行未达成，理由见「决策」最后一条：不砍功能） |
| 「快速预览**换装**」 | 角色下拉 6 项 = 4 套 B2 自包含服装 + 2 具标准体 |
| 「预览**身形**」+「**滑块**」 | 体形 `k∈[-1,1]`（→ `BS_Thin/BS_Heavy`）+ 身高 `h∈[0.92,1.08]` 双滑块 |
| 「**服装变形**」 | 同名 morph **同时**驱动场景内每一件网格；面板逐件回读 + 独立验收解析式复算 |
| 「**清凉**级别」 | **两种读法都覆盖**：① 项目侧「精简/轻量」；② 着装侧「清凉」= 预设按钮一键摘掉护肩/腰带/护腕/兜帽（`role==accessory`），并可逐件勾选；另把 2 具**标准体**（裸模）纳入下拉，作为「身形基准」——那是唯一能让体形变化**完全不被布料遮住**的载体（`garments/README.md`：B2 不做裸露躯干的泳装；要泳装级裸露需回 B1 路线，见「未做」） |

## 验收标准

- [x] `tools/3d/godot/shape-lab/run.cmd` 在 Windows 一条命令开窗；`run.cmd --shots` 离屏出图退出码 0、看门狗未触发
      → 实测 `SHOTS_TOTAL=25 failed_chars=0`、`Godot exit code = 0`、日志 `ERROR` 行 **0**；`--selftest` 37 项 `fails=0`
- [x] 6 个角色（4 服装 + 2 标准体）逐个可加载不崩；网格/骨架/带 morph 件数与缓存 manifest 一致
      → 容器实测 12/12/8/8/3/3 mesh、**1 skin / 65 joints**（6/6）；带 morph 件 **42 件**、源即无 morph **4 件**（裸模 Eyebrows/Eyes）
- [x] `k=-1/0/+1` 三档：每件网格有非零 morph 位移（`Head_Eyebrows`/`Head_Eyes` 按 `static_by_design` 除外），
      且**解析式复算**（basis + Σw·delta）显示围度/剪影随 k 单调（thin < standard < heavy）
      → 与 Godot 自己烘的网格逐顶点比 **max |Δ| = 0.000e+00 m（精确 0）**；围度代用 XZ 均宽周长
      Female_Ranger **6.859 → 6.979 → 7.152 m**、X span 1.635 → 1.664 → 1.702 m，**6/6 严格单调**
- [x] 身高滑块走「场景根节点 world scale」：**骨 pose 逐值不变**（给原始读数）、世界高度按比例变
      → h=0.92/1.00/1.08 下 `pose_position/rotation/scale` 与 `global_pose_origin` **15+ 位完全相同**；
      `skeleton world scale` = 0.920000/1.0/1.080000；解析身高 1.79408 → **1.65055 / 1.93761**
- [x] **零素材副本**：`Get-ChildItem -Recurse tools/3d/godot/shape-lab -Include *.png,*.glb,*.gltf,*.blend,*.pyc` 为空
      → **命中 0 个**（独立复验两次，工程内 26 张 PNG 全在 `tmp/shape-lab/shots/`）
- [x] 「清凉」预设隐藏的 part 集合 == 按 role 规则（`role==accessory`）独立算出的集合
      → 在工程**副本**里实例化真 `main.tscn`、**真按 Button**、直读 `visible`：6/6 相符；
      例 Female_Ranger 隐藏 5 件 = `Acc_Pauldrons / Arms_Bracer / Body_Belt_1 / Body_Belt_2 / Head_Hood`
- [x] 资产层独立验收（GLB 容器 / 顶点数 / morph 数值 / 与上游台账交叉核对）有 `.json` + `.md` 结论，且断言**能变红**（破坏性复现）
      → `verify/assets-verify.{json,md}`：**315 条 / PASS 313 / FAIL 0 / UNVERIFIED 2**；**11/11** mutant 全部命中
- [x] （追加）应用层独立验收 → `verify/app-verify.{json,md}`：**33 条 / FAIL 0 / UNVERIFIED 0**；
      **2/2** mutant 命中（其中 `swap_deltas` 只让「与台账比数值」那条变红，证明"内部一致"替代不了"数值正确"）

## 产出

| 路径 | 说明 | 写入方 |
|------|------|--------|
| `tools/3d/godot/shape-lab/` | ★ 交付：精简 Godot 4.6 工程（工程文件 / 脚本 / `run.cmd` / `run.sh` / `README.md` / `.gitignore`） | `app`（task-2） |
| `tools/3d/godot/shape-lab/bake.py` | `.blend → .glb` 烘焙器 + 缓存 manifest（零拷贝的入口） | `baker`（task-1） |
| `tmp/shape-lab/` | 缓存：`glb/<id>.glb`（贴图内嵌）、`manifest.json`、`logs/`、`reports/bake-report.json`、`shots/`（不入库） | T1/T2 |
| `task/008-godot-shape-lab/verify/` | 独立验收报告（资产层 + 应用层） | `verifier`（task-3/4） |

## 冻结契约 v1（Lead 定，改前必须先说）

- 缓存根 `tmp/shape-lab/`（`ARTSTUDIO_SHAPELAB_CACHE` 可覆盖）；索引 `manifest.json`，schema 全文见共享卡 task-1 描述。
- 资产只从**绝对路径**读：Godot 侧 `GLTFDocument.append_from_file()`；**任何素材副本都不许进 `res://`**。
- 体形：`k∈[-1,1]` → `BS_Thin=max(-k,0)`、`BS_Heavy=max(k,0)`，**shape key 索引 0/1 与名字都是硬契约**。
- 身高：**加载场景根节点的 world scale**（`assets/3d/rig/SPEC.md` §3.4 / F12），**绝不缩放 `root` 骨**。
- `role` 分类优先级（命中即止）：`head`（`Head_` 前缀）→ `skin`（材质含 `MI_Regular_`）→ `foot`（`_Feet` 结尾）→ `accessory`（`Acc_`/`_Belt`/`_Bracer`/`_Hood`）→ `cloth`。

## 分工（Agent Team，写作用域互不重叠）

| 卡 | owner | 内容 | 写作用域 |
|---|---|---|---|
| task-1 | `baker` | `.blend→.glb` 烘焙器 + manifest + 自检 | `shape-lab/bake.py`、`shape-lab/tools/`、`tmp/shape-lab/` |
| task-2 | `app` | 精简 Godot 工程（双滑块/换装/显隐/读数/截图） | `shape-lab/*.gd|*.tscn|project.godot|.gitignore|run.cmd|run.sh|README.md`、`tmp/shape-lab/shots/` |
| task-3 | `verifier` | 资产层独立验收（GLB/morph/台账交叉） | `tmp/shape-lab-verify/`、`task/008-…/verify/` |
| task-4 | `verifier` | 应用层独立验收（解析式复算/身高/零拷贝/预设） | `tmp/shape-lab-verify/`、`task/008-…/verify/` |

Lead：契约冻结、`TASK.md`、终验（跑 `run.cmd --shots` + 零拷贝审计 + 逐项对账）、对外呈现。

## 验收结果（Lead 终验，2026-10-14）

| 层 | 谁 | 判据 | 结果 | 关键数字 |
|---|---|---|---|---|
| 资产 | task-1（baker 自检） | a–e 共 5 组 | 全绿 | 6 glb 合计 **222.2 MB**；冷烘 15.0–16.1 s / 热烘 0.59 s（DoD ≤5 min）；两次 `--force` 冷烘 sha256 一致 |
| 资产 | task-3（verifier 独立） | **315 条** | **PASS 313 / FAIL 0 / UNVERIFIED 2** | morph 位移 vs 上游台账 84 个 (件,档) **max \|Δ\| ≤ 4.97e-07 m**；Blender depsgraph 第三实现 **≤ 2.18e-08 m**；**11/11** mutant 命中 |
| 应用 | task-2（app 自测） | 3 条路径 | 全绿 | `--shots` 25 张 / 退出码 0；`--selftest` 37 项 `fails=0`；`--fixtures` 9 张 / stderr 0 字节 |
| 应用 | task-4（verifier 独立） | **33 条** | **PASS 33 / FAIL 0 / UNVERIFIED 0** | 解析式复算 vs 引擎烘的网格 **max \|Δ\| = 0.000e+00 m**；`get_aabb()` 三档逐位不变；骨 pose 15+ 位不变；**26/26** 出图 sha256 与 app 那次逐位相同 |

**两条 UNVERIFIED（诚实声明，不是缺陷）**：
① task-3 的 A-23e（同一批顶点上的 mean 对账）在两具标准体上**不适用** —— 它们唯一带 morph 件的顶点数 7380 vs 7376、7283 vs 7281，不存在"干净子集"；服装四套都可检验且全过。
② `garment_manifest.json` **不含 `.blend` 级 sha256**（只有 `bodyshape_manifest.json` 有）→ 4 套服装只能证明「manifest ↔ 当前磁盘」一致，**不能**证明与台账登记那一版一致（上游台账缺口）。

**列入「未做 / 边界」（如实声明）**：
- 不做 B1 叠穿（泳装级裸露要回 B1 路线）；不摆 A-pose（契约禁止碰骨 pose，源姿态即 T-pose）；
- `run.sh`（macOS 兼容版）**本机未实测**（脚本头与 README 都标了）；交付机是 Windows，`run.cmd` 才是已实测主入口；
- 不压缩 / 不 LOD 纹理：**222 MB 是「贴图内嵌 + `export_image_format=AUTO`」的预期值**，减体积是另一个决定；
- `bake.py` 的角色清单是**固定列表**（非目录扫描）→ 加自己的资产要加一行 + 重跑（README §扩展 有步骤）；
- 本工程**不是通用 3D 查看器**：只吃「**65 骨 rig + `Basis/BS_Thin/BS_Heavy`**」的 `.blend`。

## 步骤

1. 侦察：现有重型 `tools/3d/godot/preview/`（Mac 专用 `run.sh`、穿模像素法、31KB README）与 `assets/3d/rig/`（4 自包含角色 + 2 标准体，均带 `Basis/BS_Thin/BS_Heavy`）。
2. 冻结契约 v1（缓存布局 + manifest schema + role 规则 + k/h 口径）。
3. 建共享卡 task-1..4，spawn `baker` / `app` / `verifier`。
4. 并行：烘焙层与工程层各自落地（工程层按冻结契约先写，不空等）。
5. 资产层验收（task-3）→ 应用层验收（task-4）→ Lead 终验。
6. 呈现：关键渲染图 + 一条命令用法；是否入库由用户定。

## 决策与笔记

- 2026-10-14 **不改造现有 `preview/`，另起 `shape-lab/`**：现有那套是 task-007 的**验收证据页**（承载穿模像素法与双向标定，
  31KB README 是证据链的一部分），按删除规则不该动它；且它的 `run.sh` 是 macOS 写死路径，在本机（Windows）跑不起来。
  新工程定位是**日常用的快预览器**，与证据页并存。
- 2026-10-14 **复用「Blender headless 预导出 .glb 到 `tmp/` 缓存 + Godot 运行时 `GLTFDocument` 读取」这条已验证路线**，
  而不是 Godot 的 `.blend` 直读：直读是 **Editor Setting**、headless 直接拒绝，且会把贴图解包进 `res://assets/textures/`
  （~125 MB 素材副本）—— 见 `tools/3d/godot/README.md` §1。
- 2026-10-14 **导出前必须清零 shape key 值**（源 `.blend` 里存着 1.0/1.0 的落盘状态，不清零 glTF 默认权重就是「又瘦又壮」拉满）。
- 2026-10-14 **身高不用 `root` 骨缩放**：与 `inherit_scale='NONE'` 的烘焙期契约冲突（实测身高只 +0.50%、拉伸离散度超标 8.4×）。
- 2026-10-14 **不做 B1 叠穿**（标准体 + `B1_superhero_standard/` 服装 = 泳装/裸甲那条路）：本任务只交付「一个角色一个文件」的
  B2 自包含角色 + 裸模标准体；B1 叠穿作为 README 里的扩展方向写明，避免为它引入「橙斑」类装配风险（`garments/README.md` 警告）。
  用户若确实要泳装级裸露预览，再单开任务。
- 2026-10-14 **工程目录要自己加 `.gitignore`**：仓库根 `.gitignore` **没有** 忽略 `.godot/`，现有 `preview/` 也没加 ——
  Godot 一跑就会在工程根生成 `.godot/`（导入缓存），不忽略就会跟代码一起被提交。
- 2026-10-14 **截图/探针一律绝对路径**：相对路径会落进 `res://`，「零拷贝」这句话会静默变成假话（`preview/README.md` 记过这个坑）。
- 2026-10-14 **契约升级 v1.1（role 规则，唯一改动）**：v1 的匹配条件太窄 —— 裸模的 `Body_Female/Body_Male` 被判成 `cloth`、
  `Eyebrows`/`Eyes` 判成 `cloth`、`Male_Ranger_Feet_Boots` 判成 `cloth`。后果是「仅皮肤&头」预设**在裸模上会把一切都藏掉**。
  修订（只加宽条件，优先级与"命中即止"不变）：
  `head` += `^(Eyebrows|Eyes)$` / `*_Eyebrows` / `*_Eyes` / `Hair_*` 前缀；`skin` += `Body_*` 前缀；`foot` += 名称含 `Boots`。
  修订后用真数据复核过：46 件 → accessory 10 / skin 5 / foot 4 / head 18 / cloth 9；schema `version` 保持 1，另加顶层 `role_rules:"v1.1"`。
- 2026-10-14 **批准剔除两具标准体里的 `Icosphere`**（42v/80f、无材质无蒙皮、z∈[-1,1] 的 1 m 球，会在预览里罩住脚）：
  三条件同时满足才剔（保守），清单在 `tmp/shape-lab/reports/`；上游 `garment/derive_on_character.py` 当年同样删过它（`garment_manifest.json` 的 `junk_removed`）→ **沿既有口径**，不是新发明。
- 2026-10-14 **批准「按件分档」的 morph 断言**：两具裸模的 `Eyebrows`/`Eyes` 在源 `.blend` 里**没有 shape key**，
  所以"每件都必须有 BS_Thin/BS_Heavy"会假 FAIL；正确口径是"有 morph 的件必须有 2 个 target 且顺序正确，无 morph 的件必须没有 target"。
- 2026-10-14 **实测事实（三条，来自 baker，Lead 已用真数据复核）**：
  ① morph 名在 **mesh 层** `extras.targetNames`（primitive 层为空）→ 应用层**按索引 0/1 取值、名字只当断言**；
  ② 部件必须按**节点名**索引（glTF 的 mesh 资源名 = Blender mesh data 名，`Male_Peasant` 的 `Hair_SimpleParted` 数据名竟是 `Plane.002`）；
  ③ 男装头网格有 **7 个游离顶点**（Blender 1562 → glTF `POSITION` 1555）：glTF 不导出游离顶点，属源数据固有，**不是导出丢件**。
- 2026-10-14 观察（不在本任务范围）：未入库的 `task/006-poly-multiview-tpose/` 复用了「006」这个号（`task/README.md` 约定「只加不改、绝不复用」，006 属已归档的 `006-spine-convert-batch`），且 `task/README.md` 的编号台账没更新。留给用户定夺。
- 2026-10-14 **骨索引口径修订（独立验收查出的机制，不是拍脑袋）**：verifier 把真 glb 的 `skin.joints` **整段倒序**（nodes 与层级不动）→ Godot 的骨顺序**一位没变**（`Head` 仍 54，而倒序后 joints 数组里它已是 10）。
  结论：Godot 既**不读** `skin.joints` 数组、也**不读** `nodes` 数组顺序，而是按**骨层级 DFS** 建骨（65/65 逐位相符，原样/倒序两份文件都成立）。
  所以工作区既有的「glTF 路线 `Head=6`」与本工程实测的 `Head=54` **不是矛盾**：那条量的是**上游 Quaternius 原始 glTF**（另一份文件，现已不在盘上、verifier 也无法复测），两者骨层级顺序本就不同。
  → **正确口径**：骨索引取决于**该文件里的骨层级顺序，跨文件不可复用**（比"某路线=某索引"更强也更准）。`shape-lab/README.md` 对应那句已按此改写（**Lead 改的**，因 app 已结卡；改动只是这一句措辞，无代码影响）。
  ⚠ 遗留建议（本任务不动）：`tools/3d/README.md` 与 `assets/3d/rig/SPEC.md` F4 那句「.blend 路线 54 / glTF 路线 6」建议后续按同一口径补注。
- 2026-10-14 **验收方法论沉淀（本项目最值钱的产出）**：
  ① **"绿"必须能变红** —— task-3 用 11 个 mutant、task-4 用 2 个；其中 `swap_deltas`（两档位移整段对调，名字/顺序/顶点数全对）
  只让「与台账比数值」那条变红，而"引擎与公式自洽"那条**仍然绿** → **"内部一致"替代不了"数值正确"**。
  ② **空白图判据要有阴性对照**：verifier 自造「纯背景 + 1 个白像素」对照图，真图 0/4 判红、对照 4/4 判红 → 阈值有 17–22 倍余量，判据非空洞。
  ③ **GDScript 的 invalid call 只中断当前函数、进程仍退出 0**（verifier 自己踩了两次）→ 探针必须加「关键字段齐全」的硬门禁，否则会得到"退出码 0 + 报告缺字段"。
  ④ `surface_get_blend_shape_arrays(s)` 返回的是**每个 blend shape 的 arrays（Basis 不在里面）**，且 glTF 走 **absolute 模式** → 位移 = `shape − basis`。
  verifier 第一版当 deltas 用，症状是"k=−1 的 bbox ≈ 2 倍、k=+1 完全不变" —— **不报错不崩、只是数全错**。
- 2026-10-14 **行数软目标未达成（1351 行 vs ≤900）—— 决定不砍功能**：超出主要是证据类代码（`page_stats` 空白判据 ~50 行、`--selftest` ~65 行、逐件读数 ~55 行、`--fixtures` ~45 行）。
  其中 `--fixtures` 刚顶出一个真 bug（`get_blend_shape_count()` 只在 `ArrayMesh` 上，对 `BoxMesh` 调用报 `Nonexistent function` 且**静默返回空串**，真数据一直掩盖着它），
  `--selftest` / `page_stats` 是"不许静默说谎"的防线 —— 砍它们等于拆防线。改为**可核对的对照口径**：本工程 **1351 行 / 53 KB**，`preview/` **2740 行 / 127 KB** → **行数 49% / 体积 42%**。
- 2026-10-14 **入库口径（按用户裁决）**：`task/006-poly-multiview-tpose`（另一条线）**单独一个 commit**；`tools/3d/godot/shape-lab` + `task/008-godot-shape-lab` 一个 commit；
  `git fetch` 后普通**快进** push（远端与本地 0/0，无需强推）。`tmp/**` 一律不入库（含 222 MB 缓存与 ~40 张截图，可重烘重出）。
