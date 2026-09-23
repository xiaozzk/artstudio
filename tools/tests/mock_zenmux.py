#!/usr/bin/env python
"""ZenMux 模拟服务端 —— 只给 CLI 级测试用：不打真机、不花额度。

测试里这样用（同目录的 `test_zenmux_cli.py`）：

    import mock_zenmux
    srv = mock_zenmux.start("ok")          # 场景 ok / deny / low
    srv.base_url                            # http://127.0.0.1:PORT/api/v1        （OpenAI 协议 + 平台接口）
    srv.vertex_url                          # http://127.0.0.1:PORT/api/vertex-ai  （Vertex :predict）
    srv.requests                            # 收到的请求记录（list[dict]）
    srv.shutdown()

也可以单独起一个手工 curl：

    python tools/tests/mock_zenmux.py --port 8765 --scenario ok

覆盖的端点：
    GET  /api/v1/models                              模型目录（check）
    GET  /api/v1/management/payg/balance             余额（balance / check / --min-credits）
    GET  /api/v1/management/cost                     账单（cost）
    GET  /api/v1/management/generation               单次调用明细（generation）
    POST /api/v1/images/edits                        OpenAI 协议（JSON / multipart / SSE 三种形态）
    POST /api/vertex-ai/v1/publishers/{p}/models/{m}:predict   Vertex 协议（openai 系回 b64，腾讯系回 gcsUri）
    GET  /files/out.png                              给 gcsUri 分支下载用的小图

只用标准库：不 import PIL / requests，测试以外零依赖。
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

# --------------------------------------------------------------------------- 假数据

CATALOG = [
    {"id": "openai/gpt-image-2", "output_modalities": ["image"]},
    {"id": "openai/gpt-image-2.5-flare", "output_modalities": ["image"]},
    {"id": "tencent/hy-image-v3.0", "output_modalities": ["image"]},
    {"id": "deepseek/deepseek-chat", "output_modalities": ["text"]},
]

BALANCE = {"currency": "usd", "total_credits": 12.5, "top_up_credits": 10.0, "bonus_credits": 2.5}
BALANCE_LOW = {"currency": "usd", "total_credits": 0.0, "top_up_credits": 0.0, "bonus_credits": 0.0}

COST = {
    "summary": {"totalCost": 0.18, "requestCounts": 2, "requestAvgCost": 0.09,
                "inputCost": 0.01, "outputCost": 0.17, "otherCost": 0.0, "totalTokens": 6800},
    "analysis": {
        "costByModel": [{"bizTime": "20260923", "modelSlug": "openai/gpt-image-2",
                         "billAmount": 0.18, "requestCounts": 2}],
        "costByTokenType": [{"tokenType": "image_output", "billAmount": 0.17}],
    },
}

USAGE = {"total_tokens": 6800, "input_tokens": 1200, "output_tokens": 5600}


def png_bytes(w: int = 64, h: int = 64, rgb=(200, 80, 40)) -> bytes:
    """最小 PNG 编码器（纯色 RGB），免得 mock 依赖枕头。"""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def short_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def strip_b64(obj):
    """请求/响应记录里把 base64 折成占位符，日志才看得清。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("data:") and "base64," in v:
                out[k] = f"<data-url {len(v)} chars>"
            elif isinstance(v, str) and len(v) > 200:
                out[k] = f"<{len(v)} chars>"
            else:
                out[k] = strip_b64(v)
        return out
    if isinstance(obj, list):
        return [strip_b64(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- 服务端


class MockServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, scenario: str = "ok", host: str = "127.0.0.1", port: int = 0):
        self.scenario = scenario          # ok / deny（403）/ low（余额 0）
        self.requests: list = []
        self._lock = threading.Lock()
        super().__init__((host, port), MockHandler)

    # --- 地址
    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    @property
    def base_url(self) -> str:
        return self.origin + "/api/v1"

    @property
    def vertex_url(self) -> str:
        return self.origin + "/api/vertex-ai"

    # --- 请求台账（测试断言用：也能证明"这一步没调 API"）
    def record(self, entry: dict) -> None:
        with self._lock:
            self.requests.append(entry)

    def posts(self, suffix: str = "") -> list:
        with self._lock:
            return [r for r in self.requests if r.get("method") == "POST" and r.get("path", "").endswith(suffix)]

    def gets(self, suffix: str = "") -> list:
        with self._lock:
            return [r for r in self.requests if r.get("method") == "GET" and r.get("path", "").endswith(suffix)]


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MockZenMux/0.1"

    def log_message(self, *args) -> None:      # 别把每个请求刷到测试输出里
        pass

    # --- 工具
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-request-id", "mock-0000-0000")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _error(self, code: int, etype: str, message: str) -> None:
        self._json(code, {"error": {"code": etype, "type": etype, "message": message}})

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _scenario_error(self) -> bool:
        if self.server.scenario == "deny":
            self._error(403, "access_denied", "Invalid API key (api_key_source: payg)")
            return True
        return False

    def _authorized(self) -> bool:
        if self.headers.get("Authorization"):
            return True
        self._error(403, "access_denied", "缺少 Authorization 头")
        return False

    # --- GET
    def do_GET(self) -> None:                                   # noqa: N802
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.server.record({"method": "GET", "path": u.path, "query": q})
        if u.path.endswith("/files/out.png"):          # gcsUri 下载分支：公开小图，不要鉴权
            return self._send(200, png_bytes(64, 64, (200, 80, 40)), "image/png")
        if u.path.endswith("/models"):                 # 和真机一致：模型目录是公开接口，不带 key
            return self._json(200, {"data": CATALOG})
        if self._scenario_error() or not self._authorized():
            return
        if u.path.endswith("/management/payg/balance"):
            data = BALANCE_LOW if self.server.scenario == "low" else BALANCE
            return self._json(200, {"success": True, "data": data})
        if u.path.endswith("/management/cost"):
            data = dict(COST)
            data["query"] = {"dimension": q.get("query_dimension", ""), "time": q.get("query_time", ""),
                             "models": q.get("model_slugs", "")}
            return self._json(200, {"success": True, "data": data})
        if u.path.endswith("/management/generation"):
            return self._json(200, {"success": True, "data": {
                "generationId": q.get("id", ""), "modelSlug": "openai/gpt-image-2",
                "totalCost": 0.18, "totalTokens": 6800}})
        return self._error(404, "not_found", f"mock 没有这条路：{u.path}")

    # --- POST
    def do_POST(self) -> None:                                  # noqa: N802
        u = urlsplit(self.path)
        raw = self._body()
        ctype = (self.headers.get("Content-Type") or "").lower()
        entry = {"method": "POST", "path": u.path, "content_type": ctype}
        if "application/json" in ctype and raw:
            try:
                entry["body"] = strip_b64(json.loads(raw.decode("utf-8")))
            except ValueError:
                entry["body"] = "<不是 JSON>"
        if self._scenario_error() or not self._authorized():
            self.server.record(entry)
            return

        m = re.fullmatch(r".*/v1/publishers/([^/]+)/models/(.+):predict", u.path)
        if m:
            self.server.record(entry)
            return self._predict(m.group(1), m.group(2), entry.get("body") or {})
        if u.path.endswith("/images/edits"):
            if "multipart/form-data" in ctype:
                # 只数一下图片字段，够断言"走的是 multipart 通道"就行
                entry["images"] = len(re.findall(rb'name="image', raw))
                entry["fields"] = {k.decode(): v.decode("utf-8", "replace")
                                   for k, v in re.findall(rb'name="([^"]+)"\r\n\r\n([^\r]*)\r\n', raw)}
            self.server.record(entry)
            return self._images_edits(entry.get("body") or {}, stream=bool(entry.get("body", {}).get("stream")))
        self.server.record(entry)
        return self._error(404, "not_found", f"mock 没有这条路：{u.path}")

    # --- 两个协议各自的响应形状
    def _predict(self, provider: str, model: str, body: dict) -> None:
        if not body.get("instances"):
            return self._error(400, "invalid_request", "instances 为空")
        img = png_bytes(64, 64, (40, 160, 220))
        if provider == "tencent":                       # 腾讯系实测回 COS 签名 URL（gcsUri）
            preds = [{"gcsUri": f"{self.server.origin}/files/out.png"}]
        else:                                           # Google/OpenAI 系回内嵌字节
            preds = [{"bytesBase64Encoded": short_b64(img)}
                     for _ in range(int((body.get("parameters") or {}).get("sampleCount") or 1))]
        self._json(200, {"predictions": preds, "usageMetadata": USAGE})

    def _images_edits(self, body: dict, stream: bool) -> None:
        img = png_bytes(64, 64, (40, 160, 220))
        if stream:
            events = [": ZENMUX PROCESSING", "",
                      "event: image_edit.partial_image",
                      "data: " + json.dumps({"type": "image_edit.partial_image", "partial_image_index": 0,
                                             "size": "1024x1024", "quality": "low",
                                             "b64_json": short_b64(img)}, ensure_ascii=False), "",
                      "event: image_edit.completed",
                      "data: " + json.dumps({"type": "image_edit.completed", "b64_json": short_b64(img),
                                             "created_at": 1758600000, "size": "1024x1024",
                                             "quality": "low", "background": "opaque",
                                             "usage": USAGE}, ensure_ascii=False), ""]
            return self._send(200, ("\n".join(events) + "\n").encode("utf-8"), "text/event-stream")
        data = [{"b64_json": short_b64(img)} for _ in range(int(body.get("n") or 1))]
        self._json(200, {"created": 1758600000, "data": data, "size": "1024x1024",
                         "quality": body.get("quality"), "background": body.get("background"),
                         "output_format": body.get("output_format"), "usage": USAGE})


def start(scenario: str = "ok", host: str = "127.0.0.1", port: int = 0) -> MockServer:
    """起一个后台线程的 mock 服务端，返回已就绪的 MockServer。"""
    srv = MockServer(scenario, host, port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser(description="ZenMux mock 服务端（测试用；手工调试时也能起）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--scenario", choices=("ok", "deny", "low"), default="ok")
    args = ap.parse_args()
    srv = start(args.scenario, port=args.port)
    print(f"mock ZenMux 已起：{srv.base_url}  /  {srv.vertex_url}   场景={args.scenario}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
