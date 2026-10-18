#!/usr/bin/env python3
"""只读：按 mm 矩形导出某页的标签/导线/结点/文字/元件（辅助布局排查，不写任何 .kicad_* 文件）。

用法：
  python tools/sch_region.py <sheet.kicad_sch> --x0 180 --y0 230 --x1 230 --y1 260

输出：标签(名称/类型/旋转/锚点)、导线线段、结点、文字注释、元件(位号/值/旋转/中心)。
纯读取，用于确认“标签是否在导线端点/引脚端点上”。
"""
from __future__ import annotations

import argparse
import re

LABEL_RE = re.compile(
    r'\((label|global_label|hierarchical_label)\s+"((?:[^"\\]|\\.)*)"\s*(.*?)\n\t\)', re.S
)
AT_RE = re.compile(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s*(-?[\d.]+)?")
WIRE_RE = re.compile(r"\(wire\s*\(pts\s*\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s*\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s*\)")
JUNC_RE = re.compile(r"\(junction\s*\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\)")
TEXT_RE = re.compile(r'\(text\s+"((?:[^"\\]|\\.)*)"\s*\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s*(-?[\d.]+)?')
SYM_RE = re.compile(r'\n\t\(symbol\s*\(lib_id\s+"([^"]+)"\)\s*\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s*(-?[\d.]+)?\)(.*?)\n\t\)\n', re.S)
REF_RE = re.compile(r'\(property\s+"Reference"\s+"([^"]*)"')
VAL_RE = re.compile(r'\(property\s+"Value"\s+"([^"]*)"')


def inside(x, y, box):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--x0", type=float, required=True)
    ap.add_argument("--y0", type=float, required=True)
    ap.add_argument("--x1", type=float, required=True)
    ap.add_argument("--y1", type=float, required=True)
    a = ap.parse_args()
    raw = open(a.sheet, "r", encoding="utf-8", errors="replace").read()
    box = (a.x0, a.y0, a.x1, a.y1)

    print(f"--- labels in {box} ---")
    for m in LABEL_RE.finditer(raw):
        body = m.group(3)
        at = AT_RE.search(body)
        if not at:
            continue
        x, y, rot = float(at.group(1)), float(at.group(2)), at.group(3) or "0"
        if inside(x, y, box):
            print(f"  {m.group(1):18s} {m.group(2):22s} at ({x}, {y}) rot {rot}")
    print(f"--- wires in {box} ---")
    for m in WIRE_RE.finditer(raw):
        x1, y1, x2, y2 = (float(m.group(i)) for i in range(1, 5))
        if inside(x1, y1, box) or inside(x2, y2, box):
            print(f"  ({x1}, {y1}) -> ({x2}, {y2})")
    print(f"--- junctions ---")
    for m in JUNC_RE.finditer(raw):
        x, y = float(m.group(1)), float(m.group(2))
        if inside(x, y, box):
            print(f"  ({x}, {y})")
    print(f"--- free texts ---")
    for m in TEXT_RE.finditer(raw):
        x, y = float(m.group(2)), float(m.group(3))
        if inside(x, y, box):
            print(f"  '{m.group(1)}' at ({x}, {y}) rot {m.group(4)}")
    print(f"--- symbols (centre in box) ---")
    for m in SYM_RE.finditer(raw):
        x, y = float(m.group(2)), float(m.group(3))
        if inside(x, y, box):
            ref = REF_RE.search(m.group(5))
            val = VAL_RE.search(m.group(5))
            print(f"  {(ref.group(1) if ref else '?'):10s} {m.group(1):34s} ({x}, {y}) rot {m.group(4)}  value={val.group(1) if val else '?'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
