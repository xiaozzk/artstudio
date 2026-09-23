# tools/ — 按业务场景分区的工具集

**除 `zenmux/zenmux_edit.py` 外，都是纯本地、确定性、不消耗 AI 额度。**

目录**按场景隔离**（2026-09-24 重组）：一个场景一个子目录，场景内的工具可以互相 import，
**跨场景不要互相依赖**。唯一会花钱的 AI 改图工具被单独关在 `zenmux/` 里，一眼能看出边界。

```
tools/
├── spine/     ① Spine 素材加工：图集体检修复 / 部件换皮 / 抽件
├── sprite/    ② 整图与部件的本地图像处理（生图 → 切件 → 贴图那一段）
├── zenmux/    ③ ZenMux AI 改图 CLI（唯一联网、唯一花钱）+ 它的 mock 测试
├── browser/   ④ 浏览器登录态复用（CDP 副本）
├── preview-2d/⑤ 2D 预览服务
└── *.py       兼容转发 shim（见文末）
```

## 依赖

```
python -m pip install numpy pillow opencv-python requests scipy
```

## ① `spine/` — Spine 素材加工

| 工具 | 作用 |
|------|------|
| `repair_spine/pipelines.py` | **图集体检与修复**（`diagnose` / `pagefix` / `unpack` / `repack` / `render` / `verify` / `meshfit`，以及一条龙 `build` / `prepare` / `convert` / `apply` / `file`）—— 56 个已交付包共用。口径见 [`repair_spine/README.md`](spine/repair_spine/README.md) 与根目录 `Spine图集修复通用经验.md`。⚠ **改它必须先跟用户确认** |
| `spine_part_swap.py` | 部件两件事：`locate`（哨兵色重渲定位插槽可见区 → mask / 尺寸 / 附件四边形）、`verify`（换图重渲量化改动范围，远处应为 0px） |
| `spine_part_extract.py` | 出「局部重绘」的提交三元组：`--mode pair`（摘除件单独图 + 原图置顶突出件 + 黑白 mask）/ `inplace` / `aside`；`paste-back` 把模型出图抠件、按 z 序（含覆盖表）贴回。⚠ **状态：实验性** —— 2026-09-24 用它做「整套逐件换风格」的批量实验，12 件里 4 件被模型"补全上下文"导致语义崩坏（详见该文件的实测注释），方案判为不稳定；工具留着供单件实验，**别当稳定流水线用** |
| `spine-reskin.md` | 换皮整条流水线（含实测坑与成本）|

## ② `sprite/` — 整图与部件处理（纯本地）

| 工具 | 作用 |
|------|------|
| `bbox_ref.py` | 由 bbox 规格生成「比例参考图」（喂 AI 当比例约束 / 当人工验收标尺） |
| `alpha_split.py` | 按 alpha 连通域把一张整图拆成多个部件 |
| `fit_parts.py` | 部件按 spec 比例缩放拼回原画布 + 客观质量分（`alpha_iou` / `coverage` / `spill` / `color_mae`） |
| `slice-sheet.py` | 整张部件拼图 → 部件贴图（脏像素清理 + 体检）→ 见 [`slice-sheet.md`](sprite/slice-sheet.md) |
| `outline-part.py` | 皮肤件补**内描边**（只改 RGB，不动 alpha）；幂等，写 PNG `tEXt` 标记 `SpineOutline` |
| `outfit-split.py` | 服装拆件拼图 → 可换装件（输入须纯灰底 205） |
| `image_parts_tool.py` | 部件边缘精修一体化：`analyze` / `cut` / `prep` / `prompt` / `gen` / `verify` / `apply` / `report` / `diff` / `overview` |
| `parts_sheet.py` | 把一组部件摆成互不重叠、相邻 ≥N px 的参考图 |
| `flatbg_cut.py` | 纯色底出图 → 抠成透明件（自动估底 + 反混合去边）+ 按参考部件 alpha 最大 XY 等比贴合 |
| `ps_cut/fill_from_layer1.jsx` | PS 内一键补缺口（文件 > 脚本 > 浏览） |

## ③ `zenmux/` — AI 改图（**唯一会花钱**）

| 文件 | 作用 |
|------|------|
| `zenmux_edit.py` | ZenMux 图片编辑：Vertex `:predict`（默认）/ OpenAI 协议，mask 局部重绘、多 mask 三种消化、`--dry-run`、`--min-credits` 守卫 → 见 [`zenmux-edit.md`](zenmux/zenmux-edit.md) 与 [`../../docs/zenmux-cli.md`](../docs/zenmux-cli.md) |
| `tests/` | **mock 级 CLI 测试**：`python tools/zenmux/tests/test_zenmux_cli.py`（14 条，约 6s，全程 127.0.0.1、**零真机零费用**）→ 见 [`tests/README.md`](zenmux/tests/README.md) |

## ④⑤ 已隔离的老目录

| 目录 | 用途 |
|------|------|
| `browser/` | 浏览器登录态复用（CDP 副本）—— 与图片管线无关，见 [`browser/README.md`](browser/README.md) |
| `preview-2d/` | 2D 预览服务，见 [`preview-2d/README.md`](preview-2d/README.md) |

## 兼容转发 shim（**别删**）

`tools/` 根目录下这几个文件**不是工具本体**，而是 3 行转发脚本 —— 真正的文件已经搬进场景目录，
但**已交付产物里写着旧路径**，删了会让历史履历的复现命令失效：

| shim（旧路径，仍可用） | 真正的位置 | 谁在引用旧路径 |
|---|---|---|
| `repair_spine/pipelines.py` | `spine/repair_spine/pipelines.py` | **105 份已交付的 `交付说明.md`** |
| `spine_part_swap.py` | `spine/spine_part_swap.py` | `assets/武僧/reskin_weapon1/交付说明.md` |
| `zenmux_edit.py` | `zenmux/zenmux_edit.py` | 同上（核账命令） |
| `outline-part.py` | `sprite/outline-part.py` | `assets/eva_bone/parts/outline.json` 的 note |

**新代码请直接用新路径**；旧路径只在"复现历史交付"时才会被用到。

## 通用约定

- **优先让 AI 直接输出透明背景**。把图压到纯色底再抠色会不可逆地丢掉最淡的抗锯齿像素
  （实测一条 1px 细线的 alpha 像素 167 → 69）。`--bg` 只作为兜底。
- **面积比要用相对值**：AI 那套部件可能整体按 1.5× / 2× 画出来，绝对面积差一个全局常数，
  直接比会把 `hair` 和 `head_base` 配反（实测踩过）。
- 部件贴图统一**保留同一套画布坐标**，换任何目标分辨率都只是乘一个缩放系数。

> **数据格式标识符**（`spine-outfit-split`、`spine-part-outline`、`spine-dressup-lab-sheet-parts`、`SpineOutline`）
> 是已生成产物里写死的字符串，改名会破坏与既有产物的兼容，因此保留原样。
