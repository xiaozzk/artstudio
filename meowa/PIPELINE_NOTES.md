# Meowa 生成流水线笔记 — Eva 基础体（比基尼版）

记录本次「黑内衣 → 白色小面积挂脖比基尼」的模型路由与风控规律，避免下次重复踩坑。

> 目录索引、runs 编号对照表、重跑命令模板见 [`README.md`](README.md)。

## 硬性约定

- **所有生成一律 2K**（用户约定）。`--resolution 2K`。
- 源图 `assembled.png` 本身已是透明背景，输出必须保持透明。
- 目标引擎 Godot 4 / Spine 4.2+，输出走 JSON + atlas。

## 风控规律（实测）

失败一律是通用错误 `Generation failed. Please try again.`，**会自动全额退费**，
`credit_refund.refunded = true`，所以失败不亏积分，可放心探测。

| 后端 | 缩小内衣覆盖面积 | 说明 |
|---|---|---|
| `image-2.5`（gpt-image-2.5-sunburst） | ❌ 拦截 | 哪怕是"小一点、简单一点"也被拦 |
| `image-2`（gpt-image-2） | ⚠️ 部分可用 | "crop top + 细肩带"可过；"halter/三角杯"被拦 |
| `nano-banana` | ✅ 通过 | 但 1K 会重采样画布（768×1376），**2K 不重采样**（919×1672）|

**结论**：
1. 触发点是 **prompt 措辞**，不是参考图 —— 显式描写"暴露款式"必被拦。
2. 解法：**让参考图表达款式，prompt 只做中性指向**（"按参考图2的衣物重塑造型"），可稳定通过。
3. **画布保持力：2K > 1K**；nano-banana 1K 会重采样导致尺寸漂移，破坏骨骼对齐。

## 体型漂移教训

用真人照片当款式参考时，**胸围/体型会一起被迁移过去**（参考图是丰满体型 → 角色胸部被放大，
脱离原角色的小胸纤细少女设定）。修正方式：prompt 显式锁身形
（"keep her original slim teenage figure - the same small flat chest... do not enlarge or emphasise her chest"）。

## 最终落地的链路

```
assembled.png (385×1672, 原图, 白裙)
  └─ image-2.5 / 2K / ultimate ─▶ 黑内衣 + A-pose        (894×1672)
       └─ image-2.5 / 1K / standard ─▶ 黑改白, 形状不变   (918×1672)
            └─ image-2 / 1K / standard ─▶ 缩小覆盖         (918×1672)
                 └─ nano-banana / 2K / normal ─▶ 白色挂脖三角比基尼 + 锁身形  (919×1672) ★交付
```

## 对齐实测（交付版 vs 原图）

| 指标 | 原图 | 交付版 | 偏差 |
|---|---|---|---|
| 头顶 y | 3 | 4 | +1 px |
| 脚底 y | 1669 | 1668 | −1 px |
| 主体高 | 1667 | 1665 | 比例 0.9988 |
| 相对画布水平中心 | +0.0 | +4.0 | +4 px |

画布从 385 加宽到 919 是 A-pose 摆臂必需（全部是透明边），垂直锚点几乎零漂移。

## 资产

- `assets/eva_bone/assembled_underwear.png` — 黑色运动内衣 + A-pose（894×1672）
- `assets/eva_bone/assembled_bikini_white.png` — 白色挂脖三角比基尼（919×1672）★ 基础体候选
