import { cn } from '@/lib/utils'
import { Loader2 } from 'lucide-react'

export default function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className = '',
  children,
  ...props
}) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed'
  const sizes = { sm: 'px-3 py-1.5 text-sm', md: 'px-4 py-2.5', lg: 'px-5 py-3 text-base' }
  const variants = {
    primary:
      'bg-gradient-to-b from-gold-400 to-gold-500 text-ink-950 shadow-glow hover:from-gold-300 hover:to-gold-400',
    ghost: 'bg-white/5 hover:bg-white/10 text-ink-100 border border-white/10',
    outline:
      'bg-transparent border border-gold-400/40 text-gold-200 hover:bg-gold-400/10',
    danger: 'bg-red-600/90 hover:bg-red-600 text-white',
  }
  return (
    <button
      className={cn(base, sizes[size], variants[variant], className)}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 className="w-4 h-4 animate-spin" />}
      {children}
    </button>
  )
}
