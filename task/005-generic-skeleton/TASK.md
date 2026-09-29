# 通用骨骼：基于「帝国圣骑士变体」改造

> 用户 2026-09-28 发起。基座素材：`tmp/帝国圣骑士变体/`（快照已并入最终包 `output/`，
> 见产出表）。
> 终局愿景是把这套骨架改造成**通用骨骼**（可挂任意皮肤/可迁移动作的标准骨架）；
> 本任务先落地基座批处理两步 —— Step1 朝向统一、Step2 骨骼英文名。

| 项 | 值 |
|----|-----|
| 编号 | 005 |
| 目录 | `task/005-generic-skeleton/` |
| 状态 | 已完成 <!-- 规划中 / 进行中 / 已完成 / 已放弃 / 待人工校验 --> |
| 创建 | 2026-09-28 |
| 上游 | `task/003-spine-facing-unify/`（复用其共轭烘焙工具统一朝向） |
| 基座包 | `Unit_Spine_EmpirePaladinSpe1Skin1`（Spine 4.3.26，44 骨 / 31 槽 / 33 附件 / 10 动画 / default 单皮肤，零 constraints） |

## 目标

以帝国圣骑士变体为基座，加工出一份**通用骨骼**骨架 JSON：

1. **Step1 朝向统一**：复用 `tools/spine/anim/spine_flip_bake.py`（003 产物）共轭烘焙，
   把人物翻成**脸部朝右**（与 assets/2d 全库统一朝向一致），只改 JSON、不动原包。
2. **Step2 骨骼重命名**：插槽附件图逐张图像识别 → 推断每个骨头的语义部位 →
   44 根骨头全部改成**英文语义名**（`bone`/`bone2`… 通用名 → `head`/`arm_front_upper` 一类），
   同步修正全部引用（`bones[].parent`、`slots[].bone`、动画 bones 轨道 key），保证逐骨变换与动画完全等价。

后续（另开任务，不在本任务范围）：slim 皮肤槽位规划、权重迁移、动画映射接入 002 模板。

## 验收标准

- [x] **A1 朝向**：烘焙后渲染人物脸部朝右（复现：
      `python3 tools/spine/anim/render_rig.py output/Unit_Spine_EmpirePaladinSpe1Skin1.json -o tmp/x`）；
      `spine_flip_bake` 闸门 **G1 残差 0.0 / G2 setup 3.55e-13 / G3 违规 0** 全过，
      报告 `output/step1-flip-report.jsonl`。
- [x] **A2 重命名完整性**：全文档深度扫描旧骨名残留 **0 处**（只计被改名骨；
      键名 `bone` 字段与未改名 `root` 不算）；
      parent / slot.bone / 动画轨道 key 全部指向新名，父链无环。
- [x] **A3 动画等价性**：10 个动画逐骨轨道集合与关键帧数改名前后一致（脚本自检）。
- [x] **A4 命名可读**：44 骨全部英文语义名，映射表 `output/rename-map.json`
      （含 evidence 识别依据，辅助骨推断项标 `(*)`）。
- [x] **A5 视觉抽检**：翻转包 vs 重命名包 render_rig 逐骨世界变换最大差 **0.0**，
      pose 像素 diff **空**；2026-09-28 重组为最终包后复检仍逐像素一致。

## 步骤

1. 快照基座包到 `input/Unit_Spine_EmpirePaladinSpe1Skin1/`（三件套 + 单图 + preview + 原始 zip）。
2. 看 `复原预览图.png` 判定当前朝向（2026-09-28 实测：**朝左**，脸/主武器在左，盾在右）。
3. `spine_flip_bake.py --from left --to right` 烘焙 → `output/step1-facing-right/`，闸门记录进报告。
4. 渲染验证（步骤 5 的渲染链或 render_rig）确认朝右。
5. 拼接槽标注图（attachment 单图 + 槽名标注）→ 图像识别 → 产出重命名映射表。
6. `scripts/rename_bones.py` 执行重命名 → `output/step2-renamed/`，跑完整性/等价性校验。
7. 回写 TASK.md 与台账。

## 产出（2026-09-28 用户确认后重组为**单一最终包**）

| 路径 | 说明 |
|------|------|
| `output/` | **最终交付包**（下一步换装任务直接以此为包目录）：朝右 + 44 英文骨名三件套 `Unit_Spine_EmpirePaladinSpe1Skin1.{json,atlas,png}` + `images_original/`（32 张单图）+ `交付说明.md`（含 005 差异说明）+ `复原预览图.png` + 原始资源回退 zip |
| `output/rename-map.json` | 44 骨重命名映射与识别依据（evidence） |
| `output/step1-flip-report.jsonl` | Step1 烘焙报告（翻转域骨、G1/G2/G3 数值） |
| `output/step2-rename-report.json` | Step2 重命名自检报告 |
| `scripts/rename_bones.py` | 骨骼批量重命名脚本（引用完整性 + 动画等价自检，可复用） |
| `scripts/slot_sheet.py` | 附件单图 → 槽名标注总览图（识别证据生成，工作区根运行） |
| `notes/2026-09-28-识别与命名.md` | 朝向判定 / 识别记录 / 命名决策 |
| `notes/slot-sheet.png` | 32 附件槽名标注总览图（重命名判定证据） |

## 决策与笔记

- 2026-09-28：建任务。朝向判定=当前**朝左**（看 `复原预览图.png`）→ 烘焙 `--from left --to right`；
  翻转域骨 = root 直接子骨 `bone`(→hip)、`bone27`(→shadow) 2 根。
- 2026-09-28：重命名范围=**仅 bones**（slots 槽名 / 附件名不动，后续通用化再议）。
  7 个 mesh 全部刚性绑定（无权重骨骼数组）→ 皮肤引用零风险。
- 2026-09-28：Step1+Step2 全部落地并通过 A1–A5；状态改**已完成**。
  遗留：未跑官方 player 复核、`skeleton.hash` 未重算（工具链口径，同 003 交付包处理）；
  通用骨骼下一阶段（槽位规划换皮 / 002 动画迁移接入）另立任务。
- 基座包零 constraints（无 ik/transform/path），动画轨道含 slots/bones/drawOrder/events 四类，
  重命名只需覆盖 bones 名与其引用点。
- 命名规范：lowercase_snake；侧别沿用骨架自身 R/L 标签（不随镜像换边）；
  辅助骨 `_b`/`_c`、尾/裙分段 `segN`。完整口径见
  [`notes/2026-09-28-识别与命名.md`](notes/2026-09-28-识别与命名.md)。
- 2026-09-28（**用户确认结果无误后归档重组**）：`input/` 并入 `output/` 单一最终包。
  删除的可再生中间产物（均已入 git 历史，再生命令在案）：
  - `output/step1-facing-right/` 三件套 → 复现：
    `python3 tools/spine/anim/spine_flip_bake.py <原始包> --from left --to right -o <目录>`
    （原始包用 `pipelines.py build 原始资源_*.zip` 回退）
  - `output/verify/` 两个渲染校验目录 → 复现：`render_rig.py <json> -o tmp/x`；
    重组后已对最终包复检，与删除前基准逐像素一致
  - 原始朝左旧骨名 JSON → 可从 `output/原始资源_*.zip` 回退；
    原始 atlas/png 与终稿图集内容完全一致（管线不动图集/贴图）
  - `tmp/005*`（内存如渲染批图、校验渲染）已清；slot-sheet.png 移入 `notes/` 作识别证据。
