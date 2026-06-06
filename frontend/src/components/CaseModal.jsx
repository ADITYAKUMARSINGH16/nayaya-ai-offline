import { AnimatePresence, motion } from 'framer-motion'
import { Landmark, X } from 'lucide-react'

export default function CaseModal({ caseData, onClose }) {
  return (
    <AnimatePresence>
      {caseData && (
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
            >
              <div className="flex items-start justify-between gap-4 mb-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-xl bg-gold-400/10 border border-gold-400/20 grid place-items-center text-gold-300 shrink-0">
                    <Landmark className="w-5 h-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs text-ink-400 uppercase tracking-wider">
                      {caseData.court} · {caseData.year}
                    </div>
                    <h2 className="font-serif text-xl text-ink-50 leading-tight">
                      {caseData.title}
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

              {caseData.disposition && (
                <div className="mb-4">
                  <span className="text-gold-500 font-medium text-sm">Verdict: </span>
                  <span className="text-ink-200 text-sm">{caseData.disposition}</span>
                </div>
              )}

              {caseData.source_pdf_s3_url && (
                <div className="mb-4">
                  <a 
                    href={`${import.meta.env.VITE_API_URL || ''}/api/cases/pdf/proxy?url=${encodeURIComponent(caseData.source_pdf_s3_url)}`} 
                    target="_blank" 
                    rel="noreferrer" 
                    className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gold-500/10 text-gold-500 hover:bg-gold-500/20 transition-colors text-sm font-medium border border-gold-500/20"
                  >
                    View Source PDF
                  </a>
                </div>
              )}

              <div className="text-sm text-ink-100 leading-relaxed whitespace-pre-wrap rounded-xl bg-ink-950/40 border border-white/5 p-4 max-h-96 overflow-y-auto">
                {caseData.text?.trim() || caseData.snippet?.trim() || 'No case summary available.'}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
