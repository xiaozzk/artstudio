# -*- coding: utf-8 -*-
"""005 Step2: 把 32 张附件单图拼成带槽名/附件名标注的识别总览图（纯本地、确定性）"""
import json, os
from PIL import Image, ImageDraw, ImageFont

PKG = 'task/005-generic-skeleton/input/Unit_Spine_EmpirePaladinSpe1Skin1'
IMG_DIR = os.path.join(PKG, 'images_original')
doc = json.load(open(os.path.join(PKG, 'Unit_Spine_EmpirePaladinSpe1Skin1.json'), encoding='utf-8'))

# slot -> [attachment names in setup skin]
slot_atts = {}
for s in doc['slots']:
    slot_atts[s['name']] = ([s.get('attachment')] if s.get('attachment') else [])
for sk in doc['skins']:
    for slot, atts in sk['attachments'].items():
        slot_atts.setdefault(slot, [])
        for n in atts:
            if n not in slot_atts[slot]:
                slot_atts[slot].append(n)

rows = []
for s, atts in slot_atts.items():
    for n in atts:
        rows.append((s, n))
rows.sort(key=lambda r: (-os.path.getsize(os.path.join(IMG_DIR, r[1] + '.png')), r[0], r[1]))

CELL_W, CELL_H, LABEL_H, COLS = 300, 300, 46, 5
BG = (235, 235, 245)
def font(sz):
    for p in ('/System/Library/Fonts/Supplemental/Arial.ttf',
              '/System/Library/Fonts/Helvetica.ttc'):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()
F1, F2 = font(20), font(17)

cols = (len(rows) + COLS - 1) // COLS
sheet = Image.new('RGB', (COLS * CELL_W, cols * (CELL_H + LABEL_H)), (200, 200, 210))
d = ImageDraw.Draw(sheet)
for i, (slot, att) in enumerate(rows):
    cx, cy = (i % COLS) * CELL_W, (i // COLS) * (CELL_H + LABEL_H)
    cell = Image.new('RGBA', (CELL_W - 8, CELL_H - 8), (180, 180, 195, 255))
    cd = ImageDraw.Draw(cell)
    for y in range(0, CELL_H - 8, 24):  # 棋盘底可辨透明边界
        for x in range(0, CELL_W - 8, 24):
            if (x // 24 + y // 24) % 2 == 0:
                cd.rectangle([x, y, x + 23, y + 23], fill=(205, 205, 220, 255))
    img = Image.open(os.path.join(IMG_DIR, att + '.png')).convert('RGBA')
    img.thumbnail((CELL_W - 16, CELL_H - 16))
    cell.alpha_composite(img, ((CELL_W - 8 - img.width) // 2, (CELL_H - 8 - img.height) // 2))
    sheet.paste(cell.convert('RGB'), (cx + 4, cy + 4))
    d.rectangle([cx + 4, cy + CELL_H, cx + CELL_W - 4, cy + CELL_H + LABEL_H - 6],
                fill=(25, 25, 35))
    d.text((cx + 10, cy + CELL_H + 2), f'slot[{slot}]', fill=(120, 220, 255), font=F1)
    d.text((cx + 10, cy + CELL_H + 24), f'att {att}', fill=(255, 230, 120), font=F2)
sheet.save('tmp/005/slot-sheet.png')
print('rows:', [(s, a) for s, a in rows])
print('saved tmp/005/slot-sheet.png', sheet.size)
