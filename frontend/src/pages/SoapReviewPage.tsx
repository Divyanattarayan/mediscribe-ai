import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  FileText,
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  Clock,
  RotateCcw,
  Copy,
  Check,
  Download,
  AlertTriangle,
  Edit3,
  Stethoscope,
  Save,
  ArrowLeft,
  FileSignature,
  AlertCircle,
  FileSearch,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAppStore } from '../store/appStore'
import {
  fetchConsultation,
  saveLocalReview,
  updateConsultationSoap,
  generateConsultationSoap,
  generateSoapFromTranscript,
  approveConsultationApi,
  fetchSoapEvidence,
} from '../services/api'
import { Button, Card, CardHeader, CardBody, Badge, Modal } from '../components/ui'
import EvidenceReviewPanel from '../components/EvidenceReviewPanel'
import type { ConsultationRecord, SOAPNote, EvidenceLinks } from '../types'

export default function SoapReviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { consultations, addConsultation, profile } = useAppStore()

  const [consultation, setConsultation] = useState<ConsultationRecord | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // SOAP Drafts for inline editing
  const [subjective, setSubjective] = useState('')
  const [objective, setObjective] = useState('')
  const [assessment, setAssessment] = useState('')
  const [plan, setPlan] = useState('')

  // Original values for reset
  const [originalSoap, setOriginalSoap] = useState<SOAPNote | null>(null)

  // Editing state per section
  const [editingSection, setEditingSection] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)

  // Approval Modal State
  const [approvalModalOpen, setApprovalModalOpen] = useState(false)
  const [attestationChecked, setAttestationChecked] = useState(false)
  const [clinicianNotes, setClinicianNotes] = useState('')
  const [isApproving, setIsApproving] = useState(false)

  // View state: Note editor vs Evidence grounding audit
  const [activeView, setActiveView] = useState<'editor' | 'evidence'>('editor')
  const [evidenceLinks, setEvidenceLinks] = useState<EvidenceLinks | null>(null)
  const [isEvaluatingEvidence, setIsEvaluatingEvidence] = useState(false)

  // Load Consultation
  useEffect(() => {
    const loadRecord = async () => {
      if (!id) return
      setIsLoading(true)

      const local = consultations.find((c) => c.id === id)
      if (local && local.soap_note) {
        // Case 1: Local record already has a SOAP note — render it immediately
        setConsultation(local)
        setSubjective(local.soap_note.subjective || '')
        setObjective(local.soap_note.objective || '')
        setAssessment(local.soap_note.assessment || '')
        setPlan(local.soap_note.plan || '')
        setOriginalSoap(local.soap_note)
        if (local.soap_note.evidence_links) {
          setEvidenceLinks(local.soap_note.evidence_links)
        } else {
          fetchSoapEvidence(id).then(setEvidenceLinks).catch(() => {})
        }
        setIsLoading(false)
        return
      }

      // Case 2: Local-only consultation (live mic recording with cons-* ID)
      // Do NOT attempt a backend fetch — it will fail since there's no DB record.
      // Just surface the record so the "Generate SOAP Note" UI can appear.
      const isLocalOnly = id.startsWith('cons-')
      if (local && isLocalOnly) {
        setConsultation(local)
        setIsLoading(false)
        return
      }

      // Case 3: Backend-persisted consultation — fetch from API
      try {
        const fetched = await fetchConsultation(id)
        setConsultation(fetched)
        if (fetched.soap_note) {
          setSubjective(fetched.soap_note.subjective || '')
          setObjective(fetched.soap_note.objective || '')
          setAssessment(fetched.soap_note.assessment || '')
          setPlan(fetched.soap_note.plan || '')
          setOriginalSoap(fetched.soap_note)
          if (fetched.soap_note.evidence_links) {
            setEvidenceLinks(fetched.soap_note.evidence_links)
          } else {
            fetchSoapEvidence(id).then(setEvidenceLinks).catch(() => {})
          }
        }
        addConsultation(fetched)
      } catch (err) {
        toast.error('Failed to load consultation SOAP note.')
      } finally {
        setIsLoading(false)
      }
    }
    loadRecord()
  }, [id])


  const handleGenerateSoap = async () => {
    if (!consultation) return
    setIsGenerating(true)
    try {
      // Detect local-only consultations (live microphone recordings not yet in backend DB)
      // Their IDs start with 'cons-' (e.g. cons-1234567890) instead of numeric backend IDs
      const isLocalOnly = String(consultation.id).startsWith('cons-')
      const res = isLocalOnly
        ? await generateSoapFromTranscript(
            consultation.transcription || '',
          )
        : await generateConsultationSoap(consultation.id)
      const updatedRecord: ConsultationRecord = {
        ...consultation,
        reviewStatus: res.review_status as any,
        soap_note: res,
      }
      setConsultation(updatedRecord)
      addConsultation(updatedRecord)
      setSubjective(res.subjective || '')
      setObjective(res.objective || '')
      setAssessment(res.assessment || '')
      setPlan(res.plan || '')
      setOriginalSoap(res)
      if (res.evidence_links) {
        setEvidenceLinks(res.evidence_links)
      }
      toast.success('SOAP note generated successfully')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to generate SOAP note')
    } finally {
      setIsGenerating(false)
    }
  }

  const handleRefreshEvidence = async () => {
    if (!consultation) return
    setIsEvaluatingEvidence(true)
    try {
      const fresh = await fetchSoapEvidence(consultation.id)
      setEvidenceLinks(fresh)
      toast.success('Evidence links refreshed')
    } catch {
      toast.error('Failed to re-evaluate evidence links')
    } finally {
      setIsEvaluatingEvidence(false)
    }
  }

  if (isLoading) {
    return (
      <div className="py-20 flex flex-col items-center justify-center text-center space-y-4">
        <div className="size-10 rounded-full border-3 border-[#0D9488]/20 border-t-[#0D9488] animate-spin" />
        <p className="text-sm text-[#64748B]">Loading SOAP note draft...</p>
      </div>
    )
  }

  if (!consultation || !consultation.soap_note) {
    const isLocalOnly = consultation && String(consultation.id).startsWith('cons-')
    const hasTranscript = consultation && consultation.transcription && consultation.transcription.trim().length > 0

    return (
      <div className="py-16 text-center space-y-4 max-w-md mx-auto">
        <FileText size={40} className="mx-auto text-[#0D9488]" />
        <h2 className="text-lg font-bold text-[#0F172A]">Generate SOAP Note</h2>
        {isLocalOnly && !hasTranscript ? (
          <div className="p-4 rounded-xl border border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C] text-sm text-left">
            <strong className="block mb-1">No transcript found.</strong>
            The live recording transcript is empty. Please go back to the transcript review page and
            ensure your spoken consultation was captured before generating a SOAP note.
          </div>
        ) : (
          <p className="text-sm text-[#64748B]">
            {isLocalOnly
              ? 'Your live microphone transcript is ready. Synthesize a structured SOAP note from it using Groq AI.'
              : 'No generated note exists for this consultation record yet. Synthesize a clinical SOAP note using Groq AI.'}
          </p>
        )}
        <div className="flex justify-center gap-3 pt-2">
          <Button
            variant="ghost"
            onClick={() =>
              consultation
                ? navigate(`/consultations/${consultation.id}/transcript`)
                : navigate('/history')
            }
          >
            {isLocalOnly ? 'Back to Transcript' : 'Back to History'}
          </Button>
          {hasTranscript && (
            <Button
              variant="primary"
              loading={isGenerating}
              onClick={handleGenerateSoap}
            >
              Generate with Groq
            </Button>
          )}
        </div>
      </div>
    )
  }


  const isApproved = consultation.reviewStatus === 'approved'
  const isDirty =
    originalSoap &&
    (subjective !== originalSoap.subjective ||
      objective !== originalSoap.objective ||
      assessment !== originalSoap.assessment ||
      plan !== originalSoap.plan)

  // Save manual edits to SOAP sections
  const handleSaveEdits = async () => {
    setIsSaving(true)
    const updatedSoap: SOAPNote = {
      subjective,
      objective,
      assessment,
      plan,
      source: consultation.soap_note?.source,
      review_flags: consultation.soap_note?.review_flags,
      is_draft: consultation.soap_note?.is_draft,
      disclaimer: consultation.soap_note?.disclaimer,
      generated_at: consultation.soap_note?.generated_at,
    }

    try {
      const res = await updateConsultationSoap(consultation.id, {
        subjective,
        objective,
        assessment,
        plan,
      })
      if (res?.evidence_links) {
        setEvidenceLinks(res.evidence_links)
        updatedSoap.evidence_links = res.evidence_links
      }
      toast.success('SOAP note changes submitted to backend')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to submit changes to backend')
    }

    saveLocalReview(consultation.id, {
      editedSoapNote: updatedSoap,
    })

    const updatedRecord: ConsultationRecord = {
      ...consultation,
      soap_note: updatedSoap,
    }

    setConsultation(updatedRecord)
    addConsultation(updatedRecord)
    setOriginalSoap(updatedSoap)
    setEditingSection(null)
    setIsSaving(false)
  }

  // Explicit Clinician Approval Action
  const handleConfirmApproval = async () => {
    if (!attestationChecked) {
      toast.error('Please check the clinician verification box to approve.')
      return
    }

    if (isApproved) {
      toast.error('This consultation note has already been approved.')
      return
    }

    if (!subjective.trim() || !objective.trim() || !assessment.trim() || !plan.trim()) {
      toast.error('All SOAP sections (Subjective, Objective, Assessment, Plan) must be non-empty to approve.')
      return
    }

    setIsApproving(true)
    const approvalTimestamp = new Date().toLocaleString('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
    const clinicianName = profile.firstName
      ? `Dr. ${profile.firstName} ${profile.lastName}`
      : 'Reviewing Clinician'

    const updatedSoap: SOAPNote = {
      subjective,
      objective,
      assessment,
      plan,
      source: consultation.soap_note?.source,
      review_flags: consultation.soap_note?.review_flags,
      is_draft: false,
      disclaimer: consultation.soap_note?.disclaimer,
      generated_at: consultation.soap_note?.generated_at,
    }

    try {
      await updateConsultationSoap(consultation.id, {
        subjective,
        objective,
        assessment,
        plan,
      })
      await approveConsultationApi(consultation.id, {
        approved_by: clinicianName,
        approval_notes: clinicianNotes.trim() || undefined,
      })
    } catch (err: any) {
      setIsApproving(false)
      const errorMsg = err?.response?.data?.detail || err.message || 'Approval failed'
      toast.error(`Approval failed: ${errorMsg}`)
      return
    }

    // Save in local reviews registry
    saveLocalReview(consultation.id, {
      reviewStatus: 'approved',
      approvedBy: clinicianName,
      approvedAt: approvalTimestamp,
      clinicianNotes: clinicianNotes.trim() || undefined,
      editedSoapNote: updatedSoap,
    })

    const updatedRecord: ConsultationRecord = {
      ...consultation,
      status: 'approved',
      reviewStatus: 'approved',
      approval: {
        approved: true,
        approvedBy: clinicianName,
        approvedAt: approvalTimestamp,
        clinicianNotes: clinicianNotes.trim() || undefined,
      },
      soap_note: updatedSoap,
    }

    setConsultation(updatedRecord)
    addConsultation(updatedRecord)
    setIsApproving(false)
    setApprovalModalOpen(false)
    toast.success('SOAP Note successfully approved & signed!')
  }

  // Format Full Note for Copy / Download
  const fullNoteText = `MediScribe AI — Clinical SOAP Note
Patient Identifier: ${consultation.patientId}
Encounter Date: ${consultation.date}
Audio Duration: ${consultation.duration}
Clinician: ${profile.firstName ? `${profile.firstName} ${profile.lastName}` : 'Attending Physician'} (${profile.licenseNo || 'MD'})
Status: ${isApproved ? `APPROVED & SIGNED by ${consultation.approval?.approvedBy || 'Clinician'} on ${consultation.approval?.approvedAt || ''}` : 'DRAFT — PENDING CLINICIAN REVIEW'}

--------------------------------------------------
S — SUBJECTIVE
--------------------------------------------------
${subjective}

--------------------------------------------------
O — OBJECTIVE
--------------------------------------------------
${objective}

--------------------------------------------------
A — ASSESSMENT
--------------------------------------------------
${assessment}

--------------------------------------------------
P — PLAN
--------------------------------------------------
${plan}

--------------------------------------------------
AI Verification Notice:
Generated via ${consultation.soap_note.source || 'MediScribe AI Monitored Pipeline'}.
Clinician review and verification required before clinical adoption.
`

  const handleCopyNote = async () => {
    await navigator.clipboard.writeText(fullNoteText)
    setCopied(true)
    toast.success('Full SOAP note copied to clipboard')
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownloadTxt = () => {
    const blob = new Blob([fullNoteText], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `SOAP_${consultation.patientId}_${new Date().toISOString().slice(0, 10)}.txt`
    link.click()
    URL.revokeObjectURL(url)
    toast.success('SOAP note downloaded (.txt)')
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto animate-in fade-in duration-150">
      {/* ── Header & Breadcrumbs ─────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-[#E2E8F0]">
        <div>
          <div className="flex items-center gap-2">
            <Link
              to={`/consultations/${consultation.id}`}
              className="text-xs font-semibold text-[#0D9488] hover:underline"
            >
              Consultation {consultation.patientId}
            </Link>
            <span className="text-xs text-[#94A3B8]">/</span>
            <span className="text-xs text-[#64748B]">SOAP Note Review</span>
          </div>
          <h1 className="text-2xl font-bold text-[#0F172A] tracking-tight mt-1 flex items-center gap-3">
            Structured SOAP Note Review
            {isApproved ? (
              <Badge tone="ok" dot>Approved & Signed</Badge>
            ) : (
              <Badge tone="warn" dot>Draft Awaiting Review</Badge>
            )}
          </h1>
          <p className="text-xs text-[#64748B] mt-0.5">
            Encounter Date: {consultation.date} · Model: {consultation.soap_note.source || 'groq-llama-3.3-70b-versatile'}
          </p>
        </div>

        {/* Action Header */}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            icon={<ArrowLeft size={14} />}
            onClick={() => navigate(`/consultations/${consultation.id}/transcript`)}
          >
            View Transcript
          </Button>

          <Button
            variant="secondary"
            size="sm"
            icon={copied ? <Check size={14} /> : <Copy size={14} />}
            onClick={handleCopyNote}
          >
            {copied ? 'Copied' : 'Copy'}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            icon={<Download size={14} />}
            onClick={handleDownloadTxt}
          >
            Export TXT
          </Button>

          {isDirty && (
            <Button
              variant="teal-outline"
              size="sm"
              icon={<Save size={14} />}
              loading={isSaving}
              onClick={handleSaveEdits}
            >
              Save Edits
            </Button>
          )}

          {!isApproved ? (
            <Button
              variant="primary"
              size="sm"
              icon={<FileSignature size={15} />}
              onClick={() => setApprovalModalOpen(true)}
              className="shadow-sm"
            >
              Approve & Sign Note
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              icon={<CheckCircle2 size={15} className="text-[#047857]" />}
              onClick={() => setApprovalModalOpen(true)}
            >
              View Signature
            </Button>
          )}
        </div>
      </div>

      {/* ── Mode Toggle: SOAP Editor vs Evidence Grounding Audit ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-1.5 rounded-2xl bg-[#F1F5F9] border border-[#E2E8F0]">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setActiveView('editor')}
            className={`px-3.5 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
              activeView === 'editor'
                ? 'bg-white text-[#0F172A] shadow-xs'
                : 'text-[#64748B] hover:text-[#0F172A]'
            }`}
          >
            <FileText size={14} />
            <span>SOAP Document Editor</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveView('evidence')}
            className={`px-3.5 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
              activeView === 'evidence'
                ? 'bg-white text-[#0D9488] shadow-xs ring-1 ring-[#0D9488]/30'
                : 'text-[#64748B] hover:text-[#0F172A]'
            }`}
          >
            <FileSearch size={14} />
            <span>Evidence Grounding Review</span>
            {evidenceLinks && (
              <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-teal-100 text-teal-800">
                {evidenceLinks.total_statements}
              </span>
            )}
          </button>
        </div>

        {activeView === 'editor' && (
          <div className="text-[11px] text-[#64748B] pr-2 hidden sm:block">
            Evidence mapping is kept separate from clean clinical prose
          </div>
        )}
      </div>

      {/* ── Evidence View Panel ──────────────────────────────── */}
      {activeView === 'evidence' ? (
        <EvidenceReviewPanel
          evidence={evidenceLinks}
          transcript={consultation.transcription}
          isLoading={isEvaluatingEvidence}
          onRefresh={handleRefreshEvidence}
        />
      ) : (
        <>
          {/* ── Mandatory Clinician Review Warning Banner ────────── */}
          {!isApproved ? (
            <div className="p-4 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] text-[#B45309] flex items-start gap-3">
              <ShieldAlert size={20} className="shrink-0 mt-0.5 text-[#D97706]" />
              <div className="text-xs leading-relaxed">
                <strong className="font-semibold block text-sm text-[#92400E]">
                  Clinician Review Required: Never approve automatically
                </strong>
                This SOAP document was generated by ambient AI. You must verify all medications, dosages, examination findings, and follow-up plans against your actual clinical judgement before approving.
              </div>
            </div>
          ) : (
            <div className="p-4 rounded-xl border border-[#A7F3D0] bg-[#ECFDF5] text-[#047857] flex items-center justify-between">
              <div className="flex items-center gap-3">
                <CheckCircle2 size={20} className="text-[#059669]" />
                <div className="text-xs">
                  <strong className="font-semibold text-sm block text-[#065F46]">
                    Clinician Verified & Approved
                  </strong>
                  Signed by {consultation.approval?.approvedBy || 'Physician'} on{' '}
                  {consultation.approval?.approvedAt || 'today'}. This note is finalized.
                </div>
              </div>
              <Badge tone="ok">Ready for EHR</Badge>
            </div>
          )}

          {/* ── Grounding Evidence & Unsupported Statements Warning Banner ── */}
          {evidenceLinks && evidenceLinks.unsupported_count > 0 && !isApproved && (
            <div className="p-4 rounded-xl border border-amber-300 bg-amber-50/80 text-amber-900 flex items-start gap-3">
              <AlertCircle size={20} className="shrink-0 mt-0.5 text-amber-600" />
              <div className="text-xs leading-relaxed">
                <strong className="font-semibold block text-sm text-amber-950">
                  Grounding Warning: {evidenceLinks.unsupported_count} statement(s) lack verbatim transcript evidence
                </strong>
                Claims marked with <em>"Evidence not found — review required"</em> could not be verified against the conversation. Inspect the <strong>Evidence Grounding Review</strong> tab and verify all claims before approving.
              </div>
            </div>
          )}

          {/* ── Clinical Review Flags ────────────────────────────── */}
          {consultation.soap_note?.review_flags && consultation.soap_note.review_flags.length > 0 && (
            <Card className="border-amber-300 bg-amber-50/60 shadow-xs">
              <CardHeader
                title={
                  <span className="flex items-center gap-2 text-amber-900 font-semibold text-sm">
                    <AlertCircle size={16} className="text-amber-600" />
                    <span>Clinical Review Flags ({consultation.soap_note.review_flags.length})</span>
                  </span>
                }
                actions={<Badge tone="warn">Requires Clinician Attention</Badge>}
              />
              <CardBody className="p-4 pt-1">
                <ul className="space-y-1.5 text-xs text-amber-900">
                  {consultation.soap_note.review_flags.map((flag, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <span className="text-amber-600 font-bold mt-0.5">•</span>
                      <span>{flag}</span>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          )}

          {/* ── 4 SOAP Sections ──────────────────────────────────── */}
          <div className="space-y-5">
            {/* S — Subjective */}
            <Card className="hover:border-[#CBD5E1] transition-colors">
              <CardHeader
                title={
                  <span className="flex items-center gap-2">
                    <span className="size-6 rounded-md bg-[#0D9488]/10 text-[#0D9488] font-bold text-xs flex items-center justify-center font-mono">
                      S
                    </span>
                    <span>Subjective</span>
                  </span>
                }
                actions={
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => setActiveView('evidence')}
                      className="text-xs font-medium text-[#64748B] hover:text-[#0D9488] flex items-center gap-1 transition-colors"
                      title="Inspect transcript evidence for Subjective statements"
                    >
                      <FileSearch size={12} />
                      <span>Inspect Evidence</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingSection(editingSection === 'subjective' ? null : 'subjective')}
                      className="text-xs font-medium text-[#0D9488] hover:text-[#0F766E] flex items-center gap-1"
                    >
                      <Edit3 size={12} />
                      {editingSection === 'subjective' ? 'Close Editor' : 'Edit Section'}
                    </button>
                  </div>
                }
              />
              <CardBody className="p-5">
                {editingSection === 'subjective' ? (
                  <textarea
                    value={subjective}
                    onChange={(e) => setSubjective(e.target.value)}
                    rows={5}
                    className="w-full p-3 rounded-lg border border-[#CBD5E1] font-mono text-sm leading-relaxed text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/40"
                  />
                ) : (
                  <p className="text-sm leading-relaxed text-[#334155] whitespace-pre-line font-sans">
                    {subjective}
                  </p>
                )}
              </CardBody>
            </Card>

            {/* O — Objective */}
            <Card className="hover:border-[#CBD5E1] transition-colors">
              <CardHeader
                title={
                  <span className="flex items-center gap-2">
                    <span className="size-6 rounded-md bg-[#0D9488]/10 text-[#0D9488] font-bold text-xs flex items-center justify-center font-mono">
                      O
                    </span>
                    <span>Objective</span>
                  </span>
                }
                actions={
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => setActiveView('evidence')}
                      className="text-xs font-medium text-[#64748B] hover:text-[#0D9488] flex items-center gap-1 transition-colors"
                      title="Inspect transcript evidence for Objective statements"
                    >
                      <FileSearch size={12} />
                      <span>Inspect Evidence</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingSection(editingSection === 'objective' ? null : 'objective')}
                      className="text-xs font-medium text-[#0D9488] hover:text-[#0F766E] flex items-center gap-1"
                    >
                      <Edit3 size={12} />
                      {editingSection === 'objective' ? 'Close Editor' : 'Edit Section'}
                    </button>
                  </div>
                }
              />
              <CardBody className="p-5">
                {editingSection === 'objective' ? (
                  <textarea
                    value={objective}
                    onChange={(e) => setObjective(e.target.value)}
                    rows={6}
                    className="w-full p-3 rounded-lg border border-[#CBD5E1] font-mono text-sm leading-relaxed text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/40"
                  />
                ) : (
                  <p className="text-sm leading-relaxed text-[#334155] whitespace-pre-line font-sans">
                    {objective}
                  </p>
                )}
              </CardBody>
            </Card>

            {/* A — Assessment */}
            <Card className="hover:border-[#CBD5E1] transition-colors">
              <CardHeader
                title={
                  <span className="flex items-center gap-2">
                    <span className="size-6 rounded-md bg-[#0D9488]/10 text-[#0D9488] font-bold text-xs flex items-center justify-center font-mono">
                      A
                    </span>
                    <span>Assessment</span>
                  </span>
                }
                actions={
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => setActiveView('evidence')}
                      className="text-xs font-medium text-[#64748B] hover:text-[#0D9488] flex items-center gap-1 transition-colors"
                      title="Inspect transcript evidence for Assessment statements"
                    >
                      <FileSearch size={12} />
                      <span>Inspect Evidence</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingSection(editingSection === 'assessment' ? null : 'assessment')}
                      className="text-xs font-medium text-[#0D9488] hover:text-[#0F766E] flex items-center gap-1"
                    >
                      <Edit3 size={12} />
                      {editingSection === 'assessment' ? 'Close Editor' : 'Edit Section'}
                    </button>
                  </div>
                }
              />
              <CardBody className="p-5">
                {editingSection === 'assessment' ? (
                  <textarea
                    value={assessment}
                    onChange={(e) => setAssessment(e.target.value)}
                    rows={5}
                    className="w-full p-3 rounded-lg border border-[#CBD5E1] font-mono text-sm leading-relaxed text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/40"
                  />
                ) : (
                  <p className="text-sm leading-relaxed text-[#334155] whitespace-pre-line font-sans">
                    {assessment}
                  </p>
                )}
              </CardBody>
            </Card>

            {/* P — Plan */}
            <Card className="hover:border-[#CBD5E1] transition-colors">
              <CardHeader
                title={
                  <span className="flex items-center gap-2">
                    <span className="size-6 rounded-md bg-[#0D9488]/10 text-[#0D9488] font-bold text-xs flex items-center justify-center font-mono">
                      P
                    </span>
                    <span>Plan</span>
                  </span>
                }
                actions={
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => setActiveView('evidence')}
                      className="text-xs font-medium text-[#64748B] hover:text-[#0D9488] flex items-center gap-1 transition-colors"
                      title="Inspect transcript evidence for Plan statements"
                    >
                      <FileSearch size={12} />
                      <span>Inspect Evidence</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingSection(editingSection === 'plan' ? null : 'plan')}
                      className="text-xs font-medium text-[#0D9488] hover:text-[#0F766E] flex items-center gap-1"
                    >
                      <Edit3 size={12} />
                      {editingSection === 'plan' ? 'Close Editor' : 'Edit Section'}
                    </button>
                  </div>
                }
              />
              <CardBody className="p-5">
                {editingSection === 'plan' ? (
                  <textarea
                    value={plan}
                    onChange={(e) => setPlan(e.target.value)}
                    rows={6}
                    className="w-full p-3 rounded-lg border border-[#CBD5E1] font-mono text-sm leading-relaxed text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/40"
                  />
                ) : (
                  <p className="text-sm leading-relaxed text-[#334155] whitespace-pre-line font-sans">
                    {plan}
                  </p>
                )}
              </CardBody>
            </Card>
          </div>
        </>
      )}

      {/* ── Approval Modal ───────────────────────────────────── */}
      <Modal
        open={approvalModalOpen}
        onClose={() => setApprovalModalOpen(false)}
        title={isApproved ? 'Clinician Signature Details' : 'Approve & Sign Clinical SOAP Note'}
      >
        <div className="space-y-4">
          <p className="text-xs text-[#64748B]">
            Review your signing credentials. By approving this clinical documentation, you attest that you have evaluated the AI-generated draft against your patient interaction.
          </p>

          <div className="p-3.5 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] space-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-[#64748B]">Signing Clinician:</span>
              <strong className="text-[#0F172A]">
                {profile.firstName ? `${profile.firstName} ${profile.lastName}` : 'Dr. Jane Wilson'}
              </strong>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B]">Medical License:</span>
              <span className="font-mono text-[#0F172A]">{profile.licenseNo || 'MD-92817'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B]">Specialty / Facility:</span>
              <span className="text-[#0F172A]">{profile.specialty} · {profile.hospital}</span>
            </div>
          </div>

          {!isApproved && (
            <div className="space-y-3 pt-2">
              <div>
                <label className="block text-xs font-semibold text-[#475569] mb-1">
                  Optional Clinician Attestation Notes
                </label>
                <textarea
                  value={clinicianNotes}
                  onChange={(e) => setClinicianNotes(e.target.value)}
                  placeholder="e.g. Discussed medication adjustments with patient; agreed to 6-week follow up."
                  rows={2}
                  className="w-full p-2.5 rounded-lg border border-[#CBD5E1] text-xs focus:ring-2 focus:ring-[#0D9488]/30 outline-none"
                />
              </div>

              {/* Explicit Clinician Verification Checkbox */}
              <label className="flex items-start gap-2.5 cursor-pointer p-3 rounded-lg border border-[#E2E8F0] bg-white hover:bg-[#F8FAFC]">
                <input
                  type="checkbox"
                  checked={attestationChecked}
                  onChange={(e) => setAttestationChecked(e.target.checked)}
                  className="mt-0.5 size-4 accent-[#0D9488] rounded"
                />
                <span className="text-xs text-[#0F172A] leading-snug">
                  <strong>Explicit Clinician Verification:</strong> I have reviewed each SOAP section (Subjective, Objective, Assessment, Plan) and approve this record for official clinical documentation.
                </span>
              </label>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-4 border-t border-[#E2E8F0]">
            <Button variant="ghost" onClick={() => setApprovalModalOpen(false)}>
              {isApproved ? 'Close' : 'Cancel'}
            </Button>
            {!isApproved && (
              <Button
                variant="primary"
                icon={<FileSignature size={15} />}
                loading={isApproving}
                disabled={!attestationChecked || isApproving || isApproved}
                onClick={handleConfirmApproval}
              >
                Confirm Approval & Sign
              </Button>
            )}
          </div>
        </div>
      </Modal>
    </div>
  )
}
