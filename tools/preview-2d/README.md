# 2D 预览图浏览器（preview-2d）

本地 Web 预览工具：**多个「预览库」用下拉切换**，库内**只按关键字筛选**，卡片是浏览器里
**实时渲出来的**静态图，点卡片开全屏官方 player（切动画 / 切皮肤 / 调速 / 骨骼调试）。

> **2026-09-27 改造**：从「固定扫 `assets/2d` 的复原预览图 + 分类/性别筛选」改成
> **多库 + 关键字筛选 + 实时渲染**：
> - **多库**：下拉切换；可「＋ 新建目录」登记任意磁盘目录；可「📥 导入资源」复制文件/文件夹进来。
>   导入落点固定是独立目录 `download/preview-2d-imports/`，**默认库 `assets/2d` 服务端拒绝写入**。
> - **成组只看 spine 骨架 json**（`xxx.json` + `xxx.atlas` 成对）：预览图、部件图、图集页一概不收，
>   也不再统计图片数。
> - **画面实时渲**：定格渲染，不读文件夹里离线渲好的 PNG。
> - **去掉分组与目录/子目录筛选**：平铺网格，卡片名就是完整路径，只留关键字搜索框。

## 文件

```
tools/preview-2d/
├── preview.html          # 单文件 Web 应用（HTML + CSS + 内嵌 JS）
├── preview-manifest.json # 由 serve.py 生成：各库的扫描结果
├── libraries.json        # 预览库清单（内置 3 个 + 用户自建；可手改）
├── serve.py              # 扫描 → 写 manifest → 起内置 HTTP 服务 → 开浏览器
├── vendor/spine-player/  # 官方 @esotericsoftware/spine-player@4.3.13 本地化（离线可用）
├── start.bat             # 一键启动（cmd / 双击）：纯 ASCII，避免 cmd 编码问题
├── start.ps1             # 一键启动（PowerShell）：中文消息 + PowerShell 命名参数
├── start.command         # 一键启动（macOS）
└── README.md             # 本文档
```

## 预览库（library）

**一个库 = 一个磁盘目录**，扫描结果彼此独立，网页顶部用下拉切换。
配置存在 `libraries.json`（`id / name / kind / path / builtin`）。

| 库 | kind | 路径 | 说明 |
|----|------|------|------|
| `assets/2d` | `default` | `assets/2d` | 默认库，**只读**：不允许往里导入 |
| `导入资源` | `import` | `download/preview-2d-imports` | 导入落点，与默认库**分开** |
| `实验产物` | `task` | `task/*/output/<包名>/` | 虚拟库：只收含骨架+图集的实验包 |
| （自建） | `custom` | 任意磁盘目录 | 「＋ 新建目录」创建，`⚙` 里移除 |

- 库 id 由**路径哈希**生成：同一目录反复登记得到同一个 id，URL / 下拉状态重启后不丢。
- 移除库**只改配置，不删磁盘文件**；内置库不可移除（缺了会自动补回）。
- `download/preview-2d-imports/` 属于工作区约定里的「原始落地目录」：不入库、别随手清。

## 网页操作

| 控件 | 作用 |
|------|------|
| **预览库** 下拉 | 切换库，括号里是组数 / 动画数 |
| **＋ 新建目录** | 填磁盘路径 → 不存在就创建、已存在就登记；默认填 `D:/artstudio/assets/2d` |
| **📥 导入资源** | 选**文件夹**或**多个文件** → 复制进目标库（保留子目录结构），带进度条，完成后自动重扫并切过去 |
| **⚙ 管理** | 看所有库（类型 / 路径 / 数量），移除自建库 |
| **搜索框** | 唯一筛选维度：匹配完整路径 / 骨架文件名（不区分大小写），带 120ms 防抖 |
| **↻** | **真的重扫磁盘**并刷新（不是只刷清单） |
| 卡片 | 点缩略图 = 全屏播动画；右下「🦴 骨骼」是徽标，「骨骼预览」按钮同效 |

**不做分组**：平铺网格，卡片名称就是**完整路径**（如 `恶魔/男/哪吒童`），目录层级信息
全在名字里。快捷键：`/` 聚焦搜索框、`Esc` 关弹层 / 全屏预览。

## 卡片的画面：实时静态渲染，不读文件夹里的 PNG

**成组只看骨架 json**（`xxx.json` + `xxx.atlas`）：预览图、部件图、图集页一概不收。
卡片上的人物是**浏览器里实时渲出来的**——每个插槽的附件按它当时的世界位置画一帧，渲完存成位图。
网格里不会动、也不留 player 跑动画；点卡片 = 同一份数据的全屏动画播放。

### 并行度：先看你自己的机器

缩略图走一个并发池（`THUMB_CONCURRENCY`，谁先完成谁先让位）。**别照抄数字**：官方 player
每个实例都自带一个 WebGL 上下文 + 一条独立 rAF 渲染循环，并行数上去是先撞渲染进程：

| 并行数 | 本机实测 |
|--------|----------|
| 10 | 渲染进程崩溃（标签页变 `about:blank`，重开再复现） |
| 5 | 页面卡死（连读一个文本都 275s 超时）——但测量时浏览器已被上一次的崩溃搞脏，不算干净结论 |
| **3** | 稳定，105 组缩略图正常出图（默认就取这个） |

最快的健康检查：在页面里让脚本读一下顶栏统计（`document.querySelector('#stats')`），
秒回就是没卡死。想提速又不想多占 WebGL 上下文，更稳的路子是**预取**——渲染当前包时提前把下一个包的
json / atlas / png 抓下来（fetch 不占上下文），能把大部分等待时间吃掉。

### 皮肤

有多套皮肤时**默认加载第一个**（与 runtime 自己的默认行为一致），缩略图与全屏预览都显式传
`skin: <第一个皮肤名>`。

### 踩过的坑（都写在 preview.html 的注释里）

| 坑 | 现象 | 结论 |
|----|------|------|
| **纯 setup pose** | 附件挂上了、骨骼和包围盒都对，**墨迹仍 0%** | 交付件槽位 json 大多没写 `attachment` 字段，美术在皮肤 + 动画的 attach/transform timeline 里。必须让 player 先应用一次动画才有像素 —— 所以传第一个动画，但只用于初始化 + 取定格帧，随即 `pause()` |
| **定格写法** | — | 照抄 player 时间轴的 seek：`animationState.update(目标 - playTime)` + `apply(skeleton)` + `pause()`，定格在第一个动画的 10% 处 |
| **`slot.attachment` 不可信** | 永远是 null | 渲染读的是 `slot.appliedPose.attachment`；`slot.setAttachment` 也不是方法 |
| **`mipmaps:false`** | 截出来只有背景色 | vendor 里 `page.texture.update(true)` 只在 minFilter 既不是 Nearest 也不是 Linear 时调用；关掉 mipmaps 后 minFilter 就是 Linear → 纹理永不上传 |
| **只靠 rAF** | 后台标签里缩略图永远空白 | 最后主动 `drawFrame(false)` 同步渲一帧再截 |
| **手动覆盖 `currentViewport`** | 整张渲空 | 看着更稳的"自己算紧边界"反而让墨迹归零；沿用 player 自己按动画算的视口最稳 |
| **截完要判空** | 少数包留黑砖 | 32×32 采样算非背景像素占比，低于 0.4% 就明说「无法自动取景 · 点开可看」 |

### 已知的 3 个例外（查过，没找到根因）

`火把哥布林`、`矛枪哥布林`、`骑猪勇者` 渲不出缩略图。**已逐项排除**，实测结论：

- **不是缩略图逻辑的问题**：这三个包点开「骨骼预览」全屏播放**同样一片空白**（顶栏的动画/骨骼/皮肤数
  都正常，动画列表也加载出来了，就是画面区 0 像素）。只有 3.8 时代的离线 Python 渲染器能出图。
- **json 与 atlas 数据是干净的**：无 NaN/Infinity、无 linkedmesh / mesh / deform 轨道、
  骨骼 parent 全部存在、无重名、槽位与皮肤引用一致、atlas region 与附件的 `name` 字段全部对得上、
  页尺寸 / pma / filter 与正常包一致。
- **可疑点**：这几个包 `skins[0]`（default 皮肤）里**只有 3.8 的 point 锚点**（`center` / `face` /
  `floor` / `health_bar` / `launch_point`），美术全在具名皮肤（`skin2` / `skin4` / `skin5`），
  json 又没写 `defaultSkin` 字段 —— runtime 就落到空壳皮肤上。全库有 10 个包是这种结构，
  其中 7 个渲染正常，所以这只是必要条件不是充分条件。**显式指定别的皮肤也救不回来**
  （试过传「附件最多的皮肤」，缩略图与全屏两处都传了，这 3 个仍然空白）。
- 顺带：`type: "point"` 附件（3.8 遗留，4.x 里只服务于 point constraint）实测**不是**元凶 ——
  把它从 json 里删掉，这三个包照样空白；而另外 2 个带 point 附件的包（旋风勇者 / 电弓战将）渲染正常。

要彻底解决得从数据侧入手（补 `defaultSkin`、或让 4.x 转换时把 point 锚点转成 point constraint /
命名骨），这属于改交付件，要先确认口径。当前页面对这类包明写「无法自动取景 · 点开可看」，
点开仍能进全屏预览（虽然也是空的）。**要不要给它们加"退回用 `复原预览图.png`"的兜底，你说一声我就加。**

## 启动

### 双击

| 用户 | 双击 | 备注 |
|------|------|------|
| cmd / 资源管理器 | `start.bat` | 默认探测 `python` 或 `py`；纯英文输出 |
| PowerShell | `start.ps1` | 中文输出 + 彩色 banner；首次需响应执行策略 |
| macOS Finder | `start.command` | 双击在 Terminal 里运行 |

### 命令行

```powershell
.\tools\preview-2d\start.bat                      # = python tools/preview-2d/serve.py
.\tools\preview-2d\start.bat --no-browser
.\tools\preview-2d\start.bat --port 9000
python tools/preview-2d\serve.py scan             # 只扫描 + 写 manifest
python tools/preview-2d\serve.py scan --lib 导入资源   # 只扫一个库（写出的 manifest 是局部的！）
```

| 选项 | 说明 |
|------|------|
| `--port <n>` | 指定端口（占用则自动往后找） |
| `--host <addr>` | 绑定地址，默认 `127.0.0.1`；要暴露局域网写 `0.0.0.0` |
| `--no-browser` | 不自动开浏览器 |
| `--lib <id/名字/路径>` | 只扫描指定库（可重复）。**会覆盖成局部 manifest** |

`scan` 会按库打印全量包速览（版本 / 动画数 / 骨骼 / 皮肤），`tools/spine/anim/SKILL.md`
的选包流程直接读这段输出。

## HTTP 接口（页面自己用，也能脚本化）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/tools/preview-2d/preview-manifest.json` | 清单（只服务这一个目录） |
| GET | `/@lib/<库id>/<库内相对路径>` | 库内文件（图片 / 骨架 / atlas），支持任意磁盘路径的库 |
| GET | `/api/manifest` | 同清单（内存版，不落盘时间戳） |
| POST | `/api/rescan` `{"lib": "<id>"}` | 重扫（不传 lib = 全扫），返回新清单 |
| POST | `/api/library/add` `{"path": "...", "name": "..."}` | 新建/登记目录，返回新清单 |
| POST | `/api/library/remove` `{"id": "..."}` | 只从清单移除，不删文件 |
| POST | `/api/import` | 导入单文件：请求体 = 文件原始字节，头带 `X-Lib-Target` / `X-File-Path`（URL 编码的库内相对路径） |

导入是**一个文件一个请求**（不是 multipart）：天然流式、能逐文件报进度、失败可定位到具体文件。

安全边界（都实测过）：

- 静态只服务 `/tools/preview-2d/`，`.env` / `.git` / 仓库其它内容一律 404
  （旧版用 `http.server --directory <工作区根>`，等于把整个仓库连 `.env` 一起端出去了）。
- 所有库文件路径都做过 `..` 穿越校验。
- **默认库 `assets/2d` 拒绝写入**（HTTP 400），实验产物库是虚拟的也不可写 —— 导入只能落独立目录。
- 新建目录拒绝把工作区根、`tools/`、`.git` 本身登记成预览库。

## Spine 预览

- 扫描时按**内容嗅探**识别骨架 json（顶层有 `skeleton`+`bones` 键，不看文件名——
  交付包文件名常与目录名不一致，如「法袍法师/Magic Gril.json」）。
- 图集页解析注意：libgdx 新版 atlas 页头字段顺序不固定（实测有 `filter` 在 `size`
  前面的），**不能**用「下一行是 size:」判定页名行。
- player config 用 4.3 字段名 `skeleton` / `atlas`（4.2 是 `jsonUrl`/`atlasUrl`，
  写错报 "A URL must be specified for the skeleton JSON or binary file"）。
- 105 个交付包统一 4.3.26，vendor 的 4.3.13 runtime 全兼容（patch 级无所谓）。
- 皮肤/动画切换用 player 控制条自带 UI（多皮肤时才出现 skin 按钮），不用自造。

## 故障排查

| 症状 | 原因 / 处理 |
|------|------|
| 打开页面显示「清单加载失败」 | 没跑过 `serve.py`；先跑一次 |
| 某个包没出现 | 它的目录里没有 `xxx.json` + `xxx.atlas` 成对（成组只看骨架） |
| 卡片显示「无法自动取景」 | 该骨架在 JS runtime 里算出非有限变换，自动取景救不回来；点卡片仍能播动画 |
| 图片/骨架 404 | 库里目录被挪过 → 按 `↻` 重扫；库目录被删 → 下拉里会标红「目录不存在」 |
| 导入没反应 | 目标库是不是默认库 `assets/2d`（只读，服务端会 400 拒绝）；换一个可写库 |
| 缩略图整页加载慢 | 每个包首次都要载 json+atlas+图集页（几百 KB~2MB）；渲好的位图有缓存，滚回去不重载 |
| 端口冲突 | `--port <空闲端口>`；或自动从 8000 找下一个 |
| 改了 `libraries.json` 没反应 | 重启 `serve.py`（配置只在启动时读入） |
