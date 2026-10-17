import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import bom, checks  # noqa: E402


def write(text):
    f = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, newline='')
    f.write(text)
    f.close()
    return f.name


class LoadBom(unittest.TestCase):
    def test_loose_headers_and_refs(self):
        p = write('Reference,Value,Footprint,Part Number,LCSC Part #,Type,Stock,Datasheet URL\n'
                  '"C1,C7 C8",100nF,0603,CC0603KRX7R9BB104,c14663,basic,"49,455,161",https://x/y.pdf\n'
                  ',,,,,,,\n')
        lines, missing = bom.load(p)
        self.assertEqual(missing, [])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].refs, ['C1', 'C7', 'C8'])
        self.assertEqual(lines[0].lcsc, 'C14663')
        self.assertEqual(lines[0].stock_number, 49455161)
        self.assertEqual(bom.library_type(lines[0].library), 'Basic')
        self.assertEqual(lines[0].package_verified, '')

    def test_package_verified_column(self):
        p = write('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet,Package Checked\n'
                  'L1,10uH,L_Bourns_SRP1245A,SRP1245A-100M,C2042471,Extended,20,u,2026-10-16 BD: land pattern p.2\n')
        lines, missing = bom.load(p)
        self.assertEqual(missing, [])
        self.assertEqual(lines[0].package_verified, '2026-10-16 BD: land pattern p.2')
        self.assertEqual(lines[0].extra, {})

    def test_missing_columns(self):
        p = write('Ref,Value\nC1,100nF\n')
        lines, missing = bom.load(p)
        self.assertIn('LCSC', missing)
        self.assertEqual(lines[0].lcsc, '')


SCH = [
    {'Ref': 'C1', 'Value': '100nF', 'Footprint': 'Capacitor_SMD:C_0603_1608Metric', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'C2', 'Value': '10uF', 'Footprint': 'Capacitor_SMD:C_1210_3225Metric', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'D1', 'Value': 'SMF3.3A', 'Footprint': 'Diode_SMD:D_SOD-123', 'DNP': True, 'ExcludeFromBOM': False},
    {'Ref': 'FID1', 'Value': 'Fiducial', 'Footprint': 'Fiducial:Fiducial_1mm_Mask2mm', 'DNP': False, 'ExcludeFromBOM': True},
    {'Ref': 'TP1', 'Value': 'TP', 'Footprint': 'TestPoint:TestPoint_Pad_1.0x1.0mm', 'DNP': False, 'ExcludeFromBOM': False},
]


class Gates(unittest.TestCase):
    def lines(self, text):
        return bom.load(write('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet\n' + text))[0]

    def test_lcsc_missing_fails(self):
        c = checks.bom_lcsc_check(self.lines('C1,100nF,0603,,,,,\nC2,10uF,1210,X,C1234,Basic,100,u\n'))
        self.assertEqual(c.status, 'fail')
        self.assertIn('1 of 2', c.summary)

    def test_refs_against_schematic(self):
        c = checks.bom_refs_check(self.lines('"C1,D1",100nF,0603,M,C1,Basic,1,u\nR9,1k,0603,M,C2,Basic,1,u\n'), SCH, checks.DEFAULT_SKIP_PREFIXES)
        self.assertEqual(c.status, 'fail')
        joined = ' '.join(c.details)
        self.assertIn('not in bom.csv: C2', joined)
        self.assertIn('not in the schematic: R9', joined)
        self.assertIn('DNP in the schematic but listed', joined)

    def test_refs_pass_skips_fiducials_and_testpoints(self):
        c = checks.bom_refs_check(self.lines('C1,100nF,0603,M,C1,Basic,1,u\nC2,10uF,1210,M,C2,Basic,1,u\n'), SCH, checks.DEFAULT_SKIP_PREFIXES)
        self.assertEqual(c.status, 'pass', c.details)

    def test_package_mismatch(self):
        c = checks.catalogue_package_check(self.lines('C2,10uF 50V X7R,0805,M,C1,Basic,1,u\n'), {'C1': {'mpn': 'M', 'package': '0805'}}, SCH)
        self.assertEqual(c.status, 'fail')
        self.assertIn('1210', c.details[0])

    def test_stock_gate_with_fake_catalogue(self):
        cat = {
            'C1': {'mpn': 'CC0603KRX7R9BB104', 'package': '0603', 'library': 'Basic', 'stock': 5, 'description': ''},
            'C2': {'mpn': 'OTHERPART', 'package': '1210', 'library': 'Extended', 'stock': 100000, 'description': ''},
        }
        def lookup(code):
            if code == 'C3':
                return None
            if code == 'C4':
                raise checks.stock.LookupFailed('offline')
            return cat[code]
        lines = self.lines('"C1,C7",100nF,0603,CC0603KRX7R9BB104,C1,Basic,1,u\n'
                           'C2,10uF,1210,GRM32ER71H106KA12L,C2,Basic,1,u\n'
                           'R1,1k,0603,X,C3,Basic,1,u\n'
                           'R2,2k,0603,X,C4,Basic,1,u\n'
                           'R3,3k,0603,X,,Basic,1,u\n')
        c = checks.stock_check(lines, multiple=10, lookup=lookup)
        self.assertEqual(c.status, 'fail')
        joined = '\n'.join(c.details)
        self.assertIn('stock 5 is under 10x the 2 needed', joined)
        self.assertIn('bom.csv says MPN "GRM32ER71H106KA12L"', joined)
        self.assertIn('says Basic but the catalogue says Extended', joined)
        self.assertIn('C3 (R1): not in the JLCPCB catalogue', joined)
        self.assertNotIn('C4 (R2)', joined, 'a failed lookup is not a detail of the gate: it goes under NOT CHECKED')
        self.assertEqual(len(c.unchecked), 1)
        self.assertIn('C4 (R2): lookup failed (offline)', c.unchecked[0])
        self.assertIn('1 Extended part types', c.summary)


if __name__ == '__main__':
    unittest.main()
