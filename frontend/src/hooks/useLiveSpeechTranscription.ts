import { useState, useRef, useEffect, useCallback } from 'react'
import type {
  ISpeechRecognition,
  ISpeechRecognitionEvent,
  ISpeechRecognitionErrorEvent,
} from '../types'

export interface LiveTranscriptionState {
  isRecording: boolean
  isPaused: boolean
  isPermissionGranted: boolean
  isRequestingPermission: boolean
  isSpeechSupported: boolean
  transcript: string
  interimTranscript: string
  audioLevel: number // 0 to 100 for live reactive visualizer
  durationSeconds: number
  recordedBlob: Blob | null
  recordedFile: File | null
  recordedAudioUrl: string | null
  error: string | null
  permissionError: string | null
}

export function useLiveSpeechTranscription() {
  const [isRecording, setIsRecording] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [isPermissionGranted, setIsPermissionGranted] = useState(false)
  const [isRequestingPermission, setIsRequestingPermission] = useState(false)
  const [isSpeechSupported, setIsSpeechSupported] = useState(true)
  const [transcript, setTranscript] = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [audioLevel, setAudioLevel] = useState(0)
  const [durationSeconds, setDurationSeconds] = useState(0)
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null)
  const [recordedFile, setRecordedFile] = useState<File | null>(null)
  const [recordedAudioUrl, setRecordedAudioUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [permissionError, setPermissionError] = useState<string | null>(null)

  // Internal references
  const recognitionRef = useRef<ISpeechRecognition | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animFrameRef = useRef<number | null>(null)
  const isManuallyStoppedRef = useRef(false)
  const finalTranscriptAccumulatorRef = useRef('')

  // Check Web Speech API availability on mount
  useEffect(() => {
    const SpeechRecognitionAPI =
      (window as unknown as { SpeechRecognition?: new () => ISpeechRecognition }).SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: new () => ISpeechRecognition }).webkitSpeechRecognition

    if (!SpeechRecognitionAPI) {
      setIsSpeechSupported(false)
    }
  }, [])

  // Audio level visualization analyzer loop
  const updateAudioMeter = useCallback(() => {
    if (!analyserRef.current) return
    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(dataArray)

    // Calculate RMS / average level
    let sum = 0
    for (let i = 0; i < dataArray.length; i++) {
      sum += dataArray[i]
    }
    const average = sum / dataArray.length
    // Normalize to 0-100 range
    const normalizedLevel = Math.min(100, Math.round((average / 128) * 100))
    setAudioLevel(normalizedLevel)

    animFrameRef.current = requestAnimationFrame(updateAudioMeter)
  }, [])

  // Clean up audio URL on unmount or new recording
  useEffect(() => {
    return () => {
      if (recordedAudioUrl) {
        URL.revokeObjectURL(recordedAudioUrl)
      }
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current)
      }
      if (timerRef.current) {
        clearInterval(timerRef.current)
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((track) => track.stop())
      }
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close().catch(() => {})
      }
    }
  }, [recordedAudioUrl])

  // Stop recording implementation
  const stopRecording = useCallback(() => {
    isManuallyStoppedRef.current = true
    setIsRecording(false)
    setIsPaused(false)
    setInterimTranscript('')
    setAudioLevel(0)

    // Stop duration timer
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }

    // Stop audio visualizer
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current)
      animFrameRef.current = null
    }

    // Stop speech recognition
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {
        // Ignore if already stopped
      }
      recognitionRef.current = null
    }

    // Stop MediaRecorder (generates final recorded Blob in onstop)
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      try {
        mediaRecorderRef.current.stop()
      } catch {
        // Ignore error
      }
    }

    // Stop microphone audio tracks
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => {
        track.stop()
      })
      mediaStreamRef.current = null
    }

    // Close AudioContext
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {})
      audioContextRef.current = null
    }
  }, [])

  // Start recording implementation
  const startRecording = useCallback(async () => {
    setError(null)
    setPermissionError(null)
    setInterimTranscript('')
    isManuallyStoppedRef.current = false

    // Revoke previous audio preview URL if existing
    if (recordedAudioUrl) {
      URL.revokeObjectURL(recordedAudioUrl)
      setRecordedAudioUrl(null)
    }
    setRecordedBlob(null)
    setRecordedFile(null)

    // Check getUserMedia support
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      const err = 'Live microphone capture is not supported in this browser or insecure context (HTTPS or localhost required).'
      setError(err)
      return false
    }

    setIsRequestingPermission(true)

    let stream: MediaStream
    try {
      // 1. Request microphone permission
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      mediaStreamRef.current = stream
      setIsPermissionGranted(true)
      setIsRequestingPermission(false)
    } catch (err: unknown) {
      setIsRequestingPermission(false)
      setIsPermissionGranted(false)

      const domError = err as { name?: string; message?: string }
      let message = 'Unable to access microphone.'

      if (domError.name === 'NotAllowedError' || domError.name === 'PermissionDeniedError') {
        message = 'Microphone permission was denied. Please allow microphone access in your browser address bar/settings.'
        setPermissionError(message)
      } else if (domError.name === 'NotFoundError' || domError.name === 'DevicesNotFoundError') {
        message = 'No microphone device found. Please attach or enable an audio input device.'
      } else if (domError.name === 'NotReadableError' || domError.name === 'TrackStartError') {
        message = 'Microphone is already in use by another application.'
      } else {
        message = `Microphone access error: ${domError.message || 'Unknown error'}`
      }

      setError(message)
      return false
    }

    // 2. Setup Web Audio API Analyser for live visualizer
    try {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (AudioCtx) {
        const audioCtx = new AudioCtx()
        audioContextRef.current = audioCtx
        const source = audioCtx.createMediaStreamSource(stream)
        const analyser = audioCtx.createAnalyser()
        analyser.fftSize = 64
        source.connect(analyser)
        analyserRef.current = analyser
        updateAudioMeter()
      }
    } catch (audioCtxErr) {
      console.warn('AudioContext visualization setup skipped:', audioCtxErr)
    }

    // 3. Setup MediaRecorder to record audio file
    try {
      audioChunksRef.current = []

      // Pick best supported MIME type
      let mimeType = 'audio/webm;codecs=opus'
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        if (MediaRecorder.isTypeSupported('audio/webm')) {
          mimeType = 'audio/webm'
        } else if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
          mimeType = 'audio/ogg;codecs=opus'
        } else {
          mimeType = '' // browser default
        }
      }

      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      recorder.onstop = () => {
        const actualMime = recorder.mimeType || 'audio/webm'
        const blob = new Blob(audioChunksRef.current, { type: actualMime })
        setRecordedBlob(blob)

        const ext = actualMime.includes('ogg') ? 'ogg' : 'webm'
        const filename = `live_consultation_${Date.now()}.${ext}`
        const file = new File([blob], filename, { type: actualMime })
        setRecordedFile(file)

        const url = URL.createObjectURL(blob)
        setRecordedAudioUrl(url)
      }

      recorder.start(1000) // Collect 1s slices
    } catch (recErr) {
      console.warn('MediaRecorder initialisation warning:', recErr)
    }

    // 4. Setup SpeechRecognition (Web Speech API) for live progressive transcription
    const SpeechRecognitionAPI =
      (window as unknown as { SpeechRecognition?: new () => ISpeechRecognition }).SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: new () => ISpeechRecognition }).webkitSpeechRecognition

    if (SpeechRecognitionAPI) {
      try {
        const recognition = new SpeechRecognitionAPI()
        recognition.continuous = true
        recognition.interimResults = true
        recognition.lang = 'en-US'
        recognition.maxAlternatives = 1

        finalTranscriptAccumulatorRef.current = transcript

        recognition.onresult = (event: ISpeechRecognitionEvent) => {
          let currentInterim = ''
          let accumulatedFinal = finalTranscriptAccumulatorRef.current

          for (let i = event.resultIndex; i < event.results.length; i++) {
            const res = event.results[i]
            const chunkText = res[0]?.transcript || ''

            if (res.isFinal) {
              accumulatedFinal = accumulatedFinal
                ? `${accumulatedFinal.trim()} ${chunkText.trim()}`
                : chunkText.trim()
            } else {
              currentInterim += chunkText
            }
          }

          finalTranscriptAccumulatorRef.current = accumulatedFinal
          setTranscript(accumulatedFinal)
          setInterimTranscript(currentInterim)
        }

        recognition.onerror = (event: ISpeechRecognitionErrorEvent) => {
          if (event.error === 'no-speech') {
            // Non-critical, user just paused speaking
            return
          }
          if (event.error === 'not-allowed') {
            setPermissionError('Microphone permission was blocked for speech recognition.')
            setError('Speech recognition permission denied.')
          } else if (event.error === 'network') {
            setError('Speech recognition service network issue. You can still record audio.')
          } else {
            console.warn('SpeechRecognition error:', event.error, event.message)
          }
        }

        // Automatic restart if recognition stops while still recording
        recognition.onend = () => {
          if (!isManuallyStoppedRef.current && isRecording) {
            try {
              recognition.start()
            } catch {
              // Ignore restart error
            }
          }
        }

        recognitionRef.current = recognition
        recognition.start()
      } catch (recInitErr: unknown) {
        console.warn('SpeechRecognition startup error:', recInitErr)
        setIsSpeechSupported(false)
        setError('Speech recognition engine could not be initialized in this browser. Audio is still recording.')
      }
    } else {
      setIsSpeechSupported(false)
      setError('Live speech recognition is not supported in this browser. For progressive live dictation, please use Google Chrome, Microsoft Edge, or Apple Safari. Audio recording is active.')
    }

    // 5. Start Elapsed Time Counter
    setIsRecording(true)
    setIsPaused(false)
    setDurationSeconds(0)

    timerRef.current = setInterval(() => {
      setDurationSeconds((s) => s + 1)
    }, 1000)

    return true
  }, [transcript, recordedAudioUrl, updateAudioMeter, isRecording])

  // Pause Recording
  const pauseRecording = useCallback(() => {
    if (!isRecording || isPaused) return
    setIsPaused(true)

    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      try {
        mediaRecorderRef.current.pause()
      } catch {}
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {}
    }

    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [isRecording, isPaused])

  // Resume Recording
  const resumeRecording = useCallback(() => {
    if (!isRecording || !isPaused) return
    setIsPaused(false)

    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'paused') {
      try {
        mediaRecorderRef.current.resume()
      } catch {}
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.start()
      } catch {}
    }

    timerRef.current = setInterval(() => {
      setDurationSeconds((s) => s + 1)
    }, 1000)
  }, [isRecording, isPaused])

  // Clear / Reset
  const resetSession = useCallback(() => {
    stopRecording()
    setTranscript('')
    setInterimTranscript('')
    finalTranscriptAccumulatorRef.current = ''
    setDurationSeconds(0)
    setRecordedBlob(null)
    setRecordedFile(null)
    if (recordedAudioUrl) {
      URL.revokeObjectURL(recordedAudioUrl)
      setRecordedAudioUrl(null)
    }
    setError(null)
    setPermissionError(null)
  }, [stopRecording, recordedAudioUrl])

  return {
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
  }
}
