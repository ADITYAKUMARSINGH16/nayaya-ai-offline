import { useEffect, useState } from 'react'
import { Gavel, Sparkles, BookOpenCheck, Building2, Printer, History as HistoryIcon, Clock } from 'lucide-react'
import { motion } from 'framer-motion'
import toast from 'react-hot-toast'

import Card, { CardHeader } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Input'
import Badge from '@/components/ui/Badge'
import EmptyState from '@/components/ui/EmptyState'
import CourtPanel from '@/components/CourtPanel'
import CitationCard from '@/components/CitationCard'
import CitationModal from '@/components/CitationModal'
import JudgmentCard from '@/components/JudgmentCard'
import Disclaimer from '@/components/Disclaimer'
import { api } from '@/api/client'
import { useAuth } from '@/context/AuthContext'
import { useCase } from '@/context/CaseContext'
import ConversationsSidebar from '@/components/ConversationsSidebar'

const COURTS = [
  { id: 'district', label: 'District Court' },
  { id: 'high',     label: 'High Court' },
  { id: 'supreme',  label: 'Supreme Court' },
]

export default function TrialPage() {
  const { user } = useAuth()
  const { currentCase, updateCase } = useCase()
  // Pre-fill from the shared case workspace so the user never re-pastes.
  const [facts, setFacts] = useState(currentCase.caseFacts || '')
  const [court, setCourt] = useState(currentCase.lastCourtLevel || 'district')
  const [rounds, setRounds] = useState(1)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [appealChain, setAppealChain] = useState([])
  const [activeCitation, setActiveCitation] = useState(null)
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
          const data = JSON.parse(assistantMsg.message)
          setCourt(data.court_level || 'district')
          setResult({
            ...data,
            citations: data.citations || [],
            case_id: messages[0]?.session_id?.replace('trial_', '') || null
          })
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
    setResult(null)
    setAppealChain([])
  }

  const loadChain = async (caseId) => {
    if (!caseId) return
    try {
      const res = await api.listJudgments(caseId, user?.id)
      const judgments = res.judgments || []
      setAppealChain(judgments)

      if (judgments.length > 0) {
        setResult((prevResult) => {
          if (prevResult) return prevResult
          const latest = judgments[judgments.length - 1]
          setCourt(latest.court_level)
          return {
            petitioner: latest.petitioner_output,
            opponent: latest.opponent_output,
            cross_examination: latest.cross_examination_output,
            rebuttal: latest.rebuttal_output,
            judgment: latest.judgment,
            citations: latest.citations || [],
            court_level: latest.court_level,
            case_id: latest.case_id,
          }
        })
      }
    } catch {/* noop */}
  }

  // On mount, if we already have a caseId in CaseContext from a previous
  // session, hydrate the appeal chain so the user sees their existing trials.
  useEffect(() => {
    if (currentCase.caseId) loadChain(currentCase.caseId)
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (result?.case_id) loadChain(result.case_id)
  }, [result?.case_id])

  const onFactsChange = (e) => {
    setFacts(e.target.value)
    updateCase({ caseFacts: e.target.value })
  }

  const run = async (overrideCourt) => {
    if (!facts.trim()) return toast.error('Please paste the case facts first')
    setLoading(true)
    try {
      const targetCourt = overrideCourt || court
      const res = await api.runTrial({
        question: facts,
        court_level: targetCourt,
        rounds,
        userId: user?.id,
        // Re-use the case_id from in-page state OR from CaseContext so
        // appeals to higher courts land on the same case across navigation.
        caseId: result?.case_id || currentCase.caseId || undefined,
      })
      setResult(res)
      updateCase({
        caseFacts:      facts,
        caseId:         res.case_id || currentCase.caseId,
        lastCourtLevel: targetCourt,
      })
      await loadChain(res.case_id)
      toast.success(`${targetCourt} verdict delivered`)
    } catch (err) {
      toast.error(err.message || 'Trial failed')
    } finally {
      setLoading(false)
    }
  }

  const appeal = (next) => { setCourt(next); run(next) }

  const chainNewestFirst = [...appealChain].reverse()

  return (
    <div className="flex gap-4 h-[calc(100vh-9rem)]">
      <ConversationsSidebar
        activeId={sessionId}
        onSelect={handleSelectHistory}
        onNew={handleNew}
        category="trial"
      />

      <div className="flex-1 min-w-0 overflow-y-auto pr-1 space-y-6 pb-8">
        <div className="flex items-center justify-between">
          <h1 className="font-serif text-3xl">Courtroom Simulation</h1>
        </div>

      <Card className="print:hidden">
        <CardHeader
          icon={Gavel}
          title="Simulation Configuration"
          subtitle="Four specialised agents argue, the judge rules, every citation is verified against the actual statute."
        />

        <form onSubmit={(e) => { e.preventDefault(); run() }} className="space-y-4">
          <Textarea
            label="Case facts (FIR + investigation summary)"
            rows={7}
            value={facts}
            onChange={onFactsChange}
            placeholder="Paste the FIR text and/or the investigation summary."
          />

          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <span className="label">Court level</span>
              <div className="flex gap-2">
                {COURTS.map((c) => (
                  <button
                    type="button"
                    key={c.id}
                    onClick={() => setCourt(c.id)}
                    className={`px-3 py-2 rounded-lg text-sm border transition ${
                      court === c.id
                        ? 'bg-gold-400/15 border-gold-400/40 text-gold-200'
                        : 'bg-white/5 border-white/10 text-ink-200 hover:bg-white/10'
                    }`}
                  >
                    <Building2 className="w-3.5 h-3.5 inline mr-1.5" /> {c.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className="label">Debate rounds</span>
              <div className="flex gap-2">
                {[1, 2, 3].map((n) => (
                  <button
                    type="button"
                    key={n}
                    onClick={() => setRounds(n)}
                    className={`w-10 h-10 rounded-lg text-sm border transition ${
                      rounds === n
                        ? 'bg-gold-400/15 border-gold-400/40 text-gold-200'
                        : 'bg-white/5 border-white/10 text-ink-200 hover:bg-white/10'
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            <Button type="submit" loading={loading}>
              <Sparkles className="w-4 h-4" /> {result ? 'Re-run trial' : 'Begin trial'}
            </Button>
          </div>
        </form>
      </Card>

      {!result ? (
        <Card className="print:hidden">
          <EmptyState icon={Gavel} title="No verdict yet"
            description="Provide the case facts and run the trial to see the agents debate." />
        </Card>
      ) : (
        <article className="space-y-4 printable">
          <Disclaimer className="print:hidden" />
          <div className="grid lg:grid-cols-2 gap-4">
            <CourtPanel role="petitioner" data={result.petitioner} delay={0.00} />
            <CourtPanel role="opponent"   data={result.opponent}   delay={0.08} />
            {result.cross_examination && (
              <CourtPanel role="cross_examination" data={result.cross_examination} delay={0.12} />
            )}
            <CourtPanel role="rebuttal"   data={result.rebuttal}   delay={0.16} />
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.24, duration: 0.4 }}
              className="relative overflow-hidden rounded-2xl border border-gold-400/30 glass p-5"
            >
              <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-gold-400/20 to-transparent pointer-events-none" />
              <div className="relative">
                <div className="flex items-center justify-between gap-2 mb-3">
                  <div className="flex items-center gap-2">
                    <div className="w-9 h-9 rounded-xl bg-gold-400/20 grid place-items-center border border-gold-400/30 text-gold-200">
                      <Gavel className="w-4 h-4" />
                    </div>
                    <h3 className="font-serif text-lg">Judgment · {result.court_level} court</h3>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => window.print()} className="print:hidden">
                    <Printer className="w-4 h-4" /> Print / PDF
                  </Button>
                </div>
                <p className="text-sm text-ink-100 leading-relaxed mb-3">{result.judgment.final_judgment}</p>
                {result.judgment.liability_assessment && (
                  <p className="text-sm text-ink-300 mb-3">
                    <span className="text-gold-300 font-medium">Liability: </span>
                    {result.judgment.liability_assessment}
                  </p>
                )}
                {result.judgment.applicable_sections?.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {result.judgment.applicable_sections.map((s, i) => (
                      <Badge key={i} tone="gold">{s}</Badge>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          </div>

          <Card>
            <CardHeader title="Judicial reasoning" subtitle="Court's analysis, broken out" />
            <div className="grid md:grid-cols-2 gap-4 text-sm">
              {[
                ['Court observations',     result.judgment.court_observations],
                ['Facts established',      result.judgment.facts_established],
                ['Disputed facts',         result.judgment.disputed_facts],
                ['Evidence evaluation',    result.judgment.evidence_evaluation],
                ['Procedural findings',    result.judgment.procedural_findings],
                ['Recommended next steps', result.judgment.recommended_next_steps],
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
          </Card>

          {result.citations?.length > 0 && (
            <Card>
              <CardHeader icon={BookOpenCheck} title="Citation verification"
                subtitle="Each cited section was re-retrieved from the statute database and audited." />
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {result.citations.map((c, i) => (
                  <CitationCard key={i} citation={c} onClick={setActiveCitation} />
                ))}
              </div>
            </Card>
          )}

          {appealChain.length > 1 && (
            <Card className="print:hidden">
              <CardHeader
                icon={HistoryIcon}
                title="Appeal chain"
                subtitle={`${appealChain.length} verdicts on this case · newest first`}
              />
              <div className="space-y-3">
                {chainNewestFirst.map((row, i) => (
                  <JudgmentCard
                    key={row.id}
                    row={row}
                    index={i}
                    onOpenCitation={setActiveCitation}
                  />
                ))}
              </div>
            </Card>
          )}

          {court !== 'supreme' && (
            <Card className="flex items-center justify-between flex-wrap gap-3 print:hidden">
              <div>
                <h4 className="font-serif text-lg">Appeal this verdict</h4>
                <p className="text-sm text-ink-300">
                  Escalate the same case facts to the next court — each level's verdict is preserved.
                </p>
              </div>
              <Button onClick={() => appeal(court === 'district' ? 'high' : 'supreme')} loading={loading}>
                Appeal to {court === 'district' ? 'High Court' : 'Supreme Court'}
              </Button>
            </Card>
          )}
        </article>
      )}

      <CitationModal
        citation={activeCitation}
        onClose={() => setActiveCitation(null)}
      />
      </div>
    </div>
  )
}
