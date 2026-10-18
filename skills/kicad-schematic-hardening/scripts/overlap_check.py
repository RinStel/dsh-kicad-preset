#!/usr/bin/env python3
"""KiCad 原理图重叠检查器（v2，可复用）。

判定对象（按用户需求）：标签↔标签、标签↔元件、位号↔值。
刻意**排除**引脚名/引脚号之间的相邻（那是符号内部固有排布，不是缺陷）。

原理：kicad-cli 导出的 SVG 会把每个字符串画两次，第二次是
<text opacity="0"> 元素，带 x / y / textLength / font-size / text-anchor /
transform，据此算包围盒，无需栅格化。

用法：
  python tools/overlap_check.py --export --schematic "<root>.kicad_sch" --svg-dir exports/svg
  python tools/overlap_check.py --svg-dir exports/svg --md exports/overlap_report.md --json exports/overlap.json
  python tools/overlap_check.py --svg-dir exports/svg --symbol-bounds bounds.json

  --symbol-bounds 接受 Konnect get_schematic_layout 落盘的 JSON（components[].reference + bounds）。

退出码：0 = 无缺陷；1 = 存在缺陷（可接入批量流程判定）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

KICAD_CLI = os.environ.get("KICAD_CLI", "kicad-cli")

TEXT_RE = re.compile(r"<text\b([^>]*)>(.*?)</text>", re.S)
ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
ROT_RE = re.compile(r"rotate\(\s*(-?[\d.]+)")
NUM_RE = re.compile(r"-?[\d.]+")

REF_RE = re.compile(r"^#?(?:[A-Z]{1,3}\d+|[A-Z]{1,3}\?)$")
PIN_NUM_RE = re.compile(r"^[A-Za-z]?\d{1,3}$")          # 纯数字或单字母+数字：引脚号
PIN_NAME_RE = re.compile(r"^[A-Za-z~/\+\-\.\{\}]{1,6}$")  # 极短英文：引脚名
NOTE_HINT = re.compile(r"[，。；：、（）]|待确认|未接|待核")

# 从 .kicad_sym 收集到的引脚名集合：这些文字是符号内部固有标注，不参与重叠判定
PIN_NAMES: set[str] = set()
# 从 .kicad_sch 收集到的真实位号集合（避免把 P44 这类连接器引脚号误判为位号）
REFS: set[str] = set()

PIN_DECL_RE = re.compile(r'\(pin\s+\w+\s+\w+\s*\(at[^)]*\)\s*\(length[^)]*\)\s*(?:\(hide\s+\w+\)\s*)?\(name\s+"([^"]*)"', re.S)
REF_DECL_RE = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')


def load_pin_names(paths: list[str]) -> set[str]:
    """只读解析 .kicad_sym，收集全部 (pin ... (name "...")) 。"""
    names: set[str] = set()
    for p in paths:
        if os.path.isdir(p):
            files = [os.path.join(p, f) for f in os.listdir(p) if f.endswith(".kicad_sym")]
        else:
            files = [p]
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    raw = fh.read()
            except OSError:
                continue
            for m in PIN_DECL_RE.finditer(raw):
                nm = m.group(1).replace("~{", "").replace("}", "").strip()
                if nm and nm != "~":
                    names.add(nm)
    return names


def load_refs(roots: list[str]) -> set[str]:
    """只读解析 .kicad_sch，收集工程内真实使用过的位号。"""
    refs: set[str] = set()
    for p in roots:
        if os.path.isdir(p):
            files = [os.path.join(p, f) for f in os.listdir(p) if f.endswith(".kicad_sch")]
        else:
            files = [p]
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    raw = fh.read()
            except OSError:
                continue
            refs.update(m.group(1) for m in REF_DECL_RE.finditer(raw))
    return refs


class TextBox:
    __slots__ = ("text", "x", "y", "w", "h", "anchor", "angle", "svg", "kind")

    def __init__(self, text, x, y, w, h, anchor, angle, svg):
        self.text, self.x, self.y = text, x, y
        self.w, self.h = w, h
        self.anchor, self.angle, self.svg = anchor, angle, svg
        self.kind = classify(text)

    @property
    def x0(self):
        if self.anchor == "middle":
            return self.x - self.w / 2
        if self.anchor == "end":
            return self.x - self.w
        return self.x

    @property
    def x1(self):
        return self.x0 + self.w

    @property
    def y0(self):
        return self.y - self.h * 0.78   # 大部分字形在基线上方

    @property
    def y1(self):
        return self.y + self.h * 0.22

    def box(self):
        return [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)]

    def __repr__(self):
        return f"{self.kind}:{self.text}@{self.box()}"


def classify(text: str) -> str:
    if text in PIN_NAMES:
        return "pin_name"
    if text in REFS:
        return "ref"
    if PIN_NUM_RE.match(text):
        return "pin_number"
    if REF_RE.match(text):
        return "ref"
    if NOTE_HINT.search(text) or len(text) > 24:
        return "note"
    if PIN_NAME_RE.match(text):
        return "pin_name"
    if "_" in text or re.search(r"[A-Z]{2,}\d", text) or text.count("_") >= 1:
        return "label"
    return "value"


def unescape(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&#160;", " ").replace("&quot;", '"'))


def parse_svg(path: str) -> list[TextBox]:
    """解析 SVG，沿祖先 <g transform="rotate(...)"> 累积旋转角。

    kicad-cli 对竖直标签的旋转有时写在父级 <g> 上而不是 <text> 自身，
    只读元素自身 transform 会把竖直文本当成水平盒子，产生假缺陷。
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []
    out: dict[tuple, TextBox] = {}

    def walk(node, angle_acc: float):
        tag = node.tag.split("}")[-1]
        tr = node.get("transform") or ""
        m = ROT_RE.search(tr)
        angle = (angle_acc + float(m.group(1))) % 360 if m else angle_acc
        if tag == "text" and node.get("opacity") in ("0", "0.0"):
            content = re.sub(r"\s+", " ", unescape("".join(node.itertext()))).strip()
            if content:
                try:
                    x = float(node.get("x", "0"))
                    y = float(node.get("y", "0"))
                except ValueError:
                    x = y = None
                if x is not None:
                    fs_m = NUM_RE.search(node.get("font-size", "") or "")
                    fs = float(fs_m.group()) if fs_m else 1.27
                    tl_m = NUM_RE.search(node.get("textLength", "") or "")
                    w = float(tl_m.group()) if tl_m else len(content) * fs * 0.62
                    h = fs
                    if 45 < angle % 180 < 135:
                        w, h = h, w
                    key = (content, round(x, 2), round(y, 2))
                    out.setdefault(key, TextBox(content, x, y, w, h,
                                                node.get("text-anchor", "start"), angle,
                                                os.path.basename(path)))
        for ch in list(node):
            walk(ch, angle)

    walk(tree.getroot(), 0.0)
    return list(out.values())


def ov(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def check(boxes: list[TextBox], min_ov: float, include_pin: bool):
    """返回缺陷列表：仅标签相关、位号-值、以及压元件本体。"""
    defects: list[dict] = []
    texts = [b for b in boxes if include_pin or b.kind not in ("pin_name", "pin_number")]
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            dx = ov(a.x0, a.x1, b.x0, b.x1)
            dy = ov(a.y0, a.y1, b.y0, b.y1)
            if dx <= 0 or dy <= 0 or dx < min_ov or dy < min_ov:
                continue
            kinds = {a.kind, b.kind}
            # 位号↔值：同一元件的两个字段压在一起
            if kinds == {"ref", "value"}:
                cat = "ref_value"
            elif "label" in kinds:
                cat = "label_label" if kinds <= {"label"} else "label_text"
            elif "note" in kinds:
                cat = "note_text"
            else:
                continue
            defects.append({"cat": cat, "a": a, "b": b, "dx": round(dx, 2), "dy": round(dy, 2)})
    return defects


def check_symbols(boxes: list[TextBox], bounds: dict, min_cov: float = 0.35):
    hits = []
    for b in boxes:
        if b.kind in ("pin_name", "pin_number"):
            continue
        for ref, (x0, y0, x1, y1) in bounds.items():
            dx = ov(b.x0, b.x1, x0, x1); dy = ov(b.y0, b.y1, y0, y1)
            if dx <= 0 or dy <= 0:
                continue
            cover = (dx * dy) / max(b.w * b.h, 1e-6)
            if cover > min_cov:
                hits.append({"label": b, "ref": ref, "cover": round(cover, 2)})
    return hits


def export_svgs(schematic: str, svg_dir: str, kicad_cli: str = KICAD_CLI) -> None:
    os.makedirs(svg_dir, exist_ok=True)
    subprocess.run([kicad_cli, "sch", "export", "svg", "--output", svg_dir, schematic],
                   check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")


def load_bounds(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    out = {}
    for c in (data.get("components") or data.get("symbols") or []):
        ref = c.get("reference") or c.get("ref")
        bb = c.get("bounds") or c.get("bbox")
        if not ref or not bb:
            continue
        if isinstance(bb, dict):
            out[ref] = (float(bb["x0"]), float(bb["y0"]), float(bb["x1"]), float(bb["y1"]))
        elif isinstance(bb, (list, tuple)) and len(bb) == 4:
            out[ref] = tuple(float(v) for v in bb)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--schematic")
    ap.add_argument("--kicad-cli", default=KICAD_CLI,
                    help="kicad-cli executable (default: $KICAD_CLI or 'kicad-cli')")
    ap.add_argument("--svg-dir", default="exports/svg")
    ap.add_argument("--symbol-bounds")
    ap.add_argument("--lib", nargs="*", default=None,
                    help="符号库文件或目录，用于收集引脚名做排除（默认自动探测工程内 .kicad_sym）")
    ap.add_argument("--min-overlap", type=float, default=0.30)
    ap.add_argument("--include-pin-text", action="store_true")
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.export:
        if not a.schematic:
            print("--export 需要 --schematic", file=sys.stderr); return 2
        export_svgs(a.schematic, a.svg_dir, a.kicad_cli)
    if not os.path.isdir(a.svg_dir):
        print(f"目录不存在: {a.svg_dir}", file=sys.stderr); return 2

    global PIN_NAMES
    libs = a.lib
    if not libs:
        probe = os.path.abspath(a.svg_dir)
        cand = None
        for _ in range(3):
            if any(f.endswith(".kicad_sym") for f in os.listdir(probe)):
                cand = probe
                break
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if cand:
            libs = [cand]
        elif a.schematic:
            libs = [os.path.dirname(os.path.abspath(a.schematic))]
        else:
            libs = []
    if not libs:
        print("警告：未找到 .kicad_sym；引脚名排除集为空，可用 --lib 指定符号库目录。", file=sys.stderr)
    PIN_NAMES |= load_pin_names(libs)
    global REFS
    # 位号必须从整个工程目录取：--schematic 往往只是层级壳文件（几 KB），
    # 只读它会导致 REFS 为空、ref_value 类永远判 0。
    ref_roots = [os.path.dirname(os.path.abspath(a.schematic))] if a.schematic else libs
    REFS |= load_refs(ref_roots)
    print(f"引脚名排除集：{len(PIN_NAMES)} 个；真实位号集：{len(REFS)} 个"
          f"（位号来源：{', '.join(ref_roots)}）")

    svgs = sorted(f for f in os.listdir(a.svg_dir) if f.lower().endswith(".svg"))
    bounds = load_bounds(a.symbol_bounds) if a.symbol_bounds else {}

    rows, report, total = [], {"svg_dir": os.path.abspath(a.svg_dir), "sheets": []}, 0
    cats = {}
    for svg in svgs:
        boxes = parse_svg(os.path.join(a.svg_dir, svg))
        d = check(boxes, a.min_overlap, a.include_pin_text)
        s = check_symbols(boxes, bounds) if bounds else []
        total += len(d) + len(s)
        for x in d:
            cats[x["cat"]] = cats.get(x["cat"], 0) + 1
        rows.append((svg, len(boxes), len(d), len(s)))
        report["sheets"].append({
            "svg": svg, "texts": len(boxes),
            "defects": [{"cat": x["cat"], "a": x["a"].text, "a_at": x["a"].box(),
                         "b": x["b"].text, "b_at": x["b"].box(),
                         "overlap_mm": [x["dx"], x["dy"]]} for x in d],
            "on_symbol": [{"label": x["label"].text, "at": x["label"].box(),
                           "ref": x["ref"], "cover": x["cover"]} for x in s],
        })
        if not a.quiet and (d or s):
            print(f"\n=== {svg} ===")
            for x in d:
                print(f"  [{x['cat']}] '{x['a'].text}' @{x['a'].box()} <-> '{x['b'].text}' @{x['b'].box()}  {x['dx']}x{x['dy']}mm")
            for x in s:
                print(f"  [压元件] '{x['label'].text}' @{x['label'].box()} 压住 {x['ref']} ({int(x['cover']*100)}%)")

    if a.md:
        os.makedirs(os.path.dirname(a.md) or ".", exist_ok=True)
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write("# 原理图重叠检查\n\n")
            fh.write(f"- 目录：`{report['svg_dir']}`\n- 最小重叠判定：{a.min_overlap}mm（双向）\n")
            fh.write(f"- 已排除引脚名/引脚号相邻：{'否' if a.include_pin_text else '是'}\n\n")
            fh.write("| 页 | 文本数 | 标签/位号类缺陷 | 压元件 |\n|---|---:|---:|---:|\n")
            for svg, n, dn, sn in rows:
                fh.write(f"| {svg} | {n} | {dn} | {sn} |\n")
            fh.write(f"\n**合计缺陷 {total}**（分类：" +
                     (", ".join(f"{k}={v}" for k, v in sorted(cats.items())) or "无") + "）\n\n")
            fh.write("判定：标签↔标签、标签↔文字、位号↔值 应为 0。\n")
        print(f"Markdown: {a.md}")
    if a.json:
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"JSON: {a.json}")

    print(f"\n汇总：页数={len(svgs)} 缺陷={total}（{', '.join(f'{k}={v}' for k, v in sorted(cats.items())) or '无'}）")
    print("结果：" + ("FAIL（存在重叠）" if total else "PASS（无重叠）"))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
