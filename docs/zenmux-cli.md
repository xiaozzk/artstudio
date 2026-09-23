# ZenMux 图片编辑 CLI 指南

> 本文是 `AGENTS.md` 里「ZenMux 图片编辑 CLI」一节的展开版：**什么场景用 + 怎么跑 + 实测硬规则**。
> 参数表、家族兼容全表、mask 上限调研、体积限制、错误码表见 `tools/zenmux-edit.md`（**完整口径**）。
> 路径相对工作区根；key 一律写进 `.env`，**不要贴进对话**。

## 场景

在素材图上**标记若干部位，只重绘这些部位** —— 换一把武器 / 换一件衣服 / 改配色材质。

**这是 `tools/` 里唯一会花钱的脚本**，其余本地脚本都是确定性、免费的（清单见 `tools/README.md`）。
出**原画**（角色设定图 / 三视图 / 设计稿）用 Meowa，不用这里 —— 见 `docs/meowa-cli.md`。

## 命令

`python tools/zenmux_edit.py <check|balance|cost|generation|edit>`，**一律在工作区根下执行**（读根目录 `.env`）。

## 协议（2026-09-23 起默认 Vertex AI）

- **默认 `--protocol vertex`**：`POST https://zenmux.ai/api/vertex-ai/v1/publishers/{provider}/models/{model}:predict`
  —— 统一生图端点，**模型面最宽**（openai / 腾讯混元 / 通义 / Flux / Kling / Imagen）。
  文生图 = `instances[0].prompt`；编辑 = `instances[0].referenceImages`
  （`REFERENCE_TYPE_RAW` 原图 + 可选 `REFERENCE_TYPE_MASK`，`maskMode=MASK_MODE_USER_PROVIDED`），
  **mask 语义与 OpenAI 相同：透明 = 编辑区**。
  响应 `predictions[]`：Google 系回 `bytesBase64Encoded`，**腾讯系回 `gcsUri`（COS 签名 URL，工具自动下载）**。
  `--protocol openai` 回旧 `/v1/images/edits`（SSE / multipart / `background` 只有旧协议支持）。
- **家族兼容**（请求参数按模型家族分发，源码 `FAMILIES`）：

  | 家族 | 尺寸 | 质量 | n 上限 | 备注 |
  |------|------|------|--------|------|
  | `openai/gpt-image-*` | 顶层 `imageSize` | 顶层 `quality` | 10 | |
  | `tencent/hy-image-*` | `parameters.aspectRatio`（`--size` 自动折算，如 1536x1024→3:2） | 无分档（不发） | **1** | `--enhance-prompt` ✅；`--negative-prompt`/`--sample-image-size` 未证实，被 400 就去掉 |

- **新模型实例**：`tencent/hy-image-v3.0`（混元图像 3.0）**已真机验证可用**（2026-09-23）——
  但它**还没进 ZenMux 目录**（`/models` 不显示也能跑），`check` 对 vertex 的目录外模型只 warn 不拦。
- ⚠ **vertex 不支持 `background`**（官方映射表标 ❌）：透明件走"**纯色底** + `tools/flatbg_cut.py` 本地抠底"——
  工具已把这条路做成默认：**`--solid-bg` 默认开（`#FF00FF`）**，会自动往 prompt 追加"完全均匀纯色底"指令
  （hy 系用中文指令），出图后 `flatbg_cut.py --bg-color '#FF00FF'` 抠掉即可；
  带 `--mask` 的原位编辑不注入（要保留原背景），整图编辑要保留原背景加 `--no-solid-bg`。
  不支持 SSE / multipart / `--image-url`，一律单次 POST + JSON 内嵌 base64。

  举例：`python tools/zenmux_edit.py edit --model tencent/hy-image-v3.0 -i a.png --mask m_weapon.png --prompt "把剑换成..." --min-credits 1`

## 自检 / 查余额 / 查账单（都免费）

| 命令 | 用途 |
|------|------|
| `python tools/zenmux_edit.py check` | key、模型是否在架、mask 覆盖面积、当前 PAYG 余额 |
| `python tools/zenmux_edit.py balance [--json]` | 只查余额 |
| `python tools/zenmux_edit.py cost [--models M] [--dimension BIZ_MTH\|BIZ_DT\|BIZ_HOUR] [--time T]` | 查账单 |
| `python tools/zenmux_edit.py generation --id <generationId>` | 单次调用明细（id 从 Logs 页 Request 搜索框拿） |

## 成本控制（余额接口只认管理型 key）

- `edit --min-credits 1`：开跑前低于 1 USD 就拒跑；跑完打印余额差（≈本次实际花费）。
- 每次运行都会写 `run-summary.json`（余额前后、余额差、各步 token 用量、产物清单）。
- 每次调用都打印 `x-request-id`；**产物旁边有同名 `.json` 边车**便于对账。
- **OpenAI 系单价（2026-09 实测反推）**：`image_output` ≈ **$30/1M tokens**、`image_input` ≈ $8/1M、文字 $5/1M。
  单张：**quality=low（默认）≈ $0.01~0.02**（估）、`medium` ≈ $0.04~0.05（估）、**`high` = $0.15~0.18（账单实测）**。
  **hy 系单价未实测** —— 跑完 `cost --models tencent/hy-image-v3.0` 核账。
  （算法与实测样本见 `tools/zenmux-edit.md` 的「单张图成本」。）
- ⚠ **被网关掐断的请求照样计费**（OpenAI 协议实测一轮 7 次全计费 $1.2009，只有 2 次拿到图）：
  **工具没有任何自动重试**，失败就停下用 `cost` 核账，人工决定要不要重跑。

## 硬规则 / 实测经验

1. **一次请求只能带 1 个 mask**（两种协议都如此，且只作用于第一张输入图）。
   多区域由工具消化：`union`（并成 1 张，1 次调用）/ `sequential`（逐块改并串起来，N 次调用，
   「A 换武器 + B 换衣服」用这个）/ `separate`（N 个候选）。
2. **mask 语义：透明（alpha=0）= 要重绘**。默认 `--mask-polarity marked`（涂白=要改），
   自动翻成协议需要的透明洞；PS 存成「alpha 全 255 + 黑白亮度」也能正确识别。
3. **先 `--dry-run` 再花钱**：免费出 mask 预览 + 调用计划（含家族参数分发结果）；加 `--dump-request`
   落盘请求体。覆盖 0% 报错，>95% 告警（polarity 反了）。
4. **默认值**：`png` / `n=1` / `quality=low` / `size=1024x1024` / 模型 **`openai/gpt-image-2`**
   （2026-09-23 起**不再对接 `openai/gpt-image-2.5-sunburst`**）/ **`--solid-bg` 默认开**（纯色底 `#FF00FF`，
   自动追加到 prompt；`--no-solid-bg` 关）/ `--background` 在 openai 协议下默认 **`opaque`**
   （不再默认 `transparent`——实测会被网关掐断）。透明件 = 纯色底出图 + 本地抠底。
5. **mask 不是硬边界**（OpenAI 协议实测 mask 覆盖 2.91% 时，mask 外 30.6% 像素被重画）：
   换单个部位用 `apply` 思路只把 mask 内改动贴回原图；换皮 / 新组件走
   **部件单独重画**流程：输入 = 原部件放大 + 风格参考，prompt 要单体 / 纯色底 / 保持轮廓朝向与画布位置，
   抠底得 alpha → 按"原部件 alpha maxXY ↔ 新件 alpha maxXY"等比缩放 → 放回原附件画布 → 换回 Spine 重渲验证。
6. **没有任何自动重试**：实测被掐断 / 超时 / 5xx 的请求**照样计费**，所以失败就停下 ——
   用 `cost` 核账后人工决定。每次调用都记 `requests.jsonl`（含 `request_id` / usage / 输入 sha256 / 产物）
   与 `_responses/response*.json`（b64 折叠），跟后台 Logs 页对账用得上。
7. 中间产物落 `tmp/zenmux-edit/<时间戳>/`（见 `AGENTS.md` 的中间产物规则）；**产物要删先问用户**。

## 相关文档

| 文档 | 内容 |
|------|------|
| `tools/zenmux-edit.md` | **完整口径**：依赖与凭据、默认值全表、成本拆解、家族兼容全表、mask 调研、体积限制、排错表、真机实战记录（权威） |
| `tools/README.md` | 本地脚本清单与通用经验 |
| `docs/meowa-cli.md` | 出原画（整张参考图）走 Meowa |
