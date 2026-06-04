import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Scale } from 'lucide-react'

import { useAuth } from '@/context/AuthContext'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { hasSupabase, supabase } from '@/lib/supabase'

export default function LoginPage() {
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
            
          if (profile?.role === 'admin') {
            await supabase.auth.signOut()
            throw new Error('Admins must log in via the Admin Login page')
          }
        }
      }

      toast.success('Welcome back')
      nav('/app', { replace: true })
    } catch (err) {
      toast.error(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen grid place-items-center px-6">
      <div className="w-full max-w-md glass rounded-2xl p-8 animate-slide-up">
        <Link to="/" className="flex items-center gap-2.5 mb-7">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-gold-400 to-gold-600 grid place-items-center shadow-glow">
            <Scale className="w-5 h-5 text-ink-950" />
          </div>
          <span className="font-serif text-xl">Nyaya AI</span>
        </Link>

        <h1 className="font-serif text-2xl mb-1">Sign in</h1>
        <p className="text-sm text-ink-300 mb-6">Continue your legal workspace.</p>

        {!hasSupabase && (
          <div className="mb-4 text-xs p-3 rounded-lg bg-gold-400/10 border border-gold-400/20 text-gold-200">
            Supabase isn&apos;t configured — running in demo mode. Any details work.
          </div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="Email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
          <Input
            label="Password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
          <Button type="submit" loading={loading} className="w-full">Sign in</Button>
        </form>

        <p className="text-sm text-ink-300 mt-6 text-center">
          New here? <Link to="/signup" className="text-gold-300 hover:underline">Create an account</Link>
        </p>
        <p className="text-xs text-ink-400 mt-4 text-center">
          <Link to="/admin-login" className="hover:underline">Admin Login</Link>
        </p>
      </div>
    </div>
  )
}
