"""Thin wrapper around kicad-cli: find it, run it, read its JSON reports.

Every call here is read-only on the project: reports go to a work directory the caller owns. Note that
kicad-cli itself writes a ``<board>.kicad_prl`` beside a board that has none, which is why the CLI runs
on a snapshot copy of the project by default (see cli.py).
"""
import csv
import json
import os
import shutil
import subprocess

CANDIDATES = [
    '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli',
    '/usr/bin/kicad-cli',
    '/usr/local/bin/kicad-cli',
    r'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe',
    r'C:\Program Files\KiCad\9.0\bin\kicad-cli.exe',
]

NOISE = ('Fontconfig', 'wxApp', 'wxWidgets')


class KicadError(RuntimeError):
    pass


def find_cli(explicit=None):
    for c in [explicit, os.environ.get('KICAD_CLI'), shutil.which('kicad-cli'), *CANDIDATES]:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise KicadError('kicad-cli not found; pass --kicad-cli or set KICAD_CLI')


def run(cli, *args, timeout=600):
    """Run kicad-cli; return (returncode, combined output without the usual font noise)."""
    try:
        r = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise KicadError(f'kicad-cli {args[0]} {args[1]} timed out after {timeout}s')
    lines = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip() and not any(n in ln for n in NOISE)]
    return r.returncode, '\n'.join(lines)


def version(cli):
    rc, out = run(cli, 'version')
    return out.strip().splitlines()[-1] if out else 'unknown'


def erc(cli, sch, out_json):
    rc, out = run(cli, 'sch', 'erc', '--format', 'json', '--output', out_json, sch)
    if not os.path.exists(out_json):
        raise KicadError(f'ERC produced no report:\n{out}')
    with open(out_json, encoding='utf-8') as f:
        return json.load(f), out


def drc(cli, pcb, out_json, parity=True):
    args = ['pcb', 'drc', '--format', 'json', '--output', out_json, '--all-track-errors']
    if parity:
        args.append('--schematic-parity')
    rc, out = run(cli, *args, pcb)
    if not os.path.exists(out_json):
        raise KicadError(f'DRC produced no report:\n{out}')
    with open(out_json, encoding='utf-8') as f:
        return json.load(f), out


def bom(cli, sch, out_csv):
    """One row per symbol: Ref, Value, Footprint, DNP, ExcludeFromBOM. Empty DNP/Exclude means false."""
    rc, out = run(cli, 'sch', 'export', 'bom', '--output', out_csv,
                  '--fields', 'Reference,Value,Footprint,${DNP},${EXCLUDE_FROM_BOM}',
                  '--labels', 'Ref,Value,Footprint,DNP,ExcludeFromBOM',
                  '--ref-range-delimiter', '', sch)
    if not os.path.exists(out_csv):
        raise KicadError(f'BOM export produced no file:\n{out}')
    with open(out_csv, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r['DNP'] = bool(r.get('DNP', '').strip())
        r['ExcludeFromBOM'] = bool(r.get('ExcludeFromBOM', '').strip())
    return rows


def count_severities(violations):
    errors = [v for v in violations if v.get('severity') == 'error']
    warnings = [v for v in violations if v.get('severity') == 'warning']
    return errors, warnings


def describe(v, limit=2):
    """One line for a violation: type, description and the first items' positions."""
    items = v.get('items', [])[:limit]
    where = '; '.join(f"{i.get('description', '')} @ ({i.get('pos', {}).get('x', '?')}, {i.get('pos', {}).get('y', '?')})" for i in items)
    return f"{v.get('type', '?')}: {v.get('description', '')}" + (f" [{where}]" if where else '')
