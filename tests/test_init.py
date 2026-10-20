"""`preflight bom` (init.py): fields read, grouping, the merge rules, note carry-over and drop, open lines, determinism, exit codes."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import bom as bomlib, catalogue, cli, init, stock  # noqa: E402

CAT = {
    'C14663': {'source': 'jlcpcb', 'fetched_at': '2026-10-18', 'cached': False, 'lcsc': 'C14663', 'mpn': 'CC0603KRX7R9BB104', 'manufacturer': 'YAGEO',
               'package': '0603', 'library': 'Basic', 'stock': 49456457, 'datasheet': 'https://x/C14663.pdf', 'description': '100nF 50V X7R 0603'},
    'C1588': {'source': 'jlcpcb', 'fetched_at': '2026-10-18', 'cached': False, 'lcsc': 'C1588', 'mpn': 'CL10B102KB8NNNC', 'manufacturer': 'Samsung',
              'package': '0603', 'library': 'Basic', 'stock': 6226095, 'datasheet': 'https://x/C1588.pdf', 'description': '1nF 50V X7R 0603'},
    'C72477': {'source': 'jlcpcb', 'fetched_at': '2026-10-18', 'cached': False, 'lcsc': 'C72477', 'mpn': 'RVT1E101M0607', 'manufacturer': 'ROQANG',
               'package': 'SMD,D6.3xL7.7mm', 'library': 'Extended', 'stock': 106193, 'datasheet': 'https://x/C72477.pdf', 'description': '100uF 25V'},
    'C3819953': {'source': 'jlcpcb', 'fetched_at': '2026-10-18', 'cached': False, 'lcsc': 'C3819953', 'mpn': '1935161', 'manufacturer': 'Phoenix Contact',
                 'package': 'Plugin,P=5mm', 'library': 'Extended', 'stock': 468, 'datasheet': 'https://x/1935161.pdf', 'description': ''},
}


def lookup(code):
    if code == 'C404':
        return None
    if code == 'C500':
        raise stock.LookupFailed('jlcpcb: timed out')
    return dict(CAT[code])


def sym(ref, value, fp, **fields):
    r = {'Ref': ref, 'Value': value, 'Footprint': fp, 'DNP': False, 'ExcludeFromBOM': False, 'ExcludeFromBoard': False}
    r.update(fields)
    return r


ROWS = [
    sym('C1', '100nF', 'Capacitor_SMD:C_0603_1608Metric', LCSC='C14663'),
    sym('C7', '100nF', 'Capacitor_SMD:C_0603_1608Metric', **{'LCSC Part #': 'c14663'}),
    sym('C10', '100nF', 'Capacitor_SMD:C_0603_1608Metric', LCSC='C14663'),
    sym('C65', '1nF', 'Capacitor_SMD:C_0603_1608Metric', LCSC='C1588'),
    sym('C4', '100uF 25V', 'Capacitor_SMD:CP_Elec_6.3x7.7', LCSC='C72477'),
    sym('C5', '100uF 16V', 'Capacitor_SMD:CP_Elec_6.3x7.7', LCSC='C72477'),
    sym('J1', 'J_IN', 'TerminalBlock:PT_1x02_P5.00mm', LCSC='C3819953'),
    sym('J2', 'J_PICO', 'TerminalBlock:PT_1x02_P5.00mm', LCSC='C3819953'),
    sym('L3', '15uH', 'Inductor_SMD:L_Bourns_SRP1245A', MPN='SRP1245A-150M', Manufacturer='Bourns'),
    sym('TP1', 'TP', 'TestPoint:TestPoint_Pad', LCSC='C1'),
    dict(sym('D1', 'SMF3.3A', 'Diode_SMD:D_SOD-123', LCSC='C1'), DNP=True),
]


def load(text):
    f = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, newline='', encoding='utf-8')
    f.write(text)
    f.close()
    return bomlib.load(f.name)[0]


class Fields(unittest.TestCase):
    def test_every_spelling_has_a_source_and_feeds_a_known_column(self):
        for spelling, column, source in init.FIELDS:
            self.assertIn(column, ('LCSC', 'MPN', 'Manufacturer'), spelling)
            self.assertTrue(source, spelling)
        self.assertEqual(len(set(init.field_names())), len(init.FIELDS))
        for s in ('LCSC', 'LCSC Part #', 'LCSC Part', 'lcsc#', 'JLC'):
            self.assertIn(s, init.field_names(), 'the corpus spellings')
        for spelling, _, source in init.FIELDS:
            self.assertTrue(source.startswith(('corpus:', 'KiCad', 'kicad-jlcpcb-tools', 'Fabrication Toolkit', 'JLCPCB KiCad Library')) or 'corpus:' in source,
                            f'{spelling}: a spelling needs a corpus board or the tool that writes it, not a guess ({source})')
        for s in ('LCSC_PART', 'JLCPCB Part #', 'JLCPCB', 'Mfr. Part #', 'Mfr'):
            self.assertNotIn(s, init.field_names(), 'dropped 2026-10-20: no corpus board, no tool')

    def test_first_spelling_wins_and_a_conflict_is_reported(self):
        fields, conflicts = init.read_fields({'LCSC': 'c14663 ', 'LCSC Part': 'C1588', 'MPN': 'X'})
        self.assertEqual(fields['LCSC'], ('C14663', 'LCSC'))
        self.assertEqual(fields['MPN'], ('X', 'MPN'))
        self.assertEqual(conflicts, ['field LCSC Part says C1588, field LCSC says C14663; LCSC kept'])
        self.assertEqual(init.read_fields({'LCSC': 'C14663', 'LCSC Part': 'C14663'})[1], [], 'the same code twice is not a conflict')

    def test_codes_from_fields(self):
        self.assertEqual(init.codes_from_fields(ROWS)['C7'], 'C14663')
        self.assertNotIn('L3', init.codes_from_fields(ROWS))


class Build(unittest.TestCase):
    def test_grouping_order_and_columns(self):
        r = init.build(ROWS, [], lookup)
        refs = [ln['Ref'] for ln in r['lines']]
        self.assertEqual(refs, ['C1,C7,C10', 'C4', 'C5', 'C65', 'J1', 'J2', 'L3'], 'one line per (code, value, footprint), by first reference, naturally sorted')
        self.assertEqual(r['columns'], bomlib.COLUMNS)
        c1 = r['lines'][0]
        self.assertEqual((c1['Package'], c1['MPN'], c1['Manufacturer'], c1['LCSC'], c1['Basic/Extended'], c1['Stock'], c1['Datasheet'], c1['Fetched']),
                         ('0603', 'CC0603KRX7R9BB104', 'YAGEO', 'C14663', 'Basic', '49456457', 'https://x/C14663.pdf', 'jlcpcb 2026-10-18'))
        self.assertEqual(c1['Value'], '100nF', 'the schematic\'s Value, not the description')
        self.assertEqual(r['fields'], {'LCSC': 7, 'LCSC Part #': 1})
        self.assertNotIn('TP1', refs[-1], 'skipped prefixes and DNP symbols are not bought')
        self.assertEqual(r['written'], 6)

    def test_a_line_without_a_code_is_open_with_the_footprint_name_and_the_symbols_own_mpn(self):
        r = init.build(ROWS, [], lookup)
        l3 = r['lines'][-1]
        self.assertEqual((l3['Ref'], l3['Package'], l3['LCSC'], l3['MPN'], l3['Manufacturer'], l3['Basic/Extended'], l3['Stock'], l3['Fetched']),
                         ('L3', 'L_Bourns_SRP1245A', '', 'SRP1245A-150M', 'Bourns', '', '', ''))
        self.assertEqual(r['open'], ['L3 (15uH, L_Bourns_SRP1245A)'])
        self.assertEqual(init.verdict(r), ('INCOMPLETE', 3, ['1 line without a code']))

    def test_field_code_wins_over_a_differing_line_code_and_the_change_is_printed(self):
        old = load('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet\nC65,1nF,0603,OLDPART,C14663,Basic,1,u\n')
        r = init.build(ROWS, old, lookup)
        c65 = [ln for ln in r['lines'] if ln['Ref'] == 'C65'][0]
        self.assertEqual(c65['LCSC'], 'C1588')
        self.assertIn('C65: the schematic field says C1588, bom.csv (row 2) had C14663; the field wins', r['changed'])

    def test_a_hand_entered_code_is_kept_where_the_symbol_has_no_field(self):
        old = load('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet\nL3,15uH,L_Bourns_SRP1245A,,C3819953,,,\n')
        r = init.build(ROWS, old, lookup)
        l3 = [ln for ln in r['lines'] if ln['Ref'] == 'L3'][0]
        self.assertEqual((l3['LCSC'], l3['MPN']), ('C3819953', '1935161'))
        self.assertEqual(r['open'], [])
        self.assertEqual(init.verdict(r)[0], 'COMPLETE')

    def test_a_typed_mpn_the_catalogue_spells_otherwise_is_a_printed_change(self):
        old = load('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet\nC5,100uF 16V,"SMD,D6.3xL7.7mm",RVT1E101M0607-T,C72477,Extended,1,u\n')
        r = init.build(ROWS, old, lookup)
        self.assertIn('C5: catalogue MPN RVT1E101M0607 replaces the typed RVT1E101M0607-T (same code C72477)', r['changed'])

    def test_note_carried_over_when_refs_code_and_package_string_hold(self):
        old = load('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet,Package verified,Reviewer\n'
                   'J1,J_IN,"Plugin,P=5mm",1935161,C3819953,Extended,468,u,2026-10-16 BD: drawing vs PT footprint,BD\n'
                   '"C10,C1,C7",100nF,C_0603_1608Metric,,C14663,,,,2026-10-16 BD: 0603 pads,\n')
        r = init.build(ROWS, old, lookup)
        j = [ln for ln in r['lines'] if ln['Ref'] == 'J1'][0]
        self.assertEqual(j['Package verified'], '2026-10-16 BD: drawing vs PT footprint')
        self.assertEqual(j['Reviewer'], 'BD', 'an extra column is kept per line')
        self.assertEqual(r['columns'][-1], 'Reviewer')
        c = [ln for ln in r['lines'] if ln['Ref'] == 'C1,C7,C10'][0]
        self.assertEqual(c['Package verified'], '2026-10-16 BD: 0603 pads', 'a placeholder Package (the footprint name) is the same footprint')
        self.assertEqual(sorted(r['kept']), ['C1,C7,C10', 'J1'])
        self.assertEqual(r['dropped'], [])

    def test_note_dropped_and_printed_when_refs_or_code_change(self):
        old = load('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet,Package verified\n'
                   '"J1,J2,J3",J_IN,"Plugin,P=5mm",1935161,C3819953,Extended,468,u,note A\n'
                   'C65,1nF,0603,X,C14663,Basic,1,u,note B\n'
                   'C4,100uF 25V,"SMD,D6.3xL7.7mm",RVT1E101M0607,C72477,Extended,1,u,note C\n'
                   'C99,1uF,0603,X,C1,Basic,1,u,note D\n')
        r = init.build(ROWS, old, lookup)
        self.assertEqual([ln['Package verified'] for ln in r['lines'] if ln['Ref'] in ('J1', 'J2', 'C65')], ['', '', ''])
        self.assertEqual([ln['Package verified'] for ln in r['lines'] if ln['Ref'] == 'C4'], ['note C'])
        joined = '\n'.join(r['dropped'])
        self.assertIn('J1,J2,J3: "note A" dropped: references changed (J1,J2,J3 -> J1)', joined)
        self.assertIn('C65: "note B" dropped: code changed (C14663 -> C1588)', joined)
        self.assertIn('C99: "note D" dropped: no longer a bought reference', joined)
        self.assertEqual(len(r['dropped']), 3, 'a note is judged once, against the first line its references land on')
        self.assertEqual(r['kept'], ['C4'])

    def test_note_dropped_when_the_catalogue_package_string_changed(self):
        old = load('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet,Package verified\n'
                   'J1,J_IN,"Plugin,P=5.08mm",1935161,C3819953,Extended,468,u,note A\n')
        r = init.build(ROWS, old, lookup)
        self.assertIn('catalogue package string changed ("Plugin,P=5.08mm" -> "Plugin,P=5mm")', r['dropped'][0])

    def test_codes_the_catalogue_cannot_answer_stay_open_and_keep_the_file_s_facts(self):
        rows = [sym('R1', '1k', 'Resistor_SMD:R_0603_1608Metric', LCSC='C404'), sym('R2', '2k', 'Resistor_SMD:R_0603_1608Metric', LCSC='C500'),
                sym('R3', '3k', 'Resistor_SMD:R_0603_1608Metric', LCSC='C500')]
        old = load('Ref,Value,Package,MPN,Manufacturer,LCSC,Basic/Extended,Stock,Datasheet,Fetched\n'
                   'R2,2k,0603,0603WAF2001T5E,UNI-ROYAL,C500,Basic,100,u,jlcpcb 2026-10-01\n')
        r = init.build(rows, old, lookup)
        r1, r2, r3 = r['lines']
        self.assertEqual((r1['LCSC'], r1['Package'], r1['MPN'], r1['Fetched']), ('C404', 'R_0603_1608Metric', '', ''))
        self.assertEqual((r2['LCSC'], r2['MPN'], r2['Stock'], r2['Fetched']), ('C500', '0603WAF2001T5E', '100', 'jlcpcb 2026-10-01'), 'kept as written, with its own date')
        self.assertEqual((r3['LCSC'], r3['MPN'], r3['Fetched']), ('C500', '', ''))
        self.assertEqual(len(r['open_codes']), 3)
        self.assertIn('C404 is not in the JLCPCB catalogue', r['open_codes'][0])
        self.assertIn('C500 not answered (jlcpcb: timed out); facts kept from bom.csv as written (jlcpcb 2026-10-01)', r['open_codes'][1])
        self.assertEqual(r['missing'], ['C404'])
        self.assertEqual(init.verdict(r), ('INCOMPLETE', 3, ['3 codes without a record']))

    def test_no_fields_read_is_the_old_template(self):
        r = init.build(ROWS, [], lookup, read=False)
        self.assertEqual(r['written'], 0)
        self.assertEqual(len(r['open']), 7)
        self.assertTrue(all(ln['LCSC'] == '' and ln['Fetched'] == '' for ln in r['lines']))
        self.assertEqual([ln['Package'] for ln in r['lines']][:2], ['C_0603_1608Metric', 'CP_Elec_6.3x7.7'])


class WriteAndReport(unittest.TestCase):
    def test_same_inputs_same_bytes(self):
        d = tempfile.mkdtemp()
        old = load('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet,Package verified\nJ1,J_IN,"Plugin,P=5mm",1935161,C3819953,Extended,468,u,note\n')
        outs = []
        for i in range(2):
            p = os.path.join(d, f'{i}.csv')
            init.write(p, init.build(list(reversed(ROWS)) if i else ROWS, old, lookup))
            with open(p, 'rb') as f:
                outs.append(f.read())
        self.assertEqual(outs[0], outs[1], 'symbol order in the export does not change the file')
        self.assertNotIn(b'\r', outs[0])
        self.assertTrue(outs[0].startswith(b'Ref,Value,Package,MPN,Manufacturer,LCSC,Basic/Extended,Stock,Datasheet,Fetched,Package verified\n'))
        lines, missing = bomlib.load(os.path.join(d, '0.csv'))
        self.assertEqual(missing, [], 'what bom writes, check reads')
        self.assertEqual(lines[0].fetched, 'jlcpcb 2026-10-18')
        self.assertEqual(lines[0].manufacturer, 'YAGEO')

    def test_report_format(self):
        old = load('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet,Package verified\nJ1,J_IN,"Plugin,P=5mm",1935161,C3819953,Extended,468,u,note\n'
                   'C5,100uF 16V,x,RVT1E101M0607-T,C72477,Extended,1,u,\n')
        r = init.build(ROWS, old, lookup)
        text = init.report('demo', r, 'jlcpcb 2026-10-18 (4 codes fetched)', '/p/bom.csv')
        lines = text.splitlines()
        self.assertEqual(lines[0], 'preflight bom: demo  -  7 lines  -  jlcpcb 2026-10-18 (4 codes fetched)')
        self.assertIn('  fields    codes from LCSC (7), LCSC Part # (1)', lines)
        self.assertIn('  written   6 lines from the catalogue record of their code', lines)
        self.assertIn('  kept      1 "Package verified" note (J1); 0 dropped', lines)
        self.assertIn("  open      1 line without a code: open each part on jlcpcb.com and put its C-number in the symbol's LCSC field, then run preflight bom again", lines)
        self.assertIn('            L3 (15uH, L_Bourns_SRP1245A)', lines)
        self.assertIn('            C5: catalogue MPN RVT1E101M0607 replaces the typed RVT1E101M0607-T (same code C72477)', lines)
        self.assertIn('            C5: catalogue package "SMD,D6.3xL7.7mm" replaces "x" (same code C72477)', lines)
        self.assertEqual(lines[-1], 'RESULT: INCOMPLETE  -  1 line without a code  -  exit 3')
        complete = init.build([ROWS[0]], [], lookup)
        self.assertTrue(init.report('demo', complete, 's', '/p').endswith('RESULT: COMPLETE  -  every line has a code and a record  -  exit 0'))


class Command(unittest.TestCase):
    """The command end to end with kicad-cli and the catalogue faked: exit codes, the file, --json, --quiet, the aliases."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, 'demo.kicad_pro'), 'w') as f:
            f.write('{}')
        with open(os.path.join(self.d, 'demo.kicad_sch'), 'w') as f:
            f.write('(kicad_sch)')
        self.cache = os.path.join(self.d, 'cache.json')
        self.env = mock.patch.dict(os.environ, {'PCB_PREFLIGHT_CACHE': self.cache})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.patches = [mock.patch('pcb_preflight.kicad.find_cli', return_value='/fake/kicad-cli'),
                        mock.patch('pcb_preflight.kicad.bom', side_effect=lambda cli, sch, out, fields=(): [dict(r) for r in ROWS]),
                        mock.patch('pcb_preflight.stock.lookup', side_effect=lookup)]
        self.mocks = []
        for p in self.patches:
            self.mocks.append(p.start())
            self.addCleanup(p.stop)

    def run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch('sys.stderr', new_callable=io.StringIO):
            code = cli.main(argv)
        return code, buf.getvalue()

    def test_bom_writes_the_file_and_exits_3_while_a_line_is_open(self):
        out = os.path.join(self.d, 'out', 'bom.csv')
        code, text = self.run_cli(['bom', self.d, '--bom', out, '--json', os.path.join(self.d, 'r.json')])
        self.assertEqual(code, 3)
        self.assertTrue(os.path.exists(out))
        self.assertIn('RESULT: INCOMPLETE  -  1 line without a code  -  exit 3', text)
        self.assertTrue(os.path.exists(self.cache), 'the fetched records are cached')
        import json
        with open(os.path.join(self.d, 'r.json'), encoding='utf-8') as f:
            j = json.load(f)
        self.assertEqual((j['result'], j['exit_code'], j['written'], len(j['lines'])), ('INCOMPLETE', 3, 6, 7))
        self.assertEqual(j['fields'], {'LCSC': 7, 'LCSC Part #': 1})
        # second run: served from the cache, same bytes
        with open(out, 'rb') as f:
            first = f.read()
        code, text = self.run_cli(['init', self.d, '--bom', out, '--quiet'])
        self.assertEqual(code, 3)
        self.assertEqual(text.strip(), 'RESULT: INCOMPLETE  -  1 line without a code  -  exit 3')
        with open(out, 'rb') as f:
            self.assertEqual(f.read(), first)
        self.assertEqual(self.mocks[2].call_count, 4, 'four codes fetched once; the second run asked the network nothing')

    def test_offline_without_a_cache_leaves_every_code_open(self):
        out = os.path.join(self.d, 'bom.csv')
        code, text = self.run_cli(['bom', self.d, '--bom', out, '--offline'])
        self.assertEqual(code, 3)
        self.assertIn('offline (cache only)', text)
        self.assertIn('6 codes without a catalogue record', text)
        self.assertIn('not in the cache', text)

    def test_complete_exits_0(self):
        rows = [r for r in ROWS if r['Ref'] != 'L3']
        with mock.patch('pcb_preflight.kicad.bom', side_effect=lambda cli, sch, out, fields=(): [dict(r) for r in rows]):
            code, text = self.run_cli(['bom', self.d, '--bom', os.path.join(self.d, 'bom.csv')])
        self.assertEqual(code, 0)
        self.assertIn('RESULT: COMPLETE', text)

    def test_bom_template_is_the_offline_fieldless_alias(self):
        out = os.path.join(self.d, 't.csv')
        code, text = self.run_cli(['bom-template', self.d, '-o', out, '--force'])
        self.assertEqual(code, 3)
        self.assertIn('fields    not read (bom-template)', text)
        lines, _ = bomlib.load(out)
        self.assertEqual(len(lines), 7)
        self.assertTrue(all(ln.lcsc == '' for ln in lines))
        self.assertFalse(os.path.exists(self.cache), 'no network, nothing cached')

    def test_a_non_utf8_bom_is_an_error_exit_2(self):
        out = os.path.join(self.d, 'bom.csv')
        with open(out, 'wb') as f:
            f.write('Ref,Value,Package,MPN,LCSC,Basic/Extended,Stock,Datasheet\nC1,100nF,0603,,C14663,,,\xb5\n'.encode('latin-1'))
        code, text = self.run_cli(['bom', self.d, '--bom', out])
        self.assertEqual(code, 2)
        with open(out, 'rb') as f:
            self.assertIn(b'\xb5', f.read(), 'the file was not touched')


if __name__ == '__main__':
    unittest.main()
