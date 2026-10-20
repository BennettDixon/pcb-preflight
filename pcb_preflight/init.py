"""`preflight bom` (alias `init` for one release): write bom.csv from the symbol fields and the catalogue.

It reads the part each symbol already names (an LCSC code in a symbol field), asks the catalogue for that
part's record by code only, and writes bom.csv with the record's facts plus a Fetched column saying where
and when they came from. It never chooses a part (a symbol without a code stays a line without a code,
listed as such), never edits the schematic, and never silently drops a human's "Package verified" note.
Exit 0 when every line has a code and a record (COMPLETE), 3 when any line lacks one or the catalogue
could not answer (INCOMPLETE), 2 on a tool error. The write is deterministic: same inputs, same bytes.
Design: DESIGN.md §9 and the internal design note of 2026-10-18 (decisions 1-5).
"""
import csv
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter

from . import board as boardlib, bom as bomlib, catalogue, checks, kicad, stock

# Symbol field spellings, in priority order, each with the column it feeds and where the spelling is seen.
# kicad-cli matches field names exactly (case included, 10.0.7), so every spelling is listed as written.
# A spelling is added with its source, a corpus board or the tool that writes it, like a package synonym (DESIGN.md
# §9); a field a symbol lacks exports empty. The design note's guesses (LCSC_PART, JLCPCB Part #, JLCPCB, Mfr. Part #,
# Mfr) occurred on no corpus board and were dropped 2026-10-20; add one back with the board or tool that needs it.
FIELDS = [
    ('LCSC',          'LCSC', "kicad-jlcpcb-tools writes it; KiCad's JLCPCB symbol templates; corpus: canfd-mc, sonatino, sh-rpi, pocketpd, royalblue54l-feather, beyondex-limiter, bitaxegt"),
    ('LCSC Part #',   'LCSC', 'Fabrication Toolkit reads it; corpus: openjbod-rp2040'),
    ('LCSC Part',     'LCSC', 'JLCPCB KiCad Library symbols; corpus: jlcpcb-example, openair-max, cm5-minima'),
    ('JLCPCB_PN',     'LCSC', 'corpus: openjbod-rp2040 (beside LCSC Part #)'),
    ('lcsc#',         'LCSC', 'corpus: soldiercrab'),
    ('JLC',           'LCSC', 'corpus: tiny-tapeout'),
    ('MPN',           'MPN', 'KiCad convention; corpus: tiny-tapeout'),
    ('Manufacturer_Part_Number', 'MPN', 'corpus: cm5-minima'),
    ('Part Number',   'MPN', 'corpus: soldiercrab'),
    ('Manufacturer',  'Manufacturer', 'KiCad convention'),
]

OPEN_FIX = "put its C-number in the symbol's LCSC field, then run preflight bom again"


def field_names():
    return [f for f, _, _ in FIELDS]


def read_fields(row):
    """{column: (value, spelling)} from one export row: the first non-empty spelling per column wins;
    ``conflicts`` lists a second spelling on the same symbol that names a different code."""
    out, conflicts = {}, []
    for spelling, column, _ in FIELDS:
        v = (row.get(spelling) or '').strip()
        if column == 'LCSC':
            v = v.upper().replace(' ', '')
        if not v:
            continue
        if column in out:
            if column == 'LCSC' and out[column][0] != v:
                conflicts.append(f'field {spelling} says {v}, field {out[column][1]} says {out[column][0]}; {out[column][1]} kept')
            continue
        out[column] = (v, spelling)
    return out, conflicts


def codes_from_fields(rows):
    """ref -> the LCSC code its symbol field carries (for the bom-source gate; symbols without one are absent)."""
    return {r['Ref']: read_fields(r)[0]['LCSC'][0] for r in rows if 'LCSC' in read_fields(r)[0]}


def _bare(fp):
    return fp.split(':', 1)[-1]


def _norm(s):
    return re.sub(r'[\s\-_/,.]', '', s or '').upper()


def build(rows, existing, lookup, skip_prefixes=checks.DEFAULT_SKIP_PREFIXES, read=True):
    """Merge the schematic's bought symbols, the existing bom.csv lines and the catalogue into new lines.

    One line per (code, value, footprint), sorted by first reference. A field code wins over a differing
    line code (printed under ``changed``); a hand-entered line code is kept where the symbol carries no
    field. "Package verified" notes are carried over when the line's references and code are unchanged
    and the catalogue's package string is the one the note was written against; otherwise dropped and
    printed. Extra columns of the existing file are kept per line. Returns a dict for write() and report().
    """
    bought = checks.purchasable(rows, skip_prefixes)
    by_ref = {ref: ln for ln in existing for ref in ln.refs}
    extra_headers = []
    for ln in existing:
        for h in ln.extra:
            if h not in extra_headers:
                extra_headers.append(h)
    changed, fields_used = [], Counter()
    groups = {}
    for ref, row in bought.items():
        fields, conflicts = read_fields(row) if read else ({}, [])
        changed += [f'{ref}: {c}' for c in conflicts]
        ln = by_ref.get(ref)
        code_f = fields.get('LCSC', ('', ''))[0]
        code_l = ln.lcsc if ln else ''
        if code_f:
            fields_used[fields['LCSC'][1]] += 1
            if code_l and code_l != code_f:
                changed.append(f'{ref}: the schematic field says {code_f}, bom.csv (row {ln.row}) had {code_l}; the field wins')
        code = code_f or code_l
        g = groups.setdefault((code, row['Value'], row['Footprint']), {'refs': [], 'lines': [], 'mpn': '', 'mfr': ''})
        g['refs'].append(ref)
        if ln and ln not in g['lines']:
            g['lines'].append(ln)
        g['mpn'] = g['mpn'] or fields.get('MPN', ('', ''))[0]
        g['mfr'] = g['mfr'] or fields.get('Manufacturer', ('', ''))[0]

    records, failed = {}, {}
    for code, _, _ in groups:
        if code and code not in records and code not in failed:
            try:
                records[code] = lookup(code)
            except stock.LookupFailed as e:
                failed[code] = str(e)

    out_lines, kept, dropped, open_lines, open_codes = [], [], [], [], []
    written = 0
    noted = [ln for ln in existing if ln.package_verified]
    seen_notes = set()
    for key in sorted(groups, key=lambda k: checks.natural_key(min(groups[k]['refs'], key=checks.natural_key))):
        code, value, footprint = key
        g = groups[key]
        refs = sorted(g['refs'], key=checks.natural_key)
        label = f'{checks._refs(refs, 6)} ({value}, {_bare(footprint)})'
        line = {c: '' for c in bomlib.COLUMNS}
        line.update({'Ref': ','.join(refs), 'Value': value, 'Package': _bare(footprint), 'LCSC': code})
        rec = records.get(code) if code else None
        first = g['lines'][0] if g['lines'] else None
        if code and rec:
            line.update({'Package': rec.get('package', ''), 'MPN': rec.get('mpn', ''), 'Manufacturer': rec.get('manufacturer', ''),
                         'Basic/Extended': rec.get('library') or '', 'Stock': '' if rec.get('stock') is None else str(rec['stock']),
                         'Datasheet': rec.get('datasheet', ''), 'Fetched': catalogue.fetched_label(rec)})
            written += 1
            for ln in g['lines']:
                if ln.lcsc == code and ln.mpn and _norm(ln.mpn) != _norm(rec.get('mpn')):
                    changed.append(f'{",".join(refs)}: catalogue MPN {rec.get("mpn")} replaces the typed {ln.mpn} (same code {code})')
                if ln.lcsc == code and ln.package and ln.package not in (rec.get('package', ''), _bare(footprint)):
                    changed.append(f'{",".join(refs)}: catalogue package "{rec.get("package", "")}" replaces "{ln.package}" (same code {code})')
        else:
            line['MPN'] = g['mpn'] or (first.mpn if first else '')
            line['Manufacturer'] = g['mfr'] or (first.manufacturer if first else '')
            if not code:
                open_lines.append(label)
            elif code in failed:
                same = [ln for ln in g['lines'] if ln.lcsc == code and (ln.mpn or ln.library or ln.stock or ln.datasheet)]
                if same:                          # keep the facts the file already had, with their own Fetched label
                    ln = same[0]
                    line.update({'Package': ln.package or _bare(footprint), 'MPN': ln.mpn, 'Manufacturer': ln.manufacturer,
                                 'Basic/Extended': ln.library, 'Stock': ln.stock, 'Datasheet': ln.datasheet, 'Fetched': ln.fetched})
                open_codes.append(f'{label}: {code} not answered ({failed[code]})'
                                  + (f'; facts kept from bom.csv as written ({same[0].fetched or "undated"})' if same else ''))
            else:
                open_codes.append(f'{label}: {code} is not in the JLCPCB catalogue (wrong code, or the part was retired)')
        # a human's note is carried over by (references, code, footprint); the footprint is the one those references
        # have now, and the catalogue's package string must be the one the note was written against
        for ln in noted:
            if not set(ln.refs) & set(refs) or id(ln) in seen_notes:
                continue
            seen_notes.add(id(ln))
            why = []
            if set(ln.refs) != set(refs):
                why.append(f'references changed ({",".join(ln.refs)} -> {",".join(refs)})')
            if ln.lcsc != code:
                why.append(f'code changed ({ln.lcsc or "none"} -> {code or "none"})')
            if rec and ln.package and ln.package not in (rec.get('package', ''), _bare(footprint)):
                why.append(f'catalogue package string changed ("{ln.package}" -> "{rec.get("package", "")}")')
            if why:
                dropped.append(f'{",".join(ln.refs)}: "{ln.package_verified}" dropped: {"; ".join(why)}')
            else:
                line['Package verified'] = ln.package_verified
                kept.append(','.join(refs))
        exact = [ln for ln in g['lines'] if set(ln.refs) == set(refs)]
        src = exact[0] if exact else (g['lines'][0] if len(g['lines']) == 1 else None)
        for h in extra_headers:
            line[h] = src.extra.get(h, '') if src else ''
        out_lines.append(line)
    for ln in noted:
        if id(ln) not in seen_notes:
            dropped.append(f'{",".join(ln.refs)}: "{ln.package_verified}" dropped: no longer a bought reference in the schematic')
    return {'lines': out_lines, 'columns': bomlib.COLUMNS + extra_headers, 'written': written, 'kept': kept, 'dropped': dropped,
            'open': open_lines, 'open_codes': open_codes, 'changed': changed, 'fields': dict(fields_used),
            'missing': sorted(c for c, r in records.items() if r is None), 'failed': failed}


def write(path, result):
    """Deterministic: fixed column order, LF line endings, same inputs same bytes (the file diffs cleanly in review)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(result['columns'])
        for line in result['lines']:
            w.writerow([line.get(c, '') for c in result['columns']])


def verdict(result):
    reasons = []
    if result['open']:
        reasons.append(f'{len(result["open"])} line{"s" if len(result["open"]) != 1 else ""} without a code')
    if result['open_codes']:
        reasons.append(f'{len(result["open_codes"])} code{"s" if len(result["open_codes"]) != 1 else ""} without a record')
    return ('INCOMPLETE', 3, reasons) if reasons else ('COMPLETE', 0, [])


def report(name, result, source_summary, path, read=True, limit=20):
    v, code, reasons = verdict(result)
    n = len(result['lines'])
    out = [f'preflight bom: {name}  -  {n} line{"s" if n != 1 else ""}  -  {source_summary}']
    if not read:
        out.append('  fields    not read (bom-template): every line is open, Package is the footprint name')
    elif result['fields']:
        out.append('  fields    codes from ' + ', '.join(f'{k} ({v_})' for k, v_ in sorted(result['fields'].items(), key=lambda kv: -kv[1])))
    else:
        out.append('  fields    no symbol carries an LCSC code in a field (' + ', '.join(f for f, c, _ in FIELDS if c == 'LCSC') + ')')
    out.append(f'  written   {result["written"]} line{"s" if result["written"] != 1 else ""} from the catalogue record of their code')
    if result['kept'] or result['dropped']:
        out.append(f'  kept      {len(result["kept"])} "Package verified" note{"s" if len(result["kept"]) != 1 else ""}'
                   + (f' ({checks._refs(result["kept"], 8)})' if result['kept'] else '') + f'; {len(result["dropped"])} dropped')
        out.extend(f'            {d}' for d in result['dropped'][:limit])

    def block(word, items, head):
        if items:
            out.append(f'  {word:<9} {head}')
            out.extend(f'            {d}' for d in items[:limit])
            if len(items) > limit:
                out.append(f'            ... {len(items) - limit} more (--json lists all)')
    block('open', result['open'], f'{len(result["open"])} line{"s" if len(result["open"]) != 1 else ""} without a code: open each part on jlcpcb.com and {OPEN_FIX}')
    block('open', result['open_codes'], f'{len(result["open_codes"])} code{"s" if len(result["open_codes"]) != 1 else ""} without a catalogue record')
    block('changed', result['changed'], f'{len(result["changed"])} change{"s" if len(result["changed"]) != 1 else ""} against the previous bom.csv')
    out.append(f'  wrote     {path}')
    out.append(f'RESULT: {v}  -  ' + ('; '.join(reasons) if reasons else 'every line has a code and a record') + f'  -  exit {code}')
    return '\n'.join(out)


def run(a, read=True):
    """The `bom` / `init` command (and `bom-template` with read=False: no fields, no network)."""
    project_dir = os.path.abspath(a.project_dir)
    if not os.path.isdir(project_dir):
        raise ValueError(f'{project_dir} is not a directory')
    name = boardlib.project_name(project_dir, a.project)
    cli = kicad.find_cli(a.kicad_cli)
    bom_path = os.path.abspath(a.bom or os.path.join(project_dir, 'bom.csv'))
    skip_prefixes = tuple(p.strip().upper() for p in a.skip_prefix.split(',') if p.strip())
    sch = os.path.join(project_dir, name + '.kicad_sch')
    if not os.path.exists(sch):
        raise ValueError(f'{name}.kicad_sch not found in {project_dir}')
    existing = []
    if os.path.exists(bom_path):
        try:
            existing, _ = bomlib.load(bom_path)
        except UnicodeDecodeError as e:
            raise ValueError(f'{bom_path} is not UTF-8 (byte 0x{e.object[e.start]:02x} at offset {e.start}); save it as "CSV UTF-8" or move it aside')
    work = tempfile.mkdtemp(prefix='pcb-preflight-')
    try:
        from .cli import snapshot                # the export runs on a copy: kicad-cli writes beside a project
        src = snapshot(project_dir, work)
        rows = kicad.bom(cli, os.path.join(src, name + '.kicad_sch'), os.path.join(work, 'sch_bom.csv'),
                         fields=field_names() if read else ())
    finally:
        shutil.rmtree(work, ignore_errors=True)
    offline = a.offline or not read
    with catalogue.Catalogue(parts=getattr(a, 'catalogue', None), refresh=getattr(a, 'refresh', False), offline=offline) as cat:
        result = build(rows, existing, cat.lookup, skip_prefixes, read)
        summary = cat.summary()
    write(bom_path, result)
    v, code, reasons = verdict(result)
    text = report(name, result, summary, bom_path, read)
    print(text.splitlines()[-1] if a.quiet else text)
    if getattr(a, 'json', None):
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'schema': 1, 'command': 'bom', 'project': name, 'project_dir': project_dir, 'bom_path': bom_path,
                       'catalogue': summary, 'fields_read': read, 'offline': offline, 'result': v, 'exit_code': code, 'reasons': reasons,
                       **{k: result[k] for k in ('columns', 'lines', 'written', 'kept', 'dropped', 'open', 'open_codes', 'changed', 'fields', 'missing', 'failed')}},
                      f, indent=2)
    return code
