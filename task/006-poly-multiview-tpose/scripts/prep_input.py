"""006 输入准备：poly 原图 → 合成纯灰底 205 → resize 2048×2048。

原图（005/refs/poly/poly-v5-teal.png）是**透明底** RGBA，透明区 RGB 为黑；
直接喂模型会被读成黑底，故按 meowa 硬约定先合成**纯灰底 205** 再放大到 2K。

用法（**工作区根**执行）：python task/006-poly-multiview-tpose/scripts/prep_input.py
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "task/005-generic-skeleton/refs/poly/poly-v5-teal.png"
DST = ROOT / "task/006-poly-multiview-tpose/input/poly-v5-teal-2048-gray205.png"
BG = (205, 205, 205)
SIZE = 2048


def main() -> None:
    src = Image.open(SRC).convert("RGBA")
    canvas = Image.new("RGBA", src.size, BG + (255,))
    flat = Image.alpha_composite(canvas, src).convert("RGB")
    out = flat.resize((SIZE, SIZE), Image.LANCZOS)
    DST.parent.mkdir(parents=True, exist_ok=True)
    out.save(DST)
    print(f"wrote {DST} {out.size} {out.mode}")


if __name__ == "__main__":
    main()
