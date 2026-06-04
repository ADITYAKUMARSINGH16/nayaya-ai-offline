import { useEffect, useState } from 'react'
import { History, Search, Gavel } from 'lucide-react'

import Card, { CardHeader } from '@/components/ui/Card'
import EmptyState from '@/components/ui/EmptyState'
import Badge from '@/components/ui/Badge'
import Input from '@/components/ui/Input'
import { formatDate } from '@/lib/utils'
import { api } from '@/api/client'
import { useAuth } from '@/context/AuthContext'
import { useCase } from '@/context/CaseContext'
import { useNavigate } from 'react-router-dom'
import CourtPanel from '@/components/CourtPanel'

export default function CaseHistoryPage() {
  const { user } = useAuth()
  const { updateCase } = useCase()
  const navigate = useNavigate()
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [selectedCase, setSelectedCase] = useState(null)

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
    setSelectedCase(c)
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
              
              {selectedCase.judgement_output && (
                <div className="mt-4 space-y-4">
                  {/* Judgment Box */}
                  <div className="relative overflow-hidden rounded-2xl border border-gold-400/30 glass p-5">
                    <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-gold-400/20 to-transparent pointer-events-none" />
                    <div className="relative">
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-9 h-9 rounded-xl bg-gold-400/20 grid place-items-center border border-gold-400/30 text-gold-200">
                           <Gavel className="w-4 h-4" />
                        </div>
                        <h3 className="font-serif text-lg">AI Recommended Judgement · {selectedCase.court_level || 'district'} court</h3>
                      </div>
                      <p className="text-sm text-ink-100 leading-relaxed mb-3">{selectedCase.judgement_output.final_judgment}</p>
                      {selectedCase.judgement_output.liability_assessment && (
                        <p className="text-sm text-ink-300 mb-3">
                          <span className="text-gold-300 font-medium">Liability: </span>
                          {selectedCase.judgement_output.liability_assessment}
                        </p>
                      )}
                      {selectedCase.judgement_output.applicable_sections?.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {selectedCase.judgement_output.applicable_sections.map((s, i) => (
                            <Badge key={i} tone="gold">{s}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Judicial Reasoning */}
                  <div className="border border-white/10 rounded-2xl p-5 bg-ink-900/50">
                    <h3 className="font-serif text-lg mb-1 text-ink-50">AI Judicial reasoning</h3>
                    <p className="text-xs text-ink-400 mb-4">Court's analysis, broken out</p>
                    <div className="grid md:grid-cols-2 gap-4 text-sm">
                      {[
                        ['Court observations',     selectedCase.judgement_output.court_observations],
                        ['Facts established',      selectedCase.judgement_output.facts_established],
                        ['Disputed facts',         selectedCase.judgement_output.disputed_facts],
                        ['Evidence evaluation',    selectedCase.judgement_output.evidence_evaluation],
                        ['Procedural findings',    selectedCase.judgement_output.procedural_findings],
                        ['Recommended next steps', selectedCase.judgement_output.recommended_next_steps],
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

              {selectedCase.human_verdict_status && (
                <div className="mt-4 space-y-4">
                  <div className="relative overflow-hidden rounded-2xl border border-gold-400/30 glass p-5">
                    <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-gold-400/20 to-transparent pointer-events-none" />
                    <div className="relative">
                      <div className="flex items-center gap-2 mb-3">
                        <div className="w-9 h-9 rounded-xl bg-gold-400/20 grid place-items-center border border-gold-400/30 text-gold-200">
                           <Gavel className="w-4 h-4" />
                        </div>
                        <h3 className="font-serif text-lg">Final Judgment (Judge)</h3>
                      </div>
                      <div className="flex items-center gap-2 mb-3">
                        <span className={`px-2 py-1 rounded text-xs uppercase tracking-wider font-bold ${
                          selectedCase.human_verdict_status === 'approved' ? 'bg-green-500/20 text-green-300' :
                          selectedCase.human_verdict_status === 'rejected' ? 'bg-red-500/20 text-red-300' :
                          'bg-gold-500/20 text-gold-300'
                        }`}>
                          {selectedCase.human_verdict_status}
                        </span>
                      </div>
                      {selectedCase.human_verdict?.final_judgment ? (
                        <p className="text-sm text-ink-100 leading-relaxed">{selectedCase.human_verdict.final_judgment}</p>
                      ) : (
                        <p className="text-sm text-ink-400 italic">No additional override details provided.</p>
                      )}
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
