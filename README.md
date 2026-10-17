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
preflight check path/to/board --footprints /path/to/kicad/footprints   # the KiCad footprint library for pad geometry (found by itself when KiCad is installed)
preflight bom-template path/to/board     # write the bom.csv skeleton from the schematic, one line per value+footprint
```

The project directory holds `<name>.kicad_pro`, `<name>.kicad_sch` and `<name>.kicad_pcb`, plus `bom.csv`
with the columns `Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet` (`Ref` may list several
references: `C1,C7,C8`; save it as UTF-8). Header names are matched loosely, so a JLCPCB-style `LCSC Part #`
column works. `Package` holds the package as the catalogue record prints it (`0805`, `SOT-23-5`, `ESOP-8`,
`SMD,D6.3xL7.7mm`): `bom-template` writes the footprint name there as a placeholder, and a line that still
carries it is reported as not compared, not as a match. An optional `Package verified` column records that a person compared the part's drawing with
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
| `NOT VERIFIED` | 3 | Every core gate ran and nothing blocks, but something could not be checked: the catalogue was not asked (no `--online`) or did not answer, a BOM line has no MPN to compare, a footprint has no courtyard, a `Package` cell repeats its footprint name, a package name stands for more than one land pattern, a reference prefix has no category rule, or a package could not be compared and nobody signed for it. Not a pass. |

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
        note: not bought: FID1, FID2, FID3, H1, H2, H3, H4, TP1, TP2, TP3, TP4, TP5, +2 more (prefix FID/TP/H/MH); D11, D12, D13, D14, D15, D16 (DNP)
  BOM value matches the schematic (§1): 110 references, bom.csv Value equals the schematic Value on each (µ/u, Ω/ohm, spaces and case aside)
  Catalogue and stock (§1 §2 §13): 45 codes found, 0 blocking, 0 low-stock/mismatch, 0 not checked; 23 Extended part types (one loading fee each)
  Catalogue package fits the footprint (§1): 40 agree with their footprint, 5 not compared (sign each under NOT CHECKED with a "Package verified" note on its bom.csv line, or fix the string it names)
        note: pad geometry: KiCad footprint library at /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints; where both sides are library footprints the pads decide and the names only pick the candidates
  Catalogue category matches the reference prefix (§1 §2): 66 lines filed under the category their reference prefix means
  Catalogue description matches the BOM value (§1 §2): 35 lines agree on every figure their value states (F, H, Ω, V), 31 state no figure

FINDINGS
  WARN  DRC (§12): 0 errors, 2 warnings (silk_edge_clearance x2)
        warning: silk_edge_clearance: Silkscreen clipped by board edge [Segment on Edge.Cuts @ (20.0, 20.0); Segment of [...]
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
  - Fab assembly preview: rotation of 45 polarized or asymmetric parts (D5, D2, J5, C2, J16, L1, J2, D9, J15, J13, J11, U2, +33 more) (§4)
  ...

RESULT: FAIL  -  1 blocking, 2 warnings, 1 not checked  -  exit 1
```

L3's 15 µH SRP1245A-150M is not in JLCPCB's catalogue, so the line stays open rather than holding a part
the footprint was not drawn for. The five "not compared" lines are honest: a catalogue string like
`Plugin,P=5mm` names no package, so a person compares the drawing and records it in `Package verified`;
until then, even with L3 fixed, the result would be NOT VERIFIED, not PASS. The offline package line is a
real comparison now that the `Package` column holds the string each JLCPCB record prints (`0805`,
`SOT-25-5`, `SMD,D6.3xL7.7mm`): 100 of the 110 references agree with their footprint by the same table
and pad rules the online gate uses (pads against KiCad's footprint library where both sides are library
footprints), the 8 references behind those five catalogue strings are listed again under NOT CHECKED,
one per reference, and a ninth entry there names the 2 whose `Package` repeats the footprint name and so
compares nothing: L3, which has no part and still carries the placeholder `bom-template` wrote, and Q2,
whose catalogue string `SOT-23` is also its footprint's name, so the gate cannot tell it from a copied
placeholder. The three value lines are new: every bom.csv Value equals the schematic's, every
code is filed under the category its reference prefix means (JLCPCB's own designator column says "U" for
inductors and MOSFETs, so the category is read instead), and the 35 values that state a figure agree with
their record's description (the first run of that gate blocked three LEDs whose value "green +12V" names
the net they show, which is why a figure glued to a sign is not a rating). The parity line and the
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
| bom.csv Value equals the schematic Value of every reference, spelling aside (`10uF` = `10 µF` = `10µF`, `100R` = `100Ω`, `4k7` = `4.7k`) | yes | `bom.csv` + schematic BOM export |
| Package fits the footprint (`--online`): the catalogue's package for each code against the footprint on the board. The bom.csv `Package` column records the chosen part's package but is not compared: offline it is a copy of the footprint name or of the catalogue string, and a column compared with its own source proves nothing. Names pick the candidates (0805 vs 1210, SOIC-8 vs SOIC-8 with exposed pad, SMD vs through-hole can, a stated pitch against SOIC's 1.27 mm) and, where both sides are footprints in KiCad's library, pad geometry decides (TSOT-23-6 fits SOT-23-6, VSSOP-8 fits MSOP-8 3x3, a 2.1 mm exposed pad on a 2.6 mm one is unknown, `TSSOP-14` alone is unknown because the library has it at two pitches). Same / different / unknown; unknown is listed as not checked and makes the result NOT VERIFIED unless a person signed for it; a `Package` that repeats the footprint name compares nothing | yes | `bom.csv` + schematic BOM export + catalogue record + KiCad's footprint library |
| Catalogue cross-check (`--online`): code exists, MPN matches, stock ≥ 10× quantity, Basic/Extended as recorded; a code the catalogue could not be asked about, or a line with no MPN to compare, is not checked, never passed | yes / warn | JLCPCB cart endpoint, jlcsearch fallback |
| Catalogue category matches the reference prefix (`--online`): C capacitor, R resistor, D diode/TVS/LED, L inductor or ferrite, FB ferrite, Q transistor, J connector, F fuse, Y crystal, SW switch, U none of those; a capacitor's code on an LED line blocks; a prefix without a rule is not checked | yes | the record's category (JLCPCB), else its description |
| Catalogue description matches the BOM value (`--online`): every capacitance, inductance and resistance figure the value states within 1 % of the description's, and the part's voltage rating at least the value's (a 25 V part on a `100uF 16V` line fits); a figure the description lacks is not checked | yes | the record's description |
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

105 tests cover the BOM reader, the s-expression reader, the board gates, the stock gate against a fake
catalogue, the contract (verdicts and exit codes, what the gate owns and what the project may not switch
off, KiCad's `excluded` flag, parity, footprint identity across hierarchical sheets, placement, what is not
bought, the limits of a `Package verified` note, tool failures as ERROR with a JSON written), package
matching against `tests/fixtures/packages.csv` (88 rows: real KiCad footprint names paired with package
strings copied from JLCPCB records, or with the other KiCad footprint the review named, each with its
expected verdict and rule both with KiCad's footprint library and from names alone; DESIGN.md, "Package
names"), and the value gates against `tests/fixtures/catalogue.csv` (20 JLCPCB records, description and
category verbatim, paired with bom.csv lines and the verdict each gate must give). The pad-geometry tests
run where KiCad is installed and are skipped elsewhere; the end-to-end run needs `kicad-cli` and a real
project.

## Status

0.2 (October 2026): the first cut plus the contract above, after two adversarial reviews. The first found
the first cut printing PASS with kicad-cli failing, with the catalogue unreachable, with a made-up code
offline, with unrouted connections hidden by one `.kicad_pro` line, and for a regenerated schematic. The
second, of the contract itself, found the fab's limits still the project's to set (`min_track_width 0`, a
`.kicad_dru` rule), the pin matrix unowned, exclusions unread, a pathless footprint a free pass, a part
removable with `on_board no`, and false failures on field-text parity notes and library-lookup warnings;
all are closed and tested. The three gaps that review left open in the package and value gates (names
deciding what only the pads can, a copied `Package` column passing as a comparison, values never compared
with the schematic or the catalogue) are closed as of 2026-10-17 and tested. Run so far on one of the author's own single-sheet boards. Hierarchical
schematics are read by kicad-cli for ERC, parity and the BOM export and by the identity gate; variants are
not handled. See DESIGN.md for the roadmap, including what the reviews left open and the question of an
MCP server wrapper.
