"""The contract: what each result promises, what the gate owns, and the exit codes.

  PASS          exit 0   Every gate ran under this preset and judged every item it saw. The board may be
                         ordered as far as a file-level check can tell; the BY HAND list is still yours.
  FAIL          exit 1   A finding blocks the order.
  ERROR         exit 2   A core gate did not run (kicad-cli failed, a file is missing or unreadable).
                         Nothing in the report is a pass.
  NOT VERIFIED  exit 3   Every core gate ran and nothing blocks, but something could not be checked: the
                         catalogue was not asked (no --online) or did not answer, a BOM line has no MPN to
                         compare, a footprint has no courtyard, or a package could not be compared and
                         nobody signed for it. Not a pass.

The preset names what the gate owns. KiCad applies the project's own settings when kicad-cli runs ERC and
DRC, and the project is the thing under review; so before running them the gate rewrites, in its snapshot
copy of the .kicad_pro (never in the user's file):

* the severity of the protected checks, to "error": a check the project set to "warning" or "ignore"
  still runs and still blocks. The protected set is KiCad's own default errors that decide whether the fab
  can make and assemble the board as drawn, plus the parity checks (KiCad ships them as warnings) and
  missing_courtyard (KiCad ignores it; courtyards_overlap can only see footprints that have one). A
  protected violation the project excluded blocks too. Every other check keeps the project's choice.
* the ERC pin-conflict matrix, cell by cell, to no weaker than KiCad's default.
* the board's minimum constraints and netclass clearances, to no lower than the fab's published
  capability, so a project with min_track_width 0 does not pass a 0.05 mm track.

Custom design rules (<name>.kicad_dru) are not copied into the snapshot: a rule can relax or mute a
protected constraint, and the gate checks the fab's limits, not the designer's own rules. The report says
when the project has one.
"""
import json

PRESET = 'jlcpcb-assembly@2026.10'

PASS, FAIL, ERROR, NOT_VERIFIED = 'PASS', 'FAIL', 'ERROR', 'NOT VERIFIED'
EXIT = {PASS: 0, FAIL: 1, ERROR: 2, NOT_VERIFIED: 3}

# Gates whose skip means the run cannot be trusted at all (ERROR, exit 2).
CORE = ('erc', 'drc', 'unrouted', 'parity', 'identity', 'placement', 'sch-bom')

# Schematic / PCB parity (§5). kicad-cli also files footprint_symbol_field_mismatch (field text) and
# footprint_filters_mismatch (a library hint) under schematic_parity; those keep the project's severity.
PARITY = frozenset({'missing_footprint', 'extra_footprint', 'duplicate_footprints', 'net_conflict', 'footprint_symbol_mismatch'})

# DRC checks the gate owns: run as errors, never ignored or excluded. KiCad's rule_severities keys.
DRC_PROTECTED = frozenset({
    # connectivity and copper
    'unconnected_items', 'shorting_items', 'tracks_crossing', 'zones_intersect',
    # the fab's manufacturing limits
    'clearance', 'hole_clearance', 'copper_edge_clearance', 'track_width', 'annular_width',
    'drill_out_of_range', 'microvia_drill_out_of_range', 'solder_mask_bridge', 'through_hole_pad_without_hole',
    'invalid_outline', 'text_on_edge_cuts', 'items_not_allowed', 'item_on_disabled_layer', 'courtyards_overlap',
    'missing_courtyard', 'unresolved_variable',
}) | PARITY

# ERC checks the gate owns. KiCad's erc.rule_severities keys. pin_to_pin is the on/off switch for the pin
# matrix below (KiCad ships the key as "warning"; the matrix decides warning or error per pair).
ERC_PROTECTED = frozenset({
    'pin_not_connected', 'pin_not_driven', 'power_pin_not_driven', 'pin_to_pin', 'duplicate_reference', 'unannotated',
    'different_unit_net', 'different_unit_footprint', 'unit_value_mismatch', 'extra_units', 'missing_power_pin',
    'label_dangling', 'wire_dangling', 'hier_label_mismatch', 'duplicate_sheet_names', 'unresolved_variable',
    'bus_definition_conflict', 'bus_to_bus_conflict', 'bus_to_net_conflict',
})

# KiCad's own non-error defaults, so the report only says "the project had X" when the project changed X.
# Sources, read 2026-10-16: KiCad 10.0 pcbnew/board_design_settings.cpp and eeschema/erc/erc_settings.cpp
# (the overrides after "Error is the default setting so set non-error priorities here"), cross-checked with
# the 19 project templates KiCad 10.0.7 ships (SharedSupport/template/*/*.kicad_pro, all identical).
KICAD_DEFAULT = {
    'drc': {
        'connection_width': 'warning', 'copper_sliver': 'warning', 'duplicate_footprints': 'warning',
        'extra_footprint': 'warning', 'footprint_symbol_field_mismatch': 'warning', 'footprint_symbol_mismatch': 'warning',
        'hole_to_hole': 'warning', 'holes_co_located': 'warning', 'isolated_copper': 'warning',
        'lib_footprint_issues': 'warning', 'lib_footprint_mismatch': 'warning', 'mirrored_text_on_front_layer': 'warning',
        'missing_footprint': 'warning', 'missing_tuning_profile': 'warning', 'net_conflict': 'warning',
        'nonmirrored_text_on_back_layer': 'warning', 'padstack': 'warning', 'silk_edge_clearance': 'warning',
        'silk_over_copper': 'warning', 'silk_overlap': 'warning', 'text_height': 'warning', 'text_thickness': 'warning',
        'track_dangling': 'warning', 'via_dangling': 'warning',
        'footprint_filters_mismatch': 'ignore', 'footprint_type_mismatch': 'ignore', 'missing_courtyard': 'ignore',
        'npth_inside_courtyard': 'ignore', 'pth_inside_courtyard': 'ignore', 'track_not_centered_on_via': 'ignore',
        'tuning_profile_track_geometries': 'ignore',
    },
    'erc': {
        'bus_entry_needed': 'warning', 'endpoint_off_grid': 'warning', 'field_name_whitespace': 'warning',
        'footprint_link_issues': 'warning', 'global_label_dangling': 'warning', 'ground_pin_not_ground': 'warning',
        'isolated_pin_label': 'warning', 'label_multiple_wires': 'warning', 'lib_symbol_issues': 'warning',
        'lib_symbol_mismatch': 'warning', 'missing_bidi_pin': 'warning', 'missing_input_pin': 'warning',
        'missing_unit': 'warning', 'multiple_net_names': 'warning', 'net_not_bus_member': 'warning',
        'no_connect_connected': 'warning', 'no_connect_dangling': 'warning', 'pin_to_pin': 'warning',
        'same_local_global_label': 'warning', 'same_local_global_power': 'warning', 'similar_label_and_power': 'warning',
        'similar_labels': 'warning', 'similar_power': 'warning', 'stacked_pin_name': 'warning',
        'unconnected_wire_endpoint': 'warning',
        'footprint_filter': 'ignore', 'four_way_junction': 'ignore', 'simulation_model_issue': 'ignore',
        'single_global_label': 'ignore',
    },
}

# KiCad's default ERC pin-conflict matrix (0 ok, 1 warning, 2 error), rows and columns in KiCad's pin-type
# order. Read from the 19 KiCad 10.0.7 project templates, 2026-10-16 (all identical). A project's matrix
# is raised to this cell by cell; a stricter project cell survives.
PIN_TYPES = ('input', 'output', 'bidirectional', 'tri_state', 'passive', 'free', 'unspecified',
             'power_in', 'power_out', 'open_collector', 'open_emitter', 'no_connect')
DEFAULT_PIN_MAP = [
    [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 2],
    [0, 2, 0, 1, 0, 0, 1, 0, 2, 2, 2, 2],
    [0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 2],
    [0, 1, 0, 0, 0, 0, 1, 1, 2, 1, 1, 2],
    [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 2],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2],
    [1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 2],
    [0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 2],
    [0, 2, 1, 2, 0, 0, 1, 0, 2, 2, 2, 2],
    [0, 2, 0, 1, 0, 0, 1, 0, 2, 0, 0, 2],
    [0, 2, 1, 1, 0, 0, 1, 0, 2, 0, 0, 2],
    [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
]

# The fab's minimums, in mm, as KiCad board-setup constraint keys (board.design_settings.rules). Source:
# JLCPCB PCB capabilities, https://jlcpcb.com/capabilities/pcb-capabilities, read 2026-10-16, for 1 oz
# copper; the files do not say the copper weight, so the report names the assumption (2 oz needs
# 0.16/0.16 mm on 1-2 layers and 0.15/0.15 mm on more). A project value above the floor is kept.
MINIMUMS_COPPER_WEIGHT = '1 oz'
MINIMUMS_COMMON = {
    'min_through_hole_diameter': 0.15,    # via hole 0.15 mm (the smallest standard drill)
    'min_via_diameter': 0.25,             # via diameter 0.25 mm
    'min_via_annular_width': 0.05,        # (0.25 - 0.15) / 2 for that via
    'min_hole_to_hole': 0.20,             # via hole to via hole 0.2 mm (pad holes want 0.45)
    'min_copper_edge_clearance': 0.20,    # copper to routed board edge 0.2 mm
}
MINIMUMS_BY_LAYERS = {
    2: {'min_track_width': 0.10, 'min_clearance': 0.10},     # 1-2 layers: 0.10 / 0.10 mm (4 / 4 mil)
    4: {'min_track_width': 0.09, 'min_clearance': 0.09},     # multilayer: 0.09 / 0.09 mm (3.5 / 3.5 mil)
}


def minimums(copper_layers):
    return dict(MINIMUMS_COMMON, **MINIMUMS_BY_LAYERS[2 if copper_layers <= 2 else 4])


def _load(pro_path):
    try:
        with open(pro_path, encoding='utf-8') as f:
            pro = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f'{pro_path}: not valid JSON ({e})')
    if not isinstance(pro, dict):
        raise ValueError(f'{pro_path}: not a KiCad project file (expected a JSON object)')
    return pro


def _number(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def apply(pro_path, copper_layers=2):
    """Rewrite what the gate owns in a .kicad_pro (the snapshot copy, never the user's file).

    Returns what the project had that the gate changed, so the report can say so:
    {"drc": {check: project severity}, "erc": {...}      protected checks the project had weaker than KiCad's default
     "pin_map": n                                        pin-matrix cells weaker than KiCad's default (0: none)
     "minimums": {key: (project value, floor)}           board minimums below the fab's
     "netclasses": {name: (project clearance, floor)}}   netclass clearances below the fab's
    """
    pro = _load(pro_path)
    changed = {'drc': {}, 'erc': {}, 'pin_map': 0, 'minimums': {}, 'netclasses': {}}
    ds = pro.setdefault('board', {}).setdefault('design_settings', {})
    for kind, protected, sev in (('drc', DRC_PROTECTED, ds.setdefault('rule_severities', {})),
                                 ('erc', ERC_PROTECTED, pro.setdefault('erc', {}).setdefault('rule_severities', {}))):
        for key in sorted(protected):
            default = KICAD_DEFAULT[kind].get(key, 'error')
            if sev.get(key, default) != default:
                changed[kind][key] = sev[key]
            sev[key] = 'error'

    erc = pro['erc']
    pin_map = erc.get('pin_map')
    if isinstance(pin_map, list) and len(pin_map) == 12 and all(isinstance(r, list) and len(r) == 12 for r in pin_map):
        for i in range(12):
            for j in range(12):
                if not isinstance(pin_map[i][j], int) or pin_map[i][j] < DEFAULT_PIN_MAP[i][j]:
                    changed['pin_map'] += 1
                    pin_map[i][j] = DEFAULT_PIN_MAP[i][j]
    elif pin_map is not None:                       # malformed: kicad-cli then uses its built-in default
        erc.pop('pin_map')
        changed['pin_map'] = 144

    rules = ds.setdefault('rules', {})
    floors = minimums(copper_layers)
    for key, floor in floors.items():
        if _number(rules.get(key)) < floor:
            changed['minimums'][key] = (rules.get(key), floor)
            rules[key] = floor
    for nc in pro.get('net_settings', {}).get('classes', []) or []:
        if isinstance(nc, dict) and 'clearance' in nc and _number(nc['clearance']) < floors['min_clearance']:
            changed['netclasses'][str(nc.get('name', '?'))] = (nc['clearance'], floors['min_clearance'])
            nc['clearance'] = floors['min_clearance']

    with open(pro_path, 'w', encoding='utf-8') as f:
        json.dump(pro, f, indent=2)
    return changed
