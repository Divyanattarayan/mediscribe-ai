# Competitive Research — Ambient Clinical Documentation
2026-09-17 · research supporting `.claude/prds/trustworthy-soap-notes.prd.md`

**Source handling:** vendor comparison pages are written by competitors ranking
competitors and are marked `[vendor]`. Peer-reviewed and regulator sources are
marked `[peer-reviewed]` / `[regulator]`. No fetched page contained text
addressed to the agent. Fact, inference and recommendation are separated below.

---

## 1. Executive summary

The category is real, large and crowded: ambient scribe adoption crossed **40% of
US/Canadian outpatient settings** in 2026 and revenue reached an estimated **$5B+**,
growing 20–29% CAGR. We cannot win on "AI scribe," on distribution, or on EHR
integration — the incumbents are funded and embedded.

But the published error data points at a gap none of them have closed. Across
every independent evaluation, **the dominant failure mode is omission — the note
leaving out what the consultation established — not hallucination.** And an
August 2026 benchmark shows *why* it stays unfixed: LLM judges are architecturally
blind to absence, scoring near chance (0.50–0.63) at detecting missing facts while
scoring 0.79–0.94 at detecting added ones. Five remedy families failed. The one
method that worked was **enumerate the transcript's facts first, then verify each
one against the note**.

That is the architecture this project already built. `clinical_facts.py` produces
exactly that enumeration, with evidence spans. **We do not use it in that
direction.** `verify_note(note, transcript)` checks note→transcript — the easy
direction the incumbents already handle. Nothing checks fact→note.

**The competitive advantage is one closed loop away, and we own both halves of it.**

---

## 2. Key findings

### F1 — Omission is the dominant error class, industry-wide `[peer-reviewed]`

A controlled lab study of **six commercial AI scribes** (Women's College Hospital,
Toronto) found **deletion/omission errors in all six products**. Frequently
excluded: medical history, social history, lifestyle factors. Also observed:
"generalization errors" simplifying clinical terms — *Colles fracture* → *fracture*.
Notably, names, numbers, medication names and punctuation were **not** error-prone.

Independent 2026 commentary agrees omission outranks fabrication, and names the
categories most at risk: medications spoken quickly, dosage changes mentioned in
passing, symptoms buried in conversational language.

> Caveat: the six-product study ran 2024–2025 in a lab with standardised audio.
> In a market this fast, product behaviour may have moved. Treat as directional.

### F2 — LLM judges cannot see omissions, and prompting cannot fix it `[peer-reviewed]`

Benchmark of 500 single-error note pairs from 117 consultations (August 2026):

| Task | Paired discrimination |
|---|---|
| Detect **commission** (added/altered content) | 0.79 – 0.94 |
| Detect **omission** (missing content) | 0.50 – 0.63 *(near chance)* |

Single-note omission detection bottomed at **8.3% at 6.5% false alarms**. Five
remedy families all failed: prompt wording, output format, ensemble voting, GEPA
automated prompt optimisation, criterion scope expansion.

**What recovered it — both by converting absence into presence checks:**

| Method | Detection | False alarms |
|---|---|---|
| **Pipeline: extract transcript facts, then verify each against the note** | 24.6% | 2.7% |
| Evolved single-call prompt (GEPA + reasoning budget) | 36.9% | 6.2% |

Mechanism: ~1/3 of the gain from explicit fact enumeration, ~2/3 from **closed
per-fact verdicts** replacing open "what is missing?" questions. A blinded
physician sided with the pipeline on all ten disagreement cases (p=0.002).

The study also found **100% of examined reference notes contained discrepancies
with their transcripts** — so transcript-derived fact sheets, not clinician notes,
are the defensible ground truth.

### F3 — Our architecture is the published recovery method, used in one direction only

| Capability | We have | Direction | Detects |
|---|---|---|---|
| `clinical_facts.build_fact_table` | yes — enumeration with evidence spans | transcript -> facts | — |
| `claim_verification.verify_note` | yes — per-claim verdicts | note -> transcript | **commission** (easy) |
| fact -> note verification | **absent** | — | **omission** (hard) |

`fact_table_summary` counts facts (`total`, `assertable`, `unverified`) and never
asks whether they reached the note. `soap_generator.py:524` acknowledges the
hallucination/omission trade-off in a comment — the awareness exists, the check
does not.

### F4 — Grounding is becoming table stakes; we are not first `[vendor]` (contrarian)

Vendors now market transcript grounding directly, and a "Note Check" tool that
reads any scribe's note against its transcript shipped **August 2026**. Published
hallucination rates sit at **1–3% of notes**, with one March 2026 analysis of
71,173 note sections finding confirmed edits in **5.8%**.

**Implication: commission-checking is commoditising.** Building more of what
`claim_verification.py` already does is building into a closing window. The
omission direction is where the published evidence says the field is still stuck.

### F5 — Competitive baseline for the small-practice tier `[vendor]`

| Product | Price signal | Position |
|---|---|---|
| Freed | $39–119/mo | Simplicity, style adaptation, browser EHR push |
| Heidi Health | Free tier; ~$150/mo annual | Template flexibility; strong UK/AU/NZ |
| Nabla | Free – ~$119/mo | Multilingual, telehealth |

**Nabla holds the field's first RCT: 9.5% reduction in physician time-in-note.**
That is the bar for any time-saving claim. We have no clinical validation.

Only **two of six** evaluated scribes had excellent EMR integration — the top
purchase driver and the thing a portfolio project cannot credibly build.

### F6 — Regulation favours a review-first product `[regulator]`

NHS England (April 2026): explicit patient consent is not required, but
transparency is — clinicians must disclose use and allow objection. **Clinical
responsibility remains with the clinician; outputs must be reviewed and validated
before entering the record.** FDA has general AI-enabled device software guidance;
nothing ambient-scribe-specific.

Inference: a product that makes review *fast and evidenced* is aligned with where
regulators are pointing. A product that implies the note is verified is not.

---

## 3. Implications — features we should achieve

Ranked by defensibility x evidence x cost, given what already exists.

### P1 · Omission detection at runtime — **the wedge**
Verify each assertable fact-table row against the generated note; surface the ones
that did not make it. This is F2's pipeline method, we already own the
enumeration, and it attacks the error class every competitor fails on. Closes the
loop `fact_table -> note` that F3 shows is missing.
*Surface as: "3 things you said aren't in this note" — absence made visible.*

### P2 · Source-linked review — already the PRD MVP
Every claim traceable to its span. Already computed, already returned by the API,
discarded by the client. P1 without P2 is a number with nothing to click.

### P3 · Specificity guard (generalization errors)
F1 names *Colles fracture -> fracture* as an industry-wide error. Our ontology layer
already resolves RxNorm and ICD-10 codes and flags `requires_review`. Detect when
the note is *less specific* than the coded entity the transcript supported.
No competitor evidence suggests this is addressed anywhere.

### P4 · Assertion-aware review flags
Vendor-evaluation checklists explicitly tell buyers to ask about "omissions,
negations, attribution errors." We resolve all three (ConText: negation,
temporality, experiencer, uncertainty) and surface none of them. Cheapest
credibility win available.

### P5 · Published completeness benchmark
Use the existing eval harness — PriMock57, checklist coverage, `missed_items`,
`ceiling_scores` — to publish a measured completeness figure. Near-zero competitors
publish this. The harness is built; only the reporting is missing.

### P6 · Transparency affordance
A disclosure prompt and a visible "draft — requires clinician validation" state.
Low cost, directly aligned with NHS guidance, and honest about F4's residual risk.

### Explicit anti-goals (do not build)
- **EHR write-back** — the incumbents' moat; compliance obligations we've avoided claiming.
- **Multilingual / telehealth** — Nabla's ground, no edge available.
- **Diarization arms race** — hard, and not where the published gap is.
- **Real-time streaming** — cost without differentiation.
- **Any "verified note" claim** — F6 makes this a liability.

---

## 4. Risks and caveats

| Risk | Assessment |
|---|---|
| **Omission detection is only 24.6% effective** at 2.7% FA in the published pipeline. A large improvement over ~8%, **not** a solved problem. "Catches omissions" overstates it; "surfaces some" is defensible. | High impact if overclaimed |
| **Our metrics are UK (PriMock57); target market is North American.** Carried over from the PRD. Transfer unproven. | High |
| **Grounding is commoditising** (F4). The window on provenance-as-differentiator is closing; omission is the durable half. | Medium–High |
| **No clinical validation.** Nabla has an RCT. We have offline metrics on ~3 hours of audio. Not comparable, and must never be presented as such. | High |
| **Market data is analyst-sourced** and ranges widely ($8.93B vs $15.1B by 2035). Directionally consistent, individually unreliable. | Low |
| **Six-product study is 2024–2025.** Products may have improved since. | Medium |
| **Vendor sources are self-interested.** All pricing and most feature claims are vendor assertions, uncorroborated. | Medium |
| **This is a portfolio project.** "Competitive advantage" here means *demonstrable technical differentiation to a reviewer*, not market share. P1 and P5 serve both readings; P6 serves only the product reading. | Framing |

---

## 5. Recommendation

**Reposition from "AI scribe with provenance" to "the scribe that tells you what it
left out."**

Provenance answers *can I trust this line?* — a question the market is learning to
answer. Omission answers *what is missing that I said?* — which the peer-reviewed
evidence says nobody answers well, which is the error class clinicians most fear,
and which is cognitively hardest for a clinician to catch unaided ("an omission
requires the clinician to remember exactly what was said").

We hold the published recovery mechanism already. The work is a closed loop and a
UI, not a research programme.

### Proposed build-plan integration

Amends `.claude/prds/trustworthy-soap-notes.prd.md`:

| # | Milestone | Change |
|---|---|---|
| 1 | Live service | unchanged |
| 2 | Source-linked review | unchanged (P2) |
| 3 | **Omission detection** | **NEW — P1, promoted above baseline** |
| 4 | Traceability + completeness baseline | widened to include P5 |
| 5 | Usage instrumentation | unchanged |
| — | Specificity guard (P3), assertion flags (P4), transparency (P6) | backlog, post-MVP |

Hypothesis gains a second clause: *notes whose claims are traceable **and whose
omissions are surfaced** make review fast enough to save real time.*

Success metrics gain one that needs no users: **omission-detection rate against
the PriMock57 checklists**, baselined with the existing harness.

---

## 6. Sources

**Peer-reviewed / preprint**
- [Evaluating the Usability, Technical Performance, and Accuracy of AI Scribes for Primary Care: Competitive Analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC12309782/) — six-product lab comparison
- [LLM Judges Verify Presence, Not Absence: Omission Blindness in AI Clinical Notes and What Recovers It](https://arxiv.org/html/2608.31016) — Aug 2026 benchmark, recovery methods
- [Assessing the quality of AI-generated clinical notes](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12586549/)
- [AI Scribes in Health Care: Balancing Transformative Potential With Responsible Integration](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12316405/)
- [The Impact of Acoustic and Informational Noise on AI-Generated Clinical Summaries](https://www.medrxiv.org/content/10.1101/2025.03.24.25324398.full.pdf)

**Regulator**
- [NHS England — Guidance on AI-enabled ambient scribing products](https://www.england.nhs.uk/long-read/guidance-on-the-use-of-ai-enabled-ambient-scribing-products-in-health-and-care-settings/)
- [FDA — AI-Enabled Device Software Functions](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/artificial-intelligence-enabled-device-software-functions-lifecycle-management-and-marketing)
- [NHSE publishes fresh guidance on safe use of ambient scribes](https://www.digitalhealth.net/2026/04/nhse-publishes-fresh-guidance-on-safe-use-of-ambient-scribes/)

**Vendor / trade — self-interested, treat as claims**
- [Freed — Best AI Medical Scribes](https://www.getfreed.ai/resources/best-ai-scribes)
- [Glass Health — Best Ambient AI Medical Scribes](https://glass.health/resources/best-ai-medical-scribe)
- [Twofold — The Hallucination Problem](https://www.trytwofold.com/blog/ai-scribe-hallucinations)
- [Oli Health — How to spot an AI scribe hallucination](https://olihealth.ai/blog/ai-scribe-hallucination-red-flags-clinical-notes/)
- [DEV — Measuring AI scribe faithfulness / Note Check](https://dev.to/krasynemr/we-published-how-we-measure-our-ai-scribes-faithfulness-and-built-a-checker-anyone-can-run-on-any-3jdl)
- [Forbes — Why Omissions Are The Real Risks](https://www.forbes.com/councils/forbesbusinesscouncil/2026/09/15/the-mistake-most-ai-scribes-make-and-why-omissions-are-the-real-risks/)
- [Commure — AI Medical Scribe evaluation guide](https://www.commure.com/blog-scribe/ai-medical-scribe)

**Market sizing — analyst estimates, wide variance**
- [Towards Healthcare — AI in Medical Scribing Market](https://www.towardshealthcare.com/insights/ai-in-medical-scribing-market-sizing)
- [Astute Analytica — AI Clinical Documentation (Ambient Scribe) Market](https://www.astuteanalytica.com/industry-report/ai-clinical-documentation-ambient-scribe-market)
- [Medical Economics — Take note: The AI scribe era is here](https://www.medicaleconomics.com/view/take-note-the-ai-scribe-era-is-here)
