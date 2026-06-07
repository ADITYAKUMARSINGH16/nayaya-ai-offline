import { useState } from 'react'
import { motion } from 'framer-motion'
import { AlertCircle, Scale, Shield, Sparkles, CheckCircle, Lightbulb, Clock } from 'lucide-react'

import Card, { CardHeader } from '@/components/ui/Card'
import Spinner from '@/components/ui/Spinner'
import { api } from '@/api/client'
import ConversationsSidebar from '@/components/ConversationsSidebar'
import Badge from '@/components/ui/Badge'
import CitationCard from '@/components/CitationCard'
import CitationModal from '@/components/CitationModal'
import SimilarCaseCard from '@/components/SimilarCaseCard'
import SimilarCaseModal from '@/components/SimilarCaseModal'
import Disclaimer from '@/components/Disclaimer'

export default function AILawyerPage() {
  const [caseFacts, setCaseFacts] = useState('')
  const [loading, setLoading] = useState(false)
  const [analysis, setAnalysis] = useState(null)
  const [error, setError] = useState('')
  const [sessionId, setSessionId] = useState(null)
  const [activeCitation, setActiveCitation] = useState(null)
  const [similarCases, setSimilarCases] = useState([])
  const [activeSimilarCase, setActiveSimilarCase] = useState(null)

  const handleSelectHistory = async (id) => {
    setSessionId(id)
    try {
      const res = await api.getConversation(id)
      const messages = res.messages || []
      const userMsg = messages.find(m => m.role === 'user')
      const assistantMsg = messages.find(m => m.role === 'assistant')

      if (userMsg) setCaseFacts(userMsg.message)
      if (assistantMsg) {
        try {
          const parsed = JSON.parse(assistantMsg.message)
          setAnalysis(parsed)
          // Similar cases live in a separate state slot on this page
          // (lawyer page renders them outside `analysis`), so rehydrate
          // it explicitly from the persisted payload.
          setSimilarCases(parsed.similar_cases || [])
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
    setCaseFacts('')
    setAnalysis(null)
    setSimilarCases([])
    setError('')
  }

  const handleAnalyze = async () => {
    if (!caseFacts.trim()) return
    setLoading(true)
    setError('')
    setAnalysis(null)
    setSimilarCases([])
    try {
      const data = await api.lawyerAnalyze({ caseFacts })
      setAnalysis(data)
      // Backend now returns similar_cases as part of the analyze response
      // (and persists them in chat_history), so just lift them into state.
      // No more separate /judge/case-laws/search call from this page.
      setSimilarCases(data.similar_cases || [])
    } catch (err) {
      console.error("Analyze error:", err)
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
        category="lawyer"
      />

      <div className="grid lg:grid-cols-[1fr_340px] gap-4 flex-1 min-w-0">
        <div className="flex-1 min-w-0 overflow-y-auto pr-1 space-y-6 pb-8">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <h1 className="font-serif text-3xl">AI Lawyer Analysis</h1>
            <p className="text-ink-400 mt-1">Generate strategic analysis, identify weaknesses, and prepare for trial.</p>
          </motion.div>

      <Card>
        <CardHeader icon={Scale} title="Case Facts" />
        <div className="p-4 space-y-4">
          <textarea
            value={caseFacts}
            onChange={(e) => setCaseFacts(e.target.value)}
            className="w-full h-32 rounded-xl bg-ink-900 border border-white/10 p-3 text-sm focus:border-gold-500/50 focus:ring-1 focus:ring-gold-500/50 outline-none"
            placeholder="Paste case facts, FIR details, or investigation reports here..."
          />
          <button
            onClick={handleAnalyze}
            disabled={loading || !caseFacts.trim()}
            className="w-full sm:w-auto px-6 py-2 rounded-xl bg-gold-500 text-ink-950 font-medium disabled:opacity-50 hover:bg-gold-400 transition"
          >
            {loading ? <Spinner className="w-5 h-5 mx-auto" /> : 'Analyze Case'}
          </button>
          {error && <div className="text-red-400 text-sm mt-2">{error}</div>}
        </div>
      </Card>

      {analysis && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
          <Card>
            <CardHeader icon={Lightbulb} title="Recommended Strategy" />
            <div className="p-4 text-sm leading-relaxed">{analysis.strategy}</div>
          </Card>
          
          <div className="grid sm:grid-cols-2 gap-4">
            <Card>
              <CardHeader icon={CheckCircle} title="Strengths" />
              <ul className="p-4 space-y-2 text-sm">
                {analysis.strengths.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-gold-400">•</span> <span>{s}</span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <CardHeader icon={AlertCircle} title="Weaknesses" />
              <ul className="p-4 space-y-2 text-sm">
                {analysis.weaknesses.map((w, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-red-400">•</span> <span>{w}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <Card>
            <CardHeader icon={Shield} title="Evidence Needed" />
            <ul className="p-4 space-y-2 text-sm">
              {analysis.evidence_needed.map((e, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-blue-400">•</span> <span>{e}</span>
                </li>
              ))}
            </ul>
          </Card>
        </motion.div>
      )}
      </div>

        {/* Sidebar Panel */}
        <div className="flex flex-col gap-4 h-full overflow-y-auto pr-1">
          <Card className="flex flex-col shrink-0">
            <CardHeader title="Citations" subtitle="BNS / BNSS / BSA sections retrieved by the verifier" />
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
              {!similarCases?.length ? (
                <p className="text-sm text-ink-400">
                  Similar case history will appear here once you analyze a case.
                </p>
              ) : (
                similarCases.map((c, i) => (
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
