#!/bin/sh
# Fetch the regression corpus: public KiCad projects at pinned commits, into corpus/boards/<name>/.
# Only the KiCad files, libraries, licence, README and any BOM are kept; fab outputs, 3D models and
# images are not. corpus/boards/ is gitignored; corpus/index.csv and corpus/README.md say what each
# board is and why it is here. Re-running skips boards already present (delete a directory to refetch).
#
#   sh corpus/fetch.sh            # everything
#   sh corpus/fetch.sh openjbod   # one board (or several names)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
dest="$here/boards"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
only="$*"

# KiCad's own demos directory, read from gitlab.com/kicad/code/kicad at this commit (master, 2026-10-17).
KICAD_SHA=80521a1b94d81daf044d95e0943a45a08a26d5f2

wanted() {                                      # does the caller want this board?
    [ -z "$only" ] && return 0
    for n in $only; do [ "$n" = "$1" ] && return 0; done
    return 1
}

keep() {                                        # copy the design files from $1 into $2
    src=$1; dst=$2
    mkdir -p "$dst"
    (cd "$src" && find . -type f \( -name '*.kicad_pro' -o -name '*.kicad_sch' -o -name '*.kicad_pcb' \
        -o -name '*.kicad_sym' -o -name '*.kicad_mod' -o -name '*.kicad_dru' -o -name '*.kicad_prl' \
        -o -name '*.kicad_wks' -o -name 'fp-lib-table' -o -name 'sym-lib-table' \
        -o -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'README*' -o -iname '*bom*.csv' \) \
        -not -path '*/gerber*' -not -path '*/Gerber*' -not -path '*-backups/*' -not -path '*/.git/*' -print) |
    while IFS= read -r f; do
        mkdir -p "$dst/$(dirname "$f")"
        cp "$src/$f" "$dst/$f"
    done
}

github() {                                      # github <name> <owner/repo> <sha> [subdir]
    name=$1; repo=$2; sha=$3; sub=${4:-.}
    wanted "$name" || return 0
    if [ -d "$dest/$name" ]; then echo "$name: present"; return 0; fi
    echo "$name: github.com/$repo @ $sha"
    curl -sSfL "https://github.com/$repo/archive/$sha.tar.gz" -o "$tmp/$name.tgz"
    mkdir -p "$tmp/$name"
    tar -xzf "$tmp/$name.tgz" -C "$tmp/$name" --strip-components=1
    keep "$tmp/$name/$sub" "$dest/$name"
    if [ "$sub" != "." ]; then                  # the licence and README live at the repository root
        for f in "$tmp/$name"/LICENSE* "$tmp/$name"/COPYING* "$tmp/$name"/README* "$tmp/$name"/ReadMe*; do
            [ -f "$f" ] && cp "$f" "$dest/$name/"
        done
    fi
    printf '%s\n%s\n' "https://github.com/$repo" "$sha" > "$dest/$name/.source"
    rm -rf "$tmp/$name" "$tmp/$name.tgz"
}

kicad_demo() {                                  # kicad_demo <name> <demos subdirectory>
    name=$1; path=$2
    wanted "$name" || return 0
    if [ -d "$dest/$name" ]; then echo "$name: present"; return 0; fi
    echo "$name: gitlab.com/kicad/code/kicad demos/$path @ $KICAD_SHA"
    enc=$(printf '%s' "$path" | sed 's/ /%20/g')
    curl -sSfL "https://gitlab.com/kicad/code/kicad/-/archive/$KICAD_SHA/kicad-$KICAD_SHA.tar.gz?path=demos/$enc" -o "$tmp/$name.tgz"
    mkdir -p "$tmp/$name"
    tar -xzf "$tmp/$name.tgz" -C "$tmp/$name" --strip-components=1
    keep "$tmp/$name/demos/$path" "$dest/$name"
    printf '%s\n%s\n' "https://gitlab.com/kicad/code/kicad/-/tree/master/demos/$enc" "$KICAD_SHA" > "$dest/$name/.source"
    rm -rf "$tmp/$name" "$tmp/$name.tgz"
}

mkdir -p "$dest"

# --- KiCad's bundled demos (gitlab.com/kicad/code/kicad, demos/)
kicad_demo openair-max            openair-max
kicad_demo royalblue54l-feather   royalblue54L_feather
kicad_demo tiny-tapeout           tiny_tapeout
kicad_demo complex-hierarchy      complex_hierarchy
kicad_demo multichannel           multichannel
kicad_demo jetson-thor-baseboard  jetson-agx-thor-baseboard

# The multichannel demo ships an unrouted copy of its board; this variant swaps it in under the project
# name so the gate's unrouted check runs on a real, documented, unrouted board.
if wanted multichannel-unrouted && [ -d "$dest/multichannel" ] && [ ! -d "$dest/multichannel-unrouted" ]; then
    echo "multichannel-unrouted: the same project with multichannel_mixer-unrouted.kicad_pcb as the board"
    cp -R "$dest/multichannel" "$dest/multichannel-unrouted"
    mv "$dest/multichannel-unrouted/multichannel_mixer-unrouted.kicad_pcb" "$dest/multichannel-unrouted/multichannel_mixer.kicad_pcb"
fi

# --- GitHub projects with LCSC data, fabricated or sold
github cm5-minima        piecol/CM5_MINIMA_REV3            6d77314dbbc26c8f5735add30ccb0588816cb71a
github jlcpcb-example    jvanderberg/Kicad-jlcpcb-example  fb2bebb676fea6bc796932b351a32b8281271b58
github canfd-mc          Prinsessen/canfd-mc-hardware      6e6cfba41e0ed19c80853c46d2ea8ebced49453c
github openjbod-rp2040   OpenJBOD/rp2040                   4d657ca34d95ce67ebfae65a99e9a0d66d440883
github bitaxegt          bitaxeorg/BitaxeGT                4202c2533f6036cfb19e4575d7afc07fbef58f54
github sh-rpi            hatlabs/SH-RPi-hardware           e82e3c9823bbcf94091b22927dd2e0da9cdfac8c
github soldiercrab       apfaudio/soldiercrab              6baf96aa6760cd5fc3496ccb458bde3182438012
github sonatino          luminationlabs/Sonatino           3dd28dbe4b71d82ec803c49cec8aa8b425756f4b  kicad_project
github pocketpd          CentyLab/PocketPD_HW              012f9c79fda8dbfa2381ce1f3ff53b21f533902b  "Design Files"
# Sonatino's .gitignore lists *.kicad_pro, so the repository has no project file; the gate refuses a project
# without one (ERROR). An empty project file is written here so the board can still be run: KiCad reads
# the board's own setup for DRC and uses its default severities for the rest.
if [ -d "$dest/sonatino" ] && [ ! -f "$dest/sonatino/Sonatino.kicad_pro" ]; then
    echo "sonatino: writing an empty Sonatino.kicad_pro (the repository gitignores *.kicad_pro)"
    printf '{}\n' > "$dest/sonatino/Sonatino.kicad_pro"
fi

# --- boards with a documented problem: the commit before the fix and the commit of the fix
# bitaxeAura issue #1 (2025-04-04): "C15, C19, C36, C42, C46, C47 part number is for a higher voltage
# 0603 cap. But the footprint is still for a 0402." Open; the files at HEAD still have it.
github bitaxeaura        bitaxeorg/bitaxeAura              f46f3f52f8fd860c4a4777dec5ed48d283e73895
# smarthome-metering e928c28f "Fix wrong footprints" (2026-10-02): resistors carried SOT-23 footprints
# and test points SOT-23-5 in the schematic. Before and at the fix (the board file is not updated in it).
github smarthome-metering-prefix zargony/smarthome-metering c97374d408e6f2d895a35669507688cae6df3479
github smarthome-metering        zargony/smarthome-metering e928c28f3786d0cf7d13227d27aceb11b5f4766c
# BeyondexLimiter 3256bd86 "Fix wrong footprint for R1" (2026-05-27): R1 had R_0402 and should be R_0603.
# Before the fix, and HEAD (two commits later, "Mark through holes as do not populate").
github beyondex-limiter-prefix KibbieKatt/BeyondexLimiter aa810cb5548b4888662d91fc8b919f1197da9eb9
github beyondex-limiter        KibbieKatt/BeyondexLimiter 5170588d2c3f1b1ac89d7df358cc098f9f1b85d8

echo "done: $(ls "$dest" | wc -l | tr -d ' ') boards in $dest"
