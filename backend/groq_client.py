"""One access point for every stage that calls a model.

This lived in `soap_generator` and was imported from there by
`clinical_extraction`, which made a generation module the de facto home for
shared infrastructure and meant a third caller would have deepened the tangle.
The behaviour is unchanged; only its address is.

Everything here exists because of a failure the eval harness caught:

* `GROQ_MODEL` is configurable because it was once hardcoded to a model Groq
  later decommissioned. Every call 404'd and the pipeline silently served the
  rule-based fallback for every note.
* `response_format=json_object` and a generous `max_tokens` are set because
  reasoning models spend budget before emitting output, so a small cap produced
  truncated JSON that callers read as "the LLM failed".
* Retries exist because a free-tier rate limit is a wait, not a failure, but
  callers treat any exception as a reason to downgrade the note.
"""

from __future__ import annotations

# Loaded here rather than left to the caller: this is the module that needs the
# key, and importing it from a script that had not already called load_dotenv
# produced a confusing "Missing API key" from a machine where the key was set.
from dotenv import load_dotenv

load_dotenv()

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from groq import Groq

try:  # Only needed for providers reached over the OpenAI-compatible protocol.
    from openai import OpenAI
except ImportError:  # pragma: no cover - Groq-only installs stay supported
    OpenAI = None  # type: ignore

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


# --- Providers --------------------------------------------------------------
#
# The pipeline model and the evaluation judge are separable, for two reasons.
# The second matters more than the first:
#
# 1. The Groq free tier is 200,000 tokens/day, and a four-case Phase 3 run can
#    exhaust it — this has blocked measurement twice. Pointing evaluation at a
#    second free tier lifts that ceiling without touching the pipeline.
# 2. Scoring a model's output with that same model is self-assessment. Whatever
#    blind spot produced a bad note is present in the grader that reads it, so
#    the agreement is inflated for reasons unrelated to note quality. Splitting
#    them is better evaluation practice whatever the quota situation.
#
# Every provider here except Groq speaks the OpenAI protocol, so adding one is a
# base URL and the name of its key variable.


@dataclass(frozen=True)
class Provider:
    name: str
    key_env: str
    # None means the native Groq SDK rather than an OpenAI-compatible endpoint.
    base_url: str | None = None
    # Whether `reasoning_effort` is accepted. Sending it where it is not is a
    # 400, not an ignored field, so this defaults to off and is turned on only
    # where a real call has confirmed it.
    reasoning_effort: bool = False


PROVIDERS: dict[str, Provider] = {
    "groq": Provider("groq", "GROQ_API_KEY", reasoning_effort=True),
    # Confirmed by measurement: on `gemini-3.6-flash`, effort "low" returned
    # byte-identical output for 390 total tokens against 702 without it — the
    # thinking is what the rest was. That matters beyond cost, because thinking
    # is charged against `max_tokens`: a 90-item coverage prompt spent 2,900 of
    # its 3,000 budget reasoning and returned 115 tokens of truncated JSON.
    # ("none" is rejected with a 400; "low" is the floor.)
    "gemini": Provider(
        "gemini", "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        reasoning_effort=True,
    ),
    "cerebras": Provider("cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1"),
}

# Which provider serves the pipeline. Left at Groq: every committed baseline in
# `eval/results/` was produced by `GROQ_MODEL` on Groq, and changing the
# generating model invalidates every before/after comparison in the roadmap.
# That is a deliberate re-baselining decision, not a default.
PIPELINE_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

# The judge falls back to the pipeline provider and model so that an
# unconfigured checkout behaves exactly as before. `scripts/check_model_access.py`
# reports when the two coincide, because that is the self-judging case above.
JUDGE_PROVIDER = os.getenv("EVAL_JUDGE_PROVIDER", "").strip() or PIPELINE_PROVIDER


def _judge_model() -> str:
    """The judge's model, or "" when the configuration does not determine one.

    Inheriting the pipeline's model is only meaningful when the judge is on the
    pipeline's provider. Across providers a model name does not carry over —
    handing Gemini `openai/gpt-oss-120b` is a 404 — so an unset
    `EVAL_JUDGE_MODEL` there is a misconfiguration, and `resolve_role` says so
    rather than inventing a name that cannot work.
    """
    explicit = os.getenv("EVAL_JUDGE_MODEL", "").strip()
    if explicit:
        return explicit
    return GROQ_MODEL if JUDGE_PROVIDER == PIPELINE_PROVIDER else ""


JUDGE_MODEL = _judge_model()

ROLES = {"pipeline": (PIPELINE_PROVIDER, GROQ_MODEL), "judge": (JUDGE_PROVIDER, JUDGE_MODEL)}


def resolve_role(role: str) -> tuple[Provider, str]:
    """The provider and model serving a role. Unknown names fail loudly.

    Failing loudly is the point: a model name that silently does not exist is
    exactly how this project once served its rule-based fallback for every note
    for an unknown period.
    """
    try:
        provider_name, model = ROLES[role]
    except KeyError:
        raise ValueError(f"Unknown model role {role!r}. Known roles: {', '.join(sorted(ROLES))}.")
    try:
        provider = PROVIDERS[provider_name]
    except KeyError:
        raise ValueError(
            f"Unknown provider {provider_name!r} for role {role!r}. "
            f"Known providers: {', '.join(sorted(PROVIDERS))}."
        )
    if not model:
        raise ValueError(
            f"No model configured for role {role!r} on provider {provider_name!r}. "
            f"Set EVAL_JUDGE_MODEL — a model name does not carry across providers, "
            f"so there is nothing sensible to inherit. "
            f"`python -m scripts.check_model_access --no-call` lists what "
            f"{provider_name!r} offers."
        )
    return provider, model

# Reasoning models accept this and answer faster with less reasoning overhead;
# models that do not accept it must have it unset.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low") or None

GROQ_MAX_ATTEMPTS = int(os.getenv("GROQ_MAX_ATTEMPTS", "4"))

# Token accounting. The pipeline makes several calls per note, and on a free
# tier the daily quota is the binding constraint on how much can be evaluated —
# a run of four cases exhausted 200,000 tokens before this was visible. Counting
# them makes the cost of a pipeline change something that can be seen rather
# than inferred from a 429.
_usage_lock = threading.Lock()
USAGE: dict[str, int] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

# The same totals split by provider. Once two providers are in play the combined
# figure cannot answer the question the counter exists for — which daily quota is
# about to run out — because each provider has its own ceiling.
USAGE_BY_PROVIDER: dict[str, dict[str, int]] = {}


def reset_usage() -> None:
    with _usage_lock:
        for key in USAGE:
            USAGE[key] = 0
        USAGE_BY_PROVIDER.clear()


def usage_snapshot() -> dict[str, int]:
    with _usage_lock:
        return dict(USAGE)


def usage_by_provider() -> dict[str, dict[str, int]]:
    with _usage_lock:
        return {name: dict(counts) for name, counts in USAGE_BY_PROVIDER.items()}


def _record_usage(response, provider: str = "groq") -> None:
    usage = getattr(response, "usage", None)
    with _usage_lock:
        per_provider = USAGE_BY_PROVIDER.setdefault(
            provider,
            {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "max_prompt_tokens": 0},
        )
        USAGE["calls"] += 1
        per_provider["calls"] += 1
        if usage is None:
            return
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = int(getattr(usage, field, 0) or 0)
            USAGE[field] += value
            per_provider[field] += value

        # The largest single prompt, not the average, is what decides whether a
        # provider is usable: a context limit is per call. Cerebras' free tier
        # caps at 8K, and 26,287 tokens spread over six calls says nothing about
        # whether the biggest one fits.
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        per_provider["max_prompt_tokens"] = max(per_provider["max_prompt_tokens"], prompt)


def get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Missing API key. Set GROQ_API_KEY in your environment or .env file."
        )
    return Groq(api_key=api_key)


def get_client_for(provider: Provider) -> Any:
    """A client for one provider.

    Groq keeps going through `get_client` rather than the OpenAI-compatible
    path, so the native SDK's error types — which the retry classification below
    reads — stay unchanged for the provider that path was tuned against.
    """
    if provider.base_url is None:
        return get_client()

    api_key = os.getenv(provider.key_env)
    if not api_key:
        raise EnvironmentError(
            f"Missing API key for provider {provider.name!r}. "
            f"Set {provider.key_env} in your environment or .env file."
        )
    if OpenAI is None:
        raise EnvironmentError(
            f"Provider {provider.name!r} needs the `openai` package, which is not installed."
        )
    return OpenAI(api_key=api_key, base_url=provider.base_url)


# Groq reports per-minute and per-day limits with the same 429, and they need
# opposite handling. A per-minute limit clears in seconds and is worth waiting
# out; a daily quota needs hours, so retrying it only burns the backoff and
# returns the same error more slowly — while the caller, seeing an exception,
# quietly downgrades the note.
# `ms` must be matched before `m`, or "224.999999ms" reads as 224 minutes and a
# routine per-minute limit is misclassified as one too long to wait for.
# Providers phrase this differently — Groq says "try again in 224.999999ms",
# Gemini says "Please retry in 51.170797517s". Matching only the first meant
# Gemini's stated wait was silently ignored and the doubling backoff tried
# 1s, 2s, 4s against a server asking for 51.
_RETRY_AFTER = re.compile(r"(?:try again|retry) in ([\d.]+)\s*(ms|m|s)", re.IGNORECASE)
_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0}
# `per[\s-]?day` also catches the quota identifiers other providers use, such as
# Gemini's `GenerateRequestsPerDayPerProjectPerModel`. This classification was
# tuned against Groq's message shapes, so on another provider treat a
# misclassification as expected rather than surprising: the cost is either four
# pointless retries or an early, clearly-reported failure, never a wrong answer.
_DAILY_QUOTA = re.compile(r"per[\s-]?day|\bTPD\b|\bRPD\b", re.IGNORECASE)

# The longest wait worth sitting through inside a request. A clinician waiting
# on a note will not sit through a minute of backoff; an evaluation run happily
# will, and should raise this rather than lose cases to a per-minute limit.
MAX_RETRY_WAIT_SECONDS = float(os.getenv("GROQ_MAX_RETRY_WAIT", "30"))


# --- Pacing -----------------------------------------------------------------
#
# Reacting to a 429 is strictly worse than not earning one: each refusal costs a
# round trip and, on a per-minute quota, the retries land inside the same window
# that just rejected the call. So calls are spaced instead.
#
# The interval below is measured rather than assumed. `gemini-3.8-flash` on the
# free tier refused the sixth request in a minute with
# `GenerateRequestsPerMinutePerProjectPerModel-FreeTier`, quotaValue 5 — which
# is 12 seconds a call, not the 15 requests/minute the public write-ups claim.
# Anything on a paid tier should set the variable and turn this down.
DEFAULT_MIN_INTERVAL_SECONDS = {"gemini": 12.5}

_pace_lock = threading.Lock()
_last_call_at: dict[str, float] = {}


def _min_interval(provider: Provider) -> float:
    override = os.getenv(f"{provider.name.upper()}_MIN_REQUEST_INTERVAL", "").strip()
    if override:
        return float(override)
    return DEFAULT_MIN_INTERVAL_SECONDS.get(provider.name, 0.0)


def _pace(provider: Provider) -> None:
    """Block until this provider's next call is due. No-op where unthrottled."""
    interval = _min_interval(provider)
    if interval <= 0:
        return
    # The lock is held across the sleep on purpose: it is what serialises
    # concurrent callers into one queue rather than letting them all wake at
    # once and reproduce the burst the pacing exists to prevent.
    with _pace_lock:
        due = _last_call_at.get(provider.name, 0.0) + interval
        wait = due - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call_at[provider.name] = time.monotonic()


def _retry_after_seconds(exc: Exception) -> float | None:
    """The wait Groq asked for, in seconds, when it named one."""
    match = _RETRY_AFTER.search(str(exc))
    if not match:
        return None
    return float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]


def _is_transient(exc: Exception) -> bool:
    """Whether waiting could plausibly help.

    Rate limits, timeouts and 5xx are worth waiting out; a 400 or 404 is not.
    Neither is a daily quota, which is not transient on any timescale a request
    can sit through — failing fast lets the caller degrade with a clear reason
    instead of after four pointless retries.
    """
    if _DAILY_QUOTA.search(str(exc)):
        return False

    requested = _retry_after_seconds(exc)
    if requested is not None and requested > MAX_RETRY_WAIT_SECONDS:
        return False

    status = getattr(exc, "status_code", None)
    if status in (408, 409, 429, 500, 502, 503, 504):
        return True

    # A dropped connection carries no status code and its message is just
    # "Connection error.", so neither check above sees it and a large judge
    # prompt lost its whole metric to one bad socket. The SDKs name these by
    # class, which is the more reliable signal.
    if type(exc).__name__ in ("APIConnectionError", "APITimeoutError", "InternalServerError"):
        return True

    text = str(exc).lower()
    return any(marker in text for marker in (
        "rate_limit", "rate limit", "timeout", "temporarily unavailable", "connection error",
    ))


def _call_with_retry(request: dict, provider: Provider | None = None):
    provider = provider or PROVIDERS["groq"]
    delay = 1.0
    last_error: Exception | None = None

    for attempt in range(1, GROQ_MAX_ATTEMPTS + 1):
        try:
            _pace(provider)
            return get_client_for(provider).chat.completions.create(**request)
        except Exception as exc:
            last_error = exc
            if not _is_transient(exc) or attempt == GROQ_MAX_ATTEMPTS:
                if _DAILY_QUOTA.search(str(exc)):
                    print(f"{provider.name} daily token quota exhausted — not retrying.")
                raise
            # Honour the wait the provider named; the doubling backoff is only a
            # guess for when it does not.
            requested = _retry_after_seconds(exc)
            wait = max(delay, requested) if requested else delay
            print(f"{provider.name} call failed ({type(exc).__name__}), "
                  f"retry {attempt}/{GROQ_MAX_ATTEMPTS - 1} in {wait:.0f}s")
            time.sleep(wait)
            delay *= 2

    raise last_error  # pragma: no cover - loop always returns or raises


def chat_json(
    system_prompt: str,
    user_message: str,
    *,
    max_tokens: int,
    temperature: float,
    model: str | None = None,
    role: str = "pipeline",
) -> dict[str, Any]:
    """Call the model serving `role` and parse a JSON object out of the reply.

    `response_format=json_object` does the heavy lifting; the brace extraction
    is a belt-and-braces fallback for models that ignore it.

    `role` picks the provider and model — "pipeline" for note generation,
    "judge" for evaluation. An explicit `model` still overrides the role's
    model, but is sent to that role's provider.
    """
    provider, role_model = resolve_role(role)

    request: dict[str, Any] = {
        "model": model or role_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    # Sending this to an endpoint that does not know it is a 400, not a silently
    # ignored field, so it goes only to providers confirmed to take it.
    if GROQ_REASONING_EFFORT and provider.reasoning_effort:
        request["reasoning_effort"] = GROQ_REASONING_EFFORT

    response = _call_with_retry(request, provider)
    _record_usage(response, provider.name)
    raw = (response.choices[0].message.content or "").replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    return json.loads(match.group(0) if match else raw)
