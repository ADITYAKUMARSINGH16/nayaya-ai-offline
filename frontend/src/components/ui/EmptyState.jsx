export default function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="text-center py-12 px-6">
      {Icon && (
        <div className="mx-auto w-14 h-14 grid place-items-center rounded-2xl bg-gold-400/10 border border-gold-400/20 text-gold-300 mb-4">
          <Icon className="w-6 h-6" />
        </div>
      )}
      <h3 className="font-serif text-lg text-ink-100">{title}</h3>
      {description && <p className="text-sm text-ink-300 mt-1 max-w-md mx-auto">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
