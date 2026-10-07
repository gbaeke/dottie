import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarPlus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import {
  createScheduleMutation,
  listAllQueryKey,
  listSchedulesOptions,
  listSchedulesQueryKey,
  systemOptions,
} from '@/client/@tanstack/react-query.gen'
import { ScheduleRow } from '@/components/ScheduleRow'
import { EmptyState, ListSkeleton } from '@/components/ui'
import { invalidateFamilies } from '@/lib/live'
import { ApiError, errorMessage } from '@/lib/api'
import { humanizeCron, PRESETS, presetCron, type Preset } from '@/lib/format'
import { useDottie } from '@/lib/dottie-context'

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

function NewSchedule({ dottieId, onDone }: { dottieId: number; onDone: () => void }) {
  const qc = useQueryClient()
  const system = useQuery(systemOptions())
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [preset, setPreset] = useState<Preset>('weekdays')
  const [time, setTime] = useState('08:00')
  const [day, setDay] = useState(1)
  const [custom, setCustom] = useState('0 8 * * 1-5')
  const [at, setAt] = useState('')
  const [timezone, setTimezone] = useState<string | null>(null)
  const tz = timezone ?? system.data?.timezone ?? 'UTC'
  const cron = presetCron(preset, time, day, custom)
  const create = useMutation({
    ...createScheduleMutation(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: listSchedulesQueryKey({ path: { dottie_id: dottieId } }) })
      void qc.invalidateQueries({ queryKey: listAllQueryKey() })
      void invalidateFamilies(qc, ['listDotties'])
      toast.success('Scheduled')
      onDone()
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate({
      path: { dottie_id: dottieId },
      body: {
        title,
        prompt,
        timezone: tz,
        ...(preset === 'once' ? { run_at: at ? new Date(at).toISOString() : null } : { cron }),
      },
    })
  }
  const apiError = create.error instanceof ApiError ? create.error : null
  return (
    <form onSubmit={submit} className="card space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="field-label" htmlFor="s-title">
            Title
          </label>
          <input
            id="s-title"
            className="input"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Morning briefing"
          />
        </div>
        <div>
          <label className="field-label" htmlFor="s-preset">
            Repeats
          </label>
          <select id="s-preset" className="input" value={preset} onChange={(e) => setPreset(e.target.value as Preset)}>
            {PRESETS.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        {(preset === 'weekdays' || preset === 'daily' || preset === 'weekly') && (
          <div>
            <label className="field-label" htmlFor="s-time">
              At
            </label>
            <input
              id="s-time"
              type="time"
              className="input"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              required
            />
          </div>
        )}
        {preset === 'weekly' && (
          <div>
            <label className="field-label" htmlFor="s-day">
              On
            </label>
            <select id="s-day" className="input" value={day} onChange={(e) => setDay(Number(e.target.value))}>
              {DAY_NAMES.map((n, i) => (
                <option key={n} value={i}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        )}
        {preset === 'hourly' && (
          <div>
            <label className="field-label" htmlFor="s-min">
              At minute
            </label>
            <input
              id="s-min"
              type="number"
              min={0}
              max={59}
              className="input w-24"
              value={Number(time.split(':')[1] ?? 0)}
              onChange={(e) => setTime(`08:${e.target.value.padStart(2, '0')}`)}
            />
          </div>
        )}
        {preset === 'once' && (
          <div>
            <label className="field-label" htmlFor="s-at">
              When
            </label>
            <input
              id="s-at"
              type="datetime-local"
              className="input"
              required
              value={at}
              onChange={(e) => setAt(e.target.value)}
            />
          </div>
        )}
        {preset === 'custom' && (
          <div className="min-w-48 flex-1">
            <label className="field-label" htmlFor="s-cron">
              Cron (minute hour day month weekday)
            </label>
            <input id="s-cron" className="input font-mono" value={custom} onChange={(e) => setCustom(e.target.value)} />
          </div>
        )}
        <div>
          <label className="field-label" htmlFor="s-tz">
            Timezone
          </label>
          <input
            id="s-tz"
            className="input w-48"
            value={tz}
            onChange={(e) => setTimezone(e.target.value)}
            placeholder="Europe/Brussels"
          />
        </div>
      </div>
      {preset !== 'once' && cron && (
        <p className="text-xs text-fg-muted">
          {humanizeCron(cron)} <span className="font-mono">({cron})</span>
        </p>
      )}
      <div>
        <label className="field-label" htmlFor="s-prompt">
          What should it do? Write it as complete instructions: it wakes with only this.
        </label>
        <textarea
          id="s-prompt"
          className="input min-h-24"
          required
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Summarise what changed in my projects since yesterday and tell me what needs a decision."
        />
      </div>
      {apiError && (
        <p role="alert" className="text-danger">
          {apiError.message}
        </p>
      )}
      {create.isError && !apiError && <p className="text-danger">{errorMessage(create.error)}</p>}
      <div className="flex gap-2">
        <button className="btn-primary" disabled={create.isPending}>
          Schedule
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}

export function Schedules() {
  const d = useDottie()
  const schedules = useQuery(listSchedulesOptions({ path: { dottie_id: d.id } }))
  const [adding, setAdding] = useState(false)
  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 md:p-8">
      <div className="flex items-center justify-between gap-3">
        <p className="text-fg-muted">
          {d.name} sleeps between tasks; the clock wakes {d.name} when one is due. You can also just ask in chat.
        </p>
        {!adding && (
          <button className="btn-primary shrink-0" onClick={() => setAdding(true)}>
            <CalendarPlus className="size-4" /> New schedule
          </button>
        )}
      </div>
      {adding && <NewSchedule dottieId={d.id} onDone={() => setAdding(false)} />}
      {schedules.isPending && <ListSkeleton rows={2} />}
      {schedules.data?.length === 0 && !adding && (
        <EmptyState title="Nothing scheduled">A morning briefing or a weekly review is a good first one.</EmptyState>
      )}
      <ul className="space-y-3">
        {schedules.data?.map((s) => (
          <ScheduleRow key={s.id} s={s} hue={d.hue} />
        ))}
      </ul>
    </div>
  )
}
