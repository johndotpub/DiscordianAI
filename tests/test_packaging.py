"""Packaging contract: the wheel ships ``src/`` and exposes the console script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import zipfile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
_BUILD_ROOT_FILES = (
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "README.md",
    "README.rst",
    "LICENSE",
    "MANIFEST.in",
)
_ROUTING_MODULES = frozenset(
    {
        "src/routing/__init__.py",
        "src/routing/contracts.py",
        "src/routing/context.py",
        "src/routing/features.py",
        "src/routing/heuristic.py",
        "src/routing/lexicon.py",
        "src/routing/scoring.py",
        "src/routing/telemetry.py",
    }
)
_ROUTING_LEXICON = "src/routing/data/lexicon.en.json"


def _copy_build_tree(destination: Path) -> Path:
    destination.mkdir()
    for filename in _BUILD_ROOT_FILES:
        source = REPO_ROOT / filename
        if source.is_file():
            shutil.copy2(source, destination / filename)
    shutil.copytree(
        REPO_ROOT / "src",
        destination / "src",
        ignore=shutil.ignore_patterns("*.egg-info", "__pycache__", "*.pyc"),
    )
    return destination


def _build_wheel(tmp_path: Path) -> Path:
    missing = [
        tool for tool in ("pip", "setuptools", "wheel") if importlib.util.find_spec(tool) is None
    ]
    if missing:
        pytest.skip(f"missing build tooling: {', '.join(missing)}; a wheel cannot be built")

    source_root = _copy_build_tree(tmp_path / "source")
    destination = tmp_path / "wheelhouse"
    destination.mkdir()

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
        cwd=source_root,
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
        entries = {name for name in archive.namelist() if name}
        top_level = {name.partition("/")[0] for name in entries}
        lexicon_payload = archive.read(_ROUTING_LEXICON) if _ROUTING_LEXICON in entries else None

    dist_info = {name for name in top_level if name.endswith(".dist-info")}
    assert len(dist_info) == 1, f"expected one dist-info directory, found {top_level}"
    assert top_level == dist_info | {"src"}, (
        "wheel top-level entries must be exactly the dist-info directory and src/, "
        f"found {sorted(top_level)}"
    )

    missing_routing_modules = _ROUTING_MODULES - entries
    assert not missing_routing_modules, (
        "wheel is missing routing modules (check that [tool.setuptools] packages "
        f"includes 'src.routing'): {sorted(missing_routing_modules)}"
    )

    assert lexicon_payload is not None, (
        f"wheel is missing routing lexicon {_ROUTING_LEXICON} (check that "
        "[tool.setuptools.package-data] ships src.routing/data/*.json)"
    )
    lexicon = json.loads(lexicon_payload)
    assert isinstance(lexicon, dict), f"{_ROUTING_LEXICON} must contain a JSON object"
    classes = lexicon.get("classes")
    assert isinstance(classes, dict), f"{_ROUTING_LEXICON} key 'classes' must be a JSON object"
    assert classes, f"{_ROUTING_LEXICON} must declare at least one routing class"

    project = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["discordianai"] == "src.main:main"
