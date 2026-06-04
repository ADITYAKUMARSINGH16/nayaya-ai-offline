import { useEffect, useState } from 'react'
import { ShieldAlert, Users, FolderOpen, Activity, AlertCircle } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { supabase } from '@/lib/supabase'
import Spinner from '@/components/ui/Spinner'
import toast from 'react-hot-toast'

export default function AdminDashboardPage() {
  const { user } = useAuth()
  const [users, setUsers] = useState([])
  const [totalCases, setTotalCases] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchData = async () => {
    try {
      setLoading(true)
      // Fetch users
      const { data: profiles, error: profilesError } = await supabase
        .from('profiles')
        .select('*')
        .order('created_at', { ascending: false })
      
      if (profilesError) throw profilesError
      setUsers(profiles || [])

      // Fetch case count
      const { count: casesCount, error: casesError } = await supabase
        .from('cases')
        .select('*', { count: 'exact', head: true })
        
      if (casesError) throw casesError
      setTotalCases(casesCount || 0)

    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleRoleChange = async (userId, newRole) => {
    try {
      const { error } = await supabase
        .from('profiles')
        .update({ role: newRole })
        .eq('id', userId)
        
      if (error) throw error
      toast.success('Role updated successfully')
      setUsers(users.map(u => u.id === userId ? { ...u, role: newRole } : u))
    } catch (err) {
      toast.error('Failed to update role: ' + err.message)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Spinner label="Loading dashboard data..." />
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <header className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-gold-400/20 text-gold-300 rounded-lg">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <h1 className="font-serif text-3xl">Admin Dashboard</h1>
        </div>
        <p className="text-ink-300">
          Welcome, {user?.email}. You have administrative privileges.
        </p>
      </header>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl flex items-center gap-3 text-red-400">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="p-3 bg-blue-500/10 text-blue-400 rounded-xl">
            <Users className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-ink-400 mb-1">Total Users</h3>
            <p className="text-3xl font-serif">{users.length}</p>
          </div>
        </div>
        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="p-3 bg-purple-500/10 text-purple-400 rounded-xl">
            <FolderOpen className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-ink-400 mb-1">Total Cases</h3>
            <p className="text-3xl font-serif">{totalCases}</p>
          </div>
        </div>
        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="p-3 bg-green-500/10 text-green-400 rounded-xl">
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-ink-400 mb-1">System Status</h3>
            <p className="text-3xl font-serif text-green-400">Online</p>
          </div>
        </div>
      </div>
      
      <div className="glass rounded-2xl mt-8 overflow-hidden border border-white/5">
        <div className="p-6 border-b border-white/5 bg-white/[0.02]">
          <h2 className="text-xl font-serif">User Management</h2>
          <p className="text-sm text-ink-400 mt-1">Manage registered users and their roles</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-ink-200">
            <thead className="text-xs uppercase bg-ink-900/50 text-ink-400 border-b border-white/5">
              <tr>
                <th className="px-6 py-4 font-medium">Email</th>
                <th className="px-6 py-4 font-medium">Joined Date</th>
                <th className="px-6 py-4 font-medium">Role</th>
                <th className="px-6 py-4 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="px-6 py-4 font-medium text-ink-50">{u.email || 'No email provided'}</td>
                  <td className="px-6 py-4">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border
                      ${u.role === 'admin' ? 'bg-red-500/10 text-red-400 border-red-500/20' : 
                        u.role === 'judge' ? 'bg-purple-500/10 text-purple-400 border-purple-500/20' :
                        u.role === 'lawyer' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                        'bg-ink-500/10 text-ink-300 border-ink-500/20'}
                    `}>
                      {u.role.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <select
                      value={u.role}
                      onChange={(e) => handleRoleChange(u.id, e.target.value)}
                      disabled={u.id === user.id}
                      className="bg-ink-900 border border-ink-800 rounded px-2 py-1 text-xs focus:outline-none focus:border-gold-500 disabled:opacity-50"
                    >
                      <option value="user">User</option>
                      <option value="lawyer">Lawyer</option>
                      <option value="judge">Judge</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan="4" className="px-6 py-8 text-center text-ink-400">
                    No users found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
