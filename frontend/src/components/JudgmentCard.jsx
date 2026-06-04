import { motion } from 'framer-motion'
import { Gavel, Building2, BookOpenCheck } from 'lucide-react'
import Badge from '@/components/ui/Badge'
import CitationCard from '@/components/CitationCard'
import { cn } from '@/lib/utils'

const COURT_LABEL = {
  district: 'District Court',
  high:     'High Court',
  supreme:  'Supreme Court',
}

/** A single court level's verdict — used in the appeal-chain view. */
export default function JudgmentCard({ row, index = 0, onOpenCitation }) {
  const j = row.judgment || {}
  const citations = row.citations || []
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.35 }}
      className={cn(
        'relative overflow-hidden rounded-2xl border glass p-5',
        index === 0 ? 'border-gold-400/30' : 'border-white/10',
      )}
    >
      <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-gold-400/15 to-transparent pointer-events-none" />
      <div className="relative">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-xl bg-gold-400/15 grid place-items-center border border-gold-400/30 text-gold-200">
              <Building2 className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-serif text-lg leading-none">{COURT_LABEL[row.court_level] || row.court_level}</h3>
              <p className="text-[11px] text-ink-400 mt-0.5 flex items-center gap-1">
                <Gavel className="w-3 h-3" />
                {row.created_at ? new Date(row.created_at).toLocaleString('en-IN') : '—'}
              </p>
            </div>
          </div>
        </div>

        {j.final_judgment && (
          <p className="text-sm text-ink-100 leading-relaxed mb-3">{j.final_judgment}</p>
        )}
        {j.liability_assessment && (
          <p className="text-sm text-ink-300 mb-3">
            <span className="text-gold-300 font-medium">Liability: </span>
            {j.liability_assessment}
          </p>
        )}
        {j.applicable_sections?.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {j.applicable_sections.map((s, i) => (
              <Badge key={i} tone="gold">{s}</Badge>
            ))}
          </div>
        )}

        {citations.length > 0 && (
          <div className="mt-3 border-t border-white/5 pt-3">
            <div className="flex items-center gap-1.5 text-xs text-ink-400 mb-2">
              <BookOpenCheck className="w-3.5 h-3.5 text-gold-300" />
              Verified citations
            </div>
            <div className="grid sm:grid-cols-2 gap-2">
              {citations.map((c, i) => (
                <CitationCard key={i} citation={c} onClick={onOpenCitation} />
              ))}
            </div>
          </div>
        )}
      </div>
    </motion.div>
  )
}
