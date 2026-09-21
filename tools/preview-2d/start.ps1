# ============================================
#   2D 预览图浏览器 · 一键启动 (PowerShell)
#
#   用法：
#       双击本文件，或在 PowerShell 里执行：
#           .\tools\preview-2d\start.ps1
#           .\tools\preview-2d\start.ps1 -NoBrowser
#           .\tools\preview-2d\start.ps1 -Port 9000
#
#   默认会从 8000 起找空闲端口并打开浏览器；按 Ctrl+C 停止。
#   与 start.bat 等价，但支持中文 message 与参数化（-Port / -NoBrowser）。
# ============================================

[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [int]$Port,
    [Alias('Host')]
    [string]$Address = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'

# 切到工作区根（脚本位于 tools\preview-2d\）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceRoot = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
Push-Location $WorkspaceRoot
try {
    Write-Host ''
    Write-Host '=====================================================' -ForegroundColor Cyan
    Write-Host '  2D 预览图浏览器' -ForegroundColor Cyan
    Write-Host ("  工作区  : {0}" -f $WorkspaceRoot) -ForegroundColor DarkGray
    Write-Host '=====================================================' -ForegroundColor Cyan
    Write-Host ''

    # 探测 Python 解释器
    $py = $null
    foreach ($cmd in @('python', 'py', 'python3')) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) { $py = $cmd; break }
    }
    if (-not $py) {
        Write-Host '[错误] 找不到 Python (3.7+)。请先安装并加入 PATH。' -ForegroundColor Red
        Write-Host '        下载: https://www.python.org/downloads/' -ForegroundColor Red
        Read-Host '按 Enter 退出'
        exit 1
    }
    Write-Host ("使用 Python: {0}" -f $py) -ForegroundColor DarkGray
    Write-Host ''

    # 构造传给 serve.py 的参数
    $pyArgs = @('tools\preview-2d\serve.py')
    if ($NoBrowser) { $pyArgs += '--no-browser' }
    if ($Port)       { $pyArgs += @('--port', $Port.ToString()) }
    if ($Address -ne '127.0.0.1') { $pyArgs += @('--host', $Address) }

    Write-Host ("执行: {0} {1}" -f $py, ($pyArgs -join ' ')) -ForegroundColor DarkGray
    Write-Host ''

    # 前台运行，Ctrl+C 终止
    & $py @pyArgs
    $rc = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($rc -ne 0) {
    Write-Host ''
    Write-Host ("[退出码 {0}]" -f $rc) -ForegroundColor Yellow
    Read-Host '按 Enter 退出'
}
exit $rc
