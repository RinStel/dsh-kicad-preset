#!/usr/bin/env python3
"""Determine the scale of an EasyEDA Pro .efoo footprint by testing candidate
mm-per-unit ratios against physically plausible connector geometry."""
import collections
import json
import sys


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


def pads(recs):
    out = []
    for r in recs:
        if isinstance(r, list) and r and r[0] == "PAD":
            out.append(dict(num=str(r[5]), x=float(r[6]), y=float(r[7]),
                            rot=float(r[8]), hole=r[9], pad=r[10]))
    return out


def main():
    path = sys.argv[1]
    ps = pads(load(path))
    rows = collections.defaultdict(list)
    for p in ps:
        rows[round(p["y"], 2)].append(p)
    print(f"pads={len(ps)}  distinct y rows={len(rows)}")
    for y in sorted(rows):
        print(f"  row y={y:>9} n={len(rows[y]):3d}", end="")
        xs = sorted(round(p["x"], 2) for p in rows[y])
        if len(xs) > 2:
            d = [round(b - a, 2) for a, b in zip(xs, xs[1:]) if b - a > 1e-6]
            common = collections.Counter(d).most_common(1)
            print(f"  pitch_raw={common[0][0]} (n={common[0][1]})  span_raw={xs[-1]-xs[0]:.2f}")
        else:
            print()
    sig = [p for p in ps if not str(p["num"]).upper().startswith("MP")]
    xs = [p["x"] for p in sig]
    shape = collections.Counter(tuple(p["pad"][:3]) for p in sig).most_common(1)[0][0]
    print(f"\nsignal pads={len(sig)}  bbox span_raw={max(xs)-min(xs):.2f}")
    print(f"most common pad spec: {shape}")
    print("\nscale candidates (mm per raw unit):")
    print(f"{'scale':>10} {'pitch_mm':>9} {'pad_w':>7} {'pad_h':>7} {'len_mm':>8}  verdict")
    rowy = max(rows, key=lambda y: len(rows[y]))
    xs_row = sorted(round(p["x"], 2) for p in rows[rowy])
    ds = [b - a for a, b in zip(xs_row, xs_row[1:]) if b - a > 1e-6]
    pitch_raw = collections.Counter([round(d, 2) for d in ds]).most_common(1)[0][0]
    for s in (1.0, 0.1, 0.01, 0.0254, 0.00254, 0.001, 0.02, 0.05):
        pitch = pitch_raw * s
        w = float(shape[1]) * s
        h = float(shape[2]) * s
        ln = (max(xs) - min(xs)) * s
        ok = (0.3 <= pitch <= 1.3) and (0.1 <= w <= 0.7) and (0.8 <= h <= 3.0) and (25 <= ln <= 110)
        print(f"{s:>10} {pitch:>9.4f} {w:>7.3f} {h:>7.3f} {ln:>8.2f}  {'<== PLAUSIBLE' if ok else ''}")


if __name__ == "__main__":
    main()
