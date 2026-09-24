import json
import shutil
import subprocess
from pathlib import Path

import pytest


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
    """The suite-level completed_bundle fixture is supplied by the container integration setup."""
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
