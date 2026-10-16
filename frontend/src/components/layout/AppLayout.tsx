import { Outlet } from 'react-router-dom'
import Navbar from './Navbar'
import { ShieldAlert } from 'lucide-react'

export default function AppLayout() {
  return (
    <div className="min-h-screen flex flex-col bg-[#F8FAFC] text-[#0F172A]">
      <Navbar />

      {/* Safety Notice Ribbon */}
      <div className="bg-[#F0FDFA] border-b border-[#CCFBF1] py-1.5 px-4 text-center">
        <div className="max-w-7xl mx-auto flex items-center justify-center gap-2 text-xs font-medium text-[#0F766E]">
          <ShieldAlert size={14} className="text-[#0D9488] shrink-0" />
          <span>
            <strong>AI Clinical Assistant:</strong> Generated SOAP notes are drafts for clinician review only. Clinician verification and approval is required before clinical use.
          </span>
        </div>
      </div>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="border-t border-[#E2E8F0] bg-white py-6">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-[#64748B]">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[#0F172A]">MediScribe AI</span>
            <span>· v2.0.0</span>
            <span>· Clinical Documentation Engine</span>
          </div>
          <div className="flex items-center gap-4">
            <span>Local Whisper ASR (small.en)</span>
            <span>· ConText NLP</span>
            <span>· Groq / Gemini LLM</span>
            <span>· Fact Provenance</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
