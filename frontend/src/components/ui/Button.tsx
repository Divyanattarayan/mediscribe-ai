import { cn } from '../../lib/utils'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'teal-outline' | 'navy'
type Size = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: ReactNode
  loading?: boolean
}

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-[#0D9488] text-white hover:bg-[#0F766E] border border-transparent shadow-xs focus:ring-2 focus:ring-[#0D9488]/40',
  navy: 'bg-[#0F172A] text-white hover:bg-[#1E293B] border border-transparent shadow-xs',
  secondary: 'bg-white text-[#0F172A] border border-[#E2E8F0] hover:bg-[#F8FAFC] hover:border-[#CBD5E1] shadow-xs',
  'teal-outline': 'bg-transparent text-[#0D9488] border border-[#0D9488]/30 hover:bg-[#F0FDFA] hover:border-[#0D9488]',
  ghost: 'bg-transparent text-[#334155] border border-transparent hover:bg-[#F1F5F9] hover:text-[#0F172A]',
  danger: 'bg-[#FEF2F2] text-[#B91C1C] border border-[#FECACA] hover:bg-[#FEE2E2]',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5 font-medium rounded-md',
  md: 'h-9 px-4 text-sm gap-2 font-medium rounded-lg',
  lg: 'h-11 px-5 text-base gap-2.5 font-medium rounded-lg',
}

export default function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap cursor-pointer select-none',
        'transition-all duration-150 ease-in-out',
        'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none',
        VARIANTS[variant],
        SIZES[size],
        className
      )}
      {...rest}
    >
      {loading ? (
        <span
          className="size-4 rounded-full border-2 border-current/30 border-t-current animate-spin"
          aria-hidden
        />
      ) : (
        icon
      )}
      {children}
    </button>
  )
}
