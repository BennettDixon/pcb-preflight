"""What the gate needs from a .kicad_pcb: footprints, layers, fiducials, origin, silkscreen text."""
import os
import re
from dataclasses import dataclass, field

from . import sexpr

SILK = ('F.SilkS', 'B.SilkS', 'F.Silkscreen', 'B.Silkscreen')


@dataclass
class Footprint:
    ref: str
    value: str
    lib_id: str
    layer: str
    x: float
    y: float
    rot: float
    attrs: set = field(default_factory=set)
    value_layer: str = ''
    value_hidden: bool = False
    pads: int = 0

    @property
    def dnp(self):
        return 'dnp' in self.attrs

    @property
    def excluded_from_bom(self):
        return 'exclude_from_bom' in self.attrs

    @property
    def is_fiducial(self):
        return 'fiducial' in self.lib_id.lower() or self.ref.upper().startswith('FID')

    @property
    def package(self):
        return self.lib_id.split(':', 1)[-1]


@dataclass
class Board:
    path: str
    generator_version: str
    copper_layers: int
    aux_origin: tuple
    footprints: list
    silk_texts: list      # (text, x, y, layer)
    title_rev: str
    title_title: str


def load(path):
    with open(path, encoding='utf-8') as f:
        root = sexpr.parse(f.read())
    if root[0] != 'kicad_pcb':
        raise ValueError(f'{path} is not a kicad_pcb file')
    gen = sexpr.child(root, 'generator_version')
    layers_node = sexpr.child(root, 'layers') or []
    copper = 0
    for ln in layers_node[1:]:
        if isinstance(ln, list) and len(ln) >= 3 and str(ln[1]).endswith('.Cu') and ln[2] in ('signal', 'power', 'mixed', 'jumper'):
            copper += 1
    setup = sexpr.child(root, 'setup') or []
    aux = sexpr.child(setup, 'aux_axis_origin')
    aux_origin = (sexpr.number(aux[1]), sexpr.number(aux[2])) if aux and len(aux) >= 3 else None
    tb = sexpr.child(root, 'title_block') or []
    rev = sexpr.child(tb, 'rev')
    title = sexpr.child(tb, 'title')

    fps = []
    for fp in sexpr.children(root, 'footprint'):
        at = sexpr.child(fp, 'at') or ['at', 0, 0, 0]
        props = {}
        for p in sexpr.children(fp, 'property'):
            if len(p) >= 3 and not isinstance(p[1], list):
                props[p[1]] = p
        ref = props.get('Reference', ['', '', ''])[2]
        val_node = props.get('Value', ['', '', ''])
        val_layer = (sexpr.child(val_node, 'layer') or ['', ''])[1] if len(val_node) > 3 else ''
        hide = sexpr.child(val_node, 'hide') if len(val_node) > 3 else None
        attrs = set()
        for a in sexpr.children(fp, 'attr'):
            attrs.update(sexpr.atoms(a))
        fps.append(Footprint(
            ref=ref, value=val_node[2], lib_id=fp[1], layer=(sexpr.child(fp, 'layer') or ['', ''])[1],
            x=sexpr.number(at[1]), y=sexpr.number(at[2]), rot=sexpr.number(at[3]) if len(at) > 3 else 0.0,
            attrs=attrs, value_layer=val_layer, value_hidden=bool(hide and len(hide) > 1 and hide[1] == 'yes'),
            pads=len(sexpr.children(fp, 'pad'))))

    texts = []
    for t in sexpr.children(root, 'gr_text'):
        at = sexpr.child(t, 'at') or ['at', 0, 0]
        layer = (sexpr.child(t, 'layer') or ['', ''])[1]
        texts.append((t[1], sexpr.number(at[1]), sexpr.number(at[2]), layer))

    return Board(path=path, generator_version=gen[1] if gen else '', copper_layers=copper, aux_origin=aux_origin,
                 footprints=fps, silk_texts=[t for t in texts if t[3] in SILK],
                 title_rev=rev[1] if rev and len(rev) > 1 else '', title_title=title[1] if title and len(title) > 1 else '')


REV_RE = re.compile(r'(?i)(?<![\w.])(v\d+(?:\.\d+)*|rev\.?\s*[\w.]+|\$\{REVISION\})(?![\w.])')


def rev_on_silk(board):
    return [t[0] for t in board.silk_texts if REV_RE.search(t[0])]


def name_on_silk(board, name):
    n = name.lower()
    return [t[0] for t in board.silk_texts if n in t[0].lower() or '${TITLE}' in t[0]]


def connectors_without_silk_name(board, radius=15.0):
    """Connectors (J*) whose value is not visible on silkscreen and have no silk text within ``radius`` mm."""
    out = []
    for fp in board.footprints:
        if not fp.ref.upper().startswith('J') or fp.dnp:
            continue
        if fp.value_layer in SILK and not fp.value_hidden:
            continue
        near = [t for t in board.silk_texts if abs(t[1] - fp.x) <= radius and abs(t[2] - fp.y) <= radius]
        if not near:
            out.append(fp)
    return out


POLAR_PREFIX = ('D', 'Q', 'U', 'J', 'L', 'Y')


def polarized_or_asymmetric(board):
    out = []
    for fp in board.footprints:
        if fp.dnp or fp.is_fiducial or fp.ref.upper().startswith(('TP', 'H', 'FID')):
            continue
        r = fp.ref.rstrip('0123456789')
        if r.upper() in POLAR_PREFIX or r.upper() in ('LED', 'IC', 'SW', 'F', 'FB'):
            out.append(fp)
        elif r.upper() == 'C' and ('CP_' in fp.package or 'Polar' in fp.package or 'Tantal' in fp.package):
            out.append(fp)
    return out


def project_name(project_dir, explicit=None):
    if explicit:
        return explicit
    pros = sorted(f for f in os.listdir(project_dir) if f.endswith('.kicad_pro'))
    if len(pros) == 1:
        return pros[0][:-len('.kicad_pro')]
    if not pros:
        raise FileNotFoundError(f'no .kicad_pro in {project_dir}')
    raise ValueError(f'several projects in {project_dir} ({", ".join(pros)}); pass --project')
