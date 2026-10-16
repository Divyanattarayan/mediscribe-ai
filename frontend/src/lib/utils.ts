// src/lib/utils.ts
//
// Shared frontend helpers. This file was previously excluded by an over-broad
// `.gitignore` `lib/` rule and lost on a fresh clone; it has been reconstructed
// from its call sites and the palette recorded in `project_memory.md` §3.
//
// Tailwind v4 note: any colour chosen at runtime must be applied as an inline
// style with a hex value — the v4 scanner never sees class strings that are
// assembled at runtime. That is why getEntityColors/getEntityDotColor return
// plain hex strings rather than class names.

import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

import type { EntityCategory, GroupedEntities, MedicalEntity } from '../types'

/** Standard shadcn/ui class combiner: clsx + tailwind-merge. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

// ── Formatting ───────────────────────────────────────────────────────────────

/**
 * Format a confidence value as a whole-percent string, e.g. "87%".
 * Accepts either a 0–1 fraction or an already-scaled 0–100 number.
 */
export function formatConfidence(value: number): string {
  if (!Number.isFinite(value)) return '0%'
  const pct = value <= 1 ? value * 100 : value
  return `${Math.round(pct)}%`
}

/** Locale date-time string, matching how API history rows are formatted. */
export function formatDate(date: Date): string {
  return date.toLocaleString()
}

// ── Entity categorisation ────────────────────────────────────────────────────

// Backend NER/dictionary labels → the 6 UI categories.
//   CHEMICAL   -> MEDICATION
//   DISEASE    -> CONDITION
// (the frontend uppercases labels before they reach here)
const LABEL_TO_CATEGORY: Record<string, EntityCategory> = {
  CHEMICAL: 'MEDICATION',
  MEDICATION: 'MEDICATION',
  DRUG: 'MEDICATION',
  DISEASE: 'CONDITION',
  CONDITION: 'CONDITION',
  DIAGNOSIS: 'CONDITION',
  SYMPTOM: 'SYMPTOM',
  SIGN: 'SYMPTOM',
  TEST: 'TEST',
  LAB: 'TEST',
  PROCEDURE: 'PROCEDURE',
  TREATMENT: 'PROCEDURE',
}

export function getEntityCategory(label: string): EntityCategory {
  return LABEL_TO_CATEGORY[(label ?? '').toUpperCase().trim()] ?? 'OTHER'
}

export function groupEntities(entities: MedicalEntity[]): GroupedEntities {
  const grouped: GroupedEntities = {
    symptoms: [],
    medications: [],
    conditions: [],
    procedures: [],
    tests: [],
    other: [],
  }
  const bucket: Record<EntityCategory, MedicalEntity[]> = {
    SYMPTOM: grouped.symptoms,
    MEDICATION: grouped.medications,
    CONDITION: grouped.conditions,
    PROCEDURE: grouped.procedures,
    TEST: grouped.tests,
    OTHER: grouped.other,
  }
  for (const entity of entities ?? []) {
    bucket[getEntityCategory(entity.label)].push(entity)
  }
  return grouped
}

// ── Entity colours ───────────────────────────────────────────────────────────

interface EntityColors {
  bg: string
  border: string
  text: string
}

// Palette of record — context/DESIGN_DIRECTION.md §2. Muted and warm-leaning so
// six categories stay distinguishable without any of them shouting.
//
// These stay as hex here rather than moving to index.css because the category is
// chosen at runtime, and Tailwind v4's scanner never sees class strings assembled
// at runtime. The chip is delineated by its left border (the `border` value), not
// by the fill — which is why the tints are deliberately faint in both themes.
const ENTITY_COLORS_LIGHT: Record<EntityCategory, EntityColors> = {
  SYMPTOM:    { bg: '#F7EEED', border: '#7E3F3A', text: '#7E3F3A' },
  MEDICATION: { bg: '#EDF1F5', border: '#35506B', text: '#35506B' },
  CONDITION:  { bg: '#F3EEF4', border: '#5C3D5F', text: '#5C3D5F' },
  PROCEDURE:  { bg: '#F0F3EC', border: '#455C39', text: '#455C39' },
  TEST:       { bg: '#F6F1E7', border: '#735725', text: '#735725' },
  OTHER:      { bg: '#F5F5F4', border: '#57534E', text: '#57534E' },
}

const ENTITY_COLORS_DARK: Record<EntityCategory, EntityColors> = {
  SYMPTOM:    { bg: '#38211E', border: '#E3B4AE', text: '#E3B4AE' },
  MEDICATION: { bg: '#1F2C3A', border: '#B3CCE4', text: '#B3CCE4' },
  CONDITION:  { bg: '#2F2432', border: '#D3B9D6', text: '#D3B9D6' },
  PROCEDURE:  { bg: '#232E1E', border: '#B9CFA9', text: '#B9CFA9' },
  TEST:       { bg: '#332B15', border: '#DCC48E', text: '#DCC48E' },
  OTHER:      { bg: '#2C2825', border: '#C2BCB6', text: '#C2BCB6' },
}

export function getEntityColors(category: EntityCategory, dark: boolean): EntityColors {
  const palette = dark ? ENTITY_COLORS_DARK : ENTITY_COLORS_LIGHT
  return palette[category] ?? palette.OTHER
}

/** Single accent colour for a category dot. */
export function getEntityDotColor(category: EntityCategory, dark: boolean): string {
  return getEntityColors(category, dark).border
}
