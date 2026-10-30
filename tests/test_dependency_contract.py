"""Contract tests for the project's declared runtime dependencies."""

from __future__ import annotations

import importlib
from importlib import metadata
from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_FILE = ROOT / "requirements.txt"
PYPROJECT_FILE = ROOT / "pyproject.toml"
SRC_DIR = ROOT / "src"


def _requirement_contract(requirement: Requirement) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the parts of a requirement that both files must agree on."""
    extras = tuple(sorted(requirement.extras))
    specifiers = tuple(sorted(str(specifier) for specifier in requirement.specifier))
    return extras, specifiers


def _read_requirements() -> dict[str, Requirement]:
    """Parse requirements.txt into canonical-name keyed requirements."""
    requirements: dict[str, Requirement] = {}
    for raw_line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        requirements[canonicalize_name(requirement.name)] = requirement
    return requirements


def _read_pyproject_dependencies() -> dict[str, Requirement]:
    """Parse pyproject.toml runtime dependencies into canonical-name keyed requirements."""
    data = tomllib.loads(PYPROJECT_FILE.read_text(encoding="utf-8"))
    dependencies: dict[str, Requirement] = {}
    for line in data["project"]["dependencies"]:
        requirement = Requirement(line)
        dependencies[canonicalize_name(requirement.name)] = requirement
    return dependencies


def test_requirements_and_pyproject_declare_the_same_runtime_dependencies() -> None:
    """requirements.txt and pyproject.toml must stay in lockstep."""
    requirements = _read_requirements()
    pyproject = _read_pyproject_dependencies()

    only_in_requirements = sorted(requirements.keys() - pyproject.keys())
    only_in_pyproject = sorted(pyproject.keys() - requirements.keys())
    assert requirements.keys() == pyproject.keys(), (
        f"runtime dependency names differ: only in requirements.txt="
        f"{only_in_requirements}, only in pyproject.toml={only_in_pyproject}"
    )

    mismatches = {
        name: (_requirement_contract(requirements[name]), _requirement_contract(pyproject[name]))
        for name in requirements
        if _requirement_contract(requirements[name]) != _requirement_contract(pyproject[name])
    }
    assert not mismatches, f"runtime dependency constraints differ: {mismatches}"


def test_every_declared_runtime_dependency_is_installed_and_compatible() -> None:
    """Every declared distribution is installed at a version inside its constraint."""
    failures: list[str] = []
    for name, requirement in _read_pyproject_dependencies().items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            failures.append(f"{name} is declared but not installed")
            continue
        if installed not in requirement.specifier:
            failures.append(f"{name} {installed} does not satisfy {requirement.specifier}")
    assert not failures, "\n".join(failures)


def test_websockets_and_aiohttp_are_indirect_and_all_src_modules_import() -> None:
    """Transitive-only packages are not direct dependencies, and src still imports."""
    declared = _read_pyproject_dependencies()
    assert "websockets" not in declared
    assert "aiohttp" not in declared

    failures: list[str] = []
    for path in sorted(SRC_DIR.glob("*.py")):
        module_name = f"src.{path.stem}"
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{module_name}: {type(exc).__name__}: {exc}")
    assert not failures, "src modules failed to import:\n" + "\n".join(failures)


def test_openai_constraint_has_a_floor_and_a_ceiling() -> None:
    """The OpenAI SDK must be bounded on both sides."""
    expected = {">=2.41", "<4"}
    declarations = (
        ("requirements.txt", _read_requirements()),
        ("pyproject.toml", _read_pyproject_dependencies()),
    )
    for label, declared in declarations:
        specifiers = {str(specifier) for specifier in declared["openai"].specifier}
        assert specifiers == expected, f"{label} openai constraint is {sorted(specifiers)}"
