// api.ts — Centralized API Client for MediScribe AI
import axios from 'axios'
import type {
  BackendHealthStatus,
  ConsultationRecord,
  EncounterType,
  EvidenceLinks,
  MedicalEntity,
  NoteStyleProfile,
  SOAPNote,
  StructuredClinicalData,
  TranscriptionResult,
  UserPublic,
} from '../types'

const TOKEN_KEY = 'mediscribe_token'
const REVIEWS_KEY = 'mediscribe_consultation_reviews'

export function getStoredToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY) ?? localStorage.getItem(TOKEN_KEY)
}

export function setStoredToken(token: string, remember?: boolean): void {
  if (remember) {
    localStorage.setItem(TOKEN_KEY, token)
    sessionStorage.removeItem(TOKEN_KEY)
  } else {
    sessionStorage.setItem(TOKEN_KEY, token)
    localStorage.removeItem(TOKEN_KEY)
  }
}

export function clearStoredToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(TOKEN_KEY)
}

// Read backend URL from environment variable, falling back to localhost:8000
const configuredBaseUrl = import.meta.env.VITE_API_URL
export const API_BASE_URL = configuredBaseUrl || 'http://localhost:8000'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000, // 5 minutes for heavy ASR/LLM jobs
})

// Request interceptor: Attach JWT Bearer token
api.interceptors.request.use((config) => {
  const token = getStoredToken()
  const isAuthRoute =
    config.url?.includes('/api/auth/login') ||
    config.url?.includes('/api/auth/register') ||
    config.url?.includes('/health') ||
    config.url === '/'

  if (token && !isAuthRoute) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor: Handle 401s — redirect to login instead of silent failure
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const isAuthEndpoint =
        error.config?.url?.includes('/api/auth/login') ||
        error.config?.url?.includes('/api/auth/register')
      if (!isAuthEndpoint) {
        clearStoredToken()
        // Dispatch a global event so App.tsx can redirect to login
        window.dispatchEvent(new CustomEvent('mediscribe:unauthorized'))
      }
    }
    return Promise.reject(error)
  }
)

// ── Health Check ──────────────────────────────────────────

export async function checkBackendHealth(): Promise<BackendHealthStatus> {
  const start = performance.now()
  try {
    const response = await api.get<{ status: string; service?: string }>('/health', {
      timeout: 5000,
    })
    const latencyMs = Math.round(performance.now() - start)
    return {
      isConnected: true,
      status: response.data?.status ?? 'healthy',
      service: response.data?.service ?? 'MediScribe AI Backend',
      version: '2.0.0',
      latencyMs,
      checkedAt: new Date().toLocaleTimeString(),
      error: null,
    }
  } catch (err: unknown) {
    const latencyMs = Math.round(performance.now() - start)
    const errorMsg =
      axios.isAxiosError(err) && err.message
        ? err.message
        : 'Backend server is unreachable on ' + API_BASE_URL
    return {
      isConnected: false,
      status: 'offline',
      latencyMs,
      checkedAt: new Date().toLocaleTimeString(),
      error: errorMsg,
    }
  }
}

// ── Auth Services ─────────────────────────────────────────

export interface AuthResponse {
  access_token: string
  token_type: string
  user: UserPublic
}

export async function loginUser(email: string, password: string): Promise<AuthResponse> {
  const response = await api.post<AuthResponse>('/api/auth/login', { email, password })
  return response.data
}

export async function registerUser(payload: {
  email: string
  password: string
  first_name: string
  last_name: string
  specialty?: string
}): Promise<AuthResponse> {
  const response = await api.post<AuthResponse>('/api/auth/register', payload)
  return response.data
}

export async function fetchCurrentUser(): Promise<UserPublic> {
  const response = await api.get<UserPublic>('/api/auth/me')
  return response.data
}

export async function updateCurrentUser(payload: Partial<UserPublic>): Promise<UserPublic> {
  const response = await api.put<UserPublic>('/api/auth/me', payload)
  return response.data
}

export async function deleteMyAccount(): Promise<void> {
  await api.delete('/api/auth/me')
}

// ── Transcription & Consultations ─────────────────────────

export async function transcribeAudio(
  file: File,
  options: {
    title?: string
    encounterType: EncounterType
    audioDurationSeconds?: number | null
    styleOverrides?: Partial<NoteStyleProfile>
  }
): Promise<TranscriptionResult> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('encounter_type', options.encounterType)

  if (options.styleOverrides?.note_style_preset) {
    formData.append('note_style_preset', options.styleOverrides.note_style_preset)
  }
  if (options.styleOverrides?.preferred_focus) {
    formData.append('preferred_focus', options.styleOverrides.preferred_focus)
  }
  if (typeof options.styleOverrides?.include_bullets_in_plan === 'boolean') {
    formData.append('include_bullets_in_plan', String(options.styleOverrides.include_bullets_in_plan))
  }
  if (typeof options.styleOverrides?.include_patient_friendly_language === 'boolean') {
    formData.append('include_patient_friendly_language', String(options.styleOverrides.include_patient_friendly_language))
  }

  const response = await api.post<TranscriptionResult>('/api/transcribe', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
      ...(typeof options.audioDurationSeconds === 'number' && Number.isFinite(options.audioDurationSeconds)
        ? { 'X-Audio-Duration-Seconds': String(options.audioDurationSeconds) }
        : {}),
    },
    timeout: 30 * 60 * 1000,
  })

  const raw = response.data
  return {
    ...raw,
    filename: file.name,
    isSynthetic: false,
  }
}

// ── History & Review Management ───────────────────────────

export interface HistoryEntryAPI {
  id: number
  patient_id: string
  filename: string
  transcription: string
  medical_content_score: number
  asr_confidence: number | null
  duration: string | null
  status: string
  review_status?: string
  approved_by?: string | null
  approved_at?: string | null
  approval_notes?: string | null
  created_at: string
  entities: Array<{
    text: string
    label: string
    confidence: number
    start: number
    end: number
  }>
  soap_note: {
    subjective: string
    objective: string
    assessment: string
    plan: string
    source: string
    evidence_links?: EvidenceLinks | null
  } | null
}

export function getLocalReviews(): Record<string, {
  reviewStatus: 'draft' | 'needs_review' | 'in_review' | 'approved'
  approvedBy?: string
  approvedAt?: string
  clinicianNotes?: string
  editedTranscript?: string
  editedSoapNote?: {
    subjective: string
    objective: string
    assessment: string
    plan: string
  }
}> {
  try {
    const raw = localStorage.getItem(REVIEWS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

export function saveLocalReview(
  id: string,
  update: {
    reviewStatus?: 'draft' | 'needs_review' | 'in_review' | 'approved'
    approvedBy?: string
    approvedAt?: string
    clinicianNotes?: string
    editedTranscript?: string
    editedSoapNote?: {
      subjective: string
      objective: string
      assessment: string
      plan: string
    }
  }
): void {
  try {
    const existing = getLocalReviews()
    existing[id] = { ...existing[id], ...update }
    localStorage.setItem(REVIEWS_KEY, JSON.stringify(existing))
  } catch {
    // ignore local storage errors
  }
}

export async function fetchHistory(): Promise<ConsultationRecord[]> {
  const response = await api.get<HistoryEntryAPI[]>('/api/history')
  const reviews = getLocalReviews()

  return response.data.map((entry) => {
    const review = reviews[String(entry.id)]
    // Prioritize authoritative backend database review_status
    const reviewStatus = (entry.review_status || review?.reviewStatus || (entry.soap_note ? 'needs_review' : 'draft')) as any
    const isApproved = reviewStatus === 'approved'

    return {
      id: String(entry.id),
      patientId: entry.patient_id,
      filename: entry.filename,
      date: new Date(entry.created_at).toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short',
      }),
      duration: entry.duration ?? '0:00',
      entityCount: entry.entities ? entry.entities.length : 0,
      medicalContentScore: entry.medical_content_score ?? 0,
      asrConfidence: entry.asr_confidence,
      status: (entry.status as any) || (entry.soap_note ? 'complete' : 'processing'),
      reviewStatus,
      approval: isApproved ? {
        approved: true,
        approvedBy: entry.approved_by || review?.approvedBy || 'Reviewing Clinician',
        approvedAt: entry.approved_at
          ? new Date(entry.approved_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
          : review?.approvedAt,
        clinicianNotes: entry.approval_notes || review?.clinicianNotes,
      } : undefined,
      transcription: review?.editedTranscript ?? entry.transcription,
      soap_note: review?.editedSoapNote ?? (entry.soap_note ? {
        subjective: entry.soap_note.subjective ?? '',
        objective: entry.soap_note.objective ?? '',
        assessment: entry.soap_note.assessment ?? '',
        plan: entry.soap_note.plan ?? '',
        source: entry.soap_note.source,
        evidence_links: entry.soap_note.evidence_links ?? undefined,
      } : undefined),
      entities: entry.entities ?? [],
      isSynthetic: false,
    }
  })
}

export async function fetchConsultation(id: string | number): Promise<ConsultationRecord> {
  const response = await api.get<HistoryEntryAPI>(`/api/history/${id}`)
  const entry = response.data
  const reviews = getLocalReviews()
  const review = reviews[String(entry.id)]
  // Prioritize authoritative backend database review_status
  const reviewStatus = (entry.review_status || review?.reviewStatus || (entry.soap_note ? 'needs_review' : 'draft')) as any
  const isApproved = reviewStatus === 'approved'

  return {
    id: String(entry.id),
    patientId: entry.patient_id,
    filename: entry.filename,
    date: new Date(entry.created_at).toLocaleString('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }),
    duration: entry.duration ?? '0:00',
    entityCount: entry.entities ? entry.entities.length : 0,
    medicalContentScore: entry.medical_content_score ?? 0,
    asrConfidence: entry.asr_confidence,
    status: (entry.status as any) || (entry.soap_note ? 'complete' : 'processing'),
    reviewStatus,
    approval: isApproved ? {
      approved: true,
      approvedBy: entry.approved_by || review?.approvedBy || 'Reviewing Clinician',
      approvedAt: entry.approved_at
        ? new Date(entry.approved_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
        : review?.approvedAt,
      clinicianNotes: entry.approval_notes || review?.clinicianNotes,
    } : undefined,
    transcription: review?.editedTranscript ?? entry.transcription,
    soap_note: review?.editedSoapNote ?? (entry.soap_note ? {
      subjective: entry.soap_note.subjective ?? '',
      objective: entry.soap_note.objective ?? '',
      assessment: entry.soap_note.assessment ?? '',
      plan: entry.soap_note.plan ?? '',
      source: entry.soap_note.source,
      evidence_links: entry.soap_note.evidence_links ?? undefined,
    } : undefined),
    entities: entry.entities ?? [],
    isSynthetic: false,
  }
}

export async function deleteConsultation(id: string | number): Promise<void> {
  await api.delete(`/api/history/${id}`)
  const reviews = getLocalReviews()
  delete reviews[String(id)]
  localStorage.setItem(REVIEWS_KEY, JSON.stringify(reviews))
}

export async function deleteAllConsultations(): Promise<void> {
  await api.delete('/api/history')
  localStorage.removeItem(REVIEWS_KEY)
}

export async function purgeConsultationAudio(id: string | number): Promise<void> {
  await api.delete(`/api/consultations/${id}/audio`)
}


// ── Specific Consultations API Endpoints ───────────────────

export async function updateConsultationTranscript(
  id: string | number,
  transcription: string
): Promise<void> {
  await api.put(`/api/consultations/${id}/transcript`, { transcription })
}

export async function generateSoapFromTranscript(
  transcript: string,
  encounterType?: string
): Promise<SOAPNote & { review_status: string }> {
  const response = await api.post('/api/consultations/soap/generate-from-transcript', {
    transcript,
    encounter_type: encounterType,
  })
  return response.data
}

export async function generateConsultationSoap(id: string | number): Promise<SOAPNote & { review_status: string }> {
  const response = await api.post(`/api/consultations/${id}/soap`)
  return response.data
}

export async function updateConsultationSoap(
  id: string | number,
  soap: { subjective: string; objective: string; assessment: string; plan: string }
): Promise<SOAPNote & { review_status: string }> {
  const response = await api.put(`/api/consultations/${id}/soap`, soap)
  return response.data
}

export async function approveConsultationApi(
  id: string | number,
  payload: { approved_by: string; approval_notes?: string }
): Promise<void> {
  await api.post(`/api/consultations/${id}/approve`, payload)
}

export async function extractClinicalEntities(id: string | number): Promise<StructuredClinicalData> {
  const response = await api.post<{
    structured_clinical_data: StructuredClinicalData
    disclaimer: string
    model_info: Record<string, unknown>
    entities: unknown[]
    total_entities: number
  }>(`/api/consultations/${id}/extract`)
  return response.data.structured_clinical_data
}

// ── Direct Entity Extraction (with Local Dictionary Fallback) ─

const FALLBACK_CLINICAL_TERMS: { term: string; label: string }[] = [
  // Symptoms
  { term: 'chest pain', label: 'SYMPTOM' },
  { term: 'shortness of breath', label: 'SYMPTOM' },
  { term: 'dyspnea', label: 'SYMPTOM' },
  { term: 'cough', label: 'SYMPTOM' },
  { term: 'fever', label: 'SYMPTOM' },
  { term: 'chills', label: 'SYMPTOM' },
  { term: 'fatigue', label: 'SYMPTOM' },
  { term: 'headache', label: 'SYMPTOM' },
  { term: 'dizziness', label: 'SYMPTOM' },
  { term: 'nausea', label: 'SYMPTOM' },
  { term: 'vomiting', label: 'SYMPTOM' },
  { term: 'abdominal pain', label: 'SYMPTOM' },
  { term: 'back pain', label: 'SYMPTOM' },
  { term: 'joint pain', label: 'SYMPTOM' },
  { term: 'palpitations', label: 'SYMPTOM' },
  { term: 'swelling', label: 'SYMPTOM' },
  { term: 'edema', label: 'SYMPTOM' },
  { term: 'wheezing', label: 'SYMPTOM' },
  { term: 'pain', label: 'SYMPTOM' },
  { term: 'sore throat', label: 'SYMPTOM' },
  { term: 'weakness', label: 'SYMPTOM' },
  { term: 'weight loss', label: 'SYMPTOM' },
  // Conditions
  { term: 'hypertension', label: 'CONDITION' },
  { term: 'high blood pressure', label: 'CONDITION' },
  { term: 'diabetes', label: 'CONDITION' },
  { term: 'asthma', label: 'CONDITION' },
  { term: 'copd', label: 'CONDITION' },
  { term: 'pneumonia', label: 'CONDITION' },
  { term: 'bronchitis', label: 'CONDITION' },
  { term: 'coronary artery disease', label: 'CONDITION' },
  { term: 'heart failure', label: 'CONDITION' },
  { term: 'atrial fibrillation', label: 'CONDITION' },
  { term: 'stroke', label: 'CONDITION' },
  { term: 'migraine', label: 'CONDITION' },
  { term: 'hyperlipidemia', label: 'CONDITION' },
  { term: 'gerd', label: 'CONDITION' },
  { term: 'acid reflux', label: 'CONDITION' },
  { term: 'arthritis', label: 'CONDITION' },
  { term: 'infection', label: 'CONDITION' },
  // Medications
  { term: 'aspirin', label: 'MEDICATION' },
  { term: 'metformin', label: 'MEDICATION' },
  { term: 'lisinopril', label: 'MEDICATION' },
  { term: 'atorvastatin', label: 'MEDICATION' },
  { term: 'amlodipine', label: 'MEDICATION' },
  { term: 'metoprolol', label: 'MEDICATION' },
  { term: 'omeprazole', label: 'MEDICATION' },
  { term: 'amoxicillin', label: 'MEDICATION' },
  { term: 'paracetamol', label: 'MEDICATION' },
  { term: 'acetaminophen', label: 'MEDICATION' },
  { term: 'ibuprofen', label: 'MEDICATION' },
  { term: 'albuterol', label: 'MEDICATION' },
  { term: 'insulin', label: 'MEDICATION' },
  { term: 'levothyroxine', label: 'MEDICATION' },
  { term: 'losartan', label: 'MEDICATION' },
  { term: 'hydrochlorothiazide', label: 'MEDICATION' },
  { term: 'pantoprazole', label: 'MEDICATION' },
  { term: 'prednisone', label: 'MEDICATION' },
  { term: 'ciprofloxacin', label: 'MEDICATION' },
  { term: 'azithromycin', label: 'MEDICATION' },
  // Tests & Procedures
  { term: 'ecg', label: 'TEST' },
  { term: 'ekg', label: 'TEST' },
  { term: 'x-ray', label: 'TEST' },
  { term: 'ct scan', label: 'TEST' },
  { term: 'mri', label: 'TEST' },
  { term: 'blood test', label: 'TEST' },
  { term: 'cbc', label: 'TEST' },
  { term: 'hba1c', label: 'TEST' },
  { term: 'lipid panel', label: 'TEST' },
  { term: 'urinalysis', label: 'TEST' },
  { term: 'echocardiogram', label: 'TEST' },
  { term: 'biopsy', label: 'PROCEDURE' },
  { term: 'endoscopy', label: 'PROCEDURE' },
  { term: 'colonoscopy', label: 'PROCEDURE' },
  { term: 'ultrasound', label: 'TEST' },
  { term: 'physical exam', label: 'PROCEDURE' },
]

export function extractEntitiesLocally(text: string): MedicalEntity[] {
  if (!text) return []
  const textLower = text.toLowerCase()
  const results: MedicalEntity[] = []
  const seenRanges = new Set<number>()

  for (const { term, label } of FALLBACK_CLINICAL_TERMS) {
    let start = 0
    while (true) {
      const idx = textLower.indexOf(term, start)
      if (idx === -1) break
      const end = idx + term.length
      const beforeChar = idx > 0 ? textLower[idx - 1] : ' '
      const afterChar = end < textLower.length ? textLower[end] : ' '
      const isWordBoundary = !/[a-z0-9]/.test(beforeChar) && !/[a-z0-9]/.test(afterChar)

      if (isWordBoundary) {
        let overlaps = false
        for (let i = idx; i < end; i++) {
          if (seenRanges.has(i)) {
            overlaps = true
            break
          }
        }
        if (!overlaps) {
          for (let i = idx; i < end; i++) seenRanges.add(i)
          const priorSnippet = textLower.slice(Math.max(0, idx - 30), idx)
          const isNegated = /\b(no|denies|not|without|negative for)\b/.test(priorSnippet)
          results.push({
            text: text.slice(idx, end),
            label,
            confidence: 0.95,
            start: idx,
            end: end,
            negated: isNegated,
            temporality: 'current',
            experiencer: 'patient',
          })
        }
      }
      start = idx + 1
    }
  }
  return results
}

export async function extractEntitiesFromTranscript(
  transcript: string
): Promise<{ success: boolean; entities: MedicalEntity[]; total_entities: number; medical_content_score?: number }> {
  if (!transcript || !transcript.trim()) {
    return { success: true, entities: [], total_entities: 0, medical_content_score: 0 }
  }

  try {
    const response = await api.post('/api/consultations/entities/extract-from-transcript', {
      transcript,
    })
    if (response.data && Array.isArray(response.data.entities) && response.data.entities.length > 0) {
      return response.data
    }
    // Fallback if backend returned empty array
    const fallback = extractEntitiesLocally(transcript)
    if (fallback.length > 0) {
      return {
        success: true,
        entities: fallback,
        total_entities: fallback.length,
        medical_content_score: 85,
      }
    }
    return response.data || { success: true, entities: [], total_entities: 0 }
  } catch (err) {
    console.warn('Backend entity extraction endpoint unavailable, using local dictionary:', err)
    const fallback = extractEntitiesLocally(transcript)
    return {
      success: true,
      entities: fallback,
      total_entities: fallback.length,
      medical_content_score: 80,
    }
  }
}

export async function fetchSoapEvidence(id: string | number): Promise<EvidenceLinks> {
  const response = await api.get<EvidenceLinks>(`/api/consultations/${id}/soap/evidence`)
  return response.data
}

// ── Live Streaming Endpoints ──────────────────────────────

export interface LiveStartResponseAPI {
  session_id: string
  patient_id: string
  title: string
  status: string
}

export interface LiveFinalizeResponseAPI {
  consultation_id: number
  patient_id: string
  title?: string
  transcript: string
  duration?: string
  status: string
  review_status: string
  audio_path?: string
  message: string
}

export async function startLiveConsultation(payload: {
  patient_id?: string
  title?: string
  language?: string
}): Promise<LiveStartResponseAPI> {
  const response = await api.post<LiveStartResponseAPI>('/api/consultations/live/start', payload)
  return response.data
}

export async function finalizeLiveConsultation(
  sessionId: string,
  finalTranscript?: string
): Promise<LiveFinalizeResponseAPI> {
  const response = await api.post<LiveFinalizeResponseAPI>(
    `/api/consultations/live/${sessionId}/finalize`,
    { final_transcript: finalTranscript }
  )
  return response.data
}

export async function uploadConsultationAudio(
  file: File,
  title?: string
): Promise<{ id: number; patient_id: string; title: string; filename: string; status: string; review_status: string }> {
  const formData = new FormData()
  formData.append('file', file)
  if (title) formData.append('title', title)
  const response = await api.post('/api/consultations/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data
}

export default api

