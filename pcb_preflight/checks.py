"""The gates. Each returns a Check; cli.py runs them in order and report.py prints them.

Status: pass = checked and left alone; fail = finding that blocks the order; warn = finding to look at;
skip = could not be checked (never silently counted as a pass).
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import bom as bomlib
from . import board as boardlib
from . import kicad, stock


@dataclass
class Check:
    id: str
    title: str
    pitfall: str
    status: str
    summary: str
    details: list = field(default_factory=list)

    def as_dict(self):
        return {'id': self.id, 'title': self.title, 'pitfall': self.pitfall, 'status': self.status,
                'summary': self.summary, 'details': self.details}


DEFAULT_SKIP_PREFIXES = ('FID', 'TP', 'H', 'MH', '#')


def _skip_ref(ref, prefixes):
    r = ref.upper()
    return any(r.startswith(p) and (len(r) == len(p) or r[len(p):].isdigit()) for p in prefixes)


# ---------------------------------------------------------------- KiCad's own checks

def erc_check(report):
    viol = [v for s in report.get('sheets', []) for v in s.get('violations', [])]
    errors, warnings = kicad.count_severities(viol)
    n = len(report.get('sheets', []))
    det = [kicad.describe(v) for v in errors] + [f'warning: {kicad.describe(v)}' for v in warnings]
    status = 'fail' if errors else ('warn' if warnings else 'pass')
    return Check('erc', 'ERC', '§12', status, f'{len(errors)} errors, {len(warnings)} warnings on {n} sheet{"s" if n != 1 else ""}', det)


def drc_check(report):
    errors, warnings = kicad.count_severities(report.get('violations', []))
    types = Counter(v.get('type') for v in errors + warnings)
    kinds = ', '.join(f'{t} x{c}' for t, c in types.most_common())
    det = [kicad.describe(v) for v in errors] + [f'warning: {kicad.describe(v)}' for v in warnings]
    status = 'fail' if errors else ('warn' if warnings else 'pass')
    return Check('drc', 'DRC', '§12', status, f'{len(errors)} errors, {len(warnings)} warnings' + (f' ({kinds})' if kinds else ''), det)


def unrouted_check(report):
    items = report.get('unconnected_items', [])
    det = [kicad.describe(v) for v in items]
    return Check('unrouted', 'Unrouted connections', '§11 §12', 'fail' if items else 'pass',
                 f'{len(items)} connections still to route', det)


def parity_check(report, cli_output, n_footprints):
    if 'Failed to fetch schematic netlist' in cli_output or 'parity tests require' in cli_output:
        reason = next((ln.strip() for ln in cli_output.splitlines() if 'netlist' in ln or 'parity' in ln), cli_output)
        return Check('parity', 'Schematic / PCB parity', '§5', 'skip', f'kicad-cli could not run it: {reason}')
    items = report.get('schematic_parity', [])
    errors = [v for v in items if v.get('severity') == 'error']
    warnings = [v for v in items if v.get('severity') != 'error']
    det = [kicad.describe(v) for v in errors] + [f'warning: {kicad.describe(v)}' for v in warnings]
    status = 'fail' if errors else ('warn' if warnings else 'pass')
    return Check('parity', 'Schematic / PCB parity', '§5', status,
                 f'{len(errors)} mismatches, {len(warnings)} warnings across {n_footprints} footprints', det)


# ---------------------------------------------------------------- the board file

def fiducial_check(board):
    fids = [fp for fp in board.footprints if fp.is_fiducial]
    front = [fp for fp in fids if fp.layer == 'F.Cu']
    names = ', '.join(fp.ref for fp in fids)
    if len(front) >= 3:
        return Check('fiducials', 'Fiducials', '§4', 'pass', f'{len(front)} on the front ({names})')
    return Check('fiducials', 'Fiducials', '§4', 'warn',
                 f'{len(front)} on the front, the fab\'s placement preview wants 3' + (f' ({names})' if names else ''))


def origin_check(board):
    if board.aux_origin and board.aux_origin != (0.0, 0.0):
        return Check('origin', 'Placement origin', '§4', 'pass', f'aux axis origin at {board.aux_origin[0]:g}, {board.aux_origin[1]:g} mm')
    return Check('origin', 'Placement origin', '§4', 'warn', 'no aux axis origin set; set it at a board corner so the position file and drills share one origin')


def layer_check(board):
    n = board.copper_layers
    power = [fp for fp in board.footprints if fp.ref.rstrip('0123456789').upper() == 'L' and not fp.dnp]
    if n <= 2 and power:
        return Check('layers', 'Copper layers', '§9', 'warn',
                     f'{n} copper layers with {len(power)} inductor(s) ({", ".join(fp.ref for fp in power)}): a switching regulator at hobby sizes wants 4')
    return Check('layers', 'Copper layers', '§9', 'pass', f'{n} copper layers')


def silk_check(board, name):
    revs = boardlib.rev_on_silk(board)
    names = boardlib.name_on_silk(board, name)
    det = []
    if not revs:
        det.append('no revision text (like "v0.6") on a silkscreen layer')
    if not names:
        det.append(f'no board name ("{name}") on a silkscreen layer')
    if det:
        return Check('silk', 'Board name and revision on silk', '§10', 'warn', '; '.join(det), [f'silk texts: {", ".join(t[0] for t in board.silk_texts[:12])}'] if board.silk_texts else [])
    return Check('silk', 'Board name and revision on silk', '§10', 'pass', f'name "{names[0]}", revision "{revs[0]}"')


def connector_check(board):
    missing = boardlib.connectors_without_silk_name(board)
    n = sum(1 for fp in board.footprints if fp.ref.upper().startswith('J') and not fp.dnp)
    if missing:
        return Check('connector-names', 'Connector names on silk', '§8', 'warn',
                     f'{len(missing)} of {n} connectors have neither a visible value nor silk text within 15 mm',
                     [f'{fp.ref} {fp.value} at {fp.x:g}, {fp.y:g}' for fp in missing])
    return Check('connector-names', 'Connector names on silk', '§8', 'pass', f'{n} connectors each have a name on silk')


def dnp_board_check(board, sch_rows):
    sch_dnp = {r['Ref'] for r in sch_rows if r['DNP']}
    on_board = {fp.ref for fp in board.footprints}
    gone = sorted(sch_dnp - on_board)
    board_dnp = {fp.ref for fp in board.footprints if fp.dnp}
    unflagged = sorted(sch_dnp - board_dnp - set(gone))
    det = ([f'DNP in the schematic but no footprint on the board: {", ".join(gone)}'] if gone else []) + \
          ([f'DNP in the schematic but not flagged DNP on the board (update PCB from schematic): {", ".join(unflagged)}'] if unflagged else [])
    if det:
        return Check('dnp', 'DNP parts', '§12', 'fail', f'{len(gone) + len(unflagged)} DNP parts inconsistent between schematic and board', det)
    return Check('dnp', 'DNP parts', '§12', 'pass', f'{len(sch_dnp)} DNP parts flagged on both schematic and board' + (f' ({", ".join(sorted(sch_dnp))})' if sch_dnp else ''))


# ---------------------------------------------------------------- bom.csv

def purchasable(sch_rows, skip_prefixes):
    return {r['Ref']: r for r in sch_rows if not r['DNP'] and not r['ExcludeFromBOM'] and not _skip_ref(r['Ref'], skip_prefixes)}


def bom_columns_check(missing_cols, path):
    if missing_cols:
        return Check('bom-columns', 'bom.csv columns', '§1', 'fail', f'{path} lacks columns: {", ".join(missing_cols)}',
                     ['expected: ' + ', '.join(bomlib.REQUIRED)])
    return Check('bom-columns', 'bom.csv columns', '§1', 'pass', f'all {len(bomlib.REQUIRED)} columns present')


def bom_lcsc_check(lines):
    bad = [ln for ln in lines if not bomlib.LCSC_RE.match(ln.lcsc)]
    if bad:
        return Check('bom-lcsc', 'LCSC code on every BOM line', '§1 §12', 'fail',
                     f'{len(bad)} of {len(lines)} lines have no LCSC code (a value and a package is not a part)',
                     [ln.label + (f' [has "{ln.lcsc}"]' if ln.lcsc else '') for ln in bad])
    return Check('bom-lcsc', 'LCSC code on every BOM line', '§1 §12', 'pass', f'{len(lines)} lines, each with a C-number')


def bom_fields_check(lines):
    problems = []
    for ln in lines:
        gaps = []
        if not ln.mpn:
            gaps.append('MPN')
        if not ln.package:
            gaps.append('Package')
        if not bomlib.library_type(ln.library):
            gaps.append('Basic/Extended' if not ln.library else f'Basic/Extended ("{ln.library}" is not Basic, Extended or Preferred)')
        if ln.stock_number is None:
            gaps.append('Stock')
        if not ln.datasheet:
            gaps.append('Datasheet')
        if gaps:
            problems.append(f'{ln.label}: missing {", ".join(gaps)}')
    if problems:
        return Check('bom-fields', 'BOM lines complete', '§1 §2', 'warn', f'{len(problems)} of {len(lines)} lines are not "done" (MPN, package, Basic/Extended, stock, datasheet)', problems)
    return Check('bom-fields', 'BOM lines complete', '§1 §2', 'pass', f'{len(lines)} lines carry MPN, package, library type, stock and datasheet')


def bom_refs_check(lines, sch_rows, skip_prefixes):
    wanted = purchasable(sch_rows, skip_prefixes)
    dnp = {r['Ref'] for r in sch_rows if r['DNP']}
    all_sch = {r['Ref'] for r in sch_rows}
    in_bom = Counter(ref for ln in lines for ref in ln.refs)
    missing = sorted(set(wanted) - set(in_bom))
    unknown = sorted(r for r in in_bom if r not in all_sch)
    dupes = sorted(r for r, c in in_bom.items() if c > 1)
    listed_dnp = sorted(r for r in in_bom if r in dnp)
    det = []
    if missing:
        det.append(f'in the schematic but not in bom.csv: {", ".join(missing)}')
    if unknown:
        det.append(f'in bom.csv but not in the schematic: {", ".join(unknown)}')
    if dupes:
        det.append(f'listed twice in bom.csv: {", ".join(dupes)}')
    if listed_dnp:
        det.append(f'DNP in the schematic but listed in bom.csv (the fab would place them): {", ".join(listed_dnp)}')
    if det:
        return Check('bom-refs', 'bom.csv matches the schematic', '§1 §5 §12', 'fail',
                     f'{len(missing)} missing, {len(unknown)} unknown, {len(dupes)} duplicate, {len(listed_dnp)} DNP references', det)
    return Check('bom-refs', 'bom.csv matches the schematic', '§1 §5 §12', 'pass',
                 f'{len(wanted)} purchasable references, every one on exactly one BOM line')


def bom_package_check(lines, sch_rows):
    fp_of = {r['Ref']: r['Footprint'] for r in sch_rows}
    det = []
    compared = 0
    for ln in lines:
        want = bomlib.package_token(ln.package)
        if not want:
            continue
        for ref in ln.refs:
            have = bomlib.package_token(fp_of.get(ref, ''))
            if have:
                compared += 1
                if have != want:
                    det.append(f'{ref}: bom.csv says {ln.package} ({want}); the schematic footprint is {fp_of[ref]} ({have})')
    if det:
        return Check('bom-package', 'BOM package matches the footprint', '§1', 'fail', f'{len(det)} references whose chosen part does not fit the footprint on the board', det)
    return Check('bom-package', 'BOM package matches the footprint', '§1', 'pass', f'{compared} references with a comparable package name agree with their footprint')


# ---------------------------------------------------------------- the catalogue (online)

def _norm_mpn(s):
    return re.sub(r'[\s\-_/,.]', '', s).upper()


def stock_check(lines, multiple=10, lookup=stock.lookup):
    by_code = defaultdict(list)
    for ln in lines:
        if bomlib.LCSC_RE.match(ln.lcsc):
            by_code[ln.lcsc].append(ln)
    if not by_code:
        return Check('stock', 'Catalogue and stock', '§1 §2 §13', 'skip', 'no line has an LCSC code to look up')
    fails, warns, skips, ok = [], [], [], []
    extended = set()
    for code, lns in sorted(by_code.items()):
        qty = sum(len(ln.refs) for ln in lns)
        label = f'{code} ({", ".join(r for ln in lns for r in ln.refs)})'
        try:
            rec = lookup(code)
        except stock.LookupFailed as e:
            skips.append(f'{label}: lookup failed ({e})')
            continue
        if rec is None:
            fails.append(f'{label}: not in the JLCPCB catalogue; the code is wrong or the part was retired')
            continue
        n = rec.get('stock')
        if n is None:
            skips.append(f'{label}: catalogue gave no stock figure')
        elif n == 0:
            fails.append(f'{label}: out of stock at JLCPCB ({rec["mpn"]})')
        elif n < multiple * qty:
            warns.append(f'{label}: stock {n} is under {multiple}x the {qty} needed ({rec["mpn"]})')
        for ln in lns:
            if ln.mpn and rec.get('mpn') and _norm_mpn(ln.mpn) not in _norm_mpn(rec['mpn']) and _norm_mpn(rec['mpn']) not in _norm_mpn(ln.mpn):
                fails.append(f'{label}: bom.csv says MPN "{ln.mpn}" but the catalogue says "{rec["mpn"]}" ({rec.get("description", "")[:60]})')
            want, have = bomlib.package_token(ln.package), bomlib.package_token(rec.get('package', ''))
            if want and have and want != have:
                fails.append(f'{label}: bom.csv package {ln.package} but the catalogue package is {rec["package"]}')
            lib = bomlib.library_type(ln.library)
            if lib and rec.get('library') and lib != rec['library'] and not (lib == 'Basic' and rec['library'] == 'Preferred'):
                warns.append(f'{label}: bom.csv says {lib} but the catalogue says {rec["library"]}')
        if rec.get('library') == 'Extended':
            extended.add(code)
        ok.append(f'{label}: {rec["mpn"]}, {rec.get("package", "?")}, {rec.get("library", "?")}, stock {n:,}' if isinstance(n, int) else f'{label}: {rec["mpn"]}')
    status = 'fail' if fails else ('warn' if warns else ('skip' if skips and not ok else 'pass'))
    summary = f'{len(ok)} codes found, {len(fails)} blocking, {len(warns)} low-stock/mismatch, {len(skips)} not reachable; {len(extended)} Extended part types (one loading fee each)'
    return Check('stock', 'Catalogue and stock', '§1 §2 §13', status, summary, fails + warns + [f'not checked: {s}' for s in skips] + [f'ok: {o}' for o in ok])


# ---------------------------------------------------------------- what no tool checks

def by_hand(board):
    polar = boardlib.polarized_or_asymmetric(board)
    refs = ', '.join(fp.ref for fp in polar[:12]) + (f', +{len(polar) - 12} more' if len(polar) > 12 else '')
    return [
        f'Fab assembly preview: rotation of {len(polar)} polarized or asymmetric parts ({refs}) (§4)',
        'Every footprint pin map against the datasheet drawing: SOT-23 pin order, diode cathode, connector pin 1 and entry side (§3)',
        'Every MPN opened on the supplier page, pin tables and absolute maximums copied from the datasheet (§2)',
        'Transients: plug-in, switch-on, brown-out, adjacent-pin shorts on every connector (§7)',
        'Enclosure: component heights, connector edges, mounting hole pattern (§10)',
        'Hand-drawn power loops, a human look at every autorouted trace (§11)',
        'Review doc for this revision with "checked and left alone" (§6); spares in the order (§13)',
    ]
