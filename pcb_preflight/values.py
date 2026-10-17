"""The BOM line's Value and reference, against the schematic and the catalogue record (pitfalls §1 §2).

Three small readers, each returning plain data for checks.py:

normalize(text)
  One spelling for a value: NFKC, µ and μ become u, Ω and "ohm" become R, RKM figures are expanded
  (4k7 -> 4.7k, 2u2 -> 2.2u), then no spaces and lower case. "10uF", "10 µF" and "10µF" normalise alike,
  as do "100R", "100Ω" and "100 ohm". Nothing else is inferred: 100nF and 0.1uF stay two spellings, and the
  schematic and bom.csv are expected to use one.

quantities(text, resistor=False)
  The figures a value or a catalogue description states, as {unit: [floats]} for the units F, H, Ω and V:
  "100nF 50V X7R" -> {'F': [1e-7], 'V': [50.0]}; "60Ω@100MHz 6A 9mΩ ±25% 1806 Ferrite Beads" -> {'Ω': [60, 0.009]}.
  A figure with a magnitude but no unit ("22k", "4k7", "1M") is an ohm value on a resistor line only; everywhere
  else it is left alone. A figure glued to a sign or an identifier is not read either: "+12V" in "green +12V" is
  the net the LED shows, "-100M" in SRP1245A-100M is a part number. Figures with other units (A, W, Hz, mm,
  ℃, %) are not read.

compare(value, description, resistor=False)
  For every unit the bom.csv value states that the description also states: F, H and Ω must agree within
  1 % with one of the description's figures; for V the catalogue's highest figure must reach the value's
  (a 25 V part on a "100uF 16V" line fits, a 16 V part on a "100uF 25V" line does not). A unit the
  description does not state is not checked, and says so.

prefix_class(ref) and category_fits(prefix, category, description)
  The reference prefix (C, R, D, LED, L, FB, U, Q, J, F, Y, SW) against the catalogue's category text, from
  PREFIXES and CLASSES below: every keyword names the JLCPCB record it was seen in, and
  tests/fixtures/catalogue.csv holds those records. U (an IC) is the one negative rule: its category must
  not be a passive, discrete or electromechanical class; "array", "driver" and "module" categories are
  exempt from the diode/transistor test (a Darlington array is a U). With a jlcsearch record, which has no
  category field, the description is searched instead, except for U, which is then not checked.
"""
import re
import unicodedata

PERCENT_TOLERANCE = 0.01

MAGNITUDE = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'm': 1e-3, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'G': 1e9}
UNITS = {'F': 'F', 'f': 'F', 'H': 'H', 'h': 'H', 'V': 'V', 'v': 'V', 'Ω': 'Ω', 'ohm': 'Ω', 'ohms': 'Ω', 'R': 'Ω'}

# A figure glued to a sign or an identifier is a net name (+12V, +5V_PI) or a part number (SRP1245A-100M), not a rating.
FIGURE = re.compile(r'(?<![\w.+-])(\d+(?:\.\d+)?)\s*([pnumkKMG])?\s*(F|f|H|h|V|v|Ω|ohms|ohm|R)?(?![A-Za-z0-9_])')
RKM = re.compile(r'(?<![a-z0-9.])(\d+)([kmrupn])(\d+)(?![a-z0-9])')


def _ascii_units(s):
    return unicodedata.normalize('NFKC', s).replace('µ', 'u').replace('μ', 'u').replace('Ω', 'Ω').replace('Ω', 'Ω')


def normalize(text):
    """One spelling for a value (see the module docstring); '' for None or blank."""
    s = _ascii_units(text or '').lower()
    s = re.sub(r'(?<=\d)\s*(ohms?|ω)(?![a-z])', 'r', s)
    s = RKM.sub(r'\1.\3\2', s)
    return re.sub(r'\s+', '', s)


def quantities(text, resistor=False):
    """{unit: [figures]} for F, H, Ω and V stated in ``text`` (see the module docstring)."""
    out = {}
    s = _ascii_units(text or '')
    s = RKM.sub(r'\1.\3\2', s)
    for m in FIGURE.finditer(s):
        num, mag, unit = m.groups()
        if unit is None:
            if not (resistor and mag in ('k', 'K', 'M')):
                continue
            unit = 'Ω'
        u = UNITS[unit]
        out.setdefault(u, []).append(float(num) * MAGNITUDE.get(mag or '', 1.0))
    return out


def _fmt(x, unit):
    for mag, f in (('G', 1e9), ('M', 1e6), ('k', 1e3), ('', 1.0), ('m', 1e-3), ('u', 1e-6), ('n', 1e-9), ('p', 1e-12)):
        if x >= f * 0.9999:
            return f'{x / f:g}{mag}{unit}'
    return f'{x:g}{unit}'


def compare(value, description, resistor=False):
    """(mismatches, unchecked, agreed): what the bom.csv value and the catalogue description say about F, H, Ω, V."""
    mine, theirs = quantities(value, resistor), quantities(description, resistor)
    mismatches, unchecked, agreed = [], [], []
    for unit, figures in sorted(mine.items()):
        have = theirs.get(unit)
        if not have:
            unchecked.append(f'the catalogue description states no {"voltage" if unit == "V" else unit} figure to compare with {_fmt(max(figures), unit)}')
            continue
        if unit == 'V':
            want, top = max(figures), max(have)
            if top + 1e-9 < want * (1 - PERCENT_TOLERANCE):
                mismatches.append(f'bom.csv asks for {_fmt(want, "V")} but the catalogue part is rated {_fmt(top, "V")}')
            else:
                agreed.append(f'{_fmt(want, "V")} (part rated {_fmt(top, "V")})')
            continue
        for x in figures:
            hit = next((y for y in have if abs(x - y) <= PERCENT_TOLERANCE * max(abs(x), abs(y))), None)
            if hit is None:
                mismatches.append(f'bom.csv says {_fmt(x, unit)} but the catalogue description says {", ".join(_fmt(y, unit) for y in have)}')
            else:
                agreed.append(_fmt(x, unit))
    return mismatches, unchecked, agreed


# ---------------------------------------------------------------- reference prefix against catalogue category

# Category keywords -> where each was seen (a JLCPCB record's firstSortName / secondSortName, in tests/fixtures/catalogue.csv).
CLASSES = {
    'capacitor': {'capacitor': 'C14663 Capacitors / Multilayer Ceramic Capacitors MLCC - SMD/SMT; C72477 Aluminum Electrolytic Capacitors - SMD'},
    'resistor': {'resistor': 'C25804 Resistors / Chip Resistor - Surface Mount'},
    'diode': {'diode': 'C8678 Diodes / Schottky Diodes', 'tvs': 'C315992 Circuit Protection / ESD and Surge Protection (TVS/ESD)',
              'esd': 'C315992 Circuit Protection / ESD and Surge Protection (TVS/ESD)'},
    'led': {'led': 'C2297 Optoelectronics / LED Indication - Discrete'},
    'inductor': {'inductor': 'C2042471 Inductors, Coils, Chokes / Power Inductors'},
    'ferrite': {'ferrite': 'C85844 Filters / Ferrite Beads'},
    'transistor': {'transistor': 'C8512 Transistors/Thyristors / Bipolar (BJT); C2620 Transistors/Thyristors / MOSFETs',
                   'mosfet': 'C2620 ... MOSFETs (the description names only the second sort)', 'bjt': 'C8512 ... Bipolar (BJT)'},
    'connector': {'connector': 'C144397 Connectors / Wire To Board Connector'},
    'fuse': {'fuse': 'C151074 Circuit Protection / Fuseholders; C3761525 Circuit Protection / Resettable Fuses'},
    'crystal': {'crystal': 'C9002 Crystals, Oscillators, Resonators / Crystals (YXC X322512MSB4SI)'},
    'switch': {'switch': 'C55213946 Switches / Tactile Switches (SHOU HAN TS6635PA)'},
}

# Reference prefix -> classes its catalogue category may belong to. 'U' is the negative rule (see category_fits).
PREFIXES = {
    'C': ('capacitor',), 'R': ('resistor',), 'D': ('diode', 'led'), 'LED': ('led',), 'L': ('inductor', 'ferrite'),
    'FB': ('ferrite', 'inductor'), 'Q': ('transistor',), 'J': ('connector',), 'F': ('fuse',), 'Y': ('crystal',), 'SW': ('switch',),
    'U': (),
}
IC = 'U'
NOT_AN_IC = ('capacitor', 'resistor', 'inductor', 'ferrite', 'connector', 'fuse', 'crystal', 'diode', 'transistor')
IC_EXEMPT = ('array', 'driver', 'module')          # "Darlington Transistor Arrays", "LED Drivers", "MOSFET driver" are ICs
_SEMICONDUCTOR = ('diode', 'transistor')


def prefix_of(ref):
    """The letters a reference starts with: C1 -> C, LED3 -> LED, FB1 -> FB, #PWR01 -> #PWR."""
    return re.match(r'[^\d]*', ref.strip()).group(0).upper()


def _has(keyword, text):
    """The keyword starts a word of the text: "Fuseholders", "Switches" and "LED" count, "Shielded" and "Coupled" do not."""
    return re.search(r'(?<![a-z])' + re.escape(keyword), text, re.I) is not None


def _classes_in(text):
    return [cls for cls, kws in CLASSES.items() if any(_has(k, text) for k in kws)]


def category_fits(prefix, category, description=''):
    """('ok' | 'mismatch' | 'unchecked', explanation) for a reference prefix against a catalogue record's category.

    ``category`` is the JLCPCB record's "first sort / second sort" text; when it is empty (a jlcsearch record)
    the description is searched instead, except for U, which needs the category.
    """
    text = (category or '').strip()
    source = 'category'
    if not text:
        if prefix == IC:
            return 'unchecked', 'the record carries no category, and an IC is told from its category alone'
        text, source = (description or '').strip(), 'description'
        if not text:
            return 'unchecked', 'the record carries neither a category nor a description'
    if prefix not in PREFIXES:
        return 'unchecked', f'prefix {prefix} has no category rule (known: {", ".join(sorted(PREFIXES))})'
    found = _classes_in(text)
    if prefix == IC:
        bad = [c for c in found if c in NOT_AN_IC and not (c in _SEMICONDUCTOR and any(_has(w, text) for w in IC_EXEMPT))]
        if bad:
            return 'mismatch', f'U is an IC reference but the catalogue files this part under "{text}" ({"/".join(bad)})'
        return 'ok', f'IC: catalogue {source} "{text}" is no passive, discrete or electromechanical class'
    want = PREFIXES[prefix]
    if any(c in want for c in found):
        return 'ok', f'{prefix}: catalogue {source} "{text}"'
    return 'mismatch', f'{prefix} is a {"/".join(want)} reference but the catalogue files this part under "{text}"'
