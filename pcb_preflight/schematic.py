"""What the gate needs from a .kicad_sch: the identity of every placed symbol, across every sheet.

A footprint on the board carries ``(path "/<root sheet uuid>[/<sub-sheet uuid>...]/<symbol uuid>")``, the
schematic symbol it was made from. When a generator rewrites the schematic, every symbol gets a new uuid
and every footprint on the board points at a symbol that no longer exists (pitfalls §5); KiCad's parity
test, which matches by reference, does not see it. ``load_symbols()`` reads the symbols so the gate can.
"""
import os
from dataclasses import dataclass, field

from . import sexpr


@dataclass
class Symbol:
    uuid: str
    ref: str                                # the Reference property (the last one KiCad wrote)
    lib_id: str
    sheet_file: str
    on_board: bool = True                   # (on_board no): the symbol is kept off the board on purpose
    instances: dict = field(default_factory=dict)   # sheet path ("/<root uuid>/...") -> reference on that sheet

    @property
    def references(self):
        """Every reference this symbol carries: one per sheet instance, else the property."""
        return [r for r in (list(self.instances.values()) or [self.ref]) if r]


def _prop(node, name):
    for p in sexpr.children(node, 'property'):
        if len(p) >= 3 and p[1] == name:
            return p[2]
    return ''


def _flag(node, key, default=True):
    n = sexpr.child(node, key)
    return default if not n or len(n) < 2 else n[1] != 'no'


def load_symbols(root_sch):
    """{symbol uuid: Symbol} for every symbol placed on the root sheet and every sheet it references.

    Raises OSError for a sheet file that cannot be read and ValueError for one that is not a schematic.
    """
    symbols = {}
    seen = set()
    todo = [os.path.abspath(root_sch)]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        with open(path, encoding='utf-8') as f:
            root = sexpr.parse(f.read())
        if root[0] != 'kicad_sch':
            raise ValueError(f'{path} is not a kicad_sch file')
        for s in sexpr.children(root, 'symbol'):          # placed symbols only; lib_symbols is one level down
            u = sexpr.child(s, 'uuid')
            if not u or len(u) < 2:
                continue
            sym = Symbol(uuid=u[1], ref=_prop(s, 'Reference'), lib_id=(sexpr.child(s, 'lib_id') or ['', ''])[1],
                         sheet_file=os.path.basename(path), on_board=_flag(s, 'on_board'))
            for proj in sexpr.children(sexpr.child(s, 'instances') or [], 'project'):
                for p in sexpr.children(proj, 'path'):
                    ref = sexpr.child(p, 'reference')
                    if len(p) >= 2 and ref and len(ref) >= 2:
                        sym.instances[p[1]] = ref[1]
            symbols[sym.uuid] = sym
        for sh in sexpr.children(root, 'sheet'):
            fn = _prop(sh, 'Sheetfile') or _prop(sh, 'Sheet file')
            if fn:
                todo.append(os.path.normpath(os.path.join(os.path.dirname(path), fn)))
    return symbols
