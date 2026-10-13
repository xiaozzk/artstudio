#!/usr/bin/env bash
# artstudio shape-lab —— macOS / Linux 入口（Windows 主入口是 run.cmd，两边口径一致）
#
#   ./run.sh              开窗：左固定尺寸舞台 + 右中文面板（拖 k/h 看身形与服装变形）
#   ./run.sh --shots      离屏出图到 <缓存根>/shots/
#   ./run.sh --selftest   交互链路自检（退出码 0 = 全绿）
#   ./run.sh --fixtures   缓存缺失时的离线演示（纯内存自造角色，无 morph）
#
# 环境变量：ARTSTUDIO_GODOT / ARTSTUDIO_BLENDER / ARTSTUDIO_SHAPELAB_CACHE
#           ARTSTUDIO_SHAPELAB_TIMEOUT（截图模式看门狗秒数，默认 900）
#
# ⚠⚠ 本脚本**未在本机实测**（交付机是 Windows，无 macOS 环境）—— 别把它当「已验过」。
#     run.cmd 是已实测的 Windows 主入口；本脚本只是按同一口径写的兼容版。
#
# 看门狗为什么必须有：Godot 的脚本一旦**编译失败**，进程会永久空转不退出（实测踩过）。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"

GODOT="${ARTSTUDIO_GODOT:-}"
if [[ -z "$GODOT" ]]; then
  for c in "/Applications/Godot.app/Contents/MacOS/Godot" "$(command -v godot 2>/dev/null || true)" \
           "$(command -v godot4 2>/dev/null || true)"; do
    [[ -n "$c" && -x "$c" ]] && GODOT="$c" && break
  done
fi
if [[ -z "$GODOT" || ! -x "$GODOT" ]]; then
  echo "[shape-lab] 找不到 Godot：把 ARTSTUDIO_GODOT 指到 Godot 4.6 可执行文件" >&2
  exit 2
fi

CACHE="${ARTSTUDIO_SHAPELAB_CACHE:-$REPO/tmp/shape-lab}"
EXTRA=""
MODE="interactive"
for a in "$@"; do
  case "$a" in
    --shots) MODE="shots" ;;
    --fixtures | --selftest) EXTRA="$EXTRA $a" ;;
  esac
done

# 缓存缺失或源 .blend 更新 → 先调 bake.py
NEED=0
[[ -f "$CACHE/manifest.json" ]] || NEED=1
if [[ $NEED -eq 0 ]] && [[ -n "$(find "$REPO/assets/3d/rig" -name '*.blend' -newer "$CACHE/manifest.json" -print -quit 2>/dev/null)" ]]; then
  NEED=1
fi
if [[ $NEED -eq 1 ]]; then
  if [[ ! -f "$HERE/bake.py" ]]; then
    echo "[shape-lab] 缓存缺失/过期，且找不到 bake.py（T1 产物）—— 可先用 ./run.sh --fixtures" >&2
    exit 3
  fi
  BLENDER="${ARTSTUDIO_BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
  [[ -x "$BLENDER" ]] || { echo "[shape-lab] 找不到 Blender（用 ARTSTUDIO_BLENDER 指定）" >&2; exit 3; }
  echo "[shape-lab] 缓存缺失或源 .blend 更新，先烘焙：bake.py --cache \"$CACHE\""
  ( cd "$REPO" && ARTSTUDIO_BLENDER="$BLENDER" python3 "$HERE/bake.py" --cache "$CACHE" --blender "$BLENDER" ) || exit $?
fi

if [[ "$MODE" == "interactive" ]]; then
  echo "[shape-lab] 开窗：左键拖拽环绕 / 滚轮缩放；右侧拖 k 与 h；「清凉」一键摘配件。"
  exec "$GODOT" --path "$HERE" --resolution 1500x900 -- $EXTRA
fi

TIMEOUT="${ARTSTUDIO_SHAPELAB_TIMEOUT:-900}"
echo "[shape-lab] 截图模式：离屏 960x900 舞台 + 1500x900 整页图，看门狗 ${TIMEOUT}s…"
"$GODOT" --path "$HERE" --resolution 960x900 -- --shots $EXTRA &
pid=$!
( sleep "$TIMEOUT"
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null
    echo "[shape-lab] 看门狗超时 ${TIMEOUT}s，已强杀 Godot —— 多半是脚本编译失败在空转" >&2
  fi ) &
wd=$!
wait "$pid"; rc=$?
kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
echo "[shape-lab] Godot 退出码 = $rc"
exit "$rc"
