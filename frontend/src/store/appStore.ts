import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type {
  BackendHealthStatus,
  ConsultationRecord,
  EncounterType,
  NoteStylePreset,
  PreferredFocus,
  TranscriptionResult,
  UploadState,
  UserPublic,
} from '../types'
import { clearStoredToken } from '../services/api'

interface UserProfile {
  firstName: string
  lastName: string
  email: string
  specialty: string
  hospital: string
  licenseNo: string
  noteStylePreset: NoteStylePreset
  preferredFocus: PreferredFocus
  includeBulletsInPlan: boolean
  includePatientFriendlyLanguage: boolean
}

const DEFAULT_PROFILE: UserProfile = {
  firstName: 'Dr. Jane',
  lastName: 'Wilson',
  email: 'clinician@mediscribe.ai',
  specialty: 'Internal Medicine',
  hospital: 'St. Jude General Hospital',
  licenseNo: 'MD-92817',
  noteStylePreset: 'balanced',
  preferredFocus: 'general',
  includeBulletsInPlan: false,
  includePatientFriendlyLanguage: false,
}

interface AppState {
  // Auth State
  isAuthenticated: boolean
  authUser: UserPublic | null
  setAuth: (user: UserPublic) => void
  clearAuth: () => void

  // Health Status
  backendHealth: BackendHealthStatus
  setBackendHealth: (health: BackendHealthStatus) => void

  // Consultations & Active Session
  consultations: ConsultationRecord[]
  setConsultations: (records: ConsultationRecord[]) => void
  addConsultation: (record: ConsultationRecord) => void
  removeConsultation: (id: string) => void

  // Active Working Consultation
  activeConsultation: ConsultationRecord | null
  setActiveConsultation: (record: ConsultationRecord | null) => void

  // Upload & Transcription Flow State
  uploadState: UploadState
  selectedFile: File | null
  consultationTitle: string
  selectedEncounterType: EncounterType
  styleOverridePreset: NoteStylePreset | null
  processingStatus: string
  errorMessage: string | null
  transcriptionResult: TranscriptionResult | null

  setFile: (file: File | null) => void
  setConsultationTitle: (title: string) => void
  setEncounterType: (type: EncounterType) => void
  setStyleOverridePreset: (preset: NoteStylePreset | null) => void
  setUploadState: (state: UploadState) => void
  setProcessingStatus: (status: string) => void
  setErrorMessage: (msg: string | null) => void
  setTranscriptionResult: (result: TranscriptionResult | null) => void
  resetUpload: () => void

  // Clinician Settings & Profile
  profile: UserProfile
  updateProfile: (p: Partial<UserProfile>) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // Auth: Defaults to true for local/demo clinician experience if token or demo user
      isAuthenticated: true,
      authUser: {
        id: 1,
        email: 'clinician@mediscribe.ai',
        first_name: 'Jane',
        last_name: 'Wilson',
        specialty: 'Internal Medicine',
        hospital: 'St. Jude General Hospital',
        license_no: 'MD-92817',
        note_style_preset: 'balanced',
        preferred_focus: 'general',
        include_bullets_in_plan: false,
        include_patient_friendly_language: false,
      },
      setAuth: (user) =>
        set({
          isAuthenticated: true,
          authUser: user,
          profile: {
            firstName: user.first_name,
            lastName: user.last_name,
            email: user.email,
            specialty: user.specialty ?? 'General Practice',
            hospital: user.hospital ?? 'Clinic',
            licenseNo: user.license_no ?? '',
            noteStylePreset: user.note_style_preset ?? 'balanced',
            preferredFocus: user.preferred_focus ?? 'general',
            includeBulletsInPlan: user.include_bullets_in_plan ?? false,
            includePatientFriendlyLanguage: user.include_patient_friendly_language ?? false,
          },
        }),
      clearAuth: () => {
        clearStoredToken()
        set({ isAuthenticated: false, authUser: null })
      },

      // Backend Health
      backendHealth: {
        isConnected: false,
        status: 'checking',
        service: 'MediScribe AI Backend',
        latencyMs: 0,
      },
      setBackendHealth: (health) => set({ backendHealth: health }),

      // Consultations
      consultations: [],
      setConsultations: (records) => set({ consultations: records }),
      addConsultation: (record) =>
        set((state) => ({
          consultations: [record, ...state.consultations.filter((c) => c.id !== record.id)],
        })),
      removeConsultation: (id) =>
        set((state) => ({
          consultations: state.consultations.filter((c) => c.id !== id),
          activeConsultation: state.activeConsultation?.id === id ? null : state.activeConsultation,
        })),

      // Active Consultation
      activeConsultation: null,
      setActiveConsultation: (record) => set({ activeConsultation: record }),

      // Upload flow
      uploadState: 'idle',
      selectedFile: null,
      consultationTitle: '',
      selectedEncounterType: 'acute_visit',
      styleOverridePreset: null,
      processingStatus: '',
      errorMessage: null,
      transcriptionResult: null,

      setFile: (file) => set({ selectedFile: file, errorMessage: null }),
      setConsultationTitle: (title) => set({ consultationTitle: title }),
      setEncounterType: (type) => set({ selectedEncounterType: type }),
      setStyleOverridePreset: (preset) => set({ styleOverridePreset: preset }),
      setUploadState: (state) => set({ uploadState: state }),
      setProcessingStatus: (status) => set({ processingStatus: status }),
      setErrorMessage: (msg) => set({ errorMessage: msg }),
      setTranscriptionResult: (result) => set({ transcriptionResult: result }),
      resetUpload: () =>
        set({
          selectedFile: null,
          consultationTitle: '',
          uploadState: 'idle',
          processingStatus: '',
          errorMessage: null,
          transcriptionResult: null,
        }),

      // Profile
      profile: DEFAULT_PROFILE,
      updateProfile: (p) => set((state) => ({ profile: { ...state.profile, ...p } })),
    }),
    {
      name: 'mediscribe_app_store',
      partialize: (state) => ({
        profile: state.profile,
        authUser: state.authUser,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
)
