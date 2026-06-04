import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Send, Sparkles, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

import Card, { CardHeader } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import MessageBubble from '@/components/MessageBubble'
import CitationCard from '@/components/CitationCard'
import CitationModal from '@/components/CitationModal'
import EmptyState from '@/components/ui/EmptyState'
import Disclaimer from '@/components/Disclaimer'
import ConversationsSidebar from '@/components/ConversationsSidebar'
import { api, streamAssistant } from '@/api/client'
import { useAuth } from '@/context/AuthContext'
import { genSessionId } from '@/lib/utils'

const SUGGESTIONS = [
  'What is the punishment for theft under BNS Section 303?',
  'Someone broke into my house last night — what should I do?',
  'Explain Section 351 in plain language.',
  'Is house trespass a cognizable offence?',
]

export default function AssistantPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  // Session is URL-bound: ?s=<id>. Falls back to a fresh one so the URL is
  // always shareable / reload-safe.
  const urlSession = searchParams.get('s')
  const [sessionId, setSessionId] = useState(urlSession || genSessionId())

  const [messages, setMessages] = useState([])
  const [citations, setCitations] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [input, setInput] = useState('')
  const [lowConfidence, setLowConfidence] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [activeCitation, setActiveCitation] = useState(null)
  const endRef = useRef(null)
  const abortRef = useRef(null)

  // Open a citation by section number (clicked from inside a streamed message)
  const openSection = (num) => {
    const match = citations.find((c) => String(c.section_number) === String(num))
    if (match) setActiveCitation(match)
    else toast.error(`Section ${num} not in current citations`)
  }

  // Keep URL in sync with the active session
  useEffect(() => {
    if (sessionId && searchParams.get('s') !== sessionId) {
      setSearchParams({ s: sessionId }, { replace: true })
    }
  }, [sessionId, searchParams, setSearchParams])

  // Load existing transcript when sessionId changes (e.g. user picks one from sidebar)
  useEffect(() => {
    let alive = true
    const load = async () => {
      setLoadingHistory(true)
      setMessages([])
      setCitations([])
      setLowConfidence(false)
      abortRef.current?.abort()
      try {
        const res = await api.getConversation(sessionId, user.id)
        if (!alive) return
        const msgs = res.messages || []
        setMessages(msgs.map((m) => ({ role: m.role, content: m.message })))

        // Restore the citations from the LAST assistant message so the
        // right-hand panel doesn't reset when you browse history.
        const lastWithMeta = [...msgs].reverse().find(
          (m) => m.role === 'assistant' && m.metadata?.citations?.length,
        )
        if (lastWithMeta) {
          setCitations(lastWithMeta.metadata.citations)
          setLowConfidence(Boolean(lastWithMeta.metadata.low_confidence))
        }
      } catch {
        // Anonymous / empty session — nothing to load.
      } finally {
        if (alive) setLoadingHistory(false)
      }
    }
    if (user?.id) load()
    return () => { alive = false }
  }, [sessionId, user?.id])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming])

  const send = async (text) => {
    const value = (text ?? input).trim()
    if (!value || streaming) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: value }, { role: 'assistant', content: '' }])
    setCitations([])
    setLowConfidence(false)
    setStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await streamAssistant(
        { chatInput: value, sessionId, userId: user?.id },
        {
          onToken: (delta) =>
            setMessages((m) => {
              const copy = m.slice()
              const last = copy[copy.length - 1]
              if (last && last.role === 'assistant') last.content += delta
              return copy
            }),
          onCitations: (list) => setCitations(list || []),
          onDone:      (meta) => {
            setLowConfidence(Boolean(meta?.low_confidence))
            // Refresh sidebar so this conversation appears / moves to top
            qc.invalidateQueries({ queryKey: ['conversations', user?.id] })
          },
          onError:     (msg)  => toast.error(msg || 'Stream failed'),
        },
        controller.signal,
      )
    } catch (err) {
      if (err.name !== 'AbortError') toast.error(err.message || 'Assistant failed')
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  const startNew = useCallback(() => {
    abortRef.current?.abort()
    const fresh = genSessionId()
    setSessionId(fresh)
    setMessages([])
    setCitations([])
    setLowConfidence(false)
    setInput('')
  }, [])

  const empty = messages.length === 0 && !loadingHistory

  return (
    <div className="flex gap-4 h-[calc(100vh-9rem)]">
      <ConversationsSidebar
        activeId={sessionId}
        onSelect={(id) => setSessionId(id)}
        onNew={startNew}
      />

      <div className="grid lg:grid-cols-[1fr_340px] gap-4 flex-1 min-w-0">
        <Card className="flex flex-col p-0 overflow-hidden">
          <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between">
            <div>
              <h2 className="font-serif text-lg">Nyaya Sahayak</h2>
              <p className="text-xs text-ink-400">
                Grounded in BNS, BNSS &amp; BSA 2023
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={startNew} title="Start a new conversation">
              <Trash2 className="w-3.5 h-3.5" /> New chat
            </Button>
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {loadingHistory ? (
              <div className="text-sm text-ink-400 italic">Loading conversation…</div>
            ) : empty ? (
              <EmptyState
                icon={Sparkles}
                title="Ask anything about Indian criminal law"
                description="Answers stream live from BNS / BNSS / BSA. Every claim is grounded in the citation panel on the right."
                action={
                  <div className="grid sm:grid-cols-2 gap-2 max-w-xl mx-auto">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        onClick={() => send(s)}
                        className="text-left text-sm glass-light rounded-xl px-3 py-2.5 hover:border-gold-400/30 border border-white/5 transition"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                }
              />
            ) : (
              <>
                {messages.map((m, i) => (
                  <MessageBubble
                    key={i}
                    role={m.role}
                    streaming={streaming && m.role === 'assistant' && i === messages.length - 1}
                    onSectionClick={openSection}
                  >
                    {m.content || (streaming && i === messages.length - 1
                      ? <span className="text-ink-400 italic">thinking…</span>
                      : '')}
                  </MessageBubble>
                ))}
                <div ref={endRef} />
              </>
            )}
          </div>

          <form
            onSubmit={(e) => { e.preventDefault(); send() }}
            className="p-4 border-t border-white/5 flex gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about a section, offence, punishment, or situation…"
              className="input flex-1"
              disabled={streaming}
            />
            <Button type="submit" loading={streaming} disabled={!input.trim()}>
              <Send className="w-4 h-4" />
            </Button>
          </form>
        </Card>

        <Card className="overflow-hidden flex flex-col">
          <CardHeader title="Citations" subtitle="Sections retrieved & graph-expanded" />
          {lowConfidence && (
            <Badge tone="red" className="mb-3">Low confidence — retrieval was weak</Badge>
          )}
          <div className="flex-1 overflow-y-auto space-y-3 pr-1">
            {citations.length === 0 ? (
              <p className="text-sm text-ink-400">
                Citations from the legal database will appear here once you ask a question.
              </p>
            ) : (
              citations.map((c, i) => (
                <CitationCard key={i} citation={c} onClick={setActiveCitation} />
              ))
            )}
          </div>
          <Disclaimer className="mt-4" />
        </Card>
      </div>

      <CitationModal
        citation={activeCitation}
        onClose={() => setActiveCitation(null)}
      />
    </div>
  )
}
