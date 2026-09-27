# 成品动画参数迁移（anim retarget）：给交付包批量加功能动作

| 项 | 值 |
|----|-----|
| 编号 | 002 |
| 目录 | `task/002-anim-retarget/` |
| 状态 | 进行中 <!-- 规划中 / 进行中 / 已完成 / 已放弃 --> |
| 创建 | 2026-09-24 |
| 更新 | 2026-09-25 |

## 目标

~~56 个已交付的 Spine 包批量获得功能性动作~~（2026-09-25 用户收窄为 MVP）：
**找骨骼相近的 A/B 两个包，用 harness 流程把 B 的 1~2 个简单动作高质量迁到 A**，
沉淀出 agent 可复用的 skill（SKILL.md 手册 + 确定性脚本集）。
远期形态（非本任务验收范围）：任意交付包加动作 = 挑模板 + 映射表 + 一条命令。

**AI 只做评估标注与风格判断**；提取 / 注入 / 校验全是确定性脚本。

## 验收标准

- [x] **回环无损**：法袍法师 attack 恒等映射注回自身 → 15 骨时间轴数值 diff = 0
- [x] **跨包迁移成立**：attack + death 迁到络腮胡剑士 → 官方 player 预览连贯
      （蓄力/爆发/收势三段相位、倒地侧翻全对），部件不散架
- [x] **校验器拦得住**：不存在骨骼名报错退出 / 非白名单通道丢弃告警 /
      非法 curve 拒绝 / 循环闭合按动画类型区分（idle/run 查、death 不查）
- [x] **产物链齐全**：mapping.json + 注入后 JSON + 单文件预览 HTML +
      retarget-report.json
- [x] **preview-2d 改造**：105 包 spine 预览（切动画/切皮肤/数量徽标），
      vendor player 4.3.13 离线化；**实验产物区**：task/*/output/ 的迁移包
      自动进「实验产物」区块（验收标准「A 包新增动画在 preview-2d 可播放」
      由此闭环——实测攻击动画播放连贯）
- [ ] 用户验收：preview-2d 里看迁移效果，确认「能看」

## 产出

| 路径 | 说明 |
|------|------|
| `notes/2026-09-24-调研.md` | 两个参考项目分析 + 法袍法师 8 动画关键帧实测 + A/B 选型记 |
| `input/mapping_luosai.json` | 法袍法师→络腮胡剑士 语义映射表（含证据注记，可抄） |
| `output/络腮胡剑士/NPC2.json` | 注入 attack+death 后的骨架（原包未动） |
| `output/络腮胡剑士/preview.html` | 单文件离线预览（官方 player 内嵌，5 动画可切） |
| `output/络腮胡剑士/retarget-report.json` | 迁移报告（映射命中/丢弃/符号翻转） |
| `tools/spine/anim/`（跨任务复用） | render_rig / anim_dump / anim_retarget / anim_preview + SKILL.md 手册 |
| `tools/preview-2d/`（改造） | 105 包 spine 预览：徽标 + 全屏 player（切动画/皮肤），vendor 离线 |

## 步骤

1. ~~参考源盘点~~ → **实测替代**：法袍法师包自带 8 个功能动画（idle/run/attack/damage/
   death/defence/free_run/skill_magic），结构干净（纯 bone 通道），就是模板源；
   spineboy 官方 JSON 可得性留作扩展参考源再查。
2. 模板提取器：`tmp/法袍法师/kf_dump.py` 扩展为**归一化模板**导出（时间归一 [0,1]、
   幅度按骨长/bbox 记相对值、curve 类型保留）。
3. 语义映射表：参考骨名 → 目标骨名，人工 + AI 一次生成，每包一份可复用。
4. 注入器 + 校验器：写 `animations` 段（只 bone rotate/translate/scale 通道）；
   校验 = schema / 骨骼白名单 / 循环闭合 / curve 合法值。
5. 预览验收：官方 spine-player 单文件（`rawDataURIs` 内嵌，版本与包对齐——
   法袍法师是 4.3.26 用 `@4.3.*`），已在 tmp/ 实证通过。
6. 试点：回环验证（法袍法师→法袍法师）→ 跨包迁移（法袍法师→试点包2）。

## 决策与笔记

- 2026-09-24：**路线选型**。两条路线（prompt 直写 / 参考迁移 B1）定为**混合**：
  波形来自成品参考，幅度与修饰由 prompt 层调。动画形态定**功能性动作**；
  落点定 **JSON 动画层 + 官方 player 预览先验**（`.spine` 工程最后人工进编辑器，
  或走 Spine CLI `Spine -i x.json -o x.spine -r` 反转——Spine-AI-Generator 实测可用，
  需已激活的编辑器）。
- 2026-09-24：**关键帧语法实测**（法袍法师 8 动画 + idle/run/attack/skill_magic 全量）：
  99% 线性插值 + 少量 `stepped`（定格/硬直），**零贝塞尔**；平滑与震颤都靠关键帧
  密度；时长全是 30fps 整帧数（0.67s=20 帧）；所有循环动画末帧回零。与
  Spine-AI-Generator「不写 curve、密度换平滑」注释哲学完全撞车 → 模板格式不需要
  贝塞尔字段。
- 2026-09-24：**4.3 JSON 解析陷阱**：首帧省略 `time`（缺省=0）；rotate 读 `value`、
  translate/scale 读 `x/y`；3.8 旋转键名是 `angle`（本工作区包全是 4.x，只记档）。
  另有 Spine-AI-Generator 注释坑：`curve:'smooth'` 非法（只认 `stepped`/贝塞尔数组）；
  `translate` 是相对 setup pose 的偏移，写绝对坐标会把角色平移出画面。
- 2026-09-24：**渲染出口选型**：用官方 player 单文件（语义 100% 保真、零维护），
  **不自研 canvas 渲染器**。自研版（Spine-AI-Generator `web/renderer.js`，region +
  LBS mesh 蒙皮可跑）留作「批量时序截图对比」场景的底稿，需要时再抄；其蒙皮注释
  （restWorld 必须世界坐标、每骨各持一份局部顶点）已记入调研笔记。
- 2026-09-24：tmp 原型：`tmp/法袍法师/render_preview.py`（4.3 版 player 生成器，改自
  spine-animation-ai 的 `generate_spine_player.py`，只动 CDN 版本号）、
  `tmp/法袍法师/kf_dump.py`（关键帧解析雏形）。动工时正式化进 `tools/spine/`。
- 2026-09-25：**目标收窄为 MVP**（用户睡前指令）：不做 56 包批量，做 A/B 配对 +
  harness 流程；用户确认 preview-2d 并存增强、要 Claude SKILL.md 形态、骨骼语义
  靠多模态看图（不支持图的环境委派 subagent）。
- 2026-09-25：**preview-2d 改造完成**（tools/preview-2d）：serve.py 扫骨架/图集/
  动画/皮肤进 manifest.spine_index（105 包全检出、1120 动画）；preview.html 卡片
  徽标 + 全屏官方 player。实测坑已写进 README：atlas 页头字段乱序、player 4.3
  config 字段是 skeleton/atlas（4.2 的 jsonUrl 会报 URL must be specified）。
- 2026-09-25：**A/B 选定**：A=络腮胡剑士（24 骨 boneN 无语义、3 动画、直立持剑
  面朝左），B=法袍法师（22 骨语义命名、8 动画、直立持杖面朝左）。评估依据：
  同为人形男直立、朝向一致、骨数近、拓扑同构（bone6→7→8 ≡ arm_l1→l2→l3，
  setup 世界朝向差仅 1°）、A 无 attack/death 可验收「从无到有」。
- 2026-09-25：**MVP 迁移成功**：attack（挥杖→挥剑，蓄力-爆发-收势三段连贯）+
  death（倒地侧翻）迁入络腮胡；回环自检 attack 恒等映射 15 骨 diff=0。
  校验器修正：death 是单发动作不该查循环闭合（按动画名启发式区分）。
- 2026-09-25：遗留：①迁移只做增量直搬+轴向符号，**幅度未按骨长/身高缩放**
  （两包身高比 ~1.12，attack 纯 rotate 无感；translate 多的动作要补缩放标定）
  ②络腮胡 4 件 mesh 附件自研渲染降级线框（player 验收不受影响）
  ③arm_l3→bone8 符号翻转（bone8 是 429 长的剑骨，朝向定义特殊，翻转后视觉正确，
  已在验收截图确认）。
- 2026-09-25（用户验收反馈）：**「朝向反了」** —— v1 映射表按画面位置映射左右，
  但两包朝向相反（法袍朝左/络腮胡朝右，复原预览图确认），骨架局部朝向却几乎
  相同（242°≈243°）——同增量在朝右角色身上变成「朝背后挥剑」。
  **教训：判定朝向看复原预览图，骨骼局部朝向相同 ≠ 面向相同；映射按角色语义
  （左手↔左手），不按画面位置。**
- 2026-09-25：**新增 spine_flip.py**（JSON 级水平镜像换朝向）：bones x/-rot、
  region x/-rot/scaleX 取负（贴图翻转）、mesh 加权顶点 x 取负 + triangles 绕向反转；
  动画 translate.x/rotate.value 取负；slots/attachments/drawOrder 告警保留；
  含 IK/constraints 报错退出（全库 64/105 含 IK，暂不支持）。`--check` 双翻回原文
  自检（两包都过；自检抓出并修掉两个 bug：加权顶点骨段步进错位、scaleX 缺省
  归一化）。流程新增「**阶段 0.5 朝向统一**」：朝左包 flip 成朝右 → render_rig 渲染
  + agent 看图确认 + player 验证动画合法 → 再迁移。
- 2026-09-25：v2 映射表（左右按语义互换）重迁 attack+death：符号翻转 8 轨
  （flip 后臂朝向差 ~180° 自动适配），攻击挥剑方向与角色面向一致（截图验证）；
  flip 后法袍包在官方 player 播放 8 动画正常（镜像数据被官方 runtime 接受）。
  flip 产物归档 `input/法袍法师-flipped/`。
- 2026-09-25（goal round 2）：修 death 影子不跟人走。**误诊→正解**：先以为是
  「影子位移是世界系，跳过旋转」，实为 translate 值活在**父骨骼坐标系**，
  应按「父骨骼世界朝向差」旋转（源父 root 0° → 目标父 bone 90° ⇒ 转 −90°）。
  已改为父空间模型并加客观回归判据：逐帧 translate 换算世界位移，源/产物相等
  （death 的 Shadow / body_2 / arm_l2 全部 ✅）。SKILL.md 阶段 2 已记录该坑。
- 2026-09-25（goal round 2 续）：**朝向验证闸门落地**（用户要求）。mapping 新增
  `facing_A`/`facing_B`（agent 看复原预览图判定）；`anim_retarget.py` 迁移前反查：
  声明不一致 → 拒绝；有眼骨时用「眼骨相对父骨世界 x 偏移」判面向，与声明矛盾 →
  拒绝；无眼骨（全库 17/105 有）→ 明确告警。实测三条路径：一致放行 / 朝左原包
  冒充 right 被拦 / 未声明告警。SKILL.md 阶段 0.5 已文档化。

