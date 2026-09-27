# local_edit.py — 本地图片编辑（mini-local sd-server / Qwen-Image-2.1）

对接 mini-local（192.168.3.28）上 stable-diffusion.cpp HTTP server（`sd-server`）的
**Qwen-Image-2.1 图生图**服务。**纯局域网、不消耗任何 API 额度、无计费风险** ——
图片编辑场景的免费入口；要更快 / 多 mask / 更强的语义理解再考虑同目录的
`zenmux_edit.py`（花 ZenMux 额度，见 [`zenmux-edit.md`](zenmux-edit.md)）。

服务端接口文档在 mini-local 上：`~/Desktop/project/llm/docs/sd-server-qwen-i2i-api.md`。

## 命令

**一律在工作区根下执行**（工具从根目录 `.env` 读 `SD_SERVER_HOST`）。

```powershell
# 健康检查（秒回）：服务在线 / 模型 / 服务默认值摘要
python tools/image-edit/local_edit.py check [--json]

# 图生图编辑（免费，但占 GPU 数分钟）
python tools/image-edit/local_edit.py edit -i <输入图.png> -p "编辑描述" --mask <mask.png> --seed 42
```

服务地址优先级：`--host` > `.env` 的 `SD_SERVER_HOST`（已写入）> 硬编码缺省 `http://192.168.3.28:7863`。
服务没起时到 mini-local 上执行 `./run-qwen-i2i.sh start`（`status` / `logs` 同脚本）。

## edit 参数表

| 参数 | 默认 | 说明 |
|------|------|------|
| `-i/--image` | 必填 | 输入图（PNG 保留 alpha） |
| `-p/--prompt` | 必填 | 编辑描述；`--transparent` 自动追加官方 RGBA 透明底指令 |
| `--mask` | 无 | 重绘 mask，自动缩放到输入图尺寸（告警） |
| `--mask-polarity` | `marked` | `marked`=涂白/不透明=重绘；`hole`=透明(alpha=0)=重绘（zenmux 同款约定，自动翻转成 img2img 的"白=重绘"） |
| `--denoise` | 0.75 | `denoising_strength`：1.0=完全重绘，小=保原图 |
| `--cfg-scale` | **6.0** | 显式传对齐 CLI（服务默认 7.0，别用默认值） |
| `--steps` | 20 | |
| `--seed` | 42 | `-1`=随机；真实 seed 从响应 `info` 回读写进边车 |
| `--batch` | 1 | 1–8 |
| `--width/--height` | 输入图尺寸 | 四舍五入到 **32 倍数**（64–4096）；输入非 32 倍数会告警 |
| `--sampler/--scheduler` | euler / default | 服务端 21 samplers / 18 schedulers |
| `--ref-args/--no-ref-args` | `preset=qwen` | Qwen 编辑参考图编码（同 CliT 的 `-r`） |
| `--transparent` | 关 | prompt 末尾追加 RGBA 透明底指令（抠件场景） |
| `--enable-hr` | 关 | 高清修复（`hr_scale` 2.0 / Latent） |
| `--out/--out-dir` | `tmp/local-edit/<时间戳>/` | 产物路径；旁写同名 `.json` 边车（参数 + info + 耗时） |
| `--timeout` | 900 s | 1024² 实测 ~8.5 min，别设太小 |

## 为什么走 `/sdapi/v1/img2img` 而不是 `/v1/images/edits`

OpenAI 风格 multipart 路由**只**解析 `image/mask/prompt/n/size/output_format`，
`steps / cfg_scale / seed / sampler` **不可覆盖**（走服务默认 cfg=7.0）；
CLI 验证对齐口径是 **cfg=6.0**。`/sdapi/v1/img2img` 全参可调，且 mask / hires / ref_image_args 都在。

## 服务端隐性差异（对接口文档的实测备注）

1. **RNG 不是同一条序列**：CLI 跑 `--rng cpu`，服务端 `default`（cuda 系）——
   即使 seed/steps/cfg 全一致，**服务端与 CLI 出图也不同**，别拿 seed 做跨端复现。
2. **服务默认 cfg=7.0**：本工具显式传 6.0 规避。
3. **懒加载**：服务启动后 VRAM 只有 ~250MB，首个请求才把 DiT 装进 VRAM（峰值 ~9.6GB）
   —— 第一张图明显慢是正常的。
4. **VAE 在 CPU**：1024² 的 VAE decode ~117s 是大头。提速：mini-local 上
   `BACKEND="diffusion=cuda0,vae=cuda0,llm=cpu" ./run-qwen-i2i.sh restart`（1024² 会 OOM 自动 tiling）。

## 性能基线（RTX 4060 Ti 16G，单请求）

| 尺寸 | TE encode | DiT 采样/步 | VAE decode | 总耗时 |
|------|-----------|-------------|------------|--------|
| 1024² | ~160s | ~11.0s | ~117s | **~8.5 min** |
| 640×896 | ~74s | ~5.25s | ~2s | **~3 min** |

→ 编辑默认跟随输入图尺寸，素材件（小图）很快；整张 1024² 级别的大图要等。

## 硬规则 / 实测经验

1. **mask 不是硬边界**（与 zenmux 同理）：小范围局部改动建议出图后把 mask 外像素贴回原图
   （可用 `tools/sprite/image_parts_tool.py apply` 思路），或调低 `--denoise`。
2. **透明输出用 png**（唯一保留 alpha 的格式）+ `--transparent`；jpeg 会丢 alpha。
3. 想换风格但保构图：`--denoise 0.5~0.65`；换件 / 重画部件：`--denoise 0.85~1.0`。
4. 产物边车 `.json` 里有完整请求参数 + 服务端 info meta，复现/对账够用。
5. 服务返回 `400` = 缺 prompt/缺 image/尺寸非 32 倍数；`500` = 推理异常（OOM 等，看 mini-local 日志）。
6. **免费无计费风险**：失败可以直接改参数重跑，不需要 dry-run/核账那套 zenmux 纪律；
   但占 GPU —— 批量任务别并发轰炸，队列上限 64。
