# tools/3d/ — Quaternius 3D 角色资产加工（Godot 4 方向）

面向 **Godot 4（≥4.4）** 的 3D 角色素材流水线：把第三方 glTF/FBX 素材包**批量转成自包含 `.blend`**、
按「衣服只穿在头上」的口径**合成试穿件**、并做**批量重开断言**；Godot 侧另有运行时零拷贝换装与
`.blend` 直读的最小 harness。

> 数据来源：Quaternius 两个 CC0 包 —— `Universal Base Characters`（基础角色 + 发型）与
> `Modular Character Outfits - Fantasy`（4 套成品服装 + 20 个模块化散件）。
> 台账与产物见 `assets/3d/README.md`；源包 zip 在 `assets/3d/packs/`，解压树在 `download/`（不入库）。

## 脚本

| 脚本 | 作用 | 典型用法 |
|------|------|----------|
| `pack2blend.py` | **批量 glTF/FBX → 自包含 `.blend`**（Blender 内执行）。一个 spec 的 `jobs[]` = 一个 Blender 进程串行转 N 份；贴图全部 pack；**坏引用重链**（作者机器绝对路径、`*_png` 错名）；可选网格布局；每份内嵌中文 `README_转换说明` | `Blender -b --factory-startup --python tools/3d/pack2blend.py -- spec.json` |
| `build_tryon.py` | **试穿合成**：把基础角色按顶点组裁成「只剩头部」，与服装套装（+可选发型）合并到服装自带的 65 骨 rig 上 → 单 rig 可动画件 | `Blender -b --factory-startup --python tools/3d/build_tryon.py` |
| `check_blends.py` | **批量重开断言**（Blender 内执行，输入 manifest.json）。A 蒙皮件 / B 静态件两套判据 | `Blender -b --factory-startup --python tools/3d/check_blends.py -- manifest.json` |
| `run_check.py` | 上面那个的**驱动**：收集 → 调 Blender → 汇总 `check-report.json` + 每分片联系表（PIL 拼图） | `python3 tools/3d/run_check.py` |
| `fix_blend_readme.py` | 只改 `.blend` 内文本块，并用「几何+骨骼 rest+贴图尺寸 sha256」自证**几何未变** | `Blender -b --factory-startup --python tools/3d/fix_blend_readme.py -- check`（或 `fix`） |
| `dedupe_textures.py` | **贴图去重**：把各份 `.blend` 里各自 pack 的贴图收敛成共享 `assets/3d/textures/`（按内容 sha256 去重），`.blend` 只留网格/骨骼并用相对路径引用 —— **2147.6 MB → 43.9 MB（2.0%）**，几何指纹逐份一致 | `Blender -b --factory-startup --python tools/3d/dedupe_textures.py -- scan\|apply\|verify` |
| `godot/` | Godot 4.6 侧 harness：运行时 `GLTFDocument` **零拷贝**换装、`.blend` 直读（self-contained 配置）、`SubViewport` 离屏渲染验收。口径见 [`godot/README.md`](godot/README.md)（v2 的交互预览页在 [`godot/preview/`](godot/preview/README.md)，一条命令：`tools/3d/godot/preview/run.sh`） | 见 [`godot/README.md`](godot/README.md) |

## v2 管线：体形 morph（2026-10 起）—— **先读这里**

> **v2 与上面那套（`blend/` 里的 103 份）是并存关系**：旧资产是 v2 的**输入与回归基线**（`run_check.py` 103/103），**只读不改**。
> v2 的产出全部在 **`assets/3d/rig/`**，契约是 **[`assets/3d/rig/SPEC.md`](../../assets/3d/rig/SPEC.md)**（**唯一权威**）。

**做什么**：给角色做**可调的体形（瘦/标准/壮）+ 身高**，并让**服装跟着一起变** —— 用引擎原生 **morph（blend shape）**，运行时不需要任何变形代码。

```
体形差异 = morph（逐顶点偏移表，每档 = 顶点数 × 12 字节）
身高差异 = 角色根节点 / 骨架对象的世界等比缩放（不是 morph、也不是 root 骨缩放）
```

**主路线 = B2：体形 morph 派生在「角色自身网格」上** —— 不做剥离、不做贴合、不做跨网格传递。
原因：现有试穿角色的**最终形态里根本没有那具独立标准体**（它只捐一个头），所以"身体与服装体形基准不一致"这个问题**不存在**。
复杂度结论（独立验收）：A **高** / B1 **中** / **B2 低** —— 见 [`task/007-morph-pipeline/verify/COMPLEXITY.md`](../../task/007-morph-pipeline/verify/COMPLEXITY.md)。

| 脚本 | 作用 | 典型用法 |
|------|------|----------|
| `make_standard_body.py` | **规范化标准体**：骨架改名 + 体形骨子骨设 `inherit_scale='NONE'` + 建 morph 占位通道 | `Blender -b --factory-startup --python tools/3d/make_standard_body.py` |
| `skeleton/make_profile.py` | **生成骨架契约**（**77 骨**：脊柱 7 节 + 每指掌骨，左右镜像完全对称）→ `assets/3d/rig/profiles/humanoid_biped_7spine.json`。骨名/层级/顺序是**硬契约**，手写必错 → 用生成器保证；`--check` 复校 | `python3 tools/3d/skeleton/make_profile.py`（`--check` 只校验） |
| `skeleton/make_mapping.py` | **骨架 → VRM 角色词表映射**（规则生成，不手写；骨表读自 profile，**不依赖第三方件**）→ `assets/3d/rig/skeleton_mapping.json`。**自检三关**：孤儿骨／角色重复／**规模与构成**（`77 = 52 映射 + 25 额外`）；`--check` 复校已入库产物 | `python3 tools/3d/skeleton/make_mapping.py`（`--check` 只校验） |
| `skeleton/check_proportions.py` | **按种族契约校验身体比例**（Blender 内执行）：头身比（用「**眼在头高中点**」测，不依赖找下颌）+ 7 个★骨位标志点，容差 ±1.5%H。**已实证会变红**（头身比目标改 7、肩位目标改 90% 均 exit≠0） | `Blender -b --factory-startup --python-exit-code 1 --python tools/3d/skeleton/check_proportions.py -- --race assets/3d/rig/races/humanoid/race.json --body assets/3d/rig/bodies/Body_Female_Standard.blend` |
| `bodyshape/derive.py` | **体形派生**：按 spec 摆体形骨 → 烘 `BS_Thin`/`BS_Heavy` → 回写标准体 + manifest + 三档预览。**纯 python3，不需要 Blender** | `python3 tools/3d/bodyshape/derive.py --sex both` |
| `bodyshape/verify_bodyshape.py` | **38 项断言**（含 **spec ↔ 已烘 morph 的几何闭环**，误差 0.000000 mm） | `python3 tools/3d/bodyshape/verify_bodyshape.py` |
| `bodyshape/measure_girth.py` | **关键围度**（切片 → 2D 凸包周长 = 软尺量法，对破洞/面绕向免疫） | `python3 tools/3d/bodyshape/measure_girth.py --help` |
| `bodyshape/silhouette_metric.py` | **剪影 XOR + 等效身高换算**（标尺曲线是凹的，必须分段插值） | `python3 tools/3d/bodyshape/silhouette_metric.py --help` |
| `garment/derive_on_character.py` | ★ **B2 主实现**：在角色自己的 rig 上摆体形骨 → 逐件烘同名 shape key | `Blender -b --factory-startup --python tools/3d/garment/derive_on_character.py -- --only Female_Ranger` |
| `garment/build_all.py` | 4 套一次跑完（~3 分钟，含偏斜守卫） | `python3 tools/3d/garment/build_all.py` |
| `garment/verify_fit.py` | 验收 + 出清单（**13 项判据**，含 M4b 非平凡 / M4c 臂展双信号） | 见 [`garment/README.md`](garment/README.md) |
| `garment/checks/` | **门禁对照件**：证明"判据会变红"（零 morph 假 PASS / 漏 along / 漏 NONE / 偏斜守卫） | 见 [`garment/checks/README.md`](garment/checks/README.md) |
| `garment/` 的 B1 工具 | `strip_skin` / `refit` / `transfer_morph` / `autofit` —— **已被否决（A 路线）**，保留给 Tripo 阶段参考 | 同上 |
| `godot/preview/` | **Godot 4 交互预览页面**：体形/身高双滑块 + 换装 + 换发型 + 逐件 morph 读数 + 实时穿模曲线（含双向标定） | `tools/3d/godot/preview/run.sh`（`--interactive` 开页面） |
| `godot/preview/probes/` | **Godot 骨骼陷阱探针**（A1 入树时机 / A2 pose 空间 / A3 `get_aabb()` 是静止 AABB） | 见 [`godot/preview/probes/README.md`](godot/preview/probes/README.md) |

### ⚠ v2 的八条硬约束（都是踩出来的，别重新论证）

1. **`inherit_scale='NONE'` 有"生命周期"之分**：`rig/bodies/`（**烘焙期**工件）**必须 NONE**；`rig/garments/`（**交付期**运行时资产）**应还原 FULL**。**别拿"资产里是否 NONE"当判据。**
2. **身高不能用 `root` 骨缩放** —— 与上一条冲突（实测身高只 +0.50%、拉伸离散度超标 8.4×）→ 用**角色根节点/骨架对象的世界等比缩放**（+8.00%、离散度 0.00003）。**对象级缩放与 `inherit_scale` 正交**，所以 `bodies/` 留 NONE 无妨。
3. **shape key 不修改 `mesh.vertices`**，且**写完 shape key 数据后求值缓存会失效** → 必须重新 `depsgraph_get()` / `view_layer.update()` 再取值。
4. **取骨一律 `find_bone("Head")` 按名字** —— **索引取决于「该文件里的骨层级 DFS 顺序」，跨文件不可复用**。
   008 做过决定性实验：把真 glb 的 `skin.joints` **整段倒序**（nodes 与层级不动）→ Godot 的骨顺序**一位没变**（`Head` 仍 54）⇒ **Godot 既不读 `skin.joints` 数组、也不读 `nodes` 数组顺序，只读骨层级**。
   实测：**Blender 打开 `.blend` → `Head = 6`**；**本项目的 glb 在 Godot 里 → `Head = 54`**。
5. **造"必然在体外"的合成壳不能用顶点法线外推** —— 标准体相对质心**非星形**（仅 67.2% 面满足），凹处会把点推进邻肢。
6. **像素法是穿模的权威判据，但必须带双向标定**（只渲身体 → 100.00%、只渲服装 → 0.00%，不过就报错）——实测**不带标定在"无身体"图上误报 37.3%**。且材质须 Emission 纯色 + `view_transform='Standard'`。
7. **跑 Blender 一律加 `--python-exit-code 1`** —— `blender -b --python X.py` **在脚本抛异常时仍返回 exit 0**（门禁会静默说谎）。
8. ⚠ **烘 morph 前必须清掉 IK / 全部约束** —— pose 与 shape key 是**两套独立形变来源、会叠加**（实测读到过 **33 mm 假差**）；在「IK 影响下的姿态」里读顶点会**把姿态错误烘进 morph**。
   配套结论：**资产里不带 IK 骨**（源 glTF `ik_` 计数 = 0，这是对的）；脚部贴地 / 手部持物**在 Godot 运行时**加 `TwoBoneIK3D`。⚠ Blender 5.x 把 IK 约束的**类名**改成了 `KinematicConstraint`（枚举仍是 `'IK'`），`Armature.ik_solver` 已移除。详见 [`assets/3d/rig/SPEC.md`](../../assets/3d/rig/SPEC.md) **F33**。

### 经验与验收纪律（**改 v2 之前请先读**）

| 文档 | 内容 |
|---|---|
| [`assets/3d/rig/SPEC.md`](../../assets/3d/rig/SPEC.md) | **36 条实测事实**，每条标**证据等级**（含「已撤回」「机制已定位」）。F33 IK/约束/导出、F34 8 头身实测、**F35 截断≠不存在**、**F36 glTF 不保留约束** |
| [`assets/3d/rig/SKELETON.md`](../../assets/3d/rig/SKELETON.md) | **骨层级 + 组成**；与 UE / Mixamo / Unity / VRM 的命名对照；**「是不是通用标准」的三层结论**；腿骨是 `calf_*` 不是 `shin_*`；§6 VRM 语义层决策、§7 IK 与 morph |
| ⭐ [`assets/3d/rig/RENDER.md`](../../assets/3d/rig/RENDER.md) | **NPR 渲染 / UV / 贴图契约**：简化阶梯 L0–L4、推荐组合、**Godot 实测枚举值**（零 shader 可做卡渲+描边）、UV 与贴图的**自动配方**、表情契约、**10 条实测坑**、明确「不做」的决定 |
| [`assets/3d/rig/channels.json`](../../assets/3d/rig/channels.json) | **morph 通道契约 v2.0**：体型预设轴（tent 连续插值）／连续轴／比例轴（骨缩放+归一化）／表情命名空间／数据量预算；⚠ v1 冻结为 legacy |
| [`assets/3d/rig/reference/BODIEZ-ANALYSIS.md`](../../assets/3d/rig/reference/BODIEZ-ANALYSIS.md) | **第三方参考件分析**（骨架布局 / 两层变形机制 / 借什么改什么 / **Lead 两处自我更正** / 许可提醒） |
| ⭐ [`assets/3d/rig/GENERATION-GUIDE.md`](../../assets/3d/rig/GENERATION-GUIDE.md) | **要自己生成素材（含 AI 生成）先读这份**：morph 经验 15 条 + 生成指南（三条铁律/流程/自检清单）+ `bodyshape` 该用什么格式 |
| [`assets/3d/rig/README.md`](../../assets/3d/rig/README.md) | pipeline 指南：目录 / 三路线 / 复现命令 / 验收判据 / 坑速查 |
| [`task/007-morph-pipeline/lead/ACCEPTANCE.md`](../../task/007-morph-pipeline/lead/ACCEPTANCE.md) | **验收台账 + §七 方法论 10 条** |
| [`task/007-morph-pipeline/verify/COMPLEXITY.md`](../../task/007-morph-pipeline/verify/COMPLEXITY.md) | 复杂度报告（独立验收，1377 行） |

> **一条总纲**（本任务共 16 次自我纠正或相互证伪后的归纳）：
> **凡是"看起来通过"的地方，都要问一句"它在什么条件下会变红"；
> 凡是"两个独立实现不一致"的地方，都要停下来查机制。**
> 尤其当心**静默的错** —— 不报错、不崩溃，只是安静地给你一个错的数。

## 口径与硬约束

- **一根 rig**：所有资产统一 65 骨通用人形（`root/pelvis/spine_01..03/neck_01/Head/clavicle_*/upperarm_*/.../thigh_*/calf_*/foot_*/ball_*` 五指令牌四节）。换装 = 同名骨同级叠放，**不要重定向**。
- **单位**：米制，Godot 1u = 1m；基础角色身高 1.77 m（女）/ 1.81 m（男），无需缩放。
- **服装只配头部**：上游 Readme 明确「用全身会穿模」→ `build_tryon.py` 按顶点组 `Head`/`neck_01` 权重和 > 0.5 裁掉躯干四肢（实测保留 21~22% 顶点）。
- **`Origin at 0` 发型是静态件**：源 glTF `skins=0`、FBX 无 ARMATURE —— 换装请用 `Rigged to Head Bone` 变体；断言时这 8 个按 B 类（静态）判，不要伪造 rig。
- **发型贴图是灰度**：`T_Hair_*_BaseColor` 是给运行时染色的中性底色（平均 `max-min ≈ 5`），颜色靠材质 `albedo_color` 乘上去；`check_blends.py` 只校验贴图存在，不判颜色。
- **骨骼索引不可硬编码**：索引取决于**「该文件里的骨层级 DFS 顺序」**，**跨文件不可复用**。
  008 的决定性实验：把真 glb 的 `skin.joints` **整段倒序**（nodes 与层级不动）→ Godot 骨顺序**一位没变**（`Head` 仍 54）⇒ **它既不读 `skin.joints` 数组、也不读 `nodes` 数组顺序，只读骨层级**。
  实测：**Blender 打开 `.blend` → `Head = 6`**；**本项目的 glb 在 Godot 里 → `Head = 54`**。
  ℹ **旧文档那句「glTF 路线 `Head=6`」量的是上游 Quaternius 原始 glTF**（另一份文件，现已不在盘上）—— **不是矛盾，是两个不同文件**。
  → 一律 `Skeleton3D.find_bone("Head")` / `arm.data.bones.find("Head")`。
- **两条路线朝向相反**：glTF 路线与 FBX 路线同名资产 50 对里 33 对 Y 轴镜像（源就如此）→ 别在同一工程混用。
- `*.bin` **不在 Git LFS 白名单**（只有 `.blend/.glb/.gltf/.fbx/.obj` 等是）→ 解压树不要入库，入库只放 zip 与 `.blend`。

## 已知上游缺陷（复现即可，不是转换 bug）

1. `Superhero_{Male,Female}_FullBody.gltf` 引用不存在的 `T_Hair_1_Normal_png.png` / `T_Eye_Normal_png.png`（实际文件名无 `_png` 中缀）→ `pack2blend.py` 的**文件名归一化重链**已修；直接把这些 glTF 导进 Godot/UE 会丢这几张法线图。
2. FBX 侧贴图路径是作者机器的 `C:/Dropbox/...` → 重链后 128 张全部命中。
3. glTF 散件 `Modular Parts/Male_Ranger_Arms` 少导出了 `Arms_Bracer`（FBX 同名散件有 3636 tris）→ 成品套装 vs 散件之和在 glTF 侧 +15.57%、FBX 侧 0%。
4. 男侧服装 rig 与基础角色 rig 有 58/65 关节不一致（手臂链旋转 2.55°、手指最高 13.37°、腿链 X 偏移 23.7mm），女侧 65/65 完全一致；**只有 `root/pelvis/spine_01..03/neck_01/Head` 7 根两侧相同**，所以头部直接绑到服装 rig 位置正确（Head/neck_01 世界矩阵差 = 0）。

## 复现路径（从 zip 到产物）

```bash
# 1) 解压源包（脚本默认读这两个位置；zip 在 assets/3d/packs/）
unzip "assets/3d/packs/Universal Base Characters[Standard].zip" -d download/ubc/
unzip "assets/3d/packs/Modular Character Outfits - Fantasy[Standard].zip" -d download/modular-outfits-fantasy/

# 2) 批量转 .blend（写一个 spec.json，jobs[] 里每项一个 import/out/preview）
"/Applications/Blender.app/Contents/MacOS/Blender" -b --factory-startup \
  --python tools/3d/pack2blend.py -- spec.json          # 每份输出一行 JOB_RESULT {json}

# 3) 试穿合成（默认输出 assets/3d/blend/tryon/）
"/Applications/Blender.app/Contents/MacOS/Blender" -b --factory-startup --python tools/3d/build_tryon.py

# 4) 终验：99+ 份批量重开断言 + 联系表
python3 tools/3d/run_check.py --out tmp/3d-check
```

## 存储策略：先"去重"，再谈"压缩"（2026-10 实测）

### 1) 通用压缩对这批资产几乎无效（先别指望压缩包）

| 内容 | 压缩器 | 结果 |
|---|---|---|
| `.blend`（38 MB，贴图已 pack） | `zstd -19 --long=27` / `xz -9e -T0` | **99.9%**（只省 0.1%，7.4 s / 11.6 s） |
| 源包 zip（60 MB 切片） | `zstd -19` | **94.7%**（省 5%） |
| 2D 资产 PNG（8.3 MB） | `zstd -19` | **97.9%**（省 2%） |

原因：`.blend` 里 98% 是已 deflate 的 PNG，zip 本身也是 deflate 流 —— 没有可压的熵。
所以「把 `assets/` 打成压缩包入库、clone 后解压、改完压回」**省不到 5%，却要背上**：
GitHub 普通 git 拒收 >100 MB 单文件（仍得走 LFS/Release）、压缩包**无增量**（改一次多一个整包对象）、
clone 必须拉全量再解压、二进制包无法 diff/合并。

### 2) 真正的杠杆：贴图去重（无损，−94%）

实测：103 份 `.blend` 共 **2147.6 MB**，其中贴图 2103.6 MB，而唯一贴图只有 **~177 MB → 重复 ≈11.9×**；
把 `.blend` 解开 pack 后本体只剩 **2.7~3.6%**。于是做了 `dedupe_textures.py` 改造：

| 形态 | 体积 | 说明 |
|---|---|---|
| 改造前：每份各自 pack | 2147.6 MB | 贴图重复 11.9× |
| **改造后：网格 + 共享贴图库** | **43.9 MB + 96.5 MB = ≈140 MB（−94%）** | 几何指纹逐份一致、三角面数逐片相同（103/103 断言通过） |
| 可选：贴图转 WebP 无损（实测 65~72%） | ≈ 44 + 66 MB | Blender / Godot 4 都直接读 WebP |
| 可选：降采样 2048→1024（实测 25~41%） | ≈ 44 + 25 MB | **有画质代价**；法线图别用有损（q90 只剩 5% 但细节全毁） |

### 3) 现在各自放哪

| 放哪 | 放什么 | 体积 |
|---|---|---|
| **Git（入库，可 clone 即用）** | 本目录脚本、spec、`assets/3d/manifests/`（sha256 清单）、`assets/3d/previews/`、`reports/`、`research/`、**去重后的 `assets/3d/blend/` + `assets/3d/textures/`** | **≈145 MB** |
| **本地（`.gitignore`）** | `assets/3d/packs/` 源包 zip（404 MB，官方页可重下）、`download/` 解压树（694 MB）、`assets/2d/` 2D 素材（537 MB） | — |

校验：`python3 tools/3d/run_check.py`（103/103）+ `make_manifest.py` 比 sha256，命令见 `assets/3d/README.md` 第六节。

### 4) 要"资产也版本化 + 多人共享"时

别用 Git LFS 装大二进制；用对象存储 + 指针（仓库只留清单）：

| 方案 | 3 GB 量级的月成本 | 备注 |
|---|---|---|
| **Cloudflare R2** | **$0**（免费额度 10 GB-month、出网免费）；超出 $0.015/GB·月 | `rclone` / `DVC` remote 直接对接 |
| Backblaze B2 | ≈$0.018/月（$6/TB·月），出网 ≤3× 存储免费 | 便宜大碗 |
| GitHub LFS | Free 含 10 GiB 存储 + 10 GiB/月带宽（现在入库的 145 MB 完全够） | 二进制每次改动整份存，且 clone/CI 都吃带宽 |

> 踩过的坑：`git lfs prune` 只回收**未被引用**的对象，而 **index（已暂存）也算被引用** ——
> 大件暂存着时 prune 几乎回收不到东西（实测只回收 38 MB）。先 `git rm -r --cached <路径>`（不动磁盘文件）
> 再 `git -c lfs.pruneoffsetdays=0 lfs prune`（实测 `.git/lfs` 3.0 GB → 260 MB）。

## 实测规模（2026-10）

| 分片 | 份数 | 体积 | 说明 |
|------|------|------|------|
| `base-characters` | 19 | 190 MB | 2 形体 + 8 发型 × (HeadBone / Origin0) + 总览 |
| `outfits-gltf-per-asset` | 24 | 738 MB | 4 成品 + 20 散件，逐件原点对齐 |
| `outfits-gltf` | 6 | 1.1 GB | 4 成品 + 2 总览（网格布局） |
| `outfits-fbx` | 50 | 669 MB | 两包 FBX 侧，贴图重链后 pack |
| `tryon` | 4 | 214 MB | 服装 + 基础角色头部（单 rig） |
| **合计** | **103** | **≈2.9 GB** | 全部自包含、65 骨、断言全过 |