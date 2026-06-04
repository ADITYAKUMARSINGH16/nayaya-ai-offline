import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { ShieldAlert } from 'lucide-react'

import { useAuth } from '@/context/AuthContext'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { hasSupabase, supabase } from '@/lib/supabase'

export default function AdminLoginPage() {
  const { signIn } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await signIn(email, password)

      if (hasSupabase) {
        const { data: { session } } = await supabase.auth.getSession()
        if (session) {
          const { data: profile } = await supabase
            .from('profiles')
            .select('role')
            .eq('id', session.user.id)
            .single()
            
          if (profile?.role !== 'admin') {
            await supabase.auth.signOut()
            throw new Error('Access denied: User is not an administrator')
          }
        }
      }

      toast.success('Admin login successful')
      nav('/app/admin', { replace: true })
    } catch (err) {
      toast.error(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen grid place-items-center px-6 bg-ink-950">
      <div className="w-full max-w-md glass border border-red-500/20 rounded-2xl p-8 animate-slide-up">
        <Link to="/" className="flex items-center gap-2.5 mb-7">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-red-400 to-red-600 grid place-items-center shadow-glow">
            <ShieldAlert className="w-5 h-5 text-ink-950" />
          </div>
          <span className="font-serif text-xl">Nyaya AI</span>
        </Link>

        <h1 className="font-serif text-2xl mb-1 text-red-100">Admin Sign in</h1>
        <p className="text-sm text-ink-300 mb-6">Restricted access portal.</p>

        {!hasSupabase && (
          <div className="mb-4 text-xs p-3 rounded-lg bg-gold-400/10 border border-gold-400/20 text-gold-200">
            Supabase isn&apos;t configured — running in demo mode. Any details work.
          </div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="Admin Email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@nyaya.ai"
          />
          <Input
            label="Password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
          <Button type="submit" loading={loading} className="w-full bg-red-600 hover:bg-red-500 text-white border-none">
            Sign in as Admin
          </Button>
        </form>

        <p className="text-sm text-ink-300 mt-6 text-center">
          Not an admin? <Link to="/login" className="text-red-400 hover:underline">User Sign in</Link>
        </p>
      </div>
    </div>
  )
}
