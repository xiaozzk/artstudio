# zenmux_edit.py — ZenMux 图片编辑（Vertex AI 协议默认；mask 局部重绘）

**给素材图标记若干部位，只让模型重绘这些部位**：换一把武器、换一件衣服、改配色 / 材质。

- **默认走 ZenMux 的 Vertex AI 协议**（2026-09-23 起切换）：
  `POST https://zenmux.ai/api/vertex-ai/v1/publishers/{provider}/models/{model}:predict`，
  对应官方 SDK 的 `generate_images`（文生图）/ `edit_image`（图编辑）。
  **支持的模型最多**：openai/gpt-image、腾讯混元、通义万相、Flux、Kling、Imagen 都走这一个端点。
  `--protocol openai` 可回旧路径（`/v1/images/edits`，SSE 流式 / multipart / `background` 参数都在它上面）。
- 默认协议下**请求是 `instances + parameters`**：文生图 = `instances[0].prompt`；
  图编辑 = `instances[0].referenceImages`（`REFERENCE_TYPE_RAW` 原图 + 可选 `REFERENCE_TYPE_MASK`，
  `maskMode=MASK_MODE_USER_PROVIDED`）。**mask 语义不变：透明（alpha=0）= 要重绘**。
- 默认协议下**响应**是 `predictions[]`，两种取图形态都有（工具都处理了）：
  Google 系回 `bytesBase64Encoded`（base64 字节）；**腾讯系回 `gcsUri`（COS 签名 URL）**，工具自动下载。

> 这是 `tools/` 里**唯一会消耗 AI 额度**的脚本（其余都是纯本地、确定性、免费）。
> 想省钱：`balance` → `check` → `--dry-run` 看 mask 预览 → 最后才 `edit --min-credits 1`。

## 依赖与凭据

```
python -m pip install pillow requests
```

在工作区根 `.env` 里加（**不要在对话里贴 key**）：

```
ZENMUX_API_KEY=sk-...                 # 生图/模型接口专用（**必须是普通 key**）
ZENMUX_MANAGEMENT_API_KEY=sk-mg-...   # 可选：只给 balance / --min-credits 用
```

> **两类 key 别混（2026-09 实测）**：`sk-mg-` 开头的是**管理型** key，只能打
> `/management/payg/balance`、`/management/subscription/detail` 这类平台接口；
> 拿它打**模型接口**（`/chat/completions`、`/images/edits`）**一律 403 `access_denied`**
> （消息里带 `api_key_source: payg`）。
> **更坑的是**：`/images/edits` 的 **JSON 通道**在鉴权之前就抛 500，所以用管理型 key 走 JSON 编辑
> 看到的是 `HTTP 500 internal_server_error` 而不是 403 —— 排查时非常容易误判成"服务端故障"。
> 本工具会在 `check` / `edit` 开头检测 `sk-mg-` 并直接告警。

key 在 <https://zenmux.ai/platform> 创建（普通 key）；管理型 key 在
<https://zenmux.ai/platform/management> 创建。
runner 从**执行命令的当前目录**和**工作区根**读 `.env`，工作区根执行就对了。
`--api-key` / 环境变量优先级高于 `.env`。

## 成本控制（PAYG 余额 / 账单）

对应 ZenMux 的三个平台接口（都**免费**，都只认 Management API Key）：

| 命令 | 接口 | 用途 |
|------|------|------|
| `balance [--json]` | `GET /management/payg/balance` | 看还剩多少钱 |
| `cost [--models M] [--dimension …] [--time …]` | `GET /management/cost` | 看花了多少、几次请求（`BIZ_MTH` 按月看天桶 / `BIZ_DT` 按天看小时桶 / `BIZ_HOUR` 按小时看分钟桶） |
| `generation --id <generationId>` | `GET /management/generation?id=` | 单次调用明细（用量/账单）。id 从控制台 **Logs 页的 Request 搜索框**里拿（形如 `2534CCEDTKJR00217635`） |

```powershell
python tools/zenmux_edit.py balance
python tools/zenmux_edit.py cost --models openai/gpt-image-2
python tools/zenmux_edit.py cost --dimension BIZ_DT --time 20260922   # 看那天是几点烧的
python tools/zenmux_edit.py edit ... --min-credits 1
```

- `--min-credits 1`：**开跑前**查一次余额，低于 1 USD 直接拒跑（一个请求都不发）；
  **跑完再查一次**，打印 `余额 10 → 9.8，本次消耗 ≈ 0.2 USD`。
- 每次 `edit` 都会写 `run-summary.json` + **`requests.jsonl`**（每次调用一行：时间、模型、prompt、
  `created`、`request_id`、响应头、usage、输入图 sha256、产物路径）+ `_responses/response*.json`
  （响应体，b64 已折叠）—— 这是跟后台 Logs 页对账的唯一凭据，**失败也会记**。
- `generation --id` 目前只能查"用量/账单"这类元信息；图片本体拿不回来（Images 协议没有取图接口）。

## 单张图成本（怎么算出来的）

图片编辑按 token 计费，**大头是输出图 token（`image_output`）**。从实测 7 次请求的账单反推单价：

| 计费项 | 单价 | 依据 |
|--------|------|------|
| `image_output`（出图） | **≈ $30 / 1M tokens** | 37,457 tokens → $1.12371 |
| `image_input`（输入图） | ≈ $8 / 1M tokens | 9,100 tokens → $0.0728 |
| `prompt`（文字） | $5 / 1M tokens | 与模型目录一致 |

即 `成本 ≈ 出图 token × $30/1M + 输入图 token × $8/1M + 文字 token × $5/1M`。

**实测样本（quality=high）**：

| 输入 | 输出尺寸 | 出图 token | 账单 |
|------|----------|------------|------|
| 3 张图 + mask | 704x960 | 4,496 | **$0.151155** |
| 2 张图 | 784x848 | 5,693 | **$0.179710** |

**各档估算**（`low` / `medium` 按 OpenAI 官方 quality 分档的出图 token 比例 272 : 1056 : 4160
从 high 折算，**尚未打真机验证**）：

| quality | 单张成本 | 说明 |
|---------|----------|------|
| `low`（**当前默认**） | **≈ $0.01~0.02** | 估；此时输入图 token 占比会明显上升 |
| `medium` | ≈ $0.04~0.05 | 估 |
| `high` | **$0.15~0.18** | 账单实测 |

> 省钱的两条路：**降 quality**（high → low 约省 **90%**）、**少放输入图**
> （每张 ≈ +1,000 image_input token ≈ +$0.008）。出图 token 才是大头。
> 真机验证一次 `low` 只要 ≈$0.02，跑完 3~5 分钟用 `cost` 看实际值。

## 快速开始

```powershell
# 1) 自检（不花额度）：key 是否读到、模型是否在架、mask 覆盖是否合理
python tools/zenmux_edit.py check --image assets/eva_bone/parts/hero.png --mask tmp/m_weapon.png

# 2) 免费预演：出 mask 预览图（红=要重绘 / 绿=保留）+ 打印调用计划，不发请求
python tools/zenmux_edit.py edit --image tmp/hero.png --mask tmp/m_weapon.png `
    --prompt "把手里那把剑换成一把发光的短杖" --dry-run --out-dir tmp/zenmux-edit/dry

# 3) 正式编辑（消耗额度）
python tools/zenmux_edit.py edit --image tmp/hero.png `
    --mask tmp/m_weapon.png --mask-prompt "把手里那把剑换成一把发光的短杖" `
    --mask tmp/m_coat.png   --mask-prompt "把外套换成深红色皮甲" `
    --mask-mode sequential --out-dir tmp/zenmux-edit/run1
```

## 默认值（都按"做素材"的场景定）

| 参数 | 默认 | 说明 |
|------|------|------|
| `--output-format` | `png` | 需要透明就只能是 png / webp |
| `--n` | `1` | 一次调用出图张数 |
| `--background` | openai 协议下 `opaque` | **2026-09-23 起不再默认 `transparent`**（实测该取值会被网关掐断 / 2.5 系 400）；vertex 不支持、不发送。`transparent` 仍可显式传（只能配 png/webp）。透明件统一走 `--solid-bg` + 本地抠底 |
| `--quality` | `low` | `low`≈**$0.01~0.02/张**（估）· `medium`≈$0.04~0.05（估）· `high`≈**$0.15~0.18/张**（账单实测）。`xhigh`/`max` 只有 2.5 系列认。hy 系无分档，不发 |
| `--size` | `1024x1024` | 也有 `1536x1024` / `1024x1536` / `auto` / **`match`**（跟随输入图，取 16 的倍数） |
| `--model` | **`openai/gpt-image-2`** | 文档最全（自定义尺寸 / OpenAI 协议下透明底可控）。**不再对接 `openai/gpt-image-2.5-sunburst`**；可选 `openai/gpt-image-2.5-flare`（速度优先）、`openai/gpt-image-1.5`、`tencent/hy-image-v3.0`（混元图像 3.0，单次 1 张）等 |
| `--solid-bg` | **开，`#FF00FF`** | **背景一律纯色**：自动往 prompt 追加"完全均匀纯色底"指令（hy 系中文），配 `flatbg_cut.py --bg-color` 抠成透明件。带 `--mask` 的原位编辑**不注入**；prompt 已写纯色要求也不重复注入；`--no-solid-bg` 关闭 |
| `--transport` | `json` | **openai 协议专属**（vertex 纯 JSON 内嵌，无此开关）；multipart 是给服务端 JSON 路由出问题时的备用通道 |
| `--stream` | **开** | **openai 协议专属** SSE；vertex 是单次 POST 无流式 |
| `--partials` | `0` | 流式中间图数量（同上，openai 专属） |
| `--image-url` / `--mask-url` | 无 | **openai 协议专属**（vertex 传了直接拦截）：用外链/`file:<FILE_ID>` 代替本地上传。**实测 ZenMux 没有 Files API**，`file_id` 只能来自别处；外链需公网可访问 |
| `--multipart-field` | `image[]` | multipart 的图片字段名（openai 协议）：ZenMux **正文写 `image`、curl 示例写 `image[]`**（文档自相矛盾），默认 `image[]` |
| `--out-dir` | `tmp/zenmux-edit/<时间戳>/` | 生成产物请显式指到目标目录；重名不覆盖，自动加 `-2` |
| `--retries` | — | **已经彻底移除**：实测被掐断/超时的请求照样计费，自动重试=重复烧钱。失败就停下，用 `cost` 核账后人工决定 |
| `--retry-on-timeout` | — | 同上，已移除 |

> **背景策略（2026-09-23 起）**：**背景一律纯色**。
> ① openai 协议 `--background` 默认 `opaque`（`transparent` 实测会被网关掐断连接、2.5 系直接 400）；
> ② `--solid-bg`（默认开）自动把"完全均匀纯色底 #FF00FF"写进 prompt（hy 系用中文指令）；
> ③ 出图后用 `tools/flatbg_cut.py --bg-color '#FF00FF'` 抠成透明件（反混合去边，边缘无彩边）。
> 带 `--mask` 的原位编辑不注入纯色底（要保留原背景）；整图编辑要保留原背景就 `--no-solid-bg`。

体积上限（openai 协议口径；vertex 的 `:predict` 无公开字段上限，工具按保守 50MB 拦）：

| 通道 | 限制 | 依据 |
|------|------|------|
| JSON / base64（openai 默认） | `image_url` 字段 ≤ 20MiB ⇒ 原图 ≤ 约 15MB | OpenAI schema `maxLength: 20971520` |
| multipart（openai） | 单文件 < 50MB | OpenAI/ZenMux 上传上限 |
| vertex instances 内嵌 base64 | 无公开上限；工具按原图 50MB 拦 | 未实测更大值 |
| mask PNG | > 4MB 告警（openai）、> 50MB 直接拒 | 4MB 是第三方转售文档的说法，官方未写，故只告警 |

## Vertex 协议的模型家族兼容（2026-09-23，先两族）

同一个 `:predict` 端点，**不同家族参数不同**——工具内置家族表自动分发
（源码 `FAMILIES`，新模型加一格即可）：

| 能力 | openai/gpt-image-* | tencent/hy-image-*（混元） |
|------|--------------------|-----------------------------|
| 尺寸 | 顶层透传 `imageSize`（1024x1024 / 1536x1024 / 1024x1536 / auto / 自定义 16 倍数 ≤3840、比例 ≤3:1） | **不吃 imageSize** → `parameters.aspectRatio`（`--size` 自动折算，如 1536x1024→3:2） |
| 质量 | 顶层透传 `quality`（low/medium/high/auto，计费分档） | **无 quality 分档**（不发，提示无意义） |
| 张数 n | 1~10 | **只能 1**（--n 2 直接本地拦截，不花钱） |
| prompt 增强 `--enhance-prompt` | ✗（忽略） | ✅ 文档明确支持 |
| 负向提示 `--negative-prompt` | ✗（忽略） | ⚠ 未证实（文档只列 Imagen/Kling/通义；带上传，400 就去掉） |
| 分辨率档 | — | `--sample-image-size 1K/2K/4K`（官方列了火山/百度，hy 未明说） |
| background 透明 | ❌ 协议不支持（官方映射表标 ❌）→ **透明件走"纯色底 + flatbg_cut.py 本地抠底"** | ❌ 同左 |
| SSE 流式 / multipart / `--image-url` | （旧 openai 协议才有） | ✗ 单次 POST，JSON 内嵌 base64 |

**实测（2026-09-23，真机 2 次小额计费）**：`tencent/hy-image-v3.0` 文生图与图生图（`REFERENCE_TYPE_RAW` +
base64 内嵌）均 **200 出图**——注意该模型**还没进 ZenMux 目录**（`/models` 不见踪影但已可用），
`check` 对 vertex 协议的目录外模型只 give warn 不判 fail。

mask 在 vertex 协议下照常用（`--mask` / `--mask-mode` 全套），语义与 OpenAI 一致：透明 = 编辑区。

## mask 调研结论（2026-09 核对官方文档）


### 一次请求最多几个 mask？—— **1 个**

- ZenMux 的 [Generate image edit](https://zenmux.ai/docs/api/openai/create-image-edit.html) 接口文档里
  `mask` 是**单个 object**（`{image_url}` 或 `{file_id}`，"You must provide exactly one of"），
  **且只作用于第一张输入图**；能重复的是 `images` 数组（GPT image 模型**最多 16 张参考图**）。
- OpenAI 原生 [Create image edit](https://developers.openai.com/api/reference/resources/images/methods/edit) 同样只有单个 `mask`
  （PNG、与输入图同尺寸、带 alpha）。
- 所以"多个 mask"**不是协议能力**，只能由调用方消化。
- 为什么你会记得"mask 有多个"：ZenMux 还有一条 **Google Gemini / Vertex AI 协议**
  （见 [Generate Images（Vertex AI 协议）](https://zenmux.ai/docs/zh/api/vertexai/generate-images.html)），
  那里 mask 是 `reference_images` 里的一个元素（`referenceType = REFERENCE_TYPE_MASK`），
  形态上是**数组**，多个参考图是支持的；但 ZenMux 会把 OpenAI 系模型转成 OpenAI 协议调用，
  仍然落到"1 个 mask"，所以对 gpt-image 系列没有额外收益。原生 Google 系模型（nano banana 等）
  的改图机制是**用自然语言描述区域 + 参考图**，也不是多 mask。

### mask 语义：**透明（alpha=0）= 要重绘的区域**

- ZenMux 两种协议文档口径一致："透明区域为编辑区域"；
  OpenAI 官方的说法是 mask 的 fully transparent 区域指示要编辑的位置。
- 人手画的 mask 通常是"**涂白 / 不透明 = 要改**"，所以本工具默认 `--mask-polarity marked`
  （不透明或亮 = 要改），内部自动翻成 API 需要的"透明洞"；
  若你的 mask 本身就是"透明洞 = 要改"，用 `--mask-polarity hole`。
- 灰度 mask 按亮度读（白 = 要改）；带 alpha 的 mask 按 alpha 读。阈值 `--mask-threshold`（默认 128）。
- 覆盖面积会打印：**0% = 空 mask**（直接报错），**>95% = 多半 polarity 反了**（告警，试 `hole`）。
  `--dry-run` 会出预览图，红=要重绘、绿线=边界，先肉眼验收再花钱。

### 多 mask 的三种消化方式

| `--mask-mode` | 行为 | 调用次数 | 适合 |
|---------------|------|----------|------|
| `union`（默认） | N 张 mask 用 `lighter` 并成 1 张 | 1 | 同一类改动、只想圈出"这些地方重绘" |
| `sequential` | 每个 mask 一次调用，**上一张输出当下一张输入** | N | 「A 处换武器、B 处换衣服」这类分区不同指令 |
| `separate` | 每个 mask 各出 1 张，都基于原图 | N | 想拿 N 个候选，互相不叠加 |

配 `--mask-prompt` 按下标与 `--mask` 配对：`--mask a.png --mask-prompt "…"  --mask b.png --mask-prompt "…"`。
`union` 模式下多块并成一张，模型分不清哪块该改成什么，工具会告警并建议 `sequential`。

### mask 制作建议

- 尺寸**必须与第一张输入图一致**（不一致会自动最近邻缩放并告警，但会损失精度）。
- 边缘可以 `--mask-grow 2`（向外膨胀 2px）——把武器/衣物的**描边一起吃进去**，
  gpt-image 是"软引导"，只圈内部容易在原边缘留一圈旧像素；`--mask-grow -2` 是腐蚀。
- `--mask-feather 1~2` 羽化，接缝更自然。
- 想省事：PS 里用套索 → 新建图层填白 → 导出 PNG（不透明=要改），本工具直接吃。

## 产出与纪律

- 每次调用打印：HTTP 状态、`x-request-id`、耗时、`usage.total_tokens`、每张图的尺寸与格式。
- 每张产物旁边写一份同名 `.json` 边车：`request_id` / `usage` / 完整参数 / 输入与 mask 路径 / prompt。
  出问题找 ZenMux 客服或核对退款时，报 `x-request-id` 最有用。
- `--dry-run` 只做本地校验 + mask 预览（`_masks/` 下 `*-preview.png` 与 `*-api.png`），**不发请求**。
- `--stream` 走 SSE（`image_edit.partial_image` / `image_edit.completed`），
  加 `--save-partials` 会把中间图落到 `_partials/`；耗时长的调用可以靠它看进度。
- 中间产物默认落 `tmp/`（见 `AGENTS.md`），别落在入库目录；**要删产物先问用户**。

## 排错表

| 现象 | 原因 / 处理 |
|------|-------------|
| 没有 ZENMUX_API_KEY | 按上面写进工作区根 `.env`（脚本会打印该提示） |
| `403 access_denied`（带 `api_key_source: payg`） | **key 类型不对**：`sk-mg-` 是管理型 key，模型接口一律 403 → 去 <https://zenmux.ai/platform> 建**普通** key 写进 `ZENMUX_API_KEY`；管理型 key 留给 `ZENMUX_MANAGEMENT_API_KEY` 查余额 |
| `500 internal_server_error` + 用的是管理型 key | `/images/edits` 的 **JSON 通道鉴权前就 500**（ZenMux 侧缺陷），别当成服务端故障；换普通 key 即可 |
| `403 safety_check_failed` | 上游安全策略拦了 → 改 prompt / 换模型 |
| `402 insufficient_credit` / `reject_no_credit` / `quote_exceeded` | 欠费 / 余额不足 / 订阅额度用尽 → <https://zenmux.ai/platform> |
| `404 model_not_available` / `invalid_model` / `model_not_supported` | 模型不在套餐 / 不存在 / 不支持该接口 → 先 `check` 看列表，或换 Pay-As-You-Go key |
| `413` | prompt 太长 |
| `422 provider_unprocessable_entity_error` | 平台校验过了但上游处理不了 → 去掉高级参数（`--input-fidelity` / `--moderation` 等）重试 |
| `400` + message 提到 `background` / `transparent` | 上游模型（如 2.5）在 edit 端不支持透明背景。**无自动回退**（没重试机制）：显式 `--background opaque`；要透明走"纯色底 + 本地抠底" |
| `400 invalid_image_file` | 输入图不是标准 PNG/JPEG/WEBP（手机 MPO/HDR 多帧 JPEG 是常见坑）；本工具读图时会 `load()` 取首帧再重编码，正常不会踩 |
| `400` 提到 `input_fidelity` | 第三方文档称 gpt-image-2.5 传它会 400（ZenMux 文档未明确）；不确定就别传 |
| `400` 提到 `n` | ZenMux 对部分模型不支持 `n>1` → 保持 `--n 1`，多次出图用 `--mask-mode separate` 或跑多次 |
| `429` | 限流 → 降频重试（可重试码：429/500/502/503/504/520/524） |
| mask 覆盖 0% / >95% | polarity 选错，换 `--mask-polarity`；或阈值 `--mask-threshold` 不合 |
| 输入图 base64 超过 20MiB 字段 | `--max-side 2048` 缩小输入，或改用 `--transport multipart`（50MB 上限） |
| 流式调用报 `流内错误：…` | 流一旦开始，ZenMux 不回标准 JSON 而是在流内发失败事件；本工具会把它解出来（含 `type`/`message`），不会再误报成 "HTTP 200" |
| 连接被重置 `RemoteDisconnected` | 实测 **`--background transparent` 会被网关直接掐断连接**（不是 4xx，看日志只有 RemoteDisconnected）。要透明件就走 **"纯色底 + 本地抠底"**：默认的 `--solid-bg`（#FF00FF）+ `tools/flatbg_cut.py --bg-color '#FF00FF'`。⚠ **被掐断的请求照样计费**（实测 4 次 transparent 全部扣款），工具**没有任何重试开关**：先 `cost` 核账，再人工决定要不要重跑 |
| 长请求怕被网关掐断 | 用 `--stream --partials 0`：SSE 每 10s 有保活数据，连接不空闲；图片编辑没有异步/轮询接口可退 |
| 读超时 | **先别重跑**：请求已发出，上游可能已出图计费。拿 `x-request-id` 去 platform 日志核对；确需自动重试才加 `--retry-on-timeout` |

## 已验证 / 未验证

- **Vertex 协议真机已验证（2026-09-23，2 次小额计费探针）**：
  `POST /api/vertex-ai/v1/publishers/tencent/models/hy-image-v3.0:predict`
  ① 文生图（prompt only）→ 200 出 `gcsUri`（COS 签名 URL）；② 图生图
  （`instances[0].referenceImages = [REFERENCE_TYPE_RAW + bytesBase64Encoded]`）→ 200 出 `gcsUri`。
  假 key → 与 OpenAI 协议同一错误信封（`403 access_denied` + `api_key_source`），
  平台接口（`balance` / `cost` / `generation`）在 Vertex 切换下**不受影响**。
  工具侧形状由 `tools/tests/` 的 CLI 级测试覆盖（openai 家族顶层 `imageSize`/`quality`、
  mask 的 `REFERENCE_TYPE_MASK + MASK_MODE_USER_PROVIDED`、hy `--n 2` 拦截、`gcsUri` 下载分支）。
  **未真机验证**：mask 在 vertex 协议下的实际重绘效果（要走一次小额 `--min-credits 1`）。
- **本地 mock 的 CLI 级测试（零真机、零费用）**：`python tools/tests/test_zenmux_cli.py` —— 14 条，约 6s。
  口径是「**先 mock，再只验 CLI 命令**」（用户 2026-09-23 指示：真机测试要花钱，不再逐条断内部函数）：
  断言只有退出码 / stdout 关键词 / 落盘产物 / `--dump-request` 的请求体。覆盖
  `check` / `balance`（含余额为 0 时退出 1）/ `cost` / `generation` /
  `edit` 的 openai JSON、multipart、SSE 三形态 / vertex `:predict`（含 mask 引用形状、腾讯系 `gcsUri` 下载）/
  本地拦截（`--n` 越界、透明底配 jpeg、缺 prompt、hy `--n 2`、`--aspect-ratio` 形式错、未知子命令）/
  403 `access_denied` 提示 / `--dry-run` 一个 POST 都不发。
  mock 服务端是 `tools/tests/mock_zenmux.py`（纯标准库，也能手工起）；测试进程另把 `HTTPS_PROXY`
  指到死端口兜底 —— 哪天漏配 `--base-url`，请求会立刻失败，而不是悄悄打到 zenmux.ai 烧钱。
  口径与用例清单见 [`tests/README.md`](tests/README.md)。
- 上一版那份 **92 条内部断言**的 harness（曾放 `tmp/mock_zenmux.py` + `tmp/test_zenmux_edit.py`）
  **已废弃**（文件也随 `tmp/` 清空）：它断的 mask 语义换算、union 并集面积、`--mask-grow`、
  `--size match` 下限放大、`--mask-feather` 这类**内部细节**现在不再每次复验；
  要复查就现写一次性脚本，别把它们堆回测试套件。
- **已在真机验证（免费接口）**：`check`（公开 `GET /models`：**202 个模型、8 个可出图**、默认模型在架）与
  `balance` / `check` 的余额行（`GET /management/payg/balance`）、`cost`（`/management/cost`，7 次请求 $1.200935）。
- **真机验证（2026-09-23，本轮）**：目录里 7 个可出图模型（全是 openai 系）、
  `balance` 实测 `GET /management/payg/balance` 正常；
  **vertex 协议 2 次小额计费探针**：`tencent/hy-image-v3.0` 文生图 / 图生图均 200 出 `gcsUri`；
  假 key 403 信封与 openai 协议一致。**未复验**：openai 协议真机生成（本机连不通 zenmux.ai，
  记录见"真机实战记录"）；vertex 下 mask 的实际重绘效果；`imageSize`/`quality`/`sampleImageSize`
  透传在 `:predict` 上的实际生效情况（形状以官方 SDK extra_body 语义为准，错了应是免费 400，跑一次便知）。

## 真机实战记录（武僧换武器 MVP，2026-09-21）

| 事实 | 说明 |
|------|------|
| JSON(base64) 编辑通道 | **对 gpt-image-2 恒 500**（管理型 key 下也是 500，说明它先于鉴权失败）→ 实际可用通道是 `--transport multipart` |
| 管理型 key `sk-mg-` | 打模型接口一律 **403 access_denied**；只能查余额/用量（`balance`） |
| `--background transparent` | edit 端点**直接掐断连接**（RemoteDisconnected）；透明件改走"纯色底 + 本地抠底" |
| mask 不是硬边界 | 实测 mask 只覆盖 2.91% 画面，生成图**mask 外 30.6% 像素被重画**（另一只手的武器被抹掉）→ 要么只把 mask 内改回贴回原图，要么用"部件单独重画"流程 |
| 单次编辑的实测开销 | 704x960 / high / 3 张输入图：103s、6566 tokens；784x848 单独画部件：113s、6871 tokens。**账单口径：一次 $0.15~0.18**（`image_output` 占 94%），按 flow 单价估会差 5 倍 |
| **被掐断 = 照常计费（重要）** | 实测一轮 7 次请求全计费 $1.2009，只有 2 次拿到图：其中 1 次客户端被掐断但服务端跑了 364.7s 照扣 $0.1512；另外 `background=transparent` 的 4 次（1 原始 + 3 重试）各扣 $0.1797。<br>→ 对策：**① 不用 transparent（现在默认 opaque + 纯色底）**；**② 工具无任何重试开关，失败就停下**；**③ 事后用 `cost` 核账** |
| 查询账单（免额度） | `python tools/zenmux_edit.py cost --models openai/gpt-image-2`（默认按月看天桶）<br>`... cost --dimension BIZ_DT --time 20260922`（按天看小时桶，能看出是几点烧的）<br>`... cost --json` 出原始结构；接口 `/api/v1/management/cost`，与 Usage 共享 60 次/分钟限流 |
| 长连接怎么不被打断 | 图片编辑**没有异步/轮询接口**（Images 协议是同步的；`/management/generation` 只是账单查询，3~5 分钟后才有数据）。唯一替代通道是 **SSE 流式**：`--stream`（配 `--partials 0` 最省，只要最终图），ZenMux 每 **10 秒**发一次 `: ZENMUX PROCESSING` 保活注释，连接不会长时间空闲；出问题也能收到流内 error 事件而不是干巴巴断连 |
| 部件"单独重画"流程（推荐给换皮） | 输入 = 原部件放大 + 风格参考，prompt 要"单体 / 居中 / 纯色底 / 保持轮廓朝向与画布位置"→ 抠底得 alpha → 按"原部件 alpha maxXY ↔ 新件 alpha maxXY"等比缩放 → 放回原附件画布 → 换回 Spine 重渲验证（远处应为 0px 变化） |

## 相关文档

- [`docs/zenmux-cli.md`](../docs/zenmux-cli.md) —— **本工作区的操作要点速查**（场景、常用命令、成本控制、硬规则）；本文是它的完整口径
- [Generate Images（Vertex AI 协议，ZenMux）](https://zenmux.ai/docs/api/vertexai/generate-images.html) —— `:predict` 端点、`instances+parameters`、透传参数表
- [Image Generation Guide（ZenMux）](https://zenmux.ai/docs/guide/advanced/image-generation.html) —— `edit_image` / MaskReferenceImage 示例、OpenAI 参数 → Vertex 映射表
- [Get PAYG Balance（ZenMux 平台 API）](https://zenmux.ai/docs/api/platform/payg-balance.html) —— 余额 / 成本控制
- [API 错误码参考（ZenMux）](https://zenmux.ai/docs/guide/advanced/error-codes.html) —— 403 `access_denied`、402、流内错误
- [图片生成 - OpenAI Image 协议（ZenMux）](https://zenmux.ai/docs/zh/guide/advanced/openai-image-generation.html)
- [Generate image edit（ZenMux API）](https://zenmux.ai/docs/api/openai/create-image-edit.html)
- [Image edit streaming events（ZenMux API）](https://zenmux.ai/docs/api/openai/image-edit-streaming-events.html)
- [图片生成 - Google Gemini 协议（多参考图 / mask reference）](https://zenmux.ai/docs/zh/guide/advanced/image-generation.html)
