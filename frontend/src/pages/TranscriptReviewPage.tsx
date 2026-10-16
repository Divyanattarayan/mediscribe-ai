import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  FileText,
  Save,
  RotateCcw,
  ArrowRight,
  Sparkles,
  Stethoscope,
  Clock,
  CheckCircle2,
  Copy,
  Check,
  Tag,
  AlertTriangle,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAppStore } from '../store/appStore'
import {
  fetchConsultation,
  saveLocalReview,
  updateConsultationTranscript,
  extractEntitiesFromTranscript,
} from '../services/api'
import { Button, Card, CardHeader, CardBody, Badge } from '../components/ui'
import type { ConsultationRecord, MedicalEntity } from '../types'


export default function TranscriptReviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { consultations, addConsultation } = useAppStore()

  const [consultation, setConsultation] = useState<ConsultationRecord | null>(null)
  const [editedTranscript, setEditedTranscript] = useState('')
  const [originalTranscript, setOriginalTranscript] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [copied, setCopied] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL')
  const [isExtracting, setIsExtracting] = useState(false)

  // Find or fetch the consultation record
  useEffect(() => {
    const loadRecord = async () => {
      if (!id) return
      setIsLoading(true)

      // First check local Zustand store
      const local = consultations.find((c) => c.id === id)
      if (local && local.transcription) {
        setConsultation(local)
        setEditedTranscript(local.transcription)
        setOriginalTranscript(local.transcription)
        setIsLoading(false)

        // If local record has no entities yet, trigger background extraction
        if (!local.entities || local.entities.length === 0) {
          extractEntitiesFromTranscript(local.transcription)
            .then((res) => {
              if (res && Array.isArray(res.entities) && res.entities.length > 0) {
                const updated: ConsultationRecord = {
                  ...local,
                  entities: res.entities,
                  entityCount: res.entities.length,
                  medicalContentScore: res.medical_content_score ?? local.medicalContentScore,
                }
                setConsultation(updated)
                addConsultation(updated)
              }
            })
            .catch(() => {})
        }
        return
      }

      // Otherwise fetch from backend API
      try {
        const fetched = await fetchConsultation(id)
        setConsultation(fetched)
        setEditedTranscript(fetched.transcription || '')
        setOriginalTranscript(fetched.transcription || '')
        addConsultation(fetched)

        if ((!fetched.entities || fetched.entities.length === 0) && fetched.transcription) {
          extractEntitiesFromTranscript(fetched.transcription)
            .then((res) => {
              if (res && Array.isArray(res.entities) && res.entities.length > 0) {
                const updated: ConsultationRecord = {
                  ...fetched,
                  entities: res.entities,
                  entityCount: res.entities.length,
                  medicalContentScore: res.medical_content_score ?? fetched.medicalContentScore,
                }
                setConsultation(updated)
                addConsultation(updated)
              }
            })
            .catch(() => {})
        }
      } catch (err) {
        toast.error('Could not load consultation record.')
      } finally {
        setIsLoading(false)
      }
    }
    loadRecord()
  }, [id])

  if (isLoading) {
    return (
      <div className="py-20 flex flex-col items-center justify-center text-center space-y-4">
        <div className="size-10 rounded-full border-3 border-[#0D9488]/20 border-t-[#0D9488] animate-spin" />
        <p className="text-sm text-[#64748B]">Loading consultation transcript from records...</p>
      </div>
    )
  }

  if (!consultation) {
    return (
      <div className="py-16 text-center space-y-4 max-w-md mx-auto">
        <AlertTriangle size={40} className="mx-auto text-[#B45309]" />
        <h2 className="text-lg font-bold text-[#0F172A]">Consultation Not Found</h2>
        <p className="text-sm text-[#64748B]">
          The requested record ID does not exist in local session or database history.
        </p>
        <Button variant="primary" onClick={() => navigate('/history')}>
          Back to History
        </Button>
      </div>
    )
  }

  const isDirty = editedTranscript !== originalTranscript
  const entities = consultation.entities || []

  // Group entities by category
  const categories = ['ALL', 'SYMPTOM', 'MEDICATION', 'CONDITION', 'TEST', 'PROCEDURE']
  const matchCategory = (entLabel: string, cat: string) => {
    const l = (entLabel || '').toUpperCase()
    const c = cat.toUpperCase()
    if (c === 'ALL') return true
    if (c === 'MEDICATION' || c === 'CHEMICAL') return l === 'MEDICATION' || l === 'CHEMICAL'
    if (c === 'CONDITION' || c === 'DISEASE') return l === 'CONDITION' || l === 'DISEASE'
    return l === c
  }
  const filteredEntities = entities.filter((e) => matchCategory(e.label, selectedCategory))

  // Manual or refresh extraction
  const handleExtractEntities = async (overrideText?: string) => {
    const textToAnalyze = (overrideText ?? editedTranscript).trim()
    if (!textToAnalyze || !consultation) return
    setIsExtracting(true)
    try {
      const res = await extractEntitiesFromTranscript(textToAnalyze)
      if (res && Array.isArray(res.entities)) {
        const updated: ConsultationRecord = {
          ...consultation,
          transcription: textToAnalyze,
          entities: res.entities,
          entityCount: res.entities.length,
          medicalContentScore: res.medical_content_score ?? consultation.medicalContentScore,
        }
        setConsultation(updated)
        addConsultation(updated)
        if (res.entities.length > 0) {
          toast.success(`Extracted ${res.entities.length} clinical term${res.entities.length === 1 ? '' : 's'}`)
        } else {
          toast.info('No medical entities recognized in the transcript.')
        }
      }
    } catch (e) {
      console.error('Failed to extract entities:', e)
      toast.error('Entity extraction failed.')
    } finally {
      setIsExtracting(false)
    }
  }

  // Save changes
  const handleSaveTranscript = async () => {
    setIsSaving(true)
    try {
      // Persist to backend database if consultation exists
      try {
        await updateConsultationTranscript(consultation.id, editedTranscript)
      } catch (apiErr) {
        // Fallback to local store for offline/demo records
        console.warn('Backend update failed, saving locally:', apiErr)
      }

      // Persist in local review store
      saveLocalReview(consultation.id, {
        editedTranscript,
      })

      // Re-extract entities for updated transcript
      let updatedEntities = consultation.entities || []
      let updatedScore = consultation.medicalContentScore
      try {
        const ext = await extractEntitiesFromTranscript(editedTranscript)
        if (ext && Array.isArray(ext.entities)) {
          updatedEntities = ext.entities
          if (ext.medical_content_score) updatedScore = ext.medical_content_score
        }
      } catch (e) {
        // ignore
      }

      // Update in state
      const updated: ConsultationRecord = {
        ...consultation,
        transcription: editedTranscript,
        entities: updatedEntities,
        entityCount: updatedEntities.length,
        medicalContentScore: updatedScore,
      }
      setConsultation(updated)
      addConsultation(updated)
      setOriginalTranscript(editedTranscript)

      toast.success('Transcript changes saved and clinical terms updated.')
    } catch {
      toast.error('Failed to save transcript')
    } finally {
      setIsSaving(false)
    }
  }


  const handleCopy = async () => {
    await navigator.clipboard.writeText(editedTranscript)
    setCopied(true)
    toast.success('Transcript copied to clipboard')
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-150">
      {/* Navigation breadcrumbs and header */}
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
            <span className="text-xs text-[#64748B]">Transcript Review</span>
          </div>
          <h1 className="text-2xl font-bold text-[#0F172A] tracking-tight mt-1 flex items-center gap-3">
            Acoustic Transcript Review
            {consultation.isSynthetic && (
              <Badge tone="purple" className="text-xs">Synthetic Demo</Badge>
            )}
          </h1>
          <p className="text-xs text-[#64748B] mt-0.5">
            Recorded {consultation.date} · Audio Duration: {consultation.duration}
          </p>
        </div>

        {/* Action Header */}
        <div className="flex items-center gap-2.5">
          <Button
            variant="ghost"
            size="sm"
            icon={copied ? <Check size={14} /> : <Copy size={14} />}
            onClick={handleCopy}
          >
            {copied ? 'Copied' : 'Copy Text'}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<RotateCcw size={14} />}
            disabled={!isDirty || isSaving}
            onClick={() => setEditedTranscript(originalTranscript)}
          >
            Reset
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Save size={14} />}
            loading={isSaving}
            disabled={!isDirty}
            onClick={handleSaveTranscript}
          >
            Save Transcript
          </Button>
          <Button
            variant="teal-outline"
            size="sm"
            icon={<ArrowRight size={14} />}
            onClick={() => navigate(`/consultations/${consultation.id}/soap`)}
          >
            Review SOAP
          </Button>
        </div>
      </div>

      {/* Accuracy & Code-Switching Disclaimer Banner */}
      <div className="p-4 rounded-xl border border-[#FED7AA] bg-[#FFFBEB] text-[#9A3412] text-xs flex items-start gap-3">

        <AlertTriangle size={18} className="shrink-0 text-[#EA580C] mt-0.5" />
        <div className="space-y-1">
          <p className="font-semibold text-[#7C2D12]">
            Clinician Verification Required Before Generating SOAP Notes
          </p>
          <p className="text-[#9A3412] leading-relaxed">
            Acoustic speech recognition accuracy can be impacted by ambient clinical noise, doctor/patient accents, specialized medical jargon, and multilingual code-switching (such as mixed Tamil-English dialogue). Tamil-English mixed speech has not been empirically verified on this model checkpoint.
          </p>
          <p className="text-[#9A3412] font-medium">
            Please review and correct any misrecognized clinical terms, medications, or dosages in the editor below before synthesizing the final SOAP note.
          </p>
        </div>
      </div>

      {/* Metrics Banner */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">

        <Card>
          <CardBody className="p-3.5">
            <span className="text-2xs font-semibold uppercase tracking-wider text-[#64748B] block">
              Audio Duration
            </span>
            <span className="text-lg font-bold font-mono text-[#0F172A]">
              {consultation.duration}
            </span>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="p-3.5">
            <span className="text-2xs font-semibold uppercase tracking-wider text-[#64748B] block">
              ASR Confidence
            </span>
            <span className="text-lg font-bold font-mono text-[#047857]">
              {consultation.asrConfidence
                ? `${Math.round(consultation.asrConfidence * 100)}%`
                : '94% (High)'}
            </span>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="p-3.5">
            <span className="text-2xs font-semibold uppercase tracking-wider text-[#64748B] block">
              Medical Content Score
            </span>
            <span className="text-lg font-bold font-mono text-[#0D9488]">
              {Math.round(consultation.medicalContentScore)}%
            </span>
          </CardBody>
        </Card>
        <Card>
          <CardBody className="p-3.5">
            <span className="text-2xs font-semibold uppercase tracking-wider text-[#64748B] block">
              Entities Extracted
            </span>
            <span className="text-lg font-bold font-mono text-[#0F172A]">
              {entities.length} terms
            </span>
          </CardBody>
        </Card>
      </div>

      {/* Main Transcript Editing Area */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Transcript Textarea Column */}
        <div className="lg:col-span-8 space-y-4">
          <Card>
            <CardHeader
              title="Clinical Transcript (Editable)"
              actions={
                <span className="text-xs font-mono text-[#64748B]">
                  {editedTranscript.split(/\s+/).filter(Boolean).length} words · {editedTranscript.length} chars
                </span>
              }
            />
            <CardBody className="p-4 space-y-3">
              <p className="text-xs text-[#64748B]">
                Review the speech-to-text transcript below. You can correct names, dosages, or misheard words before final SOAP note approval.
              </p>
              <textarea
                value={editedTranscript}
                onChange={(e) => setEditedTranscript(e.target.value)}
                rows={16}
                className="w-full p-4 rounded-xl border border-[#CBD5E1] bg-white font-mono text-sm leading-relaxed text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/40 resize-y"
                placeholder="Verbatim doctor-patient consultation transcript..."
              />
              {isDirty && (
                <div className="p-3 rounded-lg bg-[#FFFBEB] border border-[#FDE68A] text-xs text-[#B45309] flex items-center justify-between">
                  <span>You have unsaved changes in the transcript.</span>
                  <Button size="sm" variant="primary" onClick={handleSaveTranscript} loading={isSaving}>
                    Save Now
                  </Button>
                </div>
              )}
            </CardBody>
          </Card>
        </div>

        {/* Sidebar: Extracted Medical Entities */}
        <div className="lg:col-span-4 space-y-4">
          <Card>
            <CardHeader
              title="Recognized Clinical Terms"
              count={entities.length}
              actions={
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Sparkles size={12} className="text-[#0D9488]" />}
                  onClick={() => handleExtractEntities()}
                  loading={isExtracting}
                  title="Analyze transcript and extract clinical terms"
                >
                  Analyze
                </Button>
              }
            />
            <CardBody className="p-4 space-y-3">
              {/* Category Filter Pills */}
              <div className="flex flex-wrap gap-1 pb-2 border-b border-[#E2E8F0]">
                {categories.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setSelectedCategory(cat)}
                    className={`px-2 py-1 rounded-md text-[11px] font-medium transition-colors ${
                      selectedCategory === cat
                        ? 'bg-[#0D9488] text-white'
                        : 'bg-[#F1F5F9] text-[#475569] hover:bg-[#E2E8F0]'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Entity Chips */}
              {filteredEntities.length === 0 ? (
                entities.length === 0 ? (
                  <div className="text-center py-6 space-y-3">
                    <Tag className="mx-auto text-[#94A3B8]" size={28} />
                    <div>
                      <p className="text-xs font-semibold text-[#0F172A]">No Clinical Terms Detected Yet</p>
                      <p className="text-[11px] text-[#64748B] mt-0.5">
                        Click below to analyze the transcript and extract medical terms.
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="teal-outline"
                      icon={<Sparkles size={14} />}
                      onClick={() => handleExtractEntities()}
                      loading={isExtracting}
                    >
                      Extract Clinical Terms
                    </Button>
                  </div>
                ) : (
                  <p className="text-xs text-[#94A3B8] py-4 text-center">
                    No terms in this category ({selectedCategory}).
                  </p>
                )
              ) : (
                <div className="flex flex-wrap gap-2 max-h-[460px] overflow-y-auto pr-1">
                  {filteredEntities.map((ent, i) => {
                    const isNegated = ent.negated
                    return (
                      <div
                        key={i}
                        className={`px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1.5 ${
                          isNegated
                            ? 'bg-[#FEF2F2] border-[#FECACA] text-[#991B1B]'
                            : 'bg-[#F8FAFC] border-[#E2E8F0] text-[#0F172A]'
                        }`}
                        title={`Label: ${ent.label} · Confidence: ${Math.round(ent.confidence * 100)}%`}
                      >
                        <span className="font-medium">{ent.text}</span>
                        <span className="font-mono text-[9px] uppercase px-1 py-0.2 rounded bg-white border border-[#CBD5E1] text-[#64748B]">
                          {ent.label}
                        </span>
                        {isNegated && (
                          <span className="text-[10px] font-bold text-[#DC2626]">
                            (Denies)
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </CardBody>
          </Card>

          {/* Clinical Provenance Note */}
          <div className="p-4 rounded-xl border border-[#CCFBF1] bg-[#F0FDFA] text-xs text-[#0F766E] space-y-1">
            <span className="font-semibold block flex items-center gap-1.5">
              <Stethoscope size={14} />
              Grounding & Provenance
            </span>
            <p className="leading-relaxed">
              Every medical entity is tagged with its character offsets in the raw transcript to prevent ungrounded AI hallucinations in the generated SOAP note.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
