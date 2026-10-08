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
      `spine_flip_bake` 闸门 **G1 残差 0.0 / G2 setup 3.55e-13 / G3 违规 0** 全过
      （报告 `step1-flip-report.jsonl` 已归档于 git 历史，见产出表注）。
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
6. `scripts/rename_bones.py` 执行重命名 → `/output/Unit_Spine_EmpirePaladinSpe1Skin1.json`（028 重组后终稿直出），跑完整性/等价性校验。
7. 回写 TASK.md 与台账。

## 产出（2026-09-28 用户确认后重组为**单一最终包**）

| 路径 | 说明 |
|------|------|
| `output/` | **最终交付包**（下一步换装任务直接以此为包目录）：朝右 + 44 英文骨名三件套 `Unit_Spine_EmpirePaladinSpe1Skin1.{json,atlas,png}` + `images_original/`（32 张单图）+ `交付说明.md`（含 005 差异说明）+ `复原预览图.png` + 原始资源回退 zip |
| `output/rename-map.json` | 44 骨重命名映射与识别依据（evidence） |
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
- 2026-10-02（用户拍板）：**三类命名统一**（骨骼/插槽/附件图）——侧别不用缩写且放类型前
  （`arm_l_upper→arm_upper_left_bone`）、骨骼 `_bone` / 插槽 `_slot` 结尾、多级骨 `_1.._N`
  结尾（`tail_bone_1..7`）；槽名与所挂骨语义对齐（`Lhand2→arm_upper_left_slot`、
  `Rtui3→leg_shin_left_slot_2`、`leg_l_shin.png→leg_shin_left_slot`）；附件=图集区域=
  图片名同步（`no/by/attack→face_open/face_blink/face_attack`、`wb→tail`、
  `L/Rhand→hand_left/right`）。JSON+atlas+12 张图联动，几何/图集像素/绘制顺序不动；
  自检（映射完备/引用全效/区域双射/零残留/槽序不变）全过，渲染 setup 帧
  改名前后逐像素一致。完整映射表与校验记录见
  [`notes/2026-10-02-命名统一.md`](notes/2026-10-02-命名统一.md)；
  执行脚本 `scripts/unify_names.py`。
  **⚠ `output/*.spine` 工程未回灌（仍旧名），再从工程导出会覆盖本次命名。**
- 2026-10-02（**回滚记录**）：曾按「重建骨骼 rest pose + 烘焙贴图」的彻底方案改过 output/
  （`scripts/conjugate_bake.py`，骨骼旋转归零 + 附件 rot=0/scale=1 + 贴图重烘 + 图集重打包），
  G1–G3 数学闸门虽过，但 G4 整机渲染暴露出**镜像框架**缺陷（hip 的 scaleX=-1 被表示为
  shearY=-180 的镜像框架 → 已烘成正立的贴图穿过该框架被二次镜像，25% 像素损伤）。
  用户随后拍板：**骨骼 rest pose 不改，改附件与骨骼的相对旋转（附件去适配骨骼）**。
  已完整回滚并验证：
  - JSON 与用户提供的回滚目标逐项一致（29/29 检查项通过：骨旋转、附件 rotation/scale、
    mesh 顶点数据齐全）；
  - 25 张单图从 git HEAD（LFS）取回并按当前命名落位，尺寸与 JSON 声明逐项吻合；
  - 打包页图按图集 bounds 重拼，`pipelines.py verify` 回环 **25/25 一致，RGB/alpha 最大差 0**；
  - 整机渲染与回滚前基准 `notes/preview-setup-pose.png` **逐像素 0 差**。
  两个烘焙脚本已标注「已废弃」仅作存档；后续按「附件侧规范化」方案推进（见下条）。
- 2026-10-02（换肤前置）：`scripts/slot_sheet.py` 升级为可复用 CLI（换肤组件图）——
  默认 `--sort bone`：**不分组、紧凑网格**；排序键=骨骼 setup 世界 y（10px 桶，从高到低
  = 从头到脚，复用 `render_rig.compute_world` 同一套数学）> 层级深度（顶层/父骨先于子骨）
  > bones[] 序 > 槽名相似度（去 left/right 侧别的部件基名，左右件成对相邻、left 在前；
  2026-10-02 用户口径：ear_left/ear_right 不再被 slots 序拆开）> slots[] 序；
  每格完整标注骨名+槽名（多附件槽追加附件名），
  全名不省略（喂大模型读图）；无附件空槽不出格；可选 `--sort slot|size`；
  补 Windows 字体路径。
  **尺寸/姿态口径（对齐 preview-setup-pose，除全局缩放外 1:1 复刻）**：
  每格=附件在 setup pose 的**装配姿态**——骨世界旋转 + 附件 x/y/rotation/scaleX/scaleY
  完整叠加（region=四角四边形 2 三角投影；mesh=蒙皮顶点按 JSON triangles 逐三角形
  投影），展示尺寸=世界 bbox，全图共用全局缩放 → 任意两格相对大小与朝向
  =预览图真实比例。region 不再贴原始 PNG 方向（face 三态带 -91° 附件旋转，
  原图方向与装配方向差 90°，用户指正后改装配姿态口径）。
  ⚠ 世界矩阵必须用 Spine 官方双轴公式（x 轴角=rotation+shearX、y 轴角=
  rotation+90+shearY、各自乘 scale）——本包 hip 带 scaleX=-1 镜像域，
  用 R·diag 展开 b/c 分量会错位 → 蒙皮形状整体上下翻转（踩过）。
  改名后总览图 `notes/slot-sheet-renamed.png`
  （25 格 / 5×5 / 1800×1820：face 三态→head 11 件→双臂→上身→大腿→下装→尾→小腿）。
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
- 2026-09-29（用户拍板）：**分区名通用化修订**——`chest→upper_body`（上半身）、
  `skirt_root→lower_body`（下身），连带 `chest_upper→chest`
  （承接 chest 位，避免与 upper_body 语义重叠；`hip → upper_body → chest → head`
  即标准 Spine 人形链）。执行方式：从 git 历史（`63dab65`）恢复原始 4.3.26 包
  → flip → rename 全链路重跑（翻转 G1/G2/G3 与重命名自检再次全过）；
  等价性实证：旧终稿做 3 名替换后与新终稿**字节级一致**、渲染 pose 逐像素一致。
  换装分区挂点即 `upper_body`（上半身）/ `lower_body`（下身）。
- 2026-09-30（用户确认）：`output/` 两份过程报告删除，闸门数值已录本档案
  （Step1：G1 残差 0.0 / G2 setup 3.55e-13 / root 动画 4.33e+01 信息级 / G3 违规 0；
  Step2：44 骨改名、A2 零残留 / A3 动画等价 / problems 空）。
  再生：重跑 `spine_flip_bake.py --report <文件>` 与 `rename_bones.py` 自检即可。
- 2026-09-30（用户重建 .spine 工程）：用户在 Spine 4.3.26 编辑器内把终稿逆向重建为
  `output/*.spine` 工程文件，验证 CLI 导出链路（`--update 4.3.26` + `--export json+pack`）
  **一次通过**：三件套结构、44 英文骨名（含 09-29 分区）、10 动画、渲染逐像素与终稿一致；
  新自动 pack 图集更紧凑（1477×271 vs 2048×300）。**⚠ 排雷：CLI 必须带 `--update <版本>`，
  否则旧版 launcher 丢 `json+pack` 快捷值报 "Output specified without an input or action"。**
  完整命令、产物验证表、后续口径见 [`notes/2026-09-30-CLI导出验证.md`](notes/2026-09-30-CLI导出验证.md)。
- 2026-09-30（用户拍板）：**CLI 导出三件套覆盖 `output/` 交付版**——`.spine` 工程为
  唯一权威源，交付物由 `--export json+pack` 直出。覆盖校验全过：骨名/动画/槽位全等、
  渲染 pose 逐像素 diff=None、图集区域集合一致（自动 pack 更紧凑 1477×271）、
  hash 更新 `n/JcyJmkJwY`。旧手工三件套保留于 git `003a241` 可回退。
  此后换装流程：编辑器改 `.spine` → CLI 重出三件套（不再手工拼图集）。
- 2026-10-02（用户拍板，agent 执行）：**镜像域上移 `hip_bone` → `root_bone`**。
  翻转烘焙当年把 `scaleX=-1` 挂在 root 直接子骨（hip）上，坑：①贴图先烘正立再穿过
  镜像框架=二次镜像（conjugate_bake 25% 像素损伤事故）②旋转过镜像域变号，角度
  不能直接相加 ③隐形域难发现 ④新画皮肤件不补偿会左右反。改法（严格共轭等价，
  渲染不变）：`root_bone` 加 `scaleX=-1`；`hip_bone` 局部变换取共轭 `L'=S∘L`
  （`x: 2.735203→-2.735203`、`rotation: 0.1010933→-0.1010933`、`scaleX` 删除），
  其余全部不动。闸门全过：①除 root 外 33 骨世界矩阵最大差 1.1e-16（root=
  原矩阵∘diag(-1,1) 严格成立）②render_rig setup 渲染逐像素 0 差 ③slot_sheet
  逐像素 0 差（独立数学路径双验证）。**口径变更：镜像判断一律逐骨查 scale 正负，
  不写死骨名**（分析脚本 `tmp/005-render/inspect_orientation_matrix.py` 已改为
  自动检测全部负 scale 骨）；`slot_sheet.py`/`render_rig.py` 注释同步。
  ⚠ `.spine` 工程未回灌（仍旧名 + hip 镜像），从工程重导出会丢本修改。
  同日第二步：**`tools/spine/anim/spine_flip_bake.py` 重构为 v2（镜像挂 root）**——
  翻转域子骨改纯旋转共轭 M=Fx·A_r⁻¹·Fx·A_r（只动 x/y/rotation，shear/scale 不动），
  动画只动 translate 通道；root 零旋转特例=整个烘焙只加 root scaleX=-1。
  G1/G2/G3 全过；回归：005 基座（G2 3.13e-13）+ 3 个复杂已交付包 dry-run + 新旧产物
  175 采样点 A/B 世界矩阵差 1.7e-13。记录见
  [`../003-spine-facing-unify/notes/2026-10-02-翻转烘焙v2镜像上移root.md`](../003-spine-facing-unify/notes/2026-10-02-翻转烘焙v2镜像上移root.md)。
