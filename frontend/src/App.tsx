import { useEffect, useState, useRef } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { Toaster, toast } from 'sonner'
import { useAppStore } from './store/appStore'
import { fetchCurrentUser, fetchHistory, getStoredToken } from './services/api'
import AppLayout from './components/layout/AppLayout'

// Pages
import DashboardPage from './pages/DashboardPage'
import NewConsultationPage from './pages/NewConsultationPage'
import TranscriptReviewPage from './pages/TranscriptReviewPage'
import SoapReviewPage from './pages/SoapReviewPage'
import ConsultationHistoryPage from './pages/ConsultationHistoryPage'
import SettingsPage from './pages/SettingsPage'
import ConsultationDetailsPage from './pages/ConsultationDetailsPage'
import LoginPage from './pages/LoginPage'

// Inner component that has access to useNavigate (must be inside BrowserRouter)
function AppRoutes() {
  const navigate = useNavigate()
  const { setAuth, setConsultations, clearAuth } = useAppStore()
  const [isInitializing, setIsInitializing] = useState(true)
  const handledRef = useRef(false)

  useEffect(() => {
    const initApp = async () => {
      const token = getStoredToken()
      if (token) {
        try {
          const user = await fetchCurrentUser()
          setAuth(user)
          try {
            const historyRecords = await fetchHistory()
            setConsultations(historyRecords)
          } catch {
            // Keep existing consultations
          }
        } catch {
          clearAuth()
        }
      }
      setIsInitializing(false)
    }

    initApp()
  }, [])

  // Global handler: redirect to /login on any 401 from the API
  useEffect(() => {
    const handleUnauthorized = () => {
      if (handledRef.current) return
      handledRef.current = true
      clearAuth()
      toast.error('Session expired. Please log in again.', { duration: 4000 })
      navigate('/login', { replace: true })
      setTimeout(() => { handledRef.current = false }, 5000)
    }

    window.addEventListener('mediscribe:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('mediscribe:unauthorized', handleUnauthorized)
  }, [navigate, clearAuth])

  if (isInitializing) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center space-y-3">
        <div className="size-10 rounded-full border-3 border-[#0D9488]/20 border-t-[#0D9488] animate-spin" />
        <span className="text-sm font-medium text-[#475569]">Initializing MediScribe AI...</span>
      </div>
    )
  }

  return (
    <Routes>
      {/* Fullscreen Authentication Route */}
      <Route path="/login" element={<LoginPage />} />

      {/* Main Application Routes inside Healthcare Layout */}
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/consultations/new" element={<NewConsultationPage />} />
        <Route path="/consultations/:id" element={<ConsultationDetailsPage />} />
        <Route path="/consultations/:id/transcript" element={<TranscriptReviewPage />} />
        <Route path="/consultations/:id/soap" element={<SoapReviewPage />} />
        <Route path="/history" element={<ConsultationHistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      {/* Fallback Route */}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Toaster position="top-right" richColors />
      <AppRoutes />
    </BrowserRouter>
  )
}

