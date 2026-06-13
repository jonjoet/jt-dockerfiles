#!/usr/bin/env python3
"""Convert a GenBank file to a GFF3 annotation file plus a nucleotide FASTA.

Tuned for Benchling-exported plasmid maps: faithfully represents every feature,
uses the ``/label`` qualifier as the GFF3 ``Name``, handles circular
origin-crossing features, and never crashes on unusual input. Optionally runs
the result through AGAT's GFF3 standardizer (``--validate``).
"""

import argparse
import os
import shutil
import subprocess
import sys
from urllib.parse import quote

from Bio import SeqIO

# GenBank/Benchling feature keys -> valid Sequence Ontology terms. Keys not
# listed here are passed through unchanged (GFF3 tolerates this and AGAT will
# flag anything truly invalid during an optional --validate pass).
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
}

# Reserved GFF3 attribute names we set ourselves; qualifiers must not clobber.
RESERVED_ATTRS = {"ID", "Name", "Parent"}

# Biopython record.id placeholders that should fall back to the LOCUS name.
# Benchling exports typically have no ACCESSION, so record.id is "." or unset.
PLACEHOLDER_IDS = {"", ".", "unknown", "<unknown id>", "<unknown name>"}

# Characters that must be percent-encoded in GFF3 attribute values.
_ATTR_SAFE = "".join(
    c for c in (chr(i) for i in range(33, 127)) if c not in ";=&,\t\n\r%"
)
# Column values (seqid, source) additionally must not contain whitespace.
_COL_SAFE = "".join(c for c in _ATTR_SAFE if c != " ")


def escape_attr(value):
    """Percent-encode a GFF3 attribute value."""
    return quote(str(value), safe=_ATTR_SAFE)


def escape_col(value):
    """Percent-encode a GFF3 column value (seqid/source)."""
    return quote(str(value), safe=_COL_SAFE)


def first_qual(feature, *keys):
    """Return the first present, non-empty qualifier value among *keys."""
    for key in keys:
        vals = feature.qualifiers.get(key)
        if vals and vals[0] != "":
            return vals[0]
    return None


def feature_name(feature):
    """Display name: /label (Benchling), then /gene, /product, locus_tag."""
    return first_qual(feature, "label", "gene", "product", "locus_tag")


def cds_phases(parts, codon_start):
    """Per-segment GFF3 phase for a CDS, processed in biological order.

    ``parts`` are in genomic left-to-right order (Biopython order). For minus
    strand the biological order is reversed. Returns a list aligned to ``parts``.
    """
    initial = (codon_start - 1) % 3
    order = list(range(len(parts)))
    if parts and parts[0].strand == -1:
        order = order[::-1]
    phases = [0] * len(parts)
    prev_idx = None
    for n, i in enumerate(order):
        if n == 0:
            phases[i] = initial
        else:
            prev_len = len(parts[prev_idx])
            phases[i] = (3 - ((prev_len - phases[prev_idx]) % 3)) % 3
        prev_idx = i
    return phases


def strand_char(strand):
    return {1: "+", -1: "-"}.get(strand, ".")


def build_attributes(feat_id, name, parent, feature):
    """Assemble the GFF3 attribute column for a feature."""
    pairs = [("ID", feat_id)]
    if name is not None:
        pairs.append(("Name", name))
    if parent is not None:
        pairs.append(("Parent", parent))
    for key in sorted(feature.qualifiers):
        out_key = "Note" if key == "note" else key
        if out_key in RESERVED_ATTRS:
            continue
        values = ",".join(escape_attr(v) for v in feature.qualifiers[key])
        pairs.append((escape_attr(out_key), values))
    return ";".join(f"{k}={v}" for k, v in pairs)


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
    for record in records:
        if record.id in PLACEHOLDER_IDS:
            if record.name and record.name not in PLACEHOLDER_IDS:
                record.id = record.name
            else:
                record.id = "unknown"


def convert(records, source):
    """Yield GFF3 lines (without trailing newline) for all records."""
    yield "##gff-version 3"

    used_ids = set()
    skipped = 0

    for record in records:
        seqid = escape_col(record.id)
        yield f"##sequence-region {seqid} 1 {len(record.seq)}"

        # First pass: assign an ID to each feature and index gene features by
        # locus_tag / gene so children can reference them as Parent.
        feature_ids = {}
        gene_index = {}
        for idx, feature in enumerate(record.features):
            if feature.location is None:
                continue
            name = feature_name(feature)
            base = (
                first_qual(feature, "locus_tag")
                or name
                or f"{feature.type}_{idx + 1}"
            )
            feat_id = make_unique(str(base), used_ids)
            feature_ids[idx] = feat_id
            if feature.type == "gene":
                key = first_qual(feature, "locus_tag", "gene")
                if key is not None:
                    gene_index[key] = feat_id

        # Second pass: emit GFF3 lines.
        for idx, feature in enumerate(record.features):
            if feature.location is None:
                skipped += 1
                sys.stderr.write(
                    f"warning: skipping feature {idx + 1} of type "
                    f"'{feature.type}' in '{record.id}' (no usable location)\n"
                )
                continue

            feat_id = feature_ids[idx]
            name = feature_name(feature)
            gff_type = SO_TYPE_MAP.get(feature.type, feature.type)

            parent = None
            if feature.type in ("CDS", "mRNA", "tRNA", "rRNA", "exon"):
                key = first_qual(feature, "locus_tag", "gene")
                if key is not None and key in gene_index:
                    parent = gene_index[key]

            parts = list(feature.location.parts)
            phases = None
            if feature.type == "CDS":
                try:
                    codon_start = int(first_qual(feature, "codon_start") or 1)
                except (TypeError, ValueError):
                    codon_start = 1
                phases = cds_phases(parts, codon_start)

            attrs = build_attributes(feat_id, name, parent, feature)
            for part_i, part in enumerate(parts):
                start = int(part.start) + 1  # 0-based half-open -> 1-based incl.
                end = int(part.end)
                phase = str(phases[part_i]) if phases is not None else "."
                yield "\t".join(
                    [
                        seqid,
                        escape_col(source),
                        gff_type,
                        str(start),
                        str(end),
                        ".",
                        strand_char(part.strand),
                        phase,
                        attrs,
                    ]
                )

    if skipped:
        sys.stderr.write(f"warning: skipped {skipped} feature(s) with no location\n")


def run_agat_validate(gff_path):
    """Standardize *gff_path* in place via AGAT. Returns True on success."""
    # AGAT's GFF standardizer; older releases called it agat_convert_sp_gff2gff.pl.
    agat = shutil.which("agat_convert_sp_gxf2gxf.pl") or shutil.which(
        "agat_convert_sp_gff2gff.pl"
    )
    if agat is None:
        sys.stderr.write(
            "warning: --validate requested but AGAT not found; keeping raw GFF3\n"
        )
        return False
    # AGAT writes a log directory ("agat_log_<input-stem>") into its working
    # directory, so run it from the (writable) output directory and clean up.
    outdir = os.path.dirname(os.path.abspath(gff_path))
    tmp_out = gff_path + ".agat.tmp"
    log_dir = os.path.join(
        outdir, "agat_log_" + os.path.splitext(os.path.basename(gff_path))[0]
    )
    try:
        subprocess.run(
            [agat, "-g", gff_path, "-o", tmp_out],
            check=True,
            cwd=outdir,
            stdout=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"warning: AGAT validation failed (exit {exc.returncode}); "
            "keeping raw GFF3\n"
        )
        ok = False
    else:
        os.replace(tmp_out, gff_path)
        ok = True
    if os.path.exists(tmp_out):
        os.remove(tmp_out)
    if os.path.isdir(log_dir):
        shutil.rmtree(log_dir, ignore_errors=True)
    return ok


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
        help="run the GFF3 through AGAT's standardizer after conversion",
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

    normalize_ids(records)

    os.makedirs(args.outdir, exist_ok=True)
    prefix = args.prefix or os.path.splitext(os.path.basename(args.input))[0]
    fna_path = os.path.join(args.outdir, prefix + ".fna")
    gff_path = os.path.join(args.outdir, prefix + ".gff3")

    SeqIO.write(records, fna_path, "fasta")

    with open(gff_path, "w") as fh:
        for line in convert(records, args.source):
            fh.write(line + "\n")

    if args.validate:
        run_agat_validate(gff_path)

    sys.stderr.write(f"wrote {fna_path}\nwrote {gff_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
