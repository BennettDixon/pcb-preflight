# Corpus results and triage (2026-10-17)

What the gate says about 21 public KiCad boards it had never seen, and what of that is right. The runs are
the files under `results/` (offline, every board) and `results/online/` (the 15 boards whose bom.csv carries
LCSC codes), produced by `sh corpus/run.sh --online` with kicad-cli 10.0.7 and preset `jlcpcb-assembly@2026.10`
on 2026-10-17: first with pcb-preflight at main `3963b9a` (after PR #2: pad geometry and value gates), which
is the run the triage below sorts, then again the same day with the three gate fixes the triage asked for
(identity, parity, package reader: "Rule changes" items 1, 3 and 6, made in the working tree on top of main
`e88e6b4`), which is what `results/` holds now. Where a number moved between the two runs, the row or
paragraph says so and why: a bug was fixed, no policy changed (items 2, 4 and 5 are untouched). The boards,
their commits, licences and why each is here are in `README.md` and `index.csv`; the bom.csv files the runs
used are under `boms/` (built by `make_boms.py` from each board's own LCSC and part-number symbol fields).

Every claim below names the board and the report line it comes from; the full lines are in the `.txt`
reports. Counts of 199 for one violation type are kicad-cli's per-type cap, not a count.

## Headline

* **Every board fails** on the first run: 21 of 21 offline, 15 of 15 online. No board in the corpus reaches
  PASS or NOT VERIFIED, including the eight that were ordered, assembled and sold. After the fixes, 20 of 21
  fail offline: canfd-mc (ordered and assembled at JLCPCB) is NOT VERIFIED offline, the first board to leave
  FAIL, since its one blocking item was the no-connect `net_conflict` below; online it still fails on a
  true finding (U4 out of stock today).
* **Of the 11 boards believed fab-ready, 3 are blocked offline by nothing but false failures, noise and
  unknowns** (canfd-mc: one parity item; soldiercrab: 215 items, all false; openjbod-rp2040: false and
  noise plus 5 unrouted pins on its ATX connector that KiCad counts and the designer evidently did not).
  Four more are blocked by false failures and noise plus a borderline true item: copper within 0.2 mm of
  a routed edge on a track or pad (pocketpd 2, sonatino 5, royalblue 28: JLCPCB's published figure, and
  the fab built all three) and, on sh-rpi, one BOM line for hand-fitted supercaps the project marks
  `JLCPCB_IGNORE` (after the fixes sh-rpi's 33 parity items are warnings and its DRC and bom-lcsc lines are
  what block; soldiercrab and openjbod-rp2040 stay blocked, by the ERC/DRC items 2, 4 and 5 leave to the
  preset decision and, on openjbod, by the 5 unrouted ATX pins and the J5 shield pin). The remaining four
  carry a plain true finding: tiny-tapeout (3 pads shorted to another
  net and 1 unrouted connection, on the revision whose Gerbers are in the repo), openair-max (two DNP
  parts not flagged on the board, a pad net that differs from the schematic), cm5-minima and bitaxegt
  (BOMs not chosen from the JLCPCB catalogue: 37 and 35 lines without a code; built elsewhere or from
  Digi-Key parts). That is a **false-block rate on fab-ready boards offline of 27 % strictly (3 of 11)
  and 64 % (7 of 11) if the edge-clearance and hand-fitted-part lines are set aside**. With `--online`
  the catalogue adds a true finding to every one of the seven (a part out of stock today, a 100 pF part on
  a 0.1 µF line, an MPN naming a different maker's part), and a false one to six of them (a wrong
  *different* package verdict or a wrong category), so online no fab-ready board is blocked by false
  failures alone and none escapes them either.
* **The documented problems are caught.** BeyondexLimiter before its fix: `catalogue-package` says
  "C22980 0603WAF3601T5E (R1): 0603 on R_0402_1005Metric: footprint is 0402, part is 0603" and the pads
  differ; after the fix the same gate passes. bitaxeAura issue #1: "C92827 TMK107B7105KA-T (C4, C15, C19,
  C25, C36, C42, C46, C47): 0603 on C_0402_1005Metric", two more references than the issue lists. The
  unrouted multichannel board: 148 connections still to route. smarthome-metering: 76 missing footprints
  and 117 bought references not placed, before and after its fix (the wrong-footprint commit changed only
  the schematic, and the board was never laid out at that commit).
* **Three gate bugs, each on several boards, fixed on 2026-10-17 after this triage:** the identity gate
  mislabelled every symbol on a reused sheet as renamed (185 footprints on 3 boards: now 0, the three
  boards' identity gates pass); the parity gate blocked a footprint whose only difference from the
  symbol's is the library nickname (181 footprints on 2 boards: now warnings) and blocked padless logos
  and text footprints (16 on 4 boards: now notes, not findings), a renamed sheet's nets (sh-rpi 33: now
  warnings), a no-net pad on an unconnected pin (canfd-mc 1: now a warning) and two missing test points
  (openjbod: now warnings); `packages.fits()` returned 9 false *different* verdicts on 6 fab-ready boards
  and left 82 lines of chip parts and crystals uncompared because of EasyEDA-style footprint names and
  JLCPCB crystal spellings (now: see "Package verdicts", after the fixes).
* **ERC `power_pin_not_driven` blocks 15 of 21 boards**, 11 of them fab-ready. It is KiCad's missing
  PWR_FLAG error; nothing about it decides whether the fab can build the board.

## Policy decisions applied (2026-10-17, after the triage)

Two of the nine rule changes below were decided and applied the same day; the headline and the per-board
tables describe the run *before* them, and tests/test_corpus.py freezes the run *after*.

* **KiCad's electrical-intent ERC errors run as warnings** (`preset.ERC_DEMOTED`: pin_not_connected,
  pin_not_driven, power_pin_not_driven, pin_to_pin with the pin matrix capped at warning, missing_power_pin,
  label_dangling, wire_dangling, hier_label_mismatch). The protected ERC set keeps what decides whether the
  fab gets one unambiguous part per reference: duplicate references, unannotated symbols, unit/value/footprint
  mismatches between units, sheet-name and bus conflicts, unresolved variables.
* **courtyards_overlap and solder_mask_bridge run as warnings** (`preset.DRC_DEMOTED`). `--strict` promotes
  both groups.

Offline, after the two decisions (kicad-cli 10.0.7, `sh corpus/run.sh`):

| | Triage run | After the gate fixes | After the policy decisions | After "whose rule is it" |
|:--|:--|:--|:--|:--|
| Boards blocked by ERC | 15 of 21 | 15 of 21 | 0 of 21 | 0 of 21 |
| Boards failing offline | 21 of 21 | 20 of 21 | 18 of 21 | 16 of 21 (canfd-mc, jlcpcb-example, soldiercrab and both beyondex boards are NOT VERIFIED) |

**"Whose rule is it" (rule change 4), applied 2026-10-17** (`checks.FLOORED`): for track width, clearance,
edge clearance, hole size, annular width and hole-to-hole, the gate reads the measured figure from KiCad's
message and blocks only when it is under `preset.minimums()`; a figure that clears the fab's floor is the
project's own stricter rule and a warning, with a note saying how many and against which floor. That
reclassified 1,021 errors across 12 boards (drill_out_of_range x199 on openair-max and sh-rpi, clearance
x471 on sonatino, ...).

What still blocks the built boards offline, and is the next set of decisions:

* `copper_edge_clearance` under JLCPCB's published 0.2 mm: sonatino 5, royalblue 31, sh-rpi 2, bitaxegt 6.
  The fab built all four. Either the published figure is conservative for routed edges or the fab accepts
  it silently; a sourced answer is needed before the floor moves.
* `hole_clearance` (openjbod 9, bitaxegt 2, bitaxeaura 14) and `annular_width` (royalblue 2, openjbod 2,
  cm5-minima 6): the preset has no sourced floor for hole-to-copper, and the annular items are pads with no
  ring and no net (pegs). Both need a sourced figure or a rule for netless pads.
* `drill_out_of_range` with figures under 0.15 mm: jetson x199 and royalblue x183 use 0.1 mm holes, which
  JLCPCB lists as available at extra cost; the preset's floor is the standard 0.15 mm. **Closed 2026-10-18**
  ("ORDER on the corpus" below): the floor is the smallest priced tier, 0.10 mm, so jetson's holes are an
  ORDER line; royalblue's 183 items are `(via blind ...)` with a 0.00001 mm `(drill)` in the file, a
  sentinel for "no through drill" that the gate now reads by keyword and layers as a blind via (an HDI
  ORDER line and a DRC warning with a note), never as a hole, so royalblue left the drill block too.
* `starved_thermal` x16 on pocketpd: a zone-connection matter KiCad ships as error; not a fab limit.
* The true findings the headline names (tiny-tapeout's shorts and unrouted connection, openair-max's DNP
  and net mismatches, BOMs not chosen from the JLCPCB catalogue on cm5-minima and bitaxegt).

## How the blocking findings sort

Every blocking item in the 21 offline reports and the 15 online ones, by the rule that produced it
(from `results/*.json`; items as the gate counts them, boards as distinct report files):

| Verdict | Rule / finding | Items | Boards | Evidence |
|:--|:--|--:|--:|:--|
| false failure | ERC `power_pin_not_driven` blocks | 74 | 15 | every fab-ready board but sh-rpi and canfd-mc; KiCad's missing-PWR_FLAG error, not a manufacturability check |
| false failure → fixed (0 left) | identity gate: "X on the board is Y in the schematic" on a reused sheet | 185 | 3 | complex-hierarchy 29, multichannel 78, multichannel-unrouted 78; see bug 1. After the fix all three identity gates pass (68 of 68, 114 of 114, 114 of 114) |
| false failure → fixed (warnings) | parity `footprint_symbol_mismatch` where only the library nickname differs | 181 | 2 | complex-hierarchy 68 of 68, multichannel 113 of 115 (`complex_hierarchy:CP_Axial_...` vs `Capacitor_THT:CP_Axial_...`). After the fix: 68 and 114 warnings (multichannel's second rerun counts J6's value line as the one mismatch and 114 nickname lines), 0 blocking |
| false failure → fixed (notes) | parity `extra_footprint` / `duplicate_footprints` on a footprint with no pads | 16 | 4 | openair-max 11 (six `<no reference designator>` logos, 0 pads), openjbod-rp2040 3 (`REF**` OSHW logo), cm5-minima 1, soldiercrab 1 (`REF**` WEEE logo). After the fix each report's parity line ends "N padless footprint items not counted" and lists them in a note |
| false failure → fixed (warnings) | parity `net_conflict` when only the sheet name in the net path differs | 33 | 1 | sh-rpi: all 33 are `/Buck converter stage 2/SW` vs `/Buck converter 5V/SW` (a sheet renamed after routing); the board is a sold product. After the fix: 33 warnings, parity no longer blocks sh-rpi |
| false failure → fixed (warning) | parity `net_conflict`: pad `<no net>` vs schematic `unconnected-(U1-IO1-Pad39)` | 1 | 1 | canfd-mc, ordered and assembled at JLCPCB; the only blocking finding on that board offline. After the fix canfd-mc is NOT VERIFIED offline |
| false failure → fixed (warnings) | parity `missing_footprint` for a reference the gate itself skips (TP) | 2 | 1 | openjbod-rp2040 TP1, TP2: the placement and BOM gates skip TP by prefix, parity did not. After the fix the project's own severity (KiCad's default warning) stands: 2 warnings |
| false failure | placement: a BOM part with no footprint, excluded from the board | 1 | 1 | cm5-minima M705 "M.2 Screw" (Footprint ""), excluded from the board on purpose |
| false failure | DRC `courtyards_overlap` blocks | 108 | 8 | sonatino 63, royalblue 11, pocketpd 10, soldiercrab 10 (project had set it to warning), tiny-tapeout 8, jetson 3, cm5 2, bitaxeaura 1; six of the eight were built |
| false failure | DRC `solder_mask_bridge` blocks | 271 | 4 | soldiercrab 199 (BGA-256), cm5-minima 54 (project had set it to warning), openair-max 11, bitaxeaura 7; the fab merges the openings |
| false failure | DRC `copper_edge_clearance` on a zone fill, after the preset raised the project's edge clearance | 11 | 3 | bitaxegt 6 (project 0, zone 0.0005 mm from the edge), sh-rpi 2 (project 0.05), royalblue 3 (project 0.127); the fab mills through a pour |
| false failure | bom-lcsc rejects JLCPCB's 10-digit codes | 2 | 2 | pocketpd SW1 `C9900176956`, royalblue U1 `C9900148376`; both answer at getComponentDetail (brand "JLCPCB Assembly") |
| false failure | bom-lcsc: solder jumpers counted as bought | 2 | 1 | sh-rpi JP501 "Open", JP801 "Bridged" (SolderJumper-2 footprints): nothing to buy |
| false failure → fixed (0 left) | `catalogue-package` *different* on a correct part | 9 | 6 | see "Package verdicts" below: LQFN-56 (RP2040, 2 boards), WQFN4040-24, SOIC-8_5.23x5.23mm, SOT-5X3 and SOT-5X3-5, SOT-23-Thin-6, BGA24_6X8, TDFN-6-EP. After the fixes the online pass has 4 *different*, all true |
| false failure | `catalogue-category` U / L against the catalogue's class | 6 | 6 | crystal oscillator as U (bitaxegt U8, bitaxeaura U8: C5137262), ESD array as U (royalblue U3 C2999113, sonatino U3 C85364), common-mode choke as L (canfd-mc L1 C123085, sh-rpi L701 C2915648) |
| noise | other ERC errors (`pin_not_connected`, `pin_not_driven`, `pin_to_pin`, `label_dangling`, `hier_label_mismatch`, `wire_dangling`) | 127 | 12 | KiCad's connectivity errors the designers left (missing no-connect flags, output-to-output on paralleled pins); real in the schematic, not fab-blocking; bitaxegt's `hier_label_mismatch` (sheet pin BAP_VIN) is a genuine schematic defect |
| noise | DRC violations of the project's **own** rule, stricter than the fab's | 836 | 9 | `drill_out_of_range` with the project's min hole 0.3 (sh-rpi 199, beyondex 6+6) or 0.508 (openair-max 199) against 0.2 and 0.4 mm vias; `clearance` at the project's 0.127 (beyondex), 0.3 (multichannel 24+6), 0.1 (openair-max 14), 0.15 netclass (pocketpd 21), 0.2032 (royalblue 13), 0.2 (tiny-tapeout 9); `hole_to_hole` 0.2461 vs the project's 0.25 (sh-rpi 8); the report does not separate these from the fab's limits |
| noise | DRC `clearance` x471 on sonatino | 471 | 1 | an artefact: the repository has no `.kicad_pro` (gitignored), the empty one fetch.sh writes gives KiCad's 0.2 mm default netclass |
| noise | DRC `annular_width` 0 on a no-net PTH pad | 15 | 4 | connector pegs drawn as plated holes without a ring (cm5 J101/USB701/SW101, openair BAT1/USB1/DC1, openjbod J5, royalblue J2) |
| noise | DRC `hole_clearance` 0 between an NPTH peg and its own footprint's pad, or a net-tie polygon | 11 | 2 | openjbod-rp2040 J2/J5 (9), bitaxegt NT1/NT2 (2) |
| noise | `zones_intersect`, `starved_thermal`, `padstack`, `footprint_type_mismatch` | 20 | 4 | cm5, openair, pocketpd 16, sh-rpi, tiny-tapeout |
| unknown | DRC `drill_out_of_range`: blind vias with drill 1e-05 mm | 183 | 1 | royalblue54l-feather; the KiCad demo commit "repair malformed teardrop serialization" touched this file; a padstack artefact or a real file defect |
| unknown | unrouted: 5 connections on the ATX-24 connector's +5V/+3.3V pins | 5 | 1 | openjbod-rp2040 J1 pads 6/21/22/23 (+5v) and 12 (+3.3v); survives `--refill-zones`; the designer may rely on the PSU harness, KiCad does not |
| unknown | parity `net_conflict` "No pad found for pin M1 (GND) / S1 (GND)" | 5 | 2 | cm5-minima J701 M1-M4, openjbod-rp2040 J5 S1: symbol pins the footprint lacks; a shield left unconnected is a real question |
| unknown | DRC `padstack_invalid` | 4 | 1 | openair-max |
| true | unrouted connections | 440 | 3 | bitaxeaura 291 (mid-layout), multichannel-unrouted 148 (by construction), tiny-tapeout 1 (Net-(C3-Pad1), on the fabricated 0.9.4 files) |
| true | DRC `shorting_items` | 26 | 2 | bitaxeaura 23; tiny-tapeout 3: pad 1 of J16 (`unconnected-(J16-Pad1)` in the schematic) is routed to `out7` on the board |
| true | DRC `drill_out_of_range` against the fab's floor (0.15 mm) | 199 | 1 | jetson-thor-baseboard: 0.1 mm holes on a 10-layer HDI board; below JLCPCB's standard capability, which is what the preset promises |
| true | DRC `copper_edge_clearance` on a track or pad | 36 | 4 | royalblue 28, sonatino 5, cm5 2, pocketpd 2: copper within 0.2 mm of a routed edge, the fab's published figure; all four boards were built |
| true | DRC `items_not_allowed` (keepout) | 1 | 1 | bitaxeaura U6 in the antenna keepout |
| true | parity value / footprint mismatches | 13 | 4 | bitaxeaura R5/R7/R11/R13 (board value "R5" vs "715"), multichannel-unrouted J6, openair-max 2, smarthome-metering 2+4 |
| true | parity `net_conflict`: pad net differs from the schematic | 1 | 1 | openair-max I2C3 pad 6: board `unconnected-(I2C3-Pad6)`, schematic GND |
| true | parity `missing_footprint`; DNP and placement on an unlaid board | 352 | 2 | smarthome-metering (both states): the board holds 4 of 121 footprints |
| true | DNP in the schematic, not flagged on the board | 2 | 1 | openair-max Battery1, Solarpower1 |
| true | bom-lcsc: lines without a code | 150 | 7 | boards not chosen from the JLCPCB catalogue (bitaxeaura 47, cm5 37, bitaxegt 35, tiny-tapeout 28) and single lines (openair D1/F2/Q1, royalblue J6, sh-rpi's three supercaps marked JLCPCB_IGNORE) |
| true | `catalogue-package` *different* on a wrong part | 3 | 3 | beyondex-limiter-prefix R1, bitaxeaura C15 group, sh-rpi D303 (SS56FL is SMAF on a D_SMA footprint: a smaller land pattern, placed and sold anyway) |
| true | `catalogue-value`: the code's figure differs from the line's | 2 | 2 | openair-max C53/C56 "0.1uF" on C106200 (100 pF NP0), openjbod-rp2040 C15/C16 "34pF" on C1658 (30 pF) |
| true | stock: out of stock, or the BOM MPN names another part | 43 | 10 | out of stock today: canfd-mc U4 TCAN332GDR, openair-max 2, pocketpd 2, royalblue U4, sh-rpi 2, soldiercrab 3, sonatino U15, tiny-tapeout D1-D4; MPN mismatches: soldiercrab 13 (its `Substitution` field says the LCSC part is a substitute for the Digi-Key MPN), tiny-tapeout 4, bitaxegt 2 |

Totals over the 21 offline reports, with the verdicts above applied item by item (the script is the
classification in this table; `results/*.json` holds the items): 887 false-failure items, 1 153 noise,
197 unknown, 1 160 true. By boards rather than items: a false failure blocks 19 of 21 reports, a true
finding 15 (counting the edge-clearance tracks and the missing bom.csv of the four boards without LCSC
data as true). **After the fixes** the rows marked "→ fixed" are gone: 418 offline items (185 + 181 + 16
+ 33 + 1 + 2) are now warnings or notes and the 9 online package verdicts are *same*, so 460 false-failure
items remain, every one under items 2, 4, 5, 7 and 8 of the rule-changes list (the preset's ERC and DRC
severities, whose rule a DRC figure is, the 10-digit codes and the categories), which are decisions still
to make, not bugs. A false failure then blocks 18 of 21 reports offline (canfd-mc, complex-hierarchy's
parity and sh-rpi's parity cleared; complex-hierarchy fails on bom-file alone, which is true), and 20 of
21 still fail.

## Package verdicts (`packages.fits()`), online

The first online pass compared 409 (code, footprint) lines on 15 boards (`catalogue-package` summaries):
277 same, 12 different, 120 not compared (unknown). Of the 12 *different*, 3 are right and 9 are wrong;
of the 120 unknown, 82 are spellings the table should read (the EasyEDA chip names and the crystals
below) and the rest are connectors, custom footprints and the by-design cases. **After the fixes** (the
same 409 lines, rerun the same day; `results/online/`): 356 same, 4 different, 49 not compared. The 4
*different* are all right: the three true ones below and soldiercrab Y1 (`SMD2520-4P` on a 3225 crystal
footprint, which the first run could not read). The 49 unknown are the by-design list (connectors,
inductor bodies, buttons, custom and vendor footprints: VQFN-HR, USON, XDFN, MicroPak, CABGA, an OSC
footprint) plus openair-max's two EasyEDA names that state no pitch the reader takes (TSSOP-20_L6.5-W4.4-
P0.65-LS6.4-BL, SSOP-16_L7.2-W5.3-P0.65-LS7.8-BL) and one `VQFN-29(4x4)` whose footprint gives no body;
none is a chip, crystal or JEDEC package the catalogue strings name. The rerun also found a pattern the
first fix had got wrong: cm5-minima D401-D403's `DFN2510A-10_L2.5-W1.0-P0.50-BL` (C478121 PUSB3F96X,
`DFN2510-10`) carries a variant letter after the body digits, which the body-pins pattern now allows
(fixture row). There is no offline
package gate any more: after PR #2 the comparison runs only with `--online`, against the catalogue's
string, so a board without codes (or without the network) gets no package verdict at all; the
`bom-value` gate is what runs offline.

**False *different*** (every board a sold or ordered product; all nine are *same* after the fixes, each with
a fixture row in `tests/fixtures/packages.csv` naming the record):

| Board / ref | Footprint on the board | Catalogue string (code, MPN) | What went wrong |
|:--|:--|:--|:--|
| openjbod-rp2040 U1, pocketpd U3 | `QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm` | `LQFN-56(7x7)` (C2040 RP2040) | LQFN is not in FAMILIES (V/W/T/UQFN are) |
| pocketpd U2 | `QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` | `WQFN4040-24` (C5244513 AP33772DKZ-13) | read as QFN-4040: the body size glued to the family, the pin count after the dash |
| openjbod-rp2040 U3 | `SOIC-8_5.23x5.23mm_P1.27mm` | `SOIC-8-208mil` (C97521 W25Q128JVSIQ) | the 5.23 mm body is not in SOIC_BODY (3.9/5.3/7.5), so the footprint reads as 150 mil; KiCad 10 renamed the footprint to `SOIC-8_5.3x5.3mm_P1.27mm`, so the library fell back to a name match and compared pads with `ONSemi_SO-8FL_488AA` (5 pads) |
| openair-max U3 | `SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BR` | `SOT-23-Thin-6` (C473912 TPL5010DDCR) | "Thin" between the family and the pin count stops the pin count being read: SOT-23 vs SOT-23-6 |
| openair-max U7 | `SOT-583-8_L2.1-W1.2-P0.50-LS1.6-BL` | `SOT-5X3` (C22399676 TPS2117DRLR) | TI's DRL name; read as SOT-5-3. SOT-5X3 with 8 leads is SOT-583 |
| royalblue54l-feather U3 | `SOT-553` | `SOT-5X3-5` (C2999113 TPD3E001DRLR-TP) | same spelling, 5 leads: SOT-553 |
| soldiercrab U10 | `BGA-24_5x5_6.0x8.0mm` | `BGA24_6X8` (C5448342 APS256XXN-OBR-BG) | KiCad's `5x5` is the ball array, `6.0x8.0mm` the body; the reader took 5x5 as the body |
| sonatino Q3 | `DFN-6-1EP_3x2mm_P0.5mm_EP1.65x1.35mm_Dual_MOSFETs` | `TDFN-6-EP(2x3)` (C700968 HSCC8233) | TDFN is not in FAMILIES |

**True *different*:** beyondex-limiter-prefix R1 (0402 footprint, 0603 part; fixed in the next commit),
bitaxeaura C4/C15/C19/C25/C36/C42/C46/C47 (issue #1), sh-rpi D303 (SMAF part on an SMA footprint: the
gate keeps SMAF apart on purpose, and this is a real, if tolerated, land-pattern mismatch on a sold board).

**Not compared, and should not be** (by design: connectors, inductor bodies, custom footprints; 24 lines):
`Plugin,P=2.54mm` on pin headers (openjbod, sh-rpi: 6 lines), `SMD,P=1mm,Surface Mount，Right Angle` on
JST footprints, `SMD-4P,6.2x6.2mm` buttons, `Push-Pull,P=3.81mm` on a Phoenix block, `CABGA-256` on
`lattice_cabga256`, `XDFN-4-EP(1x1)` on `Texas_X2SON-4`, `US-8` on `VSSOP-8_2.3x2mm`.

**Not compared, and should be** (false unknown; after the fixes every line of this table is compared: the
chip names and crystals are *same*, soldiercrab Y1 is *different*, the tantalum and the two PowerPAD lines
are *same* by pads with the stacked pad 9 counted once, the three ambiguous lines are *same* because the
board's own footprint picks):

| Spelling | Lines | Boards | Record |
|:--|--:|--:|:--|
| EasyEDA / JLCPCB-library footprint names `C0402`, `C0603`, `C0805`, `C1206`, `R0805`, `L0805` against `0402` etc. | 67 | 2 | openair-max 65 of its 84 lines (e.g. C1525 CL05B104KO5NNNC on `easyeda2kicad:C0402`), jlcpcb-example L1 (C2885888 on `L0805`), R4 (C2683107 on `R0805`) |
| crystals: `SMD3225-4P`, `SMD3215-2P`, `SMD2016-4P`, `SMD2012-2P`, `SMD2520-4P` against `Crystal_SMD_3225-4Pin_3.2x2.5mm` and kin | 9 | 7 | canfd-mc X1 C9010, openjbod Y1 C9002 / Y2 C9006, pocketpd Y1 C133334, royalblue Y1 C32346 / Y2 C2682773, sh-rpi Y801 C55208, bitaxegt/bitaxeaura U8 C5137262 (footprint named `SMD3225-4P`: identical strings, still unknown since the "same name" shortcut went), soldiercrab Y1 C669070 (`SMD2520-4P` on a 3225 footprint: that one should be *different*) |
| tantalum case codes: `CASE-A-3216-18(mm)` against `CP_EIA-3216-18_Kemet-A` | 1 | 1 | openjbod-rp2040 C2 C11366 TAJA226K010RNJ |
| TI PowerPAD with thermal vias: `SO-8-EP` / `ESOP-8` against `TI_SO-PowerPAD-8_ThermalVias` (19 pads) and `TI_SO-PowerPAD-8` (12 pads) | 2 | 2 | canfd-mc U3 C477928 LM5164DDAR, sonatino U4 C16581 TP4056: the pad comparison counts the via-in-pad copies of pad 9 as pads and finds 19 against the 9 of `Diodes_SO-8EP` |
| ambiguity when the board's own footprint is one of the candidates and its pads match | 3 | 2 | sh-rpi U401 `QFN-20-EP(3x3)` on `VQFN-20-1EP_3x3mm_P0.4mm...` ("the pads match ... but names more than one land pattern"), sonatino U13 `TSSOP-16`, U15 `SSOP-20`. A deliberate decision in PR #2; on sold boards it costs a NOT VERIFIED each |

## Values and categories (`values.py`), online

* `bom-value` (bom.csv Value against the schematic): passes on all 15, as expected when the BOM is built
  from the schematic. It did not have to normalise anything the corpus cares about.
* `catalogue-value`: two true findings (openair-max C53/C56, openjbod C15/C16, above), no false ones;
  214 lines agree, 199 state no figure (connectors, ICs). Nothing in the corpus tripped the figure reader:
  "10uF/25V", "4.7uF 100V X7R", "3.6kΩ ±1%", "CAS SCAP 3.0V20F" were all read or left alone correctly.
* `catalogue-category`: 6 false failures (table above), 0 true. Three classes of part are filed by JLCPCB
  under categories the prefix rules do not expect: crystal **oscillators** (an active part, U by every
  convention) under "Crystals, Oscillators, Resonators / Crystal Oscillators"; **ESD protection arrays**
  under "Circuit Protection / ESD and Surge Protection (TVS/ESD)" (the diode class) with a U reference;
  **common-mode chokes** under "Filters / Common Mode Filters" with an L reference.
* Prefixes with no rule, each a NOT VERIFIED line: RV (potentiometers, 1), USB (3), CN (2), X (crystal,
  1), BAT, DC, NTC, TH (thermistor), FAN, IC (soldiercrab's FPGA), CARD, PWR, and openair-max's
  connector names (CE, CO, IO, NO, PM, I2C): 26 lines on 10 boards.

## The fab minimums (`preset.py`)

The preset raised a project minimum on 13 of 21 boards (every board that left KiCad's 0 defaults). Where
that produced errors:

* `min_copper_edge_clearance` 0 / 0.05 / 0.127 → 0.2 mm: bitaxegt (6), sh-rpi (2), royalblue (3) on
  **zone fills** touching a routed edge; royalblue (28), sonatino (5), cm5 (2), pocketpd (2) on tracks and
  pads. All seven boards were built. JLCPCB's figure is real, so the track cases stand; the zone cases are
  pours the fab mills through, and the report should say which is which.
* `min_through_hole_diameter` 0.1 → 0.15 mm: jetson-thor-baseboard (199, HDI vias and pads at 0.1 mm).
  Right by the preset's promise; this board is not a JLCPCB standard-process board.
* `min_via_annular_width` 0 → 0.05: openair-max (5), all on connector pegs with no ring (noise, above).
* `min_hole_to_hole` → 0.2: sonatino (5), through the artefact project file.
* `min_clearance` / `min_track_width` raised on 11 boards: **no errors** cite the raised 0.09/0.1 mm
  values; every clearance error cites the project's own larger figure. So the raised minimums did not
  block a single fab-ready board on clearance or track width.

What did block fab-ready boards under DRC is the **project's own stricter rule**: sh-rpi's 0.3 mm min
hole against 0.2 mm vias (199 errors; 4-layer product), openair-max's 0.508 mm, beyondex's 0.3 mm,
multichannel's 0.3 mm clearance, royalblue's 0.2032 mm clearance. The gate keeps "a project value above
the floor" and reports the violation exactly like a fab-limit one.

## Identity, parity and placement on hierarchical boards

* **Bug 1, identity gate.** A footprint's path is `/<sheet uuid>/<symbol uuid>` without the root sheet,
  while a symbol's `(instances (project (path "/<root uuid>/<sheet uuid>")))` carries the root. On a sheet
  placed once the lookup fails and falls back to the symbol's Reference property, which happens to be
  right; on a sheet placed twice or more, every instance but the one the property remembers is reported
  as "renamed". complex-hierarchy: `Q301 on the board is Q201 in the schematic` for 29 of 68 footprints;
  multichannel: 78 of 114. Matching the instance path by its tail (`path.endswith(sheet)`) resolves all
  107 and changes nothing on the five other hierarchical boards checked (cm5-minima, openair-max,
  jetson-thor-baseboard, sh-rpi: 0 renamed before and after). Verified with the loader on the files.
  **Fixed 2026-10-17** (`schematic.Symbol.reference_on()`: the instance whose path, root sheet dropped, is
  the footprint's sheet chain; `tests/test_contract.py` has a sheet placed twice): the rerun's identity
  gates read `68 of 68`, `114 of 114`, `114 of 114 footprints name a symbol in the schematic`, and the
  six other boards with sub-sheets are unchanged (`results/*.json`).
* **Parity on reused sheets:** kicad-cli's own parity test is fine with reused sheets (0 mismatches of
  that kind on multichannel's routed board).
* **Parity library nickname:** KiCad reports `complex_hierarchy:X doesn't match footprint given by symbol
  (Capacitor_THT:X)` as a warning; the preset promotes the whole `footprint_symbol_mismatch` type to
  blocking, so a project-local footprint copy (the demos, and any project that archives its libraries)
  blocks on every footprint. 181 items; the footprint names are identical in all of them. **Fixed
  2026-10-17** (`checks.parity_check` parses kicad-cli's `X doesn't match footprint given by symbol (Y)`
  and compares the bare names): 68 and 114 warnings in the rerun, each saying which nickname is on the
  board and which in the schematic. The same change parses `Pad net (A) doesn't match net given by
  schematic (B)` (a rename when both are sheet paths with one leaf: sh-rpi's 33), `Pad missing net given
  by schematic (unconnected-(...))` on a `<no net>` pad (canfd-mc's 1), `Missing footprint TP1 (...)` for a
  skipped prefix (openjbod's 2, now the project's own severity) and, with the board file, `extra_footprint`
  / `duplicate_footprints` whose footprints have no pads (16 items, now notes). Any other parity
  description is handled as before: `Value (R5) doesn't match symbol value (715)`, the two `'Do not
  populate' settings differ`, `No pad found for pin ...`, `unconnected-(I2C3-Pad6)` against `GND` and
  smarthome-metering's `unconnected-(X1-Pin_1-Pad1)` against `/AI2` all still block (true findings).
* **Placement gate:** correct on all 21 boards except cm5-minima's screw (M705, no footprint, excluded from
  the board: the gate asks for it to be placed). sh-rpi's `JLCPCB_IGNORE` parts (supercaps, hand-soldered)
  and solder jumpers have no representation; they come out as "no LCSC code".
* **DNP gate:** two true findings (openair-max, smarthome-metering), no false ones. The board attribute and
  the schematic flag agreed on 19 boards.

## Rule changes the corpus justifies

In the order of boards they would unblock. Items 1, 3 and 6 were made on 2026-10-17 (plain gate bugs with
evidence on several boards; `results/` is the rerun); 2, 4, 5, 7, 8 and 9 are not made here: they are
decisions about what the preset owns, not bugs.

1. **Identity: match the instance path by its tail** (schematic.py / checks.identity_check). Unblocks
   complex-hierarchy and both multichannel boards; proven above. **Done.**
2. **ERC `power_pin_not_driven` as a warning under the preset** (preset.ERC_PROTECTED keeps it; a
   `KICAD_DEFAULT` override or a preset "demoted" set). Unblocks or reduces 15 boards. The other ERC
   connectivity errors (`pin_not_connected` without a no-connect flag, output-to-output on paralleled
   pins) are the same kind; the corpus suggests the preset should name the ERC types that are
   *fab*-blocking (duplicate references, unannotated symbols, unit/footprint mismatches, bus conflicts)
   and leave KiCad's electrical-intent errors as warnings, since they are what `--strict` is for.
3. **Parity: `footprint_symbol_mismatch` where the bare footprint names are equal is a warning**, and
   `extra_footprint` / `duplicate_footprints` on a footprint with no pads is not a finding (16 items,
   4 boards); `missing_footprint` for a skip-prefix reference (TP) keeps KiCad's severity; a
   `net_conflict` whose two net names differ only in their sheet path is a rename, and one between
   `<no net>` and an `unconnected-(...)` name is a no-connect. The last two unblock sh-rpi and canfd-mc
   completely offline. **Done** (parity gate only; sh-rpi stays FAIL on its own DRC rule and the
   JLCPCB_IGNORE lines, items 4 and 7; canfd-mc is NOT VERIFIED).
4. **DRC: say whose rule it is.** Mark each violation as the fab's floor or the project's own stricter
   value (the constraint figure in KiCad's message against `preset.minimums()`), and treat the project's
   own as a warning. Removes 836 noise items on 9 boards and leaves jetson's 0.1 mm holes blocking.
   Separate zone-fill edge clearance from track/pad edge clearance (11 items, 3 sold boards).
5. **DRC: demote `courtyards_overlap` and `solder_mask_bridge` to warnings** in `DRC_PROTECTED`.
   Together they block 10 boards, 7 of them built; neither stops the fab building or placing the board.
   `annular_width` on a pad with no net and no ring is a peg (15 items, 4 boards).
6. **Packages** (packages.py tables, with the fixture rows below): `LQFN`, `TDFN` into FAMILIES;
   `SOT-5X3` / `SOT-5X3-5` into SYNONYMS (TI DRL); a family-plus-body-plus-pins spelling
   (`WQFN4040-24`); "Thin" between family and pin count (`SOT-23-Thin-6`); the 5.23 mm SOIC body as
   208 mil; BGA names: the `NxM` ball array is not the body; EasyEDA / JLCPCB-library chip names
   (`C0402`, `R0805`, `L0805`); crystal spellings (`SMD3225-4P` ↔ `Crystal_SMD_3225-4Pin`); tantalum case
   codes (`CASE-A-3216-18`); in the pad comparison, pads with the same number stacked in an exposed pad
   count once (TI ThermalVias footprints). Resolve ambiguity in favour of the board's own footprint when
   its pads match one candidate (3 lines, 2 sold boards). **Done** (`packages.PATTERNS` with a source per
   shape, `footprints.stack()`, `packages._own_pick()`; the fixture rows below are in
   `tests/fixtures/packages.csv`).
7. **bom-lcsc: accept `C` + up to 10 digits**; a `C99…` code is a JLCPCB-assembly consigned / global
   sourcing part (both corpus records answer with brand "JLCPCB Assembly" and stock 0), so the stock gate
   should list it as "pre-order, by hand" rather than out of stock. Solder-jumper prefixes (JP with a
   SolderJumper footprint) join the skip list; a `JLCPCB_IGNORE` / "not assembled" symbol field, when the
   roadmap's symbol-field BOM source lands, is a by-hand line.
8. **Categories** (values.py): exempt "Oscillators" and "ESD and Surge Protection" from the U rule, add
   "Common Mode Filters" to L, and rules for RV, X/Y (crystal), USB/CN/CON (connector), NTC/TH
   (thermistor → resistor class), BAT (battery holder), FAN (connector); unknown multi-letter prefixes
   stay not checked.
9. **Report:** when the schematic has only LCSC codes (the common Fabrication Toolkit workflow: 8 of the
   15 online boards carry no MPN field), every stock line is "no MPN in bom.csv to compare" and the board
   is NOT VERIFIED at best; `bom-template --online` could fill MPN, package, library and stock from the
   catalogue so the comparison has something to compare. **Closed 2026-10-18:** `preflight bom` does
   exactly that ("preflight bom on the corpus" below): 416 of the 565 lines on the 15 boards now carry the
   record's MPN, manufacturer, package, library type, stock and datasheet.

## Fixture rows the corpus justifies

Each row is a real string from the record named, paired with the footprint it was on. When the triage was
written, 22 of the 26 package rows **failed against the reader of `3963b9a`** (checked with
`packages.fits()` and the KiCad 10 library on 2026-10-17; the verdict it gave then is in the last column)
and the four that passed confirm the true findings. All 26 are now in `tests/fixtures/packages.csv`
(section "the regression corpus of 2026-10-17"), each giving the `expect` verdict with the library (rule
`pads`, or `pads-differ` / `names` for the *different* rows) and by names alone, together with four rows
the fixes needed for their own coverage (the 300 mil SOIC body, the two KiCad 10 renamings, openair-max
U4's EasyEDA TSSOP-20 as the case where an ambiguous string stays unknown) and four existing rows whose
expectation the ambiguity rule changed (TSSOP-14 and VSSOP-8 against the board's own footprint: now
*same*). The catalogue.csv rows below are items 7 and 8 and are **not** added.

### tests/fixtures/packages.csv (columns: footprint, part, verdict, rule, names_verdict, names_rule, seen_in, mpn)

| footprint | part | expect | seen_in | mpn | today |
|:--|:--|:--|:--|:--|:--|
| `Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm` | `LQFN-56(7x7)` | same | C2040 RP2040 (openjbod-rp2040 U1, pocketpd U3) | RP2040 | different (names) |
| `Package_DFN_QFN:QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` | `WQFN4040-24` | same | C5244513 Diodes AP33772DKZ-13 (pocketpd U2) | AP33772DKZ-13 | different (names) |
| `Package_SO:SOIC-8_5.23x5.23mm_P1.27mm` | `SOIC-8-208mil` | same | C97521 Winbond W25Q128JVSIQ (openjbod-rp2040 U3); KiCad 10 names it SOIC-8_5.3x5.3mm_P1.27mm | W25Q128JVSIQ | different (pads-differ, against ONSemi_SO-8FL_488AA) |
| `Package_TO_SOT_SMD:SOT-553` | `SOT-5X3-5` | same | C2999113 TI TPD3E001DRLR-TP (royalblue54l-feather U3); TI DRL, 5 leads | TPD3E001DRLR-TP | different (names) |
| `Package_TO_SOT_SMD:SOT-583-8` | `SOT-5X3` | same | C22399676 TI TPS2117DRLR (openair-max U7); TI DRL, 8 leads | TPS2117DRLR | different (names) |
| `SOT-583-8_L2.1-W1.2-P0.50-LS1.6-BL` | `SOT-5X3` | same | the same record on openair-max's EasyEDA footprint name | TPS2117DRLR | different (names) |
| `Package_TO_SOT_SMD:SOT-23-6` | `SOT-23-Thin-6` | same | C473912 TI TPL5010DDCR (openair-max U3) | TPL5010DDCR | different (pads-differ) |
| `SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BR` | `SOT-23-Thin-6` | same | the same record on openair-max's EasyEDA footprint name | TPL5010DDCR | different (pads-differ) |
| `easyeda2kicad:C0402` | `0402` | same | C1525 Samsung CL05B104KO5NNNC (openair-max C5) | CL05B104KO5NNNC | unknown (unreadable) |
| `easyeda2kicad:C1206` | `1206` | same | C109464 Yageo CC1206KKX7R7BB106 (openair-max C23) | CC1206KKX7R7BB106 | unknown |
| `PCM_JLCPCB:R0805` | `0805` | same | C2683107 ARG05BTC5233 (jlcpcb-example R4) | ARG05BTC5233 | unknown |
| `PCM_JLCPCB:L0805` | `0805` | same | C2885888 MLI2012F-1R5KT (jlcpcb-example L1) | MLI2012F-1R5KT | unknown |
| `easyeda2kicad:C0402` | `0603` | different | C14663 CC0603KRX7R9BB104 must not pass on a C0402 | CC0603KRX7R9BB104 | unknown |
| `Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm` | `SMD3225-4P` | same | C9010 X322540MPB4SI (canfd-mc X1); C9002 (openjbod Y1); C133334 (pocketpd Y1) | X322540MPB4SI | unknown |
| `Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm` | `SMD3215-2P` | same | C32346 Epson Q13FC13500004 (royalblue Y1) | Q13FC13500004 | unknown |
| `Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm` | `SMD2016-4P` | same | C2682773 X201632MOB4SI (royalblue Y2) | X201632MOB4SI | unknown |
| `Crystal:Crystal_SMD_2012-2Pin_2.0x1.2mm` | `SMD2012-2P` | same | C55208 X1A0000610002 (sh-rpi Y801) | X1A0000610002 | unknown |
| `Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm` | `SMD2520-4P` | different | C669070 OT252048MJBA4SL (soldiercrab Y1): a 2520 oscillator on a 3225 footprint | OT252048MJBA4SL | unknown |
| `SMD3225-4P` | `SMD3225-4P` | same | C5137262 SX3M25.000E20F30THN (bitaxegt U8): the footprint is named after the catalogue string | SX3M25.000E20F30THN | unknown |
| `Capacitor_Tantalum_SMD:CP_EIA-3216-18_Kemet-A` | `CASE-A-3216-18(mm)` | same | C11366 AVX TAJA226K010RNJ (openjbod-rp2040 C2) | TAJA226K010RNJ | unknown |
| `Package_SO:TI_SO-PowerPAD-8_ThermalVias` | `SO-8-EP` | same | C477928 TI LM5164DDAR (canfd-mc U3): pad 9 is repeated for the thermal vias | LM5164DDAR | unknown (pads-unknown: 19 pads against 9) |
| `Package_DFN_QFN:DFN-6-1EP_3x2mm_P0.5mm_EP1.65x1.35mm_Dual_MOSFETs` | `TDFN-6-EP(2x3)` | same | C700968 HSCC8233 (sonatino Q3) | HSCC8233 | different (names) |
| `Package_BGA:BGA-24_5x5_6.0x8.0mm` | `BGA24_6X8` | same | C5448342 APS256XXN-OBR-BG (soldiercrab U10): 5x5 balls, 6x8 mm body | APS256XXN-OBR-BG | different (names) |
| `Diode_SMD:D_SMA` | `SMAF` | different | C122865 SS56FL (sh-rpi D303): SMAF is DO-221AC | SS56FL | different ✓ |
| `Capacitor_SMD:C_0402_1005Metric` | `0603` | different | C92827 Taiyo Yuden TMK107B7105KA-T (bitaxeaura C15, issue #1) | TMK107B7105KA-T | different ✓ |
| `Resistor_SMD:R_0402_1005Metric` | `0603` | different | C22980 0603WAF3601T5E (BeyondexLimiter R1 before 3256bd86) | 0603WAF3601T5E | different ✓ |
| `Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.514x3.2mm_ThermalVias` | `ESOP-8` | same | C35634 CN5711 (beyondex-limiter U1) | CN5711 | same ✓ |

### tests/fixtures/catalogue.csv (columns: lcsc, mpn, package, category, description, ref, value, expect, note)

Records copied from getComponentDetail on 2026-10-17 (the `results/online/*.json` stock lines hold the
MPN, package, library and stock; the category and description are in the catalogue-category details):

| lcsc | mpn | package | category | ref | value | expect today → proposed | note |
|:--|:--|:--|:--|:--|:--|:--|:--|
| C5137262 | SX3M25.000E20F30THN | SMD3225-4P | Crystals, Oscillators, Resonators / Crystal Oscillators | U8 | 25MHz | category → ok | an oscillator is an IC (bitaxegt, bitaxeaura) |
| C2999113 | TPD3E001DRLR-TP | SOT-5X3-5 | Circuit Protection / ESD and Surge Protection (TVS/ESD) | U3 | TPD3E001 | category → ok | ESD array as U (royalblue54l-feather) |
| C85364 | SRV05-4-P-T7 | SOT-23-6 | Circuit Protection / ESD and Surge Protection (TVS/ESD) | U3 | SRV05-4 | category → ok | sonatino |
| C123085 | DLW43SH101XK2L | SMD-4P,4.5x3.2mm | Filters / Common Mode Filters | L1 | DLW43SH101XK2L | category → ok | common-mode choke as L (canfd-mc) |
| C2915648 | PCAQ7060MW-102 | SMD-4P,7x6mm | Filters / Common Mode Filters | L701 | 1mH | category → ok | sh-rpi |
| C106200 | CC0402JRNPO9BN101 | 0402 | Capacitors / Multilayer Ceramic Capacitors MLCC - SMD/SMT | C53 | 0.1uF | value ✓ | the true finding on openair-max (100 pF part) |
| C1658 | 0603CG300J500NT | 0603 | Capacitors / Multilayer Ceramic Capacitors MLCC - SMD/SMT | C15 | 34pF | value ✓ | the true finding on openjbod-rp2040 (30 pF part) |
| C9900176956 | EC11J-5DM20P1ZY15F7 | Through-hole-Plum-15mm | Others / SMT | SW1 | RotaryEncoder_Switch | (rejected by bom-lcsc) → unchecked-both, pre-order | brand "JLCPCB Assembly", stock 0, leastNumber 2 (pocketpd) |
| C9900148376 | BM15C | SMD,10x15.8mm | Others / New Arrivals | U1 | BM15x | (rejected by bom-lcsc) → unchecked-both, pre-order | brand "JLCPCB Assembly", stock 0 (royalblue54l-feather) |

## ORDER on the corpus (2026-10-18)

The ORDER section (DESIGN.md G15, `checks.order_check()`, status `cost`) lists what the files show that
lands on a priced tier of JLCPCB's (`preset.TIERS`, read 2026-10-18); it never moves the verdict. Run on
the 21 boards offline (`sh corpus/run.sh`) and on the 15 with LCSC codes online (`--online-only`), kicad-cli
10.0.7; `results/*.txt` hold the lines, `tests/test_corpus.py` `ORDER` freezes the driver names in print
order. With the hole floor moved to 0.10 mm, jetson-thor-baseboard lost its DRC block (its only remaining
block is the missing bom.csv). royalblue54l-feather kept its own at first: its 183 vias are written
`(via blind ... (drill 0.00001) (layers "F.Cu" "B.Cu"))`, and the gate read the 0.00001 as a hole below
every tier. That figure is KiCad's sentinel for a via with no through drill, not a measurement, so since
the blind-via reading (same day) the gate classifies a via by its `blind`/`micro` keyword and its two
layers, never by its drill: royalblue's 183 are blind vias, an HDI line in ORDER (JLCPCB's HDI process, sourced
2026-10-18: laser blind vias 0.075-0.15 mm, "the price is higher", no figure published) and a DRC warning with a note instead of 183 `drill_out_of_range` blocks. Its DRC
still has copper_edge_clearance, clearance and annular_width errors, so the board still fails on `drc`
and `bom-lcsc`; the blocking set lost nothing else. No other verdict or blocking set moved.

The lines print in two kinds, hidden first (a via or hole tier with its condition, HDI, parts on the back,
Extended part types, the assembly class, the stackup flags) and the designer's chosen drivers after them,
one short line each (layers, size, through-hole parts); the table below keeps the kinds in that order.

**19 of 21 boards carry at least one priced option offline; online, every one of the 15 with LCSC codes
does** (each has Extended part types). The two on the standard tier everywhere offline are the two
BeyondexLimiter states (2 layers, 22.5 × 13 mm, 0.3 mm vias, 7 SMD parts on one side, no through-hole
parts), whose README says "All the defaults are OK ... The PCBA defaults are also OK": the gate agrees,
and online adds the one line the README leaves out (4 Extended part types, one loading fee each).

| Board | Layers | Outline (mm) | Smallest via hole / diameter | Drivers offline (tier) | Extended types online |
|:--|:--|:--|:--|:--|:--|
| beyondex-limiter, -prefix | 2 | 22.5 × 13 | 0.3 / 0.5 | none (standard tier everywhere) | 4 |
| bitaxeaura | 4 | 65 × 122 | 0.3 / 0.5 | placement (40 parts on B.Cu: Standard PCBA); layers (4 layers); size (larger than 100 × 100); through-hole (6 parts) | 2 |
| bitaxegt | 6 | 65 × 112 | 0.3 / 0.5 | placement (130 on B.Cu); layers (High Precision PCB); size; through-hole (4 parts) | 3 |
| canfd-mc | 4 | 55 × 32 | 0.3 / 0.6 | layers (4 layers) | 16 |
| cm5-minima | 6 | 59.64 × 62.69 | 0.3 / 0.45 | placement (14 on B.Cu); impedance control (`dielectric_constraints yes`: Specify Stackup); layers (High Precision); through-hole (2 parts) | 6 |
| complex-hierarchy | 2 | 100.7 × 80.03 | none | size (100.7 mm: larger than 100 × 100 by the table; the quote page still showed the offer at 100 × 101 and the exact edge was not pinned); through-hole (68 parts) | not run |
| jetson-thor-baseboard | 10 | 180 × 100 | 0.1 / 0.45 | vias (3235 of 3235 below the standard option: the 0.1mm/(0.2/0.25mm) option, thickness ≤ 1.0 mm and ENIG or OSP); holes (3258 of 3309 under 0.15 mm: the 0.1 mm tier, "more costly!"); placement (360 on B.Cu); assembly class (10 layers, 1.711 mm: Standard PCBA); layers (High Precision); size; through-hole (2 parts) | not run |
| jlcpcb-example | 2 | 107.3 × 82.8 | 0.2 / 0.4 | vias (30 of 101 at 0.2 mm: the 0.2mm/(0.3/0.35mm) option, plugged vias and the Kelvin test added); size; through-hole (4 parts) | 4 |
| multichannel, -unrouted | 2 | 110 × 111 | 0.6 / 1.5 | placement (81 on B.Cu); size; through-hole (33 parts) | not run |
| openair-max | 4 | 99.45 × 72 | 0.3 / 0.5 | placement (174 on B.Cu); layers (4 layers); through-hole (17 parts) | 78 |
| openjbod-rp2040 | 4 | 72.61 × 170 | 0.3 / 0.5 | layers; size (170 mm); through-hole (14 parts) | 24 |
| pocketpd | 2 | 50 × 50 | 0.3 / 0.5 | through-hole (3 parts) | 22 |
| royalblue54l-feather | 8 | 58.42 × 22.86 | none through (183 blind, 0.35 mm diameter); smallest pad hole 0.2 | HDI (183 blind/buried vias: JLCPCB's HDI process, 1st to 3rd order); assembly class (8 layers: Standard PCBA); castellated holes (`castellated_pads yes`: Standard PCBA, "extra cost will be charged"); layers (High Precision) | 15 |
| sh-rpi | 4 | 65 × 56.5 | 0.2 / 0.5 | vias (295 of 364 at 0.2 mm: the 0.2 mm option); placement (J501, J801 through-hole on the back); layers; through-hole (9 parts) | 39 |
| smarthome-metering, -prefix | 2 | 120.5 × 86.5 | none | size; through-hole (X1, X2) | not run |
| soldiercrab | 6 | 22.2 × 22 | 0.15 / 0.41 | vias (189 of 191 at 0.15 mm: the 0.15mm/(0.25/0.3mm) option); placement (55 on B.Cu); layers (High Precision) | 21 |
| sonatino | 4 | 65 × 30 | 0.25 / 0.45 | vias (209 of 292 at 0.25 mm: the 0.25mm/(0.35/0.4mm) option); layers; through-hole (J5) | 31 |
| tiny-tapeout | 4 | 104.5 × 81 | 0.3 / 0.6 | impedance control (Specify Stackup); layers; size (104.5 mm); through-hole (6 parts) | 4 |

The thickness driver read to the nearest 0.1 mm: openjbod-rp2040's stackup sums to 1.6062 mm and
cm5-minima's to 1.5296, both 1.6 and 1.5 mm boards on the quote page's list, so neither is a driver;
jetson's 1.711 mm is. A thickness read exactly would have made openjbod a Standard PCBA board on a figure
no quote page accepts.

**Do the built boards' drivers match what their repositories say was ordered?** Where the repository says
anything, yes; most say nothing about the tier, and the files' stackup finish is the only other witness:

* **canfd-mc** (README: "Ordered from JLCPCB in September 2026 (5 boards, assembled)", "A 55 × 32 mm,
  4-layer board"): one driver, 4 layers, and `(copper_finish "HAL lead-free")` in the stackup. Online adds
  16 Extended part types, the loading fees the order carried. No driver the README contradicts.
* **jlcpcb-example** (README step 5: "I usually accept all the defaults ... Make sure 'Economic' is
  available and selected"): the gate says 30 of its 101 vias are 0.2 mm, which is not a default (the
  standard option is 0.3 mm), and that the board is 107.3 × 82.8 mm, outside the 100 × 100 class. Whether
  the quote page picks the via option up from the Gerbers was not sourced; the README's own words name
  this board "a test board", not an order record. Through-hole parts (4) and single-sided placement fit
  Economic PCBA, as the README expects.
* **beyondex-limiter** (README: defaults and PCBA defaults are OK): no driver offline, 4 Extended types
  online. Consistent.
* **soldiercrab** (README: pre-assembled units sold on Crowd Supply; `fab/soldiercrab_bom_jlc.csv` in
  JLCPCB's BOM format): 6 layers, 0.15 mm vias, parts on both sides, 0.85 mm thick. Those are the
  High Precision class, the 0.15 mm via option and Standard PCBA; a BGA-256 board could not be built
  otherwise. Consistent; the repository does not state the options.
* **royalblue54l-feather** (Crowd Supply campaign, photo of the built board): 8 layers, castellated
  pads and `(copper_finish "ENIG")` in the stackup, blind vias. High Precision, Standard PCBA, the
  castellated surcharge and an HDI process are what the file says; the 0.00001 mm drill on the 183
  `(via blind ...)` is KiCad's sentinel for a via without a through drill (the 2026-10-17 triage filed it
  as unknown), not a hole and not an order option, and the gate reads it as the via's kind.
* **sh-rpi** (sold at shop.hatlabs.fi; `assembly-panel/bom.csv` in JLCPCB's format): 4 layers, 295 vias
  at 0.2 mm, two through-hole connectors on the back, ENIG in the stackup. The 0.2 mm option and
  Standard PCBA (double-sided) are consistent with a JLCPCB assembly order; not stated in the repo.
* **openair-max** (Fabrication Toolkit project for JLCPCB; shipping product): 4 layers, 174 parts on
  the back, 17 through-hole parts, 1.2 mm, HAL lead-free. Standard PCBA; consistent, not stated.
* **sonatino, pocketpd, openjbod-rp2040, tiny-tapeout** (built; photos, fab outputs or test reports):
  sonatino's 0.25 mm vias and 4 layers, pocketpd's three through-hole connectors on a 2-layer 50 × 50
  board (Economic-eligible), openjbod's 170 mm length and 14 through-hole parts, tiny-tapeout's
  104.5 mm length and impedance flag. None of the four repositories records the options ordered.
* **jetson-thor-baseboard and cm5-minima** were not made at JLCPCB (Antmicro's own services; NextPCB).
  jetson's drivers show why: its 0.1 mm vias need a board 1.0 mm or thinner with ENIG or OSP, and the
  file is 1.711 mm thick with ENIG, so JLCPCB's quote page would grey the option out. The gate reports
  the tier and its condition and leaves the conclusion to the reader, as designed.

What the section cannot say, and says so on every report: copper weight, surface finish (the stackup's
`copper_finish` is set on 9 boards and "None" on 9, and the gate does not read it as an order option),
colour, quantity, via covering, gold fingers, panelisation. No package size is inferred from pads, so the
Economic PCBA 0402-and-finer rule is not a driver (soldiercrab's BGA-256, say, is not
reported).

## preflight bom on the corpus (2026-10-18)

`preflight bom` reads the LCSC code each symbol names in a field, asks the catalogue for that code's record
and writes bom.csv from it (`pcb_preflight/init.py`; design note of 2026-10-18). Run on the 15 boards with
LCSC data, each into a scratch `--bom` path outside the corpus, with a fresh cache (`$PCB_PREFLIGHT_CACHE`
pointed at an empty file), on 2026-10-18 with kicad-cli 10.0.7; then a second time into the same path. The
hand-made column is `boms/<name>.csv`, which `make_boms.py` built from the same symbol fields on 2026-10-17
(its CONFIG table names each board's fields by hand).

| Board | lines | filled | open: no code | open: no record | field spellings (references) | hand-made lines / with code | refs whose code differs | first run | second run |
|:--|--:|--:|--:|--:|:--|:--|--:|:--|:--|
| beyondex-limiter | 6 | 6 | 0 | 0 | LCSC (7) | 6 / 6 | 0 | 8.1 s, exit 0 | 0.5 s, cache, same bytes |
| beyondex-limiter-prefix | 6 | 6 | 0 | 0 | LCSC (7) | 6 / 6 | 0 | 0.5 s (all 6 codes already cached by the other commit), exit 0 | 0.5 s, same bytes |
| bitaxeaura | 48 | 1 | 47 | 0 | LCSC (1) | 49 / 2 | 8 | 1.7 s, exit 3 | 0.7 s, same bytes |
| bitaxegt | 38 | 4 | 34 | 0 | LCSC (5) | 39 / 4 | 0 | 3.5 s, exit 3 | 0.9 s, same bytes |
| canfd-mc | 26 | 26 | 0 | 0 | LCSC (37) | 26 / 26 | 0 | 23.2 s, exit 0 | 0.6 s, same bytes |
| cm5-minima | 39 | 6 | 33 | 0 | LCSC Part (8) | 43 / 6 | 0 | 6.3 s, exit 3 | 0.8 s, same bytes |
| jlcpcb-example | 11 | 11 | 0 | 0 | LCSC (10), LCSC Part (5) | 11 / 11 | 0 | 7.6 s, exit 0 | 0.5 s, same bytes |
| openair-max | 84 | 81 | 3 | 0 | LCSC Part (180) | 84 / 81 | 0 | 87.2 s, exit 3 | 0.6 s, same bytes |
| openjbod-rp2040 | 49 | 49 | 0 | 0 | LCSC Part # (121) | 49 / 49 | 0 | 62.4 s, exit 0 | 0.7 s, same bytes |
| pocketpd | 34 | 34 | 0 | 0 | LCSC (81) | 34 / 34 | 0 | 25.3 s, exit 0 | 0.6 s, same bytes |
| royalblue54l-feather | 29 | 28 | 1 | 0 | LCSC (47) | 29 / 28 | 0 | 19.4 s, exit 3 | 0.7 s, same bytes |
| sh-rpi | 77 | 74 | 3 | 0 | LCSC (147) | 77 / 74 | 0 | 64.0 s, exit 3 | 0.9 s, same bytes |
| soldiercrab | 29 | 29 | 0 | 0 | lcsc# (70) | 29 / 29 | 0 | 22.5 s, exit 0 | 0.8 s, same bytes |
| sonatino | 57 | 57 | 0 | 0 | LCSC (116) | 57 / 57 | 0 | 36.5 s, exit 0 | 0.6 s, same bytes |
| tiny-tapeout | 32 | 4 | 28 | 0 | JLC (8) | 32 / 4 | 0 | 4.7 s, exit 3 | 0.6 s, same bytes |
| **15 boards** | **565** | **416** | **149** | **0** | 5 spellings | 571 / 417 | 8 | 373 s, 340 codes fetched | 10 s, 0 fetched |

What the run shows:

* **Every code in the fields is in the catalogue.** 416 lines filled from a record, 0 codes the catalogue
  did not know, 0 lookups failed; 339 of the 340 distinct codes answered at JLCPCB's cart endpoint and one
  (C25120, openjbod-rp2040's R19-R22, `0402WGF499JTCE`) only at the jlcsearch mirror, so that line has no
  manufacturer and no datasheet URL. Six more records carry no datasheet URL (openair-max C6119813 and
  C5357696, sh-rpi C306602, soldiercrab C5448342, and the two consigned "JLCPCB Assembly" parts
  C9900176956 on pocketpd and C9900148376 on royalblue, which also have no stock and which `bom-lcsc`
  still rejects as 10-digit codes, rule-changes item 7). 415 of 416 lines carry a manufacturer. Library
  type: 277 Extended, 139 Basic.
* **Every open line is a symbol without a code, as designed.** 149 lines on 8 boards; the 7 boards whose
  symbols all carry a code exit 0 (COMPLETE). bitaxeaura's 47, bitaxegt's 34, cm5-minima's 33 and
  tiny-tapeout's 28 are the Digi-Key/MPN-field boards the corpus triage already named; openair-max's 3
  (J6 FPC connector, D1 BAS16J, F2 PCB fuse), royalblue's 1 and sh-rpi's 3 are the lines the hand-made BOMs
  also left without a code. The open lines carry the MPN and manufacturer the symbol itself names where it
  has those fields (bitaxegt's PARTNO is not in the spelling table, so its 34 open lines carry none).
* **The 8 differing references are the MPN-to-code resolution the hand-made BOM did by hand** (bitaxeaura
  C4, C15, C19, C25, C36, C42, C46, C47: `TMK107B7105KA-T` → C92827 in make_boms.py's CONFIG). `bom` leaves
  them open: decision 2 of the design note (no MPN-to-code resolution in the first version). Every other
  code on every other board equals the hand-made one; the line counts differ on three boards (bitaxeaura
  48/49, bitaxegt 38/39, cm5-minima 39/43) only because make_boms.py also split lines by the symbol's own
  Package and MPN fields and `bom` splits by (code, value, footprint).
* **Field spellings seen:** `LCSC` (9 boards), `LCSC Part` (3: jlcpcb-example beside `LCSC`, openair-max,
  cm5-minima), `LCSC Part #` (openjbod-rp2040), `lcsc#` (soldiercrab), `JLC` (tiny-tapeout). The last two
  are in `init.FIELDS` with the board as their source; without them 33 lines on two sold boards would be
  open. `JLCPCB_PN` (openjbod, beside `LCSC Part #`) and pocketpd's `LCSC2` supplied nothing: the first
  spelling in table order already had the code on every symbol, and no symbol carried two spellings with
  different codes. The design note's `LCSC_PART`, `JLCPCB Part #` and `JLCPCB` did not occur in the corpus and were dropped
  from the table on 2026-10-20 (with `Mfr. Part #` and `Mfr`): a spelling needs a board or a tool behind it.
* **Time and the cache.** The first pass took 373 s for 340 distinct codes (one request per code with the
  client's 0.2 s pause: about 0.9 s a code; openair-max's 79 codes 87 s). The second run of every board was
  served entirely from the cache in 0.5 to 0.9 s (kicad-cli's export is most of that) and wrote the same
  bytes as the first, which is what makes the file diff cleanly in review. Codes shared between boards were
  fetched once (beyondex-limiter-prefix cost nothing after beyondex-limiter; sonatino found 22 of its 57
  in the cache).
* **What `check` then says** is unchanged on these boards: `boms/<name>.csv` was built from the same fields,
  so the new `bom-source` gate passes on all 15 (and on the 6 boards without LCSC fields it passes saying
  bom.csv is the only source); `tests/test_corpus.py` freezes the offline verdicts with an empty cache, so
  this machine's catalogue cache stays out of the baseline, and `CorpusBom` freezes the lines, open lines
  and field spellings above (the deterministic part; what the catalogue answered is this table only).

## Per-board tables

Blocking findings per board, offline unless marked online; the verdict column is the triage. "own" means
the project's own constraint, stricter than the fab's floor.

### openair-max (fab: believed yes) — FAIL offline and online
| Gate | Finding | Verdict |
|:--|:--|:--|
| erc | 7 `power_pin_not_driven`, 41 `pin_not_driven` (resistor pins typed Input), 1 `wire_dangling` | false (7), noise (42) |
| drc | 199 `drill_out_of_range` (own 0.508 mm vs 0.4 mm vias); 14 `clearance` (own 0.1); 11 `solder_mask_bridge`; 5 `annular_width` (pegs); 4 `padstack_invalid`; 1 `zones_intersect` | noise, noise, false, noise, unknown, noise |
| parity | 6 `extra_footprint` + 5 `duplicate_footprints` on padless logos; 2 DNP-attribute mismatches; I2C3 pad 6 `unconnected-` vs GND | false (11; after the fixes a note, 3 mismatches left), true (3) |
| dnp | Battery1, Solarpower1 DNP in the schematic, not on the board | true |
| bom-lcsc | D1 BAS16J (Package field only), F2 fuse, Q1/Q2 CSD18534Q5A: no code | true |
| stock (online) | C273332, C309458 out of stock; 5 low stock; 81 lines without an MPN to compare | true; not checked |
| catalogue-package (online) | U3 SOT-23-Thin-6, U7 SOT-5X3 *different*; 65 lines `C0402`-style unknown | false (2 + 65); after the fixes 69 agree, 12 by-design unknown |
| catalogue-value (online) | C53/C56 0.1uF on a 100 pF part | true |

### royalblue54l-feather (fab: yes) — FAIL
| erc | 5 `power_pin_not_driven`, 2 `pin_to_pin` (nPM1300 paralleled outputs) | false, noise |
| drc | 183 `drill_out_of_range` blind vias at 1e-05 mm; 31 `copper_edge_clearance` (raised 0.127 → 0.2; 3 zones); 13 `clearance` (own 0.2032); 11 `courtyards_overlap`; 2 `annular_width` | unknown, false/true, noise, false, noise |
| bom-lcsc | J6 FFC connector without a code; U1 `C9900148376` | true, false |
| stock (online) | U4 W25Q16JVUXIQ out of stock | true |
| catalogue-package (online) | U3 SOT-5X3-5 *different*; 7 unknown (crystals Y1/Y2, Wurth LED, JST, Winbond USON, TXB0106 RGY) | false; false (2) + by design (5); after the fixes 22 agree, 5 by design |
| catalogue-category (online) | U3 ESD array | false |

### tiny-tapeout (fab: yes, rev 0.9.4 Gerbers in the repo) — FAIL
| erc | 2 `power_pin_not_driven`; 2 `pin_to_pin` (PWR_FLAG on a regulator output); 2 `pin_not_connected` | false, noise, noise |
| drc | 3 `shorting_items` (J16 pad 1 routed to out7); 9 `clearance` (netclass 0.2 own); 8 `courtyards_overlap`; 1 `footprint_type_mismatch`; 160 footprints without a courtyard (157 stitching vias) | true, noise, false, noise, not checked |
| unrouted | 1 (Net-(C3-Pad1)) | true |
| bom-lcsc | 28 of 32 lines carry only an MPN | true (not chosen from JLCPCB) |
| stock (online) | 4 MPN mismatches (the JLC field names a substitute), D1-D4 out of stock | true |

### complex-hierarchy (KiCad demo) — FAIL (after the fixes: FAIL on bom-file alone)
| parity | 68 `footprint_symbol_mismatch`, every one a library-nickname difference | false; after the fixes 68 warnings, 0 mismatches |
| identity | 29 "renamed" on the twice-placed ampli_ht sheet | false (bug 1); after the fixes 68 of 68 pass |
| bom-file | no bom.csv | true (no LCSC data to build one) |

### multichannel / multichannel-unrouted (KiCad demo) — FAIL
| erc | 3 `power_pin_not_driven`, 1 `pin_not_connected` | false, noise |
| drc | 24 / 6 `clearance` (own 0.3 mm) | noise |
| unrouted (unrouted variant) | 148 | true (by construction) |
| parity | 113 nickname mismatches (routed board); J6 value (both boards) | false (after the fixes 114 warnings and the J6 line as the one mismatch on the routed board; the first run folded one J6 line into the 115); true |
| identity | 78 "renamed" on the four-times-placed channel_strip sheet | false (bug 1); after the fixes 114 of 114 pass on both |
| bom-file | no bom.csv | true |

### jetson-thor-baseboard (fab: believed yes, not JLCPCB) — FAIL
| erc | 3 `pin_to_pin` (FLG outputs tied), 2 `pin_not_connected` (3007 warnings, mostly missing libraries) | noise |
| drc | 199 `drill_out_of_range` at 0.1 mm (raised 0.1 → 0.15); 3 `courtyards_overlap`; the `.kicad_dru` left out | true (per preset), false |
| bom-file | no bom.csv | true |

### cm5-minima (fab: yes, NextPCB) — FAIL
| erc | 2 `pin_not_connected` (hierarchical label in root), 1 `power_pin_not_driven`, 1 `pin_not_driven` | noise, false, noise |
| drc | 54 `solder_mask_bridge` (project: warning); 6 `annular_width` (pegs); 2 `courtyards_overlap`; 2 `copper_edge_clearance` (pads); 1 `zones_intersect`; 38 without courtyard | false, noise, false, true, noise |
| parity | J701 M1-M4 "no pad found for pin"; 1 `extra_footprint` (REF**) | unknown, false (after the fixes a note; 4 mismatches left) |
| placement | M705 M.2 screw, excluded from the board | false |
| bom-lcsc | 37 of 43 lines | true (not JLCPCB) |
| catalogue-package (online) | 5 same, CN1 JST unknown | by design; unchanged after the fixes (D401-D403 `DFN2510-10` on `DFN2510A-10` stays same, see "Package verdicts") |

### jlcpcb-example (fab: unknown) — FAIL
| erc | 3 `power_pin_not_driven` | false |
| drc | 0 errors (58 warnings: dangling stitching vias, hole-to-hole) | — |
| stock (online) | 11 found, 4 without an MPN | not checked |
| catalogue-package (online) | 9 same (TPS63070 VQFN-HR-15 by name, DBT10 block by name); L1 `L0805`, R4 `R0805` unknown | false unknown (2); after the fixes 11 agree |

The one board in the corpus drawn entirely from the JLCPCB KiCad Library is blocked by ERC alone.

### canfd-mc (fab: yes, JLCPCB assembled 2026-09) — FAIL (after the fixes: NOT VERIFIED offline, FAIL online on stock)
| parity | 1 `net_conflict`: U1 pad 39 `<no net>` vs `unconnected-(U1-IO1-Pad39)` | false; after the fixes a warning, nothing blocks offline |
| stock (online) | U4 TCAN332GDR out of stock today; 26 lines without an MPN | true; not checked |
| catalogue-package (online) | 24 same; U3 LM5164 PowerPAD (19 pads vs 9) and X1 crystal unknown | false unknown (2); after the fixes 26 agree |
| catalogue-category (online) | L1 common-mode choke | false |

### openjbod-rp2040 (fab: yes) — FAIL (after the fixes still FAIL: erc, drc, unrouted, parity's J5 S1)
| erc | 3 `power_pin_not_driven`; `label_dangling` +5vSB; `pin_not_driven` SWCLK | false, noise, noise |
| drc | 9 `hole_clearance` (J2/J5 pegs against their own pads); 2 `annular_width` | noise |
| unrouted | 5 on J1 ATX-24 +5v/+3.3v pins (after `--refill-zones` too) | unknown |
| parity | TP1/TP2 missing; REF** OSHW logo extra + duplicate; J5 pin S1 no pad | false (after the fixes 2 warnings), false (a note), unknown (the 1 mismatch left) |
| catalogue-package (online) | U1 LQFN-56, U3 SOIC-8-208mil *different*; C2 tantalum, Y1/Y2 crystals, headers unknown | false (2); false unknown (3), by design (5); after the fixes 44 agree, 5 by design |
| catalogue-value (online) | C15/C16 34pF on a 30 pF part | true |

### bitaxegt (fab: believed yes) — FAIL
| erc | 20 `power_pin_not_driven`; 7 `pin_to_pin`; 3 `pin_not_driven`; `hier_label_mismatch` BAP_VIN; `label_dangling` 5V | false, noise, noise, noise (a real schematic defect), noise |
| drc | 6 `copper_edge_clearance` zone fills (raised 0 → 0.2); 2 `hole_clearance` net ties | false, noise |
| bom-lcsc | 35 of 39 lines | true (Digi-Key BOM) |
| stock (online) | R14/R25 and J2: the BOM MPN names a different maker's part | true |
| catalogue-category (online) | U8 oscillator | false |
| catalogue-package (online) | (after the fixes) U8 `SMD3225-4P` agrees: 3 agree, 1 by design | — |

### bitaxeaura (documented problem, mid-layout) — FAIL
| erc / drc / unrouted | 29 ERC errors; 126 DRC errors (23 shorts, 80 clearance); 291 unrouted | true |
| parity | R5/R7/R11/R13 board value is the reference | true |
| bom-lcsc | 47 of 49 lines | true |
| catalogue-package (online) | C92827 TMK107B7105KA-T 0603 on C_0402 (8 refs; issue #1 names 6) | true |
| catalogue-category (online) | U8 oscillator | false |

### sh-rpi (fab: yes, sold) — FAIL (after the fixes still FAIL: drc and bom-lcsc)
| drc | 199 `drill_out_of_range` (own 0.3 vs 0.2 mm vias); 8 `hole_to_hole` (own 0.25 vs 0.2461); 2 `copper_edge_clearance` zones (raised 0.05 → 0.2); 1 `padstack` | noise, noise, false, noise |
| parity | 33 `net_conflict`, all a renamed sheet | false; after the fixes 33 warnings, parity passes to warn |
| bom-lcsc | C1004-C1006 supercaps (`JLCPCB_IGNORE`), JP501/JP801 solder jumpers | true-by-contract (hand-fitted), false |
| stock (online) | R304 group and D202 out of stock; LMV321 low | true |
| catalogue-package (online) | D303 SMAF on D_SMA *different*; U401 QFN-20-EP(3x3) ambiguous though the pads match; Y801 crystal, headers, Phoenix block, inductors unknown | true, false unknown, false unknown (1), by design (6); after the fixes 1 different (D303), 63 agree, 6 by design |
| catalogue-category (online) | L701 common-mode choke | false |

### soldiercrab (fab: yes, Crowd Supply) — FAIL (after the fixes still FAIL: erc and drc)
| erc | 5 `power_pin_not_driven` | false |
| drc | 199 `solder_mask_bridge` (BGA-256); 10 `courtyards_overlap` (project: warning) | false |
| parity | REF** WEEE logo extra; 5 `lcsc#` field notes (IC1 C1521614 on the board vs C1550826 in the schematic) | false (after the fixes a note; parity is warn); warning worth reading |
| stock (online) | 13 MPN mismatches (`Substitution` field = substitutes allowed); U10, R7, D1/D2 out of stock; IC1 stock 1 | true-by-contract; true |
| catalogue-package (online) | U10 BGA24_6X8 *different*; Y1 SMD2520-4P on a 3225 footprint unknown (should be different); CABGA-256, XDFN-4 unknown | false; false unknown; by design; after the fixes Y1 is the 1 different (true), 24 agree, 3 by design |

### sonatino (fab: yes; no .kicad_pro in the repo) — FAIL
| erc | 12 `power_pin_not_driven`; 2 `pin_not_driven` | false, noise |
| drc | 471 `clearance` at KiCad's 0.2 mm default (artefact of the empty project file); 63 `courtyards_overlap`; 5 `copper_edge_clearance` tracks | noise (artefact), false, true |
| stock (online) | U15 WM8782 out of stock (discontinued, says the README); 2 low | true |
| catalogue-package (online) | Q3 TDFN-6-EP *different*; U13 TSSOP-16 and U15 SSOP-20 ambiguous though the pads match; U4 TP4056 PowerPAD (12 pads vs 9); 7 custom | false; false unknown (3); by design; after the fixes 50 agree, 7 by design |
| catalogue-category (online) | U3 SRV05-4 ESD array | false |

### pocketpd (fab: yes, Crowd Supply) — FAIL
| erc | 2 `power_pin_not_driven` | false |
| drc | 21 `clearance` (netclass 0.15 own); 16 `starved_thermal`; 10 `courtyards_overlap`; 2 `copper_edge_clearance` pads | noise, noise, false, true |
| bom-lcsc | SW1 `C9900176956` | false |
| stock (online) | U5 W25Q16, U1/U6 LM73100 out of stock | true |
| catalogue-package (online) | U2 WQFN4040-24, U3 LQFN-56 *different*; Y1 crystal unknown; 9 custom footprints unknown | false (2); false unknown; by design; after the fixes 23 agree, 9 by design |

### smarthome-metering-prefix / smarthome-metering (documented problem) — FAIL
| erc | 15 `pin_not_connected` on the ESP32 | noise |
| parity / dnp / placement | 76 missing footprints, 16 net conflicts, 2 / 4 footprint mismatches; C6/C7/R17 DNP not on the board; 117 of 119 bought references not placed | true: the board holds 4 footprints |
| bom-file | no LCSC data | true |

The wrong-footprint fix itself (SOT-23 on resistors) is invisible to the gate at either commit: the
resistors were never on the board, and without a catalogue code there is nothing to compare the footprint
with. The parity count moves from 94 to 96 because the fixed schematic now disagrees with the stale board
on two more footprints.

### beyondex-limiter-prefix / beyondex-limiter (documented problem) — FAIL
| erc | 1 `power_pin_not_driven` | false |
| drc | 6 `drill_out_of_range` (own 0.3 vs 0.2 mm thermal vias in U1's pad); 2 `clearance` (own 0.127 vs 0.11); the `.kicad_dru` is empty | noise |
| catalogue-package (online) | prefix: R1 0603 part on R_0402 *different*; HEAD: 6 same | true; — |

Between the two commits the only change the gate sees is the R1 verdict, which is the fix.

## What the corpus did not cover

No board with a regenerated schematic (fresh symbol uuids under a routed board) was found on GitHub;
the identity gate's orphan path is exercised only by the unit tests. No KiCad 8/9/10 board with a
documented DRC-fix commit that leaves both states buildable was small enough to include (the "fix DRC
errors" commits found are student projects without licences or with the fix and the layout in one
commit). Every corpus board is 2 to 10 layers; none uses variants.
