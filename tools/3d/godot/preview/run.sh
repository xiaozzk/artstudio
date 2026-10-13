#!/usr/bin/env bash
# artstudio T3 —— Godot 4.6 交互预览页面 运行器（带看门狗）
#
# 为什么需要看门狗：Godot 的 `-s` 脚本若"编译失败"，`_initialize()` 根本不会执行，
# 于是 `quit()` 也不会被调用，进程会一直空转不退出（上游 harness 实测踩过）。
#
# 用法：
#   tools/3d/godot/preview/run.sh                 # 离屏出图 + JSON（一条命令跑完所有证据）
#   tools/3d/godot/preview/run.sh --interactive   # 开交互页面（拖滑块 / 换装 / 换发型）
#   tools/3d/godot/preview/run.sh --shots --no-bake   # 只用已有 tmp 缓存，绝不调 Blender
#
# 环境变量：
#   ARTSTUDIO_GODOT     Godot 可执行（默认 /Applications/Godot.app/Contents/MacOS/Godot）
#   ARTSTUDIO_BLENDER   Blender 可执行（默认 /Applications/Blender.app/Contents/MacOS/Blender）
#   ARTSTUDIO_PREVIEW_CACHE   glb/曲线缓存目录（默认 <repo>/tmp/godot_preview_cache）
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GODOT="${ARTSTUDIO_GODOT:-/Applications/Godot.app/Contents/MacOS/Godot}"
MODE="${1:---shots}"
shift || true

if [[ ! -x "$GODOT" ]]; then
  echo "[run.sh] 找不到 Godot：$GODOT（用 ARTSTUDIO_GODOT 覆盖）" >&2
  exit 2
fi

case "$MODE" in
  --interactive|-i)
    echo "[run.sh] 交互模式：窗口已开，拖右侧滑块即可；Ctrl-C 或关窗退出"
    exec "$GODOT" --path "$HERE" --resolution 1560x1010
    ;;
  --shots|-s|*)
    # 离屏出图：窗口给个小尺寸即可，成图分辨率由脚本里的常量决定（SubViewport）
    "$GODOT" --path "$HERE" -s res://shoot.gd --resolution 640x480 "$@" &
    pid=$!
    ( sleep 900; if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null; echo "[run.sh] TIMEOUT 900s, killed $pid"; fi ) &
    wd=$!
    wait "$pid"; rc=$?
    kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
    echo "[run.sh] exit=$rc"
    exit "$rc"
    ;;
esac