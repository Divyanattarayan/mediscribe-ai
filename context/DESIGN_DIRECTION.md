# Design Direction

Locked 2026-08-30. This is the source of truth for MediScribe AI's visual language.
Supersedes any colour, type, or spacing decision found elsewhere in the repo or in
`project_memory.md`.

**Priority:** credible first, with moments. Restrained and clinical on the working surfaces
(session view, SOAP, history, settings); real ambition permitted only where it costs nothing —
sign-in, empty states, and the 1–2 minute processing sequence.

---

## 1. The organising idea

**Colour is reserved entirely for meaning. Character comes from warmth, typography and
restraint — not from a brand hue.**

MediScribe's colour budget is spent before any brand colour exists: six entity categories plus
three status states is **nine meaning-bearing hues**. When the brand also claims a hue (today
`#1A56DB`), it competes with all nine. That is why the current interface manages to feel noisy
and generic at the same time.

Three independent sources converge on the same fix:

- **Swiss Modernism 2.0** (via the `ui-ux-pro-max` skill) — "single accent only", high
  contrast, mathematical spacing, WCAG AAA.
- **Editorial / luxury print** — ink and paper; colour appears only where it carries meaning.
- **carcompany.care** (reference we studied) — ships **no brand hue at all**: just `--dark`,
  `--light`, `--panel`, and functional accents each with a darkened `-ink` text variant.

So: warm stone neutrals replace the cool slate ramp, primary actions are **ink**, and one
restrained accent is rationed to structural roles only.

---

## 2. Colour

Every pair below was contrast-measured, not estimated.

### Neutrals — warm stone

| Token | Light | Dark | Role |
|---|---|---|---|
| `--color-paper` | `#FAFAF9` | `#141210` | app background |
| `--color-surface` | `#FFFFFF` | `#1C1917` | cards |
| `--color-sunken` | `#F5F5F4` | `#0D0B0A` | wells, table stripes |
| `--color-border` | `#E7E5E4` | `#332F2B` | hairlines |
| `--color-border-strong` | `#D6D3D1` | `#44403C` | dividers, emphasis |
| `--color-ink` | `#1C1917` | `#FAFAF9` | primary text **and primary buttons** |
| `--color-ink-muted` | `#57534E` | `#D6D3D1` | secondary text |
| `--color-ink-subtle` | `#78716C` | `#A8A29E` | labels, meta |

Measured on `--paper`: ink **16.7:1** AAA · muted **7.3:1** AAA · subtle **4.6:1** AA.
Dark: ink 17.9:1 · muted 12.6:1 · subtle 7.4:1, all AAA.

> `--ink-subtle` is `#78716C`, not the lighter `#A8A29E` — that measured **2.41:1** and fails.
> Do not lighten it.

The swap from cool slate (`#F0F4F8`, `#0F172A`, `#E2E8F0`) to warm stone is the single
highest-leverage change in the whole redesign: near-zero cost, large character shift.

### Accent — deep teal, rationed

| Token | Light | Dark |
|---|---|---|
| `--color-accent` | `#14524F` (8.6:1 AAA) | `#5EAFA6` (7.3:1 AAA) |
| `--color-accent-hover` | `#0F3D3B` | `#7CC3BA` |

**Allowed for:** focus rings · active nav indicator · links · the logo mark.
**Never for:** primary buttons (ink), status, or decoration.

*Why this and not pure ink:* focus rings and links need a hue that survives on both light
ground *and* on ink buttons. Nominally "hueless" systems (Linear, Vercel) still use a coloured
focus ring for exactly this reason.
*Why not brass/gold:* it sits too close to the amber warning state and would muddy status.
*Why it doesn't collide with status green:* far darker and far less saturated, and it only ever
appears in structural positions while status green only appears in content positions.

### Status

Deliberately desaturated — today's bright `#0BA871` / `#F59E0B` / `#DC2626` are part of what
reads as generic. Each state carries a tint and an `-ink` text variant.

| State | Tint | Ink | Ratio |
|---|---|---|---|
| ok / generated / complete | `#EDF4EF` | `#2C5A42` | 7.1:1 AAA |
| warn / awaiting / incomplete | `#FBF3E7` | `#8A5A16` | 5.4:1 AA |
| danger / failed / critical | `#FBEEED` | `#8C332C` | 7.1:1 AAA |

### Entity categories

Six muted, warm-leaning hues. All AA or better as text on their own tint.

| Category | Tint | Ink | Ratio |
|---|---|---|---|
| Symptom | `#F7EEED` | `#7E3F3A` | 6.9:1 |
| Medication | `#EDF1F5` | `#35506B` | 7.4:1 |
| Condition | `#F3EEF4` | `#5C3D5F` | 8.0:1 |
| Procedure | `#F0F3EC` | `#455C39` | 6.6:1 |
| Test | `#F6F1E7` | `#735725` | 6.0:1 |
| Other | `#F5F5F4` | `#57534E` | 7.0:1 |

Symptom (clay) and Procedure (moss) are the one deuteranopia-confusable pair. Acceptable
because category names are always rendered as text beside the chips — colour is never the sole
carrier of meaning.

### Explicitly rejected

Cyan and bright-teal health palettes · electric blue and indigo · violet or pink gradients ·
neon · any brand hue that competes with the nine semantic hues.

---

## 3. Typography — semantic, by content type

**The typeface tells you what kind of text you are looking at.**

| Face | Signifies | Used for |
|---|---|---|
| **JetBrains Mono** | raw machine output | the transcript, patient IDs, timestamps, durations, confidence figures, all table numerals |
| **Newsreader** (serif) | the finished clinical document | the SOAP note set as prose; page titles and section headings |
| **Instrument Sans** | application chrome | nav, buttons, labels, form fields, table headers, everything else |

Setting the generated SOAP note in a reading serif makes it read as *a document* rather than a
form field. That is the app's payoff moment and the place the "with moments" allowance is spent.

**Inter is deliberately avoided** — it is the default of every AI product, and using it would
undercut the entire brief.

> **Critical:** these must be defined in `@theme`. `--font-head` / `--font-sans` /
> `--font-mono` are referenced across ~10 components today and were **never defined**, which is
> why Sora and IBM Plex Mono have never rendered a single glyph. The app has been running in
> the OS system font stack this whole time.

### Scale

Nine steps, replacing the current 28 (which included half-pixel values like 10.5 and 13.5):

`11 · 12 · 13 · 14 · 16 · 18 · 21 · 28 · 36`

Chrome sits at 13–14. SOAP prose at 16 with a 60–75 character measure.
Weights: 400 body · 500 labels · 600 headings. Never below 400 at any size.

---

## 4. Shape, depth, spacing

- **Radius** — four values replacing eleven: `4px` chips and badges · `8px` buttons and inputs
  · `12px` cards · `full` avatars and dots.
- **Depth is hairline borders, not shadows.** Exactly one soft shadow exists, reserved for true
  overlays (modals, dropdowns). The current `shadow-lg` on stat cards is removed.
- **Spacing** — 8px base with a 4px half-step: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64`.
- **12-column grid**, per Swiss Modernism.

---

## 5. Motion

One curve, four durations — replacing today's seven ad-hoc values.

```
--ease: cubic-bezier(0.22, 1, 0.36, 1)   /* easeOutQuint */
```

| Token | ms | Use |
|---|---|---|
| `--dur-fast` | 150 | hover, toggle, press |
| `--dur-base` | 300 | panel, state change, collapse |
| `--dur-slow` | 600 | entrance, first paint of results |
| `--dur-reveal` | 900 | the SOAP line-by-line reveal only |

Derived from measuring the two motion references, which independently share this exact curve.
Both also favour **tiny travel** — 5–6px — and everything eases *out*; ease-in-out appears only
on infinite loops, where symmetry is correct.

Long durations are spent only on genuinely once-per-session moments. A 900ms reveal is
delightful the first time and sluggish by the fifth, so it never touches routine UI.

**`prefers-reduced-motion` is non-negotiable** in a clinical tool: reveals degrade to instant,
loops stop. Neither reference site handles this; we must.

### Signature interactions

- **SOAP note reveal** — each line wrapped in `overflow: clip`, inner element tweened on
  `yPercent` from 100 → 0, stagger ~65ms. Reads as the note being written. This is the single
  best idea lifted from the references and it lands on the payoff moment.
- **Entity chips** — staggered 60–70ms per chip within each category group, opacity + small y.
- **Processing state** — a breathing loop (2.2–3.5s, symmetric easing), not a progress bar.

---

## 6. Structure

**The sidebar is removed.** It costs a permanent 220px, carries four destinations, never
dark-branches, and its nav items aren't keyboard reachable. A horizontal top nav reclaims
exactly the width the three-column session view needs.

`MediScribe` mark · Dashboard · Sessions · Settings — user chip right.

1. **Dashboard** — the working surface. Upload zone primary; encounter type and style controls;
   recent sessions; a **real** quality panel driven by `quality_report.section_issues`.
2. **Session view** — *new, and the centrepiece.* Three columns replacing today's vertical
   stack:
   **Transcript** (mono, entities highlighted inline) │ **SOAP Note** (serif, collapsible
   S/O/A/P, editable) │ **Context** (entities by category, quality report, encounter type,
   style, confidence).
   This makes reviewing a note *against its source* possible — delivering PLAN.md Phase 4 as a
   layout decision rather than a feature build.
3. **Sessions** — the history table, quality score surfaced, tabular figures.
4. **Settings** — profile, documentation style, data. The faked API tab is deleted.
5. **Sign in** — the one surface allowed ambition. Fabricated testimonial and invented stats
   removed.

### Data we already have and don't show

The backend already returns these every request; the frontend discards them. Surfacing them is
the cheapest credibility available:

| Panel | Backing data |
|---|---|
| Quality / alerts | `quality_report.section_issues` + `quality_score` |
| Inline entity highlighting | `MedicalEntity.start` / `.end` character offsets |
| Speaker-attributed transcript | `TranscriptionCard` already regex-tags Doctor / Patient |
| System status | the real `GET /health` endpoint |
| Encounter + style badges | `resolved_encounter_type`, `resolved_style_profile` |

---

## 7. Honesty rules

Non-negotiable under the "credible" priority. Every item below currently exists in the app and
must not survive the redesign, or reappear from any reference:

- **No invented metrics.** `timeSaved = history.length * 5` goes. No fabricated percentages, no
  "time saved", no comparisons to last week.
- **No simulated progress.** `startFakeProgress()` — six `setTimeout` stage messages and an
  estimated countdown unrelated to the backend — is replaced by an honest indeterminate state
  with real stage labels and a truthful elapsed counter. No time-remaining estimate.
- **No fabricated social proof.** The "Dr. Rachel Kim" testimonial and the "8→3 min / 700+ /
  87%" stats are removed.
- **No controls that don't work.** The Alerts button with no handler, the read-only API URL
  field, the hardcoded "Backend connected", the Notifications save that only fires a toast, and
  the "Save to Record" button that silently just downloads a `.txt`.
- **Per-screen copy must be true of that screen.** "Here's your documentation overview for
  today!!" cannot appear on three different pages.

A reference looking polished does not make its invented numbers acceptable. The concept design
we studied has this exact flaw; we take its structure, not its fictions.

---

## 8. Implementation notes

### Tailwind v4 token wiring

`tailwind.config.js` is ignored in v4. Tokens go in `@theme` inside `index.css`, using v4's
namespaces so utilities are generated (`--color-*` → `bg-*`/`text-*`/`border-*`,
`--font-*` → `font-*`, `--radius-*` → `rounded-*`, `--text-*` → `text-*`).

```css
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=JetBrains+Mono:wght@400;500&display=swap');
@import "tailwindcss";

@theme {
  --font-sans:  "Instrument Sans", ui-sans-serif, system-ui, sans-serif;
  --font-serif: "Newsreader", Georgia, serif;
  --font-mono:  "JetBrains Mono", ui-monospace, monospace;

  --color-paper: #FAFAF9;
  --color-surface: #FFFFFF;
  --color-ink: #1C1917;
  --color-accent: #14524F;
  /* …full set per §2 */

  --radius-sm: 4px;  --radius-md: 8px;  --radius-lg: 12px;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
}

@layer base {
  .dark {
    --color-paper: #141210;
    --color-surface: #1C1917;
    --color-ink: #FAFAF9;
    --color-accent: #5EAFA6;
    /* …only the tokens that change */
  }
}
```

### This changes how dark mode works — for the better

Because v4 emits theme values as CSS custom properties and utilities reference them via
`var()`, redefining the tokens under `.dark` cascades automatically. Components stop needing
`dark ? '#1E293B' : '#FFFFFF'` conditionals for colour entirely.

That lets us **delete the `html.dark main … !important` override block** in `index.css`. Today
dark mode is implemented twice — per-component conditionals *and* those overrides — with four
different branching conventions coexisting, and two components (Sidebar, TranscribeButton) that
don't branch at all and rely wholly on the overrides. Token-driven theming ends that.

The one exception remains **runtime-selected colour** (entity chips), which must still be
applied as inline hex because the v4 scanner never sees class strings assembled at runtime.
Those tables live in `frontend/src/lib/utils.ts`, which already owns `getEntityColors`.

### Consolidation targets

The redesign must also collapse the duplication the inventory found: card shell ×7, primary
button ×9 (five different paddings), confirmation modal ×3, form field ×3, icon button ×3,
destructive button ×4, progress bar ×3, and eight unrelated badge recipes. These become shared
primitives in `frontend/src/components/ui/`.

### Accessibility carried into the rebuild

Sidebar nav items and the upload dropzone are `<div onClick>` — not keyboard reachable. SOAP
textareas have no border and no focus ring. UploadCard's selects have no focus style. `App.tsx`
returns `null` during session restore, showing a blank screen. All fixed as part of the rebuild.

---

## 9. Provenance

- **`ui-ux-pro-max` skill** — style (Swiss Modernism 2.0) and the Newsreader pairing adopted.
  Its recommended palette (`#0891B2` cyan on `#ECFEFF`) was **rejected** as exactly the
  generic health-tech family the brief rules out; its "FAQ/Documentation Landing" pattern was
  rejected as a keyword mismatch on the word *documentation*; Playfair Display was rejected for
  fragile hairlines at UI sizes.
- **`apple-design`** — does not exist in this environment. Apple HIG rules reach this document
  through `ui-ux-pro-max`, which cites them throughout (focus states, reduced motion, spring
  physics, one-primary-action-per-screen).
- **Motion references** — skyclinics.al and carcompany.care, analysed live in-browser
  (computed styles, keyframes, GSAP/ScrollTrigger instances, CSS custom properties).
- **Structural reference** — an unshipped "Clinical Documentation Assistant" concept; its
  information architecture and feature set informed §6, its invented metrics informed §7.
- Full working notes, including per-reference analysis and transfer assessments, are in the
  plan file for this workstream.
