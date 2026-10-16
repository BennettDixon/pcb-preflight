"""Print the gate's result the way a review doc reads: checked and left alone, findings, not checked."""
import json

MARK = {'fail': 'FAIL', 'warn': 'WARN', 'skip': 'SKIP', 'pass': 'ok'}


def verdict(checks, strict=False):
    bad = {'fail', 'warn'} if strict else {'fail'}
    return 'FAIL' if any(c.status in bad for c in checks) else 'PASS'


def render(result, max_details=15, strict=False):
    checks = result['checks']
    out = [f"{result['project']}  -  KiCad {result['kicad_version']}  -  {result['copper_layers']} copper layers, "
           f"{result['footprints']} footprints  -  bom.csv: {result['bom_path'] or 'none'}", '']
    passed = [c for c in checks if c.status == 'pass']
    found = [c for c in checks if c.status in ('fail', 'warn')]
    skipped = [c for c in checks if c.status == 'skip']

    out.append('CHECKED AND LEFT ALONE')
    for c in passed:
        out.append(f'  {c.title} ({c.pitfall}): {c.summary}')
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
    if not found:
        out.append('  none')
    out.append('')
    out.append('NOT CHECKED')
    for c in skipped:
        out.append(f'  {c.title} ({c.pitfall}): {c.summary}')
        for d in c.details[:max_details]:
            out.append(f'        {d}')
    if not skipped:
        out.append('  nothing: every gate ran')
    out.append('')
    out.append('BY HAND BEFORE ORDERING')
    for line in result['by_hand']:
        out.append(f'  - {line}')
    out.append('')
    n_fail = sum(1 for c in checks if c.status == 'fail')
    n_warn = sum(1 for c in checks if c.status == 'warn')
    v = verdict(checks, strict)
    out.append(f"RESULT: {v}  -  {n_fail} blocking, {n_warn} warnings, {len(skipped)} not checked" + ('  (--strict: warnings block)' if strict else ''))
    return '\n'.join(out)


def to_json(result, strict=False):
    d = dict(result)
    d['checks'] = [c.as_dict() for c in result['checks']]
    d['result'] = verdict(result['checks'], strict)
    return json.dumps(d, indent=2)
