import { useEffect, useState } from 'react'
import {
  ShieldAlert, Search, Users, Briefcase, AlertTriangle, ListChecks,
  Upload, Paperclip, Download, Trash2, FileText,
} from 'lucide-react'
import toast from 'react-hot-toast'

import Card, { CardHeader } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Input'
import Badge from '@/components/ui/Badge'
import EmptyState from '@/components/ui/EmptyState'
import Disclaimer from '@/components/Disclaimer'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { api } from '@/api/client'
import { useAuth } from '@/context/AuthContext'
import { useCase } from '@/context/CaseContext'
import { hasSupabase, supabase } from '@/lib/supabase'

const RISK_TONE = { low: 'green', medium: 'gold', high: 'red' }
const BUCKET = 'evidence'

function ListBlock({ icon: Icon, title, items }) {
  return (
    <div className="glass-light rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2 text-ink-100">
        <Icon className="w-4 h-4 text-gold-300" />
        <span className="font-medium text-sm">{title}</span>
        <span className="text-xs text-ink-400">({items?.length || 0})</span>
      </div>
      {items?.length ? (
        <ul className="space-y-1.5 text-sm text-ink-200">
          {items.map((it, i) => (
            <li key={i} className="flex gap-2"><span className="text-gold-400">·</span><span>{it}</span></li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-ink-400 italic">None identified.</p>
      )}
    </div>
  )
}

export default function PolicePage() {
  const { user } = useAuth()
  const { currentCase, updateCase } = useCase()
  // Pre-fill from the shared case workspace (FIR facts carry over).
  const [facts, setFacts] = useState(currentCase.caseFacts || '')
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState(currentCase.investigationReport || null)
  const [evidence, setEvidence] = useState([])
  const [pendingDelete, setPendingDelete] = useState(null) // evidence row
  const [deleting, setDeleting] = useState(false)

  const reloadEvidence = async () => {
    if (!user?.id) return
    try {
      const res = await api.listEvidence(user.id)
      setEvidence(res.evidence || [])
    } catch {/* noop */}
  }

  useEffect(() => { reloadEvidence() }, [user?.id])

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await api.investigate({ caseFacts: facts, userId: user?.id })
      setReport(res.report)
      // Persist so a Trial-page hop or refresh keeps the report visible
      // AND the shared facts stay in sync (also picked up by Trial page).
      updateCase({ caseFacts: facts, investigationReport: res.report })
      toast.success('Investigation report ready')
    } catch (err) {
      toast.error(err.message || 'Investigation failed')
    } finally {
      setLoading(false)
    }
  }

  // Keep CaseContext's caseFacts updated as the textarea changes so other
  // pages (Trial especially) see the latest scenario without a Run-Investigation click.
  const onFactsChange = (e) => {
    setFacts(e.target.value)
    updateCase({ caseFacts: e.target.value })
  }

  const handleUpload = async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    if (!hasSupabase || !user?.id) {
      toast.error('Sign in (with Supabase configured) to upload evidence')
      return
    }
    for (const file of files) {
      // Sanitize filename to avoid "Invalid key" errors from Supabase Storage
      const sanitizedName = file.name.replace(/[^a-zA-Z0-9.\-_]/g, '_')
      const storage_path = `${user.id}/${Date.now()}_${sanitizedName}`
      const { error } = await supabase.storage.from(BUCKET).upload(storage_path, file, { upsert: false })
      if (error) {
        toast.error(`Upload failed: ${error.message}`)
        continue
      }
      try {
        const row = await api.createEvidence({
          user_id:      user.id,
          storage_path,
          filename:     file.name,
          mime_type:    file.type || null,
          size_bytes:   file.size,
        })
        setEvidence((prev) => [row, ...prev])
        toast.success(`Uploaded ${file.name}`)
      } catch (err) {
        toast.error(`Saved to storage but DB link failed: ${err.message}`)
      }
    }
    e.target.value = ''
  }

  const getDownloadUrl = async (storagePath) => {
    if (!hasSupabase) return null
    const { data } = await supabase.storage.from(BUCKET)
      .createSignedUrl(storagePath, 60 * 10)
    return data?.signedUrl || null
  }

  const downloadEvidence = async (row) => {
    const url = await getDownloadUrl(row.storage_path)
    if (!url) return toast.error("Couldn't generate download URL")
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  const confirmDeleteEvidence = async () => {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      if (hasSupabase) {
        await supabase.storage.from(BUCKET).remove([pendingDelete.storage_path])
      }
      await api.deleteEvidence(pendingDelete.id, user?.id)
      setEvidence((prev) => prev.filter((e) => e.id !== pendingDelete.id))
      toast.success('Evidence removed')
    } catch (err) {
      toast.error(err.message || 'Delete failed')
    } finally {
      setDeleting(false)
      setPendingDelete(null)
    }
  }

  return (
    <div className="grid lg:grid-cols-[400px_1fr] gap-6">
      <div className="space-y-4">
        <Card>
          <CardHeader
            icon={ShieldAlert}
            title="Investigation"
            subtitle="Paste the FIR or case facts. The agent returns a structured report — not prose."
          />
          <form onSubmit={submit} className="space-y-4">
            <Textarea
              label="Case Facts *" required rows={10} value={facts}
              onChange={onFactsChange}
              placeholder="Paste the FIR text or describe the incident in detail."
            />
            <Button type="submit" loading={loading} className="w-full">
              <Search className="w-4 h-4" /> Run investigation
            </Button>
          </form>
        </Card>

        <Card>
          <CardHeader
            icon={Paperclip}
            title="Evidence"
            subtitle={`${evidence.length} file${evidence.length === 1 ? '' : 's'} attached`}
          />
          <label className="btn-ghost w-full cursor-pointer">
            <Upload className="w-4 h-4" />
            Upload files
            <input type="file" multiple onChange={handleUpload} className="hidden" />
          </label>

          {evidence.length === 0 ? (
            <p className="text-xs text-ink-400 italic mt-3">
              Photos, documents, screenshots — uploaded to Supabase Storage and
              persisted to your account.
            </p>
          ) : (
            <ul className="mt-3 space-y-1.5 text-sm">
              {evidence.map((row) => (
                <li
                  key={row.id}
                  className="group flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white/5 text-ink-200"
                >
                  <FileText className="w-3.5 h-3.5 text-gold-300 shrink-0" />
                  <button
                    onClick={() => downloadEvidence(row)}
                    className="flex-1 text-left truncate hover:text-gold-200 transition"
                    title={row.filename}
                  >
                    {row.filename}
                  </button>
                  <span className="text-[10px] text-ink-400 shrink-0">
                    {row.size_bytes ? `${Math.round(row.size_bytes / 1024)} KB` : ''}
                  </span>
                  <button
                    onClick={() => downloadEvidence(row)}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-white/10 text-ink-400 hover:text-gold-300 transition"
                    title="Download"
                  >
                    <Download className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setPendingDelete(row)}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/15 text-ink-400 hover:text-red-300 transition"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="space-y-4">
        {!report ? (
          <Card>
            <EmptyState
              icon={ShieldAlert}
              title="No investigation yet"
              description="Submit the facts to generate evidence, witnesses, suspects and a risk assessment."
            />
          </Card>
        ) : (
          <>
            <Card>
              <CardHeader
                title="Investigation Summary"
                subtitle={report.summary}
                action={
                  <Badge tone={RISK_TONE[report.risk_level] || 'gold'}>
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {report.risk_level?.toUpperCase()} risk
                  </Badge>
                }
              />
              {report.risk_rationale && <p className="text-sm text-ink-300 italic">↳ {report.risk_rationale}</p>}
            </Card>

            <div className="grid md:grid-cols-2 gap-4">
              <ListBlock icon={ListChecks}  title="Investigation Steps" items={report.investigation_steps} />
              <ListBlock icon={Briefcase}   title="Evidence"             items={report.evidence} />
              <ListBlock icon={Users}       title="Witnesses"            items={report.witnesses} />
              <ListBlock icon={ShieldAlert} title="Suspects"             items={report.suspects} />
            </div>

            <Card>
              <CardHeader title="Applicable Sections" subtitle="Per BNS / BNSS 2023" />
              <div className="flex flex-wrap gap-2">
                {report.applicable_sections?.length
                  ? report.applicable_sections.map((s, i) => <Badge key={i} tone="gold">{s}</Badge>)
                  : <p className="text-sm text-ink-400">No sections identified.</p>}
              </div>
            </Card>

            <Disclaimer />
          </>
        )}
      </div>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Remove this evidence?"
        description={pendingDelete ? `"${pendingDelete.filename}" will be deleted from both storage and the case record.` : ''}
        confirmLabel="Delete"
        destructive
        loading={deleting}
        onConfirm={confirmDeleteEvidence}
        onCancel={() => !deleting && setPendingDelete(null)}
      />
    </div>
  )
}
