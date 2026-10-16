import type { ReactNode } from 'react'
import { FolderOpen } from 'lucide-react'
import Button from './Button'

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description: string
  actionLabel?: string
  onAction?: () => void
  actionIcon?: ReactNode
  secondaryActionLabel?: string
  onSecondaryAction?: () => void
  disclaimer?: string
}

export default function EmptyState({
  icon = <FolderOpen size={36} className="text-[#94A3B8]" />,
  title,
  description,
  actionLabel,
  onAction,
  actionIcon,
  secondaryActionLabel,
  onSecondaryAction,
  disclaimer,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center p-8 sm:p-12 text-center rounded-xl border border-dashed border-[#CBD5E1] bg-[#F8FAFC]">
      <div className="size-16 rounded-2xl bg-white border border-[#E2E8F0] shadow-xs flex items-center justify-center mb-4 text-[#0D9488]">
        {icon}
      </div>
      <h3 className="text-base sm:text-lg font-semibold text-[#0F172A] tracking-tight">{title}</h3>
      <p className="mt-1.5 text-sm text-[#64748B] max-w-md leading-relaxed">{description}</p>

      {(actionLabel || secondaryActionLabel) && (
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          {actionLabel && onAction && (
            <Button variant="primary" icon={actionIcon} onClick={onAction}>
              {actionLabel}
            </Button>
          )}
          {secondaryActionLabel && onSecondaryAction && (
            <Button variant="secondary" onClick={onSecondaryAction}>
              {secondaryActionLabel}
            </Button>
          )}
        </div>
      )}

      {disclaimer && (
        <p className="mt-4 text-xs text-[#94A3B8] max-w-sm italic">{disclaimer}</p>
      )}
    </div>
  )
}
