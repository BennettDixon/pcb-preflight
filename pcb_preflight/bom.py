"""The project's bom.csv: the list of parts chosen from the fab's catalog before layout.

Columns (header names are matched loosely, case-insensitively):
  Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet
and, optionally, Package verified: a note that a human compared the part's drawing with the footprint
("2026-10-16 BD: SRP1245A land pattern vs datasheet p.2"), which packages.fits() cannot.
``Ref`` may hold one reference or several ("C1,C7,C8" or "C1 C7 C8").
"""
import csv
import re
from dataclasses import dataclass, field

REQUIRED = ['Ref', 'Value', 'Package', 'MPN', 'LCSC', 'Basic/Extended', 'Stock', 'Datasheet']
OPTIONAL = ['Package verified']

ALIASES = {
    'ref': 'Ref', 'refs': 'Ref', 'reference': 'Ref', 'references': 'Ref', 'designator': 'Ref',
    'value': 'Value', 'comment': 'Value',
    'package': 'Package', 'footprint': 'Package',
    'mpn': 'MPN', 'part number': 'MPN', 'manufacturer part number': 'MPN', 'mfr part': 'MPN',
    'lcsc': 'LCSC', 'lcsc part #': 'LCSC', 'lcsc part': 'LCSC', 'lcsc code': 'LCSC', 'jlcpcb part #': 'LCSC',
    'basic/extended': 'Basic/Extended', 'type': 'Basic/Extended', 'library': 'Basic/Extended', 'library type': 'Basic/Extended',
    'stock': 'Stock', 'stock-at-selection': 'Stock', 'stock at selection': 'Stock',
    'datasheet': 'Datasheet', 'datasheet url': 'Datasheet',
    'package verified': 'Package verified', 'package checked': 'Package verified', 'footprint verified': 'Package verified',
}

LCSC_RE = re.compile(r'^C\d{1,9}$')
LIBRARY_TYPES = {'basic': 'Basic', 'extended': 'Extended', 'preferred': 'Preferred', 'base': 'Basic', 'expand': 'Extended'}


@dataclass
class Line:
    row: int
    refs: list
    value: str = ''
    package: str = ''
    mpn: str = ''
    lcsc: str = ''
    library: str = ''
    stock: str = ''
    datasheet: str = ''
    package_verified: str = ''
    extra: dict = field(default_factory=dict)

    @property
    def label(self):
        return f"row {self.row} {','.join(self.refs) or '(no ref)'}: {self.value} ({self.package or 'no package'})"

    @property
    def stock_number(self):
        s = re.sub(r'[,\s_]', '', self.stock)
        return int(s) if s.isdigit() else None


def _canon(header):
    return ALIASES.get(header.strip().lower().lstrip('﻿'))


def load(path):
    """Return (lines, header_problems). ``header_problems`` is a list of missing required columns."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        rows = [r for r in reader]
    if not rows:
        return [], ['empty file']
    header = rows[0]
    colmap = {}
    for i, h in enumerate(header):
        c = _canon(h)
        if c and c not in colmap:
            colmap[c] = i
    missing = [c for c in REQUIRED if c not in colmap]
    lines = []
    for n, r in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in r):
            continue
        get = lambda c: r[colmap[c]].strip() if c in colmap and colmap[c] < len(r) else ''
        refs = [x for x in re.split(r'[,\s;]+', get('Ref')) if x]
        extra = {h: r[i] for i, h in enumerate(header) if i < len(r) and _canon(h) is None}
        lines.append(Line(row=n, refs=refs, value=get('Value'), package=get('Package'), mpn=get('MPN'),
                          lcsc=get('LCSC').upper().replace(' ', ''), library=get('Basic/Extended'),
                          stock=get('Stock'), datasheet=get('Datasheet'),
                          package_verified=get('Package verified'), extra=extra))
    return lines, missing


def library_type(s):
    return LIBRARY_TYPES.get(s.strip().lower())
