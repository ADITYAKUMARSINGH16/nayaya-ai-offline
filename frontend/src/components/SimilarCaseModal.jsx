import { Landmark, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import Badge from '@/components/ui/Badge'

export default function SimilarCaseModal({ similarCase, onClose }) {
  if (!similarCase) return null

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 md:p-12 bg-ink-950/80 backdrop-blur-sm">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          className="relative w-full max-w-3xl max-h-full flex flex-col glass rounded-2xl shadow-2xl border border-white/10 overflow-hidden"
        >
          {/* Header */}
          <div className="flex-none p-6 border-b border-white/10 flex items-start justify-between gap-4 bg-ink-900/50">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-full bg-gold-500/10 flex items-center justify-center shrink-0">
                  <Landmark className="w-5 h-5 text-gold-400" />
                </div>
                <h2 className="text-xl font-serif text-ink-50">
                  {similarCase.title} ({similarCase.year})
                </h2>
              </div>
              <div className="flex items-center gap-2 mt-2 ml-13 text-sm">
                <span className="text-ink-200">{similarCase.court}</span>
                {similarCase.disposition && (
                  <Badge tone="blue">{similarCase.disposition}</Badge>
                )}
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-xl text-ink-400 hover:text-ink-50 hover:bg-white/5 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div className="prose prose-invert prose-sm max-w-none text-ink-200 leading-relaxed">
              <div className="whitespace-pre-wrap">{similarCase.text || similarCase.snippet}</div>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  )
}
