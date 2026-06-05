import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Scale, FileText, ChevronRight, Gavel, CheckCircle2, Clock, Landmark } from 'lucide-react'

import { api } from '@/api/client'
import Card, { CardHeader } from '@/components/ui/Card'
import Spinner from '@/components/ui/Spinner'
import { useAuth } from '@/context/AuthContext'
import ConversationsSidebar from '@/components/ConversationsSidebar'
import Badge from '@/components/ui/Badge'
import CitationCard from '@/components/CitationCard'
import CitationModal from '@/components/CitationModal'
import SimilarCaseCard from '@/components/SimilarCaseCard'
import SimilarCaseModal from '@/components/SimilarCaseModal'
import Disclaimer from '@/components/Disclaimer'

export default function AIJudgePage() {
  const { user } = useAuth()
  const [facts, setFacts] = useState('')
  const [loading, setLoading] = useState(false)
  const [analysis, setAnalysis] = useState(null)
  const [error, setError] = useState('')
  const [sessionId, setSessionId] = useState(null)
  const [activeCitation, setActiveCitation] = useState(null)
  const [activeSimilarCase, setActiveSimilarCase] = useState(null)

  const handleSelectHistory = async (id) => {
    setSessionId(id)
    try {
      const res = await api.getConversation(id)
      const messages = res.messages || []
      const userMsg = messages.find(m => m.role === 'user')
      const assistantMsg = messages.find(m => m.role === 'assistant')
      
      if (userMsg) setFacts(userMsg.message)
      if (assistantMsg) {
        try {
          setAnalysis(JSON.parse(assistantMsg.message))
        } catch (e) {
          console.error("Failed to parse history JSON", e)
        }
      }
    } catch (err) {
      console.error("Failed to load history", err)
    }
  }

  const handleNew = () => {
    setSessionId(null)
    setFacts('')
    setAnalysis(null)
    setError('')
  }

  const handleAnalyze = async () => {
    if (!facts.trim()) return
    setLoading(true)
    setError('')
    setAnalysis(null)
    try {
      const res = await api.judgeAnalyze({ case_facts: facts })
      setAnalysis(res)
    } catch (err) {
      setError(err.message || 'Failed to analyze case')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex gap-4 h-[calc(100vh-9rem)]">
      <ConversationsSidebar
        activeId={sessionId}
        onSelect={handleSelectHistory}
        onNew={handleNew}
        category="judge"
      />

      <div className="grid lg:grid-cols-[1fr_340px] gap-4 flex-1 min-w-0">
        <div className="flex-1 min-w-0 overflow-y-auto pr-1 space-y-6 pb-8">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <h1 className="font-serif text-3xl">AI Judge Preliminary Analysis</h1>
            <p className="text-ink-400 mt-1">Review cases instantly to formulate initial legal questions and assess admissibility.</p>
          </motion.div>

          <Card className="p-6 space-y-4">
            <label className="block text-sm font-medium text-gold-300">Case Facts Summary</label>
            <textarea
              value={facts}
              onChange={e => setFacts(e.target.value)}
              placeholder="Enter the known case facts here for preliminary evaluation..."
              className="w-full h-40 rounded-xl bg-ink-950/50 border border-white/10 p-4 focus:border-gold-500/50 outline-none text-sm resize-none transition"
            />
            <div className="flex items-center justify-between">
              <div className="text-xs text-ink-500 flex items-center gap-2">
                <FileText className="w-4 h-4" /> BNS / BNSS / BSA 2023 Analysis
              </div>
              <button
                onClick={handleAnalyze}
                disabled={!facts.trim() || loading}
                className="px-6 py-2.5 rounded-xl bg-gold-500 text-ink-950 font-medium hover:bg-gold-400 transition flex items-center gap-2 disabled:opacity-50"
              >
                {loading ? <Spinner className="w-4 h-4 border-ink-950" /> : 'Evaluate Case'}
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            {error && <div className="text-red-400 text-sm">{error}</div>}
          </Card>

          <AnimatePresence>
            {analysis && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="grid grid-cols-1 gap-6"
              >
                <Card className="p-6">
                  <h3 className="font-serif text-xl mb-4 text-gold-300 flex items-center gap-2">
                    <Gavel className="w-5 h-5" /> Key Legal Questions
                  </h3>
                  <ul className="space-y-3">
                    {analysis.legal_questions.map((item, i) => (
                      <li key={i} className="flex gap-3 text-sm text-ink-200">
                        <CheckCircle2 className="w-5 h-5 text-gold-500 shrink-0" />
                        <span>{item}</span>
                      </li>
                    ))}
                    {analysis.legal_questions.length === 0 && <span className="text-ink-500">None identified.</span>}
                  </ul>
                </Card>

                <Card className="p-6">
                  <h3 className="font-serif text-xl mb-4 text-gold-300 flex items-center gap-2">
                    <Gavel className="w-5 h-5" /> Admissibility Issues
                  </h3>
                  <ul className="space-y-3">
                    {analysis.admissibility_issues.map((item, i) => (
                      <li key={i} className="flex gap-3 text-sm text-ink-200">
                        <CheckCircle2 className="w-5 h-5 text-red-400 shrink-0" />
                        <span>{item}</span>
                      </li>
                    ))}
                    {analysis.admissibility_issues.length === 0 && <span className="text-ink-500">None identified.</span>}
                  </ul>
                </Card>

                <Card className="p-6">
                  <h3 className="font-serif text-xl mb-4 text-gold-300 flex items-center gap-2">
                    <Gavel className="w-5 h-5" /> Potential Liabilities & Findings
                  </h3>
                  <ul className="space-y-3">
                    {analysis.potential_liabilities.map((item, i) => (
                      <li key={i} className="flex gap-3 text-sm text-ink-200">
                        <CheckCircle2 className="w-5 h-5 text-gold-500 shrink-0" />
                        <span>{item}</span>
                      </li>
                    ))}
                    {analysis.potential_liabilities.length === 0 && <span className="text-ink-500">None identified.</span>}
                  </ul>
                </Card>

              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="flex flex-col gap-4 h-full overflow-y-auto pr-1">
          <Card className="flex flex-col shrink-0">
            <CardHeader title="Citations" subtitle="Bare acts retrieved" />
            <div className="p-4 space-y-3">
              {!analysis?.citations?.length ? (
                <p className="text-sm text-ink-400">
                  Citations from the legal database will appear here once you analyze a case.
                </p>
              ) : (
                analysis.citations.map((c, i) => (
                  <CitationCard key={i} citation={c} onClick={setActiveCitation} />
                ))
              )}
            </div>
          </Card>

          <Card className="flex flex-col shrink-0">
            <CardHeader title="Similar Case History" subtitle="Retrieved from Supreme Court records" />
            <div className="p-4 space-y-3">
              {!analysis?.similar_cases?.length ? (
                <p className="text-sm text-ink-400">
                  Similar case history will appear here once you analyze a case.
                </p>
              ) : (
                analysis.similar_cases.map((c, i) => (
                  <SimilarCaseCard key={i} similarCase={c} onClick={setActiveSimilarCase} />
                ))
              )}
            </div>
          </Card>

          <Disclaimer className="mt-2 shrink-0" />
        </div>
      </div>

      <CitationModal
        citation={activeCitation}
        onClose={() => setActiveCitation(null)}
      />
      <SimilarCaseModal
        similarCase={activeSimilarCase}
        onClose={() => setActiveSimilarCase(null)}
      />
    </div>
  )
}
