"""preflight: refuse a KiCad board that is not ready to order.

  preflight check <project dir> [--bom bom.csv] [--online] [--strict] [--json out.json]
  preflight bom-template <project dir> [-o bom.csv]

Runs on a snapshot copy of the project by default, so nothing in the project directory changes
(kicad-cli writes a .kicad_prl beside a board that has none).
"""
import argparse
import csv
import os
import shutil
import sys
import tempfile

from . import __version__, board as boardlib, bom as bomlib, checks, kicad, report

SNAPSHOT_IGNORE = shutil.ignore_patterns('*-backups', 'fab', '.git', '__pycache__', '*.lck', '*.dsn', '*.ses',
                                         '*.pdf', '*.log', '*.zip', '*.step', '*.wrl', '*.png')


def snapshot(project_dir, work):
    dst = os.path.join(work, 'project')
    shutil.copytree(project_dir, dst, ignore=SNAPSHOT_IGNORE, symlinks=True)
    return dst


def run_check(a):
    project_dir = os.path.abspath(a.project_dir)
    if not os.path.isdir(project_dir):
        sys.exit(f'preflight: {project_dir} is not a directory')
    name = boardlib.project_name(project_dir, a.project)
    cli = kicad.find_cli(a.kicad_cli)
    bom_path = os.path.abspath(a.bom) if a.bom else os.path.join(project_dir, 'bom.csv')
    skip_prefixes = tuple(p.strip().upper() for p in a.skip_prefix.split(',') if p.strip())

    work = a.keep_work or tempfile.mkdtemp(prefix='pcb-preflight-')
    os.makedirs(work, exist_ok=True)
    try:
        src = project_dir if a.no_snapshot else snapshot(project_dir, work)
        pcb = os.path.join(src, name + '.kicad_pcb')
        sch = os.path.join(src, name + '.kicad_sch')
        for p in (pcb, sch):
            if not os.path.exists(p):
                sys.exit(f'preflight: {os.path.basename(p)} not found in {project_dir}')

        kver = kicad.version(cli)
        if not a.quiet:
            print(f'preflight {__version__}: {name} with kicad-cli {kver}' + ('' if a.no_snapshot else ' (snapshot copy)'), file=sys.stderr)
        results = []
        try:
            erc_report, _ = kicad.erc(cli, sch, os.path.join(work, 'erc.json'))
            results.append(checks.erc_check(erc_report))
        except kicad.KicadError as e:
            results.append(checks.Check('erc', 'ERC', '§12', 'skip', str(e).splitlines()[0]))

        board = boardlib.load(pcb)
        try:
            drc_report, drc_out = kicad.drc(cli, pcb, os.path.join(work, 'drc.json'), parity=True)
            results.append(checks.drc_check(drc_report))
            results.append(checks.unrouted_check(drc_report))
            results.append(checks.parity_check(drc_report, drc_out, len(board.footprints)))
        except kicad.KicadError as e:
            for cid, title in (('drc', 'DRC'), ('unrouted', 'Unrouted connections'), ('parity', 'Schematic / PCB parity')):
                results.append(checks.Check(cid, title, '§12', 'skip', str(e).splitlines()[0]))

        try:
            sch_rows = kicad.bom(cli, sch, os.path.join(work, 'sch_bom.csv'))
        except kicad.KicadError as e:
            sch_rows = None
            results.append(checks.Check('sch-bom', 'Schematic BOM export', '§1', 'skip', str(e).splitlines()[0]))

        results.append(checks.fiducial_check(board))
        results.append(checks.origin_check(board))
        results.append(checks.layer_check(board))
        results.append(checks.silk_check(board, name))
        results.append(checks.connector_check(board))
        if sch_rows is not None:
            results.append(checks.dnp_board_check(board, sch_rows))

        if not os.path.exists(bom_path):
            results.append(checks.Check('bom-file', 'bom.csv', '§1', 'fail',
                                        f'{bom_path} not found: every part is chosen from the fab catalogue before layout (preflight bom-template writes the skeleton)'))
            results.append(checks.Check('stock', 'Catalogue and stock', '§1 §2 §13', 'skip', 'no bom.csv'))
        else:
            lines, missing_cols = bomlib.load(bom_path)
            results.append(checks.bom_columns_check(missing_cols, bom_path))
            results.append(checks.bom_lcsc_check(lines))
            results.append(checks.bom_fields_check(lines))
            if sch_rows is not None:
                results.append(checks.bom_refs_check(lines, sch_rows, skip_prefixes))
                results.append(checks.bom_package_check(lines, sch_rows))
            if a.online:
                results.append(checks.stock_check(lines, multiple=a.stock_multiple))
            else:
                results.append(checks.Check('stock', 'Catalogue and stock', '§1 §2 §13', 'skip',
                                            'pass --online to look every LCSC code up at JLCPCB (stock, MPN, package, Basic/Extended)'))

        result = {
            'project': name, 'project_dir': project_dir, 'kicad_version': kver, 'copper_layers': board.copper_layers,
            'footprints': len(board.footprints), 'bom_path': bom_path if os.path.exists(bom_path) else None,
            'checks': results, 'by_hand': checks.by_hand(board), 'work_dir': work if a.keep_work else None,
        }
        text = report.render(result, max_details=a.max_details, strict=a.strict)
        if a.json:
            with open(a.json, 'w', encoding='utf-8') as f:
                f.write(report.to_json(result, strict=a.strict))
        print(text)
        return 0 if report.verdict(results, a.strict) == 'PASS' else 1
    finally:
        if not a.keep_work:
            shutil.rmtree(work, ignore_errors=True)


def run_template(a):
    project_dir = os.path.abspath(a.project_dir)
    name = boardlib.project_name(project_dir, a.project)
    cli = kicad.find_cli(a.kicad_cli)
    out = os.path.abspath(a.output or os.path.join(project_dir, 'bom.csv'))
    if os.path.exists(out) and not a.force:
        sys.exit(f'preflight: {out} exists; pass --force to overwrite it')
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


def build_parser():
    p = argparse.ArgumentParser(prog='preflight', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', action='version', version=f'pcb-preflight {__version__}')
    sub = p.add_subparsers(dest='cmd')

    def common(sp):
        sp.add_argument('project_dir', help='directory holding <name>.kicad_pro, .kicad_sch and .kicad_pcb')
        sp.add_argument('--project', help='project name when the directory holds several .kicad_pro files')
        sp.add_argument('--kicad-cli', help='path to kicad-cli (default: $KICAD_CLI, PATH, then the usual install locations)')
        sp.add_argument('--skip-prefix', default=','.join(checks.DEFAULT_SKIP_PREFIXES),
                        help='reference prefixes that are never bought parts (default: %(default)s)')

    c = sub.add_parser('check', help='run every gate and print the report (exit 1 on a blocking finding)')
    common(c)
    c.add_argument('--bom', help='bom.csv path (default: <project dir>/bom.csv)')
    c.add_argument('--online', action='store_true', help='look every LCSC code up at JLCPCB: stock, MPN, package, Basic/Extended')
    c.add_argument('--stock-multiple', type=int, default=10, help='stock must be at least this many times the quantity needed (default: %(default)s)')
    c.add_argument('--strict', action='store_true', help='warnings block too')
    c.add_argument('--json', help='also write the result as JSON to this path')
    c.add_argument('--max-details', type=int, default=15, help='detail lines per finding (default: %(default)s)')
    c.add_argument('--no-snapshot', action='store_true', help='run kicad-cli on the project directory itself instead of a copy')
    c.add_argument('--keep-work', metavar='DIR', help='keep the kicad-cli reports (erc.json, drc.json, sch_bom.csv) in DIR')
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
        return 2
    try:
        return a.fn(a)
    except (kicad.KicadError, FileNotFoundError, ValueError) as e:
        print(f'preflight: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
