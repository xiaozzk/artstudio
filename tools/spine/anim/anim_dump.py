#!/usr/bin/env python3
"""anim_dump.py — 解析 Spine JSON 动画关键帧（评估阶段的「动作分析」工具）。

用法：
    python3 tools/spine/anim/anim_dump.py <包目录或骨架json> [动画名]
    python3 tools/spine/anim/anim_dump.py <包> attack --summary   # 只看主要骨骼摘要

格式陷阱（实测，勿改）：
- 4.3 JSON 首帧常省略 "time" 字段，缺省即 0
- rotate 通道读 value，translate/scale 读 x/y
- curve 只有三种形态：省略=linear、字符串 'stepped'、数组=贝塞尔

--summary 输出每个动画的「主谋骨骼」：按峰值幅度排序，标注主要/次要动作
——对应用户方法论「评估哪些骨骼进行了变换、哪些是主要动作」这一步。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_skeleton(path: Path) -> dict:
    if path.is_dir():
        for jf in sorted(path.glob("*.json")):
            try:
                doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(doc, dict) and "bones" in doc and "skeleton" in doc:
                return doc
        raise SystemExit(f"[!] {path} 下找不到骨架 json")
    return json.loads(path.read_text(encoding="utf-8"))


def track_peak(keys: list[dict], ch: str) -> float:
    """轨道的峰值幅度（相对首帧的最大绝对偏移）。"""
    peak = 0.0
    for k in keys:
        if ch == "rotate":
            peak = max(peak, abs(k.get("value", 0.0)))
        else:
            peak = max(peak, abs(k.get("x", 0.0)), abs(k.get("y", 0.0)))
    return peak


def summarize(name: str, anim: dict) -> None:
    rows = []
    dur = 0.0
    for bname, tracks in anim.get("bones", {}).items():
        for ch, keys in tracks.items():
            if not isinstance(keys, list):
                continue
            for k in keys:
                dur = max(dur, k.get("time", 0.0))
            rows.append((track_peak(keys, ch), bname, ch, len(keys)))
    rows.sort(reverse=True)
    print(f'━━━ {name} ━━━ {dur:.2f}s，{len(rows)} 条轨道')
    if not rows:
        print('  （空动画）')
        return
    main_amp = rows[0][0]
    for peak, bname, ch, n in rows:
        role = "主" if peak >= main_amp * 0.4 and peak > 2 else "·"
        unit = "°" if ch == "rotate" else "px"
        print(f'  [{role}] {bname:<12} {ch:<9} {n:>2}帧  峰值 {peak:>7.1f}{unit}')


def dump(name: str, anim: dict) -> None:
    print(f'━━━ {name} ━━━')
    for bname in sorted(anim.get("bones", {})):
        for ch, keys in anim["bones"][bname].items():
            if not isinstance(keys, list):
                continue
            t = [round(k.get("time", 0), 2) for k in keys]
            if ch == "rotate":
                v = [round(k.get("value", 0), 1) for k in keys]
            else:
                v = [(round(k.get("x", 0), 1), round(k.get("y", 0), 1)) for k in keys]
            curves = {}
            for k in keys:
                c = str(k.get("curve", "linear"))[:12]
                curves[c] = curves.get(c, 0) + 1
            print(f'  {bname:<12} {ch:<9} {len(keys)}帧 t={t}')
            print(f'{"":16}v={v}  curve={curves}')
    for sname, s in anim.get("slots", {}).items():
        for ch, keys in s.items():
            if isinstance(keys, list):
                print(f'  [slot]{sname} {ch}: {len(keys)}帧')
    print()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    doc = load_skeleton(Path(argv[1]))
    anims = doc.get("animations", {})
    want = argv[2] if len(argv) > 2 and not argv[2].startswith("-") else None
    summary = "--summary" in argv
    for name in ([want] if want else anims):
        if name not in anims:
            print(f"[!] 没有动画 {name}（现有：{list(anims)}）")
            return 1
        if summary:
            summarize(name, anims[name])
        else:
            dump(name, anims[name])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
