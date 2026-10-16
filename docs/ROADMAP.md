# MediScribe AI — Development Roadmap

Backend rebuild around self-trained models, interleaved with the product track
from `.claude/prds/trustworthy-soap-notes.prd.md`. Competitive rationale in
`.reports/market-research.md`.

## Constraints that shape every step

- **Compute: free Colab/Kaggle only.** T4/P100, session limits, disconnects.
  LoRA/QLoRA and small models only. Every training step must checkpoint to Drive
  and be resumable from a cold session.
- **Disk must be reclaimed.** PriMock57 is ~1.9 GB. Download outside the
  OneDrive-synced tree, use, then delete. `eval/data/` is currently empty.
- **Kept, not rewritten**: the evaluation harness (`backend/eval/`, 55 committed
  baselines, 5 dataset adapters, 5 metric modules), the 12 capability specs in
  `openspec/specs/`, and the Alembic schema. Quality improvement has to be
  provable against existing baselines, or two of the three stated goals fail.
- **Rewritten**: the pipeline modules, behind a model-serving boundary, one
  model at a time. A big-bang rewrite with no measurement is the failure mode
  the harness exists to prevent.

## Track shape

Steps 1-4 are the product track and need no new model. Step 5 is the backbone of
the rewrite. Steps 6-9 are the ML track. Step 10 converts the whole thing into
evidence. Core vs stretch is marked per step.

---

## Step 1. Re-establish the measurement baseline

**Core.** Nothing after this is provable without it.

Re-download the evaluation datasets, re-run the current pipeline across the
existing suites, and record fresh baselines on today's code. The 55 committed
reports were produced against an older configuration; the overhaul needs a
current floor to beat. Reclaim the dataset disk afterwards.

Acceptance: a dated baseline report exists for the current system on at least
the ASR and note suites; dataset directories are removed after the run; the
run's model and configuration are recorded in the report.

Out of scope: changing any pipeline behaviour.

---

## Step 2. Close the fact-to-note loop (omission detection)

**Core. The competitive wedge.**

Verify each assertable fact-table row against the generated note and return the
facts that did not reach it. This is the published recovery method for omission
blindness, and both halves already exist: `clinical_facts.py` builds the
enumeration with evidence spans, `claim_verification.py` runs per-claim verdicts
in the opposite direction. No new model required.

Acceptance: the transcribe response carries a list of established facts absent
from the note; an omission-detection rate is measurable against the PriMock57
checklists; the rate and its false-alarm rate are both reported.

Out of scope: any interface claim that the note is complete. Best published
detection is ~25%; an empty result is not an all-clear.

---

## Step 3. Build the review surface (frontend)

**Core.**

Surface what the API already returns and the client currently discards:
`fact_table`, `verification`, and the omissions from step 2. Every clinical
claim becomes traceable to the consultation text supporting it, and absent facts
become visible rather than remembered.

Acceptance: a reviewer can open any claim and see its supporting transcript
span; unsupported claims are visually distinct from supported ones; omitted
facts are listed with the text that established them.

Out of scope: note editing workflow changes beyond what review requires.

---

## Step 4. Deploy

**Core.** Gates the two success metrics that need real users.

Execute the existing Railway + Vercel runbook. Validate the resource envelope
first - local speech recognition inside a free-tier memory limit is the open
risk, and it may force a hosted ASR path or a paid tier.

Acceptance: a clinician can register and produce a note from audio without
cloning the repository; the deployed configuration is recorded; the memory and
storage envelope is measured rather than assumed.

Out of scope: EHR integration, custom domains.

---

## Step 5. Introduce the model-serving boundary

**Core. The backbone of the rewrite.**

Restructure the pipeline so each ML stage sits behind one interface that can be
served by an external API or a locally hosted trained model, selected by
configuration. This is what makes steps 6-9 incremental swaps rather than a
rewrite, and what lets every swap be measured against step 1's baseline.

Acceptance: every model-backed stage resolves through a single boundary;
switching a stage between hosted and local changes configuration only; the
harness runs unchanged against either.

Out of scope: training any model.

---

## Step 6. Fine-tune the note generator

**Core ML. Start here - most feasible, largest payoff.**

Fine-tune a small open model to produce SOAP notes, replacing the hosted API.
ACI-Bench and MTS-Dialog adapters already exist and both ship reference notes,
so the data path is written. Decide the base model and the dataset mix, train
with LoRA/QLoRA within session limits, and evaluate against step 1's baseline.

Acceptance: a trained checkpoint produces notes end-to-end through the step 5
boundary; note-quality metrics are compared against the baseline on identical
cases; the dataset mix, hyperparameters and compute cost are recorded.

Out of scope: replacing the evaluation judge with the trained model, which
would mean the system grading its own homework.

---

## Step 7. Fine-tune clinical entity recognition

**Core ML.**

Replace the current biomedical NER model, which emits only CHEMICAL and DISEASE
and is patched by a dictionary scan for everything else. Select a corpus with
attention to access terms - several clinical NER corpora require a data-use
agreement that can take weeks and may not be granted - and prefer publicly
available annotations where the licence is clean.

Acceptance: the trained recogniser covers the entity categories the dictionary
layer currently patches; entity precision and recall are compared against the
baseline; corpus licence and access terms are documented.

Out of scope: assertion detection, which is a separate layer and already works.

---

## Step 8. Fine-tune speech recognition

**Stretch. Marginal expected gain, real methodological cost.**

Fine-tune the ASR model on clinical audio. PriMock57 supplies ~3 hours across 57
consultations - enough to fine-tune, not to train from scratch, and small enough
that overfitting is the default outcome. It is also the evaluation set, so a
held-out split must be reserved before any training touches it.

Acceptance: a held-out split is defined and never trained on; word error rate
and medical term recall are compared against the baseline on that split; the
result is kept only if it beats the baseline, and reported either way.

Out of scope: training on the full corpus without a held-out split.

---

## Step 9. Train a fact-extraction model

**Stretch. A labelling project before it is a training project.**

Train a model to extract the fact table directly, rather than assembling it from
entities plus a general model pass. No off-the-shelf dataset exists, so labels
must be bootstrapped - the existing checklist-to-golden tooling and the
consultation checklists are the most promising starting point. Closest step to
the competitive wedge, and the most likely to be cut for time.

Acceptance: a labelled dataset exists with its construction method documented;
extraction quality is compared against the current assembled fact table; the
honest result is reported even if the trained model loses.

Out of scope: replacing the fact table in production before it beats the
current approach on the baseline.

---

## Step 10. Publish the evidence

**Core. This is what converts the work into a portfolio artifact.**

Produce the comparison report: current system versus rebuilt system, across every
metric, on identical cases. Include traceability and omission-detection figures,
the datasets and their provenance, and the negative results. Correct the
documentation that currently understates the system.

Acceptance: a single report compares before and after on identical evaluation
cases; every figure names its dataset and date; at least one negative or
null result is reported rather than omitted.

Out of scope: claims of clinical validation. Offline metrics on a few hours of
audio are not a trial, and the comparator in this field holds a randomised
controlled trial.

---

## Sequencing notes

- **Steps 1 -> 2 -> 3 are the shortest path to something defensible.** They need
  no training, no new datasets and no GPU, and they deliver the wedge the market
  research identified.
- **Step 4 can move.** If the free-tier memory envelope fails, deploy after step
  6, when the hosted generator is replaced by a smaller local one, or accept a
  paid tier.
- **Steps 8 and 9 are genuinely optional.** Landing 6 and 7 well is worth more
  than landing all four badly, and step 9's labelling cost is easy to
  underestimate.
- **Once training lands, torch enters the dependency set** and build-failure
  chains should move from the generic resolver to the PyTorch one.
