import { useEffect, useState } from 'react'
import { ShieldAlert, Users, FolderOpen, Activity, AlertCircle, FileText, Gavel, Printer, Download } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { supabase } from '@/lib/supabase'
import { api } from '@/api/client'
import Spinner from '@/components/ui/Spinner'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'
import { useCase } from '@/context/CaseContext'
import CourtPanel from '@/components/CourtPanel'
import Badge from '@/components/ui/Badge'
import Button from '@/components/ui/Button'
import Disclaimer from '@/components/Disclaimer'
import { downloadText } from '@/lib/utils'

export default function AdminDashboardPage() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState('users')
  
  const [users, setUsers] = useState([])
  const [firs, setFirs] = useState([])
  const [cases, setCases] = useState([])
  const [graphStats, setGraphStats] = useState(null)
  
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  const [actionLoading, setActionLoading] = useState(false)
  const [selectedFir, setSelectedFir] = useState(null)
  const [selectedCase, setSelectedCase] = useState(null)

  const navigate = useNavigate()
  const { updateCase } = useCase()

  const fetchData = async () => {
    try {
      setLoading(true)
      
      // Fetch users directly via Supabase for now since it was already implemented that way
      const { data: profiles, error: profilesError } = await supabase
        .from('profiles')
        .select('*')
        .order('created_at', { ascending: false })
      
      if (profilesError) throw profilesError
      setUsers(profiles || [])

      // Fetch global FIRs via backend
      const firRes = await api.adminGetFirs()
      setFirs(firRes.firs || [])
      
      // Fetch global Cases via backend (paginated; first page only here)
      const caseRes = await api.adminGetCases({ limit: 50, offset: 0 })
      setCases(caseRes.cases || [])

      // Fetch knowledge-graph health (best-effort — non-fatal if it fails).
      try {
        const stats = await api.adminGetStats()
        setGraphStats(stats?.graph || null)
      } catch {
        setGraphStats(null)
      }
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
  
  const handleFirStatusOverride = async (firId, newStatus) => {
    try {
      setActionLoading(true)
      const res = await api.adminOverrideFirStatus(firId, newStatus)
      toast.success('FIR status updated')
      setFirs(firs.map(f => f.id === firId ? res.fir : f))
    } catch (err) {
      toast.error('Failed to override status: ' + err.message)
    } finally {
      setActionLoading(false)
    }
  }

  const handleViewCase = (c) => {
    setSelectedCase(c)
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

      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
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
          <div className="p-3 bg-red-500/10 text-red-400 rounded-xl">
            <FileText className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-ink-400 mb-1">Total FIRs</h3>
            <p className="text-3xl font-serif">{firs.length}</p>
          </div>
        </div>
        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="p-3 bg-purple-500/10 text-purple-400 rounded-xl">
            <FolderOpen className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-ink-400 mb-1">Total Cases</h3>
            <p className="text-3xl font-serif">{cases.length}</p>
          </div>
        </div>
        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="p-3 bg-green-500/10 text-green-400 rounded-xl">
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-ink-400 mb-1">Knowledge Graph</h3>
            {graphStats ? (
              <>
                <p className="text-3xl font-serif text-green-400">
                  {graphStats.entities ?? graphStats.nodes ?? '—'}
                </p>
                <p className="text-xs text-ink-400 mt-0.5">
                  entities · {graphStats.relationships ?? graphStats.edges ?? '—'} edges
                  {graphStats.communities ? ` · ${graphStats.communities} communities` : ''}
                </p>
              </>
            ) : (
              <p className="text-3xl font-serif text-ink-400">offline</p>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/10 mt-8 gap-6">
        {['users', 'firs', 'cases'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`pb-3 text-sm font-medium transition-colors border-b-2 ${
              activeTab === tab 
                ? 'border-gold-500 text-gold-400' 
                : 'border-transparent text-ink-400 hover:text-ink-200'
            }`}
          >
            {tab.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="glass rounded-2xl overflow-hidden border border-white/5">
        
        {/* USERS TAB */}
        {activeTab === 'users' && (
          <>
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
          </>
        )}

        {/* FIRS TAB */}
        {activeTab === 'firs' && (
          <>
            <div className="p-6 border-b border-white/5 bg-white/[0.02]">
              <h2 className="text-xl font-serif">Global FIRs</h2>
              <p className="text-sm text-ink-400 mt-1">View all FIRs and forcefully override their status</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-ink-200">
                <thead className="text-xs uppercase bg-ink-900/50 text-ink-400 border-b border-white/5">
                  <tr>
                    <th className="px-6 py-4 font-medium">FIR ID</th>
                    <th className="px-6 py-4 font-medium">Category</th>
                    <th className="px-6 py-4 font-medium">Date</th>
                    <th className="px-6 py-4 font-medium">Status</th>
                    <th className="px-6 py-4 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {firs.map((f) => (
                    <tr key={f.id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-4 font-medium text-ink-50">{f.id.slice(0, 8)}...</td>
                      <td className="px-6 py-4">{f.data?.category || 'General'}</td>
                      <td className="px-6 py-4">{new Date(f.created_at).toLocaleDateString()}</td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border
                          ${f.status === 'filed' ? 'bg-green-500/10 text-green-400 border-green-500/20' : 
                            f.status === 'rejected' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                            f.status === 'approved' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                            'bg-yellow-500/10 text-yellow-400 border-yellow-500/20'}
                        `}>
                          {f.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 flex items-center justify-end gap-2">
                        <button
                          onClick={() => setSelectedFir(f)}
                          className="px-3 py-1.5 text-xs font-medium bg-white/5 hover:bg-white/10 text-ink-200 border border-white/10 rounded transition"
                        >
                          View
                        </button>
                        <select
                          value={f.status}
                          onChange={(e) => handleFirStatusOverride(f.id, e.target.value)}
                          disabled={actionLoading}
                          className="bg-ink-900 border border-ink-800 rounded px-2 py-1 text-xs focus:outline-none focus:border-gold-500 disabled:opacity-50"
                        >
                          <option value="draft">Draft</option>
                          <option value="pending_approval">Pending</option>
                          <option value="approved">Approved</option>
                          <option value="rejected">Rejected</option>
                          <option value="filed">Filed</option>
                        </select>
                      </td>
                    </tr>
                  ))}
                  {firs.length === 0 && (
                    <tr>
                      <td colSpan="5" className="px-6 py-8 text-center text-ink-400">
                        No FIRs found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* CASES TAB */}
        {activeTab === 'cases' && (
          <>
            <div className="p-6 border-b border-white/5 bg-white/[0.02]">
              <h2 className="text-xl font-serif">Global Cases</h2>
              <p className="text-sm text-ink-400 mt-1">View all Cases across the platform</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-ink-200">
                <thead className="text-xs uppercase bg-ink-900/50 text-ink-400 border-b border-white/5">
                    <tr>
                    <th className="px-6 py-4 font-medium">Case ID</th>
                    <th className="px-6 py-4 font-medium">Status</th>
                    <th className="px-6 py-4 font-medium">Date</th>
                    <th className="px-6 py-4 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {cases.map((c) => (
                    <tr key={c.id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-4 font-medium text-ink-50">{c.id.slice(0, 8)}...</td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border
                          ${c.status === 'closed' ? 'bg-red-500/10 text-red-400 border-red-500/20' : 
                            'bg-green-500/10 text-green-400 border-green-500/20'}
                        `}>
                          {c.status}
                        </span>
                      </td>
                      <td className="px-6 py-4">{new Date(c.created_at).toLocaleDateString()}</td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => handleViewCase(c)}
                          className="px-3 py-1.5 text-xs font-medium bg-gold-500/10 hover:bg-gold-500/20 text-gold-300 border border-gold-500/20 rounded transition"
                        >
                          View Case
                        </button>
                      </td>
                    </tr>
                  ))}
                  {cases.length === 0 && (
                    <tr>
                      <td colSpan="5" className="px-6 py-8 text-center text-ink-400">
                        No Cases found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

      </div>

      {selectedFir && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink-950/80 backdrop-blur-sm animate-in fade-in">
          <div className="bg-ink-900 border border-white/10 p-6 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col relative shadow-2xl">
            <div className="flex items-center justify-between mb-4 shrink-0">
              <h3 className="text-xl font-serif text-gold-400">FIR Details - {selectedFir.id.slice(0, 8)}...</h3>
              <div className="flex gap-2 print:hidden">
                <Button variant="ghost" size="sm" onClick={() => window.print()}>
                  <Printer className="w-4 h-4" /> Print / PDF
                </Button>
                <Button variant="ghost" size="sm"
                  onClick={() => downloadText(`FIR_${selectedFir.complainant_name || 'draft'}_${Date.now()}.txt`, selectedFir.fir_text)}>
                  <Download className="w-4 h-4" /> .txt
                </Button>
              </div>
            </div>
            
            <div className="flex-1 overflow-auto bg-black/40 rounded-xl border border-white/5 p-5 custom-scrollbar printable">
              <Disclaimer className="mb-4 print:hidden" />
              <pre className="whitespace-pre-wrap text-sm text-ink-100 font-sans leading-relaxed print:text-black print:whitespace-pre-wrap">
                {selectedFir.fir_text}
              </pre>
              

            </div>
            
            <div className="mt-6 flex justify-end shrink-0 print:hidden">
              <button
                onClick={() => setSelectedFir(null)}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-ink-50 border border-white/10 rounded-xl transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedCase && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink-950/80 backdrop-blur-sm animate-in fade-in">
          <div className="bg-ink-900 border border-white/10 p-6 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col relative shadow-2xl">
            <h3 className="text-xl font-serif text-gold-400 mb-4 shrink-0">Case Details - {selectedCase.id.slice(0, 8)}...</h3>
            <div className="flex-1 overflow-auto space-y-4 pr-2">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="glass p-3 rounded-lg">
                  <span className="text-ink-400 block text-xs mb-1">Status</span>
                  <span className="text-ink-50">{selectedCase.status}</span>
                </div>
                <div className="glass p-3 rounded-lg">
                  <span className="text-ink-400 block text-xs mb-1">Court Level</span>
                  <span className="text-ink-50">{selectedCase.court_level || 'district'}</span>
                </div>
              </div>
              <div className="glass p-4 rounded-xl">
                <span className="text-ink-400 block text-xs mb-2">Case Facts / Question</span>
                <p className="text-sm text-ink-200 whitespace-pre-wrap">{selectedCase.question}</p>
              </div>

              {/* Court Panels */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {selectedCase.lawyer_output && (
                  <CourtPanel role="petitioner" data={selectedCase.lawyer_output} />
                )}
                {selectedCase.opponent_output && (
                  <CourtPanel role="opponent" data={selectedCase.opponent_output} />
                )}
                {selectedCase.cross_examination_output && (
                  <CourtPanel role="cross_examination" data={selectedCase.cross_examination_output} />
                )}
                {selectedCase.rebuttal_output && (
                  <CourtPanel role="rebuttal" data={selectedCase.rebuttal_output} />
                )}
              </div>
              
              {selectedCase.judge_output && (
                <div className="mt-4 space-y-4">
                  {/* Judgment Box */}
                  <div className="relative overflow-hidden rounded-2xl border border-gold-400/30 glass p-5">
                    <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-gold-400/20 to-transparent pointer-events-none" />
                    <div className="relative">
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-9 h-9 rounded-xl bg-gold-400/20 grid place-items-center border border-gold-400/30 text-gold-200">
                           <Gavel className="w-4 h-4" />
                        </div>
                        <h3 className="font-serif text-lg">Judgment · {selectedCase.court_level || 'district'} court</h3>
                      </div>
                      <p className="text-sm text-ink-100 leading-relaxed mb-3">{selectedCase.judge_output.final_judgment}</p>
                      {selectedCase.judge_output.liability_assessment && (
                        <p className="text-sm text-ink-300 mb-3">
                          <span className="text-gold-300 font-medium">Liability: </span>
                          {selectedCase.judge_output.liability_assessment}
                        </p>
                      )}
                      {selectedCase.judge_output.applicable_sections?.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {selectedCase.judge_output.applicable_sections.map((s, i) => (
                            <Badge key={i} tone="gold">{s}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Judicial Reasoning */}
                  <div className="border border-white/10 rounded-2xl p-5 bg-ink-900/50">
                    <h3 className="font-serif text-lg mb-1 text-ink-50">Judicial reasoning</h3>
                    <p className="text-xs text-ink-400 mb-4">Court's analysis, broken out</p>
                    <div className="grid md:grid-cols-2 gap-4 text-sm">
                      {[
                        ['Court observations',     selectedCase.judge_output.court_observations],
                        ['Facts established',      selectedCase.judge_output.facts_established],
                        ['Disputed facts',         selectedCase.judge_output.disputed_facts],
                        ['Evidence evaluation',    selectedCase.judge_output.evidence_evaluation],
                        ['Procedural findings',    selectedCase.judge_output.procedural_findings],
                        ['Recommended next steps', selectedCase.judge_output.recommended_next_steps],
                      ].map(([title, items]) => (
                        <div key={title} className="glass-light rounded-xl p-4">
                          <div className="font-medium text-ink-100 mb-2">{title}</div>
                          {items?.length ? (
                            <ul className="space-y-1.5 text-ink-200">
                              {items.map((it, i) => (
                                <li key={i} className="flex gap-2"><span className="text-gold-400">·</span><span>{it}</span></li>
                              ))}
                            </ul>
                          ) : <p className="text-xs text-ink-400 italic">None recorded.</p>}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}


            </div>
            <div className="mt-6 flex justify-end shrink-0">
              <button
                onClick={() => setSelectedCase(null)}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-ink-50 border border-white/10 rounded-xl transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
