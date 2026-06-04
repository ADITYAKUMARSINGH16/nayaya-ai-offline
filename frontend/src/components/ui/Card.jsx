import { cn } from '@/lib/utils'

export default function Card({ className = '', children, ...props }) {
  return (
    <div
      className={cn(
        'glass rounded-2xl p-5 sm:p-6 animate-slide-up',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ icon: Icon, title, subtitle, action }) {
  return (
    <div className="flex items-start justify-between gap-4 mb-4">
      <div className="flex items-start gap-3">
        {Icon && (
          <div className="w-10 h-10 rounded-xl bg-gold-400/10 text-gold-300 grid place-items-center border border-gold-400/20 shrink-0">
            <Icon className="w-5 h-5" />
          </div>
        )}
        <div>
          <h3 className="font-serif text-lg text-ink-50 leading-tight">{title}</h3>
          {subtitle && <p className="text-sm text-ink-300 mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  )
}
