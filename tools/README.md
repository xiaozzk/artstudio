# tools/ — 资源流水线工具

面向 Spine / Godot 的角色拆件工具链。**纯本地、确定性、不消耗 AI 额度**。

| 工具 | 作用 | 依赖 |
|------|------|------|
| `bbox_ref.py` | 由 bbox 规格生成「身体比例参考图」，并把比例换算到任意目标分辨率 | Python |
| `alpha_split.py` | 按 alpha（透明背景）连通域把一张整图拆成多个部件 | Python |
| `fit_parts.py` | 把 AI 拆出的部件按 spec 比例缩放、拼回原画布，并给出客观质量分 | Python |
| `slice-sheet.py` | 把生图产出的**整张部件拼图**切成部位贴图（含隐形脏像素清理 + 同口径体检） | Python |
| `outline-part.py` | 给皮肤件补**内描边**（只改 RGB）—— 脸型没有下颚线时用它（见 [`slice-sheet.md`](slice-sheet.md)） | Python |
| `import-parts-to-dressup-lab.mjs` | 把切件按 manifest 走 API 导进实验室项目（部位锚点 + 12 个分组） | Node ≥18 |
| `lab-sync-project.mjs` | 让锚点库与导出交付物跟上项目（`--check` 只体检） | Node ≥18 |
| [`dressup-lab/`](dressup-lab/README.md) | **换装实验室**：共享骨架 + 部位锚点（中心 + bbox）定位 + 换装预览 + 图集/部位资产导出 | Node ≥18，零 npm 依赖 |

## 依赖

```
python -m pip install numpy pillow opencv-python
```

---

## 0. `dressup-lab/` — 换装实验室（JS）

拆件之后的**快速拼装与效果确认**环节：**所有人物共享同一副骨架（只读）**，
部位 = 骨架上的锚点（中心 + 中心对称 bbox）→ 挂图 → 自动按部位 bbox 缩放、
中心对中心 → 超出 bbox 一律裁掉 → 对着骨架看「部位 ↔ 骨骼」映射 → 导出**部位图 + 图集 + 骨骼资产**。

```bash
node tools/dressup-lab/scripts/import-rig.mjs   #（可选）骨架 → 部位锚点库 + 示例项目（--rig 可指向项目里导入的骨架）
node tools/dressup-lab/server.mjs               # 启动（默认自动开浏览器 127.0.0.1:8791）
node tools/dressup-lab/scripts/verify.mjs       # 14 组（含导出交付物交叉校验 + 贴图描边同步；基准项目 human_female，换 fixture 可加项目名）
```

- **参考骨架可选、手动导入**：默认只做部位 + 部件（绑定 / 缩放 / 图片处理），不导入骨架也能全程完成，**画布上没有任何骨骼参考点**；需要看映射时在属性页「＋ 导入骨架…」，文件会存进 `projects/<项目>/rig/`，随项目走、只读；
  骨架 ↔ 画布只有一次坐标转换（**默认 root 对齐**：`canvas = root + (spine − anchor) × scale`）
- 部位 = **锚点（中心固定居中）+ 一个 bbox**，bbox 只跟部位自己走，**不再由部件并集推导**
- 加部件时按部位 bbox **自动填充**，并把**部件中心**（不透明范围中心）压到**部位中心**上；
  **超出部位 bbox 的部分不显示（强约束）**，右侧实时显示切合度 / 裁掉比例
- 换装极快：选中部件后点部件库里另一张图即换掉，`[` / `]` 同目录上一张下一张
- 部位锚点库（`anchors/*.json`，**root 坐标，与骨架和画布都无关**）所有人共用，一键载入 / 保存
- 画布下方是**类 Spine 的筛选菜单**：部位 / 部件 / 骨骼 × 编辑 / 显示 / 标签，
  只影响画布显示与交互（不改数据、不影响导出）；关掉部位+部件就能直接点选骨骼
- 默认画布 **4K 方形 4096 × 4096**；改宽以 root 水平中心**向左右对称**伸缩，改高只向上伸缩，
  内容与骨架相对 root 不动
- 导出：`slots.json`（中心点 + bbox + 裁剪框 + 骨骼映射 + 骨架坐标，三套读数）/
  `slots.png` / `atlas.png` `atlas.json` `atlas.atlas`（帧 + 中心点 + clip）/ `report.md` / `preview.png`
- **不导出 Spine 骨架** —— 转成 Spine 骨骼由其他流程处理
- 实测：初始装配与 `assembled.png` 的 alphaIoU = **0.993**，切合度 100%、中心偏差 0、bbox 外像素 0

详见 [`dressup-lab/README.md`](dressup-lab/README.md)。


## 推荐工作流

```
原图 / PSD
   │
   ├─(1) bbox_ref.py ──▶ bbox_ref.png / bbox_schematic.png / bbox_ref.json
   │                      比例参考图：喂给 AI 当比例约束，同时作为人工验收标尺
   │
   ▼
AI 生成「整图 / 拆件图」（部件之间有间隙，背景透明）
   │
   ├─(2) alpha_split.py ─▶ parts/ + parts_full/ + label_map.png + preview.png
   │                      + manifest.json（bbox / 面积 / 质心）
   │
   ├─(3) dressup-lab   ─▶ 部位锚点（中心 + bbox）+ 逐件装配/换装 + 骨架映射预览
   │                      ▶ slots.json / slots.png / atlas.png / atlas.json
   ▼
导入 Spine / Godot（用部位图 + 图集；Spine 骨架由其他流程生成）
```

> (2) 与 (3) 的分工：`alpha_split.py` 负责**确定性拆件**，`dressup-lab` 负责
> **人工把每件的位置/大小/旋转定准并沉淀成资产**（部位锚点 + 图集），
> 这两步都不调用 AI。

---

## 1. `bbox_ref.py`

```bash
python tools/bbox_ref.py spec.json -o out_dir
python tools/bbox_ref.py spec.json -o out_dir --no-base          # 纯线框（喂 AI 用）
python tools/bbox_ref.py spec.json -o out_dir --target-height 2048
python tools/bbox_ref.py spec.json -o out_dir --target-canvas 1024x4450
```

`spec.json`：

```json
{
  "canvas": [385, 1672],
  "base_image": "D:/spine/tmp/head_split/_after_rollback.png",
  "parts": [
    { "name": "head", "bbox": [4, 1, 359, 484], "color": "#e6553d" }
  ],
  "hlines": [ { "y": 442, "label": "shoulder" } ],
  "vlines": [ { "x": 192.5, "label": "center" } ]
}
```

产出：

- `bbox_ref.png` — 半透明底图 + 彩色 bbox + 标签 + 10% 刻度 + 关键横线
- `bbox_schematic.png` — 纯线框比例示意图（无底图，适合直接当 AI 参考图）
- `bbox_ref.json` — 归一化比例（`norm_bbox` 0~1、`h_ratio`、`top_pct` / `bottom_pct`）+ 目标分辨率像素坐标（`target_bbox`）
- `bbox_ref.md` — 同内容的 markdown 表格

**为什么要归一化**：`norm_bbox` / `h_ratio` 与分辨率无关。换任何目标分辨率都只是乘一个缩放系数，
不需要重新测量。`--target-height H` 以「内容总高」为基准等比缩放，是交付时最常用的一种。

---

## 2. `alpha_split.py`

```bash
# 透明背景，直接拆
python tools/alpha_split.py sheet.png -o out --regions regions.json

# 纯色背景，先抠色再拆
python tools/alpha_split.py sheet.png -o out --bg auto --bg-tol 18 --regions regions.json

# 线条可能断开（头发高光、眉毛两笔）→ 闭运算 + 间隙合并
python tools/alpha_split.py sheet.png -o out --close 2 --merge-gap 6

# 归一化到目标分辨率（整体内容高度 = 2048）
python tools/alpha_split.py sheet.png -o out --fit-height 2048
```

### 关键参数

| 参数 | 说明 |
|------|------|
| `--bg auto\|#RRGGBB` | 纯色背景抠色。**只删与画布边缘连通的同色像素**，角色内部恰好同色的区域不会被误挖空 |
| `--bg-tol N` | 背景色容差（欧氏距离）。边缘按各连通域自身色距的 95 分位做 matte 渐变，细线稿不会被削 |
| `--close N` | 形态学闭运算半径，连接断开的线条 |
| `--min-area N` | 最小连通域面积，去噪（默认 24） |
| `--merge-gap N` | bbox 间距 ≤ N px 的连通域合并（同一部件的碎片） |
| `--merge-contained` | 把完全落在更大连通域 bbox 内的小块并入（眼珠 / 高光） |
| `--regions FILE` | **区域归并**：质心落在区域内的连通域合并为同一部件 |
| `--names a,b,c` | 显式命名。数量须等于「部件数」或「未被 regions 命名的部件数」 |
| `--fit-height N` / `--fit-scale X` | 归一化缩放（以整体内容高度为基准） |
| `--sort reading\|area\|x\|y` | 编号顺序 |

### `--regions` 为什么需要

连通域只能按「像素是否相连」判断。双眼、双眉、上下睫毛是**多个独立岛**，
但业务上属于同一个部件。`regions.json` 用一个矩形把若干岛圈成一件：

```json
{
  "regions": [
    { "name": "eye",     "bbox": [800, 0, 1190, 500] },
    { "name": "eyebrow", "bbox": [0, 500, 400, 994] }
  ]
}
```

规则：连通域**质心**落在哪个 region 就归到哪个部件；命中多个时取面积最小的；
未命中任何 region 的连通域各自独立成件。

### 产出

```
out/parts/part_00_hair.png        裁剪到 bbox
out/parts_full/part_00_hair.png   与原画布同尺寸（Spine 导入自动对齐）
out/label_map.png                 彩色索引图
out/preview.png                   标注序号/名字的预览（棋盘格底）
out/manifest.json                 source_canvas / canvas / scale / content_bbox / parts[]
```

### 注意

- **优先让 AI 直接输出透明背景**。把图压到纯色底再抠色会不可逆地丢掉最淡的抗锯齿像素
  （实测一条 1px 细线的 alpha 像素 167 → 69）。`--bg` 只作为兜底。
- 一个连通域 = 一个部件。想让两处内容合成一件，要么让它们**在图上相连**，
  要么用 `--regions` 归并。
- `parts_full/` 是给 Spine 用的：所有部件保留同一套画布坐标，导入后天然对齐。

---

## 3. `fit_parts.py`

按 spec 的原始比例缩放并拼回原画布，输出客观质量分。

```bash
# 默认：每件等比缩放（五官不变形）+ 整体锁定到 spec 的整体 bbox
python tools/fit_parts.py split_run03 --spec spec_head_plan2.json -o fit --auto-match

# 全部部件共用一个缩放（整体轮廓最贴 spec，本轮实测 IoU 最高）
python tools/fit_parts.py split_run03 --spec spec_head_plan2.json -o fit \
  --auto-match --scale-mode uniform

# 逐件完全贴合 spec 尺寸（会拉伸变形，仅用于对照）
python tools/fit_parts.py split_run03 --spec spec_head_plan2.json -o fit --per-part

# 放大到目标分辨率（整身画布 385x1672 -> 内容高 2048）
python tools/fit_parts.py split_run03 --spec spec.json -o fit --target-height 2048
```

### 缩放模式（关键）

AI 给每个部件各自定尺度，所以「摆对位置」和「不变形」需要分开处理：

| 模式 | 行为 | 变形 | 整体 |
|------|------|------|------|
| `aspect`（默认） | 每件按几何平均等比缩放（不变形），再用全局系数把拼合并集 bbox 锁到 spec 整体 bbox | 0 | 贴合 |
| `uniform` | 所有部件共用一个缩放（取自各件尺寸比的中位数） | 0 | 轮廓最贴 |
| `blend` | 对数空间插值：`--aspect-weight t`，0=完全贴合 spec（会变形），1=完全不变形 | 可调 | 随 t |
| `per-part` | sx/sy 各自独立拉成 spec 尺寸 | 大 | 逐件精确 |

`--lock-overall geom|h|w|off`：整体锁定方式，默认 `geom`（宽高折中）。
`--aspect-by area|h|w`：`aspect` 模式下每件按什么对齐 spec。

spec 里可逐件覆盖：`aspect_weight`、`align`、`z`、`area`。

### 其它参数

| 参数 | 说明 |
|------|------|
| `--auto-match` | AI 件名是 `part_00…` 时，按**相对**长宽比 + **相对**面积贪心配对到 spec（含 `_L`/`_R` 按 x 修正） |
| `--anchor NAME` | `uniform` 模式只用该部件估计缩放 |
| `--align` | `center` / `top` / `bottom` / `left` / `right` |
| `--composite-base` | 拼合时保留原图作底 |

产出 `parts_scaled/`、`composite.png`、`compare.png`（左原图/右拼合）、`fit_report.json`。

`fit_report.json` 里的 `score` 是多轮生成之间唯一可比的客观指标：

| 指标 | 含义 |
|------|------|
| `alpha_iou` | 拼合轮廓 ∩ 原图 / 并集 |
| `coverage` | 原图被覆盖比例（漏画会掉） |
| `spill` | 多出来的比例（画歪会涨） |
| `color_mae` | 重叠区颜色平均绝对误差 |

> **面积必须用相对值**：AI 那套部件可能整体按 1.5×/2× 画出来，绝对面积差一个全局常数，
> 直接比会把 hair 和 head_base 配反（实测踩过）。

---

## 4. Meowa（AI 生成）与本流水线的衔接

`game-assets` skill 的 `image-edit-run` 是 **1 图进 → 1 图出**，且模型会**重绘轮廓并重新取景**
（实测同一输入两次输出的主体位置/比例都不同）。因此：

- ❌ 不要把 AI 输出「对齐回原图」——注册误差不可控
- ✅ 让 AI 出一张**完整的拆件图**（部件分开、有间隙、透明背景），
  再用 `alpha_split.py` 按 alpha 拆件。这样 AI 只需负责「画对比例」，
  拆件和对齐全部由确定性算法完成

对应的提示词要素：给出 `bbox_ref.png` 作参考 + 明确「部件之间留出明显间隙」+
「背景完全透明」+「不要改变画布尺寸和主体位置」。




