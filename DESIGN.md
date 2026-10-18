# pcb-preflight: design

**Status:** first cut, 2026-10-16. Scoping document for an open-source pre-flight gate for KiCad boards
drafted with AI help. The pitfalls it enforces are the ones in `VIBE_CODING_PCB_PITFALLS.md` (card-sorter
repo), written from two board families and referred to below by section (`§1` ... `§13`).

## 1. What it is

A command-line gate. Given a KiCad project directory it answers one question: **may this board be
ordered?** It runs KiCad's own checks through `kicad-cli`, reads the project's `bom.csv`, reads the board
file for the few things the fab will trip over, optionally asks the fab's catalogue about every part, and
prints a report with three parts: checked and left alone, findings, not checked. The result is one of four
verdicts, each with its exit code (see "Four verdicts" below): PASS 0, FAIL 1, ERROR 2 (a core gate did not
run), NOT VERIFIED 3 (something could not be checked).

The thesis: the funded tools in this space (Flux, JITX, Quilter, atopile) compete on *generation*: a
netlist, a placement, a route. The failures Bennett's boards actually had were not generation failures.
They were a made-up part number, a package assumed instead of chosen, a schematic regenerated under a
routed board, a BOM exported with every part-number column empty. Each is a verification failure, and each
is cheap to detect once someone writes the check down and makes it refuse rather than warn (§12). The
corpus of public boards (§9) sharpened the second half: refusing on the wrong things is this product's
main failure mode, so the gate refuses only on what stops the fab building or placing the board as drawn,
or leaves the order ambiguous, and reports everything else.

## 2. What it is not

* **No generation, no routing, no export.** It never writes into the project. KiCad draws, the router
  routes, `export_fab.py` (or KiBot) writes the fab package; `preflight` only decides whether they may.
* **No GUI, no plugin.** It runs where CI runs. KiCad need not be open; `kicad-cli` is enough.
* **No electrical judgement.** It does not know a buck converter from a divider. The transient questions
  (§7), the layer-count decision (§9) and the pin maps (§3) stay with the human; the tool lists them under
  "by hand" every run so they are not forgotten.
* **No part choosing.** It checks that a part was chosen and that the choice is consistent with the
  board and the catalogue. Choosing is the designer's job (an MCP server could help; see §8 below).

## 3. The gates

Order of execution is the order a review reads: KiCad's verdicts first, then the board, then the BOM,
then the catalogue. "Blocks" means exit 1; "warns" means reported, and blocking only with `--strict`.

| # | Gate | Pitfall | Reads / runs | Blocks |
|:--|:--|:--|:--|:--|
| G1 | ERC: zero errors (warnings listed). The checks the gate owns run as errors whatever the project says, the pin-conflict matrix is no weaker than KiCad's default, and a protected violation the project excluded blocks (see "Tool-owned severities") | §12 | `kicad-cli sch erc --format json --severity-all --output erc.json <sch>`; `sheets[].violations[]` with `severity` and KiCad's `excluded` flag, `ignored_checks[]` | yes |
| G2 | DRC: zero errors (warnings listed by type); same ownership, plus the board's minimum constraints raised to the fab's. For track width, clearance, edge clearance, hole size, annular width and hole-to-hole, KiCad's message carries the measured figure; a violation whose figure still clears the fab's floor is the project's own stricter rule and is a warning, so only the fab's floor blocks (`checks.FLOORED`). A footprint without a courtyard is *not checked* (courtyards_overlap cannot see it) | §12 | `kicad-cli pcb drc --format json --severity-all --all-track-errors --schematic-parity --output drc.json <pcb>`; `violations[]`, `ignored_checks[]` | yes |
| G3 | Unrouted connections: none | §11 §12 | same report, `unconnected_items[]` (KiCad's connectivity, not the router's log) | yes |
| G4 | Schematic / PCB parity: no missing, extra or duplicate footprints, no net conflicts, footprint attributes and value as in the schematic (`preset.PARITY`). Those five block whatever severity the project gives them (KiCad ships them as warnings), except four forms the regression corpus (`corpus/RESULTS.md`) proved harmless on built boards: a footprint that differs from the symbol's only in its library nickname, a pad net that differs from the schematic's only in its sheet path (a sheet renamed after routing) and a no-net pad against an `unconnected-` pin are warnings; a missing footprint for a skipped reference prefix (TP, FID, H, MH) keeps KiCad's severity; an extra or duplicate footprint with no pads (a logo, text) is a note. The descriptions are parsed in their exact kicad-cli form, never guessed. The field-text and footprint-filter notes kicad-cli files alongside them keep the project's severity. If kicad-cli prints "Failed to fetch schematic netlist" the gate is *not checked* and the result is ERROR | §5 | same run; `schematic_parity[]` | yes |
| G4b | Board footprints belong to this schematic: every footprint's `(path "[/<sub-sheet uuid>...]/<symbol uuid>")` names a symbol that exists in the schematic (all sheets), under the same reference. KiCad writes the footprint path without the root sheet uuid while a symbol's instance paths carry it, so the instance a footprint belongs to is the one whose path, root dropped, ends in the footprint's sheet chain; on a sheet placed twice each footprint thus finds its own reference (`Symbol.reference_on()`; before this, 185 footprints on three hierarchical corpus boards were reported renamed). KiCad's parity test matches by reference and passes a schematic regenerated with fresh uuids, the §5 incident itself; this gate reads the uuids. A footprint without a path is board-only (a hole, a logo) only when no symbol carries its reference; otherwise it is an unlinked part and blocks, so stripping the paths is no escape | §5 | `.kicad_pcb` footprints' `path`, `.kicad_sch` symbols' `uuid`, `instances` and `on_board` via `schematic.load_symbols()` | yes |
| G5 | DNP parts: flagged DNP in the schematic *and* on the board, footprint still on the board, absent from bom.csv | §12 | `kicad-cli sch export bom --fields 'Reference,Value,Footprint,${DNP},${EXCLUDE_FROM_BOM},${EXCLUDE_FROM_BOARD}'` (one row per symbol) + the board's `(attr ... dnp)` | yes |
| G5b | Bought parts placed: every reference that is in the BOM (not DNP, not excluded, not a FID/TP/H/MH) has a footprint on the board, and none is marked "exclude from board" in the schematic. KiCad's parity test skips an excluded symbol, so one schematic flag could take a bought part off the board while bom.csv kept its line | §5 §12 | the schematic BOM export + the board file | yes |
| G6 | `bom.csv` exists with columns Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet | §1 | `bom.csv` (header names matched loosely) | yes |
| G7 | Every BOM line has an LCSC code (`C` + digits) | §1 step 5, §12 | `bom.csv` | yes |
| G8 | Every BOM line is "done": MPN, package, Basic/Extended, stock-at-selection, datasheet | §1 (the done/not-done table), §2 | `bom.csv` | warns |
| G9 | bom.csv references equal the schematic's bought references: none missing, none unknown, none twice, no DNP. What is not bought (DNP, excluded from the BOM, FID/TP/H/MH by prefix) is printed every run, and an excluded or prefix-skipped reference whose footprint has paste pads blocks: the fab would solder a part there, so it is bought or DNP, not a name that starts with TP | §1 §5 §12 | `bom.csv` + the schematic BOM export + the board's pads | yes |
| G9b | bom.csv `Value` equals the schematic `Value` of every reference, spelling aside (µ/u, Ω/ohm/R, 4k7/4.7k, spaces, case; `values.normalize()`). Nothing else is inferred: 100nF and 0.1uF are two spellings and the files use one | §1 | `bom.csv` + schematic BOM export | yes |
| G10 | Package fits the footprint (`--online`): the catalogue's package for each code against the footprint each reference has in the schematic (`catalogue-package`). The bom.csv `Package` column is not compared: offline it is a copy of the footprint name or of the catalogue string, and comparing a column with its own source proved nothing (the first cut printed "110 of 110 same name"; the offline gate was removed on 2026-10-17). Verdicts same / different / unknown, see "Package names" below: names pick the candidates and, where both sides are footprints in KiCad's library, the pads decide; *different* blocks and a `Package verified` note never changes that; *unknown* is listed under NOT CHECKED and makes the result NOT VERIFIED, unless the line carries a `Package verified` note, printed as "by hand". | §1 (the 10 µF 1210 story) | `bom.csv` + schematic BOM export + catalogue record + KiCad's footprint library; `packages.fits()` | yes |
| G11 | Catalogue cross-check (`--online`): the code exists; catalogue MPN contains the BOM MPN; stock ≥ 10 × quantity (warn) and > 0 (block); Basic/Extended as recorded (warn); the count of Extended part types is G15's line | §1 step 3, §2, §13 | JLCPCB `getComponentDetail`, jlcsearch fallback (see §6); a lookup failure is *not checked* and makes the result NOT VERIFIED, never a pass | yes / warns |
| G11c | Catalogue category matches the reference prefix (`--online`): C a capacitor, R a resistor, D a diode, TVS or LED, L an inductor or ferrite, FB a ferrite, Q a transistor, J a connector, F a fuse, Y a crystal, SW a switch, U none of those (`values.PREFIXES`, `values.CLASSES`, each keyword with the record it was seen in). A capacitor's code on an LED line blocks; a prefix without a rule, or a jlcsearch record (no category) under a U, is *not checked* | §1 §2 | the record's `firstSortName / secondSortName`, else its description | yes |
| G11d | Catalogue description matches the BOM value (`--online`): every F, H and Ω figure the bom.csv `Value` states is within 1 % of one in the record's description, and the part's voltage rating reaches the value's (a 25 V part on a `100uF 16V` line fits, a 16 V part on a `100uF 25V` line does not). A figure the description lacks is *not checked*; a value without figures (a part number) has nothing to compare | §1 §2 | the record's description; `values.compare()` | yes |
| G12 | Three fiducials on the front and an aux-axis origin set | §4 | the board file: footprints whose library id contains "Fiducial" or whose reference starts FID; `(setup (aux_axis_origin x y))` | warns |
| G13 | Board name and a revision on a silkscreen layer; a name beside every connector (visible Value on silk, or silk text within 15 mm) | §8 §10 | the board file: `gr_text` on `F.SilkS`/`B.SilkS`, the `Value` property's layer and `hide` flag | warns |
| G14 | Two copper layers with an inductor on the board | §9 | the board file: `(layers ...)` entries ending `.Cu`, references `L*` | warns |
| G15 | Order: what moves the price off JLCPCB's standard tier, one line per driver with the figure read from the files, the fab's standard, the sourced tier it lands in and its condition (`preset.TIERS`, read 2026-10-18). Drivers: the smallest through-via hole and diameter against the quote page's via options (how many vias are below the standard one); the smallest drilled hole, through vias and pads alike; blind, buried and micro vias as their own driver (HDI: a process JLCPCB prices, tier not yet sourced, `preset.TIERS_NOT_SOURCED`), read from the `blind`/`micro` keyword and the two layers and never from the `(drill)`, which KiCad writes as a sentinel (0.00001 mm on royalblue54l-feather's 183 blind vias), so it is never a via or hole figure and the DRC gate's hole floor (G2) leaves it as a warning; copper layers (1-2, 4, "High Precision" 6+); the outline's bounding box against the 100 × 100 mm class; parts to place on both sides (paste pads front and back, or a through-hole part on the back); through-hole parts to assemble (on a BOM line when bom.csv is read); Extended part types (`--online`; Preferred exempt); a layer count other than 2/4/6 or a thickness outside 0.8-1.6 mm; the stackup's castellated, edge-plating and impedance flags. Nothing inferred: no package or pitch from pads. The lines come in two kinds, ordered by surprise (`checks.CHOSEN`; `kind` per driver in the JSON): **hidden** first, with the condition text (via and hole tiers, HDI, double-sided placement, Extended part types, the assembly class, the stackup flags), then **chosen**, one short line each without it (layers, size, through-hole parts). A line that teaches nothing on a 4-layer board the designer chose is read once; a 0.25 mm via that flips a tier is the surprise, so it comes first. Every driver prints either way; the summary and the RESULT line count both kinds. Two fixed notes name what the quote page prices that no file states (`preset.NOT_IN_FILES`) and the assembly minimum (`ASSEMBLY_MIN`) | §13 | the board file: `(via [blind|micro] (size) (drill) (layers))`, pads' `(drill)` (an oval's smaller figure), Edge.Cuts graphics, `(general (thickness))`, `(setup (stackup ...))` flags; `bom.csv`; the catalogue records | no: status `cost`, the ORDER section, counted on the RESULT line, never the verdict or exit code, not promoted by `--strict` |

Every run ends with a fixed "by hand before ordering" list with the §4 rotation preview (naming the
polarized and asymmetric parts on this board), the §3 pin maps, §2 datasheet checks, §7 transients, §10
enclosure, §11 autorouter review and §6 review doc. These are the pitfalls no file-level check can see;
printing them every time is what the "checked and left alone" style asks for. The §13 spares reminder is
the order gate's note, beside the fab's assembly minimum.

### Design decisions

* **Refuse, don't warn.** Everything in the "Blocks" column exits 1. `--strict` promotes the warnings.
* **Four verdicts, and PASS is a contract** (`preset.py`). PASS means every gate ran and nothing stops the
  order; ORDER says what moves the price. PASS (exit 0): every gate ran under the named preset and judged
  every item it saw. FAIL (1): a finding blocks. ERROR (2): a core gate (ERC, DRC,
  unrouted, parity, identity, the schematic BOM export) did not run; nothing in the report is a pass.
  NOT VERIFIED (3): nothing blocks, but the catalogue was not asked (no `--online`) or did not answer, or a
  package could not be compared and nobody signed for it. The first cut printed PASS in all three of those
  cases: with kicad-cli failing, with the network down under `--online`, and offline with a made-up code.
* **Tool-owned severities, matrix and minimums.** kicad-cli applies the project's own settings, and the
  project is the thing under review: a check set to "ignore" in `.kicad_pro` is simply not run (in the
  first cut one such line hid 199 unrouted connections behind "0 connections still to route"); a zeroed
  `erc.pin_map` makes 224 output-to-output conflicts vanish; `min_track_width 0` passes a 0.05 mm track; a
  rule in `<name>.kicad_dru` with `(constraint track_width (min 0mm))` or `(severity ignore)` does the same
  under the board's own minimums. So, in the snapshot copy's `.kicad_pro` and before kicad-cli runs, the
  gate rewrites its protected checks to "error", raises every cell of the pin matrix to no weaker than
  KiCad's default, raises the board minimums and netclass clearances to no lower than JLCPCB's published
  capability for 1 oz copper (`preset.MINIMUMS_*`, source and date in the file), and leaves `.kicad_dru`
  out of the copy; the report prints what the project had set whenever it differed from KiCad's own
  defaults (`preset.KICAD_DEFAULT`, read from KiCad 10.0's source and its 19 templates), and says when a
  custom-rules file was present. Exclusions are read from the `excluded` flag kicad-cli puts on a violation
  (it keeps the original severity; the `exclusion` severity string never appears): an excluded protected
  violation blocks, any other exclusion is honoured and counted. The protected set is the KiCad default errors
  that decide whether the fab can make and assemble the board as drawn, plus the five parity checks (KiCad:
  warnings) and `missing_courtyard` (KiCad: ignore; a footprint without a courtyard is listed as *not
  checked* rather than blocked). Demoted to warnings, whatever the project says (`preset.ERC_DEMOTED`,
  `DRC_DEMOTED`, decided on the corpus evidence on 2026-10-17): KiCad's electrical-intent ERC errors (an
  unconnected pin, an undriven power pin, two outputs tied, a dangling label; the pin matrix is capped at
  warning with them), which blocked 15 of 21 public boards for a missing PWR_FLAG, and `courtyards_overlap`
  and `solder_mask_bridge`, which blocked 10 boards, 7 of them built and sold; none decides whether the fab
  can build the board, and `--strict` promotes them. Not owned on purpose: `lib_symbol_issues`, a
  library-lookup warning that would fail every CI runner without the libraries.
* **Read-only, verified.** `kicad-cli pcb drc` writes a `<board>.kicad_prl` beside a board that has none
  (observed on KiCad 10.0.7). So the gate always copies the project to a temporary directory (minus
  backups, `fab/`, lock files and `<name>.kicad_dru`, see the next bullets) and runs there; there is no
  in-place mode. The run against `sorter_pdb_v0` was checked with a
  before/after `stat` of every file: unchanged.
* **The BOM is a file beside the project, not symbol fields.** §1 step 5 asks for `<board>/bom.csv` so the
  parts list is reviewed and diffed like code. The tool therefore reconciles that file against the
  schematic (G9) rather than reading LCSC fields off symbols; a later version can accept both.
* **Standard library only.** Parsing `.kicad_pcb` is a 40-line s-expression reader; `pcbnew` Python is not
  required, so the tool runs under any Python, in CI, without KiCad's bundled interpreter.
* **Short, stable check ids** (`erc`, `bom-lcsc`, `stock`, `catalogue-package`, ...) in the JSON output,
  for a CI step or a later MCP wrapper to key on. Each check carries `details`, `unchecked` (items it ran
  on but could not judge) and `verified` (items a human vouched for).

### Package names: same, different or unknown

A footprint name and a catalogue package string name the same land pattern in different words: KiCad's
`SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm` is JLCPCB's `ESOP-8` for TI's LMR33630 and `SOIC-8-EP` for TI's
TPS5430; Diodes Inc. calls SOT-23-5 `SOT25` and JLCPCB prints `SOT-25-5`. The first cut compared short
tokens and treated anything it could not read as "not compared", silently. That hid two kinds of error at
once: real mismatches it could not see (an exposed pad dropped from `SOIC-8-1EP`, so a padless SOIC-8 passed
on the LMR33630's footprint; `SOD-123F` read as `SOD-123`) and false failures on correct parts (the genuine
AP2112K rejected for `SOT-25-5`). The second cut read names into canonical packages, and its review found
the names still deciding too much: KiCad's `TSOT-23-6` and `SOT-23-6` have identical pads and were called
different, `MSOP-8` and `VSSOP-8` 3x3 differ in pad width by 0.1 mm and were called different, two `SSOP-8`
footprints at 1.27 and 0.65 mm pitch were called the same. The pattern now, in `pcb_preflight/packages.py`
with `pcb_preflight/footprints.py`:

1. **Three verdicts.** `fits(footprint, part, mpn=None, library=None)` returns *same*, *different* or
   *unknown*, with the canonical names it read on each side, a reason and the rule that decided
   (`Fit.rule`, one of `RULES`). *Different* blocks the order. *Unknown* is never a pass: the gate prints its
   count in its own line and lists every unknown item under NOT CHECKED. A gate where nothing at all could
   be compared is a skip.
2. **Names pick the candidates, pads decide.** Each string is read into canonical names (point 3). The
   names alone give a verdict: *same* when the sets meet and nothing they state about pitch or body width
   disagrees, *different* when they do not meet or a stated pitch or width differs (`P2.54mm` against
   SOIC's 1.27 mm; `4.4x5mm` against `6.1x...`), *unknown* when one side says less than the other
   (`QFN-16` against `QFN-16(3x3)`). Given KiCad's footprint library (`--footprints`,
   `$KICAD_FOOTPRINT_DIR`, or the install the `kicad-cli` in use belongs to; `packages.Library` indexes
   the package libraries by canonical name), each side is then resolved to library footprints: the one
   footprint the string names, else every footprint that reads as the same canonical name at the same
   pitch and width where the string gives them. Where both sides resolve, `footprints.same_pads()`
   compares copper pads (SMD or through-hole, position within 0.1 mm, size within 0.15 mm, drill, paste,
   in any of four rotations; pad numbers and shapes are not compared, the pin map is §3): a pad set that
   matches one on the other side is *same* whatever the names said (TSOT-23-6 on SOT-23-6, VSSOP-8 on
   MSOP-8 3x3, a 6.3x7.7 can on `CP_Elec_6.3x5.8`, whose height is §10); pads that match nothing are
   *different* when the names also disagree and *unknown* when the names agreed (two QFN-20 4x4 footprints
   with 2.6 and 2.1 mm exposed pads). A string without dimensions that resolves to more than one land
   pattern in the library (`TSSOP-14` at 0.65 and 0.4 mm pitch, `VSSOP-8` at 3x3 and 2.3x2, `SSOP-8` at
   0.65 and 1.27 mm) does not say which. When the other side is one footprint KiCad has (the board's own)
   and its pads match one of those land patterns, the board has said which and the verdict is *same*
   (`Fit.picked` records the ambiguity settled; sh-rpi, sonatino: three sold-board lines); when the board's
   footprint is not in KiCad's library, or its pads match none of them, it is *unknown*. A pad is one piece
   of copper: pads sharing a number that touch are one pad and a via-in-pad hole numbered like the exposed
   pad is not a pad (`footprints.stack()`: TI's `TI_SO-PowerPAD-8_ThermalVias` has 19 pad entries and 9
   pads). Without a library the names alone decide and the gate's note says so. The library is read,
   never written, and the index of 4,500 footprints (the package libraries and `Crystal`) is built in well
   under a second.
3. **Canonical names carry what changes the land pattern.** Chip sizes (`0603`); leaded families with pin
   count, exposed pad and SOIC body width (`SOIC-8-EP`, `SOIC-8-208MIL`), plus the pitch and body width
   where the name states them; no-lead and QFP families with the body size when the name gives one
   (`QFN-16(3x3)`; JLCPCB writes it in brackets, KiCad in the name); SOT, SOD and TO with non-default pin
   counts and suffixes (`SOT-23-5`, `SOD-123F`, `TO-263-7`); diode outlines (`SMA`); electrolytic cans with
   mount, diameter and height (`CAN-SMD-D6.3xL7.7`, so a through-hole can on an SMD footprint is
   *different*; two heights at one diameter are left to the pads, since KiCad draws some alike and some
   not). Thickness designators fold into their family with a source: TSOT is SOT (JEDEC MO-193 keeps the
   MO-178 land pattern), VQFN, WQFN, TQFN and UQFN are QFN (JEDEC MO-220). A SOIC without a stated pitch
   is taken at JEDEC MS-012's 1.27 mm (`STANDARD_PITCH`), which tells the 2.54 mm SOPs KiCad files under
   the same family name apart. A string may name several packages (`SC-70(SOT-323)`); two strings fit when
   their sets meet. Not compared by name: exposed-pad size (the pads catch it), can height, and everything
   without a standard name (connectors, inductor bodies, fuse clips).
4. **Spellings are data with a source.** `SYNONYMS` (whole spellings: `SOT-25-5`, `D2PAK`, `DO-214AA`,
   TI's `SOT-5X3`), `FAMILIES` (spellings that take a pin count: `SOP`, `ESOP`, `HTSSOP`, `TSOT`, `VQFN`,
   `LQFN`, `TDFN`) and `PATTERNS` (shapes: EasyEDA's `C0402`, Diodes' `WQFN4040-24`, TI's `SOT-23-Thin-6`
   and `SO-PowerPAD-8`, JLCPCB's crystal `SMD3225-4P` and tantalum `CASE-A-3216-18`, a BGA's ball layout
   before its body) map vendor names to canonical ones, and every entry names the catalogue record,
   datasheet or `.kicad_mod` file it was seen in; the 2026-10-17 corpus run supplied the last eleven, each
   from a built board (`corpus/RESULTS.md`). Nothing is added from memory: two entries carried over from the first cut (`DO-214AB`, `DPAK`)
   stayed only once a record was found for each (C224045, C10663).
5. **A fixture of real strings.** `tests/fixtures/packages.csv` pairs KiCad library footprint names with
   package strings copied from catalogue records, or with other KiCad footprint names for the pairs the
   review named, each with the record or the `.kicad_mod` files it came from and two expectations: the
   verdict and rule with the footprint library (pads decide) and the verdict and rule from names alone, as
   on a machine without KiCad. The tests run every row in both directions and both modes (the library
   mode where KiCad is installed), and fail for a table entry, a standard pitch or a rule that no row
   exercises, so a new spelling cannot land without the record that justifies it. The file is the
   regression corpus: when a run trips over a vendor string, the string goes in as a row first.
6. **The part's own name.** Many KiCad footprints are drawn for one part and named after it
   (`JST_XH_B6B-XH-A_...`, `L_Bourns_SRP1245A`). When the package strings are *unknown* and the catalogue
   MPN starts with such a name token, the verdict is *same*, with that reason. It never overrides
   *different*, and a token must hold letters and digits and be five characters or more.
7. **A copied name is not a comparison.** `bom-template` writes the footprint name into the `Package`
   column as a placeholder, and the first cut compared that column with the footprint it came from
   ("110 of 110 same name"). An offline gate on the column cannot tell a copied name from a catalogue
   string that happens to equal it (Q2's `SOT-23`), and teaching it to guess would be exactly the kind of
   mapping that does not hold, so the gate was removed (2026-10-17) rather than refined: the column stays
   as the record of the chosen part, and the comparison that matters is the catalogue's own string under
   `--online`.
8. **A human's word, labelled as such.** An optional bom.csv column, `Package verified`, holds a note
   ("2026-10-16 BD: 1935161 drawing against the PT 1,5/2 footprint"). A line with a note turns *unknown*
   into "verified by hand: <note>", printed under the gate, never counted as the tool's own pass. It never
   turns *different* into anything: a mismatch the tool can see is fixed in bom.csv or on the board, and
   the report says the note does not apply. It is meant for parts no table can cover; a vocabulary gap is
   fixed in the table instead.
9. **One function for the gate and the assistant.** `fits()` and `read()` take strings and return plain
   data (`Fit.as_dict()`), so the MCP milestone (§8) exposes the same call an assistant drafting a BOM can
   ask: "does LCSC part X fit footprint Y?"

### Values: the schematic, the BOM and the catalogue agree on what the part is

A BOM line whose code points at the wrong kind of part passed every gate above: the package fits (an 0805
capacitor on an 0805 LED footprint), the MPN matches the code, stock is fine. Three checks in
`pcb_preflight/values.py` close that, each small and each with its fixture:

1. **bom.csv against the schematic** (`bom-value`, always). `normalize()` folds the spellings that mean one
   value (µ and u, Ω and ohm and R, `4k7` and `4.7k`, spaces, case) and the two strings must then be equal.
   Nothing else is inferred, so `100nF` and `0.1uF` differ and the designer picks one spelling for both
   files. The example board's 110 references pass.
2. **Reference prefix against the catalogue's category** (`catalogue-category`, `--online`). JLCPCB's record
   carries `firstSortName / secondSortName` ("Capacitors / Multilayer Ceramic Capacitors MLCC - SMD/SMT");
   its `componentDesignator` is not used, since JLCPCB files inductors, connectors, fuses and MOSFETs under
   "U". `PREFIXES` maps C, R, D, LED, L, FB, Q, J, F, Y and SW to classes and `CLASSES` maps each class to the
   category keywords it was seen under, every keyword with its record. U is the one negative rule: its
   category must not be a passive, discrete or electromechanical class, with "array", "driver" and "module"
   categories exempt from the diode and transistor test (a Darlington array and an LED driver are ICs).
   A jlcsearch record has no category, so its description (which ends in the category words) is searched
   instead, except under U, which is then *not checked*. A prefix without a rule (K, T, X, ...) is *not
   checked* and says so.
3. **Value figures against the catalogue description** (`catalogue-value`, `--online`). `quantities()` reads
   the F, H, Ω and V figures a value or a description states ("100nF 50V X7R" -> 100 nF, 50 V; "60Ω@100MHz
   6A 9mΩ" -> 60 Ω, 9 mΩ), reading a unitless `22k` or `4k7` as ohms on a resistor line only and skipping
   figures glued to a sign or an identifier (`+12V` in an LED's "green +12V" is the net it shows; `-100M`
   in SRP1245A-100M is a part number; the first run blocked three LEDs on exactly that before the rule).
   `compare()` then requires every F, H or Ω figure the value states to be within 1 % of one in the
   description, and the description's highest voltage to reach the value's: the rating is a floor, so the
   example board's C5 (`100uF 16V` on the 25 V part C4 uses) passes and a 16 V part on a 25 V line blocks.
   A figure the description lacks is *not checked*; a value without figures (a part number) has nothing
   to compare and is counted as such. Tolerance, current and power are not compared. The voltage floor
   accepts a higher-rated part silently, and a higher rating often means a larger body, which is the
   package gate's question, not this one's: this line means "the figures agree", not "the parts are
   interchangeable".

`tests/fixtures/catalogue.csv` holds the records these rules were read from (20 JLCPCB records fetched on
2026-10-16/17, description and category verbatim) paired with bom.csv lines and the verdict each gate must
give; the tests fail for a prefix or a category keyword that no row exercises.

## 4. Prior art (verified 2026-10-16)

Star counts and dates from the GitHub API on the day; feature claims from each project's README or docs.

| Project | What it is | Overlap | What it does not do |
|:--|:--|:--|:--|
| [KiBot](https://github.com/INTI-CMNB/KiBot) (INTI-CMNB, 753 stars, active) | Fabrication/documentation automation with YAML config and CI Docker images. Preflights: `erc`, `drc`, `check_fields`, `check_zone_fills`, `update_xml`, `fill_zones`, ...; outputs include position files with JLCPCB rotation corrections (`rot_footprint` filter, `JLCPCB Rotation Offset` field) and BOMs with an LCSC column | ERC/DRC as preflights that stop the run; `check_fields` can assert that a field exists or matches a regex per component | No notion of a BOM *file* reconciled against the schematic; no package-vs-footprint check; no catalogue lookup (stock, MPN, Basic/Extended); no "not checked / by hand" output; configuration-heavy (a YAML per project) where this tool has one command |
| [Bouni/kicad-jlcpcb-tools](https://github.com/Bouni/kicad-jlcpcb-tools) (2,110 stars, active, KiCad 7–10) | A pcbnew GUI plugin: downloads the JLCPCB parts database, lets you assign LCSC codes per footprint, writes Gerbers, BOM and CPL with rotation corrections | Assigns and stores LCSC codes; shows stock and price | Needs the KiCad GUI; its `kicad_drc.py` counts violations via the pcbnew SWIG report and skips the unconnected-pads section; nothing refuses an export; no ERC, no parity, no reconciliation with a reviewed BOM file |
| [lamaalrajih/kicad-mcp](https://github.com/lamaalrajih/kicad-mcp) (527 stars, last push 2025-10) | MCP server: project listing, DRC via kicad-cli with history, BOM analysis, netlist, pattern recognition | DRC via kicad-cli | No ERC, no unrouted check, no parts/stock, no gate semantics (an assistant may read the DRC and still proceed) |
| [mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) (2,765 stars, active) | MCP server oriented to *driving* KiCad: schematic and PCB editing, routing, FreeRouting, JLCPCB part search docs | JLCPCB parts search | Generation-side; no pre-order gate |
| [Seeed-Studio/kicad-mcp-server](https://github.com/Seeed-Studio/kicad-mcp-server) (158 stars) | MCP server: `run_erc`, `run_drc`, `detect_pin_conflicts` via kicad-cli, netlist tracing, light editing | ERC/DRC as tools | No BOM/catalogue checks, no parity, no refusal |
| [oaslananka/kicad-mcp-pro](https://github.com/oaslananka/kicad-mcp-pro) (132 stars, active) | MCP server with read-only / build / release profiles, ERC/DRC through KiCad's engines, JLCPCB public catalogue for sourcing | Closest in spirit: a "release" profile with human-gated handoff | An MCP server, so the gate is whatever the assistant chooses to call; no documented BOM-file reconciliation or package-vs-footprint check |
| [l3wi/jlc-cli](https://github.com/l3wi/jlc-cli) (`@jlcpcb/cli`, `@jlcpcb/mcp` on npm; unofficial despite the scope name) | Terminal UI and MCP server for searching JLCPCB/LCSC parts and converting EasyEDA symbols/footprints to KiCad | Part search with stock filters | No board verification at all |
| [yaqwsx/jlcparts](https://github.com/yaqwsx/jlcparts) (838 stars) | Parametric search over JLCPCB's catalogue, data rebuilt by CI from JLCPCB's spreadsheet into per-category JSON in the browser | The catalogue data | No per-part HTTP endpoint; the whole shard loads client-side |
| [tscircuit jlcsearch](https://docs.tscircuit.com/web-apis/jlcsearch-api) | Hosted JSON API over an in-stock mirror of the JLCPCB catalogue | Used here as the fallback lookup | Full-text search by MPN is unreliable (SS54 returns unrelated parts); exact LCSC code works |

**What this tool does that none of them do:** treat the reviewed BOM file as the source of truth and
reconcile it both ways against the schematic; compare the chosen part's package with the footprint on the
board; cross-check MPN, package, library type and stock against the fab's live catalogue; refuse rather than
report; and print what was checked and left alone and what still has to be checked by hand. It is also
the only one of these that is read-only by construction and runs without pcbnew's Python or the GUI.

## 5. The test run

`examples/sorter_pdb_v0/` holds the BOM used and the resulting `report.txt` / `report.json`. The first
run had values chosen and parts not (65 of 67 lines without an LCSC code). The BOM now has a catalogue part
on 66 of 67 lines, each filled from the JLCPCB record (MPN, code, Basic/Extended, stock, datasheet URL).
The open line is L3, 15 µH SRP1245A-150M: JLCPCB does not carry it, and the in-stock alternatives are
other makers' bodies the footprint was not drawn for, so the line stays empty rather than holding a
wrong part. Result: G7 blocks on L3 alone, G8 warns on the same line, DRC warns twice (J17 silk clipped by
the board edge), G4b finds all 130 footprints naming a symbol in the schematic (the same board with every
schematic uuid regenerated fails it with 130 orphaned, while kicad-cli's parity test still reports 0
mismatches), G5b finds every bought reference placed, the preset raises the project's `min_clearance 0`
to 0.09 mm and says so in a note, G9b finds every bom.csv Value equal to the schematic's, G11 finds all 45
codes in stock at 10× or more, G11c files all 66 lines under the category their prefix means, G11d finds
the 35 lines that state a figure agreeing with their description and 31 stating none. G10 compares 45
code/footprint pairs online (the offline comparison of the `Package` column was removed, see "Package names" 7): 40 fit (U4's `SOT-25-5` through its table entry, the LMR33630's `ESOP-8` as the
exposed-pad SOIC-8, the JST and Bourns parts because their footprints are named for them, the rest by pads
against KiCad's library), and 5 are listed as not compared: the fuse clip, the 2920 polyfuse, the two
Phoenix terminal blocks and the D-sub, whose catalogue strings ("Plugin,P=5mm", "Push-Pull") name no
package. Those wait for a human's `Package verified` note. Wall time about 7 s plus about 0.3 s per
catalogue lookup; reading the footprint library adds a few tenths of a second.

## 6. Stock lookup: endpoints found

There is no documented public JLCPCB parts API without a login. Three unauthenticated endpoints answered
on 2026-10-16; the tool uses the first and falls back to the second.

1. **JLCPCB cart service** (undocumented, what jlcpcb.com's own parts pages call):
   `GET https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail?componentCode=C14663`
   returns `data.stockCount`, `componentLibraryType` (`base` / `expand`), `componentModelEn` (MPN),
   `componentBrandEn`, `componentSpecificationEn` (package), `dataManualUrl`, `leastNumber`, `lossNumber`
   (attrition), price ladders. An unknown code answers `{"code":400,"message":"Parameter exception."}`.
   Verified on C1525, C14663, C22452 (Basic) and C2040, C8323 (Extended). A POST sibling,
   `https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList`, searches by
   keyword and returns the same fields plus `preferredComponentFlag`.
2. **tscircuit jlcsearch** (community, documented):
   `GET https://jlcsearch.tscircuit.com/api/search?q=C14663&limit=5` returns `components[]` with `lcsc`
   (integer), `mfr`, `package`, `is_basic`, `is_preferred`, `stock`, `price`. Exact by code; the tool
   filters on `lcsc == int(code)`. Freshness and rate limits are not documented.
3. **LCSC's own store** `GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C1525` works but
   reports LCSC's warehouse stock (0 for C1525 while JLCPCB assembly stock was 24 million), so it is the
   wrong number for an assembly order and is not used.

Not usable: yaqwsx/jlcparts (no per-part endpoint; `.../data/index.json` is 404), KiCad's own HTTP library
feature (reads a database you host, does not query JLCPCB). Both endpoints above can change without notice;
`stock.py` is 80 lines and `checks.stock_check()` takes the lookup as a parameter, so a replacement is a
one-function change and the unit test exercises the gate with a fake catalogue.

## 7. Roadmap (not done)

* Accept LCSC/MPN symbol fields as an alternative BOM source, with G9 still reconciling.
* A rotation table (KiBot's and Bouni's corrections are both public) so G12 can also say which parts the
  fab's preview will turn; the preview itself stays by hand.
* Pin-map evidence: a per-footprint "checked against datasheet on <date>" column in bom.csv that G8 can
  require (§3), which turns a by-hand item into a recorded one.
* A `--fab pcbway` switch; the BOM columns are the same, the catalogue is not.
* Hierarchical sheets are covered: kicad-cli reads them for ERC, parity and the BOM export, and G4b follows
  `Sheetfile` references; variants are not.
* Left from the 2026-10-16 review of the first cut, after the package and value work of 2026-10-17 closed
  the rest (pad geometry decides where both sides are library footprints, a copied `Package` compares
  nothing, values are compared with the schematic and the catalogue): *unknown* items should block rather
  than make the result NOT VERIFIED once a `Package verified` note is keyed to (reference, code,
  footprint). Still open around those gates: a catalogue string that is also the footprint's name (Q2's
  `SOT-23` on `SOT-23` in the example BOM) is taken for a copied placeholder and not compared; prefixes K,
  T, X, BT, RV and RN have no category rule (no record was fetched for them); a jlcsearch
  record carries no category, so a U under the fallback is not checked; JLCPCB spellings seen but not yet
  in the table because no fixture pair needed them: `MLF-16` (Microchip's QFN), `DHVQFN-20`, `SOP-4-2.54mm`;
  through-hole radial cans (`CP_Radial_D10.0mm_P5.00mm`) are not read, so `Plugin,D10xL12.5mm` on one is
  unknown; `SOT-23W` reads as SOT-23 by name and only the pads tell it apart; tolerance, current and power
  figures are not compared; the footprint library is KiCad's own, so a project-local copy of a library
  footprint resolves only when it keeps the library's name.
* Left from the second review (2026-10-16, after the contract): JLCPCB's limits for 2 oz copper and for pad
  (not via) hole-to-hole spacing are not modelled, since the files do not say the copper weight; silkscreen
  text minimums are not raised (not fab-blocking); `preset.KICAD_DEFAULT` is KiCad 10.0's and needs a row
  per KiCad release; a `--verbose` flag for the per-item pass notes the JSON already carries; a
  `Package verified` note keyed to (reference, code, footprint) so it goes stale when the part changes.

## 8. Is an MCP server wrapper a sensible second milestone?

Yes, but as a thin wrapper around the same checks, and only after the gate has earned trust on a few
orders. The three tools named in the brief are different in kind. *Parts lookup* (G11's `stock.lookup`)
is a natural MCP tool: an assistant drafting a BOM can call it per line and write back the verified MPN,
package, library type, stock and datasheet URL, which is exactly the "the AI proposes, the catalogue
confirms" loop of §2, and it costs nothing beyond exposing an existing function. *Footprint pad-map read*
is also cheap and now built (`footprints.read_pads()` reads a `.kicad_mod`; `board.py` reads a board's pads), and pairs with *datasheet pin-table extraction*, which is the hard one: pin tables in PDFs are
irregular, extraction needs a PDF text layer or OCR plus a model to read the table, and a wrong extraction
presented confidently is worse than none. So the sensible shape is: milestone 2 exposes `preflight_check`,
`part_lookup` and `footprint_pads` as MCP tools with the same read-only guarantee, and treats pin-table
extraction as a research item whose output is always shown to the human beside the datasheet drawing,
never asserted as a pass. The gate stays the product; the MCP server is how an assistant is made to run
it before it says "ready to order".

## 9. Principles, after the corpus (2026-10-17)

The first corpus run (`corpus/RESULTS.md`, 21 public KiCad boards, 8 of them ordered, built and sold)
failed every board, mostly on checks a fab does not care about. What that taught, written down so the next
rule change is measured against it:

* **Refuse only on what the fab or the order needs.** A check blocks when a violation would stop the fab
  building or placing the board as drawn (connectivity, the fab's own minimums, the outline, parity between
  schematic and board) or would leave the order ambiguous (which part, which footprint, which reference).
  Everything KiCad reports about whether the circuit is what the designer meant is reported as a warning;
  `--strict` is for the designer who wants those to block too. The protected and demoted sets in
  `preset.py` are that line, and every change to them cites a corpus board.
* **Nothing unrun is a pass.** The four verdicts stay as they are: ERROR when a core gate did not run,
  NOT VERIFIED when anything could not be judged, PASS only when every gate ran and judged every item.
* **The project under review does not configure the gate.** Severities, the pin matrix, the fab minimums
  and custom rules are the preset's in the snapshot copy; the report says what the project had set.
* **Geometry over names, and names over nothing.** Where both sides resolve to KiCad library footprints the
  pads decide; the string tables exist for catalogue spellings that resolve to nothing, and a new entry
  needs a corpus board that needs it, not a guess about what a vendor might write.
* **Facts are filled in, never chosen.** The planned `preflight init` reads the part a person or an agent
  already put in the symbol fields and fills bom.csv from the catalogue record; it never proposes a part.
  The MCP server exposes the checks and lookups, never a sign-off.
* **The corpus is the regression suite for rules.** `tests/test_corpus.py` freezes the triaged state; a
  rule change that moves a board is expected to break it and is accepted with the new triaged number, and
  a change that only moves the author's own board is not evidence.
* **What is not added:** part suggestion; an offline gate that cannot tell a copied value from a real one
  (the offline Package comparison was removed for this); new flags, since policy lives in the named, dated
  preset; a model in the verdict path; a warning tier nobody is required to act on.

The corpus's "whose rule is it" item is closed the same way (2026-10-17): DRC blocked the project's own
stricter constraints as if they were the fab's (`drill_out_of_range` on four boards whose designers set a
0.3 mm minimum hole). The gate now reads the measured figure from KiCad's message and blocks only when it
is under `preset.minimums()`; a figure that clears the fab's floor is a warning. What still fails in the
corpus after that is the list of true findings and the fab's own edge-clearance figure.

The ORDER leg (2026-10-18) draws the last line: **the floor is the fab's absolute buildable minimum, and
everything above it that the fab prices is a cost tier, not a finding.** JLCPCB's 0.1 mm hole is "more
costly!" and conditional (1.0 mm or thinner, ENIG or OSP), not unbuildable, so `min_through_hole_diameter`
moved from the smallest standard drill (0.15) to the smallest tier (0.10); jetson-thor-baseboard and
royalblue54l-feather, both built, stopped failing on it and gained an ORDER line instead (royalblue's 183
`(via blind ...)` carry a 0.00001 mm `(drill)`, a sentinel the gate reads by keyword and layers as a blind
via, never as a hole). The rules of that section, so the next driver is measured against them:

* **A fifth status, `cost`, that never reaches the verdict.** Not `--strict` either: a user who wants
  "standard tier only" gets a preset variant when one is asked for, not a flag.
* **One line per driver: the figure found, the fab's standard, the sourced tier, its condition, the source
  key and the read date.** Never a dollar amount or a multiplier (they move with exchange rates and
  promotions), never a suggestion, never a live read of the quote page; the tiers are dated data in the
  preset, fab-specific by design, so a second fab is a second table.
* **A driver is listed only when it is read from the files** (a via's `(drill)`, a pad's, the outline, the
  stackup flags, the BOM), has a sourced tier, is the fab's rather than the gate's, and needs no catalogue
  lookup beyond the Basic/Extended word the stock gate already fetched. A package size inferred from pads
  would be a guess, so the 0402-and-finer row is not a driver, and the quote-page options no file states
  (copper weight, finish, colour, quantity) are named once as not in the files.
* **Ordered by surprise, hiding nothing.** Hidden drivers (a via or hole tier with its condition, parts on
  the back, Extended part types, the assembly class, the stackup flags, blind/buried vias) print first and in
  full; the designer's chosen drivers (layers, size, through-hole parts) print after them as one short line
  each. No driver is dropped or thresholded; the split is reading order, not a filter.
* **Evidence first.** `corpus/RESULTS.md` "ORDER on the corpus" says, per board, which drivers the files
  show and whether the built boards' drivers match what their repositories say was ordered.
