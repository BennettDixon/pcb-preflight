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
  (TSSOP-14 at 0.65 and 0.4 mm pitch, SSOP-8 at 0.65 and 1.27 mm) does not say which; when the other side
  is one footprint KiCad has (the board's own) and its pads match one of those land patterns, the board
  has said it and the verdict is *same* (``Fit.picked`` names the ambiguity settled); when the board's
  footprint is not in KiCad's library, or its pads match none of them, the verdict is *unknown*. Without
  a library the names alone decide, and the gate says so. A pad is one piece of copper: pads sharing a
  number that touch are one pad and a via-in-pad hole with the exposed pad's number is not a pad
  (footprints.stack; TI's PowerPAD footprints).

How a name is read
  The text (library prefix dropped) is cut into tokens at ``_ , ( ) [ ] / ;`` and spaces. Each token is
  looked up in SYNONYMS (whole spellings: SOT-25-5, D2PAK, SOT-5X3) and FAMILIES (family spellings that
  take a pin count: SOP, ESOP, TSOT, VQFN, LQFN, TDFN), read by one of the PATTERNS (shapes with a source:
  C0402, WQFN4040-24, SOT-23-Thin-6, SMD3225-4P, CASE-A-3216-18, SO-PowerPAD-8, a BGA's ball layout),
  then parsed into a canonical name:

    chip size           0603, 1210, 2920
    leaded family       SOIC-8, SOIC-8-EP, SOIC-8-208MIL, TSSOP-20-EP   (the exposed pad counts)
    no-lead / QFP       QFN-16(3x3), WSON-8(2x2), LQFP-48(7x7)          (body size when the name has it)
    SOT, SOD, TO        SOT-23, SOT-23-5, SOD-123F, TO-263, TO-263-7     (default pin counts dropped)
    diode outline       SMA, SMB, SMC, SMAF
    electrolytic can    CAN-SMD-D6.3xL7.7, CAN-THT-D10xL12.5
    crystal body        SMD-3225-4P (JLCPCB SMD3225-4P, KiCad Crystal_SMD_3225-4Pin_3.2x2.5mm)
    tantalum case       EIA-3216-18 (JLCPCB CASE-A-3216-18(mm), KiCad CP_EIA-3216-18_Kemet-A)

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
  Put it in SYNONYMS or FAMILIES (or, for a shape, in PATTERNS) with the record or document it was seen in,
  and add a row with the real strings to tests/fixtures/packages.csv; the tests fail for an entry no fixture
  row uses, PATTERNS and SOIC_BODY included. Every verdict
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
    'SOT-5X3': ('SOT-583-8', 'TI\'s DRL package with 8 leads, "SOT-5X3" in TI\'s datasheets: JLCPCB C22399676 (TPS2117DRLR) lists SOT-5X3 '
                             'on a SOT-583-8 footprint (openair-max U7, a built board); KiCad Package_TO_SOT_SMD:SOT-583-8'),
    'SOT-5X3-5': ('SOT-553', 'TI\'s DRL with 5 leads: JLCPCB C2999113 (TPD3E001DRLR-TP) lists SOT-5X3-5 on a SOT-553 footprint '
                             '(royalblue54l-feather U3, a sold board); KiCad Package_TO_SOT_SMD:SOT-553'),
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
    'LQFN': ('QFN', False, 'JLCPCB C2040 (Raspberry Pi RP2040) lists LQFN-56(7x7); the RP2040 datasheet draws a 7x7 mm QFN-56 at 0.4 mm '
                           'pitch, KiCad QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm (the footprint on openjbod-rp2040 U1 and pocketpd U3, both built)'),
    'TDFN': ('DFN', False, 'JLCPCB C700968 (HSCC8233 dual MOSFET) lists TDFN-6-EP(2x3); the thin DFN-6 2x3 mm body is KiCad\'s '
                           'DFN-6-1EP_3x2mm_P0.5mm_EP1.65x1.35mm land pattern (sonatino Q3, a sold board)'),
}

# Spellings read by shape rather than by whole token -> where the shape was seen. Every reading made by one of
# these appears in Reading.via under its source, so the fixture test can tell an unused pattern from a used one.
PATTERNS = {
    'chip prefix': 'EasyEDA / JLCPCB-library footprint names put the reference letter in front of the chip size: easyeda2kicad:C0402 '
                   '(C1525 Samsung CL05B104KO5NNNC, openair-max C5), PCM_JLCPCB:R0805 (C2683107 ARG05BTC5233, jlcpcb-example R4), '
                   'PCM_JLCPCB:L0805 (C2885888 MLI2012F-1R5KT, jlcpcb-example L1), F1206 (C2685749 BSMD1206-200-16V fuse, openair-max F1)',
    'body-pins': 'Diodes Inc. writes the body size in tenths of a millimetre between the family and the pin count: '
                 'JLCPCB C5244513 (AP33772DKZ-13) lists WQFN4040-24, the datasheet\'s W-QFN4040-24 (4.0 x 4.0 mm, 24 pins) on '
                 'KiCad QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm (pocketpd U2, a sold board); a variant letter may follow the body: '
                 'C478121 (Diodes PUSB3F96X) lists DFN2510-10 on the EasyEDA footprint DFN2510A-10_L2.5-W1.0-P0.50-BL (cm5-minima D401)',
    'thin': 'TI\'s DDC package is "SOT-23-THIN" (JEDEC MO-193, the land pattern of SOT-23-6; see TSOT): JLCPCB C473912 '
            '(TPL5010DDCR) lists SOT-23-Thin-6 on a SOT-23-6 footprint (openair-max U3)',
    'bga layout': 'KiCad names a BGA by pin count, ball layout and body: BGA-24_5x5_6.0x8.0mm (KiCad 9) and '
                  'BGA-24_6x8mm_Layout5x5_P1.0mm (KiCad 10); the NxM without mm is the ball array, the one with mm the body. '
                  'JLCPCB C5448342 (APS256XXN-OBR-BG) lists BGA24_6X8 (soldiercrab U10, a sold board)',
    'crystal': 'JLCPCB writes SMD crystals as SMD<length><width>-<pins>P: C9010 (X322540MPB4SI) SMD3225-4P, C32346 (Epson '
               'Q13FC13500004) SMD3215-2P, C2682773 SMD2016-4P, C55208 SMD2012-2P, C669070 SMD2520-4P; KiCad\'s Crystal library '
               'names the same bodies Crystal_SMD_3225-4Pin_3.2x2.5mm, Crystal_SMD_3215-2Pin_3.2x1.5mm, Crystal_SMD_2016-4Pin_2.0x1.6mm, '
               'Crystal_SMD_2012-2Pin_2.0x1.2mm, Crystal_SMD_2520-4Pin_2.5x2.0mm',
    'tantalum case': 'EIA-535BAAC tantalum chip cases: JLCPCB C11366 (AVX TAJA226K010RNJ) lists CASE-A-3216-18(mm), KiCad '
                     'Capacitor_Tantalum_SMD:CP_EIA-3216-18_Kemet-A (openjbod-rp2040 C2, a built board)',
    'powerpad': 'TI puts "PowerPAD" (its exposed pad) before the pin count: KiCad Package_SO:TI_SO-PowerPAD-8 and '
                'TI_SO-PowerPAD-8_ThermalVias (TI DDA "SO PowerPAD", the package JLCPCB C841384 LMR33630ADDAR lists as ESOP-8 '
                'and C477928 LM5164DDAR as SO-8-EP; canfd-mc U3, a JLCPCB-assembled board)',
}
CHIP_PREFIX = re.compile(r'([CRLF])(\d{4})')                       # C0402, R0805, L0805, F1206
BODY_PINS = re.compile(r'([A-Z]+)(\d\d)(\d\d)[A-Z]?-(\d+)')        # WQFN4040-24, DFN2510A-10
THIN = re.compile(r'^-?THIN')                                      # SOT-23-THIN-6: the word between family and pin count
CRYSTAL_JLC = re.compile(r'SMD(\d{4})-(\d+)P')                      # SMD3225-4P
CRYSTAL_KICAD = re.compile(r'(\d{4})-(\d+)PIN')                     # Crystal_SMD_3225-4Pin_3.2x2.5mm
TANTALUM = re.compile(r'(?:EIA|CASE-[A-Z])-(\d{4})-(\d{2})')        # EIA-3216-18, CASE-A-3216-18
POWERPAD = re.compile(r'([A-Z]+)-(?:POWERPAD|EP)-(\d+)')           # SO-POWERPAD-8

# Pitch a family is taken at when its name states none -> (mm, source). Only where the standard fixes it.
STANDARD_PITCH = {
    'SOIC': (1.27, 'JEDEC MS-012 (narrow) and MS-013 (wide) SOIC: 1.27 mm; KiCad files 2.54 mm SOPs such as '
                   'SOP-8_6.62x9.15mm_P2.54mm (TI ISO1050) under the same family name, which the stated pitch tells apart'),
}

LEADED = {'SOIC', 'SSOP', 'TSSOP', 'MSOP', 'VSSOP', 'QSOP'}            # an exposed pad changes the land pattern
ARRAY = {'QFN', 'DFN', 'SON', 'WSON', 'VSON', 'UDFN', 'LGA', 'BGA', 'LFCSP', 'LQFP', 'TQFP', 'QFP'}      # LQFN, TDFN: FAMILIES
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
# SOIC body widths KiCad writes in a footprint name -> the mil class the catalogue names. 5.23 is KiCad 9's spelling of the
# 208 mil body (SOIC-8_5.23x5.23mm_P1.27mm, on openjbod-rp2040 U3 with C97521 W25Q128JVSIQ "SOIC-8-208mil"); KiCad 10 renamed
# it SOIC-8_5.3x5.3mm_P1.27mm.
SOIC_BODY = {'3.9': '150', '5.23': '208', '5.3': '208', '7.5': '300'}


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
    picked: str = ''           # the ambiguity (two land patterns under one name) the board's own footprint settled, when it did

    def as_dict(self):
        return {'verdict': self.verdict, 'rule': self.rule, 'footprint': list(self.footprint), 'part': list(self.part),
                'reason': self.reason, 'by_names': self.by_names or self.verdict, 'picked': self.picked,
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
    """The canonical name of a family token, or None; returns (name, family).

    Besides the plain ``FAMILY-pins`` form, three shapes from PATTERNS are read here: ``SO-POWERPAD-8`` (TI's
    exposed-pad word before the pin count), ``WQFN4040-24`` (Diodes' body size glued to the family) and
    ``SOT-23-THIN-6`` (TI's thickness word between family and pin count). Each is recorded in ``via``.
    """
    used = []                                   # PATTERNS keys this token needed
    body = None
    pp = POWERPAD.fullmatch(tok)
    if pp:
        fam, n, rest, ep = pp.group(1), pp.group(2), '', True
        used.append('powerpad')
    else:
        m = FAMILY_TOKEN.fullmatch(tok)
        if not m:
            return None, None
        fam, n, rest = m.groups()
        ep = False
        bp = BODY_PINS.fullmatch(tok)
        if bp and (FAMILIES.get(bp.group(1), (bp.group(1),))[0] in ARRAY):
            fam, n, rest = bp.group(1), bp.group(4), ''
            body = _size(f'{int(bp.group(2)) / 10:g}X{int(bp.group(3)) / 10:g}')
            used.append('body-pins')
    if fam in FAMILIES:
        canon, fam_ep, src = FAMILIES[fam]
        via.append((f'{fam}-{n}', f'{canon}-{n}', src))
        fam, ep = canon, ep or fam_ep
    name = None
    if fam in LEADED:
        ep = ep or bool(re.search(r'EP|POWERPAD', rest)) or any(re.fullmatch(r'EP\d.*|POWERPAD|THERMALPAD', t) for t in toks)
        name = f'{fam}-{n}'
        if fam == 'SOIC':
            mil = SOIC_MIL.search(' '.join([rest] + toks))
            width_class = next((SOIC_BODY[b] for b in SOIC_BODY for t in toks if SIZE.fullmatch(t) and t.startswith(b + 'X')), None)
            width = mil.group(1) if mil else (width_class or ('300' if rest.startswith('W') else '150'))
            if width != '150':
                name += f'-{width}MIL'
        name += '-EP' if ep else ''
    elif fam in ARRAY:
        size = body
        if size is None:
            cands = [(s, t.endswith('MM')) for t in toks[i + 1:i + 3] for s in [_size(t)] if s]
            if cands:
                size = cands[0][0]
                if fam == 'BGA' and not cands[0][1] and any(mm for _, mm in cands):
                    size = next(s for s, mm in cands if mm)          # BGA-24_5x5_6.0x8.0mm: 5x5 is the ball layout
                    used.append('bga layout')
        name = f'{fam}-{n}' + (f'({size})' if size else '')
    elif fam in OTHER:
        base = f'{fam}-{n}'
        if THIN.match(rest):
            rest = THIN.sub('', rest)
            used.append('thin')
        k = re.match(r'([A-Z]*)-?(\d*)', rest)
        letters, pins = k.group(1), k.group(2)
        if fam == 'SOD':
            name = base + letters
        else:
            if fam == 'TO':
                base += letters
            elif letters and not pins:          # SOT-23-6L, SOT-23L: a trailing L is a vendor's "lead" marker
                letters = ''
            name = f'{base}-{pins}' if pins and pins not in DEFAULT_PINS.get(base, set()) else base
    if name is None:
        return None, None
    for key in used:
        via.append((tok, name, PATTERNS[key]))
    return name, fam


def _dims(toks, leaded):
    """(pitch, width) a leaded family's tokens state: P0.65MM and the first figure of 4.4X5MM."""
    if not leaded:
        return None, None
    pitch = next((float(m.group(1)) for t in toks for m in [PITCH.fullmatch(t)] if m), None)
    width = next((float(m.group(1)) for t in toks for m in [BODY.fullmatch(t)] if m), None)
    return pitch, width


def _pattern(tok, toks):
    """(canonical name, PATTERNS key) for a token read by shape: a chip size behind its reference letter (C0402), a
    crystal body (SMD3225-4P, Crystal_SMD_3225-4Pin) or a tantalum case (CASE-A-3216-18, EIA-3216-18); else (None, None)."""
    m = CHIP_PREFIX.fullmatch(tok)
    if m and m.group(2) in CHIP:
        return m.group(2), 'chip prefix'
    m = CRYSTAL_JLC.fullmatch(tok) or ('CRYSTAL' in toks and CRYSTAL_KICAD.fullmatch(tok))
    if m:
        return f'SMD-{m.group(1)}-{m.group(2)}P', 'crystal'
    m = TANTALUM.fullmatch(tok)
    if m:
        return f'EIA-{m.group(1)}-{m.group(2)}', 'tantalum case'
    return None, None


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
            canon, key = _pattern(tok, toks)
            if canon:
                names.add(canon)
                via.append((tok, canon, PATTERNS[key]))
                continue
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
    INDEXED = re.compile(r'^(Package_|Diode_|Capacitor_|Resistor_|LED_SMD$|Inductor_SMD$|Fuse$|Crystal$)')

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


def _own_pick(library, ra, rb, pads_a, pads_b):
    """When the part string is ambiguous but the footprint side is one known library footprint (the board's own),
    the candidates its pads match, if they are all one land pattern, pick the reading: (entry, matched entry, pads).

    sh-rpi U401 (QFN-20-EP(3x3) on VQFN-20-1EP_3x3mm_P0.4mm_EP1.7x1.7mm), sonatino U13 (TSSOP-16 on
    TSSOP-16_4.4x5mm_P0.65mm) and U15 (SSOP-20 on SSOP-20_5.3x7.2mm_P0.65mm), all sold boards: the string does not
    say which pitch or width, the board does. None when the footprint side is not one footprint, or the matching
    candidates are more than one land pattern.
    """
    if len(ra.entries) != 1 or ra.ambiguity or len(pads_a) != 1:
        return None
    ea, pa = pads_a[0]
    hits = [(eb, pb) for eb, pb in pads_b if footprints.same_pads(pa, pb)[0]]
    if not hits:
        return None
    first = hits[0][1]
    if all(footprints.same_pads(first, pb)[0] for _, pb in hits[1:]):
        return ea, hits[0][0], len(pa)
    return None


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
        own = _own_pick(library, ra, rb, pads_a, pads_b) if r is rb else None
        if own:
            ea, eb, n = own
            note = '' if names.verdict == SAME else f'; by name {names.reason}'
            return Fit(SAME, names.footprint, names.part, f'pads match: {ea.name} and {eb.name} in the KiCad library ({n} pads); '
                       f'"{bare(text)}" names more than one land pattern ({r.ambiguity}) and the board\'s footprint is the {eb.name} one{note}',
                       names.via, PADS, names.verdict, r.ambiguity)
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
