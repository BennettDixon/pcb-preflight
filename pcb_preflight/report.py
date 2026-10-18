"""Print the gate's result the way a review doc reads: the verdict first, then checked and left alone,
findings, order, not checked, by hand, and the verdict again at the end for a log's tail.

A gate that ran but could not judge some items prints its line where its status puts it and lists those
items again under NOT CHECKED; items a human vouched for print under the gate as "by hand"; what a gate did
and under which settings prints as a note, never as a finding. The RESULT line is one of the four verdicts
in preset.py (PASS, FAIL, ERROR, NOT VERIFIED) and says what it means.
"""
import json
import os

from . import preset

STATUSES = ('pass', 'warn', 'fail', 'skip', 'cost')
MARK = {'fail': 'FAIL', 'warn': 'WARN', 'skip': 'SKIP', 'pass': 'ok', 'cost': 'COST'}


def verdict(checks, strict=False):
    """PASS, FAIL, ERROR or NOT VERIFIED. ERROR outranks FAIL, which outranks NOT VERIFIED (preset.py).

    A skipped core gate is ERROR. Any other skipped gate, and any gate with items it could not judge, is
    NOT VERIFIED: something was not checked, so the result is not a pass. A ``cost`` gate is ignored here:
    what moves the price does not stop the order, and --strict does not promote it.
    """
    if any(c.status == 'skip' and c.id in preset.CORE for c in checks):
        return preset.ERROR
    bad = {'fail', 'warn'} if strict else {'fail'}
    if any(c.status in bad for c in checks):
        return preset.FAIL
    if any(c.status == 'skip' or c.unchecked for c in checks):
        return preset.NOT_VERIFIED
    return preset.PASS


def _meaning(v, checks, online):
    if v == preset.PASS:
        return (f'every gate ran under {preset.PRESET} and judged every item it saw; what no file-level check can see '
                f'is listed under BY HAND BEFORE ORDERING')
    if v == preset.FAIL:
        n = sum(1 for c in checks if c.status == 'fail')
        return f'{n} finding{"s" if n != 1 else ""} block{"" if n != 1 else "s"} the order (FAIL lines under FINDINGS); fix them and run again'
    if v == preset.ERROR:
        names = ', '.join(c.title for c in checks if c.status == 'skip' and c.id in preset.CORE)
        return f'a core gate did not run ({names}); nothing in this report is a pass'
    n = sum(1 for c in checks if c.status == 'skip' or c.unchecked)
    return (f'{n} gate{"s" if n != 1 else ""} could not check everything (see NOT CHECKED); not a pass'
            + ('' if online else '  -  run with --online to ask the catalogue'))


def cost_drivers(checks):
    """How many lines the ORDER section carries: one per driver off the standard tier."""
    return sum(len(c.details) for c in checks if c.status == 'cost')


def _result_lines(checks, strict, online):
    n_fail = sum(1 for c in checks if c.status == 'fail')
    n_warn = sum(1 for c in checks if c.status == 'warn')
    n_unv = sum(1 for c in checks if c.status == 'skip' or c.unchecked)
    v = verdict(checks, strict)
    lines = [f"RESULT: {v}  -  {n_fail} blocking, {n_warn} warnings, {n_unv} not checked, {cost_drivers(checks)} cost drivers  -  exit {preset.EXIT[v]}"
             + ('  (--strict: warnings block)' if strict else ''),
             f'  {_meaning(v, checks, online)}']
    if v == preset.ERROR:
        lines += [f'  {c.title}: {c.summary}' for c in checks if c.status == 'skip' and c.id in preset.CORE]
    return lines


def render(result, max_details=15, strict=False):
    checks = result['checks']
    online = result.get('options', {}).get('online', False)
    bom = result.get('bom_path')
    out = [f"{result['project']}  -  KiCad {result['kicad_version']}  -  {result.get('preset', preset.PRESET)}  -  "
           f"{'online' if online else 'offline'}  -  {result['copper_layers']} copper layers, {result['footprints']} footprints"
           f"  -  bom.csv: {os.path.basename(bom) if bom else 'none'}"]
    out += _result_lines(checks, strict, online)
    out.append('')
    passed = [c for c in checks if c.status == 'pass']
    found = [c for c in checks if c.status in ('fail', 'warn')]
    cost = [c for c in checks if c.status == 'cost']
    skipped = [c for c in checks if c.status == 'skip']
    partial = [c for c in checks if c.status != 'skip' and c.unchecked]

    def notes_and_verified(c):
        for d in c.notes[:max_details]:
            out.append(f'        note: {d}')
        for d in c.verified[:max_details]:
            out.append(f'        by hand: {d}')

    out.append('CHECKED AND LEFT ALONE')
    for c in passed:
        out.append(f'  {c.title} ({c.pitfall}): {c.summary}')
        notes_and_verified(c)
    if not passed:
        out.append('  nothing')
    out.append('')
    out.append('FINDINGS')
    for c in found:
        out.append(f'  {MARK[c.status]}  {c.title} ({c.pitfall}): {c.summary}')
        for d in c.details[:max_details]:
            out.append(f'        {d}')
        if len(c.details) > max_details:
            out.append(f'        ... {len(c.details) - max_details} more (--max-details)')
        notes_and_verified(c)
    if not found:
        out.append('  none')
    out.append('')
    out.append("ORDER (what moves the price off JLCPCB's standard tier; the quote page prices it)")
    for c in cost:
        out.append(f'  {MARK[c.status]}  {c.title} ({c.pitfall}): {c.summary}')
        for d in c.details[:max_details]:
            out.append(f'        {d}')
        if len(c.details) > max_details:
            out.append(f'        ... {len(c.details) - max_details} more (--max-details)')
        notes_and_verified(c)
    if not cost:
        out.append('  nothing: every driver the files can show is on the standard tier' if any(c.id == 'order' for c in checks) else '  none')
    out.append('')
    out.append('NOT CHECKED')
    for c in skipped:
        out.append(f'  {c.title} ({c.pitfall}): {c.summary}')
        for d in (c.details + c.unchecked)[:max_details]:
            out.append(f'        {d}')
    for c in partial:
        out.append(f'  {c.title} ({c.pitfall}): {len(c.unchecked)} not compared')
        for d in c.unchecked[:max_details]:
            out.append(f'        {d}')
        if len(c.unchecked) > max_details:
            out.append(f'        ... {len(c.unchecked) - max_details} more (--max-details)')
    if not skipped and not partial:
        out.append('  nothing: every gate ran in full')
    out.append('')
    out.append('BY HAND BEFORE ORDERING')
    for line in result['by_hand']:
        out.append(f'  - {line}')
    out.append('')
    out += _result_lines(checks, strict, online)
    return '\n'.join(out)


def to_json(result, strict=False):
    d = dict(result)
    d['checks'] = [c.as_dict() for c in result['checks']]
    d['result'] = verdict(result['checks'], strict)
    d['exit_code'] = preset.EXIT[d['result']]
    return json.dumps(d, indent=2)
