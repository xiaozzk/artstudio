# shape-lab 资产层独立验收（task-3）

- 生成时间：2026-10-14T02:20:01+08:00
- 生成器：`tmp/shape-lab-verify/verify_assets.py`（**verifier 自写**，不 import `tools/3d/godot/shape-lab/` 任何模块，不读 `reports/bake-report.json`）
- 缓存根：`D:\artstudio\tmp\shape-lab`
- 结论：**PASS** —— 共 315 条判据，PASS 313 / FAIL 0 / 未能证实 2 / 不适用 0

> 口径声明：所有 PASS/FAIL 均由本脚本从 **glb 字节**、`assets/3d/rig/manifests/*.json`、源 `.blend` 的 sha256 重新算出。`bake-report.json` 只在文末作『口径对照』出现，不参与任何判定。

## 1. 总结论表

| 组 | PASS | FAIL | 未能证实 |
|---|---|---|---|
| container | 196 | 0 | 2 |
| ledger | 11 | 0 | 0 |
| manifest | 99 | 0 | 0 |
| pollution | 7 | 0 | 0 |

## 2. 逐条判据（含『什么条件下会红』）

### 组：manifest

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `D-00` | D:\artstudio\tmp\shape-lab\manifest.json | 缓存 manifest.json 存在且可解析 | `14258 字节` | 存在 | **PASS** |
| `D-01` | manifest.json | schema 字段 | `shape-lab-cache` | shape-lab-cache | **PASS** |
| `D-02` | manifest.json | version 字段 | `1` | 1 | **PASS** |
| `D-03` | manifest.json | 必需顶层字段齐全 | `齐全(8 项)` | 齐全 | **PASS** |
| `D-04` | manifest.json | morph_contract 顺序 | `['BS_Thin', 'BS_Heavy']` | ['BS_Thin', 'BS_Heavy'] | **PASS** |
| `D-05` | manifest.json | k_range | `[-1.0, 1.0]` | [-1.0, 1.0] | **PASS** |
| `D-06` | manifest.json | h_range | `[0.92, 1.08]` | [0.92, 1.08] | **PASS** |
| `D-07` | manifest.json | blender_version 非空 | `5.2.0 LTS` | 非空字符串 | **PASS** |
| `D-08` | manifest.json | generated_at 是 ISO8601（含时区） | `'2026-10-14T02:05:34+08:00'` | 含 +08:00 偏移的 ISO8601 | **PASS** |
| `D-09` | manifest.json | characters 数 == 6 | `6` | 6 | **PASS** |
| `D-10` | manifest.json | id 唯一 | `6 个 id / 6 个唯一` | len == len(set) | **PASS** |
| `D-11` | manifest.json | id 集合与契约一致 | `['Body_Female_Standard', 'Body_Male_Standard', 'Female_Peasant', 'Female_Ranger', 'Male_Peasant', 'Male_Ranger']` | ['Body_Female_Standard', 'Body_Male_Standard', 'Female_Peasant', 'Female_Ranger', 'Male_Peasant', 'Male_Ranger'] | **PASS** |
| `D-11b` | manifest.json | 顶层 role_rules == 'v1.1'（role 规则版本必须自报） | `'v1.1'` | v1.1 | **PASS** |
### 组：container

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-01` | Female_Ranger | magic == 'glTF' | `glTF` | glTF | **PASS** |
| `A-02` | Female_Ranger | version == 2 | `2` | 2 | **PASS** |
| `A-03` | Female_Ranger | header.length == 文件字节数 | `55370100 vs 55370100` | 相等 | **PASS** |
| `A-04` | Female_Ranger | chunk 恰好铺满文件（无尾随字节） | `chunk 结束于 55370100 / 文件 55370100` | 相等 | **PASS** |
| `A-05` | Female_Ranger | chunk 顺序/数量：1×JSON + ≤1×BIN，JSON 在首位 | `types=['0x4e4f534a', '0x4e4942']` | [0x4E4F534A, 0x004E4942] | **PASS** |
| `A-06` | Female_Ranger | JSON chunk 可解析 & 解析器 0 错误 | `errors=[]` | [] | **PASS** |
| `A-07` | Female_Ranger | buffer 声明长度 == BIN chunk 长度（允许 0–3 字节 padding） | `[{'index': 0, 'src': 'BIN chunk[0]', 'declared': 55314492, 'actual': 55314492, 'diff': 0, 'ok': True}]` | 0 <= actual-declared <= 3 | **PASS** |
| `A-08` | Female_Ranger | skins 数 == 1 | `1` | 1 | **PASS** |
| `A-09` | Female_Ranger | skin.joints 数 == 65 | `65` | 65 | **PASS** |
| `A-10` | Female_Ranger | nodes 里存在 manifest.armature 指定的骨架节点 | `命中 True` | 存在 'RIG_TryOn_Female_Ranger' | **PASS** |
| `A-11` | Female_Ranger | mesh 数 == manifest.parts 数 | `12 vs 12` | 相等 | **PASS** |
| `A-12` | Female_Ranger | 无相机 / 无灯 / 无动画 | `cameras=0 lights=0 animations=0` | 全 0 | **PASS** |
| `A-13` | Female_Ranger | 每个 primitive 都有 POSITION/JOINTS_0/WEIGHTS_0 | `问题 0 条` | 0 条 | **PASS** |
| `A-14` | Female_Ranger | 按件分档：有 morph 的 primitive targets==2；无 morph 的 primitive targets==0 | `targets==2 的 primitive 13 个；targets==0 的 0 个；异常 0 条` | 异常 0 条 | **PASS** |
| `A-15` | Female_Ranger | targetNames 顺序 == ['BS_Thin','BS_Heavy']（索引 0/1 硬契约） | `问题 0 条; 位置=['mesh']` | 0 条, 位置 ∈ {primitive,mesh} | **PASS** |
| `A-15b` | Female_Ranger | 每个 morph target 的 POSITION count == 同 primitive 的 POSITION count（morph 对齐硬条件） | `不符 0 条` | 0 条 | **PASS** |
| `A-15c` | Female_Ranger | 每个 primitive 的 2 个 target 都带 NORMAL（export_morph_normal=True 的体现） | `缺 NORMAL 的 target 0 个` | 0 个 | **PASS** |
| `A-15d` | Female_Ranger | 记录 morph target 的 sparse 使用情况（解析器必须支持 sparse 才能读到真位移） | `3 个 target 用 sparse；例 [{'part': 'Eyebrows', 'target': 0, 'count': 380, 'accessor_count': 912, 'density': 0.4166666666666667, 'indices_componentType': 5123}, {'part': 'Eyes', 'target': 0, 'count': 282, 'accessor_count': 556, 'density': 0.5071942446043165, 'indices_componentType': 5123}]` | 记录（非判据） | **PASS** |
| `A-16` | Female_Ranger | 每件**带 morph 的**网格默认 morph 权重全 0（无 morph 的网格不需要 weights） | `非零/缺失 0 件：[]` | 0 件 | **PASS** |
| `A-17` | Female_Ranger | manifest 每个 part 名能在 glb 里定位（node 名优先，退回 mesh 名） | `未命中 0 个` | 0 个 | **PASS** |
| `A-18` | Female_Ranger | 顶点数闭环：glb POSITION count ≥ Blender『被面引用顶点数』（= verts − 游离顶点）；且 glb/台账 比值 ∈ [0.9, 2.0] | `闭环违例 0 件；合计 glb=29789 / 台账=27920 比值=1.0669；逐件最大比值=1.1635（Female_Ranger_Arms_Bracer）` | 0 件违例 且 0.9 ≤ 比值 ≤ 2.0 | **PASS** |
| `A-18b` | Female_Ranger | 三角数精确等于台账 faces（Blender 面全为三角时；否则 [faces, 2*faces] 已由 A-19 覆盖） | `精确相等 12/12 件` | 记录（非判据） | **PASS** |
| `A-19` | Female_Ranger | 三角数 ∈ [faces, 2*faces]（Blender 面数按三角化的口径差） | `越界 0 件` | 0 件 | **PASS** |
| `A-20` | Female_Ranger | 逐件材质名集合 == manifest.parts[].materials | `不符 0 件` | 0 件 | **PASS** |
| `A-21` | Female_Ranger | BS_Thin 位移非零（容差 1e-05 m = 0.01 mm；static_by_design 件按『极近零』判） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-22` | Female_Ranger | BS_Heavy 位移非零（同一容差） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-23` | Female_Ranger | BS_Thin max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 12 件；最大 \|Δ\| = 0.0000 cm = 4.690e-07 m（Female_Ranger_Body）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23h` | Female_Ranger | BS_Heavy max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 12 件；最大 \|Δ\| = 0.0000 cm = 4.858e-07 m（Female_Ranger_Head_Hood）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23d` | Female_Ranger | **第三实现**对账：Blender depsgraph 量的 max/mean 位移 vs glb 里的 max/mean 位移（不经任何台账） | `比对 12 件×2 档；max 差最大 = 2.179e-08 m（Female_Ranger_Arms_Bracer/BS_Heavy）；mean 差最大 = 5.895e-04 m` | max 差 ≤ 1e-5 m（float32 级） | **PASS** |
| `A-23e` | Female_Ranger | mean 的**干净子集**对账：仅取 glb 顶点数 == Blender 顶点数的件（同一批顶点，均值的权重与 Blender 一致）→ mean Δ ≤ 1e-6 m | `干净 12 件：mean Δ 最大 = 4.041e-09 m；非干净 12 件：mean Δ 最大 = 5.895e-04 m（顶点复制因子 1.020–1.163）` | 干净子集 mean Δ ≤ 1e-6 m | **PASS** |
| `A-24` | Female_Ranger | images 数 > 0 且 mimeType 合法 | `images=13 textures=13 declared=['image/png']` | >=1 张, mimeType ∈ {image/png,image/jpeg} | **PASS** |
| `A-25` | Female_Ranger | 抽查每张图真解出 PNG/JPEG 头且与声明一致 | `sniffed=['image/png', 'image/png', 'image/png', 'image/png', 'image/png', 'image/png']` | 全部 ∈ {image/png,image/jpeg} | **PASS** |
| `A-26` | Female_Ranger | 贴图链路完整：每个 texture 有合法 source；每个 material 的 baseColorTexture 索引可解析 | `textures 无 source 0 个；materials 有贴图 5/5（无贴图：无）` | textures 无 source == 0；materials 全部有 baseColorTexture | **PASS** |
### 组：manifest

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `D-12` | Female_Ranger | kind/sex/style 与上游台账一致 | `kind=garment sex=Female style=Ranger` | kind=garment sex=Female style=Ranger | **PASS** |
| `D-13` | Female_Ranger | label 结构 ==『{女|男} · {Ranger|Peasant} <中文gloss>（全套）』；Ranger 的 gloss 必须是『游侠』 | `女 · Ranger 游侠（全套）` | 女 · Ranger 游侠（全套） | **PASS** |
| `D-14` | Female_Ranger | armature / bones 与上游台账一致 | `armature=RIG_TryOn_Female_Ranger bones=65` | armature=RIG_TryOn_Female_Ranger bones=65 | **PASS** |
| `D-15` | Female_Ranger | manifest.bones == glb skin.joints 数 | `65 vs 65` | 相等 | **PASS** |
| `D-16` | Female_Ranger | glb 相对路径可从仓库根解析且文件存在 | `解析为 D:\artstudio\tmp\shape-lab\glb\Female_Ranger.glb（存在=True）` | 存在 | **PASS** |
| `D-17` | Female_Ranger | glb_bytes == 真实字节数 | `manifest=55370100 实际=55370100` | 相等 | **PASS** |
| `D-18` | Female_Ranger | src_sha256 == 源 .blend 重算 sha256 | `13a43ff9caf3862b vs 13a43ff9caf3862b` | 逐位相同 | **PASS** |
| `D-20` | Female_Ranger | base_height_m 合理且与台账同源 | `manifest=1.79805 台帐=1.79805 (Δ=0.00000 m)` | 1.0–2.5 m 且与台账一致 | **PASS** |
| `D-20b` | Female_Ranger | base_height_m == 我独立量测的『所有网格世界 Z 并集高度』（**排除 Icosphere**） | `manifest=1.798050；我量(排除球)=1.798046 Δ=3.67e-06；若含球=nan Δ=nan` | Δ ≤ 1e-3 m；且含球口径必须明显不符 | **PASS** |
| `D-21` | Female_Ranger | role 分类逐件重算一致（verifier 自己实现的 v1.1：head(Head_/^(Eyebrows|Eyes)$/_Eyebrows/_Eyes/Hair_)→skin(MI_Regular_/Body_)→foot(_Feet/Boots)→accessory(Acc_/_Belt/_Bracer/_Hood)→cloth） | `不符 0 件；分布={'accessory': 5, 'skin': 1, 'cloth': 2, 'foot': 1, 'head': 3}` | 0 件 | **PASS** |
| `D-21b` | Female_Ranger | role 分布 == v1.1 期望（head 18 / skin 5 / foot 4 / accessory 10 / cloth 9，共 46） | `本角色={'accessory': 5, 'skin': 1, 'cloth': 2, 'foot': 1, 'head': 3}（合计 12）` | 见全局口径（D-26 汇总 46 件） | **PASS** |
| `D-22` | Female_Ranger | parts[].has_morph / morph_names 与 glb 实际一致 | `不符 0 件` | 0 件 | **PASS** |
| `D-23` | Female_Ranger | glb 内自洽：BS_Thin POSITION target 字节数 == Σ(该 target 顶点数)×12 | `glb target 字节=714936，Σ顶点×12=714936（59578 个顶点位）` | 相等 | **PASS** |
| `D-24` | Female_Ranger | 与台账 morph_bytes 口径对照（**口径差，非判据**） | `glb BS_Thin 顶点位=59578 / 台账 Σverts=27920，比值=2.1339` | 记录（非判据） | **PASS** |
### 组：container

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-01` | Male_Ranger | magic == 'glTF' | `glTF` | glTF | **PASS** |
| `A-02` | Male_Ranger | version == 2 | `2` | 2 | **PASS** |
| `A-03` | Male_Ranger | header.length == 文件字节数 | `54800672 vs 54800672` | 相等 | **PASS** |
| `A-04` | Male_Ranger | chunk 恰好铺满文件（无尾随字节） | `chunk 结束于 54800672 / 文件 54800672` | 相等 | **PASS** |
| `A-05` | Male_Ranger | chunk 顺序/数量：1×JSON + ≤1×BIN，JSON 在首位 | `types=['0x4e4f534a', '0x4e4942']` | [0x4E4F534A, 0x004E4942] | **PASS** |
| `A-06` | Male_Ranger | JSON chunk 可解析 & 解析器 0 错误 | `errors=[]` | [] | **PASS** |
| `A-07` | Male_Ranger | buffer 声明长度 == BIN chunk 长度（允许 0–3 字节 padding） | `[{'index': 0, 'src': 'BIN chunk[0]', 'declared': 54748320, 'actual': 54748320, 'diff': 0, 'ok': True}]` | 0 <= actual-declared <= 3 | **PASS** |
| `A-08` | Male_Ranger | skins 数 == 1 | `1` | 1 | **PASS** |
| `A-09` | Male_Ranger | skin.joints 数 == 65 | `65` | 65 | **PASS** |
| `A-10` | Male_Ranger | nodes 里存在 manifest.armature 指定的骨架节点 | `命中 True` | 存在 'RIG_TryOn_Male_Ranger' | **PASS** |
| `A-11` | Male_Ranger | mesh 数 == manifest.parts 数 | `12 vs 12` | 相等 | **PASS** |
| `A-12` | Male_Ranger | 无相机 / 无灯 / 无动画 | `cameras=0 lights=0 animations=0` | 全 0 | **PASS** |
| `A-13` | Male_Ranger | 每个 primitive 都有 POSITION/JOINTS_0/WEIGHTS_0 | `问题 0 条` | 0 条 | **PASS** |
| `A-14` | Male_Ranger | 按件分档：有 morph 的 primitive targets==2；无 morph 的 primitive targets==0 | `targets==2 的 primitive 13 个；targets==0 的 0 个；异常 0 条` | 异常 0 条 | **PASS** |
| `A-15` | Male_Ranger | targetNames 顺序 == ['BS_Thin','BS_Heavy']（索引 0/1 硬契约） | `问题 0 条; 位置=['mesh']` | 0 条, 位置 ∈ {primitive,mesh} | **PASS** |
| `A-15b` | Male_Ranger | 每个 morph target 的 POSITION count == 同 primitive 的 POSITION count（morph 对齐硬条件） | `不符 0 条` | 0 条 | **PASS** |
| `A-15c` | Male_Ranger | 每个 primitive 的 2 个 target 都带 NORMAL（export_morph_normal=True 的体现） | `缺 NORMAL 的 target 0 个` | 0 个 | **PASS** |
| `A-15d` | Male_Ranger | 记录 morph target 的 sparse 使用情况（解析器必须支持 sparse 才能读到真位移） | `0 个 target 用 sparse；例 []` | 记录（非判据） | **PASS** |
| `A-16` | Male_Ranger | 每件**带 morph 的**网格默认 morph 权重全 0（无 morph 的网格不需要 weights） | `非零/缺失 0 件：[]` | 0 件 | **PASS** |
| `A-17` | Male_Ranger | manifest 每个 part 名能在 glb 里定位（node 名优先，退回 mesh 名） | `未命中 0 个` | 0 个 | **PASS** |
| `A-18` | Male_Ranger | 顶点数闭环：glb POSITION count ≥ Blender『被面引用顶点数』（= verts − 游离顶点）；且 glb/台账 比值 ∈ [0.9, 2.0] | `闭环违例 0 件；合计 glb=29782 / 台账=27637 比值=1.0776；逐件最大比值=1.4386（Male_Ranger_Body_Belt_2）` | 0 件违例 且 0.9 ≤ 比值 ≤ 2.0 | **PASS** |
| `A-18b` | Male_Ranger | 三角数精确等于台账 faces（Blender 面全为三角时；否则 [faces, 2*faces] 已由 A-19 覆盖） | `精确相等 12/12 件` | 记录（非判据） | **PASS** |
| `A-19` | Male_Ranger | 三角数 ∈ [faces, 2*faces]（Blender 面数按三角化的口径差） | `越界 0 件` | 0 件 | **PASS** |
| `A-20` | Male_Ranger | 逐件材质名集合 == manifest.parts[].materials | `不符 0 件` | 0 件 | **PASS** |
| `A-21` | Male_Ranger | BS_Thin 位移非零（容差 1e-05 m = 0.01 mm；static_by_design 件按『极近零』判） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-22` | Male_Ranger | BS_Heavy 位移非零（同一容差） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-23` | Male_Ranger | BS_Thin max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 12 件；最大 \|Δ\| = 0.0000 cm = 4.967e-07 m（Male_Ranger_Body_Belt_1）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23h` | Male_Ranger | BS_Heavy max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 12 件；最大 \|Δ\| = 0.0000 cm = 4.074e-07 m（Male_Ranger_Acc_Pauldron）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23d` | Male_Ranger | **第三实现**对账：Blender depsgraph 量的 max/mean 位移 vs glb 里的 max/mean 位移（不经任何台账） | `比对 12 件×2 档；max 差最大 = 2.165e-09 m（Male_Ranger_Head_Hood/BS_Thin）；mean 差最大 = 2.581e-04 m` | max 差 ≤ 1e-5 m（float32 级） | **PASS** |
| `A-23e` | Male_Ranger | mean 的**干净子集**对账：仅取 glb 顶点数 == Blender 顶点数的件（同一批顶点，均值的权重与 Blender 一致）→ mean Δ ≤ 1e-6 m | `干净 10 件：mean Δ 最大 = 2.842e-10 m；非干净 14 件：mean Δ 最大 = 2.581e-04 m（顶点复制因子 0.996–1.439）` | 干净子集 mean Δ ≤ 1e-6 m | **PASS** |
| `A-24` | Male_Ranger | images 数 > 0 且 mimeType 合法 | `images=13 textures=16 declared=['image/png']` | >=1 张, mimeType ∈ {image/png,image/jpeg} | **PASS** |
| `A-25` | Male_Ranger | 抽查每张图真解出 PNG/JPEG 头且与声明一致 | `sniffed=['image/png', 'image/png', 'image/png', 'image/png', 'image/png', 'image/png']` | 全部 ∈ {image/png,image/jpeg} | **PASS** |
| `A-26` | Male_Ranger | 贴图链路完整：每个 texture 有合法 source；每个 material 的 baseColorTexture 索引可解析 | `textures 无 source 0 个；materials 有贴图 6/6（无贴图：无）` | textures 无 source == 0；materials 全部有 baseColorTexture | **PASS** |
### 组：manifest

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `D-12` | Male_Ranger | kind/sex/style 与上游台账一致 | `kind=garment sex=Male style=Ranger` | kind=garment sex=Male style=Ranger | **PASS** |
| `D-13` | Male_Ranger | label 结构 ==『{女|男} · {Ranger|Peasant} <中文gloss>（全套）』；Ranger 的 gloss 必须是『游侠』 | `男 · Ranger 游侠（全套）` | 男 · Ranger 游侠（全套） | **PASS** |
| `D-14` | Male_Ranger | armature / bones 与上游台账一致 | `armature=RIG_TryOn_Male_Ranger bones=65` | armature=RIG_TryOn_Male_Ranger bones=65 | **PASS** |
| `D-15` | Male_Ranger | manifest.bones == glb skin.joints 数 | `65 vs 65` | 相等 | **PASS** |
| `D-16` | Male_Ranger | glb 相对路径可从仓库根解析且文件存在 | `解析为 D:\artstudio\tmp\shape-lab\glb\Male_Ranger.glb（存在=True）` | 存在 | **PASS** |
| `D-17` | Male_Ranger | glb_bytes == 真实字节数 | `manifest=54800672 实际=54800672` | 相等 | **PASS** |
| `D-18` | Male_Ranger | src_sha256 == 源 .blend 重算 sha256 | `fd758549d25155d7 vs fd758549d25155d7` | 逐位相同 | **PASS** |
| `D-20` | Male_Ranger | base_height_m 合理且与台账同源 | `manifest=1.86901 台帐=1.86901 (Δ=0.00000 m)` | 1.0–2.5 m 且与台账一致 | **PASS** |
| `D-20b` | Male_Ranger | base_height_m == 我独立量测的『所有网格世界 Z 并集高度』（**排除 Icosphere**） | `manifest=1.869010；我量(排除球)=1.869008 Δ=1.99e-06；若含球=nan Δ=nan` | Δ ≤ 1e-3 m；且含球口径必须明显不符 | **PASS** |
| `D-21` | Male_Ranger | role 分类逐件重算一致（verifier 自己实现的 v1.1：head(Head_/^(Eyebrows|Eyes)$/_Eyebrows/_Eyes/Hair_)→skin(MI_Regular_/Body_)→foot(_Feet/Boots)→accessory(Acc_/_Belt/_Bracer/_Hood)→cloth） | `不符 0 件；分布={'head': 3, 'accessory': 5, 'skin': 1, 'cloth': 2, 'foot': 1}` | 0 件 | **PASS** |
| `D-21b` | Male_Ranger | role 分布 == v1.1 期望（head 18 / skin 5 / foot 4 / accessory 10 / cloth 9，共 46） | `本角色={'head': 3, 'accessory': 5, 'skin': 1, 'cloth': 2, 'foot': 1}（合计 12）` | 见全局口径（D-26 汇总 46 件） | **PASS** |
| `D-22` | Male_Ranger | parts[].has_morph / morph_names 与 glb 实际一致 | `不符 0 件` | 0 件 | **PASS** |
| `D-23` | Male_Ranger | glb 内自洽：BS_Thin POSITION target 字节数 == Σ(该 target 顶点数)×12 | `glb target 字节=714768，Σ顶点×12=714768（59564 个顶点位）` | 相等 | **PASS** |
| `D-24` | Male_Ranger | 与台账 morph_bytes 口径对照（**口径差，非判据**） | `glb BS_Thin 顶点位=59564 / 台账 Σverts=27637，比值=2.1552` | 记录（非判据） | **PASS** |
### 组：container

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-01` | Female_Peasant | magic == 'glTF' | `glTF` | glTF | **PASS** |
| `A-02` | Female_Peasant | version == 2 | `2` | 2 | **PASS** |
| `A-03` | Female_Peasant | header.length == 文件字节数 | `43665480 vs 43665480` | 相等 | **PASS** |
| `A-04` | Female_Peasant | chunk 恰好铺满文件（无尾随字节） | `chunk 结束于 43665480 / 文件 43665480` | 相等 | **PASS** |
| `A-05` | Female_Peasant | chunk 顺序/数量：1×JSON + ≤1×BIN，JSON 在首位 | `types=['0x4e4f534a', '0x4e4942']` | [0x4E4F534A, 0x004E4942] | **PASS** |
| `A-06` | Female_Peasant | JSON chunk 可解析 & 解析器 0 错误 | `errors=[]` | [] | **PASS** |
| `A-07` | Female_Peasant | buffer 声明长度 == BIN chunk 长度（允许 0–3 字节 padding） | `[{'index': 0, 'src': 'BIN chunk[0]', 'declared': 43624952, 'actual': 43624952, 'diff': 0, 'ok': True}]` | 0 <= actual-declared <= 3 | **PASS** |
| `A-08` | Female_Peasant | skins 数 == 1 | `1` | 1 | **PASS** |
| `A-09` | Female_Peasant | skin.joints 数 == 65 | `65` | 65 | **PASS** |
| `A-10` | Female_Peasant | nodes 里存在 manifest.armature 指定的骨架节点 | `命中 True` | 存在 'RIG_TryOn_Female_Peasant' | **PASS** |
| `A-11` | Female_Peasant | mesh 数 == manifest.parts 数 | `8 vs 8` | 相等 | **PASS** |
| `A-12` | Female_Peasant | 无相机 / 无灯 / 无动画 | `cameras=0 lights=0 animations=0` | 全 0 | **PASS** |
| `A-13` | Female_Peasant | 每个 primitive 都有 POSITION/JOINTS_0/WEIGHTS_0 | `问题 0 条` | 0 条 | **PASS** |
| `A-14` | Female_Peasant | 按件分档：有 morph 的 primitive targets==2；无 morph 的 primitive targets==0 | `targets==2 的 primitive 8 个；targets==0 的 0 个；异常 0 条` | 异常 0 条 | **PASS** |
| `A-15` | Female_Peasant | targetNames 顺序 == ['BS_Thin','BS_Heavy']（索引 0/1 硬契约） | `问题 0 条; 位置=['mesh']` | 0 条, 位置 ∈ {primitive,mesh} | **PASS** |
| `A-15b` | Female_Peasant | 每个 morph target 的 POSITION count == 同 primitive 的 POSITION count（morph 对齐硬条件） | `不符 0 条` | 0 条 | **PASS** |
| `A-15c` | Female_Peasant | 每个 primitive 的 2 个 target 都带 NORMAL（export_morph_normal=True 的体现） | `缺 NORMAL 的 target 0 个` | 0 个 | **PASS** |
| `A-15d` | Female_Peasant | 记录 morph target 的 sparse 使用情况（解析器必须支持 sparse 才能读到真位移） | `4 个 target 用 sparse；例 [{'part': 'Hair_Long', 'target': 0, 'count': 2397, 'accessor_count': 3080, 'density': 0.7782467532467533, 'indices_componentType': 5123}, {'part': 'Eyebrows', 'target': 0, 'count': 380, 'accessor_count': 912, 'density': 0.4166666666666667, 'indices_componentType': 5123}]` | 记录（非判据） | **PASS** |
| `A-16` | Female_Peasant | 每件**带 morph 的**网格默认 morph 权重全 0（无 morph 的网格不需要 weights） | `非零/缺失 0 件：[]` | 0 件 | **PASS** |
| `A-17` | Female_Peasant | manifest 每个 part 名能在 glb 里定位（node 名优先，退回 mesh 名） | `未命中 0 个` | 0 个 | **PASS** |
| `A-18` | Female_Peasant | 顶点数闭环：glb POSITION count ≥ Blender『被面引用顶点数』（= verts − 游离顶点）；且 glb/台账 比值 ∈ [0.9, 2.0] | `闭环违例 0 件；合计 glb=16788 / 台账=16376 比值=1.0252；逐件最大比值=1.0706（Female_Peasant_Arms）` | 0 件违例 且 0.9 ≤ 比值 ≤ 2.0 | **PASS** |
| `A-18b` | Female_Peasant | 三角数精确等于台账 faces（Blender 面全为三角时；否则 [faces, 2*faces] 已由 A-19 覆盖） | `精确相等 8/8 件` | 记录（非判据） | **PASS** |
| `A-19` | Female_Peasant | 三角数 ∈ [faces, 2*faces]（Blender 面数按三角化的口径差） | `越界 0 件` | 0 件 | **PASS** |
| `A-20` | Female_Peasant | 逐件材质名集合 == manifest.parts[].materials | `不符 0 件` | 0 件 | **PASS** |
| `A-21` | Female_Peasant | BS_Thin 位移非零（容差 1e-05 m = 0.01 mm；static_by_design 件按『极近零』判） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-22` | Female_Peasant | BS_Heavy 位移非零（同一容差） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-23` | Female_Peasant | BS_Thin max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 8 件；最大 \|Δ\| = 0.0000 cm = 4.305e-07 m（Female_Peasant_Legs）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23h` | Female_Peasant | BS_Heavy max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 8 件；最大 \|Δ\| = 0.0000 cm = 4.937e-07 m（Female_Peasant_Arms）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23d` | Female_Peasant | **第三实现**对账：Blender depsgraph 量的 max/mean 位移 vs glb 里的 max/mean 位移（不经任何台账） | `比对 8 件×2 档；max 差最大 = 2.424e-09 m（Female_Peasant_Feet/BS_Thin）；mean 差最大 = 8.549e-05 m` | max 差 ≤ 1e-5 m（float32 级） | **PASS** |
| `A-23e` | Female_Peasant | mean 的**干净子集**对账：仅取 glb 顶点数 == Blender 顶点数的件（同一批顶点，均值的权重与 Blender 一致）→ mean Δ ≤ 1e-6 m | `干净 12 件：mean Δ 最大 = 1.128e-09 m；非干净 4 件：mean Δ 最大 = 8.549e-05 m（顶点复制因子 1.016–1.071）` | 干净子集 mean Δ ≤ 1e-6 m | **PASS** |
| `A-24` | Female_Peasant | images 数 > 0 且 mimeType 合法 | `images=10 textures=15 declared=['image/png']` | >=1 张, mimeType ∈ {image/png,image/jpeg} | **PASS** |
| `A-25` | Female_Peasant | 抽查每张图真解出 PNG/JPEG 头且与声明一致 | `sniffed=['image/png', 'image/png', 'image/png', 'image/png', 'image/png', 'image/png']` | 全部 ∈ {image/png,image/jpeg} | **PASS** |
| `A-26` | Female_Peasant | 贴图链路完整：每个 texture 有合法 source；每个 material 的 baseColorTexture 索引可解析 | `textures 无 source 0 个；materials 有贴图 6/6（无贴图：无）` | textures 无 source == 0；materials 全部有 baseColorTexture | **PASS** |
### 组：manifest

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `D-12` | Female_Peasant | kind/sex/style 与上游台账一致 | `kind=garment sex=Female style=Peasant` | kind=garment sex=Female style=Peasant | **PASS** |
| `D-13` | Female_Peasant | label 结构 ==『{女|男} · {Ranger|Peasant} <中文gloss>（全套）』；Ranger 的 gloss 必须是『游侠』 | `女 · Peasant 平民（全套）` | 女 · Peasant <未冻结>（全套） | **PASS** |
| `D-14` | Female_Peasant | armature / bones 与上游台账一致 | `armature=RIG_TryOn_Female_Peasant bones=65` | armature=RIG_TryOn_Female_Peasant bones=65 | **PASS** |
| `D-15` | Female_Peasant | manifest.bones == glb skin.joints 数 | `65 vs 65` | 相等 | **PASS** |
| `D-16` | Female_Peasant | glb 相对路径可从仓库根解析且文件存在 | `解析为 D:\artstudio\tmp\shape-lab\glb\Female_Peasant.glb（存在=True）` | 存在 | **PASS** |
| `D-17` | Female_Peasant | glb_bytes == 真实字节数 | `manifest=43665480 实际=43665480` | 相等 | **PASS** |
| `D-18` | Female_Peasant | src_sha256 == 源 .blend 重算 sha256 | `2a0bcf3147d608f6 vs 2a0bcf3147d608f6` | 逐位相同 | **PASS** |
| `D-20` | Female_Peasant | base_height_m 合理且与台账同源 | `manifest=1.78397 台帐=1.78397 (Δ=0.00000 m)` | 1.0–2.5 m 且与台账一致 | **PASS** |
| `D-20b` | Female_Peasant | base_height_m == 我独立量测的『所有网格世界 Z 并集高度』（**排除 Icosphere**） | `manifest=1.783970；我量(排除球)=1.783973 Δ=2.69e-06；若含球=nan Δ=nan` | Δ ≤ 1e-3 m；且含球口径必须明显不符 | **PASS** |
| `D-21` | Female_Peasant | role 分类逐件重算一致（verifier 自己实现的 v1.1：head(Head_/^(Eyebrows|Eyes)$/_Eyebrows/_Eyes/Hair_)→skin(MI_Regular_/Body_)→foot(_Feet/Boots)→accessory(Acc_/_Belt/_Bracer/_Hood)→cloth） | `不符 0 件；分布={'cloth': 3, 'foot': 1, 'head': 4}` | 0 件 | **PASS** |
| `D-21b` | Female_Peasant | role 分布 == v1.1 期望（head 18 / skin 5 / foot 4 / accessory 10 / cloth 9，共 46） | `本角色={'cloth': 3, 'foot': 1, 'head': 4}（合计 8）` | 见全局口径（D-26 汇总 46 件） | **PASS** |
| `D-22` | Female_Peasant | parts[].has_morph / morph_names 与 glb 实际一致 | `不符 0 件` | 0 件 | **PASS** |
| `D-23` | Female_Peasant | glb 内自洽：BS_Thin POSITION target 字节数 == Σ(该 target 顶点数)×12 | `glb target 字节=402912，Σ顶点×12=402912（33576 个顶点位）` | 相等 | **PASS** |
| `D-24` | Female_Peasant | 与台账 morph_bytes 口径对照（**口径差，非判据**） | `glb BS_Thin 顶点位=33576 / 台账 Σverts=16376，比值=2.0503` | 记录（非判据） | **PASS** |
### 组：container

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-01` | Male_Peasant | magic == 'glTF' | `glTF` | glTF | **PASS** |
| `A-02` | Male_Peasant | version == 2 | `2` | 2 | **PASS** |
| `A-03` | Male_Peasant | header.length == 文件字节数 | `51608164 vs 51608164` | 相等 | **PASS** |
| `A-04` | Male_Peasant | chunk 恰好铺满文件（无尾随字节） | `chunk 结束于 51608164 / 文件 51608164` | 相等 | **PASS** |
| `A-05` | Male_Peasant | chunk 顺序/数量：1×JSON + ≤1×BIN，JSON 在首位 | `types=['0x4e4f534a', '0x4e4942']` | [0x4E4F534A, 0x004E4942] | **PASS** |
| `A-06` | Male_Peasant | JSON chunk 可解析 & 解析器 0 错误 | `errors=[]` | [] | **PASS** |
| `A-07` | Male_Peasant | buffer 声明长度 == BIN chunk 长度（允许 0–3 字节 padding） | `[{'index': 0, 'src': 'BIN chunk[0]', 'declared': 51565176, 'actual': 51565176, 'diff': 0, 'ok': True}]` | 0 <= actual-declared <= 3 | **PASS** |
| `A-08` | Male_Peasant | skins 数 == 1 | `1` | 1 | **PASS** |
| `A-09` | Male_Peasant | skin.joints 数 == 65 | `65` | 65 | **PASS** |
| `A-10` | Male_Peasant | nodes 里存在 manifest.armature 指定的骨架节点 | `命中 True` | 存在 'RIG_TryOn_Male_Peasant' | **PASS** |
| `A-11` | Male_Peasant | mesh 数 == manifest.parts 数 | `8 vs 8` | 相等 | **PASS** |
| `A-12` | Male_Peasant | 无相机 / 无灯 / 无动画 | `cameras=0 lights=0 animations=0` | 全 0 | **PASS** |
| `A-13` | Male_Peasant | 每个 primitive 都有 POSITION/JOINTS_0/WEIGHTS_0 | `问题 0 条` | 0 条 | **PASS** |
| `A-14` | Male_Peasant | 按件分档：有 morph 的 primitive targets==2；无 morph 的 primitive targets==0 | `targets==2 的 primitive 9 个；targets==0 的 0 个；异常 0 条` | 异常 0 条 | **PASS** |
| `A-15` | Male_Peasant | targetNames 顺序 == ['BS_Thin','BS_Heavy']（索引 0/1 硬契约） | `问题 0 条; 位置=['mesh']` | 0 条, 位置 ∈ {primitive,mesh} | **PASS** |
| `A-15b` | Male_Peasant | 每个 morph target 的 POSITION count == 同 primitive 的 POSITION count（morph 对齐硬条件） | `不符 0 条` | 0 条 | **PASS** |
| `A-15c` | Male_Peasant | 每个 primitive 的 2 个 target 都带 NORMAL（export_morph_normal=True 的体现） | `缺 NORMAL 的 target 0 个` | 0 个 | **PASS** |
| `A-15d` | Male_Peasant | 记录 morph target 的 sparse 使用情况（解析器必须支持 sparse 才能读到真位移） | `0 个 target 用 sparse；例 []` | 记录（非判据） | **PASS** |
| `A-16` | Male_Peasant | 每件**带 morph 的**网格默认 morph 权重全 0（无 morph 的网格不需要 weights） | `非零/缺失 0 件：[]` | 0 件 | **PASS** |
| `A-17` | Male_Peasant | manifest 每个 part 名能在 glb 里定位（node 名优先，退回 mesh 名） | `未命中 0 个` | 0 个 | **PASS** |
| `A-18` | Male_Peasant | 顶点数闭环：glb POSITION count ≥ Blender『被面引用顶点数』（= verts − 游离顶点）；且 glb/台账 比值 ∈ [0.9, 2.0] | `闭环违例 0 件；合计 glb=12388 / 台账=12376 比值=1.0010；逐件最大比值=1.0053（Male_Peasant_Body）` | 0 件违例 且 0.9 ≤ 比值 ≤ 2.0 | **PASS** |
| `A-18b` | Male_Peasant | 三角数精确等于台账 faces（Blender 面全为三角时；否则 [faces, 2*faces] 已由 A-19 覆盖） | `精确相等 8/8 件` | 记录（非判据） | **PASS** |
| `A-19` | Male_Peasant | 三角数 ∈ [faces, 2*faces]（Blender 面数按三角化的口径差） | `越界 0 件` | 0 件 | **PASS** |
| `A-20` | Male_Peasant | 逐件材质名集合 == manifest.parts[].materials | `不符 0 件` | 0 件 | **PASS** |
| `A-21` | Male_Peasant | BS_Thin 位移非零（容差 1e-05 m = 0.01 mm；static_by_design 件按『极近零』判） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-22` | Male_Peasant | BS_Heavy 位移非零（同一容差） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-23` | Male_Peasant | BS_Thin max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 8 件；最大 \|Δ\| = 0.0000 cm = 4.152e-07 m（Male_Peasant_Body）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23h` | Male_Peasant | BS_Heavy max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 8 件；最大 \|Δ\| = 0.0000 cm = 4.305e-07 m（Male_Peasant_Legs）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23d` | Male_Peasant | **第三实现**对账：Blender depsgraph 量的 max/mean 位移 vs glb 里的 max/mean 位移（不经任何台账） | `比对 8 件×2 档；max 差最大 = 6.166e-10 m（Male_Peasant_Body/BS_Heavy）；mean 差最大 = 2.331e-05 m` | max 差 ≤ 1e-5 m（float32 级） | **PASS** |
| `A-23e` | Male_Peasant | mean 的**干净子集**对账：仅取 glb 顶点数 == Blender 顶点数的件（同一批顶点，均值的权重与 Blender 一致）→ mean Δ ≤ 1e-6 m | `干净 10 件：mean Δ 最大 = 3.812e-10 m；非干净 6 件：mean Δ 最大 = 2.331e-05 m（顶点复制因子 0.996–1.005）` | 干净子集 mean Δ ≤ 1e-6 m | **PASS** |
| `A-24` | Male_Peasant | images 数 > 0 且 mimeType 合法 | `images=13 textures=15 declared=['image/png']` | >=1 张, mimeType ∈ {image/png,image/jpeg} | **PASS** |
| `A-25` | Male_Peasant | 抽查每张图真解出 PNG/JPEG 头且与声明一致 | `sniffed=['image/png', 'image/png', 'image/png', 'image/png', 'image/png', 'image/png']` | 全部 ∈ {image/png,image/jpeg} | **PASS** |
| `A-26` | Male_Peasant | 贴图链路完整：每个 texture 有合法 source；每个 material 的 baseColorTexture 索引可解析 | `textures 无 source 0 个；materials 有贴图 6/6（无贴图：无）` | textures 无 source == 0；materials 全部有 baseColorTexture | **PASS** |
### 组：manifest

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `D-12` | Male_Peasant | kind/sex/style 与上游台账一致 | `kind=garment sex=Male style=Peasant` | kind=garment sex=Male style=Peasant | **PASS** |
| `D-13` | Male_Peasant | label 结构 ==『{女|男} · {Ranger|Peasant} <中文gloss>（全套）』；Ranger 的 gloss 必须是『游侠』 | `男 · Peasant 平民（全套）` | 男 · Peasant <未冻结>（全套） | **PASS** |
| `D-14` | Male_Peasant | armature / bones 与上游台账一致 | `armature=RIG_TryOn_Male_Peasant bones=65` | armature=RIG_TryOn_Male_Peasant bones=65 | **PASS** |
| `D-15` | Male_Peasant | manifest.bones == glb skin.joints 数 | `65 vs 65` | 相等 | **PASS** |
| `D-16` | Male_Peasant | glb 相对路径可从仓库根解析且文件存在 | `解析为 D:\artstudio\tmp\shape-lab\glb\Male_Peasant.glb（存在=True）` | 存在 | **PASS** |
| `D-17` | Male_Peasant | glb_bytes == 真实字节数 | `manifest=51608164 实际=51608164` | 相等 | **PASS** |
| `D-18` | Male_Peasant | src_sha256 == 源 .blend 重算 sha256 | `49b9fb4a77c4e443 vs 49b9fb4a77c4e443` | 逐位相同 | **PASS** |
| `D-20` | Male_Peasant | base_height_m 合理且与台账同源 | `manifest=1.84369 台帐=1.84369 (Δ=0.00000 m)` | 1.0–2.5 m 且与台账一致 | **PASS** |
| `D-20b` | Male_Peasant | base_height_m == 我独立量测的『所有网格世界 Z 并集高度』（**排除 Icosphere**） | `manifest=1.843690；我量(排除球)=1.843689 Δ=6.13e-07；若含球=nan Δ=nan` | Δ ≤ 1e-3 m；且含球口径必须明显不符 | **PASS** |
| `D-21` | Male_Peasant | role 分类逐件重算一致（verifier 自己实现的 v1.1：head(Head_/^(Eyebrows|Eyes)$/_Eyebrows/_Eyes/Hair_)→skin(MI_Regular_/Body_)→foot(_Feet/Boots)→accessory(Acc_/_Belt/_Bracer/_Hood)→cloth） | `不符 0 件；分布={'head': 4, 'skin': 1, 'cloth': 2, 'foot': 1}` | 0 件 | **PASS** |
| `D-21b` | Male_Peasant | role 分布 == v1.1 期望（head 18 / skin 5 / foot 4 / accessory 10 / cloth 9，共 46） | `本角色={'head': 4, 'skin': 1, 'cloth': 2, 'foot': 1}（合计 8）` | 见全局口径（D-26 汇总 46 件） | **PASS** |
| `D-22` | Male_Peasant | parts[].has_morph / morph_names 与 glb 实际一致 | `不符 0 件` | 0 件 | **PASS** |
| `D-23` | Male_Peasant | glb 内自洽：BS_Thin POSITION target 字节数 == Σ(该 target 顶点数)×12 | `glb target 字节=297312，Σ顶点×12=297312（24776 个顶点位）` | 相等 | **PASS** |
| `D-24` | Male_Peasant | 与台账 morph_bytes 口径对照（**口径差，非判据**） | `glb BS_Thin 顶点位=24776 / 台账 Σverts=12376，比值=2.0019` | 记录（非判据） | **PASS** |
### 组：container

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-01` | Body_Female_Standard | magic == 'glTF' | `glTF` | glTF | **PASS** |
| `A-02` | Body_Female_Standard | version == 2 | `2` | 2 | **PASS** |
| `A-03` | Body_Female_Standard | header.length == 文件字节数 | `14019680 vs 14019680` | 相等 | **PASS** |
| `A-04` | Body_Female_Standard | chunk 恰好铺满文件（无尾随字节） | `chunk 结束于 14019680 / 文件 14019680` | 相等 | **PASS** |
| `A-05` | Body_Female_Standard | chunk 顺序/数量：1×JSON + ≤1×BIN，JSON 在首位 | `types=['0x4e4f534a', '0x4e4942']` | [0x4E4F534A, 0x004E4942] | **PASS** |
| `A-06` | Body_Female_Standard | JSON chunk 可解析 & 解析器 0 错误 | `errors=[]` | [] | **PASS** |
| `A-07` | Body_Female_Standard | buffer 声明长度 == BIN chunk 长度（允许 0–3 字节 padding） | `[{'index': 0, 'src': 'BIN chunk[0]', 'declared': 13994568, 'actual': 13994568, 'diff': 0, 'ok': True}]` | 0 <= actual-declared <= 3 | **PASS** |
| `A-08` | Body_Female_Standard | skins 数 == 1 | `1` | 1 | **PASS** |
| `A-09` | Body_Female_Standard | skin.joints 数 == 65 | `65` | 65 | **PASS** |
| `A-10` | Body_Female_Standard | nodes 里存在 manifest.armature 指定的骨架节点 | `命中 True` | 存在 'RIG_Body_Female_Standard' | **PASS** |
| `A-11` | Body_Female_Standard | mesh 数 == manifest.parts 数 | `3 vs 3` | 相等 | **PASS** |
| `A-12` | Body_Female_Standard | 无相机 / 无灯 / 无动画 | `cameras=0 lights=0 animations=0` | 全 0 | **PASS** |
| `A-13` | Body_Female_Standard | 每个 primitive 都有 POSITION/JOINTS_0/WEIGHTS_0 | `问题 0 条` | 0 条 | **PASS** |
| `A-14` | Body_Female_Standard | 按件分档：有 morph 的 primitive targets==2；无 morph 的 primitive targets==0 | `targets==2 的 primitive 1 个；targets==0 的 2 个；异常 0 条` | 异常 0 条 | **PASS** |
| `A-15` | Body_Female_Standard | targetNames 顺序 == ['BS_Thin','BS_Heavy']（索引 0/1 硬契约） | `问题 0 条; 位置=['mesh']` | 0 条, 位置 ∈ {primitive,mesh} | **PASS** |
| `A-15b` | Body_Female_Standard | 每个 morph target 的 POSITION count == 同 primitive 的 POSITION count（morph 对齐硬条件） | `不符 0 条` | 0 条 | **PASS** |
| `A-15c` | Body_Female_Standard | 每个 primitive 的 2 个 target 都带 NORMAL（export_morph_normal=True 的体现） | `缺 NORMAL 的 target 0 个` | 0 个 | **PASS** |
| `A-15d` | Body_Female_Standard | 记录 morph target 的 sparse 使用情况（解析器必须支持 sparse 才能读到真位移） | `0 个 target 用 sparse；例 []` | 记录（非判据） | **PASS** |
| `A-16` | Body_Female_Standard | 每件**带 morph 的**网格默认 morph 权重全 0（无 morph 的网格不需要 weights） | `非零/缺失 0 件：[]` | 0 件 | **PASS** |
| `A-17` | Body_Female_Standard | manifest 每个 part 名能在 glb 里定位（node 名优先，退回 mesh 名） | `未命中 0 个` | 0 个 | **PASS** |
| `A-18` | Body_Female_Standard | 顶点数闭环：glb POSITION count ≥ Blender『被面引用顶点数』（= verts − 游离顶点）；且 glb/台账 比值 ∈ [0.9, 2.0] | `闭环违例 0 件；合计 glb=8848 / 台账=8844 比值=1.0005；逐件最大比值=1.0005（Body_Female）` | 0 件违例 且 0.9 ≤ 比值 ≤ 2.0 | **PASS** |
| `A-18b` | Body_Female_Standard | 三角数精确等于台账 faces（Blender 面全为三角时；否则 [faces, 2*faces] 已由 A-19 覆盖） | `精确相等 3/3 件` | 记录（非判据） | **PASS** |
| `A-19` | Body_Female_Standard | 三角数 ∈ [faces, 2*faces]（Blender 面数按三角化的口径差） | `越界 0 件` | 0 件 | **PASS** |
| `A-20` | Body_Female_Standard | 逐件材质名集合 == manifest.parts[].materials | `不符 0 件` | 0 件 | **PASS** |
| `A-21` | Body_Female_Standard | BS_Thin 位移非零（容差 1e-05 m = 0.01 mm；static_by_design 件按『极近零』判） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-22` | Body_Female_Standard | BS_Heavy 位移非零（同一容差） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-23` | Body_Female_Standard | BS_Thin max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 1 件；最大 \|Δ\| = 0.0000 cm = 4.974e-07 m（Body_Female）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23h` | Body_Female_Standard | BS_Heavy max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 1 件；最大 \|Δ\| = 0.0000 cm = 8.188e-08 m（Body_Female）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23d` | Body_Female_Standard | **第三实现**对账：Blender depsgraph 量的 max/mean 位移 vs glb 里的 max/mean 位移（不经任何台账） | `比对 1 件×2 档；max 差最大 = 1.855e-08 m（Body_Female/BS_Heavy）；mean 差最大 = 1.170e-06 m` | max 差 ≤ 1e-5 m（float32 级） | **PASS** |
| `A-23e` | Body_Female_Standard | mean 的**干净子集**对账：仅取 glb 顶点数 == Blender 顶点数的件（同一批顶点，均值的权重与 Blender 一致）→ mean Δ ≤ 1e-6 m | `干净 0 件：mean Δ 最大 = 0.000e+00 m；非干净 2 件：mean Δ 最大 = 1.170e-06 m（顶点复制因子 1.001–1.001）` | 干净子集 mean Δ ≤ 1e-6 m | **UNVERIFIED** |
| `A-24` | Body_Female_Standard | images 数 > 0 且 mimeType 合法 | `images=7 textures=7 declared=['image/png']` | >=1 张, mimeType ∈ {image/png,image/jpeg} | **PASS** |
| `A-25` | Body_Female_Standard | 抽查每张图真解出 PNG/JPEG 头且与声明一致 | `sniffed=['image/png', 'image/png', 'image/png', 'image/png', 'image/png', 'image/png']` | 全部 ∈ {image/png,image/jpeg} | **PASS** |
| `A-26` | Body_Female_Standard | 贴图链路完整：每个 texture 有合法 source；每个 material 的 baseColorTexture 索引可解析 | `textures 无 source 0 个；materials 有贴图 3/3（无贴图：无）` | textures 无 source == 0；materials 全部有 baseColorTexture | **PASS** |
### 组：manifest

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `D-12` | Body_Female_Standard | kind/sex/style 与上游台账一致 | `kind=body sex=Female style=Standard` | kind=body sex=Female style=Standard | **PASS** |
| `D-13` | Body_Female_Standard | label 前缀（body 必须『裸模 · 身形基准』） | `裸模 · 身形基准（女）` | 『裸模 · 身形基准』开头 | **PASS** |
| `D-14` | Body_Female_Standard | armature / bones 与上游台账一致 | `armature=RIG_Body_Female_Standard bones=65` | armature=RIG_Body_Female_Standard bones=65 | **PASS** |
| `D-15` | Body_Female_Standard | manifest.bones == glb skin.joints 数 | `65 vs 65` | 相等 | **PASS** |
| `D-16` | Body_Female_Standard | glb 相对路径可从仓库根解析且文件存在 | `解析为 D:\artstudio\tmp\shape-lab\glb\Body_Female_Standard.glb（存在=True）` | 存在 | **PASS** |
| `D-17` | Body_Female_Standard | glb_bytes == 真实字节数 | `manifest=14019680 实际=14019680` | 相等 | **PASS** |
| `D-18` | Body_Female_Standard | src_sha256 == 源 .blend 重算 sha256 | `c420817b98a89bf8 vs c420817b98a89bf8` | 逐位相同 | **PASS** |
| `D-19` | Body_Female_Standard | src_sha256 == bodyshape_manifest.blend_sha256（上游权威） | `c420817b98a89bf8 vs c420817b98a89bf8` | 逐位相同 | **PASS** |
| `D-20` | Body_Female_Standard | base_height_m 合理且与台账同源 | `manifest=1.77505 台帐=1.77505 (Δ=0.00000 m)` | 1.0–2.5 m 且与台账一致 | **PASS** |
| `D-20b` | Body_Female_Standard | base_height_m == 我独立量测的『所有网格世界 Z 并集高度』（**排除 Icosphere**） | `manifest=1.775051；我量(排除球)=1.775051 Δ=1.69e-07；若含球=2.766644 Δ=0.9916` | Δ ≤ 1e-3 m；且含球口径必须明显不符 | **PASS** |
| `D-21` | Body_Female_Standard | role 分类逐件重算一致（verifier 自己实现的 v1.1：head(Head_/^(Eyebrows|Eyes)$/_Eyebrows/_Eyes/Hair_)→skin(MI_Regular_/Body_)→foot(_Feet/Boots)→accessory(Acc_/_Belt/_Bracer/_Hood)→cloth） | `不符 0 件；分布={'skin': 1, 'head': 2}` | 0 件 | **PASS** |
| `D-21b` | Body_Female_Standard | role 分布 == v1.1 期望（head 18 / skin 5 / foot 4 / accessory 10 / cloth 9，共 46） | `本角色={'skin': 1, 'head': 2}（合计 3）` | 见全局口径（D-26 汇总 46 件） | **PASS** |
| `D-22` | Body_Female_Standard | parts[].has_morph / morph_names 与 glb 实际一致 | `不符 0 件` | 0 件 | **PASS** |
| `D-23` | Body_Female_Standard | glb 内自洽：BS_Thin POSITION target 字节数 == Σ(该 target 顶点数)×12 | `glb target 字节=177120，Σ顶点×12=177120（14760 个顶点位）` | 相等 | **PASS** |
### 组：container

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `A-01` | Body_Male_Standard | magic == 'glTF' | `glTF` | glTF | **PASS** |
| `A-02` | Body_Male_Standard | version == 2 | `2` | 2 | **PASS** |
| `A-03` | Body_Male_Standard | header.length == 文件字节数 | `13490444 vs 13490444` | 相等 | **PASS** |
| `A-04` | Body_Male_Standard | chunk 恰好铺满文件（无尾随字节） | `chunk 结束于 13490444 / 文件 13490444` | 相等 | **PASS** |
| `A-05` | Body_Male_Standard | chunk 顺序/数量：1×JSON + ≤1×BIN，JSON 在首位 | `types=['0x4e4f534a', '0x4e4942']` | [0x4E4F534A, 0x004E4942] | **PASS** |
| `A-06` | Body_Male_Standard | JSON chunk 可解析 & 解析器 0 错误 | `errors=[]` | [] | **PASS** |
| `A-07` | Body_Male_Standard | buffer 声明长度 == BIN chunk 长度（允许 0–3 字节 padding） | `[{'index': 0, 'src': 'BIN chunk[0]', 'declared': 13466004, 'actual': 13466004, 'diff': 0, 'ok': True}]` | 0 <= actual-declared <= 3 | **PASS** |
| `A-08` | Body_Male_Standard | skins 数 == 1 | `1` | 1 | **PASS** |
| `A-09` | Body_Male_Standard | skin.joints 数 == 65 | `65` | 65 | **PASS** |
| `A-10` | Body_Male_Standard | nodes 里存在 manifest.armature 指定的骨架节点 | `命中 True` | 存在 'RIG_Body_Male_Standard' | **PASS** |
| `A-11` | Body_Male_Standard | mesh 数 == manifest.parts 数 | `3 vs 3` | 相等 | **PASS** |
| `A-12` | Body_Male_Standard | 无相机 / 无灯 / 无动画 | `cameras=0 lights=0 animations=0` | 全 0 | **PASS** |
| `A-13` | Body_Male_Standard | 每个 primitive 都有 POSITION/JOINTS_0/WEIGHTS_0 | `问题 0 条` | 0 条 | **PASS** |
| `A-14` | Body_Male_Standard | 按件分档：有 morph 的 primitive targets==2；无 morph 的 primitive targets==0 | `targets==2 的 primitive 1 个；targets==0 的 2 个；异常 0 条` | 异常 0 条 | **PASS** |
| `A-15` | Body_Male_Standard | targetNames 顺序 == ['BS_Thin','BS_Heavy']（索引 0/1 硬契约） | `问题 0 条; 位置=['mesh']` | 0 条, 位置 ∈ {primitive,mesh} | **PASS** |
| `A-15b` | Body_Male_Standard | 每个 morph target 的 POSITION count == 同 primitive 的 POSITION count（morph 对齐硬条件） | `不符 0 条` | 0 条 | **PASS** |
| `A-15c` | Body_Male_Standard | 每个 primitive 的 2 个 target 都带 NORMAL（export_morph_normal=True 的体现） | `缺 NORMAL 的 target 0 个` | 0 个 | **PASS** |
| `A-15d` | Body_Male_Standard | 记录 morph target 的 sparse 使用情况（解析器必须支持 sparse 才能读到真位移） | `0 个 target 用 sparse；例 []` | 记录（非判据） | **PASS** |
| `A-16` | Body_Male_Standard | 每件**带 morph 的**网格默认 morph 权重全 0（无 morph 的网格不需要 weights） | `非零/缺失 0 件：[]` | 0 件 | **PASS** |
| `A-17` | Body_Male_Standard | manifest 每个 part 名能在 glb 里定位（node 名优先，退回 mesh 名） | `未命中 0 个` | 0 个 | **PASS** |
| `A-18` | Body_Male_Standard | 顶点数闭环：glb POSITION count ≥ Blender『被面引用顶点数』（= verts − 游离顶点）；且 glb/台账 比值 ∈ [0.9, 2.0] | `闭环违例 0 件；合计 glb=8485 / 台账=8483 比值=1.0002；逐件最大比值=1.0003（Body_Male）` | 0 件违例 且 0.9 ≤ 比值 ≤ 2.0 | **PASS** |
| `A-18b` | Body_Male_Standard | 三角数精确等于台账 faces（Blender 面全为三角时；否则 [faces, 2*faces] 已由 A-19 覆盖） | `精确相等 3/3 件` | 记录（非判据） | **PASS** |
| `A-19` | Body_Male_Standard | 三角数 ∈ [faces, 2*faces]（Blender 面数按三角化的口径差） | `越界 0 件` | 0 件 | **PASS** |
| `A-20` | Body_Male_Standard | 逐件材质名集合 == manifest.parts[].materials | `不符 0 件` | 0 件 | **PASS** |
| `A-21` | Body_Male_Standard | BS_Thin 位移非零（容差 1e-05 m = 0.01 mm；static_by_design 件按『极近零』判） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-22` | Body_Male_Standard | BS_Heavy 位移非零（同一容差） | `不合规 0 件：[]` | 0 件 | **PASS** |
| `A-23` | Body_Male_Standard | BS_Thin max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 1 件；最大 \|Δ\| = 0.0000 cm = 3.708e-08 m（Body_Male）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23h` | Body_Male_Standard | BS_Heavy max 位移 vs 上游台账同量级（|Δ| ≤ 0.05 cm，**模长**口径 → 对导出器 yup 旋转/拆点不变） | `比对 1 件；最大 \|Δ\| = 0.0000 cm = 1.543e-07 m（Body_Male）` | 全部 |Δ| ≤ 0.05 cm | **PASS** |
| `A-23d` | Body_Male_Standard | **第三实现**对账：Blender depsgraph 量的 max/mean 位移 vs glb 里的 max/mean 位移（不经任何台账） | `比对 1 件×2 档；max 差最大 = 4.694e-10 m（Body_Male/BS_Heavy）；mean 差最大 = 1.418e-06 m` | max 差 ≤ 1e-5 m（float32 级） | **PASS** |
| `A-23e` | Body_Male_Standard | mean 的**干净子集**对账：仅取 glb 顶点数 == Blender 顶点数的件（同一批顶点，均值的权重与 Blender 一致）→ mean Δ ≤ 1e-6 m | `干净 0 件：mean Δ 最大 = 0.000e+00 m；非干净 2 件：mean Δ 最大 = 1.418e-06 m（顶点复制因子 1.000–1.000）` | 干净子集 mean Δ ≤ 1e-6 m | **UNVERIFIED** |
| `A-24` | Body_Male_Standard | images 数 > 0 且 mimeType 合法 | `images=7 textures=7 declared=['image/png']` | >=1 张, mimeType ∈ {image/png,image/jpeg} | **PASS** |
| `A-25` | Body_Male_Standard | 抽查每张图真解出 PNG/JPEG 头且与声明一致 | `sniffed=['image/png', 'image/png', 'image/png', 'image/png', 'image/png', 'image/png']` | 全部 ∈ {image/png,image/jpeg} | **PASS** |
| `A-26` | Body_Male_Standard | 贴图链路完整：每个 texture 有合法 source；每个 material 的 baseColorTexture 索引可解析 | `textures 无 source 0 个；materials 有贴图 3/3（无贴图：无）` | textures 无 source == 0；materials 全部有 baseColorTexture | **PASS** |
### 组：manifest

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `D-12` | Body_Male_Standard | kind/sex/style 与上游台账一致 | `kind=body sex=Male style=Standard` | kind=body sex=Male style=Standard | **PASS** |
| `D-13` | Body_Male_Standard | label 前缀（body 必须『裸模 · 身形基准』） | `裸模 · 身形基准（男）` | 『裸模 · 身形基准』开头 | **PASS** |
| `D-14` | Body_Male_Standard | armature / bones 与上游台账一致 | `armature=RIG_Body_Male_Standard bones=65` | armature=RIG_Body_Male_Standard bones=65 | **PASS** |
| `D-15` | Body_Male_Standard | manifest.bones == glb skin.joints 数 | `65 vs 65` | 相等 | **PASS** |
| `D-16` | Body_Male_Standard | glb 相对路径可从仓库根解析且文件存在 | `解析为 D:\artstudio\tmp\shape-lab\glb\Body_Male_Standard.glb（存在=True）` | 存在 | **PASS** |
| `D-17` | Body_Male_Standard | glb_bytes == 真实字节数 | `manifest=13490444 实际=13490444` | 相等 | **PASS** |
| `D-18` | Body_Male_Standard | src_sha256 == 源 .blend 重算 sha256 | `b1a502a4396b5609 vs b1a502a4396b5609` | 逐位相同 | **PASS** |
| `D-19` | Body_Male_Standard | src_sha256 == bodyshape_manifest.blend_sha256（上游权威） | `b1a502a4396b5609 vs b1a502a4396b5609` | 逐位相同 | **PASS** |
| `D-20` | Body_Male_Standard | base_height_m 合理且与台账同源 | `manifest=1.81959 台帐=1.81959 (Δ=0.00000 m)` | 1.0–2.5 m 且与台账一致 | **PASS** |
| `D-20b` | Body_Male_Standard | base_height_m == 我独立量测的『所有网格世界 Z 并集高度』（**排除 Icosphere**） | `manifest=1.819587；我量(排除球)=1.819587 Δ=1.61e-07；若含球=2.810077 Δ=0.9905` | Δ ≤ 1e-3 m；且含球口径必须明显不符 | **PASS** |
| `D-21` | Body_Male_Standard | role 分类逐件重算一致（verifier 自己实现的 v1.1：head(Head_/^(Eyebrows|Eyes)$/_Eyebrows/_Eyes/Hair_)→skin(MI_Regular_/Body_)→foot(_Feet/Boots)→accessory(Acc_/_Belt/_Bracer/_Hood)→cloth） | `不符 0 件；分布={'skin': 1, 'head': 2}` | 0 件 | **PASS** |
| `D-21b` | Body_Male_Standard | role 分布 == v1.1 期望（head 18 / skin 5 / foot 4 / accessory 10 / cloth 9，共 46） | `本角色={'skin': 1, 'head': 2}（合计 3）` | 见全局口径（D-26 汇总 46 件） | **PASS** |
| `D-22` | Body_Male_Standard | parts[].has_morph / morph_names 与 glb 实际一致 | `不符 0 件` | 0 件 | **PASS** |
| `D-23` | Body_Male_Standard | glb 内自洽：BS_Thin POSITION target 字节数 == Σ(该 target 顶点数)×12 | `glb target 字节=174792，Σ顶点×12=174792（14566 个顶点位）` | 相等 | **PASS** |
### 组：ledger

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `B-01.Female_Ranger` | Female_Ranger | 缓存 manifest 逐件 verts/faces/materials == garment_manifest（12 件） | `不符 0 项，缺 0 件，多 0 件` | 0/0/0 | **PASS** |
| `B-01.Female_Peasant` | Female_Peasant | 缓存 manifest 逐件 verts/faces/materials == garment_manifest（8 件） | `不符 0 项，缺 0 件，多 0 件` | 0/0/0 | **PASS** |
| `B-01.Male_Ranger` | Male_Ranger | 缓存 manifest 逐件 verts/faces/materials == garment_manifest（12 件） | `不符 0 项，缺 0 件，多 0 件` | 0/0/0 | **PASS** |
| `B-01.Male_Peasant` | Male_Peasant | 缓存 manifest 逐件 verts/faces/materials == garment_manifest（8 件） | `不符 0 项，缺 0 件，多 0 件` | 0/0/0 | **PASS** |
| `B-02.Female` | Body_Female | 缓存 manifest 该标准体的 verts/faces == bodyshape_manifest | `verts=7376 faces=12812（台账 7376/12812）` | 7376/12812 | **PASS** |
| `B-02.Male` | Body_Male | 缓存 manifest 该标准体的 verts/faces == bodyshape_manifest | `verts=7281 faces=12566（台账 7281/12566）` | 7281/12566 | **PASS** |
| `B-03.Female.BS_Thin` | Body_Female | BS_Thin 的 max/mean 位移 == bodyshape_manifest.tiers[thin] | `max=0.033125/0.033125 m (Δ=4.97e-07 ≤ 1e-05)  mean=0.012853/0.012852 m (Δ=6.70e-07 ≤ 1e-04)` | max Δ≤1e-5 m；mean Δ≤1e-4 m | **PASS** |
| `B-03.Female.BS_Heavy` | Body_Female | BS_Heavy 的 max/mean 位移 == bodyshape_manifest.tiers[heavy] | `max=0.043476/0.043476 m (Δ=8.19e-08 ≤ 1e-05)  mean=0.016869/0.016868 m (Δ=1.13e-06 ≤ 1e-04)` | max Δ≤1e-5 m；mean Δ≤1e-4 m | **PASS** |
| `B-03.Male.BS_Thin` | Body_Male | BS_Thin 的 max/mean 位移 == bodyshape_manifest.tiers[thin] | `max=0.035718/0.035718 m (Δ=3.71e-08 ≤ 1e-05)  mean=0.015647/0.015646 m (Δ=9.82e-07 ≤ 1e-04)` | max Δ≤1e-5 m；mean Δ≤1e-4 m | **PASS** |
| `B-03.Male.BS_Heavy` | Body_Male | BS_Heavy 的 max/mean 位移 == bodyshape_manifest.tiers[heavy] | `max=0.046880/0.046880 m (Δ=1.54e-07 ≤ 1e-05)  mean=0.020537/0.020535 m (Δ=1.74e-06 ≤ 1e-04)` | max Δ≤1e-5 m；mean Δ≤1e-4 m | **PASS** |
| `B-04` | all | 4 套服装件数合计 == garment_manifest.summary.parts_total(40)；缓存 manifest 件数相符 | `上游合计=40；缓存 manifest 服装件数合计=40` | 40 / 40 | **PASS** |
### 组：manifest

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `D-26` | manifest.json | 全局 role 分布 == v1.1 期望 {'head': 18, 'skin': 5, 'foot': 4, 'accessory': 10, 'cloth': 9}（共 46 件） | `实测={'accessory': 10, 'skin': 5, 'cloth': 9, 'foot': 4, 'head': 18} 合计=46` | {'head': 18, 'skin': 5, 'foot': 4, 'accessory': 10, 'cloth': 9} 合计=46 | **PASS** |
| `D-27` | manifest.json | 两个独立实现（baker 出的 parts[].role vs verifier 的 classify_role）逐件一致 | `不符 0 件` | 0 件 | **PASS** |
### 组：pollution

| id | subject | 判据 | 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| `E-05.Female` | Icosphere@assets/3d/rig/bodies/Body_Female_Standard.blend | 被删对象的三条件独立复核（无材质 + 无顶点组/修改器 + z∈[-1,1] 的 1 m 球；另 42v/80f） | `vert=42 poly=80 mats=0 vg=0 mods=[] z=[-1.0000,1.0000] → 全部成立` | 三条件全成立 | **PASS** |
| `E-06.Female` | Body_Female_Standard | glb 里**确实没有** Icosphere（名字与 42v/80f 两个口径都查），且 glb 的节点名集合 == manifest.parts 名集合 | `glb 节点名=['Body_Female', 'Eyebrows', 'Eyes']；glb 网格名=['Body_Female_mesh', 'Eyebrows', 'Eyes']；名字含 icosphere=False；顶点数≤64 的网格=无；名集合相等=True` | 无 Icosphere、无 ≤64 顶点的小网格、glb 节点名集合 == manifest.parts | **PASS** |
| `E-05.Male` | Icosphere@assets/3d/rig/bodies/Body_Male_Standard.blend | 被删对象的三条件独立复核（无材质 + 无顶点组/修改器 + z∈[-1,1] 的 1 m 球；另 42v/80f） | `vert=42 poly=80 mats=0 vg=0 mods=[] z=[-1.0000,1.0000] → 全部成立` | 三条件全成立 | **PASS** |
| `E-06.Male` | Body_Male_Standard | glb 里**确实没有** Icosphere（名字与 42v/80f 两个口径都查），且 glb 的节点名集合 == manifest.parts 名集合 | `glb 节点名=['Body_Male', 'Eyebrows', 'Eyes']；glb 网格名=['Body_Male_mesh', 'Face', 'Face.001']；名字含 icosphere=False；顶点数≤64 的网格=无；名集合相等=True` | 无 Icosphere、无 ≤64 顶点的小网格、glb 节点名集合 == manifest.parts | **PASS** |
| `E-01` | tools/3d/godot/shape-lab | 工程目录内无 .png/.glb/.gltf/.blend/.pyc（零素材副本） | `命中 0 个` | 0 个 | **PASS** |
| `E-02` | assets/3d/rig/bodies | 源标准体 .blend 内容与上游台账 sha256 一致（未被烘焙流程改动） | `漂移 0 个` | 0 个 | **PASS** |
| `E-03` | assets/3d/rig/garments | 源服装 .blend 只读（无上游台账 sha 可对；记录当前 sha 与 mtime 供复核） | `4 套均存在` | 4 套存在 | **PASS** |

## 3. 会变红的条件（逐条 fail_condition）

- **`D-00`** 缓存目录里没有 manifest.json / JSON 坏了
- **`D-01`** schema != 'shape-lab-cache'（消费方按 schema 分派，写错就会用错解析器）
- **`D-02`** version != 1（契约 v1 冻结）
- **`D-03`** 任一必需字段缺失 → 消费方读到 None 后静默降级
- **`D-04`** morph_contract != ['BS_Thin','BS_Heavy']（顺序即索引，反了就是瘦壮互换）
- **`D-05`** k_range != [-1.0,1.0]
- **`D-06`** h_range != [0.92,1.08]
- **`D-07`** blender_version 空/非字符串（无法追溯烘焙环境）
- **`D-08`** generated_at 不可解析（下游无法判断缓存新旧）
- **`D-09`** 角色数 != 6（下拉会少项/多项）
- **`D-10`** 存在重复 id（下拉项互相覆盖）
- **`D-11`** 缺角色或多出未知角色（6 项 = 4 服装 + 2 标准体）
- **`D-11b`** 缺 role_rules / 版本不符 → 消费方无法判断该按 v1.0 还是 v1.1 解释 parts[].role（v1.0→v1.1 会改变若干件的分类，实测件数与清单见 D-26 的 evidence）
- **`A-01`** 前 4 字节不是 'glTF'（不是 GLB，或者被 zip/文本包了一层）
- **`A-02`** version != 2
- **`A-03`** length 字段与真实大小不符 → 文件被截断/拼接
- **`A-04`** chunk 链没有走到文件尾 → 有垃圾数据或 chunkLength 算错
- **`A-05`** JSON chunk 不唯一 / BIN chunk 多于 1 个 / 顺序错
- **`A-06`** 容器自洽性检查留下任何 error（见 errors 字段）
- **`A-07`** BIN chunk 长度与 buffer.byteLength 不匹配（超出 padding 范围）→ accessor 越界或截断
- **`A-08`** skin 数 != 1（0 = 没有蒙皮，多个 = 混了别的骨架/发型）
- **`A-09`** joints != 65 → 骨名/骨序与 65 骨契约不符（SPEC §3.1）
- **`A-10`** manifest.armature 的名字在 glb 节点里找不到 → 取骨会失败（F30 必须按名字取骨）
- **`A-11`** glb 网格数与 manifest 件数不符 → 逐件显隐/读数会错位
- **`A-12`** 导出带了相机/灯/动画（契约要求都没有；灯会让预览页亮度不可控）
- **`A-13`** 任一 primitive 缺蒙皮属性 → 引擎里该件不跟骨架动/不形变
- **`A-14`** 有 morph 件 targets != 2（缺档位）；或无 morph 件凭空多出 targets（引擎侧会多出无意义的 morph 通道）
- **`A-15`** 顺序反了 → 滑块 k 的瘦/壮互换（最典型的静默错误）；缺失 → 引擎拿不到名字只能按索引猜
- **`A-15b`** target 顶点数与基网格不等 → 引擎应用 morph 时越界/错位（这是 morph 唯一真正必须在 glTF 层保住的等式）
- **`A-15c`** 缺 morph 法线 → 形变后光照按原法线算，明暗会『静默不跟形变走』
- **`A-15d`** 本条不会红（纯记录）。它存在是为了证明：**若不支持 sparse，读到的是全零/异常** —— 实测 Blender 对 BS_Thin 会写 sparse，这是『morph 全零』型假 PASS 的天然伪装。
- **`A-16`** 源 .blend 落盘时 shape key 值是 1.0/1.0 → 导出没清零，加载即『又瘦又壮』拉满（TASK.md 点名过这个坑）
- **`A-17`** part 名对不上 glb 节点/网格名 → 逐件显隐与逐件读数必然错位（静默：控件在、控的不是那件）
- **`A-18`** glb 顶点数 < 被面引用顶点数 → 真的丢了被面使用的几何（不是游离顶点、也不是拆点）；比值越界同理。⚠ 精确相等**不是**可判据：① glTF 的 normal/UV 是 per-vertex、Blender 是 per-loop，导出必然拆点（Female_Ranger 实测 11/12 件 glb > 台账）；② 两具男模的 `Head_SuperHero_Male` 有 7 个游离顶点 + 6 条游离边，glTF 不导出游离顶点（应 glb < 台账）。两个方向都会发生。
- **`A-18b`** 本条不会红（记录用）。它证明拆点没有改变拓扑：拆点只复制顶点，不增删面。
- **`A-19`** 三角数 < faces（丢面/减面）或 > 2*faces（加了细分/应用了修改器）
- **`A-20`** 材质名/数量不符 → role 分类（skin 靠 MI_Regular_ 判）与贴图分配都会错
- **`A-21`** 该动的一件都不动 → 『空 morph 全绿』型假 PASS（SPEC F26）。容差必要性：实测 Eyebrows/Eyes 的『零』是 float32 噪声（BS_Thin 7.45e-9 m、BS_Heavy 1.21e-7 m），若把阈值设成 1e-9 会把噪声判成『真位移』而误红。
- **`A-22`** 同上（壮档）
- **`A-23`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23h`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23d`** 源 .blend 里量出的位移与 glb 里的位移不一致（> 0.01 mm）→ 导出改动了 morph 数据，而这是**不经台账**的闭环，任何『两边一起错』都骗不过它
- **`A-23e`** 干净子集里 mean 也偏 > 1e-6 m → 位移的**分布**（不只是极值）被改过。⚠ 为什么必须分子集：glTF 按 (pos,normal,uv) 拆点后同一数值会被多算几遍，mean 是逐顶点平均，**权重**因此变了（实测非干净件的 mean Δ 可达 5.9e-4 m）—— 那是复制因子造成的口径差，不是数值错误；把它算成 FAIL 就是假红。
- **`A-24`** 没有内嵌贴图 → 引擎加载后是纯白/纯灰（贴图内嵌是本任务契约）
- **`A-25`** 字节头与 mimeType 不符 / 解不出图 → 贴图是坏的但导入不报错（引擎里才静默变白）
- **`A-26`** texture 没 source → 用了它的材质在引擎里是纯色（贴图静默丢失）；material 没有 baseColorTexture 同理（本工程全部材质都应带贴图）
- **`D-12`** kind/sex/style 与台账不一致 → 下拉分组与标签会错
- **`D-13`** label 结构不符 / sex-style 与台账不一致 / Ranger 的 gloss 不是『游侠』（消费方直接显示这个串）
- **`D-14`** 骨架名或骨数不符 → 运行时取骨失败或骨序错
- **`D-15`** manifest 说 65 骨、glb 里不是 65 → 两边各自自洽但互相矛盾
- **`D-16`** 路径写错或文件没生成 → 消费方在 Windows 上会 goto 到别处（相对路径按仓库根解析是硬契约）
- **`D-17`** 字节数不符 → manifest 是旧一轮的残留（增量判断会跟着错）
- **`D-18`** sha 不符 → 缓存是旧 .blend 烘的（最典型的版本偏斜：改了源没重烘，一切看着都正常）
- **`D-20`** base_height_m 越界或与台账差 >1 cm → 1 m 标尺/取景会按错误高度算
- **`D-20b`** Δ > 1 mm → base_height_m 与 Blender 实量不符（1 m 标尺/取景会错）。判别力：若把 1 m 的 Icosphere（z∈[-1,1]）也算进去，身高会变成 ~2.77 m（Δ≈1 m），本条会立刻红 —— 故它同时是『Icosphere 确实被排除』的证据
- **`D-21`** role 判错 → 『清凉』预设会摘错件。v1.1 的三处修订都必须生效：① 标准体的 `Eyebrows`/`Eyes` 无 Head_ 前缀；② `Body_Female`/`Body_Male` 的材质是 MI_Superhero_* 不含 MI_Regular_；③ `Male_Ranger_Feet_Boots` 不以 _Feet 结尾
- **`D-21b`** 本条按角色记分布，全局对账见 D-26
- **`D-22`** manifest 自称有 morph 而 glb 没有（或反之）→ 面板显示与引擎实际相反
- **`D-23`** 字节数与张量顶点数不符 → accessor/bufferView 声明错位（读出来是错的数据仍不报错）
- **`D-24`** 本条不会红（纯记录）。garment_manifest.summary.morph_bytes_per_tier_total（4 套合计 1011708 = 84309×12）是 **Blender 侧**口径；glTF 顶点因按 (pos,normal,uv) 元组拆点而更多，两边不可直接比 —— 拿它当等式判据会假红。另：glb 里每个 target 同时含 POSITION+NORMAL（export_morph_normal=True），故 NORMAL 字节数=714936（≈ POSITION 的 1 倍额外开销）。
- **`A-01`** 前 4 字节不是 'glTF'（不是 GLB，或者被 zip/文本包了一层）
- **`A-02`** version != 2
- **`A-03`** length 字段与真实大小不符 → 文件被截断/拼接
- **`A-04`** chunk 链没有走到文件尾 → 有垃圾数据或 chunkLength 算错
- **`A-05`** JSON chunk 不唯一 / BIN chunk 多于 1 个 / 顺序错
- **`A-06`** 容器自洽性检查留下任何 error（见 errors 字段）
- **`A-07`** BIN chunk 长度与 buffer.byteLength 不匹配（超出 padding 范围）→ accessor 越界或截断
- **`A-08`** skin 数 != 1（0 = 没有蒙皮，多个 = 混了别的骨架/发型）
- **`A-09`** joints != 65 → 骨名/骨序与 65 骨契约不符（SPEC §3.1）
- **`A-10`** manifest.armature 的名字在 glb 节点里找不到 → 取骨会失败（F30 必须按名字取骨）
- **`A-11`** glb 网格数与 manifest 件数不符 → 逐件显隐/读数会错位
- **`A-12`** 导出带了相机/灯/动画（契约要求都没有；灯会让预览页亮度不可控）
- **`A-13`** 任一 primitive 缺蒙皮属性 → 引擎里该件不跟骨架动/不形变
- **`A-14`** 有 morph 件 targets != 2（缺档位）；或无 morph 件凭空多出 targets（引擎侧会多出无意义的 morph 通道）
- **`A-15`** 顺序反了 → 滑块 k 的瘦/壮互换（最典型的静默错误）；缺失 → 引擎拿不到名字只能按索引猜
- **`A-15b`** target 顶点数与基网格不等 → 引擎应用 morph 时越界/错位（这是 morph 唯一真正必须在 glTF 层保住的等式）
- **`A-15c`** 缺 morph 法线 → 形变后光照按原法线算，明暗会『静默不跟形变走』
- **`A-15d`** 本条不会红（纯记录）。它存在是为了证明：**若不支持 sparse，读到的是全零/异常** —— 实测 Blender 对 BS_Thin 会写 sparse，这是『morph 全零』型假 PASS 的天然伪装。
- **`A-16`** 源 .blend 落盘时 shape key 值是 1.0/1.0 → 导出没清零，加载即『又瘦又壮』拉满（TASK.md 点名过这个坑）
- **`A-17`** part 名对不上 glb 节点/网格名 → 逐件显隐与逐件读数必然错位（静默：控件在、控的不是那件）
- **`A-18`** glb 顶点数 < 被面引用顶点数 → 真的丢了被面使用的几何（不是游离顶点、也不是拆点）；比值越界同理。⚠ 精确相等**不是**可判据：① glTF 的 normal/UV 是 per-vertex、Blender 是 per-loop，导出必然拆点（Female_Ranger 实测 11/12 件 glb > 台账）；② 两具男模的 `Head_SuperHero_Male` 有 7 个游离顶点 + 6 条游离边，glTF 不导出游离顶点（应 glb < 台账）。两个方向都会发生。
- **`A-18b`** 本条不会红（记录用）。它证明拆点没有改变拓扑：拆点只复制顶点，不增删面。
- **`A-19`** 三角数 < faces（丢面/减面）或 > 2*faces（加了细分/应用了修改器）
- **`A-20`** 材质名/数量不符 → role 分类（skin 靠 MI_Regular_ 判）与贴图分配都会错
- **`A-21`** 该动的一件都不动 → 『空 morph 全绿』型假 PASS（SPEC F26）。容差必要性：实测 Eyebrows/Eyes 的『零』是 float32 噪声（BS_Thin 7.45e-9 m、BS_Heavy 1.21e-7 m），若把阈值设成 1e-9 会把噪声判成『真位移』而误红。
- **`A-22`** 同上（壮档）
- **`A-23`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23h`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23d`** 源 .blend 里量出的位移与 glb 里的位移不一致（> 0.01 mm）→ 导出改动了 morph 数据，而这是**不经台账**的闭环，任何『两边一起错』都骗不过它
- **`A-23e`** 干净子集里 mean 也偏 > 1e-6 m → 位移的**分布**（不只是极值）被改过。⚠ 为什么必须分子集：glTF 按 (pos,normal,uv) 拆点后同一数值会被多算几遍，mean 是逐顶点平均，**权重**因此变了（实测非干净件的 mean Δ 可达 5.9e-4 m）—— 那是复制因子造成的口径差，不是数值错误；把它算成 FAIL 就是假红。
- **`A-24`** 没有内嵌贴图 → 引擎加载后是纯白/纯灰（贴图内嵌是本任务契约）
- **`A-25`** 字节头与 mimeType 不符 / 解不出图 → 贴图是坏的但导入不报错（引擎里才静默变白）
- **`A-26`** texture 没 source → 用了它的材质在引擎里是纯色（贴图静默丢失）；material 没有 baseColorTexture 同理（本工程全部材质都应带贴图）
- **`D-12`** kind/sex/style 与台账不一致 → 下拉分组与标签会错
- **`D-13`** label 结构不符 / sex-style 与台账不一致 / Ranger 的 gloss 不是『游侠』（消费方直接显示这个串）
- **`D-14`** 骨架名或骨数不符 → 运行时取骨失败或骨序错
- **`D-15`** manifest 说 65 骨、glb 里不是 65 → 两边各自自洽但互相矛盾
- **`D-16`** 路径写错或文件没生成 → 消费方在 Windows 上会 goto 到别处（相对路径按仓库根解析是硬契约）
- **`D-17`** 字节数不符 → manifest 是旧一轮的残留（增量判断会跟着错）
- **`D-18`** sha 不符 → 缓存是旧 .blend 烘的（最典型的版本偏斜：改了源没重烘，一切看着都正常）
- **`D-20`** base_height_m 越界或与台账差 >1 cm → 1 m 标尺/取景会按错误高度算
- **`D-20b`** Δ > 1 mm → base_height_m 与 Blender 实量不符（1 m 标尺/取景会错）。判别力：若把 1 m 的 Icosphere（z∈[-1,1]）也算进去，身高会变成 ~2.77 m（Δ≈1 m），本条会立刻红 —— 故它同时是『Icosphere 确实被排除』的证据
- **`D-21`** role 判错 → 『清凉』预设会摘错件。v1.1 的三处修订都必须生效：① 标准体的 `Eyebrows`/`Eyes` 无 Head_ 前缀；② `Body_Female`/`Body_Male` 的材质是 MI_Superhero_* 不含 MI_Regular_；③ `Male_Ranger_Feet_Boots` 不以 _Feet 结尾
- **`D-21b`** 本条按角色记分布，全局对账见 D-26
- **`D-22`** manifest 自称有 morph 而 glb 没有（或反之）→ 面板显示与引擎实际相反
- **`D-23`** 字节数与张量顶点数不符 → accessor/bufferView 声明错位（读出来是错的数据仍不报错）
- **`D-24`** 本条不会红（纯记录）。garment_manifest.summary.morph_bytes_per_tier_total（4 套合计 1011708 = 84309×12）是 **Blender 侧**口径；glTF 顶点因按 (pos,normal,uv) 元组拆点而更多，两边不可直接比 —— 拿它当等式判据会假红。另：glb 里每个 target 同时含 POSITION+NORMAL（export_morph_normal=True），故 NORMAL 字节数=714768（≈ POSITION 的 1 倍额外开销）。
- **`A-01`** 前 4 字节不是 'glTF'（不是 GLB，或者被 zip/文本包了一层）
- **`A-02`** version != 2
- **`A-03`** length 字段与真实大小不符 → 文件被截断/拼接
- **`A-04`** chunk 链没有走到文件尾 → 有垃圾数据或 chunkLength 算错
- **`A-05`** JSON chunk 不唯一 / BIN chunk 多于 1 个 / 顺序错
- **`A-06`** 容器自洽性检查留下任何 error（见 errors 字段）
- **`A-07`** BIN chunk 长度与 buffer.byteLength 不匹配（超出 padding 范围）→ accessor 越界或截断
- **`A-08`** skin 数 != 1（0 = 没有蒙皮，多个 = 混了别的骨架/发型）
- **`A-09`** joints != 65 → 骨名/骨序与 65 骨契约不符（SPEC §3.1）
- **`A-10`** manifest.armature 的名字在 glb 节点里找不到 → 取骨会失败（F30 必须按名字取骨）
- **`A-11`** glb 网格数与 manifest 件数不符 → 逐件显隐/读数会错位
- **`A-12`** 导出带了相机/灯/动画（契约要求都没有；灯会让预览页亮度不可控）
- **`A-13`** 任一 primitive 缺蒙皮属性 → 引擎里该件不跟骨架动/不形变
- **`A-14`** 有 morph 件 targets != 2（缺档位）；或无 morph 件凭空多出 targets（引擎侧会多出无意义的 morph 通道）
- **`A-15`** 顺序反了 → 滑块 k 的瘦/壮互换（最典型的静默错误）；缺失 → 引擎拿不到名字只能按索引猜
- **`A-15b`** target 顶点数与基网格不等 → 引擎应用 morph 时越界/错位（这是 morph 唯一真正必须在 glTF 层保住的等式）
- **`A-15c`** 缺 morph 法线 → 形变后光照按原法线算，明暗会『静默不跟形变走』
- **`A-15d`** 本条不会红（纯记录）。它存在是为了证明：**若不支持 sparse，读到的是全零/异常** —— 实测 Blender 对 BS_Thin 会写 sparse，这是『morph 全零』型假 PASS 的天然伪装。
- **`A-16`** 源 .blend 落盘时 shape key 值是 1.0/1.0 → 导出没清零，加载即『又瘦又壮』拉满（TASK.md 点名过这个坑）
- **`A-17`** part 名对不上 glb 节点/网格名 → 逐件显隐与逐件读数必然错位（静默：控件在、控的不是那件）
- **`A-18`** glb 顶点数 < 被面引用顶点数 → 真的丢了被面使用的几何（不是游离顶点、也不是拆点）；比值越界同理。⚠ 精确相等**不是**可判据：① glTF 的 normal/UV 是 per-vertex、Blender 是 per-loop，导出必然拆点（Female_Ranger 实测 11/12 件 glb > 台账）；② 两具男模的 `Head_SuperHero_Male` 有 7 个游离顶点 + 6 条游离边，glTF 不导出游离顶点（应 glb < 台账）。两个方向都会发生。
- **`A-18b`** 本条不会红（记录用）。它证明拆点没有改变拓扑：拆点只复制顶点，不增删面。
- **`A-19`** 三角数 < faces（丢面/减面）或 > 2*faces（加了细分/应用了修改器）
- **`A-20`** 材质名/数量不符 → role 分类（skin 靠 MI_Regular_ 判）与贴图分配都会错
- **`A-21`** 该动的一件都不动 → 『空 morph 全绿』型假 PASS（SPEC F26）。容差必要性：实测 Eyebrows/Eyes 的『零』是 float32 噪声（BS_Thin 7.45e-9 m、BS_Heavy 1.21e-7 m），若把阈值设成 1e-9 会把噪声判成『真位移』而误红。
- **`A-22`** 同上（壮档）
- **`A-23`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23h`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23d`** 源 .blend 里量出的位移与 glb 里的位移不一致（> 0.01 mm）→ 导出改动了 morph 数据，而这是**不经台账**的闭环，任何『两边一起错』都骗不过它
- **`A-23e`** 干净子集里 mean 也偏 > 1e-6 m → 位移的**分布**（不只是极值）被改过。⚠ 为什么必须分子集：glTF 按 (pos,normal,uv) 拆点后同一数值会被多算几遍，mean 是逐顶点平均，**权重**因此变了（实测非干净件的 mean Δ 可达 5.9e-4 m）—— 那是复制因子造成的口径差，不是数值错误；把它算成 FAIL 就是假红。
- **`A-24`** 没有内嵌贴图 → 引擎加载后是纯白/纯灰（贴图内嵌是本任务契约）
- **`A-25`** 字节头与 mimeType 不符 / 解不出图 → 贴图是坏的但导入不报错（引擎里才静默变白）
- **`A-26`** texture 没 source → 用了它的材质在引擎里是纯色（贴图静默丢失）；material 没有 baseColorTexture 同理（本工程全部材质都应带贴图）
- **`D-12`** kind/sex/style 与台账不一致 → 下拉分组与标签会错
- **`D-13`** label 结构不符 / sex-style 与台账不一致 / Ranger 的 gloss 不是『游侠』（消费方直接显示这个串）
- **`D-14`** 骨架名或骨数不符 → 运行时取骨失败或骨序错
- **`D-15`** manifest 说 65 骨、glb 里不是 65 → 两边各自自洽但互相矛盾
- **`D-16`** 路径写错或文件没生成 → 消费方在 Windows 上会 goto 到别处（相对路径按仓库根解析是硬契约）
- **`D-17`** 字节数不符 → manifest 是旧一轮的残留（增量判断会跟着错）
- **`D-18`** sha 不符 → 缓存是旧 .blend 烘的（最典型的版本偏斜：改了源没重烘，一切看着都正常）
- **`D-20`** base_height_m 越界或与台账差 >1 cm → 1 m 标尺/取景会按错误高度算
- **`D-20b`** Δ > 1 mm → base_height_m 与 Blender 实量不符（1 m 标尺/取景会错）。判别力：若把 1 m 的 Icosphere（z∈[-1,1]）也算进去，身高会变成 ~2.77 m（Δ≈1 m），本条会立刻红 —— 故它同时是『Icosphere 确实被排除』的证据
- **`D-21`** role 判错 → 『清凉』预设会摘错件。v1.1 的三处修订都必须生效：① 标准体的 `Eyebrows`/`Eyes` 无 Head_ 前缀；② `Body_Female`/`Body_Male` 的材质是 MI_Superhero_* 不含 MI_Regular_；③ `Male_Ranger_Feet_Boots` 不以 _Feet 结尾
- **`D-21b`** 本条按角色记分布，全局对账见 D-26
- **`D-22`** manifest 自称有 morph 而 glb 没有（或反之）→ 面板显示与引擎实际相反
- **`D-23`** 字节数与张量顶点数不符 → accessor/bufferView 声明错位（读出来是错的数据仍不报错）
- **`D-24`** 本条不会红（纯记录）。garment_manifest.summary.morph_bytes_per_tier_total（4 套合计 1011708 = 84309×12）是 **Blender 侧**口径；glTF 顶点因按 (pos,normal,uv) 元组拆点而更多，两边不可直接比 —— 拿它当等式判据会假红。另：glb 里每个 target 同时含 POSITION+NORMAL（export_morph_normal=True），故 NORMAL 字节数=402912（≈ POSITION 的 1 倍额外开销）。
- **`A-01`** 前 4 字节不是 'glTF'（不是 GLB，或者被 zip/文本包了一层）
- **`A-02`** version != 2
- **`A-03`** length 字段与真实大小不符 → 文件被截断/拼接
- **`A-04`** chunk 链没有走到文件尾 → 有垃圾数据或 chunkLength 算错
- **`A-05`** JSON chunk 不唯一 / BIN chunk 多于 1 个 / 顺序错
- **`A-06`** 容器自洽性检查留下任何 error（见 errors 字段）
- **`A-07`** BIN chunk 长度与 buffer.byteLength 不匹配（超出 padding 范围）→ accessor 越界或截断
- **`A-08`** skin 数 != 1（0 = 没有蒙皮，多个 = 混了别的骨架/发型）
- **`A-09`** joints != 65 → 骨名/骨序与 65 骨契约不符（SPEC §3.1）
- **`A-10`** manifest.armature 的名字在 glb 节点里找不到 → 取骨会失败（F30 必须按名字取骨）
- **`A-11`** glb 网格数与 manifest 件数不符 → 逐件显隐/读数会错位
- **`A-12`** 导出带了相机/灯/动画（契约要求都没有；灯会让预览页亮度不可控）
- **`A-13`** 任一 primitive 缺蒙皮属性 → 引擎里该件不跟骨架动/不形变
- **`A-14`** 有 morph 件 targets != 2（缺档位）；或无 morph 件凭空多出 targets（引擎侧会多出无意义的 morph 通道）
- **`A-15`** 顺序反了 → 滑块 k 的瘦/壮互换（最典型的静默错误）；缺失 → 引擎拿不到名字只能按索引猜
- **`A-15b`** target 顶点数与基网格不等 → 引擎应用 morph 时越界/错位（这是 morph 唯一真正必须在 glTF 层保住的等式）
- **`A-15c`** 缺 morph 法线 → 形变后光照按原法线算，明暗会『静默不跟形变走』
- **`A-15d`** 本条不会红（纯记录）。它存在是为了证明：**若不支持 sparse，读到的是全零/异常** —— 实测 Blender 对 BS_Thin 会写 sparse，这是『morph 全零』型假 PASS 的天然伪装。
- **`A-16`** 源 .blend 落盘时 shape key 值是 1.0/1.0 → 导出没清零，加载即『又瘦又壮』拉满（TASK.md 点名过这个坑）
- **`A-17`** part 名对不上 glb 节点/网格名 → 逐件显隐与逐件读数必然错位（静默：控件在、控的不是那件）
- **`A-18`** glb 顶点数 < 被面引用顶点数 → 真的丢了被面使用的几何（不是游离顶点、也不是拆点）；比值越界同理。⚠ 精确相等**不是**可判据：① glTF 的 normal/UV 是 per-vertex、Blender 是 per-loop，导出必然拆点（Female_Ranger 实测 11/12 件 glb > 台账）；② 两具男模的 `Head_SuperHero_Male` 有 7 个游离顶点 + 6 条游离边，glTF 不导出游离顶点（应 glb < 台账）。两个方向都会发生。
- **`A-18b`** 本条不会红（记录用）。它证明拆点没有改变拓扑：拆点只复制顶点，不增删面。
- **`A-19`** 三角数 < faces（丢面/减面）或 > 2*faces（加了细分/应用了修改器）
- **`A-20`** 材质名/数量不符 → role 分类（skin 靠 MI_Regular_ 判）与贴图分配都会错
- **`A-21`** 该动的一件都不动 → 『空 morph 全绿』型假 PASS（SPEC F26）。容差必要性：实测 Eyebrows/Eyes 的『零』是 float32 噪声（BS_Thin 7.45e-9 m、BS_Heavy 1.21e-7 m），若把阈值设成 1e-9 会把噪声判成『真位移』而误红。
- **`A-22`** 同上（壮档）
- **`A-23`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23h`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23d`** 源 .blend 里量出的位移与 glb 里的位移不一致（> 0.01 mm）→ 导出改动了 morph 数据，而这是**不经台账**的闭环，任何『两边一起错』都骗不过它
- **`A-23e`** 干净子集里 mean 也偏 > 1e-6 m → 位移的**分布**（不只是极值）被改过。⚠ 为什么必须分子集：glTF 按 (pos,normal,uv) 拆点后同一数值会被多算几遍，mean 是逐顶点平均，**权重**因此变了（实测非干净件的 mean Δ 可达 5.9e-4 m）—— 那是复制因子造成的口径差，不是数值错误；把它算成 FAIL 就是假红。
- **`A-24`** 没有内嵌贴图 → 引擎加载后是纯白/纯灰（贴图内嵌是本任务契约）
- **`A-25`** 字节头与 mimeType 不符 / 解不出图 → 贴图是坏的但导入不报错（引擎里才静默变白）
- **`A-26`** texture 没 source → 用了它的材质在引擎里是纯色（贴图静默丢失）；material 没有 baseColorTexture 同理（本工程全部材质都应带贴图）
- **`D-12`** kind/sex/style 与台账不一致 → 下拉分组与标签会错
- **`D-13`** label 结构不符 / sex-style 与台账不一致 / Ranger 的 gloss 不是『游侠』（消费方直接显示这个串）
- **`D-14`** 骨架名或骨数不符 → 运行时取骨失败或骨序错
- **`D-15`** manifest 说 65 骨、glb 里不是 65 → 两边各自自洽但互相矛盾
- **`D-16`** 路径写错或文件没生成 → 消费方在 Windows 上会 goto 到别处（相对路径按仓库根解析是硬契约）
- **`D-17`** 字节数不符 → manifest 是旧一轮的残留（增量判断会跟着错）
- **`D-18`** sha 不符 → 缓存是旧 .blend 烘的（最典型的版本偏斜：改了源没重烘，一切看着都正常）
- **`D-20`** base_height_m 越界或与台账差 >1 cm → 1 m 标尺/取景会按错误高度算
- **`D-20b`** Δ > 1 mm → base_height_m 与 Blender 实量不符（1 m 标尺/取景会错）。判别力：若把 1 m 的 Icosphere（z∈[-1,1]）也算进去，身高会变成 ~2.77 m（Δ≈1 m），本条会立刻红 —— 故它同时是『Icosphere 确实被排除』的证据
- **`D-21`** role 判错 → 『清凉』预设会摘错件。v1.1 的三处修订都必须生效：① 标准体的 `Eyebrows`/`Eyes` 无 Head_ 前缀；② `Body_Female`/`Body_Male` 的材质是 MI_Superhero_* 不含 MI_Regular_；③ `Male_Ranger_Feet_Boots` 不以 _Feet 结尾
- **`D-21b`** 本条按角色记分布，全局对账见 D-26
- **`D-22`** manifest 自称有 morph 而 glb 没有（或反之）→ 面板显示与引擎实际相反
- **`D-23`** 字节数与张量顶点数不符 → accessor/bufferView 声明错位（读出来是错的数据仍不报错）
- **`D-24`** 本条不会红（纯记录）。garment_manifest.summary.morph_bytes_per_tier_total（4 套合计 1011708 = 84309×12）是 **Blender 侧**口径；glTF 顶点因按 (pos,normal,uv) 元组拆点而更多，两边不可直接比 —— 拿它当等式判据会假红。另：glb 里每个 target 同时含 POSITION+NORMAL（export_morph_normal=True），故 NORMAL 字节数=297312（≈ POSITION 的 1 倍额外开销）。
- **`A-01`** 前 4 字节不是 'glTF'（不是 GLB，或者被 zip/文本包了一层）
- **`A-02`** version != 2
- **`A-03`** length 字段与真实大小不符 → 文件被截断/拼接
- **`A-04`** chunk 链没有走到文件尾 → 有垃圾数据或 chunkLength 算错
- **`A-05`** JSON chunk 不唯一 / BIN chunk 多于 1 个 / 顺序错
- **`A-06`** 容器自洽性检查留下任何 error（见 errors 字段）
- **`A-07`** BIN chunk 长度与 buffer.byteLength 不匹配（超出 padding 范围）→ accessor 越界或截断
- **`A-08`** skin 数 != 1（0 = 没有蒙皮，多个 = 混了别的骨架/发型）
- **`A-09`** joints != 65 → 骨名/骨序与 65 骨契约不符（SPEC §3.1）
- **`A-10`** manifest.armature 的名字在 glb 节点里找不到 → 取骨会失败（F30 必须按名字取骨）
- **`A-11`** glb 网格数与 manifest 件数不符 → 逐件显隐/读数会错位
- **`A-12`** 导出带了相机/灯/动画（契约要求都没有；灯会让预览页亮度不可控）
- **`A-13`** 任一 primitive 缺蒙皮属性 → 引擎里该件不跟骨架动/不形变
- **`A-14`** 有 morph 件 targets != 2（缺档位）；或无 morph 件凭空多出 targets（引擎侧会多出无意义的 morph 通道）
- **`A-15`** 顺序反了 → 滑块 k 的瘦/壮互换（最典型的静默错误）；缺失 → 引擎拿不到名字只能按索引猜
- **`A-15b`** target 顶点数与基网格不等 → 引擎应用 morph 时越界/错位（这是 morph 唯一真正必须在 glTF 层保住的等式）
- **`A-15c`** 缺 morph 法线 → 形变后光照按原法线算，明暗会『静默不跟形变走』
- **`A-15d`** 本条不会红（纯记录）。它存在是为了证明：**若不支持 sparse，读到的是全零/异常** —— 实测 Blender 对 BS_Thin 会写 sparse，这是『morph 全零』型假 PASS 的天然伪装。
- **`A-16`** 源 .blend 落盘时 shape key 值是 1.0/1.0 → 导出没清零，加载即『又瘦又壮』拉满（TASK.md 点名过这个坑）
- **`A-17`** part 名对不上 glb 节点/网格名 → 逐件显隐与逐件读数必然错位（静默：控件在、控的不是那件）
- **`A-18`** glb 顶点数 < 被面引用顶点数 → 真的丢了被面使用的几何（不是游离顶点、也不是拆点）；比值越界同理。⚠ 精确相等**不是**可判据：① glTF 的 normal/UV 是 per-vertex、Blender 是 per-loop，导出必然拆点（Female_Ranger 实测 11/12 件 glb > 台账）；② 两具男模的 `Head_SuperHero_Male` 有 7 个游离顶点 + 6 条游离边，glTF 不导出游离顶点（应 glb < 台账）。两个方向都会发生。
- **`A-18b`** 本条不会红（记录用）。它证明拆点没有改变拓扑：拆点只复制顶点，不增删面。
- **`A-19`** 三角数 < faces（丢面/减面）或 > 2*faces（加了细分/应用了修改器）
- **`A-20`** 材质名/数量不符 → role 分类（skin 靠 MI_Regular_ 判）与贴图分配都会错
- **`A-21`** 该动的一件都不动 → 『空 morph 全绿』型假 PASS（SPEC F26）。容差必要性：实测 Eyebrows/Eyes 的『零』是 float32 噪声（BS_Thin 7.45e-9 m、BS_Heavy 1.21e-7 m），若把阈值设成 1e-9 会把噪声判成『真位移』而误红。
- **`A-22`** 同上（壮档）
- **`A-23`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23h`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23d`** 源 .blend 里量出的位移与 glb 里的位移不一致（> 0.01 mm）→ 导出改动了 morph 数据，而这是**不经台账**的闭环，任何『两边一起错』都骗不过它
- **`A-23e`** 干净子集里 mean 也偏 > 1e-6 m → 位移的**分布**（不只是极值）被改过。⚠ 为什么必须分子集：glTF 按 (pos,normal,uv) 拆点后同一数值会被多算几遍，mean 是逐顶点平均，**权重**因此变了（实测非干净件的 mean Δ 可达 5.9e-4 m）—— 那是复制因子造成的口径差，不是数值错误；把它算成 FAIL 就是假红。
- **`A-24`** 没有内嵌贴图 → 引擎加载后是纯白/纯灰（贴图内嵌是本任务契约）
- **`A-25`** 字节头与 mimeType 不符 / 解不出图 → 贴图是坏的但导入不报错（引擎里才静默变白）
- **`A-26`** texture 没 source → 用了它的材质在引擎里是纯色（贴图静默丢失）；material 没有 baseColorTexture 同理（本工程全部材质都应带贴图）
- **`D-12`** kind/sex/style 与台账不一致 → 下拉分组与标签会错
- **`D-13`** 标签前缀不符 → 用户看到的『身形基准』语义丢失
- **`D-14`** 骨架名或骨数不符 → 运行时取骨失败或骨序错
- **`D-15`** manifest 说 65 骨、glb 里不是 65 → 两边各自自洽但互相矛盾
- **`D-16`** 路径写错或文件没生成 → 消费方在 Windows 上会 goto 到别处（相对路径按仓库根解析是硬契约）
- **`D-17`** 字节数不符 → manifest 是旧一轮的残留（增量判断会跟着错）
- **`D-18`** sha 不符 → 缓存是旧 .blend 烘的（最典型的版本偏斜：改了源没重烘，一切看着都正常）
- **`D-19`** 与上游台账的 .blend sha 不符 → 与 SPEC F32 的『几何闭环』断链
- **`D-20`** base_height_m 越界或与台账差 >1 cm → 1 m 标尺/取景会按错误高度算
- **`D-20b`** Δ > 1 mm → base_height_m 与 Blender 实量不符（1 m 标尺/取景会错）。判别力：若把 1 m 的 Icosphere（z∈[-1,1]）也算进去，身高会变成 ~2.77 m（Δ≈1 m），本条会立刻红 —— 故它同时是『Icosphere 确实被排除』的证据
- **`D-21`** role 判错 → 『清凉』预设会摘错件。v1.1 的三处修订都必须生效：① 标准体的 `Eyebrows`/`Eyes` 无 Head_ 前缀；② `Body_Female`/`Body_Male` 的材质是 MI_Superhero_* 不含 MI_Regular_；③ `Male_Ranger_Feet_Boots` 不以 _Feet 结尾
- **`D-21b`** 本条按角色记分布，全局对账见 D-26
- **`D-22`** manifest 自称有 morph 而 glb 没有（或反之）→ 面板显示与引擎实际相反
- **`D-23`** 字节数与张量顶点数不符 → accessor/bufferView 声明错位（读出来是错的数据仍不报错）
- **`A-01`** 前 4 字节不是 'glTF'（不是 GLB，或者被 zip/文本包了一层）
- **`A-02`** version != 2
- **`A-03`** length 字段与真实大小不符 → 文件被截断/拼接
- **`A-04`** chunk 链没有走到文件尾 → 有垃圾数据或 chunkLength 算错
- **`A-05`** JSON chunk 不唯一 / BIN chunk 多于 1 个 / 顺序错
- **`A-06`** 容器自洽性检查留下任何 error（见 errors 字段）
- **`A-07`** BIN chunk 长度与 buffer.byteLength 不匹配（超出 padding 范围）→ accessor 越界或截断
- **`A-08`** skin 数 != 1（0 = 没有蒙皮，多个 = 混了别的骨架/发型）
- **`A-09`** joints != 65 → 骨名/骨序与 65 骨契约不符（SPEC §3.1）
- **`A-10`** manifest.armature 的名字在 glb 节点里找不到 → 取骨会失败（F30 必须按名字取骨）
- **`A-11`** glb 网格数与 manifest 件数不符 → 逐件显隐/读数会错位
- **`A-12`** 导出带了相机/灯/动画（契约要求都没有；灯会让预览页亮度不可控）
- **`A-13`** 任一 primitive 缺蒙皮属性 → 引擎里该件不跟骨架动/不形变
- **`A-14`** 有 morph 件 targets != 2（缺档位）；或无 morph 件凭空多出 targets（引擎侧会多出无意义的 morph 通道）
- **`A-15`** 顺序反了 → 滑块 k 的瘦/壮互换（最典型的静默错误）；缺失 → 引擎拿不到名字只能按索引猜
- **`A-15b`** target 顶点数与基网格不等 → 引擎应用 morph 时越界/错位（这是 morph 唯一真正必须在 glTF 层保住的等式）
- **`A-15c`** 缺 morph 法线 → 形变后光照按原法线算，明暗会『静默不跟形变走』
- **`A-15d`** 本条不会红（纯记录）。它存在是为了证明：**若不支持 sparse，读到的是全零/异常** —— 实测 Blender 对 BS_Thin 会写 sparse，这是『morph 全零』型假 PASS 的天然伪装。
- **`A-16`** 源 .blend 落盘时 shape key 值是 1.0/1.0 → 导出没清零，加载即『又瘦又壮』拉满（TASK.md 点名过这个坑）
- **`A-17`** part 名对不上 glb 节点/网格名 → 逐件显隐与逐件读数必然错位（静默：控件在、控的不是那件）
- **`A-18`** glb 顶点数 < 被面引用顶点数 → 真的丢了被面使用的几何（不是游离顶点、也不是拆点）；比值越界同理。⚠ 精确相等**不是**可判据：① glTF 的 normal/UV 是 per-vertex、Blender 是 per-loop，导出必然拆点（Female_Ranger 实测 11/12 件 glb > 台账）；② 两具男模的 `Head_SuperHero_Male` 有 7 个游离顶点 + 6 条游离边，glTF 不导出游离顶点（应 glb < 台账）。两个方向都会发生。
- **`A-18b`** 本条不会红（记录用）。它证明拆点没有改变拓扑：拆点只复制顶点，不增删面。
- **`A-19`** 三角数 < faces（丢面/减面）或 > 2*faces（加了细分/应用了修改器）
- **`A-20`** 材质名/数量不符 → role 分类（skin 靠 MI_Regular_ 判）与贴图分配都会错
- **`A-21`** 该动的一件都不动 → 『空 morph 全绿』型假 PASS（SPEC F26）。容差必要性：实测 Eyebrows/Eyes 的『零』是 float32 噪声（BS_Thin 7.45e-9 m、BS_Heavy 1.21e-7 m），若把阈值设成 1e-9 会把噪声判成『真位移』而误红。
- **`A-22`** 同上（壮档）
- **`A-23`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23h`** 位移与上游台账差 > 0.05 cm → 要么台账变了没重烘（版本偏斜，SPEC F32），要么导出改了几何。⚠ 这是**唯一**能抓住『名字/顺序/顶点数全对、但位移数值错』的判据（见破坏性复现 swap_deltas / half_deltas：只改数值，A-15/A-16/A-18 全绿，只有本条红）
- **`A-23d`** 源 .blend 里量出的位移与 glb 里的位移不一致（> 0.01 mm）→ 导出改动了 morph 数据，而这是**不经台账**的闭环，任何『两边一起错』都骗不过它
- **`A-23e`** 干净子集里 mean 也偏 > 1e-6 m → 位移的**分布**（不只是极值）被改过。⚠ 为什么必须分子集：glTF 按 (pos,normal,uv) 拆点后同一数值会被多算几遍，mean 是逐顶点平均，**权重**因此变了（实测非干净件的 mean Δ 可达 5.9e-4 m）—— 那是复制因子造成的口径差，不是数值错误；把它算成 FAIL 就是假红。
- **`A-24`** 没有内嵌贴图 → 引擎加载后是纯白/纯灰（贴图内嵌是本任务契约）
- **`A-25`** 字节头与 mimeType 不符 / 解不出图 → 贴图是坏的但导入不报错（引擎里才静默变白）
- **`A-26`** texture 没 source → 用了它的材质在引擎里是纯色（贴图静默丢失）；material 没有 baseColorTexture 同理（本工程全部材质都应带贴图）
- **`D-12`** kind/sex/style 与台账不一致 → 下拉分组与标签会错
- **`D-13`** 标签前缀不符 → 用户看到的『身形基准』语义丢失
- **`D-14`** 骨架名或骨数不符 → 运行时取骨失败或骨序错
- **`D-15`** manifest 说 65 骨、glb 里不是 65 → 两边各自自洽但互相矛盾
- **`D-16`** 路径写错或文件没生成 → 消费方在 Windows 上会 goto 到别处（相对路径按仓库根解析是硬契约）
- **`D-17`** 字节数不符 → manifest 是旧一轮的残留（增量判断会跟着错）
- **`D-18`** sha 不符 → 缓存是旧 .blend 烘的（最典型的版本偏斜：改了源没重烘，一切看着都正常）
- **`D-19`** 与上游台账的 .blend sha 不符 → 与 SPEC F32 的『几何闭环』断链
- **`D-20`** base_height_m 越界或与台账差 >1 cm → 1 m 标尺/取景会按错误高度算
- **`D-20b`** Δ > 1 mm → base_height_m 与 Blender 实量不符（1 m 标尺/取景会错）。判别力：若把 1 m 的 Icosphere（z∈[-1,1]）也算进去，身高会变成 ~2.77 m（Δ≈1 m），本条会立刻红 —— 故它同时是『Icosphere 确实被排除』的证据
- **`D-21`** role 判错 → 『清凉』预设会摘错件。v1.1 的三处修订都必须生效：① 标准体的 `Eyebrows`/`Eyes` 无 Head_ 前缀；② `Body_Female`/`Body_Male` 的材质是 MI_Superhero_* 不含 MI_Regular_；③ `Male_Ranger_Feet_Boots` 不以 _Feet 结尾
- **`D-21b`** 本条按角色记分布，全局对账见 D-26
- **`D-22`** manifest 自称有 morph 而 glb 没有（或反之）→ 面板显示与引擎实际相反
- **`D-23`** 字节数与张量顶点数不符 → accessor/bufferView 声明错位（读出来是错的数据仍不报错）
- **`B-01.Female_Ranger`** 缓存台账与上游台账不一致 → 烘焙漏件/多件、或拿旧版台账生成（自洽≠正确，SPEC F32）
- **`B-01.Female_Peasant`** 缓存台账与上游台账不一致 → 烘焙漏件/多件、或拿旧版台账生成（自洽≠正确，SPEC F32）
- **`B-01.Male_Ranger`** 缓存台账与上游台账不一致 → 烘焙漏件/多件、或拿旧版台账生成（自洽≠正确，SPEC F32）
- **`B-01.Male_Peasant`** 缓存台账与上游台账不一致 → 烘焙漏件/多件、或拿旧版台账生成（自洽≠正确，SPEC F32）
- **`B-02.Female`** 标准体顶点/面数与台账不符 → 裸模基准不可信
- **`B-02.Male`** 标准体顶点/面数与台账不符 → 裸模基准不可信
- **`B-03.Female.BS_Thin`** 均值/最大值与台账不符 → morph 位移表被改过或读错。只比 max 会漏掉『大部分顶点位移错但极值对』这类；mean 因此单独判（口径差见 measured）
- **`B-03.Female.BS_Heavy`** 均值/最大值与台账不符 → morph 位移表被改过或读错。只比 max 会漏掉『大部分顶点位移错但极值对』这类；mean 因此单独判（口径差见 measured）
- **`B-03.Male.BS_Thin`** 均值/最大值与台账不符 → morph 位移表被改过或读错。只比 max 会漏掉『大部分顶点位移错但极值对』这类；mean 因此单独判（口径差见 measured）
- **`B-03.Male.BS_Heavy`** 均值/最大值与台账不符 → morph 位移表被改过或读错。只比 max 会漏掉『大部分顶点位移错但极值对』这类；mean 因此单独判（口径差见 measured）
- **`B-04`** 件数对不上 → 某一套漏件/串套
- **`D-26`** 分布不符 → 有件被分错档（『清凉』预设按 role==accessory 摘件，分错就会摘错或漏摘）
- **`D-27`** 不一致 → 至少一方实现错（这正是『两个独立实现必须一致』的对照点）
- **`E-05.Female`** 三条件不成立 → 那不是『垃圾球』而是有用途的几何，删它就删错了
- **`E-06.Female`** glb 里出现球/多余小网格 → 垃圾几何没被剔干净（会占据场景、破坏取景 AABB）；节点名集合与 manifest.parts 不等 → 逐件显隐会错位
- **`E-05.Male`** 三条件不成立 → 那不是『垃圾球』而是有用途的几何，删它就删错了
- **`E-06.Male`** glb 里出现球/多余小网格 → 垃圾几何没被剔干净（会占据场景、破坏取景 AABB）；节点名集合与 manifest.parts 不等 → 逐件显隐会错位
- **`E-01`** 工程里出现素材副本 → 『零拷贝』这句话变假（且会被 git 提交）
- **`E-02`** 源 .blend 被写坏 → 后续所有烘焙都建立在坏源上
- **`E-03`** 源服装文件缺失

## 4. 破坏性复现（证明断言真的有判别力）

做法：把真 glb 复制到 `tmp/shape-lab-verify/mutants/`，**只改副本**，用同一套判据重跑。

| mutant | 改坏了什么 | 期望红的判据 | 实际红的判据 | 命中 |
|---|---|---|---|---|
| `swap_targetnames` | targetNames 顺序反了 → 瘦/壮互换（最典型的静默错） | `A-15` | `MUT-swap_targetnames-A-14`, `MUT-swap_targetnames-A-15` | ✅ |
| `wrong_targetnames` | targetNames 改名 → 引擎只能按索引猜 | `A-15` | `MUT-wrong_targetnames-A-14`, `MUT-wrong_targetnames-A-15` | ✅ |
| `default_weights` | 默认权重写 1/1 → 加载即又瘦又壮拉满 | `A-16` | `MUT-default_weights-A-16` | ✅ |
| `no_skin` | 删掉 skins → 没有蒙皮 | `A-08` | `MUT-no_skin-A-08`, `MUT-no_skin-A-09` | ✅ |
| `zero_thin_deltas` | 把 BS_Thin 位移清零 → 『空 morph 全绿』型假 PASS | `A-21` | `MUT-zero_thin_deltas-A-21`, `MUT-zero_thin_deltas-A-23`, `MUT-zero_thin_deltas-A-23d`, `MUT-zero_thin_deltas-A-23e` | ✅ |
| `pos_count` | POSITION count +1 而 target 不同步 → morph 对齐等式被破（这是抓它的判据） | `A-15b` | `MUT-pos_count-A-15b` | ✅ |
| `tri_count` | 索引数砍半 → 面数与台账不符 | `A-19` | `MUT-tri_count-A-19` | ✅ |
| `joints_60` | skin.joints 砍到 60 → 骨数与 65 骨契约不符 | `A-09` | `MUT-joints_60-A-09` | ✅ |
| `swap_deltas` | 两个 target 的位移向量整段对调（名字/索引全对，只有数值反）→ 只有『与台账比数值』抓得住 | `A-23` | `MUT-swap_deltas-A-23`, `MUT-swap_deltas-A-23h`, `MUT-swap_deltas-A-23d` | ✅ |
| `half_deltas` | BS_Thin 位移 ×0.5（仍非零、仍单调）→ 只有量级判据抓得住 | `A-23` | `MUT-half_deltas-A-23`, `MUT-half_deltas-A-23d` | ✅ |
| `extra_trailing` | 文件尾多 4 字节 → header.length 与 chunk 平铺都对不上 | `A-03` | `MUT-extra_trailing-A-03`, `MUT-extra_trailing-A-04`, `MUT-extra_trailing-A-06` | ✅ |

**11/11 个 mutant 命中了预期的判据**。

## 5. 诚实声明与口径差异

- garment_manifest 不含 .blend 级 sha256（只有 bodyshape_manifest 有）→ Female_Ranger 的 D-18 只能证明『manifest ↔ 当前磁盘 .blend 一致』，不能证明『与上游台账登记的那一版一致』。这是上游台账的缺口，不是烘焙器的错。
- garment_manifest 不含 .blend 级 sha256（只有 bodyshape_manifest 有）→ Male_Ranger 的 D-18 只能证明『manifest ↔ 当前磁盘 .blend 一致』，不能证明『与上游台账登记的那一版一致』。这是上游台账的缺口，不是烘焙器的错。
- garment_manifest 不含 .blend 级 sha256（只有 bodyshape_manifest 有）→ Female_Peasant 的 D-18 只能证明『manifest ↔ 当前磁盘 .blend 一致』，不能证明『与上游台账登记的那一版一致』。这是上游台账的缺口，不是烘焙器的错。
- garment_manifest 不含 .blend 级 sha256（只有 bodyshape_manifest 有）→ Male_Peasant 的 D-18 只能证明『manifest ↔ 当前磁盘 .blend 一致』，不能证明『与上游台账登记的那一版一致』。这是上游台账的缺口，不是烘焙器的错。
- **口径修正 1（原卡措辞会假 FAIL）**：原卡写『每个 primitive 的 extras.targetNames』。实测 Blender 5.2 把 targetNames 写在 **mesh.extras**，primitive 的 extras 不存在 → 按字面实现会全件 FAIL。本判据两种位置都接受并记录实际位置（全部 6 个 glb 都是 mesh 级）。
- **口径修正 2（原卡措辞会假 FAIL）**：原卡写『每个 primitive targets 数 == 2』。但两具标准体的 `Eyebrows`/`Eyes` 在源 .blend 里**没有 shape key**（我自跑 Blender 审计确认），glTF 里正确地没有 targets → 按字面实现会 4 个断言全红。已改为**按件分档**判据（A-14）。
- **口径修正 3（原卡措辞会假 FAIL）**：原卡写『POSITION count == manifest.parts[].verts』。两个方向都会不相等：① glTF 的 normal/UV 是 per-vertex、Blender 是 per-loop → 导出拆点，glb 顶点数**更多**（Female_Ranger 实测 12 件里 6 件更多，最多 +16.3%）；② 两具男模的 `Head_SuperHero_Male` 有 7 个游离顶点 + 6 条游离边，glTF 不导出游离顶点 → glb **更少**（1562 → 1555）。已改为『≥ 被面引用顶点数』+ 比值带 + morph target 顶点数对齐（A-15b/A-18）。
- **口径差（非缺陷）：mean 位移不能跨顶点集直接比**。glb 顶点是 Blender 顶点按 (pos,normal,uv) 拆/并后的结果，同一位移数值会被多算几遍 → 逐顶点 mean 的**权重**变了。实测：顶点数相等的『干净子集』mean Δ ≤ 4.041e-9 m；顶点数不等的件 mean Δ 最大 5.895e-4 m。而 max 与顶点重数无关，全体 84 个 (件,档) 的 max Δ ≤ 2.179e-8 m → **位移数值本身被原样保留，偏移纯属加权口径**。见 tmp/shape-lab-verify/recon_mean_delta.py。
- **口径差：`Head_Eyebrows`/`Head_Eyes` 的『零』在 Blender 里是精确 0.0，在 glb 里是 7.45e-9 m**（float32 在 ~1.8 m 量级上的分辨率；BS_Heavy 档 1.21e-7 m）。所以『static_by_design 必须零位移』的判据容差取 1e-5 m（0.01 mm）—— 取 1e-9 会把导出噪声判成真位移而假红。
- **上游台账观察（不是烘焙器的问题）**：`garment_manifest` 的 M4b 里 `Head_Eyebrows`/`Head_Eyes` 的 `moved_frac` 在 BS_Heavy 档是 **1.0**（BS_Thin 档是 0.0），而同一项的 `max_disp_cm` 是 **0.0**。这两者并不矛盾：moved_frac 数的是『非零字节』，而 BS_Heavy 档那 912/556 个顶点全带 ~1.2e-7 m 的 float32 噪声（无 magnitude 阈值）。⚠ 但 `moved_frac=1.0` 很容易被读成『眉毛跟着壮档形变』—— 它其实只动了 120 纳米。建议上游给 moved_frac 加一个 magnitude 阈值。
- **观察（非缺陷）**：`textures` 数可大于 `images` 数（Male_Ranger 16/13、Female_Peasant 15/10、Male_Peasant 15/13）—— 多个 texture 共用同一 image（采样器变体）。A-26 已确认每个 texture 都有合法 source、每个 material 的 baseColorTexture 索引可解析，故贴图链路完整。
- **观察（非缺陷）**：glb 顶点复制因子最大的件是男模腰带 （Male_Ranger_Body_Belt_1/2：928 → 1334/1335，factor 1.438/1.439），即这两件在 glb 里的顶点数据比 Blender 网格多出 44%。这不影响正确性（拆点是 glTF 规格要求），但会让顶点相关判据在这几件上『看起来差得多』，复核时别误判。
- **未能证实（诚实声明）**：A-23e 在两具**标准体**上是 UNVERIFIED —— 它们的唯一带 morph 件 （Body_Female/Body_Male）顶点数都不等于 Blender 顶点数（7380 vs 7376、7283 vs 7281），**不存在『干净子集』**，所以『同一批顶点上的 mean 是否一致』这个命题我无法在标准体上检验。服装四套都能检验且全过。
- **未能证实（诚实声明）**：`garment_manifest` 不含 .blend 级 sha256（只有 bodyshape_manifest 有）→ 4 套服装的 D-18 只能证明『manifest ↔ 当前磁盘 .blend 一致』，**不能**证明『与上游台账登记的那一版一致』。这是上游台账的缺口，不是烘焙器的错。
- **A-23d 的完整闭环**：这份报告里的 morph 数值对账不依赖任何台账 —— 我用 Blender 的 depsgraph 自己量了一次（blender/measure_morph.py，遵循 SPEC F9b），得到的是**第三个独立实现**，与 glb 侧 max Δ ≤ 2.179e-08 m。所以即使台账与 glb『一致地错』，也骗不过 A-23d。

## 6. 证据命令

```powershell
cd D:\artstudio
python tmp/shape-lab-verify/selftest_probe.py        # 解析器自测（含会红路径）
python tmp/shape-lab-verify/verify_assets.py --mutants
Get-ChildItem -Recurse tools/3d/godot/shape-lab -Include *.png,*.glb,*.gltf,*.blend,*.pyc
```
