#!/usr/bin/env bash
# run_verify.sh —— verifier 的**加固门禁**：跑全部独立验算脚本并强制它们"真的跑完"。
#
# 为什么需要它（garment 抓到、Lead 转来的坑）：
#   `blender -b --python X.py` **在脚本抛异常时仍然返回 exit code 0**。
#   → 只看 returncode 或"看有没有输出文件"的门禁会**静默说谎**。
# 本脚本三重保险：
#   ① Blender 加 `--python-exit-code 1`（脚本抛异常 → Blender 退出码非 0）
#   ② 输出里扫 `Traceback` / `Error:`（双保险，防 Blender 版本差异）
#   ③ 跑前跑后比对产物 JSON 的 sha256 → 报告"数字是否逐位不变"
# 并且内置 `--selftest`：**故意让一个脚本失败一次**，确认门禁真的会变红。
#
# 用法（在工作区根）：
#   bash task/007-morph-pipeline/verify/run_verify.sh            # 全跑 + 对账
#   bash task/007-morph-pipeline/verify/run_verify.sh --selftest # 先证明门禁会响
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
V="$ROOT/task/007-morph-pipeline/verify"
R="$ROOT/assets/3d/rig/reports"
BL="${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# script:output:runner(blender|py)
JOBS=(
  "v_rigfacts.py:verify-rigfacts-raw.json:blender"
  "v_rigfacts_analyze.py:verify-rigfacts.json:py"
  "v_selftest.py:verify-selftest.json:blender"
  "v_shelltest.py:verify-shelltest.json:blender"
  "v_topology_audit.py:verify-topology.json:blender"
  "v_heightbug.py:verify-heightbug.json:blender"
  "v_penetration.py:verify-penetration.json:blender"
  "v_rootcause.py:verify-rootcause.json:blender"
  "v_fitdepth.py:verify-fitdepth.json:blender"
  "v_humanfactor.py:verify-humanfactor.json:blender"
  "v_transfer.py:verify-transfer.json:blender"
  "v2_verify.py:verify-v2.json:blender"
  "v_pixelmetric.py:verify-pixelmetric.json:blender"
  "v_pixel_forensics.py:verify-pixel-forensics.json:blender"
  "v_b2.py:verify-b2.json:blender"
  "v_t3_integration.py:verify-t3-integration.json:blender"
  "v_digest.py:verify-digest.json:blender"
  "v_nontrivial.py:verify-nontrivial.json:blender"
  "v_godot.py:verify-godot.json:py"
  "v_t3_final.py:verify-t3-final.json:py"
)

# 逐位比对前**剥掉易变字段**（计时/时间戳/绝对路径），否则永远"变了"
hashof() {
  [ -f "$1" ] || { echo "MISSING"; return; }
  python3 - "$1" <<'PYEOF'
import hashlib, json, re, sys
# 只剥"每次跑都会变"的字段：
#   · 计时（seconds / elapsed / phases / pace）与时间戳
#   · 环境路径
# ⚠ **不剥** blend_sha256 / blend_bytes —— 那是**资产出处**，它变了说明上游重烘了资产，
#   这恰恰是我们要看见的信号（v2 重烘时就是这么发现的）。
VOL = re.compile(r"(seconds|elapsed|generated_at|^started$|_ms$|cache_dir|^root$|blender_bin|blender_version|one_command|timestamps|^phases$|^phases_s$|^autofit_moved_per_round$)")
def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if not VOL.search(str(k))}
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
    b = json.dumps(strip(d), sort_keys=True, ensure_ascii=False).encode()
except Exception:
    b = open(sys.argv[1], "rb").read()
print(hashlib.sha256(b).hexdigest()[:16])
PYEOF
}

# ---------------- 门禁自检：证明它真的会变红 ----------------
if [ "${1:-}" = "--selftest" ]; then
  echo "=============== 门禁自检：故意让脚本失败 ==============="
  cat > "$TMP/boom.py" <<'EOF'
import sys
print("before failure")
raise RuntimeError("deliberate failure for gate selftest")
EOF
  echo "--- A) 不加 --python-exit-code（应看到 exit 0 = 门禁失灵）---"
  "$BL" -b --factory-startup --python "$TMP/boom.py" >"$TMP/a.log" 2>&1
  echo "    exit code = $?   （0 就说明这个坑是真的）"
  echo "--- B) 加 --python-exit-code 1（应非 0）---"
  "$BL" -b --factory-startup --python-exit-code 1 --python "$TMP/boom.py" >"$TMP/b.log" 2>&1
  echo "    exit code = $?   （非 0 才算门禁有效）"
  echo "--- C) Traceback 扫描（双保险）---"
  if grep -q "Traceback" "$TMP/b.log"; then echo "    扫到 Traceback ✅"; else echo "    没扫到 ❌"; fi
  echo "======================================================="
  echo
fi

echo "=============== verifier 加固门禁：跑 $((${#JOBS[@]})) 个脚本 ==============="
FAIL=0; CHANGED=0; OK=0
declare -a CHANGED_LIST=()

for job in "${JOBS[@]}"; do
  IFS=':' read -r script out runner <<<"$job"
  outpath="$R/$out"
  before="$(hashof "$outpath")"
  log="$TMP/$script.log"
  if [ "$runner" = "blender" ]; then
    "$BL" -b --factory-startup --python-exit-code 1 \
      --python "$V/$script" -- --out "$outpath" >"$log" 2>&1
  else
    python3 "$V/$script" --out "$outpath" >"$log" 2>&1
  fi
  rc=$?
  tb=0; grep -q "Traceback" "$log" && tb=1
  after="$(hashof "$outpath")"
  status="OK"
  if [ $rc -ne 0 ] || [ $tb -ne 0 ] || [ "$after" = "MISSING" ]; then
    status="**FAIL**"; FAIL=$((FAIL+1))
    echo "  [FAIL] $script  exit=$rc traceback=$tb out=$after"
    tail -5 "$log" | sed 's/^/       /'
    continue
  fi
  if [ "$before" = "$after" ]; then
    echo "  [ok] $script  out=$after (与上次逐位一致)"
    OK=$((OK+1))
  else
    echo "  [!] $script  out $before -> $after (产物变了)"
    CHANGED=$((CHANGED+1)); CHANGED_LIST+=("$script  $out  $before to $after")
  fi
done

echo "---------------------------------------------------------------"
echo "OK=$OK  产物改变=$CHANGED  失败=$FAIL"
echo "参考：garments/*.blend 当前出处"
python3 - <<'PYA'
import hashlib, glob, os
for p in sorted(glob.glob("assets/3d/rig/garments/*.blend")):
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    print(f"   {os.path.basename(p):<24} {h}  {os.path.getsize(p)} B")
PYA
if [ $CHANGED -gt 0 ]; then
  echo "产物改变清单（需逐项确认是"预期内"还是"静默失败"）："
  for c in "${CHANGED_LIST[@]}"; do echo "  - $c"; done
fi
[ $FAIL -eq 0 ] || exit 1