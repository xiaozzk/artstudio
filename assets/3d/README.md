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
