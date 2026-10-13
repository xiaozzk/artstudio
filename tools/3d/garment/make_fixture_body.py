"""tools/3d/garment/make_fixture_body.py —— 开发用 fixture 标准体（**不是交付物**）

为什么存在
----------
T1（`bodyshape`）的真实 morph 数值未就绪时，`transfer_morph.py` 无法验证链路。
本工具用 Lead 已验证的「骨架滑块派生」口径（F5：瘦 0.86 / 壮 1.16）造一份**临时**
带 morph 的标准体，把整条服装链跑通；T1 交付后只要把 `--body-dir` 指回
`assets/3d/rig/bodies` 重跑即可（绑定数据可缓存复用，见 transfer_morph.py 的 --rebind）。

口径
----
对 SPEC §3.2 的 14 根体形骨，逐根 `pose_bone.scale = (s,s,s)`（s = 0.86 / 1.16），
其余 pose 归零，depsgraph 求值后把世界坐标烘进 `BS_Thin` / `BS_Heavy` shape key。
标准体已按 F6 把体形骨的直接子骨设成 `inherit_scale='NONE'`，所以缩放不外传。

⚠ 与真实 morph 的差别：这是「骨等比缩放」的近似，不是美术手调的体形。
   本 fixture 只用于**验证链路可跑通**，报告中的一切 morph 数值都标注 fixture 来源。

用法
----
  Blender -b --factory-startup --python tools/3d/garment/make_fixture_body.py -- \
      [--out tmp/garment/work/fixture] [--thin 0.86] [--heavy 1.16]
"""
import argparse
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="make_fixture_body.py")
    ap.add_argument("--out", default=os.path.join(C.WORK, "fixture"))
    ap.add_argument("--thin", type=float, default=0.86)
    ap.add_argument("--heavy", type=float, default=1.16)
    return ap.parse_args(argv)


def reset_pose(arm):
    for pb in arm.pose.bones:
        pb.scale = (1.0, 1.0, 1.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()


def main():
    a = parse_args()
    os.makedirs(a.out, exist_ok=True)
    report = []
    for sex in ("Female", "Male"):
        src = os.path.join(C.BODIES, f"Body_{sex}_Standard.blend")
        C.log(f"\n{'='*80}\n[fixture] {sex}  <- {C.rel(src)}")
        bpy.ops.wm.open_mainfile(filepath=src)
        arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        body = bpy.data.objects[f"Body_{sex}"]
        # 幂等：清掉旧 key 值
        C.clear_shape_values(body)
        # 记录 basis 世界坐标
        base_pts = C.eval_pts(body)
        mw_inv = body.matrix_world.inverted()
        stats = {}
        for key_name, s in (("BS_Thin", a.thin), ("BS_Heavy", a.heavy)):
            reset_pose(arm)
            missing = [b for b in C.SHAPE_BONES if b not in arm.pose.bones]
            for bn in C.SHAPE_BONES:
                if bn in arm.pose.bones:
                    arm.pose.bones[bn].scale = (s, s, s)
            bpy.context.view_layer.update()
            pts = C.eval_pts(body)
            kb = body.data.shape_keys.key_blocks[key_name]
            assert kb.name == key_name
            for i, p in enumerate(pts):
                kb.data[i].co = mw_inv @ p
            kb.value = 0.0
            disp = [(x - y).length for x, y in zip(pts, base_pts)]
            disp.sort()
            stats[key_name] = {
                "scale": s, "missing_bones": missing,
                "disp_mean_cm": round(100 * sum(disp) / len(disp), 4),
                "disp_p95_cm": round(100 * disp[int(0.95 * (len(disp) - 1))], 4),
                "disp_max_cm": round(100 * disp[-1], 4),
                "moved_frac": round(sum(1 for d in disp if d > 1e-7) / len(disp), 4)}
            C.log(f"  {key_name}(scale {s}): 位移 mean {stats[key_name]['disp_mean_cm']:6.3f} "
                  f"p95 {stats[key_name]['disp_p95_cm']:6.3f} max {stats[key_name]['disp_max_cm']:6.3f} cm  "
                  f"动过 {100*stats[key_name]['moved_frac']:.1f}%  缺失体形骨 {missing}")
        reset_pose(arm)
        C.clear_shape_values(body)
        order = [k.name for k in body.data.shape_keys.key_blocks]
        assert order == C.MORPH_ORDER, f"morph 顺序不符契约：{order}"
        # 内嵌说明，避免 fixture 被误当交付物
        tn = "README_FIXTURE"
        if tn in bpy.data.texts:
            bpy.data.texts.remove(bpy.data.texts[tn])
        bpy.data.texts.new(tn).write(
            "【开发 fixture，不是交付物】\n"
            "由 tools/3d/garment/make_fixture_body.py 生成，用于在 T1(bodyshape) 真实 morph\n"
            "就绪前把服装变形链跑通。口径 = SPEC F5 骨架滑块派生（BS_Thin 0.86 / BS_Heavy 1.16）。\n"
            "真实交付的标准体在 assets/3d/rig/bodies/，本文件在 tmp/ 下，可随时删。\n")
        out = os.path.join(a.out, f"Body_{sex}_Standard.blend")
        C.save_blend(out)
        report.append({"sex": sex, "out": C.rel(out), "shape_keys": order,
                       "verts": len(body.data.vertices), "keys": stats,
                       "source": C.rel(src)})
    p = os.path.join(a.out, "fixture_report.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"tool": "make_fixture_body.py",
                   "note": "开发 fixture：骨架滑块派生近似，不是真实美术 morph；"
                           "T1 交付后请用 assets/3d/rig/bodies/ 重跑 transfer_morph.py",
                   "bodies": report}, f, ensure_ascii=False, indent=2)
    C.log(f"\nfixture 报告 → {C.rel(p)}\nDONE")


main()