#!/usr/bin/env node
/**
 * 让项目的**配套资产**跟上项目本身：锚点库 + 导出交付物。
 *
 *   node tools/lab-sync-project.mjs [--project human_female] [--check]
 *
 * 项目在实验室里被编辑过（改画布、重排部位、开关裁剪、换贴图）之后，这两样东西就会过期：
 *
 *   1. `tools/dressup-lab/anchors/<项目>.json` —— 部位锚点库。
 *      过期后果：点「载入锚点库」会把部位弹回旧布局。
 *   2. `tools/dressup-lab/projects/<项目>/export/` —— 导出交付物（slots.json / 图集 / 预览 / 报告）。
 *      过期后果：交付物与项目对不上，自检第 12 组会失败。
 *      判据两条：① 结构与项目逐字段不一致（画布/部位/部件）；
 *                ② 结构一致但**输入比交付物新**（换了贴图就是这一类 —— 快照里看不出内容变化）。
 *
 * --check 只体检不写（CI / 提交前用）；不带参数则写回。
 * 导出走实验室**自己的导出实现**（src/exporters.js），通过 headless Chrome 跑，
 * 不重复实现任何导出逻辑（渲染依赖浏览器 canvas）。
 */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import url from 'node:url';
import * as M from '../tools/dressup-lab/src/model.js';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const APP = path.join(ROOT, 'tools/dressup-lab');
const arg = (n, d) => {
  const i = process.argv.indexOf('--' + n);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : d;
};
const PROJECT = arg('project', 'human_female');
const CHECK = process.argv.includes('--check');
const BASE = arg('base', process.env.DRESSLAB_BASE || 'http://127.0.0.1:8791');

const projFile = path.join(APP, 'projects', PROJECT, 'project.json');
if (!fs.existsSync(projFile)) {
  console.error(`找不到项目 ${PROJECT}：${projFile}`);
  process.exit(2);
}
const project = M.normalizeProject(JSON.parse(fs.readFileSync(projFile, 'utf8')));
const real = M.realSlots(project);
console.log(`项目 ${PROJECT}：部位 ${real.length} / 部件 ${project.parts.length} / 画布 ${project.canvas.width}×${project.canvas.height}`);

// ---------------------------------------------------------------- 1) 锚点库
const anchors = M.slotsToAnchors(project);
const libFile = path.join(APP, 'anchors', `${PROJECT}.json`);
let libDelta = Infinity;
if (fs.existsSync(libFile)) {
  const lib = JSON.parse(fs.readFileSync(libFile, 'utf8'));
  libDelta = 0;
  for (const a of anchors) {
    const b = (lib.anchors || []).find((x) => x.name === a.name);
    if (!b) { libDelta = Infinity; break; }
    libDelta = Math.max(libDelta, Math.abs(a.x - b.x), Math.abs(a.y - b.y), Math.abs(a.w - b.w), Math.abs(a.h - b.h));
  }
}
console.log(`\n[锚点库] anchors/${PROJECT}.json  偏差 maxΔ = ${libDelta === Infinity ? '不存在/缺少部位' : libDelta.toFixed(3)}`);
if (libDelta !== 0) {
  if (CHECK) console.log('  → 过期（--check 模式，不写）');
  else {
    const payload = {
      format: 'spine-dressup-lab-anchors', version: 2, name: PROJECT,
      rig: project.rig?.source || '', frame: 'root', updatedAt: new Date().toISOString(),
      coordinateSystem: 'root 坐标系：固定中心为原点，x 向右、y 向上；部位 = bbox 中心 + 尺寸。与骨架无关，画布无关。',
      note: `部位锚点库：与项目 ${PROJECT} 同步（画布 ${project.canvas.width}×${project.canvas.height}，root = 底边中点）`,
      anchors,
    };
    fs.mkdirSync(path.dirname(libFile), { recursive: true });
    fs.writeFileSync(libFile, JSON.stringify(payload, null, 2), 'utf8');
    console.log(`  → 已按当前项目重写（${anchors.length} 个锚点）`);
  }
}

// ---------------------------------------------------------------- 2) 导出交付物
const exportDir = path.join(APP, 'projects', PROJECT, 'export');
const slotsJson = path.join(exportDir, 'slots.json');
let expStale = '缺失';
if (fs.existsSync(slotsJson)) {
  const slots = JSON.parse(fs.readFileSync(slotsJson, 'utf8'));
  const snapFile = path.join(exportDir, 'project.json');
  const fc = slots.fixedCenter?.canvas;
  const expectX = project.canvas.width / 2, expectY = project.canvas.height;
  const sizeOk = !!fc && Math.abs(fc.x - expectX) < 0.5 && Math.abs(fc.y - expectY) < 0.5 && slots.slotCount === real.length;
  let why = sizeOk ? '' : `画布/部位数不匹配（slots.json 记的是 ${fc ? `${fc.x * 2}×${fc.y}` : '?'} / ${slots.slotCount} 个部位）`;
  // 位置也要比：导出快照里的 slot / part 必须与当前项目逐字段一致，
  // 否则"部件挪了 8px"这种改动会被漏判（交付物看着没变，其实已经对不上）
  if (sizeOk && fs.existsSync(snapFile)) {
    const snap = JSON.parse(fs.readFileSync(snapFile, 'utf8'));
    const key = (x) => JSON.stringify(x);
    if (key(snap.slots) !== key(project.slots)) why = '部位位置/尺寸或裁剪开关变了（与导出快照不一致）';
    else if (key(snap.parts) !== key(project.parts)) why = '部件位置/缩放变了（与导出快照不一致）';
  }
  expStale = why ? why : null;
  if (!expStale) {
    // 结构一致 ≠ 内容一致：换了贴图（或改了画布背景等不进快照的字段）之后没重新导出，
    // slots/parts 逐字段还是对得上，工件却已经旧了。用"输入比输出新"兜住这一类。
    //
    // 但 project.json 的 mtime **不能单独作数**：实验室每保存一次就刷新 updatedAt，
    // 而 updatedAt 不进任何交付物。若不排除它，每次保存后都会误报一次"需要重新导出"。
    // → 只有"除 updatedAt 外确实还有别的差异"时，才把 project.json 当成比交付物新的输入。
    const strip = (o) => { const c = { ...o }; delete c.updatedAt; return JSON.stringify(c); };
    const snapFileRaw = fs.existsSync(snapFile) ? JSON.parse(fs.readFileSync(snapFile, 'utf8')) : null;
    const projContentChanged = !snapFileRaw || strip(snapFileRaw) !== strip(project);
    const imgDir = path.join(APP, 'projects', PROJECT, 'images');
    const inputs = [...(projContentChanged ? [projFile] : []),
      ...(fs.existsSync(imgDir) ? fs.readdirSync(imgDir).map((f) => path.join(imgDir, f)) : [])]
      .filter((f) => fs.statSync(f).isFile());
    const outputs = ['atlas/atlas.png', 'atlas/atlas.json', 'atlas/atlas.atlas', 'slots.json', 'slots.png', 'report.md', 'preview.png', 'project.json']
      .map((f) => path.join(exportDir, f)).filter((f) => fs.existsSync(f));
    if (inputs.length && outputs.length) {
      const mtime = (f) => fs.statSync(f).mtimeMs;
      const newestIn = Math.max(...inputs.map(mtime));
      const oldestOut = Math.min(...outputs.map(mtime));
      if (newestIn > oldestOut + 1000) {
        const who = inputs.filter((f) => mtime(f) === newestIn).map((f) => path.basename(f));
        expStale = `有输入比交付物新 ${Math.round((newestIn - oldestOut) / 1000)}s（${who.join(', ')}）—— 结构没变但内容变了，需要重新导出`;
      }
    } else if (projContentChanged) {
      expStale = '项目内容与导出快照不一致（没有可比对的贴图输入，无法用 mtime 判断）';
    }
  }
}
console.log(`\n[导出交付物] projects/${PROJECT}/export/  ${expStale ? '过期：' + expStale : '与项目一致'}`);

if (expStale && !CHECK) {
  // 用实验室自己的导出实现生成（渲染要浏览器 canvas）
  // 触发器**入库**在 scripts/ 下：它是一段真实代码，放 tmp/（可随时清理）会让这个工具静默降级
  const TMP = path.join(ROOT, 'tmp');                       // 只用来放 headless Chrome 的临时 profile
  const trigger = path.join(APP, 'scripts', 'lab-export-trigger.html');
  if (!fs.existsSync(trigger)) {
    console.error(`  缺少 ${path.relative(ROOT, trigger).replace(/\\/g, '/')}（导出触发器），跳过导出`);
  } else {
    const PORT = 8796;
    const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png' };
    const server = http.createServer(async (req, res) => {
      const p = decodeURIComponent(new URL(req.url, `http://127.0.0.1:${PORT}`).pathname);
      if (p.startsWith('/api/') || p.startsWith('/ws/')) {
        const chunks = [];
        for await (const c of req) chunks.push(c);
        const body = Buffer.concat(chunks);
        try {
          const r = await fetch(BASE + req.url, {
            method: req.method,
            headers: { 'content-type': req.headers['content-type'] || 'application/octet-stream' },
            body: body.length ? body : undefined,
          });
          res.writeHead(r.status, { 'content-type': r.headers.get('content-type') || 'application/octet-stream' });
          res.end(Buffer.from(await r.arrayBuffer()));
        } catch (e) { res.writeHead(502); res.end('proxy: ' + e.message); }
        return;
      }
      const file = p === '/' || p === '/trigger.html' ? trigger : path.join(APP, p);
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end('404'); return; }
      res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
      fs.createReadStream(file).pipe(res);
    });
    await new Promise((r) => server.listen(PORT, '127.0.0.1', r));
    const CHROME = process.env.CHROME_PATH
      || ['C:/Program Files/Google/Chrome/Application/chrome.exe',
        'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
    if (!CHROME) {
      console.error('  找不到 Chrome / Edge，无法自动导出（可设 CHROME_PATH）');
    } else {
      const child = spawn(CHROME, [
        '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
        `--user-data-dir=${path.join(TMP, 'chrome-profile')}`, '--virtual-time-budget=60000', '--dump-dom',
        `http://127.0.0.1:${PORT}/trigger.html?project=${PROJECT}`,
      ], { stdio: ['ignore', 'pipe', 'pipe'] });
      let out = '';
      child.stdout.on('data', (d) => { out += d; });
      const code = await new Promise((r) => child.on('exit', r));
      server.close();
      const okExport = /EXPORT_OK/.test(out);
      console.log(`  → headless 导出 ${okExport ? '成功' : `失败（chrome exit ${code}）`}`);
    }
  }
}

console.log(`\n${CHECK ? '（--check 模式：只看不改）' : '同步完成'}`);
process.exit(0);
