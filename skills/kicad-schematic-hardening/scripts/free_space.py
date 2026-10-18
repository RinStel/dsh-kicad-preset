#!/usr/bin/env python3
"""在导出的 SVG 文本盒中搜索空闲位置（只读）。

用法：
  python tools/free_space.py --svg <svg> --w 4 --h 1.7 --x0 100 --y0 34 --x1 120 --y1 48 \
      [--step 0.5] [--margin 0.6] [--top 12] [--ignore R96,1MΩ] [--exclude-kinds pin_name,pin_number]

输出：按"冲突度"升序的候选左上角 (x0,y0)，并列出最近的 3 个障碍。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overlap_check as oc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--w", type=float, required=True)
    ap.add_argument("--h", type=float, required=True)
    ap.add_argument("--x0", type=float, required=True)
    ap.add_argument("--x1", type=float, required=True)
    ap.add_argument("--y0", type=float, required=True)
    ap.add_argument("--y1", type=float, required=True)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--margin", type=float, default=0.6)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--ignore", default="")
    ap.add_argument("--exclude-kinds", default="pin_name,pin_number")
    ap.add_argument("--grid", type=float, default=None, help="只保留落在该格点上的候选（如 1.27）")
    a = ap.parse_args()

    ign = {t for t in a.ignore.split(",") if t}
    exk = {t for t in a.exclude_kinds.split(",") if t}
    obstacles = []
    for b in oc.parse_svg(a.svg):
        if b.kind in exk or b.text in ign:
            continue
        obstacles.append((b.text, b.kind, b.box()))

    cands = []
    x = a.x0
    while x <= a.x1 - a.w + 1e-9:
        y = a.y0
        while y <= a.y1 - a.h + 1e-9:
            if a.grid is None or (abs((x / a.grid) - round(x / a.grid)) < 0.02
                                  and abs((y / a.grid) - round(y / a.grid)) < 0.02):
                score = 0.0
                hits = []
                for txt, kind, (ox0, oy0, ox1, oy1) in obstacles:
                    px = min(x + a.w, ox1) - max(x, ox0)
                    py = min(y + a.h, oy1) - max(y, oy0)
                    if px > -a.margin and py > -a.margin:
                        pen = min(px + a.margin, py + a.margin)
                        score += max(pen, 0.01)
                        hits.append((pen, txt, kind, (ox0, oy0, ox1, oy1)))
                cands.append((score, round(x, 2), round(y, 2), hits))
            y += a.step
        x += a.step

    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    shown = 0
    last = None
    for score, x, y, hits in cands:
        if score == 0.0:
            if last is not None and abs(last[0] - x) < 5 and abs(last[1] - y) < 1.0:
                continue
            last = (x, y)
        print(f"score={score:7.2f} box=({x},{y})-({round(x + a.w, 2)},{round(y + a.h, 2)})"
              f"  near: " + "; ".join(f"{t[:18]!r}[{k}]" for _, t, k, _ in hits[:3]))
        shown += 1
        if shown >= a.top:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
