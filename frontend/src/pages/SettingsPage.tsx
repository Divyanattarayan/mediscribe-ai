import { useState } from 'react'
import {
  Settings,
  Server,
  Activity,
  ShieldCheck,
  ShieldAlert,
  Info,
  CheckCircle2,
  XCircle,
  RefreshCw,
  User,
  Sliders,
  Lock,
  Cpu,
  Database,
  ExternalLink,
  Sparkles,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAppStore } from '../store/appStore'
import { checkBackendHealth, API_BASE_URL, updateCurrentUser } from '../services/api'
import { Button, Card, CardHeader, CardBody, Badge } from '../components/ui'
import type { NoteStylePreset, PreferredFocus } from '../types'

export default function SettingsPage() {
  const {
    profile,
    updateProfile,
    backendHealth,
    setBackendHealth,
  } = useAppStore()

  // Profile Form State
  const [firstName, setFirstName] = useState(profile.firstName)
  const [lastName, setLastName] = useState(profile.lastName)
  const [specialty, setSpecialty] = useState(profile.specialty)
  const [hospital, setHospital] = useState(profile.hospital)
  const [licenseNo, setLicenseNo] = useState(profile.licenseNo)
  const [noteStylePreset, setNoteStylePreset] = useState<NoteStylePreset>(profile.noteStylePreset)
  const [preferredFocus, setPreferredFocus] = useState<PreferredFocus>(profile.preferredFocus)
  const [includeBullets, setIncludeBullets] = useState(profile.includeBulletsInPlan)
  const [includePatientFriendly, setIncludePatientFriendly] = useState(profile.includePatientFriendlyLanguage)

  const [isPinging, setIsPinging] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  // Live Ping Backend Health
  const handlePingHealth = async () => {
    setIsPinging(true)
    try {
      const health = await checkBackendHealth()
      setBackendHealth(health)
      if (health.isConnected) {
        toast.success(`Backend connected (${health.latencyMs}ms latency)`)
      } else {
        toast.error('Backend is unreachable', { description: health.error || undefined })
      }
    } finally {
      setIsPinging(false)
    }
  }

  // Save Clinician Profile & Preferences
  const handleSaveProfile = async () => {
    setIsSaving(true)
    const updated = {
      firstName,
      lastName,
      specialty,
      hospital,
      licenseNo,
      noteStylePreset,
      preferredFocus,
      includeBulletsInPlan: includeBullets,
      includePatientFriendlyLanguage: includePatientFriendly,
    }

    updateProfile(updated)

    try {
      await updateCurrentUser({
        first_name: firstName,
        last_name: lastName,
        specialty,
        hospital,
        license_no: licenseNo,
        note_style_preset: noteStylePreset,
        preferred_focus: preferredFocus,
        include_bullets_in_plan: includeBullets,
        include_patient_friendly_language: includePatientFriendly,
      })
      toast.success('Clinician profile and documentation settings updated')
    } catch {
      // Local store is already updated
      toast.success('Settings saved to local clinician session')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="space-y-8 max-w-5xl mx-auto animate-in fade-in duration-150">
      {/* Header */}
      <div className="pb-4 border-b border-[#E2E8F0]">
        <div className="flex items-center gap-2">
          <Badge tone="teal">System & Profile</Badge>
          <span className="text-xs text-[#64748B]">Configuration Console</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold text-[#0F172A] tracking-tight mt-1">
          Settings & Environment
        </h1>
        <p className="text-sm text-[#475569] mt-0.5">
          Verify backend connectivity, review safe architecture credentials, and customize documentation prose preferences.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Diagnostics & System Architecture */}
        <div className="lg:col-span-6 space-y-6">
          {/* ── 1. Backend Connection Status Card ───────────── */}
          <Card>
            <CardHeader
              title="Backend Connection Status"
              actions={
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<RefreshCw size={12} className={isPinging ? 'animate-spin' : ''} />}
                  onClick={handlePingHealth}
                  disabled={isPinging}
                >
                  Ping Health
                </Button>
              }
            />
            <CardBody className="p-5 space-y-4">
              <div className="flex items-center justify-between p-4 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC]">
                <div className="flex items-center gap-3">
                  <div
                    className={`size-10 rounded-xl flex items-center justify-center ${
                      backendHealth.isConnected
                        ? 'bg-[#ECFDF5] text-[#047857]'
                        : 'bg-[#FEF2F2] text-[#B91C1C]'
                    }`}
                  >
                    <Server size={20} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm text-[#0F172A]">
                        {backendHealth.service || 'MediScribe AI Backend API'}
                      </span>
                      {backendHealth.isConnected ? (
                        <Badge tone="ok" dot>Healthy</Badge>
                      ) : (
                        <Badge tone="danger" dot>Offline</Badge>
                      )}
                    </div>
                    <span className="text-xs text-[#64748B] font-mono">
                      {API_BASE_URL}
                    </span>
                  </div>
                </div>

                {backendHealth.isConnected && (
                  <div className="text-right font-mono">
                    <span className="text-xs text-[#64748B] block">Latency</span>
                    <span className="text-sm font-bold text-[#047857]">
                      {backendHealth.latencyMs} ms
                    </span>
                  </div>
                )}
              </div>

              {backendHealth.error && (
                <div className="p-3.5 rounded-lg border border-[#FECACA] bg-[#FEF2F2] text-xs text-[#991B1B] leading-relaxed">
                  <strong>Connection Error:</strong> {backendHealth.error}. If running locally, please start the FastAPI server with <code>uvicorn main:app --reload</code> on port 8000.
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="p-3 rounded-lg border border-[#E2E8F0] bg-white">
                  <span className="text-[#64748B] block text-2xs uppercase tracking-wider font-semibold">
                    API Endpoint
                  </span>
                  <span className="font-mono text-[#0F172A] mt-0.5 block truncate">
                    GET /health
                  </span>
                </div>
                <div className="p-3 rounded-lg border border-[#E2E8F0] bg-white">
                  <span className="text-[#64748B] block text-2xs uppercase tracking-wider font-semibold">
                    Last Health Probe
                  </span>
                  <span className="font-mono text-[#0F172A] mt-0.5 block">
                    {backendHealth.checkedAt || 'Just now'}
                  </span>
                </div>
              </div>
            </CardBody>
          </Card>

          {/* ── 2. Safe Configuration & Security Guidance ────── */}
          <Card>
            <CardHeader title="Safe Configuration & Security Guidance" />
            <CardBody className="p-5 space-y-3.5 text-xs text-[#475569] leading-relaxed">
              <div className="p-3.5 rounded-xl border border-[#CCFBF1] bg-[#F0FDFA] flex items-start gap-2.5 text-[#0F766E]">
                <ShieldCheck size={18} className="shrink-0 mt-0.5 text-[#0D9488]" />
                <div>
                  <strong className="font-semibold block text-sm text-[#0F172A]">
                    Secrets Isolation Principle
                  </strong>
                  MediScribe AI enforces strict isolation between client and server credentials. Secrets such as <code>JWT_SECRET_KEY</code>, <code>DATABASE_URL</code>, and <code>GROQ_API_KEY</code> are confined strictly to the backend environment and never bundled into the client build.
                </div>
              </div>

              <div className="space-y-2">
                <h4 className="font-semibold text-[#0F172A]">Frontend Environment Variables:</h4>
                <div className="p-3 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] font-mono text-[11px] text-[#0F172A]">
                  <div>VITE_API_URL={API_BASE_URL}</div>
                </div>
                <p className="text-[11px] text-[#64748B]">
                  Only non-sensitive URLs are passed to the frontend. Never prefix API keys with <code>VITE_</code>.
                </p>
              </div>

              <div className="space-y-2 pt-2 border-t border-[#E2E8F0]">
                <h4 className="font-semibold text-[#0F172A]">HIPAA & Clinical Compliance Notice:</h4>
                <p>
                  Audio recordings are cached under UUIDs and purged after transcription. All entity assertions (negation, temporality) are verified prior to note generation to prevent clinical misrepresentations.
                </p>
              </div>
            </CardBody>
          </Card>

          {/* ── 3. Application Architecture Specifications ───── */}
          <Card>
            <CardHeader title="Application Architecture" />
            <CardBody className="p-5 space-y-3">
              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between py-1.5 border-b border-[#E2E8F0]">
                  <span className="text-[#64748B] flex items-center gap-1.5">
                    <Cpu size={14} /> Speech Recognition
                  </span>
                  <span className="font-mono font-medium text-[#0F172A]">
                    faster-whisper (small.en, int8)
                  </span>
                </div>
                <div className="flex items-center justify-between py-1.5 border-b border-[#E2E8F0]">
                  <span className="text-[#64748B] flex items-center gap-1.5">
                    <Activity size={14} /> Biomedical NER
                  </span>
                  <span className="font-mono font-medium text-[#0F172A]">
                    scispaCy en_ner_bc5cdr_md
                  </span>
                </div>
                <div className="flex items-center justify-between py-1.5 border-b border-[#E2E8F0]">
                  <span className="text-[#64748B] flex items-center gap-1.5">
                    <ShieldCheck size={14} /> Assertion Algorithm
                  </span>
                  <span className="font-mono font-medium text-[#0F172A]">
                    medspaCy ConText (Neg/Temp/Exp)
                  </span>
                </div>
                <div className="flex items-center justify-between py-1.5 border-b border-[#E2E8F0]">
                  <span className="text-[#64748B] flex items-center gap-1.5">
                    <Sparkles size={14} /> LLM Provider
                  </span>
                  <span className="font-mono font-medium text-[#0F172A]">
                    Groq / Gemini Multi-Provider
                  </span>
                </div>
                <div className="flex items-center justify-between py-1.5">
                  <span className="text-[#64748B] flex items-center gap-1.5">
                    <Database size={14} /> Database & Migrations
                  </span>
                  <span className="font-mono font-medium text-[#0F172A]">
                    PostgreSQL 16 + Alembic (v0005)
                  </span>
                </div>
              </div>
            </CardBody>
          </Card>
        </div>

        {/* Right Column: Clinician Profile & Documentation Preferences */}
        <div className="lg:col-span-6 space-y-6">
          <Card>
            <CardHeader title="Clinician Profile & Identity" />
            <CardBody className="p-5 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-[#475569] mb-1">
                    First Name
                  </label>
                  <input
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] text-xs sm:text-sm text-[#0F172A] focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-[#475569] mb-1">
                    Last Name
                  </label>
                  <input
                    type="text"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] text-xs sm:text-sm text-[#0F172A] focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#475569] mb-1">
                  Primary Medical Specialty
                </label>
                <input
                  type="text"
                  value={specialty}
                  onChange={(e) => setSpecialty(e.target.value)}
                  placeholder="e.g. Internal Medicine, Cardiology, Pediatrics"
                  className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] text-xs sm:text-sm text-[#0F172A] focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-[#475569] mb-1">
                    Hospital / Clinical Facility
                  </label>
                  <input
                    type="text"
                    value={hospital}
                    onChange={(e) => setHospital(e.target.value)}
                    placeholder="e.g. St. Jude General Hospital"
                    className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] text-xs sm:text-sm text-[#0F172A] focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-[#475569] mb-1">
                    Medical License #
                  </label>
                  <input
                    type="text"
                    value={licenseNo}
                    onChange={(e) => setLicenseNo(e.target.value)}
                    placeholder="e.g. MD-92817"
                    className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] text-xs sm:text-sm font-mono text-[#0F172A] focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                  />
                </div>
              </div>
            </CardBody>
          </Card>

          {/* Documentation Preferences */}
          <Card>
            <CardHeader title="SOAP Note Generation Preferences" />
            <CardBody className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-[#475569] mb-1.5">
                  Default Note Style Preset
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {(['balanced', 'concise', 'detailed'] as NoteStylePreset[]).map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => setNoteStylePreset(preset)}
                      className={`p-2.5 rounded-lg border text-xs capitalize font-medium transition-colors ${
                        noteStylePreset === preset
                          ? 'border-[#0D9488] bg-[#F0FDFA] text-[#0F766E] font-semibold ring-1 ring-[#0D9488]'
                          : 'border-[#CBD5E1] bg-white text-[#475569] hover:bg-[#F8FAFC]'
                      }`}
                    >
                      {preset}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#475569] mb-1.5">
                  Clinical Focus Emphasis
                </label>
                <select
                  value={preferredFocus}
                  onChange={(e) => setPreferredFocus(e.target.value as PreferredFocus)}
                  className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] bg-white text-xs sm:text-sm text-[#0F172A] focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                >
                  <option value="general">General Comprehensive</option>
                  <option value="symptom_driven">Symptom-Driven (Emphasizes HPI & ROS)</option>
                  <option value="assessment_driven">Assessment-Driven (Differential emphasis)</option>
                  <option value="plan_driven">Plan-Driven (Actionable items & orders)</option>
                </select>
              </div>

              <div className="space-y-3 pt-2">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={includeBullets}
                    onChange={(e) => setIncludeBullets(e.target.checked)}
                    className="size-4 accent-[#0D9488] rounded"
                  />
                  <span className="text-xs text-[#0F172A]">
                    Format plan section with bulleted order checklists
                  </span>
                </label>

                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={includePatientFriendly}
                    onChange={(e) => setIncludePatientFriendly(e.target.checked)}
                    className="size-4 accent-[#0D9488] rounded"
                  />
                  <span className="text-xs text-[#0F172A]">
                    Include layperson patient-friendly discharge explanation summary
                  </span>
                </label>
              </div>

              <div className="pt-3 border-t border-[#E2E8F0]">
                <Button
                  variant="primary"
                  loading={isSaving}
                  onClick={handleSaveProfile}
                  className="w-full"
                >
                  Save Profile & Documentation Settings
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  )
}
