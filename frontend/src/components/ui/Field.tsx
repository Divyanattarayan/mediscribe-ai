import { cn } from '../../lib/utils'
import { useId } from 'react'
import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes, ReactNode } from 'react'

// Shared control surface. Focus is handled globally by :focus-visible in
// index.css so every control in the app rings identically.
const CONTROL = cn(
  'w-full rounded-md border border-border-strong bg-surface text-ink',
  'px-3 h-10 text-base placeholder:text-ink-subtle',
  'transition-[border-color] duration-[var(--dur-fast)] ease-out-quint',
  'hover:border-ink-subtle disabled:opacity-45 disabled:pointer-events-none',
)

interface Wrap {
  label: string
  hint?: ReactNode
  error?: string
  required?: boolean
  className?: string
}

function Shell({ label, hint, error, required, id, children, className }: Wrap & { id: string; children: ReactNode }) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
        {required && <span className="text-danger-ink ml-0.5" aria-hidden>*</span>}
      </label>
      {children}
      {/* Helper text is persistent, not a placeholder. Errors sit by the field. */}
      {error
        ? <p id={`${id}-err`} role="alert" className="text-xs text-danger-ink">{error}</p>
        : hint && <p id={`${id}-hint`} className="text-xs text-ink-subtle">{hint}</p>}
    </div>
  )
}

export function Field({ label, hint, error, required, className, ...rest }: Wrap & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId()
  return (
    <Shell {...{ label, hint, error, required, id, className }}>
      <input id={id} required={required} aria-invalid={!!error || undefined}
        aria-describedby={error ? `${id}-err` : hint ? `${id}-hint` : undefined}
        className={cn(CONTROL, error && 'border-danger-ink')} {...rest} />
    </Shell>
  )
}

export function SelectField({ label, hint, error, required, className, children, ...rest }: Wrap & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId()
  return (
    <Shell {...{ label, hint, error, required, id, className }}>
      <select id={id} required={required} className={cn(CONTROL, 'pr-8')} {...rest}>{children}</select>
    </Shell>
  )
}

export function TextareaField({ label, hint, error, required, className, ...rest }: Wrap & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId()
  return (
    <Shell {...{ label, hint, error, required, id, className }}>
      <textarea id={id} required={required} aria-invalid={!!error || undefined}
        className={cn(CONTROL, 'h-auto py-2.5 leading-relaxed resize-y', error && 'border-danger-ink')} {...rest} />
    </Shell>
  )
}

export default Field
