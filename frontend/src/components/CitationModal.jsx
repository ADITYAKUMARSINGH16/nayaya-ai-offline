import { AnimatePresence, motion } from 'framer-motion'
import { BookOpen, CheckCircle2, AlertTriangle, X } from 'lucide-react'
import Badge from '@/components/ui/Badge'

export default function CitationModal({ citation, onClose }) {
  return (
    <AnimatePresence>
      {citation && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-ink-950/70 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-0 z-50 grid place-items-center p-4 pointer-events-none"
          >
            <div
              className="pointer-events-auto w-full max-w-2xl glass rounded-2xl p-6 max-h-[85vh] overflow-y-auto"
              role="dialog"
              aria-modal="true"
              aria-labelledby="citation-title"
            >
              <div className="flex items-start justify-between gap-4 mb-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-xl bg-gold-400/10 border border-gold-400/20 grid place-items-center text-gold-300 shrink-0">
                    <BookOpen className="w-5 h-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs text-ink-400 uppercase tracking-wider">
                      {citation.act || 'Statute'}
                    </div>
                    <h2 id="citation-title" className="font-serif text-xl text-ink-50 leading-tight">
                      Section {citation.section_number || '—'}
                      {citation.section_title ? ` · ${citation.section_title}` : ''}
                    </h2>
                  </div>
                </div>
                <button
                  onClick={onClose}
                  className="w-9 h-9 grid place-items-center rounded-lg hover:bg-white/5 text-ink-300"
                  aria-label="Close"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-2 mb-4">
                {citation.verified === true && (
                  <Badge tone="green">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Verified by audit agent
                  </Badge>
                )}
                {citation.verified === false && (
                  <Badge tone="red">
                    <AlertTriangle className="w-3.5 h-3.5" /> Unverified
                  </Badge>
                )}
                {/* Only show a match score when it's meaningful. Direct
                    "Section N" lookups query with a zero vector, so the
                    cosine score is ~0 and would be misleading to display. */}
                {typeof citation.score === 'number' && citation.score >= 0.05 && (
                  <Badge tone="slate">match score {(citation.score * 100).toFixed(0)}%</Badge>
                )}
              </div>

              {citation.verify_note && (
                <p className="text-xs italic text-ink-400 mb-3">↳ {citation.verify_note}</p>
              )}

              <div className="text-sm text-ink-100 leading-relaxed whitespace-pre-wrap rounded-xl bg-ink-950/40 border border-white/5 p-4">
                {citation.snippet?.trim() || 'No statute text available for this section.'}
              </div>

              <p className="text-[11px] text-ink-400 mt-4">
                Retrieved from the legal database. For official text consult India Code or
                the gazette.
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
