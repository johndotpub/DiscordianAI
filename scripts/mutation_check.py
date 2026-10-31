#!/usr/bin/env python3
"""Apply curated source mutations and verify that the named tests kill them."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutation:
    """One textual source change and the test file expected to catch it."""

    name: str
    path: str
    test: str
    old: str
    new: str


@dataclass
class Result:
    """Outcome of running one mutation."""

    mutation: Mutation
    status: str
    duration: float
    detail: str = ""


MUTATIONS = [
    Mutation(
        name="message-limit-is-2001",
        path="src/config.py",
        test="tests/test_absolute_limits.py",
        old="MESSAGE_LIMIT = 2000",
        new="MESSAGE_LIMIT = 2001",
    ),
    Mutation(
        name="invert-channel-id-check",
        path="src/message_router.py",
        test="tests/test_message_router_auth.py",
        old=(
            "    allowed_ids = _allowed_channel_ids(deps, bot)\n"
            "    if allowed_ids is not None:\n"
            "        try:\n"
            "            return int(channel.id) in allowed_ids"
        ),
        new=(
            "    allowed_ids = _allowed_channel_ids(deps, bot)\n"
            "    if allowed_ids is not None:\n"
            "        try:\n"
            "            return int(channel.id) not in allowed_ids"
        ),
    ),
    Mutation(
        name="delete-mention-guard",
        path="src/message_router.py",
        test="tests/test_message_router_auth.py",
        old=(
            "        if not _mentions_bot(message, bot):\n"
            '            _log_ignored(logger, message, "not_mentioned")\n'
            "            return\n"
        ),
        new="",
    ),
    Mutation(
        name="disable-explicit-channel-ids",
        path="src/message_router.py",
        test="tests/test_message_router_auth.py",
        old=(
            '    explicit_ids = _as_int_set(deps.get("ALLOWED_CHANNEL_IDS", []))\n'
            "    if explicit_ids:\n"
            "        return explicit_ids"
        ),
        new=(
            '    explicit_ids = _as_int_set(deps.get("ALLOWED_CHANNEL_IDS", []))\n'
            "    if False:\n"
            "        return explicit_ids"
        ),
    ),
    Mutation(
        name="scoped-guilds-only-first-guild",
        path="src/message_router.py",
        test="tests/test_channel_name_scope.py",
        old="    return guilds\n",
        new="    return guilds[:1]\n",
    ),
    Mutation(
        name="bot-reply-prefix-mentions-bot",
        path="src/message_processor.py",
        test="tests/test_bot_conversation_guard.py",
        old='= "" if author_is_bot else f"{message.author.mention} "',
        new=(
            '= f"{message.author.mention} " if author_is_bot '
            'else f"{message.author.mention} "'
        ),
    ),
    Mutation(
        name="openai-uses-perplexity-model",
        path="src/message_processor.py",
        test="tests/test_end_to_end.py",
        old=(
            "        openai_config = OpenAIConfig(\n"
            '            model=deps["GPT_MODEL"],'
        ),
        new=(
            "        openai_config = OpenAIConfig(\n"
            '            model=deps["PERPLEXITY_MODEL"],'
        ),
    ),
    Mutation(
        name="drop-reply-mention-prefix",
        path="src/message_processor.py",
        test="tests/test_end_to_end.py",
        old="            mention_prefix=reply_mention,",
        new="            mention_prefix=None,",
    ),
    Mutation(
        name="history-falls-back-to-user-id",
        path="src/smart_orchestrator.py",
        test="tests/test_conversation_scope.py",
        old=(
            '    conversation_key = getattr(request, "conversation_key", None)\n'
            "    if conversation_key is None:\n"
            "        conversation_key = request.user.id"
        ),
        new="    conversation_key = request.user.id",
    ),
    Mutation(
        name="cache-key-drops-conversation-digest",
        path="src/caching.py",
        test="tests/test_caching_scope.py",
        old=(
            '        "conversation_scope": "" if scope_id is None else str(scope_id),\n'
            '        "conversation_digest": conversation_digest,'
        ),
        new=(
            '        "conversation_scope": "" if scope_id is None else str(scope_id),\n'
            '        "conversation_digest": "",'
        ),
    ),
    Mutation(
        name="scraper-follows-redirects",
        path="src/web_scraper.py",
        test="tests/test_scraper_ssrf.py",
        old="httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=False)",
        new="httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True)",
    ),
    Mutation(
        name="rate-limit-uses-wall-clock",
        path="src/rate_limits.py",
        test="tests/test_rate_limit_clock.py",
        old=(
            "        current_time = time.monotonic()\n"
            "        log_method = None"
        ),
        new=(
            "        current_time = time.time()\n"
            "        log_method = None"
        ),
    ),
    Mutation(
        name="retry-read-timeouts",
        path="src/error_handling.py",
        test="tests/test_retry_policy.py",
        old=(
            "    return error_details.error_type not in {\n"
            "        ErrorType.API_AUTH_ERROR,\n"
            "        ErrorType.API_TIMEOUT,\n"
            "        ErrorType.CONFIG_ERROR,\n"
            "        ErrorType.VALIDATION_ERROR,\n"
            "    }"
        ),
        new=(
            "    return error_details.error_type not in {\n"
            "        ErrorType.API_AUTH_ERROR,\n"
            "        ErrorType.CONFIG_ERROR,\n"
            "        ErrorType.VALIDATION_ERROR,\n"
            "    }"
        ),
    ),
    Mutation(
        name="breaker-inside-retry-counts-attempts",
        path="src/openai_processing.py",
        test="tests/test_circuit_breaker_wiring.py",
        old=(
            "            response = await openai_circuit_breaker.call(\n"
            "                retry_with_backoff,\n"
            "                lambda: openai_client.chat.completions.create(**api_params),\n"
            "                DEFAULT_API_RETRY_CONFIG,\n"
            "                request.logger,\n"
            "            )"
        ),
        new=(
            "            response = await retry_with_backoff(\n"
            "                lambda: openai_circuit_breaker.call(\n"
            "                    lambda: openai_client.chat.completions.create(**api_params)\n"
            "                ),\n"
            "                DEFAULT_API_RETRY_CONFIG,\n"
            "                request.logger,\n"
            "            )"
        ),
    ),
    Mutation(
        name="health-loop-returns-immediately",
        path="src/health_checks.py",
        test="tests/test_absolute_limits.py",
        old=(
            "        results: dict[str, HealthCheckResult] = {}\n"
            "\n"
            "        for service, spec in PROVIDER_HEALTH_SPECS.items():"
        ),
        new=(
            "        results: dict[str, HealthCheckResult] = {}\n"
            "        return results\n"
            "\n"
            "        for service, spec in PROVIDER_HEALTH_SPECS.items():"
        ),
    ),
    Mutation(
        name="routing-skips-markup-sanitization",
        path="src/smart_orchestrator.py",
        test="tests/test_smart_orchestrator_coverage.py",
        old=(
            '    cleaned = DISCORD_MARKUP_PATTERN.sub("", message)\n'
            '    return " ".join(cleaned.split()).strip()'
        ),
        new="    return message",
    ),
]


def _select_mutations(only: str | None) -> list[Mutation]:
    if only is None:
        return list(MUTATIONS)
    needle = only.casefold()
    return [
        mutation
        for mutation in MUTATIONS
        if needle in mutation.name.casefold()
        or needle in mutation.path.casefold()
        or needle in mutation.test.casefold()
    ]


def _dirty_files(root: Path, paths: list[str]) -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = "git status failed; refusing to mutate an unknown tree"
        raise RuntimeError(message)
    return completed.stdout.strip()


def _match_snippet(text: str, old: str, new: str) -> tuple[str, str, int]:
    candidates = [(old, new)]
    if "\r\n" in text:
        candidates.insert(0, (old.replace("\n", "\r\n"), new.replace("\n", "\r\n")))
    for candidate_old, candidate_new in candidates:
        occurrences = text.count(candidate_old)
        if occurrences:
            return candidate_old, candidate_new, occurrences
    return old, new, 0


def _restore(root: Path, mutation: Mutation, backup: Path, original: bytes) -> None:
    target = root / mutation.path
    shutil.copyfile(backup, target)
    if target.read_bytes() != original:
        message = f"{mutation.path}: restored bytes differ from the backup"
        raise RuntimeError(message)
    diff = subprocess.run(
        ["git", "diff", "--quiet", "--", mutation.path],
        cwd=root,
        check=False,
    )
    if diff.returncode != 0:
        message = f"{mutation.path}: git diff reports changes after restore"
        raise RuntimeError(message)


def _run_test(root: Path, test_path: str, timeout: float) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                test_path,
                "-q",
                "-x",
                "-p",
                "no:cacheprovider",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return True, "test run timed out"
    output = (completed.stdout + completed.stderr).strip().splitlines()
    detail = output[-1] if output else ""
    return completed.returncode != 0, detail


def _print_table(results: list[Result], total_duration: float) -> None:
    width_name = max(len("Mutation"), *(len(result.mutation.name) for result in results))
    width_test = max(len("Catcher"), *(len(result.mutation.test) for result in results))
    header = (
        f"{'Mutation':<{width_name}}  {'Catcher':<{width_test}}  "
        f"{'Result':<8}  {'Seconds':>7}"
    )
    print()
    print(header)
    print("-" * len(header))
    for result in results:
        print(
            f"{result.mutation.name:<{width_name}}  "
            f"{result.mutation.test:<{width_test}}  "
            f"{result.status:<8}  {result.duration:>7.2f}"
        )
    print("-" * len(header))
    killed = sum(result.status == "KILLED" for result in results)
    print(f"{killed}/{len(results)} killed in {total_duration:.2f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        metavar="SUBSTRING",
        help="run only mutations whose name, path, or test contains this substring",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        metavar="SECONDS",
        help="per-mutation pytest timeout (default: 90)",
    )
    args = parser.parse_args(argv)

    selected = _select_mutations(args.only)
    if not selected:
        print(f"No mutation matches {args.only!r}", file=sys.stderr)
        return 2

    paths = sorted({mutation.path for mutation in selected})
    dirty = _dirty_files(ROOT, paths)
    if dirty:
        print("Refusing to run: mutation targets are not clean.", file=sys.stderr)
        print(dirty, file=sys.stderr)
        return 2

    for mutation in selected:
        if not (ROOT / mutation.test).is_file():
            print(f"Missing test file for {mutation.name}: {mutation.test}", file=sys.stderr)
            return 2

    results: list[Result] = []
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="mutation-check-") as temp_dir:
        backup_dir = Path(temp_dir)
        for index, mutation in enumerate(selected, start=1):
            print(f"[{index}/{len(selected)}] {mutation.name} ... ", end="", flush=True)
            target = ROOT / mutation.path
            original = target.read_bytes()
            backup = backup_dir / f"{index:02d}-{target.name}.bak"
            backup.write_bytes(original)
            text = original.decode("utf-8")
            old, new, occurrences = _match_snippet(text, mutation.old, mutation.new)

            if occurrences != 1:
                detail = f"expected one match in {mutation.path}, found {occurrences}"
                result = Result(mutation, "INVALID", 0.0, detail)
                results.append(result)
                print(f"INVALID ({detail})")
                continue

            mutation_started = time.perf_counter()
            status = "ERROR"
            detail = ""
            try:
                target.write_bytes(text.replace(old, new, 1).encode("utf-8"))
                killed, detail = _run_test(ROOT, mutation.test, args.timeout)
                status = "KILLED" if killed else "SURVIVED"
            finally:
                _restore(ROOT, mutation, backup, original)
            duration = time.perf_counter() - mutation_started
            results.append(Result(mutation, status, duration, detail))
            print(f"{status} ({duration:.2f}s)")

    total_duration = time.perf_counter() - started
    _print_table(results, total_duration)

    survivors = [result for result in results if result.status != "KILLED"]
    if survivors:
        print()
        for result in survivors:
            print(f"{result.status}: {result.mutation.name} ({result.mutation.test})")
            if result.detail:
                print(f"  {result.detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
