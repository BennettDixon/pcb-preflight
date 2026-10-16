# pcb-preflight: design

**Status:** first cut, 2026-10-16. Scoping document for an open-source pre-flight gate for KiCad boards
drafted with AI help. The pitfalls it enforces are the ones in `VIBE_CODING_PCB_PITFALLS.md` (card-sorter
repo), written from two board families and referred to below by section (`§1` ... `§13`).

## 1. What it is

A command-line gate. Given a KiCad project directory it answers one question: **may this board be
ordered?** It runs KiCad's own checks through `kicad-cli`, reads the project's `bom.csv`, reads the board
file for the few things the fab will trip over, optionally asks the fab's catalogue about every part, and
prints a report with three parts: checked and left alone, findings, not checked. Exit 1 on a blocking
finding.

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
| G1 | ERC: zero errors (warnings listed) | §12 | `kicad-cli sch erc --format json --output erc.json <sch>`; `sheets[].violations[]` with `severity` | yes |
| G2 | DRC: zero errors (warnings listed by type) | §12 | `kicad-cli pcb drc --format json --all-track-errors --schematic-parity --output drc.json <pcb>`; `violations[]` | yes |
| G3 | Unrouted connections: none | §11 §12 | same report, `unconnected_items[]` (KiCad's connectivity, not the router's log) | yes |
| G4 | Schematic / PCB parity: no missing, extra or mismatched footprints, no net conflicts | §5 | same run; `schematic_parity[]`. If kicad-cli prints "Failed to fetch schematic netlist" the gate is reported as *not checked*, never as passed | yes |
| G5 | DNP parts: flagged DNP in the schematic *and* on the board, footprint still on the board, absent from bom.csv | §12 | `kicad-cli sch export bom --fields 'Reference,Value,Footprint,${DNP},${EXCLUDE_FROM_BOM}'` (one row per symbol) + the board's `(attr ... dnp)` | yes |
| G6 | `bom.csv` exists with columns Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet | §1 | `bom.csv` (header names matched loosely) | yes |
| G7 | Every BOM line has an LCSC code (`C` + digits) | §1 step 5, §12 | `bom.csv` | yes |
| G8 | Every BOM line is "done": MPN, package, Basic/Extended, stock-at-selection, datasheet | §1 (the done/not-done table), §2 | `bom.csv` | warns |
| G9 | bom.csv references equal the schematic's purchasable references: none missing, none unknown, none twice, no DNP; FID/TP/H/MH never expected | §1 §5 §12 | `bom.csv` + the schematic BOM export | yes |
| G10 | The BOM line's package agrees with the footprint assigned in the schematic (0805 vs 1210, SOT-23 vs SOT-23-5, SMA vs SMB, SOIC-8 vs TSSOP-8); packages without a standard short name (connectors, electrolytics, inductors) are not compared | §1 (the 10 µF 1210 story) | `bom.csv` + schematic BOM export; `bom.package_token()` | yes |
| G11 | Catalogue cross-check (`--online`): the code exists; catalogue MPN contains the BOM MPN; catalogue package agrees; stock ≥ 10 × quantity (warn) and > 0 (block); Basic/Extended as recorded (warn); count of Extended part types (fee) | §1 step 3, §2, §13 | JLCPCB `getComponentDetail`, jlcsearch fallback (see §6); a lookup failure is *not checked*, not a pass | yes / warns |
| G12 | Three fiducials on the front and an aux-axis origin set | §4 | the board file: footprints whose library id contains "Fiducial" or whose reference starts FID; `(setup (aux_axis_origin x y))` | warns |
| G13 | Board name and a revision on a silkscreen layer; a name beside every connector (visible Value on silk, or silk text within 15 mm) | §8 §10 | the board file: `gr_text` on `F.SilkS`/`B.SilkS`, the `Value` property's layer and `hide` flag | warns |
| G14 | Two copper layers with an inductor on the board | §9 | the board file: `(layers ...)` entries ending `.Cu`, references `L*` | warns |

Every run ends with a fixed "by hand before ordering" list with the §4 rotation preview (naming the
polarized and asymmetric parts on this board), the §3 pin maps, §2 datasheet checks, §7 transients, §10
enclosure, §11 autorouter review, §6 review doc and §13 spares. These are the pitfalls no file-level check
can see; printing them every time is what the "checked and left alone" style asks for.

### Design decisions

* **Refuse, don't warn.** Everything in the "Blocks" column exits 1. `--strict` promotes the warnings.
* **Read-only, verified.** `kicad-cli pcb drc` writes a `<board>.kicad_prl` beside a board that has none
  (observed on KiCad 10.0.7). So the default is to copy the project to a temporary directory (minus
  backups, `fab/`, lock files) and run there. The run against `sorter_pdb_v0` was checked with a
  before/after `stat` of every file: unchanged.
* **The BOM is a file beside the project, not symbol fields.** §1 step 5 asks for `<board>/bom.csv` so the
  parts list is reviewed and diffed like code. The tool therefore reconciles that file against the
  schematic (G9) rather than reading LCSC fields off symbols; a later version can accept both.
* **Standard library only.** Parsing `.kicad_pcb` is a 40-line s-expression reader; `pcbnew` Python is not
  required, so the tool runs under any Python, in CI, without KiCad's bundled interpreter.
* **Short, stable check ids** (`erc`, `bom-lcsc`, `stock`, ...) in the JSON output, for a CI step or a
  later MCP wrapper to key on.

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

`examples/sorter_pdb_v0/` holds the BOM used (the board's real state: values chosen, parts not, with the
two lines whose codes were verified live filled in) and the resulting `report.txt` / `report.json`.
Result: 13 gates pass, DRC warns twice (J17 silk clipped by the board edge), G7 blocks with 65 of 67 lines
lacking an LCSC code, G8 warns on the same lines, G11 confirms the two codes against the catalogue. That is
the honest state of the board: routed and clean, not orderable. Wall time about 7 s, of which kicad-cli is
about 5 s.

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
* Hierarchical sheets are already covered by kicad-cli; variants are not.

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
