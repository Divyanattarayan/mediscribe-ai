import { useState, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity,
  PlusCircle,
  Clock,
  Settings,
  Menu,
  X,
  ShieldCheck,
  Stethoscope,
  LogOut,
  Wifi,
  WifiOff,
  RefreshCw,
} from 'lucide-react'
import { useAppStore } from '../../store/appStore'
import { checkBackendHealth } from '../../services/api'
import { Button, Badge } from '../ui'

export default function Navbar() {
  const location = useLocation()
  const navigate = useNavigate()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [isCheckingHealth, setIsCheckingHealth] = useState(false)

  const {
    authUser,
    profile,
    backendHealth,
    setBackendHealth,
    clearAuth,
  } = useAppStore()

  // Probe backend health on mount and periodically
  const runHealthCheck = async () => {
    setIsCheckingHealth(true)
    const health = await checkBackendHealth()
    setBackendHealth(health)
    setIsCheckingHealth(false)
  }

  useEffect(() => {
    runHealthCheck()
    const interval = setInterval(runHealthCheck, 30000) // check every 30s
    return () => clearInterval(interval)
  }, [])

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname])

  const navLinks = [
    { label: 'Dashboard', path: '/dashboard', icon: <Activity size={18} /> },
    { label: 'New Consultation', path: '/consultations/new', icon: <PlusCircle size={18} /> },
    { label: 'History', path: '/history', icon: <Clock size={18} /> },
    { label: 'Settings', path: '/settings', icon: <Settings size={18} /> },
  ]

  const handleLogout = () => {
    clearAuth()
    navigate('/login')
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-[#E2E8F0] bg-white/95 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand Logo */}
          <div className="flex items-center gap-8">
            <Link to="/dashboard" className="flex items-center gap-2.5 group">
              <div className="size-9 rounded-xl bg-gradient-to-br from-[#0D9488] to-[#0F766E] flex items-center justify-center text-white shadow-sm group-hover:scale-105 transition-transform duration-150">
                <Stethoscope size={20} className="stroke-[2.2]" />
              </div>
              <div className="flex flex-col">
                <span className="font-semibold text-lg text-[#0F172A] tracking-tight flex items-center gap-1.5 leading-none">
                  MediScribe <span className="text-[#0D9488] text-xs font-bold uppercase tracking-wider bg-[#F0FDFA] px-1.5 py-0.5 rounded border border-[#CCFBF1]">AI</span>
                </span>
                <span className="text-[11px] text-[#64748B] tracking-tight font-medium">Clinical Ambient Scribe</span>
              </div>
            </Link>

            {/* Desktop Navigation Links */}
            <nav className="hidden md:flex items-center gap-1">
              {navLinks.map((link) => {
                const isActive = location.pathname === link.path || (link.path !== '/dashboard' && location.pathname.startsWith(link.path))
                return (
                  <Link
                    key={link.path}
                    to={link.path}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
                      isActive
                        ? 'bg-[#F0FDFA] text-[#0F766E] font-semibold'
                        : 'text-[#475569] hover:text-[#0F172A] hover:bg-[#F8FAFC]'
                    }`}
                  >
                    <span className={isActive ? 'text-[#0D9488]' : 'text-[#64748B]'}>{link.icon}</span>
                    {link.label}
                  </Link>
                )
              })}
            </nav>
          </div>

          {/* Right Controls: Health Status & Clinician Menu */}
          <div className="hidden sm:flex items-center gap-3">
            {/* Live Backend Connection Indicator */}
            <div
              className="flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium border cursor-pointer select-none transition-colors"
              style={{
                backgroundColor: backendHealth.isConnected ? '#F0FDF4' : '#FEF2F2',
                borderColor: backendHealth.isConnected ? '#BBF7D0' : '#FECACA',
                color: backendHealth.isConnected ? '#166534' : '#991B1B',
              }}
              onClick={runHealthCheck}
              title={`Backend: ${backendHealth.isConnected ? 'Connected to ' + backendHealth.service : 'Offline - ' + (backendHealth.error || 'Server unreachable')}. Click to recheck.`}
            >
              <span
                className={`size-2 rounded-full ${
                  backendHealth.isConnected ? 'bg-[#22C55E] animate-pulse' : 'bg-[#EF4444]'
                }`}
              />
              <span className="font-mono text-[11px]">
                {backendHealth.isConnected
                  ? `API Ready${backendHealth.latencyMs ? ` · ${backendHealth.latencyMs}ms` : ''}`
                  : 'Backend Offline'}
              </span>
              <RefreshCw
                size={11}
                className={`text-current opacity-60 hover:opacity-100 ${isCheckingHealth ? 'animate-spin' : ''}`}
              />
            </div>

            {/* Quick Action: New Consultation */}
            <Button
              variant="primary"
              size="sm"
              icon={<PlusCircle size={15} />}
              onClick={() => navigate('/consultations/new')}
            >
              New Note
            </Button>

            {/* Clinician Profile */}
            <div className="flex items-center gap-2 pl-2 border-l border-[#E2E8F0]">
              <div className="size-8 rounded-full bg-[#E0F2FE] border border-[#BAE6FD] text-[#0369A1] font-semibold text-xs flex items-center justify-center">
                {profile.firstName ? profile.firstName[0] : 'D'}
                {profile.lastName ? profile.lastName[0] : 'R'}
              </div>
              <div className="flex flex-col text-left">
                <span className="text-xs font-semibold text-[#0F172A] leading-tight">
                  {profile.firstName} {profile.lastName}
                </span>
                <span className="text-[10px] text-[#64748B] leading-none">
                  {profile.specialty || 'Clinician'}
                </span>
              </div>
              <button
                onClick={handleLogout}
                className="p-1.5 text-[#94A3B8] hover:text-[#B91C1C] hover:bg-[#FEF2F2] rounded-md transition-colors"
                title="Log out"
              >
                <LogOut size={15} />
              </button>
            </div>
          </div>

          {/* Mobile Hamburger Toggle */}
          <div className="flex sm:hidden items-center gap-2">
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-2 rounded-lg text-[#475569] hover:bg-[#F1F5F9] transition-colors"
              aria-label="Toggle Navigation Menu"
            >
              {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </div>
      </div>

      {/* Responsive Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="sm:hidden border-b border-[#E2E8F0] bg-white px-4 pt-2 pb-6 space-y-3 animate-in slide-in-from-top-2 duration-150">
          {/* Backend Status on Mobile */}
          <div className="flex items-center justify-between p-2.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0]">
            <div className="flex items-center gap-2">
              {backendHealth.isConnected ? (
                <Wifi size={16} className="text-[#16A34A]" />
              ) : (
                <WifiOff size={16} className="text-[#DC2626]" />
              )}
              <span className="text-xs font-medium text-[#0F172A]">
                {backendHealth.isConnected ? 'Backend Connected' : 'Backend Disconnected'}
              </span>
            </div>
            <button
              onClick={runHealthCheck}
              className="text-xs text-[#0D9488] font-medium flex items-center gap-1"
            >
              <RefreshCw size={12} className={isCheckingHealth ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>

          {/* Navigation Links */}
          <nav className="flex flex-col gap-1">
            {navLinks.map((link) => {
              const isActive = location.pathname === link.path
              return (
                <Link
                  key={link.path}
                  to={link.path}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium ${
                    isActive
                      ? 'bg-[#F0FDFA] text-[#0F766E] font-semibold'
                      : 'text-[#475569] hover:bg-[#F8FAFC]'
                  }`}
                >
                  {link.icon}
                  {link.label}
                </Link>
              )
            })}
          </nav>

          {/* User profile & Actions */}
          <div className="pt-3 border-t border-[#E2E8F0] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="size-8 rounded-full bg-[#E0F2FE] text-[#0369A1] font-semibold text-xs flex items-center justify-center">
                {profile.firstName ? profile.firstName[0] : 'D'}
                {profile.lastName ? profile.lastName[0] : 'R'}
              </div>
              <div className="flex flex-col">
                <span className="text-xs font-semibold text-[#0F172A]">
                  {profile.firstName} {profile.lastName}
                </span>
                <span className="text-[10px] text-[#64748B]">{profile.specialty}</span>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="px-3 py-1.5 text-xs text-[#B91C1C] font-medium rounded-md hover:bg-[#FEF2F2]"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </header>
  )
}
