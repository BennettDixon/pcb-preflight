import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import checks, footprints, packages, report  # noqa: E402
from pcb_preflight.bom import Line  # noqa: E402
from pcb_preflight.packages import DIFFERENT, SAME, UNKNOWN  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'packages.csv')
ROOT = footprints.find_root(kicad_cli=os.environ.get('KICAD_CLI'))
LIBRARY = packages.load_library(ROOT)
needs_library = unittest.skipUnless(LIBRARY, 'no KiCad footprint library on this machine')


def fixture_rows():
    with open(FIXTURE, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(line for line in f if not line.startswith('#')))


class Fixture(unittest.TestCase):
    """Real footprint names against real catalogue strings: the regression corpus for packages.fits().

    Every row states the verdict and rule with KiCad's footprint library (pads decide) and without it (names
    alone). The names-only columns run everywhere; the library columns run where KiCad is installed.
    """

    def test_every_row_by_names(self):
        rows = fixture_rows()
        self.assertGreater(len(rows), 80)
        for r in rows:
            with self.subTest(footprint=r['footprint'], part=r['part']):
                self.assertIn(r['names_verdict'], (SAME, DIFFERENT, UNKNOWN))
                self.assertIn(r['names_rule'], packages.RULES)
                self.assertNotIn(r['names_rule'], packages.LIBRARY_RULES, 'names alone cannot reach a library rule')
                self.assertTrue(r['seen_in'].strip(), 'every row names the record or file it came from')
                f = packages.fits(r['footprint'], r['part'], r.get('mpn') or None)
                self.assertEqual((f.verdict, f.rule), (r['names_verdict'], r['names_rule']), f.reason)

    @needs_library
    def test_every_row_with_the_library(self):
        for r in fixture_rows():
            with self.subTest(footprint=r['footprint'], part=r['part']):
                self.assertIn(r['rule'], packages.RULES)
                f = packages.fits(r['footprint'], r['part'], r.get('mpn') or None, LIBRARY)
                self.assertEqual((f.verdict, f.rule), (r['verdict'], r['rule']), f.reason)
                self.assertEqual(f.as_dict()['rule'], r['rule'])

    def test_fits_is_symmetric(self):
        for r in fixture_rows():
            if r.get('mpn'):
                continue
            with self.subTest(footprint=r['footprint'], part=r['part']):
                self.assertEqual(packages.fits(r['part'], r['footprint']).verdict, r['names_verdict'])
                if LIBRARY:
                    g = packages.fits(r['part'], r['footprint'], library=LIBRARY)
                    if g.rule != packages.AMBIGUOUS:        # the board's own footprint picks among an ambiguous string's land patterns: one-sided by design
                        self.assertEqual(g.verdict, r['verdict'])

    def test_every_rule_has_a_row(self):
        rows = fixture_rows()
        used = {r['names_rule'] for r in rows} | ({r['rule'] for r in rows} if LIBRARY else set(packages.LIBRARY_RULES))
        for rule in packages.RULES:
            with self.subTest(rule=rule):
                self.assertIn(rule, used, f'no fixture row exercises the {rule} rule')
        for r in rows:
            self.assertIn(r['rule'], packages.RULES, r['rule'])

    def test_every_table_entry_has_a_source_and_a_row(self):
        tokens = set()
        readings = []
        for r in fixture_rows():
            for side in ('footprint', 'part'):
                tokens.update(packages._tokens(r[side]))
                readings.append(packages.read(r[side]))
        for spelling, (canon, src) in packages.SYNONYMS.items():
            with self.subTest(synonym=spelling):
                self.assertTrue(src.strip())
                self.assertIn(spelling, tokens, f'{spelling} -> {canon} has no fixture row using it')
        for fam, (canon, _ep, src) in packages.FAMILIES.items():
            with self.subTest(family=fam):
                self.assertTrue(src.strip())
                self.assertTrue(any(packages.FAMILY_TOKEN.fullmatch(t) and packages.FAMILY_TOKEN.fullmatch(t).group(1) == fam
                                    for t in tokens), f'{fam} -> {canon} has no fixture row using it')
        for fam, (pitch, src) in packages.STANDARD_PITCH.items():
            with self.subTest(standard_pitch=fam):
                self.assertTrue(src.strip())
                self.assertTrue(any(rd.pitch_source == src for rd in readings), f'no fixture row reads a {fam} without a stated pitch')
        for key, src in packages.PATTERNS.items():
            with self.subTest(pattern=key):
                self.assertTrue(src.strip())
                self.assertTrue(any(src == v[2] for rd in readings for v in rd.via), f'no fixture row is read by the {key} pattern')
        for body in packages.SOIC_BODY:
            with self.subTest(soic_body=body):
                self.assertTrue(any(t.startswith(body + 'X') and packages.SIZE.fullmatch(t) for t in tokens), f'no fixture row names a {body} mm SOIC body')


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

    def test_thickness_variants_fold_into_their_family(self):
        self.assertEqual(self.names('TSOT-23-6'), {'SOT-23-6'})
        self.assertEqual(self.names('Package_TO_SOT_SMD:TSOT-23-5_HandSoldering'), {'SOT-23-5'})
        self.assertEqual(self.names('VQFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm'), {'QFN-16(3x3)'})
        self.assertEqual(self.names('WQFN-16-1EP_3x3mm_P0.5mm_EP1.75x1.75mm'), {'QFN-16(3x3)'})
        self.assertEqual(self.names('TQFN-20-1EP_4x4mm_P0.5mm_EP2.1x2.1mm'), {'QFN-20(4x4)'})
        self.assertEqual(packages.read('TSOT-23-6').via[0][:2], ('TSOT-23', 'SOT-23'))

    def test_exposed_pad_and_width(self):
        self.assertEqual(self.names('SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm'), {'SOIC-8-EP'})
        self.assertEqual(self.names('SOIC-8_3.9x4.9mm_P1.27mm'), {'SOIC-8'})
        self.assertEqual(self.names('SOIC-16W_7.5x10.3mm_P1.27mm'), {'SOIC-16-300MIL'})
        self.assertEqual(self.names('SOP-8_150mil'), {'SOIC-8'})
        self.assertEqual(self.names('LQFN-56(7x7)'), {'QFN-56(7x7)'}, 'LQFN is a QFN (FAMILIES, C2040 RP2040)')
        self.assertEqual(self.names('TDFN-6-EP(2x3)'), {'DFN-6(2x3)'})
        self.assertEqual(self.names('Package_SO:SOIC-8_5.23x5.23mm_P1.27mm'), {'SOIC-8-208MIL'}, 'KiCad 9 spelling of the 208 mil body')
        self.assertEqual(self.names('TI_SO-PowerPAD-8_ThermalVias'), {'SOIC-8-EP'})
        self.assertEqual(self.names('Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm'), {'SOIC-16-300MIL'})

    def test_patterns_read_by_shape_and_say_so(self):
        for text, canon, key in (('easyeda2kicad:C0402', '0402', 'chip prefix'), ('PCM_JLCPCB:R0805', '0805', 'chip prefix'),
                                 ('L0805', '0805', 'chip prefix'), ('WQFN4040-24', 'QFN-24(4x4)', 'body-pins'),
                                 ('SOT-23-Thin-6', 'SOT-23-6', 'thin'), ('Package_BGA:BGA-24_5x5_6.0x8.0mm', 'BGA-24(6x8)', 'bga layout'),
                                 ('SMD3225-4P', 'SMD-3225-4P', 'crystal'), ('Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm', 'SMD-2016-4P', 'crystal'),
                                 ('CASE-A-3216-18(mm)', 'EIA-3216-18', 'tantalum case'), ('CP_EIA-3216-18_Kemet-A', 'EIA-3216-18', 'tantalum case'),
                                 ('Package_SO:TI_SO-PowerPAD-8', 'SOIC-8-EP', 'powerpad')):
            with self.subTest(text=text):
                r = packages.read(text)
                self.assertEqual(set(r.names), {canon})
                self.assertIn(packages.PATTERNS[key], [v[2] for v in r.via], 'the pattern used is recorded with its source')
        self.assertEqual(self.names('BGA24_6X8'), {'BGA-24(6x8)'})
        self.assertEqual(self.names('Package_BGA:BGA-24_6x8mm_Layout5x5_P1.0mm'), {'BGA-24(6x8)'})
        self.assertEqual(self.names('Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm'), {'QFN-16(3x3)'}, 'a QFN takes the first size as before')
        self.assertEqual(self.names('SOT-5X3'), {'SOT-583-8'})
        self.assertEqual(self.names('SOT-5X3-5'), {'SOT-553'})
        self.assertEqual(self.names('SOT-583-8_L2.1-W1.2-P0.50-LS1.6-BL'), {'SOT-583-8'})
        for s in ('C1234', 'SMD-4P,4.5x3.2mm', 'Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm', 'C9010'):
            self.assertEqual(self.names(s), set(), f'{s}: not a chip size, crystal body or array spelling the table knows')

    def test_pitch_and_body_width_are_read_from_leaded_names(self):
        r = packages.read('Package_SO:SOP-8_6.62x9.15mm_P2.54mm')
        self.assertEqual((r.pitch, r.width, r.pitch_source), (2.54, 6.62, ''))
        r = packages.read('SOIC-8')
        self.assertEqual(r.pitch, 1.27)
        self.assertIn('JEDEC MS-012', r.pitch_source)
        self.assertIsNone(packages.read('TSSOP-14').pitch)
        self.assertEqual(packages.read('SSOP-8_3.95x5.21x3.27mm_P1.27mm').width, 3.95)
        self.assertIsNone(packages.read('QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm').width, 'body size of an array is in the name')
        self.assertIsNone(packages.read('Fuse_2920_7451Metric').pitch)

    def test_nothing_readable(self):
        for s in ('Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical', 'Inductor_SMD:L_Bourns_SRP1245A', 'Plugin', 'SMD,13.5x12.5mm', ''):
            self.assertEqual(self.names(s), set(), s)

    def test_fit_reports_the_table_entry_used(self):
        f = packages.fits('Package_TO_SOT_SMD:SOT-23-5', 'SOT-25-5')
        self.assertEqual(f.verdict, SAME)
        self.assertEqual(f.via[0][:2], ('SOT-25-5', 'SOT-23-5'))
        self.assertIn('C51118', f.reason)
        self.assertEqual(f.as_dict()['via'][0]['read_as'], 'SOT-23-5')
        self.assertEqual(f.as_dict()['rule'], packages.NAMES)

    def test_identical_strings_are_read_not_trusted(self):
        f = packages.fits('Package_TO_SOT_SMD:SOT-23-5', 'SOT-23-5')
        self.assertEqual((f.verdict, f.rule), (SAME, packages.NAMES))
        f = packages.fits('Inductor_SMD:L_Bourns_SRP1245A', 'L_Bourns_SRP1245A')
        self.assertEqual((f.verdict, f.rule), (UNKNOWN, packages.UNREADABLE), 'the same unreadable name on both sides proves nothing')

    def test_stated_pitch_decides_without_a_library(self):
        f = packages.fits('Package_SO:SOP-8_6.62x9.15mm_P2.54mm', 'SOIC-8')
        self.assertEqual((f.verdict, f.rule), (DIFFERENT, packages.DIMS))
        self.assertIn('2.54 mm against 1.27 mm', f.reason)
        f = packages.fits('Package_SO:TSSOP-14_4.4x5mm_P0.65mm', 'TSSOP-14_4.4x3.6mm_P0.4mm')
        self.assertEqual((f.verdict, f.rule), (DIFFERENT, packages.DIMS))
        f = packages.fits('Package_SO:TSSOP-8_3x3mm_P0.65mm', 'TSSOP-8_4.4x3mm_P0.65mm')
        self.assertEqual((f.verdict, f.rule), (DIFFERENT, packages.DIMS))
        self.assertIn('body width', f.reason)


@needs_library
class Library(unittest.TestCase):
    def test_root_is_found_and_indexed(self):
        self.assertTrue(os.path.isdir(ROOT))
        LIBRARY.resolve('x', packages.read('0805'))
        self.assertGreater(LIBRARY.indexed, 3000)

    def test_a_library_footprint_resolves_to_itself(self):
        r = LIBRARY.resolve('Package_TO_SOT_SMD:SOT-23-6', packages.read('SOT-23-6'))
        self.assertEqual([e.lib_id for e in r.entries], ['Package_TO_SOT_SMD:SOT-23-6'])
        self.assertEqual(r.ambiguity, '')
        r = LIBRARY.resolve('TSOT-23-6', packages.read('TSOT-23-6'))
        self.assertEqual([e.lib_id for e in r.entries], ['Package_TO_SOT_SMD:TSOT-23-6'], 'a bare library name is that footprint')

    def test_a_generic_string_resolves_to_every_variant_at_its_pitch(self):
        r = LIBRARY.resolve('SOIC-8', packages.read('SOIC-8'))
        names = {e.name for e in r.entries}
        self.assertIn('SOIC-8_3.9x4.9mm_P1.27mm', names)
        self.assertIn('JEITA_SOIC-8_3.9x4.9mm_P1.27mm', names)
        self.assertNotIn('SOP-8_6.62x9.15mm_P2.54mm', names, "SOIC's standard pitch rules the 2.54 mm SOPs out")
        self.assertNotIn('SOIC-8_5.3x5.3mm_P1.27mm', names, 'a 208 mil body is another canonical name')
        self.assertEqual(r.ambiguity, '')

    def test_a_name_with_two_land_patterns_is_ambiguous(self):
        r = LIBRARY.resolve('TSSOP-14', packages.read('TSSOP-14'))
        self.assertIn('pitch 0.4 and 0.65 mm', r.ambiguity)
        r = LIBRARY.resolve('SSOP-8', packages.read('SSOP-8'))
        self.assertIn('pitch 0.65 and 1.27 mm', r.ambiguity)
        self.assertEqual(LIBRARY.resolve('SOT-23-5', packages.read('SOT-23-5')).ambiguity, '')

    def test_pads_are_copper_only_and_rotation_blind(self):
        pads = LIBRARY.pads('Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm')
        self.assertEqual(len(pads), 17, '16 leads and the exposed pad; the four paste windows are not copper')
        self.assertFalse(any(p.paste for p in pads if p.w > 1), 'the exposed pad itself takes no paste')
        tiv = LIBRARY.pads('Package_SO:TI_SO-PowerPAD-8_ThermalVias')
        self.assertEqual(len(tiv), 9, '19 pad entries: the exposed pad 9 is three stacked rectangles and eight via-in-pad holes numbered 9')
        ep = [p for p in tiv if p.w > 2]
        self.assertEqual([(p.kind, p.x, p.y, p.w, p.h, p.drill, p.paste) for p in ep], [('smd', 0.0, 0.0, 2.95, 4.5, 0.0, True)])
        tiles = LIBRARY.pads('Package_SO:TI_SO-PowerPAD-8')
        self.assertEqual(len(tiles), 9, 'four tiles numbered 9 are one pad')
        self.assertEqual([(p.w, p.h) for p in tiles if p.w > 2], [(2.41, 3.1)])
        self.assertEqual(footprints.stack([('1', footprints.Pad('thru_hole', 0, 0, 1, 1, 0.5, False)), ('1', footprints.Pad('thru_hole', 5, 0, 1, 1, 0.5, False))]),
                         (footprints.Pad('thru_hole', 0, 0, 1, 1, 0.5, False), footprints.Pad('thru_hole', 5, 0, 1, 1, 0.5, False)),
                         'two holes with one number and no copper between them stay two pads')
        sot = LIBRARY.pads('Package_TO_SOT_SMD:SOT-23')
        self.assertEqual(footprints.same_pads(sot, tuple(p.rotated(1) for p in sot)), (True, ''))
        self.assertEqual(footprints.same_pads(sot, sot[:2])[0], False)
        self.assertIsNone(LIBRARY.pads('Nowhere:Nothing'))

    def test_the_probe_cases_of_the_review(self):
        def fit(a, b):
            f = packages.fits(a, b, library=LIBRARY)
            return f.verdict, f.rule
        self.assertEqual(fit('Package_TO_SOT_SMD:SOT-23-6', 'TSOT-23-6'), (SAME, packages.PADS))
        self.assertEqual(fit('Package_SO:MSOP-8_3x3mm_P0.65mm', 'VSSOP-8_3x3mm_P0.65mm'), (SAME, packages.PADS))
        self.assertEqual(fit('Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm', 'VQFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm'), (SAME, packages.PADS))
        self.assertEqual(fit('Capacitor_SMD:CP_Elec_6.3x5.8', 'SMD,D6.3xL7.7mm'), (SAME, packages.PADS))
        self.assertEqual(fit('Package_SO:SOP-8_6.62x9.15mm_P2.54mm', 'SOIC-8'), (DIFFERENT, packages.PADS_DIFFER))
        self.assertEqual(fit('Package_SO:SSOP-8_3.9x5.05mm_P1.27mm', 'SSOP-8_2.95x2.8mm_P0.65mm'), (DIFFERENT, packages.PADS_DIFFER))
        self.assertEqual(fit('Package_SO:TSSOP-14_4.4x5mm_P0.65mm', 'TSSOP-14_4.4x3.6mm_P0.4mm'), (DIFFERENT, packages.PADS_DIFFER))
        self.assertEqual(fit('Package_SO:VSSOP-8_2.3x2mm_P0.5mm', 'VSSOP-8_3x3mm_P0.65mm'), (DIFFERENT, packages.PADS_DIFFER))
        self.assertEqual(fit('Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.6x2.6mm', 'TQFN-20-1EP_4x4mm_P0.5mm_EP2.1x2.1mm'), (UNKNOWN, packages.PADS_UNKNOWN))
        f = packages.fits('Package_SO:TSSOP-14_4.4x5mm_P0.65mm', 'TSSOP-14', library=LIBRARY)
        self.assertEqual((f.verdict, f.rule, f.by_names), (SAME, packages.PADS, SAME), 'the board\'s own footprint picks among the two TSSOP-14 pitches')
        self.assertIn('"TSSOP-14" names more than one land pattern (pitch 0.4 and 0.65 mm) and the board\'s footprint is the TSSOP-14_4.4x5mm_P0.65mm one', f.reason)
        f = packages.fits('TSSOP-20_L6.5-W4.4-P0.65-LS6.4-BL', 'TSSOP-20', library=LIBRARY)
        self.assertEqual((f.verdict, f.rule, f.by_names), (UNKNOWN, packages.AMBIGUOUS, SAME), 'a footprint KiCad does not have cannot pick')
        f = packages.fits('TSSOP-14', 'Package_SO:TSSOP-14_4.4x5mm_P0.65mm', library=LIBRARY)
        self.assertEqual((f.verdict, f.rule), (UNKNOWN, packages.AMBIGUOUS), 'an ambiguous footprint name is not picked by the part')
        f = packages.fits('Package_SO:VSSOP-8_3x3mm_P0.65mm', 'MSOP-8', library=LIBRARY)
        self.assertEqual((f.verdict, f.rule, f.by_names), (SAME, packages.PADS, DIFFERENT))
        self.assertIn('by name footprint is VSSOP-8, part is MSOP-8', f.reason)


SCH = [
    {'Ref': 'U1', 'Value': 'LMR33630', 'Footprint': 'Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'U4', 'Value': 'AP2112K-3.3', 'Footprint': 'Package_TO_SOT_SMD:SOT-23-5', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'L1', 'Value': '10uH', 'Footprint': 'Inductor_SMD:L_Bourns_SRP1245A', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'J1', 'Value': 'J_IN', 'Footprint': 'TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-2-5.0-H_1x02_P5.00mm_Horizontal', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'U5', 'Value': 'MP3202', 'Footprint': 'Package_TO_SOT_SMD:SOT-23-6', 'DNP': False, 'ExcludeFromBOM': False},
    {'Ref': 'U6', 'Value': 'LMV393', 'Footprint': 'Package_SO:VSSOP-8_3x3mm_P0.65mm', 'DNP': False, 'ExcludeFromBOM': False},
]


def line(refs, package, lcsc='', verified=''):
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
        self.assertIn('names alone were compared', c.notes[0], 'the gate says no library was used')

    def test_footprint_named_for_the_part(self):
        lines = [line(['L1'], 'L_Bourns_SRP1245A', 'C2042471')]
        c = checks.catalogue_package_check(lines, {'C2042471': {'mpn': 'SRP1245A-100M', 'package': 'SMD,13.5x12.5mm'}}, SCH)
        self.assertEqual(c.status, 'pass')
        self.assertEqual(c.unchecked, [])
        self.assertTrue(any('drawn for this part (SRP1245A' in d for d in c.details), c.details)

    def test_missing_exposed_pad_blocks(self):
        lines = [line(['U1'], 'SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm', 'C9865')]
        c = checks.catalogue_package_check(lines, {'C9865': {'mpn': 'TPS54331DR', 'package': 'SOIC-8'}}, SCH)
        self.assertEqual(c.status, 'fail')
        self.assertIn('footprint is SOIC-8-EP, part is SOIC-8', c.details[0])

    def test_nothing_comparable_is_a_skip(self):
        c = checks.catalogue_package_check([line(['L1'], 'L_Bourns_SRP1245A', 'C2847573')],
                                           {'C2847573': {'mpn': 'MDA1350-100M', 'package': 'SMD,13.5x12.6mm'}}, SCH)
        self.assertEqual(c.status, 'skip')
        self.assertEqual(len(c.unchecked), 1)

    @needs_library
    def test_pads_decide_in_the_gates(self):
        c = checks.catalogue_package_check([line(['U5'], 'TSOT-23-6', 'C8953')], {'C8953': {'mpn': 'MP3202DJ', 'package': 'TSOT-23-6'}}, SCH, LIBRARY)
        self.assertEqual(c.status, 'pass', c.details)
        self.assertIn(ROOT, c.notes[0])
        self.assertTrue(any('pads match: SOT-23-6 and TSOT-23-6' in d for d in c.details), c.details)
        c = checks.catalogue_package_check([line(['U6'], 'MSOP-8', 'C7985')], {'C7985': {'mpn': 'LMV393MMX/NOPB', 'package': 'MSOP-8'}}, SCH, LIBRARY)
        self.assertEqual(c.status, 'pass', c.details)
        self.assertTrue(any('by name footprint is VSSOP-8, part is MSOP-8' in d for d in c.details), c.details)
        c = checks.catalogue_package_check([line(['U6'], 'VSSOP-8', 'C7851')], {'C7851': {'mpn': 'SN74LVC2G74DCUR', 'package': 'VSSOP-8'}}, SCH, LIBRARY)
        self.assertEqual(c.status, 'pass', 'U6 is a known library footprint: its pads pick among the two VSSOP-8 land patterns')
        self.assertTrue(any('names more than one land pattern (pitch 0.5 and 0.65 mm) and the board\'s footprint is the VSSOP-8_3x3mm_P0.65mm one' in d for d in c.details), c.details)
        sch = SCH + [{'Ref': 'U7', 'Value': 'BQ77905', 'Footprint': 'easyeda2kicad:TSSOP-20_L6.5-W4.4-P0.65-LS6.4-BL', 'DNP': False, 'ExcludeFromBOM': False}]
        c = checks.catalogue_package_check([line(['U7'], 'TSSOP-20', 'C555146')], {'C555146': {'mpn': 'BQ7790512PWR', 'package': 'TSSOP-20'}}, sch, LIBRARY)
        self.assertEqual(c.status, 'skip')
        self.assertIn('names more than one land pattern', c.unchecked[0])

    def test_report_lists_unchecked_items(self):
        partial = checks.Check('catalogue-package', 'Catalogue package fits the footprint', '§1', 'pass', '2 agree',
                               unchecked=['C2042471 (L1): ...'], verified=['C3819953 (J1): ...'])
        text = report.render({'project': 'p', 'kicad_version': '10', 'copper_layers': 4, 'footprints': 1,
                              'bom_path': 'bom.csv', 'checks': [partial], 'by_hand': []})
        self.assertIn('        by hand: C3819953 (J1)', text)
        self.assertIn('Catalogue package fits the footprint (§1): 1 not compared', text)
        self.assertIn('0 blocking, 0 warnings, 1 not checked, 0 cost drivers  -  exit 3', text)
        self.assertEqual(report.verdict([partial]), 'NOT VERIFIED')     # an item nobody compared is not a pass


class FindRoot(unittest.TestCase):
    def test_explicit_path_must_exist(self):
        with self.assertRaises(FileNotFoundError):
            footprints.find_root('/nowhere/footprints')

    def test_env_var_wins(self):
        here = os.path.dirname(os.path.abspath(__file__))
        old = os.environ.get('KICAD_FOOTPRINT_DIR')
        os.environ['KICAD_FOOTPRINT_DIR'] = here
        try:
            self.assertEqual(footprints.find_root(), here)
        finally:
            if old is None:
                del os.environ['KICAD_FOOTPRINT_DIR']
            else:
                os.environ['KICAD_FOOTPRINT_DIR'] = old

    def test_dims_in_name(self):
        self.assertEqual(footprints.dims_in_name('TSSOP-14_4.4x3.6mm_P0.4mm'), (0.4, 4.4))
        self.assertEqual(footprints.dims_in_name('SSOP-8_3.95x5.21x3.27mm_P1.27mm'), (1.27, 3.95))
        self.assertEqual(footprints.dims_in_name('SOT-23-6'), (None, None))


if __name__ == '__main__':
    unittest.main()
