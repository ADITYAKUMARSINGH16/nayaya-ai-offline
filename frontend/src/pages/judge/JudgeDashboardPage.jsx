import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Gavel, Check, X, FileText, Clock, Landmark } from 'lucide-react'

import Card, { CardHeader } from '@/components/ui/Card'
import Spinner from '@/components/ui/Spinner'
import CaseModal from '@/components/CaseModal'
import { api } from '@/api/client'

export default function JudgeDashboardPage() {
  const [allCases, setAllCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedCase, setSelectedCase] = useState(null)
  const [overrideVerdict, setOverrideVerdict] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [activeTab, setActiveTab] = useState('pending') // 'pending' or 'history'
  const [similarCases, setSimilarCases] = useState(null)
  const [loadingSimilar, setLoadingSimilar] = useState(false)
  const [activeCaseModal, setActiveCaseModal] = useState(null)

  const renderOutput = (data, fallback = 'No data found.') => {
    if (!data) return fallback;
    return Object.entries(data).map(([key, value]) => {
      if (!value || (Array.isArray(value) && value.length === 0)) return null;
      return (
        <div key={key}>
          <h4 className="font-medium text-gold-300 mb-1 capitalize">{key.replace(/_/g, ' ')}</h4>
          {Array.isArray(value) ? (
            <ul className="list-disc list-inside space-y-1">
              {value.map((v, i) => <li key={i}>{v}</li>)}
            </ul>
          ) : (
            <p>{value}</p>
          )}
        </div>
      )
    })
  }

  useEffect(() => {
    const fetchCases = async () => {
      try {
        const data = await api.judgeGetCases()
        setAllCases(data)
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchCases()
  }, [])

  useEffect(() => {
    if (!selectedCase) {
      setSimilarCases(null)
      return
    }
    const fetchSimilar = async () => {
      setLoadingSimilar(true)
      try {
        const data = await api.judgeGetSimilarCases(selectedCase.id)
        setSimilarCases(data)
      } catch (err) {
        console.error(err)
      } finally {
        setLoadingSimilar(false)
      }
    }
    fetchSimilar()
  }, [selectedCase])

  const pendingCases = allCases.filter(c => c.status === 'trial' || c.status === 'awaiting_verdict')
  const historyCases = allCases.filter(c => c.status === 'closed')

  const displayedCases = activeTab === 'pending' ? pendingCases : historyCases

  const handleVerdict = async (status) => {
    if (!selectedCase) return
    setSubmitting(true)
    try {
      const payload = {
        verdict: {
          final_judgment: status === 'modified' ? overrideVerdict : selectedCase.judgement_output?.final_judgment || ''
        },
        status
      }
      const updatedCase = await api.judgeSubmitVerdict(selectedCase.id, payload)
      // Update in list
      setAllCases(allCases.map(c => c.id === selectedCase.id ? { ...c, ...updatedCase } : c))
      setSelectedCase(null)
    } catch (err) {
      console.error(err)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <Spinner label="Loading cases..." className="mt-20 mx-auto" />

  return (
    <div className="max-w-[90rem] mx-auto flex flex-col lg:flex-row gap-6 items-start">
      {/* List of cases */}
      <div className="lg:w-80 shrink-0 space-y-4">
        <div className="flex gap-4 mb-4 border-b border-white/10 pb-2">
          <button
            onClick={() => { setActiveTab('pending'); setSelectedCase(null) }}
            className={`font-serif text-xl transition ${activeTab === 'pending' ? 'text-gold-300' : 'text-ink-400 hover:text-white'}`}
          >
            Pending Verdicts
          </button>
          <button
            onClick={() => { setActiveTab('history'); setSelectedCase(null) }}
            className={`font-serif text-xl transition ${activeTab === 'history' ? 'text-gold-300' : 'text-ink-400 hover:text-white'}`}
          >
            History
          </button>
        </div>

        {displayedCases.length === 0 ? (
          <p className="text-ink-400">No cases found in this category.</p>
        ) : (
          displayedCases.map(c => (
            <div 
              key={c.id} 
              onClick={() => setSelectedCase(c)}
              className={`p-4 rounded-xl cursor-pointer transition border ${selectedCase?.id === c.id ? 'bg-gold-500/10 border-gold-500/30' : 'glass hover:border-white/20 border-white/5'}`}
            >
              <div className="font-medium truncate">{c.id}</div>
              <div className="text-xs text-ink-400 mt-1 truncate">{c.question}</div>
              {activeTab === 'history' && (
                <div className="mt-2 flex items-center gap-1 text-xs text-gold-300">
                  <Clock className="w-3 h-3" />
                  <span className="capitalize">{c.human_verdict_status}</span>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Case Details & Action */}
      <div className="flex-1 min-w-0">
        {selectedCase ? (
          <motion.div initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
            <Card>
              <CardHeader icon={FileText} title="Case Facts" />
              <div className="p-4 text-sm leading-relaxed">{selectedCase.question}</div>
            </Card>

            {selectedCase.lawyer_output && (
              <Card>
                <CardHeader icon={FileText} title="Petitioner Argument" />
                <div className="p-4 text-sm leading-relaxed space-y-4">
                  {renderOutput(selectedCase.lawyer_output)}
                </div>
              </Card>
            )}

            {selectedCase.opponent_output && (
              <Card>
                <CardHeader icon={FileText} title="Defence Argument" />
                <div className="p-4 text-sm leading-relaxed space-y-4">
                  {renderOutput(selectedCase.opponent_output)}
                </div>
              </Card>
            )}

            {selectedCase.rebuttal_output && (
              <Card>
                <CardHeader icon={FileText} title="Petitioner Rebuttal" />
                <div className="p-4 text-sm leading-relaxed space-y-4">
                  {renderOutput(selectedCase.rebuttal_output)}
                </div>
              </Card>
            )}

            <Card>
              <CardHeader icon={Gavel} title="AI Recommended Judgement" />
              <div className="p-4 text-sm leading-relaxed space-y-4">
                {selectedCase.judgement_output ? renderOutput(selectedCase.judgement_output) : 'No judgment found.'}
              </div>
            </Card>

            {selectedCase.status === 'closed' ? (
              <Card>
                <CardHeader icon={Gavel} title="Final Judgment (Judge)" />
                <div className="p-4 text-sm leading-relaxed space-y-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`px-2 py-1 rounded text-xs uppercase tracking-wider font-bold ${
                      selectedCase.human_verdict_status === 'approved' ? 'bg-green-500/20 text-green-300' :
                      selectedCase.human_verdict_status === 'rejected' ? 'bg-red-500/20 text-red-300' :
                      'bg-gold-500/20 text-gold-300'
                    }`}>
                      {selectedCase.human_verdict_status}
                    </span>
                  </div>
                  {selectedCase.human_verdict?.final_judgment ? (
                    <p>{selectedCase.human_verdict.final_judgment}</p>
                  ) : (
                    <p className="text-ink-400 italic">No additional override details provided.</p>
                  )}
                </div>
              </Card>
            ) : (
              <Card>
                <CardHeader icon={Gavel} title="Judge Action" />
                <div className="p-4 space-y-4">
                  <textarea
                    value={overrideVerdict}
                    onChange={(e) => setOverrideVerdict(e.target.value)}
                    className="w-full h-24 rounded-xl bg-ink-900 border border-white/10 p-3 text-sm focus:border-gold-500/50 outline-none"
                    placeholder="Leave blank to approve AI verdict, or enter override details here..."
                  />
                  <div className="flex gap-3">
                    <button 
                      onClick={() => handleVerdict('approved')}
                      disabled={submitting}
                      className="flex-1 flex justify-center items-center gap-2 py-2 rounded-xl bg-green-500/20 text-green-300 hover:bg-green-500/30 transition disabled:opacity-50"
                    >
                      <Check className="w-4 h-4" /> Approve
                    </button>
                    <button 
                      onClick={() => handleVerdict(overrideVerdict.trim() ? 'modified' : 'rejected')}
                      disabled={submitting}
                      className="flex-1 flex justify-center items-center gap-2 py-2 rounded-xl bg-red-500/20 text-red-300 hover:bg-red-500/30 transition disabled:opacity-50"
                    >
                      <X className="w-4 h-4" /> {overrideVerdict.trim() ? 'Override' : 'Reject'}
                    </button>
                  </div>
                </div>
              </Card>
            )}
          </motion.div>
        ) : (
          <div className="h-full flex items-center justify-center text-ink-500">
            Select a case to review.
          </div>
        )}
      </div>

      {/* Similar Cases Sidebar */}
      {selectedCase && (
        <div className="lg:w-[340px] shrink-0 sticky top-6">
          <Card className="overflow-hidden flex flex-col max-h-[calc(100vh-6rem)]">
            <CardHeader title="Similar Cases" subtitle="Historical precedents" />
            <div className="flex-1 overflow-y-auto space-y-3 pr-1 pb-4">
              {loadingSimilar ? (
                <div className="flex justify-center p-4"><Spinner /></div>
              ) : !similarCases?.length ? (
                <p className="text-sm text-ink-400">
                  Similar historical cases will appear here.
                </p>
              ) : (
                similarCases.map((sc, i) => (
                  <div key={i} className="p-3 rounded-xl bg-ink-950/50 border border-white/5 space-y-2">
                    <div className="flex justify-between items-start gap-2">
                      <h4 className="font-medium text-gold-100 text-sm">{sc.title}</h4>
                      <span className="text-[10px] text-ink-400 shrink-0 bg-ink-900 px-1.5 py-0.5 rounded-md">
                        {sc.year}
                      </span>
                    </div>
                    {sc.disposition && (
                      <div className="text-xs">
                        <span className="text-gold-500 font-medium">Verdict: </span>
                        <span className="text-ink-200">{sc.disposition}</span>
                      </div>
                    )}
                    <p className="text-xs text-ink-400 line-clamp-3">{sc.snippet}</p>
                    <button
                      onClick={() => setActiveCaseModal(sc)}
                      className="text-xs font-medium text-gold-400 hover:text-gold-300 underline underline-offset-2 mt-1 inline-block"
                    >
                      View full case
                    </button>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      )}

      {/* Case Modal */}
      <CaseModal 
        caseData={activeCaseModal} 
        onClose={() => setActiveCaseModal(null)} 
      />
    </div>
  )
}
