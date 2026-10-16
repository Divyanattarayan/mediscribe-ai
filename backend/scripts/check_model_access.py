"""Check that the models the pipeline and the judge are configured to use exist.

This script exists because of a specific failure this project already had:
`GROQ_MODEL` was hardcoded to a model Groq later decommissioned, every call
404'd, and the pipeline quietly served its rule-based fallback for every note
for an unknown period. Nothing announced it. The same trap was still set in the
judge, whose model name defaulted to that same decommissioned model.

A configured model name is a claim about the world, and this verifies it before
an evaluation run depends on it:

    python -m scripts.check_model_access

It lists what each provider actually offers, which is also how to find the right
model id without trusting a blog post, and then makes one deliberately tiny call
per role so a wrong name fails here rather than four hours into a run.

The calls cost a handful of tokens each. Everything else is free.
"""

from __future__ import annotations

import argparse
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from console import configure_console  # noqa: E402
from groq_client import (  # noqa: E402
    PROVIDERS,
    ROLES,
    chat_json,
    get_client_for,
    resolve_role,
    usage_by_provider,
)


def list_models(provider_name: str, limit: int) -> list[str]:
    """Model ids a provider reports, or an empty list if it will not say."""
    provider = PROVIDERS[provider_name]
    try:
        response = get_client_for(provider).models.list()
    except Exception as exc:
        print(f"    could not list models: {type(exc).__name__}: {exc}")
        return []

    ids = sorted(str(getattr(model, "id", "")) for model in getattr(response, "data", []))
    return [model_id for model_id in ids if model_id][:limit]


def probe_role(role: str) -> bool:
    """One minimal call on the model serving `role`. True when it answered."""
    try:
        provider, model = resolve_role(role)
    except ValueError as exc:
        print(f"\n  role {role!r}: MISCONFIGURED — {exc}")
        return False
    print(f"\n  role {role!r}: provider={provider.name} model={model}")

    if not os.getenv(provider.key_env):
        print(f"    SKIP — {provider.key_env} is not set.")
        return False

    try:
        # A liveness check, not a capability test — but not as small as it looks
        # like it could be. Reasoning models spend the same `max_tokens` budget
        # on thinking before emitting anything, and how much varies per call: at
        # 64 this check intermittently got a truncated `{"` back from Gemini and
        # reported a live model as broken. The headroom is the point.
        reply = chat_json(
            'Reply with JSON only.',
            'Return {"ok": true}.',
            max_tokens=512,
            temperature=0.0,
            role=role,
        )
    except Exception as exc:
        print(f"    FAIL — {type(exc).__name__}: {exc}")
        return False

    print(f"    OK — replied {reply}")
    return True


def main() -> int:
    configure_console()

    parser = argparse.ArgumentParser(description="Verify configured models exist and answer")
    parser.add_argument("--list-limit", type=int, default=40,
                        help="most model ids to print per provider")
    parser.add_argument("--no-call", action="store_true",
                        help="list models only, spend no tokens")
    args = parser.parse_args()

    print("Configured roles:")
    for role, (provider_name, model) in ROLES.items():
        provider = PROVIDERS.get(provider_name)
        key_state = "set" if provider and os.getenv(provider.key_env) else "MISSING"
        key_name = provider.key_env if provider else "?"
        shown = model or "(NOT SET -- set EVAL_JUDGE_MODEL)"
        print(f"  {role:<10} provider={provider_name:<10} model={shown:<32} {key_name}={key_state}")

    # Judging a model's output with that same model inflates agreement for
    # reasons that have nothing to do with note quality. Worth saying out loud
    # rather than leaving to be noticed.
    if ROLES["pipeline"] == ROLES["judge"]:
        print("\n  NOTE: the judge and the pipeline are the same provider and model,")
        print("        so evaluation is currently self-assessment. Set EVAL_JUDGE_PROVIDER")
        print("        and EVAL_JUDGE_MODEL to separate them.")

    configured = {name for name, _ in ROLES.values()}
    for provider_name in sorted(configured):
        provider = PROVIDERS.get(provider_name)
        if provider is None:
            print(f"\nProvider {provider_name!r} is not known.")
            continue
        print(f"\nProvider {provider_name!r} ({provider.key_env}):")
        if not os.getenv(provider.key_env):
            print("    no key set, skipping")
            continue
        for model_id in list_models(provider_name, args.list_limit):
            print(f"    {model_id}")

    if args.no_call:
        return 0

    results = {role: probe_role(role) for role in ROLES}

    usage = usage_by_provider()
    if usage:
        print("\nTokens spent by this check:")
        for provider_name, counts in sorted(usage.items()):
            print(f"  {provider_name}: {counts['total_tokens']} tokens over {counts['calls']} calls")

    # A skipped role is not a failure: an unconfigured judge is a valid state.
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
