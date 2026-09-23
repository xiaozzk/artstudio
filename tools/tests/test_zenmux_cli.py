#!/usr/bin/env python
"""ZenMux CLI 端到端测试：**先用 mock 服务端，再只验命令行行为**。

设计口径（2026-09-23 用户指示）：
* 真机测试是**要花钱**的（被掐断也计费），所以这里 **一行真机请求都不发**：
  所有 `--base-url` / `--vertex-url` 都指向本目录 `mock_zenmux.py` 起的 127.0.0.1 服务端；
  另加代理兜底（`HTTPS_PROXY=http://127.0.0.1:9` + `NO_PROXY=127.0.0.1`）——
  万一某条命令漏了 `--base-url`，请求会立刻失败，而不是悄悄打到 zenmux.ai 烧钱。
* 断言只看**命令层面**能看到的东西：退出码、stdout/stderr 关键词、落盘产物、`--dump-request` 的请求体。
  不再逐个断内部函数（那是上一版 92 条断言的写法，太贵太碎）。

跑法：

    python tools/tests/test_zenmux_cli.py            # 全部（约 30s，$0）
    python tools/tests/test_zenmux_cli.py -v         # 逐条列名
    python tools/tests/test_zenmux_cli.py -k vertex  # 只跑命中名字的
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "zenmux_edit.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_zenmux                                                    # noqa: E402

TEST_API_KEY = "sk-test-local-not-a-real-key"
RUN_DIR = ROOT / "tmp" / "zenmux-tests" / datetime.now().strftime("%Y%m%d-%H%M%S")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def cli_env() -> dict:
    """给子进程的环境：代理指向死端口当保险，免得漏配 URL 时真打 zenmux.ai。"""
    env = dict(os.environ)
    env["HTTP_PROXY"] = env["HTTPS_PROXY"] = env["http_proxy"] = env["https_proxy"] = "http://127.0.0.1:9"
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def first_json(blob: str):
    """`cost --json` 之后还会接着打摘要行，所以只取第一段 JSON。"""
    return json.JSONDecoder().raw_decode(blob[blob.index("{"):])[0]


def make_inputs(folder: Path) -> tuple:
    """造一对最小输入：64x64 RGBA 底图 + 中心 24x24 的 mask（有 alpha，marked=polarity 默认）。"""
    from PIL import Image, ImageDraw

    folder.mkdir(parents=True, exist_ok=True)
    base = folder / "base.png"
    mask = folder / "mask.png"
    Image.new("RGBA", (64, 64), (30, 120, 200, 255)).save(base)
    m = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(m).rectangle((20, 20, 43, 43), fill=(255, 255, 255, 255))
    m.save(mask)
    return base, mask


class ZenMuxCliTest(unittest.TestCase):
    """全部命令都在 mock 上跑；真机零请求。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = mock_zenmux.start("ok")
        cls.base = cls.srv.base_url
        cls.vertex = cls.srv.vertex_url
        cls.base_png, cls.mask_png = make_inputs(RUN_DIR / "_inputs")
        print(f"\n[测试] mock ZenMux：{cls.base}    产物目录：{RUN_DIR}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    # ---------------------------------------------------------------- 基础设施

    def common(self, cmd: str) -> list:
        return [cmd, "--api-key", TEST_API_KEY, "--base-url", self.base,
                "--vertex-url", self.vertex, "--timeout", "30"]

    def out(self, name: str) -> Path:
        return RUN_DIR / name

    def run_cli(self, args: list, expect: int = 0):
        cmd = [sys.executable, str(CLI)] + [str(a) for a in args]
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=cli_env(), timeout=180)
        blob = (p.stdout or "") + (p.stderr or "")
        if expect is not None:
            self.assertEqual(p.returncode, expect,
                             f"退出码 {p.returncode}≠{expect}\n命令：{' '.join(cmd)}\n输出：\n{blob}")
        return p, blob

    def assert_png(self, path: Path) -> None:
        self.assertTrue(path.exists(), f"缺产物：{path}")
        self.assertEqual(path.read_bytes()[:8], PNG_MAGIC, f"{path} 不是 PNG")

    # ---------------------------------------------------------------- 1. check

    def test_01_check_reports_catalog_and_balance(self):
        p, blob = self.run_cli(self.common("check"))
        self.assertIn("模型 4 个，其中可出图 3 个", blob)
        self.assertIn("余额 12.5 USD", blob)
        self.assertIn("[结论] 自检通过", blob)
        self.assertTrue(self.srv.gets("/models"), "mock 没收到 /models 请求")

    # ---------------------------------------------------------------- 2~3. balance

    def test_02_balance_text_and_json(self):
        _, blob = self.run_cli(self.common("balance"))
        self.assertIn("余额 12.5 USD", blob)
        self.assertIn("[来源 --api-key]", blob)

        _, blob = self.run_cli(self.common("balance") + ["--json"])
        self.assertEqual(first_json(blob)["total_credits"], 12.5)

    def test_03_balance_zero_exits_nonzero(self):
        srv = mock_zenmux.start("low")
        try:
            _, blob = self.run_cli(["balance", "--api-key", TEST_API_KEY, "--base-url", srv.base_url],
                                   expect=1)
            self.assertIn("余额 0.0 USD", blob)
            self.assertIn("余额 ≤ 0", blob)
        finally:
            srv.shutdown()
            srv.server_close()

    # ---------------------------------------------------------------- 4~5. cost / generation

    def test_04_cost_prints_summary_and_echoes_query(self):
        _, blob = self.run_cli(self.common("cost") + ["--dimension", "BIZ_DT", "--time", "20260923",
                                                      "--models", "openai/gpt-image-2"])
        self.assertIn("账单 BIZ_DT=20260923", blob)
        self.assertIn("合计 $0.18   请求 2 次", blob)
        self.assertIn("image_output", blob)

        _, blob = self.run_cli(self.common("cost") + ["--dimension", "BIZ_DT", "--time", "20260923",
                                                      "--models", "openai/gpt-image-2", "--json"])
        q = first_json(blob)["query"]
        self.assertEqual((q["dimension"], q["time"], q["models"]), ("BIZ_DT", "20260923", "openai/gpt-image-2"))

    def test_05_generation_detail(self):
        _, blob = self.run_cli(self.common("generation") + ["--id", "2534CCEDTKJR00217635"])
        self.assertEqual(first_json(blob)["generationId"], "2534CCEDTKJR00217635")

    # ---------------------------------------------------------------- 6. dry-run 不打 API

    def test_06_edit_dry_run_calls_nothing(self):
        before_posts = len(self.srv.posts())
        _, blob = self.run_cli(self.common("edit") + ["-i", self.base_png, "-p", "换一把发光短杖",
                                                      "--out-dir", self.out("dry-run"), "--dry-run"])
        self.assertIn("[dry-run] 没有调用 API", blob)
        self.assertEqual(len(self.srv.posts()), before_posts, "dry-run 竟然发了 POST")

    # ---------------------------------------------------------------- 7~9. openai 协议三种形态

    def test_07_edit_openai_json_writes_artifacts(self):
        out = self.out("openai-json")
        _, blob = self.run_cli(self.common("edit") + [
            "-i", self.base_png, "-m", self.mask_png, "-p", "把武器换成发光短杖",
            "--protocol", "openai", "--no-stream", "--out-dir", out, "--name", "mvp", "--dump-request"])
        self.assertIn("协议=OpenAI Images", blob)
        self.assertIn("── 完成", blob)
        self.assertIn("共 1 个产物", blob)
        self.assert_png(out / "mvp.png")
        self.assertTrue((out / "run-summary.json").exists())
        dump = json.loads((out / "request.json").read_text(encoding="utf-8"))
        self.assertTrue(dump["images"][0]["image_url"].startswith("<data:image/png;base64"))
        self.assertIn("image_url", dump["mask"])

    def test_08_edit_openai_multipart(self):
        out = self.out("openai-multipart")
        _, blob = self.run_cli(self.common("edit") + [
            "-i", self.base_png, "-p", "换一把发光短杖", "--protocol", "openai",
            "--transport", "multipart", "--no-stream", "--out-dir", out, "--name", "mp"])
        self.assertIn("── 完成", blob)
        self.assert_png(out / "mp.png")
        sent = self.srv.posts("/images/edits")[-1]
        self.assertIn("multipart/form-data", sent["content_type"])
        self.assertGreaterEqual(sent.get("images", 0), 1)

    def test_09_edit_openai_sse_stream(self):
        out = self.out("openai-sse")
        _, blob = self.run_cli(self.common("edit") + [
            "-i", self.base_png, "-p", "换一把发光短杖", "--protocol", "openai",
            "--stream", "--partials", "1", "--out-dir", out, "--name", "sse"])
        self.assertIn("partial #0", blob)          # SSE 中间事件解析出来了
        self.assertIn("── 完成", blob)
        self.assert_png(out / "sse.png")
        self.assertFalse((out / "_partials").exists(), "没开 --save-partials 不该落中间图")
        self.assertTrue(self.srv.posts("/images/edits")[-1]["body"]["stream"])

    # ---------------------------------------------------------------- 10~11. vertex 协议

    def test_10_edit_vertex_predict_default(self):
        out = self.out("vertex-openai")
        _, blob = self.run_cli(self.common("edit") + [
            "-i", self.base_png, "-m", self.mask_png, "-p", "把护目镜换成红色",
            "--out-dir", out, "--name", "vx"])
        self.assertIn("协议=Vertex AI", blob)
        self.assertIn(":predict", blob)
        self.assert_png(out / "vx.png")
        sent = self.srv.posts(":predict")[-1]
        self.assertIn("/v1/publishers/openai/models/gpt-image-2:predict", sent["path"])
        refs = sent["body"]["instances"][0]["referenceImages"]
        self.assertEqual([r["referenceType"] for r in refs],
                         ["REFERENCE_TYPE_RAW", "REFERENCE_TYPE_MASK"])
        self.assertEqual(refs[1]["maskImageConfig"]["maskMode"], "MASK_MODE_USER_PROVIDED")
        self.assertEqual(sent["body"]["imageSize"], "1024x1024")     # openai 家族：顶层透传
        self.assertEqual(sent["body"]["quality"], "low")

    def test_11_edit_vertex_tencent_downloads_gcs_uri(self):
        out = self.out("vertex-tencent")
        _, blob = self.run_cli(self.common("edit") + [
            "-i", self.base_png, "-p", "国风水墨，背景纯白", "--model", "tencent/hy-image-v3.0",
            "--out-dir", out, "--name", "hy"])
        self.assertIn("── 完成", blob)
        self.assert_png(out / "hy.png")            # 走的是 gcsUri 下载分支
        self.assertIn("/v1/publishers/tencent/models/hy-image-v3.0:predict",
                      self.srv.posts(":predict")[-1]["path"])

    # ---------------------------------------------------------------- 12. 本地拦截（花钱前）

    def test_12_local_rejections_never_touch_api(self):
        before = len(self.srv.posts())
        cases = {
            "--n 越界": ["-i", self.base_png, "-p", "x", "--n", "11"],
            "透明底配 jpeg": ["-i", self.base_png, "-p", "x", "--protocol", "openai",
                              "--background", "transparent", "--output-format", "jpeg"],
            "缺 prompt": ["-i", self.base_png],
            "hy 单次只能 1 张": ["-i", self.base_png, "-p", "x", "--model", "tencent/hy-image-v3.0", "--n", "2"],
            "aspect-ratio 形式错": ["-i", self.base_png, "-p", "x", "--aspect-ratio", "1024x1024"],
        }
        for label, extra in cases.items():
            with self.subTest(case=label):
                _, blob = self.run_cli(self.common("edit") + extra, expect=2)
                self.assertIn("[fail]", blob)
        with self.subTest(case="未知子命令"):
            _, blob = self.run_cli(["foo"], expect=2)
            self.assertIn("未知子命令", blob)
        self.assertEqual(len(self.srv.posts()), before, "本地校验失败的命令竟然打了 API")

    # ---------------------------------------------------------------- 13. 服务端错误

    def test_13_api_error_surfaces_auth_hint(self):
        srv = mock_zenmux.start("deny")
        try:
            _, blob = self.run_cli(["edit", "--api-key", TEST_API_KEY, "--base-url", srv.base_url,
                                    "--vertex-url", srv.vertex_url, "-i", self.base_png, "-p", "x",
                                    "--out-dir", self.out("deny")], expect=2)
            self.assertIn("HTTP 403", blob)
            self.assertIn("access_denied", blob)
        finally:
            srv.shutdown()
            srv.server_close()


    # ---------------------------------------------------------------- 14. 纯色底（默认行为）

    def test_14_solid_bg_default_injects_and_can_be_disabled(self):
        """2026-09-23 起：背景一律纯色 —— 默认把"纯色底"指令注入 prompt，可关/可跳过。"""
        # ① 默认（无 mask）：注入
        out = self.out("solid-default")
        _, blob = self.run_cli(self.common("edit") + [
            "-i", self.base_png, "-p", "把护目镜换成红色",
            "--out-dir", out, "--name", "solid"])
        self.assertIn("--solid-bg 已注入纯色底指令", blob)
        prompt = self.srv.posts(":predict")[-1]["body"]["instances"][0]["prompt"]
        self.assertIn("#FF00FF", prompt)
        self.assertIn("flat uniform solid", prompt)

        # ② --no-solid-bg：不注入
        _, blob_off = self.run_cli(self.common("edit") + [
            "-i", self.base_png, "-p", "把护目镜换成红色", "--no-solid-bg",
            "--out-dir", self.out("solid-off"), "--name", "off"])
        self.assertNotIn("已注入纯色底指令", blob_off)
        self.assertEqual(self.srv.posts(":predict")[-1]["body"]["instances"][0]["prompt"].strip(),
                         "把护目镜换成红色")

        # ③ 带 mask 的原位编辑：不注入（要保留原背景）
        self.run_cli(self.common("edit") + [
            "-i", self.base_png, "-m", self.mask_png, "-p", "把护目镜换成红色",
            "--out-dir", self.out("solid-masked"), "--name", "masked"])
        self.assertEqual(self.srv.posts(":predict")[-1]["body"]["instances"][0]["prompt"].strip(),
                         "把护目镜换成红色")


if __name__ == "__main__":
    unittest.main(verbosity=2)
