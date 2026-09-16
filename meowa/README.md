# meowa/ — AI 生图工作区

Eva 角色的生成素材、参考图与生成记录。**纯素材区**，生成走 `game-assets` skill 的 Meowa CLI。

## 目录

| 目录 | 内容 |
|---|---|
| `input/` | 原始素材 |
| `refs/` | 参考图；`refs/cel_style/` 是赛璐璐分阶参考索引（含实测数据与术语对照） |
| `templates/` | Meowa 预设信息 |
| `split_base_skin/` | 基础体拆件素材（**2D 时代的图，保留作美术参考**） |
| `outfit_split/` | 服装拆件素材（同上） |

## 硬约定

- 生成一律 **2K**
- **输入须合成纯灰底 205 保证不透明**
- 输出**透明 RGBA**
- 垂直锚点偏差 **≤ 2px**

## 凭据与跑法

key 在工作区根的 `.env`（`MEOWART_API_KEY`，已被 `.gitignore` 忽略）。
runner 从**执行命令的当前目录**读取 → 命令一律在**工作区根**下执行。

```bash
python ~/.agents/skills/game-assets/meowart_api.py credits-balance   # 校验
```

prompt 硬规则（单行、无引号、结构化约束……）见 `AGENTS.md` 的「Meowa / AI 生图规约」。

## 用途：原画生成

meowa 现在服务于 **3D 建模的原画需求** —— 为 Blender 建模与贴图提供参考图：

- **角色设定图 / 三视图**：正面 / 侧面 / 背面，供拓扑与比例对照
- **服装设计稿**：每件装备单独出图，供建模与拆件（同一 armature 下的部件）
- **配色 / 材质设定**：供贴图与 LUT 使用

> 2D 时代的「拆件拼图」用途已废弃。`split_base_skin/`、`outfit_split/` 里的图**保留仅作美术参考**，
> 不再作为生产链路的输入。

**三视图 prompt 要点**：必须显式要求**同一角色的致外观**（同一服装、同一配色、同一发型），
否则模型会在正 / 侧 / 背之间改变比例与细节，建模时无法对齐。
