# ⚠ `B1_superhero_standard/` —— **已归档的参考产物，不要在流程里使用**

> **当前生效的交付件在上一层目录**：[`../Female_Ranger.blend`](../Female_Ranger.blend)、
> [`../Male_Ranger.blend`](../Male_Ranger.blend)、[`../Female_Peasant.blend`](../Female_Peasant.blend)、
> [`../Male_Peasant.blend`](../Male_Peasant.blend)（**B2 路线，自包含角色**）。
> 本目录是 **B1/A 路线的旧产物**，**默认不使用**。

## 它是什么

这 4 份 `.blend` 是 **B1 路线**的产物：把服装**剥离皮肤面**后**贴合到一具独立的 Superhero 标准体**上，
再**跨网格传递** morph。每份**不含身体**（身体要另外加载 [`../../bodies/`](../../bodies/) 下的标准体）。

## 为什么不用它（实测结论，别重新论证）

| 问题 | 实测 |
|---|---|
| **A 路线（现标准体硬贴合 + 自动外推）** | 像素法：裸露身体 女 **63.34%** / 男 **74.21%**；自动外推后**只降到 44%** ⇒ **被否决**（SPEC F16 / D13） |
| **它必须与一具身体拼装才能看** | 而 B2 的角色**本身就是完整角色**（自带 rig + 布料 + 皮肤 + 头，**恰好 1 副骨架**）⇒ 少一个对象、少一处接口 |
| **误用会直接出橙斑** | `verifier` 的四装配对照证明：**B2 角色之上再叠一具标准体 → 大腿大片橙斑**，见 [`t3int_P3_b2_plus_standard_body_Basis.png`](../../../../../task/007-morph-pipeline/verify/renders/t3int_P3_b2_plus_standard_body_Basis.png)（对照：[`t3int_P1_b2_character_only_Basis.png`](../../../../../task/007-morph-pipeline/verify/renders/t3int_P1_b2_character_only_Basis.png) 是干净的） |
| **§4.2 传递口径仍欠定义** | `garment` 与 `verifier` 两个独立实现在**远绑定顶点**上差 **1.11 cm**，而**两者都符合字面描述**（SPEC **F20**）⇒ 走 B1 之前**必须先把口径写死** |

## 什么时候会重新需要它

**只有一种情况**：需要**"裸露躯干"的服装**（泳装 / 裸露护甲）—— 那时布料不包住躯干，**体形变化没有载体**，
B2 无解，必须回到 B1（见 [`../../SPEC.md`](../../SPEC.md) §4.0 的路线决策表与边界）。

**Tripo 阶段会怎样**：**同源之后 B1 与 B2 收敛为同一件事** ——
只要"先生成唯一标准体、再以它为基准生成/裁剪服装"，那具身体就同时是服装的基准，
不会再出现"身体与服装体形基准不一致"。见 [`../../README.md`](../../README.md) 的 §7.7。

## 相关工具（同属 B1，一并归档）

[`tools/3d/garment/`](../../../../../tools/3d/garment/) 下的 `strip_skin.py` / `refit.py` / `transfer_morph.py` /
`autofit.py` / `assemble.py` / `verify_fit_b1.py` —— **B1 专用**，
已在 [`garment/README.md`](../../../../../tools/3d/garment/README.md) 标注为"已被否决，保留给 Tripo 阶段参考"。

**当前主路线（B2）的实现**是 [`derive_on_character.py`](../../../../../tools/3d/garment/derive_on_character.py)
（**不做**剥离 / 贴合 / 传递），入口是 [`build_all.py`](../../../../../tools/3d/garment/build_all.py)。