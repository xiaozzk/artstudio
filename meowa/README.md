# meowa/ — AI 生图工作区

Eva 基础体（Spine 用）的 AI 生成素材、参考图与工作记录。
生成走 Meowa CLI（`~/.agents/skills/game-assets/meowart_api.py`，skill 版本 `2026.09.13.1`）。

## 凭据

key 放在**本工作区根的 `.env`**（已被 `.gitignore` 忽略）：

```dotenv
MEOWART_API_KEY="ma_live_..."
```

runner 从「**执行命令的当前目录**」读取 `.env` → 命令请在 `D:\spine` 下执行。
注意 runner 用 latin-1 解析 `.env`，**不要写中文注释**。
校验：`python ~/.agents/skills/game-assets/meowart_api.py credits-balance`

## 硬性约定

- 生成一律 **`--resolution 2K`**。
- 输出必须是**透明背景 RGBA**；但 `image-2` 的**输入必须不透明** ——
  先把图合成到**纯灰底 205**，出图后用 `--remove-bg-method standard` 去背。
- 目标运行时：Godot 4 + spine-godot ≥ 4.2，导出 **JSON + atlas**。
- 画布**垂直锚点必须保持**（头顶 y / 脚底 y 偏差 ≤ 2px），否则骨骼对不上。

## 当前路线（2026-09-14 起）

从「用 GPT 把整身拆成零件表」改为「**用户自己切件 → 只用 GPT 精修关节边缘**」。

| 事项 | 位置 |
|---|---|
| 唯一工具（10 个子命令） | `tools/spine_joint_tool.py` |
| 经验总结 + 标准 prompt | `meowa/JOINT_REFINE_NOTES.md` |
| 最终成品 | `assets/eva_bone/merged_sheet_FINAL.png` |
| job_id 存档（误删可免费重下） | `split_base_skin/base_ref/job_ids.md` |
| 用户手绘套索带几何 | `split_base_skin/base_ref/selection_polys.json` |

## 目录结构

```
meowa/
├── input/                    生成用的输入素材
│   └── assembled.png         原图（= assets/eva_bone/assembled.png）★ 一切的原点
├── refs/                     参考图
│   ├── ref_body_underwear.png   A-pose 正面基础体（黑内衣）
│   └── ref_bikini_style.png     挂脖三角比基尼款式参考
├── templates/                Meowa 预设信息（pixel / large-pixel / hd + 总览）
├── split_base_skin/          拆件工作区
│   ├── REPORT.md               拆件方案的评估报告（历史）
│   ├── prompt_*.txt            各轮 prompt 存档
│   ├── refs/merged_sheet.png   ★ 用户交付的成品拼图
│   └── base_ref/               基准资产：job_ids / 套索带几何 / PS 选区数据 /
│                               各版 prompt / fix2 基线 / 用户的参考图与手绘稿
├── README.md
├── PIPELINE_NOTES.md         旧方案（919×1672）的完整生成链路记录
└── JOINT_REFINE_NOTES.md     ★ 当前路线的经验与 prompt
```

## 历史产物（旧 919×1672 方案，已停用）

`assets/eva_bone/assembled_bikini_white.png`（919×1672 白色挂脖三角比基尼）、
`assembled_underwear.png`（894×1672 黑内衣 A-pose）—— 该路线的**脚本、中间生成步、
spec.json、失败记录、我的诊断图**已于 2026-09-14 清理（meowa 7.38 MB → 4.93 MB），
链路与结论完整保留在 `PIPELINE_NOTES.md` 和 `split_base_skin/REPORT.md`。

> `split_base_skin/REPORT.md` 里点名的 `scripts/*.py` 已随清理归档，
> 对应能力并入 `tools/spine_joint_tool.py`，报告正文保留为历史记录。

## 重跑命令模板

```powershell
# 凭据已在 D:\spine\.env，无需每次设置
python C:\Users\xiaozzk\.agents\skills\game-assets\meowart_api.py image-edit-run `
  --reference-image <输入图.png> `
  --reference-image <参考图.png> `
  --prompt "<prompt 单行、不含引号字符>" `
  --mode hd --generation-model <image-2|image-2.5|nano-banana> `
  --resolution 2K --quality <standard|detailed|ultimate> `
  --remove-bg-method standard `
  --output-dir meowa\split_base_skin\joints\<新编号>_<描述>
```

或者直接用工具：

```powershell
$T = tools/spine_joint_tool.py
python $T prep                                   # 生成灰底输入图
python $T gen   --part legs --runs 2 --tag v2    # 发任务
python $T verify --candidate <remove_bg.png> --region legs
python $T apply  --candidate <remove_bg.png> --region legs --out <拼图.png>
```

> 失败/中断**不要重新提交**（会重复扣费）。用原 `job_id` 轮询恢复：
> `image-2-poll --job-id <id>` / `nano-banana-poll --job-id <id>`。
> 生成失败会**自动全额退费**（`final_outputs.json` 里 `credit_refund.refunded = true`）。

## 踩坑速查

| 坑 | 要点 |
|---|---|
| prompt 带引号 | PowerShell 包装层会拆碎参数 → 用 `key = value; key = [a, b]` 结构化写法 |
| 多行 prompt | 同上，必须压成单行 |
| 同 prompt 两个任务 | 必须给**不同的 `--output-dir`**，否则互相覆盖 |
| `ui-gen-run` | 有强烈 UI 偏好（会画面板/血条），拆件图别用它 |
| `--strict` | 只在 `--mode pixel` 下可用 |
| HD 去背 | 只支持 `none` / `standard` |
