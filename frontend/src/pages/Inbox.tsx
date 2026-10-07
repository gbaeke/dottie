import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCheck, Inbox as InboxIcon, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { inboxOptions, inboxQueryKey, readInboxMutation } from '@/client/@tanstack/react-query.gen'
import { DottieAvatar } from '@/components/DottieAvatar'
import { hueStyle } from '@/lib/hue'
import { EmptyState, ListSkeleton, Page, PageTitle } from '@/components/ui'
import { invalidateFamilies } from '@/lib/live'
import { errorMessage } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'

export function Inbox() {
  const qc = useQueryClient()
  const inbox = useQuery(inboxOptions())
  const readAll = useMutation({
    ...readInboxMutation(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: inboxQueryKey() })
      void invalidateFamilies(qc, ['listDotties'])
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const unread = inbox.data?.filter((i) => !i.message.read_at).length ?? 0
  return (
    <Page>
      <PageTitle title="Inbox" sub="Everything your dotties wrote to you: answers, finished scheduled tasks, news.">
        <button className="btn-ghost" disabled={unread === 0 || readAll.isPending} onClick={() => readAll.mutate({})}>
          <CheckCheck className="size-4" /> Mark all read
        </button>
      </PageTitle>
      {inbox.isPending && <ListSkeleton rows={4} />}
      {inbox.data?.length === 0 && (
        <EmptyState icon={<InboxIcon className="size-6" />} title="Nothing yet">
          Replies and results from your dotties collect here.
        </EmptyState>
      )}
      <ul className="space-y-2">
        {inbox.data?.map((i) => {
          const isNew = !i.message.read_at
          return (
            <li key={i.message.id}>
              <Link
                to={`/dotties/${i.dottie_id}/c/${i.message.conversation_id}`}
                style={hueStyle(i.dottie_hue)}
                className={cn('card flex gap-3 transition-shadow hover:shadow-md', isNew && 'border-dot bg-dot-soft')}
              >
                <DottieAvatar hue={i.dottie_hue} state="awake" size={36} />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2">
                    <span className="font-medium">{i.dottie_name}</span>
                    <span className="truncate text-xs text-fg-muted">
                      {i.conversation_title || 'New chat'} · {relativeTime(i.message.created_at)}
                    </span>
                    {isNew && <span className="size-2 rounded-full bg-accent" aria-label="Unread" />}
                  </p>
                  <p
                    className={cn(
                      'line-clamp-3 whitespace-pre-line',
                      i.message.sender_kind === 'system' && 'text-warn',
                    )}
                  >
                    {i.message.sender_kind === 'system' && <TriangleAlert className="mr-1 inline size-4" />}
                    {i.message.body}
                  </p>
                </div>
              </Link>
            </li>
          )
        })}
      </ul>
    </Page>
  )
}
