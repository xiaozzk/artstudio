# Spine 部件换皮流水线（mask 局部重绘 → 新组件 → 换皮回验）

**目标**：给一套 Spine 素材**换风格**（换武器 / 换装 / 换材质），产出**能直接顶替原附件**的新部件。
纯本地部分（定位 / 抠底 / 排布 / 回验）全部免费；只有"让模型出图"那一步花钱。

本文是 2026-09-21「武僧换武器 MVP」跑通后的沉淀，工具都在 `tools/`，实测数据见文末。

## 一、先记住四条实测结论（都踩过）

1. **mask 不是硬边界**。实测 mask 只覆盖 2.91% 画面时，生成图里 **mask 外 30.6% 的像素也被重画了**
   （另一只手的武器直接被抹掉）。所以：
   - 「只换一个部位」→ 生成后**只把 mask 内的改动贴回原图**（`apply` 语义），漂移全部丢掉；
   - 「做新组件/整体换皮」→ **别从整图里抠组件**（不裁就带背景，裁了就挖缺口），直接走下面的"部件单独重画"。
2. **`background=transparent` 会被网关掐断连接**（`RemoteDisconnected`，不是 4xx，连试 3 次都断）。
   要透明件：`--background opaque` + prompt 要**纯色底**（推荐纯洋红 `#FF00FF`），本地抠底。
3. **JSON(base64) 编辑通道对 gpt-image-2 恒 500** → 真机一律 `--transport multipart`。
4. **key 分两类**：`sk-mg-` 是管理型 key（只能查余额/用量），打模型接口一律 403；生图要用普通 key。

## 二、五种工具，各管一段

| 工具 | 管什么 | 花不花钱 |
|------|--------|----------|
| `parts_sheet.py` | 把部件摆成**互不重叠、相邻 ≥N px** 的参考图（喂模型当"这些是独立零件"） | 免费 |
| `spine_part_swap.py locate` | 在复原预览图上定位某个插槽的**可见区域** → mask + 尺寸 + 附件四边形坐标 | 免费 |
| `spine_part_swap.py verify` | 把新附件换进去重渲 → 量化"改了哪、有没有波及别处"（远处必须 0px） | 免费 |
| `flatbg_cut.py` | 纯色底**抠成透明件** + 按参考部件 **alpha 最大 XY 等比缩放贴合** | 免费 |
| `zenmux_edit.py` | 调模型出图（mask 局部重绘 / 部件单体重画） | **花钱** |

## 三、标准流程（以"换武器"为例）

```powershell
# 0) 侦察：部件清单 + 预览复现（确认坐标可信）
python tools/spine_part_swap.py locate --json assets/武僧/monk.json `
    --images assets/武僧/images_original --preview assets/武僧/复原预览图_1.png `
    --skin 1 --slot weapon_1 --out-dir tmp/reskin
# → mask_weapon_1_visible.png（要重绘的区域）、geometry_weapon_1.json（四边形/缩放/f）

# 1) 参考图1：部件分离版（相邻间隔 ≥20px，模型才知道是几个独立零件）
python tools/parts_sheet.py --from-dir assets/武僧/images_original --out tmp/reskin/parts_sheet.png `
    --gutter 20 --json-out tmp/reskin/parts_layout.json

# 2) 参考图2：风格参考（新风格长什么样）
# 3) 出图（两条路线，选一条）—— 默认就走 SSE 流式，连接不容易被网关掐断
#   3a. 只换一个部位（整图 mask 编辑）
python tools/zenmux_edit.py edit --image assets/武僧/复原预览图_1.png --image tmp/reskin/parts_sheet.png `
    --image tmp/reskin/style_ref.png --mask tmp/reskin/mask_weapon_1_visible.png --mask-grow 2 `
    --prompt "..." --model openai/gpt-image-2 --size match --quality high --background opaque `
    --transport multipart --out-dir tmp/reskin/run1
#   3b. 做新组件（部件单体重画；推荐，组件天生干净）
python tools/zenmux_edit.py edit --image tmp/reskin/part_weapon11_x4.png --image tmp/reskin/style_ref.png `
    --prompt "Redraw this single part ... flat solid magenta background FF00FF, no hand, no character" `
    --model openai/gpt-image-2 --size match --quality high --background opaque `
    --transport multipart --out-dir tmp/reskin/run2

# 4) 抠底 + 缩放贴合（产出可直接顶替原附件的透明件）
python tools/flatbg_cut.py --in tmp/reskin/run2/part-edit.png --out tmp/reskin/weapon_11_new.png `
    --fit-to assets/武僧/images_original/weapon_11.png --json-out tmp/reskin/component_stats.json

# 5) 换回骨架回验（远处必须 0px，否则说明尺寸/挂点不对）
python tools/spine_part_swap.py verify --json assets/武僧/monk.json `
    --images assets/武僧/images_original --preview assets/武僧/复原预览图_1.png --skin 1 `
    --part weapon_11=tmp/reskin/weapon_11_new.png --out-dir tmp/reskin
```

**装配**：新附件尺寸 = 原附件画布（例：106×115），alpha 占位中心对齐原占位中心，
所以 UV / 挂点 / 图集区域都不用改；要真正入库就用 `tools/repair_spine/pipelines.py` 重打包图集
（本流程只产出新附件，**不擅自覆盖 `images_original/`**）。

## 四、缩放贴合的算法（`flatbg_cut.py --fit-to`）

```
原部件 alpha 最大 XY  = (ow, oh)     # 例 104×113
生成件 alpha 最大 XY  = (nw, nh)     # 例 632×699
缩放比 k = min(ow/nw, oh/nh)         # 等比，避免拉伸变形（例 ×0.1617）
缩放后把 alpha 占位中心对齐到原占位中心，贴进原画布尺寸
```

抠底用"到底色的 RGB 距离"做软阈值，再按 `前景 = (观测 − (1−a)·底色) / a` **反混合**去边，
所以任何纯色底都能用，边缘不会留彩边。

## 五、MVP 实测数据（武僧 · 复原预览图_1 · weapon_1）

| 指标 | 值 |
|------|-----|
| 预览复现 | 646×892，RGB 平均差 0.629（几何可信） |
| 武器可见区 | 16,754 px（占画面 2.91%），包围盒 213×232 @ x[119,331] y[499,730] |
| 附件四边形 | 预览像素 (118.6,500)-(330.6,730)，轴对齐 → 缩放比 f=2.0，纯缩放无旋转 |
| 原附件 | 106×115，alpha 占用 104×113 |
| 部件单体重画 | 输入 424×460（原部件 ×4）→ 出图 784×848，**6871 tokens / 113s** |
| 抠底结果 | alpha 632×699 → 等比 **×0.1617** → 106×115 新附件 |
| 换皮回验 | 改动 14,500 px，单簇集中在武器位；**主簇外 0 px** ✅ |
| 整图 mask 编辑（对照） | 6,566 tokens / 103s；mask 外漂移 30.6%（需 apply 回贴） |
| 单次成本 | **别按订阅详情里的 `base_usd_per_flow = $0.03283` 估图片编辑** —— 那是文本 flow 的价。实测一次编辑 **$0.15~0.18**（`image_output` 占 94%）。要精确对账：`python tools/zenmux_edit.py cost --models openai/gpt-image-2`（免费） |
| **被掐断的请求照样计费** | 实测那一轮 **7 次请求全计费 = $1.2009**，但只有 2 次拿到了图：<br>· 02:58 latency 364.7s / $0.151170 ← 客户端被掐断，**服务端跑完照扣**<br>· 03:12/03:14/03:16/03:18 latency 186~194s / 各 $0.179710 ← `background=transparent` 的 4 次（1 次原始 + 3 次重试）**全部计费**<br>· 03:01 / 03:20 是真正拿到图的 2 次<br>→ **白烧 $0.87（占 72%）**。所以：① 别用 transparent；② 被掐断**不要自动重试**（工具已默认不重试，要重试得 `--retry-on-drop`）；③ 想确认就把 `cost` 按小时桶拉出来看 |

## 六、坑与对策

| 现象 | 对策 |
|------|------|
| `RemoteDisconnected` | 多半是 `--background transparent`；改 opaque + 纯色底。多图 multipart 偶发，`--retries 2` 能过 |
| mask 外被大改 | 正常现象（见结论 1）；不要指望 mask 锁边界 |
| 组件带背景 / 有缺口 | 别从整图里抠；走"部件单体重画 + 抠底" |
| 模型把部件画小了/画歪了 | 不用重跑：`flatbg_cut.py --fit-to` 按 maxXY 缩放 + 中心对齐就能贴合 |
| 回验时远处有改动 | 尺寸/挂点没对上——检查是否用了**原附件画布尺寸**、是否按 alpha 占位中心对齐 |
