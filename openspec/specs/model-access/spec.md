# Spec: model-access

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/groq_client.py, backend/main.py (reset_usage/usage_snapshot)
> Last verified: 2026-09-17 (commit 89807ef)

Scope: the single access point every stage uses to call a model — provider and
model resolution by role, retry classification, pacing, JSON extraction, and
per-request token accounting. Every behaviour here exists because of a failure
the evaluation harness caught.

---

### Requirement: A role resolves to exactly one provider and model, or fails loudly
<!-- id: groq_client.resolve_role -->
<!-- entities: Provider -->
<!-- enforced: groq_client.resolve_role() -->

`resolve_role` SHALL map `pipeline` and `judge` to a `(Provider, model)` pair
and SHALL raise `ValueError` for an unknown role, an unknown provider, or an
empty model name. Failing loudly is the point: a model name that silently does
not exist is how this project once served its rule-based fallback for every note
for an unknown period.

#### Scenario: an unknown role
<!-- test: tests/test_groq_client.py::test_an_unknown_role_is_rejected_rather_than_guessed -->
- **WHEN** a role name outside `ROLES` is passed
- **THEN** `ValueError` names the known roles

#### Scenario: an unknown provider
<!-- test: tests/test_groq_client.py::test_an_unknown_provider_is_rejected -->
- **WHEN** a role maps to a provider outside `PROVIDERS`
- **THEN** `ValueError` names the known providers

#### Scenario: a cross-provider judge with no model
<!-- test: tests/test_groq_client.py::test_a_judge_on_another_provider_needs_its_own_model -->
- **WHEN** `EVAL_JUDGE_PROVIDER` differs from the pipeline provider and
  `EVAL_JUDGE_MODEL` is unset
- **THEN** `ValueError` says the model must be set, because a model name does
  not carry across providers and there is nothing sensible to inherit

#### Scenario: a judge on the pipeline's own provider
<!-- test: tests/test_groq_client.py::test_the_judge_still_inherits_within_one_provider -->
- **WHEN** the judge provider equals the pipeline provider
- **THEN** the judge inherits `GROQ_MODEL`, so an unconfigured checkout behaves
  exactly as before

---

### Requirement: Transient failures are retried; permanent ones are not
<!-- id: groq_client._is_transient -->
<!-- entities: Provider -->
<!-- enforced: groq_client._is_transient(), groq_client._call_with_retry() -->

`_is_transient` SHALL return True for 408/409/429/500/502/503/504, for
`APIConnectionError` / `APITimeoutError` / `InternalServerError` by class name,
and for rate-limit, timeout, "temporarily unavailable" and "connection error"
message markers. It SHALL return False for a daily quota (`per day`, `TPD`,
`RPD`) and for a provider-requested wait longer than `MAX_RETRY_WAIT_SECONDS`
(default 30). Retries are bounded by `GROQ_MAX_ATTEMPTS` (default 4).

#### Scenario: a per-minute rate limit
<!-- test: tests/test_groq_client.py::test_a_per_minute_limit_is_worth_waiting_out -->
- **WHEN** a 429 names a sub-minute wait
- **THEN** the call is retried

#### Scenario: a daily quota
<!-- test: tests/test_groq_client.py::test_a_daily_quota_is_not_retried -->
- **WHEN** the error text matches the daily-quota pattern
- **THEN** the call fails on the first attempt with the quota reported, rather
  than burning four backoffs to return the same error more slowly

#### Scenario: a long requested wait
<!-- test: tests/test_groq_client.py::test_a_long_requested_wait_is_not_retried_even_without_a_quota_marker -->
- **WHEN** the provider asks for longer than the maximum retry wait
- **THEN** the call is not retried, even with no quota marker present

#### Scenario: a client error
<!-- test: tests/test_groq_client.py::test_client_errors_are_not_retried -->
- **WHEN** a 400 or 404 is raised
- **THEN** no retry occurs — waiting cannot help

#### Scenario: a dropped connection
<!-- test: tests/test_groq_client.py::test_a_dropped_connection_is_worth_retrying -->
- **WHEN** the SDK raises `APIConnectionError` with no status code and the
  message "Connection error."
- **THEN** it is classified transient by class name

#### Scenario: retries are bounded
<!-- test: tests/test_groq_client.py::test_retries_are_bounded -->
- **WHEN** every attempt fails transiently
- **THEN** the last error is raised after `GROQ_MAX_ATTEMPTS` attempts

---

### Requirement: The provider's stated wait is honoured over the backoff guess
<!-- id: groq_client._retry_after_seconds -->
<!-- entities: Provider -->
<!-- enforced: groq_client._retry_after_seconds(), groq_client._RETRY_AFTER -->

The retry-after regex SHALL match both "try again in" and "retry in", and SHALL
match the `ms` unit before `m`, or "224.999999ms" reads as 224 minutes and a
routine per-minute limit is misclassified. The actual wait SHALL be
`max(doubling_delay, requested)`.

#### Scenario: Groq's phrasing
<!-- test: tests/test_groq_client.py::test_the_requested_wait_is_parsed -->
- **WHEN** the message says "try again in 224.999999ms"
- **THEN** 0.225 seconds is parsed, not 224 minutes

#### Scenario: Gemini's phrasing
<!-- test: tests/test_groq_client.py::test_gemini_phrasing_of_the_retry_wait_is_understood -->
- **WHEN** the message says "Please retry in 51.170797517s"
- **THEN** ~51 seconds is parsed rather than silently ignored in favour of a 1s
  doubling backoff

#### Scenario: the wait is respected
<!-- test: tests/test_groq_client.py::test_the_wait_honours_what_groq_asked_for -->
- **WHEN** the provider names a wait longer than the current backoff
- **THEN** the longer wait is slept

---

### Requirement: Calls to a rate-limited provider are paced, not merely retried
<!-- id: groq_client._pace -->
<!-- entities: Provider -->
<!-- enforced: groq_client._pace(), groq_client._min_interval() -->

Calls SHALL be spaced by a per-provider minimum interval, defaulting to 12.5s
for Gemini (measured: the free tier refused the sixth request in a minute,
quotaValue 5) and 0 elsewhere, overridable via
`{PROVIDER}_MIN_REQUEST_INTERVAL`. The pacing lock SHALL be held across the
sleep, which is what serialises concurrent callers into a queue rather than
letting them all wake at once and reproduce the burst pacing exists to prevent.

#### Scenario: a paced provider
<!-- test: tests/test_groq_client.py::test_calls_to_a_paced_provider_are_spaced -->
- **WHEN** two calls are made to Gemini in quick succession
- **THEN** the second blocks until the interval has elapsed

#### Scenario: an unpaced provider
<!-- test: tests/test_groq_client.py::test_an_unpaced_provider_does_not_sleep -->
- **WHEN** the provider has no configured interval
- **THEN** `_pace` is a no-op

---

### Requirement: Requests are shaped for the provider that receives them
<!-- id: groq_client.chat_json -->
<!-- entities: Provider -->
<!-- enforced: groq_client.chat_json() -->
<!-- depends_on: A role resolves to exactly one provider and model, or fails loudly -->

`chat_json` SHALL send `response_format={"type": "json_object"}` and an explicit
`max_tokens`, and SHALL include `reasoning_effort` only for providers whose
`Provider.reasoning_effort` flag is set — sending it elsewhere is a 400, not an
ignored field. The reply SHALL be stripped of code fences and parsed by
extracting the outermost brace-delimited object as a fallback for models that
ignore `json_object`.

#### Scenario: a provider that does not accept reasoning effort
<!-- test: tests/test_groq_client.py::test_reasoning_effort_is_not_sent_where_unsupported -->
- **WHEN** the resolved provider has `reasoning_effort=False` (Cerebras)
- **THEN** the field is omitted from the request

#### Scenario: providers that do accept it
<!-- test: tests/test_groq_client.py::test_reasoning_effort_is_sent_to_gemini, tests/test_groq_client.py::test_reasoning_effort_is_still_sent_to_groq -->
- **WHEN** the provider is Groq or Gemini and `GROQ_REASONING_EFFORT` is set
- **THEN** the field is included

#### Scenario: a transient failure that then succeeds
<!-- test: tests/test_groq_client.py::test_a_transient_failure_is_retried_and_then_succeeds -->
- **WHEN** the first attempt raises transiently and the second returns
- **THEN** the parsed JSON is returned

---

### Requirement: Token usage is accounted per request and per provider
<!-- id: groq_client._record_usage -->
<!-- entities: Provider, Transcription -->
<!-- enforced: groq_client._record_usage(), groq_client.reset_usage(), groq_client.usage_snapshot(), groq_client.usage_by_provider() -->

Every call SHALL increment `calls` even when the response carries no usage
object, and SHALL accumulate prompt, completion and total tokens both globally
and per provider. Per provider the system SHALL also track
`max_prompt_tokens` — the largest single prompt, because a context limit is per
call and a total spread over six calls says nothing about whether the biggest
one fits. `POST /api/transcribe` SHALL call `reset_usage()` before the pipeline
and return `usage_snapshot()` in the response.

#### Scenario: usage accumulates
<!-- test: tests/test_groq_client.py::test_usage_accumulates_across_calls -->
- **WHEN** several calls are made
- **THEN** the counters sum across them

#### Scenario: a response without usage
<!-- test: tests/test_groq_client.py::test_a_response_without_usage_still_counts_the_call -->
- **WHEN** the provider omits the usage object
- **THEN** `calls` still increments and token counts are unchanged

#### Scenario: per-provider split
<!-- test: tests/test_groq_client.py::test_usage_is_split_by_provider -->
- **WHEN** two providers are used in one process
- **THEN** each has its own counters, because each has its own daily ceiling

#### Scenario: reset
<!-- test: tests/test_groq_client.py::test_reset_clears_the_counters -->
- **WHEN** `reset_usage()` is called
- **THEN** global counters are zeroed and the per-provider map is cleared

---

### Requirement: A missing API key names the variable to set
<!-- id: groq_client.get_client_for -->
<!-- entities: Provider -->
<!-- enforced: groq_client.get_client(), groq_client.get_client_for() -->

An absent key SHALL raise `EnvironmentError` naming the provider and its
`key_env` variable. A provider needing the `openai` package when it is not
installed SHALL likewise say so.

#### Scenario: a provider key is unset
<!-- test: tests/test_groq_client.py::test_a_missing_provider_key_names_the_variable -->
- **WHEN** the provider's key environment variable is missing
- **THEN** the error message names that exact variable

---

### Invariant: groq_client is the single model access point
<!-- entities: Provider -->
<!-- enforced: groq_client.chat_json() -->

Every stage that calls a model — fact extraction, clinical extraction, SOAP
generation, section regeneration, claim verification, the eval judge and the
coverage metric — SHALL go through `chat_json`. This module previously lived
inside `soap_generator`, making a generation module the de facto home for shared
infrastructure.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Groq keeps the native SDK path
<!-- entities: Provider -->
<!-- enforced: groq_client.get_client_for() -->

Providers with `base_url=None` SHALL use the native Groq SDK rather than the
OpenAI-compatible client, so the SDK error types the retry classification reads
stay unchanged for the provider that classification was tuned against.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: The pipeline provider stays Groq until deliberately re-baselined
<!-- entities: Provider -->
<!-- enforced: groq_client.PIPELINE_PROVIDER, groq_client.GROQ_MODEL -->

Every committed report in `backend/eval/results/` was produced by `GROQ_MODEL`
on Groq. Changing the generating model invalidates every before/after comparison
in `context/MODEL_ROADMAP.md`, so a change is a re-baselining decision, not a
default.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: The retry and daily-quota classification was tuned against Groq's message shapes. The module header states that on another provider a misclassification is expected rather than surprising — the cost is either four pointless retries or an early clearly-reported failure. No requirement asserts correct classification off Groq. -->
