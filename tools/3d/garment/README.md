# tools/3d/garment —— 服装变形链（3D 角色管线 v2 / T2）

> 契约：[`assets/3d/rig/SPEC.md`](../../../assets/3d/rig/SPEC.md) v1.0（§3.3 morph 通道、**§4.0 B2 主路线**、§5 验收指标）
> 交付：`assets/3d/rig/garments/*.blend`、`assets/3d/rig/manifests/garment_manifest.json`、`assets/3d/rig/previews/garment_*`
> 实测过程与教训：[`task/007-morph-pipeline/lead/FINDINGS.md`](../../../task/007-morph-pipeline/lead/FINDINGS.md)（§9 已被 §11 撤回）

---

## 0. 一句话

**体形 morph 派生在「角色自己的网格」上（B2）**：用角色自己的 rig 摆 14 根体形骨 → depsgraph 取形 →
**逐件**烘 `BS_Thin`/`BS_Heavy`。**不需要**外部标准体，也不需要任何"贴合/传递"。

```bash
python3 tools/3d/garment/build_all.py            # B2 主链路一条命令重跑
python3 tools/3d/garment/build_all.py --b1 --probes   # 连 B1 路线与探针一起跑
```

---

## 1. 三条路线的定位（**B2 是主路线**）

| 路线 | 做法 | 状态 | 实测结论 |
|---|---|---|---|
| **B2** ✅ **主路线** | 对 `assets/3d/blend/tryon/TryOn_*.blend`（**就是最终角色**：服装布料 + 服装自带皮肤 + 基础体捐的头，共用角色自己的 rig），用**角色自己的 rig** 摆体形骨、**逐件**烘 morph | **已交付，4/4 全项 PASS** | 布料/皮肤/头共用同一副 rig、同一组骨变换 → 体形一变三者**同构地一起变** → **结构性不存在穿模** |
| **B1** 🟡 参考 | 剥离皮肤面 → 骨空间 refit → 从**外部标准体**传递 morph | 工具保留、**已被否决** | 服装按「Regular」剪裁、标准体是「Superhero」，**厘米级外推救不了**：像素法裸露 女 63.3%→43.9%、男 74.2%→43.8%（Lead FINDINGS §11.2）→ 产出一并挪到 `garments/B1_superhero_standard/` 备查 |
| **A** ❌ 已撤回 | 保留 Superhero 标准体 + 自动去穿模外推当主方案 | **降级为可选实验**（SPEC F11 撤回） | 判据地基有裂缝（标准体不是闭合曲面）+ 按顶点密度加权 → 假的 0.14%/0.35% |

**B2 成立的根本原因**：最终角色里**没有独立的 Superhero 身体**（它只捐一个头），
所以"标准体与服装体形基准不一致"这个矛盾**本来就不该存在**。

> 为什么保留 B1 工具：**对接 Tripo 阶段仍有用**。将来若真要用"外部标准体 + 服装"的方案（B1），
> `strip_skin` / `refit` / `transfer_morph` / `autofit` 就是那条链路的现成实现。

---

## 2. B2 主路线：用法与命令

### 2.1 一条命令

```bash
python3 tools/3d/garment/build_all.py [--only Female_Ranger]
```
依次跑：`derive_on_character.py` → `verify_fit.py` → `preview.py`（每步一个干净的 Blender 进程）。

### 2.2 分步

```bash
# ① 派生（主实现）
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
  --python tools/3d/garment/derive_on_character.py -- \
  [--tryon assets/3d/blend/tryon] \
  [--out assets/3d/rig/garments] \
  [--report tmp/garment/work/b2_report.json] \
  [--only Female_Ranger]

# ② 验收 + 出交付清单
... --python tools/3d/garment/verify_fit.py -- \
  [--garments assets/3d/rig/garments] [--body-dir assets/3d/rig/bodies] \
  [--manifest assets/3d/rig/manifests/garment_manifest.json] \
  [--previews assets/3d/rig/previews] [--res 440] [--no-pixel] [--only ...]

# ③ 视觉证据
... --python tools/3d/garment/preview.py -- \
  [--garments assets/3d/rig/garments] [--previews assets/3d/rig/previews] \
  [--width 1500] [--height 760] [--spacing 1.15] [--only ...]
```

### 2.3 B2 的口径（关键）

* **体形骨**：`pelvis, spine_01..03, thigh_{l,r}, calf_{l,r}, upperarm_{l,r}, lowerarm_{l,r}, clavicle_{l,r}`（14 根，SPEC §3.2）
* **girth 口径**：`pose_bone.scale = (s, 1.0, s)` —— **只缩垂直于骨轴的两轴，骨长不变** → 体形与身高**正交**
* `s = 1 + (目标系数 − 1) × delta_response[骨]`；档位系数与响应**从 T1 产物读**
  （`assets/3d/rig/manifests/bodyshape_manifest.json` + `bodyshape_spec.json`），读不到才退回内置默认
* 通道（**索引即契约**）：`Basis` / `BS_Thin`(0) / `BS_Heavy`(1)，**每一件网格都要有**，值为 0
* 身高**不做 morph**，用骨架 `root` 等比缩放（h ∈ [0.92, 1.08]）

### 2.4 B2 的边界（**必须知道**）

> **B2 不能做"裸露躯干"的服装**（泳装 / 裸甲）：那时体形变化没有载体
> （布料太少、又没有独立身体可参照）。要这类资产得回到 B1（同源标准体 + 传递）。

---

## 3. 文件清单

| 文件 | 路线 | 作用 |
|---|---|---|
| `common.py` | 共用 | 路径、depsgraph 求值、BVH/穿模、重心坐标+标架、骨空间映射、mesh 编辑 |
| `derive_on_character.py` | **B2 主** | 角色自身 rig 摆体形骨 → 逐件烘 `BS_Thin`/`BS_Heavy` |
| `verify_fit.py` | **B2 主** | SPEC §5 六项 + B2 专属断言 + 写 `garment_manifest.json` |
| `preview.py` | **B2 主** | 三态并排渲染 + 穿模可视化 |
| `pixel_metric.py` | 共用 | **权威判据**：像素法裸露率（无网格拓扑假设） |
| `render_util.py` | 共用 | EEVEE 离屏渲染 / 读像素 / 纯自发光材质 |
| `build_all.py` | — | 一条命令重跑（`python3`，非 Blender 脚本） |
| `strip_skin.py` | B1 | 按材质剥离 `MI_Regular_*` 皮肤面 |
| `refit.py` | B1 | 骨空间重绑 / 几何贴合 / **Shrinkwrap 语义实测** |
| `autofit.py` | B1（可选实验） | 自动去穿模外推 + 失真修复（SPEC F11 已撤回） |
| `transfer_morph.py` | B1 | 重心坐标 + 三角面标架把身体 morph 传到布料 |
| `assemble.py` | B1 | 换挂标准体骨架 / 命名 / 内嵌说明 |
| `verify_fit_b1.py` | B1 | B1 口径验收（"服装 vs 标准体"） |
| `probe_metric.py` | 探针 | 闭合性 / 噪声底 / 判据独立性 / Arms 薄壳 |
| `probe_independent.py` | 探针 | 像素法 + 骨轴径向（B1 对照） |
| `make_fixture_body.py` | 探针 | 开发用 fixture 标准体（T1 就绪前跑通 B1 链路） |

---

## 4. 验收结果（B2，4/4 全项 PASS）

`garment_manifest.json` 是权威清单（verifier 据此对账）。

> 系数源：`bodyshape_manifest.json` **spec_version 2.0**（台账 `version 2.1`、`bones_field_revision 2.1`），
> `coefficients_fingerprint` **`ca93ef919b15340df2123bd397fd4b43c8658d4ef539e4a678319c2f69821ba2`**（冻结、未变），
> thin **0.84** / heavy **1.21**，manifest sha256[:16] **`981c1e8762cb3909`**，spec sha256[:16] `938071768e221299`。
> （台账 sha 会随文档修订变动；**只有 `coefficients_fingerprint` 变化才意味着语义变了**。
>  本轮拆 `spec.tiers[].bones` 那颗雷时台账 sha 从 `17b9db51…` → `981c1e87…`，
>  但我**8 个 morph digest 与 4 套最大位移逐位未变** ⇒ 独立证实「数值一字未动」。）
> 产物与标准体**由同一版 manifest 派生** → 同名 morph 语义一致。
>
> **口令：改台账 = 不用动；改系数 = 必须重跑**（`coefficients_fingerprint` 是语义键，
> 台账修订号/mtime/文件 sha 都不含语义）。我用**逐档 morph digest** 证明了台账那次变更确实惰性：
> 4 套的最大位移与台账变更前**逐位相同**（女 Ranger `BS_Thin 3.2075 / BS_Heavy 4.2098 cm`）。
> 交付清单每套每档都记了 `morph_digest_16`，供跨成员对账。

**`morph_digest_16` 建议升格为正式验收项**（verifier 提议，我赞同）：它把"对账"从**比统计量**升级成**比字节** ——
统计量可能因口径不同而"看着差不多"，digest 只有逐位相同或不同两种结果。现已进 `summary.morph_digest_16` 与 `summary.basis_digest_16`（后者是负对照：morph 必须与之不同）。

**`morph_digest_16` 的约定（必须钉死，否则两边都算得出数字却对不上）**：
① 作用域 = 该角色**全部件网格**，按 `object.name` **排序**；② 取值 = `key_blocks[tier].data[i].co`
**绝对（物体空间）坐标**，**不是**相对 `Basis` 的偏移；③ 打包 = 逐顶点 `struct.pack("<3f", x,y,z)`，按 vertex 顺序；
④ 取 `sha256` 前 16 位。
实测反例（Female_Ranger BS_Thin）：**abs `e5346f1cf12a6dbe` ✅ / delta `4176e0edb5713f1f` ❌**。
（`bodyshape` 的 `check_digest_convention.py` 用同一口径独立复算 **8/8 逐位相同**，并补上了②这一条。）

| 套 | 网格 | 顶点 | 骨架 | morph(2 档) | 身高比 Thin/Heavy | 臂展变化 Thin/Heavy | 像素法 P_full rest/Thin/Heavy |
|---|---|---|---|---|---|---|---|
| Female_Ranger | 12 | 27,920 | 1 副 | 654 KB | 0.99891 / 1.00143 | −1.74% / +2.28% | 0.72% / 0.81% / 0.64% |
| Female_Peasant | 8 | 16,376 | 1 副 | 384 KB | 1.00019 / 0.99975 | −1.74% / +2.28% | 无皮肤面 → N/A |
| Male_Ranger | 12 | 27,637 | 1 副 | 648 KB | 0.99997 / 1.00020 | −1.96% / +2.57% | 0.78% / 0.89% / 0.68% |
| Male_Peasant | 8 | 12,376 | 1 副 | 290 KB | 0.99999 / 1.00002 | −1.96% / +2.57% | 5.34% / 5.59% / 5.16% |

**臂展变化是交叉校验项**（bodyshape 基准：瘦 −1.85% / 壮 +2.08%(女)、+2.78%(男)）——
**若算出≈0 就说明漏了 `along_axis_response`**（见 §5.1-6）。差异来自口径（我用几何 AABB 跨度、
bodyshape 用渲染剪影行宽），量级一致即通过。

**判据全部 PASS**：M1 拓扑 100% · M2 morph 同名同序 100% · M3 像素法各档 ≤ rest+2% ·
M4 morph 字节 ≤ 顶点×12 · M5 身高缩放离散度 ≤0.01 · M6 无 skip 件 ·
B2-a 身高比 ±0.002 · B2-b 每件都有 morph · B2-c 运行时身高缩放达标 ·
**B2-d 同一根骨驱动的布料/皮肤位移一致** · 恰好一副骨架。

### 两个**标定过**的判据（本轮新增，都验过"能变红"）

验收项从 11 项增到 **13 项**，新增的两项专门堵"数字全绿但 morph 其实没用"的假 PASS：

**M4b `morph_non_trivial_and_consistent`** —— 判据是「**体形骨权重 vs 实测位移必须同向**」：
逐件算 `w_shape`（顶点对 14 根体形骨的权重占比）与实测最大位移；
`w_shape > 0` 却零位移 = 真 BUG；`w_shape ≈ 0` 且零位移 = **设计如此**（头/眼/眉不受体形骨支配，
显式标 `static_by_design`，免得读的人把设计当缺陷）；另核 digest ≠ Basis digest（常量 key 会让 digest 失去判别力）。

**M4c `arm_span_calibrated`** —— 臂展（`max x − min x`）的**双信号**，独立测量（不看 derive 的报告）：

| 烘焙规则 | 瘦（BS_Thin） | 壮（BS_Heavy） | 判据 |
|---|---|---|---|
| **正确**（NONE 隔离 + manifest 的 `along` 项） | **−1.73%** | **+2.28%** | 落带内 → PASS |
| **漏 `along` 项**（写死 `(s,1,s)`） | **−0.55%** | **+0.72%** | `\|变化\| < 1.0%` → **FAIL「疑似漏 along 项」** |
| **漏 NONE 隔离**（全 `FULL` 摆骨） | **−54.53%** | **+138.86%** | `\|变化\| > 20%` → **FAIL「疑似漏 NONE 隔离」** |

标定脚本 `tmp/garment/calib_armspan.py`（本工具独立标定，与 verifier 独立测量**逐位相同**）。
**判别力已实证**（造对照件端到端跑）：
* `ctrlB`（漏 NONE）→ M4c + B2-a + B2-d **三个判据同时变红**
* `ctrlC`（漏 along）→ **只有 M4c 变红**，其余 12 项全绿 —— **这正是那个静默 2% 错误**，
  说明该项有**不可替代**的判别力（没它就会漏放行）
* 另造零 morph 对照件 → `B2-a 身高比 {1.0, 1.0} → PASS`（旧的洞），而 **M4b 抓出 10 个 BUG 件**
* 对照件生成脚本：`tmp/garment/make_armspan_controls.py`

> ✅ **那颗雷已拆**（verifier 发现 → 我确认 → bodyshape 修）：`spec.tiers[].bones` 现在**恒等于**
> `manifest.tiers[].bones_applied`（clavicle thin `[0.872, **0.92**, 0.872]` / heavy `[1.168, **1.105**, 1.168]`），
> 规范形改名存 `bones_canonical_girth`（**参考用、别拿来摆骨**）。
> 我独立复核：**28 项逐骨逐档比对，0 项不符**；bodyshape 还给该对账加了**会变红的门禁**
> （把旧口径塞回去 → `derive.py` 直接拒绝运行并指名到骨）。
> 本目录的做法不变：**只读 `manifest.tiers[].bones_applied`**。

> **M3 的阈值是带基线的，不是绝对值**：`summary.pixel_P_full_criterion` = 「各档 ≤ rest 基线 + 2 pp」（SPEC §5 原文）；
> 逐套还会给出 `M3_penetration_pixel.threshold_concrete`（例：男 Peasant 基线 5.34% → 阈值 7.34%）。
> 只写「≤2%」会让无袖的男 Peasant 被判错 —— **两处都读，别只看一处**。

### B2-d：比"像素法"更硬的结构性断言（本工具新增）

B2 下布料与皮肤由**同一条骨变换链**驱动，这一点可以直接量：取布料顶点与它最近的皮肤顶点，比 morph 位移向量。
但**判据必须是尺度无关的** —— 线性混合蒙皮是**仿射**的，位移差 `Δp − Δp′ = A·(p−p′)`，
所以两点相距 `d` 时位移差天然 ≈ `|A|·d`（BS_Heavy 的 girth 系数最大 1.16 → `|A|≈0.16`）。
**第一版我直接用绝对阈值 <1 µm 判，男 Peasant 就"失败"在 2.78 mm —— 而那其实是 `0.16 × 17 mm` 的必然结果，不是缺陷。**

修正后的两条判据：

| 判据 | 结果 |
|---|---|
| 非退化对 `max(diff/d)` ≤ 0.30 | 女 R / 男 R **非退化对 = 0 → 不适用**；男 P **0.2129** |
| 非退化对 `max(diff/(\|A\|·d))` ≤ 1.5（仿射符合度） | 男 P **0.8036** |

⚠ **非退化前置条件**（verifier 指出并已采纳，是本项的关键）：
腕/手/指骨的权重全在 `hand_*` 与指骨上，这些骨**不在 14 根体形骨名单里**、又因 F6 规则被设 `NONE`
→ **整只手作为刚体被搬走**，**刚体上任意两点位移差恒为 0**。
所以配对若整片落在手上，那个 PASS 是**空洞的** —— 我第一版正是如此（女/男 Ranger 报 0.0000 就说"一致性完美"）。
现改为用**逐顶点局部 Jacobian `|A|`** 把对分成"非退化（`|A|>0.01`）"与"退化(刚体)"，
只在前者上断言；**一对非退化都没有时标 `applicable=False`，不假装 PASS**。
真正有信息量的只有 **男 Peasant 的 0.2129 / 0.8036**（那里布料与皮肤交界处 `|A|≠0`）。

> **方法学**（verifier 的"判据退化"坑，值得写进 SPEC）：测量前先问一句
> **"在我选的这个点集上，这个量『可能不为零』吗？"** 若不可能为零，测出来的零没有信息 ——
> 这比"数值大小"更容易骗过验收方。

**Male_Peasant 的 5.3% 是美术设计不是缺陷**：那套是**无袖**装，大臂与手本来就裸露。
渲染图 `previews/garment_Male_Peasant_skin_vs_cloth_rest_front.png`（绿=布料、红=裸露皮肤）
里红色**只出现在前臂与手**。所以口径按 SPEC §5 原文：**各档 ≤ rest 基线 + 2%**。

---

## 5. 口径与坑（都是实测踩到的）

### 5.1 B2 专属

1. **`inherit_scale` 在 `arm.data.bones` 上设，不是 `PoseBone`**（写在 PoseBone 上不报错、但无效）。
2. **烘 shape key 前必须先给每件建好 `Basis` + 两档通道，且顺序必须是 `Basis/BS_Thin/BS_Heavy`** ——
   顺序就是契约，脚本内 `assert`。
3. ⚠ **`inherit_scale='NONE'` 与「身高用 root 等比缩放」不相容**（本工具实测发现）：
   `NONE` 让子骨不继承父骨 scale → root 放大时只有部分骨段跟着长。实测 root×1.08 的
   边长拉伸离散度：**NONE 0.0257–0.0760 → 还原 FULL 0.0000–0.0001**（阈值 0.01）。
   **所以：烘焙期间用 `NONE`（防体形骨缩放沿链外传），烘完、清 pose 之后必须还原 `FULL`。**
   交付资产里 `inherit_scale` 是 `FULL`，不是 `NONE` —— 别按 SPEC §3.2 字面去查资产。
4. **`girth` 口径**（(s,1,s)）与 `length` 口径（(s,s,1)）差别巨大：后者本质是改腿长、
   会连带身高 ±11%，与 §3.4 正交设计冲突。**morph 变形量是厘米级（2.5–3.2 cm），不是分米级。**
5. 源包里每份 `TryOn_*` 都带 `Icosphere`/`Camera`/`Light` 等辅助对象，交付前要清掉。
6. ⭐ **尺度一律取 `bodyshape_manifest.json` 的 `tiers[].bones_applied`，不要自己推 `(s,1,s)`。**
   v2 新增 **`along_axis_response`**（**只有 `clavicle = 0.5`**），锁骨骨的 scale 是
   `(s, 1+(coef−1)·0.5, s)` 而**不是** `(s,1,s)` —— 实测 BS_Heavy `clavicle_l = [1.168, 1.105, 1.168]`。
   写死 `(s,1,s)` 会**静默**丢掉肩宽/臂展那一项（约 2%），而且**不报错、数字看着都正常**。
   ⚠ 同时注意 manifest 里两个字段的区别：**`bones_applied` = 实摆三轴（要用这个）**，
   `bones_canonical_girth` = spec 里存的规范形 `(s,1,s)`（**不能拿来摆骨**，会丢沿骨轴项）。
   `tools/3d/bodyshape/bodyshape_core.bone_scales_for()` 是系数展开的唯一实现，也可直接用。
7. ⭐ **`inherit_scale` 是"烘焙期契约"，不是"交付资产形状"**：`tryon/` 的角色**没有**把它烘进文件，
   `derive_on_character.py` 每次**显式设这 18 根子骨**再摆骨（不设会沿链外传，瘦档宽度可差 −44%，
   且**不报错**）。烘完再还原 `FULL`（见坑 3）。所以**别拿"文件里是不是 NONE"当判据**。

### 5.1b ⭐ 系数源偏斜：一次真实事故 + 根治

**2026-10-13 实际发生**：我在 18:20:20 读到 `bodyshape_manifest.json` 的 **v1**（thin 0.86 / heavy 1.16、
`spine_02=0.92`），而 bodyshape 在 **18:20:43** 才落盘 **v2**（0.84 / 1.21、`spine_02=1.0`、`clavicle=0.8`）。
→ `BS_Heavy=1` 在标准体上代表"v2 壮"、在我的角色上代表"v1 壮" → **同名 morph 语义不一致**（Lead 抓出）。
静默用旧值是这类事故最坏的形态。

**根治 = `derive_on_character.py` 的 `assert_source_unchanged()` 偏斜守卫**：
* 读取时记下系数源的 **内容 sha256 + mtime + size**；
* **每次写产物之前再读一次**，变了就 **`SystemExit` 拒绝写出**（"系数源在我读取后被改动，请重跑"）；
* 把指纹写进 b2 报告与交付清单，任何人一眼能看出产物对应哪版 spec。
* **报错要可操作**：守卫会读新文件的 `coefficients_fingerprint` 并自动判定 ——
  * 语义键**未变** → 「仅台账/格式变化（数值应逐位相同）→ 重跑刷新溯源即可」；
  * 语义键**也变了** → 「语义变化 → 必须重跑」。
* 守卫有单元测试：`tmp/garment/test_drift_guard.py`（用 Blender 跑；验证 **6 种情形**：
  未改动通过 / 改动拦下 / 文件消失拦下 / 仅台账变化诊断 / 语义变化诊断 / 无系数源跳过）。
  **测的是真代码**（exec 去掉 `main()` 调用的源码），不是副本。

**三重指纹，各管一段**（bodyshape 的建议已采纳）：
| 指纹 | 用途 |
|---|---|
| `coefficients_fingerprint`（`ca93ef91…`） | **语义指纹**：系数一变它必变 → 守卫的**首选键**；不受"重跑一次几何逐位相同但 mtime 变了"误伤 |
| `spec_sha256`（`17448b49…`） | 关联到 `bodyshape_spec.json`，用于跨成员对账 |
| manifest 文件 sha256 + mtime | 兜底：捕获"系数没变但 manifest 被重写"（我这次就是这种） |

### 5.1b-2 ⭐ 身高缩放的口径（F12）：**对象级**，不是 `root` 骨

`SPEC §3.4` 现行写法是**骨架「对象」等比缩放**，而 `root` **骨**缩放已被 F12 废弃。实测（本工具与 bodyshape 独立复现）：

| 资产 | `inherit_scale` | `root` **骨** ×1.08 | **对象**等比 ×1.08 |
|---|---|---|---|
| `Body_*_Standard`（bodies/） | NONE × 18 | **离散度 0.079 ❌** | **+8.000%，离散度 0.0000385 ✅** |
| `TryOn_*`（未规范化） | FULL × 65 | 0.00003 ✅ | 0.00003 ✅ |
| 本工具交付的 `garments/` | **FULL × 65**（烘完还原） | 0.00003–0.00007 | **1.5e-05–7.1e-05 ✅，身高 +8.000%** |

→ 两条推论：
1. **F6（`NONE`）是「烘焙期」契约，§3.4 是「运行时」契约，两者正交** —— 前提是运行时用**对象级**。
   `bodies/` 保留 `NONE` 与本工具交付 `FULL` **各自都满足契约、互不冲突**（bodyshape 已确认）。
2. **别再拿"资产里是不是 `NONE`"当判据** —— 那只对 `bodies/` 成立，用在 `garments/` 上会误报。

### 5.1c ⭐ 门禁本身也会骗人（`build_all.py` 的教训）

`blender -b --python X.py` **在脚本抛异常时仍然返回 0**。我这次的一个 summary 键名笔误让
`verify_fit.py` 在**写清单之前**崩掉，而 `build_all.py` 报了 ✅ —— **门禁绿灯、产物却是上一版**，
正是本次偏斜事故的同类形态。已修两处：
```python
cmd = [BLENDER, "-b", "--factory-startup", "--python-exit-code", "1", "--python", path]
...
ok = (r.returncode == 0) and ("Traceback (most recent call last)" not in blob)   # 双保险
```
→ **教训：门禁的"绿"必须验证过它真的会变红**（我故意让它失败一次确认过）。

### 5.1c-2 ⭐ 指纹的输入里不能混进"纯给人看的版本号"（bodyshape 自曝、原则通用）

bodyshape 修那颗雷时**顺手把 `spec.version` 2.0 → 2.1**，而 `spec_version` 正是他们
`coefficients_fingerprint` 的输入之一 → 指纹变成 `0ddb9140…`，**会让下游的语义守卫误报"语义变化"**。
正确做法：`spec.version` 回 `2.0`（系数确实没动），字段语义修订另立 `bones_field_revision: "2.1"`；指纹随即逐位回到 `ca93ef91…`。
> **原则：语义指纹只能由「会影响结果的量」构成**，否则每次改文档都会让下游守卫误报。

**本目录的对照检查**（照这条自查过）：`coefficient_source` 里同时记了**字节级** `manifest_sha256_16` 与
**语义级** `coefficients_fingerprint`，**守卫的硬失败条件是字节级**（任何改动都拦，符合 Lead 的"变了就报错退出"），
**语义键只用于分诊**（告诉你是"仅台账变化 → 重跑刷新即可"还是"语义变化 → 必须重算"）。
所以本目录**不会**因为文档修订而误判语义 —— 但也**不会**放过任何字节变动（这是有意的严格）。

### 5.1d ⭐ "未变更"的判据要能区分「我变了」和「上游变了」

verifier 的做法值得抄进所有产物比对门禁：**对同一脚本连跑两次** ——
两次一致 ⇒ 稳定，观测到的变化来自上游；两次仍不一致 ⇒ 自己的脚本有问题。
本目录的隔离手段是 **`morph_digest_16`**（只看 morph 字节）+ **系数源三重指纹**（只看输入），
两者一叠加就能把"上游漂移"与"我这边回归"分开。我实际用它对过一次：bodyshape 台账修订（sha 变了）
但 8 个 digest 与 4 套最大位移**逐位未变** ⇒ 判定为**惰性变更**，不需要重烘。

### 5.2 度量（**最容易骗自己的地方**）

1. **shape key 不改 `mesh.vertices`** —— 一切测量必须走 depsgraph 求值（`evaluated_get`）。
2. **顶点级"穿模率"不可信**（SPEC F15 / Lead §11.1），两条原因：
   * 标准体**不是闭合曲面**（26 连通域 / 48 边界环；边界边 58% 集中在手腕/足），
     且**相对质心非星形**（仅 67.2% 的面满足「面法线与面心−质心同向」）。
     ⚠ **面绕向其实是一致的**（共享边反向遍历违例 0/18250）—— verifier r1 曾报「绕向不一致」、
     Lead 已订正为 F15b，**不要引用旧措辞**。
     → 射线奇偶在**近表面 1 cm 带**（正是穿模发生处）准确率 99.8%→95.8%；
   * **按顶点密度加权** —— `*_Feet` 一件 10,174 顶点（占 43%）却基本没问题，把总比例拉低。
   → **口径：本项目以像素法为权威，顶点级只作对照。**
3. **像素法的三个坑**（Lead 各错一轮，本仓库已规避）：
   * `view_transform` 必须是 **`Standard`** —— `AgX` 会把纯红压成鲑鱼粉，基于"红占优"的判据全废；
   * 背景**不能用颜色阈值**判 —— 用 `film_transparent=True`，**alpha 通道即剪影**；
   * 红色判据太松会把棕色皮革/皮肤一起收进来 → 本仓库**双方都换纯自发光材质**（红/绿），
     判据收紧到 `r − max(g,b) > 0.5`，从机制上消除该失效模式。
4. ⚠ **本工具自己踩过的两个像素法坑**（已加防护，值得记）：
   * **忘记给测量对象换材质** → 网格在无灯环境渲成**纯黑**、剪影 alpha 正常、红像素恒为 0
     → 量出**假的 `P_full = 0.00%`**。现加 **sanity 断言**：画面纯色占比必须 ≥0.5，否则直接报错。
   * **代理网格不随档变形 + 源网格未隐藏** → 与按档代理**共位重叠**渲染，画面混入黑像素。
     现按档从**求值后的几何**建代理，并 `hide_render` 源网格。
   * **教训（与 Lead §11.6 一致）：当度量与眼睛冲突时，先怀疑度量。** 这两条都是靠**看渲染图**发现的。
5. **"同骨驱动"要用尺度无关判据**（详见 §4 的 B2-d）：仿射变换下位移差正比于两点距离，
   拿绝对阈值卡会把"骨粗了 16% 所以相距 17 mm 的两点位移差 2.8 mm"误判为缺陷。
6. **真·绝对噪声底 = 0.0000%**（把标准体整体平移开、bbox 确认不重叠 → 全部判为体外）。
   **早先引用的 3.62%/4.52% 是合成壳构造伪影**（误判率随外推距离非单调），**已作废、不得用来下修**。
8. **失真度量必须相对"真·原始坐标"**：拿"修改后"的坐标当 rest → 拉伸比恒为 1.000（纯 bug）。

### 5.3 B1 路线专属的坑（留给将来 Tripo 阶段）

1. **Blender `Shrinkwrap` 的 `NEAREST_SURFACEPOINT + offset` 是"有符号距离钳制"**，
   不是"沿外法线推出"：原本在体内的顶点被推到「体内 0.4 cm」，**内外关系原样保留 → 穿模一点不降**
   （实测 Body 8.26%→8.26%，Arms 60.32%→63.25%）。
   要真在体外必须 `wrap_mode='OUTSIDE_SURFACE'`，但它会把**所有**顶点（含本来悬空的）压到体表
   → 保罗护肩间隙 3.67 cm→0.40 cm、面积比 0.58（垂坠件全废）。
   → 正确做法是**外科式外推**（只动真正穿模的顶点），见 `refit.py:push_out_points` 与 `autofit.py`。
2. **纯 Laplacian 平滑会把顶点区域整体收缩**（实测边长拉伸 p50 1.000→0.821，并制造 465× 的塌缩边）；
   改 Taubin（λ|μ）+ 边长护栏好一些，但**仍不能把 p99/max 压下来** ——
   B1 的失真修复是**没有干净解**的，这也是 B1 被判死的理由之一。
3. ⚠ **SPEC §4.2 的传递口径是欠定义的**：`transfer_morph.py`（本仓库）与 verifier 的独立实现在
   **自由垂坠件（远绑定顶点）** 上可差 **1.11 cm** —— 两者都符合 §4.2 的字面描述。
   → 将来若走 B1/Tripo，**必须先把绑定口径（近邻命中点、标架定义、是否夹紧重心坐标）写死**，
   否则"同名同序 morph"看着对齐、数值却对不上。
4. `bpy.data.libraries.load` 追加标准体骨架时**会连带把标准体文件里的 `Icosphere` 拉进来**
   → 清理必须放在加载**之后**（`assemble.py` 里已处理并 `assert`）。
5. 骨轴径向要用**骨链 + 按权重归骨**参数化：单骨 slab 会把躯干/另一条手臂投影进来
   （第一版把身体 r(t=0) 报成 90.8 cm 这种荒谬值）；而皮肤面全在前臂/手上，单根上臂骨又会把它们整体滤掉。

---

## 6. 复现

```bash
python3 tools/3d/garment/build_all.py          # B2：~3 分钟
python3 tools/3d/garment/build_all.py --b1 --probes   # 连 B1 与探针：~20 分钟
python3 -c "import json;d=json.load(open('assets/3d/rig/manifests/garment_manifest.json'));print(d['summary']['all_pass'])"
```

产物：
* `assets/3d/rig/garments/{Female,Male}_{Ranger,Peasant}.blend` —— B2 自包含角色（**主交付**）
* `assets/3d/rig/garments/B1_superhero_standard/*.blend` —— B1 参考（保留不删）
* `assets/3d/rig/manifests/garment_manifest.json` —— 权威清单
* `assets/3d/rig/previews/garment_*` —— 三态并排 / 穿模可视化 / 像素法对照
* 中间件与报告在 `tmp/garment/work/`（可随时清，重跑即再生）