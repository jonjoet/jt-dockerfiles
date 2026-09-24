"""Validated process-wide mounted roots and resource limits."""
from dataclasses import dataclass
from pathlib import Path
import os

from quickalign.errors import ValidationError


def positive(env, name, default):
    try:
        value = int(env.get(name, default))
        if value < 1:
            raise ValueError
        return value
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{name} must be a positive integer") from exc


def directory(path, label):
    try:
        result = Path(path).resolve(strict=True)
        if not result.is_dir():
            raise ValueError
        return result
    except (ValueError, OSError) as exc:
        raise ValidationError(f"{label} must be an existing accessible directory") from exc


@dataclass(frozen=True)
class UiConfig:
    input_roots: tuple[Path, ...]
    output_root: Path
    work_root: Path
    max_upload_files: int = 16
    max_upload_bytes: int = 128 * 1024**2
    max_upload_total_bytes: int = 512 * 1024**2
    max_download_bytes: int = 128 * 1024**2
    max_threads: int = 4
    max_directory_entries: int = 2000

    @classmethod
    def load(cls, environment=None, *, input_base=Path('/inputs')):
        env = os.environ if environment is None else environment
        base = directory(input_base, 'Input base')
        roots = tuple(dict.fromkeys(directory(p, 'Input root') for p in
                      env.get('QUICKALIGN_INPUT_ROOTS', str(base)).split(os.pathsep) if p))
        if not roots or any(not r.is_relative_to(base) for r in roots):
            raise ValidationError('Input roots must be beneath the input base')
        if not all(os.access(p, os.R_OK | os.X_OK) for p in roots):
            raise ValidationError('Input roots must be readable and searchable')
        output = directory(env.get('QUICKALIGN_OUTPUT_ROOT', '/outputs'), 'Output root')
        work = directory(env.get('QUICKALIGN_WORK_ROOT', '/work'), 'Work root')
        all_roots = [base, output, work]
        if any(a.is_relative_to(b) or b.is_relative_to(a)
               for i, a in enumerate(all_roots) for b in all_roots[i + 1:]):
            raise ValidationError('Input, output and work mounts must be separate')
        if not all(os.access(p, os.W_OK | os.X_OK) for p in (output, work)):
            raise ValidationError('Output and work mounts must be writable and searchable')
        per_file = positive(env, 'QUICKALIGN_MAX_UPLOAD_MIB', 128)
        server_limit = positive(env, 'STREAMLIT_SERVER_MAX_UPLOAD_SIZE', 128)
        if per_file > server_limit:
            raise ValidationError('Upload limit exceeds Streamlit server upload limit')
        if positive(env, 'QUICKALIGN_MAX_THREADS', 4) < 2:
            raise ValidationError('At least two threads are required for streaming alignment')
        return cls(roots, output, work,
                   positive(env, 'QUICKALIGN_MAX_UPLOAD_FILES', 16), per_file * 1024**2,
                   positive(env, 'QUICKALIGN_MAX_UPLOAD_TOTAL_MIB', 512) * 1024**2,
                   positive(env, 'QUICKALIGN_MAX_DOWNLOAD_MIB', 128) * 1024**2,
                   positive(env, 'QUICKALIGN_MAX_THREADS', 4),
                   positive(env, 'QUICKALIGN_MAX_DIRECTORY_ENTRIES', 2000))
