# artstudio 工作区

> 路径均相对**工作区根**（= 本文件所在目录）；分隔符统一写 `/`，Windows / macOS 通用。
> 本文只写**工具怎么用**与**实测经验**。
> 产出面向 **Godot 4（≥ 4.4）**。
> **主方向 = 3D 角色管线**（2026-10 转型）：素材在 `assets/3d/`、工具在 `tools/3d/`；
> 2D 时代（Spine 包 / 拆件 / 换皮）的资料与任务已归档，当历史参考，**不要照着做**。

## 语言

默认工作语言：**中文**。文档、注释、与 agent 的对话一律中文；技术名词、文件名、API、标识符保留英文原文。

## 目录结构

| 路径 | 内容 |
|------|------|
| `docs/` | 文档（根下的 `*.md`）+ **外部参考仓库**（各子目录，自带 `.git`，按 `.gitignore` 的 `docs/*/` 整目录不入库）；由 `tools/reference-repos/pull.sh` 按 `tools/reference-repos/repos.list` 自动克隆 / 更新，加新参考仓库改清单即可 |
| `assets/3d/` | **3D 主方向资产台账**（`assets/3d/README.md`）。**入库**：`blend/`（103 份网格态 `.blend`，**44 MB**）、`textures/`（**共享贴图库 24 张 / 96.5 MB**）、`previews/`、`reports/`、`research/`、`manifests/`；**不入库（本地保留）**：`packs/`（可重下的源包 zip） |
| `assets/2d/` | **2D 时代资产**（已归档保留）：`eva_bone/` 原型拆件 + 各角色族（人形 / 兽人 / 精灵 / 恶魔 / 海族 / 虫族 / 半人马 / 野兽…）；当历史资料看，**不要照着做** |
| `assets/_archive/` | 更早的素材与一次性脚本（`source/`、`scripts/`、`metadata/`） |
| `meowa/` | AI 生图素材与预设（`templates/` 放 Meowa 预设信息） |
| `tools/` | **按场景分区的工具集**：**`3d/`（3D 角色资产：glTF/FBX→自包含 .blend / 试穿合成 / 批量断言 / Godot harness）**、`spine/`（图集修复 / 换皮 / 抽件，2D 时代）、`sprite/`（整图与部件本地处理）、`image-edit/`（图片编辑：本地 sd-server 免费 + ZenMux **唯一会花钱**）、`browser/`、`preview-2d/`、`reference-repos/`；根下 `*.py` 是**兼容转发 shim**（别删）。清单见 `tools/README.md` |
| `task/` | **任务档案**：**每个子任务一个文件夹** `NNN-slug/`（**入库**）；`TASK.md` 记目标 / 验收 / 状态 / 产出。**002~006（2D 时代）已归档**，新任务从 **007** 起。约定见 `task/README.md` |
| `tmp/` | **临时目录**：已忽略、不入库、可随时清 |
| `download/` | **刚下载、还没处理**的落地目录（源包解压树 `ubc/`、`modular-outfits-fantasy/`、研究用第三方 zip `research-zips/`、`convert/`）：已忽略、不入库，但**别随手清** |
| `.env`、`.git/`、`.claude/` | 凭据 / 仓库 / 本机 agent 配置 |

- **2D 时代任务（002~006）已归档并按要求删除本地归档包（2026-10-13）**：`archive-2d/` 目录与
  `tasks-2d.zip`（445 文件 / 37 MB）都不再保留 —— 任务已完成、可复用脚本已沉淀进 `tools/`，
  所以归档只剩追溯价值。需要追溯时：002~005 的目录内容仍在 **git 历史**里；
  **006（`006-spine-convert-batch`）从未入库**，其内容与随包的 tmp 快照
  （`帝国圣骑士变体` / `005-render` / `gen-1to5` / `verify-slot.png` / `slot_sheet.diff`）**已不再保留**。
  （历史上另有 `reference-2d.7z` / `docs-2d.7z` / `dressup-lab.7z` / `meowa-2d-docs.7z`，本机未留存。）
- **agent / CLI 的中间产物一律写 `tmp/`**（提交信息草稿、报告、预览图、浏览器 profile 副本…）；
  **不要落在 `docs/` / `tools/` / `meowa/` 等入库目录** —— 否则会跟着代码一起被提交。
- **刚下载、还没处理的东西写 `download/`**（素材包、第三方仓库、待转换资源），别塞进 `tmp/`：
  两者都不入库，但 `tmp/` 是**可随手的中间产物**，`download/` 是**还没决定去留的原始下载**（别随手清）。
- **一个子任务 = `task/` 下一个文件夹** `NNN-slug/`（**入库**）：`TASK.md` 记目标 / 验收标准 / 状态 / 产出 / 决策，
  任务自己的输入与产物留在该目录内（大二进制走 LFS），编号只加不改、不复用。
  过程性的临时文件仍写 `tmp/`，**别混进任务档案**；约定与模板见 `task/README.md`、`task/_template/TASK.md`。
- 大二进制走 **Git LFS**（图 / psd / 模型 / 归档 / 音视频）；`.md`、`.json`、代码不进 LFS，保持可 diff。规则见 `.gitattributes`。
  ⚠ **`*.bin` 不在 LFS 白名单**（只有 `.blend` / `.glb` / `.gltf` / `.fbx` / `.obj` / `.zip` / `.7z` / 图片等是）——
  所以 glTF 素材的**解压树不要入库**，解压树留在 `download/`、用时再 `unzip`。
- **资产存储策略（2026-10 起）：先"去重"，再谈"压缩"。**
  - **通用压缩对这批数据近乎无效**（实测：`.blend` 用 `zstd -19`/`xz -9e` 只省 **0.1%**、源包 zip 省 5%、PNG 省 2%）。
    **不要**做"整包压缩入库 + clone 解压 + 改完压回"：省不到 5%，还要吃"单文件 >100 MB 被拒 / 无增量 /
    每次改动多一个整包对象 / 无法 diff 合并"。
  - **真正的杠杆是去重**：原先 103 份 `.blend` 各自 pack 整套贴图 → 2147.6 MB（重复 ≈11.9×）；
    用 `tools/3d/dedupe_textures.py` 收敛成 **网格态 `.blend` 43.9 MB + 共享 `textures/` 96.5 MB ≈ 140 MB（−94%）**，
    几何指纹逐份一致（无损）。所以 **`assets/3d/blend/` 与 `assets/3d/textures/` 现在是入库的**，clone 即用。
  - **不入库**（`.gitignore`，本地保留）：`assets/3d/packs/`（上游可重下的源包 zip）、`download/` 解压树、
    `assets/2d/` 的 2D 素材。
  - 校验：`python3 tools/3d/run_check.py`（103/103）+ `tools/3d/make_manifest.py` 比 sha256；
    贴图改了要保证相对路径 `//../../textures/...` 仍可解析（checker 会报 `dangling`）。
  - 要"版本化 + 多人共享"更大体量时：用 **Cloudflare R2**（10 GB 免费额度、出网免费）或 B2 + `rclone`/`DVC`，
    仓库只留清单与指针；成本对比见 `tools/3d/README.md` 的存储策略一节。
  - `git lfs prune` 只回收**未被引用**的对象，而 **index（已暂存）也算被引用** ——
    要让大件真正让出空间，必须先把它们从索引撤下（`git rm -r --cached <路径>`，不动磁盘文件）再 prune。

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

## 生图 / 改图 CLI

| CLI | 场景 | 指南 |
|-----|------|------|
| **Meowa 生图 CLI** | 出**原画**：角色设定图 / 三视图、服装设计稿、配色与材质设定 | `docs/meowa-cli.md` |
| **本地图片编辑 CLI** | 图生图 / mask 局部重绘（**免费**：打 mini-local 局域网 sd-server，Qwen-Image-2.1） | `tools/image-edit/local-edit.md` |
| **ZenMux 图片编辑 CLI** | 在素材图上**标记若干部位，只重绘这些部位**：换一把武器 / 换一件衣服 / 改配色材质；**`tools/` 里唯一会花钱的脚本** | `docs/zenmux-cli.md`（深度口径 `tools/image-edit/zenmux-edit.md`） |

图片编辑的分工：**先 `local_edit.py` 免费试效果**（要 mini-local 上先 `./run-qwen-i2i.sh start`），
效果不满意再上 ZenMux 花钱；两者 mask 口径一致（涂白=要改），mask 文件可通用。

两条共同的硬约束（细节与实测经验见各自文档）：

- **一律在工作区根下执行** —— runner 从**执行命令的当前目录**读 `.env`，换目录就读不到 key。
- prompt **单行、不含任何引号字符**（PowerShell 会把双引号当分隔符）；用无引号结构化约束代替引号。
- **先免费预演、再花钱**：Meowa 先记 `job_id`（失败自动全额退费，**不要重复提交**）；
  ZenMux 先 `--dry-run` + `--min-credits 1`（**被网关掐断照样计费，工具无自动重试**）。

## tools/ 本地脚本

**纯本地、确定性、不消耗 AI 额度**（唯一例外：`image-edit/zenmux_edit.py` 走 ZenMux 生图，**消耗额度**；
`image-edit/local_edit.py` 联网但打的是 mini-local 局域网本地服务，**免费**）；
依赖 `numpy pillow opencv-python requests scipy`。**按业务场景分区**（一个场景一个子目录，跨场景不互相依赖），
完整口径见 `tools/README.md`，一眼版：

| 场景 | 脚本 | 一句话 |
|------|------|--------|
| **`3d/`**（主方向） | `pack2blend.py` | **批量 glTF/FBX → 自包含 `.blend`**：一个 spec 的 `jobs[]` 一次 Blender 进程串行转 N 份；贴图全 pack；坏引用重链（作者机器绝对路径 / `*_png` 错名）；可选网格布局；内嵌中文 README。口径见 `tools/3d/README.md` |
| | `build_tryon.py` | **试穿合成**：基础角色按顶点组裁成「只剩头部」+ 服装（+发型）合并到服装自带 65 骨 rig → 单 rig 可动画件 |
| | `check_blends.py` / `run_check.py` | **批量重开断言 + 联系表**（A 蒙皮件 65 骨全蒙皮 / B 静态件无骨架两套判据） |
| | `fix_blend_readme.py` | 只改 `.blend` 内文本块，并用几何+骨骼+贴图 sha256 自证几何未变 |
| | `godot/` | Godot 4.6 harness：运行时 `GLTFDocument` **零拷贝**换装、`.blend` 直读（Editor Setting + self-contained）、`SubViewport` 离屏渲染；⚠ 取骨用 `find_bone()`，跨路线索引会变 |
| **`spine/`** | `repair_spine/pipelines.py` | **图集体检 / 修复 / 重打包 / 渲染验收**（`diagnose` `pagefix` `unpack` `repack` `render` `verify` `meshfit` + 一条龙 `build` `prepare` `convert` `apply` `file`）；56 个已交付包共用，⚠ **改它必须先问用户**，口径见 `tools/spine/repair_spine/README.md` 与根目录 `Spine图集修复通用经验.md` |
| | `spine_part_swap.py` | `locate` 定位插槽可见区（→ mask/尺寸/附件四边形）、`verify` 换图重渲量化改动（远处应为 0px）—— 换皮流水线见 `tools/spine/spine-reskin.md` |
| | `spine_part_extract.py` | 出局部重绘的提交三元组（`extract --mode pair`：摘除件 + 原图置顶件 + 黑白 mask），`paste-back` 按 z 序（含覆盖表）贴回 |
| **`sprite/`** | `bbox_ref.py` | 由 bbox 规格生成比例参考图（喂 AI 当比例约束 / 当人工验收标尺） |
| | `alpha_split.py` | 按 alpha 连通域把整图拆成部件 |
| | `fit_parts.py` | 部件按 spec 比例缩放拼回原画布，并给出客观质量分 |
| | `slice-sheet.py` | 整张部件拼图 → 部件贴图（含脏像素清理 + 体检），见 `tools/sprite/slice-sheet.md` |
| | `outfit-split.py` | 服装拆件拼图 → 可换装件（输入须纯灰底 205） |
| | `outline-part.py` | 皮肤件补内描边（只改 RGB，不动 alpha）；幂等 |
| | `image_parts_tool.py` | 部件边缘精修一体化：`analyze` / `cut` / `prep` / `prompt` / `gen` / `verify` / `apply` / `report` / `diff` / `overview` |
| | `parts_sheet.py` | 把部件摆成**互不重叠、相邻 ≥N px** 的参考图（喂 AI 当"这些是独立零件"） |
| | `flatbg_cut.py` | 纯色底出图 → 抠成透明件 + 按参考部件 **alpha 最大 XY 等比缩放贴合**到原附件画布 |
| | `ps_cut/fill_from_layer1.jsx` | PS 里一键补缺口（文件 > 脚本 > 浏览） |
| **`image-edit/`** | `local_edit.py` | **本地图片编辑（免费）**：mini-local 的 sd-server（FastAPI **提交-轮询**：`/sdapi/v1/img2img` 提交 → `GET /jobs/{id}` 轮询；Qwen-Image-2.1），mask 局部重绘、seed/cfg/steps/sample_method 可调；口径见 `tools/image-edit/local-edit.md` |
| | `zenmux_edit.py` | **唯一会花钱**：mask 局部重绘（默认 Vertex AI `:predict`；**混元已于 2026-09-24 移除**），`--dry-run` / `--min-credits` 守卫；指南见 `docs/zenmux-cli.md`，完整口径见 `tools/image-edit/zenmux-edit.md` |
| | `tests/` | **mock 级 CLI 测试**：`python tools/image-edit/tests/test_zenmux_cli.py`（14 条命令级用例，约 6s，**全程 127.0.0.1、零真机零费用**）→ 口径见 `tools/image-edit/tests/README.md` |
| **`browser/`** | — | 浏览器登录态复用（CDP 副本，见下节） |
| **`preview-2d/`** | — | 2D 预览服务 |
| **根下 shim** | `repair_spine/pipelines.py` 等 4 个 | **兼容转发脚本，别删**：真正的文件已搬进场景目录，但已交付产物里写着旧路径（**105 份 `交付说明.md`**、`outline.json`…） |

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

## Git / LFS 治理（2026-10 里程碑）

**里程碑标签**：`milestone/3d-pivot-2026-10`。这次对历史做了一次性治理（远端已强推覆盖）：

| 指标 | 治理前 | 治理后 |
|---|---|---|
| `.git` | 475 MB | **205 MB**（LFS 444 → 199 MB，回收 4947 个 2D 时代 LFS 对象） |
| LFS 条目（全历史） | 5357 | **332**（3D 资产 + 少量杂项） |
| 提交数 | 50 | 48（2 个只有 2D 大件的提交被清空后自动剪掉） |
| 普通对象 | 30 MB | 5.2 MB |

做法：`git filter-repo --invert-paths --path assets/2d --path assets/eva_bone --path assets/武僧`
（保留全部提交信息，只从历史里剔除 2D 大件）→ 删旧引用 → `git gc --prune=now` → `git lfs prune`。

**两条硬教训（都实际踩到了）**：

1. **强推前必须先 `git fetch`** —— 本次发现远端 `main` 领先本地一个提交（`154ede5`，10-11 在**另一台机器**推的
   2D 收尾：`task/005` 的 4 个脚本 + `repos.list`）。直接强推就会把它抹掉。
   处置：先 `git rebase -X theirs origin/main` 把本地提交叠上去，再用
   `git push --force-with-lease=refs/heads/main:<远端实际 sha>` 推送（lease 能防"推的时候远端又变了"）。
2. **`git rm --cached` 只是"不入库"，但一旦之后 checkout / rebase / 重写历史切换提交，Git 会把
   "旧提交里跟踪、新提交里没有"的文件从工作树删掉**（`.gitignore` **拦不住**）。
   本次 `assets/2d` 的 **5423 个曾入库文件被删**（磁盘 537 M → 270 M），已从远端旧提交恢复：
   ```bash
   git checkout <旧提交> -- assets/2d     # 取回（LFS 内容走本地对象库，无需联网）
   git reset -q HEAD -- assets/2d         # 退回"本地保留、不入库"状态
   ```
   → **规则**：把大件移出 git 之前，先确认存在**独立物理副本**（远端旧历史 / 备份 / 另一份拷贝）。

**备份口径（两种都要，缺一不可）**：

- `git bundle create <路径> --all` —— 只含 **git 对象（指针）**，**不含 LFS 内容**（本次 bundle 仅 7.3 MB）。
- 单独复制 **`.git/lfs`** —— LFS 实体内容（本次 442 MB）。
- 本次备份位置：`~/Desktop/artstudio-pre-rewrite2-*.bundle`、`~/Desktop/artstudio-lfs-backup-*/lfs`、
  `~/Desktop/artstudio-task005-from-remote-20261013.zip`（确认无误后可自行删除）。

**远端 LFS 配额注意**：强推**不会**释放 GitHub 上已上传的 LFS 对象（那 253 MB 的 2D 对象仍计入配额）。
要让远端 LFS 归零，只能**删除并重建仓库**（或联系 GitHub 支持）；当前占用 ≈442 MB，免费额度 10 GiB 足够，
故不折腾。克隆成本：git 层 6.3 MB + 当前提交的 LFS ≈200 MB。

## 删除规则（硬性，2026-09-14 事故后新增）

**只有用户明确通知删除的产物才能删。**

- **禁止**凭自动指标（连通域数、IoU、覆盖率、评分等）自行判定"失败"并删除产物 ——
  自动判据 ≠ 用户需求。曾因此误删用户已认可的 `leg2`（判据说"有合并"，但用户要的正是那个效果）。
- 要清理时**先列清单**（路径 + 体积 + 理由），**等用户确认后再删**。
- 用户说"清理临时文件"时，只清**可再生的中间态**，**不动**用户已认可或已指定的产物。
- 生成产物**一律先记 `job_id`**；误删后可用**对应的** `*-poll --job-id <id>`（`image-2.5-poll` / `image-2-poll` / `nano-banana-poll`）**免费**重新下载。
