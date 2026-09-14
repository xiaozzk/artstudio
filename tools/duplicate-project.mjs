#!/usr/bin/env node
/**
 * 复制（重名）一个换装实验室项目 —— 走 HTTP API，不改 tools/dressup-lab/ 的源码。
 *
 *   node tools/duplicate-project.mjs --from human_female                 # 自动起名 human_female_2
 *   node tools/duplicate-project.mjs --from human_female --to human_male
 *   node tools/duplicate-project.mjs --from human_female --to x --base http://127.0.0.1:8791
 *
 * 做的事：
 *   1. GET  /api/project?name=<源>            读出源项目的 project.json（含部位/部件/分组）
 *   2. POST /api/project                      建目标项目（名字已存在就报错，不覆盖）
 *   3. POST /api/project/upload?...           逐张把源项目 images/ 的贴图原样上传（保文件名）
 *   4. PUT  /api/project                      写目标 project.json：名称换成新名字，其余照搬
 *
 * 不复制：`export/`（可再生的导出产物）、`rig/`（骨架是手动导入的，需要就从源项目再导一次）。
 * 复制后两个项目完全独立：改一个不影响另一个。
 */
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const arg = (name, dflt) => {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : dflt;
};

const BASE = arg('base', process.env.DRESSLAB_BASE || 'http://127.0.0.1:8791');
const FROM = arg('from', '');
const TO = arg('to', '');

async function jfetch(route, opts = {}) {
  const res = await fetch(BASE + route, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(`${route} → ${res.status} ${(data && data.error) || text.slice(0, 200)}`);
  return data;
}

/** 目标项目名：没给 --to 就自动找第一个没被占用的 <源名>_N（N 从 2 起） */
async function pickName(srcName) {
  if (TO) return TO;
  const { projects } = await jfetch('/api/projects');
  const taken = new Set(projects.map((p) => p.name));
  for (let i = 2; i < 999; i++) {
    const cand = `${srcName}_${i}`;
    if (!taken.has(cand)) return cand;
  }
  throw new Error('找不到可用的目标项目名，请显式指定 --to');
}

async function main() {
  if (!FROM) throw new Error('缺少 --from <源项目名>');
  const src = await jfetch('/api/project?' + new URLSearchParams({ name: FROM }));
  const source = src.project;
  const TO_NAME = await pickName(FROM);
  if (TO_NAME === FROM) throw new Error('目标项目名与源相同，换一个 --to');

  // 源项目在磁盘上的 images/（贴图原始字节从这里读，保证 1:1 复制）
  const srcDir = path.join(ROOT, src.dir, 'images');
  if (!fs.existsSync(srcDir)) throw new Error('源项目没有 images/ 目录：' + srcDir);

  console.log(`源项目   ${FROM}  (部位 ${(source.slots || []).filter((s) => !s.virtual).length} / 部件 ${(source.parts || []).length})`);
  console.log(`目标项目 ${TO_NAME}`);

  const created = await jfetch('/api/project', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: TO_NAME }),
  });
  const existing = await jfetch('/api/parts?' + new URLSearchParams({
    dir: `tools/dressup-lab/projects/${TO_NAME}/images`,
  }));
  if (existing.items.length) {
    throw new Error(`目标项目 ${TO_NAME} 里已有 ${existing.items.length} 张贴图，拒绝覆盖；换个名字。`);
  }

  // ---- 上传贴图：按部件名去重（多个部件可能共用一张图），保原名
  const wanted = [...new Set((source.parts || []).map((p) => String(p.image?.src || '').split('/').pop()).filter(Boolean))];
  const mapping = new Map();
  for (const file of wanted) {
    const abs = path.join(srcDir, file);
    if (!fs.existsSync(abs)) { console.log(`  ! 缺贴图跳过：${file}`); continue; }
    const buf = fs.readFileSync(abs);
    const r = await jfetch('/api/project/upload?' + new URLSearchParams({ name: TO_NAME, filename: file }), {
      method: 'POST', headers: { 'content-type': 'image/png' }, body: buf,
    });
    mapping.set(file, { filename: r.filename, src: r.src, width: r.width, height: r.height });
    const flag = r.filename === file ? '' : `  (服务端改名 → ${r.filename})`;
    console.log(`  ↑ ${file.padEnd(26)} ${r.width}×${r.height}${flag}`);
  }

  // ---- 写目标 project.json：名称换掉，其余照搬；src 指向新项目的 images/
  const now = new Date().toISOString();
  const clone = JSON.parse(JSON.stringify(source));
  delete clone.export;
  clone.name = TO_NAME;
  clone.createdAt = now;
  clone.updatedAt = now;
  for (const part of clone.parts || []) {
    const base = String(part.image?.src || '').split('/').pop();
    const up = mapping.get(base);
    if (!up) continue;
    part.image.src = up.src;
    part.image.width = up.width;
    part.image.height = up.height;
  }
  clone.meta = {
    ...(clone.meta || {}),
    duplicatedFrom: FROM,
    duplicatedAt: now,
    source: 'tools/duplicate-project.mjs (API)',
  };

  const saved = await jfetch('/api/project', {
    method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name: TO_NAME, project: clone }),
  });
  console.log(`\nproject.json 已写入：${saved.path}`);

  // ---- 回读自检：两个项目逐字段对比
  const back = (await jfetch('/api/project?' + new URLSearchParams({ name: TO_NAME }))).project;
  const problems = [];
  const srcParts = source.parts || [];
  const dstParts = back.parts || [];
  if (dstParts.length !== srcParts.length) problems.push(`部件 ${dstParts.length} ≠ ${srcParts.length}`);
  if ((back.slots || []).length !== (source.slots || []).length) problems.push('部位数不一致');
  if (JSON.stringify(back.canvas) !== JSON.stringify(source.canvas)) problems.push('画布不一致');
  if (JSON.stringify(back.partLib) !== JSON.stringify(source.partLib)) problems.push('部件库分组不一致');
  for (const a of srcParts) {
    const b = dstParts.find((p) => p.id === a.id);
    if (!b) { problems.push(`${a.id}: 目标里不存在`); continue; }
    for (const k of ['slotId', 'z', 'fit', 'visible', 'opacity']) {
      if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) problems.push(`${a.id}.${k} 不一致`);
    }
    for (const k of ['pivot', 'offset']) {
      if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) problems.push(`${a.id}.${k} 不一致`);
    }
    if (!fs.existsSync(path.join(ROOT, b.image.src))) problems.push(`${a.id}: 目标贴图不存在 ${b.image.src}`);
  }
  for (const s of source.slots || []) {
    const t = (back.slots || []).find((x) => x.id === s.id);
    if (!t) { problems.push(`${s.id}: 目标里不存在`); continue; }
    for (const k of ['x', 'y', 'w', 'h']) {
      if (Math.abs((s[k] || 0) - (t[k] || 0)) > 1e-9) problems.push(`${s.id}.${k} 不一致`);
    }
  }
  console.log('回读自检：' + (problems.length ? '✗ ' + problems.join('；') : `✓ 与源项目逐字段一致（${dstParts.length} 部件 / ${(back.slots || []).length} 部位 / ${mapping.size} 张贴图）`));
  if (problems.length) process.exitCode = 1;

  console.log(`\n打开：${BASE}/  → 项目下拉选「${TO_NAME}」（源项目「${FROM}」保持不动）`);
}

await main().catch((e) => { console.error('复制失败：' + e.message); process.exit(1); });
