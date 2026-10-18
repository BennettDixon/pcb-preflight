"""The price-tier tables behind the ORDER section (preset.TIERS): sourced, dated, ordered, and never a price."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import preset  # noqa: E402

DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class Sources(unittest.TestCase):
    def test_every_source_is_a_jlcpcb_url_with_a_read_date(self):
        for key, (url, date) in preset.TIERS_SOURCES.items():
            self.assertTrue(url.startswith('https://') and 'jlcpcb.com' in url, key)
            self.assertRegex(date, DATE)
        self.assertRegex(preset.TIERS_READ, DATE)

    def test_every_table_names_known_sources_a_unit_and_rows(self):
        for name, table in preset.TIERS.items():
            self.assertEqual(set(table), {'unit', 'source', 'rows'}, name)
            self.assertTrue(table['source'] and all(s in preset.TIERS_SOURCES for s in table['source']), name)
            self.assertTrue(table['rows'], name)
            self.assertTrue(table['rows'][0]['standard'], f'{name}: the first row is the standard option')
            for row in table['rows']:
                self.assertIn('condition', row, name)
                self.assertTrue(row['standard'] or row['condition'], f'{name}: a priced row says why')

    def test_not_sourced_is_a_list_of_sentences(self):
        self.assertTrue(preset.TIERS_NOT_SOURCED)
        for s in preset.TIERS_NOT_SOURCED:
            self.assertTrue(len(s) > 20 and 'not' in s or 'surcharge' in s or 'options' in s or 'edge' in s, s)


class NoPrices(unittest.TestCase):
    def test_no_dollar_amount_or_multiplier_anywhere(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'pcb_preflight', 'preset.py'), encoding='utf-8').read()
        block = src[src.index('TIERS_READ ='):]
        self.assertNotRegex(block, r'[$€£]\s?\d')
        self.assertNotRegex(block, r'\b\d+(\.\d+)?\s?(USD|EUR|dollars?)\b')
        for word in ('twice', 'times the', 'x the price', 'cheaper', 'discount'):
            self.assertNotIn(word, block, f'a relative price is still a price: {word!r}')

    def test_no_suggestions(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'pcb_preflight', 'preset.py'), encoding='utf-8').read()
        block = src[src.index('TIERS_READ ='):]
        for word in ('you should', 'consider using', 'to save', 'recommend'):
            self.assertNotIn(word, block.lower(), word)


class Vias(unittest.TestCase):
    def test_tiers_run_from_the_standard_hole_down_and_follow_the_diameter_rule(self):
        rows = preset.TIERS['via']['rows']
        holes = [r['min_hole'] for r in rows]
        self.assertEqual(holes, sorted(holes, reverse=True))
        self.assertEqual((holes[0], holes[-1]), (0.30, 0.10))
        self.assertTrue(rows[0]['standard'] and not any(r['standard'] for r in rows[1:]))
        for r in rows:
            self.assertAlmostEqual(r['min_diameter'] - r['min_hole'], 0.10, places=6, msg=r['option'])
            self.assertAlmostEqual(r['preferred_diameter'] - r['min_hole'], 0.15, places=6, msg=r['option'])
        self.assertIn('1.0 mm or less', rows[-1]['condition'])
        self.assertIn('ENIG or OSP', rows[-1]['condition'])

    def test_hole_tiers_keep_todays_floor_and_record_the_priced_hole_below_it(self):
        rows = preset.TIERS['hole']['rows']
        self.assertEqual([r['min_drill'] for r in rows], [0.15, 0.10])
        self.assertEqual(rows[0]['min_drill'], preset.MINIMUMS_COMMON['min_through_hole_diameter'], 'the floor is still the standard drill in this commit')
        self.assertEqual(rows[-1]['min_drill'], preset.TIERS['via']['rows'][-1]['min_hole'])
        self.assertIn('more costly', rows[-1]['condition'])


class LayersSizeAssembly(unittest.TestCase):
    def test_layer_tiers_ascend_and_cover_every_layer_count(self):
        rows = preset.TIERS['layers']['rows']
        maxes = [r['max_layers'] for r in rows]
        self.assertEqual(maxes, sorted(maxes))
        self.assertEqual(maxes[0], 2)
        self.assertGreaterEqual(maxes[-1], 32)
        for r in rows[1:]:
            self.assertIn('class', r['condition'], 'a class, not a multiplier')

    def test_size_tiers_start_at_the_hundred_millimetre_class(self):
        rows = preset.TIERS['size']['rows']
        self.assertEqual((rows[0]['max_x'], rows[0]['max_y'], rows[0]['standard']), (100.0, 100.0, True))
        self.assertIsNone(rows[-1]['max_x'])

    def test_assembly_minimum(self):
        self.assertEqual(preset.ASSEMBLY_MIN, 2)

    def test_assembly_rows_are_all_readable_from_the_files(self):
        rows = preset.TIERS['assembly']['rows']
        self.assertTrue(rows[0]['standard'] and rows[0]['driver'] == 'single-sided placement')
        drivers = {r['driver'] for r in rows}
        for d in ('double-sided placement', 'through-hole parts', 'Extended part', 'castellated holes', 'edge plating', 'impedance control'):
            self.assertIn(d, drivers)
        for r in rows:
            self.assertTrue(r['detectable'].startswith('yes'), f"{r['driver']}: a driver the files cannot show is not a driver")
            self.assertTrue(r['tier'] and r['condition'])
        self.assertFalse(any('0402' in r['driver'] or '70' in r['driver'] or 'V-cut' in r['driver'] for r in rows))

    def test_copper_weight_tiers_match_the_floor_and_widen_with_weight(self):
        one, two = preset.TIERS['copper_weight']['rows']
        self.assertEqual((one['outer_oz'], one['standard']), (1.0, True))
        self.assertEqual(one['min_track_space'][2][0], preset.MINIMUMS_BY_LAYERS[2]['min_track_width'])
        self.assertEqual(one['min_track_space'][4][0], preset.MINIMUMS_BY_LAYERS[4]['min_track_width'])
        self.assertGreater(two['min_track_space'][2][0], one['min_track_space'][2][0])

    def test_not_in_files_names_what_the_quote_page_prices_beside_the_files(self):
        for name in ('copper weight', 'quantity', 'gold fingers'):
            self.assertTrue(any(name in x for x in preset.NOT_IN_FILES), name)
        self.assertNotIn('options', preset.TIERS, 'the quote-page options the files cannot show are names in NOT_IN_FILES, not tiers')


if __name__ == '__main__':
    unittest.main()
