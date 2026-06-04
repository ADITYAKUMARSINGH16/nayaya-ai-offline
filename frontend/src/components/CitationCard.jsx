import { BookOpen, CheckCircle2, AlertTriangle } from 'lucide-react'
import Badge from '@/components/ui/Badge'
import { cn } from '@/lib/utils'

export default function CitationCard({ citation, onClick }) {
  const tone = citation.verified === true ? 'green' : citation.verified === false ? 'red' : 'gold'
  const Icon = citation.verified === true
    ? CheckCircle2
    : citation.verified === false
      ? AlertTriangle
      : BookOpen

  const interactive = typeof onClick === 'function'

  const Body = (
    <>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-gold-300" />
          <span className="font-medium text-ink-50">
            {citation.act ? `${citation.act} · ` : ''}Section {citation.section_number || '—'}
          </span>
        </div>
        {citation.verified !== null && citation.verified !== undefined && (
          <Badge tone={tone}>{citation.verified ? 'Verified' : 'Unverified'}</Badge>
        )}
      </div>
      {citation.section_title && (
        <p className="text-sm text-ink-200 font-medium mb-1">{citation.section_title}</p>
      )}
      {citation.snippet && (
        <p className="text-xs text-ink-300 leading-relaxed line-clamp-4">{citation.snippet}</p>
      )}
      {citation.verify_note && (
        <p className="text-[11px] text-ink-400 mt-2 italic">↳ {citation.verify_note}</p>
      )}
      {interactive && (
        <p className="text-[11px] text-gold-300 mt-2">Click to read the full section →</p>
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
    <button type="button" onClick={() => onClick(citation)} className={classes}>
      {Body}
    </button>
  ) : (
    <div className={classes}>{Body}</div>
  )
}
