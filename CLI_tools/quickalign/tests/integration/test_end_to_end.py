"""Actual pinned aligner/indexer/bundle acceptance. Run inside the runtime image."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import importlib.util

from quickalign import jobs
from quickalign.bundle import validate_bundle
from quickalign.cli import main


def fixture(root):
    recipe = Path(__file__).parents[1] / 'fixtures' / 'make_fixture.py'
    spec = importlib.util.spec_from_file_location('fixture_recipe', recipe)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_fixture(root)


def run(*args):
    return subprocess.check_output(list(args), text=True)


def test_all_read_forms_complete_and_relocate(tmp_path):
    inputs = fixture(tmp_path / 'inputs')
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
    output, work = tmp_path / 'result', tmp_path / 'work'
    assert main(['build', str(inputs/'reference.fasta'), str(inputs/'annotation.gff3'),
                 '--reads-manifest', str(inputs/'read-groups.tsv'), '--outdir', str(output),
                 '--workdir', str(work), '--threads', '4', '--keep-work', '--zip']) == 0
    data = jobs.read_metadata(output)
    assert data['status'] == 'completed' and data['export_status'] == 'completed'
    bundle = jobs.completed_bundle(output)
    manifest = validate_bundle(bundle)
    assert len(data['tracks']) == 4 and not data['warnings']
    assert all(t['mapped'] > 0 for t in data['tracks'])
    assert checksums == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
    assert list((work/data['job_id']/'bwa').glob('reference*'))
    assert not list(bundle.rglob('*.0123'))
    for track in data['tracks']:
        bam = bundle/'alignments'/f"{track['track_id']}.bam"
        run('samtools','quickcheck',str(bam))
        header = run('samtools','view','-H',str(bam))
        assert 'SO:coordinate' in header and f"ID:{track['track_id']}" in header
        assert Path(str(bam)+'.bai').is_file()
        contig_order = {line.split('\t')[1][3:]: i for i,line in enumerate(header.splitlines()) if line.startswith('@SQ')}
        coordinates=[]
        for row in run('samtools','view',str(bam)).splitlines():
            fields=row.split('\t')
            if fields[2] != '*':
                coordinates.append((contig_order[fields[2]],int(fields[3])))
        assert coordinates == sorted(coordinates)
    assert 'gene1' in run('tabix', str(bundle/'annotation/features.gff3.gz'), 'chr1:100-1000')
    assert list((bundle/'trix').glob('*.ix'))
    assert jobs.downloadable_archive(output,10**8) is not None
    assert 'execution' in manifest or 'tool_versions' in manifest
    target = tmp_path / 'moved space " dollar$ apostrophe\' amp& brackets[] (paren); café' / bundle.name
    target.parent.mkdir()
    bundle.rename(target)
    subprocess.run(['bash',str(target/'resolve-local.sh')], cwd=tmp_path, check=True)
    local = json.loads(next(target.glob('*.local.jbrowse')).read_text())
    assert local['tracks'] and local['assemblies']
    validate_bundle(target)


def test_cli_invalid_manifest_durable_failure(tmp_path):
    inputs=fixture(tmp_path/'inputs')
    out=tmp_path/'failure'
    assert main(['build', str(inputs/'reference.fasta'), str(inputs/'annotation.gff3'),
                 '--reads-manifest',str(inputs/'missing.tsv'),'--outdir',str(out)]) == 1
    assert jobs.read_metadata(out)['status'] == 'failed'
