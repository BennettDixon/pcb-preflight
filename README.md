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
preflight bom path/to/board              # write bom.csv from the LCSC code in each symbol's field and the catalogue record of that code (exit 0 complete, 3 a line without a code or a record)
preflight bom path/to/board --offline    # the same from the cache and the fields only; --refresh ignores the cache; --catalogue parts.csv consults your own list first
```

The project directory holds `<name>.kicad_pro`, `<name>.kicad_sch` and `<name>.kicad_pcb`, plus `bom.csv`.
bom.csv is written by `preflight bom` from the symbol fields and the catalogue; a hand-made one still works.
`bom` reads the LCSC code each symbol names in a field (`LCSC`, `LCSC Part #`, `LCSC Part`, `JLCPCB Part #`
and the other spellings in `init.FIELDS`, each with the tool it comes from), asks JLCPCB for that code's
record, and writes one line per code, value and footprint with the columns `Ref, Value, Package, MPN,
Manufacturer, LCSC, Basic/Extended, Stock, Datasheet, Fetched, Package verified`. It never chooses a part:
a symbol without a code becomes a line with the footprint name as `Package` and empty catalogue columns,
listed in the report with the fix (put the C-number in the symbol's field and run `bom` again); nothing is
searched by value or MPN. An existing bom.csv is merged, not replaced: a hand-entered code on a line whose
symbol has no field is kept, a field code wins over a differing line code and the change is printed, extra
columns are kept, and a `Package verified` note is carried over while its references, code and the
catalogue's package string are unchanged, otherwise dropped and printed. `Fetched` says where and when the
catalogue facts on the line came from (`jlcpcb 2026-10-18`, `parts.csv 2026-10-01`); `Stock` is the stock
on that date. The write is deterministic, so the file diffs cleanly in review. A hand-made bom.csv needs
the eight columns `Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet` (`Ref` may list
several references: `C1,C7,C8`; save it as UTF-8; header names are matched loosely, so a JLCPCB-style
`LCSC Part #` column works); `Manufacturer` and `Fetched` are optional and used when present. `Package`
holds the package as the catalogue record prints it (`0805`, `SOT-23-5`, `ESOP-8`, `SMD,D6.3xL7.7mm`); a
line that carries the footprint name instead is reported as not compared, not as a match. The optional
`Package verified` column records that a person compared the part's drawing with the footprint where the
tool cannot ("2026-10-16 BD: 1935161 drawing against the PT 1,5/2 footprint"); the report prints it as
"by hand", never as the tool's own pass, and it never turns a mismatch the tool can see into a pass.
`bom-template` is kept for one release as an alias for `bom --offline` without reading the fields.

Catalogue facts go through a cache, `~/.cache/pcb-preflight/catalogue.json` (or `$PCB_PREFLIGHT_CACHE`):
`bom` reads a stock figure back for 7 days and the identity facts (MPN, package, library type) for 90;
`check --online` always refreshes stock and writes the cache; `check` without `--online` reads the cache,
says so, and lists every cached item as not checked, so the result is NOT VERIFIED, never PASS. One request
per code, so a 67-line board costs 67 requests once, not per run.

`check` never writes into the project (`bom` writes the one file you ask it for). It copies the
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
| `NOT VERIFIED` | 3 | Every core gate ran and nothing blocks, but something could not be checked: the catalogue was not asked (no `--online`) or did not answer, the catalogue facts came from the cache or are older than the 7-day stock limit (the stock gate says where they came from and when, and lists those items as not checked), a BOM line has no MPN to compare, a footprint has no courtyard, a `Package` cell repeats its footprint name, a package name stands for more than one land pattern and the board's footprint is not one KiCad has, a reference prefix has no category rule, or a package could not be compared and nobody signed for it. Not a pass. |

What the gate owns, it sets in its copy of the `.kicad_pro` before `kicad-cli` runs, because the project is
the thing under review: the protected checks run as errors whatever the project says (an agent told to
"make DRC pass" cannot do it by setting `unconnected_items` to `ignore`); KiCad's electrical-intent ERC errors (an unconnected pin, an undriven power pin, two outputs tied, a dangling label), the courtyard-overlap and solder-mask-bridge DRC checks, and a DRC violation of the project's own stricter constraint that still clears the fab's floor (a 0.2 mm hole where the designer asked for 0.3) run as warnings, since none decides whether the fab can build the board (`--strict` promotes them); the ERC pin-conflict matrix is
no weaker than KiCad's default; the board's minimum constraints are no lower than JLCPCB's published
capability for 1 oz copper (`min_track_width 0` does not pass a 0.05 mm track); custom design rules
(`<name>.kicad_dru`) are left out of the copy, since a rule can relax or mute a constraint; a protected
violation the project excluded blocks. The report prints what the project had set whenever it differs from
KiCad's own defaults, and says when a custom-rules file was present. Everything else keeps the project's
choice. The preset is named in every report (`jlcpcb-assembly@2026.10`); its protected checks, the fab's
minimums and their sources are in [pcb_preflight/preset.py](pcb_preflight/preset.py).

Three sources name a part, and PASS needs them to agree: the LCSC code in the symbol's field, the code on
its bom.csv line, and the catalogue record of that code. Where a field and a line both carry a code they
must be the same code, and a field with a code whose line has none is the same finding ("the schematic
says C14663, bom.csv says C1588: run preflight bom, or fix the field"); the schematic is the design and
bom.csv is written from it. A project whose symbols carry no LCSC field has one source, bom.csv, and the
gate says so. With `--online` the record is fetched today and the stock figure is today's; facts read from
the cache or older than the stock limit are printed with their source and date and make the result NOT
VERIFIED, never PASS.

### ORDER

Below FINDINGS the report has an ORDER section: what the files show that lands on a priced tier of
JLCPCB's, one line per driver with the figure read from the files, the fab's standard, the tier it lands
in with the quote page's own condition, the source and the date it was read. The section never changes the
verdict or the exit code, `--strict` does not promote it, and the RESULT line counts its lines ("3 cost
drivers"). The floor the DRC gate blocks on is the fab's absolute buildable minimum (a 0.1 mm hole is
buildable, priced and conditional, so it is an ORDER line, not a FAIL); everything above the floor that
the fab prices is a tier in [pcb_preflight/preset.py](pcb_preflight/preset.py) (`TIERS`, read 2026-10-18).
The drivers the files can show: via hole and diameter, the smallest drilled hole, blind and buried vias
(HDI), copper layers, the outline's size, parts to place on both sides, through-hole parts to assemble,
Extended part types (`--online`), a layer count or thickness outside Economic PCBA, and the stackup's
castellated, edge-plating and impedance flags. Nothing is inferred: no package size or pitch is guessed
from pads, and a blind, buried or micro via is read from its `blind`/`micro` keyword and its two layers,
never from its `(drill)`, which KiCad writes as a sentinel (0.00001 mm) rather than a hole; the DRC gate's
hole floor applies to through vias and pads only. The section prints its drivers in two kinds, by how
likely the designer already knows: **hidden** drivers first, each with the figure, the standard, the tier
and the quote page's condition (a 0.25 mm via that flips the via option, a 0.1 mm hole with its
thickness-and-finish condition, parts on the back, Extended part types, the assembly class, the stackup
flags, HDI), then **chosen** drivers, one short line each (the layer count, the outline's size, the
through-hole parts: a line that teaches nothing on a 4-layer board the designer chose is read once). The
summary counts both ("2 hidden drivers, 3 chosen"), the RESULT line counts both, the JSON carries a
`kind` per driver, and nothing is hidden or thresholded. What the quote page prices that no file states
(copper weight, surface finish, colour, quantity, via covering, gold fingers, panelisation) is named once
in the section and left to the quote page; the section never prints a price or a suggestion.

## What a run looks like

Against the card-sorter power board (`sorter_pdb_v0`, 4 layers, 130 footprints, routed and clean, a
catalogue part on 66 of 67 BOM lines), with [examples/sorter_pdb_v0/bom.csv](examples/sorter_pdb_v0/bom.csv)
and `--online` (full output in [examples/sorter_pdb_v0/report.txt](examples/sorter_pdb_v0/report.txt)):

```
sorter_pdb_v0  -  KiCad 10.0.7  -  jlcpcb-assembly@2026.10  -  online  -  4 copper layers, 130 footprints  -  bom.csv: bom.csv
RESULT: FAIL  -  1 blocking, 2 warnings, 1 not checked, 4 cost drivers  -  exit 1
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
  Catalogue and stock (§1 §2 §13): 45 codes found, 0 blocking, 0 low-stock/mismatch, 0 not checked
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

ORDER (what moves the price off JLCPCB's standard tier; the quote page prices it)
  COST  Order: what moves the price (§13): 1 hidden driver (parts), 3 chosen (layers, size, through-hole) off JLCPCB's standard tier
        parts: 23 Extended part types (one loading fee each: C107083, C134838, C144394, C144395, C144397, C151074, C158012, C190083, C2042471, C249591, C25805, C2620, +11 more); the standard is Basic and Preferred Extended parts; per unique part type: Economic PCBA: a feeder-loading fee per unique Extended part, Basic and Preferred Extended parts exempt; [...]
        layers: 4 (its own price class)
        size: 110 × 75 mm (larger than 100 × 100 mm)
        through-hole: 18 parts to assemble
        note: on the standard tier: vias smallest via 0.3 mm hole, 0.6 mm diameter (0.3mm/(0.4/0.45mm)); smallest hole 0.3 mm (0.15 mm is the smallest standard drill); single-sided placement (110 parts on F.Cu); 1.6 mm thick
        note: not in the files: copper weight, surface finish (HASL, ENIG, OSP), board thickness beyond the stackup figure, colour, quantity, via covering and plating method, gold fingers, press-fit holes, blind slots, backdrill, outline tolerance, panelisation (mouse bites, V-cut); the quote page prices those
        note: JLCPCB assembles a minimum of 2 boards; order spares (§13)

NOT CHECKED
  Catalogue package fits the footprint (§1): 5 not compared
        C3819953 1935161 (J1, J2, J3, J4; bom.csv row 29, 30, 31, 32): Plugin,P=5mm on TerminalBlock_Phoenix_PT-1,5-2-5.0-H_1x02_P5.00mm_Horizontal:
            neither name is in the package table; to clear it, compare the drawing and add a "Package verified" note (date, initials, what was compared) on that bom.csv line
        ...

BY HAND BEFORE ORDERING
  - Fab assembly preview: rotation of 45 polarized or asymmetric parts (D5, D2, J5, C2, J16, L1, J2, D9, J15, J13, J11, U2, +33 more) (§4)
  ...

RESULT: FAIL  -  1 blocking, 2 warnings, 1 not checked, 4 cost drivers  -  exit 1
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
compares nothing: L3, which has no part and so carries the footprint name `preflight bom` writes for an open line, and Q2,
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
| ERC errors (KiCad's electrical-intent errors, such as an undriven power pin, are reported as warnings); a protected check the project excludes; the pin-conflict matrix no weaker than KiCad's | yes | `kicad-cli sch erc --format json --severity-all`, run under the preset's severities |
| DRC errors (warnings reported); a protected check the project excludes; the fab's minimums, and a violation of the project's own stricter constraint that still clears the fab's floor is a warning; a footprint without a courtyard is not checked | yes | `kicad-cli pcb drc --format json --severity-all --all-track-errors`, same |
| Unrouted connections | yes | same report, `unconnected_items` |
| Schematic / PCB parity: missing, extra or duplicate footprints, net conflicts, attribute and value mismatches, whatever severity KiCad gives them; a nickname-only footprint difference, a sheet-path-only net difference and a no-net pad on an unconnected pin are warnings, a missing skipped-prefix footprint keeps KiCad's severity, a padless extra footprint (logo, text) is a note; field-text and footprint-filter notes keep the project's severity | yes | same run with `--schematic-parity` |
| Board footprints belong to this schematic: each footprint's path names a symbol uuid that exists, under the same reference (on a sheet placed more than once, the reference of the instance the footprint's sheet chain names); a footprint without a path is board-only only when no symbol carries its reference | yes | `.kicad_pcb` footprint paths + `.kicad_sch` symbols, all sheets |
| DNP parts flagged on both schematic and board, absent from bom.csv | yes | `kicad-cli sch export bom` + the board file |
| Bought parts placed: every reference in the BOM has a footprint on the board and is not excluded from the board in the schematic | yes | schematic BOM export + the board file |
| bom.csv present, UTF-8, with the eight columns (missing: run `preflight bom`) | yes | `bom.csv` |
| Every BOM line has an LCSC code | yes | `bom.csv` |
| BOM lines "done": MPN, package, Basic/Extended, stock, datasheet | warn | `bom.csv` |
| bom.csv references match the schematic (none missing, unknown, duplicated or DNP); what is not bought is printed; a part with paste pads cannot hide behind a TP/H/FID name or an exclusion | yes | `bom.csv` + schematic BOM export + the board's pads |
| LCSC code: symbol field and bom.csv agree for every bought reference where both carry one; a field with a code whose line has none is the same finding (fix: run `preflight bom`); with no field at all, bom.csv is the only source and the gate says so | yes | schematic BOM export with the `init.FIELDS` spellings + `bom.csv` |
| bom.csv Value equals the schematic Value of every reference, spelling aside (`10uF` = `10 µF` = `10µF`, `100R` = `100Ω`, `4k7` = `4.7k`) | yes | `bom.csv` + schematic BOM export |
| Package fits the footprint (`--online`): the catalogue's package for each code against the footprint on the board. The bom.csv `Package` column records the chosen part's package but is not compared: offline it is a copy of the footprint name or of the catalogue string, and a column compared with its own source proves nothing. Names pick the candidates (0805 vs 1210, SOIC-8 vs SOIC-8 with exposed pad, SMD vs through-hole can, a stated pitch against SOIC's 1.27 mm) and, where both sides are footprints in KiCad's library, pad geometry decides (TSOT-23-6 fits SOT-23-6, VSSOP-8 fits MSOP-8 3x3, a 2.1 mm exposed pad on a 2.6 mm one is unknown, `TSSOP-14` alone is unknown because the library has it at two pitches). Same / different / unknown; unknown is listed as not checked and makes the result NOT VERIFIED unless a person signed for it; a `Package` that repeats the footprint name compares nothing | yes | `bom.csv` + schematic BOM export + catalogue record + KiCad's footprint library |
| Catalogue cross-check (`--online`): code exists, MPN matches, Manufacturer matches when bom.csv has it (a clone's MPN can equal the original's), stock ≥ 10× quantity, Basic/Extended as recorded; the summary says where the facts came from and when (`jlcpcb 2026-10-18`, `via the cache`); a code the catalogue could not be asked about, a line with no MPN to compare, or a record from the cache or older than the 7-day stock limit is not checked, never passed | yes / warn | JLCPCB cart endpoint, jlcsearch fallback, through the cache (`--catalogue parts.csv` first) |
| Catalogue category matches the reference prefix (`--online`): C capacitor, R resistor, D diode/TVS/LED, L inductor or ferrite, FB ferrite, Q transistor, J connector, F fuse, Y crystal, SW switch, U none of those; a capacitor's code on an LED line blocks; a prefix without a rule is not checked | yes | the record's category (JLCPCB), else its description |
| Catalogue description matches the BOM value (`--online`): every capacitance, inductance and resistance figure the value states within 1 % of the description's, and the part's voltage rating at least the value's (a 25 V part on a `100uF 16V` line fits); a figure the description lacks is not checked | yes | the record's description |
| Three fiducials on the front, placement origin set | warn | the board file |
| Board name and revision on silkscreen, a name beside every connector | warn | the board file |
| Two copper layers under a switching regulator | warn | the board file |
| Order: what moves the price off JLCPCB's standard tier (via and hole sizes, blind/buried vias, layers, outline size, double-sided placement, through-hole parts, Extended part types with `--online`, thickness, castellated / edge plating / impedance flags), hidden drivers first with the figure, the standard, the tier, its condition and the source date, the designer's chosen drivers (layers, size, through-hole parts) after them as one short line each; never the verdict | no (`cost`) | the board file (vias and their kind, pads, Edge.Cuts, stackup), `bom.csv`, the catalogue records; `preset.TIERS` |

`--strict` makes warnings block too. Everything the tool cannot see is listed under "by hand before ordering"
rather than silently passed: pick-and-place rotation in the fab's preview, footprint pin maps against the
datasheet, transients, enclosure fit.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

203 tests cover the BOM reader, the s-expression reader, the board reader (vias and their kind, holes, outline, stackup flags), the board gates, the order gate (every driver on an inline board, blind and buried vias by keyword and layers rather than by their sentinel drill, hidden drivers before chosen ones, the verdict untouched, the ORDER section and count, the JSON), the stock gate against a fake
catalogue (and the Manufacturer rule, cached and dated facts as not checked), the catalogue cache (read-back
within the stock limit, refetch after it, `--refresh`, offline up to the identity limit, the live-failure
fallback, the parts.csv source), `preflight bom` (the field spellings, grouping, the merge rules, notes
carried over and dropped, open lines, same inputs same bytes, exit codes, the `init` and `bom-template`
aliases with kicad-cli and the catalogue faked), the `bom-source` gate, the contract (verdicts and exit codes, what the gate owns and what the project may not switch
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
with the schematic or the catalogue) are closed as of 2026-10-17 and tested. Run on the author's own board and on a regression corpus of 21 public KiCad boards (`corpus/RESULTS.md`): the
corpus found three gate bugs (fixed) and showed that KiCad's electrical-intent ERC errors and the courtyard and
solder-mask checks blocked most of the boards that had actually been built, so the preset now runs those as
warnings; what still blocks fab-ready boards offline is DRC under the project's own stricter constraints,
which is the next open decision. Hierarchical schematics are read by kicad-cli for ERC, parity and the BOM
export and by the identity gate; variants are not handled. `preflight bom` (2026-10-18) writes bom.csv from the
LCSC code in each symbol's field and the catalogue record of that code, through a cache `check` reads too;
run on the 15 corpus boards with LCSC data it filled every line whose symbol named a code and left the rest
open, and the second run came from the cache (`corpus/RESULTS.md`, "preflight bom on the corpus"). See DESIGN.md for the roadmap, including what the reviews left open and the question of an
MCP server wrapper.
