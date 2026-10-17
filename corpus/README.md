# Regression corpus

Public, open-source KiCad 8/9/10 projects the gate is run against, so its rules stop being tuned to the
one board it was written on (`examples/sorter_pdb_v0`). Twenty-one board directories from eighteen
projects: boards that were ordered, assembled and sold (with LCSC codes in their symbol fields or a
JLCPCB BOM in the repo), KiCad's own demo boards (hierarchical, reused sheets, a custom-rules file, a
deliberately unrouted board), and three repositories with a documented wrong-footprint commit or issue,
kept at the commit before the fix and at the fix.

What the gate makes of them, and what of that is right, is in [RESULTS.md](RESULTS.md).

## Files

| | |
|:--|:--|
| `index.csv` | one row per board: source URL, pinned commit, licence, KiCad version, copper layers, footprint count, sheet files, LCSC field, why it is here, whether it is believed fab-ready and the evidence |
| `fetch.sh` | downloads every board at its pinned commit into `boards/<name>/` (gitignored): the KiCad files, project libraries, licence, README and any BOM; no Gerbers, 3D models or images. `sh corpus/fetch.sh [name...]` |
| `boms/<name>.csv` | the bom.csv the runs used, one per board with LCSC data, built by `make_boms.py` from the board's own symbol fields (its LCSC field, its part-number field, its Package field where it has one; else the footprint name, as `preflight bom-template` writes it). Boards without LCSC data run without a BOM |
| `make_boms.py` | rebuilds `boms/` from `boards/` (the per-board field names are its CONFIG table); runs kicad-cli on a copy, writes nothing under `boards/` |
| `run.sh` | runs the gate on every fetched board: `results/<name>.json` and `.txt` offline, `results/online/<name>.json` and `.txt` with `--online` for the boards whose BOM carries codes. `sh corpus/run.sh [--online|--online-only] [name...]` |
| `results/` | the reports of 2026-10-17 (kicad-cli 10.0.7; pcb-preflight main `e88e6b4` plus the identity, parity and package fixes RESULTS.md records, rerun after the triage). The JSON is what `tests/test_corpus.py` freezes |
| `RESULTS.md` | the triage: every blocking and not-checked finding sorted into true, false, noise or unknown with its evidence; the rule changes and fixture rows the corpus justifies |

## The boards

Pinned commits, licences and the rest are in `index.csv`; the short version:

**Fabricated, assembled or sold, with LCSC data** (fab-ready unless the gate finds otherwise):
openair-max (AirGradient, KiCad demo; Fabrication Toolkit), royalblue54l-feather (Lords Boards, Crowd
Supply; KiCad demo), tiny-tapeout (demo board 0.9.4 with its Gerbers; KiCad demo), cm5-minima (piecol;
NextPCB), canfd-mc (ordered at JLCPCB 2026-09, with its JLCPCB BOM), openjbod-rp2040, bitaxegt, sh-rpi
(Hat Labs; JLCPCB BOM in the repo), soldiercrab (apf.audio, Crowd Supply; JLCPCB BOM in the repo),
sonatino (Lumination Labs), pocketpd (CentyLab, Crowd Supply), jlcpcb-example (drawn from the JLCPCB
KiCad Library; a test board), jetson-thor-baseboard (Antmicro, 10 layers, `.kicad_dru`; KiCad demo).

**KiCad's own demos for hierarchy:** complex-hierarchy (one sheet placed twice), multichannel (one sheet
placed four times) and multichannel-unrouted (the demo's unrouted board swapped in under the project
name).

**Documented problems:** bitaxeaura (issue #1: 0603 capacitors on 0402 footprints; mid-layout),
beyondex-limiter-prefix / beyondex-limiter (commit 3256bd86 "Fix wrong footprint for R1": 0402 → 0603),
smarthome-metering-prefix / smarthome-metering (commit e928c28f "Fix wrong footprints": SOT-23 on
resistors; the board was never laid out at either commit).

Two corrections fetch.sh makes, both said in the script: Sonatino's repository gitignores `*.kicad_pro`,
so an empty one is written (the gate refuses a project without one); multichannel-unrouted is a copy of
multichannel with the other board file renamed.

## Licences

Every board is under an open-hardware or permissive licence (CERN-OHL-P/S 2.0, MIT, Apache-2.0,
CC-BY-4.0, CC-BY-SA-4.0, EUPL-1.2, GPL-3.0 for the KiCad repository's own demos); each checkout keeps its
licence file. The corpus is used to run a checker over the files; nothing from them is redistributed in
this repository except the file names, reference designators, part numbers and KiCad's own report lines
quoted in RESULTS.md and frozen in the test.

## Reproducing

```bash
sh corpus/fetch.sh                      # ~150 MB of checkouts under corpus/boards/ (gitignored)
python3 -I corpus/make_boms.py          # rebuild corpus/boms/ from the symbol fields
sh corpus/run.sh                        # offline, every board, about 2 minutes
sh corpus/run.sh --online-only          # the catalogue pass, about 7 minutes and ~400 lookups
python3 -m unittest tests.test_corpus   # the frozen baseline against the boards on disk
```

The online results depend on JLCPCB's stock on the day; the offline ones only on the files, KiCad and the
gate.
