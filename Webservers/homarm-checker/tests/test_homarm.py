from homarm import Alignment, intron_lengths, normalize_sequence, pair_arm_hits, parse_paf


def aln(qname, strand, start, end):
    return Alignment(qname, 100, 0, 100, strand, "chrI", 10000, start, end, 100, 100, 60, {})


def test_normalize_sequence():
    assert normalize_sequence(">arm\nacgt nry\n", "arm") == "ACGTNRY"


def test_parse_paf_cigar():
    paf = "joined\t200\t0\t200\t+\tchrI\t10000\t100\t700\t198\t200\t60\tcg:Z:100=400N98=2X\n"
    parsed = parse_paf(paf)
    assert intron_lengths(parsed[0]) == [400]


def test_plus_strand_pair():
    pairs = pair_arm_hits([aln("left", "+", 100, 200)], [aln("right", "+", 800, 900)], max_gap=1000, left_length=100, right_length=100)
    assert len(pairs) == 1
    assert pairs[0].gap == 600


def test_reverse_strand_inverted_locus_pair():
    pairs = pair_arm_hits([aln("left", "-", 800, 900)], [aln("right", "-", 100, 200)], max_gap=1000, left_length=100, right_length=100)
    assert len(pairs) == 1
    assert pairs[0].gap == 600
