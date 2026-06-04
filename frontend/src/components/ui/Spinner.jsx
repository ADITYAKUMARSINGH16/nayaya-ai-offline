import { Loader2 } from 'lucide-react'

export default function Spinner({ label, className = '' }) {
  return (
    <div className={`flex items-center gap-2 text-ink-300 ${className}`}>
      <Loader2 className="w-4 h-4 animate-spin text-gold-400" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  )
}
