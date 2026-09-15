# `slice-sheet.py` — 部件拼图切片工具

把生图产出的**整张部件拼图**切成「换装实验室」可用的部位贴图（+ `parts-manifest.json` 清单）。
放在 `tools/` 下，属于工作区自己的工具，不改 `tools/dressup-lab/` 的任何源码；产物交给
`tools/import-parts-to-dressup-lab.mjs` 走 API 导进实验室。

```bash
# 默认：切 assets/eva_bone/merged_sheet_FINAL.png → assets/eva_bone/parts/
python tools/slice-sheet.py

# 常用变体
python tools/slice-sheet.py --out tmp/parts_test                  # 换个输出目录做实验
python tools/slice-sheet.py --compare <另一个切件目录>              # 拉另一批切件同口径体检对比
python tools/slice-sheet.py --alpha-floor 16 --junk-alpha 0        # 更保守：不归零极淡像素
python tools/slice-sheet.py --bleed 1                              # 边界颜色外扩 1px（GPU 过滤防暗缝）
```

## 为什么需要它（2026-09-15 实测结论）

生图工具吐出的 PNG，透明区**不是干净的 `(0,0,0,0)`**，而是「alpha≈1 + 肤色 RGB」的**隐形脏像素**：

| 指标 | 原拼图直切 | 本工具输出 |
|---|---|---|
| 隐形残色（alpha≤16 却带 RGB） | **327,407** 个 | 2,659 个 |
| 极淡像素（alpha 1–8） | 5,761 个 | **0** 个 |
| 18 张合计体积 | — | 474 KB（同一批像素，体积纯编码差异） |

**为什么必须清理**：这些像素在原尺寸下看不见，但缩放 / 预乘 / mipmap 时会被当成有效颜色参与平均。
实测把 `torso` 缩到 50%（等效 mipmap）后，未清理版本在**底部 702–704 行**（生图拼接缝隙留下的一条
alpha 2–17 肤色带）产生 **203/255 的色差**，表现为一条暖色脏边；清理后消失。其余 17 件的影响在 2–3/255。

**清理是无损的**：`--clean-alpha 1` 只把 alpha ≤ 1 的像素写成 `(0,0,0,0)`，
在 白/黑/灰/洋红 四种底色上合成，最大可见差 **0.9/255**（黑底上 211 个像素），肉眼不可分辨。

## 切件规则

| 参数 | 默认 | 作用 |
|---|---|---|
| `--alpha-floor` | `8` | **内容范围阈值**：alpha > 它的像素才算内容，bbox 由它决定（细笔画能保住） |
| `--min-area` | `64` | 小于它的连通域当碎渣丢掉（避免飞点撑大 bbox 或混进别件） |
| `--junk-alpha` | `8` | **极淡归零**：alpha ≤ 8（3% 不透明度）直接写成透明 —— 任何底色都看不见，但会撑 bbox、在图集里成灰雾 |
| `--clean-alpha` | `1` | **残色清零**：alpha ≤ 1 的像素连 RGB 一起清零（就是上表里那 32 万个脏像素） |
| `--bleed` | `0` | 把边界颜色向外扩 N 像素（alpha 仍为 0），纹理走 GPU 线性过滤时防暗缝用 1~2 |
| `--close` | `0` | 闭运算次数，补断线（描边断开时用 1~2） |
| `--merge-gap` | `0` | 相距 ≤ N px 的碎片并回同一件（细笔画断开时用 4~8） |

切件 = 连通域（8 邻接）的紧包围盒；**同 bbox 内属于别件的像素会被剔除**，不会串件。

面部五官分两种拿法：

- **眼 / 嘴**：独立连通域，直接按连通域切（判据：宽 > 高）；
- **眉毛 / 鼻梁**：实测它们是**独立细笔画域**——闭运算 2 次 + 间隙合并 10px 都并不进任何别的件，
  所以按**相对眼睛与脸型的自适应区域**抠（眉毛 = 眼睛上方 0.2~1.1 倍眼高；鼻梁 = 眼睛下缘稍下 → 嘴上缘的中缝窄带）。
  坐标不写死，换一张拼图也不会因为位置变化而抠空或抠到上唇。

## 内置体检

工具跑完会自己出一份同口径体检表（`--compare` 可把任意另一批切件拉进来对比）：

```
  本次切件 parts/          件数 18  像素 1267256  隐形脏 2659  极淡 0  针孔 16  越界实心 18
```

- **隐形脏**：alpha≤16 却带 RGB 的像素（越少越好）
- **极淡**：alpha 1–8 的像素（应为 0）
- **针孔**：实心区里 1px 的洞（形态学闭运算检出；16 个来自原图本身的描边断点）
- **越界实心**：贴到切件最外圈的实心像素（>0 说明该边被裁断；正常只出现在拼图边界与相邻件贴合处）

## 切完补描边：`tools/outline-part.py`

拼图切出来的**皮肤件**在原画里**没有线稿** —— 脸型就是一个平涂色块，下颚线一个像素都没画
（线稿只存在于头发 / 五官上，实测该美术的线色核心 = `rgb(24,14,12)`）。同时脸压在躯干的脖子/肩上，
两侧同色 → **边界彻底消失，成品是个没有下巴的脸**。修法是按配置补一条同色**内描边**：

```bash
python tools/outline-part.py --config assets/eva_bone/parts/outline.json --project human_female
```

- **只改 RGB，alpha 一个字节不动** → 贴图尺寸、部位 bbox、裁剪框、导出的越界校验全都不受影响；
- 描边权重来自「到轮廓的有符号距离」：轮廓内侧 `width` px 是线色，再往里 1px 淡出；轮廓外的
  抗锯齿像素也一并拉成线色（不这么做最外圈会留一条**亮边**，缩放后显成灰边，正是上面费劲清掉的东西）；
- 参数写在 `assets/eva_bone/parts/outline.json`（哪些部件 + 宽度/线色），默认 `2px #241a17`；
- **幂等**：写完在 PNG 里打 `tEXt` 标记 `SpineOutline`，同参数重跑直接跳过；参数变了要 `--force`；
  想彻底还原就重跑 `slice-sheet.py`（切件是确定性的）。

自检第 14 组守着这条链：配置里列的部件**必须带标记**（重切后忘了补 → 立刻红，并给出上面那行命令），
且项目 `images/` 里的副本与切件目录**逐字节相同**。

> **实验室里还有一套描边**（部件库条目右键 → 描边…，存 `project.json → partLib.outline`，
> 渲染与导出时烘进位图）。两者机制不同但约束一致（都只改 RGB 不动 alpha）：
> · **烤进 PNG**（本工具）：对实验室就是"原图的一部分"，换项目也带着，适合**基础件**（脸型这种一直要线的）；
> · **实验室设置**：跟着项目走、随时可调可关，适合**试**和**批量**（四肢要不要线还在犹豫的那种）。
> 实验室的描边对话框会探测 PNG 里的 `SpineOutline` 标记并警告 —— 已经烤过的图别再开一次，会变成两道线。

| 档位 | 效果 |
|---|---|
| `--width 1.2` | 比原画细，缩放后偏虚 |
| **`--width 2`（默认）** | 与原画下颚线粗细一致（原画头宽 355px 时线宽约 1.5px，本件脸宽 222px） |
| `--width 2.5~3` | 接近眼睫毛的份量，更醒目但偏重 |

想看效果不落盘：`python tools/outline-part.py head_base --preview tmp/face.png --width 1.6,2,2.5`

## 重切之后要跟着做的三件事

切片口径一变，部件的 bbox / 落点会整体平移 1~2px，下游要同步重建：

```bash
# 1) 重建项目（上传不覆盖同名文件，必须先删项目）
curl -X POST http://127.0.0.1:8791/api/project/delete -H "content-type: application/json" -d '{"name":"human_female"}'
node tools/import-parts-to-dressup-lab.mjs --project human_female --manifest assets/eva_bone/parts/parts-manifest.json

# 2) 补描边（缺了脸就没下巴；第 14 组会红）
python tools/outline-part.py --config assets/eva_bone/parts/outline.json --project human_female

# 3) 让配套资产跟上项目（锚点库 + 导出交付物），并跑自检
node tools/lab-sync-project.mjs            # 加 --check 只体检不写
node tools/dressup-lab/scripts/verify.mjs
```

> 项目在实验室里被编辑过（挪部件 / 改画布 / 开关裁剪 / 换贴图）之后，锚点库与导出交付物就会过期：
> 锚点库过期 → 点「载入锚点库」会把部位弹回旧布局；导出产物过期 → 自检第 12 组会跳过并提示
> （结构一致但**换了贴图**这一类由「输入比交付物新」兜住）。
> 这两件事都由上面的 `lab-sync-project.mjs` 一次修好（导出走实验室自己的导出实现，需要浏览器）。

## 关于「裁剪」（部件跑出部位就不显示）

导入脚本给每个部位写的 `clip` 是 **true**：部件超出部位 bbox 的部分**只在画布与预览里被遮挡**，
**原贴图文件一个字节都不会改**（导出的 `slots.json` 只带 `clip` 矩形，让运行时自己去切）。
这是"拖动部件时忘了连部位一起动"的可见报警 —— 拖出去就会立刻少一块。
2026-09-15 之前导入脚本写的是 `clip: false`，等于把这个保护关掉了，现已改正。

## 和其它脚本的关系

```
merged_sheet_FINAL.png
   └─ tools/slice-sheet.py ──→ assets/eva_bone/parts/*.png + parts-manifest.json
        └─ tools/outline-part.py ──→ 同目录贴图补内描边（只改 RGB）+ 覆盖项目 images/ 里的副本
             └─ tools/import-parts-to-dressup-lab.mjs ──→ 实验室项目（走 API）
                  └─ tools/lab-sync-project.mjs ──→ 锚点库 + 导出交付物
```

> `outline-part.py` 若要覆盖项目贴图需要 `--project <项目名>`；只切件不进项目时可以不加。
> 注意它的位置在 `import` **之前**还是**之后**都行 —— 它按文件名覆盖，不改任何项目元数据。
