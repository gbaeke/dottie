import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, ArrowUp, MessageSquare, MessagesSquare, Plus, Trash2, TriangleAlert, Users } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import {
  createConversationMutation,
  deleteConversationMutation,
  listConversationsOptions,
  listConversationsQueryKey,
  listDottieEventsOptions,
  listDottiesOptions,
  listMessagesOptions,
  listMessagesQueryKey,
  markReadMutation,
  sendMessageMutation,
} from '@/client/@tanstack/react-query.gen'
import type { ConversationOut, DottieOut, MessageOut } from '@/client/types.gen'
import { DottieAvatar } from '@/components/DottieAvatar'
import { hueStyle } from '@/lib/hue'
import { EventIcon } from '@/components/EventLine'
import { Markdown } from '@/components/Markdown'
import { ListSkeleton } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { invalidateFamilies } from '@/lib/live'
import { relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useDottie } from '@/lib/dottie-context'

const scrollIntoView = (el: HTMLElement | null) => el?.scrollIntoView({ block: 'end' })

const KIND_ICON = { chat: MessageSquare, schedule: AlarmClock, dottie: Users } as const

function ConversationList({
  d,
  conversations,
  activeId,
}: {
  d: DottieOut
  conversations: ConversationOut[]
  activeId?: string
}) {
  const navigate = useNavigate()
  const create = useMutation({
    ...createConversationMutation(),
    onSuccess: (c) => void navigate(`/dotties/${d.id}/c/${c.id}`),
    onError: (e) => toast.error(errorMessage(e)),
  })
  const qc = useQueryClient()
  return (
    <div className="flex h-full flex-col">
      <div className="p-2">
        <button
          className="btn-primary w-full justify-center"
          disabled={create.isPending}
          onClick={() =>
            create.mutate(
              { path: { dottie_id: d.id }, body: {} },
              {
                onSuccess: () =>
                  void qc.invalidateQueries({ queryKey: listConversationsQueryKey({ path: { dottie_id: d.id } }) }),
              },
            )
          }
        >
          <Plus className="size-4" /> New chat
        </button>
      </div>
      <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
        {conversations.map((c) => {
          const Icon = KIND_ICON[c.kind as keyof typeof KIND_ICON] ?? MessageSquare
          return (
            <li key={c.id}>
              <Link
                to={`/dotties/${d.id}/c/${c.id}`}
                aria-current={c.id === activeId}
                className={cn(
                  'block rounded-md px-3 py-2 transition-colors',
                  c.id === activeId ? 'bg-dot-soft' : 'hover:bg-muted',
                )}
              >
                <p className="flex items-center gap-1.5">
                  <Icon className="size-3.5 shrink-0 text-fg-muted" />
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {c.peer_name ? `With ${c.peer_name}` : c.title}
                  </span>
                  {c.unread > 0 && <span className="size-2 rounded-full bg-accent" aria-label="Unread" />}
                </p>
                <p className="mt-0.5 truncate text-xs text-fg-muted">
                  {c.preview.replace(/[*_`#>]/g, '') || relativeTime(c.updated_at)}
                </p>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Bubble({ m, d, hueOf }: { m: MessageOut; d: DottieOut; hueOf: (id: number | null) => number }) {
  if (m.sender_kind === 'system')
    return (
      <div className="anim-rise mx-auto flex max-w-xl items-start gap-2 rounded-md bg-warn/10 px-3 py-2 text-warn">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        <p className="whitespace-pre-line">{m.body}</p>
      </div>
    )
  if (m.sender_kind === 'scheduler') {
    const [head, ...rest] = m.body.split('\n\n')
    return (
      <details className="anim-rise mx-auto max-w-xl rounded-md border border-dashed border-border px-3 py-2 text-xs text-fg-muted">
        <summary className="flex cursor-pointer items-center gap-1.5">
          <AlarmClock className="size-3.5" /> {head?.replace('Scheduled task: ', 'Scheduled task · ')} ·{' '}
          {relativeTime(m.created_at)}
        </summary>
        <p className="mt-2 whitespace-pre-line">{rest.join('\n\n')}</p>
      </details>
    )
  }
  const mine =
    m.sender_kind === 'user' || (m.sender_kind === 'dottie' && m.sender_id === d.id && m.recipient_id !== null)
  const fromPeer = m.sender_kind === 'dottie' && m.sender_id !== d.id
  return (
    <div className={cn('anim-rise flex gap-2.5', mine && 'justify-end')} style={hueStyle(hueOf(m.sender_id))}>
      {!mine && <DottieAvatar hue={hueOf(m.sender_id)} state="awake" size={30} className="mt-1" />}
      <div className={cn('max-w-[85%] min-w-0 sm:max-w-[75%]', mine && 'text-right')}>
        {(fromPeer || (mine && m.sender_kind === 'dottie')) && (
          <p className="mb-0.5 text-xs text-fg-muted">{m.sender_name}</p>
        )}
        <div
          className={cn(
            'inline-block rounded-2xl px-3.5 py-2 text-left',
            mine ? 'rounded-br-md bg-accent text-accent-fg' : 'rounded-bl-md border border-border bg-surface',
          )}
        >
          {mine && m.sender_kind === 'user' ? (
            <p className="whitespace-pre-wrap">{m.body}</p>
          ) : (
            <Markdown>{m.body}</Markdown>
          )}
        </div>
        <p className="mt-0.5 text-[11px] text-fg-muted">{relativeTime(m.created_at)}</p>
      </div>
    </div>
  )
}

function WorkingStrip({ d }: { d: DottieOut }) {
  const events = useQuery({
    ...listDottieEventsOptions({ path: { dottie_id: d.id }, query: { limit: 12 } }),
    enabled: d.state !== 'sleeping',
  })
  const recent = (events.data ?? [])
    .filter((e) => e.kind !== 'tool_result')
    .slice(0, 3)
    .reverse()
  if (d.state === 'sleeping')
    return <p className="px-4 pb-1 text-xs text-fg-muted">{d.name} is asleep. Write to wake them.</p>
  return (
    <div className="space-y-0.5 px-4 pb-1.5 text-xs text-fg-muted" aria-live="polite">
      <p className="flex items-center gap-1.5 font-medium text-dot-ink">
        <span className="size-1.5 animate-pulse rounded-full bg-dot" />
        {d.state === 'queued' ? 'Waking up…' : 'Working…'}
      </p>
      {recent.map((e) => (
        <p key={e.id} className="anim-rise flex items-center gap-1.5 truncate">
          <EventIcon kind={e.kind} className="size-3" /> <span className="truncate font-mono">{e.text}</span>
        </p>
      ))}
    </div>
  )
}

function Thread({ d, conversation }: { d: DottieOut; conversation: ConversationOut }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const dotties = useQuery(listDottiesOptions())
  const key = { path: { conversation_id: conversation.id } }
  const messages = useQuery(listMessagesOptions(key))
  const [text, setText] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)
  const hueOf = (id: number | null) => (id === null ? d.hue : (dotties.data?.find((x) => x.id === id)?.hue ?? d.hue))
  const readOnly = conversation.kind === 'dottie'

  const send = useMutation({
    ...sendMessageMutation(),
    onMutate: async ({ body }) => {
      await qc.cancelQueries({ queryKey: listMessagesQueryKey(key) })
      const previous = qc.getQueryData<MessageOut[]>(listMessagesQueryKey(key))
      const optimistic: MessageOut = {
        id: -Date.now(),
        conversation_id: conversation.id,
        sender_kind: 'user',
        sender_id: null,
        sender_name: null,
        recipient_id: d.id,
        body: body.body,
        status: 'pending',
        read_at: null,
        created_at: new Date().toISOString(),
      }
      qc.setQueryData<MessageOut[]>(listMessagesQueryKey(key), [...(previous ?? []), optimistic])
      return { previous }
    },
    onError: (e, _v, ctx) => {
      qc.setQueryData(listMessagesQueryKey(key), ctx?.previous)
      toast.error(errorMessage(e))
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: listMessagesQueryKey(key) })
      void qc.invalidateQueries({ queryKey: listConversationsQueryKey({ path: { dottie_id: d.id } }) })
    },
  })
  const markRead = useMutation(markReadMutation())
  const remove = useMutation({
    ...deleteConversationMutation(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: listConversationsQueryKey({ path: { dottie_id: d.id } }) })
      void navigate(`/dotties/${d.id}`)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const unread = conversation.unread
  const { mutate: markConversationRead } = markRead
  useEffect(() => {
    // keeps the server's read marks in step with what is on screen (an external system)
    if (unread > 0)
      markConversationRead(
        { path: { conversation_id: conversation.id } },
        {
          onSuccess: () => {
            void qc.invalidateQueries({ queryKey: listConversationsQueryKey({ path: { dottie_id: d.id } }) })
            void invalidateFamilies(qc, ['listDotties', 'inbox'])
          },
        },
      )
  }, [unread, conversation.id, d.id, markConversationRead, qc])

  const submit = () => {
    const body = text.trim()
    if (!body || readOnly) return
    send.mutate({ path: { conversation_id: conversation.id }, body: { body } })
    setText('')
    if (box.current) box.current.style.height = 'auto'
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex h-full min-w-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2">
        <p className="min-w-0 truncate font-medium">
          {conversation.peer_name ? `With ${conversation.peer_name}` : conversation.title}
        </p>
        <button
          className="btn-ghost p-1.5"
          aria-label="Delete this conversation"
          onClick={() =>
            window.confirm('Delete this conversation and the dottie’s memory of it?') &&
            remove.mutate({ path: { conversation_id: conversation.id } })
          }
        >
          <Trash2 className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.isPending && <ListSkeleton rows={2} />}
        {messages.data?.length === 0 && <p className="py-10 text-center text-fg-muted">Say hello to {d.name}.</p>}
        {messages.data?.map((m) => (
          <Bubble key={m.id} m={m} d={d} hueOf={hueOf} />
        ))}
        <div key={`${messages.data?.length ?? 0}-${d.state}`} ref={scrollIntoView} />
      </div>
      <WorkingStrip d={d} />
      <div className="border-t border-border p-3">
        {readOnly ? (
          <p className="rounded-md bg-muted px-3 py-2 text-xs text-fg-muted">
            This is a conversation between dotties; you can read it but not join. Start a new chat to talk to {d.name}.
          </p>
        ) : (
          <div className="flex items-end gap-2 rounded-xl border border-border bg-surface p-2 focus-within:border-dot">
            <textarea
              ref={box}
              rows={1}
              value={text}
              aria-label={`Message ${d.name}`}
              placeholder={`Message ${d.name}…`}
              className="max-h-48 flex-1 resize-none bg-transparent px-2 py-1 outline-none focus-visible:outline-none"
              onChange={(e) => {
                setText(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = `${e.target.scrollHeight}px`
              }}
              onKeyDown={onKey}
            />
            <button className="btn-primary rounded-full p-2" onClick={submit} disabled={!text.trim()} aria-label="Send">
              <ArrowUp className="size-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export function Chat() {
  const d = useDottie()
  const { conversationId } = useParams()
  const conversations = useQuery(listConversationsOptions({ path: { dottie_id: d.id } }))
  const active =
    conversations.data?.find((c) => c.id === conversationId) ?? (conversationId ? undefined : conversations.data?.[0])
  // on a phone the list and the thread take turns: the list is the dottie's page, a conversation opens its thread
  return (
    <div className="flex h-full min-h-0">
      <aside
        className={cn('w-full shrink-0 border-r border-border md:block md:w-64', conversationId ? 'hidden' : 'block')}
      >
        {conversations.isPending ? (
          <ListSkeleton rows={3} className="p-2" />
        ) : (
          <ConversationList d={d} conversations={conversations.data ?? []} activeId={active?.id} />
        )}
      </aside>
      <section className={cn('min-w-0 flex-1', conversationId ? 'flex flex-col' : 'hidden md:flex md:flex-col')}>
        <Link to={`/dotties/${d.id}`} className="btn-ghost m-1 self-start md:hidden">
          <MessagesSquare className="size-4" /> Conversations
        </Link>
        {active ? (
          <div className="min-h-0 flex-1">
            <Thread key={active.id} d={d} conversation={active} />
          </div>
        ) : (
          <div className="grid flex-1 place-items-center p-6 text-center text-fg-muted">
            {conversations.isPending ? null : (
              <div>
                <DottieAvatar hue={d.hue} state={d.state} size={64} className="mx-auto mb-3" />
                <p>No conversations with {d.name} yet.</p>
                <p className="text-xs">Use “New chat” to start one.</p>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
