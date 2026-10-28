"""Contract tests for the shipped container assets.

These tests parse the compose file and Dockerfile as data. They do not need a
Docker daemon.
"""

from ipaddress import IPv4Address
from pathlib import Path
import re

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
SECURITY_DOC_PATH = REPO_ROOT / "docs" / "Security.md"

YAML_BLOCK_PATTERN = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)
HEALTHCHECK_PATTERN = re.compile(r"^\s*HEALTHCHECK\b", re.IGNORECASE)


def _load_compose():
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _bot_service():
    return _load_compose()["services"]["discordianai"]


def _service_environment(service):
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}

    values = {}
    for item in environment:
        key, _, value = str(item).partition("=")
        values[key] = value
    return values


def _env_file_paths(service):
    env_file = service.get("env_file", [])
    if isinstance(env_file, (str, dict)):
        env_file = [env_file]

    paths = []
    for entry in env_file:
        if isinstance(entry, dict):
            paths.append(str(entry.get("path", "")))
        else:
            paths.append(str(entry))
    return paths


def _healthcheck_command(service):
    command = service.get("healthcheck", {}).get("test", [])
    if isinstance(command, str):
        return command
    return " ".join(str(part) for part in command)


def _published_ports(service):
    published = []
    for entry in service.get("ports", []):
        if isinstance(entry, dict):
            published.append(
                (
                    str(entry.get("host_ip", "")),
                    str(entry.get("published", "")),
                    str(entry.get("target", "")),
                )
            )
            continue

        parts = str(entry).split(":")
        if len(parts) == 3:
            published.append((parts[0], parts[1], parts[2]))
        elif len(parts) == 2:
            published.append(("", parts[0], parts[1]))
    return published


def _volume_paths(service):
    paths = []
    for entry in service.get("volumes", []):
        if isinstance(entry, dict):
            paths.append((str(entry.get("source", "")), str(entry.get("target", ""))))
        else:
            parts = str(entry).split(":")
            source = parts[0]
            target = parts[1] if len(parts) > 1 else ""
            paths.append((source, target))
    return paths


def test_compose_has_no_version_key():
    assert "version" not in _load_compose()


def test_compose_injects_the_documented_env_file():
    env_files = [Path(path).name for path in _env_file_paths(_bot_service())]
    assert ".env" in env_files


def test_compose_publishes_the_health_port_and_binds_all_interfaces():
    service = _bot_service()
    assert ("127.0.0.1", "8080", "8080") in _published_ports(service)
    assert _service_environment(service).get("HEALTH_HOST") == str(IPv4Address(0))


def test_compose_healthcheck_queries_the_running_bot():
    command = _healthcheck_command(_bot_service()).lower()
    assert "/health" in command
    assert "validate_full_config" not in command
    assert "load_config" not in command
    assert "curl" not in command


def test_compose_has_no_mounts_for_paths_nothing_writes():
    volumes = _volume_paths(_bot_service())
    sources = {Path(source).as_posix().rstrip("/") for source, _ in volumes}
    targets = {Path(target).as_posix().rstrip("/") for _, target in volumes}
    assert not sources & {"./logs", "./data", "logs", "data"}
    assert not targets & {"/app/logs", "/app/data"}


def test_dockerfile_defines_a_healthcheck():
    lines = DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines()
    assert any(HEALTHCHECK_PATTERN.match(line) for line in lines)


def test_security_doc_lists_only_shipped_compose_properties_or_optional_hardening():
    service = _bot_service()
    doc = SECURITY_DOC_PATH.read_text(encoding="utf-8")
    checked_services = 0

    for block in YAML_BLOCK_PATTERN.findall(doc):
        data = yaml.safe_load(block)
        if not isinstance(data, dict) or "services" not in data:
            continue

        optional = "optional" in block.lower() and "not enabled" in block.lower()
        if optional:
            continue

        for name, properties in data["services"].items():
            if not isinstance(properties, dict):
                continue
            checked_services += 1
            for property_name in properties:
                assert property_name in service, (
                    f"docs/Security.md lists '{property_name}' for compose "
                    f"service '{name}', but docker-compose.yml does not define it"
                )

    assert checked_services, "No compose service examples found in docs/Security.md"
