import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import board, checks, sexpr  # noqa: E402

PCB = '''(kicad_pcb (version 20241229) (generator "pcbnew") (generator_version "9.0")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (1 "In1.Cu" power) (2 "In2.Cu" signal) (3 "B.Cu" signal) (4 "F.Mask" user) (5 "F.SilkS" user "F.Silkscreen"))
  (setup (aux_axis_origin 20 95))
  (title_block (title "demo") (rev "v0.6"))
  (footprint "Fiducial:Fiducial_1mm_Mask2mm" (layer "F.Cu") (at 1 1) (property "Reference" "FID1" (at 0 0 0) (layer "F.Fab")) (property "Value" "Fiducial" (at 0 0 0) (layer "F.Fab")) (attr exclude_from_pos_files exclude_from_bom) (pad "" smd circle (at 0 0) (size 1 1) (layers "F.Cu")))
  (footprint "Fiducial:Fiducial_1mm_Mask2mm" (layer "F.Cu") (at 1 50) (property "Reference" "FID2" (at 0 0 0) (layer "F.Fab")) (property "Value" "Fiducial" (at 0 0 0) (layer "F.Fab")) (attr exclude_from_bom))
  (footprint "Fiducial:Fiducial_1mm_Mask2mm" (layer "B.Cu") (at 50 1) (property "Reference" "FID3" (at 0 0 0) (layer "B.Fab")) (property "Value" "Fiducial" (at 0 0 0) (layer "B.Fab")) (attr exclude_from_bom))
  (footprint "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical" (layer "F.Cu") (at 30 70) (property "Reference" "J1" (at 0 0 0) (layer "F.SilkS")) (property "Value" "J_SW" (at 0 3 0) (layer "F.Fab")) (attr through_hole))
  (footprint "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical" (layer "F.Cu") (at 80 70) (property "Reference" "J2" (at 0 0 0) (layer "F.SilkS")) (property "Value" "J_PROBE" (at 0 3 0) (layer "F.SilkS")) (attr through_hole))
  (footprint "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical" (layer "F.Cu") (at 100 10) (property "Reference" "J3" (at 0 0 0) (layer "F.SilkS")) (property "Value" "J_LONELY" (at 0 3 0) (layer "F.SilkS") (hide yes)) (attr through_hole))
  (footprint "Diode_SMD:D_SOD-123" (layer "F.Cu") (at 10 40) (property "Reference" "D11" (at 0 0 0) (layer "F.SilkS")) (property "Value" "SMF3.3A DNP" (at 0 0 0) (layer "F.Fab")) (attr smd dnp))
  (footprint "Capacitor_SMD:CP_Elec_10x10" (layer "F.Cu") (at 56 19) (property "Reference" "C2" (at 0 0 0) (layer "F.SilkS")) (property "Value" "470uF" (at 0 0 0) (layer "F.Fab")) (attr smd))
  (footprint "Inductor_SMD:L_Bourns_SRP1245A" (layer "F.Cu") (at 70 30) (property "Reference" "L1" (at 0 0 0) (layer "F.SilkS")) (property "Value" "10uH" (at 0 0 0) (layer "F.Fab")) (attr smd))
  (gr_text "SW" (at 30 66) (layer "F.SilkS"))
  (gr_text "sorter_pdb v0.6" (at 50 50) (layer "F.SilkS"))
  (gr_text "hidden note \\"quoted\\"" (at 50 50) (layer "Cmts.User"))
)'''


class Sexpr(unittest.TestCase):
    def test_roundtrip_quotes(self):
        n = sexpr.parse('(a "x \\"y\\" z" (b 1 2))')
        self.assertEqual(n, ['a', 'x "y" z', ['b', '1', '2']])

    def test_unbalanced(self):
        with self.assertRaises(ValueError):
            sexpr.parse('(a (b)')


class BoardChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f = tempfile.NamedTemporaryFile('w', suffix='.kicad_pcb', delete=False)
        f.write(PCB)
        f.close()
        cls.b = board.load(f.name)

    def test_load(self):
        b = self.b
        self.assertEqual(b.copper_layers, 4)
        self.assertEqual(b.aux_origin, (20.0, 95.0))
        self.assertEqual(len(b.footprints), 9)
        self.assertEqual(b.title_rev, 'v0.6')
        self.assertEqual([t[0] for t in b.silk_texts], ['SW', 'sorter_pdb v0.6'])
        d11 = next(fp for fp in b.footprints if fp.ref == 'D11')
        self.assertTrue(d11.dnp)

    def test_fiducials_count_front_only(self):
        c = checks.fiducial_check(self.b)
        self.assertEqual(c.status, 'warn')
        self.assertIn('2 on the front', c.summary)

    def test_origin_and_layers(self):
        self.assertEqual(checks.origin_check(self.b).status, 'pass')
        self.assertEqual(checks.layer_check(self.b).status, 'pass')

    def test_silk(self):
        self.assertEqual(checks.silk_check(self.b, 'sorter_pdb').status, 'pass')
        self.assertEqual(checks.silk_check(self.b, 'other_board').status, 'warn')

    def test_connectors(self):
        c = checks.connector_check(self.b)
        self.assertEqual(c.status, 'warn')
        self.assertEqual(len(c.details), 1)
        self.assertIn('J3', c.details[0])

    def test_dnp_against_schematic(self):
        sch = [{'Ref': 'D11', 'DNP': True, 'ExcludeFromBOM': False, 'Value': '', 'Footprint': ''},
               {'Ref': 'D12', 'DNP': True, 'ExcludeFromBOM': False, 'Value': '', 'Footprint': ''}]
        c = checks.dnp_board_check(self.b, sch)
        self.assertEqual(c.status, 'fail')
        self.assertIn('D12', c.details[0])

    def test_by_hand_lists_polarized(self):
        lines = checks.by_hand(self.b)
        self.assertIn('J1', lines[0])
        self.assertIn('C2', lines[0])
        self.assertNotIn('D11', lines[0])

    def test_parity_skip_detection(self):
        c = checks.parity_check({'schematic_parity': []}, 'Failed to fetch schematic netlist for parity tests.\nFound 2 violations', 9)
        self.assertEqual(c.status, 'skip')
        c = checks.parity_check({'schematic_parity': []}, 'Found 0 schematic parity issues', 9)
        self.assertEqual(c.status, 'pass')


if __name__ == '__main__':
    unittest.main()
