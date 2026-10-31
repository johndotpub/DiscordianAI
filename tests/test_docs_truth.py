"""Mechanical documentation-truth checks for configuration and references."""

import ast
from concurrent.futures import ThreadPoolExecutor
import configparser
from functools import lru_cache
import importlib
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import warnings

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
README = ROOT / "README.md"
CONFIGURATION = DOCS / "Configuration.md"
CONNECTION_POOLING = DOCS / "ConnectionPooling.md"
CONFIG_EXAMPLE = ROOT / "config.ini.example"
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG_SOURCE = ROOT / "src" / "config.py"
ALLOWLIST = DOCS / ".doc-truth-allowlist.toml"
ARCHITECTURE = DOCS / "Architecture.md"

CONFIG_KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
DEFAULT_MARKER_PATTERN = re.compile(r"\*\*`([A-Z][A-Z0-9_]+)`\*\*.*?\*\(default:\s*(.+?)\)\*")
AUTOMODULE_PATTERN = re.compile(r"\.\.\s+automodule::\s+(src\.[A-Za-z0-9_.]+)")
SOURCE_PATH_PATTERN = re.compile(r"src/([A-Za-z_][A-Za-z0-9_]*)\.py")
BARE_PYTHON_FILE_PATTERN = re.compile(r"(?<![\w./-])([A-Za-z_][A-Za-z0-9_]*\.py)\b")
DOTTED_PATTERN = re.compile(r"(?<![\w.])((?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*)\b")
MEMORY_FIGURE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:[KMGT]i?B|B)\b",
    re.IGNORECASE,
)
STARTUP_CLAIM_PATTERN = re.compile(r"\bprevents?\s+startup\b", re.IGNORECASE)
STALE_ARCHITECTURE_PHRASES = (
    re.compile(r"\bThread-safe per-user transcripts\b", re.IGNORECASE),
    re.compile(r"\bSeparate file and console handlers\b", re.IGNORECASE),
)
README_REPOSITORY_ROOTS = ("docs/", "src/", "scripts/", "contrib/")
MARKDOWN_TARGET_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
ACTIONS_WORKFLOW_URL_PATTERN = re.compile(
    r"https://github\.com/johndotpub/DiscordianAI/actions/workflows/([^/?#)\s]+)"
)
LOCAL_WORKFLOW_REFERENCE_PATTERN = re.compile(r"\.github/workflows/([A-Za-z0-9_.-]+)")
FRONTIER_CLAIM_PATTERN = re.compile(
    r"\b(?:frontier|state[\s-]+of[\s-]+the[\s-]+art)\b",
    re.IGNORECASE,
)
EXTERNAL_PYTHON_FILES = {"discord.py"}
COMMAND_ROOTS = ("python", "pytest", "ruff", "black", "discordian.sh", "docker compose")
NON_MODULE_SUFFIXES = {
    ".cfg",
    ".conf",
    ".example",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".pid",
    ".py",
    ".rst",
    ".service",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SOURCE_MODULES = {path.stem for path in (ROOT / "src").glob("*.py") if path.stem != "__init__"}


def _documented_python_file_exists(filename: str) -> bool:
    """Return True when a bare ``*.py`` reference names a file in this repository."""
    if filename.lower() in EXTERNAL_PYTHON_FILES:
        return True
    candidates = (
        ROOT / filename,
        ROOT / "src" / filename,
        ROOT / "tests" / filename,
        ROOT / "scripts" / filename,
        DOCS / filename,
        DOCS / "api" / filename,
    )
    return any(candidate.is_file() for candidate in candidates)


def _allowlist_entries() -> list[dict[str, str]]:
    if not ALLOWLIST.exists():
        return []
    data = tomllib.loads(ALLOWLIST.read_text(encoding="utf-8"))
    entries = data.get("exception", [])
    for entry in entries:
        missing = {"check", "target", "reason"} - set(entry)
        assert not missing, f"Allowlist entry missing fields {sorted(missing)}: {entry}"
        assert entry["reason"].strip(), f"Allowlist entry needs a reason: {entry}"
    return entries


def _allowed(check: str, target: str) -> bool:
    return any(
        entry["check"] == check and entry["target"] == target for entry in _allowlist_entries()
    )


@lru_cache(maxsize=1)
def _config_module():
    spec = importlib.util.spec_from_file_location("doc_truth_config", CONFIG_SOURCE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env_keys() -> set[str]:
    tree = ast.parse(CONFIG_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_apply_env_overrides":
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "env_keys"
                for target in statement.targets
            ):
                continue
            return set(ast.literal_eval(statement.value))
    msg = "Could not find env_keys in src/config.py"
    raise AssertionError(msg)


def _loader_keys() -> set[str]:
    return set(_config_module()._CONFIG_DEFAULTS) | _env_keys()


def _ini_keys(path: Path) -> set[str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    keys: set[str] = set()
    for section in parser.sections():
        keys.update(parser.options(section))
    return keys


def _fenced_blocks(text: str) -> list[tuple[int, str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[int, str, str]] = []
    inside = False
    language = ""
    start = 0
    body: list[str] = []
    for line_number, line in enumerate(lines, 1):
        match = re.match(r"^\s*```(.*)$", line)
        if match:
            if inside:
                blocks.append((start, language, "\n".join(body)))
                inside = False
            else:
                inside = True
                language = match.group(1).strip()
                start = line_number
                body = []
            continue
        if inside:
            body.append(line)
    return blocks


def _complete_example_keys(text: str) -> set[str]:
    heading = re.search(r"^##\s+Complete Configuration Example\s*$", text, re.MULTILINE)
    assert heading, "docs/Configuration.md has no Complete Configuration Example section"
    remainder = text[heading.end() :]
    match = re.search(r"```(?:ini)?\n(.*?)```", remainder, re.DOTALL)
    assert match, "Complete Configuration Example has no fenced ini block"
    keys: set[str] = set()
    for line in match.group(1).splitlines():
        key_match = re.match(r"^\s*([A-Z][A-Z0-9_]+)\s*=", line)
        if key_match:
            keys.add(key_match.group(1))
    return keys


def _as_literal(value: str):
    stripped = value.strip().strip("`").strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        stripped = stripped[1:-1]
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"[+-]?\d+", stripped):
        return int(stripped)
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", stripped):
        return float(stripped)
    return stripped


def _defaults_equal(documented, actual) -> bool:
    if isinstance(documented, bool) or isinstance(actual, bool):
        return documented is actual
    if isinstance(documented, (int, float)) and isinstance(actual, (int, float)):
        return float(documented) == float(actual)
    return documented == actual


def _markdown_section(text: str, title: str) -> str:
    heading = re.search(rf"^##\s+{re.escape(title)}\s*$", text, re.MULTILINE)
    assert heading, f"Missing section: {title}"
    remainder = text[heading.end() :]
    next_heading = re.search(r"^##\s+", remainder, re.MULTILINE)
    return remainder[: next_heading.start()] if next_heading else remainder


def _doc_files() -> list[Path]:
    return [README, *sorted(DOCS.glob("*.md"))]


def _doc_commands() -> list[tuple[Path, int, str]]:
    commands: list[tuple[Path, int, str]] = []
    for path in _doc_files():
        for start, _language, body in _fenced_blocks(path.read_text(encoding="utf-8")):
            for offset, line in enumerate(body.splitlines(), 1):
                command = line.strip()
                if not command or command.startswith("#"):
                    continue
                if command.startswith(("$ ", "> ")):
                    command = command[2:].strip()
                if _command_root(command) in COMMAND_ROOTS:
                    commands.append((path, start + offset, command))
    return commands


def _command_root(command: str) -> str:
    normalized = command.removeprefix("./")
    if normalized.startswith("docker compose"):
        return "docker compose"
    return normalized.split(maxsplit=1)[0]


def _safe_invocation(  # noqa: PLR0911 - one branch per documented command root
    command: str,
) -> tuple[list[str], str | None]:
    root = _command_root(command)
    if root == "python":
        parts = command.split()
        if "-m" in parts:
            module = parts[parts.index("-m") + 1]
            return [sys.executable, "-m", module, "--help"], None
        script = parts[1] if len(parts) > 1 else None
        if script and script.endswith(".py"):
            return [sys.executable, script, "--help"], None
        return [sys.executable, "--help"], None
    if root == "pytest":
        return [sys.executable, "-m", "pytest", "--help"], None
    if root == "ruff":
        return [sys.executable, "-m", "ruff", "--help"], None
    if root == "black":
        return [sys.executable, "-m", "black", "--help"], None
    if root == "discordian.sh":
        return [str(ROOT / "discordian.sh"), "--help"], None
    if root == "docker compose":
        docker = shutil.which("docker")
        if docker is None:
            return [], "docker is not installed"
        return [docker, "compose", "config"], None
    return [], f"unsupported command root: {root}"


def _run_safe_command(invocation: list[str]) -> subprocess.CompletedProcess[str]:
    if Path(invocation[0]).name == "docker" and invocation[1:2] == ["compose"]:
        with tempfile.TemporaryDirectory() as temp_dir:
            compose_dir = Path(temp_dir)
            shutil.copy2(ROOT / "docker-compose.yml", compose_dir / "docker-compose.yml")
            shutil.copy2(ENV_EXAMPLE, compose_dir / ".env")
            return subprocess.run(  # noqa: S603 - fixed local commands, no shell
                invocation,
                cwd=compose_dir,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
    return subprocess.run(  # noqa: S603 - fixed local commands, no shell
        invocation,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_b1_configuration_parity() -> None:
    """Config example, loader, documentation, and complete example carry the same keys."""
    loader = _loader_keys()
    example = _ini_keys(CONFIG_EXAMPLE)
    docs_text = CONFIGURATION.read_text(encoding="utf-8")
    documented = set(CONFIG_KEY_PATTERN.findall(docs_text))
    complete_example = _complete_example_keys(docs_text)

    sources = {
        "config.ini.example": example,
        "loader": loader,
        "docs/Configuration.md": documented,
    }
    failures: list[str] = []
    for source_name, keys in sources.items():
        for key in sorted(loader - keys):
            target = f"{key}@{source_name}"
            if not _allowed("B1", target):
                failures.append(f"{target}: loader key missing from {source_name}")
        for key in sorted(keys - loader):
            target = f"{key}@not-in-loader"
            if not _allowed("B1", target):
                failures.append(f"{target}: documented in {source_name} but not read by loader")
    for key in sorted(loader - complete_example):
        target = f"{key}@complete-example"
        if not _allowed("B1", target):
            failures.append(f"{target}: loader key missing from complete config example")
    assert not failures, "\n".join(failures)


def test_b2_documented_defaults_match_code() -> None:
    """Every documented default equals the live default in src/config.py."""
    text = CONFIGURATION.read_text(encoding="utf-8")
    defaults = _config_module()._CONFIG_DEFAULTS
    failures: list[str] = []
    documented = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        match = DEFAULT_MARKER_PATTERN.search(line)
        if not match:
            continue
        key, raw_default = match.groups()
        documented += 1
        if raw_default.startswith("the value of `") and raw_default.endswith("`"):
            alias = raw_default.removeprefix("the value of `").removesuffix("`")
            if alias not in defaults:
                failures.append(f"line {line_number}: {key} aliases unknown key {alias}")
                continue
            expected = defaults[alias]
        elif key in defaults:
            expected = defaults[key]
        else:
            failures.append(f"line {line_number}: {key} has no default in src/config.py")
            continue
        actual = _as_literal(raw_default) if not raw_default.startswith("the value") else expected
        if not _defaults_equal(actual, expected):
            failures.append(
                f"line {line_number}: {key} documented as {actual!r}, code default is {expected!r}"
            )
    assert documented, "No documented defaults found in docs/Configuration.md"
    assert not failures, "\n".join(failures)


def test_b3_environment_parity() -> None:
    """Environment keys match .env.example and the environment documentation section."""
    env_keys = _env_keys()
    env_file_keys: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=", line)
        if match:
            env_file_keys.add(match.group(1))
    docs_text = CONFIGURATION.read_text(encoding="utf-8")
    env_section = _markdown_section(docs_text, "Environment Variable Override")
    documented_env = set(CONFIG_KEY_PATTERN.findall(env_section))

    failures: list[str] = []
    for key in sorted(env_keys - env_file_keys):
        target = f"{key}@.env.example"
        if not _allowed("B3", target):
            failures.append(f"{target}: environment key missing from .env.example")
    for key in sorted(env_keys - documented_env):
        target = f"{key}@docs-environment-section"
        if not _allowed("B3", target):
            failures.append(f"{target}: environment key missing from environment documentation")
    for key in sorted(env_file_keys - env_keys):
        target = f"{key}@.env.example-not-read"
        if not _allowed("B3", target):
            failures.append(f"{target}: .env.example key is not read by config")
    assert not failures, "\n".join(failures)


def _importable(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _source_symbols() -> dict[str, set[str]]:
    symbols: dict[str, set[str]] = {}
    for path in sorted((ROOT / "src").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(target.id for target in node.targets if isinstance(target, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        symbols[path.stem] = names
    return symbols


def _module_target_exists(module_name: str) -> bool:
    return (ROOT / "src" / f"{module_name}.py").exists()


def test_b4_no_dead_documentation_references() -> None:  # noqa: PLR0912
    """Documented source files, modules, functions, and autodoc targets all exist."""
    failures: list[str] = []
    symbols = _source_symbols()
    files = [*_doc_files(), *sorted(DOCS.rglob("*.rst"))]
    for path in files:
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for match in SOURCE_PATH_PATTERN.finditer(text):
            module = match.group(1)
            target = f"src/{module}.py"
            if not (ROOT / "src" / f"{module}.py").exists() and not _allowed("B4", target):
                failures.append(f"{relative}: missing {target}")
        for match in AUTOMODULE_PATTERN.finditer(text):
            target = match.group(1)
            parts = target.split(".")
            module = parts[1] if len(parts) > 1 else ""
            if not _module_target_exists(module) and not _allowed("B4", target):
                failures.append(f"{relative}: {target} has no matching src/{module}.py")
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in BARE_PYTHON_FILE_PATTERN.finditer(line):
                filename = match.group(1)
                if not _documented_python_file_exists(filename) and not _allowed("B4", filename):
                    failures.append(
                        f"{relative}:{line_number}: {filename} does not exist in this repository"
                    )
            for match in DOTTED_PATTERN.finditer(line):
                chain = match.group(1)
                if chain.endswith(tuple(NON_MODULE_SUFFIXES)):
                    continue
                parts = chain.split(".")
                if parts[0] == "src":
                    if len(parts) < 2:
                        continue
                    module = parts[1]
                    attribute = parts[2] if len(parts) > 2 else None
                    if module not in SOURCE_MODULES:
                        if not _allowed("B4", chain):
                            failures.append(
                                f"{relative}:{line_number}: src.{module} is not a module"
                            )
                        continue
                    if (
                        attribute
                        and attribute not in symbols.get(module, set())
                        and not _allowed("B4", chain)
                    ):
                        failures.append(
                            f"{relative}:{line_number}: src.{module}.{attribute} does not exist"
                        )
                    continue
                first = parts[0]
                if first in SOURCE_MODULES:
                    attribute = parts[1]
                    if attribute not in symbols.get(first, set()) and not _allowed("B4", chain):
                        failures.append(
                            f"{relative}:{line_number}: {first}.{attribute} does not exist"
                        )
                    continue
                if "_" in first and not _importable(first) and not _allowed("B4", chain):
                    failures.append(
                        f"{relative}:{line_number}: {chain} names a missing module {first!r}"
                    )
    assert not failures, "\n".join(failures)


def test_b5_documented_commands_are_runnable() -> None:
    """Fenced commands have working entry points; unsafe commands are listed when skipped."""
    commands = _doc_commands()
    assert commands, "No documented commands found"
    invocations: dict[tuple[str, ...], tuple[list[str], str]] = {}
    skipped: list[str] = []
    for path, line_number, command in commands:
        location = f"{path.relative_to(ROOT)}:{line_number}: {command}"
        if _command_root(command) == "python" and "--help" not in command:
            skipped.append(f"{location} (would start the bot; skipped)")
            continue
        invocation, reason = _safe_invocation(command)
        if reason or not invocation:
            skipped.append(f"{location} ({reason or 'no safe invocation'})")
            continue
        if "--help" not in command and not command.startswith("docker compose config"):
            skipped.append(f"{location} (ran its --help/config form instead)")
        invocations.setdefault(tuple(invocation), (invocation, location))
    if skipped:
        warnings.warn(
            "B5 skipped actual command execution for:\n" + "\n".join(skipped),
            UserWarning,
            stacklevel=2,
        )
    assert invocations, f"No safe documented commands could be run; skipped: {skipped}"
    with ThreadPoolExecutor(max_workers=len(invocations)) as executor:
        futures = {
            executor.submit(_run_safe_command, invocation): location
            for invocation, location in invocations.values()
        }
        failures: list[str] = []
        for future, location in futures.items():
            result = future.result()
            if result.returncode != 0:
                failures.append(
                    f"{location}: exit {result.returncode}\n{result.stdout}\n{result.stderr}"
                )
    assert not failures, "\n".join(failures)


def _source_constants() -> dict[str, list[object]]:
    constants: dict[str, list[object]] = {}
    for path in sorted((ROOT / "src").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
                value_node = node.value
            else:
                continue
            for target in targets:
                if not isinstance(target, ast.Name) or not target.id.isupper():
                    continue
                try:
                    value = ast.literal_eval(value_node)
                except (ValueError, TypeError):
                    continue
                constants.setdefault(target.id, []).append(value)
    return constants


def _strip_inline_comment(value: str) -> str:
    quote: str | None = None
    for index, character in enumerate(value):
        if character in {'"', "'"}:
            quote = None if quote == character else character if quote is None else quote
        elif character == "#" and quote is None:
            return value[:index].strip()
    return value.strip()


def test_b6_quoted_constants_match_source() -> None:
    """Constants quoted in prose have the same literal value as src/ definitions."""
    constants = _source_constants()
    failures: list[str] = []
    checked = 0
    assignment_pattern = re.compile(r"^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)\s*=\s*(.+?)\s*$")
    for path in _doc_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = assignment_pattern.match(line)
            if not match:
                continue
            name, raw_value = match.groups()
            if name not in constants:
                continue
            raw_value = _strip_inline_comment(raw_value)
            try:
                documented_value = ast.literal_eval(raw_value)
            except (ValueError, SyntaxError):
                continue
            live_values = constants[name]
            checked += 1
            if not any(_defaults_equal(documented_value, live) for live in live_values):
                target = f"{name}@{path.relative_to(ROOT)}"
                if not _allowed("B6", target):
                    failures.append(
                        f"{path.relative_to(ROOT)}:{line_number}: {name} documented as "
                        f"{documented_value!r}, live value is {live_values!r}"
                    )
    assert checked, "No documented constants were checked"
    assert not failures, "\n".join(failures)


def test_b7_documented_value_lists_match_validators() -> None:
    """BOT_PRESENCE and ACTIVITY_TYPE lists equal the validator-enumerated values."""
    import discord

    text = CONFIGURATION.read_text(encoding="utf-8")
    expected = {
        "BOT_PRESENCE": {status.name for status in discord.Status},
        "ACTIVITY_TYPE": {
            activity.name
            for activity in discord.ActivityType
            if activity is not discord.ActivityType.unknown
        },
    }
    failures: list[str] = []
    for key, valid_values in expected.items():
        pattern = re.compile(rf"\*\*`{key}`\*\*.*")
        match = pattern.search(text)
        if not match:
            failures.append(f"{key} is not documented in docs/Configuration.md")
            continue
        documented_values = set(re.findall(r'"([^"]+)"', match.group(0)))
        if documented_values != valid_values:
            failures.append(
                f"{key}: documented {sorted(documented_values)}, validators accept "
                f"{sorted(valid_values)}"
            )
    assert not failures, "\n".join(failures)


def test_b8_sphinx_coverage() -> None:
    """Every source module has an API page and every API page is in a toctree."""
    from tests.test_docs import missing_api_pages, missing_toctree_entries

    missing_pages = missing_api_pages()
    missing_toctree = missing_toctree_entries()
    failures = [
        *(f"src/{module}.py has no docs/api/{module}.rst" for module in missing_pages),
        *(f"docs/api/{module}.rst is not in the index toctree" for module in missing_toctree),
    ]
    assert not failures, "\n".join(failures)
    assert (ROOT / "tests" / "test_docs.py").exists(), "Sphinx -W build test is missing"


def test_b9_connection_pooling_has_no_unmeasured_memory_figure() -> None:
    """ConnectionPooling.md must not quote a memory total that no test measures."""
    text = CONNECTION_POOLING.read_text(encoding="utf-8")
    offenders = [
        f"line {line_number}: {line.strip()}"
        for line_number, line in enumerate(text.splitlines(), 1)
        if MEMORY_FIGURE_PATTERN.search(line)
    ]
    assert not offenders, (
        "docs/ConnectionPooling.md states a memory figure without a benchmark; "
        "remove it or add a measured test:\n" + "\n".join(offenders)
    )


def test_b10_startup_claims_name_the_abort_split() -> None:
    """A 'prevents startup' claim must sit beside both abort and warning behaviour."""
    failures: list[str] = []
    for path in _doc_files():
        text = path.read_text(encoding="utf-8")
        paragraphs = re.split(r"\n\s*\n", text)
        for index, paragraph in enumerate(paragraphs):
            if not STARTUP_CLAIM_PATTERN.search(paragraph):
                continue
            window = " ".join(paragraphs[max(0, index - 1) : index + 2]).lower()
            has_abort = any(
                phrase in window
                for phrase in ("abort", "exit", "stop the process", "stops the process")
            )
            if not (has_abort and "warning" in window):
                failures.append(
                    f"{path.relative_to(ROOT)}: 'prevents startup' is not adjacent to "
                    "the abort/warning split"
                )
    assert not failures, "\n".join(failures)


def test_b11_architecture_prose_matches_current_design() -> None:
    """Architecture.md must not describe per-user history or split file/console logging."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    offenders = [
        f"line {line_number}: {line.strip()}"
        for line_number, line in enumerate(text.splitlines(), 1)
        if any(pattern.search(line) for pattern in STALE_ARCHITECTURE_PHRASES)
    ]
    assert not offenders, (
        "docs/Architecture.md describes a design this code no longer has; history is keyed "
        "per conversation and the supervisor owns the only log file:\n" + "\n".join(offenders)
    )


def _readme_links() -> list[str]:
    """Return repository-relative link targets from the README."""
    text = README.read_text(encoding="utf-8")
    links: list[str] = []
    for match in MARKDOWN_TARGET_PATTERN.finditer(text):
        target = match.group(1).strip().strip("<>")
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        links.append(target.split("#", 1)[0].split("?", 1)[0])
    return links


def test_b12_readme_repository_links_resolve() -> None:
    """Every repository path linked from README exists and each source root is linked."""
    links = _readme_links()
    failures = [target for target in links if not (ROOT / target).exists()]
    missing_roots = [
        root
        for root in README_REPOSITORY_ROOTS
        if not any(target.startswith(root) for target in links)
    ]
    assert not failures, "README links missing repository paths:\n" + "\n".join(failures)
    assert not missing_roots, "README does not link a repository path under: " + ", ".join(
        missing_roots
    )


def _readme_workflow_files() -> set[str]:
    """Return workflow file names referenced by README badges or links."""
    text = README.read_text(encoding="utf-8")
    workflows = set(ACTIONS_WORKFLOW_URL_PATTERN.findall(text))
    workflows.update(LOCAL_WORKFLOW_REFERENCE_PATTERN.findall(text))
    return workflows


def test_b13_readme_workflow_links_resolve() -> None:
    """Every workflow named by a README badge or link exists under .github/workflows."""
    workflows = _readme_workflow_files()
    assert workflows, "README names no GitHub Actions workflow"
    workflow_dir = ROOT / ".github" / "workflows"
    failures = [name for name in sorted(workflows) if not (workflow_dir / name).is_file()]
    assert (
        not failures
    ), "README names workflow files that do not exist under .github/workflows:\n" + "\n".join(
        failures
    )


def test_b14_readme_does_not_claim_a_frontier_model_generation() -> None:
    """README must not call any model generation frontier or state of the art."""
    text = README.read_text(encoding="utf-8")
    matches = [match.group(0) for match in FRONTIER_CLAIM_PATTERN.finditer(text)]
    assert not matches, (
        "README claims a model generation is frontier or state of the art; the configured "
        "default is gpt-5-mini, so the claim is not true: " + ", ".join(matches)
    )


def test_b15_documentation_map_names_the_contracts() -> None:
    """The README documentation map links AGENTS.md and docs/API-CONTRACT.md."""
    section = _markdown_section(README.read_text(encoding="utf-8"), "Documentation Map")
    missing = [
        target for target in ("AGENTS.md", "docs/API-CONTRACT.md") if f"]({target})" not in section
    ]
    assert not missing, "README Documentation Map is missing links: " + ", ".join(missing)
