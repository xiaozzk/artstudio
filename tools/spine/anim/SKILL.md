---
name: spine-anim-retarget
description: >
  把成品 Spine 动画从一个交付包（B，动画多）迁移到另一个骨骼相近的包（A，动画少）。
  当用户要求「给某角色加动作」「把 A 包的 attack 迁到 B 包」「动画迁移 / 动作复用 /
  参考 B 的动画给 A 做动画」时使用。覆盖完整 harness：评估骨骼兼容性 → 视觉语义标注
  → 对齐映射 → 注入校验 → 渲染验收。适用对象是 assets/2d/ 下的 Spine 4.3.26 交付包
  （runtime JSON + atlas + 图集）。
---

# Spine 动画迁移 Harness

把 B 包的功能性动作（attack / death / jump…）高质量迁到 A 包。
**AI 只做评估标注与风格判断；提取 / 注入 / 校验全是确定性脚本。**

工具集（`tools/spine/anim/`）：

| 脚本 | 一句话 |
|------|--------|
| `render_rig.py <包> -o <目录>` | 渲 setup pose + 骨骼拓扑叠加图 + rig.json（骨骼世界坐标/朝向清单） |
| `spine_flip.py <包> -o <目录> [--check]` | JSON 级水平镜像（换朝向）；`--check` 双翻回原文自检 |
| `anim_retarget.py --A <包> --B <包> --anim <名> --map <映射.json> --out <目录>` | 按映射表把 B 的动画增量时间轴注入 A 的副本（**永远不动原包**） |
| `anim_preview.py <包目录> [--animation 名] [-o out.html]` | 生成单文件离线预览 HTML（官方 player 内嵌，双击即开） |

---

## 阶段 0.5：朝向统一（**迁移前置，别跳**）

**两包朝向不一致时，同样的旋转增量视觉方向相反**（v1 实测翻车：法袍朝左、
络腮胡朝右，骨架局部朝向却几乎一样（242°≈243°），增量直搬后动作朝背后挥）。

**判定朝向看复原预览图，不看骨骼名**：骨骼局部朝向相同 ≠ 角色面向相同。
脸的朝向、持械手位置以 `复原预览图.png`（美术原图复原）为准，rig_pose.png 辅助。

统一流程（统一到朝右）：

```bash
# 1. 朝左的包 flip 成朝右（带数学自检：双翻回原文）
python3 tools/spine/anim/spine_flip.py "assets/2d/<包>" -o tmp/flip/<包> --check
# 2. 渲染 flip 结果，agent 看图确认真的朝右了（语义验证，脚本替代不了）
python3 tools/spine/anim/render_rig.py tmp/flip/<包> -o tmp/rig/<包>-flipped
# 3. player 验证 flip 后动画数据仍被官方 runtime 接受
python3 tools/spine/anim/anim_preview.py tmp/flip/<包> --animation idle
```

- 映射表按**角色语义**写（左手↔左手），不按画面位置——flip 后画面位置会变。
  判断左右手：3/4 侧视角色面朝右时，右手在画面左前侧（持械手常是这只）。
- flip 后骨骼 setup 世界朝向变号，`anim_retarget.py` 的符号检测自动适配，
  报告里 `tracks_sign_flipped` 逐条人工核对即可。
- 边界：含 IK/constraints 的包 flip 会报错退出（全库 64/105 含 IK，暂不支持——
  遇到换包，或先解 IK 再翻，见 Spine图集修复通用经验.md §9.6/§15）。

### 朝向验证（agent + 脚本双层，**迁移前必跑**）

方向判错代价很大（动作整体朝背后挥），所以做成两层闸门：

1. **agent 视觉声明**（主）：看 `复原预览图.png`，把判断写进 mapping：
   `"facing_A": "right"`、`"facing_B": "right"`。
2. **脚本反查**（次，`anim_retarget.py` 自动执行）：
   - 两条声明不一致 → **拒绝迁移**，提示先 flip；
   - 包里有**眼骨**时按「眼骨相对父骨的世界 x 平均偏移」判定朝向
     （3/4 侧视眼睛长在面前侧）：声明与数据矛盾 → **拒绝执行**；
   - 无眼骨（全库仅 17/105 有）→ 明确告警「数据层判不了，依赖 agent 看图确认」。

⚠ 别用「头骨前倾方向」之类代理信号：络腮胡的头骨偏向画面左但它面朝右，代理判反。
朝向本质是语义判断，脚本只能反查、不能替代看图。

## 阶段 0：选配对（找 A 和 B）

原则：**骨骼结构相近 + B 动画多 / A 动画少且缺目标动作**（朝向不一致没关系，
走阶段 0.5 统一）。

```bash
# 全量包速览（版本/动画数/骨骼数/皮肤）
python3 tools/preview-2d/serve.py scan
# 逐包看骨骼：渲染拓扑图自己看
python3 tools/spine/anim/render_rig.py "assets/2d/人形/男/法袍法师" -o tmp/rig/法袍法师
```

- 候选筛：`动画 ≤4 个`的包是 A 候选；法袍法师（22 骨语义命名、8 动画）是首选 B。
- 骨数不必相等（A 缺段就丢轨），但**主干拓扑要同构**：脊柱链、双臂链、双腿链。
- 动画最多的包骨骼常是 bone12 式无语义命名且量大（骑士领主 98 骨）——MVP 别选这种当 B。

## 阶段 1：评估（视觉语义标注）

对 A、B 各跑 `render_rig.py`，**读 overlay 图 + rig.json + 槽位清单**做标注：

1. **定骨骼类型**：人形 / 兽形。本 skill 目前只支持人形（双臂双腿直立）。
2. **找主要骨骼**（用户方法论原文）：中心节点 / 胯 / 脊柱 / 头 / 左右手臂链 /
   手腕 / 左右腿链 / 脚 / 影子。无语义命名（bone12）时靠：
   - **空间位置**（rig.json 的世界坐标：头最高、腿在 y≈50~110、臂在肩线 y≈270）
   - **挂的槽位名**（lhand/rhand/tou/wq 等拼音缩写常带语义）
   - **overlay 图**（骨骼点落在哪个部件上）
   - 多模态要求：当前 agent 须能读图；不能读图就把标注子任务委派给
     支持图像的 subagent（workflow 的 `agent(prompt, {model})` 可指定
     glm5.3-flash / deepseekflash）。
3. **判定通过/不通过**：A 缺整条手臂链或腿链 → **评估不通过，停止**，在任务档案
   记录原因。A 只是缺手腕/手指等末端 → 通过（对应轨道丢弃即可）。
4. **动作分析**：用 kf_dump 思路读 B 的目标动画：哪些骨骼有轨道、rotate 还是
   translate、谁是主要动作骨（幅度大的）、动作类型（攻击/倒地/待机）。
   决定迁移范围：**宁可只迁主要骨（躯干+双臂+头）保证流畅，也不硬迁全部**。

产物：`mapping.json`（见下）+ 评估结论写进任务档案。

## 阶段 2：对齐（映射表）

`mapping.json`：

```json
{
  "facing_A": "right",
  "facing_B": "right",
  "mirror": false,
  "bone_map": { "arm_l1": "bone10", "body_1": "bone4", "Shadow": "bone23" }
}
```

对齐规则（脚本自动处理，你只需给对 bone_map）：

- **时间轴值是增量**（相对 setup pose）：同构骨骼直搬增量即天然对齐。
- **rotate 符号自动判定**：两骨 setup 世界朝向差 >90° 时增量自动取负
  （报告里 `tracks_sign_flipped` 会列出，逐条人工核对是否合理）。
- **translate 是「父骨骼空间」的量**（Spine 语义）：按**父骨骼**世界朝向差旋转
  向量 + 按身高比缩放。⚠ 别用骨骼自身朝向差——影子骨（父 root 0° → 父 bone 90°）
  会因此把水平位移转成垂直，表现为「影子不跟人走」（2026-09-25 实测踩过）。
  客观判据：迁完后把每帧 translate 用 `R(父骨骼世界朝向)·v` 换算成世界位移，
  与源包同帧对比应完全相等（脚本改动的回归验证就用的这条）。
- **朝向相反**用阶段 0.5 的 flip 统一（`mirror: true` 是另一条路，本批未用）。
- **左右判定按角色语义，不按画面位置**：先看复原预览图定向，再定左右手
  （3/4 侧视面朝右时，右手在画面左前侧，常是持械手）。

## 阶段 3：注入 + 校验

```bash
python3 tools/spine/anim/anim_retarget.py \
  --A "assets/2d/<A路径>" --B "assets/2d/<B路径>" \
  --anim attack --anim death \
  --map task/002-anim-retarget/input/mapping_xxx.json \
  --out "task/002-anim-retarget/output/<A名>"
```

校验器自动拦：不存在的目标骨（报错退出）/ 非白名单通道（丢弃并告警）/
非法 curve 值 / 循环类动画首尾不闭合（idle/run/walk/stand 才查，death/attack
这类单发动作本来就不闭合）。

## 阶段 4：渲染验收（必须看图）

```bash
python3 tools/spine/anim/anim_preview.py "task/002-anim-retarget/output/<A名>" \
  --animation attack
```

用 chrome-devtools 打开产物 html，**抓 3~4 帧关键姿势**（蓄力/爆发/收势），逐帧判：

- 动作语义是否成立（挥砍像挥砍、倒地像倒地）
- 有无违反动画原则：部件瞬移、关节反折、穿插断裂、帧间跳变
- **不连贯 → 回阶段 1 减范围**（少迁几条轨道，保主要动作骨），不是硬调数值

验收通过后：产物 json/html 留 task 档案 output/，过程记录进 notes/。

---

## 格式陷阱速查（实测踩过，校验器已内置）

| 陷阱 | 现象 | 规则 |
|------|------|------|
| 首帧省略 `time` | 解析出 time=-1 | 缺省即 0 |
| 4.3 rotate 键名 `value` | 3.8 的 `angle` 在 4.x 静默不动 | 只支持 4.x |
| `curve:'smooth'` 非法 | 运行时解析失败 | 只许省略(linear)/`stepped`/贝塞尔数组 |
| translate 是增量 | 写绝对坐标角色跑出画面 | 时间轴值全部相对 setup pose |
| player 4.3 字段名 | 报 "A URL must be specified" | 用 `skeleton`/`atlas`，不是 4.2 的 `jsonUrl`/`atlasUrl` |
| atlas 页头字段乱序 | 页名漏检 | 页名行=顶格+无冒号+图片扩展名，别依赖下一行是 size: |

## 已验证实例（2026-09-25）

A=络腮胡剑士（24 骨 boneN 无语义，3 动画）← B=法袍法师（22 骨语义命名，8 动画）：
attack（挥杖→挥剑）与 death（倒地）迁移成功，蓄力/爆发/收势连贯，
映射表 `task/002-anim-retarget/input/mapping_luosai.json` 可当模板抄。
