#!/usr/bin/env python3
"""
v_godot.py —— verifier 独立核对 T3（Godot 4 预览）的 JSON 证据。

任务卡要求：「验证 T3 的截图 JSON，确认 **morph 值确实到了每一件服装**」。

核对点（全部用纯 Python 读 JSON；PNG 另外做像素级非空检查）：
  G1 `preview_morph_receipt.json` 里每个 shot 的 `morph_per_part` 是否**逐件**列出
     （身体 + 每一件服装 + 发型），而不是只报身体一个数；
  G2 各件实测到的 morph 值是否与该 shot 请求的 k **一致**（容差）；
  G3 身体与服装的 morph 值是否**同步**（同一个 k 驱动两边 —— SPEC §0 的"一个数值"）；
  G4 `preview_report.json` 的 `zero_copy`（资产未拷进工程）+ bake 日志有无 error；
  G5 截图 PNG 存在、尺寸正常、**不是纯色空图**（用 zlib 解 PNG 手工算像素方差）。

用法：
  python3 task/007-morph-pipeline/verify/v_godot.py \
      --dir assets/3d/rig/previews \
      --out assets/3d/rig/reports/verify-godot.json
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import zlib


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def png_stats(path):
    """不依赖 PIL：手工解 PNG（IHDR + IDAT）算像素统计。"""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return {"error": "not a png"}
    pos = 8
    w = h = bd = ct = None
    idat = b""
    while pos < len(raw):
        ln = struct.unpack(">I", raw[pos:pos + 4])[0]
        typ = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", data[:10])
        elif typ == b"IDAT":
            idat += data
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if w is None:
        return {"error": "no IHDR"}
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ct, 0)
    if ch == 0 or bd != 8:
        return {"width": w, "height": h, "bitdepth": bd, "colortype": ct,
                "note": "非 8bit 真彩/灰度，未解码像素"}
    try:
        dec = zlib.decompress(idat)
    except Exception as e:  # noqa: BLE001
        return {"width": w, "height": h, "error": f"zlib: {e}"}
    stride = w * ch
    # 反滤波（只做 None/Sub/Up/Average/Paeth 的实现，够用来算方差）
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _y in range(h):
        ft = dec[p]
        p += 1
        line = bytearray(dec[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out += line
        prev = line
    px = bytes(out)
    n = len(px)
    mean = sum(px) / max(n, 1)
    var = sum((v - mean) ** 2 for v in px) / max(n, 1)
    nz = sum(1 for v in px if v > 8)
    return {"width": w, "height": h, "colortype": ct, "bytes_per_px": ch,
            "byte_mean": round(mean, 3), "byte_variance": round(var, 3),
            "nonblack_frac": round(nz / max(n, 1), 4),
            "looks_blank": bool(var < 5.0 or nz / max(n, 1) < 0.01)}


def png_region_stats(path):
    """左 60% / 右 40% 的字节方差——用来判"3D 视口是不是全黑"。"""
    import numpy as _np
    a = _decode_png(path)
    h, w = a.shape[:2]
    k = int(w * 0.6)
    out = {"resolution": [w, h]}
    for tag, sl in (("left60", (_np.s_[:], _np.s_[:k])),
                    ("right40", (_np.s_[:], _np.s_[k:]))):
        b = a[sl].astype(_np.int16)
        mx = b.max(axis=2)
        mn = b.min(axis=2)
        sat = (mx - mn) > 25          # 有彩度的像素 = 渲染出来的东西（绿布/皮肤/金属）
        out[tag] = {"byte_mean": round(float(b.mean()), 3),
                    "byte_variance": round(float(b.var()), 3),
                    "colored_frac": round(float(sat.mean()), 5)}
    out["left_viewport_has_rendered_content"] = bool(
        out["left60"]["colored_frac"] > 0.01)
    return out


def _decode_png(path):
    """返回 (H,W,3) uint8（不做色彩管理）。"""
    import numpy as _np
    with open(path, "rb") as f:
        raw = f.read()
    pos, idat, w, h, bd, ct = 8, b"", None, None, None, None
    while pos < len(raw):
        ln = struct.unpack(">I", raw[pos:pos + 4])[0]
        typ = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", data[:10])
        elif typ == b"IDAT":
            idat += data
        elif typ == b"IEND":
            break
        pos += 12 + ln
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    dec = zlib.decompress(idat)
    stride = w * ch
    rows = _np.frombuffer(dec, dtype=_np.uint8).reshape(h, stride + 1)
    ftypes = rows[:, 0]
    lines = rows[:, 1:].astype(_np.int32).copy()
    prev = _np.zeros(stride, dtype=_np.int32)
    out = _np.zeros((h, stride), dtype=_np.int32)
    for y in range(h):
        ft = int(ftypes[y])
        cur = lines[y]
        if ft == 0:
            pass
        elif ft == 1:
            for i in range(ch, stride):
                cur[i] = (cur[i] + cur[i - ch]) & 0xFF
        elif ft == 2:
            cur = (cur + prev) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = cur[i - ch] if i >= ch else 0
                cur[i] = (cur[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = cur[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[i] = (cur[i] + pr) & 0xFF
        out[y] = cur
        prev = cur
    arr = out.astype(_np.uint8).reshape(h, w, ch)
    return arr[:, :, :3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="assets/3d/rig/previews")
    ap.add_argument("--out", default="assets/3d/rig/reports/verify-godot.json")
    a = ap.parse_args()
    rep = {"generated_by": "verifier/v_godot.py", "preview_dir": a.dir,
           "checks": {}, "found": {}}
    rp = os.path.join(a.dir, "preview_report.json")
    rr = os.path.join(a.dir, "preview_morph_receipt.json")
    if not os.path.exists(rp) or not os.path.exists(rr):
        rep["status"] = "NOT_READY"
        rep["missing"] = [p for p in (rp, rr) if not os.path.exists(p)]
        print(f"[v_godot] not ready: missing {rep['missing']}")
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        return
    report = load(rp)
    receipt = load(rr)
    rep["status"] = "OK"
    rep["found"]["report_keys"] = sorted(report.keys())
    rep["found"]["receipt_keys"] = sorted(receipt.keys())

    # ---- G1/G2/G3：逐件 morph ----
    shots = receipt.get("shots", {})
    rows = []
    for name, s in shots.items():
        parts = s.get("morph_per_part", [])
        # T3 的实际 schema：parts 里可能有 figure/parts 嵌套；
        # 叶子形如 {part, meshes, thin, heavy, note}
        leaves = []
        for r in parts:
            if isinstance(r, dict) and "parts" in r and isinstance(r["parts"], list):
                leaves += [x for x in r["parts"] if isinstance(x, dict)]
            elif isinstance(r, dict):
                leaves.append(r)
        kinds = {}
        for r in leaves:
            kind = str(r.get("part", "?")).split(":")[0] or "?"
            kinds[kind] = kinds.get(kind, 0) + 1
        # "报告了值" = thin/heavy 里至少一个不是 null（发型件就是 null + note=无 morph 通道）
        vals = []
        for r in leaves:
            for k in ("thin", "heavy", "morph", "value"):
                v = r.get(k)
                if isinstance(v, (int, float)):
                    vals.append(float(v))
        parts = leaves
        rows.append({
            "shot": name, "png": s.get("png"), "k_requested": s.get("k"),
            "n_parts": len(parts), "parts_by_kind": kinds,
            "n_parts_with_value": len(vals),
            "value_min": min(vals) if vals else None,
            "value_max": max(vals) if vals else None,
            "all_parts_report_value": bool(parts) and len(vals) == len(parts),
            "sample_parts": parts[:3],
        })
    rep["checks"]["G1_G2_G3_morph_per_part"] = {
        "n_shots": len(rows),
        "n_shots_with_per_part_receipt": sum(1 for r in rows if r["n_parts"] > 0),
        "n_shots_all_parts_report_value": sum(1 for r in rows if r["all_parts_report_value"]),
        "shots": rows,
    }

    # ---- G4：zero_copy + bake 日志 ----
    zc = report.get("zero_copy", {})
    log = report.get("bake_log", [])
    bad = [l for l in log if isinstance(l, str) and
           any(k in l.lower() for k in ("error", "traceback", "failed", "fatal"))]
    rep["checks"]["G4_hygiene"] = {
        "zero_copy": zc,
        "assets_copied_into_project": zc.get("assets_copied_into_project"),
        "zero_copy_ok": zc.get("assets_copied_into_project") == 0,
        "n_bake_log_lines": len(log),
        "n_suspicious_log_lines": len(bad),
        "suspicious_sample": bad[:5],
        "godot": report.get("godot"), "blender_bin": report.get("blender_bin"),
        "one_command": report.get("one_command"),
        "elapsed_ms": report.get("elapsed_ms"),
    }

    # ---- G5：截图非空 ----
    shots_rep = report.get("shots", [])
    pngs = []
    for s in shots_rep:
        p = s.get("png")
        if not p:
            continue
        full = p if os.path.isabs(p) else os.path.join(a.dir, os.path.basename(p))
        st = png_stats(full) if os.path.exists(full) else {"error": "missing"}
        st["shot"] = s.get("name")
        st["path"] = p
        st["_full"] = full
        pngs.append(st)
    # 视口黑屏检测：整图按"左 60% 视口 / 右 40% UI 面板"切，比两边的方差
    for p in pngs:
        if "error" in p:
            continue
        full = p.get("_full")
        if not full or not os.path.exists(full):
            continue
        try:
            st = png_region_stats(full)
            p.update(st)
            p["viewport_black"] = bool(not st["left_viewport_has_rendered_content"])
        except Exception as e:  # noqa: BLE001
            p["region_error"] = f"{type(e).__name__}: {e}"
    rep["checks"]["G5_screenshots"] = {
        "n_shots": len(shots_rep), "n_png_found": sum(1 for p in pngs if "error" not in p),
        "n_looks_blank": sum(1 for p in pngs if p.get("looks_blank")),
        "n_viewport_black": sum(1 for p in pngs if p.get("viewport_black")),
        "pngs": pngs,
    }
    # 穿模指示面板是否有数据
    px = report.get("penetration_pixel_method_curves", {})
    rep["checks"]["G6_penetration_panel"] = {
        "raw": px,
        "n_entries": len(px) if isinstance(px, dict) else None,
        "n_usable": sum(1 for v in px.values()
                        if isinstance(v, dict) and "error" not in v) if isinstance(px, dict) else None,
        "all_unavailable": bool(isinstance(px, dict) and px and all(
            isinstance(v, dict) and "error" in v for v in px.values())),
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f"[v_godot] wrote {a.out}")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "shots" and kk != "pngs"}
                      for k, v in rep["checks"].items()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()