#!/usr/bin/env python3
"""EasyEDA Pro .efoo -> KiCad .kicad_mod (pads + courtyard/silk outline).

Scale defaults to 0.0254 mm/unit (= 1 mil), EasyEDA Pro's PCB-domain internal unit.
This was validated on CONN-SMD_AS0B826-S78B-7H-314P-DC-C588:
pitch 19.68*0.0254 = 0.500mm, pad 9.843*0.0254 x 78.74*0.0254 = 0.250 x 2.000mm,
row span -> total length exactly 80.00mm.

PAD record field order (per EasyEDA Pro format spec):
  0 "PAD" | 1 id | 2 layerId | 3 netName | 4 plated | 5 num
  6 centerX | 7 centerY | 8 padAngle | 9 hole | 10 defaultPad | 11 specialPad
defaultPad = ["RECT", w, h, cornerRadius] | ["ROUND", w, h] | ["NGON", d, n] | ...
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

MM_PER_UNIT = 0.0254


def load(path):
    recs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


def parse_pads(recs):
    out = []
    for r in recs:
        if not (isinstance(r, list) and r and r[0] == "PAD"):
            continue
        try:
            layer = int(r[2]) if r[2] is not None else 0
            num = str(r[5])
            x = float(r[6]); y = float(r[7]); rot = float(r[8])
            hole = r[9] if isinstance(r[9], list) else None
            pad = r[10] if isinstance(r[10], list) else None
        except (TypeError, ValueError, IndexError):
            continue
        if not pad:
            continue
        kind = str(pad[0]).upper()
        if kind == "RECT":
            w, h = float(pad[1]), float(pad[2])
            shape = "rect"
        elif kind in ("ROUND", "OVAL", "ELLIPSE"):
            w, h = float(pad[1]), float(pad[2])
            shape = "oval" if abs(w - h) > 1e-6 else "circle"
        elif kind == "NGON":
            w = h = float(pad[1]); shape = "circle"
        else:
            continue
        has_hole = bool(hole and float(hole[1] or 0) > 0)
        out.append(dict(num=num, x=x * MM_PER_UNIT, y=y * MM_PER_UNIT, rot=rot,
                        w=w * MM_PER_UNIT, h=h * MM_PER_UNIT, shape=shape,
                        layer=layer, tht=has_hole))
    return out


def build(pads, name, descr, edge=0.25):
    xs = [p["x"] for p in pads]; ys = [p["y"] for p in pads]
    hw = max(abs(x) + p["w"] / 2 for x, p in zip(xs, pads))
    hh = max(abs(y) + p["h"] / 2 for y, p in zip(ys, pads))
    x0, x1 = -hw - edge, hw + edge
    y0, y1 = -hh - edge, hh + edge
    L = [f'(footprint "{name}"',
         '  (version 20240108)',
         '  (generator "efoo2kicad")',
         '  (layer "F.Cu")',
         f'  (descr "{descr}")',
         '  (attr smd)']
    for p in pads:
        layer = "F.Cu" if p["layer"] == 0 else ("B.Cu" if p["layer"] == 1 else "F.Cu")
        side = "F" if layer == "F.Cu" else "B"
        lay = f'"{layer}" "{side}.Paste" "{side}.Mask"'
        at = f'(at {p["x"]:.4f} {p["y"]:.4f} {p["rot"]:.1f})'
        size = f'(size {p["w"]:.4f} {p["h"]:.4f})'
        if p["shape"] == "rect":
            L.append(f'  (pad "{p["num"]}" smd rect {at} {size} (layers {lay}))')
        elif p["shape"] == "oval":
            L.append(f'  (pad "{p["num"]}" smd oval {at} {size} (layers {lay}))')
        else:
            L.append(f'  (pad "{p["num"]}" smd circle {at} (size {p["w"]:.4f} {p["w"]:.4f}) (layers {lay}))')
    L.append(f'  (fp_line (start {x0:.3f} {y0:.3f}) (end {x1:.3f} {y0:.3f}) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))')
    L.append(f'  (fp_line (start {x1:.3f} {y0:.3f}) (end {x1:.3f} {y1:.3f}) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))')
    L.append(f'  (fp_line (start {x1:.3f} {y1:.3f}) (end {x0:.3f} {y1:.3f}) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))')
    L.append(f'  (fp_line (start {x0:.3f} {y1:.3f}) (end {x0:.3f} {y0:.3f}) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))')
    L.append(f'  (fp_line (start {x0-0.25:.3f} {y0-0.25:.3f}) (end {x1+0.25:.3f} {y0-0.25:.3f}) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))')
    L.append(f'  (fp_line (start {x1+0.25:.3f} {y0-0.25:.3f}) (end {x1+0.25:.3f} {y1+0.25:.3f}) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))')
    L.append(f'  (fp_line (start {x1+0.25:.3f} {y1+0.25:.3f}) (end {x0-0.25:.3f} {y1+0.25:.3f}) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))')
    L.append(f'  (fp_line (start {x0-0.25:.3f} {y1+0.25:.3f}) (end {x0-0.25:.3f} {y0-0.25:.3f}) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))')
    L.append(")")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--descr", default="Converted from EasyEDA Pro .efoo")
    a = ap.parse_args()

    pads = parse_pads(load(a.src))
    if not pads:
        print("no pads parsed", file=sys.stderr)
        return 2
    text = build(pads, a.name, a.descr)
    with open(a.dst, "w", encoding="utf-8") as fh:
        fh.write(text)

    xs = [p["x"] for p in pads]; ys = [p["y"] for p in pads]
    rows = collections.defaultdict(list)
    for p in pads:
        rows[round(p["y"], 3)].append(p)
    sig = [p for p in pads if not p["num"].upper().startswith("MP")]
    pitch = None
    if sig:
        row = max(rows.values(), key=len)
        sx = sorted(round(p["x"], 4) for p in row)
        d = [round(b - a2, 4) for a2, b in zip(sx, sx[1:]) if b - a2 > 1e-6]
        if d:
            pitch = collections.Counter(d).most_common(1)[0][0]
    print(f"wrote {a.dst}")
    print(f"  pads={len(pads)}  signal={len(sig)}  rows={len(rows)}")
    print(f"  pad w x h = {sig[0]['w']:.3f} x {sig[0]['h']:.3f} mm" if sig else "")
    if pitch:
        print(f"  row pitch = {pitch:.4f} mm")
    print(f"  body span = {(max(xs)-min(xs)):.2f} x {(max(ys)-min(ys)):.2f} mm")
    print(f"  checks: pitch~0.5 -> {abs((pitch or 0)-0.5)<0.01}; length~80 -> {abs((max(xs)-min(xs))-80)<0.5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
