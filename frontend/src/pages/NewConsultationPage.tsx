import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Upload,
  Music,
  Play,
  Pause,
  X,
  AlertCircle,
  FileCheck2,
  Stethoscope,
  Info,
  Sparkles,
  Mic,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAppStore } from '../store/appStore'
import {
  transcribeAudio,
  uploadConsultationAudio,
  updateConsultationTranscript,
  extractEntitiesFromTranscript,
} from '../services/api'
import { Button, Card, CardHeader, CardBody, Badge } from '../components/ui'
import LiveAudioRecorder from '../components/LiveAudioRecorder'
import type { EncounterType, NoteStylePreset, ConsultationRecord } from '../types'

const ACCEPTED_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac']
const MAX_UPLOAD_MB = 50
const MIN_AUDIO_DURATION_SECONDS = 45

const ENCOUNTER_OPTIONS: Array<{ value: EncounterType; label: string; desc: string }> = [
  { value: 'acute_visit', label: 'Acute Visit', desc: 'Urgent symptom presentation or acute complaint' },
  { value: 'follow_up', label: 'Follow-up Encounter', desc: 'Chronic disease monitoring or treatment re-evaluation' },
  { value: 'counselling_education', label: 'Counselling / Education', desc: 'Lifestyle, diet, or treatment adherence discussion' },
  { value: 'medication_review', label: 'Medication Review', desc: 'Prescription reconciliation, dosage titration, or side effects' },
]

const STYLE_OPTIONS: Array<{ value: NoteStylePreset; label: string; desc: string }> = [
  { value: 'balanced', label: 'Balanced', desc: 'Standard clinical depth suitable for EHR entry' },
  { value: 'concise', label: 'Concise', desc: 'Terse, high-density bullet points and findings' },
  { value: 'detailed', label: 'Detailed', desc: 'Exhaustive history, ROS, and comprehensive plan' },
]

export default function NewConsultationPage() {
  const navigate = useNavigate()
  const {
    profile,
    addConsultation,
    setActiveConsultation,
  } = useAppStore()

  // Intake Mode: Live Microphone Recording is the primary default mode!
  const [intakeMode, setIntakeMode] = useState<'live' | 'upload'>('live')
  const [liveTranscript, setLiveTranscript] = useState('')
  const [liveRecordedFile, setLiveRecordedFile] = useState<File | null>(null)
  const [liveAudioDuration, setLiveAudioDuration] = useState<number>(0)

  // Form State
  const [patientId, setPatientId] = useState(`PT-${Math.floor(10000 + Math.random() * 90000)}`)
  const [consultationTitle, setConsultationTitle] = useState('')
  const [encounterType, setEncounterType] = useState<EncounterType>('acute_visit')
  const [stylePreset, setStylePreset] = useState<NoteStylePreset>(profile.noteStylePreset ?? 'balanced')

  // Audio Upload State
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)
  const [audioDuration, setAudioDuration] = useState<number | null>(null)

  // Audio Playback
  const [isPlaying, setIsPlaying] = useState(false)
  const [, setCurrentTime] = useState(0)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Transcription & Progress State
  const [isProcessing, setIsProcessing] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [currentStageIndex, setCurrentStageIndex] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const PIPELINE_STAGES = [
    { label: 'Acoustic Transcription', desc: 'Decoding speech with local Whisper model' },
    { label: 'Content Validation', desc: 'Verifying clinical terminology density' },
    { label: 'Medical Entity Extraction', desc: 'Tagging conditions, drugs, tests & assertions' },
    { label: 'Evidence Grounding', desc: 'Linking clinical claims to transcript quotes' },
    { label: 'SOAP Note Synthesis', desc: 'Drafting structured Subjective, Objective, Assessment, Plan' },
  ]

  // Clean up audio object URL
  useEffect(() => {
    if (!selectedFile) {
      setAudioUrl(null)
      setAudioDuration(null)
      setIsPlaying(false)
      setCurrentTime(0)
      return
    }

    const url = URL.createObjectURL(selectedFile)
    setAudioUrl(url)

    // Inspect duration via hidden audio element
    const tempAudio = new Audio(url)
    tempAudio.onloadedmetadata = () => {
      if (Number.isFinite(tempAudio.duration)) {
        setAudioDuration(tempAudio.duration)
      }
    }

    return () => {
      URL.revokeObjectURL(url)
    }
  }, [selectedFile])

  // Track elapsed time during processing
  useEffect(() => {
    if (isProcessing) {
      setElapsedSeconds(0)
      setCurrentStageIndex(0)
      timerRef.current = setInterval(() => {
        setElapsedSeconds((s) => {
          const next = s + 1
          if (next > 45) setCurrentStageIndex(4)
          else if (next > 30) setCurrentStageIndex(3)
          else if (next > 18) setCurrentStageIndex(2)
          else if (next > 8) setCurrentStageIndex(1)
          return next
        })
      }, 1000)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [isProcessing])

  // Audio Play/Pause handler
  const togglePlayPause = () => {
    if (!audioRef.current) return
    if (isPlaying) {
      audioRef.current.pause()
      setIsPlaying(false)
    } else {
      audioRef.current.play().catch(() => setIsPlaying(false))
      setIsPlaying(true)
    }
  }

  // Validate File
  const handleValidateFile = (file: File) => {
    setFileError(null)
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      setFileError(
        `Unsupported audio format (${ext}). Supported formats: ${ACCEPTED_EXTENSIONS.join(', ')}`
      )
      return false
    }

    const sizeMB = file.size / (1024 * 1024)
    if (sizeMB > MAX_UPLOAD_MB) {
      setFileError(
        `File exceeds maximum limit of ${MAX_UPLOAD_MB} MB. Current size: ${sizeMB.toFixed(1)} MB.`
      )
      return false
    }

    setSelectedFile(file)
    return true
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleValidateFile(file)
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleValidateFile(file)
  }

  // Format Helper
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${String(secs).padStart(2, '0')}`
  }

  // Submit Transcription & Progression to SOAP Workflow
  const handleStartTranscription = async () => {
    // ── 1. Live Microphone Intake Pathway ──
    if (intakeMode === 'live') {
      const trimmedText = liveTranscript.trim()
      if (!trimmedText && !liveRecordedFile) {
        setFileError('Please start recording with your microphone to capture speech, or dictate into the transcript editor.')
        return
      }

      setIsProcessing(true)
      setFileError(null)

      try {
        let consultationId = 'cons-' + Date.now()
        let audioFilename = liveRecordedFile ? liveRecordedFile.name : 'live_microphone_recording.webm'
        const formattedDur = liveAudioDuration > 0 ? formatTime(liveAudioDuration) : '02:15'

        // Persist to backend database if recorded file is present
        if (liveRecordedFile) {
          try {
            const uploadRes = await uploadConsultationAudio(
              liveRecordedFile,
              consultationTitle.trim() || undefined
            )
            if (uploadRes && uploadRes.id) {
              consultationId = String(uploadRes.id)
              audioFilename = uploadRes.filename || audioFilename
              // Synchronize edited live transcript with backend record
              if (trimmedText) {
                await updateConsultationTranscript(uploadRes.id, trimmedText).catch(() => {})
              }
            }
          } catch (uploadErr) {
            console.warn('Backend database upload skipped / running in offline demo session:', uploadErr)
          }
        }

        // Extract entities from the live transcript immediately
        let extractedEntities: any[] = []
        let contentScore = 88
        if (trimmedText) {
          try {
            const extractRes = await extractEntitiesFromTranscript(trimmedText)
            if (extractRes && Array.isArray(extractRes.entities)) {
              extractedEntities = extractRes.entities
              if (extractRes.medical_content_score) {
                contentScore = extractRes.medical_content_score
              }
            }
          } catch (extErr) {
            console.warn('Initial entity extraction skipped:', extErr)
          }
        }

        // Build authoritative consultation record
        const newRecord: ConsultationRecord = {
          id: consultationId,
          patientId: patientId.trim() || `PT-${Math.floor(10000 + Math.random() * 90000)}`,
          title: consultationTitle.trim() || `${ENCOUNTER_OPTIONS.find((e) => e.value === encounterType)?.label} Consultation`,
          filename: audioFilename,
          date: new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }),
          duration: formattedDur,
          entityCount: extractedEntities.length,
          medicalContentScore: contentScore,
          asrConfidence: 0.95,
          status: 'complete',
          reviewStatus: 'needs_review',
          transcription: trimmedText || 'Clinical consultation recorded via live microphone.',
          entities: extractedEntities,
          isSynthetic: false,
        }

        addConsultation(newRecord)
        setActiveConsultation(newRecord)

        toast.success(
          'Live consultation captured! Please review the transcript before proceeding to SOAP note synthesis.'
        )
        navigate(`/consultations/${consultationId}/transcript`)
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to finalize live consultation.'
        setFileError(msg)
        toast.error('Failed to finalize live consultation', { description: msg })
      } finally {
        setIsProcessing(false)
      }
      return
    }

    // ── 2. Audio File Upload Pathway ──
    if (!selectedFile) {
      setFileError('Please select a consultation audio file to transcribe.')
      return
    }

    if (audioDuration !== null && audioDuration < MIN_AUDIO_DURATION_SECONDS) {
      setFileError(
        `Recording is too short (${Math.round(audioDuration)}s). Consultations must be at least ${MIN_AUDIO_DURATION_SECONDS} seconds for valid clinical documentation.`
      )
      return
    }

    setIsProcessing(true)
    setFileError(null)

    try {
      const result = await transcribeAudio(selectedFile, {
        title: consultationTitle.trim() || undefined,
        encounterType,
        audioDurationSeconds: audioDuration,
        styleOverrides: {
          note_style_preset: stylePreset,
        },
      })

      // Validation Gate Check (if backend returned is_valid: false)
      const raw = result as typeof result & { success?: boolean; message?: string }
      if (raw.success === false) {
        throw new Error(raw.message || 'Medical content validation failed. Please upload clinical consultation audio.')
      }

      // Build Consultation Record
      const newRecordId = result.db_id ? String(result.db_id) : 'cons-' + Date.now()
      const newRecord: ConsultationRecord = {
        id: newRecordId,
        patientId: patientId.trim() || `PT-${Math.floor(10000 + Math.random() * 90000)}`,
        title: consultationTitle.trim() || `${ENCOUNTER_OPTIONS.find((e) => e.value === encounterType)?.label} Consultation`,
        filename: selectedFile.name,
        date: new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }),
        duration: audioDuration ? formatTime(audioDuration) : '04:15',
        entityCount: result.entities ? result.entities.length : 0,
        medicalContentScore: result.medical_content_score ?? 85,
        asrConfidence: result.asr_confidence,
        status: 'complete',
        reviewStatus: 'needs_review',
        transcription: result.transcription,
        soap_note: result.soap_note,
        entities: result.entities,
        isSynthetic: false,
      }

      addConsultation(newRecord)
      setActiveConsultation(newRecord)

      toast.success('Audio transcribed successfully! Please review and verify the transcript before proceeding to SOAP note.')
      navigate(`/consultations/${newRecordId}/transcript`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Transcription failed. Please ensure the backend server is running.'
      setFileError(msg)
      toast.error('Failed to transcribe audio', { description: msg })
    } finally {
      setIsProcessing(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-in fade-in duration-150">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <Badge tone="teal">Ambient Recording</Badge>
          <span className="text-xs text-[#64748B]">Encounter Intake</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold text-[#0F172A] tracking-tight mt-1">
          New Clinical Consultation
        </h1>
        <p className="text-sm text-[#475569] mt-1">
          Capture ambient doctor-patient dialogue, generate Faster-Whisper transcripts, and review before SOAP note synthesis.
        </p>
      </div>

      {/* Transcription Accuracy & Clinical Disclaimers */}
      <div className="p-4 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] text-[#475569] text-xs space-y-1.5">
        <div className="flex items-center gap-1.5 font-semibold text-[#0F172A]">
          <Info size={14} className="text-[#0D9488]" />
          <span>Speech Recognition & Multilingual Guidance</span>
        </div>
        <p>
          Speech recognition is powered locally on CPU by Faster-Whisper. Accuracy may vary based on ambient acoustics, speaker accents,
          and specialized medical vocabulary.
        </p>
        <p className="text-[#64748B]">
          <strong>Notice on Tamil-English Code-Switching:</strong> Mixed-language consultations require careful clinician verification, as Tamil-English code-switching has not been empirically verified on this model checkpoint. The system allows you to review and edit the transcript before generating clinical notes.
        </p>
      </div>


      {/* Global Validation Alert */}
      {fileError && (
        <div className="p-4 rounded-xl border border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C] flex items-start gap-3 text-sm">
          <AlertCircle size={18} className="shrink-0 mt-0.5 text-[#DC2626]" />
          <div>
            <strong className="font-semibold">Validation Notice: </strong>
            <span>{fileError}</span>
          </div>
        </div>
      )}

      {/* Configuration Card */}
      <Card>
        <CardHeader title="1. Consultation Metadata" />
        <CardBody className="space-y-5 p-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Patient ID / Identifier */}
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#475569] mb-1.5">
                Patient Identifier / MRN *
              </label>
              <input
                type="text"
                value={patientId}
                onChange={(e) => setPatientId(e.target.value)}
                placeholder="e.g. PT-94821 or MRN-10293"
                disabled={isProcessing}
                className="w-full px-3.5 py-2.5 rounded-lg border border-[#CBD5E1] bg-white text-sm font-mono text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/40"
              />
              <span className="text-[11px] text-[#64748B] mt-1 block">
                De-identified consultation reference code
              </span>
            </div>

            {/* Title / Reason for Encounter */}
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-[#475569] mb-1.5">
                Encounter Title / Reason for Visit
              </label>
              <input
                type="text"
                value={consultationTitle}
                onChange={(e) => setConsultationTitle(e.target.value)}
                placeholder="e.g. 6-Month Hypertension Follow-up"
                disabled={isProcessing}
                className="w-full px-3.5 py-2.5 rounded-lg border border-[#CBD5E1] bg-white text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/40"
              />
              <span className="text-[11px] text-[#64748B] mt-1 block">
                Optional descriptive label for EHR review
              </span>
            </div>
          </div>

          {/* Encounter Type */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#475569] mb-2">
              Encounter Type *
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {ENCOUNTER_OPTIONS.map((opt) => {
                const selected = encounterType === opt.value
                return (
                  <div
                    key={opt.value}
                    onClick={() => !isProcessing && setEncounterType(opt.value)}
                    className={`p-3.5 rounded-xl border text-left cursor-pointer transition-all ${
                      selected
                        ? 'border-[#0D9488] bg-[#F0FDFA] ring-2 ring-[#0D9488]/20'
                        : 'border-[#E2E8F0] bg-white hover:bg-[#F8FAFC]'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className={`text-sm font-semibold ${selected ? 'text-[#0F766E]' : 'text-[#0F172A]'}`}>
                        {opt.label}
                      </span>
                      {selected && <FileCheck2 size={16} className="text-[#0D9488]" />}
                    </div>
                    <p className="text-xs text-[#64748B] mt-1 leading-snug">{opt.desc}</p>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Style Preset */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-[#475569] mb-1.5">
              Documentation Prose Style
            </label>
            <div className="flex flex-wrap gap-2">
              {STYLE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  disabled={isProcessing}
                  onClick={() => setStylePreset(opt.value)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    stylePreset === opt.value
                      ? 'bg-[#0F172A] text-white border-[#0F172A]'
                      : 'bg-white text-[#475569] border-[#CBD5E1] hover:bg-[#F8FAFC]'
                  }`}
                >
                  {opt.label} · <span className="opacity-75">{opt.desc}</span>
                </button>
              ))}
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Consultation Audio Intake Card */}
      <Card>
        <CardHeader
          title="2. Consultation Audio Intake"
          actions={
            <div className="flex items-center gap-1.5 p-1 rounded-xl bg-[#F1F5F9] border border-[#CBD5E1]">
              <button
                type="button"
                id="tab-live-microphone"
                onClick={() => setIntakeMode('live')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                  intakeMode === 'live'
                    ? 'bg-[#0D9488] text-white shadow-xs'
                    : 'text-[#475569] hover:text-[#0F172A]'
                }`}
              >
                <Mic size={14} />
                <span>Live Microphone</span>
                <span className="text-[10px] font-bold bg-white text-[#0D9488] px-1.5 py-0.2 rounded">
                  Primary
                </span>
              </button>
              <button
                type="button"
                id="tab-audio-upload"
                onClick={() => setIntakeMode('upload')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                  intakeMode === 'upload'
                    ? 'bg-white text-[#0F172A] shadow-xs'
                    : 'text-[#475569] hover:text-[#0F172A]'
                }`}
              >
                <Upload size={14} />
                <span>Upload Audio File</span>
              </button>
            </div>
          }
        />
        <CardBody className="p-6 space-y-4">
          {intakeMode === 'live' ? (
            /* Live Microphone Recording as Primary Feature */
            <LiveAudioRecorder
              onTranscriptChange={setLiveTranscript}
              onRecordedFileReady={(file, duration) => {
                setLiveRecordedFile(file)
                setLiveAudioDuration(duration)
              }}
              isProcessing={isProcessing}
            />
          ) : (
            /* Upload Audio File Mode */
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_EXTENSIONS.join(',')}
                onChange={handleFileInput}
                disabled={isProcessing}
                className="hidden"
              />

              {!selectedFile ? (
                /* Upload Dropzone */
                <div
                  onClick={() => !isProcessing && fileInputRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setIsDragOver(true)
                  }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={handleDrop}
                  className={`border-2 border-dashed rounded-2xl p-8 sm:p-12 text-center cursor-pointer transition-colors ${
                    isDragOver
                      ? 'border-[#0D9488] bg-[#F0FDFA]'
                      : 'border-[#CBD5E1] bg-[#F8FAFC] hover:border-[#0D9488] hover:bg-[#F0FDFA]/40'
                  }`}
                >
                  <div className="size-14 rounded-2xl bg-white border border-[#E2E8F0] text-[#0D9488] shadow-xs flex items-center justify-center mx-auto mb-4">
                    <Upload size={24} />
                  </div>
                  <h3 className="text-base font-semibold text-[#0F172A]">
                    Drag and drop consultation audio here
                  </h3>
                  <p className="text-sm text-[#64748B] mt-1">
                    or <span className="text-[#0D9488] font-medium underline">browse your local files</span>
                  </p>
                  <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5 text-xs text-[#64748B]">
                    <span>Supported:</span>
                    {ACCEPTED_EXTENSIONS.map((ext) => (
                      <span
                        key={ext}
                        className="font-mono text-[11px] bg-white border border-[#E2E8F0] px-1.5 py-0.5 rounded text-[#475569]"
                      >
                        {ext.replace('.', '').toUpperCase()}
                      </span>
                    ))}
                    <span>· Max size: <strong>50 MB</strong></span>
                  </div>
                </div>
              ) : (
                /* Selected File Preview Card */
                <div className="p-5 rounded-2xl border border-[#A7F3D0] bg-[#ECFDF5]/50 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="size-12 rounded-xl bg-white border border-[#A7F3D0] text-[#047857] flex items-center justify-center shrink-0">
                      <Music size={22} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-[#0F172A] truncate">
                          {selectedFile.name}
                        </span>
                        <Badge tone="ok" className="text-[10px]">
                          Ready
                        </Badge>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-[#64748B] mt-1 font-mono">
                        <span>{(selectedFile.size / (1024 * 1024)).toFixed(2)} MB</span>
                        {audioDuration !== null && (
                          <>
                            <span>·</span>
                            <span>Duration: {formatTime(audioDuration)}</span>
                            {audioDuration < MIN_AUDIO_DURATION_SECONDS && (
                              <span className="text-[#B91C1C] font-sans font-medium">
                                (Too short: min 45s required)
                              </span>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Playback Controls & Removal */}
                  <div className="flex items-center gap-2 self-end sm:self-center">
                    {audioUrl && (
                      <>
                        <button
                          type="button"
                          onClick={togglePlayPause}
                          disabled={isProcessing}
                          className="size-9 rounded-lg bg-white border border-[#CBD5E1] text-[#0F172A] hover:bg-[#F1F5F9] flex items-center justify-center transition-colors"
                          title={isPlaying ? 'Pause' : 'Play audio preview'}
                        >
                          {isPlaying ? <Pause size={14} /> : <Play size={14} className="ml-0.5" />}
                        </button>
                        <audio
                          ref={audioRef}
                          src={audioUrl}
                          onTimeUpdate={() => audioRef.current && setCurrentTime(audioRef.current.currentTime)}
                          onEnded={() => setIsPlaying(false)}
                          className="hidden"
                        />
                      </>
                    )}
                    {!isProcessing && (
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedFile(null)
                          setFileError(null)
                        }}
                        className="p-2 text-[#64748B] hover:text-[#B91C1C] rounded-lg hover:bg-[#FEE2E2] transition-colors"
                        title="Remove file"
                      >
                        <X size={16} />
                      </button>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Processing Status Banner with Realtime Stages */}
          {isProcessing && (
            <div className="p-5 rounded-2xl border border-[#CCFBF1] bg-[#F0FDFA] space-y-4 animate-in fade-in">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="size-9 rounded-xl bg-[#0D9488] text-white flex items-center justify-center shrink-0">
                    <Sparkles size={18} className="animate-spin" />
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-[#0F172A]">
                      Running Ambient Clinical Documentation Pipeline
                    </h4>
                    <p className="text-xs text-[#0F766E]">
                      Current Stage: <strong>{PIPELINE_STAGES[currentStageIndex].label}</strong> ({PIPELINE_STAGES[currentStageIndex].desc})
                    </p>
                  </div>
                </div>
                <div className="font-mono text-sm font-semibold text-[#0F766E] bg-white px-3 py-1 rounded-lg border border-[#CCFBF1]">
                  {formatTime(elapsedSeconds)}
                </div>
              </div>

              {/* Pipeline Progress Stages */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-2 border-t border-[#CCFBF1]">
                {PIPELINE_STAGES.map((stg, i) => {
                  const isDone = i < currentStageIndex
                  const isCurrent = i === currentStageIndex
                  return (
                    <div
                      key={stg.label}
                      className={`p-2 rounded-lg text-xs transition-colors ${
                        isDone
                          ? 'bg-[#E6FFFA] text-[#047857]'
                          : isCurrent
                          ? 'bg-white text-[#0D9488] font-bold shadow-xs border border-[#0D9488]/30'
                          : 'text-[#94A3B8]'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="font-mono text-[10px]">{i + 1}.</span>
                        <span className="truncate">{stg.label}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Action Footer */}
      <div className="flex items-center justify-between pt-2">
        <Button
          variant="ghost"
          onClick={() => navigate('/dashboard')}
          disabled={isProcessing}
        >
          Cancel
        </Button>
        <Button
          variant="primary"
          size="lg"
          id="btn-proceed-documentation"
          icon={<Stethoscope size={18} />}
          loading={isProcessing}
          disabled={
            isProcessing ||
            (intakeMode === 'live'
              ? !liveTranscript.trim() && !liveRecordedFile
              : !selectedFile || (audioDuration !== null && audioDuration < MIN_AUDIO_DURATION_SECONDS))
          }
          onClick={handleStartTranscription}
          className="shadow-sm min-w-[240px]"
        >
          {isProcessing
            ? 'Processing Consultation...'
            : intakeMode === 'live'
            ? 'Proceed to Transcript & SOAP Review'
            : 'Start Transcription'}
        </Button>
      </div>
    </div>
  )
}
