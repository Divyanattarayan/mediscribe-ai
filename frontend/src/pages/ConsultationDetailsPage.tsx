import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  FileText,
  Clock,
  ShieldCheck,
  ShieldAlert,
  Save,
  CheckCircle2,
  AlertTriangle,
  Download,
  Copy,
  Check,
  Edit3,
  Trash2,
  ArrowLeft,
  Activity,
  Microscope,
  Pill,
  HeartPulse,
  Info,
  XCircle,
  HelpCircle,
  AlertCircle,
  ClipboardList,
  ChevronRight,
  FileSearch,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAppStore } from '../store/appStore'
import {
  fetchConsultation,
  deleteConsultation,
  extractClinicalEntities,
  updateConsultationSoap,
  generateConsultationSoap,
  fetchSoapEvidence,
} from '../services/api'
import { Button, Card, CardHeader, CardBody, Badge, Modal } from '../components/ui'
import EvidenceReviewPanel from '../components/EvidenceReviewPanel'
import type {
  ConsultationRecord,
  StructuredClinicalData,
  ClinicalSymptom,
  ClinicalCondition,
  ClinicalMedication,
  ClinicalAllergy,
  ClinicalFinding,
  UncertainFinding,
  EvidenceLinks,
} from '../types'

// ── Label colour helpers ───────────────────────────────────────────────────────

function labelTone(label: string): string {
  const l = (label || '').toUpperCase()
  if (l === 'SYMPTOM') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (l === 'CONDITION') return 'bg-rose-50 text-rose-700 border-rose-200'
  if (l === 'MEDICATION') return 'bg-teal-50 text-teal-700 border-teal-200'
  if (l === 'PROCEDURE') return 'bg-violet-50 text-violet-700 border-violet-200'
  return 'bg-slate-50 text-slate-600 border-slate-200'
}

function temporalityBadge(t?: string) {
  if (t === 'historical') return 'bg-slate-100 text-slate-500 text-[10px] px-1.5 py-0.5 rounded font-medium'
  return null
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SectionHeader({ icon, title, count }: { icon: React.ReactNode; title: string; count?: number }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="text-[#0D9488]">{icon}</span>
      <h3 className="text-sm font-bold text-[#0F172A]">{title}</h3>
      {count !== undefined && (
        <span className="ml-auto text-xs font-semibold text-[#64748B] bg-[#F1F5F9] px-2 py-0.5 rounded-full">
          {count}
        </span>
      )}
    </div>
  )
}

function FindingPill({ label, text, tone }: { label: string; text: string; tone?: string }) {
  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs ${tone ?? labelTone(label)}`}>
      <span className="font-medium">{text}</span>
      <span className="font-mono text-[9px] uppercase opacity-60">{label}</span>
    </div>
  )
}

function SymptomRow({ sym }: { sym: ClinicalSymptom }) {
  const badgeClass = sym.negated
    ? 'bg-red-50 border-red-200 text-red-700'
    : sym.uncertain
    ? 'bg-yellow-50 border-yellow-200 text-yellow-700'
    : 'bg-green-50 border-green-200 text-green-700'

  return (
    <div className={`flex items-start gap-2 p-2.5 rounded-lg border text-xs ${badgeClass}`}>
      {sym.negated ? <XCircle size={14} className="mt-0.5 shrink-0" /> :
       sym.uncertain ? <HelpCircle size={14} className="mt-0.5 shrink-0" /> :
       <CheckCircle2 size={14} className="mt-0.5 shrink-0" />}
      <div className="flex-1 min-w-0">
        <span className="font-semibold capitalize">{sym.text}</span>
        {sym.negated && <span className="ml-1.5 font-bold">(Denied)</span>}
        {sym.uncertain && <span className="ml-1.5 font-bold">(Uncertain)</span>}
        {sym.duration && (
          <span className="ml-2 text-[10px] opacity-70 font-medium">⏱ {sym.duration}</span>
        )}
        {sym.temporality === 'historical' && (
          <span className="ml-1.5 text-[10px] opacity-60">• historical</span>
        )}
        {sym.context_sentence && (
          <p className="mt-1 text-[10px] opacity-60 italic leading-snug truncate" title={sym.context_sentence}>
            "{sym.context_sentence}"
          </p>
        )}
      </div>
    </div>
  )
}

function ConditionRow({ cond }: { cond: ClinicalCondition }) {
  const isConfirmed = cond.is_confirmed_diagnosis && !cond.negated && !cond.uncertain
  const badgeClass = cond.negated
    ? 'bg-red-50 border-red-200 text-red-700'
    : cond.uncertain
    ? 'bg-yellow-50 border-yellow-200 text-yellow-700'
    : isConfirmed
    ? 'bg-rose-50 border-rose-200 text-rose-700'
    : 'bg-orange-50 border-orange-200 text-orange-700'

  return (
    <div className={`flex items-start gap-2 p-2.5 rounded-lg border text-xs ${badgeClass}`}>
      <HeartPulse size={14} className="mt-0.5 shrink-0" />
      <div className="flex-1">
        <span className="font-semibold capitalize">{cond.text}</span>
        {isConfirmed && (
          <span className="ml-1.5 text-[10px] font-semibold bg-rose-100 text-rose-600 px-1.5 py-0.5 rounded">
            Confirmed
          </span>
        )}
        {cond.negated && <span className="ml-1.5 font-bold">(Denied)</span>}
        {cond.uncertain && <span className="ml-1.5 font-bold">(Suspected)</span>}
        {cond.temporality === 'historical' && (
          <span className="ml-1.5 text-[10px] opacity-60">• historical</span>
        )}
        {cond.context_sentence && (
          <p className="mt-1 text-[10px] opacity-60 italic leading-snug truncate" title={cond.context_sentence}>
            "{cond.context_sentence}"
          </p>
        )}
      </div>
    </div>
  )
}

function MedRow({ med, actionLabel, actionColor }: { med: ClinicalMedication; actionLabel: string; actionColor: string }) {
  return (
    <div className="flex items-center gap-2 p-2.5 rounded-lg border border-[#E2E8F0] bg-white text-xs hover:bg-[#F8FAFC] transition-colors">
      <Pill size={13} className="text-[#0D9488] shrink-0" />
      <span className="font-semibold text-[#0F172A] capitalize">{med.text}</span>
      {med.dosage && (
        <span className="font-mono text-[10px] bg-[#F1F5F9] text-[#334155] px-1.5 py-0.5 rounded">{med.dosage}</span>
      )}
      <span className={`ml-auto text-[10px] font-bold px-1.5 py-0.5 rounded ${actionColor}`}>
        {actionLabel}
      </span>
    </div>
  )
}

function AllergyRow({ allergy }: { allergy: ClinicalAllergy }) {
  if (allergy.negated) {
    return (
      <div className="flex items-center gap-2 p-2.5 rounded-lg border border-green-200 bg-green-50 text-xs text-green-700">
        <ShieldCheck size={14} className="shrink-0" />
        <span className="font-semibold">{allergy.allergen}</span>
        <span className="ml-1 opacity-70 text-[10px]">(Explicitly Confirmed)</span>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-2 p-2.5 rounded-lg border border-red-200 bg-red-50 text-xs text-red-700">
      <AlertCircle size={14} className="mt-0.5 shrink-0" />
      <div className="flex-1">
        <span className="font-semibold capitalize">{allergy.allergen}</span>
        {allergy.reaction && (
          <span className="ml-1.5 text-[10px] opacity-80">→ {allergy.reaction}</span>
        )}
        {allergy.note && (
          <p className="mt-0.5 text-[10px] opacity-60 italic">{allergy.note}</p>
        )}
      </div>
    </div>
  )
}

// ── Main Clinical Findings Panel ──────────────────────────────────────────────

function ClinicalFindingsPanel({
  consultationId,
  hasTranscript,
}: {
  consultationId: string
  hasTranscript: boolean
}) {
  const [data, setData] = useState<StructuredClinicalData | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runExtraction = async () => {
    if (!hasTranscript) {
      toast.error('No transcript available to extract from.')
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const result = await extractClinicalEntities(consultationId)
      setData(result)
      toast.success('Clinical extraction complete')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Extraction failed'
      setError(msg)
      toast.error('Clinical extraction failed: ' + msg)
    } finally {
      setIsLoading(false)
    }
  }

  // ── Empty / Loading ────────────────────────────────────────────────────────

  if (!data) {
    return (
      <div className="space-y-4">
        {/* AI disclaimer */}
        <div className="flex gap-3 p-4 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] text-[#92400E]">
          <Info size={16} className="mt-0.5 shrink-0 text-[#D97706]" />
          <p className="text-xs leading-relaxed">
            <strong className="block text-[#78350F] mb-0.5">AI-Generated Clinical Extraction</strong>
            The extracted findings are produced by NLP heuristics and linguistic analysis, not clinical
            diagnosis. Negation detection, assertion scoping, and entity boundaries may miss nuances.
            A licensed clinician must independently verify all findings before use.
          </p>
        </div>

        <div className="py-12 text-center space-y-4">
          <Microscope size={40} className="mx-auto text-[#94A3B8]" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-[#0F172A]">Extract Clinical Findings</p>
            <p className="text-xs text-[#64748B] max-w-sm mx-auto">
              Run NLP analysis on the consultation transcript to identify symptoms, diagnoses,
              medications, allergies, and clinical gaps.
            </p>
          </div>
          <Button
            variant="primary"
            onClick={runExtraction}
            disabled={isLoading || !hasTranscript}
            icon={isLoading ? undefined : <Microscope size={15} />}
          >
            {isLoading ? 'Analysing…' : 'Run Clinical Extraction'}
          </Button>
          {!hasTranscript && (
            <p className="text-xs text-[#B45309]">No transcript available. Transcribe audio first.</p>
          )}
          {error && (
            <p className="text-xs text-[#DC2626]">Error: {error}</p>
          )}
        </div>
      </div>
    )
  }

  // ── Computed counts ───────────────────────────────────────────────────────

  const activeSymptoms = data.symptoms.filter(s => !s.negated && !s.uncertain)
  const deniedSymptoms = data.symptoms.filter(s => s.negated)
  const prescribedMeds = data.medications.prescribed
  const currentMeds = data.medications.current_or_mentioned
  const discontinuedMeds = data.medications.discontinued
  const allMedCount = prescribedMeds.length + currentMeds.length + discontinuedMeds.length

  return (
    <div className="space-y-4">
      {/* Disclaimer banner */}
      <div className="flex gap-3 p-3.5 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] text-[#92400E]">
        <Info size={15} className="mt-0.5 shrink-0 text-[#D97706]" />
        <p className="text-[11px] leading-relaxed">
          <strong className="font-semibold text-[#78350F]">AI-Generated — Requires Clinician Review. </strong>
          NLP extraction using linguistic heuristics. Not clinically validated. All findings must be
          independently verified by a licensed clinician before use in patient records.
        </p>
        <button
          className="ml-auto shrink-0 text-xs underline text-[#B45309] hover:text-[#92400E]"
          onClick={runExtraction}
          title="Re-run extraction"
        >
          Re-run
        </button>
      </div>

      {/* Positive findings summary pills */}
      {data.positive_findings.length > 0 && (
        <Card>
          <CardHeader
            title="Confirmed / Positive Findings"
            count={data.positive_findings.length}
          />
          <CardBody className="p-4">
            <div className="flex flex-wrap gap-2">
              {data.positive_findings.map((f: ClinicalFinding, i: number) => (
                <FindingPill key={i} label={f.type} text={f.finding} />
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Negative findings */}
      {data.negative_findings.length > 0 && (
        <Card>
          <CardHeader
            title="Denied / Absent Findings"
            count={data.negative_findings.length}
          />
          <CardBody className="p-4">
            <div className="flex flex-wrap gap-2">
              {data.negative_findings.map((f: ClinicalFinding, i: number) => (
                <div
                  key={i}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-red-200 bg-red-50 text-red-700 text-xs"
                >
                  <XCircle size={11} />
                  <span className="font-medium line-through opacity-70">{f.finding}</span>
                  <span className="font-mono text-[9px] uppercase opacity-60">{f.type}</span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Uncertain findings */}
      {data.uncertain_findings.length > 0 && (
        <Card>
          <CardHeader
            title="Uncertain / Needs Review"
            count={data.uncertain_findings.length}
          />
          <CardBody className="p-4">
            <div className="space-y-2">
              {data.uncertain_findings.map((f: UncertainFinding, i: number) => (
                <div
                  key={i}
                  className="flex items-start gap-2 p-2.5 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-xs"
                >
                  <HelpCircle size={14} className="mt-0.5 shrink-0" />
                  <div className="flex-1">
                    <span className="font-semibold capitalize">{f.finding}</span>
                    <span className="ml-1.5 text-[10px] opacity-70">cue: "{f.cue}"</span>
                    {f.context && (
                      <p className="mt-0.5 text-[10px] opacity-60 italic truncate" title={f.context}>
                        "{f.context}"
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 text-[10px] font-bold bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">
                    Review Required
                  </span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Symptoms */}
        <Card>
          <CardBody className="p-4">
            <SectionHeader
              icon={<Activity size={16} />}
              title="Symptoms"
              count={data.symptoms.length}
            />
            {data.symptoms.length === 0 ? (
              <p className="text-xs text-[#94A3B8]">No symptoms identified.</p>
            ) : (
              <div className="space-y-1.5">
                {data.symptoms.map((s: ClinicalSymptom, i: number) => (
                  <SymptomRow key={i} sym={s} />
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        {/* Conditions */}
        <Card>
          <CardBody className="p-4">
            <SectionHeader
              icon={<HeartPulse size={16} />}
              title="Medical Conditions"
              count={data.medical_conditions.length}
            />
            {data.medical_conditions.length === 0 ? (
              <p className="text-xs text-[#94A3B8]">No conditions identified.</p>
            ) : (
              <div className="space-y-1.5">
                {data.medical_conditions.map((c: ClinicalCondition, i: number) => (
                  <ConditionRow key={i} cond={c} />
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Medications */}
      {allMedCount > 0 && (
        <Card>
          <CardHeader title="Medications" count={allMedCount} />
          <CardBody className="p-4 space-y-3">
            {prescribedMeds.length > 0 && (
              <div>
                <p className="text-[10px] font-bold uppercase text-[#059669] mb-1.5 tracking-wider">
                  ✦ Newly Prescribed
                </p>
                <div className="space-y-1.5">
                  {prescribedMeds.map((m: ClinicalMedication, i: number) => (
                    <MedRow
                      key={i}
                      med={m}
                      actionLabel="Prescribed"
                      actionColor="bg-green-100 text-green-700"
                    />
                  ))}
                </div>
              </div>
            )}
            {currentMeds.length > 0 && (
              <div>
                <p className="text-[10px] font-bold uppercase text-[#0D9488] mb-1.5 tracking-wider">
                  Current / Mentioned
                </p>
                <div className="space-y-1.5">
                  {currentMeds.map((m: ClinicalMedication, i: number) => (
                    <MedRow
                      key={i}
                      med={m}
                      actionLabel="Current"
                      actionColor="bg-teal-50 text-teal-700"
                    />
                  ))}
                </div>
              </div>
            )}
            {discontinuedMeds.length > 0 && (
              <div>
                <p className="text-[10px] font-bold uppercase text-[#DC2626] mb-1.5 tracking-wider">
                  Discontinued
                </p>
                <div className="space-y-1.5">
                  {discontinuedMeds.map((m: ClinicalMedication, i: number) => (
                    <MedRow
                      key={i}
                      med={m}
                      actionLabel="Stopped"
                      actionColor="bg-red-50 text-red-700"
                    />
                  ))}
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* Allergies */}
      {data.allergies.length > 0 && (
        <Card>
          <CardHeader title="Allergies" count={data.allergies.length} />
          <CardBody className="p-4">
            <div className="space-y-1.5">
              {data.allergies.map((a: ClinicalAllergy, i: number) => (
                <AllergyRow key={i} allergy={a} />
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Clinical Gaps */}
      {data.missing_information.length > 0 && (
        <Card>
          <CardHeader title="Clinical Documentation Gaps" count={data.missing_information.length} />
          <CardBody className="p-4">
            <div className="space-y-1.5">
              {data.missing_information.map((gap: string, i: number) => (
                <div
                  key={i}
                  className="flex items-start gap-2 p-2.5 rounded-lg border border-slate-200 bg-slate-50 text-xs text-[#475569]"
                >
                  <ClipboardList size={13} className="mt-0.5 shrink-0 text-[#64748B]" />
                  <span>{gap}</span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Durations */}
      {data.durations_and_timing.length > 0 && (
        <Card>
          <CardHeader title="Duration & Timing Mentions" count={data.durations_and_timing.length} />
          <CardBody className="p-4">
            <div className="flex flex-wrap gap-2">
              {data.durations_and_timing.map((d, i) => (
                <div key={i} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] text-xs text-[#334155]">
                  <Clock size={11} className="text-[#0D9488]" />
                  <span className="font-medium">{d.phrase}</span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

// ── Page component ─────────────────────────────────────────────────────────────

export default function ConsultationDetailsPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { consultations, addConsultation, removeConsultation } = useAppStore()

  const [consultation, setConsultation] = useState<ConsultationRecord | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'soap' | 'transcript' | 'findings' | 'evidence'>('soap')
  const [copied, setCopied] = useState(false)
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)

  // SOAP editing & direct generation state
  const [isEditingSoap, setIsEditingSoap] = useState(false)
  const [editSubjective, setEditSubjective] = useState('')
  const [editObjective, setEditObjective] = useState('')
  const [editAssessment, setEditAssessment] = useState('')
  const [editPlan, setEditPlan] = useState('')
  const [isSavingSoap, setIsSavingSoap] = useState(false)
  const [isGeneratingSoap, setIsGeneratingSoap] = useState(false)

  // Evidence links state
  const [evidenceLinks, setEvidenceLinks] = useState<EvidenceLinks | null>(null)
  const [isEvaluatingEvidence, setIsEvaluatingEvidence] = useState(false)

  useEffect(() => {
    const loadRecord = async () => {
      if (!id) return
      setIsLoading(true)

      const syncSoapState = (record: ConsultationRecord) => {
        if (record.soap_note) {
          setEditSubjective(record.soap_note.subjective || '')
          setEditObjective(record.soap_note.objective || '')
          setEditAssessment(record.soap_note.assessment || '')
          setEditPlan(record.soap_note.plan || '')
        }
      }

      const local = consultations.find((c) => c.id === id)
      if (local) {
        setConsultation(local)
        syncSoapState(local)
        if (local.soap_note?.evidence_links) {
          setEvidenceLinks(local.soap_note.evidence_links)
        } else if (local.soap_note) {
          fetchSoapEvidence(id).then(setEvidenceLinks).catch(() => {})
        }
        setIsLoading(false)
        return
      }

      try {
        const fetched = await fetchConsultation(id)
        setConsultation(fetched)
        syncSoapState(fetched)
        if (fetched.soap_note?.evidence_links) {
          setEvidenceLinks(fetched.soap_note.evidence_links)
        } else if (fetched.soap_note) {
          fetchSoapEvidence(id).then(setEvidenceLinks).catch(() => {})
        }
        addConsultation(fetched)
      } catch (err) {
        toast.error('Could not load consultation record')
      } finally {
        setIsLoading(false)
      }
    }
    loadRecord()
  }, [id])

  const handleRefreshEvidence = async () => {
    if (!consultation) return
    setIsEvaluatingEvidence(true)
    try {
      const fresh = await fetchSoapEvidence(consultation.id)
      setEvidenceLinks(fresh)
      toast.success('Evidence links updated')
    } catch {
      toast.error('Failed to update evidence links')
    } finally {
      setIsEvaluatingEvidence(false)
    }
  }

  const handleGenerateSoapDirect = async () => {
    if (!consultation) return
    setIsGeneratingSoap(true)
    try {
      const res = await generateConsultationSoap(consultation.id)
      const updated: ConsultationRecord = {
        ...consultation,
        reviewStatus: res.review_status as any,
        soap_note: res,
      }
      setConsultation(updated)
      addConsultation(updated)
      setEditSubjective(res.subjective || '')
      setEditObjective(res.objective || '')
      setEditAssessment(res.assessment || '')
      setEditPlan(res.plan || '')
      toast.success('SOAP note generated successfully')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to generate SOAP note')
    } finally {
      setIsGeneratingSoap(false)
    }
  }

  const handleSaveSoapEdits = async () => {
    if (!consultation) return
    if (!editSubjective.trim() || !editObjective.trim() || !editAssessment.trim() || !editPlan.trim()) {
      toast.error('All 4 SOAP sections must contain text.')
      return
    }
    setIsSavingSoap(true)
    try {
      const res = await updateConsultationSoap(consultation.id, {
        subjective: editSubjective.trim(),
        objective: editObjective.trim(),
        assessment: editAssessment.trim(),
        plan: editPlan.trim(),
      })
      const updated: ConsultationRecord = {
        ...consultation,
        soap_note: res,
      }
      setConsultation(updated)
      addConsultation(updated)
      setIsEditingSoap(false)
      toast.success('SOAP note changes saved to backend')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to save SOAP note')
    } finally {
      setIsSavingSoap(false)
    }
  }

  if (isLoading) {
    return (
      <div className="py-20 flex flex-col items-center justify-center text-center space-y-4">
        <div className="size-10 rounded-full border-3 border-[#0D9488]/20 border-t-[#0D9488] animate-spin" />
        <p className="text-sm text-[#64748B]">Loading consultation details...</p>
      </div>
    )
  }

  if (!consultation) {
    return (
      <div className="py-16 text-center space-y-4 max-w-md mx-auto">
        <AlertTriangle size={40} className="mx-auto text-[#B45309]" />
        <h2 className="text-lg font-bold text-[#0F172A]">Record Not Found</h2>
        <p className="text-sm text-[#64748B]">
          The consultation record could not be found in active history.
        </p>
        <Button variant="primary" onClick={() => navigate('/history')}>
          Back to History
        </Button>
      </div>
    )
  }

  const isApproved = consultation.reviewStatus === 'approved'
  const soap = consultation.soap_note
  const entities = consultation.entities || []

  const handleCopyNote = async () => {
    if (!soap) return
    const text = `MediScribe AI SOAP Note — ${consultation.patientId}
Date: ${consultation.date}
Status: ${isApproved ? `Approved by ${consultation.approval?.approvedBy || 'Doctor'}` : 'Draft'}

SUBJECTIVE:
${soap.subjective}

OBJECTIVE:
${soap.objective}

ASSESSMENT:
${soap.assessment}

PLAN:
${soap.plan}
`
    await navigator.clipboard.writeText(text)
    setCopied(true)
    toast.success('SOAP note copied to clipboard')
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownloadTxt = () => {
    if (!soap) return
    const text = `MediScribe AI SOAP Note — ${consultation.patientId}
Date: ${consultation.date}
Status: ${isApproved ? `Approved by ${consultation.approval?.approvedBy || 'Doctor'}` : 'Draft'}

SUBJECTIVE:
${soap.subjective}

OBJECTIVE:
${soap.objective}

ASSESSMENT:
${soap.assessment}

PLAN:
${soap.plan}
`
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `Consultation_${consultation.patientId}.txt`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('Note downloaded')
  }

  const handleDelete = async () => {
    await deleteConsultation(consultation.id)
    removeConsultation(consultation.id)
    setDeleteModalOpen(false)
    toast.success('Record deleted')
    navigate('/history')
  }

  const tabs = [
    { key: 'soap' as const, label: 'SOAP Note', icon: <FileText size={15} /> },
    { key: 'evidence' as const, label: 'Evidence Grounding', icon: <FileSearch size={15} /> },
    { key: 'transcript' as const, label: `Transcript & Entities (${entities.length})`, icon: <Activity size={15} /> },
    { key: 'findings' as const, label: 'Clinical Findings', icon: <Microscope size={15} /> },
  ]

  return (
    <div className="space-y-6 max-w-5xl mx-auto animate-in fade-in duration-150">
      {/* ── Breadcrumb & Title Bar ────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-[#E2E8F0]">
        <div>
          <div className="flex items-center gap-2">
            <Link to="/history" className="text-xs font-semibold text-[#0D9488] hover:underline flex items-center gap-1">
              <ArrowLeft size={12} />
              Consultations
            </Link>
            <span className="text-xs text-[#94A3B8]">/</span>
            <span className="text-xs text-[#64748B]">Record #{consultation.id}</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-[#0F172A] tracking-tight mt-1 flex items-center gap-3">
            {consultation.patientId}
            {consultation.title && (
              <span className="text-lg font-normal text-[#64748B]">· {consultation.title}</span>
            )}
            {consultation.isSynthetic && (
              <Badge tone="purple" className="text-xs">Synthetic</Badge>
            )}
            {consultation.reviewStatus === 'approved' ? (
              <Badge tone="ok" dot>Approved</Badge>
            ) : consultation.reviewStatus === 'in_review' ? (
              <Badge tone="warn" dot>In Review</Badge>
            ) : consultation.reviewStatus === 'needs_review' ? (
              <Badge tone="warn" dot>Draft Generated</Badge>
            ) : consultation.status === 'transcript_ready' || consultation.status === 'transcribed' ? (
              <Badge tone="info" dot>Transcript Ready</Badge>
            ) : consultation.status === 'transcribing' ? (
              <Badge tone="info" dot>Transcribing</Badge>
            ) : consultation.status === 'failed' ? (
              <Badge tone="danger" dot>Failed</Badge>
            ) : (
              <Badge tone="neutral" dot>Uploaded</Badge>
            )}
          </h1>
          <p className="text-xs text-[#64748B] mt-0.5">
            Recorded {consultation.date} · Audio Duration: {consultation.duration} · File: {consultation.filename}
          </p>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
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
          <Button
            variant="teal-outline"
            size="sm"
            icon={<Edit3 size={14} />}
            onClick={() => navigate(`/consultations/${consultation.id}/soap`)}
          >
            {isApproved ? 'Review & Sign' : 'Review & Approve'}
          </Button>
          <button
            type="button"
            onClick={() => setDeleteModalOpen(true)}
            className="p-2 text-[#94A3B8] hover:text-[#B91C1C] hover:bg-[#FEF2F2] rounded-lg transition-colors"
            title="Delete record"
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      {/* ── Status Banner ────────────────────────────────────── */}
      {isApproved ? (
        <div className="p-4 rounded-xl border border-[#A7F3D0] bg-[#ECFDF5] text-[#047857] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <CheckCircle2 size={20} className="text-[#059669]" />
            <div className="text-xs">
              <strong className="font-semibold text-sm block text-[#065F46]">
                Clinician Verified & Approved
              </strong>
              Signed by {consultation.approval?.approvedBy || 'Doctor'} on {consultation.approval?.approvedAt || 'record'}.
              {consultation.approval?.clinicianNotes && (
                <span className="block mt-0.5 italic">"{consultation.approval.clinicianNotes}"</span>
              )}
            </div>
          </div>
          <Badge tone="ok">Approved</Badge>
        </div>
      ) : (
        <div className="p-4 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] text-[#B45309] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldAlert size={20} className="text-[#D97706]" />
            <div className="text-xs">
              <strong className="font-semibold text-sm block text-[#92400E]">
                Draft Note — Pending Clinician Review
              </strong>
              Generated by ambient intelligence. Please review each section before approving.
            </div>
          </div>
          <Button
            size="sm"
            variant="primary"
            onClick={() => navigate(`/consultations/${consultation.id}/soap`)}
          >
            Review SOAP
          </Button>
        </div>
      )}

      {/* ── Tabs Navigation ──────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-[#E2E8F0]">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`pb-3 px-3 text-sm font-semibold border-b-2 transition-colors flex items-center gap-2 ${
              activeTab === tab.key
                ? 'border-[#0D9488] text-[#0F766E]'
                : 'border-transparent text-[#64748B] hover:text-[#0F172A]'
            }`}
          >
            {tab.icon}
            {tab.label}
            {tab.key === 'findings' && (
              <span className="text-[9px] font-bold bg-teal-100 text-teal-700 px-1.5 py-0.5 rounded-full">
                AI
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Tab Content ──────────────────────────────────────── */}

      {activeTab === 'soap' && (
        <div className="space-y-4">
          {soap ? (
            <div className="space-y-4">
              {/* Draft Disclaimer & Action Bar */}
              <div className="p-3.5 rounded-xl border border-amber-200 bg-amber-50/70 text-amber-800 text-xs flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <AlertTriangle size={16} className="text-amber-600 shrink-0" />
                  <span>
                    <strong className="font-semibold">AI-Generated Clinical Draft:</strong> Requires clinician review and editing before adoption.
                  </span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {isEditingSoap ? (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setIsEditingSoap(false)
                          setEditSubjective(soap.subjective || '')
                          setEditObjective(soap.objective || '')
                          setEditAssessment(soap.assessment || '')
                          setEditPlan(soap.plan || '')
                        }}
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<Save size={13} />}
                        loading={isSavingSoap}
                        onClick={handleSaveSoapEdits}
                      >
                        Save Changes
                      </Button>
                    </>
                  ) : (
                    <Button
                      variant="teal-outline"
                      size="sm"
                      icon={<Edit3 size={13} />}
                      onClick={() => setIsEditingSoap(true)}
                    >
                      Edit Sections
                    </Button>
                  )}
                </div>
              </div>

              {/* Review Flags */}
              {soap.review_flags && soap.review_flags.length > 0 && (
                <Card className="border-amber-300 bg-amber-50/50 shadow-xs">
                  <CardHeader
                    title={
                      <span className="flex items-center gap-2 text-amber-900 font-semibold text-sm">
                        <AlertCircle size={16} className="text-amber-600" />
                        <span>Clinical Review Flags ({soap.review_flags.length})</span>
                      </span>
                    }
                    actions={<Badge tone="warn">Requires Clinician Attention</Badge>}
                  />
                  <CardBody className="p-4 pt-1">
                    <ul className="space-y-1.5 text-xs text-amber-900">
                      {soap.review_flags.map((flag, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="text-amber-600 font-bold">•</span>
                          <span>{flag}</span>
                        </li>
                      ))}
                    </ul>
                  </CardBody>
                </Card>
              )}

              {/* 4 SOAP Sections */}
              <div className="grid grid-cols-1 gap-4">
                <Card>
                  <CardHeader
                    title="Subjective (S)"
                    actions={<Badge tone="neutral">Chief Complaint & History</Badge>}
                  />
                  <CardBody className="p-5">
                    {isEditingSoap ? (
                      <textarea
                        value={editSubjective}
                        onChange={(e) => setEditSubjective(e.target.value)}
                        rows={4}
                        className="w-full text-sm p-3 rounded-lg border border-[#CBD5E1] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/20 focus:border-[#0D9488]"
                        placeholder="Subjective findings..."
                      />
                    ) : (
                      <p className="text-sm leading-relaxed text-[#334155] whitespace-pre-line font-sans">
                        {soap.subjective}
                      </p>
                    )}
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader
                    title="Objective (O)"
                    actions={<Badge tone="neutral">Vitals & Examination</Badge>}
                  />
                  <CardBody className="p-5">
                    {isEditingSoap ? (
                      <textarea
                        value={editObjective}
                        onChange={(e) => setEditObjective(e.target.value)}
                        rows={3}
                        className="w-full text-sm p-3 rounded-lg border border-[#CBD5E1] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/20 focus:border-[#0D9488]"
                        placeholder="Objective findings and examination..."
                      />
                    ) : (
                      <p className="text-sm leading-relaxed text-[#334155] whitespace-pre-line font-sans">
                        {soap.objective}
                      </p>
                    )}
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader
                    title="Assessment (A)"
                    actions={<Badge tone="neutral">Diagnoses & Differential</Badge>}
                  />
                  <CardBody className="p-5">
                    {isEditingSoap ? (
                      <textarea
                        value={editAssessment}
                        onChange={(e) => setEditAssessment(e.target.value)}
                        rows={3}
                        className="w-full text-sm p-3 rounded-lg border border-[#CBD5E1] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/20 focus:border-[#0D9488]"
                        placeholder="Assessment and clinician impressions..."
                      />
                    ) : (
                      <p className="text-sm leading-relaxed text-[#334155] whitespace-pre-line font-sans">
                        {soap.assessment}
                      </p>
                    )}
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader
                    title="Plan (P)"
                    actions={<Badge tone="neutral">Orders, Rx & Follow-up</Badge>}
                  />
                  <CardBody className="p-5">
                    {isEditingSoap ? (
                      <textarea
                        value={editPlan}
                        onChange={(e) => setEditPlan(e.target.value)}
                        rows={4}
                        className="w-full text-sm p-3 rounded-lg border border-[#CBD5E1] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/20 focus:border-[#0D9488]"
                        placeholder="Documented plan and interventions..."
                      />
                    ) : (
                      <p className="text-sm leading-relaxed text-[#334155] whitespace-pre-line font-sans">
                        {soap.plan}
                      </p>
                    )}
                  </CardBody>
                </Card>
              </div>
            </div>
          ) : (
            <div className="py-12 text-center space-y-3">
              <FileText size={36} className="mx-auto text-[#0D9488]" />
              <p className="text-sm text-[#64748B]">No SOAP note available for this record.</p>
              <Button
                variant="primary"
                size="sm"
                icon={<ChevronRight size={14} />}
                loading={isGeneratingSoap}
                onClick={handleGenerateSoapDirect}
              >
                Generate SOAP Note with Groq
              </Button>
            </div>
          )}
        </div>
      )}

      {activeTab === 'transcript' && (
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Full Verbatim Transcript"
              actions={
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => navigate(`/consultations/${consultation.id}/transcript`)}
                >
                  Edit Transcript
                </Button>
              }
            />
            <CardBody className="p-5">
              <p className="font-mono text-sm leading-relaxed text-[#1E293B] whitespace-pre-wrap bg-[#F8FAFC] p-4 rounded-xl border border-[#E2E8F0]">
                {consultation.transcription || 'No transcript available.'}
              </p>
            </CardBody>
          </Card>

          {/* Recognized Clinical Entities */}
          <Card>
            <CardHeader title="Recognized Biomedical Entities" count={entities.length} />
            <CardBody className="p-5">
              {entities.length === 0 ? (
                <p className="text-xs text-[#94A3B8]">No entities tagged for this recording.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {entities.map((ent, i) => (
                    <div
                      key={i}
                      className="px-2.5 py-1 rounded-lg border border-[#E2E8F0] bg-white text-xs flex items-center gap-1.5 shadow-xs"
                    >
                      <span className="font-medium text-[#0F172A]">{ent.text}</span>
                      <span className="font-mono text-[9px] uppercase px-1 py-0.5 rounded bg-[#F1F5F9] text-[#64748B]">
                        {ent.label}
                      </span>
                      {ent.negated && (
                        <span className="text-[10px] font-bold text-[#DC2626]">(Denies)</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {activeTab === 'findings' && (
        <ClinicalFindingsPanel
          consultationId={consultation.id}
          hasTranscript={Boolean(consultation.transcription?.trim())}
        />
      )}

      {activeTab === 'evidence' && (
        <EvidenceReviewPanel
          evidence={evidenceLinks}
          transcript={consultation.transcription}
          isLoading={isEvaluatingEvidence}
          onRefresh={handleRefreshEvidence}
        />
      )}

      {/* Delete Confirmation Modal */}
      <Modal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        title="Delete Consultation Record"
      >
        <div className="space-y-4">
          <p className="text-sm text-[#475569]">
            Are you sure you want to delete consultation <strong>{consultation.patientId}</strong>? All audio transcription and SOAP drafts will be permanently removed.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setDeleteModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={handleDelete}>
              Confirm Delete
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
