# assets/3d/rig/ —— 角色管线 v2：体形 morph（**先看这个**）

> **这套目录是干什么的**：给 3D 角色做**可调的体形**（瘦 / 标准 / 壮）+ **身高**，
> 并让**服装跟着一起变**，用的是引擎原生的 **morph（blend shape）**，不需要任何运行时变形代码。
>
> **唯一权威契约**：[`SPEC.md`](SPEC.md)（含 F1–**F36** 全部实测事实）。改契约要通知全员。
> **骨架清单**：[`SKELETON.md`](SKELETON.md) —— 骨层级 + 组成 + 与 UE / Mixamo / Unity / VRM 的对照（含「是不是通用标准」的结论）。
> ⭐ **骨架契约 v2（77 骨）**：[`profiles/humanoid_biped_7spine.json`](profiles/humanoid_biped_7spine.json) + 映射 [`skeleton_mapping.json`](skeleton_mapping.json)（52 映射 + 25 额外）
> **morph 通道契约 v2.0**：[`channels.json`](channels.json) —— 体型预设轴（tent 插值）/ 连续轴 / 比例轴 / 表情命名空间 / 数据量预算
> **渲染 · UV · 贴图契约**：[`RENDER.md`](RENDER.md) —— **§0 为什么选 NPR（含 PBR 取舍，D20）**、简化阶梯 L0–L4、Godot 实测枚举值、UV 与贴图的自动配方、**三层结构（肤色/叠加/明暗）+ skin_tint**、**Tripo 贴图处置**、表情契约、13 条实测坑
> **第三方参考件分析**：[`reference/BODIEZ-ANALYSIS.md`](reference/BODIEZ-ANALYSIS.md)（含两处自我更正与两条方法论）
> **种族契约（一等公民）**：[`races/humanoid/race.json`](races/humanoid/race.json) —— rest 骨架 / 身高范围 / **8 头身**比例与标志点表 / 层×部位 / 比例轴 / 滑块骨 / 头接缝。任务与路线见 [`task/009-slider-body/TASK.md`](../../../task/009-slider-body/TASK.md)。
> ⭐ **要自己生成素材（含 AI 生成）？先读 [`GENERATION-GUIDE.md`](GENERATION-GUIDE.md)** —— 怎么生成才能保证「服装 × 体型」最大灵活性 + `bodyshape` 该用什么格式。
> **任务档案**：[`task/007-morph-pipeline/TASK.md`](../../../task/007-morph-pipeline/TASK.md)
> **复杂度与验收结论**：[`task/007-morph-pipeline/verify/COMPLEXITY.md`](../../../task/007-morph-pipeline/verify/COMPLEXITY.md)（独立验收方出品）
> **决策全过程与教训**：[`task/007-morph-pipeline/lead/FINDINGS.md`](../../../task/007-morph-pipeline/lead/FINDINGS.md)

---

## 0. 一句话原理

```
体形差异 = morph（逐顶点偏移表，每档 = 顶点数 × 12 字节）
身高差异 = 角色根节点 / 骨架对象的世界等比缩放（不是 morph、也不是 root 骨缩放）
```

身体与每一件服装持有**同名同序**的 morph，运行时由**一个数值**同步驱动。

---

## 1. 目录结构

```
assets/3d/rig/
  README.md                 ← 本文件（pipeline 指南）
  SPEC.md                   ← 接口契约（唯一权威，Lead 维护）
  bodyshape_spec.json       ← 体形骨定义 + 档位系数（工具与资产共用的单一事实来源）
  bodies/                   ← 标准体（65 骨 + BS_Thin/BS_Heavy 通道）
    Body_Female_Standard.blend
    Body_Male_Standard.blend
  garments/                 ← ★ 交付物：每份是「一个自包含角色」+ 同名 morph
    Female_Ranger.blend  Male_Ranger.blend
    Female_Peasant.blend Male_Peasant.blend
    B1_superhero_standard/  ← 已否决的 A/B1 路线产物，保留作参考（勿用）
  manifests/                ← 数字台账（bodyshape_manifest.json / garment_manifest.json）
  previews/                 ← 渲染与 Godot 预览截图/回执
  reports/                  ← 独立验收报告（verify-*.json）
```

**`garments/*.blend` 里有什么**：**恰好 1 副骨架** + 8–12 件网格（服装布料 + 服装自带皮肤 + 基础体的头），
**每一件网格都带 `Basis` / `BS_Thin`(索引 0) / `BS_Heavy`(索引 1)**。

| 文件 | 骨架 | 网格 | 顶点 | morph(2 档) | 身高比 Thin/Heavy |
|---|---|---|---|---|---|
| Female_Ranger | 1 | 12 | 27,920 | 654 KB | 0.99944 / 1.00064 |
| Male_Ranger | 1 | 12 | 27,637 | 648 KB | 0.99998 / 1.00010 |
| Female_Peasant | 1 | 8 | 16,376 | 384 KB | 1.00017 / 0.99981 |
| Male_Peasant | 1 | 8 | 12,376 | 290 KB | 0.99999 / 1.00001 |

---

## 2. 三条路线，以及为什么选 B2

| 路线 | 做法 | 需要额外资产 | 裸露身体占比（像素法） | 结论 |
|---|---|---|---|---|
| **B2** ⭐ | **体形 morph 派生在「角色自身网格」上** | **无** | **无（结构性）** | ✅ **主路线** |
| B1 | 标准体改用与服装**同源（Regular 比例）**的身体 | 一具同源身体 | 无（同源） | ✅ Tripo 阶段的正式形态 |
| A | 保留 Superhero 标准体 + 厘米级自动外推 | 无 | 74% → 44% ❌ | ❌ 已否决 |

### B2 为什么成立（关键洞察）

现有 `assets/3d/blend/tryon/TryOn_*.blend` **就是最终角色**：
服装布料 + 服装自带皮肤（`MI_Regular_*`）+ 基础体的头（3 件），**共用服装自己的 rig**。
→ **最终角色里根本没有独立的 Superhero 身体**（它只捐一个头）。
→ 于是"标准体与服装体形基准不一致"这个问题**本来就不该存在**。
→ 布料/皮肤/头共用**同一组骨变换** → 体形一变三者**同构地一起变** → **结构性不存在穿模**。

> 我们在这条路上绕了一大圈（F10 → F11 → 撤回 F11 → F16 → F17），
> 根因是**一开始就接受了"要把身体和服装拼起来"这个前提**。教训：**先质疑前提，再优化方法。**

### ⚠ B2 的边界（必须知道）

1. **不能做"裸露躯干"的服装**（泳装、裸露护甲）：那时布料不包住躯干，**体形变化没有载体** → 必须走 B1。
2. 每套服装是**自包含角色**（各带自己的 rig 与 morph），morph **不能跨套件复用**（单套仅 290–654 KB，可接受）。
3. 躯干被衣服盖住、看不见裸体 —— 对这批资产是**合理**的。

---

## 3. 复现命令（每步一条）

```bash
# 0) 旧资产回归（任何时候都该是 103/103）
python3 tools/3d/run_check.py

# 1) 规范化标准体（骨架改名 + 体形骨子骨 inherit_scale='NONE' + 建 morph 占位通道）
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
    --python tools/3d/make_standard_body.py

# 2) 体形派生：按 spec 摆体形骨 → 烘 BS_Thin/BS_Heavy → 回写标准体 + manifest + 三档预览
#    （纯 python3，不需要 Blender）
python3 tools/3d/bodyshape/derive.py --sex both
python3 tools/3d/bodyshape/derive.py --sex both --retune thin=0.80,heavy=1.25 --write-spec   # 调档位强度
python3 tools/3d/bodyshape/verify_bodyshape.py                                                # 28 项独立断言

# 3) ★ 服装/角色：B2 主实现 —— 体形 morph 派生在角色自身网格上
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
    --python tools/3d/garment/derive_on_character.py -- --only Female_Ranger

# 4) Lead 独立抽验（逐份重开断言：1 副骨架 / 每件有同名同序 morph / 拓扑 / 身高比 / 贴图）
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
    --python task/007-morph-pipeline/lead/accept_garments.py

# 5) Godot 4 交互预览（一条命令出截图 + JSON）
/Applications/Godot.app/Contents/MacOS/Godot --path tools/3d/godot/preview \
    -s res://shoot.gd --resolution 640x480
```

---

## 4. 验收判据（**别用错判据**）

| 判据 | 用途 | 说明 |
|---|---|---|
| **像素法** ⭐ | **权威**：裸露身体占剪影比例 | 标准体染纯红 + 胶片透明（alpha=剪影）+ 数红像素。**无网格拓扑假设** |
| 顶点级穿模率 | ⚠ **仅作参考** | 按**顶点密度加权**（`*_Feet` 一件占 43% 顶点），且依赖网格封闭性 → **严重低估** |
| 身高比 | 体形与身高正交性 | 目标 **1.0000 ± 0.002** |
| morph 名称 + 索引 | 硬契约 | 身体与**每一件**服装都必须 `Basis` / `BS_Thin`(0) / `BS_Heavy`(1) |
| 拓扑一致 | 硬前提 | 三档顶点数/面索引完全相同 |
| 数据量 | 预算 | = 顶点数 × 12 B × 档数 |

**像素法实现三坑**（都踩过）：① `AgX` 会把纯红压成鲑鱼粉（`r/g≈1.5`）→ **必须 `view_transform="Standard"`**；
② 背景**不能**用颜色阈值判 → 用 **`film_transparent=True` 的 alpha 通道**；
③ 红色判据太松会误收**棕色皮革与皮肤** → 收紧到 `g,b` 都低。
参考实现：`task/007-morph-pipeline/lead/pixel_metric.py`。

---

## 5. 已知坑速查（详见 SPEC 事实表）

| 坑 | 一句话 |
|---|---|
| **F6 / F14** | `inherit_scale='NONE'` **只断"缩放"继承，不断"位置"继承** —— 缩 `pelvis` 会让脚也动 15.9 mm。且它设在 **`arm.data.bones`** 上（不是 PoseBone） |
| **F18** | ⚠ **`inherit_scale` 有"生命周期"之分**：`bodies/`（烘焙期）**必须 NONE**，`garments/`（交付期）**应还原 FULL**。实测 root 骨 ×1.08 拉伸离散度 **NONE 0.0257–0.0760 → FULL 0.0000–0.0001**。**别拿"资产里是否 NONE"当判据** |
| **F22** | ⚠ **一致性判据容易"退化"** —— 报之前必须自问两句：**(a) 尺度无关吗？配对距离上限是什么？**（绝对 µm 阈值卡 2 cm 内点对会假失败，那是 `\|girth−1\|×d` 的仿射必然项）**(b) 在我选的点集上，这个量『可能不为零』吗？** 若不可能，**测出的零没有信息量**。⚠ 本任务里"布料↔皮肤位移差 ≈ 1 个 float32 eps"就被误当成过铁证 —— 实则那批点全在**手腕/手/指**，而手是**刚体**（`hand_*` 不在 14 根体形骨名单里且被设为 `NONE`），刚体上位移差**必然为 0** |
| **F23** | ⭐ **B2「结构性无穿模」的正确论据 = 架构事实 + 接口计数**（不依赖数值）：角色里**只有一具身体**（无 `Body_*`）；**唯一的布料↔皮肤接口只有手腕一圈**（女 510 / 男 446 顶点在 <2 cm），其余 **1264/1390** 个布料顶点距任何皮肤 >2 cm，且**躯干/腿网格没有 `MI_Regular_*` 材质** → **穿模所需的两个对象不在场**。保留的非平凡数值证据：头↔领口最小间隙三档 **≤0.5 mm** |
| **F21** | ⚠ **像素法必须带双向标定**：只渲身体 → 必须 **100.00%**；只渲服装 → 必须 **0.00%**；不过就报错。实测**不带标定在"无身体"图上误报 37.3%**；材质须 Emission 纯色 + `view_transform='Standard'` |
| **F12** | **身高不能用 `root` 骨缩放**（与 F6 冲突：身高只 +0.50%、拉伸离散度超标 8.4×）→ 用**骨架对象/角色根节点世界等比缩放** |
| **F9** | **shape key 不修改 `mesh.vertices`** → 所有测量/工具必须走 **depsgraph 求值**，否则量到"没变化" |
| **F15** | 标准体**不是闭合曲面**（26 连通域 / 48 边界环，边界边 58% 在手腕与足部）→ 穿模率在手臂/手部**不可靠** |
| **F15b** | 面绕向**是**一致的；BVH 法线定向不可靠的真因是**身体相对质心非星形**（仅 67.2% 面满足）→ 别用顶点法线外推造壳 |
| **F15c** | 紧身件布料中位有符号距离在 ±0.06 cm 内时，顶点级穿模率**趋近 50%**，与视觉脱钩 |
| 骨名 | 小腿是 **`calf_l/r`**，**没有** `shin_*`。别凭记忆写骨名 |
| 保存 | `.blend` 保存前设 `save_version = 0`，否则每次留 `.blend1` |
| 备份 | shape key 的 `data[i].co` 是**绝对坐标**，重跑前必须归零，否则**叠加** |

---

## 6. 与旧资产、与 Tripo 的关系

- **旧 `assets/3d/blend/`（103 份）只读不改**：`run_check.py` 的 103 条断言、`manifests/blend-manifest.json`
  的 sha256 清单、Godot `cfg.gd` 的路径清单三处都在依赖它。它是 v2 的**输入与回归基线**。
- **Tripo 阶段**：目标不是"换两个输入"，而是**让标准体与服装第一次就同源** ——
  即「**先生成唯一标准体，再以它为基准生成/裁剪服装**」。
  若 Tripo **分别独立**生成身体与服装，**两次生成的体形不会一致**，A 路线那块人工成本会**原样保留甚至更严重**。
  同源之后，**B1 与 B2 收敛为同一件事**。
- **迁移时要重新标定**：`delta_response` 的 9 个系数是针对当前网格调出来的；换网格后必须重调（人工介入点）。
  且 morph 的硬前提"三档顶点数一致"要求 AI 生成**可控拓扑** —— 这是 Tripo 接入前必须先解决的事。