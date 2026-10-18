"""The price-tier tables (preset.TIERS): ordered from the standard option downward, typed, and sourced."""
import datetime
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import preset  # noqa: E402


def numbers(value):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from numbers(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from numbers(v)


class Sourced(unittest.TestCase):
    def test_every_source_is_a_jlcpcb_url_with_a_read_date(self):
        self.assertTrue(preset.TIERS_SOURCES)
        for key, (url, read) in preset.TIERS_SOURCES.items():
            self.assertTrue(url.startswith('https://') and 'jlcpcb.com' in url, key)
            self.assertEqual(datetime.date.fromisoformat(read).isoformat(), read, key)

    def test_every_table_names_known_sources_a_unit_and_rows(self):
        self.assertEqual(set(preset.TIERS), {'via', 'hole', 'layers', 'size', 'assembly', 'copper_weight', 'trace_space', 'options'})
        for name, table in preset.TIERS.items():
            self.assertEqual(set(table), {'unit', 'source', 'rows'}, name)
            self.assertTrue(table['unit'], name)
            self.assertTrue(table['source'], name)
            for key in table['source']:
                self.assertIn(key, preset.TIERS_SOURCES, name)
            self.assertTrue(table['rows'], name)

    def test_read_date_is_the_sources_date(self):
        datetime.date.fromisoformat(preset.TIERS_READ)
        self.assertEqual({read for _, read in preset.TIERS_SOURCES.values()}, {preset.TIERS_READ})

    def test_no_dollar_amount_anywhere(self):
        self.assertIsNone(re.search(r'\$\s?\d', repr(preset.TIERS)))
        self.assertIsNone(re.search(r'\$\s?\d', repr(preset.TIERS_NOT_SOURCED)))

    def test_not_sourced_is_a_list_of_sentences(self):
        self.assertTrue(preset.TIERS_NOT_SOURCED)
        for item in preset.TIERS_NOT_SOURCED:
            self.assertIsInstance(item, str)
            self.assertGreater(len(item), 20)


class Typed(unittest.TestCase):
    def test_rows_are_dicts_of_numbers_strings_bools_and_none(self):
        for name, table in preset.TIERS.items():
            for row in table['rows']:
                self.assertIsInstance(row, dict, name)
                for key, value in row.items():
                    self.assertIsInstance(key, str, name)
                    if isinstance(value, str):
                        continue
                    self.assertIsInstance(value, (int, float, bool, dict, type(None)), (name, key))
                for n in numbers(row):
                    self.assertGreater(n, 0, (name, row))

    def test_a_tier_row_says_whether_it_is_the_standard_option_and_why_not(self):
        for name in ('via', 'hole', 'layers', 'size', 'copper_weight', 'trace_space', 'assembly'):
            rows = preset.TIERS[name]['rows']
            for row in rows:
                self.assertIsInstance(row['standard'], bool, name)
                self.assertIsInstance(row['condition'], str, name)
                if not row['standard']:
                    self.assertTrue(row['condition'], (name, row))
            self.assertTrue(rows[0]['standard'], name)      # the standard option comes first

    def test_options_say_priced_and_detectable(self):
        for row in preset.TIERS['options']['rows']:
            self.assertIn(row['priced'], (True, False, None), row['option'])
            self.assertTrue(row['detectable'], row['option'])
            self.assertTrue(row['condition'], row['option'])

    def test_assembly_rows_say_what_the_files_can_see(self):
        for row in preset.TIERS['assembly']['rows']:
            self.assertTrue(row['driver'] and row['tier'] and row['detectable'], row)
            self.assertRegex(row['detectable'], r'^(yes|no|partly|online only|castellated|the stackup)')


class Ordered(unittest.TestCase):
    def test_via_tiers_run_from_the_standard_hole_down_and_follow_the_diameter_rule(self):
        rows = preset.VIA_TIERS
        holes = [r['min_hole'] for r in rows]
        self.assertEqual(holes, sorted(holes, reverse=True))
        self.assertEqual(len(set(holes)), len(holes))
        self.assertEqual([r['standard'] for r in rows], [True] + [False] * (len(rows) - 1))
        for r in rows:
            self.assertAlmostEqual(r['min_diameter'], r['min_hole'] + 0.10, places=6, msg=r['option'])
            self.assertAlmostEqual(r['preferred_diameter'], r['min_hole'] + 0.15, places=6, msg=r['option'])
            self.assertIn(f"{r['min_hole']:g}mm/", r['option'])
        smallest = rows[-1]
        self.assertEqual(smallest['min_hole'], 0.10)
        for word in ('ENIG', 'OSP', '1.0 mm'):
            self.assertIn(word, smallest['condition'])

    def test_hole_tiers_keep_todays_floor_and_record_the_priced_hole_below_it(self):
        rows = preset.HOLE_TIERS
        drills = [r['min_drill'] for r in rows]
        self.assertEqual(drills, sorted(drills, reverse=True))
        self.assertEqual(rows[0]['min_drill'], preset.MINIMUMS_COMMON['min_through_hole_diameter'])
        self.assertEqual(preset.minimums(2)['min_through_hole_diameter'], 0.15)     # the floor is not moved in this task
        self.assertLess(rows[-1]['min_drill'], preset.MINIMUMS_COMMON['min_through_hole_diameter'])
        self.assertIn('ENIG', rows[-1]['condition'])
        self.assertEqual(rows[-1]['min_drill'], preset.VIA_TIERS[-1]['min_hole'])
        self.assertLess(preset.HOLE_TIERS[0]['min_drill'], preset.HOLE_ONE_LAYER_MIN)
        self.assertLess(preset.HOLE_ONE_LAYER_MIN, preset.HOLE_NPTH_MIN)

    def test_layer_tiers_ascend_and_cover_every_layer_count(self):
        caps = [r['max_layers'] for r in preset.LAYER_TIERS]
        self.assertEqual(caps, sorted(caps))
        self.assertEqual(caps[0], 2)
        self.assertEqual(caps[-1], 32)
        self.assertEqual([r['standard'] for r in preset.LAYER_TIERS], [True, False, False])

    def test_size_tiers_start_at_the_hundred_millimetre_class(self):
        first, larger = preset.SIZE_TIERS
        self.assertEqual((first['max_x'], first['max_y']), (100.0, 100.0))
        self.assertIsNone(larger['max_x'])
        self.assertIsNone(larger['max_y'])
        for layers, (x, y) in preset.SIZE_MAX_BY_LAYERS.items():
            self.assertGreater(x, 100)
            self.assertGreater(y, 100)
            self.assertIn(layers, (1, 2, 4, 6))

    def test_quantity_minimums(self):
        q = preset.QUANTITY
        self.assertEqual((q['pcb_min'], q['assembly_min']), (5, 2))
        self.assertLess(q['economic_max_some_finishes'], q['economic_max'])

    def test_copper_weight_tiers_match_the_floor_and_widen_with_weight(self):
        one, two = preset.COPPER_WEIGHT_TIERS
        self.assertEqual((one['outer_oz'], two['outer_oz']), (1.0, 2.0))
        for layers, (track, space) in one['min_track_space'].items():
            self.assertEqual(track, preset.MINIMUMS_BY_LAYERS[layers]['min_track_width'])
            self.assertEqual(space, preset.MINIMUMS_BY_LAYERS[layers]['min_clearance'])
            self.assertGreater(two['min_track_space'][layers][0], track)
            self.assertGreater(two['min_track_space'][layers][1], space)

    def test_trace_space_is_the_floor_and_not_a_priced_option(self):
        two, multi = preset.TRACE_SPACE_TIERS
        self.assertEqual((two['min_track'], two['min_space']), (0.10, 0.10))
        self.assertEqual((multi['min_track'], multi['min_space']), (0.09, 0.09))
        for row in (two, multi):
            self.assertTrue(row['standard'])
            self.assertIn('no quote-page option', row['condition'])

    def test_assembly_tiers_start_single_sided_and_name_the_known_drivers(self):
        rows = preset.ASSEMBLY_TIERS
        self.assertEqual(rows[0]['tier'], 'Economic PCBA')
        drivers = ' '.join(r['driver'] for r in rows)
        for word in ('double-sided', 'through-hole', 'Extended part', '0402', 'castellated', 'V-cut'):
            self.assertIn(word, drivers)
        self.assertEqual(sum(r['standard'] for r in rows), 1)


if __name__ == '__main__':
    unittest.main()
