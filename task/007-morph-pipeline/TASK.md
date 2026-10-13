# 007 — 3D 角色管线 v2：体形 morph + 资产重构（为 Tripo 铺路）

| 项 | 内容 |
|---|---|
| **状态** | 🟡 进行中（2026-10-13 启动） |
| **负责人** | Lead + 智能体团队（4 名成员） |
| **接口契约** | [`assets/3d/rig/SPEC.md`](../../assets/3d/rig/SPEC.md) ← **所有实现必须遵守** |
| **前序** | 002~006（2D 时代）已归档；本任务为 3D 转型后第一个正式任务 |

## 一、目标

1. **验证「骨骼滑块调体形」路线**：用现有 2 具身体（`Superhero_Female` / `SuperHero_Male`）作为标准体，用骨骼滑块派生**瘦 / 标准 / 壮**三档，烘成 morph。
2. **验证「morph 做服装变形」的复杂度**：跑通「剥离皮肤面 → 贴合标准体 → 传递 morph」全链路，量化每一步的**工时、人工介入点、失败率、数据量**。
3. **重构 3D 资产结构**：新增面向新管线的资产树（旧 `assets/3d/blend/` 保留只读），使**未来换成 Tripo 生成时只替换两个输入、链路不变**。
4. **Godot 4 交互预览页面**：体形滑块（含档间插值）+ 身高滑块 + 换装 + 换发型，能直观看到效果与穿模。

## 二、验收标准

| # | 验收项 | 判据 |
|---|---|---|
| A1 | 标准体规范化 | 2 具标准体，65 骨，体形骨按 SPEC §3.2 设 `inherit_scale='NONE'`（F6） |
| A2 | 体形派生可复现 | 一条命令从标准体产出 `BS_Thin`(0) / `BS_Heavy`(1)，三档顶点数一致（实测应为 7376/7281） |
| A3 | 服装剥离 | 4 套服装的 `MI_Regular_*` 皮肤面全部剔除，去除率与实测（女 Ranger 38% / 男 Peasant 74%）一致 |
| A4 | 服装贴合 | 服装重绑到标准体骨架；穿模率 ≤ 贴合前基线 |
| A5 | morph 传递 | 每件服装带 `BS_Thin`/`BS_Heavy` 同名同序 morph；名称+索引 100% 对齐 |
| A6 | 量化验收 | `verify_fit.py` 输出 SPEC §5 全部 6 项指标，全部达标 |
| A7 | Godot 预览 | 拖动三个滑块实时变形、换装、换发型；离屏截图 + JSON 证据 |
| A8 | 复杂度报告 | 每步的**耗时/人工介入点/失败案例/数据量**，且有独立复现 |
| A9 | 文档 | `assets/3d/README.md` 新增 v2 章节；各工具目录有 README + CLI 用法 |
| A10 | 旧资产零破坏 | `python3 tools/3d/run_check.py` 仍 **103/103** 通过；旧 `blend/` 未被修改 |

## 三、关键侦察结论（设计依据，详见 SPEC §1）

- **F2 最重要**：服装长在 **「Regular」身体**上，不是我们的 **Superhero**。`Female_Ranger_Arms` = 62% 布料 + **38% 皮肤**（`MI_Regular_Female`），`Male_Peasant_Arms` = 26% 布料 + **74% 皮肤**。→ 必须**先剥离皮肤面**。
- **F1**：24/24 资产 65 骨**骨名+顺序一致**，但 rest：女体↔女装 **0/65 不一致**、男体↔男装 **58/65 不一致（3.4 cm）** → 女侧可直接共用骨架，男侧需贴合。
- **F6**：骨架缩放**沿层级继承**（实测 scale `pelvis` 使身高意外 +11.24%）→ 体形骨必须设 `inherit_scale='NONE'`。
- **F7**：等比缩放 `root` 1.08 → **0% 相对失真** → 身高交给骨架，不做 morph。
- **F4**：morph 数据量 = 顶点数 × 12 字节（女体 86.4 KB/档，整套服装 290.7 KB/档）→ **数据不是瓶颈**。

## 四、团队与写入范围（**互不重叠**）

| 成员 | 职责 | 写入范围 |
|---|---|---|
| **Lead** | 架构 / 契约 / 标准体规范化 / 集成 / 终验 | `assets/3d/rig/SPEC.md`、`assets/3d/rig/bodies/`、`assets/3d/README.md`、`task/007-morph-pipeline/TASK.md` |
| `bodyshape` | 体形派生工具链 | `tools/3d/bodyshape/`、`assets/3d/rig/bodyshape_spec.json`、`assets/3d/rig/manifests/bodyshape_manifest.json` |
| `garment` | 服装剥离/贴合/传递/验收工具 | `tools/3d/garment/`、`assets/3d/rig/garments/`、`assets/3d/rig/manifests/garment_manifest.json` |
| `godot-preview` | Godot 4 交互预览 | `tools/3d/godot/preview/`、`assets/3d/rig/previews/` |
| `verifier` | 独立验收 + 复杂度报告 | `task/007-morph-pipeline/verify/`、`assets/3d/rig/reports/` |

**协作规则**：全部按 `assets/3d/rig/SPEC.md` 开发；上游未就绪时用**自造 fixture** 并行推进，集成由 Lead 负责。

## 五、产出清单

- [x] `assets/3d/rig/SPEC.md`（✅ Lead，v1.0 + 事实表 F1–F17）
- [x] `assets/3d/rig/README.md`（✅ Lead，pipeline 指南：目录/三路线/复现命令/验收判据/坑速查）
- [x] `assets/3d/rig/bodies/Body_{Female,Male}_Standard.blend`（✅ Lead 规范化 + bodyshape 填 morph）
- [x] `tools/3d/bodyshape/`（✅ bodyshape：`derive.py` + `verify_bodyshape.py` 28 项断言 + README）
- [x] `assets/3d/rig/garments/*.blend`（✅ garment，**B2 路线**；Lead 独立抽验 **4/4 PASS**）
- [ ] `tools/3d/garment/`（🟡 工具已交付，**README 与 B2 manifest 待补**）
- [ ] `tools/3d/godot/preview/`（🟡 页面与截图已交付，**5 处缺陷待修 + README 待补**）
- [ ] `task/007-morph-pipeline/verify/`（🟡 `COMPLEXITY.md` 40 KB 已交付，**§9.1 待补 B2 评级**）
- [x] `assets/3d/README.md` v2 章节（✅ Lead）
- [x] `assets/3d/rig/bodyshape_spec.json` + `manifests/bodyshape_manifest.json`（✅ bodyshape）

## 六、决策记录

| # | 决策 | 理由 |
|---|---|---|
| D1 | **新管线走增量目录 `assets/3d/rig/`，旧 `blend/` 只读保留** | 103 份断言 + sha256 清单 + Godot `cfg.gd` 三处依赖旧路径；按 AGENTS.md 删除规则不得擅自移动/删除 |
| D2 | **服装剥离 `MI_Regular_*` 皮肤面** | 服装自带的是 Regular 身体皮肤，与标准体（Superhero）不是同一具身体，保留会双重叠模 |
| D3 | **身高用骨架等比缩放，不做 morph** | F7 实测 0% 失真、零数据、与 morph 天然正交可叠加 |
| D4 | **体形只做 2 个 morph 通道（Thin/Heavy）** | 三档标准体型 = Basis + 两档；档间插值白送。扩展第 4 档只需再加一个通道 |
| D5 | **morph 用"骨架滑块派生 + 一键烘焙"生产** | 美术所见即所得可反复调；运行时不用骨缩放 → 绕开"与动画争 pose"的坑 |
| D6 | **A 路线（保留 Superhero 标准体）确认可行，与 B 路线并行** | Lead 实测（F11）：自动去穿模外推把穿模 29.6% → **0.35%**（两独立判据一致），凸出深度仅厘米级；代价是局部失真 p99≈2×/极值≈9×，需补失真修复。详见 [`lead/FINDINGS.md`](lead/FINDINGS.md) §九 |
| D7 | **验收判据必须与"修"所用的判据相互独立** | Lead 踩过：用同一判据"推+量" = 自我实现，量出假的 0%；失真度量必须相对真·原始坐标（拿修改后坐标当 rest → 恒为 1.000） |
| D8 | ⭐ **身高改用「骨架对象 / 角色根节点的世界等比缩放」，不用 `root` 骨缩放** | verifier 实测发现 §3.2 与"缩 root 骨"**冲突**：身高只 +0.50%、拉伸离散度 0.0841（超 §5 阈值 8.4×）。改用对象级缩放 → **+8.00% / 离散度 0.00003**。SPEC §3.4 已改（F12） |
| D9 | ⭐ **体形 morph 口径 = `girth`（`(s,1,s)`，只缩垂直于骨轴的两轴）** | `bodyshape` 的决策，Lead 追认。保证体形与身高**正交**（身高比 ≈1.0000）。**F5 的 13–14 cm 作废**（含 ±11% 身高变化），SPEC F5/F13 已标注 |
| D10 | ⚠ **穿模率在手臂/手部区域不可靠，须声明前提** | verifier 查明标准体**非闭合**（26 连通域 / 48 边界环 / 面绕向不一致），边界边 58% 集中在手腕与足部；解析 fixture 上破洞网格把射线奇偶从 99.8% 打到 95.8%。**改用无拓扑假设的判据（像素法）** |
| D11 | ⭐⭐ **主路线确定为 B2：体形 morph 派生在「角色自身网格」上** | Lead 实测通过（F17）：用 `tryon/` 角色**自己的 rig** 摆体形骨 → 逐件烘 shape key。12 件 / 27,920 顶点、身高比 **0.99944/1.00064**、最大位移 3.21 cm、**两档全角色仅 654 KB**。**结构性无穿模**（布料/皮肤/头共用同一组骨变换）。→ **§4.1 的"剥离/贴合/传递"三步全部不需要** |
| D12 | ⭐ **像素法是权威验收判据**（取代顶点级穿模率） | 顶点级判据按**顶点密度加权**（`*_Feet` 一件占 43% 顶点）且依赖网格封闭性；像素法无这两项假设。实测：男 74.2% / 女 63.3% 的剪影是裸露身体（而顶点级只报 29.6% / 10.3%，**严重低估**） |
| D13 | **A 路线（Superhero 标准体 + 厘米级外推）不采用** | 像素法实测外推只能把裸露从 74% 降到 44%，仍需真几何重塑（人工密集）。**F10 → F11 → 撤回 F11 → F16 → F17 的整个过程**记录在 FINDINGS，其中"先接受前提、再优化方法"的教训已写入 |
| D14 | **撤回 F5 的「13–14 cm」，改用 `girth` 口径的 2.90/3.31 cm** | `bodyshape` 的决策，Lead 追认：保证体形与身高**正交**（身高比 ≈1.0000）。原数字是 `length` 口径，含 ±11% 身高变化 |
| D15 | ⭐ **B2 产物已通过 Lead 独立验收 4/4 PASS**；`assets/3d/rig/README.md` 已交付（pipeline 指南） | Lead 抽验脚本 `lead/accept_garments.py`：1 副骨架 / 每件同名同序 morph / 三档拓扑 / 身高比 ±0.002 / 贴图零断链。验收台账见 [`lead/ACCEPTANCE.md`](lead/ACCEPTANCE.md) |
| D16 | ⚠ **T3 预览"腿部橙斑"根因 = 多叠了一具标准体**（不是 B2 资产的问题） | verifier 四装配对照（`reports/verify-t3-integration.json`）：`P1`(只装 B2 角色) vs `P3`(B2 角色+额外标准体) 像素差 **52%** → **预览必须只加载 `garments/*.blend` 一个文件**，骨架数应为 **1**（+发型自带 1 副 = 2） |
| D17 | ⭐ **体形系数冻结为 v2：`thin 0.84` / `heavy 1.21`**，并以 **`coefficients_fingerprint`** 作版本判据 | T5 交付（`reports/bodyshape_v2_recommendation.md`）。v1 的真短板是**臂展/肩宽几乎不动（±0.46%）**，而它是正视图最宽轮廓线（1.67 m）→ 整体"看起来没变"。v2 用 `along_axis_response.clavicle = 0.5`（锁骨 head/tail 的 z **精确相同** → 改肩宽不改身高）修好。**瘦↔壮剪影 XOR 26.96% → 33.57%（+41%），≈ 身高滑块区间的 62–69%** |
| D18 | ⭐ **新增 SPEC F22 / F23**：一致性判据必须自问"**在我选的这个点集上，这个量可能不为零吗？**"，且 B2「结构性无穿模」的正确论据 = **架构事实 + 接口计数**，不是"数值为零" | verifier **自我推翻**了它原稿的最强论据（那 510/446 对点全在**手腕/手/指**，而手是刚体 → 位移差**必然为 0**，与 B2 好坏无关）。换成：角色里**只有一具身体**、**唯一的布料↔皮肤接口只有手腕一圈**、躯干/腿**没有皮肤材质** → **穿模所需的两个对象不在场** |
| D19 | ⚠ **D-1 版本偏斜的根治：下游必须"读前记指纹、写前再校验"** | 事故窗口只有 **1 秒**（garment 18:20:20 读、v2 18:20:21 落盘）→ 导致标准体 v2 / 角色 v1。**判定版本只认 `spec_version` / `coefficients` / `delta_response_values` + `along_axis_response_values` / `coefficients_fingerprint`** —— 比 mtime 稳、比文件 sha 准 |
| D20 | ✅ **「F6 vs 身高」疑问闭环**：`bodies/`（`NONE×18`）与 `garments/`（`FULL×65`）**各自合规、谁都不用改** | `bodyshape` A/B 实测（`reports/bodyshape_height_method.json`）：**对象级缩放与 F6 正交** —— 即使保留 `NONE×18`，对象级 ×1.08 仍是 **+8.000% / 离散度 0.0000385**（比阈值好 **260×**）；`root` 骨法的不相容根因是"骨缩放走层级被 F6 断开"，**与"该不该留 NONE"无关**（F12 已废弃它）。已固化 SPEC **F12b** |
| D21 | ⭐ **`derive.py` 的 Tripo 前瞻改动：硬失败 → 「自设(幂等) → 再自检」** | **验收判据 = 未规范化输入必须产出逐位相同的 morph**：`FULL×65` 输入自设 18 根后，四位 morph digest 与 `NONE×18` 输入**逐位相同** → **Tripo 换身体时这条不再是坑** |
| D22 | ⭐ **验收门禁必须"证明它会变红"**：`blender -b --python X.py` **抛异常仍返回 exit 0** | `garment` 因此出现"门禁全绿、清单停在旧版"。修法：`--python-exit-code 1` **+** 扫 `Traceback` **+** 产物 sha256 前后比对，并**故意让脚本失败一次**确认会变红（`verify/run_verify.sh --selftest`）。**Lead 验收脚本已同样加固**（三重判定：rc=0 且无 Traceback 且有 DONE 标记） |
| D23 | ⭐ **判据口径三教训**（本任务给复杂度报告最有价值的部分） | ① **判据退化**：写 shape key 后求值缓存失效（→ F9b）；② **判据退化**：B2"位移差为零"其实是**刚体手部**的必然结果（→ F22/F23）；③ **门禁不响**：见 D22。**一句话：测出的零要先问"它可能不为零吗"；"绿"必须被验证过它会变红。** |