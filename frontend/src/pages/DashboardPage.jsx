import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { MessagesSquare, FileText, ShieldAlert, Gavel, ArrowRight, History } from 'lucide-react'

import Card, { CardHeader } from '@/components/ui/Card'
import { useAuth } from '@/context/AuthContext'

const QUICK_ACTIONS_USER = [
  { to: '/app/assistant',     icon: MessagesSquare, title: 'Ask the assistant',  desc: 'Get a grounded answer with citations.' },
  { to: '/app/fir',           icon: FileText,       title: 'Draft an FIR',       desc: 'Convert facts into a police-style FIR.' },
  { to: '/app/investigation', icon: ShieldAlert,    title: 'Run investigation',  desc: 'Evidence, witnesses, risk level.' },
  { to: '/app/trial',         icon: Gavel,          title: 'Simulate trial',     desc: 'Petitioner → Defence → Rebuttal → Judge.' },
]

const QUICK_ACTIONS_LAWYER = [
  { to: '/app/lawyer/ai',     icon: MessagesSquare, title: 'AI Lawyer',          desc: 'Analyze cases, find weaknesses, prep cross-examination.' },
  { to: '/app/cases',         icon: FileText,       title: 'Active Cases',       desc: 'Review cases assigned to you.' },
  { to: '/app/trial',         icon: Gavel,          title: 'Courtroom',          desc: 'Enter virtual courtroom.' },
]

const QUICK_ACTIONS_JUDGE = [
  { to: '/app/judge',         icon: Gavel,          title: 'Pending Verdicts',   desc: 'Review and approve/override AI recommended verdicts.' },
  { to: '/app/cases',         icon: History,        title: 'Case History',       desc: 'View all closed and active cases.' },
]

export default function DashboardPage() {
  const { user } = useAuth()
  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <p className="text-sm text-ink-400">Welcome back,</p>
        <h1 className="font-serif text-3xl">{user?.email?.split('@')[0] || 'Counsel'}</h1>
      </motion.div>

      {/* Quick actions */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {(user?.role === 'lawyer' ? QUICK_ACTIONS_LAWYER : user?.role === 'judge' ? QUICK_ACTIONS_JUDGE : QUICK_ACTIONS_USER).map((a, i) => (
          <Link key={a.to} to={a.to}>
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: i * 0.04 }}
              className="glass rounded-2xl p-5 h-full hover:border-gold-400/30 transition group cursor-pointer"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="w-11 h-11 rounded-xl bg-gold-400/10 border border-gold-400/20 grid place-items-center text-gold-300">
                  <a.icon className="w-5 h-5" />
                </div>
                <ArrowRight className="w-4 h-4 text-ink-400 group-hover:text-gold-300 group-hover:translate-x-1 transition" />
              </div>
              <div className="font-serif text-lg leading-tight">{a.title}</div>
              <div className="text-sm text-ink-300 mt-1 leading-relaxed">{a.desc}</div>
            </motion.div>
          </Link>
        ))}
      </div>

      {/* Pipeline overview */}
      <Card>
        <CardHeader
          icon={Gavel}
          title="How a case flows through Nyaya AI"
          subtitle="Each stage is its own agent. Citations and case state carry through to the next."
        />
        <div className="grid md:grid-cols-5 gap-3 mt-2 text-sm">
          {[
            { n: '1', t: 'Assistant',    d: 'Chat to gather facts & relevant sections.' },
            { n: '2', t: 'FIR',          d: 'Draft a formal FIR under BNS 2023.' },
            { n: '3', t: 'Investigation',d: 'Build evidence, witness, suspect tree.' },
            { n: '4', t: 'Trial',        d: 'Multi-agent courtroom simulation.' },
            { n: '5', t: 'Verdict',      d: 'Verified citations + appeal option.' },
          ].map((s) => (
            <div key={s.n} className="glass-light rounded-xl p-4 border border-white/5">
              <div className="text-gold-300 font-mono text-xs mb-1">0{s.n}</div>
              <div className="font-medium">{s.t}</div>
              <div className="text-xs text-ink-400 mt-1 leading-relaxed">{s.d}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
