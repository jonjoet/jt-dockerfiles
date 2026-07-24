# Regression fixtures

`genomic_edge_cases.gb` is a deterministic synthetic, multi-record fixture
created for this repository on 2026-07-24. It covers alternative transcripts,
plus- and minus-strand split CDS features, `codon_start` 1/2/3, a remote
reference, a circular record without a source feature, an exact origin wrap, a
gapped origin-spanning CDS, reserved attribute characters, and a between-base
site.

The real-record regression in `test_converter.py` mirrors the relationship
qualifiers and coordinates of the minus-strand PON2 model from GenBank
`AC005021.1`, retrieved from:

<https://www.ncbi.nlm.nih.gov/nuccore/AC005021.1>

The full human BAC record is not copied into the repository; the regression
retains only the annotations required to test the converter's hierarchy policy.
