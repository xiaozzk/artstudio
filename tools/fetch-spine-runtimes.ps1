<#
.SYNOPSIS
  按 pinned commit 稀疏拉取官方 Spine 运行时（只取本项目需要的部分）。

.DESCRIPTION
  reference/spine-runtimes-4.3 是官方仓库 EsotericSoftware/spine-runtimes 的克隆，
  完整工作区 286 MB —— 但本项目（Godot 4 + spine-godot）只需要：
      spine-godot  (~17 MB)
      spine-cpp    (~1 MB，spine-godot 基于它)
  其余约 270 MB 是别的引擎运行时与官方示例。

  本脚本用「blobless + sparse」克隆，只把那两个目录签出来（约 20 MB），
  并固定在指定的 commit 上 —— 仓库里因此**不需要**保存这 286 MB。

.NOTES
  本机直连 github.com 的 git 传输**不稳定**（HTTP/2 与 blob 按需拉取常被 Connection reset）。
  脚本因此做了两件事：
    1. 所有 git 网络命令强制 `http.version=HTTP/1.1`（HTTP/2 是触发重置的主因）；
    2. 提供 -Proxy，直连失败时用镜像前缀重试，例如：
         -Proxy https://ghfast.top/     →  https://ghfast.top/https://github.com/...
       git 用 SHA-1 校验对象，镜像**无法**篡改内容；SHA 还会与
       GitHub API（https://api.github.com/repos/EsotericSoftware/spine-runtimes/commits/4.3）
       互相印证，所以走镜像不影响可信度。

  本机实测可用的镜像：https://ghfast.top/ 、 https://ghproxy.net/

.EXAMPLE
  pwsh tools/fetch-spine-runtimes.ps1
  pwsh tools/fetch-spine-runtimes.ps1 -Proxy https://ghfast.top/
  pwsh tools/fetch-spine-runtimes.ps1 -Paths spine-godot,spine-cpp,spine-c
  pwsh tools/fetch-spine-runtimes.ps1 -Commit <其他commit>
  pwsh tools/fetch-spine-runtimes.ps1 -Force          # 已存在时删掉重拉
#>
[CmdletBinding()]
param(
    [string]   $Target = 'reference/spine-runtimes-4.3',
    [string]   $Url    = 'https://github.com/EsotericSoftware/spine-runtimes.git',
    [string]   $Proxy  = '',
    [string]   $Branch = '4.3',
    [string]   $Commit = 'f182572b6360e6875d10a7c2b92dffed8c46c7d1',
    [string[]] $Paths  = @('spine-godot', 'spine-cpp'),
    [switch]   $Force
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot '.git'))) { $RepoRoot = (Get-Location).Path }
$Dest = if ([System.IO.Path]::IsPathRooted($Target)) { $Target } else { Join-Path $RepoRoot $Target }

# git 网络参数：强制 HTTP/1.1 + 加大 postBuffer（本机 github.com 直连不稳定）
$GitNet = @('-c', 'http.version=HTTP/1.1', '-c', 'http.postBuffer=524288000')
$CloneUrl = if ($Proxy) { "$Proxy$Url" } else { $Url }

Write-Host "仓库根目录 : $RepoRoot"
Write-Host "目标目录   : $Dest"
Write-Host "上游       : $CloneUrl  (branch $Branch)"
Write-Host "固定 commit: $Commit"
Write-Host "稀疏目录   : $($Paths -join ', ')"
Write-Host ''

# --- 已存在？--------------------------------------------------------------
if (Test-Path $Dest) {
    $cur = (& git -C $Dest rev-parse HEAD 2>$null)
    if ($cur -and -not $Force) {
        Write-Host "已存在（当前 commit $($cur.Substring(0,10))）。" -ForegroundColor Yellow
        if ($cur -eq $Commit) {
            Write-Host "  已经是指定的 commit，无需更新。" -ForegroundColor Green
            exit 0
        }
        Write-Host "  刷新到固定 commit : pwsh $($MyInvocation.MyCommand.Path) -Force"
        Write-Host "  只更新不重拉     : git -C `"$Dest`" -c http.version=HTTP/1.1 fetch origin $Commit; git -C `"$Dest`" checkout $Commit"
        exit 0
    }
    if (-not $Force) {
        Write-Host "目标目录已存在且不是 git 仓库：$Dest（加 -Force 覆盖）" -ForegroundColor Yellow
        exit 1
    }
    Write-Host '清理旧目录…' -ForegroundColor Yellow
    Remove-Item $Dest -Recurse -Force
}

# --- 重试包装：直连失败时自动改用镜像 ---------------------------------------
function Get-GitUrlCandidates {
    $list = [System.Collections.Generic.List[string]]::new()
    $list.Add($CloneUrl)
    if (-not $Proxy) {
        $list.Add('https://ghfast.top/' + $Url)
        $list.Add('https://ghproxy.net/' + $Url)
    }
    return $list
}

function Invoke-GitNet {
    param([string[]] $GitArgs, [string] $What)
    $last = 0
    foreach ($u in (Get-GitUrlCandidates)) {
        # 逐元素重建参数数组（不要用管道，避免数组被当成单个对象）
        $real = [System.Collections.Generic.List[string]]::new()
        foreach ($a in $GitArgs) { $real.Add($(if ($a -eq '__URL__') { $u } else { $a })) }
        Write-Host "  git $What  via $u" -ForegroundColor DarkGray
        & git @GitNet @real
        $last = $LASTEXITCODE
        if ($last -eq 0) { return }
        Write-Host "  失败（exit $last），换下一个通道…" -ForegroundColor Yellow
        # 半途失败的 clone 会留下目录，清掉再试下一个通道
        if ($What -eq 'clone' -and (Test-Path $Dest)) { Remove-Item $Dest -Recurse -Force -ErrorAction SilentlyContinue }
    }
    throw "git $What 在所有通道上均失败（最后 exit $last）"
}

# --- 克隆（blobless + 不签出）--------------------------------------------
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null
Invoke-GitNet -What 'clone' -GitArgs @('clone', '--filter=blob:none', '--no-checkout', '--branch', $Branch, '__URL__', $Dest)

# --- 稀疏签出 --------------------------------------------------------------
& git -C $Dest sparse-checkout init --cone
& git -C $Dest sparse-checkout set @Paths
# 确保目标 commit 在本地（可能不是分支尖端）
& git @GitNet -C $Dest fetch --no-tags origin $Commit 2>$null | Out-Null
& git -C $Dest checkout $Commit
if ($LASTEXITCODE -ne 0) { throw "checkout $Commit 失败" }

# --- 结果 ------------------------------------------------------------------
$size = (Get-ChildItem $Dest -Recurse -File -Force -ErrorAction SilentlyContinue |
         Measure-Object Length -Sum).Sum / 1MB
$gitSize = (Get-ChildItem (Join-Path $Dest '.git') -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum / 1MB
Write-Host ''
Write-Host '完成 ✅' -ForegroundColor Green
Write-Host ("  实际 commit : " + (& git -C $Dest rev-parse HEAD))
Write-Host ("  内容体积    : {0:N1} MB    （.git {1:N1} MB）" -f $size, $gitSize)
Write-Host ("  已签出      : " + ((Get-ChildItem $Dest -Directory -Force | Where-Object { $_.Name -ne '.git' } | Select-Object -ExpandProperty Name) -join ', '))
Write-Host ''
Write-Host '需要别的引擎或官方示例时：'
Write-Host "  git -C `"$Dest`" sparse-checkout add examples/spineboy"
