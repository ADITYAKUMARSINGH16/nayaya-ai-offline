import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Scale, FileText, ChevronRight, Gavel, CheckCircle2, Clock } from 'lucide-react'

import { api } from '@/api/client'
import Card from '@/components/ui/Card'
import Spinner from '@/components/ui/Spinner'
import { useAuth } from '@/context/AuthContext'
import ConversationsSidebar from '@/components/ConversationsSidebar'

export default function AIJudgePage() {
  const { user } = useAuth()
  const [facts, setFacts] = useState('')
  const [loading, setLoading] = useState(false)
  const [analysis, setAnalysis] = useState(null)
  const [error, setError] = useState('')
  const [sessionId, setSessionId] = useState(null)

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
      // We pass case_facts under the hood for InvestigationRequest schema
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

      <div className="flex-1 min-w-0 overflow-y-auto pr-1 space-y-6 pb-8">
        <div className="flex items-center gap-4 mb-8">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-gold-400 to-gold-600 grid place-items-center shadow-glow">
            <Scale className="w-6 h-6 text-ink-950" />
          </div>
          <div>
            <h1 className="font-serif text-3xl">AI Judge Analysis</h1>
            <p className="text-ink-400 mt-1">Get a preliminary, neutral judicial evaluation of case facts.</p>
          </div>
        </div>

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
            
            {analysis.citations?.length > 0 && (
              <Card className="p-6">
                <h3 className="font-serif text-xl mb-4 text-gold-300">Citations (BNS/BNSS/BSA)</h3>
                <div className="space-y-3">
                  {analysis.citations.map((cit, i) => (
                    <div key={i} className="p-3 rounded-xl bg-ink-900 border border-white/5 text-sm">
                      <div className="font-medium text-gold-200">{cit.act} {cit.section_number}: {cit.section_title}</div>
                      <div className="text-ink-400 mt-1">{cit.snippet}</div>
                      {cit.verified && (
                        <div className="mt-2 text-xs text-green-400">✓ Verified: {cit.verify_note}</div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </motion.div>
        )}
      </AnimatePresence>
      </div>
    </div>
  )
}
