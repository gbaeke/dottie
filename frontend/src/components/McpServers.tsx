import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Link2, Plus, Plug, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { listSecretsOptions, testServerMutation } from '@/client/@tanstack/react-query.gen'
import type { McpServer, McpTest } from '@/client/types.gen'
import { Spinner } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { isLiteralCredential, refsIn, secretRef, urlHasLiteralCredential } from '@/lib/secrets'
import { cn } from '@/lib/utils'

const MAX_ROWS = 10
type Row = { id: number; key: string; value: string }
type Item = { id: number; name: string; url: string; headers: Row[]; query: Row[] }

let counter = 0
const nextId = () => ++counter
const toRows = (m: Record<string, string> | undefined): Row[] =>
  Object.entries(m ?? {}).map(([key, value]) => ({ id: nextId(), key, value }))
const toRecord = (rows: Row[]): Record<string, string> =>
  Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]))
const fromServer = (s: McpServer): Item => ({
  id: nextId(),
  name: s.name,
  url: s.url,
  headers: toRows(s.headers),
  query: toRows(s.query),
})
const toServer = (i: Item): McpServer => ({
  name: i.name,
  url: i.url,
  headers: toRecord(i.headers),
  query: toRecord(i.query),
})

const TAVILY: McpServer = {
  name: 'tavily',
  url: 'https://mcp.tavily.com/mcp/',
  headers: { Authorization: `Bearer ${secretRef('tavily')}` },
  query: {},
}

/** Key/value rows (headers or query parameters). Each value can take a stored secret instead of typed text. */
function KeyValueRows({
  label,
  rows,
  onChange,
  secretNames,
  keyPlaceholder,
}: {
  label: string
  rows: Row[]
  onChange: (rows: Row[]) => void
  secretNames: string[]
  keyPlaceholder: string
}) {
  const patch = (id: number, p: Partial<Row>) => onChange(rows.map((r) => (r.id === id ? { ...r, ...p } : r)))
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="field-label mb-0">{label}</span>
        <button
          type="button"
          className="btn-ghost px-2 py-0.5 text-xs"
          disabled={rows.length >= MAX_ROWS}
          onClick={() => onChange([...rows, { id: nextId(), key: '', value: '' }])}
        >
          <Plus className="size-3.5" /> Add
        </button>
      </div>
      {rows.length === 0 && <p className="text-xs text-fg-muted">None.</p>}
      <div className="space-y-2">
        {rows.map((r) => {
          const literal = isLiteralCredential(r.key, r.value)
          return (
            <div key={r.id}>
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[11rem_minmax(0,1fr)_auto_auto]">
                <input
                  className="input col-span-2 font-mono sm:col-span-1"
                  aria-label={`${label}: name`}
                  placeholder={keyPlaceholder}
                  spellCheck={false}
                  value={r.key}
                  onChange={(e) => patch(r.id, { key: e.target.value })}
                />
                <input
                  className={cn('input col-span-2 font-mono sm:col-span-1', literal && 'border-warn')}
                  aria-label={`${label}: value`}
                  placeholder="value or {{secret:NAME}}"
                  spellCheck={false}
                  autoComplete="off"
                  value={r.value}
                  onChange={(e) => patch(r.id, { value: e.target.value })}
                />
                <select
                  className="input w-full sm:w-40"
                  aria-label="Use a secret"
                  value=""
                  disabled={secretNames.length === 0}
                  title={secretNames.length === 0 ? 'No secrets yet: add one on the Connect page' : 'Use a secret'}
                  onChange={(e) => e.target.value && patch(r.id, { value: r.value + secretRef(e.target.value) })}
                >
                  <option value="">Use a secret</option>
                  {secretNames.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-ghost p-1.5"
                  aria-label={`Remove ${label.toLowerCase()} row`}
                  onClick={() => onChange(rows.filter((x) => x.id !== r.id))}
                >
                  <X className="size-4" />
                </button>
              </div>
              {literal && (
                <p className="mt-1 text-xs text-warn" role="alert">
                  Keep credentials in a secret: this looks like one. Use the “Use a secret” menu.
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function TestResult({ result }: { result: McpTest }) {
  if (result.problems.length > 0 || (!result.ok && result.tools.length === 0)) {
    return (
      <div className="rounded-md border border-warn/50 bg-warn/10 p-3 text-sm" role="status">
        <p className="mb-1 flex items-center gap-1.5 font-medium">
          <AlertTriangle className="size-4 text-warn" /> It did not connect
        </p>
        <ul className="list-disc pl-5">
          {result.problems.length > 0 ? (
            result.problems.map((p) => <li key={p}>{p}</li>)
          ) : (
            <li>The server answered but offers no tools.</li>
          )}
        </ul>
      </div>
    )
  }
  return (
    <div className="rounded-md border border-ok/50 bg-ok/10 p-3 text-sm" role="status">
      <p className="mb-2 flex items-center gap-1.5 font-medium">
        <CheckCircle2 className="size-4 text-ok" /> Connected: {result.tools.length} tool
        {result.tools.length === 1 ? '' : 's'}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {result.tools.map((t) => (
          <span
            key={t.name}
            title={t.description || t.name}
            className="rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-xs"
          >
            {t.name}
          </span>
        ))}
      </div>
    </div>
  )
}

function ServerEditor({
  item,
  secretNames,
  secretsLoaded,
  onChange,
  onRemove,
}: {
  item: Item
  secretNames: string[]
  secretsLoaded: boolean
  onChange: (p: Partial<Item>) => void
  onRemove: () => void
}) {
  const test = useMutation(testServerMutation())
  const server = toServer(item)
  const used = new Set([...refsIn(item.url), ...[...item.headers, ...item.query].flatMap((r) => refsIn(r.value))])
  const missing = secretsLoaded ? [...used].filter((n) => !secretNames.includes(n)) : []
  const urlLeak = urlHasLiteralCredential(item.url)
  const canTest = item.name.trim() !== '' && item.url.trim() !== ''

  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[10rem_minmax(0,1fr)_auto]">
        <input
          className="input col-span-2 sm:col-span-1"
          aria-label="Server name"
          placeholder="name"
          pattern="[a-zA-Z][a-zA-Z0-9_\-]{0,39}"
          value={item.name}
          onChange={(e) => onChange({ name: e.target.value })}
        />
        <input
          className={cn('input', urlLeak && 'border-warn')}
          type="url"
          aria-label="Server URL"
          placeholder="https://example.com/mcp"
          value={item.url}
          onChange={(e) => onChange({ url: e.target.value })}
        />
        <button type="button" className="btn-ghost p-1.5" aria-label="Remove server" onClick={onRemove}>
          <X className="size-4" />
        </button>
      </div>
      {urlLeak && (
        <p className="text-xs text-warn" role="alert">
          Keep credentials in a secret: the URL has a key in its query. Remove it from the URL and add it under “Query
          parameters” with a secret.
        </p>
      )}

      <div className="space-y-4">
        <KeyValueRows
          label="Headers"
          rows={item.headers}
          onChange={(headers) => onChange({ headers })}
          secretNames={secretNames}
          keyPlaceholder="Authorization"
        />
        <KeyValueRows
          label="Query parameters"
          rows={item.query}
          onChange={(query) => onChange({ query })}
          secretNames={secretNames}
          keyPlaceholder="apiKey"
        />
      </div>

      {missing.length > 0 && (
        <p className="flex flex-wrap items-center gap-1 text-xs text-warn" role="alert">
          <AlertTriangle className="size-3.5" /> Not set yet: {missing.map((n) => secretRef(n)).join(', ')}.
          <Link to="/connect#secrets" className="underline">
            Add it on the Connect page
          </Link>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn-ghost border border-border"
          disabled={!canTest || test.isPending}
          onClick={() => test.mutate({ body: server })}
        >
          {test.isPending ? <Spinner /> : <Plug className="size-4" />} Test connection
        </button>
        {test.isPending && <span className="text-xs text-fg-muted">Connecting, this can take up to 30 seconds…</span>}
      </div>
      {test.isError && (
        <p className="text-sm text-danger" role="alert">
          {errorMessage(test.error)}
        </p>
      )}
      {test.data && !test.isPending && <TestResult result={test.data} />}
    </div>
  )
}

/** The MCP servers of a dottie: URL, headers and query parameters, with stored secrets for anything that is a credential. */
export function McpServers({ initial, onChange }: { initial: McpServer[]; onChange: (servers: McpServer[]) => void }) {
  const secrets = useQuery(listSecretsOptions())
  const secretNames = secrets.data?.map((s) => s.name) ?? []
  const [items, setItems] = useState<Item[]>(() => initial.map(fromServer))
  const first = useRef(true)

  // tell the form whenever the servers change (not on mount: nothing has changed yet)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    onChange(items.map(toServer))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items])

  const patch = (id: number, p: Partial<Item>) =>
    setItems((list) => list.map((i) => (i.id === id ? { ...i, ...p } : i)))
  const addTavily = () =>
    setItems((list) => {
      const taken = new Set(list.map((i) => i.name))
      let name = TAVILY.name
      for (let n = 2; taken.has(name); n++) name = `${TAVILY.name}-${n}`
      return [...list, fromServer({ ...TAVILY, name })]
    })
  const tavilySecretMissing = secrets.data && !secretNames.includes('tavily')
  const hasTavily = items.some((i) => refsIn(i.headers.map((h) => h.value).join(' ')).includes('tavily'))

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <ServerEditor
          key={item.id}
          item={item}
          secretNames={secretNames}
          secretsLoaded={secrets.isSuccess}
          onChange={(p) => patch(item.id, p)}
          onRemove={() => setItems((list) => list.filter((i) => i.id !== item.id))}
        />
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setItems((l) => [...l, { id: nextId(), name: '', url: '', headers: [], query: [] }])}
        >
          <Plus className="size-4" /> Add a server
        </button>
        <button type="button" className="btn-ghost" onClick={addTavily} title="Web search for your dotties">
          <Link2 className="size-4" /> Add Tavily
        </button>
      </div>
      {hasTavily && tavilySecretMissing && (
        <p className="text-xs text-fg-muted">
          Tavily needs your API key as a secret called <code className="font-mono">tavily</code>.{' '}
          <Link to="/connect#secrets" className="underline">
            Add it on the Connect page
          </Link>
          , then test the connection here.
        </p>
      )}
    </div>
  )
}
