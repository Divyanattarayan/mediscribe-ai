# Trustworthy SOAP Notes from Consultation Audio

## Problem

Clinicians in small practices spend hours after each clinic writing up encounters
they have already conducted. Automating the write-up only helps if the output can
be trusted: a generated note that may contain claims the consultation never
supported has to be read word-against-memory, which costs as much as writing it.
The cost of leaving this unsolved is that documentation stays a second unpaid
shift, and any automation that ignores trust simply moves the work from writing
to verifying.

## Evidence

- **Desk research** — documentation burden identified as a recognised problem in
  the North American healthcare sector via published/online sources. Secondary,
  not gathered from users of this product.
- **Assumption — needs validation via user research.** No clinician has used this
  system or been interviewed about it. The problem is credible; its specific
  shape for *small-practice* clinicians is unvalidated.
- **Technical evidence exists but describes a different population**: measured
  ASR and coverage results come from a UK primary-care consultation corpus, not
  North American practice. See Risks.

## Users

- **Primary**: a clinician in a solo or small-group practice with no enterprise
  scribe budget, documenting their own encounters at the end of a clinic session.
  Triggered at the point a consultation ends and a note is owed.
- **Not for**: hospital enterprise deployments, EHR-integrated scribe products,
  and any use where the generated note is filed without clinician review.

## Hypothesis

We believe **SOAP notes whose every clinical claim can be traced back to what was
actually said, and whose omissions are surfaced rather than left to memory**,
will **make review fast enough that automated documentation saves real time** for
**small-practice clinicians**.

We'll know we're right when **a clinician can accept a note faster than they
could write it, can confirm any individual line without replaying the audio, and
is told what they said that the note left out**.

The second clause is the load-bearing one. Published evaluation finds omission —
not fabrication — is the dominant error class across every commercial scribe
tested, and that detecting it requires enumerating transcript facts and checking
each against the note. See `.reports/market-research.md`.

## Success Metrics

| Metric | Target | How measured |
|---|---|---|
| Claims traceable to the transcript | TBD — baseline first | Share of generated clinical claims carrying a supporting transcript span. Measurable now, without users. |
| Omission detection rate | TBD — baseline first | Share of established transcript facts absent from the note that the system flags, at a stated false-alarm rate. Measurable now against existing consultation checklists, without users. Published comparator: 24.6% at 2.7% false alarms. |
| Review time per note | TBD — needs users | Elapsed time from note-ready to clinician-accepted. Requires a deployed service and instrumentation that does not exist yet. |
| Edit rate before acceptance | TBD — needs users | Proportion of generated note text changed before acceptance. Requires the review surface to record edits. |

Only the first can be baselined before launch. The other two are the metrics that
actually test the time-saving thesis, and both are blocked on having users —
which is why deployment is in the MVP.

## Scope

**MVP** — Deploy the service so a clinician can use it without a local setup, and
surface claim-level provenance in the review experience so each line of a
generated note can be checked against what was said.

The provenance data is already produced and already returned by the API on every
request; the review experience currently discards it. This makes the MVP a
delivery-and-surfacing problem rather than a modelling problem.

**Out of scope**

- **EHR / chart integration** — a system-of-record write path carries compliance
  obligations the project has deliberately avoided claiming.
- **Patient instructions and referral letters** — additional artifacts are worth
  less than trust in the primary one.
- **Specialty-aware quality checks** — depends on a validated user segment.
- **Longitudinal pull-forward across visits** — requires patient-identity and
  safety design that has not been done.
- **Filing notes without review** — the product produces drafts for a clinician,
  and nothing in this scope changes that.

## Delivery Milestones

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | Live service | A clinician can register and produce a note from audio without cloning anything. | pending | — |
| 2 | Source-linked review | Every clinical claim in a note can be traced to the consultation text that supports it, and unsupported claims are visibly unsupported. | pending | — |
| 3 | Omission surfacing | A clinician is told what the consultation established that the note does not record, instead of having to notice its absence from memory. | pending | — |
| 4 | Traceability and completeness baseline | Published figures for what share of claims are traceable and what share of omissions are caught, so later changes can be compared against them. | pending | — |
| 5 | Usage instrumentation | Review time and edit rate become observable, unblocking the two metrics that test the time-saving thesis. | pending | — |

## Open Questions

- [ ] Does the target market's regulatory regime (North American PHI handling)
      apply to a portfolio deployment, and does it change what may be stored or
      where it may be hosted?
- [ ] Is claim-level traceability the right granularity for review, or do
      clinicians want it per sentence or per SOAP section?
- [ ] What does a clinician do with an accepted note today — copy into a system
      of record, or keep it in the app? This determines whether export is
      sufficient or whether the app is the record.
- [ ] Should a note containing unsupported claims be blocked, flagged, or simply
      annotated?
- [ ] Does the measured quality on UK primary-care consultations transfer to
      North American practice, or does the target user need their own baseline?

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Evaluation corpus and target market mismatch — quality is measured on UK primary care, the user is North American | High | High | State the provenance of every published figure; treat transfer as unproven until a target-population baseline exists |
| Problem is desk-researched, not user-validated for small practices | High | High | Milestone 1 exists partly to get the product in front of a real clinician; treat scope beyond MVP as unlocked only by that feedback |
| Two of three success metrics cannot be measured before launch | Certain | Medium | Baseline traceability now; accept the others as post-launch |
| Trust surface increases perceived authority of a draft note | Medium | High | Provenance must make unsupported claims *more* visible, not present the note as verified; review remains mandatory |
| Omission detection is partial and could be mistaken for complete | High | High | Best published method catches ~25% of omissions. The interface must claim "some things you said are missing", never "nothing is missing"; an empty result is not an all-clear |
| Free-tier hosting cannot carry local speech recognition within its memory and storage limits | Medium | High | Validate resource envelope before committing to the deployment target |
| Generation depends on a free third-party model tier whose limits change | Medium | Medium | A degraded non-LLM path already exists; keep it and surface which path produced a note |

---
*Status: DRAFT — requirements only. Implementation planning pending via /plan.*
