"""catalogue.py: the cache, its limits, the parts.csv source, offline reading, and what `check` makes of cached facts."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pcb_preflight import catalogue, checks, report, stock  # noqa: E402
from pcb_preflight.bom import Line  # noqa: E402

REC = {'source': 'jlcpcb', 'lcsc': 'C14663', 'mpn': 'CC0603KRX7R9BB104', 'manufacturer': 'YAGEO', 'package': '0603',
       'library': 'Basic', 'stock': 49456457, 'datasheet': 'https://x/C14663.pdf', 'description': '100nF 50V X7R 0603', 'category': 'Capacitors'}


class Fetch:
    """A fake live client that counts its calls and can be switched off."""
    def __init__(self, rec=REC, fail=False):
        self.calls, self.rec, self.fail = [], rec, fail

    def __call__(self, code):
        self.calls.append(code)
        if self.fail:
            raise stock.LookupFailed('offline')
        return dict(self.rec, lcsc=code) if self.rec else None


class Cache(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), 'sub', 'catalogue.json')

    def test_a_fetch_is_written_and_read_back_within_the_stock_limit(self):
        f = Fetch()
        with catalogue.Catalogue(path=self.path, fetch=f, on='2026-10-18') as cat:
            rec = cat.lookup('C14663')
        self.assertEqual((rec['source'], rec['fetched_at'], rec['cached']), ('jlcpcb', '2026-10-18', False))
        self.assertTrue(catalogue.is_current(rec, on='2026-10-18'))
        self.assertEqual(catalogue.fetched_label(rec), 'jlcpcb 2026-10-18')
        with open(self.path, encoding='utf-8') as fh:
            d = json.load(fh)
        self.assertEqual(d['schema'], catalogue.SCHEMA)
        self.assertNotIn('cached', d['records']['C14663'], 'the file holds the record, not the run-time flag')
        cat2 = catalogue.Catalogue(path=self.path, fetch=f, on='2026-10-24')      # 6 days later: still within STOCK_DAYS
        rec2 = cat2.lookup('C14663')
        self.assertEqual(f.calls, ['C14663'], 'served from the cache, not fetched again')
        self.assertTrue(rec2['cached'])
        self.assertEqual(catalogue.fetched_label(rec2), 'jlcpcb 2026-10-18', 'same label as the live run: same bytes in bom.csv')
        self.assertEqual(catalogue.fetched_label(rec2, via=True), 'jlcpcb 2026-10-18 via the cache')
        self.assertFalse(catalogue.is_current(rec2, on='2026-10-24'), 'a cached record is never today\'s stock')
        self.assertEqual(cat2.counts['cache'], 1)

    def test_an_old_stock_figure_is_refetched_online(self):
        f = Fetch()
        with catalogue.Catalogue(path=self.path, fetch=f, on='2026-10-01') as cat:
            cat.lookup('C14663')
        with catalogue.Catalogue(path=self.path, fetch=f, on='2026-10-18') as cat:   # 17 days: past STOCK_DAYS
            rec = cat.lookup('C14663')
        self.assertEqual(f.calls, ['C14663', 'C14663'])
        self.assertEqual(rec['fetched_at'], '2026-10-18')
        self.assertEqual(cat.counts, {'fetched': 1, 'cache': 0, 'parts': 0, 'missing': 0, 'failed': 0})

    def test_refresh_ignores_a_fresh_record_and_rewrites_it(self):
        f = Fetch()
        with catalogue.Catalogue(path=self.path, fetch=f, on='2026-10-18') as cat:
            cat.lookup('C14663')
        with catalogue.Catalogue(path=self.path, fetch=f, on='2026-10-18', refresh=True) as cat:
            rec = cat.lookup('C14663')
        self.assertEqual(len(f.calls), 2)
        self.assertFalse(rec['cached'])

    def test_offline_serves_the_cache_up_to_the_identity_limit_and_nothing_else(self):
        f = Fetch()
        with catalogue.Catalogue(path=self.path, fetch=f, on='2026-07-01') as cat:
            cat.lookup('C14663')
        off = Fetch(fail=True)
        cat = catalogue.Catalogue(path=self.path, fetch=off, on='2026-09-01', offline=True)   # 62 days: identity still good
        rec = cat.lookup('C14663')
        self.assertEqual((rec['cached'], rec['fetched_at'], rec['mpn']), (True, '2026-07-01', 'CC0603KRX7R9BB104'))
        self.assertEqual(off.calls, [], 'offline never calls the network')
        with self.assertRaises(stock.LookupFailed) as e:
            cat.lookup('C99999')
        self.assertIn('not in the cache', str(e.exception))
        cat = catalogue.Catalogue(path=self.path, fetch=off, on='2026-10-18', offline=True)   # 109 days: too old even for identity
        with self.assertRaises(stock.LookupFailed) as e:
            cat.lookup('C14663')
        self.assertIn(f'older than {catalogue.IDENTITY_DAYS} days', str(e.exception))
        self.assertEqual(cat.counts['failed'], 1)

    def test_a_live_failure_falls_back_to_the_cache_labelled(self):
        with catalogue.Catalogue(path=self.path, fetch=Fetch(), on='2026-10-10') as cat:
            cat.lookup('C14663')
        cat = catalogue.Catalogue(path=self.path, fetch=Fetch(fail=True), on='2026-10-18')
        rec = cat.lookup('C14663')
        self.assertTrue(rec['cached'])
        with self.assertRaises(stock.LookupFailed) as e:
            cat.lookup('C1')
        self.assertIn('nothing in the cache', str(e.exception))

    def test_an_unknown_code_is_not_cached(self):
        f = Fetch(rec=None)
        with catalogue.Catalogue(path=self.path, fetch=f, on='2026-10-18') as cat:
            self.assertIsNone(cat.lookup('C1'))
        self.assertFalse(os.path.exists(self.path), 'nothing to write: None is not a record')
        self.assertEqual(cat.counts['missing'], 1)

    def test_an_unreadable_cache_file_is_an_empty_cache(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'w') as fh:
            fh.write('not json')
        cat = catalogue.Catalogue(path=self.path, fetch=Fetch(), on='2026-10-18')
        self.assertEqual(cat.records, {})
        self.assertEqual(cat.lookup('C14663')['mpn'], 'CC0603KRX7R9BB104')

    def test_env_and_default_path(self):
        with mock.patch.dict(os.environ, {'PCB_PREFLIGHT_CACHE': '/tmp/x/c.json'}):
            self.assertEqual(catalogue.cache_path(), '/tmp/x/c.json')
            self.assertEqual(catalogue.cache_path('/tmp/y.json'), '/tmp/y.json', 'an explicit path wins')
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(catalogue.cache_path().endswith(os.path.join('.cache', 'pcb-preflight', 'catalogue.json')))

    def test_summary_line(self):
        f = Fetch()
        cat = catalogue.Catalogue(path=self.path, fetch=f, on='2026-10-18')
        cat.lookup('C1')
        cat.lookup('C1')
        self.assertEqual(cat.summary(), 'jlcpcb 2026-10-18 (1 codes fetched, 1 from cache)')
        self.assertEqual(catalogue.Catalogue(path=self.path, offline=True).summary(), 'offline (cache only) (nothing looked up)')


class PartsFile(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.path = os.path.join(d, 'catalogue.json')
        self.parts = os.path.join(d, 'parts.csv')
        with open(self.parts, 'w', encoding='utf-8') as fh:
            fh.write('LCSC,MPN,Manufacturer,Package,Library,Stock,Description,Datasheet,fetched_at\n'
                     'C2042471,SRP1245A-100M,Bourns,"SMD,13.5x12.5mm",extended,"20",10uH shielded,https://x/srp.pdf,2026-10-01\n'
                     ',,,,,,,,\n')

    def test_parts_file_is_consulted_first_and_labelled(self):
        f = Fetch()
        cat = catalogue.Catalogue(path=self.path, parts=self.parts, fetch=f, on='2026-10-18')
        rec = cat.lookup('C2042471')
        self.assertEqual(f.calls, [])
        self.assertEqual((rec['source'], rec['library'], rec['stock'], rec['fetched_at']), ('parts.csv', 'Extended', 20, '2026-10-01'))
        self.assertEqual(catalogue.fetched_label(rec), 'parts.csv 2026-10-01')
        self.assertFalse(catalogue.is_current(rec, on='2026-10-18'), 'a figure dated 17 days ago is not today\'s stock')
        other = cat.lookup('C14663')
        self.assertEqual(f.calls, ['C14663'], 'codes the file does not have go to the catalogue')
        self.assertEqual(other['source'], 'jlcpcb')
        self.assertIn('1 from parts.csv', cat.summary())

    def test_parts_file_rows_without_a_code_are_skipped(self):
        self.assertEqual(list(catalogue.load_parts(self.parts)), ['C2042471'])


class CheckWithCachedFacts(unittest.TestCase):
    """The stock gate on records that are not today's: unchecked, labelled, never a pass (design decision 4)."""

    def lines(self):
        return [Line(row=2, refs=['C1', 'C7'], package='0603', lcsc='C14663', mpn='CC0603KRX7R9BB104', library='Basic', fetched='jlcpcb 2026-10-11')]

    def test_cached_facts_are_unchecked_and_say_where_they_came_from(self):
        rec = dict(REC, fetched_at='2026-10-11', cached=True)
        s = checks.stock_check(self.lines(), lookup=lambda c: rec)
        self.assertEqual(s.status, 'skip')
        self.assertEqual(len(s.unchecked), 1)
        self.assertIn('facts from jlcpcb 2026-10-11 via the cache, not current', s.unchecked[0])
        self.assertIn('facts from jlcpcb 2026-10-11 via the cache (1 code)', s.summary)
        self.assertIn('bom.csv Fetched: jlcpcb 2026-10-11 (1 line)', s.notes[0])
        self.assertEqual(report.verdict([s]), 'NOT VERIFIED')

    def test_a_cached_disagreement_is_said_in_the_unchecked_line(self):
        rec = dict(REC, mpn='OTHER', stock=0, fetched_at='2026-10-11', cached=True)
        s = checks.stock_check(self.lines(), lookup=lambda c: rec)
        self.assertEqual(s.status, 'skip', 'nothing from the cache blocks or passes')
        self.assertIn('the cached record says: out of stock at JLCPCB (OTHER); bom.csv says MPN "CC0603KRX7R9BB104"', s.unchecked[0])

    def test_a_live_record_older_than_the_stock_limit_is_not_current(self):
        rec = dict(REC, fetched_at='2026-10-01', cached=False)

        class Fixed(catalogue.datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 18)
        with mock.patch('pcb_preflight.catalogue.datetime.date', Fixed):
            s = checks.stock_check(self.lines(), lookup=lambda c: rec)
        self.assertEqual(s.status, 'skip')
        self.assertIn('not current', s.unchecked[0])

    def test_a_fresh_live_record_passes_as_before(self):
        rec = dict(REC, fetched_at=catalogue.today(), cached=False)
        s = checks.stock_check(self.lines(), lookup=lambda c: rec)
        self.assertEqual(s.status, 'pass')
        self.assertIn(f'facts from jlcpcb {catalogue.today()} (1 code)', s.summary)
        self.assertEqual(checks.stock_check(self.lines(), lookup=lambda c: dict(REC)).status, 'pass', 'a record with no date (plain stock.lookup) is live')


class Manufacturer(unittest.TestCase):
    def test_a_different_maker_behind_the_same_code_blocks(self):
        ln = Line(row=2, refs=['C1'], package='0603', lcsc='C14663', mpn='CC0603KRX7R9BB104', manufacturer='Samsung')
        s = checks.stock_check([ln], lookup=lambda c: dict(REC))
        self.assertEqual(s.status, 'fail')
        self.assertIn('bom.csv says Manufacturer "Samsung" but the catalogue says "YAGEO"', s.details[0])

    def test_spelling_and_a_missing_column_do_not_block(self):
        for maker in ('yageo', 'YAGEO ', 'Yageo Corp', ''):
            ln = Line(row=2, refs=['C1'], package='0603', lcsc='C14663', mpn='CC0603KRX7R9BB104', manufacturer=maker)
            self.assertEqual(checks.stock_check([ln], lookup=lambda c: dict(REC)).status, 'pass', maker)
        ln = Line(row=2, refs=['C1'], package='0603', lcsc='C14663', mpn='CC0603KRX7R9BB104', manufacturer='Samsung')
        self.assertEqual(checks.stock_check([ln], lookup=lambda c: dict(REC, manufacturer='')).status, 'pass', 'a record without a maker (jlcsearch) compares nothing')


if __name__ == '__main__':
    unittest.main()
