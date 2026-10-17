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
is cheap to detect once someone writes the check down and makes it refuse rather than warn (§12).

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
| G2 | DRC: zero errors (warnings listed by type); same ownership, plus the board's minimum constraints raised to the fab's. A footprint without a courtyard is *not checked* (courtyards_overlap cannot see it) | §12 | `kicad-cli pcb drc --format json --severity-all --all-track-errors --schematic-parity --output drc.json <pcb>`; `violations[]`, `ignored_checks[]` | yes |
| G3 | Unrouted connections: none | §11 §12 | same report, `unconnected_items[]` (KiCad's connectivity, not the router's log) | yes |
| G4 | Schematic / PCB parity: no missing, extra or duplicate footprints, no net conflicts, footprint attributes and value as in the schematic (`preset.PARITY`). Those five block whatever severity the project gives them (KiCad ships them as warnings); the field-text and footprint-filter notes kicad-cli files alongside them keep the project's severity. If kicad-cli prints "Failed to fetch schematic netlist" the gate is *not checked* and the result is ERROR | §5 | same run; `schematic_parity[]` | yes |
| G4b | Board footprints belong to this schematic: every footprint's `(path "/<sheet uuid>/<symbol uuid>")` names a symbol that exists in the schematic (all sheets), under the same reference. KiCad's parity test matches by reference and passes a schematic regenerated with fresh uuids, the §5 incident itself; this gate reads the uuids. A footprint without a path is board-only (a hole, a logo) only when no symbol carries its reference; otherwise it is an unlinked part and blocks, so stripping the paths is no escape | §5 | `.kicad_pcb` footprints' `path`, `.kicad_sch` symbols' `uuid`, `instances` and `on_board` via `schematic.load_symbols()` | yes |
| G5 | DNP parts: flagged DNP in the schematic *and* on the board, footprint still on the board, absent from bom.csv | §12 | `kicad-cli sch export bom --fields 'Reference,Value,Footprint,${DNP},${EXCLUDE_FROM_BOM},${EXCLUDE_FROM_BOARD}'` (one row per symbol) + the board's `(attr ... dnp)` | yes |
| G5b | Bought parts placed: every reference that is in the BOM (not DNP, not excluded, not a FID/TP/H/MH) has a footprint on the board, and none is marked "exclude from board" in the schematic. KiCad's parity test skips an excluded symbol, so one schematic flag could take a bought part off the board while bom.csv kept its line | §5 §12 | the schematic BOM export + the board file | yes |
| G6 | `bom.csv` exists with columns Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet | §1 | `bom.csv` (header names matched loosely) | yes |
| G7 | Every BOM line has an LCSC code (`C` + digits) | §1 step 5, §12 | `bom.csv` | yes |
| G8 | Every BOM line is "done": MPN, package, Basic/Extended, stock-at-selection, datasheet | §1 (the done/not-done table), §2 | `bom.csv` | warns |
| G9 | bom.csv references equal the schematic's bought references: none missing, none unknown, none twice, no DNP. What is not bought (DNP, excluded from the BOM, FID/TP/H/MH by prefix) is printed every run, and an excluded or prefix-skipped reference whose footprint has paste pads blocks: the fab would solder a part there, so it is bought or DNP, not a name that starts with TP | §1 §5 §12 | `bom.csv` + the schematic BOM export + the board's pads | yes |
| G10 | Package fits the footprint, twice: the bom.csv `Package` against the footprint each reference has in the schematic (`bom-package`), and with `--online` the catalogue's package for each code against that footprint (`catalogue-package`). Verdicts same / different / unknown, see "Package names" below: *different* blocks and a `Package verified` note never changes that; *unknown* is listed under NOT CHECKED and makes the result NOT VERIFIED, unless the line carries a `Package verified` note, printed as "by hand" | §1 (the 10 µF 1210 story) | `bom.csv` + schematic BOM export + catalogue record; `packages.fits()` | yes |
| G11 | Catalogue cross-check (`--online`): the code exists; catalogue MPN contains the BOM MPN; stock ≥ 10 × quantity (warn) and > 0 (block); Basic/Extended as recorded (warn); count of Extended part types (fee) | §1 step 3, §2, §13 | JLCPCB `getComponentDetail`, jlcsearch fallback (see §6); a lookup failure is *not checked* and makes the result NOT VERIFIED, never a pass | yes / warns |
| G12 | Three fiducials on the front and an aux-axis origin set | §4 | the board file: footprints whose library id contains "Fiducial" or whose reference starts FID; `(setup (aux_axis_origin x y))` | warns |
| G13 | Board name and a revision on a silkscreen layer; a name beside every connector (visible Value on silk, or silk text within 15 mm) | §8 §10 | the board file: `gr_text` on `F.SilkS`/`B.SilkS`, the `Value` property's layer and `hide` flag | warns |
| G14 | Two copper layers with an inductor on the board | §9 | the board file: `(layers ...)` entries ending `.Cu`, references `L*` | warns |

Every run ends with a fixed "by hand before ordering" list with the §4 rotation preview (naming the
polarized and asymmetric parts on this board), the §3 pin maps, §2 datasheet checks, §7 transients, §10
enclosure, §11 autorouter review, §6 review doc and §13 spares. These are the pitfalls no file-level check
can see; printing them every time is what the "checked and left alone" style asks for.

### Design decisions

* **Refuse, don't warn.** Everything in the "Blocks" column exits 1. `--strict` promotes the warnings.
* **Four verdicts, and PASS is a contract** (`preset.py`). PASS (exit 0): every gate ran under the named
  preset and judged every item it saw. FAIL (1): a finding blocks. ERROR (2): a core gate (ERC, DRC,
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
  violation blocks, any other exclusion is honoured and counted. The protected set is KiCad's default errors
  that decide whether the fab can make and assemble the board as drawn, plus the five parity checks (KiCad:
  warnings), `pin_to_pin` (the matrix's on/off switch) and `missing_courtyard` (KiCad: ignore; a footprint
  without a courtyard is listed as *not checked* rather than blocked). Not owned on purpose:
  `lib_symbol_issues`, a library-lookup warning that would fail every CI runner without the libraries.
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
AP2112K rejected for `SOT-25-5`). The pattern that replaced it, in `pcb_preflight/packages.py`:

1. **Three verdicts.** `fits(footprint, part, mpn=None)` returns *same*, *different* or *unknown*, with the
   canonical names it read on each side and a reason. *Different* blocks the order. *Unknown* is never a
   pass: the gate prints its count in its own line and lists every unknown item under NOT CHECKED. A gate
   where nothing at all could be compared is a skip.
2. **Canonical names carry what changes the land pattern.** Chip sizes (`0603`); leaded families with pin
   count, exposed pad and SOIC body width (`SOIC-8-EP`, `SOIC-8-208MIL`); no-lead and QFP families with the
   body size when the name gives one (`QFN-16(3x3)`; JLCPCB writes it in brackets, KiCad in the name);
   SOT, SOD and TO with non-default pin counts and suffixes (`SOT-23-5`, `SOD-123F`, `TO-263-7`); diode
   outlines (`SMA`); electrolytic cans with mount, diameter and height (`CAN-SMD-D6.3xL7.7`, so a
   through-hole can on an SMD footprint is *different*). A string may name several packages
   (`SC-70(SOT-323)`); two strings fit when their sets meet. Not compared: pitch, exposed-pad size, TSSOP
   width, and everything without a standard name (connectors, inductor bodies, fuse clips).
3. **Spellings are data with a source.** `SYNONYMS` (whole spellings: `SOT-25-5`, `D2PAK`, `DO-214AA`) and
   `FAMILIES` (spellings that take a pin count: `SOP`, `ESOP`, `HTSSOP`) map vendor names to canonical ones,
   and every entry names the catalogue record or datasheet it was seen in. Nothing is added from memory:
   two entries carried over from the first cut (`DO-214AB`, `DPAK`) stayed only once a record was found
   for each (C224045, C10663).
4. **A fixture of real strings.** `tests/fixtures/packages.csv` pairs KiCad library footprint names with
   package strings copied from catalogue records, with the expected verdict and the record. The tests run
   every row in both directions and fail for a table entry that no row uses, so a new spelling cannot land
   without the record that justifies it. The file is the regression corpus: when a run trips over a vendor
   string, the string goes in as a row first.
5. **The part's own name.** Many KiCad footprints are drawn for one part and named after it
   (`JST_XH_B6B-XH-A_...`, `L_Bourns_SRP1245A`). When the package strings are *unknown* and the catalogue
   MPN starts with such a name token, the verdict is *same*, with that reason. It never overrides
   *different*, and a token must hold letters and digits and be five characters or more.
6. **A human's word, labelled as such.** An optional bom.csv column, `Package verified`, holds a note
   ("2026-10-16 BD: 1935161 drawing against the PT 1,5/2 footprint"). A line with a note turns *unknown*
   into "verified by hand: <note>", printed under the gate, never counted as the tool's own pass. It never
   turns *different* into anything: a mismatch the tool can see is fixed in bom.csv or on the board, and
   the report says the note does not apply. It is meant for parts no table can cover; a vocabulary gap is
   fixed in the table instead.
7. **One function for the gate and the assistant.** `fits()` and `read()` take strings and return plain
   data (`Fit.as_dict()`), so the MCP milestone (§8) exposes the same call an assistant drafting a BOM can
   ask: "does LCSC part X fit footprint Y?"

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
to 0.09 mm and says so in a note, G11 finds all 45 codes in stock at 10× or more. G10 compares 110 references offline and
45 code/footprint pairs online: 40 fit (U4's `SOT-25-5` through its table entry, the LMR33630's `ESOP-8` as
the exposed-pad SOIC-8, the JST and Bourns parts because their footprints are named for them), and 5 are
listed as not compared: the fuse clip, the 2920 polyfuse, the two Phoenix terminal blocks and the D-sub,
whose catalogue strings ("Plugin,P=5mm", "Push-Pull") name no package.
Those wait for a human's `Package verified` note. Wall time about 7 s plus about 0.3 s per catalogue
lookup.

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
* Left from the 2026-10-16 review of the first cut: the offline `bom-package` gate compares the Package
  column with the footprint name it was generated from (110 of 110 "same name" on the example board), so
  it proves little until the column holds the catalogue's string; *unknown* items should block rather than
  make the result NOT VERIFIED once a `Package verified` note is keyed to (reference, code, footprint);
  *same* and *different* should be decided from pad geometry rather than names where both sides resolve to
  library footprints (KiCad's SOT-23-6 and TSOT-23-6 have identical pads; VQFN/WQFN are QFN thicknesses;
  electrolytic can height is §10, not §1); bom.csv values should be compared with the schematic and the
  catalogue description (a capacitor's code on an LED line passes today).
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
is also cheap and already half-built (`board.py` reads pads; a `kicad_mod` reader is the same s-expression
code), and pairs with *datasheet pin-table extraction*, which is the hard one: pin tables in PDFs are
irregular, extraction needs a PDF text layer or OCR plus a model to read the table, and a wrong extraction
presented confidently is worse than none. So the sensible shape is: milestone 2 exposes `preflight_check`,
`part_lookup` and `footprint_pads` as MCP tools with the same read-only guarantee, and treats pin-table
extraction as a research item whose output is always shown to the human beside the datasheet drawing,
never asserted as a pass. The gate stays the product; the MCP server is how an assistant is made to run
it before it says "ready to order".
