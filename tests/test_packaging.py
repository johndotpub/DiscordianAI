"""Packaging contract: the wheel ships ``src/`` and exposes the console script."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tomllib
import zipfile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def _build_wheel(destination: Path) -> Path:
    if importlib.util.find_spec("pip") is None:
        pytest.skip("pip is not installed, so a wheel cannot be built")

    completed = subprocess.run(  # noqa: S603 - fixed interpreter and arguments, no shell
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(destination),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    wheels = sorted(destination.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, found {wheels}"
    return wheels[0]


def test_wheel_ships_src_package_and_exposes_console_script(tmp_path):
    wheel = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel) as archive:
        top_level = {name.partition("/")[0] for name in archive.namelist() if name}

    dist_info = {name for name in top_level if name.endswith(".dist-info")}
    assert len(dist_info) == 1, f"expected one dist-info directory, found {top_level}"
    assert top_level == dist_info | {"src"}, (
        "wheel top-level entries must be exactly the dist-info directory and src/, "
        f"found {sorted(top_level)}"
    )

    project = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["discordianai"] == "src.main:main"
