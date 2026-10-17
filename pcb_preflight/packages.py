"""Does a catalogue part fit a footprint? Same, different or unknown (pitfalls §1).

``fits(footprint, part, mpn=None, library=None)`` compares a KiCad footprint name with a catalogue package
string and answers one of three verdicts. It never guesses: a spelling it cannot read is ``unknown``, which
the gates report as not compared, never as a pass.

Names select, pads decide
  Both strings are read into canonical package names (below). The names alone give a verdict: *same* when
  the two sets of names meet and nothing they state about pitch or body width disagrees, *different* when
  they do not meet or a stated pitch or width differs, *unknown* when a side is unreadable or says less than
  the other (QFN-16 against QFN-16 3x3). Given KiCad's footprint library (footprints.py, a ``Library``),
  each side is then resolved to library footprints: the one footprint the string names, else every library
  footprint that reads as the same canonical name (and the same pitch and width where the string gives
  them). When both sides resolve, the pads decide: a pad set that matches one on the other side is *same*
  whatever the names said (TSOT-23-6 on SOT-23-6, VSSOP-8 3x3 on MSOP-8 3x3, CP_Elec_6.3x7.7 on
  CP_Elec_6.3x5.8: the can's height is §10, not §1); pads that match nothing are *different* when the
  names also disagree and *unknown* when the names agreed (two QFN-20 4x4 footprints with 2.6 and 2.1 mm
  exposed pads). A string without dimensions that resolves to more than one land pattern in the library
  (TSSOP-14 at 0.65 and 0.4 mm pitch, SSOP-8 at 0.65 and 1.27 mm) is *unknown*: the name does not say
  which. Without a library the names alone decide, and the gate says so.

How a name is read
  The text (library prefix dropped) is cut into tokens at ``_ , ( ) [ ] / ;`` and spaces. Each token is
  looked up in SYNONYMS (whole spellings: SOT-25-5, D2PAK) and FAMILIES (family spellings that take a pin
  count: SOP, ESOP, TSOT, VQFN), then parsed into a canonical name:

    chip size           0603, 1210, 2920
    leaded family       SOIC-8, SOIC-8-EP, SOIC-8-208MIL, TSSOP-20-EP   (the exposed pad counts)
    no-lead / QFP       QFN-16(3x3), WSON-8(2x2), LQFP-48(7x7)          (body size when the name has it)
    SOT, SOD, TO        SOT-23, SOT-23-5, SOD-123F, TO-263, TO-263-7     (default pin counts dropped)
    diode outline       SMA, SMB, SMC, SMAF
    electrolytic can    CAN-SMD-D6.3xL7.7, CAN-THT-D10xL12.5

  A string can name several packages at once ("SC-70(SOT-323)"); two strings fit when their sets share a
  name. Two no-lead names that differ only because one side gives no body size are ``unknown``. For a
  leaded family the pitch (``P0.65mm``) and the body width (the first figure of ``4.4x5mm``) are read too
  where the name states them; a SOIC that states no pitch is taken at 1.27 mm (STANDARD_PITCH, with its
  source).

The part's own name
  Many KiCad footprints are drawn for one part and named after it (JST_XH_B6B-XH-A_..., L_Bourns_SRP1245A).
  When the package strings cannot be compared and the catalogue MPN starts with such a name token, the
  verdict is ``same``: the footprint was drawn for this part. This never overrides ``different``.

What it does not compare
  Pad shapes and pad numbers (the pin map is §3 and stays by hand), can height, lead length, connector
  series, inductor bodies, fuse clips, and anything else without a standard name. Those come back
  ``unknown`` and are listed for a human.

Adding a spelling
  Put it in SYNONYMS or FAMILIES with the record or document it was seen in, and add a row with the real
  strings to tests/fixtures/packages.csv; the tests fail for an entry no fixture row uses. Every verdict
  also carries the rule that produced it (``Fit.rule``, one of RULES); the fixture names the rule it expects
  for each row, and the tests fail for a rule no row exercises. A new spelling is data with a source, not
  a regex tweak.
"""
import re
from dataclasses import dataclass

from . import footprints

SAME, DIFFERENT, UNKNOWN = 'same', 'different', 'unknown'

# Fit.rule: how a verdict was reached.
BLANK = 'blank'                   # no text on one side
UNREADABLE = 'unreadable'         # a side is not in the package table
NAMES = 'names'                   # the canonical names meet (same) or do not (different)
DIMS = 'dims'                     # the names meet but a stated pitch or body width differs
HALF = 'half'                     # the names meet but only one side gives the body size
AMBIGUOUS = 'ambiguous'           # a name without dimensions resolves to more than one land pattern in the library
PADS = 'pads'                     # the pads match a library footprint on the other side
PADS_UNKNOWN = 'pads-unknown'     # the names agree, the pads match nothing on the other side
PADS_DIFFER = 'pads-differ'       # the names disagree and so do the pads
DRAWN_FOR = 'drawn-for'           # the footprint is named for the part (its MPN)
RULES = (BLANK, UNREADABLE, NAMES, DIMS, HALF, AMBIGUOUS, PADS, PADS_UNKNOWN, PADS_DIFFER, DRAWN_FOR)
LIBRARY_RULES = (AMBIGUOUS, PADS, PADS_UNKNOWN, PADS_DIFFER)      # reachable only with a footprint library

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
    'TSOT': ('SOT', False, 'JEDEC MO-193 (thin SOT-23) shares the MO-178 land pattern: KiCad 10.0.7 draws TSOT-23-5/-6 '
                           '(Package_TO_SOT_SMD) with the pads of SOT-23-5/-6; JLCPCB C8953 (MPS MP3202DJ) lists TSOT-23-6'),
    'VQFN': ('QFN', False, 'JEDEC MO-220 thickness designator (V = very thin): KiCad VQFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm '
                           '(descr "MO-220 variant VEED-6") has the pads of QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm; TI RGT is a VQFN and '
                           'JLCPCB C43590 (TPS62130RGTR) lists it as QFN-16-EP(3x3)'),
    'WQFN': ('QFN', False, 'JEDEC MO-220 thickness designator (W = very very thin): KiCad WQFN-16-1EP_3x3mm_P0.5mm_EP1.75x1.75mm '
                           '(onsemi FUSB307B) pads within 0.03 mm of QFN-16-1EP_3x3mm_P0.5mm_EP1.75x1.75mm'),
    'TQFN': ('QFN', False, 'Maxim\'s thin QFN, JEDEC MO-220: KiCad TQFN-20-1EP_4x4mm_P0.5mm_EP2.1x2.1mm (Maxim 21-0139 T2044-2) '
                           'against QFN-20-1EP_4x4mm_P0.5mm_EP2.6x2.6mm: same outline, exposed pad 2.1 vs 2.6 mm'),
    'UQFN': ('QFN', False, 'Microchip\'s ultra-thin QFN (packaging spec 00000049BS, JEDEC MO-220 outline): KiCad '
                           'UQFN-16-1EP_3x3mm_P0.5mm_EP1.75x1.75mm against QFN-16-1EP_3x3mm_P0.5mm_EP1.75x1.75mm'),
}

# Pitch a family is taken at when its name states none -> (mm, source). Only where the standard fixes it.
STANDARD_PITCH = {
    'SOIC': (1.27, 'JEDEC MS-012 (narrow) and MS-013 (wide) SOIC: 1.27 mm; KiCad files 2.54 mm SOPs such as '
                   'SOP-8_6.62x9.15mm_P2.54mm (TI ISO1050) under the same family name, which the stated pitch tells apart'),
}

LEADED = {'SOIC', 'SSOP', 'TSSOP', 'MSOP', 'VSSOP', 'QSOP'}            # an exposed pad changes the land pattern
ARRAY = {'QFN', 'DFN', 'SON', 'WSON', 'VSON', 'LQFN', 'UDFN', 'TDFN', 'LGA', 'BGA', 'LFCSP', 'LQFP', 'TQFP', 'QFP'}
OTHER = {'SOT', 'SOD', 'TO', 'SC'}
DEFAULT_PINS = {                                                         # pin counts that add nothing to the name
    'SOT-23': {'3'}, 'SOT-223': {'3', '4'}, 'SOT-89': {'3'}, 'SOT-323': {'3'}, 'SOT-523': {'3'},
    'SOT-723': {'3'}, 'SOT-883': {'3'}, 'SOT-353': {'5'}, 'SOT-363': {'6'}, 'SOT-563': {'6'}, 'SC-70': {'3'},
    'TO-263': {'2', '3'}, 'TO-252': {'2', '3'}, 'TO-220': {'3'}, 'TO-220F': {'3'}, 'TO-247': {'3'}, 'TO-92': {'3'},
    'TO-126': {'3'},
}
CHIP = {'01005', '0201', '0402', '0603', '0805', '1206', '1210', '1806', '1812', '2010', '2512', '2920'}
PLAIN = {'SMA', 'SMB', 'SMC', 'SMAF', 'SMBF'}

WIDTH_TOLERANCE = 0.8          # mm; KiCad's SOIC-16 bodies of 3.9, 4.4 and 4.55 mm are one class, TSSOP's 4.4 and 6.1 are two

TOKEN_SPLIT = re.compile(r'[\s_,()\[\]/;]+')
FAMILY_TOKEN = re.compile(r'([A-Z]+)-?(\d+)(.*)')
SIZE = re.compile(r'(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)(?:MM)?')
BODY = re.compile(r'(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)(?:X\d+(?:\.\d+)?)?MM')
PITCH = re.compile(r'P(\d+(?:\.\d+)?)MM')
CAN_PART = re.compile(r'D(\d+(?:\.\d+)?)XL(\d+(?:\.\d+)?)(?:MM)?')
SOIC_MIL = re.compile(r'(150|208|300)MIL')
SOIC_BODY = {'3.9': '150', '5.3': '208', '7.5': '300'}


@dataclass(frozen=True)
class Reading:
    names: frozenset           # canonical names this text stands for (empty: nothing readable)
    via: tuple                 # (spelling, canonical, source) for every table entry used
    pitch: float = None        # mm, for a leaded family: as stated, else the family's standard pitch
    width: float = None        # mm, body width for a leaded family, as stated
    pitch_source: str = ''     # '' when stated; the standard's source when implied


@dataclass(frozen=True)
class Fit:
    verdict: str               # SAME, DIFFERENT or UNKNOWN
    footprint: tuple           # canonical names read from the footprint side
    part: tuple                # canonical names read from the part side
    reason: str
    via: tuple = ()
    rule: str = NAMES          # one of RULES
    by_names: str = ''         # the verdict the names alone gave, when the pads decided

    def as_dict(self):
        return {'verdict': self.verdict, 'rule': self.rule, 'footprint': list(self.footprint), 'part': list(self.part),
                'reason': self.reason, 'by_names': self.by_names or self.verdict,
                'via': [{'spelling': s, 'read_as': c, 'source': src} for s, c, src in self.via]}


def _num(s):
    return format(float(s), 'g')


def _size(tok):
    m = SIZE.fullmatch(tok)
    if not m:
        return None
    a, b = sorted((_num(m.group(1)), _num(m.group(2))), key=float)
    return f'{a}x{b}'


def bare(text):
    """The name without its library prefix: ``Package_SO:SOIC-8`` -> ``SOIC-8``."""
    return text.split(':', 1)[-1].strip()


_strip = bare


def _tokens(text):
    return [t for t in TOKEN_SPLIT.split(bare(text).upper()) if t]


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
    """The canonical name of a family token, or None; returns (name, family)."""
    m = FAMILY_TOKEN.fullmatch(tok)
    if not m:
        return None, None
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
        return name + ('-EP' if ep else ''), fam
    if fam in ARRAY:
        size = next((s for s in (_size(t) for t in toks[i + 1:i + 3]) if s), None)
        return f'{fam}-{n}' + (f'({size})' if size else ''), fam
    if fam in OTHER:
        base = f'{fam}-{n}'
        k = re.match(r'([A-Z]*)-?(\d*)', rest)
        letters, pins = k.group(1), k.group(2)
        if fam == 'SOD':
            return base + letters, fam
        if fam == 'TO':
            base += letters
        elif letters and not pins:          # SOT-23-6L, SOT-23L: a trailing L is a vendor's "lead" marker
            letters = ''
        if pins and pins not in DEFAULT_PINS.get(base, set()):
            return f'{base}-{pins}', fam
        return base, fam
    return None, None


def _dims(toks, leaded):
    """(pitch, width) a leaded family's tokens state: P0.65MM and the first figure of 4.4X5MM."""
    if not leaded:
        return None, None
    pitch = next((float(m.group(1)) for t in toks for m in [PITCH.fullmatch(t)] if m), None)
    width = next((float(m.group(1)) for t in toks for m in [BODY.fullmatch(t)] if m), None)
    return pitch, width


def read(text):
    """The canonical package names a footprint or catalogue string stands for, with pitch and width where stated."""
    if not text or not text.strip():
        return Reading(frozenset(), ())
    toks = _tokens(text)
    names, via, fams = set(), [], set()
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
            name, fam = _family(tok, i, toks, via)
            if name:
                names.add(name)
                fams.add(fam)
    pitch, width = _dims(toks, fams & LEADED)
    source = ''
    if pitch is None:
        for fam in fams & set(STANDARD_PITCH):
            pitch, source = STANDARD_PITCH[fam]
    return Reading(frozenset(names), tuple(via), pitch, width, source)


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


# ---------------------------------------------------------------- the KiCad footprint library

@dataclass(frozen=True)
class Entry:
    lib_id: str
    name: str
    pitch: float = None
    width: float = None


@dataclass(frozen=True)
class Resolved:
    entries: tuple             # library footprints the text stands for (one when it names a footprint)
    ambiguity: str = ''        # why the text alone does not pick a land pattern, when it does not


def _classes(values, tol):
    """Distinct values more than ``tol`` apart, sorted; values within ``tol`` of one another are one class."""
    out = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


class Library:
    """KiCad's footprint library, indexed by canonical package name, for fits().

    The package libraries (Package_*, Diode_*, Capacitor_*, Resistor_*, LED_SMD, Inductor_SMD, Fuse) are indexed
    by what read() makes of each footprint name; any library under the root can be opened by ``Library:Name``.
    Pads are read on demand and kept.
    """
    INDEXED = re.compile(r'^(Package_|Diode_|Capacitor_|Resistor_|LED_SMD$|Inductor_SMD$|Fuse$)')

    def __init__(self, root):
        self.root = root
        self._pads = {}
        self._by_name = None
        self._exact = None
        self.indexed = 0

    def _build(self):
        self._by_name, self._exact = {}, {}
        for lib, d in footprints.libraries(self.root).items():
            if not self.INDEXED.match(lib):
                continue
            for name in footprints.footprint_names(d):
                lib_id = f'{lib}:{name}'
                pitch, width = footprints.dims_in_name(name)
                e = Entry(lib_id, name, pitch, width)
                self.indexed += 1
                self._exact.setdefault(name.upper(), []).append(e)
                for canon in read(name).names:
                    self._by_name.setdefault(canon, []).append(e)

    def pads(self, lib_id):
        """The copper pads of a library footprint, or None when it is not in the library or unreadable."""
        if lib_id not in self._pads:
            path = footprints.path_of(self.root, lib_id)
            try:
                self._pads[lib_id] = footprints.read_pads(path) if path else None
            except (OSError, ValueError):
                self._pads[lib_id] = None
        return self._pads[lib_id]

    def resolve(self, text, reading):
        """The library footprints a footprint name or package string stands for (see the module docstring)."""
        if self._by_name is None:
            self._build()
        if ':' in text and footprints.path_of(self.root, text.strip()):
            lib_id = text.strip()
            name = bare(lib_id)
            return Resolved((Entry(lib_id, name, *footprints.dims_in_name(name)),))
        exact = self._exact.get(bare(text).upper())
        if exact:
            return Resolved(tuple(exact))
        seen, entries = set(), []
        for canon in sorted(reading.names):
            for e in self._by_name.get(canon, []):
                if e.lib_id in seen:
                    continue
                if reading.pitch is not None and e.pitch is not None and abs(e.pitch - reading.pitch) > footprints.PITCH_TOLERANCE:
                    continue
                if reading.width is not None and e.width is not None and abs(e.width - reading.width) > WIDTH_TOLERANCE:
                    continue
                seen.add(e.lib_id)
                entries.append(e)
        why = []
        if reading.pitch is None:
            pitches = _classes([e.pitch for e in entries if e.pitch is not None], footprints.PITCH_TOLERANCE)
            if len(pitches) > 1:
                why.append('pitch ' + ' and '.join(f'{p:g}' for p in pitches) + ' mm')
        if reading.width is None:
            widths = _classes([e.width for e in entries if e.width is not None], WIDTH_TOLERANCE)
            if len(widths) > 1:
                why.append('body width ' + ' and '.join(f'{w:g}' for w in widths) + ' mm')
        return Resolved(tuple(entries), '; '.join(why))


def load_library(root):
    """A Library for a footprints directory, or None when ``root`` is None."""
    return Library(root) if root else None


# ---------------------------------------------------------------- the verdict

def fits(footprint, part, mpn=None, library=None):
    """Fit verdict for a part's catalogue package against a footprint name.

    The two package arguments may come in either order; ``mpn`` (the part's manufacturer number) is only
    matched against the footprint argument's name, and only when the packages themselves are unknown.
    ``library`` is a Library (KiCad's footprints) for pad geometry, or None to compare names alone.
    """
    f = _fits(footprint, part, library)
    if f.verdict == UNKNOWN and mpn and footprint:
        tok = _drawn_for(footprint, mpn)
        if tok:
            return Fit(SAME, f.footprint, f.part, f'the footprint is drawn for this part ({tok} in its name, MPN {mpn})', f.via, DRAWN_FOR)
    return f


def _by_names(footprint, part, a, b):
    via = a.via + b.via
    fa, fb = tuple(sorted(a.names)), tuple(sorted(b.names))
    if not a.names and not b.names:
        return Fit(UNKNOWN, fa, fb, 'neither name is in the package table', via, UNREADABLE)
    if not a.names or not b.names:
        blank = footprint if not a.names else part
        return Fit(UNKNOWN, fa, fb, f'"{bare(blank)}" is not in the package table', via, UNREADABLE)
    common = a.names & b.names
    if common:
        if a.pitch is not None and b.pitch is not None and abs(a.pitch - b.pitch) > footprints.PITCH_TOLERANCE:
            implied = next((f' ({r.pitch:g} mm is {_show(common)}\'s standard pitch: {r.pitch_source})' for r in (a, b) if r.pitch_source), '')
            return Fit(DIFFERENT, fa, fb, f'both are {_show(common)}, but the pitch differs: {a.pitch:g} mm against {b.pitch:g} mm{implied}', via, DIMS)
        if a.width is not None and b.width is not None and abs(a.width - b.width) > WIDTH_TOLERANCE:
            return Fit(DIFFERENT, fa, fb, f'both are {_show(common)}, but the body width differs: {a.width:g} mm against {b.width:g} mm', via, DIMS)
        used = '; '.join(f'{s} read as {c} ({src})' for s, c, src in via)
        return Fit(SAME, fa, fb, f'both are {_show(common)}' + (f'; {used}' if used else ''), via, NAMES)
    half = [(x, y) for x in a.names for y in b.names if _base(x) == _base(y) and ('(' in x) != ('(' in y)]
    if half:
        x, y = half[0]
        return Fit(UNKNOWN, fa, fb, f'both are {_base(x)}, but only one side gives the body size ({x} against {y})', via, HALF)
    return Fit(DIFFERENT, fa, fb, f'footprint is {_show(a.names)}, part is {_show(b.names)}', via, NAMES)


def _fits(footprint, part, library):
    if not footprint or not part or not footprint.strip() or not part.strip():
        return Fit(UNKNOWN, (), (), 'no package text on one side', (), BLANK)
    a, b = read(footprint), read(part)
    names = _by_names(footprint, part, a, b)
    if library is None:
        return names
    ra, rb = library.resolve(footprint, a), library.resolve(part, b)
    ambiguous = next(((text, r) for text, r in ((footprint, ra), (part, rb)) if r.ambiguity), None)
    pads_a = [(e, p) for e in ra.entries for p in [library.pads(e.lib_id)] if p]
    pads_b = [(e, p) for e in rb.entries for p in [library.pads(e.lib_id)] if p]
    match = first = None
    for ea, pa in pads_a:
        for eb, pb in pads_b:
            ok, why = footprints.same_pads(pa, pb)
            if ok:
                match = (ea, eb, len(pa))
                break
            first = first or (ea, eb, why)
        if match:
            break
    if ambiguous:
        text, r = ambiguous
        some = ', '.join(e.name for e in r.entries[:4]) + (f', +{len(r.entries) - 4} more' if len(r.entries) > 4 else '')
        what = f'"{bare(text)}" names more than one land pattern in the KiCad library ({r.ambiguity}: {some}); the string does not say which'
        if match:
            return Fit(UNKNOWN, names.footprint, names.part, f'the pads match {match[0].name if match[0].lib_id != text.strip() else match[1].name}, but {what}',
                       names.via, AMBIGUOUS, names.verdict)
        if names.verdict != DIFFERENT:
            return Fit(UNKNOWN, names.footprint, names.part, what, names.via, AMBIGUOUS, names.verdict)
    if match:
        ea, eb, n = match
        note = '' if names.verdict == SAME else f'; by name {names.reason}'
        return Fit(SAME, names.footprint, names.part, f'pads match: {ea.name} and {eb.name} in the KiCad library ({n} pads){note}',
                   names.via, PADS, names.verdict)
    if not pads_a or not pads_b:
        return names
    ea, eb, why = first
    if names.verdict == DIFFERENT:
        return Fit(DIFFERENT, names.footprint, names.part, f'{names.reason}; the pads differ too ({ea.name} against {eb.name}: {why})',
                   names.via, PADS_DIFFER, names.verdict)
    return Fit(UNKNOWN, names.footprint, names.part, f'{names.reason}, but the pads differ ({ea.name} against {eb.name}: {why})',
               names.via, PADS_UNKNOWN, names.verdict)
