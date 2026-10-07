import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, Repeat, Trash2 } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import {
  deleteScheduleMutation,
  listAllQueryKey,
  listSchedulesQueryKey,
  runNowMutation,
  updateScheduleMutation,
} from '@/client/@tanstack/react-query.gen'
import type { ScheduleOut } from '@/client/types.gen'
import { DottieChip, Switch } from '@/components/ui'
import { invalidateFamilies } from '@/lib/live'
import { errorMessage } from '@/lib/api'
import { absoluteTime, describeTiming, relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'

/** One schedule: what, when, last and next run, with the switch, run-now and delete. */
export function ScheduleRow({ s, hue, showDottie }: { s: ScheduleOut; hue: number; showDottie?: boolean }) {
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: listAllQueryKey() })
    void qc.invalidateQueries({ queryKey: listSchedulesQueryKey({ path: { dottie_id: s.dottie_id } }) })
    void invalidateFamilies(qc, ['listDotties'])
  }
  const onError = (e: unknown) => toast.error(errorMessage(e))
  const update = useMutation({ ...updateScheduleMutation(), onSuccess: refresh, onError })
  const run = useMutation({
    ...runNowMutation(),
    onSuccess: () => {
      refresh()
      toast.success('Sent. It is waking up.')
    },
    onError,
  })
  const remove = useMutation({ ...deleteScheduleMutation(), onSuccess: refresh, onError })
  return (
    <li className={cn('card flex flex-wrap items-center gap-x-4 gap-y-2', !s.enabled && 'opacity-70')}>
      <div className="min-w-0 flex-1 basis-60">
        <p className="flex flex-wrap items-center gap-2 font-medium">
          {s.title}
          {showDottie && (
            <Link to={`/dotties/${s.dottie_id}`}>
              <DottieChip name={s.dottie_name} hue={hue} />
            </Link>
          )}
          {s.created_by === 'dottie' && <span className="chip">set by the dottie</span>}
        </p>
        <p className="mt-0.5 flex items-center gap-1.5 text-fg-muted">
          <Repeat className="size-3.5" /> {describeTiming(s)} <span className="text-xs">({s.timezone})</span>
        </p>
        <p className="mt-1 line-clamp-2 text-xs text-fg-muted">{s.prompt}</p>
      </div>
      <div className="text-xs text-fg-muted">
        <p title={s.next_run_at ? absoluteTime(s.next_run_at) : undefined}>
          Next: {s.enabled && s.next_run_at ? relativeTime(s.next_run_at) : s.enabled ? 'finished' : 'paused'}
        </p>
        <p>Last: {s.last_run_at ? relativeTime(s.last_run_at) : 'never'}</p>
      </div>
      <div className="flex items-center gap-1">
        <Switch
          checked={s.enabled}
          label={`${s.enabled ? 'Pause' : 'Enable'} ${s.title}`}
          onChange={(enabled) => update.mutate({ path: { schedule_id: s.id }, body: { enabled } })}
        />
        <button
          className="btn-ghost"
          onClick={() => run.mutate({ path: { schedule_id: s.id } })}
          disabled={run.isPending}
          aria-label={`Run ${s.title} now`}
        >
          <Play className="size-4" /> Run now
        </button>
        <button
          className="btn-ghost p-1.5"
          aria-label={`Delete ${s.title}`}
          onClick={() => window.confirm(`Delete "${s.title}"?`) && remove.mutate({ path: { schedule_id: s.id } })}
        >
          <Trash2 className="size-4" />
        </button>
      </div>
    </li>
  )
}
