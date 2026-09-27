#!/bin/bash
# ============================================
#   2D 预览图浏览器 · 一键启动 (macOS)
#
#   用法：
#       · 在 Finder 里双击本文件（Terminal 自动接管运行）
#       · 或在终端里执行：
#           ./tools/preview-2d/start.command
#           ./tools/preview-2d/start.command --no-browser
#           ./tools/preview-2d/start.command --port 9000
#           ./tools/preview-2d/start.command scan
#
#   除脚本自身外，所有参数原样透传给 serve.py（--port / --host / --no-browser
#   或子命令 scan / serve）。默认从 8000 起找空闲端口并打开浏览器；
#   Ctrl+C 停止服务。
#
#   与 start.bat / start.ps1 等价：切到工作区根 → 探测 Python → 调 serve.py。
#   若 Finder 双击显示成文本编辑器（执行位丢了），修复：
#       chmod +x tools/preview-2d/start.command
# ============================================

SELF="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SELF")" >/dev/null 2>&1 && pwd -P)" || SCRIPT_DIR=""
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." >/dev/null 2>&1 && pwd -P)" || WORKSPACE_ROOT=""

# 输出颜色（只在接 tty 时用，管道 / 重定向时关闭）
if [ -t 1 ]; then
    C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_GRAY=$'\033[90m'; C_OFF=$'\033[0m'
else
    C_CYAN=''; C_RED=''; C_YEL=''; C_GRAY=''; C_OFF=''
fi

# 双击场景（Terminal / iTerm / VSCode 终端）出错时暂停，别让窗口一闪而过
pause_if_gui_terminal() {
    case "${TERM_PROGRAM:-}" in
        Apple_Terminal|iTerm.app|vscode)
            if [ -t 0 ]; then
                echo
                printf '按 Enter 关闭窗口…'
                IFS= read -r REPLY || true
                echo
            fi
            ;;
    esac
}

fail() {
    echo "$C_RED$*$C_OFF"
    pause_if_gui_terminal
    exit 1
}

echo
echo "$C_CYAN=====================================================$C_OFF"
echo "$C_CYAN  2D 预览图浏览器 (macOS)$C_OFF"
echo "$C_GRAY  工作区  : $WORKSPACE_ROOT$C_OFF"
echo "$C_CYAN=====================================================$C_OFF"
echo

# --- 切到工作区根（serve.py 依赖此 cwd：图片用 /assets/2d 绝对 URL） ---
[ -n "$WORKSPACE_ROOT" ] || fail "[错误] 无法定位脚本目录：$SELF"
cd "$WORKSPACE_ROOT" || fail "[错误] 无法进入工作区根：$WORKSPACE_ROOT"

# --- 探测 Python 3.7+ ---
# 顺序：PATH 里的 python3（pyenv / Homebrew / CLT）→ python →
#       Homebrew 固定路径（PATH 没配好兜底）→ /usr/bin/python3（仅 CLT 已装，
#       否则 stub 会弹「需要安装开发者工具」对话框，跳过）
cands=""
for c in python3 python; do
    p="$(command -v "$c" 2>/dev/null)" && cands="$cands $p"
done
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    [ -x "$p" ] && cands="$cands $p"
done
if command -v xcode-select >/dev/null 2>&1 && xcode-select -p >/dev/null 2>&1; then
    [ -x /usr/bin/python3 ] && cands="$cands /usr/bin/python3"
fi

PY=""
for c in $cands; do
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' 2>/dev/null; then
        PY="$c"
        break
    fi
done

[ -n "$PY" ] || fail "[错误] 找不到 Python 3.7+。
        macOS 上装任意一种即可：
          · xcode-select --install                 （系统自带 CLT）
          · brew install python                    （Homebrew）
          · pyenv install 3.12 && pyenv global 3.12 （pyenv）"

printf '%s%s%s\n' "$C_GRAY" "使用 Python: $PY" "$C_OFF"
echo

# 前台运行；serve.py 自己管端口避让与浏览器打开
"$PY" tools/preview-2d/serve.py "$@"
rc=$?

if [ "$rc" -ne 0 ]; then
    echo
    printf '%s[退出码 %s]%s\n' "$C_YEL" "$rc" "$C_OFF"
    pause_if_gui_terminal
fi
exit "$rc"
