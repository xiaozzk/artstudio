# tools/3d/godot/preview/probes/ —— **Godot 骨骼陷阱探针**（可复跑）

> 这几个探针把三个**只在引擎里才暴露**的坑变成**可一键检出的检查**。
> 它们不是预览页面的一部分，而是"下次有人写骨骼逻辑时别再踩"的工具。
> 契约依据：`assets/3d/rig/SPEC.md` **F30**（A1–A4）；证据与原始输出在 `task/007-morph-pipeline/verify/godot_probe/`。

## 三个坑（以及为什么它们难）

| # | 坑 | 实测证据 | 规则 |
|---|---|---|---|
| **A1** | **`set_bone_pose_rotation()` 只在骨架【已入树】之后设才有效**；入树前设的值**不会追溯生效** | V1–V4 对照：V3 差 `0.000000`/`0.0°`（无效）；V4 差 `1.488280`/`90.0114°`（生效）；**V1≡V2 说明未 priming 的缓存会粘住假值** | pose 只在入树后设，**设完立刻断言**（`on_attached()` 是**必需**，不是防御）；**不要在入树前读 `get_bone_global_pose()`** |
| **A2** | **glTF 骨架的 pose 空间与直觉不符** —— `pose_local = rest⁻¹·R·rest` 的共轭写法推不出想要的方向 | 共轭写法偏 **165.9°**（另一实现 60.1°，目标轴不同）；`set_bone_global_pose_override()` 偏 **0.0°** | 需要精确姿态时用 **`set_bone_global_pose_override()`**（注意它是**绝对**的，父骨 pose 缩放不传递）；否则**从子骨位置反推方向**再下达 |
| **A3** | **`MeshInstance3D.get_aabb()` 是静止(rest)网格 AABB** —— 不含蒙皮、不含姿态、**也不含 blend shape** | 转骨 90° 与设 `BS_Thin=1` 后 **逐位不变** | 取景 / 剔除 / 包围盒**不能**拿它当"形变+姿态之后"的结果 |
| **A4** | **别凭"绕某轴转 N 度"的直觉写骨骼旋转** —— 骨局部轴不与世界轴对齐（约 60° 偏差） | 由 A2 推出 + 独立数字 | 同上 |

⭐ **两个"测量陷阱"**（都真实发生过，各骗过一个人）：① **`Basis.get_euler()` 在万向节锁下骗人**（本骨架 `upperarm_l` 的 rest 在 Z 轴 −90°，差别很大的旋转会打印出**几乎相同**的欧拉角）；② **未 priming 的缓存骗人**（入树前读 `get_bone_global_pose()` 会返回"看起来合理但并非生效姿态"的矩阵，**且入树后不刷新**）。
→ **比较骨骼姿态禁用 euler，要比 `basis` 矩阵或方向向量。**

## 探针

| 文件 | 作用 |
|---|---|
| `a1_v1v4.gd` | **A1 的决定性对照**（V1–V4 四个变体）；也是 `independent_conflicts` 收口的依据 |
| `a1_noeuler.gd` | 同一问题、**改用 basis 矩阵/方向向量**（不碰 euler）——用来证明上一版是被万向节锁骗的 |
| `probe.gd` / `probe2.gd` | **A2 / A3** 的探针 |
| `project.godot` | 独立最小工程（不自包含素材：运行时从绝对路径读 `assets/3d/rig/garments/*.blend` 的 glb 缓存） |

## 跑法

```bash
# 冷缓存需要先生成 glb（预览页面的 run.sh 会做，缓存到工程外的 tmp/）
tools/3d/godot/preview/run.sh --interactive   # 或先跑一次 run.sh 生成缓存

/Applications/Godot.app/Contents/MacOS/Godot --path tools/3d/godot/preview/probes \
    -s res://a1_v1v4.gd
```

⚠ **探针存图一律用绝对路径** —— Godot 的工作目录**就是工程根**，写相对路径会把图**落进工程内部**，从而**悄悄证伪"工程内零素材副本"这句交付声明**（本任务真实发生过，靠交付前自查才发现）。交付前请跑：
```bash
find tools/3d/godot/preview -type f \( -name '*.png' -o -name '*.glb' -o -name '*.pyc' -o -name '_probe*' \)
# 必须为空
```

> **为什么这些探针值得留着**：A1 那条结论走过「成立 → 自己误撤回 → 又回到成立」，
> 而**两次误判各来自一个不同的测量陷阱**，且**两个不同的人被同一个静默缓存各骗了一次 —— 两次都没报错、没崩溃**。
> 结论只在这套骨架上验证过，但**规则可迁移**。