// ── Medical & Clinical Types ──────────────────────────────

export interface MedicalEntity {
  text: string
  label: string
  confidence: number
  start: number
  end: number
  negated?: boolean
  temporality?: string
  experiencer?: string
  uncertain?: boolean
  ontology?: {
    system?: string
    code?: string
    display?: string
    requires_review?: boolean
  }
}

export interface ClinicalFinding {
  finding: string
  type: string
  context?: string
  assertion?: string
  temporality?: string
  duration?: string | null
}

export interface UncertainFinding {
  finding: string
  type: string
  cue: string
  context?: string
  requires_review: boolean
}

export interface ClinicalSymptom {
  text: string
  label: string
  negated: boolean
  uncertain: boolean
  temporality: string
  experiencer: string
  duration?: string | null
  context_sentence?: string
}

export interface ClinicalCondition {
  text: string
  label: string
  negated: boolean
  uncertain: boolean
  temporality: string
  is_confirmed_diagnosis?: boolean
  duration?: string | null
  context_sentence?: string
}

export interface ClinicalMedication {
  text: string
  label: string
  action: 'prescribed' | 'current_or_mentioned' | 'discontinued'
  dosage?: string
  negated: boolean
  temporality: string
  context_sentence?: string
}

export interface ClinicalAllergy {
  allergen: string
  reaction: string | null
  negated: boolean
  note?: string
}

export interface DurationRecord {
  phrase: string
  start: number
  end: number
}

export interface StructuredClinicalData {
  symptoms: ClinicalSymptom[]
  medical_conditions: ClinicalCondition[]
  medications: {
    prescribed: ClinicalMedication[]
    current_or_mentioned: ClinicalMedication[]
    discontinued: ClinicalMedication[]
  }
  allergies: ClinicalAllergy[]
  positive_findings: ClinicalFinding[]
  negative_findings: ClinicalFinding[]
  uncertain_findings: UncertainFinding[]
  durations_and_timing: DurationRecord[]
  missing_information: string[]
}

export interface EvidenceStatement {
  id: string
  section: string
  statement: string
  status: 'supported' | 'unsupported' | 'conflicting' | 'ambiguous'
  evidence_quote?: string | null
  evidence_start?: number | null
  evidence_end?: number | null
  similarity: number
  review_message?: string | null
}

export interface EvidenceLinks {
  disclaimer: string
  supported_count: number
  unsupported_count: number
  conflicting_count: number
  ambiguous_count: number
  total_statements: number
  statements: EvidenceStatement[]
}

export interface SOAPNote {
  subjective: string
  objective: string
  assessment: string
  plan: string
  source?: string
  review_flags?: string[]
  is_draft?: boolean
  disclaimer?: string
  generated_at?: string
  evidence_links?: EvidenceLinks
}

export type NoteStylePreset = 'balanced' | 'concise' | 'detailed'
export type PreferredFocus = 'general' | 'symptom_driven' | 'assessment_driven' | 'plan_driven'
export type EncounterType = 'acute_visit' | 'follow_up' | 'counselling_education' | 'medication_review'

export interface NoteStyleProfile {
  note_style_preset: NoteStylePreset
  preferred_focus: PreferredFocus
  include_bullets_in_plan: boolean
  include_patient_friendly_language: boolean
}

export interface ClinicalRepresentation {
  patient?: Record<string, unknown>
  encounter?: Record<string, unknown>
  subjective_data?: Record<string, unknown>
  objective_data?: Record<string, unknown>
  assessment_context?: Record<string, unknown>
  plan_context?: Record<string, unknown>
  history_gaps?: string[]
  source_entities?: Record<string, unknown>
  structured_at?: string
}

export interface SOAPQualityReport {
  overall_score: number
  target_score: number
  passes_threshold: boolean
  section_scores: Record<string, number>
  section_issues: Record<string, string[]>
}

export interface TranscriptionResult {
  db_id?: number
  transcription: string
  entities: MedicalEntity[]
  soap_note: SOAPNote
  medical_content_score: number
  asr_confidence?: number | null
  resolved_encounter_type?: EncounterType
  resolved_style_profile?: NoteStyleProfile
  clinical_representation?: ClinicalRepresentation
  quality_report?: SOAPQualityReport
  quality_score?: number
  processing_time?: number
  filename?: string
  isSynthetic?: boolean
}

// ── Review & Approval Workflow Types ──────────────────────

export type ReviewStatus = 'draft' | 'needs_review' | 'in_review' | 'approved'

export type ConsultationStatus =
  | 'uploaded'
  | 'transcribing'
  | 'transcribed'
  | 'transcript_ready'
  | 'draft_generated'
  | 'in_review'
  | 'approved'
  | 'failed'
  | 'complete'
  | 'processing'

export interface ClinicianApproval {
  approved: boolean
  approvedBy?: string
  approvedAt?: string
  clinicianNotes?: string
  signature?: string
}

// ── History & Consultation Record Types ───────────────────

export interface ConsultationRecord {
  id: string
  patientId: string
  title?: string
  filename: string
  date: string
  duration: string
  entityCount: number
  medicalContentScore: number
  asrConfidence?: number | null
  status: ConsultationStatus
  reviewStatus: ReviewStatus
  approval?: ClinicianApproval
  transcription?: string
  soap_note?: SOAPNote
  entities?: MedicalEntity[]
  error?: string | null
  isSynthetic?: boolean
}

export interface HistoryEntry {
  id: string
  date: string
  patientId: string
  duration: string
  entityCount: number
  medicalContentScore: number
  status: 'complete' | 'processing' | 'failed'
  result?: TranscriptionResult
}

export interface BackendHealthStatus {
  isConnected: boolean
  status: string
  service?: string
  version?: string
  latencyMs?: number
  checkedAt?: string
  error?: string | null
}

// ── UI & Flow State Types ─────────────────────────────────

export type UploadState = 'idle' | 'selected' | 'processing' | 'done' | 'error'
export type AppPage = 'login' | 'dashboard' | 'history' | 'settings'

// ── Entity Category Types ─────────────────────────────────

export type EntityCategory =
  | 'SYMPTOM'
  | 'MEDICATION'
  | 'CONDITION'
  | 'PROCEDURE'
  | 'TEST'
  | 'OTHER'

export interface GroupedEntities {
  symptoms: MedicalEntity[]
  medications: MedicalEntity[]
  conditions: MedicalEntity[]
  procedures: MedicalEntity[]
  tests: MedicalEntity[]
  other: MedicalEntity[]
}

// ── User Profile Types ────────────────────────────────────

export interface UserPublic {
  id: number
  email: string
  first_name: string
  last_name: string
  specialty: string | null
  hospital: string | null
  license_no: string | null
  note_style_preset?: NoteStylePreset
  preferred_focus?: PreferredFocus
  include_bullets_in_plan?: boolean
  include_patient_friendly_language?: boolean
}

// ── Web Speech API Declarations ───────────────────────────

export interface SpeechRecognitionResultItem {
  transcript: string
  confidence: number
}

export interface SpeechRecognitionResult {
  readonly length: number
  item(index: number): SpeechRecognitionResultItem
  [index: number]: SpeechRecognitionResultItem
  isFinal: boolean
}

export interface SpeechRecognitionResultList {
  readonly length: number
  item(index: number): SpeechRecognitionResult
  [index: number]: SpeechRecognitionResult
}

export interface ISpeechRecognitionEvent extends Event {
  resultIndex: number
  results: SpeechRecognitionResultList
}

export interface ISpeechRecognitionErrorEvent extends Event {
  error: string
  message?: string
}

export interface ISpeechRecognition extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  maxAlternatives: number
  onstart: ((this: ISpeechRecognition, ev: Event) => void) | null
  onend: ((this: ISpeechRecognition, ev: Event) => void) | null
  onerror: ((this: ISpeechRecognition, ev: ISpeechRecognitionErrorEvent) => void) | null
  onresult: ((this: ISpeechRecognition, ev: ISpeechRecognitionEvent) => void) | null
  start(): void
  stop(): void
  abort(): void
}
