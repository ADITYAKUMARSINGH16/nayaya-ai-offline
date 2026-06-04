import { cn } from '@/lib/utils'

export default function Skeleton({ className = '' }) {
  return (
    <div
      className={cn(
        'animate-pulse rounded-md bg-gradient-to-r from-white/5 via-white/10 to-white/5 bg-[length:200%_100%]',
        className,
      )}
    />
  )
}

export function SkeletonText({ lines = 3, className = '' }) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className="h-3"
          style={{ width: `${85 - i * 10}%` }}
        />
      ))}
    </div>
  )
}

export function SkeletonCard({ className = '' }) {
  return (
    <div className={cn('glass rounded-2xl p-5 space-y-3', className)}>
      <div className="flex items-center gap-3">
        <Skeleton className="w-10 h-10 rounded-xl" />
        <Skeleton className="h-4 w-32" />
      </div>
      <SkeletonText />
    </div>
  )
}
