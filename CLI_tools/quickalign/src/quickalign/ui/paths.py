"""Root-relative browsing with containment checks repeated at submission."""
from dataclasses import dataclass
from pathlib import Path
import re

from quickalign.errors import ValidationError

SUFFIXES = {
    'reference': ('.fa', '.fasta', '.fna'),
    'annotation': ('.gff', '.gff3', '.gff.gz', '.gff3.gz'),
    'reads': ('.fq', '.fastq', '.fq.gz', '.fastq.gz'),
}


@dataclass(frozen=True)
class Selection:
    root: int
    relative: str = '.'


def suffix(name, kind):
    return next((s for s in SUFFIXES[kind] if name.lower().endswith(s)), None)


def resolve(config, selection, kind=None, *, expect_file=False):
    if not isinstance(selection.root, int) or not 0 <= selection.root < len(config.input_roots):
        raise ValidationError('Unknown input root')
    rel = Path(selection.relative)
    if rel.is_absolute() or any(p == '..' or p.startswith('.') for p in rel.parts):
        raise ValidationError('Hidden paths and traversal are not allowed')
    root = config.input_roots[selection.root]
    try:
        candidate = (root / rel).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValidationError('Selected file is missing or inaccessible') from exc
    if not candidate.is_relative_to(root):
        raise ValidationError('Selected path escapes its input root')
    if any(p.startswith('.') for p in candidate.relative_to(root).parts):
        raise ValidationError('Hidden paths are not allowed')
    if expect_file and (not candidate.is_file() or (kind and not suffix(candidate.name, kind))):
        raise ValidationError('Select a supported regular file')
    return candidate


def browse(config, selection, kind):
    path = resolve(config, selection)
    if not path.is_dir():
        raise ValidationError('Select a directory')
    entries = []
    count = 0
    try:
        for item in path.iterdir():
            count += 1
            if count > config.max_directory_entries:
                raise ValidationError('Too many directory entries; use a smaller configured input root')
            if item.name.startswith('.'):
                continue
            child = Selection(selection.root, str(Path(selection.relative) / item.name))
            try:
                real = resolve(config, child)
                if real.is_dir() or (real.is_file() and suffix(real.name, kind)):
                    entries.append((item.name, real.is_dir(), child))
            except ValidationError:
                continue
    except OSError as exc:
        raise ValidationError('Directory is inaccessible') from exc
    return sorted(entries, key=lambda e: (not e[1], e[0]))


def label(selection):
    return f'Input {selection.root + 1}/{selection.relative}'


def redact(message):
    text = str(message)
    text = re.sub(r'[A-Za-z]:[\\/][^\n,;]+', '[server path]', text)
    return re.sub(r'(?<![\w/])/(?!/)[^\n,;]+', '[server path]', text)
