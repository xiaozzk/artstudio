// 在已连接的 CDP 页面上下文里执行 JS，返回结果。
//
// 用法:
//   node cdp-eval.mjs <port> "<expression>"
//   node cdp-eval.mjs <port> @path/to/script.js      # 从文件读，避免命令行转义地狱
//   node cdp-eval.mjs <port> @script.js --url mixamo # 按 URL 子串挑标签页
//
// 约定:
//   * 表达式会被当作 async 函数体执行，可用 await。
//   * 想要返回值就 `return <value>`。
//   * 只在目标页面的 origin 上下文跑，因此 fetch 自动带 same-origin 凭据。
//
// 这是「借登录态」流程的操作端：先 borrow-login.ps1 起好副本，
// 再用本脚本在已登录页面里调站点自己的 API。

import { readFileSync } from "node:fs";

const port = process.argv[2] || "9222";
let source = process.argv[3];
const urlFilter = (() => {
  const i = process.argv.indexOf("--url");
  return i > -1 ? process.argv[i + 1] : null;
})();

if (!source) {
  console.error("usage: node cdp-eval.mjs <port> <expression|@file> [--url substr]");
  process.exit(2);
}
if (source.startsWith("@")) source = readFileSync(source.slice(1), "utf8");

const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const pages = targets.filter((t) => t.type === "page");
const page = (urlFilter ? pages.find((t) => t.url.includes(urlFilter)) : null) || pages[0];
if (!page) { console.error("no page target on port " + port); process.exit(1); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
await new Promise((r) => ws.addEventListener("open", r));
function send(method, params = {}) {
  const id = ++seq;
  return new Promise((res) => { pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
}

const wrapped = `(async () => { ${source} })()`;
const r = await send("Runtime.evaluate", {
  expression: wrapped,
  returnByValue: true,
  awaitPromise: true,
});

if (r.result?.exceptionDetails) {
  console.error("JS exception:", JSON.stringify(r.result.exceptionDetails).slice(0, 1200));
  ws.close();
  process.exit(1);
}
const val = r.result?.result?.value;
console.log(typeof val === "string" ? val : JSON.stringify(val, null, 2));
ws.close();
