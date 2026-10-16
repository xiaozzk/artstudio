# 渲染 / UV / 贴图契约（NPR 二次元）

> **风格档位**：**① 写实二次元**（与既有库同档：8 头身）。
> **决定**：上「**卡渲 + 描边**」两件；**不做面部 SDF**、**不做飘眉**。**总共只新增 2 条契约。**
> **面向**：Godot 4.6 **前向**渲染（不用延迟、不注册自定义 shading model —— 那是 UE 的能力，Godot 没有）。
> **依据**：SPEC **F33**（IK/约束/导出实测）、[`SKELETON.md`](SKELETON.md) §7；业界参考见 [`reference/BODIEZ-ANALYSIS.md`](reference/BODIEZ-ANALYSIS.md)。

---

## 1. 简化阶梯（每一档可独立选，且能后续升级）

| 档 | 面部方案 | 新增契约 | 效果 | 成本 |
|---|---|---|---|---|
| **L0** | 用 PBR | 0 | 不是二次元（软过渡/无描边/灰阴影/连续高光） | 0 |
| **L1** ⭐ | **半兰伯特 + ramp**，面部一视同仁 | **1**（ramp 图） | 转脸时脸上明暗会"爬" | 低 |
| **L2** ⭐⭐ | **面部明暗画进贴图**（不随光变） | **0** | 脸在暗处偏亮（**二游里被广泛接受**） | 极低 |
| L3 | 面部 **SDF + 专用 UV** | 3 | 稳定、可控、最像 | 中（**每个头型一份**美术活） |
| L4 | 鸣潮档：延迟 + 自定义 shading model + stencil 飘眉 + 逐件描边 | 4+ | 顶配 | 高，**且 Godot 做不了** |

**升级路径**：先做 **L1 + L2**；将来觉得不够，**补 L3 的 SDF 与飘眉即可** —— 它们都在**渲染层**，**不碰几何契约**。

---

## 2. 推荐组合（7 行，新增契约只有 2 条）

| 件 | 做法 | 新契约 |
|---|---|---|
| **卡渲** | `DIFFUSE_TOON` + `SPECULAR_TOON` + `rim`；要自定义 ramp 色再加一个 3 行 shader | **1**（ramp 图，**全角色共用一张**） |
| **描边** | `next_pass` + `grow` + `cull_front` + `unshaded` | **1**（**平滑法线**，Blender 自动烘） |
| **面部** | **单独一片「脸皮」网格** + `shading_mode = UNSHADED` | **0** |
| **眉毛** | **画进脸皮贴图** | **0** |
| **表情** | **贴图图集 + UV 偏移**（+ 脸红叠加 + 眼睛单独一层） | **0**（复用同一材质机制） |
| **层** | **P1 只做 3 层**（身体/内层/配件），**不做叠穿** | **0**（且避开描边冲突） |
| **头** | 中低模 + **普通展开 UV**（不需要面部专用 UV，因为不做 SDF） | **0** |

---

## 3. Godot 侧具体设置（**枚举值全部实测于 4.6.2**，别去猜）

### 3.1 卡渲（零 shader）

```gdscript
# ⚠ BaseMaterial3D 不可实例化（ClassDB.can_instantiate == false）→ 用 StandardMaterial3D
var m := StandardMaterial3D.new()
m.albedo_texture = preload("平色贴图.png")
m.diffuse_mode   = BaseMaterial3D.DIFFUSE_TOON     # 实测 = 3（hint: Burley, Lambert, Lambert Wrap, Toon）
m.specular_mode  = BaseMaterial3D.SPECULAR_TOON    # 实测 = 1（hint: SchlickGGX, Toon, Disabled）
m.rim            = 0.5                             # hint: 0,1,0.01
```

⚠ **内置 Toon 不能换 ramp 图**（阶梯形状写死）。要**自定义 ramp / 阴影可染色**（二次元的灵魂）就得写 shader，核心三行：

```glsl
// spatial shader 的 light() 里
float nl = dot(NORMAL, LIGHT);
float half_lam = nl * 0.5 + 0.5;                              // 半兰伯特
float band = texture(ramp_tex, vec2(half_lam, 0.5)).r;        // 查 ramp（1D）
DIFFUSE_LIGHT += mix(shadow_color, base_color, band) * ATTENUATION * LIGHT_COLOR;
```

### 3.2 描边（零 shader）

```
主材质：  cull_mode = Back
next_pass（Material 上有 next_pass ✅）：
    grow         = true
    grow_amount  = 0.004                  # ⚠ 单位是【米】（hint 带 suffix:m，范围 −16..16）
    cull_mode    = BaseMaterial3D.CULL_FRONT    # 实测 = 1（hint: Back, Front, Disabled）
    shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED   # 实测 = 0（hint: Unshaded, Per-Pixel, Per-Vertex）
    albedo_color = 黑（或阴影色）
```

⚠ **`grow_amount` 是世界空间**，三个后果：
1. 拖身高滑块（±8%）→ **描边粗细也跟着变 8%**
2. 远看时描边**按透视变细**（屏幕空间不稳定）
3. → **要么接受，要么改用屏幕空间描边（写 shader）**。**P1 建议接受。**

⚠ **`grow` 沿网格自带法线外扩** → 硬边处会**撕裂** → 需要**平滑法线**（见 §4.2）。

### 3.3 面部（L2，零 shader）

```
头壳（颅骨 / 耳 / 被头发盖住的区域） → 普通卡渲材质
脸皮（面部一块略前凸的薄面片）      → shading_mode = UNSHADED
                                      albedo_texture = 已画好明暗的脸贴图
```

- ✅ **副产品极大**：**眉毛直接画在脸皮上** → 不需要独立眉毛网格、不需要"飘眉"那套 stencil
- ⚠ 脸皮与头壳的**剪影要对齐**否则露缝 → **靠头发盖住边界**（二次元标配做法）

### 3.4 表情（blendshape 接口已实测齐全）

```
MeshInstance3D.find_blend_shape_by_name() / set_blend_shape_value()
                / get_blend_shape_count() / bake_mesh_from_current_blend_shape_mix()
```
★ **首选"贴图图集 + UV 偏移"**（与 L2 天然一致：脸本来就是"画死的贴图"）：
- 表情格：普通 / 笑 / 怒 / 哀 / 惊 / 羞 / 闭眼 / 半闭
- 平滑：**lerp 两格**（改 UV 偏移 → **一次 draw call**，不换材质、不断批）
- **零几何成本** → **完美契合"头不用精细"**（不需要为表情留环线）
- ⚠ 代价：没有真正的形变（脸型不变）；表情数受图集大小限制（2048² 放 16 格 512² 够用）

**口型同步**（以后做对话时）：同一套图集画 **5 个口型**（a/i/u/e/o），按音频驱动 UV → **与表情同一机制，几乎零额外成本**。

---

## 4. 两条新契约的规格

### 4.1 `ramp` 图（全项目共用一张）

| 项 | 规格 |
|---|---|
| 尺寸 | **256 × 16**（够；1D 查表） |
| 格式 | PNG，灰度（R 通道用） |
| 内容 | 横轴 = `half_lambert ∈ [0,1]`，纵轴留白/分层给不同材质组 |
| 归属 | **不是资产**，是**全项目共享资源**（放在 `assets/3d/rig/` 或引擎侧的共享资源目录） |
| 变体 | 若要材质分层（皮肤/布/金属各一套阶梯），**在同一张图的纵轴上分行** → 仍是一张图 |

### 4.2 描边平滑法线

| 项 | 规格 |
|---|---|
| 为什么 | `grow` 沿**网格自带法线**外扩；硬边/UV 缝处法线分裂 → **描边断线** |
| 怎么做 | **在 Blender 里自动生成**：把网格"平滑化"后的**平均法线**烘到**顶点色**（或 UV2/自定义属性），描边 pass 用它代替几何法线 |
| 工具 | `bpy.ops.object.bake(type='NORMAL')` 或直接按"顶点邻域平均法线"算 —— **不手画** |
| 存放 | 顶点色（最省，Godot 可直接读 `COLOR`）|
| 验证 | 断言：描边在**所有硬边处不断线**（渲染一张极端硬边件 → 目视 + 像素连续性判据） |

---

## 5. UV 契约

| 资产 | UV 要求 |
|---|---|
| **头** | ⭐ **必须带"面部平面投影 UV"**（正对脸的平面投影块）← **唯一新增的 UV 约束** |
| **身体 / 衣服** | 只要求**有主 UV**，**不约束布局** |
| ramp 图 | 不属资产（全项目共用） |

**为什么头必须平面投影**：脸贴图（五官 + 表情图集）要在**正对脸的平面**上对齐；普通球面/柱面展开会让五官扭曲、表情格对不上。

**已验证可用的 Blender 算子**（5.2.2，headless 都能跑）：
```
uv.smart_project ✅   uv.unwrap ✅        uv.mark_seam ✅
uv.pack_islands ✅    uv.project_from_view ✅
uv.cube/cylinder/sphere_project ✅          uv.average_islands_scale ✅
```

### ⭐ NPR 让 UV 展开容易得多
明暗是 **ramp 算的**、颜色是**平铺的** → **纯色区域上的接缝根本看不见**。PBR 才怕接缝（法线/粗糙度不连续会露出来）。

### 自动化到什么程度
- **全自动**：`smart_project` → `pack_islands`。但接缝位置不可控（会丢在脸颊、胸口正中）
- **半自动（推荐）**：`mark_seam`（手工标，约 5 分钟）→ `unwrap(method='ANGLE_BASED')` → `pack_islands` → `average_islands_scale`
  - 接缝标在：**腋下 / 内侧手臂 / 背中线 / 胯内侧 / 发际线 / 脸的外轮廓**
- **对称减半**：角色左右近乎对称 → 展一半、镜像

### 两处**必须人工**
1. **面部** —— 必须平面投影（`project_from_view` 在正视图下）
2. **接缝位置** —— 见上

---

## 6. 贴图契约 + 自动配方

### 6.1 ⭐⭐ 硬规则：**身体不画死明暗，只有脸可以**

| | 明暗从哪来 | 为什么 |
|---|---|---|
| **身体 / 衣服** | **ramp shader 实时算**（贴图只放平色 + 花纹） | 身体**要随体型变**（morph 动顶点）→ **画死的明暗会跟着变形而错位** |
| **脸** | ✅ **可以画死在贴图里** | 脸**不随体型变**（头 100% 静态）→ 画死永远对 |

> **这条规则的根据就是 D7**：头是静态资产 ⇒ L2「面部明暗画进贴图」才安全。
> **反过来**：如果哪天头也变得随体型动（例如头身比做成 morph 轴），**这条规则立刻失效**。

### 6.2 贴图清单（NPR vs PBR）

| | PBR | **NPR（L1+L2）** |
|---|---|---|
| BaseColor | ✅ 高分辨率 | ✅ —— **可以是纯色 / 程序化烘出来** |
| Normal | ✅ | ❌ **不需要**（明暗靠 ramp） |
| Roughness | ✅ | ❌ |
| Metallic | ✅ | ❌ |
| AO | ✅ | ❌（要就烘进 base color） |
| **ramp** | — | ✅ 1 张，256×16，**全项目共用** |
| **面部贴图** | — | ✅ 1 张 —— **唯一必须画的** |
| 可选 mask | — | 描边遮罩 / 脸红 / 材质 ID |

**从 5 张高分辨率 → 2 张（其中 1 张极小且共用）。**

### 6.3 可执行配方（全部已验证）

```python
# ① 身体/衣服：标 seams → 展开 → 打包
bpy.ops.mesh.mark_seam(...)                       # 手工标，或跳过走 smart_project
bpy.ops.uv.unwrap(method='ANGLE_BASED')
bpy.ops.uv.pack_islands(margin=0.01)
bpy.ops.uv.average_islands_scale()

# ② 脸：平面投影（在正视图下）
bpy.ops.uv.project_from_view(orthographic=True, ...)

# ③ 贴图：从"材质分区"烘出平色图 → 零手绘
bpy.context.scene.render.bake.use_pass_direct   = False
bpy.context.scene.render.bake.use_pass_indirect = False
bpy.context.scene.render.bake.use_pass_color    = True     # 只要颜色
bpy.ops.object.bake(type='DIFFUSE')                        # ✅ 已验证可用
```

→ **一张"平色贴图"是自动生成的**：区域分好材质、给好颜色、烘一次。**一笔都不用画。**

### 6.4 AI 生图的现实限制
- **AI 不认你的 UV 布局** → 两条路：(a) 生成「**UV 空间**」的图（把 UV 模板当线稿喂进去）；(b) **在图像空间生成脸，再对齐/投影到面部 UV** ← **更实际**
- **平色区域不需要 AI** —— 填几个颜色比调 AI 快
- ⭐ **AI 擅长的恰好是"脸"** —— 正好用在**唯一必须手工的那块**上

---

## 7. 表情契约

| 项 | 规定 |
|---|---|
| **命名空间** | **`EX_*`** —— 与体型 morph（`BS_*`）**不得交叉**（见 [`channels.json`](channels.json)） |
| **同步范围** | 表情**只作用在头/脸网格**，**不跨件同步**；体型 morph **跨件同步** |
| **语义层** | **VRM 表情词表**（与骨架同样做法：**词表做语义层，本地名不改**） |
| **VRM 预置** | `happy` `angry` `sad` `relaxed` `surprised` `neutral`｜`aa` `ih` `ou` `ee` `oh`｜`blink` `blinkLeft` `blinkRight`｜`lookUp` `lookDown` `lookLeft` `lookRight`｜`custom.*` |
| **映射** | 本地图集格名/通道名 → VRM 词表；写在同一份映射表里（待建 `expression_mapping.json`） |

**为什么复用 VRM 词表**：骨架已经采用 VRM 角色词表做语义层（[`SKELETON.md`](SKELETON.md) §6），表情用同一套 → **一份映射，将来导出 VRM 直接可用**，且表情语义有统一命名。

---

## 8. ⚠ 描边 × 分件模块化的冲突（P1 用"不做叠穿"绕开）

反壳描边画的是**整个网格的轮廓**，包括被别的件盖住的部分。在 modular 体系里：

```
袖子根部会画出一条【不该存在的描边线】   ← 那片区域本该被躯干盖住
两层布料叠穿时，【内层的描边会透过外层】露出来
```

**业界（鸣潮）的答案**：**描边逐部件单独一遍** + 用 stencil/mask 控制"哪里画"（一个角色 5 条 outline pass）。

**我们的 P1 做法**：**层压到 3 层、不做叠穿** → 冲突基本消失（只剩"相邻件接缝处可能有细描边"，低模小尺寸下通常能接受）。
**要做叠穿时**再补**第 3 条契约：per-part 描边遮罩**。

---

## 9. 已实测的坑（别重新踩）

| # | 坑 | 出处 |
|---|---|---|
| 1 | **`BaseMaterial3D` 不可实例化** → 必须用 `StandardMaterial3D` | Godot 4.6.2 `ClassDB.can_instantiate("BaseMaterial3D") == false` |
| 2 | **`grow_amount` 单位是米** → 描边粗细随身高滑块变（±8%）、随透视变细 | hint `-16,16,0.001,suffix:m` |
| 3 | **`grow` 依赖网格自带法线** → 硬边撕裂 → 需烘平滑法线 | —— |
| 4 | **内置 Toon 不能换 ramp**，想自定义阶梯/阴影色要写 shader | `diffuse_mode` 只有 4 项 |
| 5 | **Godot 做不了延迟自定义 shading model** → 不能照搬鸣潮那套 | Godot 前向管线 |
| 6 | **Blender 5.x 把 IK 约束类名改成 `KinematicConstraint`**（枚举仍是 `'IK'`），`Armature.ik_solver` 已移除 | SPEC **F33** |
| 7 | **glTF 没有 IK/约束** → 导出两条口径别混（`export_force_sampling` 烘成采样帧 / `export_def_bones` 剥控制骨） | SPEC **F33** |
| 8 | **烘 morph 前必须清掉 IK/全部约束**（pose 与 shape key 会叠加，实测 33 mm 假差） | SPEC **F33** |
| 9 | **UV 层名 ≠ UV 层内容** —— 第三方件有 7 层 UV，其中 `face_main` 等 5 层是**全 0 空壳** | [`reference/BODIEZ-ANALYSIS.md`](reference/BODIEZ-ANALYSIS.md) |
| 10 | **审批输出被截断 ≠ 查询结果为空** —— 曾据此误判"第三方件的比例逻辑在插件里" | SPEC **F35** |

---

## 10. 明确"不做"的决定（免得以后有人以为是漏了）

| 不做 | 代价（已知并接受） | 何时重新考虑 |
|---|---|---|
| **面部 SDF** | 转脸时脸部明暗**不跟随光照**（暗场景脸偏亮） | 觉得"脸在暗处太亮"时 → 补 L3 |
| **飘眉（刘海不遮眉）** | 眉毛**画进脸贴图**，**不能单独动** | 需要"眉毛独立表达"时 → 补 stencil/mask 方案 |
| **per-part 描边遮罩** | 相邻件接缝处**可能有细描边** | 开始做**叠穿**时必补 |
| **屏幕空间描边** | 描边粗细**随身高滑块变 8%**、远处变细 | 觉得描边不稳定时 |
| **延迟渲染 / 自定义 shading model** | 拿不到鸣潮那种 GBuffer 级控制 | **Godot 不支持，长期不做** |