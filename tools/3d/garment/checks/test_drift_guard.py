"""验证 derive_on_character.py 的偏斜守卫**真的会拦下来**（不改 bodyshape 的文件）。

自包含：临时文件写在**本脚本自己的 tmp 目录**（不存在则自建），
所以 `tmp/` 被清空后仍可直接复跑。请在**工作区根**执行。
"""
import hashlib, os, sys, time
sys.path.insert(0, "tools/3d/garment")
src = open("tools/3d/garment/derive_on_character.py", encoding="utf-8").read()
# 去掉末尾的 main() 调用，只取函数定义（测的是**真代码**，不是副本）
src = src[:src.rindex("main()")]
ns = {"__name__": "derive_test", "__file__": os.path.abspath("tools/3d/garment/derive_on_character.py")}
exec(compile(src, "derive_on_character.py", "exec"), ns)

_probe_dir = os.path.abspath("tmp/garment_checks")
os.makedirs(_probe_dir, exist_ok=True)
tmp = os.path.join(_probe_dir, "guard_probe.json")
open(tmp, "w").write('{"tiers":[{"shape_key":"BS_Heavy","target_coefficient":1.21}]}')

fp = ns["source_fingerprint"](tmp)
print("指纹:", fp["sha256_16"], fp["mtime"], fp["size"])

print("\n① 未改动 → 应静默通过")
ns["assert_source_unchanged"](fp, "test-1")
print("   ✅ 通过（无异常）")

print("\n② 改动后 → 应 SystemExit")
time.sleep(1.1)
open(tmp, "w").write('{"tiers":[{"shape_key":"BS_Heavy","target_coefficient":1.16}]}')
try:
    ns["assert_source_unchanged"](fp, "test-2")
    print("   ❌ 守卫没拦住！")
    sys.exit(1)
except SystemExit as e:
    print("   ✅ 已拦下：", str(e).strip().splitlines()[0])
    print("     ", str(e).strip().splitlines()[1])

print("\n③ 文件消失 → 应 SystemExit")
os.remove(tmp)
try:
    ns["assert_source_unchanged"](fp, "test-3")
    print("   ❌ 守卫没拦住！"); sys.exit(1)
except SystemExit as e:
    print("   ✅ 已拦下：", str(e).strip().splitlines()[0])

print("\n③b 语义分支：只改内容、coefficients_fingerprint 不变 → 应报「仅台账/格式变化」")
open(tmp, "w").write('{"coefficients_fingerprint":"AAA","x":1}')
fp2 = ns["source_fingerprint"](tmp)
time.sleep(1.1)
open(tmp, "w").write('{"coefficients_fingerprint":"AAA","x":2}')
try:
    ns["assert_source_unchanged"](fp2, "test-3b")
    print("   ❌ 没拦住！"); sys.exit(1)
except SystemExit as e:
    msg = str(e)
    line = [l.strip() for l in msg.splitlines() if "判定" in l][0]
    ok = "台账/格式" in line
    print(f"   {'✅' if ok else '❌'} 诊断为「仅台账/格式变化」")
    print("     ", line)

print("\n③c 语义分支：coefficients_fingerprint 也变了 → 应报「语义变化」")
open(tmp, "w").write('{"coefficients_fingerprint":"AAA","x":1}')
fp3 = ns["source_fingerprint"](tmp)
time.sleep(1.1)
open(tmp, "w").write('{"coefficients_fingerprint":"BBB","x":1}')
try:
    ns["assert_source_unchanged"](fp3, "test-3c")
    print("   ❌ 没拦住！"); sys.exit(1)
except SystemExit as e:
    msg = str(e)
    line = [l.strip() for l in msg.splitlines() if "判定" in l][0]
    ok = "语义变化" in line and "无法判定" not in line
    print(f"   {'✅' if ok else '❌'} 诊断为「语义变化」")
    print("     ", line)

print("\n④ fp=None（未找到系数源）→ 应静默跳过（有 ⚠ 日志）")
ns["assert_source_unchanged"](None, "test-4")
print("   ✅ 通过")
print("\n守卫单元测试全部通过")
