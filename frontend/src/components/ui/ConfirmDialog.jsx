import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, X } from 'lucide-react'
import Button from '@/components/ui/Button'

/**
 * Themed replacement for window.confirm().
 *
 * Usage:
 *   const [pending, setPending] = useState(null)
 *   <ConfirmDialog
 *     open={Boolean(pending)}
 *     onConfirm={async () => { await doThing(pending); setPending(null) }}
 *     onCancel={() => setPending(null)}
 *     title="Delete this conversation?"
 *     description="This cannot be undone."
 *     confirmLabel="Delete"
 *     destructive
 *   />
 */
export default function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title = 'Are you sure?',
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  loading = false,
}) {
  // Esc to close
  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') onCancel?.()
      if (e.key === 'Enter' && !loading) onConfirm?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel, onConfirm, loading])

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onCancel}
            className="fixed inset-0 z-[60] bg-ink-950/70 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.96 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-0 z-[60] grid place-items-center p-4 pointer-events-none"
          >
            <div
              className="pointer-events-auto w-full max-w-md glass rounded-2xl p-5 sm:p-6"
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="confirm-title"
            >
              <div className="flex items-start gap-3 mb-4">
                <div
                  className={
                    destructive
                      ? 'w-10 h-10 rounded-xl grid place-items-center bg-red-500/10 border border-red-500/30 text-red-300 shrink-0'
                      : 'w-10 h-10 rounded-xl grid place-items-center bg-gold-400/10 border border-gold-400/20 text-gold-300 shrink-0'
                  }
                >
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div className="flex-1 min-w-0">
                  <h2 id="confirm-title" className="font-serif text-lg text-ink-50 leading-tight">
                    {title}
                  </h2>
                  {description && (
                    <p className="text-sm text-ink-300 mt-1 leading-relaxed">{description}</p>
                  )}
                </div>
                <button
                  onClick={onCancel}
                  className="w-8 h-8 grid place-items-center rounded-lg hover:bg-white/5 text-ink-300 shrink-0"
                  aria-label="Cancel"
                  type="button"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex justify-end gap-2 mt-5">
                <Button variant="ghost" size="sm" onClick={onCancel} disabled={loading}>
                  {cancelLabel}
                </Button>
                <Button
                  variant={destructive ? 'danger' : 'primary'}
                  size="sm"
                  onClick={onConfirm}
                  loading={loading}
                >
                  {confirmLabel}
                </Button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
