# tools/ — 本地图片与部件处理工具

**纯本地、确定性、不消耗 AI 额度。** 与具体引擎无关，服务于「生图 → 切件 → 贴图处理」这一段。

## 依赖

```
python -m pip install numpy pillow opencv-python
```

## 工具一览

| 工具 | 作用 |
|------|------|
| `bbox_ref.py` | 由 bbox 规格生成「比例参考图」（喂 AI 当比例约束 / 当人工验收标尺），并把比例换算到任意分辨率 |
| `alpha_split.py` | 按 alpha 连通域把一张整图拆成多个部件（可选纯色底抠色、闭运算、区域归并） |
| `fit_parts.py` | 把 AI 拆出的部件按 spec 比例缩放、拼回原画布，并给出客观质量分（`alpha_iou` / `coverage` / `spill` / `color_mae`） |
| `slice-sheet.py` | 把整张部件拼图切成部件贴图（含隐形脏像素清理 + 同口径体检）→ 见 [`slice-sheet.md`](slice-sheet.md) |
| `outline-part.py` | 给皮肤件补**内描边**（只改 RGB，不动 alpha）；幂等，写 PNG `tEXt` 标记 `SpineOutline` |
| `outfit-split.py` | 把服装拆件拼图切成可换装件（输入为纯灰底 205） |
| `image_parts_tool.py` | 部件边缘精修一体化：`analyze` / `cut` / `prep` / `prompt` / `gen` / `verify` / `apply` / `report` / `diff` / `overview` |
| `ps_cut/fill_from_layer1.jsx` | PS 内一键补缺口（文件 > 脚本 > 浏览） |

## 子目录

| 目录 | 用途 |
|------|------|
| `browser/` | **浏览器登录态复用（CDP 副本）** —— 借日常浏览器的登录态做自动化，用完销毁。与图片管线无关，见 [`browser/README.md`](browser/README.md) |

## 通用约定

- **优先让 AI 直接输出透明背景**。把图压到纯色底再抠色会不可逆地丢掉最淡的抗锯齿像素
  （实测一条 1px 细线的 alpha 像素 167 → 69）。`--bg` 只作为兜底。
- **面积比要用相对值**：AI 那套部件可能整体按 1.5× / 2× 画出来，绝对面积差一个全局常数，
  直接比会把 `hair` 和 `head_base` 配反（实测踩过）。
- 部件贴图统一**保留同一套画布坐标**，换任何目标分辨率都只是乘一个缩放系数。

> **数据格式标识符**（`spine-outfit-split`、`spine-part-outline`、`spine-dressup-lab-sheet-parts`、`SpineOutline`）
> 是已生成产物里写死的字符串，改名会破坏与既有产物的兼容，因此保留原样。
