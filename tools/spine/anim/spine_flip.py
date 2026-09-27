#!/usr/bin/env python3
"""spine_flip.py — Spine 包 JSON 级水平镜像（更换人物朝向）。

把朝左的包翻成朝右（或反之）。镜像的是**骨架数据本身**（bones/attachments/animations），
不是运行时 flipX——产物导入编辑器/运行时就是永久朝右。

用法：
  python3 tools/spine/anim/spine_flip.py <包目录> -o <输出目录> --check   # 默认镜像一次
  python3 tools/spine/anim/spine_flip.py <包目录> -o <输出目录> --from right --to left
  python3 tools/spine/anim/spine_flip.py <包目录> --detect               # 只打印朝向线索

**方向配置**（--from / --to）：工具本身不定义"朝左/朝右"的语义——那是视觉判断，
由 agent 看复原预览图（必要时开 player 放 run 动画看跑动方向）声明，再用
`--from <当前> --to <目标>` 告诉工具"要不要翻"：相同则原样输出、不同则镜像一次。
不给这两个参数时默认镜像一次（把当前方向换成它的镜像）。
⚠ 别把「我翻过一次的副本」当成原包再翻——那样会转回原样（法袍法师踩过）。

镜像数学（Y-up 坐标系，X 轴镜像 M=diag(-1,1)，变换共轭 M·T·M）：
  骨骼局部：  x → -x，  rotation → -rotation   （scale/shear 不动）
  region：    x → -x，  rotation → -rotation， scaleX → -scaleX（贴图水平翻转）
  mesh：      顶点 x 取负（y 不动），triangles 绕向反转（[a,b,c]→[a,c,b]，否则背面被剔除），
              uvs 不动（顶点镜像后采样同区域 = 贴图镜像）；附件 x/rotation 同 region 规则
  加权顶点：  [骨数, [骨索引, x, y, 权重]×n ...] 格式里只翻 x（骨索引/权重不动）
  动画：      bones.translate.x → -x；bones.rotate.value → -value；scale/shear 不动；
              deform 顶点位移的 x 取负（4.3 在 animations.<名>.attachments.<皮肤>.
              <槽位>.<附件>.deform[]，3.8 在 animations.<名>.deform[] 两级都认）；
              slots（附件切换）/ drawOrder（层序）**语义上不需要镜像**，保持原样
              （附件名不变、镜像不改变相对深度关系）

边界（遇到就报错退出，别静默产出错数据）：
  - constraints（ik/transform/path…）：方向性参数翻转规则未实现（全库 64/105 包含 IK，
    遇到换包或先解 IK 再翻——见 Spine图集修复通用经验.md §9.6/§15）
  - path/point/boundingbox/clipping 附件：不翻转（点/框不镜像——point 附件其实该翻 x，
    但本批包没有用于视觉的，遇到了按需补）

自检（--check）：镜像两次 = 恒等（bones/attachments/animations 数值回原文）。
朝向的语义验证（翻转后是不是真的朝右）不在脚本里——用 render_rig.py 渲染后 agent 看图判。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SKIP_ATTACHMENT_TYPES = {"point", "boundingbox", "clipping", "path"}


def load_skeleton_json(pkg: Path) -> tuple[dict, Path]:
    if pkg.is_dir():
        for jf in sorted(pkg.glob("*.json")):
            try:
                doc = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if isinstance(doc, dict) and "bones" in doc and "skeleton" in doc:
                return doc, jf
        raise SystemExit(f"[!] {pkg} 下找不到骨架 json")
    return json.loads(pkg.read_text(encoding="utf-8")), pkg


def flip_bones(doc: dict) -> int:
    for b in doc.get("bones", []):
        if "x" in b:
            b["x"] = -b["x"]
        if "rotation" in b:
            b["rotation"] = -b["rotation"]
    return len(doc.get("bones", []))


def flip_attachment(att: dict, warnings: list[str], ctx: str) -> None:
    atype = att.get("type", "region")
    if atype in SKIP_ATTACHMENT_TYPES:
        warnings.append(f"{ctx}: 跳过类型 {atype}")
        return
    # 位移/旋转字段（region 与 mesh 都有）
    if "x" in att:
        att["x"] = -att["x"]
    if "rotation" in att:
        att["rotation"] = -att["rotation"]
    if atype == "region":
        if "scaleX" in att:
            att["scaleX"] = -att["scaleX"]
        else:
            att["scaleX"] = -1.0
        return
    if atype in ("mesh", "linkedmesh"):
        # linkedmesh 没有自己的顶点（共享父网格），只翻位移字段
        verts = att.get("vertices")
        uvs = att.get("uvs")
        if verts and uvs and len(verts) != len(uvs):
            # 加权格式：[骨数, [骨索引, x, y, 权重]×n ...]
            # 每骨段 4 个值：索引(不动)、x(取负)、y(不动)、权重(不动)
            i = 0
            while i < len(verts):
                n = int(verts[i]); i += 1
                for _ in range(n):
                    i += 1  # 骨索引
                    verts[i] = -verts[i]  # x 取负
                    i += 3  # 跳过 x、y、权重 → 下一段骨索引位
        elif verts:
            for i in range(0, len(verts), 2):
                verts[i] = -verts[i]
        tris = att.get("triangles")
        if tris:
            att["triangles"] = [t for tri in
                                [tris[i:i + 3] for i in range(0, len(tris), 3)]
                                for t in (tri[0], tri[2], tri[1])]
        return
    warnings.append(f"{ctx}: 未知附件类型 {atype}，未翻转")


def _flip_deform_vertices(verts: list) -> list:
    """deform 顶点是 (x, y) 偏移对，镜像只取负 x（y 不动）。"""
    out = list(verts)
    for i in range(0, len(out), 2):
        out[i] = -out[i]
    return out


def flip_animations(doc: dict, warnings: list[str]) -> int:
    n = 0
    for aname, anim in doc.get("animations", {}).items():
        n += 1
        for bname, tracks in anim.get("bones", {}).items():
            for ch, keys in tracks.items():
                if not isinstance(keys, list):
                    continue
                for k in keys:
                    if ch == "rotate" and "value" in k:
                        k["value"] = -k["value"]
                    elif ch == "translate" and "x" in k:
                        k["x"] = -k["x"]
                    # scale/shear 不动
        # deform（网格顶点位移）必须镜像 x，否则形变会歪向错的一侧。
        # 4.3：animations.<名>.attachments.<皮肤>.<槽位>.<附件>.deform[]
        # 3.8：animations.<名>.deform.<皮肤>.<槽位>.<附件>[]
        for top in ("attachments", "deform"):
            bucket = anim.get(top)
            if not isinstance(bucket, dict):
                continue
            for skin_name, slots in bucket.items():
                if not isinstance(slots, dict):
                    continue
                for slot_name, atts in slots.items():
                    if not isinstance(atts, dict):
                        continue
                    for att_name, att in atts.items():
                        if not isinstance(att, dict):
                            continue
                        tracks = att.get("deform")
                        if not isinstance(tracks, list):
                            continue
                        for kf in tracks:
                            if isinstance(kf, dict) and isinstance(kf.get("vertices"), list):
                                kf["vertices"] = _flip_deform_vertices(kf["vertices"])
        # 其余顶层通道：
        #   slots（attachment 切换）/ drawOrder（层序偏移）**语义上不需要镜像**——
        #   附件名不变、镜像不改变相对深度关系，保持原样是正确的。
        #   别的通道（events/两色 tint…）原样保留并告警。
        for top in anim:
            if top in ("bones", "attachments", "deform", "slots", "drawOrder"):
                continue
            warnings.append(f"动画 {aname}: 顶层通道 {top} 原样保留（未镜像）")
    return n


def flip_doc(doc: dict) -> tuple[dict, list[str]]:
    out = json.loads(json.dumps(doc))  # 深拷贝
    warnings: list[str] = []
    cons = out.get("constraints", [])
    if cons:
        types = sorted({c.get("type", "?") for c in cons})
        raise SystemExit(f"[!] 包含 constraints {types}，翻转规则未实现，拒绝产出（换包或先解 IK）")
    nb = flip_bones(out)
    na = 0
    for skin in out.get("skins", []):
        for slot, atts in skin.get("attachments", {}).items():
            for name, att in atts.items():
                flip_attachment(att, warnings, f"{slot}/{name}")
                na += 1
    nan = flip_animations(out, warnings)
    # skeleton 段的 x/width（若存在）也镜像
    sk = out.get("skeleton", {})
    if "x" in sk and "width" in sk:
        sk["x"] = -(sk["x"] + sk["width"])
    report = {"bones": nb, "attachments": na, "animations": nan}
    return out, warnings, report


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Spine 包水平镜像（换朝向）")
    ap.add_argument("pkg", help="包目录或骨架 json")
    ap.add_argument("-o", "--out", required=True, help="输出目录（不动原包）")
    ap.add_argument("--check", action="store_true", help="镜像两次回原文的数学自检")
    ap.add_argument("--from", dest="frm", choices=["left", "right"],
                    help="输入包当前朝向（由 agent 看复原预览图判定；与 --to 成对使用）")
    ap.add_argument("--to", dest="to", choices=["left", "right"],
                    help="目标朝向；与 --from 相同则不镜像、直接原样输出")
    ap.add_argument("--detect", action="store_true",
                    help="只打印眼骨启发式的朝向线索（仅 17/105 包有眼骨，仅作参考）后退出")
    args = ap.parse_args(argv[1:])

    doc, json_path = load_skeleton_json(Path(args.pkg))

    if args.detect:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from anim_retarget import detect_facing
        except Exception as e:  # pragma: no cover
            raise SystemExit(f"[!] 无法加载 detect_facing：{e}")
        det, conf, reason = detect_facing(doc)
        print(f"[detect] {json_path.parent.name}: {det} (置信度 {conf}) — {reason}")
        return 0

    # 方向配置：--from/--to 成对给出时按声明决定翻不翻；否则默认翻一次
    if bool(args.frm) != bool(args.to):
        raise SystemExit("[!] --from 与 --to 必须成对给出，例如 --from right --to left")
    if args.frm and args.to:
        do_flip = args.frm != args.to
        print(f"[dir] 声明：输入={args.frm} → 目标={args.to} ⇒ "
              f"{'镜像一次' if do_flip else '原样输出（不镜像）'}")
    else:
        do_flip = True
        print("[dir] 未给 --from/--to：默认镜像一次"
              "（要按方向配置就写 --from <当前朝向> --to <目标朝向>）")

    flipped, warnings, report = flip_doc(doc)
    if do_flip:
        print(f"[flip] bones={report['bones']} attachments={report['attachments']} "
              f"animations={report['animations']}")
    for w in warnings:
        if do_flip:
            print(f"       ⚠ {w}")

    if args.check:
        twice, _, _ = flip_doc(flipped)

        def norm(o):
            """归一化：浮点等值（1 vs 1.0）与缺省 scaleX 视为等价。
            镜像会给原本没写 scaleX 的 region 补上 scaleX=-1，翻回来是 1.0，
            和原文「没写」语义相同，不应判为不一致。"""
            if isinstance(o, dict):
                o = {k: norm(v) for k, v in o.items()}
                if "scaleX" in o and o["scaleX"] == 1:
                    del o["scaleX"]
                return o
            if isinstance(o, list):
                return [norm(v) for v in o]
            if isinstance(o, float) and o == int(o):
                return int(o)
            return o

        same = json.dumps(norm(twice), sort_keys=True) == json.dumps(
            norm(json.loads(json.dumps(doc))), sort_keys=True)
        print(f"[check] 镜像两次回原文: {'✅' if same else '❌ 不一致！'}")
        if not same:
            return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_doc = flipped if do_flip else doc
    (out_dir / json_path.name).write_text(
        json.dumps(out_doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for f in json_path.parent.glob("*.atlas"):
        shutil.copy2(f, out_dir / f.name)
    for f in json_path.parent.glob("*.png"):
        if not f.name.startswith("复原预览图"):
            shutil.copy2(f, out_dir / f.name)
    print(f"[out] {out_dir / json_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
