# tools/zenmux/tests/ — ZenMux CLI 的 mock 级测试

**口径（2026-09-23 用户指示）：先 mock，再只验 CLI 命令。**
真机测试**是要花钱的**（实测被网关掐断的请求照常计费），所以这里一条真机请求都不发。

```powershell
# 在工作区根执行
python tools/zenmux/tests/test_zenmux_cli.py            # 全部 14 条，约 6 秒，花费 $0
python tools/zenmux/tests/test_zenmux_cli.py -v         # 逐条列名
python tools/zenmux/tests/test_zenmux_cli.py -k vertex  # 只跑命中名字的
```

## 两个文件

| 文件 | 作用 |
|------|------|
| `mock_zenmux.py` | 假 ZenMux 服务端（**纯标准库**，不依赖 PIL / requests）。可被测试 import，也能手工起：`python tools/zenmux/tests/mock_zenmux.py --port 8765 --scenario ok`（场景 `ok` / `deny`=403 / `low`=余额 0） |
| `test_zenmux_cli.py` | 14 条 CLI 级用例：起 mock → 用 `subprocess` 跑 `tools/zenmux/zenmux_edit.py` → 断言退出码 / 输出关键词 / 落盘产物 |

## 怎么保证"零真机、零费用"

1. 每条命令都显式带 `--base-url http://127.0.0.1:PORT/api/v1` 与 `--vertex-url http://127.0.0.1:PORT/api/vertex-ai`；
2. **代理兜底**：测试进程给子进程设 `HTTPS_PROXY=http://127.0.0.1:9`（死端口）+ `NO_PROXY=127.0.0.1`。
   万一哪天漏配了 URL，请求会立刻连接失败（`ProxyError`），而不是悄悄打到 `zenmux.ai` 烧钱；
3. `.env` 里就算放着真 key 也没关系 —— 测试一律用 `--api-key sk-test-local-not-a-real-key`，
   而且所有出口都在 127.0.0.1。

## 覆盖清单（14 条）

| 用例 | 验证的命令层行为 |
|------|------------------|
| 01 | `check`：模型目录 4 个 / 可出图 3 个、余额行、`[结论] 自检通过` |
| 02 | `balance` 文本 + `--json` |
| 03 | 余额为 0 → 退出码 1 + `余额 ≤ 0` 告警 |
| 04 | `cost`：摘要数字 + `--json` 里回显 `query_dimension/query_time/model_slugs` |
| 05 | `generation --id`：JSON 明细 |
| 06 | `edit --dry-run`：打印 `[dry-run]` 且 mock **一个 POST 都没收到** |
| 07 | `edit --protocol openai --no-stream`：出图 + `run-summary.json`，`--dump-request` 的 `request.json` 形状（`images[].image_url` 是 data URL、带 `mask`） |
| 08 | `--transport multipart`：mock 收到 `multipart/form-data` 且含图片字段 |
| 09 | `--stream --partials 1`：SSE 中间事件 + `completed` 解析出图；没开 `--save-partials` 不落 `_partials/` |
| 10 | 默认 vertex `:predict`：`REFERENCE_TYPE_RAW + REFERENCE_TYPE_MASK(MASK_MODE_USER_PROVIDED)`、openai 家族顶层 `imageSize`/`quality` |
| 11 | vertex 响应是 `gcsUri`（签名 URL）时能下载落盘 —— 用**合成 provider** `mock/gcs-image` 覆盖该分支 |
| 12 | 本地拦截（花钱前）：`--n` 越界、透明底配 jpeg、缺 prompt、`--aspect-ratio` 形式错、未知子命令 → 退出码 2，且**没打 API** |
| 13 | 服务端 403 `access_denied` → 退出码 2 + 鉴权提示 |
| 14 | `--solid-bg` 默认行为：默认把纯色底指令注入 prompt（`#FF00FF`）、`--no-solid-bg` 不注入、带 `--mask` 的原位编辑不注入 |

## 边界（别在这里做的事）

- **不要往这里加"真机用例"**。要真机验证就人工跑：先 `--dry-run`，再 `--min-credits 1` 小额试一张，
  跑完用 `cost` 核账（口径见 [`../zenmux-edit.md`](../zenmux-edit.md)）。
- 断言只写**命令能观察到**的东西（退出码 / stdout / 产物 / `--dump-request`），别去断内部函数 ——
  上一版 92 条内部断言太碎，已按用户指示废弃。
- 测试产物落在 `tmp/zenmux-tests/<时间戳>/`（可再生、不入库），没开自动清理。
