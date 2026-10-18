#!/usr/bin/env python3
"""Inspect an EasyEDA Pro .efoo footprint (JSONL) to learn its record layout."""
import collections
import json
import sys


def load(path):
    recs = []
    with open(path, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"parse fail line {ln}: {exc}")
    return recs


def main():
    path = sys.argv[1]
    recs = load(path)
    print("records:", len(recs))
    c = collections.Counter(r[0] for r in recs if isinstance(r, list) and r)
    for k, v in c.most_common():
        print(f"  {k:16} {v}")

    for kind in ("PAD", "TRACK", "CIRCLE", "ARC", "RECT", "POLYGON", "SOLIDREGION", "HOLE", "TEXT", "ATTR"):
        sample = [r for r in recs if isinstance(r, list) and r and r[0] == kind]
        if not sample:
            continue
        print(f"\n--- {kind} (n={len(sample)}) ---")
        for r in sample[:2]:
            s = json.dumps(r, ensure_ascii=False)
            print("  " + (s[:700] + ("..." if len(s) > 700 else "")))

    pads = [r for r in recs if isinstance(r, list) and r and r[0] == "PAD"]
    if pads:
        print("\nunique pad shapes:", collections.Counter(
            (p[3] if len(p) > 3 else None) for p in pads))
        print("unique pad layers:", collections.Counter(
            (p[2] if len(p) > 2 else None) for p in pads))


if __name__ == "__main__":
    main()
