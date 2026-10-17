"""The regression corpus (corpus/README.md): the offline gates on real public boards, frozen as a baseline.

Runs `preflight check` on every corpus board present under corpus/boards/ (fetched by corpus/fetch.sh;
skipped when absent, as is the whole module when kicad-cli is not installed) with the bom.csv under
corpus/boms/, and asserts what corpus/RESULTS.md triaged on 2026-10-17: the verdict, which gates block,
and the counts the gate's own logic produces (identity, parity, unrouted, placement, DNP, bom-lcsc).
KiCad's own ERC/DRC counts are asserted by status only, since they move with the KiCad release (the
baseline was taken with kicad-cli 10.0.7).

The baseline freezes behaviour, not correctness: RESULTS.md says which of these numbers are false
failures (the 29 and 78 "renamed" footprints, the 68 and 115 library-nickname parity mismatches, the
canfd-mc net conflict, cm5-minima's screw). A change that fixes one of them is expected to break the
matching assertion here, and the baseline is then updated with the new, triaged number.

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
    'beyondex-limiter-prefix': ('FAIL', {'erc', 'drc'}, {'bom-lcsc': '6 lines, each with a C-number'}),
    'beyondex-limiter': ('FAIL', {'erc', 'drc'}, {'bom-lcsc': '6 lines, each with a C-number'}),
    'bitaxeaura': ('FAIL', {'erc', 'drc', 'unrouted', 'parity', 'bom-lcsc'},
                   {'unrouted': '291 connections still to route', 'parity': '4 mismatches across 193 footprints',
                    'bom-lcsc': '47 of 49 lines have no LCSC code'}),
    'bitaxegt': ('FAIL', {'erc', 'drc', 'bom-lcsc'}, {'bom-lcsc': '35 of 39 lines have no LCSC code',
                                                      'identity': '186 of 187 footprints name a symbol in the schematic, 1 board-only'}),
    'canfd-mc': ('FAIL', {'parity'}, {'parity': '1 mismatches across 51 footprints', 'identity': '51 of 51 footprints'}),
    'cm5-minima': ('FAIL', {'erc', 'drc', 'parity', 'placement', 'bom-lcsc'},
                   {'parity': '5 mismatches across 112 footprints', 'placement': '1 of 72 bought references',
                    'bom-lcsc': '37 of 43 lines have no LCSC code'}),
    'complex-hierarchy': ('FAIL', {'parity', 'identity', 'bom-file'},
                          {'identity': '0 orphaned, 0 unlinked, 29 renamed of 68 footprints', 'parity': '68 mismatches across 68 footprints'}),
    'jetson-thor-baseboard': ('FAIL', {'erc', 'drc', 'bom-file'}, {'identity': '1123 of 1125 footprints name a symbol in the schematic, 2 board-only'}),
    'jlcpcb-example': ('FAIL', {'erc'}, {'bom-lcsc': '11 lines, each with a C-number', 'parity': '0 mismatches across 19 footprints'}),
    'multichannel': ('FAIL', {'erc', 'drc', 'parity', 'identity', 'bom-file'},
                     {'identity': '0 orphaned, 0 unlinked, 78 renamed of 114 footprints', 'parity': '115 mismatches across 114 footprints'}),
    'multichannel-unrouted': ('FAIL', {'erc', 'drc', 'unrouted', 'parity', 'identity', 'bom-file'},
                              {'unrouted': '148 connections still to route', 'identity': '78 renamed of 114 footprints',
                               'parity': '1 mismatches across 114 footprints'}),
    'openair-max': ('FAIL', {'erc', 'drc', 'parity', 'dnp', 'bom-lcsc'},
                    {'parity': '14 mismatches, 1 field/filter notes across 210 footprints', 'dnp': '2 DNP parts inconsistent',
                     'bom-lcsc': '3 of 84 lines have no LCSC code'}),
    'openjbod-rp2040': ('FAIL', {'erc', 'drc', 'unrouted', 'parity'},
                        {'unrouted': '5 connections still to route', 'parity': '6 mismatches across 129 footprints',
                         'bom-lcsc': '49 lines, each with a C-number'}),
    'pocketpd': ('FAIL', {'erc', 'drc', 'bom-lcsc'}, {'bom-lcsc': '1 of 34 lines have no LCSC code', 'parity': '0 mismatches, 73 field/filter notes'}),
    'royalblue54l-feather': ('FAIL', {'erc', 'drc', 'bom-lcsc'}, {'bom-lcsc': '2 of 29 lines have no LCSC code'}),
    'sh-rpi': ('FAIL', {'drc', 'parity', 'bom-lcsc'}, {'parity': '33 mismatches across 168 footprints', 'bom-lcsc': '3 of 77 lines have no LCSC code'}),
    'smarthome-metering-prefix': ('FAIL', {'erc', 'parity', 'dnp', 'placement', 'bom-file'},
                                  {'parity': '94 mismatches across 4 footprints', 'placement': '117 of 119 bought references', 'dnp': '3 DNP parts inconsistent'}),
    'smarthome-metering': ('FAIL', {'erc', 'parity', 'dnp', 'placement', 'bom-file'},
                           {'parity': '96 mismatches across 4 footprints', 'placement': '117 of 119 bought references', 'dnp': '3 DNP parts inconsistent'}),
    'soldiercrab': ('FAIL', {'erc', 'drc', 'parity'}, {'parity': '1 mismatches, 5 field/filter notes across 77 footprints', 'bom-lcsc': '29 lines, each with a C-number'}),
    'sonatino': ('FAIL', {'erc', 'drc'}, {'bom-lcsc': '57 lines, each with a C-number', 'parity': '0 mismatches across 129 footprints'}),
    'tiny-tapeout': ('FAIL', {'erc', 'drc', 'unrouted', 'bom-lcsc'}, {'unrouted': '1 connections still to route', 'bom-lcsc': '28 of 32 lines have no LCSC code'}),
}

# Online (opt-in): catalogue-package summary per board, 2026-10-17. RESULTS.md: of the 12 "do not fit", 3 are right.
ONLINE_PACKAGE = {
    'beyondex-limiter-prefix': '1 do not fit the footprint; 5 agree',
    'beyondex-limiter': '6 agree with their footprint',
    'bitaxeaura': '1 do not fit the footprint; 0 agree with their footprint, 1 not compared',
    'bitaxegt': '2 agree with their footprint, 2 not compared',
    'canfd-mc': '24 agree with their footprint, 2 not compared',
    'cm5-minima': '5 agree with their footprint, 1 not compared',
    'jlcpcb-example': '9 agree with their footprint, 2 not compared',
    'openair-max': '2 do not fit the footprint; 14 agree with their footprint, 65 not compared',
    'openjbod-rp2040': '2 do not fit the footprint; 39 agree with their footprint, 8 not compared',
    'pocketpd': '2 do not fit the footprint; 20 agree with their footprint, 10 not compared',
    'royalblue54l-feather': '1 do not fit the footprint; 19 agree with their footprint, 7 not compared',
    'sh-rpi': '1 do not fit the footprint; 61 agree with their footprint, 8 not compared',
    'soldiercrab': '1 do not fit the footprint; 23 agree with their footprint, 4 not compared',
    'sonatino': '1 do not fit the footprint; 46 agree with their footprint, 10 not compared',
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


if __name__ == '__main__':
    unittest.main()
