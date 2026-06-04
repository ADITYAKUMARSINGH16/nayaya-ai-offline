import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, MessagesSquare, FileText, ShieldAlert, Gavel,
  History, Scale, BarChart3, PanelLeftClose, PanelLeftOpen,
} from 'lucide-react'
import { cn } from '@/lib/utils'

import { useAuth } from '@/context/AuthContext'

const NAV = [
  { to: '/app',              label: 'Dashboard',     icon: LayoutDashboard, end: true },
  { to: '/app/assistant',    label: 'AI Assistant',  icon: MessagesSquare },
  { to: '/app/fir',          label: 'FIR Draft',     icon: FileText },
  { to: '/app/investigation',label: 'Investigation', icon: ShieldAlert },
  { to: '/app/trial',        label: 'Courtroom',     icon: Gavel },
  { to: '/app/cases',        label: 'Case History',  icon: History },
  { to: '/app/eval',         label: 'Evaluation',    icon: BarChart3 },
]

export default function Sidebar({ collapsed, onToggle }) {
  const { user } = useAuth()
  
  let navItems = [...NAV]
  
  if (user?.role === 'lawyer') {
    navItems = [
      { to: '/app',              label: 'Lawyer Dashboard',icon: LayoutDashboard, end: true },
      { to: '/app/lawyer/ai',    label: 'AI Lawyer',     icon: MessagesSquare },
      { to: '/app/cases',        label: 'Case Files',    icon: FileText },
      { to: '/app/trial',        label: 'Courtroom',     icon: Gavel },
      { to: '/app/eval',         label: 'Evaluation',    icon: BarChart3 },
    ]
  } else if (user?.role === 'judge') {
    navItems = [
      { to: '/app',              label: 'Judge Dashboard', icon: LayoutDashboard, end: true },
      { to: '/app/judge',        label: 'Pending Verdicts',icon: Gavel },
      { to: '/app/judge/ai',     label: 'AI Judge',        icon: MessagesSquare },
      { to: '/app/investigation',label: 'Investigation',   icon: ShieldAlert },
      { to: '/app/trial',        label: 'Courtroom',       icon: Gavel },
      { to: '/app/cases',        label: 'Case History',    icon: History },
      { to: '/app/eval',         label: 'Evaluation',      icon: BarChart3 },
    ]
  }

  if (user?.role === 'admin') {
    navItems.push({ to: '/app/admin', label: 'Admin Dashboard', icon: ShieldAlert })
  }

  return (
    <aside
      className={cn(
        // sticky + h-screen so the sidebar stays viewport-tall; the nav
        // inside scrolls if needed, but the footer (Collapse + Disclaimer)
        // is always pinned to the bottom of the visible area.
        'hidden lg:flex shrink-0 flex-col border-r border-white/5 bg-ink-950/60 backdrop-blur-xl transition-[width] duration-200',
        'sticky top-0 h-screen self-start',
        collapsed ? 'w-[68px]' : 'w-64',
      )}
    >
      {/* Header */}
      <div
        className={cn(
          'flex items-center gap-2.5 border-b border-white/5 h-[65px]',
          collapsed ? 'justify-center px-2' : 'px-6',
        )}
      >
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-gold-400 to-gold-600 grid place-items-center shadow-glow shrink-0">
          <Scale className="w-5 h-5 text-ink-950" />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="font-serif text-lg leading-none">Nyaya AI</div>
            <div className="text-[10px] text-ink-400 tracking-wider uppercase">
              Indian Legal Intelligence
            </div>
          </div>
        )}
      </div>

      {/* Nav — flex-1 + min-h-0 + overflow lets it scroll internally
          when the link list is longer than viewport, without pushing
          the footer (Collapse + Disclaimer) off-screen. */}
      <nav className="flex-1 min-h-0 overflow-y-auto p-3 space-y-1">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-xl text-sm transition border',
                collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5',
                isActive
                  ? 'bg-gold-400/10 text-gold-200 border-gold-400/20'
                  : 'text-ink-300 hover:text-ink-50 hover:bg-white/5 border-transparent',
              )
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            {!collapsed && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Footer: collapse toggle + (when expanded) disclaimer */}
      <div className={cn('p-3 space-y-3', collapsed && 'p-2')}>
        {!collapsed && (
          <div className="p-3 rounded-xl glass-light text-[11px] text-ink-300 leading-relaxed">
            <span className="text-gold-300 font-medium">Disclaimer: </span>
            Educational tool only. Not a substitute for legal advice — always consult a qualified advocate.
          </div>
        )}
        <button
          onClick={onToggle}
          className={cn(
            'w-full flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-ink-200 transition',
            collapsed ? 'justify-center p-2' : 'px-3 py-2 text-sm',
          )}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <PanelLeftOpen className="w-4 h-4" />
          ) : (
            <>
              <PanelLeftClose className="w-4 h-4" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
