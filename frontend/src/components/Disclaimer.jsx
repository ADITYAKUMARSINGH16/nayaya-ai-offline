import { AlertTriangle } from 'lucide-react'

export default function Disclaimer({ className = '' }) {
  return (
    <div
      className={`flex items-start gap-2 text-[11px] leading-relaxed p-3 rounded-lg
                  bg-gold-400/5 border border-gold-400/20 text-gold-200 ${className}`}
    >
      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
      <span>
        AI-generated content. Educational use only — not legal advice. Every output should be
        reviewed by a qualified advocate before any official use.
      </span>
    </div>
  )
}
