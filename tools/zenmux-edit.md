# zenmux_edit.py — ZenMux 图片编辑（mask 局部重绘）

**给素材图标记若干部位，只让模型重绘这些部位**：换一把武器、换一件衣服、改配色 / 材质。
走 ZenMux 的 OpenAI Images 协议（`POST /v1/images/edits`），输入图以 **base64 data URL** 发送。

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

## 成本控制（PAYG 余额）

对应 ZenMux 的 [Get PAYG Balance](https://zenmux.ai/docs/api/platform/payg-balance.html)：
`GET https://zenmux.ai/api/v1/management/payg/balance`，**免费**，但**只接受 Management API Key**。

```powershell
python tools/zenmux_edit.py balance            # 余额 10 USD（充值 10 + 赠送 0）    [来源 ZENMUX_API_KEY]
python tools/zenmux_edit.py balance --json     # 原始结构，便于脚本对账
python tools/zenmux_edit.py check              # 自检时顺带报余额
python tools/zenmux_edit.py edit ... --min-credits 1
```

- `--min-credits 1`：**开跑前**查一次余额，低于 1 USD 直接拒跑（一个请求都不发）；
  **跑完再查一次**，打印 `余额 10 → 9.8，本次消耗 ≈ 0.2 USD`（余额差，同账号其它会话也会算进去）。
- 每次运行都在产物目录写 `run-summary.json`：余额前后、余额差、各步 `total_tokens` / 耗时 /
  `x-request-id` / 产物清单 —— 对账、复现、报障都用它。
- 没有管理型 key 时，`--min-credits` 只是警告后跳过（不阻塞干活）；`balance` 会直接告诉你缺哪把 key。
- 余额接口有独立限流（文档：超出返回 422），脚本会提示"等一分钟再试"。

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
| `--background` | `transparent` | 只有你显式说要不透明时才改 `opaque`；`none`=完全不传该字段 || `--quality` | `medium` | `low` / `medium` / `high` / `auto`（`xhigh` / `max` 只有 2.5 系列认） |
| `--size` | `1024x1024` | 也有 `1536x1024` / `1024x1536` / `auto` / **`match`**（跟随输入图，取 16 的倍数） |
| `--model` | `openai/gpt-image-2.5-sunburst` | 编辑精度优先。同价可选：`...-sunburst-2026-09-08`（钉版本）、`openai/gpt-image-2.5-flare`（速度优先）、`openai/gpt-image-2`（上一代，**文档明确支持 `background=transparent`**）、`openai/gpt-image-1.5` |
| `--transport` | `json` | base64 data URL；`multipart` 是给服务端 JSON 路由出问题时的备用通道 |
| `--multipart-field` | `image[]` | multipart 的图片字段名：ZenMux **正文写 `image`、curl 示例写 `image[]`**（文档自相矛盾），默认 `image[]`，被 400 拒了会自动退回 `image` |
| `--out-dir` | `tmp/zenmux-edit/<时间戳>/` | 生成产物请显式指到目标目录；重名不覆盖，自动加 `-2` |
| `--retries` | `0` | **不自动重试**：5xx / 超时下自动重试有重复计费风险，要重试请显式给次数 |
| `--retry-on-timeout` | 关 | 读超时默认**不重试**（请求已发出，上游可能已计费）；只有连接失败才在 `--retries` 内安全重试 |

> **默认模型 × 默认透明背景的已知张力**：默认模型是 `openai/gpt-image-2.5-sunburst`，
> 而 ZenMux 的 OpenAI 协议文档把 `transparent` 列为 `background` 合法取值（流式事件里也会回 `background: transparent`），
> 但第三方实测 **2.5 系列在 edit 端传 `transparent` 会 400**（ZenMux 文档未明确）。
> 于是：默认仍按需求发 `transparent`，被 400 拒时 `--bg-fallback`（默认开）自动去掉该字段重试一次（会告警，那张可能是不透明底）。
> **要保证透明底**（贴图 / 换装件）就显式用 `--model openai/gpt-image-2`，或先在 `--dry-run` 里确认计划，再按第一次实测结果决定。

体积上限（三条不是一回事）：

| 通道 | 限制 | 依据 |
|------|------|------|
| JSON / base64（默认） | `image_url` 字段 ≤ 20MiB ⇒ 原图 ≤ 约 15MB | OpenAI schema `maxLength: 20971520` |
| multipart | 单文件 < 50MB | OpenAI/ZenMux 上传上限 |
| mask PNG | > 4MB 告警、> 50MB 直接拒 | 4MB 是第三方转售文档的说法，官方未写，故只告警 |

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
| `400` + message 提到 `background` / `transparent` | 上游模型（如 2.5）在 edit 端不支持透明背景。默认已开 `--bg-fallback`：自动去掉 `background` 重试一次并告警；也可显式 `--background opaque` |
| `400 invalid_image_file` | 输入图不是标准 PNG/JPEG/WEBP（手机 MPO/HDR 多帧 JPEG 是常见坑）；本工具读图时会 `load()` 取首帧再重编码，正常不会踩 |
| `400` 提到 `input_fidelity` | 第三方文档称 gpt-image-2.5 传它会 400（ZenMux 文档未明确）；不确定就别传 |
| `400` 提到 `n` | ZenMux 对部分模型不支持 `n>1` → 保持 `--n 1`，多次出图用 `--mask-mode separate` 或跑多次 |
| `429` | 限流 → 降频重试（可重试码：429/500/502/503/504/520/524） |
| mask 覆盖 0% / >95% | polarity 选错，换 `--mask-polarity`；或阈值 `--mask-threshold` 不合 |
| 输入图 base64 超过 20MiB 字段 | `--max-side 2048` 缩小输入，或改用 `--transport multipart`（50MB 上限） |
| 流式调用报 `流内错误：…` | 流一旦开始，ZenMux 不回标准 JSON 而是在流内发失败事件；本工具会把它解出来（含 `type`/`message`），不会再误报成 "HTTP 200" |
| 连接被重置 `RemoteDisconnected` | 实测 **`--background transparent` 会被网关直接掐断连接**（不是 4xx，看日志只有 RemoteDisconnected）。要透明件就改走 **"纯色底 + 本地抠底"**：`--background opaque` + prompt 要求纯洋红 `#FF00FF` 背景，出图后按 `min(R,B)-G` 抠掉。多图 multipart 偶发同症状，`--retries 2` 能过 |
| 读超时 | **先别重跑**：请求已发出，上游可能已出图计费。拿 `x-request-id` 去 platform 日志核对；确需自动重试才加 `--retry-on-timeout` |

## 已验证 / 未验证

- **已验证（本地 mock 服务端，92 项断言全通过）**：请求体形状（`images[].image_url` data URL、
  `mask.image_url`、`n/size/quality/background/output_format` 默认值、默认模型
  `openai/gpt-image-2.5-sunburst`）、mask 语义转换
  （标记区 → 透明洞，实测覆盖面积与几何面积吻合；`hole` 语义、**alpha 全 255 的 RGBA mask 回退按亮度读**
  都已核对）、union 并集面积、sequential 两次调用与分区 prompt、**串行时 mask 自动跟随上一步输出尺寸**、
  `--mask-grow` 膨胀、mask 尺寸不一致自动缩放、`--size match`（含下限放大）、SSE 流式解析与 usage 提取、
  **流内 error 事件被解析成真实错误**、multipart 备用通道与字段名切换、重名不覆盖、`--dump-request` 多步落盘、
  缺 prompt / 缺 key / `n` 越界 / `jpeg + transparent` 的本地拦截、2.5 默认模型下的透明背景告警、
  **余额读取与成本控制**（`balance` / `balance --json` / `check` 报余额 / `--min-credits` 守卫拦截与放行 /
  `run-summary.json` 的余额差与 token 汇总）。
  （harness 在 `tmp/mock_zenmux.py` + `tmp/test_zenmux_edit.py`，属临时产物，未入库；随时可重跑，**全程不打真机、不花钱**。）
- **已在真机验证（免费接口）**：`check`（公开 `GET /models`：199 个模型、7 个可出图、默认模型在架）与
  `balance` / `check` 的余额行（`GET /management/payg/balance` → `余额 10 USD（充值 10 + 赠送 0）`）。
- **未验证**：对 ZenMux 真机的**生成**调用——按用户要求把所有远程生成调用都 mock 掉，没有产生任何计费请求。
  真机首次使用建议：先 `check`，再 `check --probe`（预期 404 invalid_model），最后跑一次单 mask 的 `edit --min-credits 1`。

## 真机实战记录（武僧换武器 MVP，2026-09-21）

| 事实 | 说明 |
|------|------|
| JSON(base64) 编辑通道 | **对 gpt-image-2 恒 500**（管理型 key 下也是 500，说明它先于鉴权失败）→ 实际可用通道是 `--transport multipart` |
| 管理型 key `sk-mg-` | 打模型接口一律 **403 access_denied**；只能查余额/用量（`balance`） |
| `--background transparent` | edit 端点**直接掐断连接**（RemoteDisconnected）；透明件改走"纯色底 + 本地抠底" |
| mask 不是硬边界 | 实测 mask 只覆盖 2.91% 画面，生成图**mask 外 30.6% 像素被重画**（另一只手的武器被抹掉）→ 要么只把 mask 内改回贴回原图，要么用"部件单独重画"流程 |
| 一次编辑的实测开销 | 704x960 / high / 3 张输入图：103s、6566 tokens；784x848 单独画部件：113s、6871 tokens |
| 部件"单独重画"流程（推荐给换皮） | 输入 = 原部件放大 + 风格参考，prompt 要"单体 / 居中 / 纯色底 / 保持轮廓朝向与画布位置"→ 抠底得 alpha → 按"原部件 alpha maxXY ↔ 新件 alpha maxXY"等比缩放 → 放回原附件画布 → 换回 Spine 重渲验证（远处应为 0px 变化） |

## 相关文档

- [Get PAYG Balance（ZenMux 平台 API）](https://zenmux.ai/docs/api/platform/payg-balance.html) —— 余额 / 成本控制
- [API 错误码参考（ZenMux）](https://zenmux.ai/docs/guide/advanced/error-codes.html) —— 403 `access_denied`、402、流内错误
- [图片生成 - OpenAI Image 协议（ZenMux）](https://zenmux.ai/docs/zh/guide/advanced/openai-image-generation.html)
- [Generate image edit（ZenMux API）](https://zenmux.ai/docs/api/openai/create-image-edit.html)
- [Image edit streaming events（ZenMux API）](https://zenmux.ai/docs/api/openai/image-edit-streaming-events.html)
- [图片生成 - Google Gemini 协议（多参考图 / mask reference）](https://zenmux.ai/docs/zh/guide/advanced/image-generation.html)
