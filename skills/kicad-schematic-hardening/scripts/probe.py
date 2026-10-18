#!/usr/bin/env python3
"""只读探查工具（不修改任何 .kicad_* 文件）。

子命令：
  texts   --svg <svg> [--x0 X --y0 Y --x1 X --y1 Y]
          列出 SVG 中（含旋转）文本包围盒，可按区域过滤；复用 overlap_check.parse_svg。
  fields  --sch <kicad_sch> --refs R96,R97
          列出指定位号字段的存档坐标。
  labels  --sch <kicad_sch> [--near x,y --r 20]
          列出 label / global_label / hierarchical_label 及自由 text 的坐标。
  wires   --sch <kicad_sch> [--near x,y --r 20]
          列出导线段。
  syms    --sch <kicad_sch> [--near x,y --r 20]
          列出符号位号/值/坐标/旋转。
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overlap_check as oc  # noqa: E402  只读复用


def _blocks(raw: str, head: str):
    for m in re.finditer(r"\(" + re.escape(head) + r"\b", raw):
        start = m.start()
        depth = 0
        i = start
        inq = False
        while i < len(raw):
            c = raw[i]
            if inq:
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    inq = False
            else:
                if c == '"':
                    inq = True
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        yield start, i + 1
                        break
            i += 1


def _at(blk: str):
    m = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)", blk)
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)), float(m.group(3) or 0.0))


def _within(at, near, r):
    if not near:
        return True
    if at is None:
        return False
    return math.hypot(at[0] - near[0], at[1] - near[1]) <= r


def cmd_texts(a):
    boxes = oc.parse_svg(a.svg)
    rows = []
    for b in boxes:
        x0, y0, x1, y1 = b.box()
        if a.x0 is not None and x1 < a.x0:
            continue
        if a.x1 is not None and x0 > a.x1:
            continue
        if a.y0 is not None and y1 < a.y0:
            continue
        if a.y1 is not None and y0 > a.y1:
            continue
        rows.append((y0, x0, b))
    rows.sort(key=lambda r: (r[0], r[1]))
    for _, _, b in rows:
        print(f"{b.kind:11s} {b.text[:40]!r:44s} box={b.box()} ang={b.angle:g} anchor={b.anchor}")


def cmd_fields(a):
    raw = open(a.sch, encoding="utf-8").read()
    want = {r.strip() for r in a.refs.split(",") if r.strip()}
    for s, e in _blocks(raw, "symbol"):
        blk = raw[s:e]
        m = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', blk)
        if not m or m.group(1) not in want:
            continue
        print(f"--- {m.group(1)}")
        at = _at(blk)
        print(f"    symbol at=(%.3f,%.3f) rot=%g" % at if at else "    symbol at=?")

        for pm in re.finditer(r'\(property\s+"([^"]+)"\s+"([^"]*)"\s*(.*?)\)\s*(?=\(property|\(pin|\Z)',
                              blk, re.S):
            name, val, rest = pm.group(1), pm.group(2), pm.group(3)
            pat = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)", rest)
            just = re.search(r"\(justify\s+([^)]*)\)", rest)
            hide = "hide" in rest
            if pat:
                print(f"    {name:12s} = {val[:18]!r:22s} at=({pat.group(1)},{pat.group(2)})"
                      f" rot={pat.group(3)} justify={just.group(1) if just else '-'}"
                      f" hide={hide}")


LABEL_KINDS = ("label", "global_label", "hierarchical_label", "text")


def cmd_labels(a):
    raw = open(a.sch, encoding="utf-8").read()
    rows = []
    for kind in LABEL_KINDS:
        for s, e in _blocks(raw, kind):
            blk = raw[s:e]
            m = re.match(r'\(\s*' + kind + r'\s+"((?:[^"\\]|\\.)*)"', blk)
            if not m:
                continue
            at = _at(blk)
            just = re.search(r"\(justify\s+([^)]*)\)", blk)
            rows.append((at, kind, m.group(1), just.group(1) if just else "-", s))
    rows.sort(key=lambda r: (r[0][1] if r[0] else 0, r[0][0] if r[0] else 0))
    for at, kind, txt, just, s in rows:
        if not _within(at, a.near, a.r):
            continue
        print(f"{kind:20s} {txt[:44]!r:48s} at=({at[0]:.2f},{at[1]:.2f}) rot={at[2]:g} justify={just}")


def cmd_wires(a):
    raw = open(a.sch, encoding="utf-8").read()
    rows = []
    for s, e in _blocks(raw, "wire"):
        blk = raw[s:e]
        pts = re.findall(r"\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)", blk)
        if len(pts) < 2:
            continue
        p = [(float(x), float(y)) for x, y in pts]
        rows.append(p)
    for p in sorted(rows, key=lambda p: (p[0][1], p[0][0])):
        if a.near:
            (x1, y1), (x2, y2) = p[0], p[1]
            dx, dy = x2 - x1, y2 - y1
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((a.near[0] - x1) * dx + (a.near[1] - y1) * dy) / L2))
            px, py = x1 + t * dx, y1 + t * dy
            if math.hypot(px - a.near[0], py - a.near[1]) > a.r:
                continue
        print(f"wire ({p[0][0]:.2f},{p[0][1]:.2f}) -> ({p[1][0]:.2f},{p[1][1]:.2f})")


def cmd_syms(a):
    raw = open(a.sch, encoding="utf-8").read()
    for s, e in _blocks(raw, "symbol"):
        blk = raw[s:e]
        mr = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', blk)
        mv = re.search(r'\(property\s+"Value"\s+"([^"]*)"', blk)
        ml = re.search(r'\(lib_id\s+"([^"]*)"', blk)
        at = _at(blk)
        if not mr or at is None:
            continue
        if not _within(at, a.near, a.r):
            continue
        print(f"{mr.group(1):8s} {ml.group(1) if ml else '?':34s} at=({at[0]:.2f},{at[1]:.2f})"
              f" rot={at[2]:g} value={mv.group(1)[:14] if mv else '?'}")


def cmd_raw(a):
    raw = open(a.sch, encoding="utf-8").read()
    for s, e in _blocks(raw, a.kind):
        blk = raw[s:e]
        if a.needle in blk:
            print(blk[:1200])
            print("---")
            if not a.all:
                return


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("texts")
    t.add_argument("--svg", required=True)
    for k in ("x0", "y0", "x1", "y1"):
        t.add_argument("--" + k, type=float, default=None)
    t.set_defaults(fn=cmd_texts)

    f = sub.add_parser("fields")
    f.add_argument("--sch", required=True)
    f.add_argument("--refs", required=True)
    f.set_defaults(fn=cmd_fields)

    for name, fn in (("labels", cmd_labels), ("wires", cmd_wires), ("syms", cmd_syms)):
        p = sub.add_parser(name)
        p.add_argument("--sch", required=True)
        p.add_argument("--near", default=None)
        p.add_argument("--r", type=float, default=20.0)
        p.set_defaults(fn=fn)

    r = sub.add_parser("raw")
    r.add_argument("--sch", required=True)
    r.add_argument("--kind", required=True)
    r.add_argument("--needle", required=True)
    r.add_argument("--all", action="store_true")
    r.set_defaults(fn=cmd_raw)

    a = ap.parse_args()
    if getattr(a, "near", None):
        a.near = tuple(float(v) for v in a.near.split(","))
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
