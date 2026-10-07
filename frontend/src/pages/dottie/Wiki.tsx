import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FilePlus, FileText, Folder, Pencil, Trash2 } from 'lucide-react'
import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import {
  deletePageMutation,
  listPagesOptions,
  listPagesQueryKey,
  readPageOptions,
  readPageQueryKey,
  writePageMutation,
} from '@/client/@tanstack/react-query.gen'
import type { PageSummary } from '@/client/types.gen'
import { Markdown } from '@/components/Markdown'
import { EmptyState, ListSkeleton, Skeleton } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { absoluteTime, relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useDottie } from '@/lib/dottie-context'

type Group = { folder: string; pages: PageSummary[] }

function group(pages: PageSummary[]): Group[] {
  const by = new Map<string, PageSummary[]>()
  for (const p of pages) {
    const i = p.path.lastIndexOf('/')
    const folder = i < 0 ? '' : p.path.slice(0, i)
    by.set(folder, [...(by.get(folder) ?? []), p])
  }
  const rank = (p: PageSummary) => (p.path === 'index.md' ? 0 : 1)
  return [...by.entries()]
    .sort(([a], [b]) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b)))
    .map(([folder, ps]) => ({ folder, pages: ps.sort((a, b) => rank(a) - rank(b) || a.path.localeCompare(b.path)) }))
}

const WhoBadge = ({ by }: { by: string }) => (
  <span
    className={cn(
      'rounded-full px-1.5 text-[10px] font-medium',
      by === 'user' ? 'bg-accent-soft text-accent' : 'bg-dot-soft text-dot-ink',
    )}
  >
    {by === 'user' ? 'you' : 'dottie'}
  </span>
)

export function Wiki() {
  const d = useDottie()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const pages = useQuery(listPagesOptions({ path: { dottie_id: d.id } }))
  const selected = params.get('p') ?? 'index.md'
  const open = (path: string) => setParams({ p: path })
  const pageKey = { path: { dottie_id: d.id, path: selected } }
  const page = useQuery({ ...readPageOptions(pageKey), retry: false })
  const [draft, setDraft] = useState<string | null>(null) // null: reading
  const [naming, setNaming] = useState<string | null>(null)
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: listPagesQueryKey({ path: { dottie_id: d.id } }) })
    void qc.invalidateQueries({ queryKey: readPageQueryKey(pageKey) })
  }
  const save = useMutation({
    ...writePageMutation(),
    onSuccess: () => {
      refresh()
      setDraft(null)
      toast.success('Saved')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    ...deletePageMutation(),
    onSuccess: () => {
      refresh()
      setParams({})
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const resolve = (target: string) => {
    const t = target.replace(/^\/+/, '')
    const file = t.endsWith('.md') ? t : `${t}.md`
    const all = pages.data ?? []
    return (
      all.find((p) => p.path === file)?.path ??
      all.find((p) => p.path.split('/').pop() === file.split('/').pop())?.path ??
      file
    )
  }
  const doSave = () =>
    draft !== null && save.mutate({ path: { dottie_id: d.id, path: selected }, body: { content: draft } })
  const onKey = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault()
      doSave()
    }
  }
  const create = (e: FormEvent) => {
    e.preventDefault()
    const raw = (naming ?? '').trim().replace(/^\/+/, '')
    if (!raw) return
    open(raw.endsWith('.md') ? raw : `${raw}.md`)
    setDraft('')
    setNaming(null)
  }
  const missing = page.isError
  const content = page.data?.content ?? ''

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      <aside className="max-h-56 shrink-0 overflow-y-auto border-b border-border p-2 md:max-h-none md:w-64 md:border-r md:border-b-0">
        {naming === null ? (
          <button className="btn-ghost w-full" onClick={() => setNaming('')}>
            <FilePlus className="size-4" /> New page
          </button>
        ) : (
          <form onSubmit={create} className="flex gap-1">
            <input
              autoFocus
              className="input"
              placeholder="people/anna"
              value={naming}
              onChange={(e) => setNaming(e.target.value)}
              aria-label="New page path"
              onKeyDown={(e) => e.key === 'Escape' && setNaming(null)}
            />
          </form>
        )}
        {pages.isPending && <ListSkeleton rows={4} className="mt-2" />}
        <nav className="mt-2 space-y-2" aria-label="Wiki pages">
          {group(pages.data ?? []).map((g) => (
            <div key={g.folder}>
              {g.folder && (
                <p className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-fg-muted">
                  <Folder className="size-3.5" /> {g.folder}
                </p>
              )}
              {g.pages.map((p) => (
                <button
                  key={p.path}
                  onClick={() => {
                    setDraft(null)
                    open(p.path)
                  }}
                  aria-current={p.path === selected}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left',
                    g.folder && 'pl-5',
                    p.path === selected ? 'bg-dot-soft font-medium' : 'text-fg-muted hover:bg-muted hover:text-fg',
                  )}
                >
                  <FileText className="size-3.5 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{p.path.split('/').pop()}</span>
                  <WhoBadge by={p.updated_by} />
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <section className="min-w-0 flex-1 overflow-y-auto p-4 md:p-6" onKeyDown={onKey}>
        {page.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : missing && draft === null ? (
          <EmptyState title={`${selected} doesn't exist`}>
            <button className="btn-primary" onClick={() => setDraft('')}>
              Create it
            </button>
          </EmptyState>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-mono text-sm font-medium">{selected}</p>
                {page.data && (
                  <p className="text-xs text-fg-muted" title={absoluteTime(page.data.updated_at)}>
                    updated {relativeTime(page.data.updated_at)} by {page.data.updated_by === 'user' ? 'you' : d.name}
                  </p>
                )}
              </div>
              <div className="flex gap-1">
                {draft === null ? (
                  <>
                    <button className="btn-ghost" onClick={() => setDraft(content)}>
                      <Pencil className="size-4" /> Edit
                    </button>
                    <button
                      className="btn-ghost p-1.5"
                      aria-label={`Delete ${selected}`}
                      onClick={() =>
                        window.confirm(`Delete ${selected}?`) &&
                        remove.mutate({ path: { dottie_id: d.id, path: selected } })
                      }
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </>
                ) : (
                  <>
                    <button className="btn-primary" onClick={doSave} disabled={save.isPending}>
                      Save
                    </button>
                    <button className="btn-ghost" onClick={() => setDraft(null)}>
                      Cancel
                    </button>
                  </>
                )}
              </div>
            </div>
            {draft !== null ? (
              <textarea
                autoFocus
                aria-label={`Contents of ${selected}`}
                className="input min-h-[60vh] font-mono text-[13px]"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
            ) : (
              <div className="card">
                <Markdown onWikiLink={(t) => open(resolve(t))}>{content || '*This page is empty.*'}</Markdown>
              </div>
            )}
            {draft !== null && (
              <p className="mt-1 text-xs text-fg-muted">Markdown. Link pages with [[page-name]]. ⌘/Ctrl+S saves.</p>
            )}
          </>
        )}
      </section>
    </div>
  )
}
