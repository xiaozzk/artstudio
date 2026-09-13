<#
.SYNOPSIS
  按 pinned commit 稀疏拉取官方 Spine 运行时（只取本项目需要的部分）。

.DESCRIPTION
  reference/spine-runtimes-4.3 是官方仓库 EsotericSoftware/spine-runtimes 的完整克隆，
  工作区 286 MB —— 但本项目（Godot 4 + spine-godot）只需要：
      spine-godot  (~17 MB)
      spine-cpp    (~1 MB，spine-godot 基于它)
  其余约 270 MB 是别的引擎运行时与官方示例。

  本脚本用「blobless + sparse」克隆，只把那两个目录签出来（约 19 MB），
  并固定在指定的 commit 上 —— 仓库里因此**不需要**保存这 286 MB。

.EXAMPLE
  pwsh tools/fetch-spine-runtimes.ps1
  pwsh tools/fetch-spine-runtimes.ps1 -Paths spine-godot,spine-cpp,spine-c
  pwsh tools/fetch-spine-runtimes.ps1 -Commit <其他commit>
  pwsh tools/fetch-spine-runtimes.ps1 -Force          # 已存在时删掉重拉
#>
[CmdletBinding()]
param(
    [string]   $Target = 'reference/spine-runtimes-4.3',
    [string]   $Url    = 'https://github.com/EsotericSoftware/spine-runtimes.git',
    [string]   $Branch = '4.3',
    [string]   $Commit = '51d8d78b5414645875c2641630a6f4cdb2737440',
    [string[]] $Paths  = @('spine-godot', 'spine-cpp'),
    [switch]   $Force
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot '.git'))) { $RepoRoot = (Get-Location).Path }
$Dest = if ([System.IO.Path]::IsPathRooted($Target)) { $Target } else { Join-Path $RepoRoot $Target }

Write-Host "仓库根目录 : $RepoRoot"
Write-Host "目标目录   : $Dest"
Write-Host "上游       : $Url  (branch $Branch)"
Write-Host "固定 commit: $Commit"
Write-Host "稀疏目录   : $($Paths -join ', ')"
Write-Host ''

# --- 已存在？--------------------------------------------------------------
if (Test-Path $Dest) {
    $cur = (& git -C $Dest rev-parse HEAD 2>$null)
    if ($cur -and -not $Force) {
        Write-Host "已存在（当前 commit $($cur.Substring(0,10))）。" -ForegroundColor Yellow
        Write-Host "  刷新到固定 commit : pwsh $($MyInvocation.MyCommand.Path) -Force"
        Write-Host "  只更新不重拉     : git -C `"$Dest`" fetch --filter=blob:none origin $Commit; git -C `"$Dest`" checkout $Commit"
        exit 0
    }
    if (-not $Force) {
        Write-Host "目标目录已存在且不是 git 仓库：$Dest（加 -Force 覆盖）" -ForegroundColor Yellow
        exit 1
    }
    Write-Host '清理旧目录…' -ForegroundColor Yellow
    Remove-Item $Dest -Recurse -Force
}

# --- 克隆（blobless + 不签出）--------------------------------------------
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null
& git clone --filter=blob:none --no-checkout --branch $Branch $Url $Dest
if ($LASTEXITCODE -ne 0) { throw 'git clone 失败' }

# --- 稀疏签出 --------------------------------------------------------------
& git -C $Dest sparse-checkout init --cone
& git -C $Dest sparse-checkout set @Paths
# 确保目标 commit 在本地（可能不是分支尖端）
& git -C $Dest fetch --filter=blob:none origin $Commit 2>$null | Out-Null
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
