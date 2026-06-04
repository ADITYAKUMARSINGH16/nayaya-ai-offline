import { motion } from 'framer-motion'
import { Gavel, Scale, Shield, Sword } from 'lucide-react'

const ROLE_META = {
  petitioner: { icon: Sword,   label: 'Petitioner',     tint: 'from-emerald-500/15 to-emerald-500/0', accent: 'text-emerald-300' },
  opponent:   { icon: Shield,  label: 'Defence',        tint: 'from-sky-500/15 to-sky-500/0',         accent: 'text-sky-300' },
  cross_examination: { icon: Sword, label: 'Cross Exam', tint: 'from-red-500/15 to-red-500/0',        accent: 'text-red-300' },
  rebuttal:   { icon: Scale,   label: 'Rebuttal',       tint: 'from-amber-500/15 to-amber-500/0',     accent: 'text-amber-300' },
  judge:      { icon: Gavel,   label: 'Judgment',       tint: 'from-gold-400/20 to-gold-400/0',       accent: 'text-gold-300' },
}

export default function CourtPanel({ role, data, delay = 0 }) {
  const m = ROLE_META[role] || ROLE_META.petitioner
  const Icon = m.icon
  if (!data) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className={`relative overflow-hidden rounded-2xl border border-white/5 glass p-5`}
    >
      <div className={`absolute inset-x-0 top-0 h-32 bg-gradient-to-b ${m.tint} pointer-events-none`} />
      <div className="relative">
        <div className="flex items-center gap-2 mb-3">
          <div className={`w-9 h-9 rounded-xl bg-white/5 grid place-items-center border border-white/10 ${m.accent}`}>
            <Icon className="w-4 h-4" />
          </div>
          <h3 className="font-serif text-lg">{m.label}</h3>
        </div>

        {data.opinion && (
          <p className="text-sm text-ink-100 leading-relaxed mb-3">{data.opinion}</p>
        )}

        {Array.isArray(data.arguments) && data.arguments.length > 0 && (
          <ul className="space-y-1.5 text-sm text-ink-200">
            {data.arguments.map((a, i) => {
              let text = a;
              if (typeof a === 'object' && a !== null) {
                text = a.argument || a.text || Object.values(a)[0] || JSON.stringify(a);
              } else if (typeof a === 'string') {
                try {
                  const parsed = JSON.parse(a);
                  if (parsed && typeof parsed === 'object' && parsed.argument) {
                    text = parsed.argument;
                  }
                } catch (e) {
                  const match = a.match(/['"]argument['"]\s*:\s*['"]([\s\S]*?)['"]\s*,\s*['"]legal_reference['"]/);
                  if (match) {
                    text = match[1].replace(/\\'/g, "'").replace(/\\"/g, '"');
                  } else {
                    const fallback = a.match(/['"]?argument['"]?\s*:\s*['"]([\s\S]*?)['"]\s*[},]/);
                    if (fallback) text = fallback[1].replace(/\\'/g, "'").replace(/\\"/g, '"');
                  }
                }
              }
              return (
                <li key={i} className="flex gap-2">
                  <span className="text-gold-400">·</span>
                  <span>{text}</span>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </motion.div>
  )
}
