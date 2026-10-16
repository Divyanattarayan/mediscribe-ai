import { cn } from '../../lib/utils'
import type { ReactNode } from 'react'

export type Tone = 'ok' | 'warn' | 'danger' | 'neutral' | 'teal' | 'info' | 'purple'

const TONES: Record<Tone, string> = {
  ok: 'bg-[#ECFDF5] text-[#047857] border border-[#A7F3D0]',
  warn: 'bg-[#FFFBEB] text-[#B45309] border border-[#FDE68A]',
  danger: 'bg-[#FEF2F2] text-[#B91C1C] border border-[#FECACA]',
  neutral: 'bg-[#F1F5F9] text-[#475569] border border-[#E2E8F0]',
  teal: 'bg-[#F0FDFA] text-[#0F766E] border border-[#99F6E4]',
  info: 'bg-[#F0F9FF] text-[#0369A1] border border-[#BAE6FD]',
  purple: 'bg-[#FAF5FF] text-[#7E22CE] border border-[#E9D5FF]',
}

export default function Badge({
  tone = 'neutral',
  dot = false,
  children,
  className,
}: {
  tone?: Tone
  dot?: boolean
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium whitespace-nowrap',
        TONES[tone],
        className
      )}
    >
      {dot && <span className="size-1.5 rounded-full bg-current shrink-0" aria-hidden />}
      {children}
    </span>
  )
}
