"""Absolute execution paths must not become portable input display names."""
import importlib.util
import json
from pathlib import Path
import subprocess

from quickalign import jobs
from quickalign.cli import main
from quickalign.inputs import TRUNCATION_TEXT


def test_absolute_tsv_sources_keep_portable_names_and_labels(tmp_path, capsys):
    recipe = Path(__file__).parents[1] / "fixtures" / "make_fixture.py"
    spec = importlib.util.spec_from_file_location("portable_fixture_recipe", recipe)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = module.make_fixture(tmp_path / "distinctive-private-source" / "patient cohort")
    # The incomplete header should warn while both complete long reads survive.
    with (source / "nanopore.fastq").open("ab") as handle:
        handle.write(b"@")
    manifest_path = tmp_path / "groups.tsv"
    manifest_path.write_text(
        "label\ttechnology\tlayout\tread1\tread2\n"
        f"My Paired Label\tillumina\tpaired\t{source / 'r1.fastq'}\t{source / 'r2.fastq'}\n"
        f"Warning Long Label\tnanopore\tsingle\t{source / 'nanopore.fastq'}\t\n"
    )
    output = tmp_path / "outputs"
    assert main([
        "build", str(source / "reference.fasta"), str(source / "annotation.gff3"),
        "--reads-manifest", str(manifest_path), "--outdir", str(output),
        "--workdir", str(tmp_path / "work"), "--threads", "2",
    ]) == 0
    captured = capsys.readouterr()
    (tmp_path / "cli.stdout.txt").write_text(captured.out)
    (tmp_path / "cli.stderr.txt").write_text(captured.err)
    assert "Warning Long Label: nanopore.fastq" in captured.err
    assert TRUNCATION_TEXT in captured.err
    assert str(source) not in captured.out + captured.err

    bundle = jobs.completed_bundle(output)
    manifest = json.loads((bundle / "manifest.json").read_text())
    config = json.loads((bundle / "config.json").read_text())
    groups = manifest["read_groups"]
    assert [(group["label"], group["track_id"], group["input_display_names"]) for group in groups] == [
        ("My Paired Label", "my-paired-label", ["r1.fastq", "r2.fastq"]),
        ("Warning Long Label", "warning-long-label", ["nanopore.fastq"]),
    ]
    tracks = [track for track in config["tracks"] if track["type"] == "AlignmentsTrack"]
    assert [(track["trackId"], track["name"], track["metadata"]["read1"], track["metadata"]["read2"])
            for track in tracks] == [
        ("my-paired-label", "My Paired Label (paired)", "r1.fastq", "r2.fastq"),
        ("warning-long-label", "Warning Long Label (single)", "nanopore.fastq", None),
    ]
    warning, = manifest["warnings"]
    assert warning["group_label"] == "Warning Long Label"
    assert warning["group_id"] == "warning-long-label"
    assert warning["input_name"] == "nanopore.fastq" and warning["code"] == "truncated_fastq"
    for filename in ("README.txt", "README.html"):
        content = (bundle / filename).read_text()
        assert "Warning Long Label" in content and "nanopore.fastq" in content and TRUNCATION_TEXT in content

    # Check every portable text/JSON artifact, including flagstat and launchers.
    portable_texts = [path for path in bundle.rglob("*") if path.is_file() and
                      path.suffix in {".json", ".jbrowse", ".txt", ".html", ".sh", ".ps1", ".cmd", ".fai", ".fasta"}]
    assert {"config.json", "manifest.json", "local.template.jbrowse"} <= {path.name for path in portable_texts}
    for path in portable_texts:
        content = path.read_text()
        assert str(source.parent) not in content, path
        assert str(tmp_path) not in content, path

    # Private execution metadata retains real file locations; the aligners read them.
    metadata = jobs.read_metadata(output)
    assert metadata["run_spec"]["read_groups"][0]["read1"] == str(source / "r1.fastq")
    assert metadata["run_spec"]["read_groups"][0]["read2"] == str(source / "r2.fastq")
    assert metadata["run_spec"]["read_groups"][1]["read1"] == str(source / "nanopore.fastq")
    assert metadata["warnings"] == manifest["warnings"]
    for group, names, expected_total in [(groups[0], {"pair", "unmapped"}, 4),
                                          (groups[1], {"ont-map", "ont-unmapped"}, 2)]:
        bam = bundle / "alignments" / f"{group['track_id']}.bam"
        rows = subprocess.check_output(["samtools", "view", str(bam)], text=True).splitlines()
        assert {row.split("\t", 1)[0] for row in rows} == names
        assert len(rows) == expected_total
        assert group["counts"]["mapped"] > 0
