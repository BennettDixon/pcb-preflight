"""The catalogue behind `preflight bom` and `check --online`: a cache, a user source, and the live client.

Three layers, each a few dozen lines (internal design note of 2026-10-18):

1. A cache, ``~/.cache/pcb-preflight/catalogue.json`` (or ``$PCB_PREFLIGHT_CACHE``): code -> record +
   ``fetched_at`` (ISO date) + the source that answered. A record younger than STOCK_DAYS is served from
   the cache; an older one is refetched when online (stock moves daily). Offline, a record up to
   IDENTITY_DAYS old is still served, labelled ``cache <date>``: its MPN, package and library type do not
   move, its stock figure is not current, so `check` lists such items as not checked, never as a pass.
2. A user source, ``--catalogue parts.csv``: a record-shaped CSV (lcsc, mpn, manufacturer, package,
   library, stock, description, datasheet, fetched_at) consulted first. A team can pin one in the repo; a
   fab that publishes a parts list drops in. Its records are labelled with the file's name.
3. The live client, stock.lookup (JLCPCB's cart endpoint, the jlcsearch mirror): one request per code,
   a pause between; the cache makes a 67-line board cost 67 requests once, not per run.

Every record that leaves here carries ``source`` (the catalogue that answered: ``jlcpcb``, ``jlcsearch``,
or the parts file's name), ``fetched_at`` (the date it answered) and ``cached`` (True when served from the
cache rather than fetched on this run). ``fetched_label()`` is the Fetched column's text, ``jlcpcb 2026-10-18``:
the catalogue and the date, the same whether the record was fetched now or read back within the stock
limit, so two runs in the same week write the same bytes. ``is_current()`` is the stock gate's question:
fetched on this run, within STOCK_DAYS; a cached record never is, whatever its age.
Nothing here chooses a part: the only question asked is "what is C14663".
"""
import csv
import datetime
import json
import os
import tempfile

from . import bom as bomlib
from . import stock

STOCK_DAYS = 7          # a stock figure older than this is refetched when online, not current when not
IDENTITY_DAYS = 90      # MPN, package and library type are trusted from the cache up to this age
DEFAULT_PATH = os.path.join('~', '.cache', 'pcb-preflight', 'catalogue.json')
SCHEMA = 1

PARTS_COLUMNS = ('lcsc', 'mpn', 'manufacturer', 'package', 'library', 'stock', 'description', 'datasheet', 'fetched_at')
LIVE = ('jlcpcb', 'jlcsearch')


def cache_path(explicit=None):
    return os.path.abspath(os.path.expanduser(explicit or os.environ.get('PCB_PREFLIGHT_CACHE') or DEFAULT_PATH))


def today():
    return datetime.date.today().isoformat()


def age_days(fetched_at, on=None):
    """Days between an ISO date and today (or ``on``); None when the date does not parse."""
    try:
        d = datetime.date.fromisoformat((fetched_at or '')[:10])
    except ValueError:
        return None
    ref = datetime.date.fromisoformat(on) if on else datetime.date.today()
    return (ref - d).days


def is_current(rec, on=None):
    """True when the record's stock figure may be taken as today's: fetched on this run, within STOCK_DAYS."""
    if not rec or rec.get('cached'):
        return False
    if not rec.get('fetched_at'):
        return True                              # a record straight from stock.lookup (no cache in the path)
    age = age_days(rec['fetched_at'], on)
    return age is not None and 0 <= age <= STOCK_DAYS


def fetched_label(rec, via=False):
    """The Fetched text: ``jlcpcb 2026-10-18``, ``parts.csv 2026-10-01`` or ``parts.csv``; with ``via``, a
    cached record reads ``jlcpcb 2026-10-11 via the cache`` (the stock gate's wording)."""
    if not rec:
        return ''
    text = ' '.join(x for x in (rec.get('source', ''), rec.get('fetched_at', '')) if x)
    return text + (' via the cache' if via and rec.get('cached') else '')


def load_parts(path):
    """code -> record from a user parts file. Headers are matched by lower-cased name; the file's name is the source."""
    name = os.path.basename(path)
    out = {}
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            r = {(k or '').strip().lower(): (v or '').strip() for k, v in row.items()}
            code = r.get('lcsc', '').upper().replace(' ', '')
            if not code:
                continue
            stock_s = r.get('stock', '').replace(',', '')
            out[code] = {
                'source': name, 'lcsc': code, 'mpn': r.get('mpn', ''), 'manufacturer': r.get('manufacturer', ''),
                'package': r.get('package', ''), 'library': bomlib.library_type(r.get('library', '')) or r.get('library', ''),
                'stock': int(stock_s) if stock_s.isdigit() else None, 'description': r.get('description', ''),
                'datasheet': r.get('datasheet', ''), 'category': '', 'min_qty': None, 'attrition': None,
                'fetched_at': r.get('fetched_at', ''),
            }
    return out


class Catalogue:
    """lookup(code) -> record | None | stock.LookupFailed, read through the parts file and the cache.

    ``refresh`` ignores cached records (they are still written); ``offline`` never calls the live client and
    serves the cache up to IDENTITY_DAYS, labelled; a live failure falls back to the cache the same way.
    ``counts`` says where the answers came from (fetched, cache, parts, missing, failed) for the report.
    """

    def __init__(self, path=None, parts=None, refresh=False, offline=False, fetch=None, on=None):
        self.path = cache_path(path)
        self.parts_path = parts
        self.parts = load_parts(parts) if parts else {}
        self.refresh, self.offline, self.fetch, self.on = refresh, offline, fetch or stock.lookup, on
        self.records = self._read()
        self.counts = {'fetched': 0, 'cache': 0, 'parts': 0, 'missing': 0, 'failed': 0}
        self.dirty = False

    # -- the cache file
    def _read(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            return {}
        return d.get('records', {}) if isinstance(d, dict) else {}

    def save(self):
        if not self.dirty:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix='.catalogue-', suffix='.json')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'schema': SCHEMA, 'records': self.records}, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
        self.dirty = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.save()

    # -- lookups
    def _cached(self, code):
        rec = self.records.get(code)
        if not rec:
            return None, None
        return dict(rec, cached=True), age_days(rec.get('fetched_at'), self.on)

    def lookup(self, code):
        if code in self.parts:
            self.counts['parts'] += 1
            return dict(self.parts[code], cached=False)
        cached, age = self._cached(code)
        fresh = cached is not None and age is not None and 0 <= age <= STOCK_DAYS
        if fresh and not self.refresh and not self.offline:
            self.counts['cache'] += 1
            return cached
        if self.offline:
            if cached is not None and age is not None and 0 <= age <= IDENTITY_DAYS:
                self.counts['cache'] += 1
                return cached
            self.counts['failed'] += 1
            raise stock.LookupFailed('offline: ' + ('not in the cache' if cached is None
                                                    else f'the cached record of {cached.get("fetched_at")} is older than {IDENTITY_DAYS} days'))
        try:
            rec = self.fetch(code)
        except stock.LookupFailed as e:
            if cached is not None and age is not None and 0 <= age <= IDENTITY_DAYS:
                self.counts['cache'] += 1
                return cached
            self.counts['failed'] += 1
            raise stock.LookupFailed(f'{e}; nothing in the cache')
        if rec is None:
            self.counts['missing'] += 1
            return None
        rec = dict(rec, fetched_at=self.on or today())
        rec.setdefault('source', 'jlcpcb')
        rec.pop('cached', None)
        self.records[code] = rec
        self.dirty = True
        self.counts['fetched'] += 1
        return dict(rec, cached=False)

    def summary(self):
        """``jlcpcb 2026-10-18 (45 codes fetched, 3 from cache)`` for a report's header line."""
        c = self.counts
        parts = []
        if c['fetched']:
            parts.append(f'{c["fetched"]} codes fetched')
        if c['cache']:
            parts.append(f'{c["cache"]} from cache')
        if c['parts']:
            parts.append(f'{c["parts"]} from {os.path.basename(self.parts_path)}')
        if c['missing']:
            parts.append(f'{c["missing"]} not in the catalogue')
        if c['failed']:
            parts.append(f'{c["failed"]} not answered')
        head = 'offline (cache only)' if self.offline else f'jlcpcb {self.on or today()}'
        return head + (f' ({", ".join(parts)})' if parts else ' (nothing looked up)')


def lookup(code, refresh=False, offline=False, path=None, parts=None):
    """One code through a throwaway Catalogue (the cache is still written)."""
    with Catalogue(path=path, parts=parts, refresh=refresh, offline=offline) as cat:
        return cat.lookup(code)
