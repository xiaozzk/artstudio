# -*- coding: utf-8 -*-
"""
将图片统一缩放到 1024x1024，保留人物比例不变。

策略:
1. 自动检测非背景内容包围盒 (基于透明度或四角背景色), 裁掉空边
2. 按比例 (最长边 = 1024) 缩放, 不做拉伸 -> 人物比例保持不变
3. 居中粘贴到 1024x1024 透明画布

输入/输出目录通过命令行参数控制, 默认:
  INPUT_DIR  = 当前目录
  OUTPUT_DIR = 当前目录/resized
"""
import os
import sys
import numpy as np
from PIL import Image

TARGET_SIZE = 1024


def detect_background_color(rgb: np.ndarray) -> np.ndarray:
    """从图像四角采样, 取中位数作为背景色."""
    h, w = rgb.shape[:2]
    corners = np.concatenate([
        rgb[0:5, :].reshape(-1, 3),
        rgb[-5:, :].reshape(-1, 3),
        rgb[:, 0:5].reshape(-1, 3),
        rgb[:, -5:].reshape(-1, 3),
    ])
    return np.median(corners, axis=0).astype(int)


def get_content_bbox(img: Image.Image):
    """
    返回 (left, top, right, bottom), 即非背景像素的最小包围盒.
    优先用 alpha 通道; 无 alpha 时按四角背景色差异判定.
    """
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    alpha = arr[:, :, 3]

    if alpha.min() < 250:
        # 有透明区域: 透明像素视为背景
        mask = alpha > 8
    else:
        rgb = arr[:, :, :3]
        bg = detect_background_color(rgb)
        diff = np.abs(rgb.astype(int) - bg).sum(axis=2)
        mask = diff > 30  # 与背景明显不同的像素

    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        return 0, 0, img.width, img.height

    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    return int(cmin), int(rmin), int(cmax + 1), int(rmax + 1)


def resize_preserve_aspect(img: Image.Image) -> Image.Image:
    """按最长边 1024 等比缩放, 不改变宽高比."""
    w, h = img.size
    scale = TARGET_SIZE / max(w, h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return img.resize((new_w, new_h), Image.LANCZOS)


def process_one(src_path: str, dst_path: str) -> dict:
    img = Image.open(src_path)
    original_size = img.size

    bbox = get_content_bbox(img)
    cropped = img.crop(bbox)

    # 缩放, 保持比例
    resized = resize_preserve_aspect(cropped)
    rw, rh = resized.size

    # 创建 1024x1024 透明画布, 居中粘贴
    canvas = Image.new("RGBA", (TARGET_SIZE, TARGET_SIZE), (0, 0, 0, 0))
    paste_x = (TARGET_SIZE - rw) // 2
    paste_y = (TARGET_SIZE - rh) // 2

    if resized.mode != "RGBA":
        resized = resized.convert("RGBA")
    canvas.alpha_composite(resized, dest=(paste_x, paste_y))

    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    canvas.save(dst_path)

    return {
        "src": src_path,
        "dst": dst_path,
        "original_size": original_size,
        "crop_bbox": bbox,
        "resized_content": (rw, rh),
        "final_canvas": (TARGET_SIZE, TARGET_SIZE),
        "paste_offset": (paste_x, paste_y),
    }


# 基于站位的新文件名 (英文, 仅描述站位)
RENAMES = {
    "01_image-1786891552998-yvaer35c8v.png": "01_front_centered.png",
    "02_image-1786891707684-pjnycl89p9.png": "02_chibi_front_centered.png",
    "03_image-1786891812660-gasonjbl3ow.png": "03_left_side_centered.png",
    "04_image-1786891893835-2b0d48g1zps.png": "04_back_centered.png",
}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    input_dir = sys.argv[1] if len(sys.argv) > 1 else here
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "resized")
    os.makedirs(output_dir, exist_ok=True)

    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print("-" * 70)

    for old_name, new_name in RENAMES.items():
        src = os.path.join(input_dir, old_name)
        dst = os.path.join(output_dir, new_name)
        if not os.path.exists(src):
            print(f"[跳过] 源文件不存在: {src}")
            continue

        info = process_one(src, dst)
        print(f"[OK] {old_name}")
        print(f"     -> {new_name}")
        print(f"     原始尺寸: {info['original_size']}")
        print(f"     裁剪包围盒: {info['crop_bbox']}")
        print(f"     缩放后人物: {info['resized_content']}  (比例保持不变)")
        print(f"     画布尺寸:   {info['final_canvas']}")
        print(f"     居中偏移:   {info['paste_offset']}")
        print("-" * 70)


if __name__ == "__main__":
    main()