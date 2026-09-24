from pathlib import Path

from quickalign.alignment import _parse_flagstat


def test_flagstat_counts_primary_summary_lines():
    text = "10 + 0 in total (QC-passed reads + QC-failed reads)\n7 + 0 mapped (70.00% : N/A)\n"
    assert _parse_flagstat(text) == (7, 10)
