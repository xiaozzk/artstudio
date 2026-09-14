#!/usr/bin/env node
/**
 * 把切好的部件贴图**通过 API** 导进「换装实验室」（tools/dressup-lab）。
 *
 *   node tools/import-parts-to-dressup-lab.mjs --project human_female \
 *        --manifest assets/eva_bone/parts/parts-manifest.json [--base http://127.0.0.1:8791]
 *
 * 本脚本属于**工作区自己的工具**，不改动 tools/dressup-lab/ 里的任何源码；
 * 只通过它对外暴露的 HTTP API 干活：
 *   1. POST /api/project                  建项目（已存在就是幂等的）
 *   2. POST /api/project/upload?...        逐张上传 PNG（原始字节）→ projects/<项目>/images/
 *   3. PUT  /api/project                   写完整 project.json：
 *        部位锚点 = 新图里该部件的中心（画布坐标 y↓，root 坐标 y↑ 由画布底边中点换算）
 *        slot 尺寸 = 部件贴图尺寸  → 装配时 pivot=贴图中心、offset=0、scale=1，
 *        于是「数值上」逐像素还原新图里的原位；以后换同尺寸的部件即 100% 切合。
 *
 * 部件库分组（12 类：头发/脸型/耳朵/眼睛/眉毛/鼻子/嘴巴/躯干/手臂/手腕/腿部/脚步）
 * 写进这个项目自己的 `partLib`，**不动**实验室的默认分组。
 *
 * 注意：上传接口不覆盖同名文件（自动加 _2），项目里已有贴图时本脚本会拦下来，
 * 免得部件库被同名重复图污染 —— 重建请先删项目或换 --project。
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

const PROJECT = arg('project', 'human_female');
const MANIFEST = path.resolve(ROOT, arg('manifest', 'assets/eva_bone/parts/parts-manifest.json'));
const BASE = arg('base', process.env.DRESSLAB_BASE || 'http://127.0.0.1:8791');
const ANCHOR_LIB = path.resolve(ROOT, arg('anchors', 'tools/dressup-lab/anchors/human_female.json'));

/** 本项目用的部件库分组：12 类（只写进 project.json，不改实验室默认） */
const GROUPS = [
  { id: 'grp_hair', name: '头发', order: 0 },
  { id: 'grp_head', name: '脸型', order: 1 },
  { id: 'grp_ear', name: '耳朵', order: 2 },
  { id: 'grp_eye', name: '眼睛', order: 3 },
  { id: 'grp_brow', name: '眉毛', order: 4 },
  { id: 'grp_nose', name: '鼻子', order: 5 },
  { id: 'grp_mouth', name: '嘴巴', order: 6 },
  { id: 'grp_torso', name: '躯干', order: 7 },
  { id: 'grp_arm', name: '手臂', order: 8 },
  { id: 'grp_wrist', name: '手腕', order: 9 },
  { id: 'grp_leg', name: '腿部', order: 10 },
  { id: 'grp_foot', name: '脚步', order: 11 },
];
const GROUP_OF = {
  hair: 'grp_hair',
  head_base: 'grp_head',
  ear: 'grp_ear',
  face_eye_left: 'grp_eye', face_eye_right: 'grp_eye',
  face_eyebrow_left: 'grp_brow', face_eyebrow_right: 'grp_brow',
  face_nose: 'grp_nose',
  face_mouth: 'grp_mouth',
  torso: 'grp_torso',
  left_arm: 'grp_arm', right_arm: 'grp_arm',
  left_arm_wrist: 'grp_wrist', right_arm_wrist: 'grp_wrist',
  left_leg: 'grp_leg', right_leg: 'grp_leg',
  left_leg_foot: 'grp_foot', right_leg_foot: 'grp_foot',
};
/** 绘制层序：数值大者在上。躯干/腿先铺，手臂压在上面，头发最后压住脸型 */
const Z_ORDER = {
  left_leg_foot: 0, right_leg_foot: 1,
  left_leg: 10, right_leg: 11,
  torso: 20,
  left_arm: 30, right_arm: 31,
  left_arm_wrist: 40, right_arm_wrist: 41,
  head_base: 110,
  face_nose: 115, face_mouth: 116,
  face_eye_left: 117, face_eye_right: 118,
  face_eyebrow_left: 119, face_eyebrow_right: 120,
  ear: 121,
  hair: 130,
};

async function jfetch(route, opts = {}) {
  const res = await fetch(BASE + route, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(`${route} → ${res.status} ${(data && data.error) || text.slice(0, 200)}`);
  return data;
}

async function main() {
  if (!fs.existsSync(MANIFEST)) throw new Error('找不到清单：' + MANIFEST);
  const man = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
  const sheetRel = man.sheet;
  if (!fs.existsSync(path.join(ROOT, sheetRel))) throw new Error('清单里的画布不存在：' + sheetRel);
  const [W, H] = man.canvas;

  let boneOf = {};
  try {
    const lib = JSON.parse(fs.readFileSync(ANCHOR_LIB, 'utf8'));
    boneOf = Object.fromEntries((lib.anchors || []).map((a) => [a.name, a.bone]));
  } catch { /* 锚点库可选 */ }

  // ---- 1) 建项目（幂等：已存在也返回 ok）
  const created = await jfetch('/api/project', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: PROJECT }),
  });
  const existing = await jfetch('/api/parts?' + new URLSearchParams({
    dir: `tools/dressup-lab/projects/${PROJECT}/images`,
  }));
  if (existing.items.length) {
    throw new Error(
      `项目 ${PROJECT} 的 images/ 里已有 ${existing.items.length} 张贴图；` +
      `上传不会覆盖同名文件，重跑会生成 _2 副本。\n` +
      `  想重建：先 POST /api/project/delete {name:"${PROJECT}"}（真删目录），或直接删目录 ` +
      `tools/dressup-lab/projects/${PROJECT}\n` +
      `  想共存：换 --project <别的名字>`,
    );
  }
  console.log(`项目就绪：${created.name}  (${created.dir})`);

  // ---- 2) 逐张上传（清单里 parts 的 key 已是部位名；face 的 key 要补上 face_ 前缀）
  const items = [
    ...Object.entries(man.parts),
    ...Object.entries(man.face).map(([k, v]) => [k.startsWith('face_') ? k : `face_${k}`, v]),
  ];
  const uploaded = new Map();
  for (const [name, info] of items) {
    const file = path.resolve(path.dirname(MANIFEST), info.file);
    const buf = fs.readFileSync(file);
    const qs = new URLSearchParams({ name: PROJECT, filename: info.file });
    const r = await jfetch('/api/project/upload?' + qs, {
      method: 'POST', headers: { 'content-type': 'image/png' }, body: buf,
    });
    if (r.width !== info.w || r.height !== info.h) {
      throw new Error(`${name}: 上传后尺寸 ${r.width}x${r.height} ≠ 清单 ${info.w}x${info.h}`);
    }
    uploaded.set(name, { src: r.src, filename: r.filename, w: r.width, h: r.height });
    console.log(`  ↑ ${info.file.padEnd(24)} ${r.width}×${r.height}  → ${r.src}`);
  }

  // ---- 3) 组装 project.json
  const rootSlot = {
    id: 'slot_root', name: 'root', bone: null,
    x: W / 2, y: H, w: 0, h: 0, clip: false,
    color: '#ffd479', visible: true, locked: true, virtual: true, order: -1,
  };
  const slots = [rootSlot];
  const parts = [];
  const COLORS = ['#ff7ac6', '#6ee7d7', '#59e08b', '#7fd1ff', '#ffb454', '#ff8fa3',
    '#c9a6ff', '#ffe066', '#ff9f6e', '#a0b4ff', '#f4a9c0', '#8de0a8'];
  let i = 0;
  for (const [name, info] of items) {
    const up = uploaded.get(name);
    const cx = (info.bbox[0] + info.bbox[2]) / 2;    // 画布坐标（y↓）
    const cy = (info.bbox[1] + info.bbox[3]) / 2;
    const slot = {
      id: `slot_${name}`, name,
      bone: boneOf[name] ?? null,
      x: cx, y: cy, w: info.w, h: info.h,
      clip: false,                       // 新图里各部件本就不重叠，先不裁，便于看清
      color: COLORS[i % COLORS.length],
      visible: true, locked: false, virtual: false,
      order: i,
      z: Z_ORDER[name] ?? 100 + i,
    };
    slots.push(slot);
    parts.push({
      id: `part_${name}`, name, slotId: slot.id,
      image: { src: up.src, width: up.w, height: up.h },
      pivot: { x: info.w / 2, y: info.h / 2 },
      offset: { x: 0, y: 0 },
      rotation: 0, scaleX: 1, scaleY: 1,
      z: slot.z,
      opacity: 1, visible: true, locked: false, blendMode: 'source-over',
      fit: 'fill', visual: null,
    });
    i++;
  }
  parts.sort((a, b) => a.z - b.z);

  const project = {
    format: 'spine-dressup-lab', version: 3, name: PROJECT,
    createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
    canvas: { width: W, height: H, background: '#0e1218', grid: 64 },
    rig: { source: '', scale: 1, spine: '', size: { width: 0, height: 0 }, anchor: { x: 0, y: 0 }, bones: [], missing: false },
    overlay: { bones: 'mapped' },
    ruler: { show: true, unit: 'root' },
    atlas: { padding: 2, trim: false, powerOfTwo: true, scale: 1, maxSize: 2048 },
    slots, parts,
    meta: {
      source: 'tools/import-parts-to-dressup-lab.mjs (API)',
      sheet: sheetRel,
      anchors: { name: 'human_female', file: 'tools/dressup-lab/anchors/human_female.json', frame: 'root', count: items.length, note: '新项目未挂骨架，bone 字段作为映射备注保留' },
      frame: `画布 = 切片源画布 ${W}×${H}，root = 底边中点 (${W / 2}, ${H})`,
      partGroups: GROUPS.map((g) => g.name).join('/'),
    },
    filters: {
      slot: { edit: true, show: true, label: true },
      part: { edit: true, show: true, label: false },
      bone: { edit: true, show: false, label: false },
    },
    partLib: {
      groups: GROUPS.map((g) => ({ ...g })),
      assign: Object.fromEntries(items.map(([name, info]) => [info.file, GROUP_OF[name] || 'grp_torso'])),
    },
  };

  const saved = await jfetch('/api/project', {
    method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name: PROJECT, project }),
  });
  console.log(`\nproject.json 已写入：${saved.path}`);
  console.log(`  部位 ${slots.length - 1} 个，部件 ${parts.length} 件，画布 ${W}×${H}，root (${W / 2}, ${H})`);

  // ---- 4) 回读自检
  const back = await jfetch('/api/project?' + new URLSearchParams({ name: PROJECT }));
  const p = back.project;
  const problems = [];
  if (p.slots.length !== slots.length) problems.push('部位数不一致');
  if (p.parts.length !== parts.length) problems.push('部件数不一致');
  for (const part of p.parts) {
    const slot = p.slots.find((s) => s.id === part.slotId);
    if (!slot) { problems.push(`${part.name}: 找不到部位`); continue; }
    if (slot.w !== part.image.width || slot.h !== part.image.height) problems.push(`${part.name}: slot 尺寸 ≠ 贴图尺寸`);
    if (Math.abs(part.image.width / 2 - part.pivot.x) > 1e-6) problems.push(`${part.name}: pivot 不在贴图中心`);
  }
  const imgs = await jfetch('/api/parts?' + new URLSearchParams({ dir: `tools/dressup-lab/projects/${PROJECT}/images` }));
  if (imgs.items.length !== items.length) problems.push(`images/ 里 ${imgs.items.length} 张图 ≠ ${items.length}`);
  const groups = p.partLib?.groups || [];
  const assign = p.partLib?.assign || {};
  if (groups.length !== GROUPS.length) problems.push(`分组 ${groups.length} 个 ≠ ${GROUPS.length}`);
  for (const g of GROUPS) {
    if (!groups.some((x) => x.id === g.id && x.name === g.name)) problems.push(`缺分组 ${g.name}`);
  }
  for (const part of p.parts) {
    const base = String(part.image.src).split('/').pop();
    const g = assign[base];
    if (!g) problems.push(`${base}: 未归组`);
    else if (!groups.some((x) => x.id === g)) problems.push(`${base}: 指向不存在的分组 ${g}`);
  }
  console.log('\n分组：' + groups.slice().sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map((g) => `${g.name}(${Object.values(assign).filter((v) => v === g.id).length})`).join(' / '));
  console.log('\n回读自检：' + (problems.length ? '✗ ' + problems.join('；') : `✓ 全部通过（${imgs.items.length} 张贴图 / ${p.slots.length} 部位 / ${p.parts.length} 部件）`));
  if (problems.length) process.exitCode = 1;

  console.log(`\n打开：${BASE}/  → 项目下拉选「${PROJECT}」`);
}

await main().catch((e) => { console.error('导入失败：' + e.message); process.exit(1); });
