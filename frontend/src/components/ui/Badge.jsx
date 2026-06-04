import { cn } from '@/lib/utils'

const TONES = {
  gold:  'bg-gold-400/15 text-gold-200 border-gold-400/30',
  green: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  red:   'bg-red-500/15 text-red-300 border-red-500/30',
  blue:  'bg-sky-500/15 text-sky-300 border-sky-500/30',
  slate: 'bg-white/5 text-ink-200 border-white/10',
}

export default function Badge({ tone = 'slate', className = '', children }) {
  return (
    <span className={cn('pill border', TONES[tone] || TONES.slate, className)}>
      {children}
    </span>
  )
}
