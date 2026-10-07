import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { listSkillsOptions, listToolkitsOptions } from '@/client/@tanstack/react-query.gen'
import type { DottieIn } from '@/client/types.gen'
import { DottieAvatar } from '@/components/DottieAvatar'
import { McpServers } from '@/components/McpServers'
import { hueStyle } from '@/lib/hue'
import { HUES } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Everything about a dottie that a person decides: used to create one and to change it. */
export function DottieForm({
  initial,
  submitLabel,
  pending,
  onSubmit,
  children,
}: {
  initial: DottieIn
  submitLabel: string
  pending: boolean
  onSubmit: (value: DottieIn) => void
  children?: ReactNode
}) {
  const toolkits = useQuery(listToolkitsOptions())
  const skills = useQuery(listSkillsOptions())
  const [v, setV] = useState<DottieIn>(initial)
  const set = <K extends keyof DottieIn>(key: K, value: DottieIn[K]) => setV((p) => ({ ...p, [key]: value }))
  const toggle = <T,>(list: T[] | undefined, item: T) =>
    list?.includes(item) ? list.filter((x) => x !== item) : [...(list ?? []), item]
  const servers = v.mcp_servers ?? []
  const hue = v.hue ?? 250

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit({ ...v, model: v.model?.trim() || null, mcp_servers: servers.filter((s) => s.name && s.url) })
  }

  return (
    <form onSubmit={submit} className="space-y-6" style={hueStyle(hue)}>
      <section className="card space-y-4">
        <div className="flex items-center gap-4">
          <DottieAvatar hue={hue} state="awake" size={64} />
          <div className="grid flex-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="field-label" htmlFor="d-name">
                Name
              </label>
              <input
                id="d-name"
                className="input"
                required
                maxLength={80}
                value={v.name}
                onChange={(e) => set('name', e.target.value)}
              />
            </div>
            <div>
              <label className="field-label" htmlFor="d-role">
                What is it for?
              </label>
              <input
                id="d-role"
                className="input"
                maxLength={200}
                value={v.role ?? ''}
                onChange={(e) => set('role', e.target.value)}
                placeholder="Keeps track of my projects"
              />
            </div>
          </div>
        </div>
        <div>
          <span className="field-label">Colour</span>
          <div className="flex flex-wrap items-center gap-2">
            {HUES.map((h) => (
              <button
                key={h}
                type="button"
                aria-label={`Hue ${h}`}
                aria-pressed={h === hue}
                onClick={() => set('hue', h)}
                className={cn('size-7 rounded-full ring-offset-2 ring-offset-surface', h === hue && 'ring-2 ring-fg')}
                style={{ background: `oklch(0.74 0.14 ${h})` }}
              />
            ))}
            <input
              type="range"
              min={0}
              max={360}
              value={hue}
              onChange={(e) => set('hue', Number(e.target.value))}
              aria-label="Hue"
              className="w-40 accent-dot"
            />
          </div>
        </div>
        <div>
          <label className="field-label" htmlFor="d-personality">
            Personality: how it thinks, talks and what it cares about
          </label>
          <textarea
            id="d-personality"
            className="input min-h-32"
            maxLength={8000}
            value={v.personality ?? ''}
            onChange={(e) => set('personality', e.target.value)}
            placeholder="Calm and brief. Pushes back when something doesn't add up."
          />
        </div>
      </section>

      <section className="card space-y-3">
        <h2 className="font-semibold">What it can do</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {toolkits.data?.map((t) => {
            const on = v.tools?.includes(t.key) ?? false
            return (
              <label
                key={t.key}
                className={cn(
                  'flex cursor-pointer gap-3 rounded-md border p-3',
                  on ? 'border-dot bg-dot-soft' : 'border-border',
                )}
              >
                <input
                  type="checkbox"
                  className="mt-1 accent-dot"
                  checked={on}
                  onChange={() => set('tools', toggle(v.tools, t.key))}
                />
                <span>
                  <span className="block font-medium capitalize">{t.key}</span>
                  <span className="text-xs text-fg-muted">{t.description}</span>
                </span>
              </label>
            )
          })}
        </div>
        <div>
          <span className="field-label">Skills</span>
          <div className="flex flex-wrap gap-2">
            {skills.data?.map((s) => {
              const on = v.skill_ids?.includes(s.id) ?? false
              return (
                <button
                  key={s.id}
                  type="button"
                  aria-pressed={on}
                  title={s.description}
                  onClick={() => set('skill_ids', toggle(v.skill_ids, s.id))}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs',
                    on
                      ? 'border-dot bg-dot-soft font-medium text-dot-ink'
                      : 'border-border text-fg-muted hover:text-fg',
                  )}
                >
                  {s.name}
                </button>
              )
            })}
          </div>
        </div>
      </section>

      <section className="card space-y-3">
        <h2 className="font-semibold">Connections (MCP servers)</h2>
        <p className="text-xs text-fg-muted">
          Remote MCP servers (streamable HTTP). Their tools become this dottie's tools. Put API keys in a secret, not in
          the URL or a header.
        </p>
        <McpServers initial={servers} onChange={(list) => set('mcp_servers', list)} />
        <details className="text-fg-muted">
          <summary className="cursor-pointer text-xs">Advanced</summary>
          <div className="mt-2 max-w-sm">
            <label className="field-label" htmlFor="d-model">
              Model override (a deployment name; empty uses the app's default)
            </label>
            <input
              id="d-model"
              className="input"
              value={v.model ?? ''}
              onChange={(e) => set('model', e.target.value)}
            />
          </div>
        </details>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={pending || !v.name.trim()}>
          {submitLabel}
        </button>
        {children}
      </div>
    </form>
  )
}
