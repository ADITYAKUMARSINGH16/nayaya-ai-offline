import { createContext, useContext, useEffect, useState } from 'react'
import { hasSupabase, supabase } from '@/lib/supabase'

const AuthCtx = createContext({
  user: null,
  loading: true,
  signIn: async () => {},
  signUp: async () => {},
  signOut: async () => {},
})

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!hasSupabase) {
      // Demo mode — no Supabase configured. Use a pseudo-user so the app still runs.
      setUser({ id: 'demo-user', email: 'demo@nyaya.ai', demo: true, role: 'admin' })
      setLoading(false)
      return
    }

    const fetchProfile = async (sessionUser) => {
      if (!sessionUser) {
        setUser(null)
        setLoading(false)
        return
      }
      
      const { data } = await supabase
        .from('profiles')
        .select('role')
        .eq('id', sessionUser.id)
        .single()
        
      const rawRole = data?.role || sessionUser?.user_metadata?.role || 'user'
      setUser({ ...sessionUser, role: rawRole.toLowerCase() })
      setLoading(false)
    }

    supabase.auth.getSession().then(({ data }) => {
      fetchProfile(data.session?.user)
    })

    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      fetchProfile(session?.user)
    })

    return () => sub.subscription.unsubscribe()
  }, [])

  const signIn = async (email, password) => {
    if (!hasSupabase) throw new Error('Supabase is not configured')
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
  }
  const signUp = async (email, password, role = 'user') => {
    if (!hasSupabase) throw new Error('Supabase is not configured')
    const { error } = await supabase.auth.signUp({ 
      email, 
      password,
      options: {
        data: {
          role
        }
      }
    })
    if (error) throw error
  }
  const signOut = async () => {
    if (hasSupabase) await supabase.auth.signOut()
    setUser(null)
  }

  return (
    <AuthCtx.Provider value={{ user, loading, signIn, signUp, signOut }}>
      {children}
    </AuthCtx.Provider>
  )
}

export const useAuth = () => useContext(AuthCtx)
