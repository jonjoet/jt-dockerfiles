import json
import shutil
import subprocess
from pathlib import Path

import pytest

from quickalign.bundle import build_bundle, validate_bundle
from quickalign.models import PreparedInputs, ReadGroup, ReservedJob, RunSpec, TrackResult


class SubprocessRunner:
    def run(self, step, argv, stdout_path=None):
        return subprocess.run(argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def completed_bundle(tmp_path: Path) -> Path:
    partial = tmp_path / "source" / "fixture.jbrowse.partial"
    (partial / "reference").mkdir(parents=True)
    (partial / "annotation").mkdir()
    (partial / "alignments").mkdir()
    fasta = partial / "reference" / "assembly.fasta"
    fasta.write_text(">ctg\nACGTACGTACGT\n", encoding="ascii")
    (partial / "reference" / "assembly.fasta.fai").write_text("ctg\t12\t5\t12\t13\n", encoding="ascii")
    gff = partial / "annotation" / "features.gff3"
    gff.write_text("##gff-version 3\nctg\tquickalign\tgene\t1\t4\t.\t+\t.\tID=g1;Name=Gene1\n", encoding="ascii")
    subprocess.run(["bgzip", "-f", "-k", str(gff)], check=True)
    subprocess.run(["tabix", "-f", "-p", "gff", str(gff) + ".gz"], check=True)
    gff.unlink()
    group = ReadGroup("reads", "illumina", "single", Path("reads.fastq.gz"))
    bam = partial / "alignments" / "reads.bam"
    bai = partial / "alignments" / "reads.bam.bai"
    flagstat = partial / "alignments" / "reads.flagstat.txt"
    bam.write_bytes(b"fixture bam")
    bai.write_bytes(b"fixture bai")
    flagstat.write_text("1 + 0 in total\n", encoding="ascii")
    final = partial.with_name("fixture.jbrowse")
    spec = RunSpec(Path("original.fa"), Path("original.gff3"), (group,), "fixture")
    job = ReservedJob("fixture", partial.parent, tmp_path / "work", partial, final, spec)
    prepared = PreparedInputs(fasta, Path(str(gff) + ".gz"), (group,), {"ctg": 12})
    track = TrackResult("reads", group, bam, bai, flagstat, 1, 1)
    build_bundle(job, prepared, [track], SubprocessRunner(), [], {"jbrowse": "4.3.0"})
    partial.rename(final)
    validate_bundle(final)
    return final


def _assert_local_locations(path: Path, root: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    found = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("locationType") == "LocalPathLocation":
                found.append(Path(value["localPath"]))
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(document)
    assert found
    assert all(item.is_file() and item.is_relative_to(root) for item in found)


@pytest.mark.parametrize("launcher", ["resolve-local.sh", "resolve-local.ps1"])
def test_relocated_resolver_completed_fixture(completed_bundle: Path, tmp_path: Path, launcher: str):
    destination = tmp_path / "space $'\"&[](); nonascii-é" / "portable.jbrowse"
    destination.parent.mkdir()
    shutil.copytree(completed_bundle, destination)
    if launcher.endswith(".ps1"):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            pytest.skip("PowerShell test image is not in use")
        argv = [pwsh, "-NoProfile", "-File", str(destination / launcher)]
    else:
        argv = [str(destination / launcher)]
    subprocess.run(argv, cwd=tmp_path, check=True, capture_output=True, text=True)
    _assert_local_locations(destination / "portable.local.jbrowse", destination)
    assert validate_bundle(destination)["sample_name"] == "fixture"
