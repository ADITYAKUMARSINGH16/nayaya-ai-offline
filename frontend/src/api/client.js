import { supabase, hasSupabase } from '@/lib/supabase'
import { streamPost } from '@/lib/sse'

const BASE = import.meta.env.VITE_API_URL || ''

async function authHeaders() {
  if (!hasSupabase) return {}
  const { data } = await supabase.auth.getSession()
  const token = data?.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const headers = { 'Content-Type': 'application/json', ...(await authHeaders()) }
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json())?.detail || '' } catch { detail = await res.text() }
    throw new Error(`${res.status} ${detail || res.statusText}`)
  }
  return res.json()
}

export const api = {
  health:       ()        => request('/api/health'),
  assistant:    (payload) => request('/api/assistant', { method: 'POST', body: payload }),
  generateFIR:  (payload) => request('/api/fir', { method: 'POST', body: payload }),
  investigate:  (payload) => request('/api/investigation', { method: 'POST', body: payload }),
  runTrial:     (payload) => request('/api/cases/trial', { method: 'POST', body: payload }),
  getCase:      (id)      => request(`/api/cases/${id}`),
  listCases:    ()        => request('/api/cases'),
  evalRuns:     (limit=30)=> request(`/api/eval/runs?limit=${limit}`),
  evalLatest:   ()        => request('/api/eval/latest'),

  // Chat-history sidebar — user_id passed as query param because soft-auth
  // can't verify the new ES256 Supabase JWT yet, so the backend can't derive
  // it from the token. Browser supplies it directly.
  listConversations: ({ userId, category }) => {
    const params = new URLSearchParams()
    if (userId) params.set('user_id', userId)
    if (category) params.set('category', category)
    const qs = params.toString()
    return request(`/api/conversations${qs ? `?${qs}` : ''}`)
  },
  getConversation: (sessionId, userId) =>
    request(`/api/conversations/${sessionId}/messages${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`),
  deleteConversation: (sessionId, userId) =>
    request(`/api/conversations/${sessionId}${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`, { method: 'DELETE' }),

  // Evidence
  listEvidence: (userId, investigationId) => {
    const params = new URLSearchParams()
    if (userId) params.set('user_id', userId)
    if (investigationId) params.set('investigation_id', investigationId)
    const qs = params.toString()
    return request(`/api/evidence${qs ? `?${qs}` : ''}`)
  },
  createEvidence: (payload) =>
    request('/api/evidence', { method: 'POST', body: payload }),
  deleteEvidence: (evidenceId, userId) =>
    request(`/api/evidence/${evidenceId}${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`, { method: 'DELETE' }),

  // Judgments (appeal chain)
  listJudgments: (caseId, userId) =>
    request(`/api/cases/${caseId}/judgments${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`),

  // Lawyer
  lawyerAnalyze: (payload) => request('/api/lawyer/analyze', { method: 'POST', body: payload }),

  // Judge
  judgeGetCases: () => request('/api/judge/cases'),
  judgeSubmitVerdict: (caseId, payload) => request(`/api/judge/cases/${caseId}/verdict`, { method: 'POST', body: payload }),
  judgeAnalyze: (payload) => request('/api/judge/analyze', { method: 'POST', body: payload }),

  /**
   * Streaming assistant. Pass `{ signal, onEvent }` where `onEvent` receives
   * `{ event, data }` for each SSE message (event = "token"|"citations"|"intent"|"done"|"error").
   */
  assistantStream: async (payload, { signal, onEvent } = {}) =>
    streamPost(`${BASE}/api/assistant/stream`, payload, {
      headers: await authHeaders(),
      signal,
      onEvent: (event, data) => onEvent?.({ event, data }),
    }),

  // Admin
  adminGetFirs: () => request('/api/admin/firs'),
  adminGetCases: () => request('/api/admin/cases'),
  adminOverrideFirStatus: (firId, status) => request(`/api/admin/firs/${firId}/status`, { method: 'POST', body: { status } }),

  // Bare Acts
  bareActsList: () => request('/api/bare-acts/'),
  bareActsSearch: (q, act) => {
    const params = new URLSearchParams({ q })
    if (act) params.set('act', act)
    return request(`/api/bare-acts/search?${params.toString()}`)
  },
  bareActsGet: (act) => request(`/api/bare-acts/${act}`),
}

/**
 * Streaming assistant. Calls `/api/assistant/stream` and invokes the callbacks
 * as events arrive: token (string), citations (array), intent (string),
 * done (object), error (string).
 */
export async function streamAssistant(payload, callbacks = {}, signal) {
  return streamPost(`${BASE}/api/assistant/stream`, payload, {
    headers: await authHeaders(),
    signal,
    onEvent: (event, data) => {
      switch (event) {
        case 'token':       return callbacks.onToken?.(data)
        case 'intent':      return callbacks.onIntent?.(data)
        case 'citations':   try { callbacks.onCitations?.(JSON.parse(data)) } catch { /* noop */ }; return
        case 'done':        try { callbacks.onDone?.(JSON.parse(data)) } catch { callbacks.onDone?.({}) }; return
        case 'error':       return callbacks.onError?.(data)
      }
    },
  })
}
