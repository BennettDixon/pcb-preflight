"""Live part lookup by LCSC code, for the stock gate (pitfalls §1 step 3, §2, §13).

Endpoints found in Oct 2026 that answer a bare LCSC code without a key (see DESIGN.md "Stock lookup"):

1. JLCPCB's own cart service (undocumented, used by the jlcpcb.com parts pages):
   GET https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail?componentCode=C14663
   -> data.stockCount, componentLibraryType ("base"/"expand"), componentModelEn (MPN),
      componentSpecificationEn (package), dataManualUrl, leastNumber, lossNumber (attrition),
      describe (the description: "100nF 50V X7R ±10% 0603 Multilayer Ceramic Capacitors MLCC - SMD/SMT ROHS"),
      firstSortName / secondSortName (the category: "Capacitors" / "Multilayer Ceramic Capacitors MLCC - SMD/SMT").
      componentDesignator is not used: JLCPCB files inductors, connectors, fuses and MOSFETs under "U".
2. tscircuit's jlcsearch (community mirror of the JLCPCB catalogue, documented at docs.tscircuit.com):
   GET https://jlcsearch.tscircuit.com/api/search?q=C14663&limit=5
   -> components[].{lcsc, mfr, package, is_basic, is_preferred, stock, price, description}; no category field,
      so the record's 'category' is empty and the gates that need one say they could not check.

Both may change without notice; a failure of one falls through to the other, and a failure of both is
reported as "not checked", never as a pass. There is no official JLCPCB parts API without a login.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

JLCPCB_DETAIL = 'https://cart.jlcpcb.com/shoppingCart/smtGood/getComponentDetail?componentCode={code}'
JLCSEARCH = 'https://jlcsearch.tscircuit.com/api/search?q={code}&limit=5'
HEADERS = {'User-Agent': 'pcb-preflight/0.1 (+https://github.com/bennettdixon/pcb-preflight)', 'Accept': 'application/json'}


class LookupFailed(Exception):
    """Network or endpoint failure: the part may exist; the check could not run."""


def _get(url, timeout):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _from_jlcpcb(code, timeout):
    try:
        d = _get(JLCPCB_DETAIL.format(code=code), timeout)
    except (urllib.error.URLError, ValueError, OSError) as e:
        raise LookupFailed(f'jlcpcb: {e}')
    if d.get('code') == 400 or not d.get('data'):
        return None                      # JLCPCB answers 400 "Parameter exception" for an unknown code
    data = d['data']
    lib = {'base': 'Basic', 'expand': 'Extended'}.get(data.get('componentLibraryType'), data.get('componentLibraryType'))
    if data.get('preferredComponentFlag'):
        lib = 'Preferred'
    category = ' / '.join(x for x in (data.get('firstSortName', ''), data.get('secondSortName', '')) if x)
    return {
        'source': 'jlcpcb', 'lcsc': data.get('componentCode', code), 'mpn': data.get('componentModelEn', ''),
        'manufacturer': data.get('componentBrandEn', ''), 'package': data.get('componentSpecificationEn', ''),
        'library': lib, 'stock': data.get('stockCount'), 'datasheet': data.get('dataManualUrl', ''),
        'min_qty': data.get('leastNumber'), 'attrition': data.get('lossNumber'),
        'description': data.get('describe', ''), 'category': category,
    }


def _from_jlcsearch(code, timeout):
    try:
        d = _get(JLCSEARCH.format(code=urllib.parse.quote(code)), timeout)
    except (urllib.error.URLError, ValueError, OSError) as e:
        raise LookupFailed(f'jlcsearch: {e}')
    num = int(code[1:])
    for c in d.get('components', []):
        if c.get('lcsc') == num:
            return {
                'source': 'jlcsearch', 'lcsc': code, 'mpn': c.get('mfr', ''), 'manufacturer': '',
                'package': c.get('package', ''),
                'library': 'Preferred' if c.get('is_preferred') else ('Basic' if c.get('is_basic') else 'Extended'),
                'stock': c.get('stock'), 'datasheet': '', 'min_qty': None, 'attrition': None,
                'description': c.get('description', ''), 'category': '',
            }
    return None


def lookup(code, timeout=15, pause=0.2):
    """Catalog record for an LCSC code, None when no catalogue knows it, LookupFailed when none could answer."""
    errors = []
    for fn in (_from_jlcpcb, _from_jlcsearch):
        try:
            rec = fn(code, timeout)
        except LookupFailed as e:
            errors.append(str(e))
            continue
        time.sleep(pause)
        return rec
    raise LookupFailed('; '.join(errors))
