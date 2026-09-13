#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webp_to_png.py

将 WebP 图片转换为 PNG, 并缩放到 512×512 像素。
为保证图片中人物比例不变, 采用 "等比缩放 + 居中加白边(画布)" 的方式:
  - 长边适配到 512, 短边保持原始比例 (不会把人物拉变形)
  - 不足 512 的边用纯色背景补齐, 得到一张完整的 512×512 方图

依赖: pip install Pillow

用法:
    python webp_to_png.py FILE [OUTPUT.png]
    python webp_to_png.py DIRECTORY [OUTPUT_DIR]
    python webp_to_png.py DIRECTORY [OUTPUT_DIR] --recursive
"""

import os
import sys
import io
import argparse
from pathlib import Path

# 修复 Windows 下 stdout 默认 GBK 编码导致 emoji 报错的问题
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass

from PIL import Image


# ===== 可调参数 =====
TARGET_SIZE = 512                # 输出画布尺寸 (像素)
PADDING_COLOR = (255, 255, 255)  # 画布填充色: 默认白色
RESAMPLING = Image.LANCZOS       # 高质量重采样, 适合缩放人像
# ===================


def convert_webp_to_png_512(input_path, output_path=None, padding_color=PADDING_COLOR):
    """
    将单个 WebP 图片转换为 512×512 PNG, 保持人物比例不变。

    Args:
        input_path:   输入 WebP 文件路径
        output_path:  输出 PNG 文件路径 (默认: 同目录下同名 .png)
        padding_color: 画布填充色, RGB 元组
    """
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_suffix(".png")
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(input_path) as img:
        # 动画 WebP 取第一帧
        try:
            img.seek(0)
        except Exception:
            pass

        # 统一到 RGBA, 方便后续处理透明通道
        if img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA")
        has_alpha = img.mode in ("RGBA", "LA")

        w, h = img.size
        # 计算等比缩放比例: 取宽度比和高度比的较小值, 保证图能完整放进 512×512
        ratio = min(TARGET_SIZE / w, TARGET_SIZE / h)
        new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))

        # 等比缩放 (人像不会被拉变形)
        resized = img.resize(new_size, RESAMPLING)

        # 新建方形画布
        if has_alpha:
            canvas = Image.new(
                "RGBA",
                (TARGET_SIZE, TARGET_SIZE),
                padding_color + (0,),
            )
        else:
            canvas = Image.new(
                "RGB",
                (TARGET_SIZE, TARGET_SIZE),
                padding_color,
            )

        # 计算居中粘贴的左上角坐标
        paste_x = (TARGET_SIZE - new_size[0]) // 2
        paste_y = (TARGET_SIZE - new_size[1]) // 2

        if resized.mode == "RGBA":
            # 用自身 alpha 作为 mask, 避免透明区域被画布颜色覆盖
            canvas.alpha_composite(resized, dest=(paste_x, paste_y))
        else:
            canvas.paste(resized, (paste_x, paste_y))

        # 保存为 PNG
        save_kwargs = {"format": "PNG", "optimize": True}
        if has_alpha:
            canvas.save(output_path, **save_kwargs)
        else:
            canvas.convert("RGB").save(output_path, **save_kwargs)

        print(f"  ✔ {input_path.name}  ({w}×{h})  ->  {output_path.name}  ({TARGET_SIZE}×{TARGET_SIZE})")


def batch_convert(input_dir, output_dir=None, recursive=False):
    """批量转换目录下的所有 WebP 文件。"""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir) if output_dir else input_dir / "png_512"
    output_dir.mkdir(parents=True, exist_ok=True)

    pattern = "**/*" if recursive else "*"
    webp_files = sorted({
        *input_dir.glob(f"{pattern}.webp"),
        *input_dir.glob(f"{pattern}.WEBP"),
    })
    # 仅保留真实文件
    webp_files = [p for p in webp_files if p.is_file()]

    if not webp_files:
        print(f"❌ 在 {input_dir} 下未找到任何 WebP 文件")
        return

    print(f"📂 共找到 {len(webp_files)} 个 WebP 文件, 开始转换...")
    success, failed = 0, 0
    for webp in webp_files:
        try:
            if recursive:
                rel = webp.relative_to(input_dir)
                out = output_dir / rel.with_suffix(".png")
            else:
                out = output_dir / (webp.stem + ".png")
            convert_webp_to_png_512(webp, out)
            success += 1
        except Exception as e:
            print(f"  ✘ 转换失败: {webp}  ->  {e}")
            failed += 1

    print(f"\n✅ 完成: 成功 {success} 个, 失败 {failed} 个")
    print(f"   输出目录: {output_dir.resolve()}")


def main():
    parser = argparse.ArgumentParser(
        description="将 WebP 转换为 512×512 PNG, 保持人物比例不变",
    )
    parser.add_argument("input", help="输入 WebP 文件或包含 WebP 的目录")
    parser.add_argument("output", nargs="?", help="输出文件或输出目录 (可选)")
    parser.add_argument(
        "--padding",
        type=str,
        default="255,255,255",
        help="画布填充色, RGB 用逗号分隔, 例如 0,0,0 表示黑色 (默认 255,255,255 白色)",
    )
    parser.add_argument(
        "--recursive", "-r", action="store_true", help="递归处理子目录"
    )

    args = parser.parse_args()

    # 解析填充色
    try:
        pad = tuple(int(x) for x in args.padding.split(","))
        if len(pad) != 3 or any(c < 0 or c > 255 for c in pad):
            raise ValueError
    except ValueError:
        print("❌ --padding 必须是三个 0-255 的整数, 用逗号分隔, 例如 0,0,0")
        sys.exit(1)

    if not os.path.exists(args.input):
        print(f"❌ 输入路径不存在: {args.input}")
        sys.exit(1)

    if os.path.isdir(args.input):
        batch_convert(args.input, args.output, recursive=args.recursive)
    else:
        convert_webp_to_png_512(args.input, args.output, padding_color=pad)


if __name__ == "__main__":
    main()
