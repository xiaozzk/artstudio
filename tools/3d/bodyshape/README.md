# tools/3d/bodyshape/ —— 体形派生工具链（骨骼滑块 → 烘 BS_Thin / BS_Heavy）

> 契约：[`assets/3d/rig/SPEC.md`](../../../assets/3d/rig/SPEC.md) v1.0 §3.2 / §3.3 / §3.4 / F13 / F14 / F18
> 维护者：`bodyshape`｜任务：[`task/007-morph-pipeline/TASK.md`](../../../task/007-morph-pipeline/TASK.md)（T1、T5）
> **当前冻结版本：spec v2.0 —— `thin 0.84` / `heavy 1.21`**
> `coefficients_fingerprint = ca93ef919b15340df2123bd397fd4b43c8658d4ef539e4a678319c2f69821ba2`
> （下游判版本请只认 manifest 的 `spec_version` + `coefficients` + `coefficients_fingerprint`）

## 0. 一句话

标准体只生成一次；**瘦/壮不重新生成**，而是给体形骨摆 pose scale，再把骨架形变
**烘成一张逐顶点偏移表（shape key）**，最后清 pose、清权重回写文件。

```
Body_*_Standard.blend  ──① 按 spec 摆 14 根体形骨的 pose scale──▶  depsgraph 求值
      ▲                                                                │
      └────④ 清 pose / 清权重，只回写 BS_Thin / BS_Heavy 的坐标 ◀──② 抄进 shape key
                                                                       │
                                       ③ 清 pose → 渲染 瘦/标准/壮 三档并排 ◀┘
```

**B2 路线（SPEC F17 / §4.0）下同一套工具直接复用**：把"标准体"换成**角色自己的网格 + rig**，
逐件烘 shape key 即可 —— `silhouette_metric.py` 的 `--target tryon` 就是这么跑的。

## 1. 交付物

| 路径 | 是什么 |
|---|---|
| `bodyshape_core.py` | **系数展开的唯一实现**（derive / measure_girth / silhouette_metric 共用，杜绝公式漂移） |
| `bodyshape_spec.json` | **源头 spec**：体形骨列表 + 每档 `target_coefficient` + `delta_response` + `along_axis_response` + 物化好的 `tiers[].bones` + `rationale` |
| `derive.py` | headless Blender CLI：烘焙 + 回写 + manifest + 预览图 |
| `verify_bodyshape.py` | 独立验收：重开文件实测 + 结构不变量 + 与 manifest 对账（28 项断言） |
| `measure_girth.py` | **T5**：关键围度 % + 系数响应曲线 + 网格健康度 + 插值精确性 |
| `silhouette_metric.py` | **T5**：剪影 XOR / 面积 / 宽度剖面 + 换算成"等效身高变化" |
| `check_height_method.py` | **T5**：身高缩放法（`root` 骨 vs 对象级）× `inherit_scale` 的相容性实测 |
| `check_digest_convention.py` | **跨成员**：canonical morph digest 的复算与对账（附"空 morph"护栏） |
| `../../assets/3d/rig/bodyshape_spec.json` | spec 的**同步副本**（`derive.py` 每次自动同步，不允许漂移） |
| `../../assets/3d/rig/manifests/bodyshape_manifest.json` | 数字台账：版本/系数指纹 / 三档顶点数 / 位移 / 身高比 / 数据量 / digest |
| `../../assets/3d/rig/previews/bodyshape_{Female,Male}.png` | 瘦 0.84 / 标准 1.00 / 壮 1.21 三档并排真实渲染（间距 1.9 m > 臂展，手臂不叠不裁） |
| `../../assets/3d/rig/reports/bodyshape_strength.json` | T5 围度与健康度报告 |
| `../../assets/3d/rig/reports/bodyshape_silhouette.json` | T5 剪影可分辨性报告 |
| `../../assets/3d/rig/reports/bodyshape_v2_recommendation.md` | T5 结论：判据 / 加档成本 / 索引顺序建议 |

## 1.1 ⚠ `inherit_scale` 是**契约**，不要为了"统一"去改（SPEC F18）

| 目录 | 现状 | 是否符合契约 |
|---|---|---|
| `assets/3d/rig/bodies/*.blend` 的标准体 | `FULL 47 / NONE 18` | ✅ 符合（那 18 根 = **14 根体形骨的直接子骨**） |
| `assets/3d/rig/garments/*.blend` | `FULL 65` | ✅ 符合 |

**不要**把 `bodies/` 的 18 根 `NONE` 改成 `FULL` 去"对齐"服装。
标准体上这 18 个 `NONE` 是**烘焙期工件**：没有它，摆体形骨时缩放会沿骨架链一路传下去，
烘出来的 morph 会连身高一起改（F6 原始症状：scale `pelvis` → 身高意外 +11.24%）。
服装那份是全 `FULL`、也**不需要**改 —— 服装自己的 morph 是**从角色 rig 传来的偏移表**，
不靠在服装文件上摆骨得到。**两者各自满足契约，互不矛盾。**

> 推论（T5 踩到的静默失败）：任何**在未规范化 rig 上摆体形骨**的工具都必须自己先把这条规则设上，
> 否则结果是错的且**不报错**。`silhouette_metric.py` / `measure_girth.py` 都已内置，
> 并把"本次新设了几根"记进报告。

### 1.1.1 `derive.py` **自设**这条规则（幂等），不再硬失败

早期版本是"输入必须已设好，否则 `raise SystemExit`" —— 那会让 **Tripo 生成的新标准体**
（不会带这个设置）在**换身体的第一个环节**就把工具挡死。现在改为：

```
normalize_inherit_scale(arm, spec)   # 幂等：已是 NONE 的不动；返回 (本次改动的骨, 输入原始值)
        ↓
check_inherit_scale(arm, spec)       # 自检保留：设完之后再校验，此时必须 0 违规（否则才 raise）
```

manifest 每个 body 多一行 `inherit_scale_normalization`：

| 字段 | 含义 |
|---|---|
| `direct_children_count` | 14 根体形骨的直接子骨总数（=18） |
| `input_non_none_count` / `input_already_normalized` | **本次输入**原本是 NONE 还是 FULL |
| `set_to_none_this_run` / `n_set_this_run` | 本次实际改了几根 |
| `post_set_violations` | 自设之后的自检结果（必须 `[]`） |
| `delivered_state` | 保持 `NONE`（SPEC F18：`bodies/` 的 NONE 是烘焙期工件） |

**等价性已实测**（morph 逐位相同，这才是关键）：

| 输入 | 行为 | `BS_Thin` digest | `BS_Heavy` digest |
|---|---|---|---|
| `FULL 47 / NONE 18`（已规范化） | 本次设 **0** 根 | `6a0f0b08170ed694…` | `9a75f5cb3666e7d9…` |
| **`FULL 65`（完全未规范化）** | 本次设 **18** 根 | `6a0f0b08170ed694…` **逐位相同** | `9a75f5cb3666e7d9…` **逐位相同** |

两种输入跑完产物都是 `FULL 47 / NONE 18`。→ **换身体（Tripo）时这条不再是个坑。**

### 1.1.2 ⚠ 身高缩放必须用**对象级**，不能用 `root` 骨 —— 且这与 F18 无关（实测）

有人会问："`bodies/` 留着 18 根 `NONE`，那标准体的**身高滑块**不就不准了吗？"
**不会** —— 前提是身高走**对象级等比缩放**（SPEC §3.4 现行写法 / F12）。实测见
`check_height_method.py`（口径与 `verify/vlib.py` 一致：`dispersion_rel = (P99(r) − P01(r)) / median(r)`，阈值 0.01）：

| 资产 | `inherit_scale` | ① `root` **骨**缩放 | ② 骨架**对象**等比缩放 |
|---|---|---|---|
| `Body_Female_Standard` | **NONE × 18** | +0.498%（不是 +8%）**离散度 0.0786 ❌** | **+8.000%，离散度 0.0000385 ✅** |
| `Body_Male_Standard` | **NONE × 18** | +0.443% **离散度 0.0799 ❌** | **+8.000%，离散度 0.0000320 ✅** |
| `TryOn_Female_Ranger` | FULL × 65 | +8.000%，离散度 0.0000320 ✅ | +8.000%，离散度 0.0000281 ✅ |
| `TryOn_Male_Ranger` | FULL × 65 | +8.000%，离散度 0.0000271 ✅ | +8.000%，离散度 0.0000246 ✅ |

**读法**：
* ①`root` **骨**缩放走骨架层级 → F6 把中层断开 → 缩放传不过去 → 部分骨段长、部分不长 → 离散度爆表。
  **这正是 SPEC F12 废弃它的原因**，与"该不该留 NONE"无关。
  `garment` 量到的 NONE 0.0257–0.0760 就是这个方法（我复现到 0.0786 / 0.0799）。
* ②**对象级**缩放是对象级仿射变换，整套求值结果被统一缩放，**与骨架层级、与 F6 完全无关** →
  即使 `bodies/` 留着 18 根 `NONE`，离散度 **0.0000385**，比阈值好 **260×**。
* → **`bodies/`（NONE×18）与 `garments/`（FULL×65）各自都满足契约，两边都不用改。**
  F6 是**烘焙期**契约（F18），§3.4 是**运行时**契约，两者正交 —— 只要运行时用对象级。

> 附带一条我自己踩的坑：写这个 A/B 时 `reset()` 忘了清 `arm.scale`，于是下一种方法继承了
> 上一种的缩放、量到 `1.08² = +16.64%`，差点报出一条**不存在的**"双次应用"结论。
> → 量 A/B 多状态时 **reset 必须覆盖所有会被改的字段**（骨 pose **和** 对象 scale 都要清）。

## 2. 用法

**一律在工作区根下执行。**

```bash
# 全流程：两具身体 → 烘 morph → 回写 .blend → manifest → 三档预览图
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
    --python tools/3d/bodyshape/derive.py -- --sex both

# 只做一具、不渲染（快）
... --python tools/3d/bodyshape/derive.py -- --sex Female --no-render

# 跑通全流程但不落盘（改档位系数前先预演）
... --python tools/3d/bodyshape/derive.py -- --sex both --dry-run

# 换口径复现 SPEC §1 F5 那份"13–14 cm"（含骨长，会改身高）
... --python tools/3d/bodyshape/derive.py -- --sex Female --axis-profile length --dry-run

# 调档位强度（--retune 默认不落盘；加 --write-spec 才持久化，两份 spec 同步）
... --python tools/3d/bodyshape/derive.py -- --retune thin=0.80,heavy=1.25 --write-spec

# 独立验收（--baseline-dir 传未加工的 bodies 副本，验"结构未被改动"）
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
    --python tools/3d/bodyshape/verify_bodyshape.py -- --baseline-dir <未加工副本目录>

# 不开 Blender 也能看帮助
python3 tools/3d/bodyshape/derive.py --help
python3 tools/3d/bodyshape/verify_bodyshape.py --help
```

> Blender 会吃掉自己的参数，所以**我们自己的参数必须放在 `--` 之后**。脚本同时兼容
> 不带 `--` 的调用（直接取 `sys.argv`）。

## 3. 口径（这些数字都是实测出来的，别凭直觉改）

### 3.1 骨骼缩放口径 = `girth`（默认）

`pose_bone.scale` 是**骨骼局部轴** `(x, y, z)`，其中 **Y 恒为沿骨轴**（head→tail）。

| 口径 | `pb.scale` | 含义 | 实测（系数 0.86 / 1.16，Body_Female） |
|---|---|---|---|
| **`girth`（默认）** | X/Z 按 `delta_response`、Y 按 `along_axis_response`（默认 0） | 垂直于骨轴的两轴改**周长**；沿骨轴只对**水平骨**开 | 最大位移 **2.90 / 3.31 cm**，身高比 **1.00017 / 0.99981** |
| `length` | `(s, s, 1)` | 含沿骨轴缩放（=改骨长） | 最大位移 **11.35 / 12.97 cm**，身高比 **0.89849 / 1.11601** |
| `uniform` | `(s, s, s)` | 三轴齐缩 | 同 `length` 量级 |

**为什么默认 `girth`**：SPEC §3.4 / D3 要求"身高交给**骨架对象/角色根节点**等比缩放"，
体形 morph 必须与身高**正交**。`length` 口径下"最大位移 13–14 cm"看起来很壮观，但那是**腿长变化**——
代价是身高一起 ±11%（瘦档整个人矮 10%，壮档高 11.6%），而且头/颈区域也被拖着动
**73 / 83 mm**（因为整条骨链位置都变了）。`girth` 口径下头/颈只动 2.9 / 3.4 mm
（来自肩颈顶点的混合权重），身高纹丝不动。

→ SPEC §1 F5 那个"14.00 / 13.42 cm"就是这么来的，**不是体形指标**。留档在 manifest 的
`reference_f5_demo_profile` 里，用 `--axis-profile length` 一条命令即可复现对账。

### 3.1.1 ⭐ `along_axis_response`：只对**骨轴水平**的骨开（v2 新增）

`bone_scale.y = 1 + (coef-1) × along_axis_response[group]`，默认 **0**。

"沿骨轴缩放会改身高"这条规则**只对竖直骨成立**。骨轴**水平**时，沿骨轴缩放改的是**宽度**。
锁骨（`clavicle_l/r`）的 head/tail **z 完全相同** → 精确水平 → 沿它缩放 = 改**肩宽/臂展**，
**身高代价为 0**（v2 实测身高比仍是 1.00019 / 0.99975）。

为什么值得开：T-pose 下**臂展 1.67 m 是正视图里最宽的轮廓线**，v1 里它只动 ±0.46%
（因为锁骨只缩了垂直轴），于是整体轮廓"看起来没变"，哪怕躯干粗了 15%。
v2 开 `clavicle 0.5` 后臂展动 **±1.7–2.3%**、肩关节间距 **±9.5–12.5%**（≈2–2.5 SD，真实双肩宽 SD/均值 ≈ 3.5–5%）。

**其他骨一律保持 0**：`pelvis`/`spine_*`/`thigh`/`calf` 骨轴竖直（等于改身高），
`upperarm`/`lowerarm` 骨轴是臂长方向（等于改臂长）。要新开必须先证明该骨"骨轴与世界 Z 近乎垂直"。

### 3.2 每档的骨系数（**v2 冻结值**）

`bone_scale.x = bone_scale.z = 1 + (target_coefficient - 1) × delta_response[group]`

`delta_response`（v2）：`pelvis 1.0 / spine_01 1.0 / spine_02 1.0 / spine_03 1.0 /
thigh 0.95 / calf 0.85 / upperarm 1.05 / lowerarm 0.95 / clavicle 0.8`
`along_axis_response`（v2）：`clavicle 0.5`，其余 0

v1 → v2 的两处实质修正：
1. `spine_02/spine_03` 0.92/0.85 → **1.0**：v1 的**胸腔响应只有骨盆的 72%**（胸 −9.8% vs 臀 −13.6%），
   而衣服下胸腔比骨盆更显眼，这里被压住最亏。
2. `clavicle` 0.5 → 0.8 **且新开沿骨轴 0.5**：把轮廓最宽的维度接回来。

**调档位强度只改一处**：`spec.tiers[].target_coefficient`（或用 `--retune`）。
`tiers[].bones` 存的是**实摆三轴向量** —— 就是 `axis_profile.rule` 说的那一份，
也是 manifest 的 `bones_applied` 那一份（**两者必须相等**，`derive.py` 每次对账，对不上直接报错）。
可以直接摆到 pose bone 上；**规范形** `(s,1,s)`（不含 `along`）另存 `tiers[].bones_canonical_girth`，
**仅供参照，不要拿来摆骨**。

> ⚠ **历史缺陷（v2.0，已修）**：v2.0 时 `tiers[].bones` 存的是**规范形** `(s,1,s)`，而 spec 自己的
> `axis_profile.rule` 却说 `y = 1+(coef-1)·along_axis_response` —— **spec 自相矛盾**。
> 消费方最自然就是读 `tiers[].bones` 去摆骨，于是**照 spec 读反而丢掉肩宽/臂展项、且不报错**
> （`garment` 实际踩到，我在 T5 也踩过一次，假差 11.6 mm）。
> v2.1 起改为存实摆三轴：**让"最自然读到的那一块就是对的"**。
> 教训：**一个会误导消费方的字段，等于一个 bug** —— 即使代码路径全对。

### 3.3 morph 通道顺序（契约，改不得）

| shape key | Blender `key_blocks` 索引 | glTF morph target 索引 | 含义 |
|---|---|---|---|
| `Basis` | 0 | —（不导出） | 标准体 |
| `BS_Thin` | 1 | **0** | 瘦，`target_coefficient = 0.86` |
| `BS_Heavy` | 2 | **1** | 壮，`target_coefficient = 1.16` |

⚠ **两套索引别混**：Blender 的 `key_blocks[0]` 永远是 `Basis`；glTF 的 morph target 0 是
`BS_Thin`（Basis 不作为 target 导出）。SPEC §3.3 表格里写的"索引 0 / 1"是**后者**。
manifest 里两个索引都记了。

交付态：三档权重**全为 0**（= 标准体）。运行时权重 ∈ `[0, 1]`。

## 4. 已知坑（都真踩过）

1. **shape key 不改 `mesh.vertices`**（SPEC F9）。读 `obj.data.vertices` 只会拿到 Basis 的
   坐标，量出来的位移**永远是 0**。必须
   `bpy.context.evaluated_depsgraph_get()` → `obj.evaluated_get(dg)` → `to_mesh()`。
   `to_mesh()` 与 `key.data[i].co` 都是**对象局部空间**，可以直接互相赋值。

2. **`inherit_scale='NONE'` 只断了「缩放」的继承，没断「位置」的继承。**
   缩 `pelvis` 时 `thigh_l.head` 会沿世界 X 内移 ≈12.6 mm（0.09 m × 14%），于是
   **脚也会跟着动 ≈15.9 mm** —— 尽管脚上一根体形骨都没有（权重全在 `foot_l`/`ball_l`）。
   这不是 bug，是想要的效果（胯变窄、腿自然内收），但它推翻了一个很自然的直觉断言
   "体形骨零权重的顶点不该动"。
   → 真正可证伪的不变量是：**一个顶点的全部加权骨的「姿态矩阵」都没变 → 它必须一点不动**。
   `derive.py` 现在按这个算（`pose_invariant_indices()`），实测这些顶点的位移是
   **122–137 纳米**（float32 舍入），并作为硬断言写进流程。
   → 顺带：`girth` 口径下 62/65 根骨的姿态矩阵会变，`length` 口径下 64/65。

3. **幂等要靠"烘之前先归零"。** shape key 的 `data[i].co` 是**绝对坐标**（偏移 =
   `key.co - basis.co`），不是增量。第二次跑如果没先把 `BS_*` 的 `value` 归零，
   depsgraph 会把上一次的结果**叠进**这一次。`derive.py` 每次烘之前都
   `zero_morph_weights()` + `clear_pose()`。
   实测：连跑两次，`shape_key_data_sha256`、`max_displacement_m` 等**全部数字逐位一致**。

4. **快照/还原 pose。** 上游资产里本来就带着 ±1e-6 的 pose 浮点噪声（`scale` 1.4e-06 级）。
   我们只被授权改 shape key 数值，所以 `derive.py` 先快照全骨 pose、清成 rest 再烘、
   最后原样还原。副产品是：**量位移必须在 rest 态量**，否则这 1e-6 的噪声会污染
   第 6 位小数（`verify_bodyshape.py` 一开始就是这么差分出来的）。

5. **渲染辅助对象绝不能进 `bodies/*.blend`。** 预览要相机 + 灯 + 三份副本 + 文字标签，
   这些一旦被保存就改变了资产结构（违反"骨架/网格结构不得改"）。所以顺序是
   **先回写 `.blend`，再在内存里搭渲染场景**，并且全流程只在最后渲染、**渲染后不再保存**。

6. **`bpy.context.preferences.filepaths.save_version = 0`**，否则每次保存都留下 `.blend1`。

7. **`mathutils.Quaternion` 的索引 0 是 `w`，不是 `x`。** 用 `q[0..2]` 当"旋转偏差"会
   永远得到 1.0（单位四元数的 w）。要取 xyz 得用 `q[1..3]`。

8. **文字标签只用 ASCII。** Blender 默认内置 `Bfont` 没有中文字形，写中文会渲染成空白/方块。

9. **`--help` 在没装 bpy 的普通 Python 下也要能用**：脚本顶层 `try: import bpy`，
   失败时只放行 `--help`，其余报错退出。方便 CI 和人工查用法。

10. **别在一次求值里跨多个对象复用结果。** 用一次性诊断脚本量"摆 pose"与"用 shape key"
    两条路线时，曾在一个循环里连续对 Body/Eyebrows/Eyes 取 `to_mesh()`，量到 0.85 mm 的
    一次性偏差；改成**单对象、每次改完状态先 `view_layer.update()` 再取**，两条路线的
    逐顶点最大差是 **0.00043 mm**（float32 精度）——**烘焙是精确的**。
    → 测量循环里状态一变就 update，别贪省一次求值。

11. **⭐ pose 与 shape key 是两套独立的形变来源，会叠加。** 用摆骨量形之前**必须先把
    shape key 权重清零**（`measure_girth.py: zero_keys()`）。只清 pose 不清权重，量到的就是
    "pose + 当前 weight 的 morph"，数字**全错且不报错** —— T5 在这里读到过 **33 mm 的假差**，
    并把"线性插值是否精确"误判成不成立。
    配套的廉价保险：**同一个状态连量两次，两条结果必须逐顶点相同**
    （`assert_stable()`，容差 1 µm）。就是它把这个 bug 抓出来的。

12. **`ortho_scale` 是"较长那条传感器边"的长度，不是宽度。** 竖构图时它对应**竖向**：
    按宽度去算 ortho_scale 会把 T-pose 的手臂裁掉，于是"最大行宽"恒等于图宽（指标静默失效，
    看起来还"合理"）。正确写法：竖构图 `ortho = max(h, w * res_y/res_x)`。

13. **在未规范化 rig 上摆体形骨是静默失败。** `bodies/` 的标准体已经把 F6 规则
    （体形骨的直接子骨 `inherit_scale='NONE'`）烘进文件，但 `assets/3d/blend/tryon/` 的角色**没有**。
    不自己设就摆骨 → 缩放沿骨架链传下去 → 剪影直接炸（实测瘦档宽度 **−44%**，正确值是个位数）。
    `measure_girth.py` / `silhouette_metric.py` 现在都对任何 target 先设一遍并记进报告。

14. **"等效换算"必须在实测曲线上分段插值，不能从端点线性折算。** 身高标尺的
    XOR 曲线是**凹的**（饱和），拿 `x / XOR(8%) * 8` 会系统性高估 —— 实测把 5.45% 报成 6.82%。

15. **检查"morph 混合 == 等价 pose"时，要插值完整的三轴向量。** v2 起 `clavicle` 的 Y≠1，
    只取 `tiers[].bones[b][0]` 再摆 `(s,1,s)` 会丢掉沿骨轴那一项 → w=0 就开始报假差（11.6 mm）。
    统一走 `bodyshape_core.applied_bones()`。

16. **shape key 驱动的 morph，不能用"骨的位置"当判据。** 体形 morph 若是**烘进 shape key** 的
    （B2 路线），骨骼**一个都不动** —— 你去读 `pose.bones[...].head` 只会拿到 rest 值，
    算出来恒为 0%（我实测就是这样，差点误报"肩宽没响应"）。
    → 判据必须落在**网格顶点**上（AABB 跨度 / 剪影 / 顶点位移）。

17. **A/B 多状态测量时，reset 必须覆盖"所有会被改的字段"。** 量"`root` 骨缩放 vs 对象级缩放"时
    我的 `reset()` 只清了骨 pose、忘了清 `arm.scale` → 第二种方法继承了第一种的缩放，
    量到 `1.08² = +16.64%`，差点报出一条**不存在的**"scale 被应用两次"结论。
    → 对象 scale、骨 pose、shape key 权重、对象可见性，**四类状态都要在 reset 里清**。

## 4.1 身体以外：头 / 眼 / 眉 完全不动（实测）

`girth` 口径下 65 根骨里**只有 `root` / `neck_01` / `Head` 三根的姿态矩阵没变**
（62 根被牵动），所以：

* `Eyebrows`（912 顶点）与 `Eyes`（556 顶点）在瘦/壮两档的位移是 **0.000 cm**（逐顶点精确 0），
  它们刚性挂在 `Head` 上，**不需要 morph 通道**，也不会有面部接缝；
* 之前口径里那个"头/颈 ≤ 4.2 mm"是**颈↔肩权重混合区**的顶点（部分权重在 `clavicle`/`spine_03` 上），
  **不是头在平移**。

## 5. 验收口径（`verify_bodyshape.py`，**38 项断言**全过）

| 断言 | 判据 |
|---|---|
| 三档顶点数一致 | `BS_Thin` / `BS_Heavy` 求值后顶点数 == Basis（7376 / 7281） |
| shape key 名称 + 顺序 | `['Basis', 'BS_Thin', 'BS_Heavy']`，与 SPEC §3.3 一致 |
| 14 根体形骨齐全 | 逐名核对，不是凭记忆 |
| `inherit_scale='NONE'` | 14 根体形骨的**全部直接子骨**（18 根）都是 `NONE` |
| **结构未被改动** | 网格顶点/拓扑/材质/**顶点组权重**/骨架骨名+顺序+rest 矩阵/修改器/内嵌文本/贴图路径 的 sha256 == 基线 |
| 体形与身高正交 | 各档身高比 \|Δ\| < 0.005（实测 ≤ 0.0002） |
| morph 数据量 | ≤ 顶点 × 12 字节（实测 86.4 / 85.3 KB/档） |
| 与 manifest 对账 | 重开文件量到的数字 + shape key digest 必须与台账一致 |
| 交付态权重全 0 | SPEC §3.3 默认标准体 |
| **spec ↔ manifest 版本对账** | `manifest.spec_sha256` == 当前 spec 文件；`coefficients` / `delta_response_values` / `along_axis_response_values` 逐项相等；`coefficients_fingerprint` **按同一配方重算一致** |
| **`spec.tiers[].bones` ≡ `manifest.bones_applied`** | 逐骨逐档比对（14×2） |
| ⭐ **spec ↔ 已烘 morph 的几何闭环** | 按 `spec.tiers[].bones` **重新摆一次骨**，与已烘的 shape key **逐顶点比对**，要求 < 0.01 mm（实测 **0.000000 mm**） |

### 5.1 为什么加"几何闭环"这一条

原来 28 项断言只证明 **「文件 ↔ manifest 自洽」** —— 若有人**改了 spec 的系数却没重烘 bodies**
（D-1 那类版本偏斜），两边各自都"自洽"，**全部会绿**，而下游拿到的是新系数配旧产物。

现在最后一条把环闭上：**几何上证明"烘出来的形状就是 spec 说的形状"**。

**这条门禁验证过它会变红**（造一份"coefficients: 0.84→0.85 但不重烘"的偏斜 spec）：

| 断言 | 结果 |
|---|---|
| `manifest.spec_sha256` == 当前 spec | ❌ FAIL |
| `manifest.coefficients` == spec | ❌ FAIL（0.84 vs 0.85） |
| `coefficients_fingerprint` 重算一致 | ❌ FAIL（`ca93ef91…` vs `3cfa57b8…`） |
| `tiers[].bones` ≡ `bones_applied` | ❌ FAIL（14 处） |
| **已烘 morph == 按 spec 重摆骨** | ❌ FAIL（女 2.070 mm / 男 2.232 mm） |

→ **6 项 FAIL**（旧的 28 项全绿）。**"没验证过会变红的门禁不算门禁"。**

## 6. 实测数字（Blender 5.2.2 LTS，**v2 冻结版**）

| 身体 | 顶点 | 档 | 最大位移 | 均值位移 | 身高比 | 数据量/档 | 头/颈位移 |
|---|---|---|---|---|---|---|---|
| Body_Female (7376) | 7376 | `BS_Thin` 0.84 | 3.31 cm | 1.285 cm | 1.00019 | 86.4 KiB | 4.17 mm |
| Body_Female | 7376 | `BS_Heavy` 1.21 | 4.35 cm | 1.687 cm | 0.99975 | 86.4 KiB | 5.47 mm |
| Body_Male (7281) | 7281 | `BS_Thin` 0.84 | 3.57 cm | 1.565 cm | 0.99999 | 85.3 KiB | 5.55 mm |
| Body_Male | 7281 | `BS_Heavy` 1.21 | 4.69 cm | 2.054 cm | 1.00002 | 85.3 KiB | 7.28 mm |

全套（两具身体：烘 4 档 + 回写 + manifest + 2 张 2800×1000 预览）**~5 s**。

补充实测：

| 项 | 数字 |
|---|---|
| 烘焙保真度（摆 pose vs 用 shape key，逐顶点最大差） | **0.00043 mm** |
| **morph 线性插值精确性**（w=0…1 与等价 pose 的最大差） | **0.00037–0.00061 mm** → 插值**精确**，加档不会产生"不像人"的中间态 |
| 姿态完全冻结的顶点数（瘦/壮两档各自的严格不变量集） | 1473（女）/ 1314（男），位移 121–137 **纳米** |
| 姿态被牵动的骨 | 62/65（`girth`）；冻结的是 `root` / `neck_01` / `Head` |
| `Eyebrows` / `Eyes`（含头）两档位移 | **0.000 cm** |
| 幂等（连跑两次） | `shape_key_data_sha256` 与全部数字**逐位一致**；`.blend` 字节不同（Blender 序列化的固有非确定性），结构指纹一致 |
| 几何安全包络（翻转面 = 0） | 0.58 ≤ coef ≤ 1.45（女）/ ≤1.25（男）；腿间隙始终 > 0（0.58 时仍 +0.63 cm） |

## 7. T5：档位强度评估与 v2（**冻结**）

### 7.1 判据（可复算，不靠"看起来明显吗"）

1. **关键围度**（胸/腰/臀/上臂/大腿/小腿）三档变化 % —— `measure_girth.py`。
   切片 → 投影 → **2D 凸包周长**：凸包等价于软尺量法，且对**破洞与面绕向免疫**
   （标准体 26 个连通域 / 48 条边界环，SPEC F15 → "边界环求周长"必然错）。
2. **剪影 XOR 差异率 / 面积 / 宽度剖面** —— `silhouette_metric.py`（透明胶片 alpha）。
3. ⭐ 用**已被认可"看得出来"的身高滑块**（对象级等比 1.00→1.08）当标尺，
   把 2 换算成**"等效身高变化"**。诚实边界：纵向 vs 横向分布不同 →
   它是**量级标尺**，不是严格心理物理等价；两个量都报。

### 7.2 结果

| | v1（0.86/1.16） | **v2（0.84/1.21）** |
|---|---|---|
| 臀围（女） | −13.6% / +15.6% | **−15.5% / +20.6%** |
| 胸围（女） | −9.8% / +11.4%（只有骨盆的 72%） | **−14.3% / +18.8%**（与骨盆齐平） |
| 上臂围（女） | −14.7% / +20.8% | **−16.8% / +27.4%** |
| 臂展（最宽轮廓） | −0.41% / +0.47% ← **真短板** | **−1.73% / +2.27%** |
| 肩关节间距 | −2.3% / +2.6% | **−9.5% / +12.5%** |
| 剪影 XOR（女 B2 角色） | 26.96% | **33.57%** |
| ≈ 等效身高变化（女 B2） | 3.98% | **5.55%** |
| 剪影面积 | −10.4% / +11.8% | **−12.8% / +16.8%** |

**v1 的结论**：围度变化本来就大（臀/腰 ≈ ±14%），"看起来弱"的真因是**轮廓最宽的维度没动**。
**v2**：把上身响应从骨盆的 72% 拉到 100%，并用 `along_axis_response.clavicle` 免费拿回肩宽响应
（锁骨精确水平 → 身高代价 0）。等效身高从 3.98% → 5.55%（**+41%**），
≈ 身高滑块可用区间的 **62–69%**。

### 7.3 加第 3 档的成本 / 索引顺序

* **数据量**：每档 = `顶点数 × 12 B`。B2 全角色（27,920 顶点）**327.2 KiB/档**，
  2 档 654.4 → 3 档 981.6 KiB（**+50%**）。标准体 86.4 KiB/档。
* **改文件面（追加在末尾时最小）**：只需在 spec 加一个 `tiers[]` 条目；
  `derive.py` / `verify_bodyshape.py` **完全数据驱动，不用改**；
  `garment` 若按"遍历 spec.tiers"写也不用改；`godot-preview` 要加第 3 个控件；SPEC §3.3 加一行。
* **中间态**：**不会"不像人"** —— LBS 对每骨缩放是**仿射线性**的，
  `w·v(s_thin)+(1-w)·v(s_heavy) ≡ v(w·s_thin+(1-w)·s_heavy)`，已实测到 **0.0004 mm**。
  唯一风险是"给不同部位独立系数"（目前单一系数驱动，不存在）。
* **索引顺序**：**追加在末尾**（`BS_Stocky` → glTF target 2 / key_block 3）。
  glTF 按下标引用 target，追加不改变 0/1 含义 → **已产出的服装/角色 morph 全部继续有效**；
  重排 = 所有下游产物**静默变形**（不报错，只是 `BS_Heavy` 变成别的东西）。

> 完整论证与数字见 [`assets/3d/rig/reports/bodyshape_v2_recommendation.md`](../../../assets/3d/rig/reports/bodyshape_v2_recommendation.md)。

### 7.4 canonical morph digest —— 跨成员对账口径（**已互验**）

两个成员独立实现了"morph 数据指纹"，各自报告里的 digest 要能互相复算，就必须把打包口径钉死：

```
1. 取所有【带 shape key】的 MESH 对象，按对象名**字典序排序**（不是遍历顺序）
2. 对目标 shape key K：逐顶点取 key_blocks[K].data[i].co 的**绝对坐标**
   （⚠ 不是相对 Basis 的偏移）→ struct.pack("<3f", x, y, z)
3. digest = sha256(字节流)，报告里取前 16 位十六进制
```

**两个易错点**（都实测过）：
* **绝对坐标 vs 偏移**：Female_Ranger `BS_Thin` → abs = `e5346f1cf12a6dbe`，
  delta = `4176e0edb5713f1f`，**完全不同**。口径必须写清楚。
* **件序必须先排序**：按 `bpy.data.objects` 遍历顺序在不同文件/版本下可能不同。

**工具自带负对照（自诊断）**：`check_digest_convention.py` 对每个 shape key **同时**算出
"错误口径（相对 Basis 的偏移）"的 digest，写进 JSON 的 `negative_control`。
→ 若某份报告的数字对不上，**先比负对照**：命中负对照值 = **口径问题**，不是数据问题。
（`negative_control.differs_from_canonical` 为 `false` 会另报警 —— 那说明该 shape key 是常量，
正负口径碰巧相同，digest 失去判别力。）
另附一个**空 morph 护栏**：`nonzero_vertex_count` 为 0 直接标 `empty_morph` ——
"空 morph"会让任何"通过"的判定变成假 PASS。

**互验结果（2026-10-13）**：用 `check_digest_convention.py` 从 `garment` 交付的
`assets/3d/rig/garments/*.blend` 复算其公布的 4 套 × 2 档 digest → **8/8 逐位相同**：

| 套 | BS_Thin | BS_Heavy |
|---|---|---|
| Female_Ranger | `e5346f1cf12a6dbe` | `6d87cac343fd772d` |
| Female_Peasant | `2f1e1a18e76f609f` | `33c7cfe143a2e33a` |
| Male_Ranger | `ee34ee72fb0dd997` | `7864b3144db1538b` |
| Male_Peasant | `4905a02aa50cbaa9` | `7d011d19451e9d61` |

> `verify_bodyshape.py` 的 `shape_key_data_sha256` 用的是**同一个打包原语**，但作用域是
> **单个对象**（标准体的 body 网格）；上面这套是**多件按名排序**。**scope 不同、原语相同** ——
> 两者不能直接比数值，只能比"同一 scope 下两方算法是否一致"。
> **本工具是唯一能立刻复算跨成员 digest 的东西，请留在仓库里。**

### 7.4.1 怎么复核「B2 服装 morph 真的带上了 `along` 项」（判据要有判别力）

光看 digest 相同只能证明"两方算法一致"，**证明不了 morph 的形状对不对**。判别力在**臂展**：

| 口径 | `BS_Thin` 臂展 | `BS_Heavy` 臂展 |
|---|---|---|
| 漏了 `along`（只用 `(s,1,s)`） | ≈ **−0.46%** | ≈ **+0.46%** |
| **带 `along`（v2 正确）** | ≈ **−1.7% ~ −2.0%** | ≈ **+2.3% ~ +2.6%** |

实测（直接从 `assets/3d/rig/garments/*.blend` 读网格 AABB 跨度）：

| 套 | thin 臂展 | heavy 臂展 | 身高比 |
|---|---|---|---|
| Female_Ranger / Peasant | **−1.74%** | **+2.28%** | 0.99891–1.00019 / 0.99975–1.00143 |
| Male_Ranger / Peasant | **−1.96%** | **+2.57%** | 0.99997–0.99999 / 1.00002–1.00020 |

→ 落在"带 `along`"那一档，**修复生效**。这是一个**能变红**的判据（漏项时会掉到 ±0.46%），
不是"看起来对"。

> ⚠ 复核时**不要去读骨的位置**（见坑 #16）：B2 的 morph 烘在 shape key 里，骨骼一个都不动，
> 读 `pose.bones[...].head` 恒得 0%，会让这个判据**恒绿**、彻底失去判别力。

### 7.4.2 这条门禁**验证过它会变红**

修完 `tiers[].bones` 的语义后，我把**旧口径**（`clavicle_l = [0.872, 1.0, 0.872]`）塞回一份 tmp spec，
`derive.py` **拒绝运行**并指名道姓：

```
spec 的 tiers[].bones 与 delta_response/along_axis_response 推导结果不一致（spec 漂移）
—— 注意 v2.1 起 tiers[].bones 必须存**实摆三轴**（y 也带 along_axis_response），不再是规范形 (s,1,s)：
  clavicle_l: 按规则推导=[0.872, 0.92, 0.872] spec 声明=[0.872, 1.0, 0.872]
```

→ `garment` 当初踩的那个坑（照 spec 读 → 静默丢项、**不报错**）现在变成**硬错误**。
**没验证过会变红的门禁不算门禁** —— 这条和 §7.4.1 的臂展判别力是同一件事的两面。

### 7.5 下游判版本怎么判

**消费方该读哪一份 `bones`（F25）**
> **读 `spec.tiers[].bones`（= `manifest.tiers[].bones_applied`）** —— 两者**必须相等**，
> `derive.py` 每次对账，不一致直接报错退出。它就是 `axis_profile.rule` 说的实摆三轴，可直接摆骨。
> `tiers[].bones_canonical_girth` 只是不含 `along` 的参照形，**别拿来摆骨**。
> （v2.0 时 `tiers[].bones` 存的正是这个参照形 —— 照 spec 读会**静默丢掉肩宽/臂展项**，已修。）

**只认 `bodyshape_manifest.json` 的这四行**：`spec_version` / `coefficients` /
`delta_response_values` + `along_axis_response_values` / **`coefficients_fingerprint`**。
指纹是系数的**语义指纹**，系数一变必变 —— 比 mtime 稳（重跑一次几何逐位相同却被 mtime 误伤），
比整文件 sha 准。**读前记指纹、写前再校验**（`garment` 已加这道守卫）。