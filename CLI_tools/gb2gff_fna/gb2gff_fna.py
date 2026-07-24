#!/usr/bin/env python3
"""Convert a GenBank file to GFF3 annotations plus nucleotide FASTA.

The converter preserves flat plasmid annotations while also retaining hierarchy
that is explicitly present in genomic GenBank records. Validation is
non-destructive: it reports problems but never rewrites the generated GFF3.
"""

import argparse
import os
import sys
from collections import defaultdict
from urllib.parse import quote, unquote

from Bio import SeqIO
from Bio.SeqFeature import ExactPosition, SeqFeature, SimpleLocation

# GenBank/INSDC feature keys -> valid Sequence Ontology terms.
SO_TYPE_MAP = {
    "source": "region",
    "rep_origin": "origin_of_replication",
    "primer_bind": "primer_binding_site",
    "misc_feature": "sequence_feature",
    "misc_binding": "binding_site",
    "protein_bind": "protein_binding_site",
    "RBS": "ribosome_entry_site",
    "sig_peptide": "signal_peptide",
    "mat_peptide": "mature_protein_region",
    "5'UTR": "five_prime_UTR",
    "3'UTR": "three_prime_UTR",
    "-10_signal": "minus_10_signal",
    "-35_signal": "minus_35_signal",
    "D-loop": "D_loop",
    "misc_RNA": "transcript",
    "precursor_RNA": "primary_transcript",
    "prim_transcript": "primary_transcript",
    "transit_peptide": "transit_peptide",
    "assembly_gap": "gap",
    "mobile_element": "mobile_genetic_element",
    "regulatory": "regulatory_region",
}

# INSDC keys which are already SO terms accepted in GFF3 column 3.
SO_PASSTHROUGH = {
    "CDS",
    "centromere",
    "enhancer",
    "exon",
    "gap",
    "gene",
    "intron",
    "mRNA",
    "ncRNA",
    "operon",
    "promoter",
    "repeat_region",
    "rRNA",
    "stem_loop",
    "telomere",
    "terminator",
    "tmRNA",
    "tRNA",
}

# Reserved or generated GFF3 attributes; qualifiers must not clobber them.
RESERVED_ATTRS = {"ID", "Name", "Parent", "Is_circular", "part", "gbkey"}
QUALIFIER_KEY_MAP = {"note": "Note", "db_xref": "Dbxref"}

# Biopython record.id placeholders that should fall back to the LOCUS name.
# Benchling exports typically have no ACCESSION, so record.id is "." or unset.
PLACEHOLDER_IDS = {"", ".", "unknown", "<unknown id>", "<unknown name>"}

# Characters that must be percent-encoded in GFF3 attribute values. Spaces are
# encoded for broad parser compatibility even though GFF3 permits literal ones.
_ATTR_SAFE = "".join(
    c for c in (chr(i) for i in range(33, 127)) if c not in ";=&,\t\n\r%"
)
_SEQID_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.:^*$@!+_?-|"


def escape_attr(value):
    """Percent-encode a GFF3 attribute value."""
    return quote(str(value), safe=_ATTR_SAFE)


def escape_seqid(value):
    """Percent-encode a GFF3 seqid using the specification's exact safe set."""
    return quote(str(value), safe=_SEQID_SAFE)


def escape_source(value):
    """Percent-encode a source-column value."""
    return quote(str(value), safe=_ATTR_SAFE)


def first_qual(feature, *keys):
    """Return the first present, non-empty qualifier value among *keys."""
    for key in keys:
        vals = feature.qualifiers.get(key)
        if vals and vals[0] != "":
            return vals[0]
    return None


def feature_name(feature):
    """Return a useful type-aware display name."""
    if feature.type == "gene":
        return first_qual(feature, "label", "gene", "locus_tag")
    if feature.type in ("mRNA", "tRNA", "rRNA", "ncRNA", "tmRNA"):
        return first_qual(
            feature, "label", "transcript_id", "product", "gene", "locus_tag"
        )
    if feature.type == "CDS":
        return first_qual(
            feature, "label", "protein_id", "product", "gene", "locus_tag"
        )
    return first_qual(feature, "label", "gene", "product", "locus_tag")


def feature_id_base(feature, index):
    """Return the preferred stable base for a generated feature ID."""
    if feature.type == "gene":
        value = first_qual(feature, "locus_tag", "gene", "label")
    elif feature.type in ("mRNA", "tRNA", "rRNA", "ncRNA", "tmRNA"):
        value = first_qual(
            feature, "transcript_id", "locus_tag", "gene", "label", "product"
        )
    elif feature.type == "CDS":
        value = first_qual(
            feature, "protein_id", "locus_tag", "gene", "label", "product"
        )
    else:
        value = first_qual(feature, "locus_tag", "label", "gene", "product")
    return str(value if value is not None else f"{feature.type}_{index + 1}")


def cds_phases(parts, codon_start):
    """Per-segment GFF3 phase for a CDS, processed in biological order.

    Biopython stores CompoundLocation parts in biological/extraction order,
    including complement(join(...)) locations. Returns a list aligned to parts.
    """
    phases = [0] * len(parts)
    if not parts:
        return phases
    phases[0] = codon_start - 1
    for i in range(1, len(parts)):
        phases[i] = (3 - ((len(parts[i - 1]) - phases[i - 1]) % 3)) % 3
    return phases


def strand_char(strand):
    return {1: "+", -1: "-", 0: "?", None: "."}.get(strand, ".")


def _escaped_values(values):
    """Serialize independently escaped values with comma separators."""
    return ",".join(escape_attr(v) for v in values)


def build_attributes(feat_id, name, parent, feature, extra=None):
    """Assemble the GFF3 attribute column for a feature."""
    pairs = [("ID", [feat_id])]
    if name is not None:
        pairs.append(("Name", [name]))
    if parent is not None:
        pairs.append(("Parent", [parent]))
    extra = extra or {}
    for key, values in extra.items():
        if not isinstance(values, (list, tuple)):
            values = [values]
        pairs.append((key, values))
    for key in sorted(feature.qualifiers):
        out_key = QUALIFIER_KEY_MAP.get(key, key)
        if out_key in RESERVED_ATTRS:
            continue
        values = feature.qualifiers[key]
        if not isinstance(values, (list, tuple)):
            values = [values]
        values = ["true" if value in ("", None) else value for value in values]
        pairs.append((out_key, values))
    return ";".join(
        f"{escape_attr(key)}={_escaped_values(values)}" for key, values in pairs
    )


def make_unique(base, used):
    """Return an ID based on *base* not already in *used*, recording it."""
    candidate = base
    n = 1
    while candidate in used:
        n += 1
        candidate = f"{base}_{n}"
    used.add(candidate)
    return candidate


def normalize_ids(records):
    """Replace placeholder record ids with the LOCUS name, in place.

    Keeps the FASTA header and GFF3 seqid consistent and meaningful.
    """
    seen = set()
    for record in records:
        if record.id in PLACEHOLDER_IDS:
            if record.name and record.name not in PLACEHOLDER_IDS:
                record.id = record.name
            else:
                record.id = "unknown"
        if record.id in seen:
            raise ValueError(
                f"duplicate record identifier after normalization: {record.id}"
            )
        seen.add(record.id)


def _qualifier_set(feature, *keys):
    """Return all non-empty qualifier values for *keys*."""
    values = set()
    for key in keys:
        for value in feature.qualifiers.get(key, []):
            if value not in ("", None):
                values.add(str(value))
    return values


def _same_strand(left, right):
    """Whether two locations are compatible in strand."""
    left_strand = left.location.strand
    right_strand = right.location.strand
    return (
        left_strand in (None, 0)
        or right_strand in (None, 0)
        or left_strand == right_strand
    )


def _location_contains(parent, child):
    """Whether every child part fits inside a parent part on the same strand."""
    if not _same_strand(parent, child):
        return False
    try:
        parent_parts = list(parent.location.parts)
        child_parts = list(child.location.parts)
        return all(
            any(
                child_part.ref == parent_part.ref
                and int(parent_part.start) <= int(child_part.start)
                and int(child_part.end) <= int(parent_part.end)
                for parent_part in parent_parts
            )
            for child_part in child_parts
        )
    except (TypeError, ValueError):
        return False


def _indexed_candidates(feature, index, *keys):
    """Return ordered unique feature indexes sharing qualifier values."""
    candidates = []
    seen = set()
    for value in _qualifier_set(feature, *keys):
        for idx in index.get(value, []):
            if idx not in seen:
                candidates.append(idx)
                seen.add(idx)
    return candidates


def _unique_compatible(feature, candidate_indexes, features):
    """Return the sole location-compatible candidate index, else None."""
    compatible = [
        idx for idx in candidate_indexes if _location_contains(features[idx], feature)
    ]
    return compatible[0] if len(compatible) == 1 else None


def _parent_for_feature(
    feature,
    features,
    feature_ids,
    gene_index,
    mrna_transcript_index,
    mrna_gene_index,
    record_id,
):
    """Resolve an evidenced Parent without synthesizing hierarchy."""
    gene_candidate_indexes = _indexed_candidates(
        feature, gene_index, "locus_tag", "gene"
    )
    gene_idx = _unique_compatible(feature, gene_candidate_indexes, features)

    if feature.type in ("mRNA", "tRNA", "rRNA", "ncRNA", "tmRNA"):
        if gene_idx is not None:
            return feature_ids[gene_idx]
        if len(gene_candidate_indexes) > 1:
            sys.stderr.write(
                f"warning: ambiguous gene parent for {feature.type} in "
                f"'{record_id}'; leaving Parent unset\n"
            )
        return None

    if feature.type not in ("CDS", "exon"):
        return None

    transcript_candidates = _indexed_candidates(
        feature, mrna_transcript_index, "transcript_id"
    )
    mrna_idx = _unique_compatible(feature, transcript_candidates, features)
    if mrna_idx is None and not transcript_candidates:
        transcript_candidates = _indexed_candidates(
            feature, mrna_gene_index, "locus_tag", "gene"
        )
        mrna_idx = _unique_compatible(feature, transcript_candidates, features)
    if mrna_idx is not None:
        return feature_ids[mrna_idx]
    if len(transcript_candidates) > 1:
        sys.stderr.write(
            f"warning: ambiguous mRNA parent for {feature.type} in "
            f"'{record_id}'; falling back to gene\n"
        )
    if gene_idx is not None:
        return feature_ids[gene_idx]
    if len(gene_candidate_indexes) > 1:
        sys.stderr.write(
            f"warning: ambiguous gene parent for {feature.type} in "
            f"'{record_id}'; leaving Parent unset\n"
        )
    return None


def _gff_type(feature_type, record_id):
    """Map a GenBank key to an SO type, warning on generic fallback."""
    if feature_type in SO_TYPE_MAP:
        return SO_TYPE_MAP[feature_type]
    if feature_type in SO_PASSTHROUGH:
        return feature_type
    sys.stderr.write(
        f"warning: no verified Sequence Ontology mapping for feature type "
        f"'{feature_type}' in '{record_id}'; using sequence_feature\n"
    )
    return "sequence_feature"


def _prepared_parts(feature, record_id):
    """Return checked part dictionaries, or None when a feature must be skipped."""
    parts = list(feature.location.parts)
    prepared = []
    fuzzy = False
    for part in parts:
        if part.ref is not None or part.ref_db is not None:
            sys.stderr.write(
                f"warning: skipping feature '{feature.type}' in '{record_id}' "
                f"(remote location reference {part.ref or part.ref_db!r})\n"
            )
            return None
        try:
            start0 = int(part.start)
            end0 = int(part.end)
        except (TypeError, ValueError):
            sys.stderr.write(
                f"warning: skipping feature '{feature.type}' in '{record_id}' "
                "(non-integer/unknown location endpoint)\n"
            )
            return None
        if not isinstance(part.start, ExactPosition) or not isinstance(
            part.end, ExactPosition
        ):
            fuzzy = True
        if start0 == end0:
            site = max(1, start0)
            gff_start = gff_end = site
        else:
            gff_start = start0 + 1
            gff_end = end0
        prepared.append(
            {
                "part": part,
                "start0": start0,
                "end0": end0,
                "start": gff_start,
                "end": gff_end,
            }
        )
    if fuzzy:
        sys.stderr.write(
            f"warning: feature '{feature.type}' in '{record_id}' has fuzzy "
            "endpoints; emitting integer approximations\n"
        )
    return prepared


def _collapsed_origin_wrap(feature, prepared, record_length, circular):
    """Return a virtual-coordinate row for an exact circular boundary wrap."""
    if (
        not circular
        or record_length <= 0
        or len(prepared) != 2
        or getattr(feature.location, "operator", None) != "join"
    ):
        return None
    first, second = prepared
    strands = {first["part"].strand, second["part"].strand}
    if strands == {1} and first["end0"] == record_length and second["start0"] == 0:
        return {
            "start": first["start"],
            "end": record_length + second["end0"],
            "strand": 1,
            "phase_index": 0,
        }
    if strands == {-1} and first["start0"] == 0 and second["end0"] == record_length:
        return {
            "start": second["start"],
            "end": record_length + first["end0"],
            "strand": -1,
            "phase_index": 0,
        }
    return None


def _valid_codon_start(feature, record_id):
    """Return codon_start 1..3, warning and falling back to 1 if invalid."""
    raw = first_qual(feature, "codon_start")
    if raw is None:
        return 1
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = None
    if value not in (1, 2, 3):
        sys.stderr.write(
            f"warning: invalid /codon_start={raw!r} on CDS in '{record_id}'; "
            "using 1\n"
        )
        return 1
    return value


def _is_full_length(feature, record_length):
    """Whether a feature is a simple full-record location."""
    if feature.location is None:
        return False
    try:
        parts = list(feature.location.parts)
        return (
            len(parts) == 1
            and int(parts[0].start) == 0
            and int(parts[0].end) == record_length
        )
    except (TypeError, ValueError):
        return False


def _emit_feature(
    record,
    feature,
    feat_id,
    parent,
    source,
    extra_attributes=None,
):
    """Yield checked GFF3 rows for one feature."""
    prepared = _prepared_parts(feature, record.id)
    if prepared is None:
        return

    phases = None
    if feature.type == "CDS":
        phases = cds_phases(
            [item["part"] for item in prepared],
            _valid_codon_start(feature, record.id),
        )

    circular = str(record.annotations.get("topology", "")).lower() == "circular"
    collapsed = _collapsed_origin_wrap(feature, prepared, len(record.seq), circular)
    base_extra = {"gbkey": "Src" if feature.type == "source" else feature.type}
    if extra_attributes:
        base_extra.update(extra_attributes)

    gff_type = _gff_type(feature.type, record.id)
    seqid = escape_seqid(record.id)
    source_col = escape_source(source)
    name = feature_name(feature)

    if collapsed is not None:
        phase = (
            str(phases[collapsed["phase_index"]]) if phases is not None else "."
        )
        attrs = build_attributes(feat_id, name, parent, feature, base_extra)
        yield "\t".join(
            [
                seqid,
                source_col,
                gff_type,
                str(collapsed["start"]),
                str(collapsed["end"]),
                ".",
                strand_char(collapsed["strand"]),
                phase,
                attrs,
            ]
        )
        return

    part_count = len(prepared)
    for part_i, item in enumerate(prepared):
        row_extra = dict(base_extra)
        if part_count > 1:
            row_extra["part"] = f"{part_i + 1}/{part_count}"
        attrs = build_attributes(feat_id, name, parent, feature, row_extra)
        phase = str(phases[part_i]) if phases is not None else "."
        yield "\t".join(
            [
                seqid,
                source_col,
                gff_type,
                str(item["start"]),
                str(item["end"]),
                ".",
                strand_char(item["part"].strand),
                phase,
                attrs,
            ]
        )


def convert(records, source):
    """Yield GFF3 lines (without trailing newline) for all records."""
    yield "##gff-version 3"

    used_ids = set()
    skipped = 0

    for record in records:
        seqid = escape_seqid(record.id)
        yield f"##sequence-region {seqid} 1 {len(record.seq)}"
        circular = str(record.annotations.get("topology", "")).lower() == "circular"
        features = list(record.features)

        full_source_indexes = [
            idx
            for idx, feature in enumerate(features)
            if feature.type == "source" and _is_full_length(feature, len(record.seq))
        ]
        synthetic_region = None
        synthetic_region_id = None
        if not full_source_indexes:
            synthetic_region = SeqFeature(
                SimpleLocation(0, len(record.seq), strand=1),
                type="source",
                qualifiers={},
            )
            synthetic_region_id = make_unique(f"{record.id}_region", used_ids)

        # First pass: assign every ID, then build relationship indexes.
        feature_ids = {}
        gene_index = defaultdict(list)
        mrna_transcript_index = defaultdict(list)
        mrna_gene_index = defaultdict(list)
        for idx, feature in enumerate(features):
            if feature.location is None:
                continue
            feat_id = make_unique(feature_id_base(feature, idx), used_ids)
            feature_ids[idx] = feat_id
            if feature.type == "gene":
                for key in _qualifier_set(feature, "locus_tag", "gene"):
                    gene_index[key].append(idx)
            elif feature.type == "mRNA":
                for key in _qualifier_set(feature, "transcript_id"):
                    mrna_transcript_index[key].append(idx)
                for key in _qualifier_set(feature, "locus_tag", "gene"):
                    mrna_gene_index[key].append(idx)

        if synthetic_region is not None:
            synthetic_extra = {"gbkey": "Src"}
            if circular:
                synthetic_extra["Is_circular"] = "true"
            yield from _emit_feature(
                record,
                synthetic_region,
                synthetic_region_id,
                None,
                source,
                synthetic_extra,
            )

        # Second pass: emit GFF3 lines.
        emitted = 0
        for idx, feature in enumerate(features):
            if feature.location is None:
                skipped += 1
                sys.stderr.write(
                    f"warning: skipping feature {idx + 1} of type "
                    f"'{feature.type}' in '{record.id}' (no usable location)\n"
                )
                continue

            feat_id = feature_ids[idx]
            parent = _parent_for_feature(
                feature,
                features,
                feature_ids,
                gene_index,
                mrna_transcript_index,
                mrna_gene_index,
                record.id,
            )
            extra = {}
            if idx in full_source_indexes and circular:
                extra["Is_circular"] = "true"
            rows = list(
                _emit_feature(record, feature, feat_id, parent, source, extra)
            )
            emitted += len(rows)
            yield from rows

        if not features:
            sys.stderr.write(f"warning: record '{record.id}' has no features\n")
        elif emitted == 0 and synthetic_region is None:
            sys.stderr.write(f"warning: record '{record.id}' emitted no features\n")

    if skipped:
        sys.stderr.write(f"warning: skipped {skipped} feature(s) with no location\n")


def _parse_gff_attributes(raw):
    """Parse the attribute syntax emitted by this converter."""
    attrs = defaultdict(list)
    if raw == ".":
        return attrs
    for item in raw.split(";"):
        if not item:
            continue
        if "=" not in item:
            attrs[unquote(item)]
            continue
        key, value = item.split("=", 1)
        attrs[unquote(key)].extend(unquote(part) for part in value.split(","))
    return attrs


def _parent_cycle(graph):
    """Return one cycle path from a Parent graph, or None."""
    visiting = set()
    visited = set()
    path = []

    def visit(node):
        if node in visiting:
            start = path.index(node)
            return path[start:] + [node]
        if node in visited:
            return None
        visiting.add(node)
        path.append(node)
        for parent in graph.get(node, ()):
            cycle = visit(parent)
            if cycle is not None:
                return cycle
        path.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in graph:
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return None


def validate_gff(gff_path):
    """Validate *gff_path* without modifying it. Return True on success."""
    errors = []
    sequence_regions = {}
    duplicate_regions = set()
    features = []

    try:
        with open(gff_path) as handle:
            lines = list(handle)
    except OSError as exc:
        sys.stderr.write(f"error: unable to read GFF3 for validation: {exc}\n")
        return False

    first_content = next((line.strip() for line in lines if line.strip()), "")
    if first_content != "##gff-version 3":
        errors.append("line 1: first content must be exactly '##gff-version 3'")
    version_headers = [
        line_no
        for line_no, line in enumerate(lines, 1)
        if line.strip() == "##gff-version 3"
    ]
    if len(version_headers) != 1:
        errors.append(
            "GFF3 must contain exactly one '##gff-version 3' directive"
        )

    for line_no, raw_line in enumerate(lines, 1):
        line = raw_line.rstrip("\r\n")
        if not line or line == "##gff-version 3":
            continue
        if line.startswith("##sequence-region "):
            parts = line.split()
            if len(parts) != 4:
                errors.append(f"line {line_no}: malformed ##sequence-region")
                continue
            seqid = unquote(parts[1])
            try:
                start, end = int(parts[2]), int(parts[3])
            except ValueError:
                errors.append(
                    f"line {line_no}: non-integer ##sequence-region bounds"
                )
                continue
            if start < 1 or start > end:
                errors.append(f"line {line_no}: invalid ##sequence-region bounds")
            if seqid in sequence_regions:
                duplicate_regions.add(seqid)
            else:
                sequence_regions[seqid] = (start, end, line_no)
            continue
        if line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) != 9:
            errors.append(f"line {line_no}: expected 9 tab-delimited columns")
            continue
        seqid = unquote(columns[0])
        try:
            start, end = int(columns[3]), int(columns[4])
        except ValueError:
            errors.append(f"line {line_no}: non-integer feature coordinates")
            continue
        attrs = _parse_gff_attributes(columns[8])
        feature = {
            "line": line_no,
            "seqid": seqid,
            "source": unquote(columns[1]),
            "type": columns[2],
            "start": start,
            "end": end,
            "strand": columns[6],
            "phase": columns[7],
            "attrs": attrs,
        }
        features.append(feature)

        if start < 1 or start > end:
            errors.append(f"line {line_no}: coordinates require 1 <= start <= end")
        if columns[6] not in ("+", "-", ".", "?"):
            errors.append(f"line {line_no}: invalid strand {columns[6]!r}")
        if columns[2] == "CDS":
            if columns[7] not in ("0", "1", "2"):
                errors.append(f"line {line_no}: CDS phase must be 0, 1, or 2")
        elif columns[7] != ".":
            errors.append(f"line {line_no}: non-CDS phase must be '.'")
        if not attrs.get("ID"):
            errors.append(f"line {line_no}: generated feature is missing ID")
        elif len(attrs["ID"]) != 1:
            errors.append(f"line {line_no}: feature must have exactly one ID")

    for seqid in sorted(duplicate_regions):
        errors.append(f"duplicate ##sequence-region for seqid {seqid!r}")

    circular_seqids = set()
    for feature in features:
        bounds = sequence_regions.get(feature["seqid"])
        if (
            bounds
            and feature["type"] == "region"
            and feature["start"] == bounds[0]
            and feature["end"] == bounds[1]
            and feature["attrs"].get("Is_circular") == ["true"]
        ):
            circular_seqids.add(feature["seqid"])

    for feature in features:
        bounds = sequence_regions.get(feature["seqid"])
        if bounds is None:
            errors.append(
                f"line {feature['line']}: seqid {feature['seqid']!r} has no "
                "##sequence-region"
            )
            continue
        region_start, region_end, _ = bounds
        if feature["start"] < region_start:
            errors.append(
                f"line {feature['line']}: feature starts before sequence region"
            )
        if feature["end"] > region_end:
            region_length = region_end - region_start + 1
            if feature["seqid"] not in circular_seqids:
                errors.append(
                    f"line {feature['line']}: out-of-bounds feature on non-circular "
                    "seqid"
                )
            elif feature["start"] > region_end or feature["end"] > (
                region_end + region_length
            ):
                errors.append(
                    f"line {feature['line']}: circular virtual coordinates exceed "
                    "one landmark turn"
                )

    groups = defaultdict(list)
    all_ids = set()
    for feature in features:
        ids = feature["attrs"].get("ID", [])
        if ids:
            feature_id = ids[0]
            all_ids.add(feature_id)
            groups[feature_id].append(feature)

    graph = defaultdict(set)
    for feature in features:
        child_ids = feature["attrs"].get("ID", [])
        for parent in feature["attrs"].get("Parent", []):
            if parent not in all_ids:
                errors.append(
                    f"line {feature['line']}: Parent {parent!r} does not resolve"
                )
            for child in child_ids[:1]:
                if child == parent:
                    errors.append(
                        f"line {feature['line']}: feature cannot parent itself"
                    )
                graph[child].add(parent)

    cycle = _parent_cycle(graph)
    if cycle is not None:
        errors.append("Parent cycle: " + " -> ".join(cycle))

    for feature_id, group in groups.items():
        if len(group) == 1:
            if group[0]["attrs"].get("part"):
                errors.append(
                    f"line {group[0]['line']}: singleton ID {feature_id!r} "
                    "must not have part"
                )
            continue
        invariant = None
        part_numbers = []
        for feature in group:
            attrs = {
                key: tuple(values)
                for key, values in feature["attrs"].items()
                if key != "part"
            }
            current = (
                feature["seqid"],
                feature["source"],
                feature["type"],
                feature["strand"],
                attrs,
            )
            if invariant is None:
                invariant = current
            elif current != invariant:
                errors.append(
                    f"line {feature['line']}: repeated ID {feature_id!r} has "
                    "inconsistent seqid/source/type/strand/attributes"
                )
            part_values = feature["attrs"].get("part", [])
            if len(part_values) != 1 or "/" not in part_values[0]:
                errors.append(
                    f"line {feature['line']}: repeated ID {feature_id!r} needs "
                    "one part=X/Y value"
                )
                continue
            try:
                number, total = (int(value) for value in part_values[0].split("/", 1))
            except ValueError:
                errors.append(
                    f"line {feature['line']}: invalid part value {part_values[0]!r}"
                )
                continue
            part_numbers.append((number, total))
        if part_numbers:
            totals = {total for _, total in part_numbers}
            numbers = {number for number, _ in part_numbers}
            if totals != {len(group)} or numbers != set(range(1, len(group) + 1)):
                errors.append(
                    f"repeated ID {feature_id!r}: part values must cover "
                    f"1/{len(group)} through {len(group)}/{len(group)}"
                )

    try:
        import gffutils

        gffutils.create_db(
            gff_path,
            dbfn=":memory:",
            force=True,
            keep_order=True,
            merge_strategy="create_unique",
            disable_infer_genes=True,
            disable_infer_transcripts=True,
        )
    except Exception as exc:
        errors.append(f"gffutils parse failed: {exc}")

    if errors:
        sys.stderr.write(
            f"validation failed for {gff_path} ({len(errors)} error(s)):\n"
        )
        for error in errors:
            sys.stderr.write(f"  - {error}\n")
        return False

    sys.stderr.write(
        f"validated {gff_path}: {len(features)} feature row(s), "
        f"{len(sequence_regions)} sequence region(s)\n"
    )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert a GenBank file to GFF3 + nucleotide FASTA (.fna)."
    )
    parser.add_argument("input", help="input GenBank file")
    parser.add_argument(
        "-o", "--outdir", default=".", help="output directory (default: .)"
    )
    parser.add_argument(
        "--prefix",
        help="output basename (default: input filename without extension)",
    )
    parser.add_argument(
        "--source",
        default="GenBank",
        help="value for the GFF3 source column (default: GenBank)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="validate the generated GFF3 without modifying it",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input):
        sys.stderr.write(f"error: input file not found: {args.input}\n")
        return 1

    try:
        records = list(SeqIO.parse(args.input, "genbank"))
    except Exception as exc:  # Biopython raises a variety of parse errors
        sys.stderr.write(f"error: failed to parse GenBank '{args.input}': {exc}\n")
        return 1

    if not records:
        sys.stderr.write(f"error: no records found in '{args.input}'\n")
        return 1

    try:
        normalize_ids(records)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    prefix = args.prefix or os.path.splitext(os.path.basename(args.input))[0]
    fna_path = os.path.join(args.outdir, prefix + ".fna")
    gff_path = os.path.join(args.outdir, prefix + ".gff3")

    SeqIO.write(records, fna_path, "fasta")

    with open(gff_path, "w") as fh:
        for line in convert(records, args.source):
            fh.write(line + "\n")

    sys.stderr.write(f"wrote {fna_path}\nwrote {gff_path}\n")
    if args.validate and not validate_gff(gff_path):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
