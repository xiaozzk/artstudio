# `assets/3d/rig/garments/` —— **当前交付件：4 个自包含角色（B2 路线）**

> 契约：[`../SPEC.md`](../SPEC.md)（**唯一权威**）｜pipeline 指南：[`../README.md`](../README.md)
> 复杂度结论：[`../../../../task/007-morph-pipeline/verify/COMPLEXITY.md`](../../../../task/007-morph-pipeline/verify/COMPLEXITY.md)

## 每个文件**本身就是一个完整角色**

**恰好 1 副骨架** + 8~12 件网格（服装布料 + 服装自带皮肤 + 基础体的头），
**每一件网格都持有 `Basis` / `BS_Thin`(索引 0) / `BS_Heavy`(索引 1)** —— 名称与索引是**硬契约**。

| 文件 | 骨架 | 网格 | 顶点 | morph(2 档) | 身高比 Thin/Heavy |
|---|---|---|---|---|---|
| `Female_Ranger.blend` | **1** | 12 | 27,920 | 654 KB | 0.99891 / 1.00143 |
| `Male_Ranger.blend` | **1** | 12 | 27,637 | 648 KB | 0.99997 / 1.00020 |
| `Female_Peasant.blend` | **1** | 8 | 16,376 | 384 KB | 1.00019 / 0.99975 |
| `Male_Peasant.blend` | **1** | 8 | 12,376 | 290 KB | 0.99999 / 1.00002 |

体形档位（**冻结**）：`thin 0.84` / `heavy 1.21`，`coefficients_fingerprint = ca93ef91…821ba2`。
数据量恒等于 **顶点数 × 12 B × 档数**。

## ⚠ 用法硬约束

1. **一套 = 一个角色，直接加载这一个文件即可** —— **不要**再额外加载 [`../bodies/`](../bodies/) 下的标准体。
   多叠一具身体会**立刻出橙斑**（`verifier` 的四装配对照有图：干净的 [`t3int_P1_b2_character_only_Basis.png`](../../../../task/007-morph-pipeline/verify/renders/t3int_P1_b2_character_only_Basis.png)
   vs 出橙斑的 [`t3int_P3_b2_plus_standard_body_Basis.png`](../../../../task/007-morph-pipeline/verify/renders/t3int_P3_b2_plus_standard_body_Basis.png)）。
2. **身高走"角色根节点/骨架对象的世界等比缩放"**，**不是** `root` 骨缩放（后者与本套件的 `inherit_scale` 规则冲突）。
3. **取骨一律 `find_bone("Head")` 按名字** —— **索引取决于「该文件里的骨层级 DFS 顺序」，跨文件不可复用**（008 做过决定性实验：把真 glb 的 `skin.joints` **整段倒序**、nodes 与层级不动 → Godot 的骨顺序**一位没变**（`Head` 仍 54）⇒ **Godot 既不读 `skin.joints` 数组、也不读 `nodes` 数组顺序，只读骨层级**）。
   实测：**Blender 打开 `.blend` → `Head = 6`**；**本项目的 glb 在 Godot 里 → `Head = 54`**（6/6 一致）。
4. **预览/加载请走工具**：[`tools/3d/godot/preview/`](../../../../tools/3d/godot/preview/README.md) 的 `run.sh`（工程内零素材副本）。

## 复现

```bash
# 全部重出（~3 分钟，含偏斜守卫：读系数源记指纹、写产物前再校验，变了就报错退出）
python3 tools/3d/garment/build_all.py
```

入口脚本：[`build_all.py`](../../../../tools/3d/garment/build_all.py)｜B2 主实现：[`derive_on_character.py`](../../../../tools/3d/garment/derive_on_character.py)

## `B1_superhero_standard/` = **已归档的参考产物**

B1/A 路线的旧产物（**不含身体**，要另加载标准体才能看）。**默认不使用** ——
原因、边界与"什么时候会重新需要它"见 [`B1_superhero_standard/README.md`](B1_superhero_standard/README.md)。

> 一句话：**只有需要"裸露躯干"的服装（泳装 / 裸露护甲）时才回到 B1**，因为那时布料不包住躯干、
> 体形变化没有载体。Tripo 阶段若做到"先生成唯一标准体、再以它为基准裁衣服"，**B1 与 B2 会收敛为同一件事**。