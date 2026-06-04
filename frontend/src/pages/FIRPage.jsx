import { useState } from 'react'
import { FileText, Download, Printer, Sparkles } from 'lucide-react'
import toast from 'react-hot-toast'

import Card, { CardHeader } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Input, { Textarea } from '@/components/ui/Input'
import EmptyState from '@/components/ui/EmptyState'
import CitationCard from '@/components/CitationCard'
import Disclaimer from '@/components/Disclaimer'
import { api } from '@/api/client'
import { useAuth } from '@/context/AuthContext'
import { useCase } from '@/context/CaseContext'
import { downloadText, genSessionId } from '@/lib/utils'

const EMPTY_FORM = {
  complainantName:    '',
  complainantAddress: '',
  complainantPhone:   '',
  complainantAge:     '',
  complainantGender:  '',
  policeStation:      '',
  incidentDate:       '',
  incidentTime:       '',
  incidentLocation:   '',
  accused:            '',
  facts:              '',
}

export default function FIRPage() {
  const { user } = useAuth()
  const { currentCase, updateCase } = useCase()

  // Pre-fill from the persisted case: previous form values if any, else just
  // the shared `caseFacts` so the user doesn't re-type the scenario.
  const [form, setForm] = useState(() => ({
    ...EMPTY_FORM,
    ...(currentCase.firForm || {}),
    facts: currentCase.firForm?.facts || currentCase.caseFacts || '',
  }))
  const [loading, setLoading] = useState(false)
  const [result, setResult]   = useState(
    currentCase.firText ? { fir_text: currentCase.firText, citations: [] } : null,
  )

  const set = (k) => (e) => {
    const next = { ...form, [k]: e.target.value }
    setForm(next)
    // Keep CaseContext in sync as the user types — survives navigation/refresh.
    updateCase({ firForm: next, ...(k === 'facts' ? { caseFacts: e.target.value } : {}) })
  }

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await api.generateFIR({
        ...form,
        sessionId: genSessionId(),
        userId: user?.id,
      })
      setResult(res)
      updateCase({
        firForm:    form,
        firText:    res.fir_text,
        firRecordId: res.record_id || null,
        caseFacts:  form.facts || currentCase.caseFacts,
      })
      toast.success('FIR drafted')
    } catch (err) {
      toast.error(err.message || 'FIR generation failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid lg:grid-cols-[400px_1fr] gap-6">
      <Card className="print:hidden">
        <CardHeader
          icon={FileText}
          title="Draft an FIR"
          subtitle="Provide what you know. Missing fields stay as bracketed placeholders — never fabricated."
        />
        <form onSubmit={submit} className="space-y-4">
          <Input label="Complainant Name *" required value={form.complainantName} onChange={set('complainantName')} placeholder="Full legal name" />
          <Input label="Complainant Address" value={form.complainantAddress} onChange={set('complainantAddress')} placeholder="House, street, city, PIN" />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Phone" value={form.complainantPhone} onChange={set('complainantPhone')} placeholder="+91 ..." />
            <Input label="Age" value={form.complainantAge} onChange={set('complainantAge')} placeholder="e.g. 32" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Gender" value={form.complainantGender} onChange={set('complainantGender')} placeholder="M / F / Other" />
            <Input label="Police Station" value={form.policeStation} onChange={set('policeStation')} placeholder="e.g. Sector 39 PS" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Incident Date *" type="date" required value={form.incidentDate} onChange={set('incidentDate')} />
            <Input label="Incident Time" type="time" value={form.incidentTime} onChange={set('incidentTime')} />
          </div>
          <Input label="Incident Location" value={form.incidentLocation} onChange={set('incidentLocation')} placeholder="Address / area" />
          <Input label="Accused (if known)" value={form.accused} onChange={set('accused')} placeholder="Name / description" />
          <Textarea label="Facts of the case *" required rows={6} value={form.facts} onChange={set('facts')}
            placeholder="Describe what happened, when, where, and any witnesses or evidence." />
          <Button type="submit" loading={loading} className="w-full">
            <Sparkles className="w-4 h-4" /> Generate FIR
          </Button>
        </form>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader
            title="Drafted FIR"
            subtitle="Review carefully. AI-drafted documents must be vetted by a human before filing."
            action={
              result && (
                <div className="flex gap-2 print:hidden">
                  <Button variant="ghost" size="sm" onClick={() => window.print()}>
                    <Printer className="w-4 h-4" /> Print / PDF
                  </Button>
                  <Button variant="ghost" size="sm"
                    onClick={() => downloadText(`FIR_${form.complainantName || 'draft'}_${Date.now()}.txt`, result.fir_text)}>
                    <Download className="w-4 h-4" /> .txt
                  </Button>
                </div>
              )
            }
          />
          {result ? (
            <article className="printable">
              <Disclaimer className="mb-4 print:hidden" />
              <pre className="whitespace-pre-wrap text-sm text-ink-100 font-sans leading-relaxed bg-ink-950/60 rounded-xl p-5 border border-white/5 max-h-[60vh] overflow-y-auto print:max-h-none print:bg-white print:text-black print:border-0 print:p-0">
                {result.fir_text}
              </pre>
            </article>
          ) : (
            <EmptyState icon={FileText} title="No draft yet" description="Fill the form on the left to generate a police-style FIR." />
          )}
        </Card>

        {result?.citations?.length > 0 && (
          <Card className="print:hidden">
            <CardHeader title="Statute sections used" subtitle="Retrieved + graph-expanded from the legal database" />
            <div className="grid sm:grid-cols-2 gap-3">
              {result.citations.map((c, i) => <CitationCard key={i} citation={c} />)}
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
