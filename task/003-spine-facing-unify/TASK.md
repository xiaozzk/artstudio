# assets/2d 全量烘焙镜像（朝向统一）：107 包人物全部面向同一侧

> `002-anim-retarget` 子任务衍生。需求完整口径见
> [`notes/2026-09-26-需求调研与方案.md`](notes/2026-09-26-需求调研与方案.md)（含算法规格、映射表、
> 分层清单、决策点）——实施 agent 以该文档为唯一权威输入。

| 项 | 值 |
|----|-----|
| 编号 | 003 |
| 目录 | `task/003-spine-facing-unify/` |
| 状态 | 规划中 <!-- 规划中 / 进行中 / 已完成 / 已放弃 --> |
| 创建 | 2026-09-26 |
| 更新 | 2026-09-26 |
| 上游 | `task/002-anim-retarget/`（阶段 0.5 朝向统一的全库升级版） |

## 目标

`assets/2d` 下 **107 个 Spine 包（全部 4.3.26）数据级统一人物朝向**：
改 JSON 本身（烘焙），不改运行时 flipX、不动原包、不动图集/贴图/附件。
目的：后续 002 动作迁移时**模板增量直搬即视觉正确**，不再需要
轴向符号翻转与"translate 按父骨世界朝向差旋转"两套坐标换算。

核心算法（共轭烘焙）：只取反 **root 直接子骨（inherit=normal）** 的奇对称分量
（x / rotation / shearX / shearY / scaleX）及其动画通道；其余全部不动。
数学性质：烘焙产物与「运行时 root scaleX=−1」逐骨世界矩阵严格等价。

## 验收标准

逐包闸门（详见调研文档 §7）：

- [ ] **G1 双翻恒等**：烘焙两次回原文，数值 diff=0（归一化口径同 `spine_flip.py --check`）
- [ ] **G2 运行时等价**：模拟官方 runtime（Bone.updateWorldTransformWith + 各时间线 apply 语义），
      「原包+scaleX=−1」vs「烘焙包+scaleX=+1」逐骨世界矩阵 diff ≤ 1e-6（每动画关键帧时刻+首末帧）
- [ ] **G3 不动项审计**：diff 仅允许出现在 root 直接子骨 5 字段及其动画通道；
      skins/slots/skeleton/atlas/png 逐字节一致
- [ ] **G4 视觉**：render_rig 渲染对比原包水平翻转图，agent 看图确认朝向翻转、无穿帮（逐包）
- [ ] **G5 player**：官方 4.3.x player 播放全部动画无报错、循环连贯（逐包）
- [ ] **G6 迁移抽检**：Tier 1 选 2 包按 002 流程直搬迁移（映射表零轴向换算）player 验收通过
- [ ] 87 个 Tier 1 包全过 G1–G5；20 个 Tier 2 包（排除域挂可见附件，清单见调研文档附录 B）
      按 D2 决策的策略执行并逐包过 G4/G5，报告记录所选策略
- [ ] 批量报告：`flip-bake-report.json`（每包：朝向声明、是否翻转、策略、闸门结果、警告）

## 步骤

1. 用户拍板决策点 D1–D6（朝向、Tier 2 策略、产物落位等，见调研文档 §8）。
2. 实施 `tools/spine/anim/spine_flip_bake.py`：共轭烘焙 + 排除域判定 + G1/G2/G3 数值自检
   （G2 需要 runtime 公式模拟器，Bone.ts/Animation.ts 关键语义已摘录在调研文档）。
3. 朝向判定批次：render_rig 渲染 setup 帧 → agent 看图逐包声明 left/right（`--from/--to` 成对）。
4. 批量执行 + 逐包 G4/G5 验收（preview-2d / 单文件 player 流程）。
5. Tier 2 包按所选策略处理，逐包看图验收。
6. G6 迁移抽检 → 报告归档 `output/` → 状态改已完成，回写 002（阶段 0.5 指向本任务的产物集）。

## 产出

（实施后回填）

| 路径 | 说明 |
|------|------|
| `tools/spine/anim/spine_flip_bake.py` | 共轭烘焙工具（含 G1–G3 自检） |
| `output/<分类>/<包名>/<包名>.json` | 烘焙产物（目录树同 assets/2d，仅 JSON；复用原 atlas/png） |
| `output/flip-bake-report.json` | 批量报告 |
| `notes/2026-09-26-需求调研与方案.md` | 需求与算法规格（本文档为实施输入） |

## 决策与笔记

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
