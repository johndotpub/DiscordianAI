#!/usr/bin/env python3
"""Probe the live OpenAI and Perplexity contracts. Prints shapes, never secrets.

Run:  set -a && . ~/.config/environment.d/hermes.conf && set +a
      .venv/bin/python scripts/probe_providers.py
"""
import json
import os
import sys

import httpx

SHAPE = lambda d, depth=0: sorted(d.keys()) if isinstance(d, dict) else type(d).__name__


def show(label, resp):
    print(f"\n--- {label} ---")
    print("status:", resp.status_code)
    interesting = [h for h in resp.headers if h.lower().startswith(("retry-after", "x-ratelimit", "x-request", "x-pplx"))]
    for h in interesting:
        print(f"  header {h}: {resp.headers[h]}")
    try:
        body = resp.json()
    except Exception:
        print("  body: <non-json>", resp.text[:200])
        return None
    if resp.status_code >= 400:
        print("  error keys:", SHAPE(body))
        err = body.get("error", body)
        if isinstance(err, dict):
            print("  error.type:", err.get("type"))
            print("  error.code:", err.get("code"))
            print("  error.message:", str(err.get("message"))[:160])
        return body
    print("  top-level keys:", SHAPE(body))
    if "usage" in body and isinstance(body["usage"], dict):
        usage = body["usage"]
        print("  usage keys:", SHAPE(usage))
        usage_keys = (
            "prompt_tokens",
            "completion_tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost",
        )
        print("  usage:", {k: usage[k] for k in usage_keys if k in usage})
    if isinstance(body.get("output"), list):
        print("  output item types:", [item.get("type") for item in body["output"] if isinstance(item, dict)])
        for item in body["output"]:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "search_results":
                results = item.get("results") or []
                print("    search_results count:", len(results))
                if results and isinstance(results[0], dict):
                    print("    search_results[0] keys:", SHAPE(results[0]))
                    print("    search_results[0].id:", results[0].get("id"))
            elif item.get("type") == "message":
                content = item.get("content") or []
                print("    message content types:", [part.get("type") for part in content if isinstance(part, dict)])
                text = next((part.get("text") for part in content if isinstance(part, dict) and part.get("type") == "output_text"), None)
                print("    output_text preview:", repr(str(text)[:60]))
    for k in ("citations", "search_results", "related_questions"):
        if k in body:
            v = body[k]
            print(f"  {k}: {len(v) if isinstance(v, list) else v}")
            if isinstance(v, list) and v and isinstance(v[0], dict):
                print(f"    {k}[0] keys:", SHAPE(v[0]))
    if body.get("choices"):
        msg = body["choices"][0].get("message", {})
        print("  finish_reason:", body["choices"][0].get("finish_reason"))
        print("  message keys:", SHAPE(msg))
        print("  content preview:", repr(str(msg.get("content"))[:60]))
    return body


def main():
    oai = os.environ.get("OPENAI_API_KEY")
    pplx = os.environ.get("PERPLEXITY_API_KEY")
    if not oai or not pplx:
        sys.exit("missing OPENAI_API_KEY / PERPLEXITY_API_KEY in env")

    cheap = {
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 16,
    }

    with httpx.Client(timeout=60) as c:
        # 1. OpenAI chat completions, current Bender model
        r = c.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {oai}"},
            json={"model": "gpt-5", "messages": cheap["messages"], "max_completion_tokens": 16},
        )
        show("openai /chat/completions gpt-5", r)

        # 2. OpenAI with a current-generation model, to test the allowlist assumption
        r = c.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {oai}"},
            json={"model": "gpt-5.4", "messages": cheap["messages"], "max_completion_tokens": 16},
        )
        show("openai gpt-5.4 (newer generation)", r)

        # 3. OpenAI context-length error shape: force it with an absurd token floor
        r = c.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {oai}"},
            json={"model": "gpt-5", "messages": cheap["messages"], "max_completion_tokens": 200000},
        )
        show("openai oversized max_completion_tokens", r)

        # 4. Perplexity, the path the SDK actually calls, with the #256 header
        r = c.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {pplx}",
                "X-Pplx-Integration": "discordian-ai",
            },
            json={"model": "sonar-pro", "max_tokens": 16, **cheap},
        )
        show("perplexity /chat/completions sonar-pro + integration header", r)

        # 5. Perplexity canonical path from the current spec
        r = c.post(
            "https://api.perplexity.ai/v1/sonar",
            headers={"Authorization": f"Bearer {pplx}"},
            json={"model": "sonar-pro", "max_tokens": 16, **cheap},
        )
        show("perplexity /v1/sonar (spec canonical path)", r)

        # 6. Perplexity validation error shape: bogus model
        r = c.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {pplx}"},
            json={"model": "sonar-pro-typo", "max_tokens": 16, **cheap},
        )
        show("perplexity bogus model (validation error shape)", r)

        # 7. Does Perplexity accept reasoning_effort values outside its enum?
        r = c.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {pplx}"},
            json={"model": "sonar-pro", "max_tokens": 16, "reasoning_effort": "xhigh", **cheap},
        )
        show("perplexity reasoning_effort=xhigh (outside documented enum)", r)

        pplx_headers = {
            "Authorization": f"Bearer {pplx}",
            "X-Pplx-Integration": "discordian-ai",
        }
        agent_request = {
            "model": "perplexity/sonar",
            "instructions": "Answer in one sentence and cite sources.",
            "input": [{"role": "user", "content": "What was the top news headline today?"}],
            "max_output_tokens": 200,
            "tools": [{"type": "web_search"}],
        }

        # 8. Perplexity Agent API canonical path, with web search
        r = c.post(
            "https://api.perplexity.ai/v1/agent",
            headers=pplx_headers,
            json=agent_request,
        )
        show("perplexity /v1/agent perplexity/sonar + web_search", r)

        # 9. Agent API OpenAI-compatible alias, a query that needs no search
        r = c.post(
            "https://api.perplexity.ai/v1/responses",
            headers=pplx_headers,
            json={
                "model": "perplexity/sonar",
                "instructions": "Be brief.",
                "input": [{"role": "user", "content": "Reply with the single word: ok"}],
                "max_output_tokens": 16,
                "tools": [{"type": "web_search"}],
            },
        )
        show("perplexity /v1/responses no-search shape", r)

        # 10. The unversioned path the SDK would use without the /v1 base URL
        r = c.post(
            "https://api.perplexity.ai/responses",
            headers=pplx_headers,
            json=agent_request,
        )
        show("perplexity /responses unversioned path", r)

        # 11. Agent API validation error shape: bogus model
        r = c.post(
            "https://api.perplexity.ai/v1/agent",
            headers=pplx_headers,
            json={**agent_request, "model": "perplexity/typo"},
        )
        show("perplexity /v1/agent bogus model (validation error shape)", r)


if __name__ == "__main__":
    main()
