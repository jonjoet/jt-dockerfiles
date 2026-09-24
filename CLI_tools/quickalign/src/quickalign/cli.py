"""Command-line adapter for the shared job lifecycle."""
import argparse
from dataclasses import asdict, replace
from pathlib import Path
import sys

from . import __version__, jobs
from .errors import QuickalignError
from .inputs import parse_manifest, safe_name
from .models import ReadGroup, RunSpec


class ReadAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        groups = list(getattr(namespace, self.dest, None) or [])
        technology = 'nanopore' if option_string == '--nanopore' else 'illumina'
        layout = {'--illumina-paired': 'paired', '--illumina-interleaved': 'interleaved'}.get(option_string, 'single')
        paths = values if isinstance(values, list) else [values]
        groups.append((technology, layout, paths))
        setattr(namespace, self.dest, groups)


def parser():
    p = argparse.ArgumentParser(prog='quickalign', description='Build portable JBrowse Desktop alignment bundles.')
    p.add_argument('--version', action='version', version=__version__)
    commands = p.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build')
    build.add_argument('reference', type=Path)
    build.add_argument('annotation', type=Path)
    build.add_argument('--outdir', type=Path, required=True)
    build.add_argument('--name')
    for name in ('--illumina-single', '--illumina-interleaved', '--nanopore'):
        build.add_argument(name, dest='reads', action=ReadAction, metavar='FASTQ')
    build.add_argument('--illumina-paired', dest='reads', action=ReadAction, nargs=2, metavar=('R1', 'R2'))
    build.add_argument('--reads-manifest', type=Path)
    build.add_argument('--threads', type=int, default=4)
    build.add_argument('--sort-memory', default='256M', help='samtools sort memory per worker (default: 256M)')
    build.add_argument('--workdir', type=Path)
    build.add_argument('--keep-work', action='store_true')
    build.add_argument('--zip', action='store_true', dest='zip_export')
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.reads_manifest and args.reads:
        p.error('--reads-manifest and direct read options are mutually exclusive')
    job = None
    try:
        name = safe_name(args.name if args.name is not None else args.reference.stem)
        spec = RunSpec(args.reference, args.annotation, (), name, args.threads,
                       args.sort_memory, args.keep_work, 'cli', args.zip_export)
        job = jobs.reserve_job(jobs.new_job_id(), args.outdir,
                               args.workdir or args.outdir / '.quickalign-work-root', spec)
        if args.reads_manifest:
            groups = parse_manifest(args.reads_manifest)
        else:
            groups = tuple(ReadGroup(Path(paths[0]).name, tech, layout, Path(paths[0]),
                          Path(paths[1]) if len(paths) == 2 else None)
                          for tech, layout, paths in (args.reads or []))
        spec = replace(spec, read_groups=groups)
        job = replace(job, spec=spec)
        jobs.update_metadata(job, run_spec=asdict(spec))
        result = jobs.run_job(job)
        print(f'Completed bundle: {result.bundle}')
        for warning in result.warnings:
            print(f'WARNING [{warning.group_label}: {warning.input_name}]: {warning.message}', file=sys.stderr)
        for track in result.tracks:
            if track.mapped == 0:
                print(f'WARNING [{track.group.label}]: No reads mapped; the valid BAM is retained.', file=sys.stderr)
        if result.archive:
            print(f'ZIP: {result.archive}')
        return 0
    except (QuickalignError, OSError, ValueError) as error:
        print(f'quickalign: {error}', file=sys.stderr)
        if job is not None:
            jobs.fail_job(job, error)
            try:
                jobs.cleanup_work(job)
            except (QuickalignError, OSError, ValueError):
                pass
            try:
                bundle = jobs.completed_bundle(job.output_dir)
                print(f'Completed bundle remains available: {bundle}', file=sys.stderr)
                for warning in jobs.read_metadata(job.output_dir).get('warnings', []):
                    print(f"WARNING [{warning['group_label']}: {warning['input_name']}]: {warning['message']}", file=sys.stderr)
            except (QuickalignError, OSError, ValueError):
                print(f'Job diagnostics: {job.output_dir}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
