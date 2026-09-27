#!/usr/bin/env python3
"""batch_bake.py — task/003 全库批量烘焙驱动。

读 input/facing.json 的逐包朝向声明，对 assets/2d 全库：
  facing==left  → spine_flip_bake.py 烘焙一次（含 G1/G2/G3 闸门）
  facing==right → 原样复制 JSON（不动 hash）
产物：output/<分类>/<包名>/<包名>.json（仅 JSON，复用原 atlas/png）
报告：output/flip-bake-report.json（每包：朝向声明、是否翻转、策略、闸门结果、警告、拒绝原因）

用法：python3 task/003-spine-facing-unify/scripts/batch_bake.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[3]
TASK = WS / "task" / "003-spine-facing-unify"
TOOL = WS / "tools" / "spine" / "anim" / "spine_flip_bake.py"
OUT = TASK / "output"


def main() -> int:
    facing = json.loads((TASK / "input" / "facing.json").read_text(encoding="utf-8"))
    target = facing.get("target", "right")
    entries = facing["packages"]

    # 清空旧 JSONL
    jsonl = OUT / "_batch_log.jsonl"
    OUT.mkdir(parents=True, exist_ok=True)
    jsonl.write_text("", encoding="utf-8")

    results = []
    n_baked = n_copy = n_fail = 0
    for i, e in enumerate(entries, 1):
        pkg = e["pkg"]                     # 相对 assets/2d 的路径
        face = e["facing"]
        src = WS / "assets" / "2d" / pkg
        dst = OUT / Path(pkg).parent
        dst.mkdir(parents=True, exist_ok=True)
        rec = {"pkg": pkg, "facing": face, "target": target,
               "confidence": e.get("confidence"), "note": e.get("note")}
        cmd = [sys.executable, str(TOOL), str(src), "-o", str(dst),
               "--from", face, "--to", target, "--report", str(jsonl)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        # 读工具写出的 JSONL 末行
        tool_rec = None
        try:
            lines = [l for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
            if lines:
                tool_rec = json.loads(lines[-1])
                if tool_rec.get("package") != str(src):
                    tool_rec = None
        except Exception:
            tool_rec = None
        rec["returncode"] = p.returncode
        rec["stdout_tail"] = "\n".join((p.stdout or "").splitlines()[-4:])
        if p.returncode != 0:
            rec["status"] = "failed"
            rec["stderr_tail"] = "\n".join((p.stderr or "").splitlines()[-4:])
            n_fail += 1
        else:
            if tool_rec:
                rec.update({k: tool_rec.get(k) for k in
                            ("action", "baked", "constraints", "tier2",
                             "inherit_rewritten", "warnings", "gates", "out")})
                rec["status"] = "baked" if tool_rec.get("baked") else "copied"
            else:
                rec["status"] = "baked" if face != target else "copied"
            if rec["status"] == "baked":
                n_baked += 1
            else:
                n_copy += 1
        results.append(rec)
        flag = {"baked": "B", "copied": "=", "failed": "X"}.get(rec["status"], "?")
        print(f"[{i:3d}/107] {flag} {pkg}", flush=True)

    # 汇总
    summary = {
        "task": "003-spine-facing-unify",
        "target_facing": target,
        "date": "2026-09-27",
        "total": len(results),
        "baked": n_baked,
        "copied": n_copy,
        "failed": n_fail,
        "gate_tolerances": {"G1": 1e-9, "G2": 1e-6},
        "gates_note": "G1 双翻恒等 / G2 真镜像逐骨世界矩阵(root固定setup口径) / G3 不动项审计；"
                      "G2_rootanim 为含 root 动画的信息级偏差（D4 已知边界，非闸门）",
        "packages": results,
    }
    (OUT / "flip-bake-report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完成：烘焙 {n_baked}，复制 {n_copy}，失败 {n_fail} / 共 {len(results)}")
    print(f"报告 → {OUT / 'flip-bake-report.json'}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
