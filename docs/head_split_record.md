# 头部拆分记录（assembled.psd）

> 目标：把 `assembled.psd` 的单个 `head` 图层拆成 **发型 / 头型（含颈部）/ 眼睛 / 嘴巴 / 眉毛** 五个独立部件，供 Spine 换装与表情切换使用。
> 路线：**混合法** —— 需要生成式补全的交给 Meowa 万能编辑（`image-edit-run`），五官用像素级遮罩提取。

## 1. 最终图层结构（assembled.psd，自上而下）

| 顺序 | 图层名 | 来源 | 内容包围盒 |
|------|--------|------|------------|
| 1 | `hair` | Meowa 生成 | `[5, 0, 359, 453]` |
| 2 | `eyebrow` | 原图像素 + 遮罩 | `[176, 220, 338, 249]` |
| 3 | `eye` | 原图像素 + 遮罩 | `[174, 243, 337, 308]` |
| 4 | `mouth` | 原图像素 + 遮罩 | `[246, 338, 268, 351]` |
| 5 | `head` | Meowa 生成（完整光头基底） | `[67, 77, 336, 491]` |
| — | `head_original` | **原图层，已隐藏保留作备份** | `[4, 1, 359, 484]` |

Z 轴依据：原图中头发压在脸部外眼角之上，因此 `hair` 必须在 `eye` 之上；被头发遮住的五官外溢部分自动被覆盖，无需精确裁掉。

## 2. Meowa 调用参数与实测成本

两次成功调用均为：

```
image-edit-run
  --mode hd --generation-model image-2
  --resolution 2K --quality standard
  --remove-bg-method standard
  --reference-image tmp/head_split/head_source.png
```

| 调用 | 输出尺寸 | 实际扣费 |
|------|----------|----------|
| 发型隔离 | 385 × 509 | 11 积分 |
| 头型基底 | 385 × 501 | 11 积分 |
| **合计** | | **22 积分** |

**成本构成（实测）**：2K standard 基础 2 + 参考图 2 + 去背景 5 = **11 积分/次**。
> 注意：skill 文档给出的「2K standard = 2 分」公式**漏算了去背景的 5 分**，预算时须按 11 分/次计算。

## 3. 对齐校正数据（实测，非估算）

用「隔离结果与原图同坐标像素的平均色差」做判据，网格搜索偏移与缩放：

| 部件 | dx | dy | scale | 判定依据 |
|------|----|----|-------|----------|
| 发型 | **0** | **-5** | **1.000** | 校正前色差 33.68 → 校正后 12.31 |
| 头型基底 | 1 | 3 | 0.990 | 仅微弱改善，且基底脸型本身偏大（见第 5 节） |

结论：**万能编辑在水平方向零偏移、零缩放，只产生约 5px 的垂直漂移**，可用色差搜索确定性校正。

## 4. 五官提取方法（纯 PS/像素级，0 积分）

原画是平面动漫上色，可用确定性的像素方法提取，无需生成式：

1. **皮肤参考色**：取纯肤色区 `x[190,270] y[302,312]` 的中位数 → `RGB(225, 204, 196)`
2. **色距阈值**：`dist(RGB, 参考色) > T` 即判为特征（眉毛 T=26，嘴 T=26）
3. **眼睛**：改用「暗像素（`max(RGB)<150`）的**凸包**」——睫毛与眼线构成近似凸形轮廓，凸包可完整覆盖眼白与虹膜，避免颜色阈值抓不住浅色眼白的问题（眼白与肤色色距仅 46，曾导致眼睛出现空洞）
4. **发色排除**：发色判据 `G-B>8 且 R-G<20 且 max>120`，膨胀 4px 后排除，避免发锁黑边混入五官遮罩
5. **边缘羽化**：`gaussian(sigma=0.9) × 1.35`，减轻与 AI 基底的接缝

提取结果：

| 部件 | 遮罩像素 | 包围盒 |
|------|----------|--------|
| 眼睛（左右合计） | 5177 | `[174,243,337,308]` |
| 眉毛（左右合计） | 1189 | `[176,220,338,249]` |
| 嘴巴 | 73 | `[246,338,268,351]` |

## 5. 验收与已知问题

**合成验收**：`head` + `eye` + `mouth` + `eyebrow` + `hair` 五层叠合后与原图对比，全图平均色差 **11.14**，脸区 **13.51**——与 AI 重绘产生的轮廓级噪声同一量级，视觉上完整复原原角色外观。

**已知问题（需要你判断是否进一步处理）**：

1. **AI 头型基底的脸型比原图偏大偏圆**（色差 44，明显高于发型的 12）。因为它必须在「头发轮廓内」凭空造出一个光头，模型扩大了颅骨。合成后额头区域比原图宽，下颌也更饱满。
2. **AI 是「重绘轮廓」而非像素级抠图**：差异热图显示差异全部压在边缘线上，发丝走向、高光位置与原图不完全一致。
3. **AI 基底的颈部/肩线与 `torso` 图层可能不完全衔接**（基底自带颈肩，与躯干层在 y≈442 处重叠）。
4. 万能编辑**无法一次拆多件**，5 个部件需要 5 次独立调用，各自位移量未必相同，必须逐件测量校正。

## 6. 关键约束（踩坑记录）

| 现象 | 说明 |
|------|------|
| `--remove-bg-method advanced` 报错 | **HD 编辑只支持 `none` / `standard`**，契约 JSON 未体现该限制，以运行时校验为准。快速失败，不扣费 |
| 契约 JSON 说 `advanced` 仅 image-2.5 不可用 | 与实际运行时不符，**不要信文档，信运行时** |
| 输出画布高度会变 | 500 → 509 / 501，宽度不变；必须裁回并做 dy 校正 |
| `.env` 位置 | runner 依次查找 `cwd/.env`、skill 目录 `.env`、skill 上级目录 `.env` |

## 7. 产物清单

```
tmp/head_split/
├── head_source.png              导出的 head 图层源图（385×500，含 alpha）
├── .env                         Meowa 认证（tmp/ 已被 .gitignore 忽略）
├── parts/                       ★ 5 个部件成品（385×500，含 alpha）
│   ├── part_hair.png
│   ├── part_head.png
│   ├── part_eye.png
│   ├── part_eyebrow.png
│   └── part_mouth.png
├── hair_aligned.png             发型（已应用 dy=-5 校正）
├── head_base_aligned.png        头型基底（已对齐）
├── feature_masks.npz            五官单通道遮罩（可直接复用）
├── _layers_stacked.png          五层叠合验证图
├── _sbs_composite.png           原图 | 合成 | 差异热图
└── out_hair_run02/ out_headbase_run01/   Meowa 原始输出与 final_outputs.json
```

## 8. 复现命令

```powershell
# 从含 .env 的目录执行
cd D:\spine\tmp\head_split
python "C:\Users\xiaozzk\.agents\skills\game-assets\meowart_api.py" image-edit-run `
  --reference-image "D:\spine\tmp\head_split\head_source.png" `
  --prompt "<提示词>" `
  --mode hd --generation-model image-2 --resolution 2K `
  --quality standard --remove-bg-method standard `
  --output-dir "D:\spine\tmp\head_split\out_xxx"
```

眼睛凸包提取：`extract_final2.py`；部件生成：`make_parts.py`；对齐测量：`diag_align3.py`（发型）、`align_base.py`（头型）。
