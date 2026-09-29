# assets/2d 全量烘焙镜像（朝向统一）：107 包人物全部面向同一侧

> `002-anim-retarget` 子任务衍生。需求完整口径见
> [`notes/2026-09-26-需求调研与方案.md`](notes/2026-09-26-需求调研与方案.md)（含算法规格、映射表、
> 分层清单、决策点）——实施 agent 以该文档为唯一权威输入。

| 项 | 值 |
|----|-----|
| 编号 | 003 |
| 目录 | `task/003-spine-facing-unify/` |
| 状态 | 待人工校验 <!-- 规划中 / 进行中 / 已完成 / 已放弃 / 待人工校验 --> |
| 创建 | 2026-09-26 |
| 更新 | 2026-09-27 |
| 上游 | `task/002-anim-retarget/`（阶段 0.5 朝向统一的全库升级版） |

> **2026-09-27 进展**：工具与全库批量已落地，数值闸门（G1/G2/G3）全过，统一朝向=**向右**（D1 用户拍板）。
> 产出 94/107 包（烘焙 81 + 原样复制 13），**13 包因 noScale 骨安全闸门拒绝**（清单见报告与
> notes/2026-09-27）。**G4 视觉 / G5 player / G6 迁移抽检按用户要求留待人工校验**——
> 校验入口：`output/flip-bake-report.json` 逐包记录，预览可用 `tools/spine/anim/anim_preview.py`。
> 状态在人工验收通过前保持「待人工校验」。

## 目标

`assets/2d` 下 **107 个 Spine 包（全部 4.3.26）数据级统一人物朝向**：
改 JSON 本身（烘焙），不改运行时 flipX、不动原包、不动图集/贴图/附件。
目的：后续 002 动作迁移时**模板增量直搬即视觉正确**，不再需要
轴向符号翻转与"translate 按父骨世界朝向差旋转"两套坐标换算。

核心算法（共轭烘焙）：只取反 **root 直接子骨（inherit=normal）** 的奇对称分量
（x / rotation / shearX / shearY / scaleX）及其动画通道；其余全部不动。
数学性质：烘焙产物与「运行时 root scaleX=−1」逐骨世界矩阵严格等价。

## 验收标准

逐包闸门（详见调研文档 §7 与 notes/2026-09-27 的落地修正）：

- [x] **G1 双翻恒等**：烘焙两次回原文（归一化口径，θr≠0 包允许 ≤1e-9 浮点残差）——94/94 过
- [x] **G2 镜像正确性**（口径已修正为真镜像，见 notes/2026-09-27 §3.5-3）：烘焙包逐骨世界矩阵
      == Fx·(原包+1 世界)，镜像子树逐骨 (a,b,c,d,worldX,worldY) max diff ≤ 1e-6，
      采样=每动画全部关键帧时刻∪首末帧；root 固定 setup 为闸门、含 root 动画为信息级（D4）——94/94 过（max 9.7e-10）
- [x] **G3 不动项审计**：diff 仅允许翻转域骨 6 字段（含 y，K 共轭所致）+ 其动画 rotate/translate/shear
      通道 + noScale 安全改写骨的 inherit 字段；slots/skins 其余/skeleton/atlas/png 不动——94/94 过
- [ ] **G4 视觉**：render_rig/复原预览图对比原包水平翻转图，确认朝向翻转、无穿帮（逐包）——**留待人工**
      （已抽检 1 包：法袍法师烘焙后 player 渲染确实朝右 ✓）
- [ ] **G5 player**：官方 4.3.x player 播放全部动画无报错、循环连贯（逐包）——**留待人工**
      （已抽检 2 包：法袍法师烘焙版、ShadowSoldier/多身魅魔/player 原包均能正常播放 ✓）
- [ ] **G6 迁移抽检**：Tier 1 选 2 包按 002 流程直搬迁移（映射表零轴向换算）player 验收通过——**留待人工/后续**
- [x] Tier 1 包全过 G1–G3（数值）；20 个 Tier 2 包按 D2=B-a 判定分流执行——
      **实测 20 包排除骨世界旋转在动画中变化 66°–274°，全部超阈 → 全部落 B-c（保持原样）**，
      逐包记录于报告，视觉完整性交人工 G4/G5 判断
- [x] 批量报告：`output/flip-bake-report.json`（每包：朝向声明、是否翻转、策略、闸门结果、警告/拒绝原因）

## 步骤

1. 用户拍板决策点 D1–D6（朝向、Tier 2 策略、产物落位等，见调研文档 §8）。
2. 实施 `tools/spine/anim/spine_flip_bake.py`：共轭烘焙 + 排除域判定 + G1/G2/G3 数值自检
   （G2 需要 runtime 公式模拟器，Bone.ts/Animation.ts 关键语义已摘录在调研文档）。
3. 朝向判定批次：render_rig 渲染 setup 帧 → agent 看图逐包声明 left/right（`--from/--to` 成对）。
4. 批量执行 + 逐包 G4/G5 验收（preview-2d / 单文件 player 流程）。
5. Tier 2 包按所选策略处理，逐包看图验收。
6. G6 迁移抽检 → 报告归档 `output/` → 状态改已完成，回写 002（阶段 0.5 指向本任务的产物集）。

## 产出

| 路径 | 说明 |
|------|------|
| [`tools/spine/anim/spine_flip_bake.py`](../../tools/spine/anim/spine_flip_bake.py) | 共轭烘焙工具（K 共轭 + noScale 安全改写 + Tier2 B-a/B-c 分流 + G1/G2/G3 自检，防御性退出） |
| [`output/<分类>/<包名>/<包名>.json`](output/) | 产物 94 包：烘焙 81（紧凑 JSON）+ 原样复制 13（字节一致）；目录树同 assets/2d，仅 JSON，复用原 atlas/png |
| [`output/flip-bake-report.json`](output/flip-bake-report.json) | 批量报告：107 包逐条（朝向声明/置信度、动作、翻转域骨、noScale 改写、Tier2 策略明细、G1/G2/G3 数值、constraints 计数、警告/拒绝原因） |
| [`input/facing.json`](input/facing.json) | 107 包逐包朝向声明（94 left / 13 right）+ 置信度 + 依据；3 包经 player 复核 |
| [`scripts/batch_bake.py`](scripts/batch_bake.py) | 批量驱动（读 facing.json 逐包烘焙/复制 + 汇总报告） |
| [`notes/2026-09-26-需求调研与方案.md`](notes/2026-09-26-需求调研与方案.md) | 需求与算法规格（实施输入） |
| [`notes/2026-09-27-实施记录与决策.md`](notes/2026-09-27-实施记录与决策.md) | 决策拍板 D1–D6、实施期重大实测修正（constraints 68/107、noScale 陷阱、G2 真镜像个径）、闸门落地口径 |

**未产出（13 包，报告 status=failed）**：Pest、RogueSekaniFlamebringer、Kimchul、kunai_ninja、CatGirl、
electro-archer、bbaksang、Tattooist、gonbong、yunggul、Act3_Polearm_GuardL、bboy、1021（哪吒童）。
原因统一为「noScale 骨改写不安全（父骨世界 |scale|≠1 或已含反射）」；leega/_replaced_leega/player
三包同属此结构但本身已朝右，原样复制即可。后续策略（逐包定制矩阵烘焙或旧式全量翻转）另行决策。

## 决策与笔记

- 2026-09-27：**单包试运行（用户指定）**：按用户要求用 `spine_flip_bake.py` 把
  `assets/2d/人形/男/帝国圣骑士变体/` 烘焙为朝右，先出完整包目录
  `assets/2d/人形/男/帝国圣骑士变体-右/`（json+atlas+png 三件套，原包不动）供人工验证。
  闸门：G1 残差 0、G2 setup 3.55e-13 / root 动画 4.33e+01（D4 信息级边界）、G3 零违规；
  翻转域骨 2、动画轨 20。预览：`tmp/003_paladin_variant_left.html`（原包）vs
  `tmp/003_paladin_variant_right.html`（烘焙包）。
  **→ 人工验证通过**：烘焙 JSON 已替换回原包（SHA256 与烘焙产物一致，atlas/png 原样），
  `帝国圣骑士变体-右/` 目录已按用户指示删除；原包可随时经
  `原始资源_*.zip` 回退。首个 assets/2d 原包就地翻向落地。
- 2026-09-27：**D1–D6 用户拍板**——D1 统一**向右**；D2 由 agent 定（B-a 判定分流 + 失败降 B-c）；
  D3 产物落 `task/003-spine-facing-unify/output/`（待人工校验后再沉淀）；D4/D5/D6 由 agent 定
  （D4 接受镜像轴固定、D5 保留旧 spine_flip.py、D6 做 K 精确共轭）。详见 notes/2026-09-27。
- 2026-09-27：**批量落地**：94/107 产出（烘焙 81 + 复制 13），数值闸门 G1/G2/G3 全过
  （G2 真镜像 max 9.7e-10）；13 包 noScale 安全闸门拒绝（leega 系与 player 因已朝右原样复制）。
  朝向判定：94 left / 13 right（2 个 002 锚点校准：法袍=left、络腮胡=right；3 包 player 复核）。
  Tier2 的 20 包排除骨动画旋转 66°–274° 全超阈 → 全部 B-c 保持原样（报告记录，视觉交人工）。
  G4/G5/G6 留待人工校验。
- 2026-09-26：需求调研完成（本文件夹 notes/）。关键实测：107 包全 4.3.26、root 零 shear、
  旋转≤0.185°、**零 constraints**（002 的 64/105 含 IK 痛点不适用于本库）、零 bezier、
  skeleton.x/y 全 0、1 包 root scaleX=−1、26 包 key 了 root rotate、
  20 包存在排除域可见附件（Tier 2）。
- 2026-09-26：算法定稿为**共轭烘焙**（只动 root 直接子骨），明确
  「全部骨头取反是错的」（嵌套两层起 Fx·L1·Fx·L2 ≠ Fx·L1·L2）；
  inherit 语义以官方 Bone.ts 源码为准（noScale 继承反射 → 参与翻转；其余三类为排除域）。
- 2026-09-26：scale 时间线 key **不变**——4.3 runtime 中 scale key 是 setup scale 的相对乘数
  （`x *= bone.data.scaleX`），镜像符号由 setup 的 −scaleX 提供（Animation.ts 实证）。
- 2026-09-26：与现有 `tools/spine/anim/spine_flip.py` 的分工：旧工具面向交付包库（含 IK，逐包按需翻）；
  本库（零 constraints）用新工具一次性全量烘焙，产物即 002 后续迁移的标准输入。
