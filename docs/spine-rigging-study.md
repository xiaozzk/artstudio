# Spine 骨骼动画：自动定位 → 建骨骼 → 预览 全链路技术调研

> 来源：深度精读 [spine-animation-ai](https://github.com/GenielabsOpenSource/spine-animation-ai)（本地克隆 `docs/spine-animation-ai/`）的 `position_parts.py` / `build_spine_json.py` / `make_atlas.py` / `generate_spine_player.py` 四个脚本 + 其 `references/spine-json-spec.md`、`docs/adjustment-format.md`，并结合 Spine 4.2 官方格式知识整理。
> 目的：加深对 Spine 骨骼体系的理解，把经验落到本工作区（Godot 4、Eva 拆件素材）。
> 日期：2026-02。面向 Godot 4（≥ 4.4），用户不应熟悉 Spine 编辑器。

---

## 0. 一图看懂全链路

```
单图角色 PNG ──(split_character.py, Gemini+连通域)──▶ 分件 PNGs
分件 PNGs + 拼合参考图 ──(position_parts.py)──▶ layout.json（各件 x/y/scale/rot/z）
layout.json ──(Claude/Claude 按人形模板组织 bones+slots)──▶ config.json
config.json ──(build_spine_json.py)──▶ skeleton.json（Spine 4.2 骨骼+动画）
分件 PNGs ──(make_atlas.py)──▶ skeleton.png + skeleton.atlas
三件套 ──(generate_spine_player.py)──▶ preview.html（浏览器自包含预览）
三件套 ──▶ 可直接 Import 进 Spine 编辑器 / 各引擎 runtime（含 Godot）
```

关键认知：**Spine 编辑器在这里全程缺席**。AI 的"操作 Spine"就是程序化读写 Spine 的 JSON + atlas 文本格式——这两者都是稳定、公开、文档完备的格式，完全不需要打开编辑器。

---

## 1. Spine 骨骼体系核心概念（地基）

### 1.1 四层结构：Bone → Slot → Attachment → Skin

| 概念 | 是什么 | 类比 |
|------|--------|------|
| **Bone** | 变换节点：x/y/rotation/scaleX/scaleY/length，父子层级，子继承父变换 | Godot 的 Node2D |
| **Slot** | 挂在 bone 上的"图槽"，一个 bone 可有多个 slot；**slot 在数组里的顺序 = draw order**（index 小的画在后面） | 无直接对应，是"可换图的容器" |
| **Attachment** | slot 里实际显示的图（region/mesh/bounding 等），带 x/y/width/height 偏移 | Sprite2D |
| **Skin** | 若干 attachment 的命名集合；换装 = 切 skin | 无，本质是"配置预设" |

最容易误解的点：**bone ≠ 图片**。一个 bone 可以不显示任何东西（纯变换用），一张图的摆放位置写在 attachment 的 x/y 偏移上而不是 bone 上。调整"某个部件的位置"，动的是 `skins[].attachments` 里的 x/y，不是 bone 的坐标。

### 1.2 坐标系：Y 轴向上

- +X 向右，**+Y 向上**，+rotation 逆时针（度）。
- 与 HTML canvas / 图像处理（Y 向下）正好相反。**从图像坐标换算：`spine_y = canvas_height - canvas_y`**。屏幕上"太高了"要下调 = 给负 dy。
- `skeleton` 头部的 `x/y/width/height` 定义包围盒，通常 `x = -width/2` 让角色中心在原点。

### 1.3 数据三件套

任何 Spine runtime（编辑器、Web Player、Godot）都需要：

1. `skeleton.json`（或二进制 `.skel`）—— 骨骼层级 + 皮肤 + 动画时间轴；
2. `skeleton.atlas` —— 纯文本图集索引；
3. `skeleton.png` —— 打包后的图集贴图。

atlas 文本格式（逐行含义，手写也能过）：

```
skeleton.png        ← 该页贴图文件名（可多页）
size: 512,512       ← 贴图尺寸
format: RGBA8888
filter: Linear,Linear   ← 运行时采样过滤
repeat: none
regionName          ← 区域名（= attachment 名，必须和 JSON 对上）
  rotate: false
  xy: 0, 0          ← 在贴图里的左上角坐标
  size: 120, 200
  orig: 120, 200    ← 原始尺寸（trim 后 restore 用）
  offset: 0, 0      ← 原图中被裁掉的部分的偏移
  index: -1         ← 多 sprite（split/strip）时才用
```

对 attachment�权重字段：`width/height` 是原图（region）显示尺寸，`x/y` 是相对格的偏移。若 atlas 有 trim（`orig` ≠ `size`），attachment 需要把 trim 信息映射回 `width/height/x/y`，否则图会错位。

---

## 2. 自动定位：SIFT + RANSAC + 遮挡投票（`position_parts.py`）

### 2.1 问题定义

输入：一张**拼合好的角色参考图**（reference）+ 一堆**分件透明 PNG**。
输出：每个件的 x/y（参考图中左上角）、scale、rotation、可信度，以及全局 draw order。

这是整个流水线里最"计算机视觉"的一环，也是与我们 `tools/` 差异最大的地方：我们用 alpha 连通域 + spec 比例目测拼（确定性、快），它用特征匹配自动求精确变换（泛化、无人值守）。

### 2.2 Phase 1a：SIFT 匹配（主力）

对每个分件：

1. **前提约束**：分件必须带 alpha；不透明像素 < 1% 直接跳过。
2. **alpha 掩码参与关键点提取**：`sift.detectAndCompute(gray, mask)`，只在可见像素上找特征 —— 这是对我们最有用的技巧，避免在透明区/裁边处产生虚假关键点。
3. **SIFT 参数为"游戏美术"调过**：
   ```python
   cv2.SIFT_create(nfeatures=0, contrastThreshold=0.02, edgeThreshold=20)
   ```
   `contrastThreshold` 从默认 0.04 降到 0.02：卡通风/赛璐璐画布暗但清晰的特征点会被漏掉，降阈值能多留特征；`edgeThreshold=20` 放宽边缘抑制，利用描边/轮廓线。**特征点少的软肋用灵敏度换**。
4. **FLANN 匹配（KD 树 ×5，checks 150）+ knnMatch k=2 + Lowe ratio test（默认 0.80）**。ratio 是唯一主观旋钮：调到 0.75 甚至 0.70 可以在参考图与分件风格略异（如 AI 重绘）时保住更多匹配。
5. **RANSAC 求相似变换而非单应矩阵**——这是本项目最值得学的选择：
   ```python
   M, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                         ransacReprojThreshold=5.0)
   ```
   | | 全 homography（8 DOF） | **相似变换（4 DOF：平移+等比缩放+旋转）** |
   |---|---|---|
   | 最少内点 | 4 | **2** |
   | 假设 | 允许透视/剪切/非等比 | 只允许"移动+放大旋转+旋转" |
   | 游戏美术场景 | 匹配稀疏时极易拟合出离谱的透视 | **理论约束严，2 个对的点就基本锁死** |

   `estimateAffinePartial2D` 就是 OpenCV 里"相似变换版 RANSAC"。**凡是拆件回拼参考图的场景，4 DOF 优于 8 DOF** —— 正确答案一定落在这个子空间里，多余自由度只会吸收噪声。
6. **从 2×3 矩阵反读 scale / rotation**：
   ```
   M = [[s·cosθ, -s·sinθ, tx], [s·sinθ, s·cosθ, ty]]
   scale    = √(M00² + M10²)         （M 的第一列模长）
   rotation = atan2(M10, M00) 转度
   ```
7. **常识性剪枝（sanity check）**：scale 限 0.3–3.0，rotation 限 ±20°。剪掉的是"靠 5 个错匹配拼出 90° 旋转+3× 放大"这类统计学上成立、美术上荒谬的解。**给优化解加"领域常识门"比调匹配阈值更有效**。

### 2.3 兜底：模板匹配（Template Matching）

小配件（耳环、纽扣、帽饰）纹理稀疏，SIFT 凑不齐 keypoint。兜底方案：

- 在 **7 档缩放**（0.85–1.15）下逐档跑 `cv2.matchTemplate(TM_CCORR_NORMED, mask=alpha)`；
- 加**背景惩罚**：匹配窗内的前景栅格（reference 的 fg_mask）占比 `fg_ratio` 参与打分 —— `combined = max_val × (0.3 + 0.7 × fg_ratio)`，防止模板落在参考图透明区外；
- **DMZ 技巧：用 SIFT 的结果反哺模板匹配的缩放档位**。全体成功 SIFT 件的 `scale` 中位数 ±20% 重排 9 档，把模板匹配从"盲搜"变成"已知解附近精搜"。一次成功匹配（哪怕只对 60% 的件）能把整个兜底的搜索空间估计收窄为 90%。

### 2.4 Phase 2：draw order 通过遮挡分析反推

这是第二个"聪明"的设计。**人类画师按遮挡关系分层；反推 draw order 时，遮挡本身就是标签。**

对每一对重叠的件 A、B：

1. 在重叠区（取 bbox 交集）里按步长采样（约 500 个样本）；
2. 只采样两点都不透明的像素；
3. 每个像素与参考原图比色差：`dISS(A) = ‖ref − A_px‖`、`dISS(B)`；
4. 差距 > 5（容错误差）才投票：谁的色差小，谁"在前面"；
5. 一对里票数超过对方的 1.2 倍才结算（`tot > 5` 才有效），避免势均力敌时翻车。

然后按**净胜分**（`depth[a] += wins; depth[b] -= wins`）全局排序得到 back→front。用加权计分而不是严格图拓扑排序，好处是**循环遮挡**（这在手绘角色里常出现）不会挂死，天然给出柔和的近似解。

### 2.5 可调试性设计（值得抄的工程习惯）

`--debug` 产出四张图：
- `composite.png`：按算出的 z 序拼回去的结果 —— **先看这张**，肉眼验证；
- `comparison.png`：参考 vs 拼合并排 —— 一眼看出哪件偏了；
- `bboxes.png`：每个件一个彩色框 + 方法/缩放/内点数标注；
- `sift_<part>.jpg`：per-part 特征匹配连线图（绿色 = RANSAC 内点）。

**教训：把"算法为什么错了"做成一图片化输出**，比读日志快十倍。我们的 `fit_parts.py` 质量分思路与之一致，但缺少逐件可视化，值得补。

### 2.6 何时该用 SIFT、何时不用

| 场景 | 建议方案 |
|------|---------|
| 分件精确来自参考图（PS 拆层） | 我们现有的 bbox/比例法就够，又快又确定 |
| 分件是 **AI 重绘/重划**的（尺寸有 1.2–2× 全局漂移、轻微旋转） | SIFT + RANSAC 是对的：它天生对等比缩放/旋转不变 |
| 分件极小、纯平色 | 模板匹配兜底，但给缩放档位从已知解逼近 |
| 含对称件（左右手等） | **SIFT 大概率会左右弄反**（特征对称）。要用相对面积排名 + 命名先验（我们踩过的坑），或手动确认 |

---

## 3. 建骨骼：从 layout 到合规 Spine 4.2 JSON（`build_spine_json.py`）

### 3.1 生成策略：脚本管"机械"，AI 管"语义"

这个脚本**不做**骨骼设计 —— 输入的 `config.json`（bones/slots/attachments）由 Claude 按人形先验拼出来（如 `hip` 在 root 上方、`torso` 挂 hip、slot 顺序 = z_order）。脚本负责：

- 结构正确性（父先于子、hash、包围盒、默认皮肤骨架）；
- **动画生成**：6 个预置动画（idle/walk/run/wave/jump/attack）按"有哪些 bone 就动哪些"的原则生成，不存在的 bone 自动跳过。
  - 这种**能力探测式生成**（`if "hip" in B:`）是脚本可复用的关键：同一份生成器适配资源不同的工程。
- **4.2 线上格式转换**（见 3.3，全是坑）。

### 3.2 JSON 骨架速记

```json
{
  "skeleton": { "hash": "...", "spine": "4.2.0", "x": -200, "y": 0, "width": 400, "height": 600 },
  "bones": [ { "name": "root" }, { "name": "hip", "parent": "root", "x": 0, "y": 200, "length": 30 } ],
  "slots": [ { "name": "torso", "bone": "torso", "attachment": "torso" } ],
  "skins": [ { "name": "default", "attachments": { "torso": { "torso": { "width": 120, "height": 200, "x": 0, "y": 60 } } } } ],
  "animations": { "idle": { "bones": { "torso": { "rotate": [...], "translate": [...] } } } }
}
```

- `hash` 由 config 内容算 MD5 —— 改任何一项 hash 都会变，方便看版本；
- 注意 skins 里是**双重键**：外层是 slot 名，内层是 attachment 名（默认相等但不强制）。

### 3.3 Spine 3.8 → 4.2 三个官方暗坑（此脚本 docstring 里的字面教训）

**这些是"手写 Spine JSON"最容易翻的场景，逐条记下：**

1. **rotate 的关键帧字段 renamed**：3.8 写 `"angle"`，4.x 读成 0（骨骼一动不动）。4.2 要写 **`"value"`**。
2. **bezier 是"每属性"而不是"每关键帧"**：`rotate` 动 1 个属性 → curve 数组 4 个数；`translate` / `scale` / `shear` 动 2 个（x、y）→ **8 个数**。给 4 个的 8 属性曲线，runtime 会读越界拿到 `undefined`，NaN 穿透骨髓变换，**动画渲染一帧后消失**（不是报错，是蒸发）。
3. **bezier 控制点是绝对坐标，不是 0–1 归一化**。spine-core 的 `Animation.js` 里：
   ```js
   let dx = (cx1 - time1) * 0.3 + ...; let x = time1 + dx;
   ```
   即 `cx1` 是**时间**、`cy2` 是**值**，用与周围关键帧相同的单位。把 0–1 归一化坐标塞进去，句柄会飘到段外，动画会"抽搐"而不是缓动。把 `(t1,v1)→(t2,v2)` 段摆一个标准 ease：
   ```
   cx1 = t1 + (t2-t1)×0.25   cy1 = v1 + (v2-v1)×0
   cx2 = t1 + (t2-t1)×0.75   cy2 = v1 + (v2-v1)×1
   ```
4. （作者原 docstring 还有一句）**curve 管它"开始"的那一段**。脚本作者把生成器的 curve 修在"段终点"，序列化前整体前移一帧 —— 这个语义 converter 有裨益：生成器用"写工整"的书写习惯，序列化层负责翻成 runtime 真正的字节序 —— **写与读用不同的 dialect，中间做一次显式的 format 转换**（`_to_spine_42` 函数），这个分层对我们生成任何需要匹配 runtime 的格式都适用。

### 3.4 动画生成器的"动画十二原则"落地

写 Spine 动画，值的是**关键帧的组织方式**而不是做表情驱动。看本项目的几个典型 mindset：

| 动画 | 组织学 | 映射到的原则 |
|------|--------|-------------|
| idle 1.6s | 不同关节**用不同频率+相位错开**做重叠正弦（torso 1.5°/0.5 相位、head −2°/0.6 相位） | overlapping action；错相位制造"呼吸感" |
| walk 0.8s | *左右腿 phase 0/0.5 相位倒转、左右臂反相*；hip y 方向 2 度/一拍抬起 | 对应 phase 对称原理 |
| run 0.5s | **恒定前倾角**（torso base 8°、head base −6°矫正） + 更大幅度的 walk | identity / exaggeration |
| wave 1.2s | 大臂一次到位（0.2s 内 −130 °，EASE_OUT），小臂 4 次摆动；endings 用 EASE_IN 收回 | 自然的 anticipation→sustain→settle 三段式 |
| jump 1.0s | 0.15s 蹲（y = −20, EASE_IN）→ 0.35s 起（y = +70, EASE_OUT）→ 0.55 悬停 → 0.8 落地（−10 impact）→ settle | **anticipation(预备)→action→follow-through** 完整三段结构 |
| attack 0.6s | 0.1 蓄力（40°, EASE_IN）→ 0.25 砍出（−80°, EASE_FAST）→ 0.4 收势 → D 归位 | wind-up→strike→follow-through |

共同习惯：
- **第一帧 curve 置空/线性**（`_kf(0, ..., curve=None)`），之后铺垫缓动——首个关键帧没有"前一段"，写 curve 无意义还会前后段截断错位；
- **缓动预设统一走 4 顶点宝贝 bezier**（EASE=标准/EASE_IN/EASE_OUT/EASE_BOUNCE=回弹/EASE_FAST），统一手感；
- 相位错开 0.5×/0.55× 而不是整齐 0.5 —— 一点点偏差让循环不那么机械。

### 3.5 调改格式 `adjustments.json`（AI 与外部互操作层）

AI 修骨骼时不直接说"改吧"，而是产出结构化账本：

```json
{ "adjustments": {
    "right-arm": {
      "original_offset": {"x": -1.5, "y": 0},
      "user_offset":     {"dx": -29.4, "dy": -84.1, "drot": 0},
      "final_offset":    {"x": -30.9, "y": -84.1}
    } },
  "draw_order": ["right-arm", ...] }
```

三重价值：**可审查**（每个部件一看就懂）、**可回退**（delta 明确）、**可叠加**（v1 final 是 v2 original，即"调整链"）。这个格式可以直接用在我们的工作流上：让 AI 修 Eva 拆件位置时也输出这种账本，对应我们"不许删产物、保留历史"的纪律。

---

## 4. 图集打包（`make_atlas.py`）

原理简单但稳定：**行式装箱**。

- 按高降序摆件，一排塞不下就换行；padding 默认 2 px（线性过滤下，**2–4 px 防外扩黑边**的最低门槛）；
- 贴图尺寸向上取 2 的幂（WebGL 友好）；
- 输出 `skeleton.png` + 手写 `.atlas` 文本（regionName 与 PNG 文件名一致 —— **attachment 名 = PNG 名 = slot 默认名**，三方_id 必须一致，否则 runtime 找不到 region 就是白屏）。

局限：不旋转、不去重（镜像件左右手会重复占区域）、不 trim —— 生产管线（TexturePacker / Spine 自带打包器）会做得更密，但可读性/可编程性优先时这里够用。**trim + offset 映射**是这层升级的关键（见 1.2 末尾）。

---

## 5. 预览：.transforms 一个自包含 HTML（`generate_spine_player.py`）

用官方 Web Player（`@esotericsoftware/spine-player@4.2.*`），**零服务**地玩所有功能：

- **`rawDataURIs`**：把 skeleton.json、atlas 文本、atlas PNG 直接 **base64 data URI 内嵌**进 HTML，单文件拷走即用。比"玩家+文件+server"的做法交付性好一个量级。
- 加载成败都走 JS 回调，`success` 里顺手把可用动画名/皮肤名 dump 到 console —— 省去 " 为什么没动 " 的排查时间。
- `premultipliedAlpha: false` 要与贴图生成方式对齐：我们的 PNG 是非预乘的，贴图管线重算时（spine-pixi/游戏 runtime）如果 mismatch，会出现**黑边/白边**。
- 常见慢性坑（沿用项目脚本注释）：
  - 白屏 → atla­s 里引用的 PNG 文件名对不上；
  - 控制台 404 → CDN 网络问题（这项目玩家用 unpkg，国内网络不保证稳定，可改本地 copy）；
  - 骨骼报 4.2 无效 → 必须查 hash/spine 字段，`spine: "4.2.0"` 是官方 runtime 的硬约束（Godot 的 spine-godot runtime 对小版本也敏感）。

### 交互版编辑器

`demo/sombrero_editor.html` 证明了一个真正值得记住的形态：**在 Web Player 上层加 overlay，拖动每个 slot，导出 layout JSON** —— 类似"轻量级自制 Spine 编辑器"，跟 reskin-app 的 SpineCanvas 用同一套 spine-pixi-v8 思路。对我们未来做"浏览器内 Eva 拼件验收工具"是直接可参考的实现。

---

## 6. Godot 4 对接视角（本项目的落脚点）

- Godot 4.4+ 上官方 spine-godot runtime 已支持导入 `%.Spine.json + .atlas + .png` 三件套，作为 `SkeletonModification2D` 的外部 `SpineSprite`/`SpineAnimationNode`（不是 Godot 原生 `Skeleton2D`），坐标系自动处理 Y-up。
- 注意：**Spine runtime 属于扩展**，需要从 Esoteric 下 `spine-godot` addon 包（版本必须与导出 JSON 的 spine 标记一致 —— 4.2 → spine-godot 4.2）；原生 `Skeleton2D` 不吃这个格式，所以 `skeleton.json` 也应保持"可以直接双击导入 Spine 编辑器"的兼容，这是双人协作/回修改的保险。
- 动画名、皮肤名在 Godot 里通过 `SpineAnimationNode` / `SpineSprite` 的 exposed API 控件切换，映射关系就是 1.1 的 S s/Attachment/Skin 结构。

---

## 7. 陷阱与排查表（实战摘录）

| 症状 | 根因 | 解法 |
|------|------|------|
| `position_parts` "not enough matches" | 纯色小件、对称件、ratio 太严 | 降 `--ratio` 到 0.75；确认 alpha 背景；对称件手动指定；或 `--min-matches 2` |
| 拼图大体对但个别件错 | 对称件被匹配反 / 同形件张冠李戴 | 用相对面积与命名先验预筛；或直接手改 layout.json |
| Spine 编辑器说 JSON 无效 | 标记 spine 版本不匹配 / bones 顺序错 | 确认 `"spine": "4.2.0"`；父 bone 必须出现在子之前 |
| 预览白屏 / 空白 | atlas 文件名对不上 PNG；MD5/网络问题 | 核对 atlas 首行文件名；--atlas-image 显式传；CDN 改本地 |
| 动画一帧后消失 / 骨骼不渲染 | rotate 用了 `angle`；bezier 只写了 4 位数的 8 属性曲线 | 字段改 `value`；`translate/scale/shear` 的曲线补足 8 个数 |
| 缓动生硬或抽搐 | bezier 控制点写了归一化小数 | 控制点用绝对 time/值，按 3.3 的换算公式 |
| 语义正确的"太高/太平"改不准确 | 忽略了 Spine Y-up | 屏幕上看要往上抬就不应动精确 → dy 取负 |
| 贴图边缘黑线/白晕 | premultipliedAlpha 与 PNG 打包方式不一致 | 保持 player 配置 `premultipliedAlpha: false`，贴图不做预乘处理 |

---

## 8. 对本工作区的落地建议

1. **拼件**：`assets/eva_bone/` 已具备分件+拼合图，等价上述输入。若后续要 AI 重绘部件（zenmux_edit 局部重绘）导致尺寸/角度漂移，**SIFT+RANSAC 4 DOF 是首选**，且我们的 `fit_parts.py` 可以借它比绝对/相对面积更普遍的变换求解；对称件依旧要靠命名先验，不能全信 SIFT。
2. **z 序**：遮挡投票的"像素级比色 vs 参考图"可以被 `alpha_split.py` / `slice-sheet.py` 复用在我们拆件管线回写 manifest 的 layer 顺序上，比纯猜或用 bbox 中心更可靠。
3. **调改账本**：把 `adjustments.json` 格式搬进我们的工作流，AI 每次修件输出一份 delta，形成链式可回退历史 —— 契合我们的"不许删产物"纪律。
4. **预览**：spine-player 的 `rawDataURIs` webhook 自包含 HTML 是**免费的动画预览德福** —— 我们可做一个 `tools/spine_preview.py`，包装 skeleton/atlas/png 三件套成单 HTML（CDN 换成本地 copy 以避免断网），让用户在浏览器直接验收 Eva 动画，无需 Godot 项目包围。
5. **本地备份每一原典**：本文档 + 克隆的 `docs/spine-animation-ai/` 可作为"手写 Spine 4.2 JSON + 自动拆件"的权威参照，`references/spine-json-spec.md` 中 bezier/curve/rotation 的坑是忧郁重要質料，千万别删。
