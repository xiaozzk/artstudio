"""006 视图镜像：把一张视图水平镜像成它的「另一侧」版本（**本地操作，不消耗额度**）。

用途：转身图里「另一侧」不必再花一次生成 —— 直接拿已有视图镜像（对称角色足够用；
左右不对称的配饰/武器/惯用手会被镜像翻转，别用在那种件上）。

用法（**工作区根**执行）：

    python task/006-poly-multiview-tpose/scripts/mirror_view.py \
        --src task/006-poly-multiview-tpose/output/base-model-tpose-4view-v2/views/three_quarter.png \
        --out task/006-poly-multiview-tpose/output/base-model-tpose-4view-v3/views/left.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="源视图 PNG")
    ap.add_argument("--out", required=True, help="输出 PNG（水平镜像）")
    args = ap.parse_args()

    src = Path(args.src).resolve()
    dst = Path(args.out).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    im = Image.open(src)
    out = im.transpose(Image.FLIP_LEFT_RIGHT)
    out.save(dst)
    print(f"mirrored {src.name} {im.size} {im.mode} -> {dst} {out.size}")


if __name__ == "__main__":
    main()
