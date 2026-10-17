"""KiCad's footprint libraries, read for pad geometry (pitfalls §1).

A footprint name and a catalogue package string can disagree in words and agree in copper (KiCad's
``TSOT-23-6`` and ``SOT-23-6`` have identical pads), or agree in words and disagree in copper (two
``QFN-20`` 4x4 footprints with exposed pads of 2.6 and 2.1 mm). The pads settle it, so where both sides of a
comparison resolve to footprints in KiCad's own library, ``packages.fits()`` compares their pads with this
module and lets the names only choose the candidates.

What is compared, per pad: SMD or through-hole, position, size, drill and whether the pad takes paste, each
within a small tolerance (``same_pads``), with the footprint tried in its four rotations. Pads without
copper (paste windows over an exposed pad) are not pads; pads with one number that touch are one pad, and
a via-in-pad hole with the exposed pad's number is not a pad (``stack``). Shapes (rect, roundrect, oval)
and pad numbers are otherwise not compared: the land pattern is the question here, the pin map is §3 and
stays by hand.

The library is found from ``--footprints``, ``$KICAD_FOOTPRINT_DIR``, the ``KICAD<n>_FOOTPRINT_DIR``
variables KiCad itself sets, or the install the ``kicad-cli`` in use belongs to. Without one, the gates
compare names only and say so.
"""
import os
import re
from dataclasses import dataclass

from . import sexpr

POSITION_TOLERANCE = 0.1      # mm; KiCad's QFN-16 and WQFN-16 3x3 footprints differ by 0.013
SIZE_TOLERANCE = 0.15         # mm; MSOP-8 and VSSOP-8 3x3 differ in pad width by 0.1, the 2.6 vs 2.1 mm exposed pads by 0.5
PITCH_TOLERANCE = 0.02        # mm; 0.635 (QSOP) and 0.65 (SSOP) are one pitch class

ENV_VARS = ('KICAD_FOOTPRINT_DIR', 'KICAD10_FOOTPRINT_DIR', 'KICAD9_FOOTPRINT_DIR')
CANDIDATE_ROOTS = (
    '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints',
    '/usr/share/kicad/footprints',
    '/usr/local/share/kicad/footprints',
    r'C:\Program Files\KiCad\10.0\share\kicad\footprints',
    r'C:\Program Files\KiCad\9.0\share\kicad\footprints',
)


@dataclass(frozen=True)
class Pad:
    kind: str          # smd, thru_hole, np_thru_hole
    x: float
    y: float
    w: float
    h: float
    drill: float       # 0 for SMD
    paste: bool

    def rotated(self, quarter_turns):
        x, y, w, h = self.x, self.y, self.w, self.h
        for _ in range(quarter_turns % 4):
            x, y, w, h = -y, x, h, w
        return Pad(self.kind, x, y, w, h, self.drill, self.paste)


def find_root(explicit=None, kicad_cli=None):
    """The footprints directory to read, or None. An explicit path that is not a directory is an error."""
    if explicit:
        if os.path.isdir(explicit):
            return explicit
        raise FileNotFoundError(f'--footprints {explicit}: not a directory')
    for var in ENV_VARS:
        d = os.environ.get(var)
        if d and os.path.isdir(d):
            return d
    if kicad_cli:                                        # .../KiCad.app/Contents/MacOS/kicad-cli -> .../Contents/SharedSupport/footprints
        contents = os.path.dirname(os.path.dirname(os.path.abspath(kicad_cli)))
        for d in (os.path.join(contents, 'SharedSupport', 'footprints'),
                  os.path.join(os.path.dirname(contents), 'share', 'kicad', 'footprints')):
            if os.path.isdir(d):
                return d
    for d in CANDIDATE_ROOTS:
        if os.path.isdir(d):
            return d
    return None


def libraries(root):
    """{library name: directory} for every <name>.pretty under root."""
    return {d[:-len('.pretty')]: os.path.join(root, d) for d in sorted(os.listdir(root)) if d.endswith('.pretty')}


def footprint_names(lib_dir):
    return sorted(f[:-len('.kicad_mod')] for f in os.listdir(lib_dir) if f.endswith('.kicad_mod'))


def path_of(root, lib_id):
    """The .kicad_mod file for ``Library:Name``, or None when the library or the footprint is not there."""
    lib, _, name = lib_id.rpartition(':')
    if not lib or not name:
        return None
    p = os.path.join(root, lib + '.pretty', name + '.kicad_mod')
    return p if os.path.isfile(p) else None


def _touch(a, b):
    """Two axis-aligned pads whose copper rectangles overlap or touch."""
    return (abs(a.x - b.x) <= (a.w + b.w) / 2 + 1e-6) and (abs(a.y - b.y) <= (a.h + b.h) / 2 + 1e-6)


def _inside(hole, pad):
    return abs(hole.x - pad.x) <= pad.w / 2 + 1e-6 and abs(hole.y - pad.y) <= pad.h / 2 + 1e-6


def stack(numbered):
    """One pad per piece of copper: SMD pads with the same number that touch or overlap are one pad (their
    bounding box, paste if any of them takes it); a through-hole pad with the same number whose centre lies in
    that copper is a thermal via in the pad, not a pad.

    TI's PowerPAD footprints draw the exposed pad as several stacked or tiled pads numbered 9, with via-in-pad
    holes numbered 9 (KiCad Package_SO:TI_SO-PowerPAD-8_ThermalVias: 19 pad entries, 9 pads; TI_SO-PowerPAD-8:
    four tiles for pad 9). ``numbered`` is [(number, Pad)]; pads without a number are left as they are.
    """
    out, groups = [], {}
    for n, p in numbered:
        if n == '':
            out.append(p)
        else:
            groups.setdefault(n, []).append(p)
    for n, pads in groups.items():
        smd = [p for p in pads if p.kind == 'smd']
        holes = [p for p in pads if p.kind != 'smd']
        merged = []
        while smd:
            group = [smd.pop(0)]
            grew = True
            while grew:
                grew = False
                for p in list(smd):
                    if any(_touch(p, g) for g in group):
                        group.append(p)
                        smd.remove(p)
                        grew = True
            if len(group) == 1:
                merged.append(group[0])
            else:
                x0, x1 = min(g.x - g.w / 2 for g in group), max(g.x + g.w / 2 for g in group)
                y0, y1 = min(g.y - g.h / 2 for g in group), max(g.y + g.h / 2 for g in group)
                merged.append(Pad('smd', round((x0 + x1) / 2, 6), round((y0 + y1) / 2, 6), round(x1 - x0, 6), round(y1 - y0, 6),
                                  0.0, any(g.paste for g in group)))
        out.extend(merged)
        out.extend(h for h in holes if not any(_inside(h, m) for m in merged))
    return tuple(out)


def read_pads(path):
    """The copper pads of a .kicad_mod file, as Pad tuples, stacked pads counted once (``stack``); raises OSError or
    ValueError for a bad file."""
    with open(path, encoding='utf-8') as f:
        root = sexpr.parse(f.read())
    if root[0] not in ('footprint', 'module'):
        raise ValueError(f'{path} is not a footprint file')
    pads = []
    for p in sexpr.children(root, 'pad'):
        atoms = sexpr.atoms(p)
        kind = atoms[1] if len(atoms) > 1 else 'smd'
        number = str(p[1]) if len(p) > 1 and not isinstance(p[1], list) else ''
        at = sexpr.child(p, 'at') or ['at', 0, 0]
        size = sexpr.child(p, 'size') or ['size', 0, 0]
        layers = [str(a) for a in (sexpr.child(p, 'layers') or [])[1:]]
        if not any(a.endswith('.Cu') for a in layers):
            continue                                    # a paste window or a mask-only aperture, not copper
        drill = sexpr.child(p, 'drill')
        d = 0.0
        if drill:
            nums = [sexpr.number(a) for a in drill[1:] if not isinstance(a, list) and a not in ('oval',)]
            d = max(nums) if nums else 0.0
        w, h = sexpr.number(size[1]), sexpr.number(size[2])
        rot = sexpr.number(at[3]) if len(at) > 3 else 0.0
        if abs(rot % 180 - 90) < 1e-6:
            w, h = h, w
        pads.append((number, Pad(kind, sexpr.number(at[1]), sexpr.number(at[2]), w, h, d, any(a.endswith('.Paste') for a in layers))))
    return stack(pads)


def _near(a, b, tol):
    return abs(a - b) <= tol + 1e-9


def _pad_differs(a, b):
    """None when two pads are one pad within tolerance, else what differs (for the report)."""
    if a.kind != b.kind:
        return f'{a.kind} against {b.kind}'
    if not (_near(a.x, b.x, POSITION_TOLERANCE) and _near(a.y, b.y, POSITION_TOLERANCE)):
        return f'position ({a.x:g}, {a.y:g}) against ({b.x:g}, {b.y:g})'
    if not (_near(a.w, b.w, SIZE_TOLERANCE) and _near(a.h, b.h, SIZE_TOLERANCE)):
        return f'size {a.w:g}x{a.h:g} against {b.w:g}x{b.h:g} at ({a.x:g}, {a.y:g})'
    if not _near(a.drill, b.drill, POSITION_TOLERANCE):
        return f'drill {a.drill:g} against {b.drill:g}'
    if a.paste != b.paste:
        return f'paste {"on" if a.paste else "off"} against {"on" if b.paste else "off"} at ({a.x:g}, {a.y:g})'
    return None


def _match(pads_a, pads_b):
    """None when every pad of a has one pad of b within tolerance and vice versa, else the first difference."""
    free = list(pads_b)
    for a in pads_a:
        best, best_why = None, None
        for i, b in enumerate(free):
            if _near(a.x, b.x, POSITION_TOLERANCE) and _near(a.y, b.y, POSITION_TOLERANCE):
                why = _pad_differs(a, b)
                if why is None:
                    best = i
                    break
                best_why = best_why or why
        if best is None:
            return best_why or f'no pad near ({a.x:g}, {a.y:g})'
        free.pop(best)
    return None


def same_pads(pads_a, pads_b):
    """(True, '') when the two pad sets are one land pattern within tolerance, in any of four rotations;
    (False, why) otherwise. Pad count must agree exactly: an exposed pad is a pad (a via inside it is not: ``stack``)."""
    if len(pads_a) != len(pads_b):
        return False, f'{len(pads_a)} pads against {len(pads_b)}'
    if not pads_a:
        return False, 'no pads on either side'
    first = None
    for q in range(4):
        why = _match(pads_a, tuple(p.rotated(q) for p in pads_b))
        if why is None:
            return True, ''
        first = first or why
    return False, first


PITCH_IN_NAME = re.compile(r'(?:^|_)P(\d+(?:\.\d+)?)MM(?:_|$)')
BODY_IN_NAME = re.compile(r'(?:^|_)(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)(?:X\d+(?:\.\d+)?)?MM(?:_|$)')


def dims_in_name(name):
    """(pitch, body width) in mm as a KiCad footprint name states them (``_P0.65mm``, ``_4.4x5mm``), None where absent."""
    up = name.upper()
    p, b = PITCH_IN_NAME.search(up), BODY_IN_NAME.search(up)
    return (float(p.group(1)) if p else None), (float(b.group(1)) if b else None)
