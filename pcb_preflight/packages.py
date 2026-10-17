"""Does a catalogue part fit a footprint? Same, different or unknown (pitfalls §1).

``fits(footprint, part)`` compares a KiCad footprint name with a catalogue package string and answers one
of three verdicts. It never guesses: a spelling it cannot read is ``unknown``, which the gates report as
not compared, never as a pass.

How a name is read
  The text (library prefix dropped) is cut into tokens at ``_ , ( ) [ ] / ;`` and spaces. Each token is
  looked up in SYNONYMS (whole spellings: SOT-25-5, D2PAK) and FAMILIES (family spellings that take a pin
  count: SOP, ESOP), then parsed into a canonical name:

    chip size           0603, 1210, 2920
    leaded family       SOIC-8, SOIC-8-EP, SOIC-8-208MIL, TSSOP-20-EP   (the exposed pad counts)
    no-lead / QFP       QFN-16(3x3), WSON-8(2x2), LQFP-48(7x7)          (body size when the name has it)
    SOT, SOD, TO        SOT-23, SOT-23-5, SOD-123F, TO-263, TO-263-7     (default pin counts dropped)
    diode outline       SMA, SMB, SMC, SMAF
    electrolytic can    CAN-SMD-D6.3xL7.7, CAN-THT-D10xL12.5

  A string can name several packages at once ("SC-70(SOT-323)"); two strings fit when their sets share a
  name. Two no-lead names that differ only because one side gives no body size are ``unknown``.

The part's own name
  Many KiCad footprints are drawn for one part and named after it (JST_XH_B6B-XH-A_..., L_Bourns_SRP1245A).
  When the package strings cannot be compared and the catalogue MPN starts with such a name token, the
  verdict is ``same``: the footprint was drawn for this part. This never overrides ``different``.

What it does not compare
  Pitch, lead length, exposed-pad size, TSSOP body width, connector series, inductor bodies, fuse clips,
  and anything else without a standard name. Those come back ``unknown`` and are listed for a human.

Adding a spelling
  Put it in SYNONYMS or FAMILIES with the record or document it was seen in, and add a row with the real
  strings to tests/fixtures/packages.csv; the tests fail for an entry no fixture row uses. A new
  spelling is data with a source, not a regex tweak.
"""
import re
from dataclasses import dataclass

SAME, DIFFERENT, UNKNOWN = 'same', 'different', 'unknown'

# Whole spellings -> (canonical name, where the spelling was seen).
SYNONYMS = {
    'SOT-25-5': ('SOT-23-5', 'JLCPCB C51118 (Diodes AP2112K-3.3TRG1) lists SOT-25-5; Diodes calls SOT-23-5 "SOT25"'),
    'SOT25': ('SOT-23-5', 'Diodes AP2112 datasheet: SOT25 "previously ... identified as SOT23-5"'),
    'SC-74A': ('SOT-23-5', 'JLCPCB C5513 (Nexperia 74AHC1G14GV, package SOT753) lists SC-74A'),
    'DO-214AC': ('SMA', 'JEDEC outline of SMA; JLCPCB C8678 (SS34) lists SMA(DO-214AC)'),
    'DO-214AA': ('SMB', 'JEDEC outline of SMB; JLCPCB C315992 (Littelfuse SMBJ26A) lists DO-214AA'),
    'DO-214AB': ('SMC', 'JEDEC outline of SMC; JLCPCB C224045 (Littelfuse SMCJ24A) lists DO-214AB'),
    'D2PAK': ('TO-263', 'JEDEC TO-263; JLCPCB C2620 (Infineon IRF4905STRLPBF) lists D2PAK'),
    'DPAK': ('TO-252', 'JEDEC TO-252; JLCPCB C10663 (onsemi NTD2955T4G) lists DPAK, C2583 (Infineon IRFR024N) DPAK(TO-252AA)'),
}

# Family spellings that take a pin count -> (canonical family, exposed pad implied, where it was seen).
FAMILIES = {
    'SOP': ('SOIC', False, 'JLCPCB lists the 150-mil SOIC-8 as SOP-8: C695838 (UMW NE555DR) vs C7593 (TI NE555DR, SOIC-8)'),
    'SO': ('SOIC', False, 'Diodes AP2112 datasheet: SO-8 "previously ... identified as SOIC-8"'),
    'ESOP': ('SOIC', True, 'JLCPCB C841384 (TI LMR33630ADDAR, TI package DDA "SO PowerPAD") lists ESOP-8'),
    'HTSSOP': ('TSSOP', True, 'TI PowerPAD TSSOP (PWP): JLCPCB lists it as HTSSOP-20-EP (C7096) and TSSOP-20-EP (C9379)'),
}

LEADED = {'SOIC', 'SSOP', 'TSSOP', 'MSOP', 'VSSOP', 'QSOP'}            # an exposed pad changes the land pattern
ARRAY = {'QFN', 'DFN', 'SON', 'WSON', 'VSON', 'UQFN', 'VQFN', 'WQFN', 'LQFN', 'TQFN', 'UDFN', 'TDFN', 'LGA',
         'BGA', 'LFCSP', 'LQFP', 'TQFP', 'QFP'}                          # body size is the comparable part
OTHER = {'SOT', 'TSOT', 'SOD', 'TO', 'SC'}
DEFAULT_PINS = {                                                         # pin counts that add nothing to the name
    'SOT-23': {'3'}, 'TSOT-23': {'3'}, 'SOT-223': {'3', '4'}, 'SOT-89': {'3'}, 'SOT-323': {'3'}, 'SOT-523': {'3'},
    'SOT-723': {'3'}, 'SOT-883': {'3'}, 'SOT-353': {'5'}, 'SOT-363': {'6'}, 'SOT-563': {'6'}, 'SC-70': {'3'},
    'TO-263': {'2', '3'}, 'TO-252': {'2', '3'}, 'TO-220': {'3'}, 'TO-220F': {'3'}, 'TO-247': {'3'}, 'TO-92': {'3'},
    'TO-126': {'3'},
}
CHIP = {'01005', '0201', '0402', '0603', '0805', '1206', '1210', '1806', '1812', '2010', '2512', '2920'}
PLAIN = {'SMA', 'SMB', 'SMC', 'SMAF', 'SMBF'}

TOKEN_SPLIT = re.compile(r'[\s_,()\[\]/;]+')
FAMILY_TOKEN = re.compile(r'([A-Z]+)-?(\d+)(.*)')
SIZE = re.compile(r'(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)(?:MM)?')
CAN_PART = re.compile(r'D(\d+(?:\.\d+)?)XL(\d+(?:\.\d+)?)(?:MM)?')
SOIC_MIL = re.compile(r'(150|208|300)MIL')
SOIC_BODY = {'3.9': '150', '5.3': '208', '7.5': '300'}


@dataclass(frozen=True)
class Reading:
    names: frozenset           # canonical names this text stands for (empty: nothing readable)
    via: tuple                 # (spelling, canonical, source) for every table entry used


@dataclass(frozen=True)
class Fit:
    verdict: str               # SAME, DIFFERENT or UNKNOWN
    footprint: tuple           # canonical names read from the footprint side
    part: tuple                # canonical names read from the part side
    reason: str
    via: tuple = ()

    def as_dict(self):
        return {'verdict': self.verdict, 'footprint': list(self.footprint), 'part': list(self.part),
                'reason': self.reason, 'via': [{'spelling': s, 'read_as': c, 'source': src} for s, c, src in self.via]}


def _num(s):
    return format(float(s), 'g')


def _size(tok):
    m = SIZE.fullmatch(tok)
    if not m:
        return None
    a, b = sorted((_num(m.group(1)), _num(m.group(2))), key=float)
    return f'{a}x{b}'


def _strip(text):
    return text.split(':', 1)[-1].strip()


def _tokens(text):
    return [t for t in TOKEN_SPLIT.split(_strip(text).upper()) if t]


def _can(toks):
    """Electrolytic can: KiCad C_Elec/CP_Elec_<D>x<L> (SMD) or JLCPCB 'SMD,D6.3xL7.7mm' / 'Plugin,D10xL12.5mm'."""
    if 'ELEC' in toks:
        for t in toks:
            m = SIZE.fullmatch(t)
            if m:
                return f'CAN-SMD-D{_num(m.group(1))}xL{_num(m.group(2))}'
    mount = 'SMD' if 'SMD' in toks else ('THT' if 'PLUGIN' in toks or '插件' in toks else None)
    if mount:
        for t in toks:
            m = CAN_PART.fullmatch(t)
            if m:
                return f'CAN-{mount}-D{_num(m.group(1))}xL{_num(m.group(2))}'
    return None


def _family(tok, i, toks, via):
    m = FAMILY_TOKEN.fullmatch(tok)
    if not m:
        return None
    fam, n, rest = m.groups()
    ep = False
    if fam in FAMILIES:
        canon, ep, src = FAMILIES[fam]
        via.append((f'{fam}-{n}', f'{canon}-{n}', src))
        fam = canon
    if fam in LEADED:
        ep = ep or bool(re.search(r'EP|POWERPAD', rest)) or any(re.fullmatch(r'EP\d.*|POWERPAD|THERMALPAD', t) for t in toks)
        name = f'{fam}-{n}'
        if fam == 'SOIC':
            mil = SOIC_MIL.search(' '.join([rest] + toks))
            body = next((SOIC_BODY[b] for b in SOIC_BODY for t in toks if SIZE.fullmatch(t) and t.startswith(b + 'X')), None)
            width = mil.group(1) if mil else (body or ('300' if rest.startswith('W') else '150'))
            if width != '150':
                name += f'-{width}MIL'
        return name + ('-EP' if ep else '')
    if fam in ARRAY:
        size = next((s for s in (_size(t) for t in toks[i + 1:i + 3]) if s), None)
        return f'{fam}-{n}' + (f'({size})' if size else '')
    if fam in OTHER:
        base = f'{fam}-{n}'
        k = re.match(r'([A-Z]*)-?(\d*)', rest)
        letters, pins = k.group(1), k.group(2)
        if fam == 'SOD':
            return base + letters
        if fam == 'TO':
            base += letters
        elif letters and not pins:          # SOT-23-6L, SOT-23L: a trailing L is a vendor's "lead" marker
            letters = ''
        if pins and pins not in DEFAULT_PINS.get(base, set()):
            return f'{base}-{pins}'
        return base
    return None


def read(text):
    """The canonical package names a footprint or catalogue string stands for."""
    if not text or not text.strip():
        return Reading(frozenset(), ())
    toks = _tokens(text)
    names, via = set(), []
    can = _can(toks)
    if can:
        names.add(can)
    for i, tok in enumerate(toks):
        if tok in SYNONYMS:
            canon, src = SYNONYMS[tok]
            names.add(canon)
            via.append((tok, canon, src))
        elif tok in CHIP or tok in PLAIN:
            names.add(tok)
        else:
            name = _family(tok, i, toks, via)
            if name:
                names.add(name)
    return Reading(frozenset(names), tuple(via))


def _base(name):
    return name.split('(', 1)[0]


def _show(names):
    return '/'.join(sorted(names)) or 'nothing readable'


def _drawn_for(footprint, mpn):
    """The footprint-name token the MPN starts with (B6B-XH-A for B6B-XH-A(LF)(SN)), or None."""
    core = re.sub(r'\(.*?\)', '', mpn.upper()).strip()
    for tok in _tokens(footprint):
        if len(tok) >= 5 and re.search(r'[A-Z]', tok) and re.search(r'\d', tok) and core.startswith(tok):
            return tok
    return None


def fits(footprint, part, mpn=None):
    """Fit verdict for a part's catalogue package against a footprint name.

    The two package arguments may come in either order; ``mpn`` (the part's manufacturer number) is only
    matched against the footprint argument's name, and only when the packages themselves are unknown.
    """
    f = _fits(footprint, part)
    if f.verdict == UNKNOWN and mpn and footprint:
        tok = _drawn_for(footprint, mpn)
        if tok:
            return Fit(SAME, f.footprint, f.part, f'the footprint is drawn for this part ({tok} in its name, MPN {mpn})', f.via)
    return f


def _fits(footprint, part):
    if not footprint or not part or not footprint.strip() or not part.strip():
        return Fit(UNKNOWN, (), (), 'no package text on one side')
    if _strip(footprint).upper() == _strip(part).upper():
        return Fit(SAME, (), (), 'same name')
    a, b = read(footprint), read(part)
    via = a.via + b.via
    fa, fb = tuple(sorted(a.names)), tuple(sorted(b.names))
    if not a.names and not b.names:
        return Fit(UNKNOWN, fa, fb, 'neither name is in the package table', via)
    if not a.names or not b.names:
        blank = footprint if not a.names else part
        return Fit(UNKNOWN, fa, fb, f'"{_strip(blank)}" is not in the package table', via)
    common = a.names & b.names
    if common:
        used = '; '.join(f'{s} read as {c} ({src})' for s, c, src in via)
        return Fit(SAME, fa, fb, f'both are {_show(common)}' + (f'; {used}' if used else ''), via)
    half = [(x, y) for x in a.names for y in b.names if _base(x) == _base(y) and ('(' in x) != ('(' in y)]
    if half:
        x, y = half[0]
        return Fit(UNKNOWN, fa, fb, f'both are {_base(x)}, but only one side gives the body size ({x} against {y})', via)
    return Fit(DIFFERENT, fa, fb, f'footprint is {_show(a.names)}, part is {_show(b.names)}', via)
