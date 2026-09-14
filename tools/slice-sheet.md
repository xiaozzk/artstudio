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

## 重切之后要跟着做的三件事

切片口径一变，部件的 bbox / 落点会整体平移 1~2px，下游要同步重建：

```bash
# 1) 重建项目（上传不覆盖同名文件，必须先删项目）
curl -X POST http://127.0.0.1:8791/api/project/delete -H "content-type: application/json" -d '{"name":"human_female"}'
node tools/import-parts-to-dressup-lab.mjs --project human_female --manifest assets/eva_bone/parts/parts-manifest.json

# 2) 重生成配套锚点库（bbox 变了）
node tmp/gen_anchor_lib.mjs

# 3) 重生成导出交付物 + 刷新自检里的 golden 落点
node tmp/gen_export_fixture.mjs human_female
node tmp/gen_golden.mjs            # 把输出贴进 scripts/verify.mjs 第 6 组的 GOLDEN
node tools/dressup-lab/scripts/verify.mjs
```

## 和其它脚本的关系

```
merged_sheet_FINAL.png
   └─ tools/slice-sheet.py ──→ assets/eva_bone/parts/*.png + parts-manifest.json
                                    └─ tools/import-parts-to-dressup-lab.mjs ──→ 实验室项目（走 API）
```
