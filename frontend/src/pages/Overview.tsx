import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ArrowRight, Plus, TriangleAlert } from 'lucide-react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import {
  createDottieMutation,
  listDottiesOptions,
  listDottiesQueryKey,
  listEventsOptions,
  listSkillsOptions,
  listTemplatesOptions,
  systemOptions,
  trafficOptions,
} from '@/client/@tanstack/react-query.gen'
import type { DottieOut } from '@/client/types.gen'
import { DottieAvatar } from '@/components/DottieAvatar'
import { hueStyle } from '@/lib/hue'
import { EventIcon } from '@/components/EventLine'
import { DottieChip, EmptyState, ListSkeleton, Page, StatePill, UnreadBadge } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { fromTemplate } from '@/lib/templates'

function greeting() {
  const h = new Date().getHours()
  return h < 5 ? 'Still up?' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function DottieCard({ d }: { d: DottieOut }) {
  return (
    <Link
      to={`/dotties/${d.id}`}
      style={hueStyle(d.hue)}
      className="card group flex flex-col gap-3 transition-shadow hover:shadow-md focus-visible:shadow-md"
    >
      <div className="flex items-start gap-3">
        <DottieAvatar hue={d.hue} state={d.state} size={48} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate font-semibold">{d.name}</p>
            <UnreadBadge n={d.unread} />
          </div>
          <p className="line-clamp-2 text-fg-muted">{d.role || 'No role yet'}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted">
        <StatePill state={d.state} />
        <span>{d.next_run_at ? `next ${relativeTime(d.next_run_at)}` : 'nothing scheduled'}</span>
        <span>{d.last_woke_at ? `woke ${relativeTime(d.last_woke_at)}` : 'never woke'}</span>
      </div>
    </Link>
  )
}

function Starters() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const templates = useQuery(listTemplatesOptions())
  const skills = useQuery(listSkillsOptions())
  const create = useMutation({
    ...createDottieMutation(),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: listDottiesQueryKey() })
      void navigate(`/dotties/${d.id}`)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <EmptyState icon={<DottieAvatar hue={265} size={56} />} title="No dotties yet">
      <p>
        A dottie is a persistent agent with its own memory and computer. It sleeps until you, the clock or another
        dottie wakes it.
      </p>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {templates.data?.map((t) => (
          <button
            key={t.key}
            disabled={create.isPending || !skills.data}
            onClick={() => create.mutate({ body: fromTemplate(t, skills.data ?? []) })}
            className="card flex flex-col items-center gap-2 text-center transition-shadow hover:shadow-md disabled:opacity-60"
            style={hueStyle(t.hue)}
          >
            <DottieAvatar hue={t.hue} state="awake" size={40} />
            <span className="font-medium text-fg">{t.name}</span>
            <span className="text-xs">{t.role}</span>
          </button>
        ))}
      </div>
      <Link to="/dotties/new" className="mt-3 inline-block text-accent hover:underline">
        or design your own
      </Link>
    </EmptyState>
  )
}

export function Overview() {
  const dotties = useQuery(listDottiesOptions())
  const system = useQuery(systemOptions())
  const events = useQuery(listEventsOptions({ query: { limit: 14 } }))
  const bus = useQuery(trafficOptions({ query: { limit: 10 } }))
  return (
    <Page wide>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">{greeting()}.</h1>
        <p className="text-fg-muted">
          {dotties.data
            ? `${dotties.data.filter((d) => d.state === 'awake' || d.state === 'idle').length} awake, ${dotties.data.filter((d) => d.state === 'sleeping').length} asleep.`
            : ' '}
        </p>
      </div>
      {system.data && !system.data.llm_configured && (
        <div role="alert" className="mb-6 flex gap-3 rounded-lg border border-warn/40 bg-warn/10 p-4">
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-warn" />
          <div>
            <p className="font-medium">No model is configured</p>
            <p className="text-fg-muted">
              Dotties can't think until the app has <code className="chip">LLM_BASE_URL</code> and{' '}
              <code className="chip">LLM_MODEL</code> (and <code className="chip">LLM_API_KEY</code> unless it uses a
              managed identity). Set them in the environment and restart.
            </p>
          </div>
        </div>
      )}
      {dotties.isPending && <ListSkeleton rows={3} />}
      {dotties.data?.length === 0 && <Starters />}
      {dotties.data && dotties.data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {dotties.data.map((d) => (
            <DottieCard key={d.id} d={d} />
          ))}
          <Link
            to="/dotties/new"
            className="flex min-h-28 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border text-fg-muted transition-colors hover:border-accent hover:text-accent"
          >
            <Plus className="size-5" /> New dottie
          </Link>
        </div>
      )}
      <div className="mt-8 grid gap-4 lg:grid-cols-2">
        <section className="card" aria-labelledby="live">
          <h2 id="live" className="mb-3 flex items-center gap-2 font-semibold">
            <Activity className="size-4 text-accent" /> Live activity
          </h2>
          {events.isPending && <ListSkeleton rows={4} />}
          {events.data?.length === 0 && <p className="text-fg-muted">Nothing has happened yet.</p>}
          <ul className="space-y-2">
            {events.data?.map((e) => (
              <li key={e.id} className="anim-rise flex items-start gap-2">
                <EventIcon kind={e.kind} className="mt-0.5" />
                <div className="min-w-0 flex-1">
                  <p className="truncate">{e.text || e.kind}</p>
                  <p className="text-xs text-fg-muted">
                    {e.dottie_name} · {relativeTime(e.created_at)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="bus">
          <h2 id="bus" className="mb-3 flex items-center gap-2 font-semibold">
            <ArrowRight className="size-4 text-accent" /> Between dotties
          </h2>
          {bus.data?.length === 0 && (
            <p className="text-fg-muted">When dotties write to each other, the messages show up here.</p>
          )}
          <ul className="space-y-3">
            {bus.data?.map((b) => {
              const hue = dotties.data?.find((d) => d.id === b.message.sender_id)?.hue ?? 265
              return (
                <li key={b.message.id} className="anim-rise">
                  <p className="flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
                    <DottieChip name={b.message.sender_name ?? '?'} hue={hue} /> <ArrowRight className="size-3" />{' '}
                    <span className="font-medium text-fg">{b.recipient_name}</span> ·{' '}
                    {relativeTime(b.message.created_at)}
                  </p>
                  <p className="mt-0.5 line-clamp-2">{b.message.body}</p>
                </li>
              )
            })}
          </ul>
        </section>
      </div>
    </Page>
  )
}
