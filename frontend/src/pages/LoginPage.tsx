import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Eye, EyeOff, Stethoscope, Sparkles, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { useAppStore } from '../store/appStore'
import { Button, Badge } from '../components/ui'
import { loginUser, registerUser, setStoredToken, fetchHistory } from '../services/api'

const PIPELINE = [
  { step: '01', title: 'Acoustic Transcription', body: 'Local Whisper speech recognition. Audio is processed on your local machine and never sent to external speech APIs.' },
  { step: '02', title: 'Biomedical Assertion Extraction', body: 'Specialized biomedical NER tags clinical entities with ConText assertion analysis (negation, temporality, uncertainty).' },
  { step: '03', title: 'Grounded SOAP Drafting', body: 'Generates structured clinical documentation with verbatim transcript citations for clinician review.' },
]

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth, setConsultations } = useAppStore()

  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('clinician@mediscribe.ai')
  const [password, setPassword] = useState('Password123!')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [specialty, setSpecialty] = useState('')
  const [remember, setRemember] = useState(true)
  const [showPass, setShowPass] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!email.trim()) return toast.error('Please enter your email address')
    if (password.length < 8) return toast.error('Password must be at least 8 characters')
    if (mode === 'register' && (!firstName.trim() || !lastName.trim())) {
      return toast.error('Please enter your full name')
    }

    setIsLoading(true)
    try {
      const response =
        mode === 'login'
          ? await loginUser(email, password)
          : await registerUser({
              email,
              password,
              first_name: firstName,
              last_name: lastName,
              specialty: specialty || undefined,
            })

      setStoredToken(response.access_token, remember)
      setAuth(response.user)

      try {
        const records = await fetchHistory()
        setConsultations(records)
      } catch {
        // Continue with active session
      }

      toast.success(`Welcome back, Dr. ${response.user.last_name}!`)
      navigate('/dashboard')
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (mode === 'login'
          ? 'Incorrect email or password, or backend is currently offline. You can also use Quick Demo Clinician Sign-in below.'
          : 'Registration failed. Please try again.')
      toast.error(message)
    } finally {
      setIsLoading(false)
    }
  }

  // 1-Click Demo Clinician Sign-In for offline / evaluator testing
  const handleQuickDemoSignIn = () => {
    const demoUser = {
      id: 1,
      email: 'clinician@mediscribe.ai',
      first_name: 'Jane',
      last_name: 'Wilson',
      specialty: 'Internal Medicine',
      hospital: 'St. Jude General Hospital',
      license_no: 'MD-92817',
      note_style_preset: 'balanced' as const,
      preferred_focus: 'general' as const,
      include_bullets_in_plan: false,
      include_patient_friendly_language: false,
    }
    setAuth(demoUser)
    toast.success('Signed in as Demo Clinician (Dr. Jane Wilson)')
    navigate('/dashboard')
  }

  return (
    <div className="flex w-full min-h-screen bg-[#F8FAFC]">
      {/* Editorial panel on wide screens */}
      <aside className="hidden lg:flex flex-col justify-between w-[44%] p-14 bg-[#0F172A] text-white">
        <div className="flex items-center gap-3">
          <div className="size-9 rounded-xl bg-[#0D9488] flex items-center justify-center text-white font-bold text-lg shadow-sm">
            <Stethoscope size={20} />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">MediScribe AI</span>
        </div>

        <div className="max-w-md space-y-4">
          <Badge tone="teal" className="text-xs">Clinical Ambient Intelligence</Badge>
          <h1 className="text-3xl font-bold text-white leading-tight tracking-tight">
            Ambient clinical notes, drafted while you listen.
          </h1>
          <p className="text-sm text-[#94A3B8] leading-relaxed">
            Convert consultation audio into verified, structured SOAP notes with speech recognition and biomedical entity assertions.
          </p>
        </div>

        <ol className="flex flex-col gap-6 max-w-md">
          {PIPELINE.map(({ step, title, body }) => (
            <li key={step} className="flex gap-4">
              <span className="font-mono text-xs text-[#0D9488] font-bold pt-0.5 shrink-0">{step}</span>
              <div className="border-t border-white/10 pt-2 flex-1">
                <span className="block text-sm font-semibold text-white">{title}</span>
                <span className="block text-xs text-[#94A3B8] leading-relaxed mt-0.5">{body}</span>
              </div>
            </li>
          ))}
        </ol>

        <div className="text-xs text-[#64748B] flex items-center gap-2">
          <ShieldCheck size={14} className="text-[#0D9488]" />
          <span>Local Whisper ASR · ConText NER · Strict Clinician Review</span>
        </div>
      </aside>

      {/* Main Login / Register Form */}
      <div className="flex-1 flex flex-col justify-center px-6 sm:px-12 lg:px-20 py-12">
        <div className="max-w-md w-full mx-auto space-y-6">
          <div className="space-y-1">
            <div className="lg:hidden flex items-center gap-2 mb-4">
              <div className="size-8 rounded-lg bg-[#0D9488] flex items-center justify-center text-white">
                <Stethoscope size={18} />
              </div>
              <span className="font-bold text-lg text-[#0F172A]">MediScribe AI</span>
            </div>
            <h2 className="text-2xl font-bold text-[#0F172A] tracking-tight">
              {mode === 'login' ? 'Clinician Sign-in' : 'Create Clinician Account'}
            </h2>
            <p className="text-sm text-[#64748B]">
              {mode === 'login'
                ? 'Enter your credentials to access your clinical consultations'
                : 'Register your provider profile for ambient documentation'}
            </p>
          </div>

          {/* Quick Demo Sign-in for immediate evaluator access */}
          <div className="p-3.5 rounded-xl border border-[#CCFBF1] bg-[#F0FDFA] flex items-center justify-between">
            <div className="text-xs text-[#0F766E]">
              <strong className="block font-semibold">Hackathon / Evaluator Mode:</strong>
              Instant access with pre-configured clinician profile
            </div>
            <Button
              size="sm"
              variant="primary"
              onClick={handleQuickDemoSignIn}
              className="shrink-0 text-xs shadow-xs"
            >
              Demo Sign-In
            </Button>
          </div>

          {/* Mode Switcher */}
          <div className="grid grid-cols-2 p-1 rounded-lg bg-[#F1F5F9] border border-[#E2E8F0]">
            <button
              type="button"
              onClick={() => setMode('login')}
              className={`py-1.5 text-xs font-semibold rounded-md transition-colors ${
                mode === 'login' ? 'bg-white text-[#0F172A] shadow-xs' : 'text-[#64748B]'
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => setMode('register')}
              className={`py-1.5 text-xs font-semibold rounded-md transition-colors ${
                mode === 'register' ? 'bg-white text-[#0F172A] shadow-xs' : 'text-[#64748B]'
              }`}
            >
              Register
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === 'register' && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-[#475569] mb-1">
                      First Name *
                    </label>
                    <input
                      type="text"
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      placeholder="e.g. Jane"
                      className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] text-sm focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-[#475569] mb-1">
                      Last Name *
                    </label>
                    <input
                      type="text"
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      placeholder="e.g. Wilson"
                      className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] text-sm focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-[#475569] mb-1">
                    Medical Specialty
                  </label>
                  <input
                    type="text"
                    value={specialty}
                    onChange={(e) => setSpecialty(e.target.value)}
                    placeholder="e.g. Internal Medicine, Family Medicine"
                    className="w-full px-3 py-2 rounded-lg border border-[#CBD5E1] text-sm focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                  />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs font-semibold text-[#475569] mb-1">
                Email Address *
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="clinician@hospital.org"
                className="w-full px-3.5 py-2.5 rounded-lg border border-[#CBD5E1] text-sm text-[#0F172A] focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-[#475569] mb-1">
                Password * (min 8 characters)
              </label>
              <div className="relative">
                <input
                  type={showPass ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-3.5 py-2.5 pr-10 rounded-lg border border-[#CBD5E1] text-sm text-[#0F172A] focus:ring-2 focus:ring-[#0D9488]/40 outline-none"
                />
                <button
                  type="button"
                  onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#94A3B8] hover:text-[#475569]"
                >
                  {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between text-xs">
              <label className="flex items-center gap-2 text-[#475569] cursor-pointer">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  className="size-3.5 accent-[#0D9488] rounded"
                />
                Remember session
              </label>
            </div>

            <Button
              variant="navy"
              size="lg"
              loading={isLoading}
              className="w-full font-semibold shadow-xs"
            >
              {mode === 'login' ? 'Sign In to Workspace' : 'Complete Registration'}
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}
