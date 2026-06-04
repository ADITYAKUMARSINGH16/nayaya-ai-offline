import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer, LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, Legend,
} from 'recharts'
import { BarChart3, CheckCircle2, Gauge, ListChecks } from 'lucide-react'

import Card, { CardHeader } from '@/components/ui/Card'
import Badge from '@/components/ui/Badge'
import EmptyState from '@/components/ui/EmptyState'
import { SkeletonCard } from '@/components/ui/Skeleton'
import { api } from '@/api/client'

function pct(n) {
  return `${Math.round((n || 0) * 100)}%`
}

function ms(n) {
  return n != null ? `${Math.round(n)}ms` : '—'
}

function Stat({ icon: Icon, label, value, sub }) {
  return (
    <div className="glass-light rounded-xl p-4 border border-white/5">
      <div className="flex items-center gap-2 text-ink-300 text-xs uppercase tracking-wider mb-1">
        <Icon className="w-3.5 h-3.5 text-gold-300" /> {label}
      </div>
      <div className="font-serif text-2xl text-ink-50">{value}</div>
      {sub && <div className="text-xs text-ink-400 mt-0.5">{sub}</div>}
    </div>
  )
}

export default function EvalDashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['eval-runs'],
    queryFn: () => api.evalRuns(30),
    refetchInterval: 5 * 60_000,
  })

  if (isLoading) {
    return (
      <div className="space-y-4">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    )
  }

  const runs = data?.runs || []
  const latest = runs[runs.length - 1]

  const chartData = runs.map((r) => ({
    at: new Date(r.run_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }),
    precision: Math.round((r.precision_at_k || 0) * 100),
    verified:  Math.round((r.citation_verified_rate || 0) * 100),
    p50:       Math.round(r.latency_ms_p50 || 0),
    p95:       Math.round(r.latency_ms_p95 || 0),
  }))

  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-ink-400">Retrieval quality over time</p>
        <h1 className="font-serif text-3xl flex items-center gap-2">
          <BarChart3 className="w-6 h-6 text-gold-300" /> Evaluation
        </h1>
      </div>

      {!latest ? (
        <Card>
          <EmptyState
            icon={ListChecks}
            title="No eval runs yet"
            description="The daily eval cron in n8n hasn't produced a run. Trigger one manually with: docker compose exec backend python -m eval.runner"
          />
        </Card>
      ) : (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat icon={CheckCircle2} label="Precision @ k"
              value={pct(latest.precision_at_k)} sub={`${latest.hits}/${latest.total} cases`} />
            <Stat icon={CheckCircle2} label="Citation verified rate"
              value={pct(latest.citation_verified_rate)} sub="avg over returned citations" />
            <Stat icon={Gauge} label="Latency p50" value={ms(latest.latency_ms_p50)} sub="per query" />
            <Stat icon={Gauge} label="Latency p95" value={ms(latest.latency_ms_p95)} sub="tail" />
          </div>

          <Card>
            <CardHeader title="Quality trend" subtitle="Precision + verified-rate over the last runs" />
            <div className="w-full h-72">
              <ResponsiveContainer>
                <LineChart data={chartData}>
                  <CartesianGrid stroke="#ffffff10" />
                  <XAxis dataKey="at" stroke="#9aa1bd" fontSize={11} />
                  <YAxis stroke="#9aa1bd" fontSize={11} domain={[0, 100]} unit="%" />
                  <Tooltip
                    contentStyle={{ background: '#0f1331', border: '1px solid #ffffff22', borderRadius: 8 }}
                    labelStyle={{ color: '#f4dd92' }}
                  />
                  <Legend />
                  <Line type="monotone" dataKey="precision" stroke="#e6b22d" strokeWidth={2} dot={false} name="precision@k" />
                  <Line type="monotone" dataKey="verified"  stroke="#34d399" strokeWidth={2} dot={false} name="verified rate" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card>
            <CardHeader title="Latency trend" subtitle="p50 and p95 per run (ms)" />
            <div className="w-full h-64">
              <ResponsiveContainer>
                <LineChart data={chartData}>
                  <CartesianGrid stroke="#ffffff10" />
                  <XAxis dataKey="at" stroke="#9aa1bd" fontSize={11} />
                  <YAxis stroke="#9aa1bd" fontSize={11} unit="ms" />
                  <Tooltip
                    contentStyle={{ background: '#0f1331', border: '1px solid #ffffff22', borderRadius: 8 }}
                    labelStyle={{ color: '#f4dd92' }}
                  />
                  <Legend />
                  <Line type="monotone" dataKey="p50" stroke="#60a5fa" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="p95" stroke="#f472b6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card>
            <CardHeader title="Latest run · per-case detail"
              subtitle={`Run at ${new Date(latest.run_at).toLocaleString('en-IN')}`} />
            <div className="space-y-2 text-sm">
              {(latest.details || []).slice(0, 12).map((d, i) => (
                <div key={i} className="glass-light rounded-lg p-3 flex items-start justify-between gap-3 border border-white/5">
                  <div className="min-w-0">
                    <div className="text-ink-100 truncate">{d.query}</div>
                    <div className="text-[11px] text-ink-400 mt-0.5">
                      expected {d.expected?.join(', ')} · got {d.returned?.slice(0, 4).join(', ') || '—'}
                    </div>
                  </div>
                  <Badge tone={d.hit ? 'green' : 'red'}>{d.hit ? 'hit' : 'miss'}</Badge>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
