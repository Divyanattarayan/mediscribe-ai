import { useState, useMemo } from 'react'
import {
  ShieldCheck,
  AlertTriangle,
  HelpCircle,
  AlertCircle,
  FileSearch,
  ExternalLink,
  Info,
  CheckCircle2,
  X,
  Filter,
  RefreshCw,
} from 'lucide-react'
import type { EvidenceLinks, EvidenceStatement } from '../types'
import { Badge, Button } from './ui'

interface EvidenceReviewPanelProps {
  evidence?: EvidenceLinks | null
  transcript?: string
  isLoading?: boolean
  onRefresh?: () => void
}

export default function EvidenceReviewPanel({
  evidence,
  transcript = '',
  isLoading = false,
  onRefresh,
}: EvidenceReviewPanelProps) {
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [filterSection, setFilterSection] = useState<string>('all')
  const [selectedStatement, setSelectedStatement] = useState<EvidenceStatement | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)

  const statements = evidence?.statements ?? []

  const filteredStatements = useMemo(() => {
    return statements.filter((s) => {
      const matchStatus = filterStatus === 'all' || s.status === filterStatus
      const matchSection = filterSection === 'all' || s.section.toLowerCase() === filterSection.toLowerCase()
      return matchStatus && matchSection
    })
  }, [statements, filterStatus, filterSection])

  const openTranscriptModal = (stmt: EvidenceStatement) => {
    setSelectedStatement(stmt)
    setIsModalOpen(true)
  }

  const closeTranscriptModal = () => {
    setIsModalOpen(false)
    setSelectedStatement(null)
  }

  // Highlight transcript passage
  const highlightedTranscript = useMemo(() => {
    if (!transcript) return null
    if (!selectedStatement || selectedStatement.evidence_start == null || selectedStatement.evidence_end == null) {
      return <span>{transcript}</span>
    }

    const start = Math.max(0, selectedStatement.evidence_start)
    const end = Math.min(transcript.length, selectedStatement.evidence_end)

    if (start >= end || start >= transcript.length) {
      return <span>{transcript}</span>
    }

    const before = transcript.slice(0, start)
    const target = transcript.slice(start, end)
    const after = transcript.slice(end)

    return (
      <div className="font-mono text-xs leading-relaxed whitespace-pre-wrap select-text">
        <span className="text-[#64748B]">{before}</span>
        <mark className="bg-amber-200 text-amber-950 font-semibold px-1 py-0.5 rounded shadow-sm border border-amber-300">
          {target}
        </mark>
        <span className="text-[#64748B]">{after}</span>
      </div>
    )
  }, [transcript, selectedStatement])

  if (!evidence && !isLoading) {
    return (
      <div className="p-8 text-center rounded-xl border border-dashed border-[#CBD5E1] bg-[#F8FAFC]">
        <FileSearch size={36} className="mx-auto text-[#94A3B8] mb-2" />
        <h4 className="text-sm font-semibold text-[#0F172A]">No Evidence Mapped</h4>
        <p className="text-xs text-[#64748B] max-w-md mx-auto mt-1">
          Evidence links have not been generated for this note yet. Generate or update the SOAP note to evaluate transcript grounding.
        </p>
        {onRefresh && (
          <Button
            variant="secondary"
            size="sm"
            onClick={onRefresh}
            className="mt-4"
            icon={<RefreshCw size={13} />}
          >
            Run Evidence Audit
          </Button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* ── Mandatory Clinical Accuracy Disclaimer ─────────────── */}
      <div className="p-3.5 rounded-xl border border-teal-200 bg-teal-50/70 text-teal-900 flex items-start gap-2.5 shadow-xs">
        <Info size={18} className="shrink-0 mt-0.5 text-teal-700" />
        <div className="text-xs leading-relaxed">
          <strong className="font-semibold block text-teal-950 mb-0.5">
            Evidence Verification Notice
          </strong>
          {evidence?.disclaimer ||
            'Evidence linking identifies supporting transcript passages only and does not verify or guarantee clinical accuracy or medical correctness. Clinician judgement is always required.'}
        </div>
      </div>

      {/* ── Statistics Summary Bar ────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
        <button
          type="button"
          onClick={() => setFilterStatus('all')}
          className={`p-3 rounded-xl border text-left transition-all ${
            filterStatus === 'all'
              ? 'border-[#0D9488] bg-[#0D9488]/5 ring-1 ring-[#0D9488]'
              : 'border-[#E2E8F0] bg-white hover:border-[#CBD5E1]'
          }`}
        >
          <div className="text-[11px] font-medium text-[#64748B]">Total Statements</div>
          <div className="text-lg font-bold text-[#0F172A] mt-0.5">
            {evidence?.total_statements ?? statements.length}
          </div>
        </button>

        <button
          type="button"
          onClick={() => setFilterStatus('supported')}
          className={`p-3 rounded-xl border text-left transition-all ${
            filterStatus === 'supported'
              ? 'border-emerald-500 bg-emerald-50/80 ring-1 ring-emerald-500'
              : 'border-[#E2E8F0] bg-white hover:border-[#CBD5E1]'
          }`}
        >
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-emerald-700">
            <CheckCircle2 size={13} />
            <span>Supported</span>
          </div>
          <div className="text-lg font-bold text-emerald-800 mt-0.5">
            {evidence?.supported_count ?? 0}
          </div>
        </button>

        <button
          type="button"
          onClick={() => setFilterStatus('ambiguous')}
          className={`p-3 rounded-xl border text-left transition-all ${
            filterStatus === 'ambiguous'
              ? 'border-amber-500 bg-amber-50/80 ring-1 ring-amber-500'
              : 'border-[#E2E8F0] bg-white hover:border-[#CBD5E1]'
          }`}
        >
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-amber-700">
            <HelpCircle size={13} />
            <span>Ambiguous</span>
          </div>
          <div className="text-lg font-bold text-amber-800 mt-0.5">
            {evidence?.ambiguous_count ?? 0}
          </div>
        </button>

        <button
          type="button"
          onClick={() => setFilterStatus('conflicting')}
          className={`p-3 rounded-xl border text-left transition-all ${
            filterStatus === 'conflicting'
              ? 'border-rose-500 bg-rose-50/80 ring-1 ring-rose-500'
              : 'border-[#E2E8F0] bg-white hover:border-[#CBD5E1]'
          }`}
        >
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-rose-700">
            <AlertCircle size={13} />
            <span>Conflicting</span>
          </div>
          <div className="text-lg font-bold text-rose-800 mt-0.5">
            {evidence?.conflicting_count ?? 0}
          </div>
        </button>

        <button
          type="button"
          onClick={() => setFilterStatus('unsupported')}
          className={`p-3 rounded-xl border text-left transition-all ${
            filterStatus === 'unsupported'
              ? 'border-orange-500 bg-orange-50/80 ring-1 ring-orange-500'
              : 'border-[#E2E8F0] bg-white hover:border-[#CBD5E1]'
          }`}
        >
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-orange-700">
            <AlertTriangle size={13} />
            <span>Unsupported</span>
          </div>
          <div className="text-lg font-bold text-orange-800 mt-0.5">
            {evidence?.unsupported_count ?? 0}
          </div>
        </button>
      </div>

      {/* ── Section Filter Buttons ────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1 pb-1">
        <div className="flex items-center gap-1.5">
          <Filter size={13} className="text-[#64748B]" />
          <span className="text-xs font-medium text-[#64748B]">Section:</span>
          {(['all', 'subjective', 'objective', 'assessment', 'plan'] as const).map((sec) => (
            <button
              key={sec}
              type="button"
              onClick={() => setFilterSection(sec)}
              className={`px-2.5 py-1 text-xs rounded-lg font-medium transition-colors ${
                filterSection === sec
                  ? 'bg-[#0F172A] text-white'
                  : 'bg-[#F1F5F9] text-[#64748B] hover:bg-[#E2E8F0] hover:text-[#0F172A]'
              }`}
            >
              {sec.charAt(0).toUpperCase() + sec.slice(1)}
            </button>
          ))}
        </div>

        {onRefresh && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onRefresh}
            loading={isLoading}
            icon={<RefreshCw size={12} />}
          >
            Re-evaluate Evidence
          </Button>
        )}
      </div>

      {/* ── Statement Evidence List ───────────────────────────── */}
      {filteredStatements.length === 0 ? (
        <div className="p-8 text-center rounded-xl border border-dashed border-[#CBD5E1] bg-[#F8FAFC]">
          <p className="text-xs text-[#64748B]">No statements match the active filters.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredStatements.map((stmt) => {
            const isSupported = stmt.status === 'supported'
            const isAmbiguous = stmt.status === 'ambiguous'
            const isConflicting = stmt.status === 'conflicting'
            const isUnsupported = stmt.status === 'unsupported'

            return (
              <div
                key={stmt.id}
                className={`p-4 rounded-xl border transition-all ${
                  isConflicting
                    ? 'border-rose-300 bg-rose-50/40 shadow-xs'
                    : isAmbiguous
                    ? 'border-amber-300 bg-amber-50/30'
                    : isUnsupported
                    ? 'border-orange-200 bg-orange-50/20'
                    : 'border-[#E2E8F0] bg-white hover:border-[#CBD5E1]'
                }`}
              >
                {/* Statement Header */}
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2">
                    <span className="size-5 rounded bg-[#0F172A]/5 text-[#0F172A] font-bold text-[10px] flex items-center justify-center font-mono">
                      {stmt.section.charAt(0).toUpperCase()}
                    </span>
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B]">
                      {stmt.section}
                    </span>
                    <span className="text-[10px] text-[#94A3B8] font-mono">#{stmt.id}</span>
                  </div>

                  {/* Status Badge */}
                  <div>
                    {isSupported && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800 border border-emerald-200">
                        <CheckCircle2 size={12} />
                        Supported ({Math.round(stmt.similarity)}%)
                      </span>
                    )}
                    {isAmbiguous && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-300">
                        <HelpCircle size={12} />
                        Ambiguous Dialogue
                      </span>
                    )}
                    {isConflicting && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-100 text-rose-900 border border-rose-300 animate-pulse">
                        <AlertCircle size={12} />
                        Conflicting Evidence
                      </span>
                    )}
                    {isUnsupported && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-orange-100 text-orange-900 border border-orange-300">
                        <AlertTriangle size={12} />
                        Review Required
                      </span>
                    )}
                  </div>
                </div>

                {/* Clinical Statement Text */}
                <p className="text-sm font-medium text-[#0F172A] leading-relaxed">
                  {stmt.statement}
                </p>

                {/* Conflicting / Ambiguous Review Warnings */}
                {stmt.review_message && (
                  <div
                    className={`mt-2.5 p-2.5 rounded-lg text-xs leading-snug flex items-start gap-2 ${
                      isConflicting
                        ? 'bg-rose-100/90 text-rose-900 font-medium border border-rose-200'
                        : isAmbiguous
                        ? 'bg-amber-100/90 text-amber-900 font-medium border border-amber-200'
                        : isUnsupported
                        ? 'bg-orange-100/80 text-orange-900 font-semibold border border-orange-200'
                        : 'bg-slate-100 text-slate-700'
                    }`}
                  >
                    {isConflicting ? (
                      <AlertCircle size={14} className="shrink-0 mt-0.5 text-rose-700" />
                    ) : isAmbiguous ? (
                      <HelpCircle size={14} className="shrink-0 mt-0.5 text-amber-700" />
                    ) : (
                      <AlertTriangle size={14} className="shrink-0 mt-0.5 text-orange-700" />
                    )}
                    <span>{stmt.review_message}</span>
                  </div>
                )}

                {/* Evidence Quote Excerpt (if grounded) */}
                {stmt.evidence_quote ? (
                  <div className="mt-3 p-3 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0]">
                    <div className="flex items-center justify-between text-[11px] font-semibold text-[#64748B] mb-1.5">
                      <span className="flex items-center gap-1.5">
                        <FileSearch size={12} className="text-[#0D9488]" />
                        <span>Verbatim Transcript Excerpt</span>
                      </span>
                      {stmt.evidence_start != null && stmt.evidence_end != null && (
                        <span className="font-mono text-[10px] text-[#94A3B8]">
                          Offsets: [{stmt.evidence_start}–{stmt.evidence_end}]
                        </span>
                      )}
                    </div>

                    <blockquote className="text-xs text-[#334155] italic border-l-2 border-[#0D9488] pl-2.5 py-0.5 leading-relaxed bg-white rounded-r">
                      "{stmt.evidence_quote}"
                    </blockquote>

                    {transcript && (
                      <div className="mt-2 flex justify-end">
                        <button
                          type="button"
                          onClick={() => openTranscriptModal(stmt)}
                          className="text-xs font-semibold text-[#0D9488] hover:text-[#0F766E] flex items-center gap-1 transition-colors"
                        >
                          <ExternalLink size={12} />
                          <span>Inspect in Full Transcript</span>
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  isUnsupported && (
                    <div className="mt-2.5 p-2.5 rounded-lg bg-orange-50 border border-orange-200 text-xs font-medium text-orange-900 flex items-center gap-2">
                      <AlertTriangle size={13} className="text-orange-600 shrink-0" />
                      <span>Evidence not found — review required.</span>
                    </div>
                  )
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* ── Interactive Transcript Inspector Modal ────────────── */}
      {isModalOpen && selectedStatement && (
        <div
          className="fixed inset-0 z-50 grid place-items-center p-4 bg-black/50 backdrop-blur-xs animate-in fade-in"
          onClick={closeTranscriptModal}
        >
          <div
            className="w-full max-w-3xl max-h-[85vh] flex flex-col bg-white border border-[#CBD5E1] rounded-2xl shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="p-4 px-6 border-b border-[#E2E8F0] flex items-center justify-between bg-[#F8FAFC]">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-[#0D9488]">
                    Transcript Evidence Inspector
                  </span>
                  <span className="text-xs text-[#94A3B8]">·</span>
                  <span className="text-xs font-medium text-[#64748B]">
                    Statement #{selectedStatement.id} ({selectedStatement.section})
                  </span>
                </div>
                <h3 className="text-sm font-semibold text-[#0F172A] mt-0.5 line-clamp-1">
                  {selectedStatement.statement}
                </h3>
              </div>
              <button
                type="button"
                onClick={closeTranscriptModal}
                className="p-1 rounded-lg text-[#64748B] hover:text-[#0F172A] hover:bg-[#E2E8F0] transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Highlighted Target Banner */}
            <div className="p-3 px-6 bg-amber-50/80 border-b border-amber-200 text-xs text-amber-950 flex items-start gap-2">
              <Info size={15} className="text-amber-700 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Matched Passage:</span> "{selectedStatement.evidence_quote}"
                {selectedStatement.evidence_start != null && selectedStatement.evidence_end != null && (
                  <span className="ml-2 font-mono text-[10px] text-amber-800">
                    [chars {selectedStatement.evidence_start} to {selectedStatement.evidence_end}]
                  </span>
                )}
              </div>
            </div>

            {/* Modal Scrollable Transcript */}
            <div className="p-6 overflow-y-auto flex-1 bg-white">
              <div className="text-xs font-semibold uppercase tracking-wider text-[#64748B] mb-2">
                Verbatim Consultation Transcript:
              </div>
              <div className="p-4 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC]">
                {highlightedTranscript}
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-3 px-6 border-t border-[#E2E8F0] bg-[#F8FAFC] flex items-center justify-between text-xs text-[#64748B]">
              <span>
                Verbatim slices are extracted directly without modification to ensure clinical fidelity.
              </span>
              <Button variant="secondary" size="sm" onClick={closeTranscriptModal}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
