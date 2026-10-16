"""Minimal reader for KiCad's s-expression files (.kicad_pcb, .kicad_sch).

Every list becomes a Python list whose first element is the keyword; quoted strings and bare atoms
both become ``str``. Numbers stay strings until the caller asks for them, so nothing is lost.
"""
import re

_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def parse(text):
    stack = [[]]
    for m in _TOKEN.finditer(text):
        tok = m.group()
        if tok == '(':
            stack.append([])
        elif tok == ')':
            if len(stack) < 2:
                raise ValueError('unbalanced s-expression: too many ")"')
            node = stack.pop()
            stack[-1].append(node)
        elif tok[0] == '"':
            stack[-1].append(tok[1:-1].replace('\\"', '"').replace('\\\\', '\\'))
        else:
            stack[-1].append(tok)
    if len(stack) != 1:
        raise ValueError('unbalanced s-expression: missing ")"')
    if not stack[0]:
        raise ValueError('empty file')
    return stack[0][0]


def children(node, key):
    """All direct children of ``node`` whose keyword is ``key``."""
    return [n for n in node[1:] if isinstance(n, list) and n and n[0] == key]


def child(node, key, default=None):
    for n in node[1:]:
        if isinstance(n, list) and n and n[0] == key:
            return n
    return default


def find_all(node, key):
    """Every list anywhere under ``node`` whose keyword is ``key`` (depth first)."""
    out = []
    todo = [node]
    while todo:
        n = todo.pop()
        for c in n[1:] if isinstance(n, list) else ():
            if isinstance(c, list) and c:
                if c[0] == key:
                    out.append(c)
                todo.append(c)
    return out


def atoms(node):
    """The bare atoms of a node after its keyword, e.g. ``(attr smd dnp)`` -> ['smd', 'dnp']."""
    return [a for a in node[1:] if not isinstance(a, list)]


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
