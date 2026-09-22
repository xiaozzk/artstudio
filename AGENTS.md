# artstudio 工作区

> 路径均相对**工作区根**（= 本文件所在目录）；分隔符统一写 `/`，Windows / macOS 通用。
> 本文只写**工具怎么用**与**实测经验**。
> 产出面向 **Godot 4（≥ 4.4）**。

## 语言

默认工作语言：**中文**。文档、注释、与 agent 的对话一律中文；技术名词、文件名、API、标识符保留英文原文。

## 目录结构

| 路径 | 内容 |
|------|------|
| `docs/` | 空目录（`.gitkeep` 占位） |
| `assets/eva_bone/` | Eva 原型素材：`parts/` 基础体拆件、`parts_outfit/` 服装件、拼合图与 manifest |
| `assets/_archive/` | 更早的素材与一次性脚本（`source/`、`scripts/`、`metadata/`） |
| `meowa/` | AI 生图素材与预设（`templates/` 放 Meowa 预设信息） |
| `tools/` | 本地图片 / 部件处理脚本 + 浏览器登录态复用 + `zenmux_edit.py`（唯一会花钱的）；清单见 `tools/README.md` |
| `tmp/` | **临时目录**：已忽略、不入库、可随时清 |
| `download/` | **刚下载、还没处理**的落地目录（素材包 / 第三方仓库 / 待转换资源）：已忽略、不入库，但**别随手清** |
| `archive-2d/` | 2D 时代归档（4 个 7z，**不入库**，本地保留）；当历史资料看，不要照着做 |
| `.env`、`.git/`、`.claude/` | 凭据 / 仓库 / 本机 agent 配置 |

- `archive-2d/` 解压：`7z x archive-2d/<包>.7z -o<目标>`。
  内含 `reference-2d.7z`（旧 `reference/`）、`docs-2d.7z`（旧 `docs/`）、
  `dressup-lab.7z`（旧 `tools/dressup-lab/`）、`meowa-2d-docs.7z`（旧 meowa 的 2D 文档）。
- **agent / CLI 的中间产物一律写 `tmp/`**（提交信息草稿、报告、预览图、浏览器 profile 副本…）；
  **不要落在 `docs/` / `tools/` / `meowa/` 等入库目录** —— 否则会跟着代码一起被提交。
- **刚下载、还没处理的东西写 `download/`**（素材包、第三方仓库、待转换资源），别塞进 `tmp/`：
  两者都不入库，但 `tmp/` 是**可随手的中间产物**，`download/` 是**还没决定去留的原始下载**（别随手清）。
- 大二进制走 **Git LFS**（图 / psd / 模型 / 归档 / 音视频）；`.md`、`.json`、代码不进 LFS，保持可 diff。规则见 `.gitattributes`。

## 凭据与权限（已确认，无需再议）

- Meowa API key（`ma_live_...`）放在工作区根 **`.env`**（已被 `.gitignore` 忽略），对接**官方渠道**，不构成泄露风险。
- ZenMux 有**两类 key，别混**（2026-09 实测）：
  - `ZENMUX_API_KEY=sk-...`（**普通 key**）—— 生图/模型接口只用这个；`.env` 里没有它就只能干等。
  - `ZENMUX_MANAGEMENT_API_KEY=sk-mg-...`（**管理型 key**）—— 只能打余额/用量等平台接口；
    **拿它打模型接口一律 403 `access_denied`**（消息带 `api_key_source: payg`）。
    更坑的是：`/images/edits` 的 **JSON 通道**在鉴权前就 500，所以管理型 key 走 JSON 编辑会看到
    `HTTP 500 internal_server_error` 而不是 403 —— 排查时别被 500 带跑偏。
- 在命令中使用 key 是允许的、预期的做法；**不要再提醒轮换或提出安全建议**。
- skill 明确规定**不要要求用户把 key 贴进对话** —— 引导其写入 `.env` 即可。
- 用户已授予最大权限，按此前提协作。

## Meowa 生图 CLI

**用途**：出**原画** —— 角色设定图 / 三视图、服装设计稿、配色与材质设定。

- **命令**：`python ~/.agents/skills/game-assets/meowart_api.py <子命令>`
- **一律在工作区根下执行** —— runner 从**执行命令的当前目录**读 `.env`，换目录就读不到 key。
- **`.env` 按 latin-1 解析 → 禁止中文注释**，写了会直接解码报错。
- **校验连通 / 余额**：`... meowart_api.py credits-balance`
- **更新 CLI 走 codeload tar.gz**（`git clone` 常被重置），整目录覆盖 `~/.agents/skills/game-assets`
  与 `.claude/skills/game-assets` 两个安装点。
- **prompt 硬规则**：**单行、且不含任何引号字符**（PowerShell 会把双引号当分隔符）。
  用无引号结构化约束代替引号，例如 `Constraints: canvas = ...; edit = [...]; must_not_change = [...]`；
  给**整图**并说明上下文；显式禁止模型"顺手改结构"。
- **参数限制**：`--strict` 只在 `--mode pixel` 可用；HD 编辑去背只支持 `none` / `standard`。
- **产物纪律**：每次生成先记 `job_id`；`--output-dir` 必须互不相同。失败自动全额退费，
  **不要重复提交**；误删可用 `image-2-poll --job-id <id>` **免费**重新下载。
- **三视图要点**：prompt 里必须显式要求**同一角色的致外观**（同服装 / 同配色 / 同发型），
  否则正 / 侧 / 背之间比例会变，对不上。

## ZenMux 图片编辑 CLI

**用途**：在素材图上**标记若干部位，只重绘这些部位** —— 换一把武器 / 换一件衣服 / 改配色材质。
走 ZenMux 的 OpenAI Images 协议（`POST /v1/images/edits`），图片以 base64 data URL 传入。
**这是 `tools/` 里唯一会花钱的脚本。**

- **命令**：`python tools/zenmux_edit.py <check|balance|cost|generation|edit>`，**一律在工作区根下执行**（读根目录 `.env`）。
- **自检 / 查余额 / 查账单（都免费）**：
  - `python tools/zenmux_edit.py check` —— key、模型是否在架、mask 覆盖面积、当前 PAYG 余额
  - `python tools/zenmux_edit.py balance [--json]` —— 只查余额
  - `python tools/zenmux_edit.py cost [--models M] [--dimension BIZ_MTH|BIZ_DT|BIZ_HOUR] [--time T]` —— 查账单
  - `python tools/zenmux_edit.py generation --id <generationId>` —— 单次调用明细（id 从 Logs 页 Request 搜索框拿）
- **成本控制**（余额接口只认管理型 key）：
  - `edit --min-credits 1`：开跑前低于 1 USD 就拒跑；跑完打印余额差（≈本次实际花费）
  - 每次运行都会写 `run-summary.json`（余额前后、余额差、各步 token 用量、产物清单）
  - 每次调用都打印 `x-request-id` 与 `usage.total_tokens`；**产物旁边有同名 `.json` 边车**便于对账
  - **单价别按订阅页的 `$0.03283/flow` 估**（那是文本 flow 价）：图片编辑实测**一次 $0.15~0.18**
    （`image_output` 占 94%）。精确对账：`python tools/zenmux_edit.py cost --models openai/gpt-image-2`
    （按天看小时桶加 `--dimension BIZ_DT --time YYYYMMDD`）。
  - ⚠ **被网关掐断的请求照样计费**（实测一轮 7 次全计费 $1.2009，只有 2 次拿到图，白烧 72%）：
    所以透明件不要用 `--background transparent`（实测该参数会被断连、且 4 次全扣款）；
    **工具没有任何自动重试**，失败就停下用 `cost` 核账，人工决定要不要重跑。
- **硬规则 / 实测经验**：
  1. **一次请求只能带 1 个 mask**（OpenAI Images 协议如此，且只作用于第一张输入图；输入图最多 16 张）。
     多区域由工具消化：`union`（并成 1 张，1 次调用）/ `sequential`（逐块改并串起来，N 次调用，
     「A 换武器 + B 换衣服」用这个）/ `separate`（N 个候选）。
  2. **mask 语义：透明（alpha=0）= 要重绘**。工具默认按人画 mask 的习惯读入（`--mask-polarity marked`：
     涂白/不透明=要改），自动翻成 API 需要的透明洞；PS 存成「alpha 全 255 + 黑白亮度」也能正确识别。
  3. **先 `--dry-run` 再花钱**：免费出 mask 预览（红=要重绘 / 绿线=边界），确认覆盖面积合理再正式跑。
     覆盖 0% 会直接报错，>95% 会告警（多半 polarity 反了）。
  4. **默认值**：`png` / `n=1` / `background=transparent` / `quality=medium` / `size=1024x1024`；
     默认模型 `openai/gpt-image-2.5-sunburst`（编辑精度优先）。**要保证透明底就显式
     `--model openai/gpt-image-2`** —— 2.5 在 edit 端可能 400 拒 `transparent`；工具**不会**自动回退，
     按报错改 `--background opaque` 再跑。
     实测（2026-09-21）：**`--background transparent` 会被网关直接掐断连接**（RemoteDisconnected），
     要透明件请走"`--background opaque` + prompt 要纯洋红 `#FF00FF` 底 + 本地抠底"。
  4b. **JSON(base64) 编辑通道对 gpt-image-2 恒 500** → 真机一律 `--transport multipart`。
  4c. **mask 不是硬边界**（实测 mask 覆盖 2.91% 时，mask 外 30.6% 像素被重画）：
     换单个部位就用 `apply` 思路只把 mask 内的改动贴回原图；要"换皮/做新组件"就走
     **部件单独重画**流程：输入 = 原部件放大 + 风格参考，prompt 要单体/纯色底/保持轮廓朝向与画布位置，
     抠底得 alpha → 按"原部件 alpha maxXY ↔ 新件 alpha maxXY"等比缩放 → 放回原附件画布 → 换回 Spine 重渲验证。
  5. **没有任何自动重试**（`--retries` / `--retry-on-drop` / `--retry-on-timeout` 已全部移除）：
     实测被掐断 / 超时 / 5xx 的请求**照样计费**，所以失败就停下 —— 用 `cost` 核账后人工决定。
     **默认走 SSE 流式**（`--stream`，`--partials 0`）：服务端每 10s 发 `: ZENMUX PROCESSING` 保活，
     连接不空闲、最不容易被掐断；`--no-stream` 可退回一次性 JSON。
     每次调用都会记 `requests.jsonl`（`created` / `request_id` / 响应头 / usage / 输入 sha256 / 产物）
     与 `_responses/response*.json`（响应体，b64 折叠），跟后台 Logs 页对账用得上；
     `generation --id <generationId>` 可按 id 查单次明细（id 在 Logs 页的 Request 搜索框里拿）。
  5b. **图片没有 Files API**（`/files` 404、上传 500），所以做不到"上传一次、按 id 反复引用"；
     要少传字节只能 `--image-url`（外链）或 `--mask-url file:<id>`（id 得来自别处）。
  6. 中间产物落 `tmp/zenmux-edit/<时间戳>/`（见上面的中间产物规则）；产物要删先问用户。
- **完整口径**（参数表、mask 上限调研、体积限制、错误码表）：`tools/zenmux-edit.md`

## tools/ 本地脚本

**纯本地、确定性、不消耗 AI 额度**（唯一例外：`zenmux_edit.py` 走 ZenMux 生图，**消耗额度**）；
依赖 `numpy pillow opencv-python requests`。完整口径见 `tools/README.md`，一眼版：

| 脚本 | 一句话 |
|------|--------|
| `bbox_ref.py` | 由 bbox 规格生成比例参考图（喂 AI 当比例约束 / 当人工验收标尺） |
| `alpha_split.py` | 按 alpha 连通域把整图拆成部件 |
| `fit_parts.py` | 部件按 spec 比例缩放拼回原画布，并给出客观质量分 |
| `slice-sheet.py` | 整张部件拼图 → 部件贴图（含脏像素清理 + 体检），见 `tools/slice-sheet.md` |
| `outfit-split.py` | 服装拆件拼图 → 可换装件（输入须纯灰底 205） |
| `outline-part.py` | 皮肤件补内描边（只改 RGB，不动 alpha）；幂等 |
| `image_parts_tool.py` | 部件边缘精修一体化：`analyze` / `cut` / `prep` / `prompt` / `gen` / `verify` / `apply` / `report` / `diff` / `overview` |
| `zenmux_edit.py` | **ZenMux 图片编辑（mask 局部重绘，消耗额度）**：标记部位只重绘该处（换武器 / 换衣服）；多 mask 有 union / sequential / separate 三种消化（协议层一次只收 1 个 mask）；见 `tools/zenmux-edit.md` |
| `parts_sheet.py` | 把部件摆成**互不重叠、相邻 ≥N px** 的参考图（喂 AI 当"这些是独立零件"） |
| `flatbg_cut.py` | 纯色底出图 → 抠成透明件 + 按参考部件 **alpha 最大 XY 等比缩放贴合**到原附件画布 |
| `spine_part_swap.py` | `locate` 定位插槽可见区（→ mask/尺寸/附件四边形）、`verify` 换图重渲量化改动（远处应为 0px）—— 换皮流水线见 `tools/spine-reskin.md` |
| `ps_cut/fill_from_layer1.jsx` | PS 里一键补缺口（文件 > 脚本 > 浏览） |
| `browser/` | 浏览器登录态复用（见下节） |

**通用经验**

- **优先让 AI 直接输出透明背景**。压到纯色底再抠色会**不可逆**地丢掉最淡的抗锯齿像素
  （实测：一条 1px 细线的 alpha 像素 167 → 69）。`--bg` 只当兜底。
- **面积比要用相对值**：AI 画的部件可能整体按 1.5× / 2× 出图，绝对面积差一个全局常数，
  直接比会把 `hair` 和 `head_base` **配反**（实测踩过）。
- 部件贴图**统一保留同一套画布坐标**，换目标分辨率只是乘一个缩放系数。
- 产物里写死的格式标识符（`spine-outfit-split`、`spine-part-outline`、`SpineOutline` 等）
  **不要改名** —— 改了会破坏与既有产物的兼容。

## 浏览器登录态复用（CDP 副本）

**场景**：用户已在日常浏览器（**非 CDP**）里人工登录某站点，agent 需要**借用**这个登录态做自动化，
但不得污染真实 profile、也不该让用户重新登录。

做法**不是**让 MCP 接管用户浏览器，而是：**复制出一份可丢弃的 profile 副本 → 用同一个 exe 带 CDP 端口启动 → 用完销毁。**

- 工具：`tools/browser/borrow-login.ps1`（复制 + 启动）、`tools/browser/cdp-eval.mjs`（在页面上下文跑 JS）
- 参数默认值、排查表、Mixamo 已验证实例：`tools/browser/README.md`

**三个硬前提（每个都推翻了一个想当然的假设，实测踩过）**：

1. **必须用与源 profile 相同的 exe** —— App-Bound Encryption 把 cookie 密钥绑定到 exe **路径 + 签名**。
   Edge ↔ Chrome 之间搬 cookie **解不开**，换程序直接读也解不开。
2. **cookie 与 Local Storage 都要复制** —— 登录态未必在 cookie 里。
   实测 Mixamo 的 session 是**纯 `localStorage.access_token`**，只复制 `Cookies` 会白干。
   （leveldb 不加密、不受 ABE 影响 —— 真正能搬的恰恰是它。）
3. **复制前必须关闭源浏览器** —— 运行中 `Cookies` 是独占锁，`FileShare.ReadWrite|Delete` 都打不开，
   `robocopy /b` 备份模式同样失败。管理员可用 **VSS 卷影快照**绕过（只读快照不受锁约束）。

**流程**：

```
1. 用户在 Edge/Chrome 里人工登录
2. 关闭该浏览器
3. tools/browser/borrow-login.ps1 -Exe <同一浏览器 exe> -SourceUserData <User Data> -Url <站点>
4. node tools/browser/cdp-eval.mjs <port> @tmp/job.js    # 在已登录页面里调站点自己的 API
5. 用完销毁副本目录（-CloneDir，默认 tmp/borrowed-profile）
```

**验证登录态用键名，不要看页面长得像不像登录**：出现 `access_token` / `session` 一类键才算借到；
只有 `Optanon*` / `AMCV_*` / `s_nr` 这类统计项 = 没借到，漏了 `Local Storage`。

**不需要**给 chrome-devtools MCP 加 `--browserUrl` —— 那会把 MCP 绑死在副本上、还要重载 Host。
直接用 CDP 更轻（Node ≥ 22 自带 WebSocket，零依赖）。

## 删除规则（硬性，2026-09-14 事故后新增）

**只有用户明确通知删除的产物才能删。**

- **禁止**凭自动指标（连通域数、IoU、覆盖率、评分等）自行判定"失败"并删除产物 ——
  自动判据 ≠ 用户需求。曾因此误删用户已认可的 `leg2`（判据说"有合并"，但用户要的正是那个效果）。
- 要清理时**先列清单**（路径 + 体积 + 理由），**等用户确认后再删**。
- 用户说"清理临时文件"时，只清**可再生的中间态**，**不动**用户已认可或已指定的产物。
- 生成产物**一律先记 `job_id`**；误删后可用 `image-2-poll --job-id <id>` **免费**重新下载。
