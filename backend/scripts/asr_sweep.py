"""Ablate the ASR decoding settings one change at a time.

Four things changed in `transcription.py` at once — the initial prompt, VAD,
`condition_on_previous_text`, and word timestamps — and a single combined run
cannot say which of them helped. The first one-channel check was already enough
to show why that matters: deletions fell *and* medical-term recall got worse, so
at least two effects were pulling in opposite directions.

Each variant runs in its own process because the decoding settings are read from
the environment at import time, and each is scored on the same channels so the
comparison is like-for-like.

    python -m scripts.asr_sweep --limit 6

Prints a table ordered by medical-term recall, which is the metric that tracks
whether a note can be written from the transcript at all.

`--models` reuses the same machinery to compare Whisper checkpoints rather than
decoding settings, holding every decoder setting at its shipping default so the
model is the only thing that varies:

    python -m scripts.asr_sweep --models base.en,distil-small.en,large-v3-turbo --limit 3

The table reports wall-clock time alongside accuracy, because the two trade off
against each other here and the same machine serves live transcription: a model
slower than realtime is unusable in the app whatever its error rate. Note that
running this downloads each checkpoint to the Hugging Face cache; the ones not
chosen are worth deleting afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BACKEND_DIR / "eval" / "results"

# A condition-neutral framing sentence. The hypothesis it tests: the old prompt
# may have helped by telling Whisper this is clinical speech, while hurting
# through the list of specific diagnoses bolted onto it.
GENERIC_PROMPT = "A clinical consultation between a doctor and a patient."

# The original prompt, kept verbatim as the control. Its disease list is the
# vocabulary of the two demo recordings the project was built around.
LEGACY_PROMPT = (
    "English clinical consultation between a medical student and a patient. "
    "Common terms include chest pain, breathlessness, palpitations, sore throat, "
    "heart attack, pericarditis, ECG, troponin, date of birth, diabetes, "
    "blood test, glucose, insulin, HbA1c, metformin, thrush, urinary tract "
    "infection, lifestyle, retinal screening, foot check, and GP surgery."
)

# The legacy prompt mixes two different things: generic consultation vocabulary
# ("date of birth", "blood test", "GP surgery") and a list of diagnoses from two
# specific recordings. The first sweep showed it beating a short generic
# framing, which does not distinguish between those. This keeps the generic
# clinical vocabulary and drops every condition name, so the two can be told
# apart.
RICH_GENERIC_PROMPT = (
    "English clinical consultation between a doctor and a patient. "
    "Common terms include date of birth, symptoms, examination, medication, "
    "dose, blood test, results, referral, follow-up, appointment, GP surgery, "
    "medical history, allergies, and lifestyle."
)

VARIANTS: dict[str, dict[str, str]] = {
    # The settings as they shipped before Phase 4, re-run here so the comparison
    # is against these exact channels rather than the 20-channel baseline.
    "a-legacy": {
        "WHISPER_INITIAL_PROMPT": LEGACY_PROMPT,
        "WHISPER_VAD_FILTER": "0",
        "WHISPER_CONDITION_ON_PREVIOUS": "1",
        "WHISPER_WORD_TIMESTAMPS": "0",
    },
    # Does removing the demo-specific prompt cost anything on its own?
    "b-no-prompt": {
        "WHISPER_INITIAL_PROMPT": "",
        "WHISPER_VAD_FILTER": "0",
        "WHISPER_CONDITION_ON_PREVIOUS": "1",
        "WHISPER_WORD_TIMESTAMPS": "0",
    },
    # Or was the value in the framing rather than the diagnoses?
    "c-generic-prompt": {
        "WHISPER_INITIAL_PROMPT": GENERIC_PROMPT,
        "WHISPER_VAD_FILTER": "0",
        "WHISPER_CONDITION_ON_PREVIOUS": "1",
        "WHISPER_WORD_TIMESTAMPS": "0",
    },
    "d-generic-vad": {
        "WHISPER_INITIAL_PROMPT": GENERIC_PROMPT,
        "WHISPER_VAD_FILTER": "1",
        "WHISPER_CONDITION_ON_PREVIOUS": "1",
        "WHISPER_WORD_TIMESTAMPS": "0",
    },
    "e-generic-vad-nocond": {
        "WHISPER_INITIAL_PROMPT": GENERIC_PROMPT,
        "WHISPER_VAD_FILTER": "1",
        "WHISPER_CONDITION_ON_PREVIOUS": "0",
        "WHISPER_WORD_TIMESTAMPS": "0",
    },
    # Is the legacy prompt's advantage its clinical vocabulary, or its diagnoses?
    "f-rich-generic-vad": {
        "WHISPER_INITIAL_PROMPT": RICH_GENERIC_PROMPT,
        "WHISPER_VAD_FILTER": "1",
        "WHISPER_CONDITION_ON_PREVIOUS": "1",
        "WHISPER_WORD_TIMESTAMPS": "0",
    },
    # The legacy prompt on equal terms with the others, to keep the comparison
    # about the prompt rather than about VAD.
    "g-legacy-vad": {
        "WHISPER_INITIAL_PROMPT": LEGACY_PROMPT,
        "WHISPER_VAD_FILTER": "1",
        "WHISPER_CONDITION_ON_PREVIOUS": "1",
        "WHISPER_WORD_TIMESTAMPS": "0",
    },
}

REPORTED = (
    "medical_term_recall",
    "medical_term_error_rate",
    "wer",
    "wer_fluent",
    "wer_deletions",
    "wer_substitutions",
    "wer_insertions",
)


def run_variant(name: str, overrides: dict[str, str], limit: int, offset: int = 0) -> dict | None:
    environment = {**os.environ, **overrides}
    environment.setdefault(
        "MEDISCRIBE_EVAL_DATA",
        os.getenv("MEDISCRIBE_EVAL_DATA", str(BACKEND_DIR / "eval" / "data")),
    )
    environment["PYTHONIOENCODING"] = "utf-8"

    label = f"asr-sweep-{name}"
    print(f"\n=== {name} ===", flush=True)
    completed = subprocess.run(
        [sys.executable, "-m", "eval", "run", "--suite", "primock57",
         "--stages", "asr", "--limit", str(limit), "--offset", str(offset),
         "--label", label],
        cwd=BACKEND_DIR, env=environment, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        print(f"  failed: {completed.stderr[-400:]}", flush=True)
        return None

    reports = sorted(RESULTS_DIR.glob(f"*{label}.json"))
    if not reports:
        print("  produced no report", flush=True)
        return None

    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    aggregate = report.get("aggregate", {})
    runtime = report.get("runtime_seconds")
    print(
        f"  medical_term_recall={aggregate.get('medical_term_recall', {}).get('mean')} "
        f"wer={aggregate.get('wer', {}).get('mean')} "
        f"runtime_seconds={runtime}",
        flush=True,
    )
    return {
        "name": name,
        "aggregate": aggregate,
        "runtime_seconds": runtime,
        "config": report.get("asr_config", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ablate ASR decoding settings")
    parser.add_argument("--limit", type=int, default=6, help="channels per variant")
    parser.add_argument("--only", default=None, help="comma-separated variant names")
    parser.add_argument(
        "--models", default=None,
        help="comma-separated Whisper model names to compare instead of decoding "
             "variants, e.g. base.en,distil-small.en,large-v3-turbo. Each runs on "
             "the shipping decoder configuration so only the model differs.",
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        help="skip the first N channels, to check a result on unseen audio",
    )
    parser.add_argument(
        "--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE",
        help="extra environment override applied to every variant, repeatable. "
             "Decoder settings tuned on one checkpoint do not necessarily hold "
             "on another, so this exists to vary them alongside the model.",
    )
    args = parser.parse_args()

    extra = {}
    for item in args.overrides:
        key, _, value = item.partition("=")
        if not key or not _:
            parser.error(f"--set expects KEY=VALUE, got {item!r}")
        extra[key.strip()] = value

    if args.models:
        # Only WHISPER_MODEL is overridden: every other decoder setting stays at
        # the shipping default, so the comparison isolates the model. Model names
        # go in the variant key so the result filenames stay readable.
        selected = {
            f"model-{name.strip()}": {"WHISPER_MODEL": name.strip()}
            for name in args.models.split(",") if name.strip()
        }
    elif args.only:
        selected = {k: v for k, v in VARIANTS.items() if k in set(args.only.split(","))}
    else:
        selected = VARIANTS

    if extra:
        # Applied last so an explicit --set wins over a variant's own value.
        suffix = "-" + "-".join(f"{k.split('_')[-1].lower()}{v}" for k, v in extra.items())
        selected = {name + suffix: {**overrides, **extra} for name, overrides in selected.items()}

    outcomes = [
        result for name, overrides in selected.items()
        if (result := run_variant(name, overrides, args.limit, args.offset)) is not None
    ]
    if not outcomes:
        print("no variant produced a report", file=sys.stderr)
        return 1

    header = (f"{'variant':<22}" + "".join(f"{metric[:16]:>18}" for metric in REPORTED)
              + f"{'runtime_s':>12}")
    print("\n" + header)
    print("-" * len(header))
    # Best medical-term recall first: it is the metric that decides whether the
    # transcript can support a note.
    for outcome in sorted(
        outcomes,
        key=lambda o: o["aggregate"].get("medical_term_recall", {}).get("mean", 0),
        reverse=True,
    ):
        row = f"{outcome['name']:<22}"
        for metric in REPORTED:
            value = outcome["aggregate"].get(metric, {}).get("mean")
            row += f"{value if value is not None else '-':>18}"
        # Wall clock matters as much as accuracy here: the same machine serves
        # live transcription, where a model slower than realtime is unusable.
        runtime = outcome.get("runtime_seconds")
        row += f"{runtime if runtime is not None else '-':>12}"
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
