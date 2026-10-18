"""The regression corpus (corpus/README.md): the offline gates on real public boards, frozen as a baseline.

Runs `preflight check` on every corpus board present under corpus/boards/ (fetched by corpus/fetch.sh;
skipped when absent, as is the whole module when kicad-cli is not installed) with the bom.csv under
corpus/boms/, and asserts what corpus/RESULTS.md triaged on 2026-10-17: the verdict, which gates block,
and the counts the gate's own logic produces (identity, parity, unrouted, placement, DNP, bom-lcsc).
KiCad's own ERC/DRC counts are asserted by status only, since they move with the KiCad release (the
baseline was taken with kicad-cli 10.0.7).

The baseline freezes behaviour, not correctness: RESULTS.md says which of these numbers are false
failures (cm5-minima's screw, the ERC power_pin_not_driven and DRC courtyard/mask blocks the preset has
not decided on). A change that fixes one of them is expected to break the matching assertion here, and
the baseline is then updated with the new, triaged number; the 2026-10-17 fixes of the identity gate
(185 false "renamed"), the parity gate (nickname-only, padless, renamed-sheet, no-connect and skipped-
prefix items: 233) and the package reader did that once, and canfd-mc became the first board to leave
FAIL (NOT VERIFIED offline). The policy decisions of the same day (preset.ERC_DEMOTED: KiCad's
electrical-intent ERC errors as warnings; preset.DRC_DEMOTED: courtyards_overlap and solder_mask_bridge as
warnings) did it again: ERC blocks no board any more, and jlcpcb-example and soldiercrab left FAIL. Then
"whose rule is it" (checks.FLOORED): a DRC violation whose measured figure still clears the fab's floor is
the project's own stricter rule and a warning; both beyondex boards left FAIL, and what blocks the built
boards now is copper_edge_clearance (the fab's 0.2 mm figure), hole_clearance and annular_width (no floor
in the preset yet), starved_thermal, and the true findings. Then the ORDER section (2026-10-18): the hole
floor moved from the smallest standard drill (0.15 mm) to the smallest priced tier (0.10 mm), so
jetson-thor-baseboard's 0.1 mm holes stopped blocking and became its ORDER lines; royalblue54l-feather
keeps its drill_out_of_range block, since its 183 blind vias carry a 1e-05 mm drill, below every tier.
ORDER freezes, per board, the drivers the order gate reads off the standard tier (never the verdict).

  PREFLIGHT_CORPUS_BOARDS=canfd-mc,sh-rpi   run a subset
  PREFLIGHT_CORPUS_ONLINE=1                  also run the catalogue pass (network; stock moves daily,
                                             only the package-fit counts are asserted)
"""
import contextlib
import io
import json
import os
import tempfile
import unittest

from pcb_preflight import cli, kicad

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARDS = os.path.join(ROOT, 'corpus', 'boards')
BOMS = os.path.join(ROOT, 'corpus', 'boms')

# board -> (result, blocking gates, {gate: substring of its summary})
BASELINE = {
    'beyondex-limiter': ('NOT VERIFIED', set(),
                {'bom-lcsc': '6 lines, each with a C-number'}),
    'beyondex-limiter-prefix': ('NOT VERIFIED', set(),
                {'bom-lcsc': '6 lines, each with a C-number'}),
    'bitaxeaura': ('FAIL', {'bom-lcsc', 'drc', 'parity', 'unrouted'},
                {'bom-lcsc': '47 of 49 lines have no LCSC code',
                 'parity': '4 mismatches across 193 footprints',
                 'unrouted': '291 connections still to route'}),
    'bitaxegt': ('FAIL', {'bom-lcsc', 'drc'},
                {'bom-lcsc': '35 of 39 lines have no LCSC code',
                 'identity': '186 of 187 footprints name a symbol in the schematic, 1 board-only'}),
    'canfd-mc': ('NOT VERIFIED', set(),
                {'identity': '51 of 51 footprints', 'parity': '0 mismatches, 1 warnings across 51 footprints'}),
    'cm5-minima': ('FAIL', {'bom-lcsc', 'drc', 'parity', 'placement'},
                {'bom-lcsc': '37 of 43 lines have no LCSC code',
                 'parity': '4 mismatches across 112 footprints; 1 padless footprint items not counted',
                 'placement': '1 of 72 bought references'}),
    'complex-hierarchy': ('FAIL', {'bom-file'},
                {'identity': '68 of 68 footprints name a symbol in the schematic',
                 'parity': '0 mismatches, 68 warnings across 68 footprints'}),
    'jetson-thor-baseboard': ('FAIL', {'bom-file'},
                {'identity': '1123 of 1125 footprints name a symbol in the schematic, 2 board-only',
                 'drc': '0 errors'}),
    'jlcpcb-example': ('NOT VERIFIED', set(),
                {'bom-lcsc': '11 lines, each with a C-number', 'parity': '0 mismatches across 19 footprints'}),
    'multichannel': ('FAIL', {'bom-file', 'parity'},
                {'identity': '114 of 114 footprints name a symbol in the schematic',
                 'parity': '1 mismatches, 114 warnings across 114 footprints'}),
    'multichannel-unrouted': ('FAIL', {'bom-file', 'parity', 'unrouted'},
                {'identity': '114 of 114 footprints name a symbol in the schematic',
                 'parity': '1 mismatches across 114 footprints',
                 'unrouted': '148 connections still to route'}),
    'openair-max': ('FAIL', {'bom-lcsc', 'dnp', 'drc', 'parity'},
                {'bom-lcsc': '3 of 84 lines have no LCSC code',
                 'dnp': '2 DNP parts inconsistent',
                 'parity': '3 mismatches, 1 field/filter notes across 210 footprints; 11 padless footprint items not counted'}),
    'openjbod-rp2040': ('FAIL', {'drc', 'parity', 'unrouted'},
                {'bom-lcsc': '49 lines, each with a C-number',
                 'parity': '1 mismatches, 2 warnings across 129 footprints; 3 padless footprint items not counted',
                 'unrouted': '5 connections still to route'}),
    'pocketpd': ('FAIL', {'bom-lcsc', 'drc'},
                {'bom-lcsc': '1 of 34 lines have no LCSC code', 'parity': '0 mismatches, 73 field/filter notes'}),
    'royalblue54l-feather': ('FAIL', {'bom-lcsc', 'drc'},
                {'bom-lcsc': '2 of 29 lines have no LCSC code'}),
    'sh-rpi': ('FAIL', {'bom-lcsc', 'drc'},
                {'bom-lcsc': '3 of 77 lines have no LCSC code', 'parity': '0 mismatches, 33 warnings across 168 footprints'}),
    'smarthome-metering': ('FAIL', {'bom-file', 'dnp', 'parity', 'placement'},
                {'dnp': '3 DNP parts inconsistent',
                 'parity': '96 mismatches across 4 footprints',
                 'placement': '117 of 119 bought references'}),
    'smarthome-metering-prefix': ('FAIL', {'bom-file', 'dnp', 'parity', 'placement'},
                {'dnp': '3 DNP parts inconsistent',
                 'parity': '94 mismatches across 4 footprints',
                 'placement': '117 of 119 bought references'}),
    'soldiercrab': ('NOT VERIFIED', set(),
                {'bom-lcsc': '29 lines, each with a C-number',
                 'parity': '0 mismatches, 5 field/filter notes across 77 footprints; 1 padless footprint items not counted'}),
    'sonatino': ('FAIL', {'drc'},
                {'bom-lcsc': '57 lines, each with a C-number', 'parity': '0 mismatches across 129 footprints'}),
    'tiny-tapeout': ('FAIL', {'bom-lcsc', 'drc', 'unrouted'},
                {'bom-lcsc': '28 of 32 lines have no LCSC code', 'unrouted': '1 connections still to route'}),
}

# board -> the order gate's drivers off JLCPCB's standard tier, offline (the word before the colon on each ORDER line);
# an empty list is a board on the standard tier everywhere (status pass). With --online the gate adds "parts"
# (Extended part types) where the catalogue says so. corpus/RESULTS.md "ORDER on the corpus" reads these.
ORDER = {
    'beyondex-limiter': [],
    'beyondex-limiter-prefix': [],
    'bitaxeaura': ['layers', 'size', 'placement', 'through-hole'],
    'bitaxegt': ['layers', 'size', 'placement', 'through-hole'],
    'canfd-mc': ['layers'],
    'cm5-minima': ['layers', 'placement', 'through-hole', 'impedance control'],
    'complex-hierarchy': ['size', 'through-hole'],
    'jetson-thor-baseboard': ['vias', 'holes', 'layers', 'size', 'placement', 'through-hole', 'assembly class'],
    'jlcpcb-example': ['vias', 'size', 'through-hole'],
    'multichannel': ['size', 'placement', 'through-hole'],
    'multichannel-unrouted': ['size', 'placement', 'through-hole'],
    'openair-max': ['layers', 'placement', 'through-hole'],
    'openjbod-rp2040': ['layers', 'size', 'through-hole'],
    'pocketpd': ['through-hole'],
    'royalblue54l-feather': ['vias', 'holes', 'layers', 'assembly class', 'castellated holes'],
    'sh-rpi': ['vias', 'layers', 'placement', 'through-hole'],
    'smarthome-metering': ['size', 'through-hole'],
    'smarthome-metering-prefix': ['size', 'through-hole'],
    'soldiercrab': ['vias', 'layers', 'placement'],
    'sonatino': ['vias', 'layers', 'through-hole'],
    'tiny-tapeout': ['layers', 'size', 'through-hole', 'impedance control'],
}


def drivers(report):
    order = next(c for c in report['checks'] if c['id'] == 'order')
    return [d.split(':', 1)[0] for d in order['details']]


# Online (opt-in): catalogue-package summary per board, 2026-10-17 after the package-reader fixes. RESULTS.md: the 4 "do
# not fit" are right (the three documented problems and soldiercrab's 2520 oscillator on a 3225 footprint); the first run
# had 12, 9 of them wrong, and 120 not compared, 82 of them spellings the table now reads.
ONLINE_PACKAGE = {
    'beyondex-limiter-prefix': '1 do not fit the footprint; 5 agree',
    'beyondex-limiter': '6 agree with their footprint',
    'bitaxeaura': '1 do not fit the footprint; 1 agree with their footprint',
    'bitaxegt': '3 agree with their footprint, 1 not compared',
    'canfd-mc': '26 agree with their footprint',
    'cm5-minima': '5 agree with their footprint, 1 not compared',
    'jlcpcb-example': '11 agree with their footprint',
    'openair-max': '69 agree with their footprint, 12 not compared',
    'openjbod-rp2040': '44 agree with their footprint, 5 not compared',
    'pocketpd': '23 agree with their footprint, 9 not compared',
    'royalblue54l-feather': '22 agree with their footprint, 5 not compared',
    'sh-rpi': '1 do not fit the footprint; 63 agree with their footprint, 6 not compared',
    'soldiercrab': '1 do not fit the footprint; 24 agree with their footprint, 3 not compared',
    'sonatino': '50 agree with their footprint, 7 not compared',
    'tiny-tapeout': '4 agree with their footprint',
}


def _cli_present():
    try:
        kicad.find_cli()
        return True
    except kicad.KicadError:
        return False


def _present():
    wanted = os.environ.get('PREFLIGHT_CORPUS_BOARDS')
    names = [n.strip() for n in wanted.split(',')] if wanted else sorted(BASELINE)
    return [n for n in names if os.path.isdir(os.path.join(BOARDS, n))]


def report_without_order(report):
    """The verdict the same checks give with the order gate removed (report.verdict on the JSON's statuses)."""
    from pcb_preflight import checks as checklib, report as reportlib
    kept = [checklib.Check(c['id'], c['title'], c['pitfall'], c['status'], c['summary'], unchecked=c['unchecked'])
            for c in report['checks'] if c['id'] != 'order']
    return reportlib.verdict(kept, report['options']['strict'])


def run(name, online=False):
    out = os.path.join(tempfile.mkdtemp(prefix='corpus-test-'), name + '.json')
    argv = ['check', os.path.join(BOARDS, name), '--bom', os.path.join(BOMS, name + '.csv'), '--quiet', '--json', out]
    if online:
        argv.append('--online')
    with contextlib.redirect_stdout(io.StringIO()):          # the report goes to the JSON; the test reads that
        code = cli.main(argv)
    with open(out, encoding='utf-8') as f:
        return code, json.load(f)


@unittest.skipUnless(_cli_present(), 'kicad-cli not installed')
@unittest.skipUnless(os.path.isdir(BOARDS) and _present(), 'corpus not fetched (sh corpus/fetch.sh)')
class CorpusBaseline(unittest.TestCase):
    """What the offline gates say about each corpus board on disk, as triaged in corpus/RESULTS.md."""

    def test_offline(self):
        for name in _present():
            result, blocking, summaries = BASELINE[name]
            with self.subTest(board=name):
                code, report = run(name)
                self.assertEqual(report['result'], result, name)
                self.assertEqual(code, report['exit_code'])
                checks = {c['id']: c for c in report['checks']}
                self.assertEqual({cid for cid, c in checks.items() if c['status'] == 'fail'}, blocking, name)
                for cid, text in summaries.items():
                    self.assertIn(cid, checks, name)
                    self.assertIn(text, checks[cid]['summary'], f'{name} {cid}: {checks[cid]["summary"]}')
                # offline, the catalogue is never consulted and the result is never a pass
                self.assertEqual(checks['stock']['status'], 'skip')
                self.assertNotEqual(report['result'], 'PASS')
                # the order gate: its drivers, and a status that never reaches the verdict
                self.assertEqual(drivers(report), ORDER[name], name)
                self.assertEqual(checks['order']['status'], 'cost' if ORDER[name] else 'pass', name)
                self.assertEqual(report['result'], report_without_order(report), name)

    def test_order_drivers_match_the_boards_own_files(self):
        """Spot checks a reader can repeat with grep on the board file (corpus/RESULTS.md "ORDER on the corpus")."""
        wanted = {'jetson-thor-baseboard': ('vias', '0.1 mm hole', '3235 of 3235 vias'),
                  'jlcpcb-example': ('vias', '0.2 mm hole', '30 of 101 vias'),
                  'royalblue54l-feather': ('castellated holes', 'set in the stackup', 'Standard PCBA'),
                  'soldiercrab': ('vias', '0.15 mm hole', '0.15mm/(0.25/0.3mm)'),
                  'openjbod-rp2040': ('size', '72.61 × 170 mm', 'Engineering fee')}
        for name, (driver, *texts) in wanted.items():
            if name not in _present():
                continue
            with self.subTest(board=name):
                _, report = run(name)
                line = next(d for d in next(c for c in report['checks'] if c['id'] == 'order')['details'] if d.startswith(driver + ':'))
                for text in texts:
                    self.assertIn(text, line)

    def test_documented_problems_are_the_only_difference(self):
        """BeyondexLimiter before and after 'Fix wrong footprint for R1': offline, the reports agree gate for gate
        (the fix is a package the catalogue has to be asked about; corpus/RESULTS.md)."""
        pair = ('beyondex-limiter-prefix', 'beyondex-limiter')
        if not all(os.path.isdir(os.path.join(BOARDS, n)) for n in pair):
            self.skipTest('both BeyondexLimiter states are needed')
        before, after = (run(n)[1] for n in pair)
        self.assertEqual([(c['id'], c['status']) for c in before['checks']], [(c['id'], c['status']) for c in after['checks']])


@unittest.skipUnless(os.environ.get('PREFLIGHT_CORPUS_ONLINE') == '1', 'set PREFLIGHT_CORPUS_ONLINE=1 to ask the catalogue')
@unittest.skipUnless(_cli_present(), 'kicad-cli not installed')
@unittest.skipUnless(os.path.isdir(BOARDS) and _present(), 'corpus not fetched (sh corpus/fetch.sh)')
class CorpusOnline(unittest.TestCase):
    """The catalogue-package verdict counts per board (stock changes daily and is not asserted)."""

    def test_package_verdicts(self):
        for name in _present():
            if name not in ONLINE_PACKAGE:
                continue
            with self.subTest(board=name):
                code, report = run(name, online=True)
                checks = {c['id']: c for c in report['checks']}
                self.assertIn('catalogue-package', checks, name)
                self.assertIn(ONLINE_PACKAGE[name], checks['catalogue-package']['summary'], f'{name}: {checks["catalogue-package"]["summary"]}')
                self.assertNotEqual(report['result'], 'PASS')
                found = drivers(report)
                self.assertEqual([d for d in found if d != 'parts'], ORDER[name], f'{name}: online adds at most the Extended count')


if __name__ == '__main__':
    unittest.main()
