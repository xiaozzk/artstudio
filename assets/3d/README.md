# assets/3d/ — 3D 角色资产台账（当前主方向）

> 来源：**Quaternius** 两个 **CC0 1.0** 包（商用免署名）。
> 加工工具与口径见 [`tools/3d/README.md`](../../tools/3d/README.md)；Godot 4 侧验证见 [`tools/3d/godot/README.md`](../../tools/3d/godot/README.md)。

## 一、原始资产（`packs/`）—— **不入库**（本地保留）

| 包 | zip | 官方页 | 许可 |
|---|---|---|---|
| Universal Base Characters [Standard] | `packs/Universal Base Characters[Standard].zip`（123 MB） | https://quaternius.com/packs/universalbasecharacters.html | CC0 1.0 |
| Modular Character Outfits - Fantasy [Standard] | `packs/Modular Character Outfits - Fantasy[Standard].zip`（294 MB） | https://quaternius.com/packs/modularcharacteroutfitsfantasy.html | CC0 1.0 |

> **存储策略（2026-10 起）**：`packs/` 与 `blend/` 都**不进 git**（见 `.gitignore`）——
> 源包是**可公开重下**的上游产物，`.blend` 是**可确定性重出**的生成物，都不该由仓库保管。
> 仓库里只留：脚本（`tools/3d/`）+ 清单（`manifests/`）+ 预览（`previews/`）+ 报告（`reports/`）+ 笔记（`research/`），
> 合计几 MB。校验与重下依据见下方「清单与复现」。

**解压树也不入库**（`*.bin` 不在 Git LFS 白名单，整树进 git 会污染对象库）。跑脚本前先解压：

```bash
unzip "assets/3d/packs/Universal Base Characters[Standard].zip" -d download/ubc/
unzip "assets/3d/packs/Modular Character Outfits - Fantasy[Standard].zip" -d download/modular-outfits-fantasy/
```

两个包的标准版**都只含部分模型**：基础角色只给 2/6 形体（Superhero 男女）+ 8/20 发型；服装只给 4 套成品
（Peasant / Ranger × 男女）+ 20 个散件。Source 版才有其余模型、`.blend` 源文件与引擎工程。

## 二、加工产物（`blend/` 103 份 + `textures/` 共享贴图库）—— **入库**

**2026-10 贴图去重改造**：原先 103 份 `.blend` 各自 pack 整套贴图 → 共 **2147.6 MB**（贴图重复 ≈11.9×）；
改造后 `.blend` 只存**网格 / 骨骼 / 材质**（**43.9 MB，占原来的 2.0%**），贴图收敛到共享库
[`textures/`](textures)（**24 张唯一贴图 / 96.5 MB**，按内容 sha256 去重）。
合计 **≈140 MB**（原 2.5 GB，**−94%**），而且**无损**：改造前后几何指纹逐份一致、三角面数逐片相同
（109352 / 314368 / 157184 / 228145 / 104345），103 份断言全过。

> 为什么这么做：通用压缩器对这批数据几乎无效（`.blend` 用 zstd −19 只省 **0.1%**、源包 zip 省 5%、PNG 省 2%），
> 而"每份各 pack 一遍贴图"才是 98% 体积的来源。去重后**可以直接 `git clone`**：不需要压缩包/解压流程、
> 能 diff、能增量、改一张贴图全局生效。工具：[`tools/3d/dedupe_textures.py`](../../tools/3d/dedupe_textures.py)（`scan` / `apply` / `verify`）。

每份 `.blend`：**65 骨通用人形 rig**（`RIG_<件名>`）、内嵌中文 `README_转换说明`，
贴图走**相对路径** `//../../textures/<文件>`（`.blend` 与 `textures/` 同在 `assets/3d/` 下，整体搬迁不断链）。分片：

| 目录 | 份数 | 体积（去重后） | 内容 |
|------|------|------|------|
| `blend/base-characters/` | 19 | 6.5 MB | 2 形体 + 8 发型 ×（Rigged to Head Bone / Origin at 0）+ `UBC_Standard_ALL` 总览 |
| `blend/outfits-gltf/` | 6 | 12.6 MB | 4 套成品 + `ModularParts` / `MCO-Fantasy_ALL` 两个**网格布局总览件**（便于一屏浏览） |
| `blend/outfits-gltf-per-asset/` | 24 | 9.4 MB | 4 成品 + 20 散件，逐件**原点对齐**（装配用这套） |
| `blend/outfits-fbx/` | 50 | 10.6 MB | 两包 **FBX 侧**（贴图从作者机器的 `C:/Dropbox/...` 重链后收敛到共享库） |
| `blend/tryon/` | 4 | 4.8 MB | **试穿件**：服装 + 基础角色「只剩头部」→ 单 rig 可动画 |
| `textures/` | 24 | 96.5 MB | **共享贴图库**（唯一副本，按 sha256 去重） |

各分片目录里带自己的 `preview/`（逐件渲染）与转换报告 `conversion-report.json`。

## 三、预览、报告与清单（**入库**）

- `previews/` —— 联系表与关键渲染：`base-characters_all.png`、`outfits_all.png`、`tryon_sheet.png`、
  `contact_fbx_*.png`、以及 Godot 4.6 的 4 张渲染（`render_outfits_4.png`、`render_hair_swap_2x8.png`、
  `..._tinted.png`、`render_blend_vs_gltf.png`）。
- `reports/` —— 转换报告、Lead 终验、独立验收（99 份 + 试穿 + 103 份）、Godot 报告与原始日志、转换 spec。
- `manifests/blend-manifest.json` —— **不入库大件的 sha256 清单**（103 份 `.blend` + 2 个源包 zip，
  含官方下载页），重出/重下后逐文件校验用；生成命令：`python3 tools/3d/make_manifest.py`。
- `research/` —— 3D 转型前期的调研笔记与快照（Configura / SkyMiX / MakeHuman-MPFB2 / 免费素材站清单等）。

## 四、口径（换人接手先看这几条）

1. **一根 rig**：全部 65 骨通用人形，骨名一致 → 换装就是同名骨同级叠放，**不做重定向**。
2. **单位**：米制，Godot 1u = 1m；女高 1.77 m / 男高 1.81 m。
3. **服装只配头部**：上游 Readme 明确「用全身会穿模」；`blend/tryon/` 已按顶点组裁成只剩头部（保留 21~22% 顶点）。
4. **`Origin at 0` 是静态件**（源无骨架），换装用 `Rigged to Head Bone` 变体。
5. **发型贴图是灰度**，颜色靠材质 `albedo_color` 乘上去（不是丢材质）。
6. 两条路线**不可混用**：glTF 侧与 FBX 侧同名资产朝向相反（50 对里 33 对 Y 轴镜像），骨骼索引顺序也不同（取骨用 `find_bone`）。

## 五、上游缺陷（已在本批产物里修掉 / 已记录）

1. UBC 形体 glTF 引用不存在的 `T_Hair_1_Normal_png.png` / `T_Eye_Normal_png.png`（实际名无 `_png`）→ 转换时按文件名归一化重链修好；**直接拿原始 glTF 进 Godot/UE 会丢这几张法线图**。
2. FBX 贴图是作者机器绝对路径 → 重链后 128 张全部命中。
3. glTF 散件 `Male_Ranger_Arms` 少导出 `Arms_Bracer`（FBX 同名散件有 3636 tris）→ 成品 vs 散件 glTF 侧 +15.57%、FBX 侧 0%。
4. 男侧服装 rig 与基础角色 rig 有 58/65 关节不一致，女侧 65/65 一致；两侧仅 `root/pelvis/spine_01..03/neck_01/Head` 7 根相同 —— 头部直接绑到服装 rig 位置正确（Head/neck_01 世界矩阵差 = 0）。

## 六、清单与校验（资产已在仓库里，clone 即用）

```bash
# 1) 断言：逐份重开，检查 65 骨 / 蒙皮 / 贴图可解析（pack 或外部共享库都算合格）
python3 tools/3d/run_check.py                       # 期望 103/103 通过

# 2) 清单校验：sha256 与 manifests/blend-manifest.json 对齐（有改动就会列出差异）
python3 tools/3d/make_manifest.py --out tmp/manifest.new.json
python3 -c "import json;old={e['path']:e['sha256'] for e in json.load(open('assets/3d/manifests/blend-manifest.json'))['entries']};new={e['path']:e['sha256'] for e in json.load(open('tmp/manifest.new.json'))['entries']};print('不一致:',[k for k in new if old.get(k)!=new[k]] or '无（逐文件一致）')"

# 3) 万一要重出（贴图库损坏 / 想换分辨率）：源包重下 → tools/3d 转换 → 再走 1) 2)
```

> `textures/` 是**唯一副本**：改一张贴图 = 所有引用它的 `.blend` 一起更新（这就是去重的最大好处）。
> 重命名/移动贴图后，用 `tools/3d/dedupe_textures.py -- verify` 或上一步 1) 复检相对路径是否仍可解析。

> 若确实需要"资产也版本化 + 多人共享"，不要把 3 GB 塞进 Git LFS：
> 用 **Cloudflare R2**（10 GB 免费额度、出网免费）或 B2 做对象存储 + `rclone`/`DVC` 同步，
> 仓库里只放清单与指针。理由与成本对比见 `tools/3d/README.md` 末尾。

---

## 七、v2 管线：**体形 morph 派生在角色自身网格上（B2）**（🟡 收尾中，2026-10-13 起）

> 任务档案：[`task/007-morph-pipeline/TASK.md`](../../task/007-morph-pipeline/TASK.md)
> **pipeline 指南：[`rig/README.md`](rig/README.md)｜接口契约：[`rig/SPEC.md`](rig/SPEC.md)（含实测事实 F1–F21）**
> **复杂度结论：[`task/007-morph-pipeline/verify/COMPLEXITY.md`](../../task/007-morph-pipeline/verify/COMPLEXITY.md)（独立验收）**

### 7.1 一句话

**体形差异 = morph（逐顶点偏移表，每档 = 顶点数 × 12 字节）；身高差异 = 角色根节点的世界等比缩放。**
一个数值同步驱动**每一件**网格的同名 morph。

### 7.2 目录（**增量新增，§二 的旧 `blend/` 一律不动**）

```
assets/3d/rig/
  SPEC.md                     ← 接口契约（唯一权威，F1–F21）
  README.md                   ← pipeline 指南（先看这个）
  bodyshape_spec.json         ← 体形骨定义 + 档位系数
  bodies/                     ← 标准体（**烘焙期工件**：含体形骨 NONE + morph 通道）
  garments/                   ← ★ 交付物：4 个**自包含角色** + 同名 morph
  manifests/  previews/  reports/
```

**为什么不动旧的 `blend/`**：那 103 份有 `run_check.py` 的 103 条断言、`manifests/blend-manifest.json`
的 sha256 清单、以及 Godot harness 的 `cfg.gd` 路径清单在依赖。按删除规则，旧产物保留作 v2 的**输入与回归基线**。

### 7.3 ⭐ 主路线 B2：**不引入外部身体**

现有 `blend/tryon/TryOn_*.blend` **本身就是最终角色**（服装布料 + 服装自带皮肤 + 基础体的头，**共用角色自己的 rig**）
→ **最终角色里没有独立的 Superhero 身体**（它只捐一个头）→ 于是"身体与服装体形基准不一致"这件事**根本不存在**。

因此正确做法是：**用角色自己的 rig 摆体形骨 → 逐件烘 shape key**。**不需要**剥离皮肤面、**不需要**贴合、**不需要**跨网格传递。

| 路线 | 工序 | 人工介入 | 裸露身体（像素法） | 结论 |
|---|---|---|---|---|
| **B2** ⭐ | **1 步** | **0 个** | **无独立身体**（论据见 SPEC F23） | ✅ **主路线** |
| B1（换同源 Regular 身体 + 传递） | 3 步 | 1 个 | 无（同源） | ✅ Tripo 阶段形态 |
| A（Superhero 硬贴合 + 外推） | 3 步 | 4 个 | 74% → 44% ❌ | ❌ 已否决 |

### 7.4 交付物与关键数字

| 文件 | 骨架 | 网格 | 顶点 | morph(2档) | 身高比 Thin/Heavy |
|---|---|---|---|---|---|
| `garments/Female_Ranger.blend` | **1** | 12 | 27,920 | 654 KB | 0.999442 / 1.000638 |
| `garments/Male_Ranger.blend` | **1** | 12 | 27,637 | 648 KB | 0.999978 / 1.000101 |
| `garments/Female_Peasant.blend` | **1** | 8 | 16,376 | 384 KB | 1.000169 / 0.999807 |
| `garments/Male_Peasant.blend` | **1** | 8 | 12,376 | 290 KB | 0.999989 / 1.000012 |

每件网格都持有 `Basis` / `BS_Thin`(索引 0) / `BS_Heavy`(索引 1) —— **名称与索引是硬契约**。

### 7.5 三条口径（都是实测踩出来的，别再重新论证）

1. **`inherit_scale='NONE'` 有"生命周期"之分（F18）**：`bodies/`（烘焙期）**必须 NONE**（否则体形骨缩放沿链传递，实测 `pelvis` 会让身高意外 +11.24%）；`garments/`（交付期）**应还原 FULL**（实测 root 骨×1.08 拉伸离散度 NONE 0.079 → FULL 0.0001）。**别拿"资产里是否 NONE"当判据。**
2. **身高不能用 `root` 骨缩放（F12）**：与上面那条冲突（身高只 +0.50%、离散度超标 8.4×）→ 用**角色根节点/骨架对象的世界等比缩放**（实测 +8.00%、离散度 0.00003）。
3. **shape key 不修改 `mesh.vertices`（F9）**，且**写完 shape key 数据后求值缓存会失效（F9b）** —— 必须重新 `depsgraph_get()` / `view_layer.update()` 再取值，否则会量到"没变化"而误判。

### 7.6 骨名以文件为准（**别凭记忆写**）

小腿骨叫 **`calf_l` / `calf_r`** —— 这套骨架**没有** `shin_*`。完整 65 骨名以 `rig/bodies/` 的标准体为准。

### 7.7 为什么这套结构"为 Tripo 铺路"

**关键不是"换两个输入"，而是"让标准体与服装第一次就同源"。**

- ✅ **不变的**：morph 契约（同名同序）、拓扑/契约/数据量校验、数据量结论（顶点×12 B）、`inherit_scale` 硬规则、"体形 morph 派生"这个思路。
- ⚠ **要重调的**：`delta_response` 的 9 个系数（**针对当前网格调的，且目前没有客观判据** —— 这是 B2 唯一的随规模增长的人时项）。
- ❌ **风险**：若 Tripo **分别独立**生成身体与服装 → 两次生成体形不会一致，**A 路线那块人工成本会原样保留甚至更严重**。
  只有「**先生成唯一标准体，再以它为基准生成/裁剪服装**」才能真正消掉它 —— 那时 **B1 与 B2 收敛为同一件事**。
- ⚠ **硬前提**：morph 要求"各档顶点数一致"，所以 Tripo 接入前必须先解决 **AI 生成拓扑可控**。
- ⚠ **已知欠定义**：SPEC §4.2 的传递口径（F20）在走 B1 之前必须先写死。
