#!/bin/sh
# Run the gate on every fetched corpus board: offline for all (corpus/results/<name>.json and .txt), and
# --online for the boards whose bom.csv carries LCSC codes (corpus/results/online/<name>.json and .txt).
# The gate itself runs on a snapshot copy; nothing under corpus/boards is written.
#
#   sh corpus/run.sh                 # offline, every board
#   sh corpus/run.sh --online        # the online pass too (a few hundred catalogue lookups)
#   sh corpus/run.sh --online-only   # only the online pass
#   sh corpus/run.sh [--online|--online-only] NAME...
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
online=0
if [ "${1:-}" = "--online" ]; then online=1; shift; fi
if [ "${1:-}" = "--online-only" ]; then online=2; shift; fi
names="$*"
[ -z "$names" ] && names=$(ls "$here/boards")
mkdir -p "$here/results/online"
for name in $names; do
    dir="$here/boards/$name"
    [ -d "$dir" ] || { echo "$name: not fetched (sh corpus/fetch.sh)"; continue; }
    bom="$here/boms/$name.csv"
    if [ -f "$bom" ]; then bomarg="--bom $bom"; else bomarg="--bom $here/boms/$name.csv"; fi
    if [ "$online" != 2 ]; then
        # shellcheck disable=SC2086
        python3 -m pcb_preflight check "$dir" $bomarg --quiet --max-details 40 --json "$here/results/$name.json" > "$here/results/$name.txt" 2>&1
        echo "$name: offline exit $? ($(sed -n 2p "$here/results/$name.txt" | sed 's/.*RESULT: //'))"
    fi
    if [ "$online" != 0 ] && [ -f "$bom" ] && grep -q ',C[0-9][0-9]*,' "$bom"; then
        # shellcheck disable=SC2086
        python3 -m pcb_preflight check "$dir" $bomarg --online --quiet --max-details 40 --json "$here/results/online/$name.json" > "$here/results/online/$name.txt" 2>&1
        echo "$name: online exit $? ($(sed -n 2p "$here/results/online/$name.txt" | sed 's/.*RESULT: //'))"
    fi
done
