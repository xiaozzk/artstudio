# tools/zenmux 改名 image-edit（图片编辑）+ 新增本地 sd-server 图片编辑工具

| 项 | 值 |
|----|-----|
| 编号 | 004 |
| 目录 | `task/004-image-edit-local/` |
| 状态 | 已完成 <!-- 规划中 / 进行中 / 已完成 / 已放弃 --> |
| 创建 | 2026-09-28 |
| 更新 | 2026-09-28 |

## 目标

图片编辑不再 = ZenMux（花钱）一家：`tools/zenmux/` 改名 `tools/image-edit/`（场景 = 图片编辑），
并新增一个对接 mini-local 上 sd-server（stable-diffusion.cpp 引擎 / Qwen-Image-2.1）HTTP 服务的本地工具
`local_edit.py` —— 局域网内、**不消耗任何 API 额度**的图生图 / mask 局部编辑，
作为 ZenMux 免费替代 / 免费预演的第一站。

## 验收标准

- [x] `tools/image-edit/` 就位，`tools/zenmux/` 不复存在；shim `tools/zenmux_edit.py` 转发新路径
- [x] 新工具 `python tools/image-edit/local_edit.py check` 能对 mini-local 服务做健康检查
- [x] 新工具 `edit` 支持 mask 局部重绘（白=重绘，`--mask-polarity` 可反）、尺寸对齐 32 倍数、seed/sampler/cfg 可调
- [x] zenmux mock 测试 14 条全绿（改名零破坏，6.2s，$0）
- [x] 真机冒烟：`check` 通过 + `ear.png` 59×90 → 64×96 一张 4.5s 出图成功（尖精灵耳、透明底，产物 `tmp/local-edit-smoke/ear_elf.png`）
- [x] 全仓文档路径引用已更新（AGENTS / tools/README / docs/zenmux-cli / zenmux-edit.md / spine-reskin / tests）

## 产出

| 路径 | 说明 |
|------|------|
| `tools/image-edit/local_edit.py` | 本地图片编辑工具（对接 mini-local sd-server） |
| `tools/image-edit/local-edit.md` | 工具口径文档 |
| `tools/image-edit/`（整目录） | 原 `tools/zenmux/` 改名而来，内容不变 |

## 步骤

1. 读远程 `mini-local:~/Desktop/project/llm/docs/sd-server-qwen-i2i-api.md`，确定路由与参数
2. `git mv tools/zenmux tools/image-edit`；更新根 shim
3. 写 `local_edit.py`（走 `/sdapi/v1/img2img`，参数最全；`/v1/models` 做健康检查）
4. 写文档 + 全仓路径引用更新 + mock 测试回归
5. 真机冒烟

## 决策与笔记

- 2026-09-28：选 `/sdapi/v1/img2img` 而非 `/v1/images/edits` —— 文档明确 OpenAI 路由**不可覆盖**
  `steps/cfg_scale/seed/sampler`（走服务默认 cfg=7.0），而 CLI 验证口径是 cfg=6.0；img2img 全参可调。
- 2026-09-28：服务默认值与隐性差异（RNG 序列与 CLI 不同、cfg 默认 7.0）记入工具文档；
  VAE 在 CPU，1024² 单张 ~8.5 min，默认尺寸跟随输入图（32 倍数对齐）避免无谓放大。
- 2026-09-28 真机冒烟：服务在线（懒加载后首请求装配 DiT）；59×90 小图 4.5s 出图，
  语义正确（尖精灵耳 + 透明底）。小图会把边长警告性取整到 32 倍数（64×96），
  实际素材件多为小图、很快；整张 1024² 级别才需要 --timeout 加大（默认 900s 已留余量）。
- 2026-09-28 **服务端架构变更跟进**（同日晚些）：服务改为 **Python（FastAPI + 单 worker）+ 异步非阻塞
  提交-轮询**（`202 {id, poll_url}` → `GET /jobs/{id}`，无长连接；C++ 层 `/sdcpp/v1/*` 下线）。
  `local_edit.py` 重写为提交-轮询：状态机 queued/generating/completed/failed 全程打印、
  429 队列满 / 404 TTL 过期 / failed(stderr 尾 8 行) 分别给出处置提示。
  Python 层不再收 ref_image_args / scheduler / clip_skip，字段改 `sample_method`；
  **RNG 强制 cpu 与 CLI 同序列**（旧版服务/CLI 不同序列的坑消失，seed 可复现），cfg 默认已对齐 6.0。
  回归冒烟：hair.png 344×432 → 352×448，1m05s 出图正确（波浪长发），边车 json 记 job 时间戳与服务端留档路径。
