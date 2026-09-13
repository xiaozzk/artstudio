# meowa 沉淀总览

> **一页看懂这个工作区**：做过什么、结论是什么、东西在哪、下次从哪继续。
>
> 配套文档：
> `README.md` 使用说明（凭据 / 约定 / 命令模板 / 踩坑速查）
> `JOINT_REFINE_NOTES.md` **当前路线**的经验与标准 prompt
> `PIPELINE_NOTES.md` 旧方案（919×1672）的完整生成链路
> `split_base_skin/REPORT.md` 旧方案的评测报告（GPT vs BANANA）

---

## 一、一句话结论

**生成模型能做"形状设计"，不能做"零件拆分"。**
现在定下来的路线是：**用户自己切件 → 只用 GPT 精修关节边缘 → 校验后回填**。

---

## 二、时间线

| 时间 | 阶段 | 做法 | 结论 |
|---|---|---|---|
| 09-13 上午 | 拆件 v1 | 让 GPT 直接输出 16 件零件表 | ❌ 模型**无法可靠保持零件分离**（会粘合、会闭合轮廓） |
| 09-13 下午 | 拆件 v2 | alpha_split 确定性切件 + spec + 彩色掩码/布局掩码引导 GPT | ⚠️ 旧 919×1672 方案，最佳 IoU 0.8467，后整体停用 |
| 09-13 晚 | 关节精修 | BJD 球关节方案（leg1/leg2） | ❌ 用户否掉："BJD 关节太明显了" |
| 09-14 | **换路线** | **用户自己切件，只让 GPT 精修关节边缘** | ✅ 成功 → `assets/eva_bone/merged_sheet_FINAL.png` |
| 09-14 | 备选路线 | PS 内确定性椭圆切件（套索带 → 椭圆 → 三层带重叠） | ✅ 可复现，已并入工具 `cut` |
| 09-14 | 收尾 | 脚本合并 + 清理 | 50 个脚本 → **1 个工具**；meowa 7.38 MB → 4.93 MB |

---

## 三、最重要的五条经验

1. **生成模型不是切图工具。**
   让它"保持零件分离"基本无效 —— 给局部特写它会**把骨盆和大腿粘成一整个身体**，缝隙全消失。
   要分离就用确定性脚本；要它做形状，就只让它做形状，**自己回填**。

2. **输入给整张拼图，别给特写。**
   整张零件表 + 明说"每块是独立图层" → 布局能保住；只给胯部特写 → 零件被粘合。

3. **必须显式禁止模型"顺手切分"。**
   实测：不写 `each leg is ONE single piece - do not split it at the knee`，
   模型会把腿从膝盖切成大腿/小腿两段。写上就正常了。

4. **prompt 必须单行、且不含引号字符。**
   PowerShell 包装层把双引号当分隔符，`{"canvas":"..."}` 会让参数碎成一地。
   改用无引号结构化约束：`Constraints: canvas = ...; edit = [a, b]; must_not_change = [..]; forbidden = [..]`

5. **"看起来对"不算通过，判据自己也会骗人。**
   - 模型会**平移零件 10~17px、改宽度 8px** → 必须量包围盒
   - 自动指标曾导致**误删用户认可的产物**；内裤掩膜里 7 个抗锯齿杂点曾把椭圆**多推 40px**
   - 正确做法：`verify` 量"允许区域内/外"改动量 + 单独量零件包围盒；删除永远要人确认

---

## 四、当前状态（2026-09-14）

| 项目 | 位置 / 值 |
|---|---|
| 成品拼图（腿已修好） | `assets/eva_bone/merged_sheet_FINAL.png` ★ |
| 合成版（原图 + 只替换腿部） | 已删；`apply --region legs` 可重建 |
| 唯一工具（10 子命令） | `tools/spine_joint_tool.py` |
| 标准 prompt | `tools/spine_joint_tool.py prompt --part legs\|arms` |
| job_id 存档 | `split_base_skin/base_ref/job_ids.md` |
| 用户手绘套索带几何 | `split_base_skin/base_ref/selection_polys.json` |
| 原始素材 | `input/assembled.png`（= `assets/eva_bone/assembled.png`） |
| 用户交付的拼图 | `split_base_skin/refs/merged_sheet.png` |
| skill 版本 | `2026.09.13.1`（装在 `.agents` 与 `.claude` 两处） |

**成本**：HD 编辑 2K/ultimate 每张 ≈ **52 积分**；**失败自动全额退费**。
本轮（腿部 5 次 + 手臂 2 次成功）账面从 7743 → 7387。

---

## 五、文件地图

```
meowa/
├── SUMMARY.md                ← 你正在看的这份
├── README.md                 使用说明（凭据/约定/命令模板/踩坑速查）
├── JOINT_REFINE_NOTES.md     当前路线：经验 + 标准 prompt 全文
├── PIPELINE_NOTES.md         旧方案（919×1672）生成链路（历史）
├── input/
│   └── assembled.png         ★ 原始素材，一切的原点
├── refs/                     风格参考图
├── templates/                Meowa 预设信息（pixel/large-pixel/hd）
└── split_base_skin/
    ├── REPORT.md             旧方案评测报告（GPT vs BANANA）
    ├── prompt_*.txt          各轮 prompt 存档
    ├── refs/merged_sheet.png ★ 用户交付的零件拼图
    └── base_ref/             基准资产
        ├── job_ids.md            全部 job_id（误删可 image-2-poll 免费重下）
        ├── selection_polys.json  用户手绘套索带几何
        ├── cutpoly/ellipse_data_v3.jsx  PS 选区数据
        ├── prompt_used.txt / prompt_make_fix2.txt  当时的 prompt
        ├── base_parts_sheet_fix2.png  旧方案认可的基线
        ├── joint_ref_legs.png        手臂任务用的关节参考图
        ├── source_user_sheet.png / assembly_marks.png / leg_connection_ref.png  用户提供的参考
        └── joint_ref_legs.png
```

工具在 `tools/`（不消耗额度）：`spine_joint_tool.py`、`ps_cut/fill_from_layer1.jsx`。

---

## 六、下次继续

**待办**

1. **手臂**再迭代一轮 —— prompt 里已加像素锚点约束
   （`the left arm occupies x 83-351, y 952-1528 ... keep both bounding boxes identical`），
   跑 2 张约 104 积分，验完用 `apply --region arms --part arms` 并进成品
2. 把成品拼图拿去做 **PS 切件 → Spine 绑骨**（这是 `merged_sheet_FINAL.png` 的用途）
3. 新文件目前都是**未跟踪**状态（`tools/spine_joint_tool.py`、`meowa/JOINT_REFINE_NOTES.md`、
   `assets/eva_bone/merged_sheet_FINAL.png`），需要时提交进 git

**继续迭代的标准动作**

```powershell
$T = tools/spine_joint_tool.py
python $T prompt  --part arms                 # 1. 看/改 prompt（prompt 常量就在工具里）
python $T gen     --part arms --runs 2 --tag v2   # 2. 发任务
python $T verify  --candidate <remove_bg.png> --region arms --part arms
                                              # 3. changed_outside 几千 = 纯抗锯齿；
                                              #    上万 = 模型动了别处；再量零件包围盒
python $T apply   --candidate <remove_bg.png> --region arms --part arms --out <拼图.png>
python $T diff    <原图> <新图>               # 4. 有疑问时诊断差异性质
```
