#!/usr/bin/env python3
"""tools/3d/garment/build_all.py —— 服装变形链**一条命令重跑**（B2 主路线）

用法
----
  python3 tools/3d/garment/build_all.py                # B2 主链路：派生 → 验收 → 预览
  python3 tools/3d/garment/build_all.py --b1           # 额外跑 B1 路线（剥离/贴合/传递/组装/验收）
  python3 tools/3d/garment/build_all.py --probes       # 额外跑度量体检与独立判据探针
  python3 tools/3d/garment/build_all.py --only Female_Ranger

每一步都独立成 Blender 进程（干净的 factory-startup），任一步非 0 退出即整体失败。
所有脚本幂等：每次从 `assets/3d/blend/` 原件重读，可随意重跑。
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")

B2_STEPS = [
    ("B2 ① 派生：角色自身 rig 摆体形骨 → 逐件烘 morph", "derive_on_character.py", []),
    ("B2 ② 验收：SPEC §5 六项 + B2 专属断言 + 交付清单", "verify_fit.py", []),
    ("B2 ③ 视觉证据：三态并排 + 穿模可视化", "preview.py", []),
]
B1_STEPS = [
    ("B1 ① 剥离 MI_Regular_* 皮肤面", "strip_skin.py", []),
    ("B1 ② 骨空间重绑", "refit.py", ["--method", "bone"]),
    ("B1 ②b 自动去穿模外推（可选实验，SPEC F11 已撤回）", "autofit.py", []),
    ("B1 ③ 重心坐标 + 三角面标架传递", "transfer_morph.py", []),
    ("B1 ④ 组装（换挂标准体骨架）", "assemble.py", []),
    ("B1 ⑤ B1 口径验收", "verify_fit_b1.py", []),
]
PROBE_STEPS = [
    ("探针 A 度量体检：闭合性 / 噪声底 / 判据独立性 / Arms 薄壳", "probe_metric.py", []),
    ("探针 B 独立判据：像素法 + 骨轴径向（B1 对照）", "probe_independent.py", []),
    ("探针 C 开发用 fixture 标准体（B1 链路用）", "make_fixture_body.py", []),
]


def run(title, script, extra, only):
    path = os.path.join(HERE, script)
    if not os.path.exists(path):
        print(f"  [skip] 缺脚本 {script}")
        return True
    # ⚠ `--python-exit-code 1`：没有它时，脚本抛异常 Blender **仍然返回 0**
    #   → 门禁会亮绿灯而产物没更新（本工具实际踩过：manifest 停在旧版却报 ✅）
    cmd = [BLENDER, "-b", "--factory-startup", "--python-exit-code", "1", "--python", path]
    args = list(extra)
    if only:
        args += ["--only", only]
    if args:
        cmd += ["--"] + args
    print(f"\n{'='*100}\n▶ {title}\n  $ {' '.join(cmd)}", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    dt = time.time() - t0
    sys.stdout.write(r.stdout)
    sys.stdout.write(r.stderr)
    # 双保险：即使退出码骗人，输出里出现 Traceback 也算失败
    blob = (r.stdout or "") + (r.stderr or "")
    tb = "Traceback (most recent call last)" in blob
    ok = (r.returncode == 0) and not tb
    why = "" if ok else (f"退出码 {r.returncode}" + ("；输出含 Traceback" if tb else ""))
    print(f"  {'✅' if ok else '❌'} {script} {why or '退出码 0'}，用时 {dt:.1f}s", flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser(prog="build_all.py")
    ap.add_argument("--b1", action="store_true", help="额外跑 B1 路线（默认只跑 B2）")
    ap.add_argument("--probes", action="store_true", help="额外跑度量体检与探针")
    ap.add_argument("--only", default=None, help="只处理一套，如 Female_Ranger")
    ap.add_argument("--skip-b2", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(BLENDER):
        print(f"找不到 Blender：{BLENDER}（用环境变量 BLENDER 覆盖）", file=sys.stderr)
        return 2
    steps = ([] if a.skip_b2 else B2_STEPS) + (B1_STEPS if a.b1 else []) + (PROBE_STEPS if a.probes else [])
    print(f"工作区 {ROOT}\nBlender {BLENDER}\n共 {len(steps)} 步（B2 是主路线）")
    failed = []
    for title, script, extra in steps:
        if not run(title, script, extra, a.only):
            failed.append(script)
    print(f"\n{'#'*100}\n# 汇总\n{'#'*100}")
    if failed:
        print(f"  ❌ 失败 {len(failed)} 步：{failed}")
        return 1
    print(f"  ✅ 全部 {len(steps)} 步成功")
    print("  产物：assets/3d/rig/garments/*.blend、"
          "assets/3d/rig/manifests/garment_manifest.json、assets/3d/rig/previews/garment_*")
    return 0


if __name__ == "__main__":
    sys.exit(main())