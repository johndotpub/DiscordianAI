"""Guardrails for the single source of configuration defaults."""

import ast
import json
from pathlib import Path
import re

import pytest

from src.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
CONFIG_PATH = SRC_DIR / "config.py"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "resolved_config_minimal.json"

CONSTANT_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
PUBLIC_CONSTANT_ALLOWLIST: set[str] = set()

ENV_KEYS = (
    "DISCORD_TOKEN",
    "ADDRESS",
    "ALLOWED_CHANNELS",
    "ALLOWED_CHANNEL_IDS",
    "ALLOWED_GUILDS",
    "ALLOWED_GUILD_IDS",
    "BOT_PRESENCE",
    "ACTIVITY_TYPE",
    "ACTIVITY_STATUS",
    "OPENAI_API_KEY",
    "OPENAI_API_URL",
    "PERPLEXITY_API_KEY",
    "PERPLEXITY_API_URL",
    "PERPLEXITY_MODEL",
    "GPT_MODEL",
    "INPUT_TOKENS",
    "OUTPUT_TOKENS",
    "PERPLEXITY_OUTPUT_TOKENS",
    "CONTEXT_WINDOW",
    "SYSTEM_MESSAGE",
    "RATE_LIMIT",
    "RATE_LIMIT_PER",
    "OPENAI_MAX_CONNECTIONS",
    "OPENAI_MAX_KEEPALIVE",
    "PERPLEXITY_MAX_CONNECTIONS",
    "PERPLEXITY_MAX_KEEPALIVE",
    "LOOKBACK_MESSAGES_FOR_CONSISTENCY",
    "MAX_HISTORY_PER_USER",
    "CONVERSATION_TTL_SECONDS",
    "USER_LOCK_CLEANUP_INTERVAL",
    "ENTITY_DETECTION_MIN_WORDS",
    "MAX_URLS_PER_MESSAGE",
    "MAX_TOTAL_SCRAPED_CHARS",
    "SCRAPE_DEADLINE_SECONDS",
    "LOG_FILE",
    "LOG_LEVEL",
    "DISCORDIANAI_LOG_COLOR",
    "HEALTH_ENABLED",
    "HEALTH_HOST",
    "HEALTH_PORT",
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _constant_value_nodes(tree: ast.Module) -> dict[int, str]:
    """Map numeric value-node ids to the module constant they define."""
    values: dict[int, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and CONSTANT_NAME.fullmatch(target.id):
                values[id(value)] = target.id
    return values


def _config_constants(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and CONSTANT_NAME.fullmatch(target.id):
                names.add(target.id)
    return names


def _referenced_names() -> set[str]:
    references: set[str] = set()
    for path in SRC_DIR.rglob("*.py"):
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                references.add(node.id)
            elif isinstance(node, ast.Attribute):
                references.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                references.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                references.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
    return references


@pytest.mark.parametrize("literal", ["perplexity/sonar", "gpt-6-luna"])
def test_model_default_literal_appears_once_in_src(literal):
    sites = [
        f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
        for path in sorted(SRC_DIR.rglob("*.py"))
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Constant) and node.value == literal
    ]

    assert len(sites) == 1, f"{literal!r} literals in src/: {sites}"


@pytest.mark.parametrize(
    ("constant_name", "value"),
    [
        ("DEFAULT_OUTPUT_TOKENS", 8000),
        ("DEFAULT_CONTEXT_WINDOW", 128000),
    ],
)
def test_default_value_literal_lives_only_in_its_constant(constant_name, value):
    tree = _parse(CONFIG_PATH)
    constant_values = _constant_value_nodes(tree)

    occurrences = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is int and node.value == value
    ]
    assert any(
        constant_values.get(id(node)) == constant_name for node in occurrences
    ), f"{constant_name} must be defined as a numeric literal in config.py"

    duplicated = [node.lineno for node in occurrences if id(node) not in constant_values]
    assert not duplicated, (
        f"{value} is duplicated as bare literal(s) at config.py lines {duplicated}; "
        f"use {constant_name} instead"
    )


def test_resolved_config_matches_recorded_fixture(tmp_path, monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    config_path = tmp_path / "config.ini"
    config_path.write_text("[Discord]\nDISCORD_TOKEN=test-token\n", encoding="utf-8")

    config = load_config(str(config_path))
    rendered = json.dumps(config, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    assert rendered == FIXTURE_PATH.read_text(encoding="utf-8")


def test_every_config_constant_is_referenced_or_allowlisted():
    constants = _config_constants(_parse(CONFIG_PATH))
    unreferenced = sorted(constants - _referenced_names() - PUBLIC_CONSTANT_ALLOWLIST)

    assert not unreferenced, (
        "config.py exports constants that nothing in src/ reads: "
        f"{unreferenced}. Delete them or add them to PUBLIC_CONSTANT_ALLOWLIST "
        "with a reason."
    )
