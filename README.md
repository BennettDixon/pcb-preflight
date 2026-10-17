# pcb-preflight

A gate, not a generator. `preflight` takes a KiCad project directory and refuses it until it is ready to
order from an assembly fab: ERC and DRC at zero, nothing left to route, schematic and board in step, and
**every line of the bill of materials chosen from the fab's catalogue** (an LCSC code, not a value and a
guessed package). It prints the result the way a review doc reads: the verdict, what it checked and left
alone, what it found, what it could not check, and what still has to be done by hand.

It exists because boards drafted with an AI's help fail in a particular way: the netlist is fine, the
parts are plausible, and the first thing that goes wrong is at the order page, where "10 µF 50 V X7R" turns
out to be a 1210 and the board was routed for an 0805. The rules it enforces come from
[DESIGN.md](DESIGN.md), which maps each gate to the pitfall it prevents.

Out of scope, on purpose: schematic generation, placement, routing, and fab-file export. KiCad and the
routers do those; this tool only decides whether their output may be ordered.

## Requirements

* KiCad 9 or 10 with `kicad-cli` (found automatically on macOS, Linux and Windows; else `--kicad-cli` or `$KICAD_CLI`, and a wrong path is an error, never silently replaced).
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
preflight check path/to/board --online   # exit 0 PASS, 1 FAIL, 2 ERROR (a gate did not run), 3 NOT VERIFIED (something was not checked)
preflight check path/to/board            # offline: the catalogue is not asked, so the best result is NOT VERIFIED (exit 3)
preflight check path/to/board --bom other/bom.csv --strict --json report.json
preflight bom-template path/to/board     # write the bom.csv skeleton from the schematic, one line per value+footprint
```

The project directory holds `<name>.kicad_pro`, `<name>.kicad_sch` and `<name>.kicad_pcb`, plus `bom.csv`
with the columns `Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet` (`Ref` may list several
references: `C1,C7,C8`; save it as UTF-8). Header names are matched loosely, so a JLCPCB-style `LCSC Part #`
column works. An optional `Package verified` column records that a person compared the part's drawing with
the footprint where the tool cannot ("2026-10-16 BD: 1935161 drawing against the PT 1,5/2 footprint"); the
report prints it as "by hand", never as the tool's own pass, and it never turns a mismatch the tool can see
into a pass.

`check` never writes into the project (`bom-template` writes the one file you ask it for). It copies the
project to a temporary directory and runs `kicad-cli` there, because `kicad-cli` itself drops a
`.kicad_prl` beside any board that lacks one, and because the gate sets what it owns in that copy before
`kicad-cli` runs (see below). `--keep-work DIR` keeps the copy and the ERC/DRC JSON and the schematic BOM
export; a `--json` file is written on every run, including one that ends in ERROR.

## What PASS means

The RESULT line is on the second line of the report and again at the end, and the exit code follows it:

| Result | Exit | Promise |
|:--|:--|:--|
| `PASS` | 0 | Every gate ran under the named preset and judged every item it saw. The board may be ordered as far as a file-level check can tell; the BY HAND list is still yours. |
| `FAIL` | 1 | A finding blocks the order. |
| `ERROR` | 2 | A core gate did not run (kicad-cli failed, a file is missing or unreadable), or the tool itself failed. Nothing in the report is a pass. |
| `NOT VERIFIED` | 3 | Every core gate ran and nothing blocks, but something could not be checked: the catalogue was not asked (no `--online`) or did not answer, a BOM line has no MPN to compare, a footprint has no courtyard, or a package could not be compared and nobody signed for it. Not a pass. |

What the gate owns, it sets in its copy of the `.kicad_pro` before `kicad-cli` runs, because the project is
the thing under review: the protected checks run as errors whatever the project says (an agent told to
"make DRC pass" cannot do it by setting `unconnected_items` to `ignore`); the ERC pin-conflict matrix is
no weaker than KiCad's default; the board's minimum constraints are no lower than JLCPCB's published
capability for 1 oz copper (`min_track_width 0` does not pass a 0.05 mm track); custom design rules
(`<name>.kicad_dru`) are left out of the copy, since a rule can relax or mute a constraint; a protected
violation the project excluded blocks. The report prints what the project had set whenever it differs from
KiCad's own defaults, and says when a custom-rules file was present. Everything else keeps the project's
choice. The preset is named in every report (`jlcpcb-assembly@2026.10`); its protected checks, the fab's
minimums and their sources are in [pcb_preflight/preset.py](pcb_preflight/preset.py).

## What a run looks like

Against the card-sorter power board (`sorter_pdb_v0`, 4 layers, 130 footprints, routed and clean, a
catalogue part on 66 of 67 BOM lines), with [examples/sorter_pdb_v0/bom.csv](examples/sorter_pdb_v0/bom.csv)
and `--online` (full output in [examples/sorter_pdb_v0/report.txt](examples/sorter_pdb_v0/report.txt)):

```
sorter_pdb_v0  -  KiCad 10.0.7  -  jlcpcb-assembly@2026.10  -  online  -  4 copper layers, 130 footprints  -  bom.csv: bom.csv
RESULT: FAIL  -  1 blocking, 2 warnings, 1 not checked  -  exit 1
  1 finding blocks the order (FAIL lines under FINDINGS); fix them and run again

CHECKED AND LEFT ALONE
  ERC (§12): 0 errors, 0 warnings on 1 sheet
  Unrouted connections (§11 §12): 0 connections still to route
  Schematic / PCB parity (§5): 0 mismatches across 130 footprints
  Board footprints belong to this schematic (§5): 130 of 130 footprints name a symbol in the schematic
  ...
  Bought parts placed on the board (§5 §12): 110 of 110 bought references have a footprint on the board
  bom.csv matches the schematic (§1 §5 §12): 110 bought references, every one on exactly one BOM line
        note: not bought: FID1, FID2, FID3, H1, H2, H3, H4, TP1, ... (prefix FID/TP/H/MH); D11, D12, D13, D14, D15, D16 (DNP)
  BOM package matches the footprint (§1): 110 agree with their footprint
  Catalogue and stock (§1 §2 §13): 45 codes found, 0 blocking, 0 low-stock/mismatch, 0 not checked; 23 Extended part types (one loading fee each)
  Catalogue package fits the footprint (§1): 40 agree with their footprint, 5 not compared (no readable package name; sign each under NOT CHECKED ...)

FINDINGS
  WARN  DRC (§12): 0 errors, 2 warnings (silk_edge_clearance x2)
        warning: silk_edge_clearance: Silkscreen clipped by board edge [...]
        note: minimums: JLCPCB 1 oz copper, 4 layers; below the fab's in the project, raised in the copy: min_clearance 0.0 -> 0.09 mm
  FAIL  LCSC code on every BOM line (§1 §12): 1 of 67 lines have no LCSC code (a value and a package is not a part)
        row 47 L3: 15uH SRP1245A-150M (L_Bourns_SRP1245A)
  WARN  BOM lines complete (§1 §2): 1 of 67 lines are not "done" (MPN, package, Basic/Extended, stock, datasheet)

NOT CHECKED
  Catalogue package fits the footprint (§1): 5 not compared
        C3819953 1935161 (J1, J2, J3, J4; bom.csv row 29, 30, 31, 32): Plugin,P=5mm on TerminalBlock_Phoenix_PT-1,5-2-5.0-H_1x02_P5.00mm_Horizontal:
            neither name is in the package table; to clear it, compare the drawing and add a "Package verified" note (date, initials, what was compared) on that bom.csv line
        ...

BY HAND BEFORE ORDERING
  - Fab assembly preview: rotation of 45 polarized or asymmetric parts (D5, D2, J5, C2, ...) (§4)
  ...

RESULT: FAIL  -  1 blocking, 2 warnings, 1 not checked  -  exit 1
```

L3's 15 µH SRP1245A-150M is not in JLCPCB's catalogue, so the line stays open rather than holding a part
the footprint was not drawn for. The five "not compared" lines are honest: a catalogue string like
`Plugin,P=5mm` names no package, so a person compares the drawing and records it in `Package verified`;
until then, even with L3 fixed, the result would be NOT VERIFIED, not PASS. The parity line and the
"belong to this schematic" line are two different checks: KiCad's parity test matches footprints by
reference, so a schematic regenerated with fresh identities (the §5 incident) passes it with 0 mismatches
while every footprint on the board points at a symbol that no longer exists; the second line reads the
uuids, and a board whose links were stripped fails it too. The "minimums" note says the project left
KiCad's default `min_clearance 0`, which the gate raised to the fab's figure in its copy before DRC ran.

The `§` numbers refer to the sections of the pitfalls guide the gates were drawn from (see DESIGN.md).

## The gates

| Gate | Blocks? | Reads |
|:--|:--|:--|
| ERC errors; a protected check the project excludes; the pin-conflict matrix no weaker than KiCad's | yes | `kicad-cli sch erc --format json --severity-all`, run under the preset's severities |
| DRC errors (warnings reported); a protected check the project excludes; the fab's minimums; a footprint without a courtyard is not checked | yes | `kicad-cli pcb drc --format json --severity-all --all-track-errors`, same |
| Unrouted connections | yes | same report, `unconnected_items` |
| Schematic / PCB parity: missing, extra or duplicate footprints, net conflicts, attribute and value mismatches, whatever severity KiCad gives them; field-text and footprint-filter notes keep the project's severity | yes | same run with `--schematic-parity` |
| Board footprints belong to this schematic: each footprint's path names a symbol uuid that exists, under the same reference; a footprint without a path is board-only only when no symbol carries its reference | yes | `.kicad_pcb` footprint paths + `.kicad_sch` symbols, all sheets |
| DNP parts flagged on both schematic and board, absent from bom.csv | yes | `kicad-cli sch export bom` + the board file |
| Bought parts placed: every reference in the BOM has a footprint on the board and is not excluded from the board in the schematic | yes | schematic BOM export + the board file |
| bom.csv present, UTF-8, with the eight columns | yes | `bom.csv` |
| Every BOM line has an LCSC code | yes | `bom.csv` |
| BOM lines "done": MPN, package, Basic/Extended, stock, datasheet | warn | `bom.csv` |
| bom.csv references match the schematic (none missing, unknown, duplicated or DNP); what is not bought is printed; a part with paste pads cannot hide behind a TP/H/FID name or an exclusion | yes | `bom.csv` + schematic BOM export + the board's pads |
| Package fits the footprint: bom.csv package, and with `--online` the catalogue's package, against the footprint on the board (0805 vs 1210, SOIC-8 vs SOIC-8 with exposed pad, SMD vs through-hole can). Same / different / unknown; unknown is listed as not checked and makes the result NOT VERIFIED unless a person signed for it | yes | `bom.csv` + schematic BOM export + catalogue record |
| Catalogue cross-check (`--online`): code exists, MPN matches, stock ≥ 10× quantity, Basic/Extended as recorded; a code the catalogue could not be asked about, or a line with no MPN to compare, is not checked, never passed | yes / warn | JLCPCB cart endpoint, jlcsearch fallback |
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

75 tests cover the BOM reader, the s-expression reader, the board gates, the stock gate against a fake
catalogue, the contract (verdicts and exit codes, what the gate owns and what the project may not switch
off, KiCad's `excluded` flag, parity, footprint identity across hierarchical sheets, placement, what is not
bought, the limits of a `Package verified` note, tool failures as ERROR with a JSON written), and package
matching against `tests/fixtures/packages.csv`: real KiCad footprint names paired with package strings
copied from JLCPCB records, each with its expected verdict (DESIGN.md, "Package names"). The end-to-end run
needs `kicad-cli` and a real project.

## Status

0.2 (October 2026): the first cut plus the contract above, after two adversarial reviews. The first found
the first cut printing PASS with kicad-cli failing, with the catalogue unreachable, with a made-up code
offline, with unrouted connections hidden by one `.kicad_pro` line, and for a regenerated schematic. The
second, of the contract itself, found the fab's limits still the project's to set (`min_track_width 0`, a
`.kicad_dru` rule), the pin matrix unowned, exclusions unread, a pathless footprint a free pass, a part
removable with `on_board no`, and false failures on field-text parity notes and library-lookup warnings;
all are closed and tested. Run so far on one of the author's own single-sheet boards. Hierarchical
schematics are read by kicad-cli for ERC, parity and the BOM export and by the identity gate; variants are
not handled. See DESIGN.md for the roadmap, including what the reviews left open and the question of an
MCP server wrapper.
