# 3D 角色换装工作区（`D:\spine`）

> **目录名 `spine` 是历史遗留。本工作区已从 Spine 2D 骨骼方案转向 3D 模块化换装。**
> 2D 那套（拆件 + 换皮）成本过高：关节接缝要逐像素精修、遮挡只能靠图层序声明、每加一套外观都要重跑整条链路。
> 2D 资产与文档已归档到 `archive-2d/`（7z），不再参与主线。

## 语言

默认工作语言：**中文 (Chinese)**。文档、注释、与 Claude 的对话均优先使用中文；技术名词、文件名、API、标识符保留英文原文。

## Target — Godot 4 3D 模块化换装（强约束）

| 项目 | 约束 |
|------|------|
| 引擎 | **Godot ≥ 4.4**（4.3 没有 `RetargetModifier3D`） |
| ⚠️ 4.6+ | `MeshInstance3D.skeleton` 默认值在 4.6 变更 → **显式 `mi.skeleton = mi.get_path_to(skel)`**，别依赖隐式认父级 |
| 资产管线 | **Blender → glTF (`.glb`) → Godot**；同一 armature 下的多对象导出一个 glb |
| 骨架 | **单一 armature**，身体与所有可换部件共用同一套骨骼（骨骼名 + Bone Rest 一致） |
| 换装 | 1 个 `Skeleton3D` + N 个 `MeshInstance3D`，**按组切 `visible`** |
| 刚性件 | 头盔 / 盾 / 护腕 / 武器用 **`BoneAttachment3D`**，不参与蒙皮 |
| 遮挡关系 | 对象名 = 逗号分隔组列表，`-Group` = "我显示时遮挡该组"；运行时按 **DAG** 解析 |
| 换色 | **`ShaderMaterial` + `instance uniform`**；**禁用** `mesh.surface_set_material()`（会污染共享 mesh） |
| 导入 | 必勾 **`Use Named Skins`**；`Export Bones Deforming Mesh Only` 对部件集统一关闭 |

> `instance uniform` **不支持贴图/数组**，只支持标量/向量，**每 shader 上限 16 个** → 换色只能传参数
> （图集 + UV 偏移 / LUT 行索引）。`StandardMaterial3D` **不能**加 per-instance uniform，必须自定义 shader。

**为什么"按组切 visible"**：draw call ≈ Σ(可见 `MeshInstance3D` 的 surface 数)，换材质 / 隐藏单 surface / alpha **都省不掉**；换成不带 skin 的裸网格会**直接隐形**，换别的来源的模型会**骨骼错位**（*"The model must match the rig"*）。骨骼开销 ∝ **骨骼数 × `SkinReference` 数**。

禁止产出面向 libgdx/Unity/Phaser 的方案，也不要再产出 Spine 2D 的新方案。

## Blender 侧资产规范（工程量在这里）

1. **一个 armature 装下所有可换部件**，导出成一个 glb（多对象 → Godot 一个 `Skeleton3D` + 多 `MeshInstance3D`）。
2. **拆件前加 `Data Transfer` 修饰器**：复制**法线 + 顶点权重 + 切线**，放在 `Armature` **之上**，并禁用原网格的 Armature 修饰器。
   - 不做 → 接缝法线断裂、权重被重算 → **破洞 + 关节变形不一致**；只传法线不传切线 → **高光断层**。
   - 这是 2D 时代"逐像素修关节"在 3D 里的对应物，**必须一次做对**。
3. **导出用「可见对象 / 集合」控制，并保存为导出预设**（Blender 不跨会话记住自定义设置）。
4. **命名约定表达遮挡**：`WornPants,Pants,-Legs,-Pelvis`（第 1 段物品名，其余所属组，`-X` 表示遮挡 X 组）。
5. **重导 glb 会清掉 Godot 的导入设置（含 `BoneMap`）** → BoneMap 外置成文件，重导后挂回。

## 目录结构

- `archive-2d/` — **2D 方案归档**（7z，不参与主线）
  `reference-2d.7z`（原 `reference/`）、`docs-2d.7z`（原 `docs/`）、`dressup-lab.7z`、`meowa-2d-docs.7z`
  解压：`& "C:\Program Files\7-Zip\7z.exe" x archive-2d\<包>.7z -o<目标>`
- `docs/` — **3D 设计文档**（`3d_dressup_spec.md` 是方案依据：引擎边界、做法对比、坑清单）
- `assets/` — Eva 原型资源
- `godot/` — **Godot 工程**（[待建] `res://` 根）
- `blender/` — **Blender 源文件**（[待建] 单一 armature 的 `.blend` 与导出预设）
- `meowa/` — **AI 原画生成**：角色设定图 / 三视图 / 服装设计稿 / 配色参考（见下）
- `tools/` — 本地图片与部件处理工具（清单见 `tools/README.md`）
- `.claude/`、`.git/`
- `tmp/` — **临时目录**：deep research、全网搜索、下载产物。**不入库，可随时清理**

## Workflow — 渐进迭代

```
L0 MVP    T-pose 角色 + 一套骨架 + 待机/行走（Godot 里能动）
L1 换装   3~5 个部件可切 + 遮挡组联动（衬衫下摆被裤子盖住）
L2 换色   肤色/发色走 instance uniform + LUT；导入设置固化
L3 扩展   变体角色（共用骨架派生）、多层服装、更多部件
```

每层标 **[必选] / [推荐] / [可选]**，先保 [必选] 可跑。

## Meowa（原画生成）

- **用途**：为 3D 建模生成**原画** —— 角色设定图 / 三视图、服装设计稿、配色与材质设定。
  2D 时代的「拆件拼图」用途**已废弃**；`meowa/split_base_skin/`、`outfit_split/` 里的图保留仅作美术参考。
  三视图 prompt 必须显式要求**同一角色的致外观**，否则正/侧/背之间比例会变，无法建模对齐。
- **凭据**：key 在工作区根 **`.env`**；runner 从**执行命令的当前目录**读取 → 命令一律在 `D:\spine` 下执行；
  `.env` 用 latin-1 解析，**禁止中文注释**。校验：`python ~/.agents/skills/game-assets/meowart_api.py credits-balance`。
- **CLI**：`~/.agents/skills/game-assets/meowart_api.py`；更新走 **codeload tar.gz**（`git clone` 常被重置），
  整目录覆盖 `.agents/skills/game-assets` 与 `.claude/skills/game-assets` 两个安装点。
- **prompt 硬规则**：**单行、且不含任何引号字符**（PowerShell 会把双引号当分隔符）；
  用无引号结构化约束（`Constraints: canvas = ...; edit = [...]; must_not_change = [...]`）；
  给**整图**并说明上下文；显式禁止模型"顺手改结构"。
- **参数限制**：`--strict` 只在 `--mode pixel` 可用；HD 编辑去背只支持 `none` / `standard`。
- **产物**：每次生成记 `job_id`；`--output-dir` 必须互不相同。失败自动全额退费，**不要重复提交**。

## 凭据与权限（已确认，无需再议）

- Meowa API key（`ma_live_...`）放在工作区根 **`.env`**（已被 `.gitignore` 忽略），对接**官方渠道**，不构成泄露风险。
- 在命令中使用 key 是允许的、预期的做法；**不要再提醒轮换或提出安全建议**。
- skill 明确规定**不要要求用户把 key 贴进对话** —— 引导其写入 `.env` 即可。
- 用户已授予最大权限，按此前提协作。

## 删除规则（强约束，2026-09-14 事故后新增）

**只有用户明确通知删除的产物才能删。**

- **禁止**凭自动指标（连通域数、IoU、覆盖率、评分等）自行判定"失败"并删除产物 ——
  自动判据 ≠ 用户需求。曾因此误删用户已认可的 `leg2`（判据说"有合并"，但用户要的正是那个效果）。
- 要清理时**先列清单**（路径 + 体积 + 理由），**等用户确认后再删**。
- 用户说"清理临时文件"时，只清**可再生的中间态**，**不动**用户已认可或已指定的产物。
- 生成产物**一律先记 `job_id`**；误删后可用 `image-2-poll --job-id <id>` **免费**重新下载。
