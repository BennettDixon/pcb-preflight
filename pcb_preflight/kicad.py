"""Thin wrapper around kicad-cli: find it, run it, read its JSON reports.

Every call here is read-only on the project: reports go to a work directory the caller owns. Note that
kicad-cli itself writes a ``<board>.kicad_prl`` beside a board that has none, which is why the CLI runs
on a snapshot copy of the project (see cli.py).
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


def _runnable(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find_cli(explicit=None):
    """The kicad-cli to run. An explicit path (--kicad-cli, then $KICAD_CLI) is authoritative: a wrong one
    is an error, never silently replaced by whatever else is installed."""
    for name, path in (('--kicad-cli', explicit), ('$KICAD_CLI', os.environ.get('KICAD_CLI'))):
        if path:
            if _runnable(path):
                return path
            raise KicadError(f'{name} {path}: not an executable file')
    for c in [shutil.which('kicad-cli'), *CANDIDATES]:
        if _runnable(c):
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


def _cause(out):
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else 'kicad-cli printed nothing'


def erc(cli, sch, out_json):
    """ERC report with every severity included (errors, warnings and the project's exclusions)."""
    rc, out = run(cli, 'sch', 'erc', '--format', 'json', '--severity-all', '--output', out_json, sch)
    if not os.path.exists(out_json):
        raise KicadError(f'ERC produced no report: {_cause(out)}')
    with open(out_json, encoding='utf-8') as f:
        return json.load(f), out


def drc(cli, pcb, out_json, parity=True):
    """DRC report with every severity included, so excluded violations are visible to the gate."""
    args = ['pcb', 'drc', '--format', 'json', '--severity-all', '--output', out_json, '--all-track-errors']
    if parity:
        args.append('--schematic-parity')
    rc, out = run(cli, *args, pcb)
    if not os.path.exists(out_json):
        raise KicadError(f'DRC produced no report: {_cause(out)}')
    with open(out_json, encoding='utf-8') as f:
        return json.load(f), out


def bom(cli, sch, out_csv):
    """One row per symbol: Ref, Value, Footprint, DNP, ExcludeFromBOM, ExcludeFromBoard. Empty flags mean false."""
    rc, out = run(cli, 'sch', 'export', 'bom', '--output', out_csv,
                  '--fields', 'Reference,Value,Footprint,${DNP},${EXCLUDE_FROM_BOM},${EXCLUDE_FROM_BOARD}',
                  '--labels', 'Ref,Value,Footprint,DNP,ExcludeFromBOM,ExcludeFromBoard',
                  '--ref-range-delimiter', '', sch)
    if not os.path.exists(out_csv):
        raise KicadError(f'BOM export produced no file: {_cause(out)}')
    with open(out_csv, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for flag in ('DNP', 'ExcludeFromBOM', 'ExcludeFromBoard'):
            r[flag] = bool((r.get(flag) or '').strip())
    return rows


def is_excluded(v):
    """kicad-cli keeps an excluded violation's own severity and marks it ``"excluded": true`` (KiCad 10.0.7,
    ERC and DRC alike); it appears only under --severity-all / --severity-exclusions. The ``exclusion``
    severity string, which the report's included_severities lists, is kept as a fallback."""
    return bool(v.get('excluded')) or v.get('severity') == 'exclusion'


def count_severities(violations):
    """(errors, warnings, excluded): live errors, live warnings (anything not an error), and the project's exclusions."""
    excluded = [v for v in violations if is_excluded(v)]
    live = [v for v in violations if not is_excluded(v)]
    errors = [v for v in live if v.get('severity') == 'error']
    warnings = [v for v in live if v.get('severity') != 'error']
    return errors, warnings, excluded


def describe(v, limit=2):
    """One line for a violation: type, description and the first items' positions."""
    items = v.get('items', [])[:limit]
    where = '; '.join(f"{i.get('description', '')} @ ({i.get('pos', {}).get('x', '?')}, {i.get('pos', {}).get('y', '?')})" for i in items)
    return f"{v.get('type', '?')}: {v.get('description', '')}" + (f" [{where}]" if where else '')
