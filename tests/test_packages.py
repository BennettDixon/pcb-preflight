import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import checks, packages, report  # noqa: E402
from pcb_preflight.packages import DIFFERENT, SAME, UNKNOWN  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'packages.csv')


def fixture_rows():
    with open(FIXTURE, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(line for line in f if not line.startswith('#')))


class Fixture(unittest.TestCase):
    """Real footprint names against real catalogue strings: the regression corpus for packages.fits()."""

    def test_every_row(self):
        rows = fixture_rows()
        self.assertGreater(len(rows), 40)
        for r in rows:
            with self.subTest(footprint=r['footprint'], part=r['part']):
                self.assertIn(r['verdict'], (SAME, DIFFERENT, UNKNOWN))
                self.assertTrue(r['seen_in'].strip(), 'every row names the record it came from')
                f = packages.fits(r['footprint'], r['part'], r.get('mpn') or None)
                self.assertEqual(f.verdict, r['verdict'], f.reason)

    def test_fits_is_symmetric(self):
        for r in fixture_rows():
            if r.get('mpn'):
                continue
            with self.subTest(footprint=r['footprint'], part=r['part']):
                self.assertEqual(packages.fits(r['part'], r['footprint']).verdict, r['verdict'])

    def test_every_table_entry_has_a_source_and_a_row(self):
        tokens = set()
        for r in fixture_rows():
            for side in ('footprint', 'part'):
                tokens.update(packages._tokens(r[side]))
        for spelling, (canon, src) in packages.SYNONYMS.items():
            with self.subTest(synonym=spelling):
                self.assertTrue(src.strip())
                self.assertIn(spelling, tokens, f'{spelling} -> {canon} has no fixture row using it')
        for fam, (canon, _ep, src) in packages.FAMILIES.items():
            with self.subTest(family=fam):
                self.assertTrue(src.strip())
                self.assertTrue(any(packages.FAMILY_TOKEN.fullmatch(t) and packages.FAMILY_TOKEN.fullmatch(t).group(1) == fam
                                    for t in tokens), f'{fam} -> {canon} has no fixture row using it')


class Read(unittest.TestCase):
    def names(self, text):
        return set(packages.read(text).names)

    def test_chip_sizes(self):
        self.assertEqual(self.names('Capacitor_SMD:C_0805_2012Metric'), {'0805'})
        self.assertEqual(self.names('Fuse:Fuse_2920_7451Metric'), {'2920'})
        self.assertEqual(self.names('0603'), {'0603'})

    def test_sot_pin_counts(self):
        self.assertEqual(self.names('Package_TO_SOT_SMD:SOT-23'), {'SOT-23'})
        self.assertEqual(self.names('SOT-23-3'), {'SOT-23'})
        self.assertEqual(self.names('SOT-23-5'), {'SOT-23-5'})
        self.assertEqual(self.names('SOT-223-3_TabPin2'), {'SOT-223'})
        self.assertEqual(self.names('TO-263-2'), {'TO-263'})
        self.assertEqual(self.names('TO-263-7'), {'TO-263-7'})

    def test_exposed_pad_and_width(self):
        self.assertEqual(self.names('SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm'), {'SOIC-8-EP'})
        self.assertEqual(self.names('SOIC-8_3.9x4.9mm_P1.27mm'), {'SOIC-8'})
        self.assertEqual(self.names('SOIC-16W_7.5x10.3mm_P1.27mm'), {'SOIC-16-300MIL'})
        self.assertEqual(self.names('SOP-8_150mil'), {'SOIC-8'})
        self.assertEqual(self.names('LQFN-56(7x7)'), {'LQFN-56(7x7)'})

    def test_nothing_readable(self):
        for s in ('Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical', 'Inductor_SMD:L_Bourns_SRP1245A', 'Plugin', 'SMD,13.5x12.5mm', ''):
            self.assertEqual(self.names(s), set(), s)

    def test_fit_reports_the_table_entry_used(self):
        f = packages.fits('Package_TO_SOT_SMD:SOT-23-5', 'SOT-25-5')
        self.assertEqual(f.verdict, SAME)
        self.assertEqual(f.via[0][:2], ('SOT-25-5', 'SOT-23-5'))
        self.assertIn('C51118', f.reason)
        self.assertEqual(f.as_dict()['via'][0]['read_as'], 'SOT-23-5')


SCH = [
    {'Ref': 'U1', 'Value': 'LMR33630', 'Footprint': 'Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'U4', 'Value': 'AP2112K-3.3', 'Footprint': 'Package_TO_SOT_SMD:SOT-23-5', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'L1', 'Value': '10uH', 'Footprint': 'Inductor_SMD:L_Bourns_SRP1245A', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'J1', 'Value': 'J_IN', 'Footprint': 'TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-2-5.0-H_1x02_P5.00mm_Horizontal', 'DNP': False, 'ExcludeFromBOM': False},
]


def line(refs, package, lcsc='', verified=''):
    from pcb_preflight.bom import Line
    return Line(row=2, refs=refs, package=package, lcsc=lcsc, package_verified=verified)


class Gates(unittest.TestCase):
    def test_catalogue_package_gate(self):
        lines = [line(['U1'], 'SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm', 'C841384'),
                 line(['U4'], 'SOT-23-5', 'C51118'),
                 line(['L1'], 'L_Bourns_SRP1245A', 'C2042471'),
                 line(['J1'], 'TerminalBlock_Phoenix_PT-1,5-2-5.0-H_1x02_P5.00mm_Horizontal', 'C3819953', '2026-10-16: 1935161 drawing')]
        records = {'C841384': {'mpn': 'LMR33630ADDAR', 'package': 'ESOP-8'},
                   'C51118': {'mpn': 'AP2112K-3.3TRG1', 'package': 'SOT-25-5'},
                   'C2042471': {'mpn': 'MDA1350-100M', 'package': 'SMD,13.5x12.6mm'},
                   'C3819953': {'mpn': '1935161', 'package': 'Plugin,P=5mm'}}
        c = checks.catalogue_package_check(lines, records, SCH)
        self.assertEqual(c.status, 'pass', c.details)
        self.assertIn('2 agree', c.summary)
        self.assertEqual(len(c.unchecked), 1)
        self.assertIn('L1', c.unchecked[0])
        self.assertEqual(len(c.verified), 1)
        self.assertIn('1935161 drawing', c.verified[0])
        self.assertTrue(any('SOT-25-5 read as SOT-23-5' in d for d in c.details), 'the table entry used is recorded (JSON; printed when the gate is a finding)')

    def test_footprint_named_for_the_part(self):
        lines = [line(['L1'], 'L_Bourns_SRP1245A', 'C2042471')]
        c = checks.catalogue_package_check(lines, {'C2042471': {'mpn': 'SRP1245A-100M', 'package': 'SMD,13.5x12.5mm'}}, SCH)
        self.assertEqual(c.status, 'pass')
        self.assertEqual(c.unchecked, [])
        self.assertIn('drawn for this part (SRP1245A', c.details[0])

    def test_missing_exposed_pad_blocks(self):
        lines = [line(['U1'], 'SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm', 'C9865')]
        c = checks.catalogue_package_check(lines, {'C9865': {'mpn': 'TPS54331DR', 'package': 'SOIC-8'}}, SCH)
        self.assertEqual(c.status, 'fail')
        self.assertIn('footprint is SOIC-8-EP, part is SOIC-8', c.details[0])

    def test_nothing_comparable_is_a_skip(self):
        c = checks.bom_package_check([line(['L1'], 'SRP1245A')], SCH)
        self.assertEqual(c.status, 'skip')
        self.assertEqual(len(c.unchecked), 1)

    def test_report_lists_unchecked_items(self):
        partial = checks.Check('catalogue-package', 'Catalogue package fits the footprint', '§1', 'pass', '2 agree',
                               unchecked=['C2042471 (L1): ...'], verified=['C3819953 (J1): ...'])
        text = report.render({'project': 'p', 'kicad_version': '10', 'copper_layers': 4, 'footprints': 1,
                              'bom_path': 'bom.csv', 'checks': [partial], 'by_hand': []})
        self.assertIn('        by hand: C3819953 (J1)', text)
        self.assertIn('Catalogue package fits the footprint (§1): 1 not compared', text)
        self.assertIn('0 blocking, 0 warnings, 1 not checked  -  exit 3', text)
        self.assertEqual(report.verdict([partial]), 'NOT VERIFIED')     # an item nobody compared is not a pass


if __name__ == '__main__':
    unittest.main()
