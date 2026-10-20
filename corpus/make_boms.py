"""Write corpus/boms/<name>.csv for every corpus board that carries LCSC data in its symbol fields.

The lines are built the way the README describes: one line per (value, footprint, part), Ref listing every
reference, Package = the symbol's own Package field when it has one, else the footprint name (what
`preflight bom` writes for a line without a code), MPN from the board's own part-number field, LCSC from its LCSC field,
Datasheet from the symbol. Basic/Extended and Stock are left blank (the catalogue fills them with --online).
kicad-cli runs on a copy of each project; nothing is written into corpus/boards.
"""
import csv, os, re, shutil, subprocess, sys, tempfile, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pcb_preflight import checks, bom as bomlib
CLI = os.environ.get('KICAD_CLI', '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
BOARDS = os.path.join(ROOT, 'corpus', 'boards')
OUT = os.path.join(ROOT, 'corpus', 'boms')

# board -> (project name, LCSC fields in priority order, MPN fields, Package fields, MPN->LCSC resolved by hand)
CONFIG = {
    'beyondex-limiter':        ('BeyondexLimiter', ['LCSC'], ['MP'], ['Package'], {}),
    'beyondex-limiter-prefix': ('BeyondexLimiter', ['LCSC'], ['MP'], ['Package'], {}),
    # bitaxeAura issue #1: TMK107B7105KA-T is JLCPCB C92827 (0603), looked up 2026-10-17 via selectSmtComponentList
    'bitaxeaura':              ('bitaxeAura', ['LCSC'], ['PARTNO', 'PARTNUM', 'Partnum'], [], {'TMK107B7105KA-T': 'C92827'}),
    'bitaxegt':                ('BitaxeGT', ['LCSC'], ['PARTNO', 'PARTNUM', 'Partnum'], [], {}),
    'canfd-mc':                ('canfd-mc', ['LCSC'], [], [], {}),
    'cm5-minima':              ('CM5_MINIMA_3', ['LCSC Part'], ['Manufacturer_Part_Number', 'P/N'], ['Package'], {}),
    'jlcpcb-example':          ('SMPS 12V-5V', ['LCSC', 'LCSC Part'], ['Part'], [], {}),
    'openair-max':             ('One-Air-Max', ['LCSC Part'], ['MANUFACTURER_PART_NUMBER', 'MP'], ['Package'], {}),
    'openjbod-rp2040':         ('OpenJBOD-RP2040', ['LCSC Part #', 'JLCPCB_PN', 'LCSC Part'], [], [], {}),
    'pocketpd':                ('PicoPDSupply', ['LCSC'], ['Manufacturer Part', 'Manufacture #'], [], {}),
    'royalblue54l-feather':    ('RoyalBlue54L-Feather', ['LCSC'], [], [], {}),
    'sh-rpi':                  ('SH-RPi', ['LCSC'], [], [], {}),
    'soldiercrab':             ('soldiercrab', ['lcsc#'], ['Part Number', 'PN'], [], {}),
    'sonatino':                ('Sonatino', ['LCSC', 'LCSC Part'], [], [], {}),
    'tiny-tapeout':            ('tinytapeout-demo', ['JLC'], ['MPN'], [], {}),
}

def export(board, project, fields):
    src = os.path.join(BOARDS, board)
    work = tempfile.mkdtemp(prefix='corpus-bom-')
    try:
        dst = os.path.join(work, 'p')
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns('*-backups', '.git'))
        out = os.path.join(work, 'bom.csv')
        names = ['Reference', 'Value', 'Footprint', 'Datasheet', '${DNP}', '${EXCLUDE_FROM_BOM}'] + fields
        labels = ['Ref', 'Value', 'Footprint', 'Datasheet', 'DNP', 'ExcludeFromBOM'] + [f'F{i}' for i in range(len(fields))]
        r = subprocess.run([CLI, 'sch', 'export', 'bom', '--output', out, '--fields', ','.join(names),
                            '--labels', ','.join(labels), '--ref-range-delimiter', '', os.path.join(dst, project + '.kicad_sch')],
                           capture_output=True, text=True, timeout=300)
        if not os.path.exists(out):
            raise SystemExit(f'{board}: export failed: {r.stdout} {r.stderr}')
        with open(out, newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            for i, fname in enumerate(fields):
                row[fname] = row.pop(f'F{i}', '')
        return rows
    finally:
        shutil.rmtree(work, ignore_errors=True)

def first(row, names):
    for n in names:
        v = (row.get(n) or '').strip()
        if v:
            return v
    return ''

os.makedirs(OUT, exist_ok=True)
for board, (project, lcsc_f, mpn_f, pkg_f, resolved) in sorted(CONFIG.items()):
    if not os.path.isdir(os.path.join(BOARDS, board)):
        print(f'{board}: not fetched, skipped'); continue
    rows = export(board, project, lcsc_f + mpn_f + pkg_f)
    for r in rows:
        r['DNP'] = bool((r.get('DNP') or '').strip()); r['ExcludeFromBOM'] = bool((r.get('ExcludeFromBOM') or '').strip())
    bought = checks.purchasable(rows, checks.DEFAULT_SKIP_PREFIXES)
    groups = collections.OrderedDict()
    n_codes = n_mpn = 0
    for ref, r in bought.items():
        lcsc = first(r, lcsc_f).upper().replace(' ', '')
        mpn = first(r, mpn_f)
        if not lcsc and mpn in resolved:
            lcsc = resolved[mpn]
        if lcsc and not bomlib.LCSC_RE.match(lcsc):
            lcsc = lcsc  # keep whatever is there; the gate reports it
        pkg = first(r, pkg_f)
        if pkg in ('Package', 'None', '~'):       # BeyondexLimiter's SnapEDA symbols carry a placeholder
            pkg = ''
        pkg = pkg or r['Footprint'].split(':', 1)[-1]
        ds = r.get('Datasheet', '').strip()
        ds = '' if ds in ('~', '') else ds
        key = (r['Value'], r['Footprint'], lcsc, mpn, pkg)
        groups.setdefault(key, {'refs': [], 'ds': ds})['refs'].append(ref)
    path = os.path.join(OUT, board + '.csv')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(bomlib.REQUIRED)
        for (value, fp, lcsc, mpn, pkg), g in groups.items():
            w.writerow([','.join(g['refs']), value, pkg, mpn, lcsc, '', '', g['ds']])
            n_codes += bool(lcsc); n_mpn += bool(mpn)
    print(f'{board}: {len(groups)} lines from {len(bought)} bought references ({len(rows)} symbols); {n_codes} lines with an LCSC code, {n_mpn} with an MPN -> {os.path.relpath(path, ROOT)}')
