import { Scale, User } from 'lucide-react'
import { cn } from '@/lib/utils'
import Markdown from '@/components/Markdown'

export default function MessageBubble({
  role,
  children,
  time,
  streaming,
  onSectionClick,
}) {
  const isUser = role === 'user'
  const contentIsString = typeof children === 'string'

  return (
    <div className={cn('flex gap-3 mb-4 animate-fade-in', isUser && 'flex-row-reverse')}>
      <div
        className={cn(
          'w-9 h-9 rounded-xl grid place-items-center shrink-0 border',
          isUser
            ? 'bg-ink-700 text-ink-100 border-white/10'
            : 'bg-gold-400/10 text-gold-300 border-gold-400/20',
        )}
      >
        {isUser ? <User className="w-4 h-4" /> : <Scale className="w-4 h-4" />}
      </div>
      <div
        className={cn(
          'max-w-[78%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
          isUser
            ? 'bg-ink-700/80 text-ink-50 border border-white/5 whitespace-pre-wrap'
            : 'glass-light text-ink-100 border border-white/5',
        )}
      >
        {isUser ? (
          children
        ) : contentIsString ? (
          <Markdown onSectionClick={onSectionClick}>{children}</Markdown>
        ) : (
          children
        )}

        {streaming && (
          <span
            className="inline-block w-[7px] h-[1.05em] align-text-bottom ml-0.5
                       bg-gold-300 rounded-sm animate-pulse"
            aria-hidden="true"
          />
        )}
        {time && <div className="text-[10px] text-ink-400 mt-2">{time}</div>}
      </div>
    </div>
  )
}
