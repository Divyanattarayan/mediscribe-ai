import { cn } from '../../lib/utils'
import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  /** Dashed border marks in-progress / draft state. */
  draft?: boolean
  as?: 'div' | 'section' | 'article' | 'aside'
}

/** Depth is a hairline border, not a shadow. */
export function Card({ children, className, draft = false, as: Tag = 'div' }: CardProps) {
  return (
    <Tag className={cn(
      'bg-surface border rounded-lg',
      draft ? 'border-dashed border-border-strong' : 'border-border',
      className,
    )}>
      {children}
    </Tag>
  )
}

interface CardHeaderProps {
  title: ReactNode
  /** Small count shown beside the title, e.g. "Entities (12)". */
  count?: number
  actions?: ReactNode
  className?: string
}

export function CardHeader({ title, count, actions, className }: CardHeaderProps) {
  return (
    <div className={cn(
      'flex items-center justify-between gap-3 px-4 py-3 border-b border-border',
      className,
    )}>
      <h2 className="font-head text-lg font-semibold text-ink leading-none">
        {title}
        {count !== undefined && (
          <span className="ml-1.5 font-sans text-sm font-normal text-ink-subtle tabular-nums">
            ({count})
          </span>
        )}
      </h2>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  )
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('p-4', className)}>{children}</div>
}

export default Card
