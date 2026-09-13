# 关节边缘精修 · 经验总结与 Prompt

> 目标：把角色拼图里"直切 + 硬角 + 黑描边"的关节切口（大腿上沿、手臂肩端/腕端）
> 改成**顺着关节窝的浅凸圆弧**，且**只有这些部位被改动**。

---

## 一、结论先行

1. **生成模型能做这件事，但必须用 prompt 精确约束**；一次成功的概率不高，做好迭代 2～3 轮的准备。
2. **不要直接把生成结果当最终图**（除非你接受它把整张图重绘一遍）。稳妥流程：
   `verify` 量"允许区域内外"的改动 → `apply` 只把允许区域贴回原图。
3. 模型的"顺手改动"分两类，必须分开看：
   - **轮廓抗锯齿级的亚像素差**（铺满全图，肉眼不可见）—— 可接受
   - **形状/位置/尺寸变化**（如把腿切成两段、把手臂平移 17px）—— 不可接受，必须重发 prompt

---

## 二、一条流水线（都在 `tools/spine_joint_tool.py` 里）

```bash
T=tools/spine_joint_tool.py
python $T analyze --selection <套索带.json>       # 1. 量用户手绘的两条带
python $T cut     --selection <..> --out-dir <..> # 2. 确定性椭圆切件（备选路线）
python $T prep                                     # 3. 生成灰底任务输入图
python $T prompt  --part legs                      # 4. 打印标准 prompt
python $T gen     --part legs --runs 2             # 5. 发 Meowa 任务（一次 2 张）
python $T verify  --candidate <remove_bg.png> --region legs --part legs
python $T apply   --candidate <remove_bg.png> --region legs --out <拼图.png>
python $T report  --candidate <..> --box y0,y1,x0,x1
```

内置允许区域（`REGIONS`）：`legs` = y1430–2520 / x290–1020，`arms` = 左右两条臂列，`hip` = 胯部。

---

## 三、标准 Prompt（原文可直接复用）

### 3.1 腿部（**已实测成功**）

```
Character parts sheet for a 2D skeletal animation rig. Every visible piece is a separate layer and the pieces must stay separate. Edit ONLY the top cut edge of the two legs. Each leg is ONE single piece from hip to ankle - do not split it at the knee and do not add any new seam or cut anywhere. Today each leg ends at the top with a straight angled cut that has a sharp corner and a dark outline. Replace only that top straight cut with a smooth shallow convex arc, like a shallow ball cap, so the leg can tuck under the pelvis. The new edge must be a clean flat cel-shaded edge: no dark outline, no shading, no bevel, no cross-section. Constraints: canvas = keep the input size and layout exactly; background = flat grey; edit = [top cut edge of the left leg becomes a smooth shallow convex arc, top cut edge of the right leg becomes a smooth shallow convex arc]; must_not_change = [hair, head, face, eyes, mouth, ear, torso, bikini, arms, hands, feet, knee, shin, ankle, everything below the top edge of each leg]; forbidden = [splitting a leg into two pieces, adding any new seam or cut, joining pieces together, closing the gaps between pieces, moving or resizing any piece, adding an outline on the new edge, adding shading on the new edge].
```

关键点：`Each leg is ONE single piece ... do not split it at the knee` —— **这一句是成败分水岭**，没有它模型会把腿从膝盖切成两段。

### 3.2 手臂（**弧线对了，但位置锚定还需要加强**）

```
Character parts sheet for a 2D skeletal animation rig. Every visible piece is a separate layer and the pieces must stay separate. Edit ONLY the two arms. Each arm is ONE single piece from shoulder to wrist - do not split it anywhere and do not add any new seam or cut. The second reference image shows the refined hip and thigh joint, where the thigh ends in a smooth shallow convex arc with no dark outline. Apply that same joint style to each arm: reshape the shoulder end and the wrist end of each arm into the same kind of smooth shallow convex arc, so the arm can tuck under the torso shoulder and under the hand. The new edges must be clean flat cel-shaded edges: no dark outline, no shading, no bevel, no cross-section. Every piece must stay at exactly the same pixel position and size as the input - keep both arm bounding boxes identical. Constraints: canvas = keep the input size and layout exactly; background = flat grey; must_not_change = [hair, head, face, eyes, mouth, ear, torso, bikini, hands, legs, feet]; forbidden = [splitting an arm into two pieces, adding any new seam or cut, joining pieces together, closing the gaps between pieces, moving or resizing any piece, adding an outline on a new edge, adding shading on a new edge].
```

**实测结果**：腕端确实从直切变成了圆弧 ✅，但两条手臂被**整体平移 10～17px、宽度少 8px** ❌。
下一轮建议再加上像素锚点：`the left arm occupies x 83-351, y 952-1528 and the right arm is its mirror`。

### 3.3 关于 "JSON 约束"

直接写 `{"key":"value"}` **不行** —— PowerShell 的批处理包装层会把双引号当分隔符，参数被拆成碎片。
用**无引号结构化块**代替，效果等价且能活下来：

```
Constraints: canvas = ...; background = flat grey; edit = [a, b]; must_not_change = [..]; forbidden = [..]
```

---

## 四、踩过的坑（按重要性排序）

| # | 坑 | 现象 | 解法 |
|---|---|---|---|
| 1 | 用**局部特写**当输入 | 模型把骨盆+大腿粘成一个完整身体，零件缝隙全消失 | 必须给**整张拼图**，并明说"每块是独立图层" |
| 2 | 没禁止切膝盖 | 模型自作主张把腿切成大腿/小腿两段 | 显式写 `do not split it at the knee` |
| 3 | prompt 里带引号 | 参数被拆碎，`unrecognized arguments: the input size and layout exactly,...` | 用无引号结构化块 |
| 4 | 判据过敏 | 内裤掩膜混入大腿内侧软阴影的 7 个杂点 → 椭圆被多推 40px | 掩膜先做**连通域过滤**，丢掉 <150px 碎片 |
| 5 | 两腿分界拉直线 | 大腿贴合处被切进身体 → 腿件缺块、躯干多"舌头" | 分界改成**沿缝隙中线**走 |
| 6 | PS `clear()` 清错图层 | 左腿被"整身层+左腿层"叠加两次（alpha 恰好 = 1-(1-a)²） | `clear()` 前必须 `doc.activeLayer = ly` |
| 7 | 多子路径选区不可靠 | 逐个 `makeSelection + EXTEND` 只生效一个 | 多个 SubPath 放进**同一个 PathItem** 再 `makeSelection` 一次 |
| 8 | 导入图片拼图层位置飘 | `place_image` / `doc.paste()` 落点不稳定 | 用「复制图层 + 选区 clear」而不是导入 PNG |
| 9 | image-2 输入透明 | 会画一个假棋盘格 | 输入合成到**纯灰底 205**，出图后 `--remove-bg-method standard` |
| 10 | 参数组合限制 | `--strict` 报 "available only in pixel mode"；`--advanced` 报 "HD editing supports only none or standard" | HD 模式：不加 `--strict`，去背用 `none/standard` |
| 11 | 模型平移零件 | 手臂整体挪了 10～17px | `verify` 必须**先做整体对齐**再比改动量，并单独量零件包围盒 |

---

## 五、文件地图

| 路径 | 说明 |
|---|---|
| `tools/spine_joint_tool.py` | **唯一工具**：analyze / cut / prep / prompt / gen / verify / apply / report |
| `tools/ps_cut/fill_from_layer1.jsx` | PS 内一键从「图层 1」补选区缺口（残留小缺口时用） |
| `assets/eva_bone/merged_sheet_FINAL.png` | **最终成品**：GPT 生成的整张拼图（腿已修好）★ |
| 合成版 `merged_sheet_legs_fixed.png` | 原图 + 只替换腿部区域 —— **已删**，用 `apply --region legs` 重建 |
| 预览图（差异图 / 关节放大 / 候选对比） | **已删**，用 `report` 与 `overview` 重建 |
| `meowa/split_base_skin/base_ref/job_ids.md` | 全部 job_id（误删可 `image-2-poll` 免费重下） |
| `meowa/split_base_skin/base_ref/selection_polys.json` | 用户手绘套索带几何（切件的输入） |
| `meowa/split_base_skin/refs/merged_sheet.png` | 用户交付的原始拼图（一切的原点） |

---

## 六、下次怎么继续

1. 改 prompt → `python tools/spine_joint_tool.py prompt --part arms` 看全文
2. 发任务 → `gen --part arms --runs 2 --tag v2`
3. 判优劣 → `verify --candidate <remove_bg.png> --region arms --part arms`
   - `changed_outside` 应该是**几千量级**（纯抗锯齿）；上到几万说明模型动了别处
   - 再单独量零件包围盒，确认**位置/尺寸没变**
4. 通过 → `apply --region arms --part arms --out <拼图.png>` 并进成品
