"""The project's bom.csv: the list of parts chosen from the fab's catalog before layout.

Columns (header names are matched loosely, case-insensitively):
  Ref, Value, Package, MPN, LCSC, Basic/Extended, Stock, Datasheet
``Ref`` may hold one reference or several ("C1,C7,C8" or "C1 C7 C8").
"""
import csv
import re
from dataclasses import dataclass, field

REQUIRED = ['Ref', 'Value', 'Package', 'MPN', 'LCSC', 'Basic/Extended', 'Stock', 'Datasheet']

ALIASES = {
    'ref': 'Ref', 'refs': 'Ref', 'reference': 'Ref', 'references': 'Ref', 'designator': 'Ref',
    'value': 'Value', 'comment': 'Value',
    'package': 'Package', 'footprint': 'Package',
    'mpn': 'MPN', 'part number': 'MPN', 'manufacturer part number': 'MPN', 'mfr part': 'MPN',
    'lcsc': 'LCSC', 'lcsc part #': 'LCSC', 'lcsc part': 'LCSC', 'lcsc code': 'LCSC', 'jlcpcb part #': 'LCSC',
    'basic/extended': 'Basic/Extended', 'type': 'Basic/Extended', 'library': 'Basic/Extended', 'library type': 'Basic/Extended',
    'stock': 'Stock', 'stock-at-selection': 'Stock', 'stock at selection': 'Stock',
    'datasheet': 'Datasheet', 'datasheet url': 'Datasheet',
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
                          stock=get('Stock'), datasheet=get('Datasheet'), extra=extra))
    return lines, missing


def library_type(s):
    return LIBRARY_TYPES.get(s.strip().lower())


# --- package normalisation: so "C_0805_2012Metric", "0805" and JLCPCB's "0805" compare equal ---

CHIP = re.compile(r'(?<!\d)(01005|0201|0402|0603|0805|1206|1210|1806|1812|2010|2512|2920)(?!\d)')
ALIAS_PKG = {'DO-214AC': 'SMA', 'DO-214AA': 'SMB', 'DO-214AB': 'SMC', 'D2PAK': 'TO-263', 'DPAK': 'TO-252', 'SOP': 'SOIC'}
FAMILY = re.compile(r'(?i)\b(SOIC|SOP|SSOP|TSSOP|MSOP|VSSOP|HTSSOP|QFN|DFN|WSON|LQFN|LQFP|TQFP|QFP|UQFN|VQFN|SC-70|SOT|SOD|TO|LGA|BGA)-?(\d+)')
PLAIN = re.compile(r'(?i)\b(SMA|SMB|SMC|SMAF|SMBF|DO-214A[ABC]|D2PAK|DPAK|PowerPAK)\b')


def package_token(text):
    """A comparable package token, or None when the package has no standard short name.

    Compares only what is safe to compare: chip sizes (0603, 1210, ...), SOT/SOD/SOIC/QFN-style families
    with their pin count, and the SMA/SMB/SMC diode packages. Connectors, electrolytics and inductors
    return None, so they are never compared.
    """
    if not text:
        return None
    t = text.split(':', 1)[-1].replace('_', ' ')
    m = CHIP.search(t)
    if m:
        return m.group(1)
    m = FAMILY.search(t)
    if m:
        fam = ALIAS_PKG.get(m.group(1).upper(), m.group(1).upper())
        n = m.group(2)
        if fam == 'TO':
            return f'TO-{n}' if n in ('263', '252', '220', '247', '92', '126') else None
        if fam == 'SOT' and n == '23':
            k = re.search(r'(?i)SOT-?23-?(\d)', t)
            return 'SOT-23' if not k or k.group(1) == '3' else f'SOT-23-{k.group(1)}'
        return f'{fam}-{n}'
    m = PLAIN.search(t)
    if m:
        p = m.group(1).upper()
        return ALIAS_PKG.get(p, p)
    return None
