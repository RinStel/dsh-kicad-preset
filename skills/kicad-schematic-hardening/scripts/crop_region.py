#!/usr/bin/env python3
"""按 KiCad 原理图 mm 坐标裁剪渲染图（辅助排查工具，不参与验收）。

用法：
  python tools/crop_region.py <png> <x0> <y0> <x1> <y1> <out.png> [--page-w 419.989] [--page-h 297.0022] [--scale 3]

原理：render_schematic_png 的输出与页面尺寸等比，px/mm = width_px / page_w_mm。
--scale 只放大输出（最近邻→LANCZOS），不改变几何关系。
"""
from __future__ import annotations

import argparse
from PIL import Image


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("png")
    ap.add_argument("x0", type=float)
    ap.add_argument("y0", type=float)
    ap.add_argument("x1", type=float)
    ap.add_argument("y1", type=float)
    ap.add_argument("out")
    ap.add_argument("--page-w", type=float, default=419.9890)
    ap.add_argument("--page-h", type=float, default=297.0022)
    ap.add_argument("--scale", type=float, default=2.0)
    a = ap.parse_args()

    im = Image.open(a.png)
    W, H = im.size
    sx, sy = W / a.page_w, H / a.page_h
    left, top = int(a.x0 * sx), int(a.y0 * sy)
    right, bottom = int(a.x1 * sx), int(a.y1 * sy)
    left, top = max(0, left), max(0, top)
    right, bottom = min(W, right), min(H, bottom)
    crop = im.crop((left, top, right, bottom))
    if a.scale != 1.0:
        crop = crop.resize(
            (int(crop.width * a.scale), int(crop.height * a.scale)),
            Image.LANCZOS,
        )
    crop.save(a.out)
    print(f"{a.out} {crop.width}x{crop.height} px  from {a.png} ({W}x{H}, {sx:.4f} px/mm)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
