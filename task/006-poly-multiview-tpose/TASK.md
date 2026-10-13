# poly 角色四方向 T-pose 站位图（去角去尾 → 四视图拼图 → 切割）

| 项 | 值 |
|----|-----|
| 编号 | 006 |
| 目录 | `task/006-poly-multiview-tpose/` |
| 状态 | 已完成 <!-- 规划中 / 进行中 / 已完成 / 已放弃 --> |
| 创建 | 2026-10-11 |
| 更新 | 2026-10-11 |
| 上游 | `task/005-generic-skeleton/refs/poly/poly-v5-teal.png`（1024×1024 透明底角色原图） |

## 目标

把带**角**与**尾巴**的 poly 角色原图加工成**前 / 左 / 右 / 后 四方向 T-pose 站位图**：
先一次图生图**去掉尾巴和角**，再以它为参考**一次生成一张含四方向的拼图**（同图内出四视图 =
保证四方向一致性），最后按 2×2 **切成 4 张单图**。产出可当换装 / 建模的比例与朝向对照。

## 验收标准

- [x] **A1 去角去尾**：第 1 次生成图**无角、无尾巴**，其余（脸 / 发型 / 配色 / 服装 / 姿势 / 画风）与原图一致
      （`output/step1-no-tail-horn.png`；人物整体略缩小下移，非缺陷）
- [x] **A2 四方向齐备**：第 2 次生成图里 前 / 左 / 右 / 后 四个方向都在，朝向正确，
      同一角色、同一服装、同一配色、同一比例（`output/sheet-4views-tpose.png`）
- [x] **A3 T 字站位**：四视图均为 T-pose（双臂平举、双腿并拢直立）
- [x] **A4 切割正确**：2×2 切成 4 张，每张只含一个方向；四张**同尺寸 912×993、同比例**
      （人物行范围 960/959/959/961 px，顶/底对齐差 ≤2px）
- [x] **A5 尺寸与格式**：生成图 2K（2048×2048）；单图 PNG 912×993（统一窗口裁切，非各自贴边）

## 产出

> **2026-10-12 清理**：用户确认「保留 v3，删除其他临时人物」→ 下面标注 **🗑 已删** 的 9 项（+ 2048 输入）
> 已从工作区移除。**所有 job_id 都留在本档案与 `notes/` 里，可随时用对应的 `*-poll` 免费重下**，
> 输入也可由 `scripts/prep_input.py` 一键再生。

| 路径 | 状态 | 说明 |
|------|------|------|
| `output/base-model-tpose-4view-v3/views/{front,left,right,back}.png` | ✅ **现行交付集** | 四视图 v3：`left` = **2/3 斜视水平镜像**、`right` = 2/3 斜视原图，四张同为 977×1015（本地镜像，**零额度**） |
| `notes/2026-10-11-生成记录.md` | ✅ | 全部 6 次生成的 job_id / 提示词原文 / 切割口径 / 验收数据 / 已知偏差 / 积分账 |
| `notes/base-model-human-ears-head-zoom.png` | ✅ | 人类耳复核放大图 |
| `scripts/prep_input.py` | ✅ | 输入准备（合成灰底 205 + resize 2K，可复现） |
| `scripts/slice_views.py` | ✅ | 拼图切割（统一窗口 + 分隔线剔除 + `--map`，可复现，带 bbox 报告） |
| `scripts/mirror_view.py` | ✅ | 视图水平镜像（本地、免费、可复现） |
| `input/poly-v5-teal-2048-gray205.png` | 🗑 已删 | 生成输入；再生：`python task/006-poly-multiview-tpose/scripts/prep_input.py` |
| `output/step1-no-tail-horn.png` + `output/step1-no-tail-no-horn/` | 🗑 已删 | 第 1 次生成：去尾巴 + 去角（`job_241ec5ac82e24fbc85c3ca549b70ac18`） |
| `output/sheet-4views-tpose.png` + `output/step2-multiview-tpose/` | 🗑 已删 | 第 2 次生成：带服装的四方向 T-pose 拼图（`job_8dde5ef570e74fe7ab37cd8787bd6f0b`） |
| `output/views/{front,left,right,back}.png` | 🗑 已删 | 第 2 次拼图切出的 4 张（带服装版，912×993） |
| `output/base-model/poly-base-model-bald-underwear.png` | 🗑 已删 | 第 3 次生成：光头 + 无角无尾 + 白色内衣（`job_08e40c54a00c4d18813a1afea2d78ec6`） |
| `output/base-model-human-ears/poly-base-model-human-ears.png` | 🗑 已删 | 第 4 次生成：精灵耳 → 人类耳（`job_055d63879ac04e53a4dbd3519f509909`） |
| `output/base-model-tpose-3view/`（含 sheet） | 🗑 已删 | 第 5 次生成：三视图（侧面为横臂画法，已被 v2 取代）（`job_3e06c1cf0cfb4756951bd1526646a7e0`） |
| `output/base-model-tpose-4view-v2/`（含 sheet） | 🗑 已删 | 第 6 次生成：四视图 v2（含 v3 的镜像源 `three_quarter.png`，需要时用 `job_a8e852ede4864eb7a87b9b119903b465` 免费重下）（`job_a8e852ed…`） |

## 步骤

1. 建任务目录；原图合成灰底 205 → resize 2048×2048（`scripts/prep_input.py`）。
2. 第 1 次生成 `image-2.5-run`（参考图 = 2048 输入）：**去掉尾巴和角**，其余全不动。记 `job_id`。
3. 人工/读图验收第 1 次结果（A1）；不满意用 `image-2.5-poll --job-id` 恢复，**不重复提交**。
4. 第 2 次生成 `image-2.5-run`（参考图 = 第 1 次结果）：**一张 2×2 拼图**，左上=前、右上=左、
   左下=右、右下=后，四视图同一角色同服装同配色、统一 **T 字站位**、纯灰底。记 `job_id`。
5. 验收第 2 次结果（A2/A3）；按 2×2 切图 → `output/views/{front,left,right,back}.png`。
6. 逐张验收（A4/A5），回写 TASK.md 与 `task/README.md` 台账，决策与 job_id 记 `notes/`。

## 决策与笔记

- 2026-10-11（用户拍板）：**四方向 = 前 / 左 / 右 / 后**（对齐用户贴的 Meowa 多视图模型四个槽位
  前 / 左侧 / 右侧 / 后）；产物**新建 006 任务目录**（符合「一个子任务一个文件夹」入库约定）。
- 2026-10-11（用户口径）：模型用 **gpt-image-2.5** → CLI `image-2.5-run`；**总共只生成两次**
  （① 去尾巴和角 ② 四方向 T-pose 拼图），不是四次独立生成 —— 用**一张拼图**保证四视图一致性。
- 2026-10-11：输入按 `meowa/README.md` 硬约定**合成纯灰底 205**。原图透明底且透明区 RGB 为黑，
  不合成的话模型会读到黑底。
- 2026-10-11：生成一律 **2K / 1:1**；失败自动全额退费，**先记 `job_id`**，中断用
  `image-2.5-poll --job-id <id>` 免费恢复下载，**绝不重复提交**。
- 2026-10-11（实测，切割踩坑）：模型在拼图上**顺手画了 2×2 分隔线**，会被当成前景把每格 bbox 撑满整格。
  剔除竖线**不能全图扫** —— 上下两格人物竖向对齐，躯干所在列在上下两格里都是前景，全图扫会把它
  当竖线剔掉、人物身上留缝；改为**只在中线 ±32px 内扫**才正确。
- 2026-10-11（口径）：四张单图**裁同一个窗口**（四格 bbox 并集 + 外扩，窗口四边再内缩 3px 挡分隔线），
  所以四张尺寸一致、人物同比例 —— 转身图**不能各自贴边裁**。
- 2026-10-11（已知偏差，未修）：左/右视图基本互为镜像（多视图模型固有行为）；侧视图手臂是横向平举的
  简化画法；发型比原图简化；背景是模型自出的灰 ≈165（不是输入的 205）。细节见 `notes/2026-10-11-生成记录.md`。
- 2026-10-11（环境备注）：`tmp/` 里留有**上一轮**同名编号的中间产物（`tmp/006-*`，脚本里引用的
  `task/006-poly-tpose-rig/` 现已不存在）；若那个任务还要恢复，本目录编号可能撞车，届时可改号。
- 2026-10-12（用户追加口径）：**人物基础模型**单张 —— 用 `005/refs/poly` 做底，**光头**（发型全去）、
  无角无尾、**只留内衣**；`assets/eva_bone/assembled_bikini_white.png` 只当「基础模型长什么样」的参考，
  **不是**身份来源。执行：参考图 = 本任务 step1（身份）+ Eva 基础模型图（内衣/站姿），
  `job_08e40c54a00c4d18813a1afea2d78ec6`（14 积分）。落 `output/base-model/`。
  偏差：脸比原图柔和/圆一点（受参考图 2 影响），需要更贴原图可去掉参考图 2 重跑。
  ⚠ 本目录 slug 仍是 `multiview-tpose`，现已含「基础模型」产出；若要把基础模型独立成任务（007）说一声即可拆。
- 2026-10-12（用户追加口径）：基础模型**耳朵改人类耳**（原为尖精灵耳）。执行：`image-edit-run`（万能编辑，
  只改一处更稳）`--mode hd --generation-model image-2.5 --resolution 2K --quality detailed`，
  参考图 = 上一版基础模型，`job_055d63879ac04e53a4dbd3519f509909`（12 积分）。落 `output/base-model-human-ears/`。
  头部放大 2× 复核：两耳圆润带耳垂、无尖角，其余全保持。
  ⚠ 记一笔：`image-edit-run` 回执是 `job_type=workflow`、产物名 `edited.png`、**没有 `credit_cost` 字段**，
  积分只能按余额差核算。
- 2026-10-12（用户追加口径）：**T-pose 三视图**（正面 / 侧面朝右 / 背面，按 `meowa/README.md` 的三视图口径）。
  仍走「一张 2×2 拼图 → 切割」（一次生成 12 积分、同图内比例必然对齐），提示词显式要求**右下格留空**
  （模型遵守）；`job_3e06c1cf0cfb4756951bd1526646a7e0`。切割用新增的 `--map front=tl,side=tr,back=bl`。
  成品 948×1018，顶部对齐差 ≤1px、高度差 ≤6px。偏差同前：侧视图手臂仍是横向平举画法。
- 2026-10-12（用户追加口径，**现行版**）：**四视图 v2** —— 侧面改**真正交侧视、双臂只留肩部短桩**，
  并补一张 **2/3 斜视**（身体朝右转约 45°）；方向组合经用户确认 = 正面 / 纯侧面(短桩) / 2/3 斜视 / 背面。
  `job_a8e852ede4864eb7a87b9b119903b465`（12 积分）。切割 `--map front=tl,side=tr,three_quarter=bl,back=br`，
  成品 977×1015，四张顶部对齐完全一致（back 矮约 1%）。
  ⚠ 第 5 次三视图的侧面是「横臂」画法，**已被本版取代**；要三视图直接用本版 front/side/back。
- 2026-10-12（用户追加口径，**现行交付集**）：留桩版**用户判定效果不好** → 弃用纯侧面，
  **左侧视图改用 2/3 斜视的水平镜像**、右侧保留原 2/3；正/背面照旧。
  落 `output/base-model-tpose-4view-v3/views/`（front/left/right/back，四张同 977×1015），
  **本次零生成、零额度**，镜像用新增的 `scripts/mirror_view.py`。
  ⚠ 命名口径：`left` = **2/3 镜像**（不是纯侧面）；镜像会翻转左右不对称细节，本角色对称无影响。
  ⚠ v2 的 `side.png`（纯侧面短桩）**保留未删**（用户未说删），只是不再作为交付视图。
- 2026-10-12（**清理，用户确认后执行**）：用户口径「保留 v3，清理其他的临时人物」。
  按工作区删除规则**先列清单（路径+体积+理由）→ 用户勾选确认 → 才删**，删除前跑干跑校验
  「所有待删绝对路径必须落在 `task/006-poly-multiview-tpose\` 或 `tmp\` 内」（越界项 0）后执行。
  - **删 80 项**：006 内除 v3 外的 9 项中间人物版本 + `input/` 的 2048 灰底输入（10 项 / 24.05 MB）；
    `tmp/` 里 `006|slot-split|parts-|poly-v5-teal-2048|reskin|orig-zip|v[0-9]-|mark-|dbg|zoom` 命中的
    70 项 / 52.77 MB（含**上一轮工作流**的 slot-split v1–v8、parts-raw、006-render/remake/ruler、
    mark-crop、zoom 等，用户已知悉风险并勾选）。
  - **保留**：`output/base-model-tpose-4view-v3/`（现行交付集）+ `TASK.md` + `notes/` + `scripts/`。
  - 可再生性：所有 job_id 留在本档案与 `notes/`；输入由 `prep_input.py` 再生；v3 的镜像源可由
    `job_a8e852ede4864eb7a87b9b119903b465` 免费重下后再跑 `mirror_view.py`。
  - `tmp/` 仍余 14 项**不在清单内**的小文件（`ambiguous-parts.png`、`sheet-numbered.png`、`slot-ref-18.png`
    与 11 个 `.py` 小工具），**未删**（不在用户确认的范围内）。
