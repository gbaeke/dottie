import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, Plug, Trash2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useLocation } from 'react-router'
import { toast } from 'sonner'
import {
  createTokenMutation,
  deleteTokenMutation,
  listTokensOptions,
  listTokensQueryKey,
} from '@/client/@tanstack/react-query.gen'
import { Secrets } from '@/components/Secrets'
import { Telegram } from '@/components/Telegram'
import { EmptyState, ListSkeleton, Page, PageTitle, Spinner } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { absoluteTime, relativeTime } from '@/lib/format'

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!done) return
    const t = setTimeout(() => setDone(false), 1800)
    return () => clearTimeout(t)
  }, [done])
  return (
    <button
      type="button"
      className="btn-ghost shrink-0 p-1.5"
      aria-label={label}
      title={label}
      onClick={() =>
        navigator.clipboard.writeText(text).then(
          () => setDone(true),
          () => toast.error('Could not copy: select the text and copy it by hand.'),
        )
      }
    >
      {done ? <Check className="size-4 text-ok" /> : <Copy className="size-4" />}
    </button>
  )
}

/** The config another tool needs. `token` is the one just made, if any; otherwise a placeholder to fill in. */
const snippet = (url: string, token: string) =>
  JSON.stringify({ dottie: { type: 'http', url, headers: { Authorization: `Bearer ${token}` } } }, null, 2)

export function Connect() {
  const qc = useQueryClient()
  const tokens = useQuery(listTokensOptions())
  const url = `${window.location.origin}/mcp/`
  const { hash } = useLocation()
  useEffect(() => {
    // the MCP editor links to #secrets: React Router does not scroll to an anchor by itself
    if (hash === '#secrets') document.getElementById('secrets')?.scrollIntoView({ block: 'start' })
  }, [hash])
  const [name, setName] = useState('')
  const [fresh, setFresh] = useState<{ name: string; token: string } | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: listTokensQueryKey() })
  const onError = (e: unknown) => toast.error(errorMessage(e))

  // a token is shown once: it is dropped when the page is left (the state goes with the component)
  const create = useMutation({
    ...createTokenMutation(),
    onSuccess: (t) => {
      setFresh({ name: t.name, token: t.token })
      setName('')
      void refresh()
    },
    onError,
  })
  const remove = useMutation({ ...deleteTokenMutation(), onSuccess: refresh, onError })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setFresh(null)
    create.mutate({ body: { name: name.trim() } })
  }

  return (
    <Page>
      <PageTitle title="Connect" sub="Secrets for your dotties' tools, and access to your dotties from other tools." />
      <Secrets />
      <Telegram />
      <h2 className="mb-1 font-medium">Use your dotties from other tools</h2>
      <p className="mb-4 text-sm text-fg-muted">
        Your dotties answer on <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{url}</code>. A tool
        signs in with a personal access token, sent as a Bearer token, and then sees only your dotties: it can list
        them, ask one something and read its wiki. Make a token for each tool, and delete it when you stop using it.
      </p>

      <section className="card mb-6" aria-labelledby="config-title">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 id="config-title" className="font-medium">
            Configuration
          </h2>
          <CopyButton text={snippet(url, fresh?.token ?? '<token>')} label="Copy the configuration" />
        </div>
        <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
          {snippet(url, fresh?.token ?? '<token>')}
        </pre>
        {!fresh && <p className="mt-2 text-xs text-fg-muted">Make a token below and it is filled in here.</p>}
      </section>

      {fresh && (
        <section
          className="mb-6 rounded-lg border border-ok/50 bg-ok/10 p-4"
          role="status"
          aria-live="polite"
          aria-label="New token"
        >
          <div className="mb-1 flex items-center gap-2 font-medium">
            <KeyRound className="size-4 text-ok" /> Token “{fresh.name}” is ready
          </div>
          <p className="mb-2 text-sm">
            Copy it now. It <strong>cannot be shown again</strong>: only a fingerprint is kept. If you lose it, make a
            new one.
          </p>
          <div className="flex items-center gap-1 rounded-md border border-border bg-surface px-3 py-2">
            <code className="min-w-0 flex-1 font-mono text-xs break-all" data-testid="new-token">
              {fresh.token}
            </code>
            <CopyButton text={fresh.token} label="Copy the token" />
          </div>
          <button type="button" className="btn-ghost mt-2 px-2 py-1 text-xs" onClick={() => setFresh(null)}>
            I have copied it, hide it
          </button>
        </section>
      )}

      <section aria-labelledby="tokens-title">
        <h2 id="tokens-title" className="mb-2 font-medium">
          Personal access tokens
        </h2>
        <form onSubmit={submit} className="mb-4 flex flex-col gap-2 sm:flex-row">
          <label className="sr-only" htmlFor="token-name">
            Token name
          </label>
          <input
            id="token-name"
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="What it is for, e.g. claude code on my laptop"
            maxLength={80}
          />
          <button className="btn-primary justify-center" disabled={!name.trim() || create.isPending}>
            {create.isPending && <Spinner />} Make a token
          </button>
        </form>

        {tokens.isPending && <ListSkeleton />}
        {tokens.isError && <p className="text-danger">{errorMessage(tokens.error)}</p>}
        {tokens.data?.length === 0 && (
          <EmptyState icon={<Plug className="size-6" />} title="No tokens yet">
            Make one above to connect a tool.
          </EmptyState>
        )}
        <ul className="space-y-2">
          {tokens.data?.map((t) => (
            <li key={t.id} className="card flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate font-medium">{t.name}</p>
                <p className="text-xs text-fg-muted">
                  <span title={absoluteTime(t.created_at)}>Made {relativeTime(t.created_at)}</span>
                  {' · '}
                  {t.last_used_at ? (
                    <span title={absoluteTime(t.last_used_at)}>last used {relativeTime(t.last_used_at)}</span>
                  ) : (
                    'never used'
                  )}
                </p>
              </div>
              <button
                className="btn-ghost shrink-0 p-1.5"
                aria-label={`Delete token ${t.name}`}
                title="Delete"
                disabled={remove.isPending}
                onClick={() =>
                  window.confirm(`Delete the token "${t.name}"? Tools that use it stop working.`) &&
                  remove.mutate({ path: { token_id: t.id } })
                }
              >
                <Trash2 className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      </section>
    </Page>
  )
}
