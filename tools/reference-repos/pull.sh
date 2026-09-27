#!/usr/bin/env bash
# 拉取 / 更新 docs/ 下的外部参考仓库（清单：tools/reference-repos/repos.list）。
#
# 用法（任意目录执行均可，自动定位工作区根）：
#   bash tools/reference-repos/pull.sh          # 浅克隆（--depth 1）/ ff-only 更新
#   bash tools/reference-repos/pull.sh --full   # 完整克隆（保留全部历史）
#
# 行为：
#   - 不在本地        → git clone（默认浅克隆，参考资料够用）
#   - 已存在          → git pull --ff-only（失败不硬来，留给人工处理）
#   - docs/ 下的孤儿仓库（含 .git 但不在清单）→ 只提示，不动它
# 退出码：有任何失败则非 0。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIST="$SCRIPT_DIR/repos.list"
DOCS="$ROOT/docs"
SHALLOW=1
[[ "${1:-}" == "--full" ]] && SHALLOW=0

mkdir -p "$DOCS"

# 读清单（去注释 / 空行）
URLS=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="$(echo "$line" | tr -d '[:space:]')"
  [[ -n "$line" ]] && URLS+=("$line")
done < "$LIST"

CLONED=0; UPDATED=0; FRESH=0; FAIL=0
IN_LIST=()

for url in "${URLS[@]}"; do
  name="$(basename "$url" .git)"
  dir="$DOCS/$name"
  report="$name"
  IN_LIST+=("$name")

  if [[ ! -e "$dir" ]]; then
    clone_args=("$url" "$dir"); (( SHALLOW )) && clone_args=(--depth 1 "${clone_args[@]}")
    if git clone "${clone_args[@]}" > /tmp/ref-repos-clone.log 2>&1; then
      echo "  CLONE  $name  ($(git -C "$dir" log -1 --format='%h %ad %s' --date=short))"
      CLONED=$((CLONED + 1))
      continue
    fi
    echo "  FAILED $name  clone 失败（详见 /tmp/ref-repos-clone.log）"
    FAIL=$((FAIL + 1)); continue
  fi

  if [[ ! -e "$dir/.git" ]]; then
    echo "  SKIP   $name  目录已存在但不是 git 仓库，不覆盖"
    continue
  fi

  cur="$(git -C "$dir" log -1 --format='%h %s' 2>/dev/null || echo '?')"
  if git -C "$dir" pull --ff-only > /tmp/ref-repos-pull.log 2>&1; then
    new="$(git -C "$dir" log -1 --format='%h %s' 2>/dev/null || echo '?')"
    if [[ "$cur" == "$new" ]]; then
      echo "  LATEST $name  已是最新（${cur}）"
      FRESH=$((FRESH + 1))
    else
      echo "  UPDATE $name  $cur"
      echo "              → $new"
      UPDATED=$((UPDATED + 1))
    fi
  else
    echo "  FAILED $name  pull --ff-only 失败（本地改动或历史被改写？详见 /tmp/ref-repos-pull.log）"
    FAIL=$((FAIL + 1))
  fi
done

# 孤儿检测：docs/ 下含 .git 但不在清单的
for d in "$DOCS"/*/; do
  [[ -d "$d" ]] || continue
  name="$(basename "$d")"
  is_listed=0
  for n in "${IN_LIST[@]}"; do [[ "$n" == "$name" ]] && is_listed=1 && break; done
  if (( ! is_listed )) && [[ -e "$d/.git" ]]; then
    echo "  WARN   $name  在 docs/ 下但不在 repos.list（不会被更新；如需纳管，把 URL 加进清单）"
  fi
done

echo "──────────────────────────────────────────────"
echo "完成：克隆 $CLONED · 更新 $UPDATED · 已最新 $FRESH · 失败 $FAIL"
exit $(( FAIL > 0 ? 1 : 0 ))
