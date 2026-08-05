# Yeast Homology-Arm Off-Target Checker

A small Streamlit app for screening donor-DNA homology arms against a yeast genome.

It aligns three queries with minimap2: the left arm, the right arm, and a synthetic `left + right` query. Separate arm hits are filtered and paired by chromosome, strand, order, and maximum genomic separation. Joined-query splice-mode alignments are shown as supporting evidence, while explicit arm pairing remains the source of truth.

## Run

```bash
docker compose up --build
```

Open `http://localhost:8501`.

## Inputs

- Reference genome FASTA; use the actual strain assembly when possible.
- Left and right homology-arm sequences.
- Maximum allowed genomic separation.
- Minimum arm coverage and identity.

## Outputs

- Compatible paired-arm loci.
- Strong individual-arm hits.
- Raw minimap2 PAF.
- Downloadable TSV files.

Coordinates in result tables are 1-based and inclusive. Raw PAF coordinates remain 0-based and half-open.

## Caveats

This is a screening tool, not a calibrated recombination predictor. Minimap2 is optimized for longer sequences and can miss very short or seed-poor matches. Validate short or borderline arms with sensitive BLASTN or exact-match searches. Repetitive and subtelomeric sequences may produce many hits.
