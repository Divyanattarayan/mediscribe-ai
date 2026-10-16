"""Retry policy for the shared Groq client.

Groq reports a per-minute limit and a daily quota with the same 429, and the
right response to each is the opposite of the other. Getting this wrong is not
cosmetic: every caller treats an exception as "the LLM failed" and silently
downgrades — to the rule-based note generator, or to the weaker lexical
groundedness check — so burning four retries on a quota that resets in hours
costs the user a worse note and tells nobody why.
"""

import pytest

import groq_client


class _FakeRateLimit(Exception):
    def __init__(self, message, status_code=429):
        super().__init__(message)
        self.status_code = status_code


PER_MINUTE = (
    "Error code: 429 - Rate limit reached for model `openai/gpt-oss-120b` on tokens "
    "per minute (TPM): Limit 8000, Used 3512, Requested 4518. "
    "Please try again in 224.999999ms."
)
PER_DAY = (
    "Error code: 429 - Rate limit reached for model `openai/gpt-oss-120b` on tokens "
    "per day (TPD): Limit 200000, Used 198760, Requested 2425. "
    "Please try again in 8m31.919999999s."
)


# ── Classification ────────────────────────────────────────────────────────────

def test_a_per_minute_limit_is_worth_waiting_out():
    assert groq_client._is_transient(_FakeRateLimit(PER_MINUTE)) is True


def test_a_daily_quota_is_not_retried():
    """It resets in hours. Retrying returns the same error more slowly."""
    assert groq_client._is_transient(_FakeRateLimit(PER_DAY)) is False


def test_a_long_requested_wait_is_not_retried_even_without_a_quota_marker():
    exc = _FakeRateLimit("Error code: 429 - slow down. Please try again in 12m0s.")
    assert groq_client._is_transient(exc) is False


def test_client_errors_are_not_retried():
    assert groq_client._is_transient(_FakeRateLimit("model_not_found", status_code=404)) is False
    assert groq_client._is_transient(_FakeRateLimit("bad request", status_code=400)) is False


def test_server_errors_and_timeouts_are_retried():
    assert groq_client._is_transient(_FakeRateLimit("bad gateway", status_code=502)) is True
    assert groq_client._is_transient(Exception("connection timeout")) is True


# ── The requested wait ────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("Please try again in 0.5s", 0.5),
    ("Please try again in 30s", 30.0),
    ("Please try again in 8m31.9s", 8 * 60.0),
    ("no wait mentioned", None),
])
def test_the_requested_wait_is_parsed(message, expected):
    assert groq_client._retry_after_seconds(_FakeRateLimit(message)) == expected


# ── Retry loop ────────────────────────────────────────────────────────────────

def _stub_client(monkeypatch, side_effects):
    """A client whose `create` walks through `side_effects`."""
    calls = []

    class _Completions:
        def create(self, **request):
            calls.append(request)
            effect = side_effects[len(calls) - 1]
            if isinstance(effect, Exception):
                raise effect
            return effect

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    monkeypatch.setattr(groq_client, "get_client", lambda: _Client())
    monkeypatch.setattr(groq_client.time, "sleep", lambda seconds: None)
    return calls


def test_a_transient_failure_is_retried_and_then_succeeds(monkeypatch):
    calls = _stub_client(monkeypatch, [_FakeRateLimit(PER_MINUTE), "ok"])
    assert groq_client._call_with_retry({"model": "m"}) == "ok"
    assert len(calls) == 2


def test_a_daily_quota_fails_on_the_first_attempt(monkeypatch):
    """Four attempts against a daily cap wastes the user's time for nothing."""
    calls = _stub_client(monkeypatch, [_FakeRateLimit(PER_DAY)] * 4)
    with pytest.raises(Exception):
        groq_client._call_with_retry({"model": "m"})
    assert len(calls) == 1


def test_retries_are_bounded(monkeypatch):
    calls = _stub_client(monkeypatch, [_FakeRateLimit(PER_MINUTE)] * 10)
    with pytest.raises(Exception):
        groq_client._call_with_retry({"model": "m"})
    assert len(calls) == groq_client.GROQ_MAX_ATTEMPTS


def test_the_wait_honours_what_groq_asked_for(monkeypatch):
    """The doubling backoff is a guess; the server's own figure is not."""
    waits = []
    monkeypatch.setattr(groq_client.time, "sleep", waits.append)

    class _Completions:
        def __init__(self):
            self.calls = 0

        def create(self, **request):
            self.calls += 1
            if self.calls == 1:
                raise _FakeRateLimit("429 rate limit. Please try again in 12s.")
            return "ok"

    completions = _Completions()
    monkeypatch.setattr(groq_client, "get_client", lambda: type(
        "C", (), {"chat": type("Ch", (), {"completions": completions})()}
    )())

    assert groq_client._call_with_retry({"model": "m"}) == "ok"
    assert waits == [12.0]      # not the 1s the backoff would have chosen


# ── Token accounting ──────────────────────────────────────────────────────────

class _Usage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _Response:
    def __init__(self, usage=None):
        self.usage = usage
        message = type("M", (), {"content": '{"ok": true}'})()
        self.choices = [type("C", (), {"message": message})()]


def test_usage_accumulates_across_calls(monkeypatch):
    """The pipeline makes several calls per note; the cost that matters is the
    total for the request, not for one call."""
    groq_client.reset_usage()
    _stub_client(monkeypatch, [_Response(_Usage(100, 50)), _Response(_Usage(200, 25))])

    for _ in range(2):
        groq_client.chat_json("sys", "user", max_tokens=10, temperature=0)

    usage = groq_client.usage_snapshot()
    assert usage == {"calls": 2, "prompt_tokens": 300, "completion_tokens": 75, "total_tokens": 375}


def test_a_response_without_usage_still_counts_the_call(monkeypatch):
    groq_client.reset_usage()
    _stub_client(monkeypatch, [_Response(usage=None)])
    groq_client.chat_json("sys", "user", max_tokens=10, temperature=0)
    assert groq_client.usage_snapshot()["calls"] == 1


def test_reset_clears_the_counters(monkeypatch):
    groq_client.reset_usage()
    _stub_client(monkeypatch, [_Response(_Usage(10, 5))])
    groq_client.chat_json("sys", "user", max_tokens=10, temperature=0)
    groq_client.reset_usage()
    assert groq_client.usage_snapshot()["total_tokens"] == 0


# ── Provider selection ────────────────────────────────────────────────────────
#
# The judge is separable from the pipeline so that evaluation stops being
# self-assessment and stops competing for the same daily quota. These cover the
# ways that separation can go wrong quietly.

def _stub_provider_client(monkeypatch, captured):
    """Replace client construction, so no provider key is needed."""
    class _Completions:
        def create(self, **request):
            captured.append(request)
            return _Response(_Usage(3, 2))

    monkeypatch.setattr(groq_client, "get_client_for", lambda provider: type(
        "C", (), {"chat": type("Ch", (), {"completions": _Completions()})()}
    )())


def test_an_unknown_role_is_rejected_rather_than_guessed():
    with pytest.raises(ValueError, match="Unknown model role"):
        groq_client.resolve_role("reviewer")


def test_an_unknown_provider_is_rejected(monkeypatch):
    """A typo in EVAL_JUDGE_PROVIDER must not fall back to the pipeline model,
    which would silently make evaluation self-assessment again."""
    monkeypatch.setitem(groq_client.ROLES, "judge", ("gemeni", "some-model"))
    with pytest.raises(ValueError, match="Unknown provider"):
        groq_client.resolve_role("judge")


def test_a_dropped_connection_is_worth_retrying():
    """It carries no status code and its message is only "Connection error.",
    so neither the status check nor the text markers saw it — and a 90-item
    judge prompt lost its entire metric to one bad socket."""
    connection_error = type("APIConnectionError", (Exception,), {})("Connection error.")
    assert groq_client._is_transient(connection_error) is True


def test_gemini_phrasing_of_the_retry_wait_is_understood():
    """Groq says "try again in 224.999999ms", Gemini says "Please retry in
    51.170797517s". Matching only the first meant Gemini's stated wait was
    ignored and the backoff tried 1s, 2s, 4s against a server asking for 51."""
    assert groq_client._retry_after_seconds(Exception("Please retry in 51.170797517s.")) == 51.170797517
    assert groq_client._retry_after_seconds(Exception("try again in 224.999999ms")) == 0.224999999


def test_calls_to_a_paced_provider_are_spaced(monkeypatch):
    """Earning a 429 costs a round trip, and on a per-minute quota the retries
    land inside the window that just refused the call. Spacing avoids both."""
    slept = []
    monkeypatch.setattr(groq_client.time, "sleep", slept.append)
    monkeypatch.setitem(groq_client.DEFAULT_MIN_INTERVAL_SECONDS, "gemini", 12.5)
    monkeypatch.delenv("GEMINI_MIN_REQUEST_INTERVAL", raising=False)
    groq_client._last_call_at.clear()

    provider = groq_client.PROVIDERS["gemini"]
    groq_client._pace(provider)   # first call is due immediately
    groq_client._pace(provider)   # second must wait out the interval

    # Exactly one wait: the first call finds nothing owed, the second does.
    assert len(slept) == 1
    assert 0 < slept[0] <= 12.5


def test_an_unpaced_provider_does_not_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(groq_client.time, "sleep", slept.append)
    groq_client._last_call_at.clear()
    groq_client._pace(groq_client.PROVIDERS["groq"])
    groq_client._pace(groq_client.PROVIDERS["groq"])
    assert slept == []


def test_a_judge_on_another_provider_needs_its_own_model(monkeypatch):
    """A model name does not carry across providers: handing Gemini the
    pipeline's `openai/gpt-oss-120b` is a 404. Inheriting it would turn a
    missing setting into a confusing runtime failure instead of a clear one."""
    monkeypatch.setitem(groq_client.ROLES, "judge", ("gemini", ""))
    with pytest.raises(ValueError, match="EVAL_JUDGE_MODEL"):
        groq_client.resolve_role("judge")


def test_the_judge_still_inherits_within_one_provider(monkeypatch):
    """Same provider, no explicit model: inheriting is meaningful, and keeps an
    unconfigured checkout behaving as it did before providers were separable."""
    monkeypatch.setattr(groq_client, "PIPELINE_PROVIDER", "groq")
    monkeypatch.setattr(groq_client, "JUDGE_PROVIDER", "groq")
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)
    assert groq_client._judge_model() == groq_client.GROQ_MODEL


def test_reasoning_effort_is_not_sent_where_unsupported(monkeypatch):
    """An endpoint that does not know `reasoning_effort` returns 400 rather than
    ignoring it, which would make every call fail for a reason nothing names."""
    captured = []
    _stub_provider_client(monkeypatch, captured)
    monkeypatch.setattr(groq_client, "GROQ_REASONING_EFFORT", "low")
    monkeypatch.setitem(groq_client.ROLES, "judge", ("cerebras", "some-model"))

    groq_client.chat_json("sys", "user", max_tokens=10, temperature=0, role="judge")
    assert "reasoning_effort" not in captured[0]
    assert captured[0]["model"] == "some-model"


def test_reasoning_effort_is_sent_to_gemini(monkeypatch):
    """Gemini does take it, and capping the thinking is what stops it eating the
    `max_tokens` budget a long judge reply needs."""
    captured = []
    _stub_provider_client(monkeypatch, captured)
    monkeypatch.setattr(groq_client, "GROQ_REASONING_EFFORT", "low")
    monkeypatch.setitem(groq_client.ROLES, "judge", ("gemini", "gemini-3.6-flash"))

    groq_client.chat_json("sys", "user", max_tokens=10, temperature=0, role="judge")
    assert captured[0]["reasoning_effort"] == "low"


def test_reasoning_effort_is_still_sent_to_groq(monkeypatch):
    captured = []
    _stub_provider_client(monkeypatch, captured)
    monkeypatch.setattr(groq_client, "GROQ_REASONING_EFFORT", "low")
    monkeypatch.setitem(groq_client.ROLES, "pipeline", ("groq", "openai/gpt-oss-120b"))

    groq_client.chat_json("sys", "user", max_tokens=10, temperature=0, role="pipeline")
    assert captured[0]["reasoning_effort"] == "low"


def test_usage_is_split_by_provider(monkeypatch):
    """One combined total cannot answer which daily quota is about to run out,
    which is the question the counter exists to answer."""
    captured = []
    _stub_provider_client(monkeypatch, captured)
    monkeypatch.setitem(groq_client.ROLES, "pipeline", ("groq", "pipeline-model"))
    monkeypatch.setitem(groq_client.ROLES, "judge", ("gemini", "judge-model"))
    groq_client.reset_usage()

    groq_client.chat_json("sys", "user", max_tokens=10, temperature=0, role="pipeline")
    groq_client.chat_json("sys", "user", max_tokens=10, temperature=0, role="judge")
    groq_client.chat_json("sys", "user", max_tokens=10, temperature=0, role="judge")

    by_provider = groq_client.usage_by_provider()
    assert by_provider["groq"]["calls"] == 1
    assert by_provider["gemini"]["calls"] == 2
    assert by_provider["gemini"]["total_tokens"] == 10
    # The combined total still covers every provider.
    assert groq_client.usage_snapshot()["calls"] == 3


def test_a_missing_provider_key_names_the_variable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="GEMINI_API_KEY"):
        groq_client.get_client_for(groq_client.PROVIDERS["gemini"])
