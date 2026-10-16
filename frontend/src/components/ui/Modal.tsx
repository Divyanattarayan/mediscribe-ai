import { useEffect, useRef } from 'react'
import { cn } from '../../lib/utils'
import Button from './Button'
import type { ReactNode } from 'react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  description?: ReactNode
  confirmLabel?: string
  onConfirm?: () => void
  destructive?: boolean
  busy?: boolean
  children?: ReactNode
}

export default function Modal({
  open, onClose, title, description,
  confirmLabel, onConfirm, destructive = false, busy = false, children,
}: ModalProps) {
  const panel = useRef<HTMLDivElement>(null)

  // Escape always dismisses; focus moves into the dialog on open.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    const prev = document.activeElement as HTMLElement | null
    panel.current?.focus()
    return () => { document.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4 bg-ink/45 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={e => e.stopPropagation()}
        className={cn(
          'w-full max-w-md bg-surface border border-border rounded-lg p-6 outline-none',
          'shadow-[var(--shadow-overlay)]',
        )}
      >
        <h2 className="font-head text-xl font-semibold text-ink">{title}</h2>
        {description && <p className="mt-2 text-base text-ink-muted leading-relaxed">{description}</p>}
        {children}
        <div className="flex justify-end gap-2 mt-6">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          {onConfirm && (
            <Button
              variant={destructive ? 'danger' : 'primary'}
              onClick={onConfirm}
              loading={busy}
            >
              {confirmLabel ?? 'Confirm'}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
