# Spine 工作区

本工作区（`D:\spine`）专用于 **Spine** —— 二维骨骼动画运行时与工具链。

## 语言

默认工作语言：**中文 (Chinese)**。文档、注释、与 Claude 的对话均优先使用中文；技术名词、文件名、API、标识符保留英文原文。

## Target Engine — Godot (强约束)

所有 Spine 资产、动画、皮肤、运行时方案 **必须适配 Godot 4** 引擎。具体约束：

| 项目 | 约束 |
|------|------|
| 运行时 | `spine-godot` 官方运行时（4.3，对应 Spine 编辑器 4.3.x） |
| 导出格式 | **JSON 格式**（`.json` + `.atlas`），不要用二进制 `.skel`，便于 Godot 导入与版本 diff |
| 节点 | Godot 中通过 `SpineSprite` 节点加载，GDScript 或 C# 调用 API |
| 版本兼容 | Spine 编辑器 4.3.x ↔ spine-godot 4.3（官方适配 Spine 4.3.xx 导出的数据）↔ Godot ≥ 4.3 |
| 资源组织 | Godot 项目的 `res://spine/` 目录下；纹理走 `.import` 管线 |
| 动画状态 | 使用 `AnimationState` 的 `TrackEntry` 做混合/过渡 |
| 皮肤切换 | `Skeleton.set_skin(name)` / `add_skin()` |
| 异化扩展 | 通过 **基础骨骼 + 换皮 + 子模板派生** 实现（换装 / 捏脸部件的规范见 `docs/head_split_spec.md`） |

任何方案讨论、模板生成、代码示例，默认面向 Godot 适配；如无特别说明，禁止产出仅适用于 libgdx/Unity/Phaser 的方案。

## 目录结构

- `reference/` — Spine 参考资料（**不入库**；用脚本按 pinned commit 稀疏拉取）
  - `spine-runtimes-4.3/` — 官方 `EsotericSoftware/spine-runtimes`（branch 4.3，pin `f182572b` / 2026-09-14，即当前最新已发布版本）。完整克隆 286 MB，本项目只用 `spine-godot` + `spine-cpp`；`pwsh tools/fetch-spine-runtimes.ps1` 拉到约 41 MB（含 .git），内容与完整克隆等价。
    ⚠️ 本机直连 `github.com` 的 git 传输不稳（HTTP/2 与 blob 按需拉取常被 Connection reset）→ 脚本强制 `http.version=HTTP/1.1`，失败时自动回退镜像（`ghfast.top` / `ghproxy.net`；git 以 SHA-1 校验对象，镜像无法篡改内容）
- `docs/` — 设计文档与实测记录
  - `character_proportions.md` — 角色比例与部件尺寸（直接读 `assembled.psd` 图层 `bounds` 实测，非目测）
  - `head_split_spec.md` — 头部拆件 Spec（捏脸系统的可替换组件：`pivot` / `mirror` / `z` 序）
  - `head_split_record.md` — 头部拆分记录（hair / head / eye / mouth / eyebrow 五件）
- `assets/` — Eva 原型资源（后续按设计落地）
- `.claude/` — Claude Code 项目配置与记忆
- `.git/` — 版本控制
- `meowa/` — **AI 生图工作区**：Eva 基础体的生成素材、参考图与工作记录。
  - `input/` 原始素材、`refs/` 参考图、`templates/` Meowa 预设信息
  - `split_base_skin/` 拆件工作区：成品拼图、评估报告、各轮 prompt、`base_ref/`（job_id 与几何存档）
  - 文档：`SUMMARY.md` 沉淀总览 / `README.md` 工作区说明 / `JOINT_REFINE_NOTES.md` 当前路线经验与 prompt / `PIPELINE_NOTES.md` 旧方案链路
  - 约定：生成一律 2K、**输入须合成纯灰底 205 保证不透明**、输出透明 RGBA、垂直锚点偏差 ≤ 2px
- `tools/` — **本地脚本工具**（纯本地，不消耗 AI 额度）
  - `spine_joint_tool.py` — 关节边缘精修一体化工具（见下）
  - `dressup-lab/` — **换装定位台**（浏览器版，零 npm 依赖）：部位锚点 + 部件装配 + 导出 Spine 图集/锚点；单入口自检 `scripts/verify.mjs`（13 组 / 104 项子检查，基准项目 `human_female`）。跑法：`node tools/dressup-lab/server.mjs`
  - `ps_cut/fill_from_layer1.jsx` — PS 内一键补缺口（文件 > 脚本 > 浏览）
  - `fetch-spine-runtimes.ps1` — 按 pinned commit 稀疏拉取官方 Spine 运行时（只取 spine-godot + spine-cpp）；直连失败自动回退镜像
- `tmp/` — **临时目录**：所有 deep research（深度研究）、全网搜索、爬取产生的临时文件与下载产物均放此目录。**不纳入版本控制，可随时清理**。

## 工具 — `tools/spine_joint_tool.py`

关节边缘精修的**唯一入口**（2026-09-14 由 26 + 24 个一次性脚本合并而来，输出经逐像素比对与原脚本一致）：

| 子命令 | 作用 |
|---|---|
| `analyze` | 量用户手绘的套索带（两条边界、宽度、端点） |
| `cut` | 确定性椭圆切件（腿/躯干；含"缝隙中线分腿"+"避开内裤"判据） |
| `prep` | 生成 Meowa 任务输入图（灰底、统一比例） |
| `prompt` | 打印标准 prompt（`--part legs\|arms`） |
| `gen` | 调 Meowa CLI 发任务（默认一次 2 张） |
| `verify` | 对齐候选图并统计"允许区域内外"的改动量 |
| `apply` | 只把允许区域从候选图合成回原图 |
| `report` | 出预览图（原图 / 候选 / 差异） |
| `diff` | 诊断两图差异性质（真改动 / 预乘 alpha / 编码 / 位移） |
| `overview` | 一轮多个候选拼成带标注总览图 |

## Meowa / AI 生图规约

- **凭据**：key 放在工作区根的 **`.env`**（`MEOWART_API_KEY="ma_live_..."`，已被 `.gitignore` 忽略）。
  runner 从**执行命令的当前目录**读取 → 命令一律在 `D:\spine` 下执行；`.env` 用 latin-1 解析，**禁止中文注释**。
  校验：`python ~/.agents/skills/game-assets/meowart_api.py credits-balance`。
- **CLI**：`~/.agents/skills/game-assets/meowart_api.py`（`--version` 查版本）。
  版本落后只警告不阻断；更新走 **codeload tar.gz**（`git clone` 常被连接重置），整目录覆盖两个安装点
  （`.agents/skills/game-assets` 与 `.claude/skills/game-assets`）。
- **prompt 硬规则**（血泪，详见 `meowa/JOINT_REFINE_NOTES.md`）：
  - **必须单行，且不含任何引号字符** —— PowerShell 包装层把双引号当分隔符，参数会被拆成碎片
  - 用**无引号结构化约束**代替 JSON：`Constraints: canvas = ...; edit = [a, b]; must_not_change = [..]; forbidden = [..]`
  - 输入给**整张拼图**并明说"每块是独立图层"；给局部特写 → 模型会把零件**粘成一个整体**
  - 必须显式禁止模型"顺手切分"（例：`each leg is ONE single piece - do not split it at the knee`）
- **参数限制**：`--strict` 只在 `--mode pixel` 可用；HD 编辑去背只支持 `none` / `standard`。
- **产物**：每次生成记 `job_id` 到 `meowa/split_base_skin/base_ref/job_ids.md`；`--output-dir` 必须互不相同。
- **验证**：不要只看"看起来对"。用 `verify` 量区域内外改动量 + 单独量零件包围盒
  （模型实测会平移 10~17px、改宽度 8px）。失败自动全额退费，**不要重复提交**。

## Workflow — 渐进迭代

本项目采用 **MVP → 增强 → 完整** 三层渐进策略：

```
L0 MVP      最小可运行：能站立 + 待机 + 一个攻击
L1 增强     加入装备换装 + 基础表情切换
L2 完整     加入披风动态链 + 完整表情 + 异化扩展接口
L3 扩展     派生变体角色（通过 skin / bone 扩展）
```

每个层级标注 **[必选] / [推荐] / [可选]**，落地时优先保证 [必选] 可运行，再逐步补齐。

## 凭据与权限（已确认，无需再议）

- Meowa API key（`ma_live_...`）保存在本工作区根的 **`.env`**（已被 `.gitignore` 忽略），对接**官方渠道**，不构成泄露风险。
- 在命令中使用 key 是允许的、预期的做法；**不要再提醒轮换或提出安全建议**。
- 但 skill 明确规定**不要要求用户把 key 贴进对话** —— 引导其写入 `.env` 即可（runner 从当前目录读取）。
- 用户已授予最大权限，按此前提协作。

## 删除规则（强约束，2026-09-14 事故后新增）

**只有用户明确通知删除的产物才能删。**

- **禁止**凭自动指标（连通域数、IoU、覆盖率、评分等）自行判定"失败"并删除产物 ——
  自动判据 ≠ 用户需求。曾因此误删用户已认可的 `leg2`（判据说"有合并"，但用户要的正是那个效果）。
- 要清理时**先列清单**（路径 + 体积 + 判断理由），**等用户确认后再删**。
- 用户说"清理临时文件"时，只清**可再生的中间态**（去背图、切件、拼接中间结果、对照图），
  **不动**用户已认可或已指定的产物。
- 生成产物**一律先记 `job_id`** 到 `meowa/split_base_skin/base_ref/job_ids.md`；
  误删后可用 `image-2-poll --job-id <id>` **免费**重新下载，不重复扣费。


