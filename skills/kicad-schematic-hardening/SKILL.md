---
name: kicad-schematic-hardening
description: |
  Hard-won safety and verification rules for editing KiCad schematics through
  Konnect MCP: preventing GUI overwrite, netlist-diff gates, power-symbol and
  cross-page label rules, EasyEDA import normalization, and read-only clearance
  and geometry checks. Use for any schematic edit, batch re-layout, label
  cleanup, ERC/netlist sign-off, or when "ERC error=0" must not be trusted.
  Triggers: "edit schematic", "re-layout sheet", "remove labels", "netlist
  diff", "ERC pass", "clearance", "overlap", "EasyEDA import", "GUI overwrite".
argument-hint: "[schematic edit or verification task]"
---

# KiCad Schematic Hardening

This skill adds the gates that Konnect and ERC do not provide. Load `konnect`
and `kicad-schematic` first; this skill does not replace them. Read
[`reference/PITFALLS.md`](reference/PITFALLS.md) for the full case study,
quantified baseline, and the original Konnect tool gaps.

## Non-negotiable rules

1. **Close the KiCad GUI before any MCP schematic mutation.** A running GUI can
   rewrite every sheet from an older in-memory snapshot without an error. Before
   starting, require `Get-Process kicad,eeschema,pcbnew` to be empty and no
   `~*.kicad_pro.lck` to exist. Do not open the GUI until the batch is verified.
2. **Connectivity truth is the exported netlist.** Treat Konnect's
   `get_pin_net_name` / `get_component_nets` as geometry heuristics, not final
   proof. Export with `kicad-cli sch export netlist` and compare actual net
   membership.
3. **Power symbols only on wire or pin endpoints.** Never drop a power symbol in
   the middle of a wire and rely on an automatic junction. Split the wire or add
   a short stub first, then place the symbol on the endpoint.
4. **Cross-page signals use `global_label`, or a hierarchical label plus sheet
   pin.** A local label with the same text as a global label is a different net.
   Same-name local/global pairs are a defect, not a warning to ignore.
5. **Normalize EasyEDA pin electrical types immediately after import.** The
   converter often emits `unspecified` or `input` for every pin, which produces
   hundreds of `pin_to_pin` / `pin_not_driven` ERC findings. Correct types before
   wiring, and verify the package suffix against the orderable MPN.
6. **Diff the netlist before and after every batch.** For appearance-only work
   (moving fields/labels), require byte-identical netlists apart from the
   timestamp. For de-labeling / real-wire rewiring, allow renamed or unnamed
   nets but require every net's **member set** to be unchanged. Member mapping is
   the most sensitive short/open detector.
7. **Use ASCII project, sheet, and library paths.** Chinese paths break the DSH
   workspace sandbox, `easyeda2kicad`, and some Python subprocess paths. Rename
   the project before editing, not in the middle.
8. **Layout first, then wires, then delete labels.** Re-layout the functional
   block, redraw local connections as solid wires, and only then remove the
   labels that are now redundant. Doing it in the reverse order causes repeated
   rework and leaves orphan stubs.

## Batch loop

Run this for every sheet or functional block:

1. **Snapshot** — export the netlist, and record each `.kicad_sch` mtime, MD5,
   and `(wire` / `(junction` counts.
2. **Plan** — identify the functional block, required names (whitelist below),
   and target coordinates before touching anything.
3. **Move** — place/move components; expect old wires, junctions, and labels to
   stay behind.
4. **Reconnect** — clear the old routing for the moved block, draw local solid
   wires, then add only the labels/power symbols that must remain.
5. **Verify** — repeat the snapshot, diff the netlist, run root-sheet ERC,
   clearance, structural checks, and a rendered crop.
6. **Stop on GUI overwrite signals** — multiple `.kicad_sch` files with the same
   second-level mtime, a drop in wire count, or a new `.lck` file. Stop, report,
   and reconcile before any further write.

## Completion triangle

A schematic is complete only when all three are true:

- **Netlist** — expected members per net, no shorts, no lost nets.
- **Structure** — no unintended shorts, orphans, single-pin nets, or undriven
  power pins; run these checks per sheet and reconcile findings.
- **Clearance** — `scripts/sch_clearance_check.py` reports 0 conflicts; optional
  SVG overlap check agrees.

ERC is a fourth signal, not the whole gate. `ERC error = 0` does **not** prove
electrical correctness: an isolated ground island with no `power_in` pin, an
unconnected wire endpoint, or a local/global name mismatch can pass or appear
only as a warning. Report ERC warnings and these blind spots explicitly.

## Drawing style: local wires, remote names

Default to a solid local wire, no label, when two or three pins are close and a
short orthogonal path avoids other nets. Keep names for:

- cross-page signals (`global_label` or hierarchical label + sheet pin);
- power rails (`power` symbols);
- members spread across the page where a wire would cross other blocks;
- signals the requirements/documentation identify by name (`RS485_x_*`,
  `ETH0_*`, `PCIE2_*`, `HDMI0_*`, `USB*`).

Strong signals that a label should become a wire: two or more labels with the
same name on one page; a label joining pins a few millimeters apart; a label
used to route around a component instead of re-laying out the block. Do not
over-correct: a net with four or more dispersed members, repeated channels, or
a genuinely remote node is clearer with a name.

De-labeling changes net names and can create anonymous nets. That is acceptable
only when the per-net member set is preserved (see rule 6).

## Read-only tools

All scripts under `scripts/` are read-only: they parse `.kicad_sch` or exported
SVG and never write `.kicad_*`. Run them with the workspace Python; `crop_region.py`
needs Pillow. See [`scripts/README.md`](scripts/README.md) for every flag.

Preferred clearance gate (zero dependencies, parses source directly):

```text
python scripts/sch_clearance_check.py --sch <sheet>.kicad_sch --clear 1.0 --md <report>.md --json <report>.json
```

`overlap_check.py` is the earlier SVG-based checker. It is useful as a second
opinion, but the handoff records false positives in earlier versions and it
covers less than the source parser (text-on-symbol, component body); prefer
`sch_clearance_check.py` and investigate, do not blindly fix, its findings.

Geometry queries: `probe.py` (texts/fields/labels/wires/symbols), `sch_region.py`
(region dump), `fields_dump.py` (Reference/Value coordinates), `free_space.py`
(free placement candidates), `crop_region.py` (mm-region crop of a render).

## Konnect tool quirks

- **Multi-unit symbols**: place every unit before querying the others' pins;
  edit fields per unit. A missing unit makes pin lookups fail.
- **`update_symbols_from_library`**: always `dry_run` first. A pin move is
  refused by default; do not force `allow_pin_moves=true` — report the refusal.
- **Moving a component** does not move its wires; old wires stay behind. The
  `no_connect` flags do move with the pin — read them back, do not rebuild.
- **Text notes** cannot be edited in place; delete with `batch_delete` and
  recreate.
- **Custom rail power symbols**: `add_power_symbol` only knows library names.
  Reuse/move an existing rail instance, or place `VCC` then change its Value.
- **Title block** has no MCP editor; ask the user to fill it or record it as an
  explicit omission.
- **Render to file + `read_image`**; avoid inline base64 PNG (context blowup).
- **ERC JSON** may omit x/y for unconnected endpoints; locate them with
  `find_orphan_items` per sheet.

## EasyEDA import notes

- `easyeda2kicad --output` must be an **absolute path**; a relative output with
  `--project-relative` raises `ValueError: not in the subpath`.
- After conversion, verify the footprint against the exact orderable suffix. A
  real example: `THVD1450DR` is SOIC-8, while the generated (and some official)
  symbols used a VSON-8 footprint.
- The `efoo*.py` scripts convert EasyEDA Pro `.efoo` JSONL footprints; validate
  scale (`efoo_scale.py`) and record types (`efoo_inspect.py`) before trusting a
  conversion.

## Directory hygiene

`exports/` is for deliverables only: one current `<project>_<category>_<version>`
file per artifact. One-off scripts belong in `tools/` or `tmp/`; intermediate
snapshots and probe scripts belong in `tmp/`. Do not leave `v2/v3/final/final2`
copies in `exports/`.
