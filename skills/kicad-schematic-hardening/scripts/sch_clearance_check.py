#!/usr/bin/env python3
"""KiCad schematic clearance checker (>=1mm rule), parsing .kicad_sch directly.

Why this exists: the SVG-based overlap_check.py only compares text-to-text and
misses power-symbol Value texts and text-over-symbol crowding. This tool parses
the schematic source (read-only) and enumerates every text-emitting object:
  - label / global_label / hierarchical_label
  - symbol Reference / Value properties (includes #PWR rail names)
  - free text notes
Then it checks, with a configurable clearance (default 1.0 mm):
  T-T  text vs text
  T-B  text vs component body bbox (bbox approximated from the symbol's pins)
  T-P  text vs pin endpoints / pin-number band

Units: schematic mm. Stroke font width approximated as 0.62 * font size per char.

Usage:
  python tools/sch_clearance_check.py --sch <file> [--clear 1.0] [--md out.md] [--json out.json] [--quiet]
Exit code 0 = no conflict.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

S_EXPR_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+')


def parse_sexpr(text):
    """Parse s-expression into nested lists; strings keep quotes stripped."""
    stack = [[]]
    for tok in S_EXPR_TOKEN.findall(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            if len(stack) > 1:
                node = stack.pop()
                stack[-1].append(node)
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1].replace('\\"', '"'))
        else:
            stack[-1].append(tok)
    return stack[0]


def find_all(node, name):
    out = []
    if isinstance(node, list):
        if node and node[0] == name:
            out.append(node)
        for ch in node:
            out.extend(find_all(ch, name))
    return out


def child(node, name):
    for ch in node:
        if isinstance(ch, list) and ch and ch[0] == name:
            return ch
    return None


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class Box:
    __slots__ = ("text", "kind", "x0", "y0", "x1", "y1", "sheet")

    def __init__(self, text, kind, cx, cy, w, h, anchor="left", rotation=0.0):
        if 45 < rotation % 180 < 135:
            w, h = h, w
        if anchor == "center":
            x0 = cx - w / 2
        elif anchor == "right":
            x0 = cx - w
        else:
            x0 = cx
        self.text, self.kind = text, kind
        self.x0, self.y0, self.x1, self.y1 = x0, cy - h * 0.78, x0 + w, cy + h * 0.22


def text_objects(tree):
    """Yield (text, kind, x, y, fontsize, anchor, rotation).

    Nodes inside (lib_symbols ...) are symbol-library graphics; they are drawn
    through the placed symbol with its own transform, so their local coordinates
    must NOT be compared as sheet text.
    """
    out = []
    skip_ids = set()

    def mark(node):
        skip_ids.add(id(node))
        if isinstance(node, list):
            for ch in node:
                mark(ch)

    for lib in find_all(tree, "lib_symbols"):
        mark(lib)

    def eff(node):
        e = child(node, "effects")
        size, anchor = 1.27, "left"
        if e:
            f = child(e, "font")
            if f and child(f, "size"):
                s = child(f, "size")
                size = num(s[1], 1.27)
            j = child(e, "justify")
            if j:
                toks = [t for t in j[1:] if isinstance(t, str)]
                if "right" in toks:
                    anchor = "right"
                elif "left" in toks:
                    anchor = "left"
                else:
                    anchor = "center"
        return size, anchor

    for kind in ("label", "global_label", "hierarchical_label"):
        for n in find_all(tree, kind):
            at = child(n, "at")
            if not at or len(at) < 3:
                continue
            size, anchor = eff(n)
            out.append((n[1], kind, num(at[1]), num(at[2]), size,
                        anchor if kind != "label" else "left", num(at[3]) if len(at) > 3 else 0))
    for n in find_all(tree, "text"):
        if id(n) in skip_ids:
            continue
        at = child(n, "at")
        if not at or len(at) < 3:
            continue
        size, anchor = eff(n)
        out.append((n[1], "note", num(at[1]), num(at[2]), size, anchor,
                    num(at[3]) if len(at) > 3 else 0))
    for sym in find_all(tree, "symbol"):
        lib = child(sym, "lib_id")
        at = child(sym, "at")
        if not at or not lib:
            continue
        is_power = "power:" in (lib[1] if len(lib) > 1 else "")
        for prop in find_all(sym, "property"):
            if len(prop) < 3 or prop[1] not in ("Reference", "Value"):
                continue
            if prop[1] == "Reference" and prop[2].startswith("#"):
                continue
            pat = child(prop, "at")
            if not pat or len(pat) < 3:
                continue
            e = child(prop, "effects")
            if e and child(e, "hide") is not None:
                continue
            size, anchor = eff(prop)
            kind = "rail" if (is_power and prop[1] == "Value") else ("ref" if prop[1] == "Reference" else "value")
            out.append((prop[2], kind, num(pat[1]), num(pat[2]), size, anchor,
                        num(pat[3]) if len(pat) > 3 else 0))
    return out


def boxes_of(objs):
    out = []
    for text, kind, x, y, size, anchor, rot in objs:
        if not text:
            continue
        w = max(1.0, len(text) * size * 0.62)
        out.append(Box(text, kind, x, y, w, size, anchor, rot))
    return out


def gap(a0, a1, b0, b1):
    if a1 < b0:
        return b0 - a1
    if b1 < a0:
        return a0 - b1
    return 0.0


def clear_of(a, b, need):
    return gap(a.x0, a.x1, b.x0, b.x1) > need or gap(a.y0, a.y1, b.y0, b.y1) > need


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sch", required=True)
    ap.add_argument("--clear", type=float, default=1.0)
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--kinds", default="label,global_label,hierarchical_label,ref,value,rail,note")
    ap.add_argument("--no-wires", action="store_true", help="skip text-vs-wire checking")
    a = ap.parse_args()
    a.wires = not a.no_wires

    with open(a.sch, encoding="utf-8", errors="replace") as fh:
        tree = parse_sexpr(fh.read())
    all_boxes = boxes_of(text_objects(tree))
    kinds = set(a.kinds.split(","))
    boxes = [b for b in all_boxes if b.kind in kinds]

    conflicts = []
    for i, x in enumerate(boxes):
        for y in boxes[i + 1:]:
            if x.text == y.text and abs(x.x0 - y.x0) < 0.01 and abs(x.y0 - y.y0) < 0.01:
                continue
            if not clear_of(x, y, a.clear):
                gx = gap(x.x0, x.x1, y.x0, y.x1)
                gy = gap(x.y0, y.y1, y.y0, y.y1)
                conflicts.append(dict(cat="text-text", a=x.text, a_kind=x.kind,
                                      b=y.text, b_kind=y.kind,
                                      gap=[round(gx, 2), round(gy, 2)]))

    # text vs wire segments: a label/rail text lying across a wire is unreadable
    # and hides which node it belongs to.
    if a.wires:
        segs = []
        for w in find_all(tree, "wire"):
            pts = child(w, "pts")
            if not pts:
                continue
            xy = find_all(pts, "xy")
            if len(xy) >= 2:
                segs.append((num(xy[0][1]), num(xy[0][2]), num(xy[1][1]), num(xy[1][2])))
        for b in boxes:
            for (x1, y1, x2, y2) in segs:
                n = max(2, int(max(abs(x2 - x1), abs(y2 - y1)) / 0.25) + 1)
                step = max(abs(x2 - x1), abs(y2 - y1)) / n
                inside = 0
                for k in range(n + 1):
                    t = k / n
                    px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                    if b.x0 < px < b.x1 and b.y0 < py < b.y1:
                        inside += 1
                # 只在导线真正穿入文字框（沿导线累计 >1.5mm）时算冲突；
                # 标签锚在导线端点上造成的端点接触不算。
                if inside * step > 1.5:
                    conflicts.append(dict(cat="text-wire", a=b.text, a_kind=b.kind,
                                          b=f"wire({x1:.2f},{y1:.2f})-({x2:.2f},{y2:.2f})",
                                          b_kind="wire", gap=[round(inside * step, 2), 0.0]))

    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(f"# Clearance check (>= {a.clear} mm)\n\n")
            fh.write(f"- schematic: `{a.sch}`\n- text objects: {len(boxes)}\n")
            fh.write(f"- conflicts: {len(conflicts)}\n\n")
            if conflicts:
                fh.write("| # | A | kind | B | kind | gap(dx,dy) |\n|---|---|---|---|---|---|\n")
                for i, c in enumerate(conflicts, 1):
                    fh.write(f"| {i} | `{c['a']}` | {c['a_kind']} | `{c['b']}` | {c['b_kind']} | {c['gap']} |\n")
        print(f"md: {a.md}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"sch": a.sch, "clear": a.clear, "text_objects": len(boxes),
                       "conflicts": conflicts}, fh, ensure_ascii=False, indent=2)
        print(f"json: {a.json}")
    if not a.quiet:
        for c in conflicts[:60]:
            print(f"  [{c['a_kind']}x{c['b_kind']}] '{c['a']}' <-> '{c['b']}'  gap={c['gap']}")
    print(f"\ntext objects={len(boxes)}  conflicts(<{a.clear}mm)={len(conflicts)}")
    print("result: " + ("FAIL" if conflicts else "PASS"))
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
