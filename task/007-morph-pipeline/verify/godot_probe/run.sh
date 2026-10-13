#!/usr/bin/env bash
# verifier 独立复算 T3 的三条 Godot 断言（**独立工程**，不用 tools/3d/godot/preview）
# 依赖：先跑过 T3 的 bake（或让 run.sh 生成缓存）→ tmp/godot_preview_cache/glb/*.glb
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
cp "$HERE/project.godot" "$HERE/probe.gd" "$HERE/probe2.gd" "$WORK/"
Godot="${GODOT_BIN:-/Applications/Godot.app/Contents/MacOS/Godot}"
"$Godot" --headless --path "$WORK" -s res://probe.gd
"$Godot" --headless --path "$WORK" -s res://probe2.gd
rm -rf "$WORK"
