# tools/3d/garment/checks/ —— **门禁对照件**（证明判据"会变红"）

> 这三个脚本不是生产流程的一部分，而是**验收纪律的工具化**。
> 它们的存在理由：本任务里出现过**一个全零 morph 通过全部 11 项判据**的假 PASS，
> 以及**一处静默丢掉臂展项、不报错、其他数字全正常**的错误。
> **"绿"必须被验证过它会变红** —— 这三个脚本就是那条规则的执行体。
> 契约依据：`assets/3d/rig/SPEC.md` **F24 / F26 / F28**；方法论见 `task/007-morph-pipeline/lead/ACCEPTANCE.md` §七。

## 三个脚本

| 脚本 | 证明什么 | 对应判据 |
|---|---|---|
| `make_armspan_controls.py` | 造两个**应当 FAIL** 的对照角色：<br>· `ctrlB` = 漏 `NONE` 隔离（全 `FULL` + manifest 的 `bones_applied`）<br>· `ctrlC` = 漏 `along_axis_response`（`NONE` 隔离 + 只用 `(s,1,s)`） | — |
| `calib_armspan.py` | 标定**臂展**判据的两种失效模式：正确 −1.7%/+2.3%；**漏 `along` ≈ ±0.46%**；**漏 `NONE` ≥ ±50%** | **F24** |
| `test_drift_guard.py` | 验证 `derive_on_character.py` 的**偏斜守卫真的会拦下来**（读前记指纹、写前再校验，变了就 `SystemExit`） | **F18 / D-19** |

## 判别力实证（这三条是它们存在的意义）

| 对照件 | 结果 |
|---|---|
| **零 morph**（在 `M4b` 之前） | `身高比 = 1.000000 → PASS`，M1/M2/M4/M5/像素法**全部 PASS → ALL_PASS` ❌ |
| 加了 **M4b** 之后 | 抓出 **10 个 BUG 件** ✅ |
| `ctrlB`（漏 NONE） | M4c + B2-a + B2-d **三项同时红** |
| `ctrlC`（漏 `along`） | **只有 M4c 红，其余 12 项全绿** ⇒ **那处静默 2% 错误只能靠 M4c 拦住** |

## 跑法（在**工作区根**执行）

```bash
# 造对照件（写到 tmp/，不动 assets/3d/rig/garments/）
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python tools/3d/garment/checks/make_armspan_controls.py

# 标定臂展判据
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python tools/3d/garment/checks/calib_armspan.py

# 证明偏斜守卫会变红（4 情形：未改动通过 / 改动拦下 / 文件消失拦下 / 无源跳过）
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python-exit-code 1 \
    --python tools/3d/garment/checks/test_drift_guard.py
```

⚠ **跑 Blender 一律加 `--python-exit-code 1`**：`blender -b --python X.py` **在脚本抛异常时仍返回 exit 0**（SPEC 记录的门禁静默失效，`task/.../verify/run_verify.sh` 里有三重保险与 `--selftest`）。