import { Landmark } from 'lucide-react'
import Badge from '@/components/ui/Badge'
import { cn } from '@/lib/utils'

export default function SimilarCaseCard({ similarCase, onClick }) {
  const interactive = typeof onClick === 'function'

  const Body = (
    <>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2">
          <Landmark className="w-4 h-4 text-gold-300" />
          <span className="font-medium text-ink-50">
            {similarCase.title} ({similarCase.year})
          </span>
        </div>
      </div>
      {similarCase.court && (
        <p className="text-sm text-ink-200 font-medium mb-1">{similarCase.court}</p>
      )}
      {similarCase.disposition && (
        <Badge tone="blue" className="mb-2">{similarCase.disposition}</Badge>
      )}
      {similarCase.snippet && (
        <p className="text-xs text-ink-300 leading-relaxed line-clamp-4 mt-2">{similarCase.snippet}</p>
      )}
      {interactive && (
        <p className="text-[11px] text-gold-300 mt-2">Click to read the full case →</p>
      )}
    </>
  )

  const classes = cn(
    'block w-full text-left glass-light rounded-xl p-4 border border-white/5 transition',
    interactive
      ? 'hover:border-gold-400/40 hover:bg-ink-800/60 cursor-pointer focus:outline-none focus:ring-2 focus:ring-gold-400/40'
      : 'hover:border-gold-400/30',
  )

  return interactive ? (
    <button type="button" onClick={() => onClick(similarCase)} className={classes}>
      {Body}
    </button>
  ) : (
    <div className={classes}>{Body}</div>
  )
}
