import json
import subprocess
from pathlib import Path

import pytest

from quickalign.bundle import ANNOTATION_TRACK_ID, TEXT_ATTRIBUTES, _localize_config, build_bundle, validate_bundle
from quickalign.errors import ValidationError
from quickalign.models import InputWarning, PreparedInputs, ReadGroup, ReservedJob, RunSpec, TrackResult


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.records = [
            {
                "step": "thread-allocation",
                "requested": 4,
                "aligner_threads": 2,
                "sort_worker_threads": 1,
                "sort_main_threads": 1,
            }
        ]

    def run(self, step, argv, stdout_path=None):
        self.calls.append((step, argv, stdout_path))
        config_path = Path(argv[argv.index("--target") + 1])
        root = config_path.parent
        (root / "trix").mkdir()
        (root / "trix" / "assembly.ix").write_text("index\n", encoding="utf-8")
        (root / "trix" / "assembly.ixx").write_text("offset\n", encoding="utf-8")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["aggregateTextSearchAdapters"] = [
            {
                "type": "TrixTextSearchAdapter",
                "textSearchAdapterId": "assembly-index",
                "ixFilePath": {"locationType": "UriLocation", "uri": "trix/assembly.ix"},
                "ixxFilePath": {"locationType": "UriLocation", "uri": "trix/assembly.ixx"},
                "metaFilePath": {"locationType": "UriLocation", "uri": "trix/assembly_meta.json"},
                "assemblyNames": ["assembly"],
            }
        ]
        (root / "trix" / "assembly_meta.json").write_text("{}\n", encoding="utf-8")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)


def _fixture(tmp_path: Path):
    partial = tmp_path / "sample.jbrowse.partial"
    (partial / "reference").mkdir(parents=True)
    (partial / "annotation").mkdir()
    (partial / "alignments").mkdir()
    (partial / "reference" / "assembly.fasta").write_text(">ctg\nACGT\n", encoding="ascii")
    (partial / "reference" / "assembly.fasta.fai").write_text("ctg\t4\t5\t4\t5\n", encoding="ascii")
    (partial / "annotation" / "features.gff3.gz").write_bytes(b"gff")
    (partial / "annotation" / "features.gff3.gz.tbi").write_bytes(b"tbi")
    group = ReadGroup("reads one", "illumina", "single", Path("input reads/R 1.fastq.gz"))
    bam = partial / "alignments" / "reads-one.bam"
    bai = partial / "alignments" / "reads-one.bam.bai"
    flagstat = partial / "alignments" / "reads-one.flagstat.txt"
    bam.write_bytes(b"bam")
    bai.write_bytes(b"bai")
    flagstat.write_text("1 + 0 in total\n", encoding="ascii")
    spec = RunSpec(Path("ref original.fa"), Path("genes original.gff3"), (group,), "sample")
    job = ReservedJob("job-1", tmp_path, tmp_path / "work", partial, tmp_path / "sample.jbrowse", spec)
    prepared = PreparedInputs(
        partial / "reference" / "assembly.fasta",
        partial / "annotation" / "features.gff3.gz",
        (group,),
        {"ctg": 4},
    )
    track = TrackResult("reads-one", group, bam, bai, flagstat, 1, 1)
    return job, prepared, track


def _build(tmp_path: Path):
    job, prepared, track = _fixture(tmp_path)
    runner = FakeRunner()
    warning = InputWarning("reads-one", "reads one", "R 1.fastq.gz", "truncated", "complete records only")
    build_bundle(job, prepared, [track], runner, [warning], {"jbrowse": "4.3.0", "samtools": "1.22"})
    return job, runner


def _replace_config(job, config):
    import hashlib

    payload = (json.dumps(config, indent=2, sort_keys=True) + "\n").encode()
    (job.partial / "config.json").write_bytes(payload)
    try:
        localized = _localize_config(config)
    except ValidationError:
        localized = config  # Let portable validation report intentionally invalid test data.
    template_payload = (json.dumps(localized, indent=2, sort_keys=True) + "\n").encode()
    (job.partial / "local.template.jbrowse").write_bytes(template_payload)
    manifest_path = job.partial / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    replacements = {
        "config.json": payload,
        "local.template.jbrowse": template_payload,
    }
    for record in manifest["files"]:
        replacement = replacements.get(record["path"])
        if replacement is not None:
            record.update(size=len(replacement), sha256=hashlib.sha256(replacement).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_builds_deterministic_relative_bundle_and_manifest(tmp_path, monkeypatch):
    monkeypatch.delenv('QUICKALIGN_MEMORY', raising=False)
    job, runner = _build(tmp_path)
    manifest = validate_bundle(job.partial)

    assert runner.calls == [
        (
            "jbrowse-text-index",
            [
                "jbrowse",
                "text-index",
                "--target",
                str(job.partial / "config.json"),
                "--tracks",
                ANNOTATION_TRACK_ID,
                "--attributes",
                TEXT_ATTRIBUTES,
                "--force",
                "--quiet",
            ],
            None,
        )
    ]
    config = json.loads((job.partial / "config.json").read_text())
    assert _localize_config(config) == json.loads((job.partial / "local.template.jbrowse").read_text())
    assert config["tracks"][1]["category"] == ["Alignments", "Illumina"]
    assert config["defaultSession"]["views"][0]["init"] == {
        "assembly": "assembly", "loc": "ctg:1..4",
        "tracks": ["assembly-ReferenceSequenceTrack", "annotation", "reads-one"],
    }
    assert manifest["warnings"][0]["code"] == "truncated"
    assert manifest["read_groups"][0]["counts"] == {"mapped": 1, "total": 1}
    memory = manifest["run"].pop("container_memory")
    assert manifest["run"] == {
        "requested_threads": 4,
        "aligner_threads": 2,
        "sort_worker_threads": 1,
        "sort_main_threads": 1,
        "sort_memory_per_worker": "256M",
    }
    assert memory["configured_memory"] == "256g"
    assert memory["effective_memory_bytes"] is None or memory["effective_memory_bytes"] > 0
    inventory = {record["path"] for record in manifest["files"]}
    assert "manifest.json" not in inventory
    assert "local.template.jbrowse" in inventory
    assert all(not Path(item).is_absolute() for item in inventory)
    serialized = b"".join(path.read_bytes() for path in job.partial.rglob("*") if path.is_file())
    assert str(tmp_path).encode() not in serialized


def test_shell_resolver_survives_relocation_and_generated_file_is_uninventoried(tmp_path):
    job, _ = _build(tmp_path)
    relocated = tmp_path / "moved $'\"&[](); unicode-é" / "renamed sample.jbrowse"
    relocated.parent.mkdir()
    job.partial.rename(relocated)

    completed = subprocess.run(
        ["/bin/bash", str(relocated / "resolve-local.sh")],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    local_path = Path(completed.stdout.strip())
    assert local_path == relocated / "renamed sample.local.jbrowse"
    local = json.loads(local_path.read_text(encoding="utf-8"))
    locations = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("locationType") == "LocalPathLocation":
                locations.append(Path(value["localPath"]))
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(local)
    assert locations
    assert all(item.is_file() and item.is_relative_to(relocated) for item in locations)
    assert validate_bundle(relocated)["sample_name"] == "sample"


def test_validator_detects_tampering_absolute_uri_and_symlinks(tmp_path):
    job, _ = _build(tmp_path)
    target = job.partial / "annotation" / "features.gff3.gz"
    target.write_bytes(b"changed")
    with pytest.raises(ValidationError, match="(Size|SHA-256) mismatch"):
        validate_bundle(job.partial)

    job, _ = _build(tmp_path / "absolute")
    config_path = job.partial / "config.json"
    config = json.loads(config_path.read_text())
    config["tracks"][0]["adapter"]["gffGzLocation"]["uri"] = "/etc/passwd"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    # Update only its inventory digest so URI validation, rather than hash validation, is exercised.
    manifest_path = job.partial / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for record in manifest["files"]:
        if record["path"] == "config.json":
            import hashlib

            payload = config_path.read_bytes()
            record.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValidationError, match="annotation path|Non-relative URI"):
        validate_bundle(job.partial)

    job, _ = _build(tmp_path / "symlink")
    (job.partial / "extra-link").symlink_to(job.partial / "config.json")
    with pytest.raises(ValidationError, match="Symlinks are forbidden"):
        validate_bundle(job.partial)


def test_validator_rejects_nonobject_json_and_missing_adapter_contracts(tmp_path):
    job, _ = _build(tmp_path / "manifest-shape")
    (job.partial / "manifest.json").write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="must contain an object"):
        validate_bundle(job.partial)

    job, _ = _build(tmp_path / "config-shape")
    _replace_config(job, [])
    with pytest.raises(ValidationError, match="config.json must contain an object"):
        validate_bundle(job.partial)

    job, _ = _build(tmp_path / "missing-bam-track")
    config = json.loads((job.partial / "config.json").read_text())
    config["tracks"] = [item for item in config["tracks"] if item["trackId"] == "annotation"]
    _replace_config(job, config)
    with pytest.raises(ValidationError, match="missing BAM track"):
        validate_bundle(job.partial)

    job, _ = _build(tmp_path / "absolute-local-path")
    config = json.loads((job.partial / "config.json").read_text())
    config["metadata"] = {"locationType": "LocalPathLocation", "localPath": "/server/secret"}
    _replace_config(job, config)
    with pytest.raises(ValidationError, match="local filesystem locations"):
        validate_bundle(job.partial)


def test_validation_cache_uses_full_stat_signature_and_returns_a_copy(tmp_path, monkeypatch):
    import quickalign.bundle as bundle

    job, _ = _build(tmp_path)
    first = validate_bundle(job.partial)
    first["sample_name"] = "caller mutation"
    monkeypatch.setattr(bundle, "_sha256", lambda path: (_ for _ in ()).throw(AssertionError("rehash")))
    assert validate_bundle(job.partial)["sample_name"] == "sample"

    config = job.partial / "config.json"
    config.write_bytes(config.read_bytes() + b" ")
    with pytest.raises(AssertionError, match="rehash"):
        validate_bundle(job.partial)


@pytest.mark.parametrize("mutation", ["singular", "missing-tracks", "unbounded"])
def test_validator_rejects_uninitialized_default_view(tmp_path, mutation):
    job, _ = _build(tmp_path)
    config = json.loads((job.partial / "config.json").read_text())
    session = config["defaultSession"]
    if mutation == "singular":
        session["view"] = session.pop("views")[0]
    elif mutation == "missing-tracks":
        session["views"][0]["init"]["tracks"] = []
    else:
        session["views"][0]["init"]["loc"] = "ctg:1..100000000"
    _replace_config(job, config)
    with pytest.raises(ValidationError, match="defaultSession.views|default view"):
        validate_bundle(job.partial)


@pytest.mark.parametrize("uri", ["../outside", "/absolute", "https://example.org/file", "file?query"])
def test_localization_rejects_unsafe_uris(uri):
    with pytest.raises(ValidationError, match="relative"):
        _localize_config({"locationType": "UriLocation", "uri": uri})
