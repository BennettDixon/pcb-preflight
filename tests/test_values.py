"""Values: bom.csv against the schematic, and the catalogue record against the reference prefix and the value's figures."""
import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import checks, report, values  # noqa: E402
from pcb_preflight.bom import Line  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'catalogue.csv')


def fixture_rows():
    with open(FIXTURE, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(line for line in f if not line.startswith('#')))


class Normalize(unittest.TestCase):
    def test_spellings_fold(self):
        for a, b in [('10uF', '10 µF'), ('10uF', '10μF'), ('10uF', '10 uf'), ('100R', '100Ω'), ('100R', '100 ohm'), ('100R', '100 ohms'),
                     ('4k7', '4.7k'), ('4k7 1%', '4.7k 1%'), ('22K', '22k'), ('1uF 50V X7R', '1uF  50V  x7r'), ('2u2', '2.2u')]:
            self.assertEqual(values.normalize(a), values.normalize(b), (a, b))

    def test_values_stay_apart(self):
        for a, b in [('100nF', '0.1uF'), ('10uF', '10nF'), ('10k', '10k 1%'), ('', '10k'), ('1uF 50V', '1uF 16V')]:
            self.assertNotEqual(values.normalize(a), values.normalize(b), (a, b))
        self.assertEqual(values.normalize(None), '')


class Quantities(unittest.TestCase):
    def check(self, text, expected, resistor=False):
        got = values.quantities(text, resistor)
        self.assertEqual(set(got), set(expected), text)
        for unit, figures in expected.items():
            self.assertEqual(len(got[unit]), len(figures), text)
            for x, y in zip(got[unit], figures):
                self.assertAlmostEqual(x, y, delta=abs(y) * 1e-9, msg=text)

    def test_units_read(self):
        self.check('100nF 50V X7R', {'F': [1e-7], 'V': [50.0]})
        self.check('10uH SRP1245A-100M', {'H': [1e-5]})
        self.check('BLM41PG600SN1L 60R 6A', {'Ω': [60.0]})
        self.check('1 60Ω@100MHz 6A 9mΩ ±25% 1806 Ferrite Beads ROHS', {'Ω': [60.0, 0.009]})
        self.check('LMR33630ADDAR 5.1 V', {'V': [5.1]})
        self.check('-40℃~+85℃ 100mW 120° 2.6V~3.1V 430mcd 513nm~528nm 5mA', {'V': [2.6, 3.1]})
        self.check('500uA@40V', {'V': [40.0]})

    def test_what_is_not_a_figure(self):
        for s in ('AP2112K-3.3', '1N4148W', 'SS54', 'MMBT2222A', '0603', '±10%', '100mW', '500uA', '400kHz', '12MHz', '2000hrs@105℃', '6.3mm',
                  'SMD,13.5x12.5mm', 'J_IN', 'green VIN_F', 'green +12V', 'green +5V_PI', '+3V3_PROBE', 'VBUS'):
            self.assertEqual(values.quantities(s), {}, s)

    def test_unitless_magnitudes_are_ohms_on_a_resistor_line_only(self):
        self.check('10k 1%', {'Ω': [1e4]}, resistor=True)
        self.check('4k7', {'Ω': [4700.0]}, resistor=True)
        self.check('1M', {'Ω': [1e6]}, resistor=True)
        self.check('10k 1%', {})
        self.check('10uH SRP1245A-100M', {'H': [1e-5]}, resistor=True)
        self.check('15uH SRP1245A-150M', {'H': [1.5e-5]})


class Compare(unittest.TestCase):
    def test_voltage_is_a_floor_other_units_are_equalities(self):
        desc = '-40℃~+105℃ 100uF 2000hrs@105℃ 25V 6.3mm 7.7mm ±20% SMD,D6.3xL7.7mm Aluminum Electrolytic Capacitors - SMD ROHS'
        self.assertEqual(values.compare('100uF 16V', desc)[0], [])
        self.assertEqual(values.compare('100uF 25V', desc)[0], [])
        self.assertIn('asks for 35V but the catalogue part is rated 25V', values.compare('100uF 35V', desc)[0][0])
        self.assertIn('bom.csv says 47uF but the catalogue description says 100uF', values.compare('47uF 25V', desc)[0][0])
        self.assertEqual(values.compare('10k', '10kΩ ±1% 0603 Chip Resistor', resistor=True)[0], [])
        self.assertEqual(values.compare('10.05k', '10kΩ', resistor=True)[0], [], 'within 1 %')
        self.assertNotEqual(values.compare('10.2k', '10kΩ', resistor=True)[0], [])

    def test_absence_is_unchecked_and_a_part_number_is_nothing(self):
        mism, unch, agreed = values.compare('100nF 50V', '')
        self.assertEqual((mism, agreed), ([], []))
        self.assertEqual(len(unch), 2)
        self.assertIn('states no F figure to compare with 100nF', unch[0])
        self.assertEqual(values.compare('SS54', 'anything 40V'), ([], [], []))


class Category(unittest.TestCase):
    def test_u_is_the_negative_rule(self):
        self.assertEqual(values.category_fits('U', 'Power Management (PMIC) / DC-DC Converters')[0], 'ok')
        self.assertEqual(values.category_fits('U', 'Capacitors / Multilayer Ceramic Capacitors MLCC - SMD/SMT')[0], 'mismatch')
        self.assertEqual(values.category_fits('U', 'Transistors/Thyristors / Darlington Transistor Arrays')[0], 'ok', 'an array is an IC')
        self.assertEqual(values.category_fits('U', 'Power Management (PMIC) / LED Drivers')[0], 'ok')
        self.assertEqual(values.category_fits('U', 'Interface / Analog Switches, Multiplexers')[0], 'ok')
        self.assertEqual(values.category_fits('U', '', 'any description')[0], 'unchecked')

    def test_keywords_start_words(self):
        self.assertEqual(values.category_fits('C', 'Optoelectronics / Shielded Molded Coupled thing')[0], 'mismatch', 'LED inside a word is not an LED')
        self.assertEqual(values.category_fits('F', 'Circuit Protection / Fuseholders')[0], 'ok')
        self.assertEqual(values.category_fits('SW', 'Switches / Tactile Switches')[0], 'ok')
        self.assertEqual(values.prefix_of('LED3'), 'LED')
        self.assertEqual(values.prefix_of('FB1'), 'FB')
        self.assertEqual(values.prefix_of('#PWR01'), '#PWR')


def record(r):
    return {'mpn': r['mpn'], 'package': r['package'], 'category': r['category'], 'description': r['description'], 'library': 'Basic', 'stock': 1000}


class CatalogueFixture(unittest.TestCase):
    """Real JLCPCB records against bom.csv lines: the regression corpus for the two online value gates."""

    def test_every_row(self):
        rows = fixture_rows()
        self.assertGreater(len(rows), 40)
        for r in rows:
            with self.subTest(lcsc=r['lcsc'], ref=r['ref'], value=r['value']):
                self.assertIn(r['expect'], ('ok', 'category', 'value', 'unchecked-category', 'unchecked-value', 'unchecked-both'))
                lines = [Line(row=2, refs=[r['ref']], value=r['value'], lcsc=r['lcsc'], mpn=r['mpn'])]
                records = {r['lcsc']: record(r)}
                cat = checks.catalogue_category_check(lines, records)
                val = checks.catalogue_value_check(lines, records)
                want_cat = {'category': 'fail', 'unchecked-category': 'skip', 'unchecked-both': 'skip'}.get(r['expect'], 'pass')
                want_val = {'value': 'fail'}.get(r['expect'], 'pass')
                self.assertEqual(cat.status, want_cat, (cat.summary, cat.details, cat.unchecked))
                self.assertEqual(val.status, want_val, (val.summary, val.details, val.unchecked))
                self.assertEqual(len(cat.unchecked), 1 if r['expect'] in ('unchecked-category', 'unchecked-both') else 0, cat.unchecked)
                self.assertEqual(bool(val.unchecked), r['expect'] in ('unchecked-value', 'unchecked-both'), val.unchecked)
                if r['expect'] == 'ok':
                    self.assertEqual(report.verdict([cat, val]), 'PASS')

    def test_every_keyword_and_prefix_has_a_row(self):
        rows = [r for r in fixture_rows() if r['expect'] == 'ok']
        for cls, keywords in values.CLASSES.items():
            for kw, src in keywords.items():
                with self.subTest(keyword=kw):
                    self.assertTrue(src.strip(), 'every keyword names the record it was seen in')
                    self.assertTrue(any(values._has(kw, r['category'] + ' ' + r['description'])
                                        and cls in values.PREFIXES.get(values.prefix_of(r['ref']), ())
                                        for r in rows), f'no ok row exercises the {cls} keyword "{kw}"')
        for prefix in values.PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertTrue(any(values.prefix_of(r['ref']) == prefix for r in rows), f'no ok row has a {prefix} reference')
        self.assertTrue(all(r['description'] or r['expect'] == 'unchecked-both' for r in fixture_rows()))


SCH = [{'Ref': 'C1', 'Value': '10 µF 50V', 'Footprint': 'Capacitor_SMD:C_1210_3225Metric', 'DNP': False, 'ExcludeFromBOM': False},
       {'Ref': 'C2', 'Value': '10uF 50V', 'Footprint': 'Capacitor_SMD:C_1210_3225Metric', 'DNP': False, 'ExcludeFromBOM': False},
       {'Ref': 'R1', 'Value': '4k7', 'Footprint': 'Resistor_SMD:R_0603_1608Metric', 'DNP': False, 'ExcludeFromBOM': False},
       {'Ref': 'R2', 'Value': '100Ω', 'Footprint': 'Resistor_SMD:R_0603_1608Metric', 'DNP': False, 'ExcludeFromBOM': False},
       {'Ref': 'D1', 'Value': 'SS34', 'Footprint': 'Diode_SMD:D_SMA', 'DNP': False, 'ExcludeFromBOM': False}]


class BomValueGate(unittest.TestCase):
    def test_spellings_pass_and_values_block(self):
        lines = [Line(row=2, refs=['C1', 'C2'], value='10uF 50V', lcsc='C1'), Line(row=3, refs=['R1'], value='4.7k', lcsc='C2'),
                 Line(row=4, refs=['R2'], value='100R', lcsc='C3'), Line(row=5, refs=['D1'], value='SS34', lcsc='C4'), Line(row=6, refs=['R9'], value='x', lcsc='C5')]
        c = checks.bom_value_check(lines, SCH)
        self.assertEqual(c.status, 'pass', c.details)
        self.assertIn('5 references', c.summary)
        lines[0].value = '10uF 16V'
        lines[3].value = ''
        c = checks.bom_value_check(lines, SCH)
        self.assertEqual(c.status, 'fail')
        self.assertEqual(len(c.details), 3, c.details)
        self.assertIn('C1 (bom.csv row 2): "10uF 16V" in bom.csv, "10 µF 50V" in the schematic', c.details[0])
        self.assertIn('D1 (bom.csv row 5): "" in bom.csv, "SS34" in the schematic', c.details[2])
        self.assertEqual(report.verdict([c]), 'FAIL')


class OnlineGates(unittest.TestCase):
    def test_unreachable_codes_are_listed_not_passed(self):
        lines = [Line(row=2, refs=['C1'], value='100nF 50V', lcsc='C14663'), Line(row=3, refs=['J1'], value='J_IN', lcsc='C3819953')]
        records = {'C14663': {'mpn': 'CC0603KRX7R9BB104', 'category': 'Capacitors / Multilayer Ceramic Capacitors MLCC - SMD/SMT',
                              'description': '100nF 50V X7R ±10% 0603 Multilayer Ceramic Capacitors MLCC - SMD/SMT ROHS'}, 'C3819953': None}
        for c in (checks.catalogue_category_check(lines, records), checks.catalogue_value_check(lines, records)):
            self.assertEqual(c.status, 'pass', c.details)
            self.assertEqual(len(c.unchecked), 1)
            self.assertIn('1 codes not looked up', c.unchecked[0])
        self.assertEqual(checks.catalogue_category_check(lines, {}).status, 'skip')
        self.assertEqual(checks.catalogue_value_check(lines, {}).status, 'skip')

    def test_a_capacitor_on_an_led_line_blocks(self):
        lines = [Line(row=2, refs=['D4', 'D5'], value='green', lcsc='C14663')]
        records = {'C14663': {'mpn': 'CC0603KRX7R9BB104', 'category': 'Capacitors / Multilayer Ceramic Capacitors MLCC - SMD/SMT', 'description': '100nF 50V X7R'}}
        c = checks.catalogue_category_check(lines, records)
        self.assertEqual(c.status, 'fail')
        self.assertIn('C14663 CC0603KRX7R9BB104 (D4, D5; bom.csv row 2): D is a diode/led reference but the catalogue files this part under "Capacitors', c.details[0])
        self.assertEqual(report.verdict([c]), 'FAIL')


if __name__ == '__main__':
    unittest.main()
