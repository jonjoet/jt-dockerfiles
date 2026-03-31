#!/bin/bash

# Usage: ./annotate_targets.sh input.gb targets.tsv output.gb
# Takes a GenBank file and a CHOPCHOP TSV, writes a new GenBank with
# guide RNA targets added as misc_feature annotations.

set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 <input.gb> <targets.tsv> <output.gb>" >&2
    exit 1
fi

GENBANK="$1"
TARGETS="$2"
OUTPUT="$3"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Single-pass split of GenBank into header, features, and origin sections
awk '
    /^FEATURES/ { section="features" }
    /^ORIGIN/   { section="origin" }
    section == ""         { print > "'"$TMPDIR"'/header.tmp" }
    section == "features" { print > "'"$TMPDIR"'/features.tmp" }
    section == "origin"   { print > "'"$TMPDIR"'/origin.tmp" }
    BEGIN { section="" }
' "$GENBANK"

# Assemble output: header, then features (minus trailing ORIGIN line), then new annotations, then origin
cat "$TMPDIR/header.tmp" > "$OUTPUT"
cat "$TMPDIR/features.tmp" >> "$OUTPUT"

# Add guide RNA annotations from TSV
tail -n +2 "$TARGETS" | while IFS=$'\t' read -r rank seq loc strand gc sc eff mm0 gt1; do
    pos=$(echo "$loc" | sed 's/.*://')
    len=${#seq}
    end=$((pos + len - 1))

    if [[ "$strand" == "+" ]]; then
        range="$pos..$end"
    else
        range="complement($pos..$end)"
    fi

    printf '     misc_feature    %s\n' "$range" >> "$OUTPUT"
    printf '                     /label="Rank %s, Eff %s"\n' "$rank" "$eff" >> "$OUTPUT"
    printf '                     /note="Target: %s"\n' "$seq" >> "$OUTPUT"
done

# Append ORIGIN section
cat "$TMPDIR/origin.tmp" >> "$OUTPUT"
