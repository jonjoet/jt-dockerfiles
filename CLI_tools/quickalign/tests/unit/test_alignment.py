from pathlib import Path
import subprocess

from quickalign.alignment import _parse_flagstat, build_alignments
from quickalign.commands import CommandRunner
from quickalign.models import PreparedInputs, ReadGroup, ReservedJob, RunSpec


def test_flagstat_counts_primary_summary_lines():
    text = (
        "10 + 2 in total (QC-passed reads + QC-failed reads)\n"
        "7 + 1 primary mapped (70.00% : N/A)\n"
        "7 + 1 mapped (70.00% : N/A)\n"
    )
    assert _parse_flagstat(text) == (8, 12)


def test_bam_program_headers_do_not_contain_absolute_job_paths(tmp_path):
    inputs = tmp_path / "absolute-inputs"
    output = tmp_path / "absolute-output"
    work = tmp_path / "absolute-work" / "job"
    partial = output / "sample.jbrowse.partial"
    for directory in (inputs, output, work, partial):
        directory.mkdir(parents=True, exist_ok=True)
    sequence = "ACGT" * 250
    reference = inputs / "reference.fasta"
    reference.write_text(f">chr1\n{sequence}\n")
    reads = inputs / "reads.fastq"
    read_sequence = sequence[100:300]
    reads.write_text(f"@read\n{read_sequence}\n+\n{'I' * len(read_sequence)}\n")
    group = ReadGroup("portable", "nanopore", "single", reads)
    spec = RunSpec(reference, inputs / "unused.gff3", (group,), "sample", threads=2)
    job = ReservedJob("job", output, work, partial, output / "sample.jbrowse", spec)
    runner = CommandRunner(job)
    tracks = build_alignments(job, PreparedInputs(reference, spec.annotation, (group,), {"chr1": len(sequence)}), runner)

    header = subprocess.run(
        ["samtools", "view", "--no-PG", "-H", str(tracks[0].bam)],
        check=True, capture_output=True, text=True,
    ).stdout
    for absolute_root in (str(inputs), str(output), str(work), str(tmp_path)):
        assert absolute_root not in header
    pipeline_records = [record for record in runner.records if record["step"] in {"portable-align", "portable-sort"}]
    assert len(pipeline_records) == 2
    assert all(record["cwd"] == str(work) for record in pipeline_records)
    assert all(not Path(argument).is_absolute() for record in pipeline_records for argument in record["argv"][1:]
               if argument not in {"-"} and not argument.startswith("@RG") and not argument.isdigit())
