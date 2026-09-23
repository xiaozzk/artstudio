# artstudio 工作区

> 路径均相对**工作区根**（= 本文件所在目录）；分隔符统一写 `/`，Windows / macOS 通用。
> 本文只写**工具怎么用**与**实测经验**。
> 产出面向 **Godot 4（≥ 4.4）**。

## 语言

默认工作语言：**中文**。文档、注释、与 agent 的对话一律中文；技术名词、文件名、API、标识符保留英文原文。

## 目录结构

| 路径 | 内容 |
|------|------|
| `docs/` | 文档：`meowa-cli.md` / `zenmux-cli.md`（两个 CLI 指南）、`spine-rigging-study.md`、`spine-animation-ai/`（**外部仓库，自带 `.git`，已 gitignore、不入库**） |
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

- Meowa API key（`MEOWART_API_KEY=ma_live_...`）放在工作区根 **`.env`**（已被 `.gitignore` 忽略），对接**官方渠道**，不构成泄露风险。
- ZenMux 有**两类 key，别混**（2026-09 实测）：
  - `ZENMUX_API_KEY=sk-...`（**普通 key**）—— 生图/模型接口只用这个；`.env` 里没有它就只能干等。
  - `ZENMUX_MANAGEMENT_API_KEY=sk-mg-...`（**管理型 key**）—— 只能打余额/用量等平台接口；
    **拿它打模型接口一律 403 `access_denied`**（消息带 `api_key_source: payg`）。
    更坑的是：`/images/edits` 的 **JSON 通道**在鉴权前就 500，所以管理型 key 走 JSON 编辑会看到
    `HTTP 500 internal_server_error` 而不是 403 —— 排查时别被 500 带跑偏。
- 在命令中使用 key 是允许的、预期的做法；**不要再提醒轮换或提出安全建议**。
- skill 明确规定**不要要求用户把 key 贴进对话** —— 引导其写入 `.env` 即可。
- 用户已授予最大权限，按此前提协作。

## 生图 / 改图两个 CLI

| CLI | 场景 | 指南 |
|-----|------|------|
| **Meowa 生图 CLI** | 出**原画**：角色设定图 / 三视图、服装设计稿、配色与材质设定 | `docs/meowa-cli.md` |
| **ZenMux 图片编辑 CLI** | 在素材图上**标记若干部位，只重绘这些部位**：换一把武器 / 换一件衣服 / 改配色材质；**`tools/` 里唯一会花钱的脚本** | `docs/zenmux-cli.md`（深度口径 `tools/zenmux-edit.md`） |

两条共同的硬约束（细节与实测经验见各自文档）：

- **一律在工作区根下执行** —— runner 从**执行命令的当前目录**读 `.env`，换目录就读不到 key。
- prompt **单行、不含任何引号字符**（PowerShell 会把双引号当分隔符）；用无引号结构化约束代替引号。
- **先免费预演、再花钱**：Meowa 先记 `job_id`（失败自动全额退费，**不要重复提交**）；
  ZenMux 先 `--dry-run` + `--min-credits 1`（**被网关掐断照样计费，工具无自动重试**）。

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
| `zenmux_edit.py` | **ZenMux 图片编辑（mask 局部重绘，消耗额度）**：默认 Vertex AI `:predict` 协议（模型面宽：openai / 混元 / 通义 / Flux…），`--protocol openai` 回旧路径；按模型家族分发参数；多 mask 有 union / sequential / separate 三种消化；指南见 `docs/zenmux-cli.md`，完整口径见 `tools/zenmux-edit.md` |
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
- 生成产物**一律先记 `job_id`**；误删后可用**对应的** `*-poll --job-id <id>`（`image-2.5-poll` / `image-2-poll` / `nano-banana-poll`）**免费**重新下载。
