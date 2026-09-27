# 2D 预览图浏览器

针对 `assets/2d/` 下所有 `复原预览图*.png` 的本地 Web 预览工具。
**2026-09-24 起同时是 Spine 作品预览器**：卡片带「🎬 N 动画 · M 骨骼 · K 皮肤」徽标，
点「骨骼预览」开全屏官方 player（切动画 / 切皮肤 / 调速 / 全屏 / 骨骼调试）。

## 文件

```
tools/preview-2d/
├── preview.html          # 单文件 Web 应用（HTML + CSS + 内嵌 JS）
├── preview-manifest.json # 由 serve.py 生成，扫描结果的结构化清单（含 spine_index）
├── serve.py              # 启动脚本：扫描 → 写 manifest → 起 http.server → 开浏览器
├── vendor/spine-player/  # 官方 @esotericsoftware/spine-player@4.3.13 本地化（离线可用）
├── start.bat             # 一键启动（cmd / 双击）：纯 ASCII，避免 cmd 编码问题
├── start.ps1             # 一键启动（PowerShell）：中文消息 + PowerShell 命名参数
├── start.command         # 一键启动（macOS）：Finder 可双击，终端可直跑，参数透传
└── README.md             # 本文档
```

## Spine 预览

- 扫描时按**内容嗅探**识别骨架 json（顶层有 `skeleton`+`bones` 键，不看文件名——
  交付包文件名常与目录名不一致，如「法袍法师/Magic Gril.json」）。
- 图集页解析注意：libgdx 新版 atlas 页头字段顺序不固定（实测有 `filter` 在 `size`
  前面的），**不能**用「下一行是 size:」判定页名行。
- player config 的 4.3 字段名是 `skeleton` / `atlas`（4.2 是 `jsonUrl`/`atlasUrl`，
  写错报 "A URL must be specified for the skeleton JSON or binary file"）。
- 全部 105 个交付包统一 4.3.26，vendor 的 4.3.13 runtime 全兼容（patch 级无所谓）。
- 皮肤/动画切换用 player 控制条自带 UI（多皮肤时才出现 skin 按钮），不用自造。
- **实验产物预览**（2026-09-25）：`task/*/output/<包名>/` 下含骨架+atlas 的目录
  会被扫进 `spine_index`，key 形如 `实验/<task>/<包名>`，前端在列表末尾的
  「实验产物」区出无图卡片；`url_prefix` 指向包目录（assets 包用 `/assets/2d/`，
  实验包用自己目录）。动画迁移产物由此可在 preview-2d 里直接验收。

## 一键启动

### 在文件资源管理器里双击

| 用户 | 双击 | 备注 |
|------|------|------|
| cmd / 资源管理器 | `start.bat` | 默认探测 `python` 或 `py` 解释器；纯英文输出 |
| PowerShell | `start.ps1` | 中文输出 + 彩色 banner；首次需要响应执行策略 |
| macOS Finder | `start.command` | 中文输出 + 彩色 banner；双击后在 Terminal 里运行 |

### 从命令行调用

**cmd / PowerShell 通用（推荐先试这种）**：

```powershell
.\tools\preview-2d\start.bat                        # 等价于 python tools/preview-2d/serve.py
.\tools\preview-2d\start.bat --no-browser
.\tools\preview-2d\start.bat --port 9000
```

**macOS / 终端（`start.command`，也可用 sh/bash 跑，兼容 Linux）**：

```bash
./tools/preview-2d/start.command                    # 默认开浏览器，按 Ctrl+C 停止
./tools/preview-2d/start.command --no-browser       # 不开浏览器
./tools/preview-2d/start.command --port 9000
./tools/preview-2d/start.command --host 0.0.0.0     # 暴露给局域网
./tools/preview-2d/start.command scan               # 只扫描 + 写 manifest
```

> Python 探测顺序：PATH 里的 `python3`（pyenv / Homebrew / CLT）→ `python` →
> Homebrew 固定路径（`/opt/homebrew`、`/usr/local`）→ `/usr/bin/python3`
> （仅在 CLT 已装时启用，避免触发「安装开发者工具」弹窗）。
> 双击后窗口一闪而过或 Finder 只打开编辑器，多半是执行位丢了：
> `chmod +x tools/preview-2d/start.command` 修一次即可。

**PowerShell 专属（更强类型）**：

```powershell
.\tools\preview-2d\start.ps1                        # 默认开浏览器
.\tools\preview-2d\start.ps1 -NoBrowser             # 不开浏览器
.\tools\preview-2d\start.ps1 -Port 9000
.\tools\preview-2d\start.ps1 -Address 0.0.0.0       # 暴露给局域网
```

> **执行策略提示**：如果双击 `start.ps1` 被系统阻止，第一次在 PowerShell 里执行：
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
> 或绕过单次执行：
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\tools\preview-2d\start.ps1
> ```

三者做的事完全一致：`切到工作区根 → 探测 Python → 调 serve.py`。

## 手动启动

仍然可以直接跑 Python：

```powershell
python tools/preview-2d/serve.py                    # 默认：扫描 + 起服务 + 开浏览器
python tools/preview-2d/serve.py scan               # 只扫描 + 写 manifest，不起服务
python tools/preview-2d/serve.py serve --no-browser --port 9000 --host 0.0.0.0
```

脚本会：

1. 扫描 `assets/2d/**/复原预览图*.png`，按 `category / gender / character / variant` 组织
2. 写入 `tools/preview-2d/preview-manifest.json`
3. 在工作区根启动 `python -m http.server`（端口自动从 8000 起找空闲端口）
4. 1.5 秒后用默认浏览器打开预览页

按 **Ctrl + C** 即可停止服务。

如果只想生成清单、不启服务：

```powershell
python tools/preview-2d/serve.py scan
```

## 选项

| 选项 | 说明 |
|------|------|
| `--port <n>` | 指定端口（已被占用会找下一个空闲端口） |
| `--host <addr>` | 绑定地址，默认 `127.0.0.1`；要暴露局域网写 `0.0.0.0` |
| `--no-browser` | 不自动打开浏览器 |

## 何时需要重新扫描

下列任一情况都需要重跑 `serve.py` 让浏览器刷新清单：

- 新增 / 删除了某个 `复原预览图*.png`
- 把角色目录挪到了别的 `category / gender` 下
- 给某个角色加了新变体（如 `复原预览图_skin2.png`）

预览页右上角的 `↻` 按钮只刷新**清单**，不重新扫描。

如果只想看当前清单的某个新角色图片，理论上只要新文件已经在 `assets/2d/` 下，重扫后刷新页面即可。
浏览器有 `loading="lazy"` + `cache`，同一图片路径（`assets/2d/<category>/<gender>/<character>/<filename>`）一般会复用缓存。

## 网页操作

- **筛选**：分类 / 性别 chips；搜索框匹配角色名与路径片段（不区分大小写）
- **卡片**：点击缩略图打开大图（Lightbox）
- **Lightbox**：
  - 左右方向键 / 上下张按钮切换
  - Esc / ✕ 关闭
  - 点击图片本身 = 下一张（沿用图片查看器惯例）
- **快捷键**：`/` 聚焦到搜索框

## 设计说明

- **数据驱动**：HTML 只负责渲染；图片清单完全来自 `preview-manifest.json`，便于以后接入其它格式
- **单文件**：单 HTML 部署友好，复制该文件到别处只需同时复制 `preview-manifest.json`
- **路径约定**：HTML 在 `/tools/preview-2d/` 下；图片用绝对路径 `/assets/2d/...`。HTTP server 工作目录固定在工作区根，因此图片 / manifest 都能直接通过 URL 取到
- **端口自动避让**：避免和已经在跑的 `python -m http.server` 撞端口

## 故障排查

| 症状 | 原因 / 处理 |
|------|------|
| 打开页面显示「清单加载失败」 | 没跑过 `serve.py`；先跑一次 |
| 图片全部 404 | HTTP server 工作目录不在工作区根；确认用 `serve.py` 而不是手动 `python -m http.server` 时没切目录 |
| 浏览器没自动打开 | `serve.py` 默认会开；用了 `--no-browser` 就不会开；下次去掉即可 |
| 端口冲突 | `--port <空闲端口>`；或 `serve.py` 会自动从 8000 找下一个空闲端口 |
| 大图打开慢 | 单图最大 2 MB 左右；浏览器串行解码无压力，按需滚动即可 |
