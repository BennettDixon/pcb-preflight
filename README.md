# pcb-preflight

A gate, not a generator. `preflight` takes a KiCad project directory and refuses it until it is ready to
order from an assembly fab: ERC and DRC at zero, nothing left to route, schematic and board in step, and
**every line of the bill of materials chosen from the fab's catalogue** (an LCSC code, not a value and a
guessed package). It prints the result the way a review doc reads: what it checked and left alone, what it
found, what it could not check, and what still has to be done by hand.

It exists because boards drafted with an AI's help fail in a particular way: the netlist is fine, the
parts are plausible, and the first thing that goes wrong is at the order page, where "10 µF 50 V X7R" turns
out to be a 1210 and the board was routed for an 0805. The rules it enforces come from
[DESIGN.md](DESIGN.md), which maps each gate to the pitfall it prevents.

Out of scope, on purpose: schematic generation, placement, routing, and fab-file export. KiCad and the
routers do those; this tool only decides whether their output may be ordered.

## Requirements

* KiCad 9 or 10 with `kicad-cli` (found automatically on macOS, Linux and Windows; else `--kicad-cli` or `$KICAD_CLI`).
* Python 3.9 or newer. No third-party packages.

## Install

```bash
pip install -e ~/projects/pcb-preflight
```

or run it in place without installing:

```bash
python3 -m pcb_preflight check <project dir>
```

## Use

```bash
preflight check path/to/board            # exit 0 = may be ordered, 1 = findings, 2 = tool error
preflight check path/to/board --online   # also look every LCSC code up at JLCPCB (stock, MPN, package, Basic/Extended)
preflight check path/to/board --bom other/bom.csv --strict --json report.json
preflight bom-template path/to/board     # write the bom.csv skeleton from the schematic, one line per value+footprint
```

The project directory holds `<name>.kicad_pro`, `<name>.kicad_sch` and `<name>.kicad_pcb`, plus `bom.csv`
with the columns `Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet` (`Ref` may list several
references: `C1,C7,C8`). Header names are matched loosely, so a JLCPCB-style `LCSC Part #` column works.

`preflight` never writes into the project. It copies the project to a temporary directory and runs
`kicad-cli` there, because `kicad-cli` itself drops a `.kicad_prl` beside any board that lacks one.
`--no-snapshot` runs in place; `--keep-work DIR` keeps the ERC/DRC JSON and the schematic BOM export.

## What a run looks like

Against the card-sorter power board (`sorter_pdb_v0`, 4 layers, 130 footprints, routed and clean, parts not
yet chosen), with [examples/sorter_pdb_v0/bom.csv](examples/sorter_pdb_v0/bom.csv) and `--online`
(full output in [examples/sorter_pdb_v0/report.txt](examples/sorter_pdb_v0/report.txt)):

```
CHECKED AND LEFT ALONE
  ERC (§12): 0 errors, 0 warnings on 1 sheet
  Unrouted connections (§11 §12): 0 connections still to route
  Schematic / PCB parity (§5): 0 mismatches, 0 warnings across 130 footprints
  Fiducials (§4): 3 on the front (FID2, FID1, FID3)
  Placement origin (§4): aux axis origin at 20, 95 mm
  ...
  bom.csv matches the schematic (§1 §5 §12): 110 purchasable references, every one on exactly one BOM line
  BOM package matches the footprint (§1): 85 references with a comparable package name agree with their footprint
  Catalogue and stock (§1 §2 §13): 2 codes found, 0 blocking, 0 low-stock/mismatch, 0 not reachable; 0 Extended part types

FINDINGS
  WARN  DRC (§12): 0 errors, 2 warnings (silk_edge_clearance x2)
  FAIL  LCSC code on every BOM line (§1 §12): 65 of 67 lines have no LCSC code (a value and a package is not a part)
        row 2 C1,C7,C8: 1uF 50V X7R (C_0805_2012Metric)
        ...

BY HAND BEFORE ORDERING
  - Fab assembly preview: rotation of 45 polarized or asymmetric parts (D5, D2, J5, C2, ...) (§4)
  - Every footprint pin map against the datasheet drawing ... (§3)
  ...

RESULT: FAIL  -  1 blocking, 2 warnings, 0 not checked
```

The `§` numbers refer to the sections of the pitfalls guide the gates were drawn from (see DESIGN.md).

## The gates

| Gate | Blocks? | Reads |
|:--|:--|:--|
| ERC errors | yes | `kicad-cli sch erc --format json` |
| DRC errors (warnings reported) | yes | `kicad-cli pcb drc --format json --all-track-errors` |
| Unrouted connections | yes | same report, `unconnected_items` |
| Schematic / PCB parity | yes | same run with `--schematic-parity` |
| DNP parts flagged on both schematic and board, absent from bom.csv | yes | `kicad-cli sch export bom` + the board file |
| bom.csv present, with the eight columns | yes | `bom.csv` |
| Every BOM line has an LCSC code | yes | `bom.csv` |
| BOM lines "done": MPN, package, Basic/Extended, stock, datasheet | warn | `bom.csv` |
| bom.csv references match the schematic (none missing, unknown, duplicated or DNP) | yes | `bom.csv` + schematic BOM export |
| BOM package agrees with the footprint on the board (0805 vs 1210, SOT-23 vs SOT-23-5, SMA vs SMB) | yes | `bom.csv` + schematic BOM export |
| Catalogue cross-check (`--online`): code exists, MPN and package match, stock ≥ 10× quantity, Basic/Extended as recorded | yes / warn | JLCPCB cart endpoint, jlcsearch fallback |
| Three fiducials on the front, placement origin set | warn | the board file |
| Board name and revision on silkscreen, a name beside every connector | warn | the board file |
| Two copper layers under a switching regulator | warn | the board file |

`--strict` makes warnings block too. Everything the tool cannot see is listed under "by hand before ordering"
rather than silently passed: pick-and-place rotation in the fab's preview, footprint pin maps against the
datasheet, transients, enclosure fit.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Twenty tests cover the BOM reader, package normalisation, the s-expression reader, the board gates and the
stock gate against a fake catalogue. The end-to-end run needs `kicad-cli` and a real project.

## Status

First cut (October 2026), run so far on one of the author's own single-sheet boards. Hierarchical schematics are read by
kicad-cli for ERC, parity and the BOM export, so they should work unchanged; variants are not handled. See DESIGN.md for the
roadmap, including the question of an MCP server wrapper.
