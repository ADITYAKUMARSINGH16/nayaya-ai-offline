import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, Plus, Trash2, MessagesSquare } from 'lucide-react'
import toast from 'react-hot-toast'

import { api } from '@/api/client'
import { cn } from '@/lib/utils'
import { useAuth } from '@/context/AuthContext'
import { SkeletonText } from '@/components/ui/Skeleton'
import ConfirmDialog from '@/components/ui/ConfirmDialog'

function bucket(iso) {
  if (!iso) return 'Earlier'
  const at = new Date(iso)
  const now = new Date()
  const day = 86_400_000
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (at.getTime() >= startOfToday) return 'Today'
  if (at.getTime() >= startOfToday - day) return 'Yesterday'
  if (at.getTime() >= startOfToday - 7 * day) return 'Previous 7 days'
  if (at.getTime() >= startOfToday - 30 * day) return 'Previous 30 days'
  return 'Older'
}

export default function ConversationsSidebar({ activeId, onSelect, onNew, category = 'assistant' }) {
  const { user } = useAuth()
  const userId = user?.id
  const qc = useQueryClient()
  const [pendingDelete, setPendingDelete] = useState(null) // { sessionId, title }
  const [deleting, setDeleting] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['conversations', userId, category],
    queryFn: () => api.listConversations({ userId, category }),
    enabled: Boolean(userId),
    refetchOnWindowFocus: false,
    staleTime: 10_000,
  })

  const conversations = data?.conversations || []

  // group by bucket while preserving newest-first order
  const grouped = []
  let lastBucket = null
  for (const c of conversations) {
    const b = bucket(c.last_at)
    if (b !== lastBucket) {
      grouped.push({ heading: b })
      lastBucket = b
    }
    grouped.push({ conv: c })
  }

  const askDelete = (e, conv) => {
    e.stopPropagation()
    setPendingDelete({ sessionId: conv.session_id, title: conv.title })
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      await api.deleteConversation(pendingDelete.sessionId, userId)
      toast.success('Conversation deleted')
      qc.invalidateQueries({ queryKey: ['conversations', userId, category] })
      if (pendingDelete.sessionId === activeId) onNew?.()
    } catch (err) {
      toast.error(err.message || 'Delete failed')
    } finally {
      setDeleting(false)
      setPendingDelete(null)
    }
  }

  return (
    <aside className="hidden md:flex w-72 shrink-0 flex-col glass rounded-2xl p-3 h-full overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-2 pb-3 border-b border-white/5">
        <div className="flex items-center gap-2 text-sm text-ink-200">
          <MessagesSquare className="w-4 h-4 text-gold-300" />
          <span className="font-medium">
            {category === 'lawyer' ? 'Analyses' : category === 'judge' ? 'Evaluations' : 'Conversations'}
          </span>
        </div>
        <button
          onClick={onNew}
          className="text-xs flex items-center gap-1 px-2 py-1 rounded-lg bg-gold-400/15 text-gold-200 border border-gold-400/30 hover:bg-gold-400/25 transition"
          title="New conversation"
        >
          <Plus className="w-3.5 h-3.5" /> New
        </button>
      </div>

      <div className="flex-1 overflow-y-auto mt-2 pr-1 space-y-0.5">
        {isLoading ? (
          <SkeletonText lines={5} className="px-2 pt-2" />
        ) : conversations.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-ink-400">
            No history yet — every chat is saved here.
          </div>
        ) : (
          grouped.map((g, i) =>
            g.heading ? (
              <div
                key={`h-${i}`}
                className="px-2 pt-3 pb-1 text-[10px] uppercase tracking-wider text-ink-400"
              >
                {g.heading}
              </div>
            ) : (
              <button
                key={g.conv.session_id}
                onClick={() => onSelect?.(g.conv.session_id)}
                className={cn(
                  'group w-full text-left px-2.5 py-2 rounded-lg transition flex items-start gap-2',
                  activeId === g.conv.session_id
                    ? 'bg-gold-400/10 border border-gold-400/20 text-ink-50'
                    : 'hover:bg-white/5 border border-transparent text-ink-200',
                )}
              >
                <MessageSquare className="w-3.5 h-3.5 mt-0.5 shrink-0 text-ink-400 group-hover:text-gold-300" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">{g.conv.title || 'New conversation'}</div>
                  <div className="text-[10px] text-ink-400 mt-0.5">
                    {g.conv.message_count} msg
                  </div>
                </div>
                <button
                  onClick={(e) => askDelete(e, g.conv)}
                  className="opacity-0 group-hover:opacity-100 transition p-1 rounded hover:bg-red-500/15 text-ink-400 hover:text-red-300"
                  title="Delete conversation"
                  aria-label="Delete"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </button>
            ),
          )
        )}
      </div>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this conversation?"
        description={
          pendingDelete?.title
            ? `"${pendingDelete.title}" and all its messages will be permanently removed.`
            : 'This conversation and all its messages will be permanently removed.'
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        destructive
        loading={deleting}
        onConfirm={confirmDelete}
        onCancel={() => !deleting && setPendingDelete(null)}
      />
    </aside>
  )
}
