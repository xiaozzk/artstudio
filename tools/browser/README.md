# tools/browser/ — 借登录态到可丢弃的 CDP 浏览器

> 命令均在**工作区根**下执行；本文路径均为相对路径，分隔符统一写 `/`，Windows / macOS 通用。

**用途**：你在日常浏览器里人工登录了某站点，agent 需要**借用**这个登录态做自动化 ——
但既不能污染你的真实 profile，也不该让你重新登录一次。

做法不是让 MCP 接管你的浏览器，而是：**复制一份可丢弃的 profile 副本 → 用同一个 exe 带 CDP 端口启动 → 用完删除。**

## 三个硬前提

每个都推翻了一个想当然的假设，实测踩过：

| # | 坑 | 事实 | 后果 |
|---|----|------|------|
| 1 | **ABE 绑定应用身份** | Chromium 的 App-Bound Encryption 把 cookie 密钥绑定到 exe **路径 + 签名** | Edge 的 cookie 搬到 Chrome **解不开**；换程序直接读也解不开。**必须用同一个 exe** |
| 2 | **登录态未必在 cookie** | 很多 SPA 把 session 放在 `Local Storage`（leveldb）里 | 只复制 `Cookies` 会白干。实测 Mixamo 的 session 是纯 `localStorage.access_token`。**顺带一提：leveldb 不加密、不受 ABE 影响 —— 真正能搬的恰恰是它** |
| 3 | **运行中文件被独占锁定** | 浏览器运行时的 `Cookies` 连 `FileShare.ReadWrite\|Delete` 都打不开 | 普通复制失败，`robocopy /b` 备份模式同样失败（exit 8）。**先关浏览器**；管理员可用 **VSS 卷影快照**绕过（只读快照不受锁约束） |

## 流程

```
1. 你在 Edge/Chrome 里人工登录目标站点
2. 关闭该浏览器                      ← 不关就会卡在坑 3
3. borrow-login.ps1 复制 profile 并用同一 exe 启动副本（带 CDP 端口）
4. cdp-eval.mjs 在已登录页面上下文里跑 JS / 调站点 API
5. 用完销毁副本目录
```

### 3. 复制并启动

先关掉浏览器，然后在**工作区根**下执行。`-Exe` 与 `-SourceUserData` 按平台给：

**Windows（Chrome）**

```powershell
tools/browser/borrow-login.ps1 `
  -Exe "$env:ProgramFiles/Google/Chrome/Application/chrome.exe" `
  -SourceUserData "$env:LOCALAPPDATA/Google/Chrome/User Data" `
  -Url "https://example.com/"
```

**Windows（Edge）**

```powershell
tools/browser/borrow-login.ps1 `
  -Exe "$env:ProgramFiles(x86)/Microsoft/Edge/Application/msedge.exe" `
  -SourceUserData "$env:LOCALAPPDATA/Microsoft/Edge/User Data" `
  -Url "https://example.com/"
```

**macOS（Chrome）**

```bash
pwsh tools/browser/borrow-login.ps1 \
  -Exe "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  -SourceUserData "$HOME/Library/Application Support/Google/Chrome" \
  -Url "https://example.com/"
```

> `-Exe` 与 `-SourceUserData` 是**唯一**需要外来绝对路径的参数 —— 它们指向浏览器安装位置和用户数据，
> 本来就不在工作区内。两者必须属于**同一个浏览器**，否则 App-Bound Encryption 会拒绝解密。

其余参数都有默认值：`-ProfileDirectory`（`Default`）、`-CloneDir`（`<工作区根>/tmp/borrowed-profile`）、
`-Port`（`9222`）、`-Force`（源浏览器仍在运行时强行复制，默认拒绝）。

脚本会复制这几样，**缺一不可**：

```
Local State                        ← 加密密钥（ABE 引用）
Default/Network/Cookies            ← 部分站点的 session
Default/Local Storage              ← ← 很多 SPA 的真登录态在这
Default/Session Storage
Default/IndexedDB
Default/Storage
Default/Preferences
```

### 4. 在页面上下文执行

```bash
# 直接写表达式
node tools/browser/cdp-eval.mjs 9222 "return document.title"

# 从文件读（推荐，避免 PowerShell 引号地狱）
node tools/browser/cdp-eval.mjs 9222 @tmp/job.js

# 多标签页时按 URL 挑
node tools/browser/cdp-eval.mjs 9222 @tmp/job.js --url mixamo
```

`cdp-eval.mjs` 把内容包成 `(async () => { ... })()` 执行，所以 **可用 `await`，要返回值就 `return`**。
因为在目标 origin 的页面里跑，`fetch` 自动带 same-origin 凭据 —— **不用手动搬 token**。

### 5. 销毁

```bash
rm -rf tmp/borrowed-profile          # macOS / Linux
```

```powershell
Remove-Item tmp/borrowed-profile -Recurse -Force    # Windows
```

## 验证登录态是否真的借到了

不要只看页面长得像登录了。**看 localStorage / cookie 的键名**：

```bash
node tools/browser/cdp-eval.mjs 9222 "return { ls: Object.keys(localStorage), cookie: document.cookie.split(';').map(s=>s.trim().split('=')[0]) }"
```

- 出现 `access_token` / `session` / `token` 之类的键 → 借到了
- 只有 `Optanon*`、`AMCV_*`、`s_nr` 这类统计项 → **没借到**，说明漏复制了 `Local Storage`

## 排查表

| 现象 | 原因 | 处理 |
|------|------|------|
| `Cookies` 复制报 "being used by another process" | 源浏览器在运行 | 关掉它；或走 VSS 快照（Windows） |
| 复制成功但页面仍未登录 | 漏了 `Local Storage` | 补上 `Default/Local Storage` 重来 |
| cookie 数量对但站点不认 | 跨浏览器搬运（ABE） | 换回与源 profile 相同的 exe |
| CDP 端口连不上 | 副本启动失败 / 端口被占 | 看 `/json/version`；换 `-Port` |
| 关闭浏览器后终端里的会话断了 | 你关的是承载对话的那个浏览器 | 用另一个浏览器承载对话 |

## 已验证实例：Mixamo

```powershell
# 1. 你在 Chrome 里登录 mixamo.com
# 2. 关闭 Chrome
tools/browser/borrow-login.ps1 `
  -Exe "$env:ProgramFiles/Google/Chrome/Application/chrome.exe" `
  -SourceUserData "$env:LOCALAPPDATA/Google/Chrome/User Data" `
  -Url "https://www.mixamo.com/"
```

还原出来的导出 API（`Authorization: Bearer <localStorage.access_token>` + `X-Api-Key: mixamo2`）：

```
GET  /api/v1/products?page=N&limit=96&type=Motion%2CMotionPack   → 列表 + pagination
GET  /api/v1/products/{animId}?similar=0&character_id={char}     → details.gms_hash
POST /api/v1/animations/export
     { character_id, gms_hash:[…], product_name, type:"Motion",
       preferences:{ format:"fbx7", skin:"false", fps:"30", reducekf:"0" } }
GET  /api/v1/characters/{char}/monitor                            → 轮询 status: processing→completed
                                                                 → completed 时 job_result = S3 签名 URL
```

两个易错点：

- `gms_hash.params` 是 `[key, value]` 数组，提交前必须**压平成逗号串**（`params.map(p => p[1]).join(',')`）
- `product_name` 含逗号的是 **pack**，要跳过

`skin:"false"` = Without Skin，`reducekf:"0"` = 无关键帧压缩。
实测同一动作：`Without Skin` **0.67 MB** vs `With Skin` **17 MB**。
