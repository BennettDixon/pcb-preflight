"""The ORDER section (checks.order_check, status ``cost``): every driver read from an inline board against
preset.TIERS, the verdict and exit code untouched by it, the report section and count, and the JSON."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import board, checks, preset, report  # noqa: E402
from pcb_preflight.bom import Line  # noqa: E402


def pcb(body, layers='(0 "F.Cu" signal) (31 "B.Cu" signal)', general='(general (thickness 1.6))', setup='(setup (aux_axis_origin 0 0))',
        outline='(gr_rect (start 0 0) (end 80 50) (layer "Edge.Cuts"))'):
    text = f'''(kicad_pcb (version 20241229) (generator "pcbnew") (generator_version "9.0")
  {general}
  (layers {layers})
  {setup}
  {outline}
  {body}
)'''
    f = tempfile.NamedTemporaryFile('w', suffix='.kicad_pcb', delete=False)
    f.write(text)
    f.close()
    return board.load(f.name)


def via(size, drill):
    return f'(via (at 1 1) (size {size}) (drill {drill}) (layers "F.Cu" "B.Cu"))'


def smd(ref, layer='F.Cu', paste=True, attrs='smd'):
    paste_layer = f' "{layer[0]}.Paste"' if paste else ''
    return (f'(footprint "Resistor_SMD:R_0603_1608Metric" (layer "{layer}") (at 5 5) (property "Reference" "{ref}" (at 0 0 0) (layer "F.SilkS")) '
            f'(property "Value" "x" (at 0 0 0) (layer "F.Fab")) (attr {attrs}) '
            f'(pad "1" smd rect (at 0 0) (size 1 1) (layers "{layer}"{paste_layer}) (net 1 "A")))')


def tht(ref, layer='F.Cu', drill='0.8', attrs='through_hole', pads=2, net=True):
    n = ' (net 1 "A")' if net else ''
    pad = ' '.join(f'(pad "{i}" thru_hole circle (at {i * 2.54} 0) (size 1.6 1.6) (drill {drill}) (layers "*.Cu" "*.Mask"){n})' for i in range(pads))
    return (f'(footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical" (layer "{layer}") (at 20 20) '
            f'(property "Reference" "{ref}" (at 0 0 0) (layer "F.SilkS")) (property "Value" "x" (at 0 0 0) (layer "F.Fab")) (attr {attrs}) {pad})')


def line(refs, lcsc='C1'):
    return Line(row=2, refs=refs, value='x', package='', mpn='', lcsc=lcsc, library='', stock='', datasheet='', package_verified='')


READ = preset.TIERS_READ
STANDARD_2L = pcb(via('0.45', '0.3') + smd('R1') + smd('R2'))


class Standard(unittest.TestCase):
    def test_a_plain_board_is_on_the_standard_tier_everywhere(self):
        c = checks.order_check(STANDARD_2L)
        self.assertEqual((c.id, c.status, c.pitfall), ('order', 'pass', '§13'))
        self.assertEqual(c.summary, "every driver the files can show is on JLCPCB's standard tier")
        self.assertEqual(c.details, [])
        self.assertEqual(c.unchecked, [])
        self.assertTrue(c.notes[0].startswith('on the standard tier: vias smallest via 0.3 mm hole, 0.45 mm diameter (0.3mm/(0.4/0.45mm)); '
                                              'smallest hole 0.3 mm (0.15 mm is the smallest standard drill); 2 copper layers (1-2 layers); '
                                              'outline 80 × 50 mm (100 × 100 mm or smaller); single-sided placement (2 parts on F.Cu); '
                                              'no through-hole parts to assemble; 1.6 mm thick'), c.notes[0])

    def test_the_two_fixed_notes(self):
        c = checks.order_check(STANDARD_2L)
        self.assertEqual(c.notes[-2], f'not in the files: {", ".join(preset.NOT_IN_FILES)}; the quote page prices those')
        self.assertEqual(c.notes[-1], f'JLCPCB assembles a minimum of {preset.ASSEMBLY_MIN} boards; order spares (§13)')
        self.assertIn('copper weight', c.notes[-2])
        self.assertNotIn('spares', ' '.join(checks.by_hand(STANDARD_2L)), 'the spares reminder moved into the order gate')

    def test_never_a_price_or_a_suggestion(self):
        b = pcb(via('0.25', '0.1') + smd('R1') + smd('R2', 'B.Cu') + tht('J1'), layers='(0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (3 "In3.Cu" signal) (4 "In4.Cu" signal) (31 "B.Cu" signal)',
                general='(general (thickness 2.0))', setup='(setup (stackup (castellated_pads yes) (edge_plating yes) (dielectric_constraints yes)))',
                outline='(gr_rect (start 0 0) (end 120 80) (layer "Edge.Cuts"))')
        c = checks.order_check(b, records={'C1': {'library': 'Extended'}})
        text = '\n'.join(c.details + c.notes + [c.summary])
        self.assertNotRegex(text, r'[$€£]\s?\d')
        for word in ('you should', 'consider', 'cheaper', 'instead'):
            self.assertNotIn(word, text.lower(), word)


class Vias(unittest.TestCase):
    def test_small_vias_land_in_their_option_and_are_counted(self):
        b = pcb(via('0.45', '0.3') + via('0.3', '0.2') + via('0.3', '0.2') + smd('R1'))
        c = checks.order_check(b)
        self.assertEqual(c.status, 'cost')
        self.assertEqual(len(c.details), 1)
        d = c.details[0]
        self.assertTrue(d.startswith('vias: smallest via 0.2 mm hole, 0.3 mm diameter; 2 of 3 vias are below the standard 0.3mm/(0.4/0.45mm) option; '
                                     'lands in the 0.2mm/(0.3/0.35mm) option: priced; the quote page adds "Plugged Via" and the "4-Wire Kelvin Test" itself'), d)
        self.assertIn(f'(source: quote, capabilities, read {READ})', d)
        self.assertIn('2 copper layers (1-2 layers)', c.notes[0])
        self.assertEqual(c.summary, "1 driver off JLCPCB's standard tier (vias)")

    def test_a_tenth_millimetre_via_quotes_the_quote_pages_conditions_and_is_a_hole_driver_too(self):
        b = pcb(via('0.2', '0.1') + smd('R1'), general='(general (thickness 1.0))')
        c = checks.order_check(b)
        self.assertEqual(c.status, 'cost')
        self.assertEqual([d.split(':', 1)[0] for d in c.details], ['vias', 'holes'])
        self.assertIn('lands in the 0.1mm/(0.2/0.25mm) option: priced; board thickness 1.0 mm or less and ENIG or OSP finish', c.details[0])
        self.assertIn('"0.1mm Via is only supported for board thickness ≤ 1.0mm"', c.details[0])
        self.assertIn('"HASL is incompatible with 0.1mm (0.2/0.25mm) hole sizes. Please choose ENIG or OSP."', c.details[0])
        self.assertTrue(c.details[1].startswith('holes: smallest drilled hole 0.1 mm; 1 of 1 holes are below the standard 0.15 mm drill; '
                                                'lands in the 0.1 mm hole tier: "more costly!"; board thickness 1 mm or less and ENIG or OSP finish'), c.details[1])
        self.assertIn(f'(source: capabilities, quote, read {READ})', c.details[1])

    def test_a_via_below_every_option_is_said_to_be_drcs(self):
        c = checks.order_check(pcb(via('0.1', '0.05') + smd('R1')))
        self.assertIn('below every option (the smallest is 0.1mm/(0.2/0.25mm)); DRC blocks it', c.details[0])
        self.assertIn('below every tier (the smallest is 0.1 mm); DRC blocks it', c.details[1])

    def test_the_floor_is_the_smallest_tier(self):
        self.assertEqual(preset.MINIMUMS_COMMON['min_through_hole_diameter'], preset.TIERS['hole']['rows'][-1]['min_drill'])
        self.assertEqual(preset.MINIMUMS_COMMON['min_via_diameter'], preset.TIERS['via']['rows'][-1]['min_diameter'])
        c = checks.drc_check({'violations': [{'type': 'drill_out_of_range', 'severity': 'error', 'excluded': False,
                                              'description': 'Hole size out of range (board setup constraints min hole 0.3000 mm; actual 0.1000 mm)', 'items': []}],
                              'ignored_checks': []}, owned={}, copper_layers=2)
        self.assertEqual(c.status, 'warn', 'a 0.1 mm hole clears the floor: the project\'s own rule, and an ORDER line')


class Holes(unittest.TestCase):
    def test_a_pad_drill_counts_as_a_hole_and_an_oval_by_its_smaller_figure(self):
        b = pcb(tht('J1', drill='oval 0.12 1.0') + smd('R1'))
        c = checks.order_check(b)
        holes = next(d for d in c.details if d.startswith('holes:'))
        self.assertIn('smallest drilled hole 0.12 mm; 2 of 2 holes are below the standard 0.15 mm drill', holes)

    def test_a_board_without_vias_or_pads_says_so(self):
        c = checks.order_check(pcb(smd('R1')))
        self.assertEqual(c.status, 'pass')
        self.assertNotIn('vias', c.notes[0])
        self.assertNotIn('smallest hole', c.notes[0])


class LayersSizeThickness(unittest.TestCase):
    def test_four_layers_is_its_own_class_six_is_high_precision(self):
        four = pcb(smd('R1'), layers='(0 "F.Cu" signal) (1 "In1.Cu" power) (2 "In2.Cu" signal) (31 "B.Cu" signal)')
        c = checks.order_check(four)
        self.assertEqual(c.status, 'cost')
        self.assertEqual(c.details, [f'layers: 4 copper layers; the standard class is 1-2 layers; lands in 4 layers: its own price class (source: quote, production-time, read {READ})'])
        six = pcb(smd('R1'), layers='(0 "F.Cu" signal) (1 "In1.Cu" power) (2 "In2.Cu" signal) (3 "In3.Cu" signal) (4 "In4.Cu" signal) (31 "B.Cu" signal)')
        c = checks.order_check(six)
        self.assertIn('lands in High Precision PCB (6 layers and more): the quote page\'s "High Precision PCB" class', c.details[0])
        self.assertEqual(len(c.details), 1, '6 layers at 1.6 mm is still Economic PCBA')

    def test_a_large_outline(self):
        b = pcb(smd('R1'), outline='(gr_line (start 0 0) (end 120 0) (layer "Edge.Cuts")) (gr_line (start 120 0) (end 120 80) (layer "Edge.Cuts")) '
                                   '(gr_line (start 120 80) (end 0 80) (layer "Edge.Cuts")) (gr_line (start 0 80) (end 0 0) (layer "Edge.Cuts"))')
        c = checks.order_check(b)
        self.assertEqual(c.details, ['size: outline 120 × 80 mm; the standard class is 100 × 100 mm or smaller; lands in larger than 100 × 100 mm: '
                                     f'priced as "Engineering fee" plus a "Board" line that grows with area (source: quote, production-time, dimensions, read {READ})'])

    def test_a_tall_board_fits_the_class_either_way_round(self):
        c = checks.order_check(pcb(smd('R1'), outline='(gr_rect (start 0 0) (end 50 100) (layer "Edge.Cuts"))'))
        self.assertEqual(c.status, 'pass')
        self.assertIn('outline 50 × 100 mm', c.notes[0])
        c = checks.order_check(pcb(smd('R1'), outline='(gr_rect (start 0.0001 0) (end 59.6366 62.6911) (layer "Edge.Cuts"))'))
        self.assertIn('outline 59.64 × 62.69 mm', c.notes[0], 'to the hundredth of a millimetre')

    def test_no_outline_is_said_not_guessed(self):
        c = checks.order_check(pcb(smd('R1'), outline=''))
        self.assertEqual(c.status, 'pass')
        self.assertIn('outline: no Edge.Cuts graphics, so the size was not read', c.notes[0])

    def test_thickness_and_layer_count_outside_economic(self):
        c = checks.order_check(pcb(smd('R1'), general='(general (thickness 2.0))'))
        self.assertEqual([d.split(':', 1)[0] for d in c.details], ['assembly class'])
        self.assertIn('2 copper layers, 2 mm thick; the standard is 2, 4 or 6 layers at 0.8-1.6 mm; lands in Standard PCBA: Economic PCBA: "2,4,6-layers", "0.8mm - 1.6mm"', c.details[0])
        c = checks.order_check(pcb(smd('R1'), general='(general (thickness 1.6062))'))
        self.assertEqual(c.status, 'pass', 'a stackup sum of 1.6062 is a 1.6 mm board: read to the nearest 0.1 mm')
        self.assertIn('1.6062 mm thick', c.notes[0])
        c = checks.order_check(pcb(smd('R1'), general='(general (thickness 1.66))'))
        self.assertEqual(c.status, 'cost')
        c = checks.order_check(pcb(smd('R1'), general=''))
        self.assertEqual(c.status, 'pass', "KiCad's 1.6 mm default when the file has no thickness")
        self.assertIn('1.6 mm thick', c.notes[0])
        eight = pcb(smd('R1'), layers=' '.join(f'({i} "In{i}.Cu" signal)' for i in range(1, 7)) + ' (0 "F.Cu" signal) (31 "B.Cu" signal)')
        c = checks.order_check(eight)
        self.assertEqual([d.split(':', 1)[0] for d in c.details], ['layers', 'assembly class'])


class Assembly(unittest.TestCase):
    def test_paste_on_both_sides_is_double_sided_placement(self):
        c = checks.order_check(pcb(smd('R1') + smd('R2', 'B.Cu') + smd('R3', 'B.Cu')))
        self.assertEqual(len(c.details), 1)
        self.assertTrue(c.details[0].startswith('placement: parts to place on both sides (1 on F.Cu, 2 on B.Cu: R2, R3 on the back); the standard is Economic PCBA: '
                                                '"Single sided placement (SMT/Thru-hole)"; Standard PCBA: "Single & double sided placement (SMT/Thru-hole)"; '
                                                'setup and stencil are priced per side'), c.details[0])
        self.assertIn(f'(source: pcba-capabilities, pcba-price, pcba-faqs, blog-pcba-cost, castellated, read {READ})', c.details[0])

    def test_a_dnp_or_pasteless_back_part_does_not_count(self):
        c = checks.order_check(pcb(smd('R1') + smd('R2', 'B.Cu', attrs='smd dnp') + smd('R3', 'B.Cu', paste=False)))
        self.assertEqual(c.status, 'pass')

    def test_a_through_hole_part_on_the_back_counts_as_double_sided(self):
        c = checks.order_check(pcb(smd('R1') + tht('J1', 'B.Cu')))
        self.assertEqual([d.split(':', 1)[0] for d in c.details], ['placement', 'through-hole'])

    def test_through_hole_parts_to_assemble(self):
        b = pcb(tht('J1') + tht('J2', pads=3) + tht('H1', net=False) + tht('J9', attrs='through_hole dnp') + smd('R1'))
        c = checks.order_check(b)
        self.assertEqual(len(c.details), 1)
        self.assertTrue(c.details[0].startswith('through-hole: 2 through-hole parts to assemble (J1, J2; 5 plated holes); the standard is surface mount only; '
                                                'either tier, wave soldering: priced per solder joint ("Manual Assembly") plus a hand-soldering labour fee per order'), c.details[0])
        self.assertIn('"+ 1 more day"', c.details[0])
        c = checks.order_check(b, lines=[line(['J2', 'R1'])])
        self.assertIn('1 through-hole part to assemble (J2; 3 plated holes)', c.details[0], 'with a BOM, only parts on a BOM line are assembled')
        c = checks.order_check(b, lines=[line(['R1'])])
        self.assertEqual(c.status, 'pass')
        self.assertIn('no through-hole parts to assemble', c.notes[0])

    def test_extended_part_types_move_here_from_the_stock_gate(self):
        records = {'C1': {'library': 'Extended'}, 'C2': {'library': 'Basic'}, 'C3': {'library': 'Preferred'}, 'C4': None, 'C5': {'library': 'Extended'}}
        c = checks.order_check(STANDARD_2L, lines=[line(['R1']), line(['R2'], 'C5')], records=records)
        self.assertEqual(c.details, ['parts: 2 Extended part types (one loading fee each: C1, C5); the standard is Basic and Preferred Extended parts; '
                                     'per unique part type: Economic PCBA: a feeder-loading fee per unique Extended part, Basic and Preferred Extended parts exempt; '
                                     f'Standard PCBA: a feeder-loading fee per unique part, Basic or Extended (source: pcba-capabilities, pcba-price, pcba-faqs, blog-pcba-cost, castellated, read {READ})'])
        c = checks.order_check(STANDARD_2L, records={'C2': {'library': 'Basic'}, 'C3': {'library': 'Preferred'}})
        self.assertEqual(c.status, 'pass')
        self.assertIn('every catalogue part is Basic or Preferred Extended', c.notes[0])
        c = checks.order_check(STANDARD_2L, records=None)
        self.assertNotIn('catalogue part', c.notes[0], 'offline the catalogue was not asked: nothing to say')

    def test_stackup_flags(self):
        b = pcb(smd('R1'), setup='(setup (stackup (layer "F.Cu" (type copper)) (castellated_pads yes) (edge_plating yes) (dielectric_constraints yes)))')
        c = checks.order_check(b)
        self.assertEqual([d.split(':', 1)[0] for d in c.details], ['castellated holes', 'edge plating', 'impedance control'])
        self.assertIn('castellated holes: set in the stackup; the standard is without; lands in Standard PCBA: Economic PCBA: "Not Support"', c.details[0])
        self.assertIn('hole ≥ 0.5 mm, board ≥ 10 × 10 mm and ≥ 0.6 mm thick', c.details[0])
        self.assertIn('lands in Specify Stackup', c.details[2])
        b = pcb(smd('R1'), setup='(setup (stackup (layer "F.Cu" (type copper)) (castellated_pads no)))')
        self.assertEqual(checks.order_check(b).status, 'pass', 'absent or "no" means no')
        self.assertEqual(c.summary, "3 drivers off JLCPCB's standard tier (castellated holes, edge plating, impedance control)")


def chk(cid, status, details=()):
    return checks.Check(cid, cid, '§', status, '', details=list(details))


class VerdictAndReport(unittest.TestCase):
    base = {'project': 'p', 'kicad_version': '10', 'copper_layers': 2, 'footprints': 1, 'bom_path': None, 'by_hand': []}
    cost = checks.Check('order', 'Order: what moves the price', '§13', 'cost', "2 drivers off JLCPCB's standard tier (vias, layers)",
                        ['vias: smallest via 0.2 mm hole ...', 'layers: 4 copper layers ...'], notes=['on the standard tier: ...', 'not in the files: ...'])

    def test_cost_never_moves_the_verdict_or_the_exit_code(self):
        self.assertEqual(report.verdict([chk('erc', 'pass'), self.cost]), 'PASS')
        self.assertEqual(report.verdict([chk('erc', 'pass'), self.cost], strict=True), 'PASS', '--strict does not promote cost')
        self.assertEqual(report.verdict([chk('stock', 'skip'), self.cost]), 'NOT VERIFIED')
        self.assertEqual(report.verdict([chk('drc', 'fail'), self.cost]), 'FAIL')
        self.assertEqual(report.verdict([chk('drc', 'skip'), self.cost]), 'ERROR')
        self.assertEqual(preset.EXIT[report.verdict([self.cost])], 0)

    def test_the_order_section_sits_between_findings_and_not_checked_and_the_count_is_on_the_result_lines(self):
        text = report.render(dict(self.base, checks=[chk('erc', 'pass'), chk('drc', 'warn', ['warning: x']), self.cost], options={'online': True}))
        lines = text.splitlines()
        self.assertTrue(lines[1].startswith('RESULT: PASS  -  0 blocking, 1 warnings, 0 not checked, 2 cost drivers  -  exit 0'), lines[1])
        self.assertEqual(lines[1], lines[-2])
        i = lines.index("ORDER (what moves the price off JLCPCB's standard tier; the quote page prices it)")
        self.assertLess(lines.index('FINDINGS'), i)
        self.assertLess(i, lines.index('NOT CHECKED'))
        self.assertEqual(lines[i + 1], "  COST  Order: what moves the price (§13): 2 drivers off JLCPCB's standard tier (vias, layers)")
        self.assertEqual(lines[i + 2], '        vias: smallest via 0.2 mm hole ...')
        self.assertEqual(lines[i + 4], '        note: on the standard tier: ...')
        self.assertNotIn('Order: what moves the price', '\n'.join(lines[:i]), 'a cost gate is not a finding and not "left alone"')

    def test_a_passing_order_gate_is_checked_and_left_alone_with_its_notes(self):
        c = checks.order_check(STANDARD_2L)
        text = report.render(dict(self.base, checks=[chk('erc', 'pass'), c], options={'online': False}))
        lines = text.splitlines()
        self.assertIn('0 not checked, 0 cost drivers', lines[1])
        i = lines.index('CHECKED AND LEFT ALONE')
        self.assertEqual(lines[i + 2], "  Order: what moves the price (§13): every driver the files can show is on JLCPCB's standard tier")
        self.assertTrue(lines[i + 3].startswith('        note: on the standard tier: vias smallest via 0.3 mm hole'))
        self.assertTrue(lines[i + 5].startswith('        note: JLCPCB assembles a minimum of 2 boards; order spares (§13)'))
        j = lines.index("ORDER (what moves the price off JLCPCB's standard tier; the quote page prices it)")
        self.assertEqual(lines[j + 1], '  nothing: every driver the files can show is on the standard tier')

    def test_without_an_order_gate_the_section_says_none(self):
        text = report.render(dict(self.base, checks=[chk('erc', 'pass')], options={'online': False}))
        self.assertIn("ORDER (what moves the price off JLCPCB's standard tier; the quote page prices it)\n  none\n", text)

    def test_json_carries_the_status_and_the_lines(self):
        j = json.loads(report.to_json(dict(self.base, checks=[chk('erc', 'pass'), self.cost])))
        self.assertEqual((j['result'], j['exit_code']), ('PASS', 0))
        order = next(c for c in j['checks'] if c['id'] == 'order')
        self.assertEqual(order['status'], 'cost')
        self.assertEqual(len(order['details']), 2)
        self.assertEqual(order['notes'][1], 'not in the files: ...')
        j = json.loads(report.to_json(dict(self.base, checks=[chk('erc', 'pass'), self.cost]), strict=True))
        self.assertEqual(j['result'], 'PASS')


if __name__ == '__main__':
    unittest.main()
