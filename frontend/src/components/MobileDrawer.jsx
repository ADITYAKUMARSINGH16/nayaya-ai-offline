import { AnimatePresence, motion } from 'framer-motion'
import { X, Scale } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, MessagesSquare, FileText, ShieldAlert, Gavel, History, BarChart3,
} from 'lucide-react'
import { cn } from '@/lib/utils'

import { useAuth } from '@/context/AuthContext'

const NAV = [
  { to: '/app',               label: 'Dashboard',     icon: LayoutDashboard, end: true },
  { to: '/app/assistant',     label: 'AI Assistant',  icon: MessagesSquare },
  { to: '/app/fir',           label: 'FIR Draft',     icon: FileText },
  { to: '/app/investigation', label: 'Investigation', icon: ShieldAlert },
  { to: '/app/trial',         label: 'Courtroom',     icon: Gavel },
  { to: '/app/cases',         label: 'Case History',  icon: History },
  { to: '/app/eval',          label: 'Eval Dashboard',icon: BarChart3 },
]

export default function MobileDrawer({ open, onClose }) {
  const { user } = useAuth()
  
  const navItems = [...NAV]
  if (user?.role === 'admin') {
    navItems.push({ to: '/app/admin', label: 'Admin Dashboard', icon: ShieldAlert })
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-ink-950/70 backdrop-blur-sm z-40 lg:hidden"
          />
          <motion.aside
            initial={{ x: -320 }}
            animate={{ x: 0 }}
            exit={{ x: -320 }}
            transition={{ type: 'spring', damping: 28, stiffness: 260 }}
            className="fixed top-0 left-0 bottom-0 w-72 bg-ink-950 border-r border-white/5 z-50 lg:hidden flex flex-col"
          >
            <div className="px-5 py-4 flex items-center justify-between border-b border-white/5">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-gold-400 to-gold-600 grid place-items-center shadow-glow">
                  <Scale className="w-5 h-5 text-ink-950" />
                </div>
                <div className="font-serif text-lg">Nyaya AI</div>
              </div>
              <button onClick={onClose} className="p-2 rounded-lg hover:bg-white/5">
                <X className="w-5 h-5 text-ink-300" />
              </button>
            </div>
            <nav className="flex-1 p-3 space-y-1">
              {navItems.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  onClick={onClose}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition',
                      isActive
                        ? 'bg-gold-400/10 text-gold-200 border border-gold-400/20'
                        : 'text-ink-300 hover:text-ink-50 hover:bg-white/5 border border-transparent',
                    )
                  }
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{label}</span>
                </NavLink>
              ))}
            </nav>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
