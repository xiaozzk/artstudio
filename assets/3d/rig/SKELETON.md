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

---

## 6. ⭐ 决策：**VRM 角色词表定为「语义层标准」，但骨名不改**

> 本节记录 2026-10-14 与用户对齐的决定，以及**为什么"采用 VRM 规范"不等于"把骨名改成 VRM 的名字"**。

### 6.1 决定

| | |
|---|---|
| **语义层** | **VRM 1.0 角色词表**（`hips`/`spine`/`chest`/`upperChest`/`neck`/`head`、`leftUpperArm`…、`leftThumbProximal`…） |
| **授权层（骨名）** | **保持现状**（UE Mannequin 风格）**不改名** |
| **两者之间** | 一份**可生成、可校验**的映射产物 [`skeleton_mapping.json`](skeleton_mapping.json) |

### 6.2 为什么选 VRM 做语义层

1. **它把映射做成"数据"而不是"编辑器状态"**（`humanBones` 里显式写 node 索引）→ **机器可处理**，这正是工具化最友好的形态
2. **开放 + 厂商中立**，且**就是 glTF 扩展、单位是米** → 与本仓库的 Godot 管线同源
3. ⭐ **Godot 4.6 的 `SkeletonProfileHumanoid` 就是同一套词表**（实测 **56 骨**，骨名即 VRM 角色名）→ **一份映射同时喂** Godot `RetargetModifier3D` / VRM `humanBones` / Unity Humanoid / Mixamo 对照
4. 必需集合小且清楚（**15 个必需角色**），达标门槛低

### 6.3 为什么不改骨名（三条，按重要性）

1. ⚠ **VRM 词表覆盖不了生产骨架的全部** —— 它只有 **56 个角色名**，**没有 `root`**（spec 明说 root 是 "not a humanoid bone, origin"）、**没有 IK 骨、没有 twist 骨、没有叶子标记**。
   → 就算全改，你**仍然**会有一批自有骨 → **必然是混用**，不如把"混用"显式化成一张映射表
2. ⚠ **24/24 资产、全部脚本、全部验收判据都建在现有骨名上**（`find_bone("Head")` 遍布管线）→ 改名 = 重跑整条验证链
3. **现有骨名与 UE Mannequin 逐名对齐**（§4.1）→ 保留它同时保住 UE 侧的可识别性；而**导入任何来源的动画本来就需要一份映射**，改名并不会省掉这一步

### 6.4 映射产物：`skeleton_mapping.json`

生成器 [`tools/3d/skeleton/make_mapping.py`](../../../tools/3d/skeleton/make_mapping.py)（**规则生成，不手写**）。**实测闭合**：

```
65 骨 = 52 根映射到 VRM 角色 + 13 根显式额外骨（1 × root + 12 × 叶子标记）
VRM 必需角色覆盖 15/15 ✅
```

**门禁（已实证会变红）** —— 三类坏输入均 `exit≠0`：

| 坏输入 | 拦下的依据 |
|---|---|
| 某根骨名被改（孤儿） | 「既未映射角色、也未登记额外骨」 |
| 两根骨抢同一个角色 | 「角色重复」 |
| 删掉 12 根叶子骨 | **「骨数 53 ≠ 期望 65」** ← ⚠ 这条是**补出来的**：没有它时，删骨**照样通过**（53 = 52 + 1），门禁会静默接受另一副骨架 |

> ⚠ **第 3 类正是「它在什么退化输入下也会通过？」的实例** —— 前两类能拦，第 3 类一开始**不能**。
> 教训固化为规则：**凡"通过"的判据，必须同时断言"期望的规模与构成"**，而不只是"内部自洽"。

### 6.5 一处必须记住的差异

**Godot 把 `LeftShoulder`/`RightShoulder` 标为 `required=true`，而 VRM 里 `leftShoulder` 是可选** → **Godot 的要求略严于 VRM**。
所以"能满足 Godot `SkeletonProfileHumanoid`"⇒ 自动满足 VRM 的必需集合（反之不一定）。

---

## 7. IK 与 morph：Godot / Blender / glTF（实测于 Godot 4.6.2 + Blender 5.2.2）

> 契约事实见 [`SPEC.md`](SPEC.md) **F33**（那里是权威表述）；本节是面向操作的展开。

### 7.1 Godot 的 IK：完整，且**不需要「IK 骨」**

```
SkeletonModifier3D                    ← Node3D（所有骨修饰的基类）
├── IKModifier3D
│   ├── ChainIK3D
│   │   ├── IterateIK3D → CCDIK3D / FABRIK3D / JacobianIK3D
│   │   └── SplineIK3D
│   └── TwoBoneIK3D                   ← 手臂/腿最常用，最快
├── SkeletonIK3D                      （旧的，也已归入 modifier 体系）
├── AimModifier3D / LookAtModifier3D / CopyTransform3D / ConvertTransform3D
├── SpringBoneSimulator3D（+ Sphere/Capsule/Plane 碰撞体）
├── RetargetModifier3D（配 SkeletonProfile / SkeletonProfileHumanoid）
└── XRBodyModifier3D / XRHandModifier3D / XRFaceModifier3D
```

| | 机制 | 需不需要骨架里有 `ik_*` 骨 |
|---|---|---|
| **UE** | `ik_foot_l` 等**不是求解器**，是动画蓝图读的**目标锚点骨** | 需要 |
| **Godot** | IK 是**修饰器节点**，`target` 可以是**任意 `Node3D`**（一个 `Marker3D` 就够） | **不需要** |

→ 所以"Godot 支持 IK 骨吗"的准确回答是：**它不要求你这么做**。把 UE 风格的 `ik_*` 骨导进来，Godot 当**普通关节**处理（多余但无害）。

### 7.2 Blender 的 IK：⚠ 5.x **改了类名**

| | 实际情况（5.2.2 实测） |
|---|---|
| **Python 类名** | **`KinematicConstraint`**（**不再是 `IKConstraint`**） |
| **枚举标识符** | **仍是 `'IK'`** → `pb.constraints.new('IK')` 照旧，`c.type == 'IK'` |
| **`Armature.ik_solver`** | **已不存在**（5.x 去掉了 Legacy / iTaSC 的选择） |

**关键参数**：`target` / `subtarget`｜`chain_count`｜`pole_target` + `pole_angle`（膝盖/肘朝向）｜`iterations`｜`use_tail`｜`use_stretch`｜`use_location` / `use_rotation`（各带 `lock_x/y/z`）｜`ik_type` / `limit_mode` / `distance`。另有 `SplineIKConstraint`。

**标准做法**：控制骨（`ik_foot_l`…）**不放进形变链** → 末端形变骨（`foot_l`）加 IK 约束（`chain_count` 2~3）→ 设 **IK limits**（`Bone.use_ik_limit_*` + `ik_stiffness_*`）防膝/肘反折 → 设 **pole target** → 用 **Bone Collection** 分组 → 控制骨设 **`use_deform = False`**。

### 7.3 导出 glTF / Godot：两条口径，**别混**

**glTF 规范里没有 IK**，约束不会被导出。实测导出器相关选项：

| 选项 | 默认 | 作用 |
|---|---|---|
| `export_force_sampling` | **True** | 把约束求解**烘成逐帧采样动画** ← IK 就是这样"被导出"的 |
| `export_def_bones` | False | 打开则**只导形变骨** → **`use_deform=False` 的 IK 控制骨被剥掉** |
| `export_rest_position_armature` | True | 以 rest 姿态导出 |
| `export_reset_pose_bones` | True | 导出前重置 pose 骨 |
| `export_leaf_bone` | False | 是否为终端补叶子骨 |

- **(a) 动画烘成采样帧交付**：Godot 播烘好的骨骼动画，**运行时不需要 IK**
- **(b) IK 留给 Godot 运行时**：**别导出控制骨**，在 Godot 里加 `TwoBoneIK3D` 指向自己的目标节点

### 7.4 ⭐ 对 morph 的硬结论

| | 改什么 | 属于 |
|---|---|---|
| **morph（shape key）** | **顶点** | 制作期（体型走这条） |
| **IK** | **骨 pose** | 运行期 |

两者**可叠加**（最终 = morph 后的网格 + pose 后的骨架）✓

> ⚠ **但烘 morph 前必须清掉 IK / 全部约束**。理由：pose 与 shape key 是**两套独立形变来源、会叠加**（§3.3 实测读到过 **33 mm 假差**）→ 在「IK 影响下的姿态」里读顶点位置，会**把姿态错误烘进 morph**。

**因此：资产里不带 IK 骨**（源 glTF 里 `ik_` 计数 = **0**，这是对的、别改）。
脚部贴地 / 手部持物 → **在 Godot 运行时**加 `TwoBoneIK3D`（目标用 `Marker3D` 或 `BoneAttachment3D`）→ **不动资产、不动 morph、不动骨架契约**。
只在 Blender 里用 IK **摆姿势 / 烘动画**，再烘成 **FK 采样帧**导出。

> 顺带：**`BoneAttachment3D`** 正是 modular 体系里"**挂点**"（武器/帽子/挂件）的原生方案；
> **`SpringBoneSimulator3D`** 是头发/裙摆/斗篷的次级动画（等价 VRM springbone）。
> 这两样加上 `RetargetModifier3D`，说明 **Godot 侧对「分件 + 换装 + 重定向」的支持是完整的**。