#!/usr/bin/env bash
# 带看门狗的 Godot 运行器（task-5）。
# 为什么需要：Godot 的 -s 脚本如果“编译失败”，_initialize() 根本不会执行，
# 于是 quit() 也不会被调用，进程会一直空转不退出（实测踩过）。
# 用法：run.sh <godot 可执行> <超时秒> [godot 参数...]
set -uo pipefail
BIN="$1"; TMO="$2"; shift 2
"$BIN" "$@" &
pid=$!
( sleep "$TMO"; if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null; echo "[run.sh] TIMEOUT after ${TMO}s, killed pid $pid"; fi ) &
wd=$!
wait "$pid"; rc=$?
kill "$wd" 2>/dev/null
wait "$wd" 2>/dev/null
exit "$rc"