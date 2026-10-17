"""The contract (preset.py): verdicts and exit codes, what the gate owns, parity, identity, placement, sign-off."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import board, checks, cli, kicad, preset, report, schematic  # noqa: E402
from pcb_preflight.bom import Line  # noqa: E402

ROOT_SCH = '''(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")
  (uuid "root-0000")
  (paper "A4")
  (lib_symbols
    (symbol "Device:R" (property "Reference" "R" (at 0 0 0)) (symbol "R_0_1" (rectangle (start 0 0) (end 1 1))))
  )
  (symbol (lib_id "Device:R") (at 10 10 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid "sym-r1")
    (property "Reference" "R1" (at 0 0 0)) (property "Value" "10k" (at 0 0 0))
    (pin "1" (uuid "p1")) (pin "2" (uuid "p2"))
    (instances (project "demo" (path "/root-0000" (reference "R1") (unit 1))))
  )
  (symbol (lib_id "Device:C") (at 20 10 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid "sym-c1")
    (property "Reference" "C1" (at 0 0 0)) (property "Value" "100nF" (at 0 0 0))
    (instances (project "demo" (path "/root-0000" (reference "C1") (unit 1))))
  )
  (symbol (lib_id "Device:C") (at 25 10 0) (unit 1) (in_bom yes) (on_board no) (dnp no) (uuid "sym-c2")
    (property "Reference" "C2" (at 0 0 0)) (property "Value" "1uF" (at 0 0 0))
    (instances (project "demo" (path "/root-0000" (reference "C2") (unit 1))))
  )
  (symbol (lib_id "power:GND") (at 30 10 0) (unit 1) (uuid "sym-pwr")
    (property "Reference" "#PWR01" (at 0 0 0))
    (instances (project "demo" (path "/root-0000" (reference "#PWR01") (unit 1))))
  )
  (sheet (at 50 50) (size 20 10) (uuid "sheet-pwr")
    (property "Sheetname" "power" (at 0 0 0)) (property "Sheetfile" "power.kicad_sch" (at 0 0 0))
    (instances (project "demo" (path "/root-0000" (page "2"))))
  )
  (sheet_instances (path "/" (page "1")))
)'''

SUB_SCH = '''(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")
  (uuid "power-0000")
  (symbol (lib_id "Device:L") (at 10 10 0) (unit 1) (uuid "sym-l1")
    (property "Reference" "L1" (at 0 0 0)) (property "Value" "10uH" (at 0 0 0))
    (instances (project "demo" (path "/root-0000/sheet-pwr" (reference "L1") (unit 1))))
  )
)'''


def pcb(*footprints):
    body = '\n'.join(footprints)
    return f'''(kicad_pcb (version 20241229) (generator "pcbnew") (generator_version "9.0")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  {body}
)'''


def fp(ref, lib, path=None, attrs='smd', pads=''):
    p = f' (path "{path}")' if path is not None else ''
    return (f'(footprint "{lib}" (layer "F.Cu") (at 1 1) (property "Reference" "{ref}" (at 0 0 0) (layer "F.SilkS")) '
            f'(property "Value" "x" (at 0 0 0) (layer "F.Fab")){p} (attr {attrs}) {pads})')


PASTE_PAD = '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask") (net 1 "GND"))'
BARE_PAD = '(pad "1" thru_hole circle (at 0 0) (size 3 3) (drill 2) (layers "*.Cu" "*.Mask") (net 1 "GND"))'


def write(dirname, name, text):
    path = os.path.join(dirname, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def jload(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def chk(cid, status, unchecked=()):
    return checks.Check(cid, cid, '§', status, '', unchecked=list(unchecked))


def row(ref, footprint='Resistor_SMD:R_0603_1608Metric', dnp=False, excl=False, off_board=False):
    return {'Ref': ref, 'Value': 'x', 'Footprint': footprint, 'DNP': dnp, 'ExcludeFromBOM': excl, 'ExcludeFromBoard': off_board}


class Verdicts(unittest.TestCase):
    def test_pass_only_when_everything_ran_and_judged(self):
        self.assertEqual(report.verdict([chk('erc', 'pass'), chk('stock', 'pass')]), 'PASS')

    def test_core_skip_is_error_even_with_findings(self):
        self.assertEqual(report.verdict([chk('drc', 'skip'), chk('bom-lcsc', 'fail')]), 'ERROR')
        for cid in preset.CORE:
            self.assertEqual(report.verdict([chk(cid, 'skip')]), 'ERROR', cid)
        self.assertIn('placement', preset.CORE)

    def test_fail_outranks_not_verified(self):
        self.assertEqual(report.verdict([chk('bom-lcsc', 'fail'), chk('stock', 'skip')]), 'FAIL')

    def test_other_skip_or_unchecked_is_not_verified(self):
        self.assertEqual(report.verdict([chk('erc', 'pass'), chk('stock', 'skip')]), 'NOT VERIFIED')
        self.assertEqual(report.verdict([chk('catalogue-package', 'pass', ['C1 (R1): ...'])]), 'NOT VERIFIED')

    def test_strict_promotes_warnings(self):
        self.assertEqual(report.verdict([chk('drc', 'warn')]), 'PASS')
        self.assertEqual(report.verdict([chk('drc', 'warn')], strict=True), 'FAIL')

    def test_exit_codes(self):
        self.assertEqual(preset.EXIT, {'PASS': 0, 'FAIL': 1, 'ERROR': 2, 'NOT VERIFIED': 3})


class Report(unittest.TestCase):
    base = {'project': 'p', 'kicad_version': '10', 'copper_layers': 2, 'footprints': 1, 'bom_path': '/x/y/bom.csv', 'by_hand': []}

    def test_verdict_is_on_the_second_line_and_the_last(self):
        text = report.render(dict(self.base, checks=[chk('erc', 'pass'), chk('stock', 'skip')], options={'online': False}))
        lines = text.splitlines()
        self.assertTrue(lines[0].endswith('bom.csv: bom.csv'), lines[0])
        self.assertTrue(lines[1].startswith('RESULT: NOT VERIFIED  -  0 blocking, 0 warnings, 1 not checked  -  exit 3'), lines[1])
        self.assertIn('run with --online', lines[2])
        self.assertEqual(lines[1], lines[-2])

    def test_error_names_the_gate_that_did_not_run_up_top(self):
        c = checks.Check('erc', 'ERC', '§12', 'skip', 'ERC produced no report: boom')
        text = report.render(dict(self.base, checks=[c, chk('bom-lcsc', 'fail')], options={'online': True}))
        lines = text.splitlines()
        self.assertTrue(lines[1].startswith('RESULT: ERROR'))
        self.assertIn('a core gate did not run (ERC); nothing in this report is a pass', lines[2])
        self.assertEqual(lines[3], '  ERC: ERC produced no report: boom')

    def test_pass_and_json(self):
        text = report.render(dict(self.base, checks=[chk('erc', 'pass')], options={'online': True}))
        self.assertIn('RESULT: PASS  -  0 blocking, 0 warnings, 0 not checked  -  exit 0', text)
        self.assertIn(f'every gate ran under {preset.PRESET}', text)
        self.assertIn('online  -  2 copper layers', text)
        j = json.loads(report.to_json(dict(self.base, checks=[chk('erc', 'pass')])))
        self.assertEqual((j['result'], j['exit_code']), ('PASS', 0))
        self.assertIn('notes', j['checks'][0])

    def test_notes_print_under_the_gate_but_pass_details_do_not(self):
        c = checks.Check('stock', 'Catalogue and stock', '§', 'pass', '2 codes found', details=['should not print'], notes=['ok: C1 ...'])
        text = report.render(dict(self.base, checks=[c], options={'online': True}))
        self.assertIn('        note: ok: C1 ...', text)
        self.assertNotIn('should not print', text)


class OwnedSeverities(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        pin_map = [list(r) for r in preset.DEFAULT_PIN_MAP]
        pin_map[8][8] = 0            # power_out x power_out: error -> ok
        pin_map[1][1] = 1            # output x output: error -> warning
        pin_map[0][11] = 2           # already the default
        self.pro = write(self.dir, 'demo.kicad_pro', json.dumps({
            'board': {'design_settings': {
                'rule_severities': {'unconnected_items': 'ignore', 'missing_courtyard': 'ignore', 'clearance': 'error',
                                    'missing_footprint': 'warning', 'silk_edge_clearance': 'warning', 'text_on_edge_cuts': 'warning'},
                'rules': {'min_track_width': 0.0, 'min_clearance': 0.2, 'min_via_diameter': 0.4, 'min_via_annular_width': 0.1,
                          'min_through_hole_diameter': 0.3, 'min_hole_to_hole': 0.25, 'min_copper_edge_clearance': 0.3},
                'drc_exclusions': ['shorting_items|1|2|a|b|F.Cu|']}},
            'erc': {'rule_severities': {'pin_not_connected': 'ignore', 'pin_to_pin': 'warning', 'similar_labels': 'warning'},
                    'pin_map': pin_map},
            'net_settings': {'classes': [{'name': 'Default', 'clearance': 0.05}, {'name': 'power', 'clearance': 0.25}]}}))

    def test_apply_reports_only_what_the_project_changed_from_kicads_defaults(self):
        changed = preset.apply(self.pro)
        self.assertEqual(changed['drc'], {'unconnected_items': 'ignore', 'text_on_edge_cuts': 'warning'},
                         'missing_courtyard: ignore and missing_footprint: warning are KiCad defaults, not the project\'s doing')
        self.assertEqual(changed['erc'], {'pin_not_connected': 'ignore'})
        self.assertEqual(changed['pin_map'], 2)
        self.assertEqual(changed['minimums'], {'min_track_width': (0.0, 0.10)})
        self.assertEqual(changed['netclasses'], {'Default': (0.05, 0.10)})

    def test_apply_rewrites_the_copy(self):
        preset.apply(self.pro)
        pro = jload((self.pro))
        drc = pro['board']['design_settings']['rule_severities']
        for key in preset.DRC_PROTECTED:
            self.assertEqual(drc[key], 'error', key)
        self.assertEqual(drc['silk_edge_clearance'], 'warning', 'not protected: the project keeps its choice')
        erc = pro['erc']
        for key in preset.ERC_PROTECTED:
            self.assertEqual(erc['rule_severities'][key], 'error', key)
        self.assertEqual(erc['rule_severities']['similar_labels'], 'warning')
        self.assertEqual(erc['pin_map'][8][8], 2)
        self.assertEqual(erc['pin_map'][1][1], 2)
        self.assertEqual(erc['pin_map'][4][4], preset.DEFAULT_PIN_MAP[4][4])
        rules = pro['board']['design_settings']['rules']
        self.assertEqual((rules['min_track_width'], rules['min_clearance'], rules['min_via_diameter']), (0.10, 0.2, 0.4))
        self.assertEqual([c['clearance'] for c in pro['net_settings']['classes']], [0.10, 0.25])
        self.assertEqual(pro['board']['design_settings']['drc_exclusions'][0][:14], 'shorting_items', 'exclusions stay; the gate reads them')

    def test_multilayer_floor(self):
        preset.apply(self.pro, copper_layers=4)
        self.assertEqual(jload((self.pro))['board']['design_settings']['rules']['min_track_width'], 0.09)

    def test_apply_on_a_bare_project_file(self):
        bare = write(self.dir, 'bare.kicad_pro', '{}')
        changed = preset.apply(bare)
        self.assertEqual((changed['drc'], changed['erc'], changed['pin_map']), ({}, {}, 0))
        self.assertEqual(set(changed['minimums']), set(preset.minimums(2)))
        pro = jload((bare))
        self.assertEqual(pro['board']['design_settings']['rule_severities']['unconnected_items'], 'error')
        self.assertEqual(pro['board']['design_settings']['rules']['min_track_width'], 0.10)

    def test_malformed_project_file_names_the_file(self):
        bad = write(self.dir, 'bad.kicad_pro', '{not json')
        with self.assertRaises(ValueError) as cm:
            preset.apply(bad)
        self.assertIn('bad.kicad_pro', str(cm.exception))
        lst = write(self.dir, 'list.kicad_pro', '[]')
        with self.assertRaises(ValueError):
            preset.apply(lst)

    def test_protected_sets_are_kicads_default_errors_plus_the_named_exceptions(self):
        self.assertTrue(preset.PARITY <= preset.DRC_PROTECTED)
        self.assertIn('missing_courtyard', preset.DRC_PROTECTED)
        self.assertIn('pin_to_pin', preset.ERC_PROTECTED)
        self.assertNotIn('lib_symbol_issues', preset.ERC_PROTECTED, 'a library-lookup warning must not block a CI runner')
        self.assertNotIn('silk_edge_clearance', preset.DRC_PROTECTED)
        for key in preset.DRC_PROTECTED - preset.PARITY - {'missing_courtyard'}:
            self.assertEqual(preset.KICAD_DEFAULT['drc'].get(key, 'error'), 'error', key)
        for key in preset.ERC_PROTECTED - {'pin_to_pin'}:
            self.assertEqual(preset.KICAD_DEFAULT['erc'].get(key, 'error'), 'error', key)
        self.assertEqual(len(preset.DEFAULT_PIN_MAP), 12)
        self.assertTrue(all(len(r) == 12 and all(c in (0, 1, 2) for c in r) for r in preset.DEFAULT_PIN_MAP))
        self.assertEqual(preset.DEFAULT_PIN_MAP[11], [2] * 12, 'no_connect against anything is an error')
        self.assertEqual(preset.minimums(2)['min_track_width'], 0.10)
        self.assertEqual(preset.minimums(6)['min_clearance'], 0.09)


def violation(vtype, severity, desc='x', excluded=False):
    v = {'type': vtype, 'severity': severity, 'description': desc, 'items': [{'description': 'item', 'pos': {'x': 1, 'y': 2}}]}
    if excluded:
        v['excluded'] = True
    return v


class KicadGates(unittest.TestCase):
    def test_severity_buckets_use_kicads_excluded_flag(self):
        e, w, x = kicad.count_severities([violation('clearance', 'error'), violation('silk_overlap', 'warning'),
                                          violation('clearance', 'error', excluded=True), violation('text_height', 'exclusion')])
        self.assertEqual((len(e), len(w), len(x)), (1, 1, 2))

    def test_drc_blocks_when_the_project_ignores_a_protected_check(self):
        rep = {'violations': [], 'ignored_checks': [{'key': 'unconnected_items'}, {'key': 'track_not_centered_on_via'}, {'key': 'silk_overlap'}]}
        c = checks.drc_check(rep, owned={})
        self.assertEqual(c.status, 'fail')
        self.assertTrue(any(d.startswith('blocked: unconnected_items is ignored in the project') for d in c.details), c.details)
        self.assertEqual(len(c.notes), 1)
        self.assertIn("beyond KiCad's defaults", c.notes[0])
        self.assertIn('silk_overlap', c.notes[0])
        self.assertNotIn('track_not_centered_on_via', c.notes[0], 'KiCad ignores it by default: not the project\'s doing')

    def test_drc_blocks_an_excluded_protected_violation_and_keeps_the_rest_excluded(self):
        rep = {'violations': [violation('shorting_items', 'error', excluded=True), violation('silk_edge_clearance', 'warning', excluded=True)],
               'ignored_checks': []}
        c = checks.drc_check(rep, owned={})
        self.assertEqual(c.status, 'fail')
        self.assertIn('0 errors, 0 warnings, 2 excluded by the project', c.summary)
        self.assertTrue(any(d.startswith('blocked: excluded in the project, but') and 'shorting_items' in d for d in c.details))
        self.assertFalse(any('silk_edge_clearance' in d for d in c.details), 'an excluded warning stays excluded')

    def test_drc_notes_say_what_the_gate_changed(self):
        owned = {'drc': {'unconnected_items': 'ignore'}, 'erc': {}, 'pin_map': 0,
                 'minimums': {'min_track_width': (0.0, 0.1)}, 'netclasses': {'Default': (0.05, 0.1)}}
        c = checks.drc_check({'violations': [], 'ignored_checks': []}, owned, custom_rules='/p/demo.kicad_dru', copper_layers=4)
        self.assertEqual(c.status, 'pass')
        self.assertEqual(c.details, [])
        self.assertIn(f'severities: {preset.PRESET}; the project had lowered unconnected_items to ignore (KiCad default error)', c.notes)
        self.assertIn("minimums: JLCPCB 1 oz copper, 4 layers; below the fab's in the project, raised in the copy: min_track_width 0.0 -> 0.1 mm, netclass Default clearance 0.05 -> 0.1 mm", c.notes)
        self.assertTrue(any('demo.kicad_dru' in n and 'not applied' in n for n in c.notes))
        c = checks.drc_check({'violations': [violation('clearance', 'warning')], 'ignored_checks': []}, owned={})
        self.assertEqual((c.status, c.details[0][:18], c.notes), ('warn', 'warning: clearance', []))

    def test_missing_courtyard_is_not_checked_rather_than_blocked(self):
        rep = {'violations': [violation('missing_courtyard', 'error', 'Footprint has no courtyard defined')], 'ignored_checks': []}
        c = checks.drc_check(rep, owned={})
        self.assertEqual(c.status, 'pass')
        self.assertEqual(c.details, [])
        self.assertEqual(len(c.unchecked), 1)
        self.assertIn('courtyards_overlap could not see this footprint', c.unchecked[0])
        self.assertIn('1 footprints without a courtyard', c.summary)
        self.assertEqual(report.verdict([c]), 'NOT VERIFIED')

    def test_erc(self):
        rep = {'sheets': [{'violations': []}], 'ignored_checks': [{'key': 'pin_not_connected'}]}
        self.assertEqual(checks.erc_check(rep, owned={}).status, 'fail')
        rep = {'sheets': [{'violations': [violation('pin_not_connected', 'error')]}], 'ignored_checks': []}
        c = checks.erc_check(rep, owned={'drc': {}, 'erc': {}, 'pin_map': 3, 'minimums': {}, 'netclasses': {}})
        self.assertEqual(c.status, 'fail')
        self.assertIn('1 errors, 0 warnings on 1 sheet', c.summary)
        self.assertTrue(any('weakened 3 of its 144 cells' in n for n in c.notes))

    def test_parity_blocks_the_five_parity_checks_whatever_kicad_calls_them(self):
        rep = {'schematic_parity': [violation('missing_footprint', 'warning', 'Missing footprint C90'),
                                    violation('extra_footprint', 'warning', 'Extra footprint', excluded=True)]}
        c = checks.parity_check(rep, '', 129)
        self.assertEqual(c.status, 'fail')
        self.assertIn('2 mismatches across 129 footprints', c.summary)
        self.assertIn(f'blocks under {preset.PRESET}', c.details[0])
        self.assertIn('Not in schematic', c.details[1], 'extra_footprint names the one-checkbox fix')
        self.assertEqual(checks.parity_check({'schematic_parity': []}, '', 130).status, 'pass')
        self.assertEqual(checks.parity_check({}, 'Failed to fetch schematic netlist', 130).status, 'skip')

    def test_parity_field_and_filter_notes_keep_the_projects_severity(self):
        rep = {'schematic_parity': [violation('footprint_symbol_field_mismatch', 'warning', "Field 'Datasheet' differs"),
                                    violation('footprint_filters_mismatch', 'warning', 'does not match filters')]}
        c = checks.parity_check(rep, '', 130)
        self.assertEqual(c.status, 'warn')
        self.assertEqual(c.summary, '0 mismatches, 2 field/filter notes across 130 footprints')
        self.assertTrue(all(d.startswith('warning: ') for d in c.details))
        rep = {'schematic_parity': [violation('footprint_filters_mismatch', 'error', 'the project raised it')]}
        self.assertEqual(checks.parity_check(rep, '', 130).status, 'fail')


class Identity(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.sch = write(self.dir, 'demo.kicad_sch', ROOT_SCH)
        write(self.dir, 'power.kicad_sch', SUB_SCH)
        self.symbols = schematic.load_symbols(self.sch)

    def test_symbols_across_sheets(self):
        self.assertEqual(set(self.symbols), {'sym-r1', 'sym-c1', 'sym-c2', 'sym-pwr', 'sym-l1'}, 'placed symbols only, lib_symbols never')
        l1 = self.symbols['sym-l1']
        self.assertEqual((l1.ref, l1.lib_id, l1.sheet_file, l1.on_board), ('L1', 'Device:L', 'power.kicad_sch', True))
        self.assertEqual(l1.instances, {'/root-0000/sheet-pwr': 'L1'})
        self.assertEqual(l1.references, ['L1'])
        self.assertFalse(self.symbols['sym-c2'].on_board)

    def test_missing_sheet_file_raises(self):
        write(self.dir, 'broken.kicad_sch', ROOT_SCH.replace('power.kicad_sch', 'gone.kicad_sch'))
        with self.assertRaises(OSError):
            schematic.load_symbols(os.path.join(self.dir, 'broken.kicad_sch'))

    def board(self, *fps):
        return board.load(write(self.dir, 'demo.kicad_pcb', pcb(*fps)))

    def test_every_footprint_names_its_symbol(self):
        b = self.board(fp('R1', 'Resistor_SMD:R_0603_1608Metric', '/root-0000/sym-r1'),
                       fp('C1', 'Capacitor_SMD:C_0603_1608Metric', '/root-0000/sym-c1'),
                       fp('L1', 'Inductor_SMD:L_Bourns_SRP1245A', '/root-0000/sheet-pwr/sym-l1'),
                       fp('FID1', 'Fiducial:Fiducial_1mm_Mask2mm'),
                       fp('H1', 'MountingHole:MountingHole_3.2mm_M3_Pad', attrs='through_hole board_only', pads=BARE_PAD))
        self.assertEqual(b.footprints[0].path, '/root-0000/sym-r1')
        c = checks.identity_check(b, self.symbols)
        self.assertEqual(c.status, 'pass', c.details)
        self.assertEqual(c.summary, '3 of 5 footprints name a symbol in the schematic, 2 board-only')
        self.assertEqual(c.details, [])
        self.assertEqual(c.notes, ['2 board-only footprints (no path, reference not in the schematic): FID1, H1'])

    def test_regenerated_schematic_is_caught(self):
        b = self.board(fp('R1', 'Resistor_SMD:R_0603_1608Metric', '/root-0000/new-r1'),
                       fp('C1', 'Capacitor_SMD:C_0603_1608Metric', '/root-0000/new-c1'),
                       fp('L1', 'Inductor_SMD:L_Bourns_SRP1245A', '/root-0000/sheet-pwr/new-l1'))
        c = checks.identity_check(b, self.symbols)
        self.assertEqual(c.status, 'fail')
        self.assertEqual(c.summary, '3 orphaned, 0 unlinked, 0 renamed of 3 footprints')
        self.assertIn('regenerated', c.details[0])
        self.assertIn('R1: points at a symbol that is not in the schematic', c.details)

    def test_stripping_the_paths_is_no_escape(self):
        b = self.board(fp('R1', 'Resistor_SMD:R_0603_1608Metric', attrs='smd board_only'),
                       fp('C1', 'Capacitor_SMD:C_0603_1608Metric'),
                       fp('L1', 'Inductor_SMD:L_Bourns_SRP1245A'))
        c = checks.identity_check(b, self.symbols)
        self.assertEqual(c.status, 'fail')
        self.assertEqual(c.summary, '0 orphaned, 3 unlinked, 0 renamed of 3 footprints')
        self.assertIn('R1: no schematic link, but the schematic has a R1; re-link it with Update PCB from Schematic', c.details)
        self.assertTrue(any('regenerated' in d or 'stripped' in d for d in c.details))
        self.assertEqual(c.notes, [])

    def test_one_unlinked_blocks_without_the_regenerated_diagnosis(self):
        b = self.board(fp('R1', 'Resistor_SMD:R_0603_1608Metric', '/root-0000/sym-r1'),
                       fp('C1', 'Capacitor_SMD:C_0603_1608Metric', '/root-0000/sym-c1'),
                       fp('L1', 'Inductor_SMD:L_Bourns_SRP1245A', '/root-0000/sheet-pwr/sym-l1'),
                       fp('C2', 'Capacitor_SMD:C_0603_1608Metric'))
        c = checks.identity_check(b, self.symbols)
        self.assertEqual(c.status, 'fail')
        self.assertEqual(c.summary, '0 orphaned, 1 unlinked, 0 renamed of 4 footprints')
        self.assertFalse(any('regenerated' in d for d in c.details))

    def test_nothing_linked_at_all_blocks(self):
        b = self.board(fp('G1', 'Symbol:Logo', attrs='smd board_only'), fp('G2', 'Symbol:Logo', attrs='smd board_only'))
        c = checks.identity_check(b, self.symbols)
        self.assertEqual(c.status, 'fail')
        self.assertIn('no footprint on the board is linked to any symbol in the schematic', c.details)

    def test_renamed_reference_blocks(self):
        b = self.board(fp('R7', 'Resistor_SMD:R_0603_1608Metric', '/root-0000/sym-r1'))
        c = checks.identity_check(b, self.symbols)
        self.assertEqual(c.status, 'fail')
        self.assertIn('R7 on the board is R1 in the schematic (Device:R)', c.details)


class Placement(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def board(self, *fps):
        return board.load(write(self.dir, 'demo.kicad_pcb', pcb(*fps)))

    def test_bought_parts_must_be_on_the_board(self):
        rows = [row('R1'), row('C1', off_board=True), row('L1'), row('D11', dnp=True), row('FID1')]
        b = self.board(fp('R1', 'Resistor_SMD:R_0603_1608Metric', '/r/1'))
        c = checks.placement_check(b, rows, checks.DEFAULT_SKIP_PREFIXES)
        self.assertEqual(c.status, 'fail')
        self.assertEqual(c.summary, '2 of 3 bought references have no footprint on the board')
        self.assertIn('in the BOM but excluded from the board in the schematic (place it, or exclude it from the BOM too): C1', c.details)
        self.assertIn('bought in the schematic but no footprint on the board: L1', c.details)
        b = self.board(fp('R1', 'Resistor_SMD:R_0603_1608Metric', '/r/1'), fp('C1', 'C', '/c/1'), fp('L1', 'L', '/l/1'))
        c = checks.placement_check(b, [row('R1'), row('C1'), row('L1'), row('D11', dnp=True)], checks.DEFAULT_SKIP_PREFIXES)
        self.assertEqual((c.status, c.summary), ('pass', '3 of 3 bought references have a footprint on the board'))


class BomRefs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def board(self, *fps):
        return board.load(write(self.dir, 'demo.kicad_pcb', pcb(*fps)))

    def test_what_is_not_bought_is_said(self):
        rows = [row('R1'), row('FID1'), row('D11', dnp=True), row('L3', excl=True), row('TP1')]
        lines = [Line(row=2, refs=['R1'], package='0603', lcsc='C1')]
        c = checks.bom_refs_check(lines, rows, checks.DEFAULT_SKIP_PREFIXES)
        self.assertEqual(c.status, 'pass')
        self.assertEqual(c.summary, '1 bought references, every one on exactly one BOM line')
        self.assertEqual(c.notes, ['not bought: FID1, TP1 (prefix FID/TP/H/MH); D11 (DNP); L3 (excluded from the BOM)'])

    def test_a_soldered_part_cannot_hide_behind_a_prefix_or_an_exclusion(self):
        rows = [row('R1'), row('TP99'), row('L3', excl=True), row('TP1'), row('FID1')]
        lines = [Line(row=2, refs=['R1'], package='0603', lcsc='C1')]
        b = self.board(fp('R1', 'R', '/r/1', pads=PASTE_PAD), fp('TP99', 'L', '/t/99', pads=PASTE_PAD),
                       fp('L3', 'L', '/l/3', attrs='smd exclude_from_bom', pads=PASTE_PAD),
                       fp('TP1', 'TestPoint:TestPoint_Pad_D1.0mm', '/t/1', pads=BARE_PAD),
                       fp('FID1', 'Fiducial:Fiducial_1mm_Mask2mm', '/f/1', pads=BARE_PAD))
        self.assertTrue(b.footprints[1].paste)
        self.assertFalse(b.footprints[3].paste)
        c = checks.bom_refs_check(lines, rows, checks.DEFAULT_SKIP_PREFIXES, b)
        self.assertEqual(c.status, 'fail')
        self.assertTrue(any(d.startswith('excluded from the BOM, but with paste pads') and 'L3' in d for d in c.details), c.details)
        self.assertTrue(any(d.startswith('prefix FID/TP/H/MH, but with paste pads') and 'TP99' in d and 'TP1' not in d for d in c.details), c.details)
        self.assertIn('2 hidden soldered parts', c.summary)
        self.assertEqual(c.notes, ['not bought: FID1, TP1, TP99 (prefix FID/TP/H/MH); L3 (excluded from the BOM)'])
        # a symbol with (in_bom no) is not in kicad-cli's export at all: the board still shows the soldered part
        b = self.board(fp('R1', 'R', '/r/1', pads=PASTE_PAD), fp('L9', 'L', '/l/9', attrs='smd exclude_from_bom', pads=PASTE_PAD),
                       fp('LOGO1', 'Symbol:Logo', attrs='smd board_only'))
        c = checks.bom_refs_check(lines, [row('R1')], checks.DEFAULT_SKIP_PREFIXES, b)
        self.assertEqual(c.status, 'fail')
        self.assertTrue(any(d.startswith('excluded from the BOM, but with paste pads') and 'L9' in d for d in c.details), c.details)
        self.assertEqual(c.notes, ['not bought: L9 (excluded from the BOM); LOGO1 (board-only, no symbol)'])
        c = checks.bom_refs_check(lines, rows, checks.DEFAULT_SKIP_PREFIXES)
        self.assertEqual(c.status, 'pass', 'without the board the gate cannot see pads and says nothing about them')


SCH_ROWS = [{'Ref': 'C1', 'Value': '10uF', 'Footprint': 'Capacitor_SMD:C_0805_2012Metric', 'DNP': False, 'ExcludeFromBOM': False},
            {'Ref': 'J1', 'Value': 'J_IN', 'Footprint': 'TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-2-5.0-H_1x02_P5.00mm_Horizontal', 'DNP': False, 'ExcludeFromBOM': False}]


class SignOff(unittest.TestCase):
    def test_a_note_never_overrides_a_known_mismatch(self):
        lines = [Line(row=2, refs=['C1'], package='1210', lcsc='C49678', package_verified='ok')]
        c = checks.bom_package_check(lines, SCH_ROWS)
        self.assertEqual(c.status, 'fail')
        self.assertEqual(c.verified, [])
        self.assertIn('C1 (bom.csv row 2): 1210 on C_0805_2012Metric: footprint is 0805, part is 1210', c.details[0])
        self.assertIn('the "Package verified" note ("ok") does not apply', c.details[0])

    def test_a_note_still_covers_what_the_tool_cannot_read(self):
        lines = [Line(row=2, refs=['J1'], package='Plugin,P=5mm', lcsc='C3819953', package_verified='2026-10-16 BD: 1935161 drawing')]
        c = checks.bom_package_check(lines, SCH_ROWS)
        self.assertEqual(c.status, 'pass')
        self.assertEqual(len(c.verified), 1)
        self.assertEqual(c.unchecked, [])

    def test_an_unknown_item_says_how_to_clear_it(self):
        lines = [Line(row=3, refs=['J1'], package='Plugin,P=5mm', lcsc='C3819953')]
        c = checks.bom_package_check(lines, SCH_ROWS)
        self.assertEqual(c.status, 'skip')
        self.assertIn('bom.csv row 3', c.unchecked[0])
        self.assertIn('"Package verified" note (date, initials, what was compared)', c.unchecked[0])
        self.assertIn('sign each under NOT CHECKED', c.summary)


class CatalogueOutage(unittest.TestCase):
    def test_unreachable_codes_are_not_checked_not_passed(self):
        lines = [Line(row=2, refs=['C1'], package='0805', lcsc='C28323', mpn='CL21B105KBFNNNE'),
                 Line(row=3, refs=['J1'], package='Plugin,P=5mm', lcsc='C3819953', mpn='1935161')]
        def lookup(code):
            if code == 'C3819953':
                raise checks.stock.LookupFailed('jlcpcb: timed out; jlcsearch: timed out')
            return {'mpn': 'CL21B105KBFNNNE', 'package': '0805', 'library': 'Basic', 'stock': 2000000}
        records = {}
        s = checks.stock_check(lines, lookup=lookup, records=records)
        self.assertEqual(s.status, 'pass')
        self.assertEqual(records['C3819953'], None)
        self.assertEqual(len(s.unchecked), 1)
        self.assertIn('C3819953 (J1): lookup failed', s.unchecked[0])
        self.assertTrue(s.details[0].startswith('ok: C28323'), 'per-item evidence is a detail (JSON), not a note')
        p = checks.catalogue_package_check(lines, records, SCH_ROWS)
        self.assertEqual(p.status, 'pass')
        self.assertIn('1 agree', p.summary)
        self.assertIn('1 not reachable', p.summary)
        self.assertEqual(len(p.unchecked), 1)
        self.assertIn('1 codes not looked up', p.unchecked[0])
        self.assertEqual(report.verdict([s, p]), 'NOT VERIFIED')

    def test_everything_unreachable_is_a_skip(self):
        lines = [Line(row=2, refs=['C1'], package='0805', lcsc='C28323')]
        def lookup(code):
            raise checks.stock.LookupFailed('offline')
        records = {}
        s = checks.stock_check(lines, lookup=lookup, records=records)
        self.assertEqual(s.status, 'skip')
        p = checks.catalogue_package_check(lines, records, SCH_ROWS)
        self.assertEqual(p.status, 'skip')
        self.assertEqual(len(p.unchecked), 1)
        self.assertEqual(report.verdict([s, p]), 'NOT VERIFIED')

    def test_a_blank_mpn_is_not_a_checked_line(self):
        for mpn in ('', '-', ' '):
            lines = [Line(row=2, refs=['R72'], package='0603', lcsc='C14663', mpn=mpn)]
            s = checks.stock_check(lines, lookup=lambda c: {'mpn': 'CC0603KRX7R9BB104', 'package': '0603', 'library': 'Basic', 'stock': 10 ** 7})
            self.assertEqual(s.status, 'pass', mpn)
            self.assertEqual(len(s.unchecked), 1, mpn)
            self.assertIn("no MPN in bom.csv to compare with the catalogue's CC0603KRX7R9BB104", s.unchecked[0])
            self.assertEqual(report.verdict([s]), 'NOT VERIFIED')
        f = checks.bom_fields_check([Line(row=2, refs=['R72'], package='0603', lcsc='C14663', mpn='-', library='Basic', stock='1', datasheet='u')])
        self.assertIn('missing MPN', f.details[0])


class Cli(unittest.TestCase):
    def test_tool_failures_exit_2_and_write_the_json(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, 'r.json')
        with mock.patch('sys.stderr'):
            self.assertEqual(cli.main(['check', os.path.join(d, 'nope'), '--json', out]), 2)
        j = jload((out))
        self.assertEqual((j['result'], j['exit_code'], j['checks']), ('ERROR', 2, []))
        self.assertIn('is not a directory', j['error'])
        with mock.patch('sys.stderr'):
            self.assertEqual(cli.main(['check', d]), 2, 'no .kicad_pro')
        with self.assertRaises(SystemExit):
            with mock.patch('sys.stderr'):
                cli.main(['check', d, '--stock-multiple', '0'])

    def test_an_explicit_kicad_cli_that_does_not_exist_is_an_error(self):
        with self.assertRaises(kicad.KicadError):
            kicad.find_cli('/nonexistent/kicad-cli')
        with mock.patch.dict(os.environ, {'KICAD_CLI': '/nonexistent/kicad-cli'}):
            with self.assertRaises(kicad.KicadError):
                kicad.find_cli(None)

    def test_snapshot_drops_custom_rules_and_can_be_repeated(self):
        src, work = tempfile.mkdtemp(), tempfile.mkdtemp()
        write(src, 'demo.kicad_pro', '{}')
        write(src, 'demo.kicad_dru', '(version 1)')
        dst = cli.snapshot(src, work)
        self.assertTrue(os.path.exists(os.path.join(dst, 'demo.kicad_pro')))
        self.assertFalse(os.path.exists(os.path.join(dst, 'demo.kicad_dru')))
        self.assertEqual(cli.snapshot(src, work), dst, 'a second run into the same --keep-work dir replaces the copy')


if __name__ == '__main__':
    unittest.main()
