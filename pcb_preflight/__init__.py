"""pcb-preflight: a gate that refuses a KiCad board that is not ready to order.

No generation, no routing. It runs KiCad's own checks through kicad-cli, reads the project's
bom.csv, and prints what it checked and left alone, what it found, and what it cannot check.
"""
__version__ = "0.1.0"
