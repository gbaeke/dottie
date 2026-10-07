import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LockKeyhole, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import {
  deleteSecretMutation,
  listSecretsOptions,
  listSecretsQueryKey,
  setSecretMutation,
} from '@/client/@tanstack/react-query.gen'
import type { SecretOut } from '@/client/types.gen'
import { EmptyState, ListSkeleton, Spinner } from '@/components/ui'
import { ApiError, errorMessage } from '@/lib/api'
import { absoluteTime, relativeTime } from '@/lib/format'
import { SECRET_NAME, secretRef } from '@/lib/secrets'

const isOff = (e: unknown) => e instanceof ApiError && e.code === 'not_configured'

/** A password field for a value that must never be kept or shown: no autofill, no manager, cleared by its parent. */
function ValueInput({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  return (
    <input
      id={id}
      className="input font-mono"
      type="password"
      autoComplete="new-password"
      data-1p-ignore
      data-lpignore="true"
      spellCheck={false}
      maxLength={8000}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="The value (shown once, here)"
    />
  )
}

function SecretRow({ s, onOff }: { s: SecretOut; onOff: () => void }) {
  const qc = useQueryClient()
  const [replacing, setReplacing] = useState(false)
  const [value, setValue] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: listSecretsQueryKey() })
  const save = useMutation({
    ...setSecretMutation(),
    onSuccess: () => {
      setValue('') // a typed value is not kept once it is saved
      setReplacing(false)
      toast.success(`Secret "${s.name}" replaced.`)
      void refresh()
    },
    onError: (e) => (isOff(e) ? onOff() : toast.error(errorMessage(e))),
  })
  const remove = useMutation({
    ...deleteSecretMutation(),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(errorMessage(e)), // 409 in_use: the server says who uses it
  })
  const used = s.used_by.length > 0

  return (
    <li className="card py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <code className="font-mono font-medium">{s.name}</code>
            <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-xs text-fg-muted">
              {s.hint ? `…${s.hint}` : 'set'}
            </span>
            {s.used_by.map((d) => (
              <span key={d} className="rounded-full bg-dot-soft px-2 py-0.5 text-xs text-dot-ink">
                used by {d}
              </span>
            ))}
          </p>
          <p className="text-xs text-fg-muted" title={absoluteTime(s.updated_at)}>
            Updated {relativeTime(s.updated_at)} · use it as <code className="font-mono">{secretRef(s.name)}</code>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => setReplacing((r) => !r)}>
            {replacing ? 'Cancel' : 'Replace value'}
          </button>
          <button
            type="button"
            className="btn-ghost p-1.5"
            aria-label={`Delete secret ${s.name}`}
            title={used ? `In use by ${s.used_by.join(', ')}: remove it from their MCP servers first` : 'Delete'}
            disabled={used || remove.isPending}
            onClick={() =>
              window.confirm(`Delete the secret "${s.name}"? It cannot be recovered.`) &&
              remove.mutate({ path: { name: s.name } })
            }
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      </div>
      {replacing && (
        <form
          className="mt-2 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate({ path: { name: s.name }, body: { value } })
          }}
        >
          <label className="sr-only" htmlFor={`replace-${s.name}`}>
            New value for {s.name}
          </label>
          <ValueInput id={`replace-${s.name}`} value={value} onChange={setValue} />
          <button className="btn-primary justify-center" disabled={!value || save.isPending}>
            {save.isPending && <Spinner />} Save
          </button>
        </form>
      )}
    </li>
  )
}

/** The user's secrets: write-only. Names and hints are listed; a value can be set or replaced, never read back. */
export function Secrets() {
  const qc = useQueryClient()
  const secrets = useQuery(listSecretsOptions())
  const [name, setName] = useState('')
  const [value, setValue] = useState('')
  const [off, setOff] = useState(false)
  const exists = secrets.data?.some((s) => s.name === name.trim())

  const save = useMutation({
    ...setSecretMutation(),
    onSuccess: (s) => {
      setName('')
      setValue('') // a typed value is not kept once it is saved
      toast.success(`Secret "${s.name}" saved.`)
      void qc.invalidateQueries({ queryKey: listSecretsQueryKey() })
    },
    onError: (e) => (isOff(e) ? setOff(true) : toast.error(errorMessage(e))),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate({ path: { name: name.trim() }, body: { value } })
  }

  return (
    <section id="secrets" className="mb-8 scroll-mt-4" aria-labelledby="secrets-title">
      <h2 id="secrets-title" className="mb-1 flex items-center gap-2 font-medium">
        <LockKeyhole className="size-4" /> Secrets
      </h2>
      <p className="mb-3 text-sm text-fg-muted">
        Values you store here are encrypted and can never be shown again. Reference one in an MCP server as{' '}
        <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{'{{secret:NAME}}'}</code>; it is filled in
        only when a dottie connects, and never reaches its sandbox.
      </p>

      {off ? (
        <p className="mb-3 rounded-md border border-warn/50 bg-warn/10 p-3 text-sm" role="status">
          Secrets are switched off on this installation: the app has no <code className="font-mono">SECRETS_KEY</code>.
          Ask whoever runs it to set one.
        </p>
      ) : (
        <form onSubmit={submit} className="card mb-3 space-y-2" autoComplete="off">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,14rem)_1fr_auto]">
            <div>
              <label className="field-label" htmlFor="secret-name">
                Name
              </label>
              <input
                id="secret-name"
                className="input font-mono"
                required
                maxLength={40}
                pattern={SECRET_NAME}
                title="Letters, digits, - and _, starting with a letter"
                autoComplete="off"
                spellCheck={false}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="tavily"
              />
            </div>
            <div>
              <label className="field-label" htmlFor="secret-value">
                Value
              </label>
              <ValueInput id="secret-value" value={value} onChange={setValue} />
            </div>
            <div className="flex items-end">
              <button className="btn-primary w-full justify-center" disabled={!name.trim() || !value || save.isPending}>
                {save.isPending && <Spinner />} Save secret
              </button>
            </div>
          </div>
          {exists && (
            <p className="text-xs text-warn">A secret called “{name.trim()}” exists: saving replaces its value.</p>
          )}
        </form>
      )}

      {secrets.isPending && <ListSkeleton rows={2} />}
      {secrets.isError && <p className="text-danger">{errorMessage(secrets.error)}</p>}
      {secrets.data?.length === 0 && (
        <EmptyState icon={<LockKeyhole className="size-6" />} title="No secrets yet">
          Add an API key above, then use it in a dottie's MCP server.
        </EmptyState>
      )}
      <ul className="space-y-2">
        {secrets.data?.map((s) => (
          <SecretRow key={s.name} s={s} onOff={() => setOff(true)} />
        ))}
      </ul>
    </section>
  )
}
