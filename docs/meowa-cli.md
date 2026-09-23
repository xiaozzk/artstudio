# Meowa 生图 CLI 指南

> 本文是 `AGENTS.md` 里「Meowa 生图 CLI」一节的展开版：**什么场景用 + 怎么跑 + 实测硬规则**。
> 安装、认证、每个子命令的完整参数由 skill 自带文档负责（见文末「相关文档」）。
> 路径相对工作区根；key 一律写进 `.env`，**不要贴进对话**。

## 场景

**出原画** —— 角色设定图 / 三视图、服装设计稿、配色与材质设定。
产出是**整张参考图**；要拆件、抠底、缩放、拼回画布，接着走 `tools/` 的本地脚本（清单见 `tools/README.md`）。

**要改已有素材的局部**（换一把武器 / 换一件衣服 / 改材质）用 ZenMux，不用这里 —— 见 `docs/zenmux-cli.md`。

本工作区对素材另有硬约定（生成一律 2K / 输入须合成纯灰底 205 / 输出透明 RGBA / 垂直锚点偏差 ≤2px）：`meowa/README.md`。

## 命令与执行位置

- 命令：`python ~/.agents/skills/game-assets/meowart_api.py <子命令>`
- **一律在工作区根下执行** —— runner 从**执行命令的当前目录**读 `.env`，换目录就读不到 key。
- 校验连通 / 余额：`... meowart_api.py credits-balance`（能返回余额即配置成功）；
  `... free-credits` 查免费额度资格并拿积分中心链接。
- **`.env` 按 latin-1 解析 → 禁止中文注释**，写了会直接解码报错。
- key 名是 `MEOWART_API_KEY`（`ma_live_...`），放工作区根 `.env`（已被 `.gitignore` 忽略）；
  runner 不接受命令行凭据参数，值只写 key 本身、不要加 `Bearer` 之类前缀。

## 常用子命令（摘录，权威口径见 skill 文档）

| 子命令 | 用途 / 关键默认值 |
|--------|-------------------|
| `image-2.5-run --prompt "..."` | 通用生成（Image 2.5 Sunburst）；`--quality standard`，质量档 `standard/detailed/ultimate`（= canonical `low/medium/high`）；`--resolution 1K/2K` 默认 1K；`--aspect-ratio` 默认 1:1（1:1 / 3:4 / 4:3 / 9:16 / 16:9）；可重复 `--reference-image` |
| `image-edit-run` | 万能编辑；`--generation-model image-2.5` 时参数与 `image-2` 相同 |
| `game-design-run` | 策划文档任务（`game_design_outputs.json` + `design_docs/`），按实际 token 实时扣费 |
| `map-reference-search` / `map-reference-download` | 地图参考检索，未认证也能用 |
| `*-poll --job-id <id>` | **恢复原任务**（`image-2.5-poll` / `image-2-poll` / `nano-banana-poll`）；只轮询，不重新提交、不再扣费 |

积分（服务端结算）：Image 2.5 基础积分 1K = 1/5/10、2K = 2/10/20（对应普通 / 精细 / 极致），每张参考图另加 2；
Image 2.5 去背景免费，只提供普通抠图，失败则不去背景、不扣附加费。

## prompt 硬规则

- **单行、且不含任何引号字符** —— PowerShell 会把双引号当分隔符。
- 用**无引号结构化约束**代替引号，例如
  `Constraints: canvas = ...; edit = [...]; must_not_change = [...]`。
- 给**整图**并说明上下文；显式禁止模型"顺手改结构"。

## 参数限制

- `--strict` 只在 `--mode pixel` 可用。
- HD 编辑去背只支持 `none` / `standard`。
- Image 2.5 的 `--remove-bg-method` 默认 `none`（与网页去背景开关一致）。

## 产物纪律

- 每次生成**先记 `job_id`**；`--output-dir` 必须**互不相同**。
- 失败自动全额退费，**不要重复提交**。
- 误删可用**对应的** `*-poll --job-id <id>` **免费**重新下载。
- 只交付任务目录中的最终媒体与 `final_outputs.json`。

## 三视图要点

prompt 里必须显式要求**同一角色的致外观**（同服装 / 同配色 / 同发型），
否则正 / 侧 / 背之间比例会变，对不上。

## 更新 CLI

- 走 **codeload tar.gz**（`git clone` 常被重置），**整目录覆盖**两个安装点：
  `~/.agents/skills/game-assets` 与 `.claude/skills/game-assets`。
- 不能只换 `SKILL.md` 或 `meowart_api.py`；更新后用顶层 `--help` 看可用的 `*-poll` 恢复命令，
  再用原 `job_id` 恢复下载（**不要重新提交已扣费的任务**）。

## 相关文档

| 文档 | 内容 |
|------|------|
| `~/.agents/skills/game-assets/meowart_api.md` | 安装、更新、Meowa key 创建、`.env` 配法、各命令参数与积分（**权威口径**） |
| `~/.agents/skills/game-assets/SKILL.md` | 美术能力模块与工作流协作方式 |
| `meowa/README.md` | 本工作区素材硬约定（2K / 纯灰底 205 / 透明 RGBA / 锚点 ≤2px） |
| `meowa/templates/preset-overview.md` | Meowa 预设契约清单 |
| `docs/zenmux-cli.md` | 改图（mask 局部重绘）走 ZenMux |
