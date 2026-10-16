import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  FileText,
  Clock,
  CheckCircle2,
  AlertCircle,
  PlusCircle,
  ArrowRight,
  TrendingUp,
  Stethoscope,
  Sparkles,
  Search,
  ExternalLink,
  ChevronRight,
} from 'lucide-react'
import { useAppStore } from '../store/appStore'
import { fetchHistory } from '../services/api'
import { Button, Card, CardHeader, CardBody, Badge, EmptyState } from '../components/ui'
import type { ConsultationRecord } from '../types'

export default function DashboardPage() {
  const navigate = useNavigate()
  const {
    authUser,
    profile,
    consultations,
    setConsultations,
    backendHealth,
    addConsultation,
  } = useAppStore()

  const [isLoading, setIsLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Load consultations from backend on mount
  useEffect(() => {
    const loadRecords = async () => {
      setIsLoading(true)
      setLoadError(null)
      try {
        const records = await fetchHistory()
        setConsultations(records)
      } catch (err: unknown) {
        // If backend is offline or unauthorized, preserve cached consultations
        console.warn('Backend history fetch notice:', err)
      } finally {
        setIsLoading(false)
      }
    }
    loadRecords()
  }, [])

  // Calculate statistics from actual records
  const totalConsultations = consultations.length
  const draftNotes = consultations.filter((c) => c.reviewStatus === 'needs_review' || c.reviewStatus === 'draft').length
  const approvedNotes = consultations.filter((c) => c.reviewStatus === 'approved').length
  const recentConsultations = consultations.slice(0, 5)

  // Explicit Synthetic Demo loader for testing/evaluating without uploading audio
  const handleLoadSyntheticDemo = () => {
    const demoRecord: ConsultationRecord = {
      id: 'demo-' + Date.now(),
      patientId: 'PT-DEMO-2041',
      title: 'Routine Hypertension & Glycemic Follow-up',
      filename: 'sample_patient_consultation.mp3',
      date: new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }),
      duration: '04:15',
      entityCount: 14,
      medicalContentScore: 92.5,
      asrConfidence: 0.94,
      status: 'complete',
      reviewStatus: 'needs_review',
      isSynthetic: true,
      transcription:
        'Doctor: Good morning, Mrs. Davis. How have you been feeling since our last visit? Patient: Good morning, doctor. Generally well, but I had some mild dizziness a couple of mornings after taking my morning amlodipine. No chest pain, no palpitations, and shortness of breath has resolved. Doctor: That is reassuring that the shortness of breath is gone. Let us check your vitals. Blood pressure is 128 over 82, pulse is 72 regular. Blood glucose log shows morning fasting levels between 105 and 118. Patient: I have been sticking to the low-sodium diet and walking 30 minutes daily. Doctor: Excellent work. We will continue amlodipine 5 milligrams daily and metformin 500 milligrams twice daily. Let us order your routine HbA1c and basic metabolic panel for next month.',
      soap_note: {
        subjective:
          'Patient is a 58-year-old female returning for routine follow-up of hypertension and type 2 diabetes mellitus. Reports mild transient dizziness upon rising after morning medication, now resolving. Denies chest pain, palpitations, or orthopnea. Shortness of breath reported at prior visit has fully resolved. Adhering to low-sodium diet and exercise regimen.',
        objective:
          'Constitutional: Well-appearing, alert, in no acute distress.\nVitals: BP 128/82 mmHg, HR 72 bpm regular, SpO2 99% on room air.\nCardiovascular: Normal S1/S2, regular rate and rhythm, no murmurs.\nPulmonary: Clear to auscultation bilaterally, no wheezes or rales.\nHome logs: Fasting blood sugars 105–118 mg/dL.',
        assessment:
          '1. Essential hypertension: Well-controlled on current monotherapy. Transient postural symptoms noted.\n2. Type 2 diabetes mellitus: Good compliance with oral hypoglycemic agent and lifestyle modifications.\n3. Resolved dyspnea.',
        plan:
          '1. Continue Amlodipine 5 mg PO daily. Advised patient to rise slowly and maintain adequate hydration.\n2. Continue Metformin 500 mg PO twice daily with meals.\n3. Order HbA1c and Comprehensive Metabolic Panel (CMP) in 4 weeks.\n4. Follow-up in clinic in 6 weeks or sooner if dizziness worsens.',
        source: 'groq-llama-3.3-70b-versatile',
        generated_at: new Date().toISOString(),
      },
      entities: [
        { text: 'dizziness', label: 'SYMPTOM', confidence: 0.94, start: 162, end: 171 },
        { text: 'amlodipine', label: 'CHEMICAL', confidence: 0.98, start: 228, end: 238 },
        { text: 'chest pain', label: 'SYMPTOM', confidence: 0.95, start: 243, end: 253, negated: true },
        { text: 'palpitations', label: 'SYMPTOM', confidence: 0.96, start: 258, end: 270, negated: true },
        { text: 'shortness of breath', label: 'SYMPTOM', confidence: 0.96, start: 276, end: 295 },
        { text: 'metformin', label: 'CHEMICAL', confidence: 0.97, start: 620, end: 629 },
        { text: 'HbA1c', label: 'TEST', confidence: 0.95, start: 698, end: 703 },
        { text: 'basic metabolic panel', label: 'TEST', confidence: 0.93, start: 708, end: 729 },
      ],
    }

    addConsultation(demoRecord)
    navigate(`/consultations/${demoRecord.id}`)
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-150">
      {/* ── Welcome Header Section ───────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-[#E2E8F0]">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#0D9488] bg-[#F0FDFA] px-2 py-0.5 rounded border border-[#CCFBF1]">
              Clinician Workspace
            </span>
            <span className="text-xs text-[#64748B]">
              {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-[#0F172A] tracking-tight mt-1">
            Welcome back, {profile.firstName ? `${profile.firstName} ${profile.lastName}` : 'Doctor'}
          </h1>
          <p className="text-sm text-[#475569] mt-0.5">
            {profile.hospital || 'Hospital'} · {profile.specialty || 'General Practice'}
          </p>
        </div>

        {/* Primary Call to Action */}
        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            size="md"
            icon={<PlusCircle size={17} />}
            onClick={() => navigate('/consultations/new')}
            className="shadow-sm"
          >
            Start New Consultation
          </Button>
        </div>
      </div>

      {/* ── Metric Cards ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        {/* Total Consultations */}
        <Card className="hover:shadow-card transition-shadow">
          <CardBody className="flex items-center justify-between p-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">
                Total Consultations
              </p>
              <p className="text-3xl font-bold text-[#0F172A] mt-1 font-mono">
                {totalConsultations}
              </p>
              <p className="text-xs text-[#64748B] mt-1">Recorded in database</p>
            </div>
            <div className="size-12 rounded-xl bg-[#F0FDFA] border border-[#CCFBF1] text-[#0D9488] flex items-center justify-center">
              <FileText size={24} />
            </div>
          </CardBody>
        </Card>

        {/* Draft Notes (Awaiting Review) */}
        <Card className="hover:shadow-card transition-shadow">
          <CardBody className="flex items-center justify-between p-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-[#B45309]">
                Draft Notes Awaiting Review
              </p>
              <p className="text-3xl font-bold text-[#B45309] mt-1 font-mono">
                {draftNotes}
              </p>
              <p className="text-xs text-[#64748B] mt-1">Pending clinician sign-off</p>
            </div>
            <div className="size-12 rounded-xl bg-[#FFFBEB] border border-[#FDE68A] text-[#B45309] flex items-center justify-center">
              <Clock size={24} />
            </div>
          </CardBody>
        </Card>

        {/* Approved Notes */}
        <Card className="hover:shadow-card transition-shadow">
          <CardBody className="flex items-center justify-between p-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-[#047857]">
                Approved & Signed Notes
              </p>
              <p className="text-3xl font-bold text-[#047857] mt-1 font-mono">
                {approvedNotes}
              </p>
              <p className="text-xs text-[#64748B] mt-1">Clinician verified & completed</p>
            </div>
            <div className="size-12 rounded-xl bg-[#ECFDF5] border border-[#A7F3D0] text-[#047857] flex items-center justify-center">
              <CheckCircle2 size={24} />
            </div>
          </CardBody>
        </Card>
      </div>

      {/* ── Recent Consultations Section ─────────────────────── */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-[#0F172A] tracking-tight">
              Recent Consultation Records
            </h2>
            <p className="text-xs text-[#64748B]">
              Latest doctor-patient encounters processed through the ambient pipeline
            </p>
          </div>
          {totalConsultations > 0 && (
            <Link
              to="/history"
              className="text-xs font-semibold text-[#0D9488] hover:text-[#0F766E] flex items-center gap-1 hover:underline"
            >
              View all ({totalConsultations})
              <ChevronRight size={14} />
            </Link>
          )}
        </div>

        {totalConsultations === 0 ? (
          /* Empty State when no data exists */
          <EmptyState
            icon={<Stethoscope size={36} className="text-[#0D9488]" />}
            title="No consultation records yet"
            description="You haven't processed any clinical audio recordings yet. Start your first consultation to convert voice into structured SOAP notes with medical entity recognition."
            actionLabel="Start New Consultation"
            actionIcon={<PlusCircle size={16} />}
            onAction={() => navigate('/consultations/new')}
            secondaryActionLabel="Load Synthetic Demo Consultation"
            onSecondaryAction={handleLoadSyntheticDemo}
            disclaimer="The demo consultation is explicitly labelled as synthetic non-clinical test data for interface evaluation."
          />
        ) : (
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-xs font-semibold text-[#475569] uppercase tracking-wider">
                    <th className="py-3 px-4">Patient / ID</th>
                    <th className="py-3 px-4">Date & Time</th>
                    <th className="py-3 px-4">Audio Duration</th>
                    <th className="py-3 px-4">Medical Score</th>
                    <th className="py-3 px-4">Review Status</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E2E8F0]">
                  {recentConsultations.map((record) => {
                    const isApproved = record.reviewStatus === 'approved'
                    return (
                      <tr
                        key={record.id}
                        className="hover:bg-[#F8FAFC] transition-colors group cursor-pointer"
                        onClick={() => navigate(`/consultations/${record.id}`)}
                      >
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-semibold text-[#0F172A]">
                              {record.patientId}
                            </span>
                            {record.isSynthetic && (
                              <Badge tone="purple" className="text-[10px]">
                                Synthetic
                              </Badge>
                            )}
                          </div>
                          {record.title && (
                            <span className="text-xs text-[#64748B] block truncate max-w-xs">
                              {record.title}
                            </span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-xs text-[#475569]">
                          {record.date}
                        </td>
                        <td className="py-3.5 px-4 text-xs font-mono text-[#64748B]">
                          {record.duration}
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-1.5 font-mono text-xs text-[#0F172A]">
                            <span className="font-medium">
                              {Math.round(record.medicalContentScore)}%
                            </span>
                            <span className="text-[10px] text-[#64748B]">density</span>
                          </div>
                        </td>
                        <td className="py-3.5 px-4">
                          {isApproved ? (
                            <Badge tone="ok" dot>
                              Approved & Signed
                            </Badge>
                          ) : (
                            <Badge tone="warn" dot>
                              Needs Review
                            </Badge>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => navigate(`/consultations/${record.id}/transcript`)}
                            >
                              Transcript
                            </Button>
                            <Button
                              variant="teal-outline"
                              size="sm"
                              onClick={() => navigate(`/consultations/${record.id}/soap`)}
                            >
                              SOAP Note
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>

      {/* ── System Health & Safety Guidance ──────────────────── */}
      <Card className="bg-gradient-to-r from-[#F0FDFA] to-white border-[#CCFBF1]">
        <CardBody className="p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="size-10 rounded-xl bg-[#0D9488]/10 text-[#0D9488] flex items-center justify-center shrink-0 mt-0.5">
              <Sparkles size={20} />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-[#0F172A]">
                AI-Assisted Clinical Documentation Engine Ready
              </h4>
              <p className="text-xs text-[#475569] mt-0.5 leading-relaxed">
                MediScribe AI runs speech recognition via local Whisper, extracts biomedical entities using ConText assertions, and verifies note claims against verbatim transcript evidence.
              </p>
            </div>
          </div>
          <Button
            variant="secondary"
            size="sm"
            icon={<ExternalLink size={14} />}
            onClick={() => navigate('/settings')}
            className="shrink-0 text-xs"
          >
            System Diagnostics
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}
