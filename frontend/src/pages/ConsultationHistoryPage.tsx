import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Clock,
  Search,
  Filter,
  Trash2,
  ExternalLink,
  PlusCircle,
  FileText,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  Sparkles,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAppStore } from '../store/appStore'
import { fetchHistory, deleteConsultation, deleteAllConsultations } from '../services/api'
import { Button, Card, CardHeader, CardBody, Badge, EmptyState, Modal } from '../components/ui'
import type { ConsultationRecord } from '../types'

export default function ConsultationHistoryPage() {
  const navigate = useNavigate()
  const { consultations, setConsultations, removeConsultation } = useAppStore()

  const [isLoading, setIsLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'needs_review' | 'approved'>('all')
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [showClearAllModal, setShowClearAllModal] = useState(false)

  // Fetch actual records from backend
  const loadHistory = async () => {
    setIsLoading(true)
    try {
      const records = await fetchHistory()
      // Preserve any local session consultations (e.g., cons-* or demo-* IDs)
      const localPending = consultations.filter(
        (c) => String(c.id).startsWith('cons-') || String(c.id).startsWith('demo-')
      )
      const backendIds = new Set(records.map((r) => String(r.id)))
      const merged = [
        ...localPending.filter((c) => !backendIds.has(String(c.id))),
        ...records,
      ]
      setConsultations(merged)
    } catch (err) {
      console.warn('Backend history fetch error:', err)
    } finally {
      setIsLoading(false)
    }
  }

  const handleLoadSampleDemo = () => {
    const demoRecord: ConsultationRecord = {
      id: 'demo-' + Date.now(),
      patientId: 'PT-83921',
      title: 'Acute Cardiology Consultation',
      filename: 'cardiology_encounter.mp3',
      date: new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }),
      duration: '03:45',
      entityCount: 8,
      medicalContentScore: 94.0,
      asrConfidence: 0.96,
      status: 'complete',
      reviewStatus: 'needs_review',
      isSynthetic: true,
      transcription:
        'Doctor: Hello Mr. Henderson, what brings you in today? Patient: Doctor, I have had this tightness and chest pain for the last two days, especially when walking up stairs. I also get shortness of breath. No fever, no cough, and no dizziness. Doctor: Thank you. Let us examine your heart and lungs. Heart sounds normal with regular rhythm. Blood pressure is 142 over 88. We will obtain an ECG immediately and start you on Aspirin 81 milligrams daily and Lisinopril 10 milligrams.',
      soap_note: {
        subjective:
          'Patient is a 54-year-old male presenting with a 2-day history of exertional substernal chest tightness and dyspnea on exertion. Denies fever, cough, palpitations, or lightheadedness.',
        objective:
          'Vitals: BP 142/88 mmHg, HR 76 bpm, SpO2 98% on room air.\nCardiovascular: Regular rate and rhythm, normal S1/S2, no murmurs or gallops.\nPulmonary: Clear to auscultation bilaterally without wheezing or crackles.',
        assessment:
          '1. Exertional chest tightness - rule out acute coronary syndrome / coronary artery disease.\n2. Stage 1 essential hypertension.',
        plan:
          '1. 12-lead Electrocardiogram (ECG) stat.\n2. Prescribed Aspirin 81 mg PO daily.\n3. Prescribed Lisinopril 10 mg PO daily for blood pressure control.\n4. Troponin and basic metabolic panel ordered.\n5. Advised emergency department evaluation if chest pain worsens or radiates.',
        source: 'groq-llama-3.3-70b-versatile',
        generated_at: new Date().toISOString(),
      },
      entities: [
        { text: 'chest pain', label: 'SYMPTOM', confidence: 0.98, start: 76, end: 86, negated: false },
        { text: 'shortness of breath', label: 'SYMPTOM', confidence: 0.97, start: 148, end: 167, negated: false },
        { text: 'fever', label: 'SYMPTOM', confidence: 0.95, start: 172, end: 177, negated: true },
        { text: 'cough', label: 'SYMPTOM', confidence: 0.95, start: 182, end: 187, negated: true },
        { text: 'dizziness', label: 'SYMPTOM', confidence: 0.94, start: 196, end: 205, negated: true },
        { text: 'ECG', label: 'TEST', confidence: 0.96, start: 321, end: 324, negated: false },
        { text: 'Aspirin', label: 'MEDICATION', confidence: 0.99, start: 355, end: 362, negated: false },
        { text: 'Lisinopril', label: 'MEDICATION', confidence: 0.99, start: 389, end: 399, negated: false },
      ],
    }
    setConsultations([demoRecord, ...consultations])
    toast.success('Loaded sample consultation record into history.')
  }

  useEffect(() => {
    loadHistory()
  }, [])

  // Filter consultations
  const filteredRecords = consultations.filter((record) => {
    const matchesSearch =
      record.patientId.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (record.title && record.title.toLowerCase().includes(searchQuery.toLowerCase())) ||
      record.date.toLowerCase().includes(searchQuery.toLowerCase())

    const matchesStatus =
      statusFilter === 'all'
        ? true
        : statusFilter === 'approved'
        ? record.reviewStatus === 'approved'
        : record.reviewStatus === 'needs_review' || record.reviewStatus === 'draft'

    return matchesSearch && matchesStatus
  })

  // Delete single consultation
  const handleDeleteRecord = async (id: string) => {
    try {
      await deleteConsultation(id)
      removeConsultation(id)
      setDeleteConfirmId(null)
      toast.success('Consultation record deleted')
    } catch {
      // Also remove locally if server is unreachable
      removeConsultation(id)
      setDeleteConfirmId(null)
      toast.success('Record removed from session')
    }
  }

  // Clear all consultations
  const handleClearAll = async () => {
    try {
      await deleteAllConsultations()
      setConsultations([])
      setShowClearAllModal(false)
      toast.success('All consultation records deleted')
    } catch {
      setConsultations([])
      setShowClearAllModal(false)
      toast.success('Local session history cleared')
    }
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-in fade-in duration-150">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-[#E2E8F0]">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#0D9488] bg-[#F0FDFA] px-2 py-0.5 rounded border border-[#CCFBF1]">
              Consultation Archive
            </span>
            <span className="text-xs text-[#64748B]">Permanent Records</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-[#0F172A] tracking-tight mt-1">
            Consultation History
          </h1>
          <p className="text-sm text-[#475569] mt-0.5">
            Database records of all processed clinical encounters, transcribed audio, and finalized SOAP notes.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {consultations.length > 0 && (
            <Button
              variant="danger"
              size="sm"
              icon={<Trash2 size={14} />}
              onClick={() => setShowClearAllModal(true)}
            >
              Clear All
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            icon={<PlusCircle size={15} />}
            onClick={() => navigate('/consultations/new')}
          >
            New Consultation
          </Button>
        </div>
      </div>

      {/* Search and Filters Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        {/* Search Input */}
        <div className="relative flex-1 max-w-md">
          <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by Patient ID, title, or date..."
            className="w-full pl-9 pr-4 py-2 rounded-lg border border-[#CBD5E1] bg-white text-xs sm:text-sm text-[#0F172A] placeholder:text-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/40"
          />
        </div>

        {/* Status Filter Tabs */}
        <div className="flex items-center gap-1.5 p-1 rounded-lg bg-[#F1F5F9] border border-[#E2E8F0]">
          <button
            onClick={() => setStatusFilter('all')}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              statusFilter === 'all'
                ? 'bg-white text-[#0F172A] font-semibold shadow-xs'
                : 'text-[#64748B] hover:text-[#0F172A]'
            }`}
          >
            All ({consultations.length})
          </button>
          <button
            onClick={() => setStatusFilter('needs_review')}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              statusFilter === 'needs_review'
                ? 'bg-white text-[#B45309] font-semibold shadow-xs'
                : 'text-[#64748B] hover:text-[#0F172A]'
            }`}
          >
            Needs Review (
            {consultations.filter((c) => c.reviewStatus === 'needs_review' || c.reviewStatus === 'draft').length}
            )
          </button>
          <button
            onClick={() => setStatusFilter('approved')}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              statusFilter === 'approved'
                ? 'bg-white text-[#047857] font-semibold shadow-xs'
                : 'text-[#64748B] hover:text-[#0F172A]'
            }`}
          >
            Approved ({consultations.filter((c) => c.reviewStatus === 'approved').length})
          </button>
        </div>
      </div>

      {/* Main Consultations Table or Empty State */}
      {isLoading ? (
        <div className="py-20 text-center space-y-3">
          <div className="size-8 rounded-full border-2 border-[#0D9488]/30 border-t-[#0D9488] animate-spin mx-auto" />
          <p className="text-xs text-[#64748B]">Loading consultation history from backend...</p>
        </div>
      ) : filteredRecords.length === 0 ? (
        <EmptyState
          icon={<Clock size={36} className="text-[#0D9488]" />}
          title={searchQuery ? 'No matching consultations found' : 'No consultations recorded'}
          description={
            searchQuery
              ? `No consultation records match the query "${searchQuery}". Try searching for another Patient ID or clearing your filter.`
              : 'There are no consultation records recorded yet. Start an ambient recording to create your first clinical note, or load a sample consultation.'
          }
          actionLabel={searchQuery ? 'Clear Search' : 'New Consultation'}
          onAction={() => (searchQuery ? setSearchQuery('') : navigate('/consultations/new'))}
          secondaryActionLabel={!searchQuery ? 'Load Sample Consultation' : undefined}
          onSecondaryAction={!searchQuery ? handleLoadSampleDemo : undefined}
        />
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-xs font-semibold text-[#475569] uppercase tracking-wider">
                  <th className="py-3 px-4">Identifier / Title</th>
                  <th className="py-3 px-4">Creation Time</th>
                  <th className="py-3 px-4">Audio Duration</th>
                  <th className="py-3 px-4">Medical Content</th>
                  <th className="py-3 px-4">Review Status</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {filteredRecords.map((record) => {
                  const isApproved = record.reviewStatus === 'approved'
                  return (
                    <tr
                      key={record.id}
                      className="hover:bg-[#F8FAFC] transition-colors cursor-pointer group"
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
                          <span className="text-xs text-[#64748B] block truncate max-w-xs mt-0.5">
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
                            Approved
                          </Badge>
                        ) : record.reviewStatus === 'in_review' ? (
                          <Badge tone="warn" dot>
                            In Review
                          </Badge>
                        ) : record.reviewStatus === 'needs_review' ? (
                          <Badge tone="warn" dot>
                            Draft Generated
                          </Badge>
                        ) : record.status === 'transcript_ready' || record.status === 'transcribed' ? (
                          <Badge tone="info" dot>
                            Transcript Ready
                          </Badge>
                        ) : record.status === 'transcribing' ? (
                          <Badge tone="info" dot>
                            Transcribing
                          </Badge>
                        ) : record.status === 'failed' ? (
                          <Badge tone="danger" dot>
                            Failed
                          </Badge>
                        ) : (
                          <Badge tone="neutral" dot>
                            Uploaded
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
                            SOAP
                          </Button>
                          <button
                            type="button"
                            onClick={() => setDeleteConfirmId(record.id)}
                            className="p-1.5 text-[#94A3B8] hover:text-[#B91C1C] hover:bg-[#FEF2F2] rounded-md transition-colors"
                            title="Delete consultation"
                          >
                            <Trash2 size={14} />
                          </button>
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

      {/* Delete Single Modal */}
      <Modal
        open={Boolean(deleteConfirmId)}
        onClose={() => setDeleteConfirmId(null)}
        title="Delete Consultation Record"
      >
        <div className="space-y-4">
          <p className="text-sm text-[#475569]">
            Are you sure you want to permanently delete consultation record{' '}
            <strong className="text-[#0F172A]">
              {consultations.find((c) => c.id === deleteConfirmId)?.patientId}
            </strong>
            ? This will remove the audio transcript, medical entities, and SOAP note from database history.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setDeleteConfirmId(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => deleteConfirmId && handleDeleteRecord(deleteConfirmId)}
            >
              Confirm Delete
            </Button>
          </div>
        </div>
      </Modal>

      {/* Clear All Modal */}
      <Modal
        open={showClearAllModal}
        onClose={() => setShowClearAllModal(false)}
        title="Clear All Consultation History"
      >
        <div className="space-y-4">
          <p className="text-sm text-[#475569]">
            This will delete all <strong>{consultations.length}</strong> consultation records for this clinician account. This action cannot be undone.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowClearAllModal(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={handleClearAll}>
              Delete All Records
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
