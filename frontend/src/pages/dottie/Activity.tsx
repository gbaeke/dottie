import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Moon, Sun } from 'lucide-react'
import { listDottieEventsInfiniteOptions, listRunsOptions } from '@/client/@tanstack/react-query.gen'
import type { EventOut } from '@/client/types.gen'
import { EventIcon } from '@/components/EventLine'
import { EmptyState, ListSkeleton } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { absoluteTime, relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useDottie } from '@/lib/dottie-context'

const PAGE = 60
const pageOf = (dottieId: number, before?: number) => ({
  path: { dottie_id: dottieId },
  query: { limit: PAGE, ...(before === undefined ? {} : { before }) },
})

/** Events newest first → one group per run. Events outside a run (going back to sleep) belong to the run before them. */
function byRun(events: EventOut[]) {
  const groups: { key: string; runId: number | null; events: EventOut[] }[] = []
  let loose: EventOut[] = []
  for (const e of events) {
    if (e.run_id === null) {
      loose.push(e)
      continue
    }
    const last = groups.at(-1)
    if (last && last.runId === e.run_id) last.events.push(...loose, e)
    else groups.push({ key: `${e.id}`, runId: e.run_id, events: [...loose, e] })
    loose = []
  }
  if (loose.length) groups.push({ key: `loose-${loose[0]?.id}`, runId: null, events: loose })
  return groups
}

const TRIGGER = { user: 'You wrote', scheduler: 'A schedule fired', dottie: 'Another dottie wrote' } as const

export function Activity() {
  const d = useDottie()
  const key = { path: { dottie_id: d.id }, query: { limit: PAGE } }
  const events = useInfiniteQuery({
    ...listDottieEventsInfiniteOptions(key),
    initialPageParam: pageOf(d.id),
    getNextPageParam: (last: EventOut[]) => (last.length < PAGE ? undefined : pageOf(d.id, last.at(-1)?.id)),
  })
  const runs = useQuery(listRunsOptions({ path: { dottie_id: d.id }, query: { limit: 100 } }))
  const all = events.data?.pages.flat() ?? []
  const runById = new Map(runs.data?.map((r) => [r.id, r]))
  return (
    <div className="mx-auto max-w-3xl p-4 md:p-8">
      {events.isPending && <ListSkeleton rows={4} />}
      {events.isError && <p className="text-danger">{errorMessage(events.error)}</p>}
      {all.length === 0 && !events.isPending && (
        <EmptyState icon={<Moon className="size-6" />} title="Nothing yet">
          When {d.name} wakes up and does something, it shows here.
        </EmptyState>
      )}
      <div className="space-y-4">
        {byRun(all).map((g) => {
          const run = g.runId === null ? undefined : runById.get(g.runId)
          return (
            <section key={g.key} className="card">
              {run && (
                <div className="mb-2 flex flex-wrap items-center gap-2 border-b border-border pb-2">
                  <Sun className="size-4 text-warn" />
                  <span className="font-medium">{TRIGGER[run.trigger as keyof typeof TRIGGER] ?? run.trigger}</span>
                  <span
                    className={cn(
                      'rounded-full px-2 py-0.5 text-xs font-medium',
                      run.status === 'done' && 'bg-ok/15 text-ok',
                      run.status === 'failed' && 'bg-danger/15 text-danger',
                      run.status === 'running' && 'bg-warn/15 text-warn',
                    )}
                  >
                    {run.status}
                  </span>
                  <span className="ml-auto text-xs text-fg-muted" title={absoluteTime(run.started_at)}>
                    {relativeTime(run.started_at)}
                  </span>
                  {run.summary && <p className="basis-full text-xs text-fg-muted">{run.summary}</p>}
                </div>
              )}
              <ol className="space-y-1.5">
                {[...g.events].reverse().map((e) => (
                  <li key={e.id} className="flex items-start gap-2" title={absoluteTime(e.created_at)}>
                    <EventIcon kind={e.kind} className="mt-0.5" />
                    <p
                      className={cn(
                        'min-w-0 flex-1 break-words',
                        e.kind === 'tool' && 'font-mono text-[13px]',
                        e.kind === 'tool_result' && 'text-xs text-fg-muted',
                      )}
                    >
                      {e.text || e.kind}
                    </p>
                    <span className="shrink-0 text-xs text-fg-muted">{relativeTime(e.created_at)}</span>
                  </li>
                ))}
              </ol>
            </section>
          )
        })}
      </div>
      {events.hasNextPage && (
        <button
          className="btn-ghost mx-auto mt-4"
          onClick={() => void events.fetchNextPage()}
          disabled={events.isFetchingNextPage}
        >
          Load older
        </button>
      )}
    </div>
  )
}
