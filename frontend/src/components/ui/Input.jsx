import { cn } from '@/lib/utils'

export default function Input({ label, error, className = '', ...props }) {
  return (
    <label className="block">
      {label && <span className="label">{label}</span>}
      <input className={cn('input', className)} {...props} />
      {error && <span className="text-xs text-red-400 mt-1 block">{error}</span>}
    </label>
  )
}

export function Textarea({ label, error, className = '', rows = 5, ...props }) {
  return (
    <label className="block">
      {label && <span className="label">{label}</span>}
      <textarea rows={rows} className={cn('input resize-y', className)} {...props} />
      {error && <span className="text-xs text-red-400 mt-1 block">{error}</span>}
    </label>
  )
}
