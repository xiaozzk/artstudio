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
| `godot/` | Godot 4.6 侧 harness：运行时 `GLTFDocument` **零拷贝**换装、`.blend` 直读（self-contained 配置）、`SubViewport` 离屏渲染验收。口径见 [`godot/README.md`](godot/README.md) | `tmp/3d-godot` 工程内 `Godot --path . -s res://render_hair.gd` |

## 口径与硬约束

- **一根 rig**：所有资产统一 65 骨通用人形（`root/pelvis/spine_01..03/neck_01/Head/clavicle_*/upperarm_*/.../thigh_*/calf_*/foot_*/ball_*` 五指令牌四节）。换装 = 同名骨同级叠放，**不要重定向**。
- **单位**：米制，Godot 1u = 1m；基础角色身高 1.77 m（女）/ 1.81 m（男），无需缩放。
- **服装只配头部**：上游 Readme 明确「用全身会穿模」→ `build_tryon.py` 按顶点组 `Head`/`neck_01` 权重和 > 0.5 裁掉躯干四肢（实测保留 21~22% 顶点）。
- **`Origin at 0` 发型是静态件**：源 glTF `skins=0`、FBX 无 ARMATURE —— 换装请用 `Rigged to Head Bone` 变体；断言时这 8 个按 B 类（静态）判，不要伪造 rig。
- **发型贴图是灰度**：`T_Hair_*_BaseColor` 是给运行时染色的中性底色（平均 `max-min ≈ 5`），颜色靠材质 `albedo_color` 乘上去；`check_blends.py` 只校验贴图存在，不判颜色。
- **跨路线骨骼索引会变**：同一素材 `Head` 在 `.blend` 路线是 index 54、glTF 路线是 index 6 → 取骨一律 `find_bone("Head")`，**别硬编码 index**。
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