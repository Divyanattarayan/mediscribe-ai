import React, { useState, useRef, useEffect } from 'react'
import {
  Mic,
  MicOff,
  Square,
  Play,
  Pause,
  RotateCcw,
  Copy,
  Check,
  AlertCircle,
  Volume2,
  VolumeX,
  Sparkles,
  Info,
  CheckCircle2,
  Radio,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button, Badge } from './ui'
import { useLiveSpeechTranscription } from '../hooks/useLiveSpeechTranscription'

interface LiveAudioRecorderProps {
  onTranscriptChange: (text: string) => void
  onRecordedFileReady: (file: File | null, durationSeconds: number) => void
  isProcessing?: boolean
}

export default function LiveAudioRecorder({
  onTranscriptChange,
  onRecordedFileReady,
  isProcessing = false,
}: LiveAudioRecorderProps) {
  const {
    isRecording,
    isPaused,
    isPermissionGranted,
    isRequestingPermission,
    isSpeechSupported,
    transcript,
    interimTranscript,
    audioLevel,
    durationSeconds,
    recordedBlob,
    recordedFile,
    recordedAudioUrl,
    error,
    permissionError,
    startRecording,
    stopRecording,
    pauseRecording,
    resumeRecording,
    setTranscript,
    resetSession,
  } = useLiveSpeechTranscription()

  const [copied, setCopied] = useState(false)
  const [isPlayingPreview, setIsPlayingPreview] = useState(false)
  const audioPreviewRef = useRef<HTMLAudioElement | null>(null)

  // Notify parent component of transcript changes
  useEffect(() => {
    onTranscriptChange(transcript)
  }, [transcript, onTranscriptChange])

  // Notify parent component when recorded audio file is ready
  useEffect(() => {
    onRecordedFileReady(recordedFile, durationSeconds)
  }, [recordedFile, durationSeconds, onRecordedFileReady])

  // Format time MM:SS
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }

  // Copy transcript handler
  const handleCopy = async () => {
    if (!transcript) return
    await navigator.clipboard.writeText(transcript)
    setCopied(true)
    toast.success('Transcript copied to clipboard')
    setTimeout(() => setCopied(false), 2000)
  }

  // Audio preview play/pause
  const togglePreviewPlayback = () => {
    if (!audioPreviewRef.current) return
    if (isPlayingPreview) {
      audioPreviewRef.current.pause()
      setIsPlayingPreview(false)
    } else {
      audioPreviewRef.current.play().catch(() => setIsPlayingPreview(false))
      setIsPlayingPreview(true)
    }
  }

  const wordCount = transcript.trim() ? transcript.trim().split(/\s+/).length : 0

  return (
    <div className="space-y-4">
      {/* ── Microphone Permission & Browser Support Alerts ── */}
      {permissionError && (
        <div className="p-4 rounded-xl border border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C] flex items-start gap-3 text-xs sm:text-sm animate-in fade-in">
          <MicOff size={20} className="shrink-0 text-[#DC2626] mt-0.5" />
          <div className="space-y-1">
            <strong className="font-semibold block text-[#991B1B]">
              Microphone Permission Denied
            </strong>
            <p className="text-[#B91C1C]">{permissionError}</p>
            <p className="text-[#991B1B] text-xs">
              To resolve: Click the camera/microphone icon in your browser URL address bar and choose &quot;Always allow&quot;, then try again.
            </p>
          </div>
        </div>
      )}

      {error && !permissionError && (
        <div className="p-4 rounded-xl border border-[#FED7AA] bg-[#FFFBEB] text-[#9A3412] flex items-start gap-3 text-xs sm:text-sm animate-in fade-in">
          <AlertCircle size={20} className="shrink-0 text-[#EA580C] mt-0.5" />
          <div className="space-y-1">
            <strong className="font-semibold block text-[#7C2D12]">
              Speech Recognition Notice
            </strong>
            <p>{error}</p>
          </div>
        </div>
      )}

      {!isSpeechSupported && !error && (
        <div className="p-3.5 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] text-[#475569] flex items-start gap-3 text-xs">
          <Info size={16} className="shrink-0 text-[#0D9488] mt-0.5" />
          <p>
            <strong>Browser Compatibility:</strong> Continuous speech recognition is supported in Google Chrome, Microsoft Edge, and Safari. Your microphone audio is still recorded, and you can edit the transcript directly.
          </p>
        </div>
      )}

      {/* ── Main Recording Control Panel ── */}
      <div className={`p-6 rounded-2xl border transition-all ${
        isRecording
          ? 'border-[#0D9488] bg-[#F0FDFA]/70 shadow-sm'
          : recordedBlob
          ? 'border-[#A7F3D0] bg-[#ECFDF5]/40'
          : 'border-[#CBD5E1] bg-white'
      }`}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          {/* Left: Status & Duration */}
          <div className="flex items-center gap-4">
            <div
              className={`size-14 rounded-2xl flex items-center justify-center transition-all ${
                isRecording
                  ? 'bg-[#DC2626] text-white shadow-md shadow-red-200 animate-pulse'
                  : isPaused
                  ? 'bg-[#F59E0B] text-white'
                  : recordedBlob
                  ? 'bg-[#0D9488] text-white'
                  : 'bg-[#F1F5F9] text-[#64748B]'
              }`}
            >
              {isRecording ? (
                <Radio size={28} className="animate-spin" />
              ) : isPaused ? (
                <Pause size={26} />
              ) : recordedBlob ? (
                <CheckCircle2 size={26} />
              ) : (
                <Mic size={26} />
              )}
            </div>

            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-base text-[#0F172A]">
                  {isRecording
                    ? isPaused
                      ? 'Recording Paused'
                      : 'Live Recording in Progress...'
                    : recordedBlob
                    ? 'Recording Completed'
                    : 'Live Microphone Capture'}
                </span>
                {isRecording && !isPaused && (
                  <Badge tone="danger" className="text-[10px] animate-pulse">
                    LIVE
                  </Badge>
                )}
                {isPaused && (
                  <Badge tone="warn" className="text-[10px]">
                    PAUSED
                  </Badge>
                )}
                {recordedBlob && !isRecording && (
                  <Badge tone="ok" className="text-[10px]">
                    READY
                  </Badge>
                )}
              </div>

              <div className="flex items-center gap-3 text-xs text-[#64748B] mt-1 font-mono">
                <span className="font-semibold text-sm text-[#0F172A]">
                  {formatTime(durationSeconds)}
                </span>
                <span>·</span>
                <span>
                  {isRecording
                    ? 'Speak clearly into your microphone'
                    : recordedBlob
                    ? 'Audio captured & ready for documentation'
                    : 'Click Start Recording to begin'}
                </span>
              </div>
            </div>
          </div>

          {/* Right: Audio Visualizer & Action Buttons */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Live Audio Level Meter */}
            {isRecording && !isPaused && (
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-[#CCFBF1] shadow-2xs">
                {audioLevel > 5 ? (
                  <Volume2 size={16} className="text-[#0D9488] animate-bounce" />
                ) : (
                  <VolumeX size={16} className="text-[#94A3B8]" />
                )}
                <div className="flex items-end gap-0.5 h-4 w-12">
                  {[15, 30, 45, 60, 75].map((threshold, idx) => (
                    <div
                      key={idx}
                      className={`w-2 rounded-t-sm transition-all duration-75 ${
                        audioLevel >= threshold
                          ? 'bg-[#0D9488]'
                          : 'bg-[#E2E8F0]'
                      }`}
                      style={{
                        height: `${Math.max(20, Math.min(100, (idx + 1) * 20))}%`,
                      }}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* 1. Start Recording Button */}
            {!isRecording && (
              <Button
                variant="primary"
                size="md"
                id="btn-start-recording"
                icon={<Mic size={18} />}
                disabled={isProcessing || isRequestingPermission}
                loading={isRequestingPermission}
                onClick={startRecording}
                className="bg-[#0D9488] hover:bg-[#0F766E] shadow-xs"
              >
                {isRequestingPermission
                  ? 'Requesting Mic...'
                  : recordedBlob
                  ? 'Record Again'
                  : 'Start Recording'}
              </Button>
            )}

            {/* Pause / Resume Controls */}
            {isRecording && (
              <>
                {isPaused ? (
                  <Button
                    variant="secondary"
                    size="md"
                    id="btn-resume-recording"
                    icon={<Play size={16} />}
                    onClick={resumeRecording}
                  >
                    Resume
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    size="md"
                    id="btn-pause-recording"
                    icon={<Pause size={16} />}
                    onClick={pauseRecording}
                  >
                    Pause
                  </Button>
                )}

                {/* 2. Stop Recording Button */}
                <Button
                  variant="danger"
                  size="md"
                  id="btn-stop-recording"
                  icon={<Square size={16} />}
                  onClick={stopRecording}
                  className="bg-[#DC2626] hover:bg-[#B91C1C] text-white shadow-sm"
                >
                  Stop Recording
                </Button>
              </>
            )}

            {/* Reset Session */}
            {(recordedBlob || transcript) && !isRecording && (
              <Button
                variant="ghost"
                size="sm"
                icon={<RotateCcw size={14} />}
                disabled={isProcessing}
                onClick={resetSession}
                title="Clear current recording and transcript"
              >
                Reset
              </Button>
            )}
          </div>
        </div>

        {/* ── Audio Playback Preview (After Recording Stops) ── */}
        {recordedAudioUrl && !isRecording && (
          <div className="mt-4 pt-4 border-t border-[#E2E8F0] flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={togglePreviewPlayback}
                className="size-8 rounded-lg bg-white border border-[#CBD5E1] text-[#0F172A] hover:bg-[#F1F5F9] flex items-center justify-center transition-colors shadow-2xs"
                title={isPlayingPreview ? 'Pause audio preview' : 'Play audio preview'}
              >
                {isPlayingPreview ? <Pause size={14} /> : <Play size={14} className="ml-0.5" />}
              </button>
              <audio
                ref={audioPreviewRef}
                src={recordedAudioUrl}
                onEnded={() => setIsPlayingPreview(false)}
                className="hidden"
              />
              <span className="text-[#475569] font-medium">
                Audio preview ({formatTime(durationSeconds)}) · Captured via browser microphone
              </span>
            </div>
            <span className="font-mono text-[11px] text-[#64748B]">
              Format: {recordedBlob?.type || 'audio/webm'} ({(recordedBlob ? recordedBlob.size / 1024 : 0).toFixed(1)} KB)
            </span>
          </div>
        )}
      </div>

      {/* ── Live Recognized Speech Display & Clinician Review Editor ── */}
      <div className="p-5 rounded-2xl border border-[#CBD5E1] bg-white space-y-3 shadow-2xs">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-[#0D9488]" />
            <h3 className="text-sm font-semibold text-[#0F172A]">
              Live Speech Transcript (Progressive & Editable)
            </h3>
            {isRecording && !isPaused && (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F0FDFA] text-[#0D9488] border border-[#CCFBF1]">
                <span className="size-1.5 rounded-full bg-[#0D9488] animate-ping" />
                Listening to speech...
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 text-xs text-[#64748B]">
            <span className="font-mono">
              {wordCount} {wordCount === 1 ? 'word' : 'words'}
            </span>
            <span>·</span>
            <span className="font-mono">{transcript.length} chars</span>
            {transcript && (
              <button
                type="button"
                onClick={handleCopy}
                className="ml-2 inline-flex items-center gap-1 px-2 py-1 rounded bg-[#F1F5F9] hover:bg-[#E2E8F0] text-[#0F172A] transition-colors"
                title="Copy transcript"
              >
                {copied ? <Check size={12} className="text-[#0D9488]" /> : <Copy size={12} />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            )}
          </div>
        </div>

        {/* Live Interim Streaming Indicator */}
        {isRecording && interimTranscript && (
          <div className="p-2.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] text-xs font-mono text-[#0D9488] italic flex items-center gap-2">
            <span className="size-2 rounded-full bg-[#0D9488] animate-pulse" />
            <span>Speaking now: &quot;{interimTranscript}&quot;</span>
          </div>
        )}

        {/* Clinician Review & Edit Text Area */}
        <div className="relative">
          <textarea
            id="live-transcript-editor"
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            disabled={isProcessing}
            rows={6}
            placeholder={
              isRecording
                ? 'Listening to live microphone... Recognized medical dialogue will display progressively here.'
                : 'Recognized speech from your live microphone will appear here progressively. You can edit, format, or type additional clinical notes directly into this box.'
            }
            className="w-full px-4 py-3 rounded-xl border border-[#CBD5E1] bg-[#F8FAFC] focus:bg-white text-sm text-[#0F172A] leading-relaxed font-sans placeholder:text-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#0D9488]/30 transition-all resize-y"
          />
        </div>

        <div className="flex items-center justify-between text-[11px] text-[#64748B]">
          <span>
            {isRecording
              ? 'Speech updates continuously as you speak. You can freely edit text during or after recording.'
              : 'Review and correct any medical terms, dosages, or acronyms before synthesizing the SOAP note.'}
          </span>
          {transcript && (
            <span className="text-[#0D9488] font-medium flex items-center gap-1">
              <CheckCircle2 size={12} />
              Transcript editable
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
