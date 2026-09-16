<#
.SYNOPSIS
  把一个已登录浏览器的 profile 复制成可丢弃副本，并用同一个 exe 带 CDP 端口启动。

.DESCRIPTION
  场景：你在日常浏览器（非 CDP）里人工登录了某个站点，希望自动化/agent 通过 CDP
  复用这个登录态，同时**不污染真实 profile**。

  三条硬前提（踩过的坑，别绕）：
    1. 必须用与源 profile 相同的浏览器可执行文件。
       Chromium 的 App-Bound Encryption 把 cookie 密钥绑定到 exe 路径 + 签名，
       换浏览器（Edge↔Chrome）或换程序读，cookie 一律解不开。
    2. 登录态可能在 cookie，也可能在 Local Storage（leveldb）。**两类都要复制。**
       实测 Mixamo 的 session 是纯 localStorage 的 access_token，只复制 Cookies 会白干。
    3. 源浏览器运行时会独占锁定 Cookies（连 FileShare.ReadWrite|Delete 都打不开，
       robocopy /b 备份模式也失败）。→ 先关闭源浏览器，或用 VSS 卷影快照（Windows）。

  跨平台：内部路径一律用 `/`，Windows / macOS 通用。需 PowerShell 7+（pwsh）。

.PARAMETER Exe
  浏览器可执行文件全路径。必须与源 profile 所属浏览器一致。
  Windows: "$env:ProgramFiles/Google/Chrome/Application/chrome.exe"
  macOS  : "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

.PARAMETER SourceUserData
  源 profile 根（User Data 目录）。
  Windows: "$env:LOCALAPPDATA/Google/Chrome/User Data"
  macOS  : "$HOME/Library/Application Support/Google/Chrome"

.PARAMETER ProfileDirectory
  profile 子目录名，默认 Default。

.PARAMETER CloneDir
  副本根目录。默认 <工作区根>/tmp/borrowed-profile（tmp 不入库，用完即删）。

.PARAMETER Port
  CDP 调试端口，默认 9222。

.PARAMETER Url
  启动后打开的地址，默认 about:blank。

.PARAMETER Force
  源浏览器仍在运行时也强行复制。会拿到可能不一致的数据，仅在明确知情时使用。

.EXAMPLE
  # Windows：借 Chrome 的登录态（先手动关掉 Chrome）；在**工作区根**下执行
  tools/browser/borrow-login.ps1 `
      -Exe "$env:ProgramFiles/Google/Chrome/Application/chrome.exe" `
      -SourceUserData "$env:LOCALAPPDATA/Google/Chrome/User Data" `
      -Url "https://www.mixamo.com/"

.EXAMPLE
  # macOS：同上
  pwsh tools/browser/borrow-login.ps1 `
      -Exe "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" `
      -SourceUserData "$HOME/Library/Application Support/Google/Chrome" `
      -Url "https://www.mixamo.com/"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$SourceUserData,
    [string]$ProfileDirectory = 'Default',
    [string]$CloneDir = '',
    [int]$Port = 9222,
    [string]$Url = 'about:blank',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# 默认副本目录从脚本位置推导（tools/browser/ → 工作区根），避免硬编码绝对路径。
if (-not $CloneDir) {
    $workspaceRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $CloneDir = Join-Path $workspaceRoot 'tmp' 'borrowed-profile'
}

if (-not (Test-Path -LiteralPath $Exe)) { throw "浏览器 exe 不存在：$Exe" }
if (-not (Test-Path -LiteralPath $SourceUserData)) { throw "源 User Data 不存在：$SourceUserData" }

# --- 1. 源浏览器是否在运行（它会独占锁定 Cookies） -------------------------------
$procName = [System.IO.Path]::GetFileNameWithoutExtension($Exe)
$running = @(Get-Process -Name $procName -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    if (-not $Force) {
        throw "检测到 $($running.Count) 个 $procName 进程正在运行，Cookies 会被独占锁定。请先关闭它再重跑（或加 -Force 强行尝试）。"
    }
    Write-Warning "$procName 仍在运行，复制结果可能不一致。"
}

# --- 2. 复制：cookie 与 origin 存储都要带 --------------------------------------
# 用 '/' 而非 '\' —— Windows 与 macOS 都接受正斜杠，而反斜杠在 macOS 上不是分隔符。
$cloneUserData = Join-Path $CloneDir 'User Data'
New-Item -ItemType Directory -Force -Path (Join-Path $cloneUserData "$ProfileDirectory/Network") | Out-Null

$items = @(
    'Local State',                                   # 加密密钥（ABE 引用），必须
    "$ProfileDirectory/Preferences",
    "$ProfileDirectory/Network/Cookies",             # 部分站点的 session
    "$ProfileDirectory/Network/Cookies-journal",
    "$ProfileDirectory/Local Storage",               # ← 很多 SPA 的真登录态在这
    "$ProfileDirectory/Session Storage",
    "$ProfileDirectory/IndexedDB",
    "$ProfileDirectory/Storage"
)

foreach ($item in $items) {
    $src = Join-Path $SourceUserData $item
    $dst = Join-Path $cloneUserData   $item
    if (-not (Test-Path -LiteralPath $src)) { Write-Verbose "跳过（源不存在）：$item"; continue }

    if ((Get-Item -LiteralPath $src).PSIsContainer) {
        Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
        $size = (Get-ChildItem -LiteralPath $dst -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
        Write-Host ("  [dir ] {0,-32} {1,9:N2} MB" -f $item, ($size / 1MB))
    }
    else {
        Copy-Item -LiteralPath $src -Destination $dst -Force
        Write-Host ("  [file] {0,-32} {1,9:N1} KB" -f $item, ((Get-Item -LiteralPath $dst).Length / 1KB))
    }
}

# --- 3. 同一 exe 启动副本 + CDP 端口 -------------------------------------------
Write-Host ""
Write-Host "启动副本浏览器（port $Port）..."
Start-Process -FilePath $Exe -ArgumentList @(
    "--user-data-dir=`"$cloneUserData`"",
    "--remote-debugging-port=$Port",
    '--no-first-run',
    '--no-default-browser-check',
    $Url
)

# --- 4. 验证 CDP 就绪 ----------------------------------------------------------
$ok = $false
foreach ($i in 1..20) {
    Start-Sleep -Milliseconds 800
    try {
        $v = Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -TimeoutSec 3
        Write-Host ""
        Write-Host "CDP 就绪：$($v.Browser)"
        Write-Host "副本 profile：$cloneUserData"
        Write-Host "用完销毁：Remove-Item '$CloneDir' -Recurse -Force"
        $ok = $true
        break
    }
    catch { }
}

if (-not $ok) { throw "CDP 端口 $Port 未就绪，启动失败。" }
