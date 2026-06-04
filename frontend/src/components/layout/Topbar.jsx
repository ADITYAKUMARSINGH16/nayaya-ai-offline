import { useEffect, useState } from 'react'
import { LogOut, Menu, Moon, Sun, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import Button from '@/components/ui/Button'
import { useAuth } from '@/context/AuthContext'

export default function Topbar({ onMenu }) {
  const { user, signOut } = useAuth()
  const nav = useNavigate()
  const [theme, setTheme] = useState(
    () => (typeof window !== 'undefined' && localStorage.getItem('nyaya-theme')) || 'dark',
  )
  
  useEffect(() => {
    console.log("Topbar rendered. user:", user);
  }, [user])

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('light', theme === 'light')
    root.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('nyaya-theme', theme)
  }, [theme])

  const handleSignOut = async () => {
    await signOut()
    nav('/login', { replace: true })
  }

  return (
    <header className="h-16 px-4 sm:px-6 flex items-center justify-between border-b border-white/5 bg-ink-950/40 backdrop-blur-xl sticky top-0 z-20 no-print">
      <div className="flex items-center gap-2 min-w-0">
        <button
          onClick={onMenu}
          className="lg:hidden p-2 rounded-lg hover:bg-white/5"
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5 text-ink-200" />
        </button>
        <div className="hidden md:flex items-center gap-2 font-serif text-base text-ink-100">
          <span>Nyaya AI</span>
          <span className="text-xs text-ink-400 font-sans">Indian legal AI · BNS, BNSS, BSA 2023</span>
          {(user?.role || user?.user_metadata?.role || 'user') && (
            <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-sans font-medium bg-gold-500/10 text-gold-400 border border-gold-500/20 uppercase tracking-wider">
              {user?.role || user?.user_metadata?.role || 'user'}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
          className="p-2 rounded-lg hover:bg-white/5 text-ink-200"
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg glass-light text-sm text-ink-200">
          <User className="w-4 h-4 text-gold-300" />
          <span className="truncate max-w-[200px]">{user?.email}</span>
        </div>
        <Button variant="ghost" size="sm" onClick={handleSignOut}>
          <LogOut className="w-4 h-4" />
          <span className="hidden sm:inline">Sign out</span>
        </Button>
      </div>
    </header>
  )
}
