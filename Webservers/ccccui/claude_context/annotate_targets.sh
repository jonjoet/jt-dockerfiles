#!/bin/bash

# Usage: ./annotate_targets_from_genbank.sh input.gb targets.tsv output.gb

GENBANK="$1"
TARGETS="$2"
OUTPUT="$3"

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 <input.gb> <targets.tsv> <output.gb>"
    exit 1
fi

# Split GenBank into three parts:
# 1. Before FEATURES
# 2. FEATURES section
# 3. ORIGIN section

awk '
/^FEATURES/ {print > "features.tmp"; nextfile}
{print > "header.tmp"}
' "$GENBANK"

awk '
/^FEATURES/,/^ORIGIN/ {print > "features.tmp"}
/^ORIGIN/,/^\/\// {print > "origin.tmp"}
' "$GENBANK"

# Write header to output
cat header.tmp > "$OUTPUT"

# Write FEATURES section and add new annotations
cat features.tmp | awk '/^ORIGIN/ {exit} {print}' >> "$OUTPUT"

# Add new FEATURES
tail -n +2 "$TARGETS" | while IFS=$'\t' read -r rank seq loc strand gc sc eff mm0 gt1; do
    pos=$(echo "$loc" | sed 's/.*://')
    len=${#seq}
    end=$((pos + len - 1))

    if [[ "$strand" == "+" ]]; then
        range="$pos..$end"
    else
        range="complement($pos..$end)"
    fi

    {
    echo "     misc_feature    $range"
    echo "                     /label=\"Rank $rank, Eff $eff\""
    echo "                     /note=\"Target: $seq\""
    } >> "$OUTPUT"
done

# Append ORIGIN section
cat origin.tmp >> "$OUTPUT"

# Clean up
rm header.tmp features.tmp origin.tmp
