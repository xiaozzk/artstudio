# 2D 预览图浏览器

针对 `assets/2d/` 下所有 `复原预览图*.png` 的本地 Web 预览工具。

## 文件

```
tools/preview-2d/
├── preview.html          # 单文件 Web 应用（HTML + CSS + 内嵌 JS）
├── preview-manifest.json # 由 serve.py 生成，扫描结果的结构化清单
├── serve.py              # 启动脚本：扫描 → 写 manifest → 起 http.server → 开浏览器
├── start.bat             # 一键启动（cmd / 双击）：纯 ASCII，避免 cmd 编码问题
├── start.ps1             # 一键启动（PowerShell）：中文消息 + PowerShell 命名参数
└── README.md             # 本文档
```

## 一键启动

### 在文件资源管理器里双击

| 用户 | 双击 | 备注 |
|------|------|------|
| cmd / 资源管理器 | `start.bat` | 默认探测 `python` 或 `py` 解释器；纯英文输出 |
| PowerShell | `start.ps1` | 中文输出 + 彩色 banner；首次需要响应执行策略 |

### 从命令行调用

**cmd / PowerShell 通用（推荐先试这种）**：

```powershell
.\tools\preview-2d\start.bat                        # 等价于 python tools/preview-2d/serve.py
.\tools\preview-2d\start.bat --no-browser
.\tools\preview-2d\start.bat --port 9000
```

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

两者做的事完全一致：`切到工作区根 → 探测 Python → 调 serve.py`。

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
