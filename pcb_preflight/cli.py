"""preflight: refuse a KiCad board that is not ready to order.

  preflight check <project dir> [--bom bom.csv] [--online] [--strict] [--json out.json]
  preflight bom-template <project dir> [-o bom.csv]

Exit codes (preset.py): 0 PASS, 1 FAIL, 2 ERROR (a core gate did not run, or the tool itself failed),
3 NOT VERIFIED (something could not be checked: no --online, catalogue unreachable, a package or an MPN
nobody compared).

`check` runs on a snapshot copy of the project, never on the project itself: kicad-cli writes a .kicad_prl
beside a board that has none, and the gate sets what it owns (severities, pin matrix, the fab's minimums)
in the copy's .kicad_pro before kicad-cli runs. Custom design rules (<name>.kicad_dru) are left out of the
copy; the report says so.
"""
import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
import traceback

from . import __version__, board as boardlib, bom as bomlib, checks, footprints, kicad, packages, preset, report, schematic

SCHEMA = 1     # of the JSON report; bumped when a field changes meaning or goes away

SNAPSHOT_IGNORE = shutil.ignore_patterns('*-backups', 'fab', '.git', '__pycache__', '*.lck', '*.dsn', '*.ses',
                                         '*.pdf', '*.log', '*.zip', '*.step', '*.wrl', '*.png', '*.kicad_dru')


def snapshot(project_dir, work):
    dst = os.path.join(work, 'project')
    if os.path.isdir(dst):                      # --keep-work DIR reused: the previous copy goes
        shutil.rmtree(dst)
    shutil.copytree(project_dir, dst, ignore=SNAPSHOT_IGNORE, symlinks=True)
    return dst


def run_check(a):
    project_dir = os.path.abspath(a.project_dir)
    if not os.path.isdir(project_dir):
        raise ValueError(f'{project_dir} is not a directory')
    name = boardlib.project_name(project_dir, a.project)
    cli = kicad.find_cli(a.kicad_cli)
    library = packages.load_library(footprints.find_root(a.footprints, cli))
    bom_path = os.path.abspath(a.bom) if a.bom else os.path.join(project_dir, 'bom.csv')
    skip_prefixes = tuple(p.strip().upper() for p in a.skip_prefix.split(',') if p.strip())
    for p in (name + '.kicad_pcb', name + '.kicad_sch', name + '.kicad_pro'):
        if not os.path.exists(os.path.join(project_dir, p)):
            raise ValueError(f'{p} not found in {project_dir}')
    custom_rules = os.path.join(project_dir, name + '.kicad_dru')
    custom_rules = custom_rules if os.path.exists(custom_rules) else None

    work = a.keep_work or tempfile.mkdtemp(prefix='pcb-preflight-')
    os.makedirs(work, exist_ok=True)
    try:
        src = snapshot(project_dir, work)
        pcb = os.path.join(src, name + '.kicad_pcb')
        sch = os.path.join(src, name + '.kicad_sch')
        board = boardlib.load(pcb)
        # What the gate owns is set in the copy, never in the project (preset.py).
        owned = preset.apply(os.path.join(src, name + '.kicad_pro'), board.copper_layers)

        kver = kicad.version(cli)
        if not a.quiet:
            print(f'preflight {__version__}: {name} with kicad-cli {kver} ({cli}), {preset.PRESET}, on a snapshot copy; '
                  f'footprints: {library.root if library else "none found (package names only)"}', file=sys.stderr)
        results = []
        try:
            erc_report, _ = kicad.erc(cli, sch, os.path.join(work, 'erc.json'))
            results.append(checks.erc_check(erc_report, owned))
        except kicad.KicadError as e:
            results.append(checks.Check('erc', 'ERC', '§12', 'skip', str(e)))

        try:
            drc_report, drc_out = kicad.drc(cli, pcb, os.path.join(work, 'drc.json'), parity=True)
            results.append(checks.drc_check(drc_report, owned, custom_rules, board.copper_layers))
            results.append(checks.unrouted_check(drc_report))
            results.append(checks.parity_check(drc_report, drc_out, len(board.footprints)))
        except kicad.KicadError as e:
            for cid, title, pitfall in (('drc', 'DRC', '§12'), ('unrouted', 'Unrouted connections', '§11 §12'),
                                        ('parity', 'Schematic / PCB parity', '§5')):
                results.append(checks.Check(cid, title, pitfall, 'skip', str(e)))

        try:
            results.append(checks.identity_check(board, schematic.load_symbols(sch)))
        except (OSError, ValueError) as e:
            results.append(checks.Check('identity', 'Board footprints belong to this schematic', '§5', 'skip',
                                        f'could not read the schematic: {e}'))

        try:
            sch_rows = kicad.bom(cli, sch, os.path.join(work, 'sch_bom.csv'))
        except kicad.KicadError as e:
            sch_rows = None
            results.append(checks.Check('sch-bom', 'Schematic BOM export', '§1', 'skip', str(e)))

        results.append(checks.fiducial_check(board))
        results.append(checks.origin_check(board))
        results.append(checks.layer_check(board))
        results.append(checks.silk_check(board, name))
        results.append(checks.connector_check(board))
        if sch_rows is not None:
            results.append(checks.dnp_board_check(board, sch_rows))
            results.append(checks.placement_check(board, sch_rows, skip_prefixes))

        lines = None
        if not os.path.exists(bom_path):
            results.append(checks.Check('bom-file', 'bom.csv', '§1', 'fail',
                                        f'{bom_path} not found: every part is chosen from the fab catalogue before layout (preflight bom-template writes the skeleton)'))
        else:
            try:
                lines, missing_cols = bomlib.load(bom_path)
            except UnicodeDecodeError as e:
                results.append(checks.Check('bom-file', 'bom.csv', '§1', 'fail',
                                            f'{bom_path} is not UTF-8 (byte 0x{e.object[e.start]:02x} at offset {e.start}; Excel\'s "CSV (Comma delimited)" '
                                            f'writes the Windows code page): save it as "CSV UTF-8"'))
        if lines is None:
            results.append(checks.Check('stock', 'Catalogue and stock', '§1 §2 §13', 'skip', 'no readable bom.csv'))
        else:
            results.append(checks.bom_columns_check(missing_cols, bom_path))
            results.append(checks.bom_lcsc_check(lines))
            results.append(checks.bom_fields_check(lines))
            if sch_rows is not None:
                results.append(checks.bom_refs_check(lines, sch_rows, skip_prefixes, board))
                results.append(checks.bom_value_check(lines, sch_rows))
                results.append(checks.bom_package_check(lines, sch_rows, library))
            if a.online:
                records = {}
                results.append(checks.stock_check(lines, multiple=a.stock_multiple, records=records))
                results.append(checks.catalogue_package_check(lines, records, sch_rows, library))
                results.append(checks.catalogue_category_check(lines, records))
                results.append(checks.catalogue_value_check(lines, records))
            else:
                results.append(checks.Check('stock', 'Catalogue and stock', '§1 §2 §13', 'skip',
                                            'not asked: pass --online to look every LCSC code up at JLCPCB (stock, MPN, package, Basic/Extended)'))

        result = {
            'schema': SCHEMA, 'version': __version__, 'project': name, 'project_dir': project_dir,
            'kicad_version': kver, 'kicad_cli': cli, 'preset': preset.PRESET,
            'options': {'online': a.online, 'strict': a.strict, 'skip_prefixes': list(skip_prefixes),
                        'stock_multiple': a.stock_multiple, 'custom_rules_present': bool(custom_rules),
                        'footprints': library.root if library else None},
            'owned': {k: ({kk: list(vv) if isinstance(vv, tuple) else vv for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in owned.items()},
            'copper_layers': board.copper_layers, 'footprints': len(board.footprints),
            'bom_path': bom_path if os.path.exists(bom_path) else None,
            'checks': results, 'by_hand': checks.by_hand(board), 'work_dir': work if a.keep_work else None,
        }
        print(report.render(result, max_details=a.max_details, strict=a.strict))
        if a.json:
            with open(a.json, 'w', encoding='utf-8') as f:
                f.write(report.to_json(result, strict=a.strict))
        return preset.EXIT[report.verdict(results, a.strict)]
    finally:
        if not a.keep_work:
            shutil.rmtree(work, ignore_errors=True)


def run_template(a):
    project_dir = os.path.abspath(a.project_dir)
    name = boardlib.project_name(project_dir, a.project)
    cli = kicad.find_cli(a.kicad_cli)
    out = os.path.abspath(a.output or os.path.join(project_dir, 'bom.csv'))
    if os.path.exists(out) and not a.force:
        raise ValueError(f'{out} exists; pass --force to overwrite it')
    skip_prefixes = tuple(p.strip().upper() for p in a.skip_prefix.split(',') if p.strip())
    work = tempfile.mkdtemp(prefix='pcb-preflight-')
    try:
        src = snapshot(project_dir, work)
        rows = kicad.bom(cli, os.path.join(src, name + '.kicad_sch'), os.path.join(work, 'sch_bom.csv'))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    groups = {}
    for r in checks.purchasable(rows, skip_prefixes).values():
        groups.setdefault((r['Value'], r['Footprint']), []).append(r['Ref'])
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(bomlib.REQUIRED)
        for (value, fp), refs in groups.items():
            w.writerow([','.join(refs), value, fp.split(':', 1)[-1], '', '', '', '', ''])
    print(f'wrote {out}: {len(groups)} lines to fill from the fab catalogue (LCSC, MPN, Basic/Extended, Stock, Datasheet)')
    return 0


def _positive(s):
    n = int(s)
    if n < 1:
        raise argparse.ArgumentTypeError('must be 1 or more (the margin is part of the contract; it cannot be switched off)')
    return n


def build_parser():
    p = argparse.ArgumentParser(prog='preflight', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', action='version', version=f'pcb-preflight {__version__}')
    sub = p.add_subparsers(dest='cmd')

    def common(sp):
        sp.add_argument('project_dir', help='directory holding <name>.kicad_pro, .kicad_sch and .kicad_pcb')
        sp.add_argument('--project', help='project name when the directory holds several .kicad_pro files')
        sp.add_argument('--kicad-cli', help='path to kicad-cli (default: $KICAD_CLI, PATH, then the usual install locations); a wrong path is an error')
        sp.add_argument('--skip-prefix', default=','.join(checks.DEFAULT_SKIP_PREFIXES),
                        help='reference prefixes that are never bought parts (default: %(default)s); printed in the report, and a skipped reference with paste pads still blocks')

    c = sub.add_parser('check', help='run every gate and print the report (exit 0 PASS, 1 FAIL, 2 ERROR, 3 NOT VERIFIED)')
    common(c)
    c.add_argument('--bom', help='bom.csv path (default: <project dir>/bom.csv)')
    c.add_argument('--footprints', metavar='DIR', help='KiCad footprint library directory for pad geometry (default: $KICAD_FOOTPRINT_DIR, '
                   'then the kicad-cli install); without one, package names alone are compared')
    c.add_argument('--online', action='store_true', help='look every LCSC code up at JLCPCB: stock, MPN, package, Basic/Extended (without it the result is at best NOT VERIFIED)')
    c.add_argument('--stock-multiple', type=_positive, default=10, help='stock must be at least this many times the quantity needed (default: %(default)s)')
    c.add_argument('--strict', action='store_true', help='warnings block too')
    c.add_argument('--json', help='also write the result as JSON to this path (written even when the run ends in ERROR)')
    c.add_argument('--max-details', type=int, default=15, help='detail lines per finding (default: %(default)s)')
    c.add_argument('--keep-work', metavar='DIR', help='keep the snapshot copy and the kicad-cli reports (erc.json, drc.json, sch_bom.csv) in DIR')
    c.add_argument('--quiet', action='store_true', help='no progress line on stderr')
    c.set_defaults(fn=run_check)

    t = sub.add_parser('bom-template', help='write a bom.csv skeleton from the schematic, one line per value and footprint')
    common(t)
    t.add_argument('-o', '--output', help='where to write it (default: <project dir>/bom.csv)')
    t.add_argument('--force', action='store_true', help='overwrite an existing file')
    t.set_defaults(fn=run_template)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in ('check', 'bom-template', '-h', '--help', '--version') and not argv[0].startswith('-'):
        argv.insert(0, 'check')
    p = build_parser()
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return preset.EXIT[preset.ERROR]
    try:
        return a.fn(a)
    except Exception as e:                       # anything the tool itself could not do is ERROR, never FAIL
        print(f'preflight: {e}', file=sys.stderr)
        if os.environ.get('PREFLIGHT_DEBUG'):
            traceback.print_exc()
        if getattr(a, 'json', None):
            try:
                with open(a.json, 'w', encoding='utf-8') as f:
                    json.dump({'schema': SCHEMA, 'version': __version__, 'preset': preset.PRESET, 'result': preset.ERROR,
                               'exit_code': preset.EXIT[preset.ERROR], 'error': str(e), 'checks': []}, f, indent=2)
            except OSError as e2:
                print(f'preflight: could not write {a.json}: {e2}', file=sys.stderr)
        return preset.EXIT[preset.ERROR]


if __name__ == '__main__':
    sys.exit(main())
