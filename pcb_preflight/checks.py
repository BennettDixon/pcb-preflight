"""The gates. Each returns a Check; cli.py runs them in order and report.py prints them.

Status: pass = checked and left alone; fail = finding that blocks the order; warn = finding to look at;
skip = could not be checked, never counted as a pass: a core gate's skip makes the result ERROR, any other
skip NOT VERIFIED (preset.py). A gate that ran but could not judge every item lists those items in
``unchecked`` (printed under NOT CHECKED; the result is then NOT VERIFIED); items a human vouched for in
bom.csv go in ``verified`` (printed as "by hand", never folded into the tool's own count); what the gate
did and under which settings goes in ``notes``, which is never a finding.
"""
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import bom as bomlib
from . import board as boardlib
from . import kicad, packages, preset, stock, values

SIGN_OFF = 'to clear it, compare the drawing and add a "Package verified" note (date, initials, what was compared) on that bom.csv line'


@dataclass
class Check:
    id: str
    title: str
    pitfall: str
    status: str
    summary: str
    details: list = field(default_factory=list)      # findings: violations, blocking lines, "warning: ..."
    unchecked: list = field(default_factory=list)    # items the gate ran on but could not judge
    verified: list = field(default_factory=list)     # items a human vouched for
    notes: list = field(default_factory=list)        # what the gate did, under which settings; never a finding

    def as_dict(self):
        return {'id': self.id, 'title': self.title, 'pitfall': self.pitfall, 'status': self.status, 'summary': self.summary,
                'details': self.details, 'unchecked': self.unchecked, 'verified': self.verified, 'notes': self.notes}


DEFAULT_SKIP_PREFIXES = ('FID', 'TP', 'H', 'MH', '#')


def _skip_ref(ref, prefixes):
    r = ref.upper()
    return any(r.startswith(p) and (len(r) == len(p) or r[len(p):].isdigit()) for p in prefixes)


def _refs(refs, limit=20):
    refs = list(refs)
    return ', '.join(refs[:limit]) + (f', +{len(refs) - limit} more' if len(refs) > limit else '')


# ---------------------------------------------------------------- KiCad's own checks

def _owned_notes(report, kind, owned, excluded):
    """What the project did to the checks the gate owns (preset.py): blocking lines and notes.

    ``owned`` is preset.apply()'s return value. A protected check kicad-cli still lists as ignored, or a
    protected violation the project excluded, blocks: the gate could not or did not see it.
    """
    protected = preset.DRC_PROTECTED if kind == 'drc' else preset.ERC_PROTECTED
    where = 'Board Setup' if kind == 'drc' else 'Schematic Setup'
    ignored = [c.get('key') for c in report.get('ignored_checks', [])]
    blocked = [f'blocked: {k} is ignored in the project and {preset.PRESET} requires it ({where} > Violation Severity)'
               for k in ignored if k in protected]
    blocked += [f'blocked: excluded in the project, but {preset.PRESET} requires it: {kicad.describe(v)}'
                for v in excluded if v.get('type') in protected]
    notes = []
    lowered = (owned or {}).get(kind, {})
    if lowered:
        notes.append(f'severities: {preset.PRESET}; the project had lowered ' + ', '.join(
            f'{k} to {v} (KiCad default {preset.KICAD_DEFAULT[kind].get(k, "error")})' for k, v in sorted(lowered.items())))
    beyond = [k for k in ignored if k not in protected and preset.KICAD_DEFAULT[kind].get(k, 'error') != 'ignore']
    if beyond:
        notes.append(f"ignored by the project beyond KiCad's defaults (not required by {preset.PRESET}): {', '.join(beyond)}")
    return blocked, notes


def erc_check(report, owned=None):
    viol = [v for s in report.get('sheets', []) for v in s.get('violations', [])]
    errors, warnings, excluded = kicad.count_severities(viol)
    n = len(report.get('sheets', []))
    blocked, notes = _owned_notes(report, 'erc', owned, excluded)
    if owned and owned.get('pin_map'):
        notes.append(f"pin-conflict matrix: KiCad's default; the project had weakened {owned['pin_map']} of its 144 cells")
    det = [kicad.describe(v) for v in errors] + blocked + [f'warning: {kicad.describe(v)}' for v in warnings]
    status = 'fail' if errors or blocked else ('warn' if warnings else 'pass')
    summary = (f'{len(errors)} errors, {len(warnings)} warnings' + (f', {len(excluded)} excluded by the project' if excluded else '')
               + f' on {n} sheet{"s" if n != 1 else ""}')
    return Check('erc', 'ERC', '§12', status, summary, det, notes=notes)


def drc_check(report, owned=None, custom_rules=None, copper_layers=2):
    errors, warnings, excluded = kicad.count_severities(report.get('violations', []))
    no_courtyard = [v for v in errors if v.get('type') == 'missing_courtyard']
    errors = [v for v in errors if v.get('type') != 'missing_courtyard']
    unchecked = [f'{kicad.describe(v)}: no courtyard, so courtyards_overlap could not see this footprint' for v in no_courtyard]
    types = Counter(v.get('type') for v in errors + warnings)
    kinds = ', '.join(f'{t} x{c}' for t, c in types.most_common())
    blocked, notes = _owned_notes(report, 'drc', owned, excluded)
    if owned and (owned.get('minimums') or owned.get('netclasses')):
        raised = [f'{k} {v[0]} -> {v[1]} mm' for k, v in sorted(owned['minimums'].items())]
        raised += [f'netclass {n} clearance {v[0]} -> {v[1]} mm' for n, v in sorted(owned['netclasses'].items())]
        notes.append(f"minimums: JLCPCB {preset.MINIMUMS_COPPER_WEIGHT} copper, {copper_layers} layers; below the fab's in the project, raised in the copy: {', '.join(raised)}")
    if custom_rules:
        notes.append(f'custom design rules {os.path.basename(custom_rules)} are in the project and were not applied: '
                     f"the gate checks the fab's limits, not the designer's own rules (run DRC in KiCad for those)")
    det = [kicad.describe(v) for v in errors] + blocked + [f'warning: {kicad.describe(v)}' for v in warnings]
    status = 'fail' if errors or blocked else ('warn' if warnings else 'pass')
    summary = (f'{len(errors)} errors, {len(warnings)} warnings' + (f', {len(excluded)} excluded by the project' if excluded else '')
               + (f' ({kinds})' if kinds else '') + (f'; {len(unchecked)} footprints without a courtyard' if unchecked else ''))
    return Check('drc', 'DRC', '§12', status, summary, det, unchecked=unchecked, notes=notes)


def unrouted_check(report):
    items = report.get('unconnected_items', [])
    det = [kicad.describe(v) for v in items]
    return Check('unrouted', 'Unrouted connections', '§11 §12', 'fail' if items else 'pass',
                 f'{len(items)} connections still to route', det)


BOARD_ONLY_HINT = ('a footprint meant to live only on the board (mounting hole, logo) is marked "Not in schematic" in its '
                   'properties (attr board_only); KiCad then leaves it out of this test')


def parity_check(report, cli_output, n_footprints):
    """G4: the five parity checks (preset.PARITY) block whatever severity the project gives them (§5); the
    field-text and footprint-filter notes kicad-cli files alongside them keep the project's severity."""
    if 'Failed to fetch schematic netlist' in cli_output or 'parity tests require' in cli_output:
        reason = next((ln.strip() for ln in cli_output.splitlines() if 'netlist' in ln or 'parity' in ln), cli_output)
        return Check('parity', 'Schematic / PCB parity', '§5', 'skip', f'kicad-cli could not run it: {reason}')
    items = report.get('schematic_parity', [])
    owned = [v for v in items if v.get('type') in preset.PARITY]
    o_err, o_warn, _ = kicad.count_severities([v for v in items if v.get('type') not in preset.PARITY])
    det = []
    for v in owned:
        line = f'{kicad.describe(v)} (blocks under {preset.PRESET}, whatever severity the project gives it)'
        if v.get('type') == 'extra_footprint':
            line += '; ' + BOARD_ONLY_HINT
        det.append(line)
    det += [kicad.describe(v) for v in o_err] + [f'warning: {kicad.describe(v)}' for v in o_warn]
    status = 'fail' if owned or o_err else ('warn' if o_warn else 'pass')
    summary = f'{len(owned) + len(o_err)} mismatches' + (f', {len(o_warn)} field/filter notes' if o_warn else '') + f' across {n_footprints} footprints'
    return Check('parity', 'Schematic / PCB parity', '§5', status, summary, det)


def identity_check(board, symbols):
    """G4b: every footprint's (path ...) names a symbol in this schematic, under the same reference (§5).

    KiCad's parity test matches footprints by reference, so a schematic regenerated with fresh uuids passes
    it although "Update PCB from Schematic" would replace every routed footprint. A footprint without a
    path is board-only (a hole, a logo) only when the schematic has no symbol with its reference; otherwise
    it is an unlinked part. ``symbols`` is schematic.load_symbols().
    """
    sch_refs = {r for s in symbols.values() for r in s.references}
    orphans, unlinked, renamed, board_only = [], [], [], []
    linked = 0
    for fp in board.footprints:
        if not fp.path or fp.path == '/':
            (unlinked if fp.ref in sch_refs else board_only).append(fp.ref)
            continue
        sheet, _, uuid = fp.path.rpartition('/')
        sym = symbols.get(uuid)
        if sym is None:
            orphans.append(fp.ref)
            continue
        ref = sym.instances.get(sheet or '/', sym.ref)
        if ref and ref != fp.ref:
            renamed.append(f'{fp.ref} on the board is {ref} in the schematic ({sym.lib_id})')
        else:
            linked += 1
    n = len(board.footprints)
    det = []
    if len(orphans) + len(unlinked) >= max(3, n // 2):
        det.append('most footprints are not linked to this schematic: it was regenerated with new identities, or the '
                   'links were stripped; "Update PCB from Schematic" would replace the routed footprints (§5)')
    det += [f'{r}: points at a symbol that is not in the schematic' for r in orphans]
    det += [f'{r}: no schematic link, but the schematic has a {r}; re-link it with Update PCB from Schematic' for r in unlinked]
    det += renamed
    if n and symbols and not linked:
        det.append('no footprint on the board is linked to any symbol in the schematic')
    notes = [f'{len(board_only)} board-only footprints (no path, reference not in the schematic): {_refs(board_only)}'] if board_only else []
    title = 'Board footprints belong to this schematic'
    if det:
        return Check('identity', title, '§5', 'fail',
                     f'{len(orphans)} orphaned, {len(unlinked)} unlinked, {len(renamed)} renamed of {n} footprints', det, notes=notes)
    return Check('identity', title, '§5', 'pass',
                 f'{linked} of {n} footprints name a symbol in the schematic' + (f', {len(board_only)} board-only' if board_only else ''), notes=notes)


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


def placement_check(board, sch_rows, skip_prefixes):
    """G5b: every bought reference (in the BOM, not DNP) has a footprint on the board (§5 §12).

    KiCad's parity test skips a symbol marked "exclude from board", so a part can leave the board with
    one schematic flag while bom.csv still carries its line; this gate works from the BOM side.
    """
    wanted = purchasable(sch_rows, skip_prefixes)
    on_board = {fp.ref for fp in board.footprints}
    excluded = sorted(r for r, row in wanted.items() if row.get('ExcludeFromBoard'))
    gone = sorted(r for r in wanted if r not in on_board and r not in excluded)
    det = []
    if excluded:
        det.append(f'in the BOM but excluded from the board in the schematic (place it, or exclude it from the BOM too): {_refs(excluded)}')
    if gone:
        det.append(f'bought in the schematic but no footprint on the board: {_refs(gone)}')
    placed = len(wanted) - len(gone) - len(excluded)
    title = 'Bought parts placed on the board'
    if det:
        return Check('placement', title, '§5 §12', 'fail', f'{len(gone) + len(excluded)} of {len(wanted)} bought references have no footprint on the board', det)
    return Check('placement', title, '§5 §12', 'pass', f'{placed} of {len(wanted)} bought references have a footprint on the board')


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
        if not _norm_mpn(ln.mpn):
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


def bom_refs_check(lines, sch_rows, skip_prefixes, board=None):
    """G9: bom.csv references equal the schematic's bought references, and nothing bought hides from the BOM.

    What is not bought is said every run (DNP, excluded from the BOM, skipped by prefix). A reference that
    is excluded or skipped but whose footprint has paste pads is a part the fab would solder: it needs a
    BOM line or a DNP flag, not a name that happens to start with TP.
    """
    wanted = purchasable(sch_rows, skip_prefixes)
    dnp = {r['Ref'] for r in sch_rows if r['DNP']}
    excl = {r['Ref'] for r in sch_rows if r['ExcludeFromBOM'] and not r['DNP']}
    skipped = {r['Ref'] for r in sch_rows if _skip_ref(r['Ref'], skip_prefixes) and r['Ref'] not in dnp and r['Ref'] not in excl}
    all_sch = {r['Ref'] for r in sch_rows}
    in_bom = Counter(ref for ln in lines for ref in ln.refs)
    missing = sorted(set(wanted) - set(in_bom))
    unknown = sorted(r for r in in_bom if r not in all_sch)
    dupes = sorted(r for r, c in in_bom.items() if c > 1)
    listed_dnp = sorted(r for r in in_bom if r in dnp)
    det = []
    if missing:
        det.append(f'in the schematic but not in bom.csv: {_refs(missing)}')
    if unknown:
        det.append(f'in bom.csv but not in the schematic: {_refs(unknown)}')
    if dupes:
        det.append(f'listed twice in bom.csv: {_refs(dupes)}')
    if listed_dnp:
        det.append(f'DNP in the schematic but listed in bom.csv (the fab would place them): {_refs(listed_dnp)}')
    prefix = f'prefix {"/".join(p for p in skip_prefixes if p != "#")}'
    groups = {prefix: set(skipped), 'DNP': set(dnp), 'excluded from the BOM': set(excl), 'board-only, no symbol': set()}
    hidden = {prefix: [], 'excluded from the BOM': [], 'board-only, no symbol': []}
    if board is not None:                        # the export omits symbols excluded from the BOM: read the board
        for fp in board.footprints:
            if fp.ref in wanted or fp.ref in in_bom:
                continue
            why = ('DNP' if fp.dnp or fp.ref in dnp else prefix if _skip_ref(fp.ref, skip_prefixes)
                   else 'excluded from the BOM' if fp.excluded_from_bom or fp.ref in excl or fp.ref in all_sch else 'board-only, no symbol')
            groups[why].add(fp.ref)
            if why != 'DNP' and fp.paste and not fp.net_tie and not fp.is_fiducial:
                hidden[why].append(fp.ref)
    for why, refs in hidden.items():
        if refs:
            det.append(f'{why}, but with paste pads, so the fab solders a part there: {_refs(sorted(refs))}; a soldered part is bought (a BOM line) or DNP'
                       + ('; give it a bought reference' if why == prefix else ''))
    not_bought = '; '.join(f'{_refs(sorted(refs), 12)} ({why})' for why, refs in groups.items() if refs)
    notes = [f'not bought: {not_bought}' if not_bought else 'not bought: nothing (no DNP, excluded, prefix-skipped or board-only references)']
    if det:
        return Check('bom-refs', 'bom.csv matches the schematic', '§1 §5 §12', 'fail',
                     f'{len(missing)} missing, {len(unknown)} unknown, {len(dupes)} duplicate, {len(listed_dnp)} DNP references'
                     + (f', {sum(len(r) for r in hidden.values())} hidden soldered parts' if board is not None else ''),
                     det, notes=notes)
    return Check('bom-refs', 'bom.csv matches the schematic', '§1 §5 §12', 'pass',
                 f'{len(wanted)} bought references, every one on exactly one BOM line', notes=notes)


def _library_note(library):
    if library is None:
        return ('pad geometry: no KiCad footprint library found, so package names alone were compared '
                '(pass --footprints DIR or set KICAD_FOOTPRINT_DIR)')
    return (f'pad geometry: KiCad footprint library at {library.root}; where both sides are library footprints the pads '
            f'decide and the names only pick the candidates')


def _fit_gate(cid, title, pairs, library=None, extra_unchecked=(), extra_summary=''):
    """One package gate over (label, footprint, package, mpn, verified note) tuples: packages.fits() on each.

    different -> blocks, and a "Package verified" note never changes that (a known mismatch is fixed, not
    signed off); unknown -> listed as not compared with the way to clear it, or as verified by hand when the
    line carries a note. A gate where nothing could be compared is a skip, not a pass. ``library`` is the
    KiCad footprint library for pad geometry (packages.Library) or None for names only; the gate says which.
    """
    det, unknown, by_hand, evidence = [], [], [], []
    same = 0
    for label, footprint, package, mpn, note in pairs:
        f = packages.fits(footprint, package, mpn, library)
        what = f'{label}: {package or "(no package)"} on {packages.bare(footprint)}: {f.reason}'
        if f.verdict == packages.SAME:
            same += 1
            if f.via or f.rule == packages.DRAWN_FOR or (f.rule == packages.PADS and f.by_names != packages.SAME):
                evidence.append(what)             # how a line passed by table or by pads: a detail (JSON), printed when the gate is a finding
        elif f.verdict == packages.DIFFERENT:
            det.append(what + (f'; the "Package verified" note ("{note}") does not apply: a known mismatch is fixed in '
                               f'bom.csv or on the board, not signed off' if note else ''))
        elif note:
            by_hand.append(f'{what}; verified by hand: {note}')
        else:
            unknown.append(f'{what}; {SIGN_OFF}')
    unknown = list(extra_unchecked) + unknown
    parts = [f'{same} agree with their footprint']
    if by_hand:
        parts.append(f'{len(by_hand)} verified by hand')
    if unknown:
        parts.append(f'{len(unknown)} not compared (sign each under NOT CHECKED with a "Package verified" note on its bom.csv line, '
                     f'or fix the string it names)')
    if extra_summary:
        parts.append(extra_summary)
    notes = [_library_note(library)]
    if det:
        return Check(cid, title, '§1', 'fail', f'{len(det)} do not fit the footprint; ' + ', '.join(parts), det + evidence, unknown, by_hand, notes)
    if not same and not by_hand:
        return Check(cid, title, '§1', 'skip', ', '.join(parts), evidence, unknown, by_hand, notes)
    return Check(cid, title, '§1', 'pass', ', '.join(parts), evidence, unknown, by_hand, notes)


def _with_records(lines, records):
    """(lines whose code has a catalogue record, note for the codes no catalogue could be asked about)."""
    unreachable = sorted({ln.lcsc for ln in lines if ln.lcsc in records and records[ln.lcsc] is None})
    note = ([f'{len(unreachable)} codes not looked up, so their records were not compared '
             f'(catalogue not reachable; the codes are listed under Catalogue and stock)'] if unreachable else [])
    return [ln for ln in lines if records.get(ln.lcsc) is not None], note


def catalogue_package_check(lines, records, sch_rows=None, library=None):
    """G11b: the catalogue's package for each LCSC code against the footprint on the board (online).

    ``records`` maps code -> catalogue record as stock_check() filled it, or None for a code the catalogue
    could not be asked about (listed as not compared). Codes absent from ``records`` were not valid codes
    or are not in the catalogue; the stock gate already reports those.
    """
    fp_of = {r['Ref']: r['Footprint'] for r in sch_rows} if sch_rows else {}
    groups = {}                                  # (code, footprint) -> [refs, rows, verified note]
    with_rec, unreachable = _with_records(lines, records)
    for ln in with_rec:
        for ref in ln.refs:
            g = groups.setdefault((ln.lcsc, fp_of.get(ref) or ln.package), [[], set(), ''])
            g[0].append(ref)
            g[1].add(ln.row)
            g[2] = g[2] or ln.package_verified
    pairs = []
    for (code, fp), (refs, rows, note) in groups.items():
        rec = records[code]
        rows = ', '.join(str(r) for r in sorted(rows))
        pairs.append((f'{code} {rec.get("mpn", "")} ({", ".join(refs)}; bom.csv row {rows})', fp, rec.get('package', ''), rec.get('mpn'), note))
    title = 'Catalogue package fits the footprint'
    if not pairs:
        return Check('catalogue-package', title, '§1', 'skip', 'no catalogue record to compare', unchecked=unreachable)
    c = _fit_gate('catalogue-package', title, pairs, library)
    c.unchecked = unreachable + c.unchecked
    if unreachable:
        c.summary += f', {len(unreachable)} not reachable'
    return c


# ---------------------------------------------------------------- values

def bom_value_check(lines, sch_rows):
    """G9b: every bom.csv Value equals the schematic Value of its references, spelling aside (§1).

    values.normalize() folds µ/u, Ω/ohm/R, RKM figures (4k7), spaces and case; nothing else (100nF and 0.1uF
    are two spellings: the schematic and bom.csv use one). References bom.csv has that the schematic lacks
    are the bom-refs gate's finding, not this one's.
    """
    value_of = {r['Ref']: r['Value'] for r in sch_rows}
    det, n = [], 0
    for ln in lines:
        for ref in ln.refs:
            if ref not in value_of:
                continue
            n += 1
            if values.normalize(ln.value) != values.normalize(value_of[ref]):
                det.append(f'{ref} (bom.csv row {ln.row}): "{ln.value}" in bom.csv, "{value_of[ref]}" in the schematic')
    title = 'BOM value matches the schematic'
    if det:
        return Check('bom-value', title, '§1', 'fail', f'{len(det)} of {n} references carry a different value in bom.csv and the schematic', det)
    return Check('bom-value', title, '§1', 'pass', f'{n} references, bom.csv Value equals the schematic Value on each (µ/u, Ω/ohm, spaces and case aside)')


def catalogue_category_check(lines, records):
    """G11c (online): the reference prefix agrees with the catalogue's category for its part (§1 §2).

    C is a capacitor, R a resistor, D a diode or LED, L an inductor or ferrite, Q a transistor, J a connector,
    U anything that is none of those (values.PREFIXES, values.CLASSES, each keyword with the record it was seen
    in). A capacitor's code on an LED line blocks. A prefix without a rule, or a record without a category
    where one is needed, is not checked and says so.
    """
    with_rec, unreachable = _with_records(lines, records)
    det, unchecked = [], list(unreachable)
    ok = 0
    for ln in with_rec:
        rec = records[ln.lcsc]
        for prefix in sorted({values.prefix_of(r) for r in ln.refs}):
            refs = [r for r in ln.refs if values.prefix_of(r) == prefix]
            label = f'{ln.lcsc} {rec.get("mpn", "")} ({", ".join(refs)}; bom.csv row {ln.row})'
            status, why = values.category_fits(prefix, rec.get('category', ''), rec.get('description', ''))
            if status == 'ok':
                ok += 1
            elif status == 'mismatch':
                det.append(f'{label}: {why}')
            else:
                unchecked.append(f'{label}: {why}')
    title = 'Catalogue category matches the reference prefix'
    if not with_rec:
        return Check('catalogue-category', title, '§1 §2', 'skip', 'no catalogue record to compare', unchecked=unchecked)
    summary = f'{ok} lines filed under the category their reference prefix means'
    summary += (f', {len(det)} under another' if det else '') + (f', {len(unchecked)} not checked' if unchecked else '')
    return Check('catalogue-category', title, '§1 §2', 'fail' if det else ('pass' if ok else 'skip'), summary, det, unchecked)


def catalogue_value_check(lines, records):
    """G11d (online): the figures in the bom.csv Value (F, H, Ω, V) agree with the catalogue description's (§1 §2).

    values.compare(): capacitance, inductance and resistance within 1 %; the part's voltage rating at least
    the value's. A figure the description does not state is not checked and says so; a value without
    figures (a part number) has nothing to compare and is counted as such, not as unchecked.
    """
    with_rec, unreachable = _with_records(lines, records)
    det, unchecked = [], list(unreachable)
    agreed = no_figure = 0
    for ln in with_rec:
        rec = records[ln.lcsc]
        label = f'{ln.lcsc} {rec.get("mpn", "")} ({", ".join(ln.refs)}; bom.csv row {ln.row})'
        desc = rec.get('description', '') or ''
        mism, unch, agree = values.compare(ln.value, desc, any(values.prefix_of(r) == 'R' for r in ln.refs))
        if mism:
            det.append(f'{label}: {"; ".join(mism)} (bom.csv value "{ln.value}", description "{desc[:90]}")')
        unchecked += [f'{label}: {u} (bom.csv value "{ln.value}")' for u in unch]
        if agree and not mism:
            agreed += 1
        elif not mism and not unch:
            no_figure += 1
    title = 'Catalogue description matches the BOM value'
    if not with_rec:
        return Check('catalogue-value', title, '§1 §2', 'skip', 'no catalogue record to compare', unchecked=unchecked)
    summary = (f'{agreed} lines agree on every figure their value states (F, H, Ω, V), {no_figure} state no figure'
               + (f', {len(det)} disagree' if det else '') + (f', {len(unchecked)} not checked' if unchecked else ''))
    return Check('catalogue-value', title, '§1 §2', 'fail' if det else 'pass', summary, det, unchecked)


# ---------------------------------------------------------------- the catalogue (online)

def _norm_mpn(s):
    return re.sub(r'[\s\-_/,.]', '', s or '').upper()


def stock_check(lines, multiple=10, lookup=stock.lookup, records=None):
    """G11: every code exists, is in stock (>= multiple x quantity), and matches the BOM's MPN and library.

    ``records``, when given, is filled with code -> catalogue record for catalogue_package_check(), and
    code -> None for a code no catalogue could be asked about. Those codes, and lines with no MPN to
    compare with the catalogue's, are listed under NOT CHECKED (``unchecked``), never counted as a pass.
    """
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
            if records is not None:
                records[code] = None
            continue
        if records is not None and rec is not None:
            records[code] = rec
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
            mine, theirs = _norm_mpn(ln.mpn), _norm_mpn(rec.get('mpn'))
            if not mine:
                skips.append(f'{label}: no MPN in bom.csv to compare with the catalogue\'s {rec.get("mpn") or "(none)"}; the code was not checked against a part')
            elif theirs and mine not in theirs and theirs not in mine:
                fails.append(f'{label}: bom.csv says MPN "{ln.mpn}" but the catalogue says "{rec["mpn"]}" ({rec.get("description", "")[:60]})')
            lib = bomlib.library_type(ln.library)
            if lib and rec.get('library') and lib != rec['library'] and not (lib == 'Basic' and rec['library'] == 'Preferred'):
                warns.append(f'{label}: bom.csv says {lib} but the catalogue says {rec["library"]}')
        if rec.get('library') == 'Extended':
            extended.add(code)
        ok.append(f'{label}: {rec["mpn"]}, {rec.get("package", "?")}, {rec.get("library", "?")}, stock {n:,}' if isinstance(n, int) else f'{label}: {rec["mpn"]}')
    status = 'fail' if fails else ('warn' if warns else ('skip' if skips and not ok else 'pass'))
    summary = f'{len(ok)} codes found, {len(fails)} blocking, {len(warns)} low-stock/mismatch, {len(skips)} not checked; {len(extended)} Extended part types (one loading fee each)'
    return Check('stock', 'Catalogue and stock', '§1 §2 §13', status, summary, fails + warns + [f'ok: {o}' for o in ok], unchecked=skips)


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
