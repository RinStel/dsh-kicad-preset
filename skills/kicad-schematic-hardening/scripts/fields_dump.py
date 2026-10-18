#!/usr/bin/env python3
"""只读：列出某页每个符号的 Reference / Value 及其字段坐标（辅助布局排查，不写文件）。

用法：
  python tools/fields_dump.py <sheet.kicad_sch> [--ref R160] [--region x0,y0,x1,y1]

字段文本渲染经验值（KiCad 10 + kicad-cli SVG，1.27mm 字体，左对齐）：
  文本框 x0 = 字段 x,  y0 = 字段 y - 0.7,  y1 = 字段 y + 1.0
"""
from __future__ import annotations

import argparse
import re

AT_RE = re.compile(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?")
PROP_RE = re.compile(r'\(property\s+"(Reference|Value)"\s+"((?:[^"\\]|\\.)*)"\s*')


def blocks(raw: str, head: str) -> list[str]:
    out, i, n = [], 0, len(raw)
    while i < n:
        j = raw.find(head, i)
        if j < 0:
            break
        depth, k = 0, j
        while k < n:
            c = raw[k]
            if c == '"':                      # 跳过字符串
                k += 1
                while k < n and raw[k] != '"':
                    k += 2 if raw[k] == "\\" else 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    out.append(raw[j:k + 1])
                    break
            k += 1
        i = k + 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--ref")
    ap.add_argument("--region", help="x0,y0,x1,y1")
    a = ap.parse_args()
    raw = open(a.sheet, "r", encoding="utf-8", errors="replace").read()
    box = [float(v) for v in a.region.split(",")] if a.region else None

    rows = []
    for blk in blocks(raw, "\n\t(symbol\n"):
        lib = re.search(r'\(lib_id\s+"([^"]+)"', blk)
        sym_at = AT_RE.search(blk)
        if not lib or not sym_at:
            continue
        sx, sy = float(sym_at.group(1)), float(sym_at.group(2))
        fields = {}
        for m in PROP_RE.finditer(blk):
            tail = blk[m.end():m.end() + 120]
            at = AT_RE.search(tail)
            if at:
                fields[m.group(1)] = (m.group(2), float(at.group(1)), float(at.group(2)))
        ref = fields.get("Reference", ("?", 0, 0))
        val = fields.get("Value", ("?", 0, 0))
        row = (ref[0], val[0], sx, sy, ref[1], ref[2], val[1], val[2], lib.group(1))
        if a.ref and row[0] != a.ref:
            continue
        if box:
            inside = any(box[0] <= x <= box[2] and box[1] <= y <= box[3]
                         for x, y in ((sx, sy), (ref[1], ref[2]), (val[1], val[2])))
            if not inside:
                continue
        rows.append(row)

    rows.sort(key=lambda r: (r[1], r[0]))
    print(f"{'ref':9s} {'sym(x,y)':>16s}  {'ref@':>16s}  {'value':16s} {'val@':>16s}")
    for r in rows:
        print(f"{r[0]:9s} ({r[2]:7.2f},{r[3]:7.2f})  ({r[4]:7.2f},{r[5]:6.2f})  "
              f"{r[1]:16s} ({r[6]:7.2f},{r[7]:6.2f})")
    print(f"-- {len(rows)} symbol(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
