# Product Lens — Founder Review: mediscribe-ai
2026-09-17 · main @ 89807ef · 75 commits, Nov 2025 – Sep 2026

## First: the standard rubric is the wrong lens here

Mode 2 scores PMF via usage growth, retention, revenue signals and moat. Applied
literally, this project scores ~0 on three of four — and that number would be
meaningless, because the README states the actual frame:

> "20-week portfolio project for university applications."

There is no billing code, no pricing page, no users, and none of that is a gap.
The customer is **an admissions reviewer**, and the product is **the evidence that
you can build and reason about a hard system**. Scoring it as a startup would be
founder-theater on a project that never claimed to be one.

So: the same seven questions, aimed at the real customer.

## Who is it for, and what is the pain?

- **Nominal user:** a clinician doing post-consultation documentation.
- **Actual user being optimised for:** a reviewer with ~10 minutes, deciding
  whether this demonstrates research-grade engineering judgment.

Those two want different things, and right now the repo is built for the first
and *read* by the second.

## What the code actually earns

This is the finding that matters. The September work is not "portfolio project"
work — it is measurement discipline that most professional codebases lack:

- A **fact table** giving every clinical claim a transcript span, so provenance
  exists by construction rather than by post-hoc checking.
- **Per-claim verification** that replaced a lexical proxy, with the header
  explaining why the proxy was wrong in both directions.
- An **evaluation harness** with 55 committed run reports, real datasets
  (PriMock57), and an **off-provider judge** so the pipeline cannot grade itself.
- **Recorded negative results**: `spell_correction` is disabled *with the numbers
  that condemned it* (`regular` -> `irregular`, 24x). Publishing a measurement
  that killed your own feature is a stronger signal than any feature.
- CI that applies migrations **forward and reverse** and asserts model/migration
  agreement.

## The one thing that would 10x this

**Fix the narrative artifact, not the code.** The README undersells the project
to the only audience that reads it, and does so provably:

```
README.md:399  "Negation detection is not implemented — 'denies chest pain'
                and 'chest pain' both extract the entity"
```

That is **false as of the Phase 2 work**. `clinical_assertions.py` implements
ConText negation, `test_a_denied_symptom_is_marked_negated` passes, migration
0002 added the columns, and the *same README mentions ConText six times
elsewhere*. The Known Limitations section contradicts the rest of its own file.

A reviewer reading line 399 concludes the project has the exact naive-NLP flaw
that separates a student project from a serious one — while the repo contains
the fix, tested. This is the single highest-leverage defect in the project, and
it is a documentation defect.

Related undersell: the word "provenance" appears **0 times** in the README. The
fact table — the architecture's central idea — gets two passing mentions.

## Trajectory

```
2025-11   2     2026-01  16     2026-03  18     2026-05   5
2025-12  13     2026-02   9     2026-04   3     2026-09   9
```

Four-month gap (May -> Sep), then a burst that is qualitatively different from
everything before it. Earlier commits read "Week 14 development complete";
September reads "Move the judge to the Lite tier: same quality, 25x the quota."
The project changed from feature-completion to engineering rigor. **The README
still describes the pre-September project.**

## What you are building that may not matter

Stated plan is Weeks 15–16 deployment, 17–20 user testing and launch. Deployment
is currently the gate on everything remaining, and September went to pipeline
depth instead.

That was probably the right call — a measured eval harness is rarer than a live
demo link — but it cannot be the call twice. Weeks 17–20 (user testing) are
**unreachable without deployment**, so continuing to deepen the pipeline defers
the milestone that unblocks the rest of the stated plan.

Anti-goal worth naming explicitly: this does not need more pipeline stages. It
has more measured capability than its documentation claims.

## How you would know it is working

Not usage. For this customer: can a reviewer, in ten minutes, correctly state
what is technically hard about the project? Today the README points them at
"full-stack app with dark mode and session history" and buries the fact table,
the verification layer and the eval harness.

## Recommendation: build — but the next build is not a feature

| Rank | Action | Why |
|---|---|---|
| 1 | Correct README Known Limitations; lead with provenance + evaluation | A false limitation claim is actively costing you the strongest signal you have. Hours of work. |
| 2 | Deploy (Railway + Vercel; runbook already written) | Gates weeks 17–20. The runbook exists; execution does not. |
| 3 | Test `soap_generator`'s quality scorer and fallback | 1,430 LOC, six tests. The one place the rigor narrative has a visible hole. |
| 4 | Assert provenance-by-construction in a test | The central design claim is currently unguarded (see `openspec/specs/clinical-facts/`). |

Items 1 and 2 are not engineering problems, which is precisely why they have
gone unaddressed while the engineering got better.
