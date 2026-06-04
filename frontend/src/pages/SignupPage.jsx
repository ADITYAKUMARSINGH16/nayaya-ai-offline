import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Scale } from 'lucide-react'

import { useAuth } from '@/context/AuthContext'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { hasSupabase } from '@/lib/supabase'

export default function SignupPage() {
  const { signUp } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('user')
  const [loading, setLoading] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await signUp(email, password, role)
      toast.success('Account created — check your email to verify')
      nav('/app', { replace: true })
    } catch (err) {
      toast.error(err.message || 'Sign-up failed')
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

        <h1 className="font-serif text-2xl mb-1">Create your account</h1>
        <p className="text-sm text-ink-300 mb-6">Two minutes — then you can run your first case.</p>

        {!hasSupabase && (
          <div className="mb-4 text-xs p-3 rounded-lg bg-gold-400/10 border border-gold-400/20 text-gold-200">
            Supabase isn&apos;t configured — running in demo mode.
          </div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="block text-sm font-medium text-ink-200">Select Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full bg-ink-900 border border-ink-800 rounded-lg px-4 py-2.5 text-ink-100 focus:outline-none focus:border-gold-500 transition-colors"
            >
              <option value="user">User</option>
              <option value="lawyer">Lawyer</option>
              <option value="judge">Judge</option>
            </select>
          </div>
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
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="at least 6 characters"
          />
          <Button type="submit" loading={loading} className="w-full">Create account</Button>
        </form>

        <p className="text-sm text-ink-300 mt-6 text-center">
          Already registered? <Link to="/login" className="text-gold-300 hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
