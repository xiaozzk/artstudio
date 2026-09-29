# local_edit.py — 本地图片编辑（mini-local sd-server / Qwen-Image-2.1，提交-轮询）

对接 mini-local（192.168.3.28）上 **Python 重写的 sd-server**（FastAPI + 单 worker，
`infer-engine/sd-server/server.py`，推理引擎是 stable-diffusion.cpp 的 `sd-cli` 每任务 spawn）。
**纯局域网、不消耗任何 API 额度、无计费风险** —— 图片编辑场景的免费入口；
要更快 / 多 mask / 更强的语义理解再考虑同目录的 `zenmux_edit.py`
（花 ZenMux 额度，见 [`zenmux-edit.md`](zenmux-edit.md)）。

> **2026-09-28 服务端架构变更**：C++ `sd-server` → Python（FastAPI + 单 worker），
> 所有生成路由改为**异步非阻塞、提交-轮询**（`202 {id, poll_url}` → `GET /jobs/{id}`），
> 不再有长连接；`/sdcpp/v1/*` 原生路由已下线。服务端接口文档在 mini-local 上：
> `~/Desktop/project/llm/docs/sd-server-qwen-i2i-api.md`。

## 命令

**一律在工作区根下执行**（工具从根目录 `.env` 读 `SD_SERVER_HOST`）。

```powershell
# 健康检查（秒回）：服务在线 / 模型 / 队列状态
python tools/image-edit/local_edit.py check [--json]

# 图生图编辑（免费，但占 GPU 数分钟；提交后工具自动轮询到出图）
python tools/image-edit/local_edit.py edit -i <输入图.png> -p "编辑描述" --mask <mask.png> --seed 42
```

服务地址优先级：`--host` > `.env` 的 `SD_SERVER_HOST`（已写入）> 硬编码缺省 `http://192.168.3.28:7863`。
服务没起时到 mini-local 上执行 `./run-qwen-i2i.sh start`（`status` / `logs` 同脚本）。

## 提交-轮询协议（本工具已封装，了解状态机便于排错）

```
POST /sdapi/v1/img2img  →  202 {"id": "...", "status": "queued", "poll_url": "/jobs/..."}
GET  /jobs/{id}         →  queued（含 queue_position）→ generating → completed / failed
DELETE /jobs/{id}       →  取消（仅 queued 可；generating 中 409）
```

- 状态机：`queued ─▶ generating ─▶ completed / failed`；`failed` 的 `error` 带 sd-cli stderr 尾 8 行
- 队列上限 **10**（第 11 个提交 `429`，`SD_SERVER_MAX_PENDING_JOBS` 可调）；**单 worker 串行**
- 结果保留 **10 分钟 TTL**（404 = 过期），每次新提交前自动清理过期任务
- 轮询间隔默认 5s（文档建议 5-10s）；`--timeout` 默认 1200s 覆盖提交+排队+生成全程

## edit 参数表

| 参数 | 默认 | 说明 |
|------|------|------|
| `-i/--image` | 必填 | 输入图（PNG 保留 alpha） |
| `-p/--prompt` | 必填 | 编辑描述；`--transparent` 自动追加官方 RGBA 透明底指令 |
| `--mask` | 无 | 重绘 mask，自动缩放到输入图尺寸（告警）。⚠ **Python 服务上未实测**（文档原话），首次用先小图验证 |
| `--mask-polarity` | `marked` | `marked`=涂白/不透明=重绘；`hole`=透明(alpha=0)=重绘（zenmux 同款约定，自动翻转成"白=重绘"） |
| `--denoise` | 0.75 | `denoising_strength`：1.0=完全重绘，小=保原图（A1111 兼容字段，文档未单列） |
| `--cfg-scale` | 6.0 | 服务默认已与 CLI 对齐（6.0） |
| `--steps` | 20 | |
| `--seed` | 42 | `-1`=随机（服务不回传实际 seed）。**RNG 强制 cpu，与 CLI 同一序列**，seed/cfg 相同即可复现 |
| `--width/--height` | 输入图尺寸 | 四舍五入到 **32 倍数**（64–4096）；输入非 32 倍数会告警 |
| `--sampler` | euler | 服务字段 `sample_method` |
| `--transparent` | 关 | prompt 末尾追加 RGBA 透明底指令（抠件场景） |
| `--out/--out-dir` | `tmp/local-edit/<时间戳>/` | 产物路径；旁写同名 `.json` 边车（参数 + job 时间戳 + 耗时 + 服务端留档路径） |
| `--timeout` | 1200 s | 提交+轮询总时长上限；1024² 实测 ~8.5 min，别设太小 |
| `--poll-interval` | 5 s | 轮询间隔 |

> Python 层**不再收** `ref_image_args` / `scheduler` / `clip_skip`（旧 C++ 服务的字段已下线）；
> 输出格式固定 **png**（jpeg/webp 转换留待后续）。

## 服务端默认值（Python 层，2026-09-28 文档口径）

| 参数 | 默认 | 说明 |
|------|------|------|
| `steps` | 20 | |
| `cfg_scale` | **6.0** | 已与 CLI 验证对齐（不再有旧版"服务 7.0 vs CLI 6.0"的坑） |
| `sample_method` | euler | Qwen-Image 系适用 |
| `size` | 1024x1024 | 服务端裁剪到 32 的倍数 |
| RNG | **强制 cpu**（CLI 层写死） | **CLI 与服务同一 RNG 序列**，seed/cfg 相同可复现（旧版不能） |

## 性能基线（RTX 4060 Ti 16G，实测）

| 尺寸 | cond | sample/步 | CPU VAE | 总时长 |
|------|------|-----------|---------|--------|
| 1024² | ~160s | ~11s | ~117s | **~8.5 min** |
| 640×896 | ~74s | ~5.2s | ~25s | **~3.5 min** |
| 512² | ~36s | ~2s | ~25s | **~100s** |

→ 编辑默认跟随输入图尺寸，素材件（小图）很快；整张 1024² 级别的大图要等。
DiT 懒加载：首个任务装进 GPU（峰值 ~9.6GB），任务结束自动回收。
VAE 提速：mini-local 上 `SD_BACKEND="diffusion=cuda0,vae=cuda0,llm=cpu" ./run-qwen-i2i.sh restart`。

## 硬规则 / 实测经验

1. **mask 不是硬边界**（与 zenmux 同理）：小范围局部改动建议出图后把 mask 外像素贴回原图
   （`tools/sprite/image_parts_tool.py apply` 思路），或调低 `--denoise`。
2. **透明输出用 png** + `--transparent`；模型对抠件指令服从度随机（seed 决定），
   必要时在 prompt 里强调 "solid black for the background"，成品做阈值清理兜底。
3. 想换风格但保构图：`--denoise 0.5~0.65`；换件 / 重画部件：`--denoise 0.85~1.0`。
4. **免费无计费风险**：失败直接改参数重跑；但单 worker 串行 + 队列上限 10 —— 批量别并发轰炸。
5. 排错速查：`400` 尺寸非法/缺 prompt/图片识别失败；`429` 队列满；`409` 取消 generating 中任务；
   `404` 任务不存在或 TTL 过期；`500` sd-cli 非零退出（error 带 stderr 尾 8 行，完整日志 `./run-qwen-i2i.sh logs`）。
