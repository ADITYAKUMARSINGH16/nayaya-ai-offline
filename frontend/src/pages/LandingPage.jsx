import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Scale, Gavel, ShieldCheck, MessagesSquare, FileText, ArrowRight, Sparkles,
} from 'lucide-react'

const FEATURES = [
  { icon: MessagesSquare, title: 'Grounded Legal Assistant', desc: 'Chat answers drawn from BNS, BNSS and BSA 2023 — every claim cites a real section.' },
  { icon: FileText,       title: 'AI FIR Drafting',          desc: 'Convert a conversation into a clean, police-style FIR with the right BNS sections.' },
  { icon: ShieldCheck,    title: 'Structured Investigation', desc: 'Evidence, witnesses, suspects, risk level — produced as queryable JSON, not prose.' },
  { icon: Gavel,          title: 'Multi-Agent Courtroom',    desc: 'Petitioner → Defence → Rebuttal → Judge, with citation verification on every verdict.' },
]

export default function LandingPage() {
  return (
    <div className="min-h-screen overflow-x-hidden">
      {/* Nav */}
      <header className="px-6 lg:px-10 py-5 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-gold-400 to-gold-600 grid place-items-center shadow-glow">
            <Scale className="w-5 h-5 text-ink-950" />
          </div>
          <span className="font-serif text-xl">Nyaya AI</span>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/login" className="btn-ghost text-sm">Sign in</Link>
          <Link to="/signup" className="btn-primary text-sm">Get started</Link>
        </div>
      </header>

      {/* Hero */}
      <section className="px-6 lg:px-10 pt-16 pb-24 max-w-6xl mx-auto text-center">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full glass-light text-xs text-gold-200 border border-gold-400/20 mb-6"
        >
          <Sparkles className="w-3.5 h-3.5" />
          Built on Bharatiya Nyaya Sanhita 2023
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.05 }}
          className="font-serif text-5xl sm:text-6xl lg:text-7xl leading-[1.05] tracking-tight"
        >
          Indian legal reasoning,
          <br />
          <span className="gradient-text">simulated end to end.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.12 }}
          className="mt-6 max-w-2xl mx-auto text-ink-300 text-lg leading-relaxed"
        >
          From the first complaint to a reasoned trial judgment — Nyaya AI orchestrates a
          team of specialised agents grounded in India&apos;s 2023 criminal codes, with every
          citation verified against the actual statute.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.18 }}
          className="mt-10 flex flex-wrap items-center justify-center gap-3"
        >
          <Link to="/signup" className="btn-primary">
            Start a case <ArrowRight className="w-4 h-4" />
          </Link>
          <Link to="/login" className="btn-ghost">I already have an account</Link>
        </motion.div>
      </section>

      {/* Features */}
      <section className="px-6 lg:px-10 pb-24 max-w-6xl mx-auto">
        <div className="grid sm:grid-cols-2 gap-4">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: i * 0.05 }}
              className="glass rounded-2xl p-6 hover:border-gold-400/30 transition"
            >
              <div className="w-11 h-11 rounded-xl bg-gold-400/10 border border-gold-400/20 grid place-items-center text-gold-300 mb-4">
                <f.icon className="w-5 h-5" />
              </div>
              <h3 className="font-serif text-xl mb-1.5">{f.title}</h3>
              <p className="text-sm text-ink-300 leading-relaxed">{f.desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Pipeline */}
      <section className="px-6 lg:px-10 pb-24 max-w-6xl mx-auto">
        <div className="glass rounded-3xl p-8 lg:p-12">
          <div className="text-center mb-8">
            <h2 className="font-serif text-3xl sm:text-4xl">The case lifecycle, automated.</h2>
            <p className="text-ink-300 mt-2">Five connected stages — citations and trust signals carried through.</p>
          </div>
          <div className="grid sm:grid-cols-5 gap-3 text-sm">
            {['Assistant', 'FIR', 'Investigation', 'Trial', 'Verdict + Appeal'].map((s, i) => (
              <div
                key={s}
                className="glass-light rounded-xl p-4 text-center relative border border-white/5"
              >
                <div className="text-gold-300 font-mono text-xs mb-1">0{i + 1}</div>
                <div className="font-medium">{s}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="px-6 lg:px-10 py-8 border-t border-white/5 text-center text-xs text-ink-400">
        Educational research project · Not a substitute for qualified legal counsel
      </footer>
    </div>
  )
}
