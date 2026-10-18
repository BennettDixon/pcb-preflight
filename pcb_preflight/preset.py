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
  still runs and still blocks. The protected set is the KiCad default errors that decide whether the fab
  can make and assemble the board as drawn, plus the parity checks (KiCad ships them as warnings) and
  missing_courtyard (KiCad ignores it; courtyards_overlap can only see footprints that have one). A
  protected violation the project excluded blocks too.
* the severity of the demoted checks, to "warning": KiCad's electrical-intent ERC errors (ERC_DEMOTED) and
  the courtyard-overlap and solder-mask-bridge DRC checks (DRC_DEMOTED). They still run and are listed;
  they do not block, because none decides whether the fab can build the board (--strict promotes them).
  The corpus of public boards (corpus/RESULTS.md) is the evidence: they blocked most of the boards that
  had been ordered and built. Every other check keeps the project's choice.
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
    'drill_out_of_range', 'microvia_drill_out_of_range', 'through_hole_pad_without_hole',
    'invalid_outline', 'text_on_edge_cuts', 'items_not_allowed', 'item_on_disabled_layer',
    'missing_courtyard', 'unresolved_variable',
}) | PARITY

# DRC checks the gate runs as warnings whatever the project says: the designer wants to see them, but the fab
# builds and places the board regardless (the corpus, 2026-10-17: 10 of 21 public boards blocked on them, 7
# of those ordered and sold). --strict blocks them.
DRC_DEMOTED = frozenset({'courtyards_overlap', 'solder_mask_bridge'})

# ERC checks the gate owns: the ones that decide whether the fab gets one unambiguous part per reference.
# KiCad's erc.rule_severities keys.
ERC_PROTECTED = frozenset({
    'duplicate_reference', 'unannotated', 'different_unit_net', 'different_unit_footprint', 'unit_value_mismatch',
    'extra_units', 'duplicate_sheet_names', 'unresolved_variable',
    'bus_definition_conflict', 'bus_to_bus_conflict', 'bus_to_net_conflict',
})

# KiCad's electrical-intent errors, run as warnings whatever the project says: an unconnected pin, an undriven
# power pin (the missing PWR_FLAG, which blocked 15 of the corpus's 21 boards, 11 of them built), two outputs
# tied together, a dangling label. They are about whether the circuit is what the designer meant, not about
# whether the fab can build it, and --strict blocks them. pin_to_pin is the on/off switch for the pin matrix
# below; the matrix decides warning or error per pair, so its cells are capped at warning as well.
ERC_DEMOTED = frozenset({
    'pin_not_connected', 'pin_not_driven', 'power_pin_not_driven', 'pin_to_pin', 'missing_power_pin',
    'label_dangling', 'wire_dangling', 'hier_label_mismatch',
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

# ---- Price tiers: the data behind the ORDER section ----------------------------------------------------
# What in the files moves the order off JLCPCB's standard (cheapest) option, as sourced tables: the figure
# the gate finds lands in a tier, and the report names the tier and its condition, never a dollar amount.
# Dollar amounts are deliberately not stored (they move with exchange rates); every table runs from the
# standard option downward; nothing here is read live. Every table names its sources in TIERS_SOURCES.
# The quote page was probed on 2026-10-18 on its defaults (FR-4, 2 layers, 100 × 100 mm, 5 pieces, 1.6 mm,
# green, HASL, 1 oz), one option changed at a time, reading the option list, the greyed-out options'
# messages and the "Charge Details" panel after each change. The gate change that uses these tables is a
# later task; MINIMUMS_COMMON above is still the floor until then.
TIERS_READ = '2026-10-18'
TIERS_SOURCES = {
    'quote': ('https://cart.jlcpcb.com/quote', '2026-10-18'),
    'capabilities': ('https://jlcpcb.com/capabilities/pcb-capabilities', '2026-10-18'),
    'pcba-capabilities': ('https://jlcpcb.com/capabilities/pcb-assembly-capabilities', '2026-10-18'),
    'pcba-price': ('https://jlcpcb.com/help/article/pcb-assembly-price', '2026-10-18'),        # "Last updated on Sep 09, 2026"
    'pcba-faqs': ('https://jlcpcb.com/help/article/pcb-assembly-faqs', '2026-10-18'),          # "Last updated on Sep 09, 2026"
    'production-time': ('https://jlcpcb.com/help/article/pcb-fabrication-services-and-production-time', '2026-10-18'),
    'dimensions': ('https://jlcpcb.com/help/article/pcb-dimensions', '2026-10-18'),
    'castellated': ('https://jlcpcb.com/help/article/what-is-castellated-holes', '2026-10-18'),
    'blog-pcba-cost': ('https://jlcpcb.com/blog/reduce-pcb-assembly-cost-prototype', '2026-10-18'),  # published 2026-10-13, prices read there 2026-10-09
}

# Via tiers: the quote page's "Min via hole size/diameter" options, hole/(minimum diameter/preferred diameter)
# in mm, standard first. The capabilities page: "Via diameter should be 0.1mm(0.15mm preferred) larger than
# Via hole size", "Preferred Min. Via hole size: 0.2mm", and "0.1mm or 0.15mm hole size with any size via
# diameter, and 0.2mm or 0.25mm hole size with via diameter less than 0.45mm, will cost more. Please select
# corresponding via size option when placing order." The figure the gate reads is the board's smallest via
# hole; the tier it lands in is the first row whose min_hole it is not below.
_SMALL_VIA = 'priced; the quote page adds "Plugged Via" and the "4-Wire Kelvin Test" itself'
VIA_TIERS = [
    {'option': '0.3mm/(0.4/0.45mm)', 'min_hole': 0.30, 'min_diameter': 0.40, 'preferred_diameter': 0.45, 'standard': True, 'condition': ''},
    {'option': '0.25mm/(0.35/0.4mm)', 'min_hole': 0.25, 'min_diameter': 0.35, 'preferred_diameter': 0.40, 'standard': False, 'condition': _SMALL_VIA},
    {'option': '0.2mm/(0.3/0.35mm)', 'min_hole': 0.20, 'min_diameter': 0.30, 'preferred_diameter': 0.35, 'standard': False, 'condition': _SMALL_VIA},
    {'option': '0.15mm/(0.25/0.3mm)', 'min_hole': 0.15, 'min_diameter': 0.25, 'preferred_diameter': 0.30, 'standard': False, 'condition': _SMALL_VIA},
    {'option': '0.1mm/(0.2/0.25mm)', 'min_hole': 0.10, 'min_diameter': 0.20, 'preferred_diameter': 0.25, 'standard': False,
     'condition': 'priced; board thickness 1.0 mm or less and ENIG or OSP finish (the quote page greys the option out '
                  'at 1.6 mm: "0.1mm Via is only supported for board thickness ≤ 1.0mm", and refuses it with HASL: '
                  '"HASL is incompatible with 0.1mm (0.2/0.25mm) hole sizes. Please choose ENIG or OSP."); '
                  'plugged vias and the 4-wire Kelvin test are added'},
]

# The smallest drilled hole, vias and PTH pads alike (the quote page has no separate PTH-drill option; the via
# option covers both). Capabilities page: "2-layer: 0.15 – 6.3 mm", "Multilayer: 0.15 – 6.3 mm (0.1mm
# microvias only available for board thickness ≤1mm; ENIG/OSP surface finish required)", "Min. drill diameter
# for 2- or more-layer PCBs is 0.1 mm (more costly!)". So 0.1 mm is a priced option with conditions, not a
# capability limit; 0.15 mm is the smallest standard drill (MINIMUMS_COMMON's floor today). Companions:
# 1-layer boards drill 0.3 mm at the smallest; the smallest non-plated hole is 0.5 mm.
HOLE_TIERS = [
    {'min_drill': 0.15, 'standard': True, 'condition': 'the smallest drill without a surcharge on 2 and more layers'},
    {'min_drill': 0.10, 'standard': False,
     'condition': '"more costly!"; board thickness 1 mm or less and ENIG or OSP finish; ordered through the 0.1 mm via option'},
]
HOLE_ONE_LAYER_MIN = 0.30
HOLE_NPTH_MIN = 0.50

# Layer-count classes, as the quote page prices them at 100 × 100 mm, 5 pieces (web price, 2026-10-18): 1 and 2
# layers quote the same "Special Offer" figure; 4 layers a "Special Offer" figure twice that; 6 layers, grouped
# with 8-16 under the "High Precision PCB" heading, eight times that. 4 layers and up add inner copper weight,
# stackup/impedance, press-fit and backdrill options. The help centre's production-time classes are the same
# three (1/2, 4, 6 layers, each "Size ≤ 100x100mm").
LAYER_TIERS = [
    {'max_layers': 2, 'label': '1-2 layers', 'standard': True, 'condition': ''},
    {'max_layers': 4, 'label': '4 layers', 'standard': False, 'condition': 'its own price class (twice the 2-layer figure on 2026-10-18)'},
    {'max_layers': 32, 'label': 'High Precision PCB (6 layers and more)', 'standard': False,
     'condition': 'the quote page\'s "High Precision PCB" group (6 layers: eight times the 2-layer figure on 2026-10-18)'},
]

# Board-size classes. The help centre prices and schedules "Size ≤ 100x100mm"; on the quote page that size shows
# a "Special Offer" line, and a larger board is priced as an "Engineering fee" plus a "Board" line. At 4 layers
# a 50 × 50 mm board quoted the same figure as 100 × 100 mm (no smaller class on the web price). Boundary
# observed on 2026-10-18: 100 × 101 mm still the offer, 100 × 110 mm and 150 × 150 mm not; the exact edge was
# not pinned. Maximum sizes are capability limits (dimensions article), not tiers.
SIZE_TIERS = [
    {'max_x': 100.0, 'max_y': 100.0, 'label': '100 × 100 mm or smaller', 'standard': True, 'condition': ''},
    {'max_x': None, 'max_y': None, 'label': 'larger than 100 × 100 mm', 'standard': False,
     'condition': 'priced as "Engineering fee" plus a "Board" line that grows with area'},
]
SIZE_MAX_BY_LAYERS = {1: (606, 510), 2: (670, 600), 4: (663, 593), 6: (656, 586)}   # FR-4, thickness ≥ 0.8 mm
SIZE_MIN = (3, 3)                                                                  # FR-4; castellated or plated edges: 10 × 10

# Quantities. The quote page's PCB Qty defaults to 5 and the help centre's smallest class is "5pcs"; the blog:
# "JLCPCB fabricates at least 5 bare boards per order but can assemble as few as 2 of them". PCBA capabilities:
# Economic "2 - 50 pcs" (2-30 for most non-green, non-1.6 mm, non-HASL combinations in its specs table),
# Standard "2 - 80000 pcs".
QUANTITY = {'pcb_min': 5, 'assembly_min': 2, 'economic_max': 50, 'economic_max_some_finishes': 30}

# Assembly drivers: what in the board or BOM files moves the order from Economic PCBA (single-sided, 2/4/6
# layers, 0.8-1.6 mm, 2-50 pieces, 0402 and larger, IC pitch ≥ 0.4 mm, BGA pitch ≥ 0.5 mm, no gold fingers /
# castellated holes / edge plating, mouse-bite panels only) to Standard PCBA, or adds a line inside a tier.
# Fees are per the price article: setup and stencil are per side on Standard; through-hole parts are "Manual
# Assembly" per joint plus a hand-soldering labour fee per order on both tiers (FAQ: "wave soldering",
# "+ 1 more day"); Economic charges a feeder-loading fee per unique Extended part (Basic and Preferred
# Extended parts exempt), Standard per unique part, Basic or Extended.
ASSEMBLY_TIERS = [
    {'driver': 'single-sided placement', 'tier': 'Economic PCBA', 'standard': True,
     'detectable': 'yes: every placed footprint on one copper layer',
     'condition': 'Economic PCBA: "Single sided placement (SMT/Thru-hole)"'},
    {'driver': 'double-sided placement', 'tier': 'Standard PCBA', 'standard': False,
     'detectable': 'yes: placed footprints on both F.Cu and B.Cu (a through-hole part on the back counts too)',
     'condition': 'Standard PCBA: "Single & double sided placement (SMT/Thru-hole)"; setup and stencil are priced per side'},
    {'driver': 'through-hole parts', 'tier': 'either tier, wave soldering', 'standard': False,
     'detectable': 'yes: (attr through_hole) footprints in the BOM',
     'condition': 'priced per solder joint ("Manual Assembly") plus a hand-soldering labour fee per order; '
                  '"available under both the Economic and Standard PCBA"; no feeder-loading fee; "+ 1 more day"'},
    {'driver': 'Extended part', 'tier': 'per unique part type', 'standard': False,
     'detectable': 'online only: the catalogue says Basic, Preferred Extended or Extended per LCSC code',
     'condition': 'Economic PCBA: a feeder-loading fee per unique Extended part, Basic and Preferred Extended parts '
                  'exempt; Standard PCBA: a feeder-loading fee per unique part, Basic or Extended'},
    {'driver': 'package below 0402, IC pitch below 0.4 mm, BGA pitch below 0.5 mm', 'tier': 'Standard PCBA', 'standard': False,
     'detectable': 'partly: pad geometry in the footprint; a package name alone is not',
     'condition': 'Economic PCBA minimums: package 0402, IC pin spacing 0.4 mm, BGA 0.5 mm; Standard: 01005, 0.35 mm, 0.3 mm'},
    {'driver': 'layer count other than 2, 4 or 6, or thickness outside 0.8-1.6 mm', 'tier': 'Standard PCBA', 'standard': False,
     'detectable': 'yes: copper layers; thickness is (general (thickness)) in the board file, KiCad\'s 1.6 default unless set',
     'condition': 'Economic PCBA: "2,4,6-layers", "0.8mm - 1.6mm"; Standard: "1 - 32 layers", thickness "No limit"'},
    {'driver': 'gold fingers, castellated holes or edge plating', 'tier': 'Standard PCBA', 'standard': False,
     'detectable': 'castellated: yes (stackup castellated_pads, plated holes cut by the outline); edge plating: the '
                   'stackup\'s edge_plating flag when set; gold fingers: no',
     'condition': 'Economic PCBA: "Not Support"; Standard: "Support"'},
    {'driver': 'board smaller than 70 × 70 mm on Standard PCBA', 'tier': 'Standard PCBA, panel or rails', 'standard': False,
     'detectable': 'yes: board outline',
     'condition': 'Standard PCBA single board "70x70mm - 460x500mm"; Economic "10x10mm - 470x500mm"; panels up to 250 × 250 mm'},
    {'driver': 'V-cut panel', 'tier': 'Standard PCBA', 'standard': False,
     'detectable': 'no: a delivery-format choice on the quote page',
     'condition': 'Economic PCBA: "Single PCB, Panel with mouse bites"; Standard adds "Panel with V-cut"'},
]

# Copper weight: a priced "Outer Copper Weight" option the files cannot see (a stackup copper thickness of
# 0.035 mm means 1 oz only when the designer edited the stackup). The capabilities page's track/space minimums
# per weight, 2-layer and multilayer, are the note the report carries with the 1 oz assumption.
COPPER_WEIGHT_TIERS = [
    {'outer_oz': 1.0, 'standard': True, 'min_track_space': {2: (0.10, 0.10), 4: (0.09, 0.09)}, 'condition': ''},
    {'outer_oz': 2.0, 'standard': False, 'min_track_space': {2: (0.16, 0.16), 4: (0.15, 0.15)},
     'condition': 'priced "Outer Copper Weight" option; 2.5 / 3.5 / 4.5 oz exist for 2-layer boards only, at 0.2 / 0.25 / 0.3 mm track and space'},
]

# Trace and space: capabilities, not quote-page options (no trace/space choice appears at 2, 4 or 6 layers), so
# a 3.5 mil multilayer trace is buildable at no surcharge. "3 mil is acceptable in BGA fan-outs."
TRACE_SPACE_TIERS = [
    {'layers': '1-2', 'min_track': 0.10, 'min_space': 0.10, 'standard': True, 'condition': 'capability; no quote-page option'},
    {'layers': 'multilayer', 'min_track': 0.09, 'min_space': 0.09, 'standard': True, 'condition': 'capability; no quote-page option'},
]

# The other quote-page options that are read from the board files or chosen beside them, with whether the
# files can show them. priced None: a surcharge was not observed on the quote page and no page states one.
OPTION_TIERS = [
    {'option': 'Castellated Holes', 'priced': True,
     'detectable': 'yes: (castellated_pads yes) in the stackup; plated holes cut by the Edge.Cuts outline',
     'condition': 'help centre: "If "Yes" is checked, the castellated holes will be made with a special process and extra '
                  'cost will be charged"; hole ≥ 0.5 mm, board ≥ 10 × 10 mm and ≥ 0.6 mm thick; the quote page asks for the '
                  'number of edges (1-4) before pricing; Standard PCBA only'},
    {'option': 'Edge Plating', 'priced': True,
     'detectable': 'the stackup\'s edge_plating flag when set',
     'condition': 'quote page: "ENIG surface finish is required for edge plating"; board ≥ 10 × 10 mm and ≥ 0.6 mm thick; '
                  'Standard PCBA only'},
    {'option': 'Gold Fingers', 'priced': True, 'detectable': 'no',
     'condition': 'quote page: "HASL is chosen, the fingers will be tinned. If gold fingers are needed, please choose ENIG"; '
                  'beveling 30° / 45° offered with it; Standard PCBA only'},
    {'option': 'Specify Stackup / impedance control', 'priced': None,
     'detectable': 'partly: (dielectric_constraints yes) in the stackup when the designer ticked impedance control',
     'condition': '4 layers and more on the quote page; capabilities: controlled impedance on 4-32 layers, tolerance ±10%'},
    {'option': 'Via Covering (plugged, epoxy or copper-paste filled) and Via Plating Method', 'priced': True, 'detectable': 'no',
     'condition': 'forced on by the via tiers below 0.3 mm; otherwise a choice beside the files'},
    {'option': 'Press-Fit Hole', 'priced': None, 'detectable': 'no',
     'condition': '4 layers and more on the quote page; capabilities: "Multilayer ENIG boards and circular holes only"'},
    {'option': 'Blind Slots', 'priced': None, 'detectable': 'no', 'condition': 'capabilities: 2-32 layer FR-4, thickness ≥ 0.8 mm'},
    {'option': 'Backdrill', 'priced': None, 'detectable': 'no', 'condition': '4 layers and more on the quote page'},
    {'option': 'Board Outline Tolerance ±0.1 mm (Precision)', 'priced': None, 'detectable': 'no',
     'condition': 'quote page: needs at least 3 alignment holes ≥ 1.5 mm, board ≥ 50 × 50 mm'},
]

TIERS = {
    'via': {'unit': 'mm', 'source': ('quote', 'capabilities'), 'rows': VIA_TIERS},
    'hole': {'unit': 'mm', 'source': ('capabilities', 'quote'), 'rows': HOLE_TIERS},
    'layers': {'unit': 'copper layers', 'source': ('quote', 'production-time'), 'rows': LAYER_TIERS},
    'size': {'unit': 'mm', 'source': ('quote', 'production-time', 'dimensions'), 'rows': SIZE_TIERS},
    'assembly': {'unit': 'driver', 'source': ('pcba-capabilities', 'pcba-price', 'pcba-faqs', 'blog-pcba-cost'), 'rows': ASSEMBLY_TIERS},
    'copper_weight': {'unit': 'oz', 'source': ('quote', 'capabilities'), 'rows': COPPER_WEIGHT_TIERS},
    'trace_space': {'unit': 'mm', 'source': ('capabilities', 'quote'), 'rows': TRACE_SPACE_TIERS},
    'options': {'unit': 'option', 'source': ('quote', 'capabilities', 'castellated', 'pcba-capabilities'), 'rows': OPTION_TIERS},
}

# What could not be read from a JLCPCB page on 2026-10-18 and is therefore not in the tables (never guessed).
TIERS_NOT_SOURCED = (
    'the exact board-size edge of the "Special Offer" class (between 100 × 101 and 100 × 110 mm)',
    'the quote page\'s assembly options (they need a Gerber upload); the assembly rows come from the PCBA capabilities and price pages',
    'a surcharge for Specify Stackup / impedance control, press-fit holes, blind slots, backdrill, precision outline',
    'the castellated-hole surcharge line (the quote page wants an edge count first; the help centre states the charge)',
)


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
     "demoted": {"drc": [check, ...], "erc": [...]}      demoted checks the project did not already have as warnings
     "pin_map": n                                        pin-matrix cells weaker than KiCad's default (0: none)
     "minimums": {key: (project value, floor)}           board minimums below the fab's
     "netclasses": {name: (project clearance, floor)}}   netclass clearances below the fab's
    """
    pro = _load(pro_path)
    changed = {'drc': {}, 'erc': {}, 'demoted': {'drc': [], 'erc': []}, 'pin_map': 0, 'minimums': {}, 'netclasses': {}}
    ds = pro.setdefault('board', {}).setdefault('design_settings', {})
    for kind, protected, demoted, sev in (('drc', DRC_PROTECTED, DRC_DEMOTED, ds.setdefault('rule_severities', {})),
                                          ('erc', ERC_PROTECTED, ERC_DEMOTED, pro.setdefault('erc', {}).setdefault('rule_severities', {}))):
        for key in sorted(protected):
            default = KICAD_DEFAULT[kind].get(key, 'error')
            if sev.get(key, default) != default:
                changed[kind][key] = sev[key]
            sev[key] = 'error'
        for key in sorted(demoted):
            if sev.get(key, KICAD_DEFAULT[kind].get(key, 'error')) != 'warning':
                changed['demoted'][kind].append(key)
            sev[key] = 'warning'

    erc = pro['erc']
    pin_map = erc.get('pin_map')
    if isinstance(pin_map, list) and len(pin_map) == 12 and all(isinstance(r, list) and len(r) == 12 for r in pin_map):
        for i in range(12):
            for j in range(12):
                if not isinstance(pin_map[i][j], int) or pin_map[i][j] < DEFAULT_PIN_MAP[i][j]:
                    changed['pin_map'] += 1
                    pin_map[i][j] = DEFAULT_PIN_MAP[i][j]
                pin_map[i][j] = min(pin_map[i][j], 1)          # pin conflicts are demoted: warnings, never errors
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
