import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Gavel, Check, X, FileText } from 'lucide-react'

import Card, { CardHeader } from '@/components/ui/Card'
import Spinner from '@/components/ui/Spinner'
import { api } from '@/api/client'

export default function JudgeDashboardPage() {
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedCase, setSelectedCase] = useState(null)
  const [overrideVerdict, setOverrideVerdict] = useState('')
  const [submitting, setSubmitting] = useState(false)

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
        // Filter to only show cases that are in trial/awaiting verdict
        setCases(data.filter(c => c.status === 'trial' || c.status === 'awaiting_verdict'))
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchCases()
  }, [])

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
      await api.judgeSubmitVerdict(selectedCase.id, payload)
      // Remove from list
      setCases(cases.filter(c => c.id !== selectedCase.id))
      setSelectedCase(null)
    } catch (err) {
      console.error(err)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <Spinner label="Loading cases..." className="mt-20 mx-auto" />

  return (
    <div className="max-w-6xl mx-auto flex flex-col md:flex-row gap-6">
      {/* List of pending cases */}
      <div className="md:w-1/3 space-y-4">
        <h2 className="font-serif text-2xl mb-4">Pending Verdicts</h2>
        {cases.length === 0 ? (
          <p className="text-ink-400">No cases awaiting verdict.</p>
        ) : (
          cases.map(c => (
            <div 
              key={c.id} 
              onClick={() => setSelectedCase(c)}
              className={`p-4 rounded-xl cursor-pointer transition border ${selectedCase?.id === c.id ? 'bg-gold-500/10 border-gold-500/30' : 'glass hover:border-white/20 border-white/5'}`}
            >
              <div className="font-medium truncate">{c.id}</div>
              <div className="text-xs text-ink-400 mt-1 truncate">{c.question}</div>
            </div>
          ))
        )}
      </div>

      {/* Case Details & Action */}
      <div className="md:w-2/3">
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
              <CardHeader icon={Gavel} title="AI Recommended Verdict" />
              <div className="p-4 text-sm leading-relaxed space-y-4">
                {selectedCase.judgement_output ? renderOutput(selectedCase.judgement_output) : 'No judgment found.'}
              </div>
            </Card>

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
          </motion.div>
        ) : (
          <div className="h-full flex items-center justify-center text-ink-500">
            Select a case to review.
          </div>
        )}
      </div>
    </div>
  )
}
