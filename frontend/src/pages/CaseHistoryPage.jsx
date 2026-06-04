import { useEffect, useState } from 'react'
import { History, Search } from 'lucide-react'

import Card, { CardHeader } from '@/components/ui/Card'
import EmptyState from '@/components/ui/EmptyState'
import Badge from '@/components/ui/Badge'
import Input from '@/components/ui/Input'
import { formatDate } from '@/lib/utils'
import { api } from '@/api/client'
import { useAuth } from '@/context/AuthContext'
import { useCase } from '@/context/CaseContext'
import { useNavigate } from 'react-router-dom'

export default function CaseHistoryPage() {
  const { user } = useAuth()
  const { updateCase } = useCase()
  const navigate = useNavigate()
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!user?.id) {
      setLoading(false)
      return
    }
    ;(async () => {
      try {
        const data = await api.listCases()
        setCases(data || [])
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    })()
  }, [user])

  const filtered = cases.filter((c) =>
    !q.trim() || (c.question || '').toLowerCase().includes(q.toLowerCase()),
  )

  const handleViewCase = (c) => {
    updateCase({
      caseId: c.id,
      caseFacts: c.question || '',
      lastCourtLevel: c.court_level || 'district',
    })
    navigate('/app/trial')
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          icon={History}
          title="Case History"
          subtitle="Every trial you run is saved here for review and appeal."
          action={
            <div className="relative">
              <Search className="w-4 h-4 text-ink-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <Input
                placeholder="Search by facts…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="pl-9 w-64"
              />
            </div>
          }
        />

        {loading ? (
          <p className="text-sm text-ink-400">Loading…</p>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={History}
            title="No cases yet"
            description="Run your first trial — it will appear here."
          />
        ) : (
          <div className="space-y-3">
            {filtered.map((c) => (
              <div
                key={c.id}
                className="glass-light rounded-xl p-4 border border-white/5 hover:border-gold-400/30 transition"
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2">
                    <Badge tone="gold">{c.court_level || 'district'}</Badge>
                    <Badge tone={c.status === 'judged' ? 'green' : 'slate'}>
                      {c.status || 'open'}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-xs text-ink-400">{formatDate(c.created_at)}</span>
                    <button
                      onClick={() => handleViewCase(c)}
                      className="px-3 py-1.5 text-xs font-medium bg-gold-500/10 hover:bg-gold-500/20 text-gold-300 border border-gold-500/20 rounded-lg transition"
                    >
                      View Case
                    </button>
                  </div>
                </div>
                <p className="text-sm text-ink-200 line-clamp-3 whitespace-pre-wrap">
                  {(c.question || '').slice(0, 320)}
                </p>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
