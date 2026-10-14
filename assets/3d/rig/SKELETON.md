# 骨架契约 —— 65 骨通用人形（`humanoid_biped_65`）

> **来源**：Quaternius **Universal Base Characters**（CC0 1.0）。
> **已核实**：`skin[0].joints = 65` —— 65 根是**源文件就这么定义的**，不是导出/导入器的产物。
> `_leaf` 后缀、`Head` 的大写 H，**在源 glTF 里原本就是这个名字**。
> 本仓库 **24/24 资产**共用这一套骨名与顺序（`SPEC.md` **F1**）。

---

## 1. 完整清单（65 根，按层级）

```
root                                    ← 唯一根骨
└── pelvis                              [躯干 5]
    ├── spine_01
    │   └── spine_02
    │       └── spine_03
    │           ├── clavicle_l          [左臂 24，含手]
    │           │   └── upperarm_l
    │           │       └── lowerarm_l
    │           │           └── hand_l
    │           │               ├── index_01_l → index_02_l → index_03_l → index_04_leaf_l
    │           │               ├── middle_01_l → middle_02_l → middle_03_l → middle_04_leaf_l
    │           │               ├── pinky_01_l → pinky_02_l → pinky_03_l → pinky_04_leaf_l
    │           │               ├── ring_01_l → ring_02_l → ring_03_l → ring_04_leaf_l
    │           │               └── thumb_01_l → thumb_02_l → thumb_03_l → thumb_04_leaf_l
    │           ├── clavicle_r          [右臂 24，与左完全镜像]
    │           │   └── upperarm_r → lowerarm_r → hand_r → {index,middle,pinky,ring,thumb}_*_r
    │           └── neck_01             [颈头 2]
    │               └── Head
    ├── thigh_l                         [左腿 5]
    │   └── calf_l
    │       └── foot_l
    │           └── ball_l
    │               └── ball_leaf_l
    └── thigh_r                         [右腿 5，与左完全镜像]
        └── calf_r → foot_r → ball_r → ball_leaf_r
```

## 2. 组成（65 = 5 + 2 + 24×2 + 5×2）

| 段 | 根数 | 明细 |
|---|---|---|
| **躯干** | **5** | `root`、`pelvis`、`spine_01`、`spine_02`、`spine_03` |
| **颈头** | **2** | `neck_01`、`Head` |
| **单臂（含手）** | **24** | `clavicle`→`upperarm`→`lowerarm`→`hand`（4）+ 5 指 ×（`_01`,`_02`,`_03`,`_04_leaf`）（20） |
| **单腿** | **5** | `thigh`→`calf`→`foot`→`ball`→`ball_leaf` |
| 合计 | **65** | 5 + 2 + 24×2 + 5×2 |

**手部保真度**：每指 **3 个真实关节 + 1 个末端标记**（`_04_leaf`）。末端标记不承载形变，只为骨链收尾。

## 3. ⚠ 腿骨叫 `calf_*`，**没有** `shin_*`

这是实际踩过的坑（`shin_l/shin_r` 不存在，查询会静默拿不到骨）。取骨**一律按名**，别按记忆。

---

## 4. 是"通用标准"吗？—— 分三层看，答案不同

**没有唯一的通用标准。** 但三层要分开评价：

### 4.1 命名约定 —— ✅ **对齐 Unreal Engine 4/5 Mannequin 风格**

| 本仓库 | Unreal Engine | Mixamo | Unity Humanoid（语义） | VRM |
|---|---|---|---|---|
| `root` | `root` ✅ | — | — | — |
| `pelvis` | `pelvis` ✅ | `Hips` | Hips | `hips` |
| `spine_01..03` | `spine_01..03` ✅ | `Spine`/`Spine1`/`Spine2` | Spine / Chest / UpperChest | `spine`/`chest`/`upperChest` |
| `neck_01` | `neck_01` ✅ | `Neck` | Neck | `neck` |
| **`Head`** | **`head`** ⚠ **大小写不同** | `Head` | Head | `head` |
| `clavicle_l` | `clavicle_l` ✅ | `LeftShoulder` | Shoulder | `leftShoulder` |
| `upperarm_l` | `upperarm_l` ✅ | `LeftArm` | UpperArm | `leftUpperArm` |
| `lowerarm_l` | `lowerarm_l` ✅ | `LeftForeArm` | LowerArm | `leftLowerArm` |
| `hand_l` | `hand_l` ✅ | `LeftHand` | Hand | `leftHand` |
| `thigh_l` | `thigh_l` ✅ | `LeftUpLeg` | UpperLeg | `leftUpperLeg` |
| `calf_l` | `calf_l` ✅ | `LeftLeg` | LowerLeg | `leftLowerLeg` |
| `foot_l` | `foot_l` ✅ | `LeftFoot` | Foot | `leftFoot` |
| `ball_l` | `ball_l` ✅ | `LeftToeBase` | Toes | `leftToes` |
| `index_01_l` | `index_01_l` ✅ | `LeftHandIndex1` | （可选） | `leftIndexProximal` |

→ **除 `Head` 大小写外，命名与 UE Mannequin 逐名对齐。** 这是一个**真实且被工具链广泛识别**的约定。

### 4.2 结构 —— 65 是"中高保真"，**不是任何标准的固定数字**

| 相对 UE Mannequin | 我们 |
|---|---|
| 手指 3 节 + 末端 | ✅ 一致（`_01..03` + `_04_leaf`） |
| **IK 骨**（`ik_foot_l/r`、`ik_hand_l/r`、`ik_hand_gun`…） | ❌ **没有** → 脚部贴地/手部持物需在引擎里另做，或加骨 |
| **twist/roll 骨**（`upperarm_twist_01_l`、`thigh_twist_01_l`…） | ❌ **没有** → 前臂/大腿扭转靠蒙皮权重硬扛，**长袖大幅扭转时可能变形** |
| `Head` 大小写 | ⚠ `Head` vs UE 的 `head` |

### 4.3 真正决定"通用性"的是**语义映射**，不是骨数或名字

| 目标 | 要什么 |
|---|---|
| **Unity Humanoid (Mecanim)** | 一份 **mapping**（~15 必需骨 + 可选手指），不要固定骨架 |
| **VRM** | 一份 mapping（`hips`/`spine`/`chest`/… + 手指） |
| **Godot 4.3+** | 内置 **humanoid profile** 做 retarget，同样靠 mapping |
| **Mixamo 动画** | 一份 `mixamorig:*` ↔ 本骨架的对照表 |

→ 我们这套结构**可以**映射到以上全部（含手指）；**缺的只是一份对照表**。

---

## 5. 结论与建议

> **不要把"通用标准"当目标**（它不存在）。真正要的是两件事：
> ① **把骨名 + 层级 + 顺序冻结成自己的契约** —— 这才是会伤害你的东西
>    （`SPEC.md` **F30**：索引随文件而变（`.blend` 里 `Head=6` vs Godot glTF 里 `Head=54`），**一律按名取骨**）；
> ② **写一份到各家语义的映射表** —— 这样任何来源的动画都能重定向进来。

**自己生成素材时，建议沿用它这套 UE 风格命名**：工具链识别度高，且现有 **24/24 资产、全部脚本、全部验收判据**都建在它上面，改名要动的东西远多于收益。

### 可选补强（**都是"追加"，安全**）

| 补什么 | 好处 | 风险 |
|---|---|---|
| **IK 骨**（`ik_foot_l/r`、`ik_hand_l/r`） | 脚部贴地、手部持物 | **追加在末尾** → 不影响现有索引与 morph |
| **twist 骨**（`upperarm_twist_01_l`…） | 长袖/大腿扭转质量 | 同上；但**权重需重画**，且 morph 需重烘 |
| **改名 `Head`→`head`** | 与 UE 资产直接互导更省事 | ⚠ **破坏性**：会打断现有名字契约、现有资产与脚本全要改 → **不建议** |

> **追加骨是安全的，改名是破坏性的。** 要动名字必须当成一次**契约版本升级**来做：
> 同步改 SPEC / 全部脚本 / 重新烘 morph / 重跑全部验收判据。