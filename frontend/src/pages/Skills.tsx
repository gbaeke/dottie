import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Lock, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import {
  createSkillMutation,
  deleteSkillMutation,
  listSkillsOptions,
  listSkillsQueryKey,
  updateSkillMutation,
} from '@/client/@tanstack/react-query.gen'
import type { SkillOut } from '@/client/types.gen'
import { Markdown } from '@/components/Markdown'
import { ListSkeleton, Page, PageTitle } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { pluralize } from '@/lib/format'
import { cn } from '@/lib/utils'

const NAME_PATTERN = '[a-z0-9]+(-[a-z0-9]+)*'

function SkillForm({
  skill,
  initial,
  onDone,
}: {
  skill?: SkillOut
  initial?: { name: string; description: string; body: string }
  onDone: (id: number | null) => void
}) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: listSkillsQueryKey() })
  const onError = (e: unknown) => toast.error(errorMessage(e))
  const create = useMutation({
    ...createSkillMutation(),
    onSuccess: (s) => {
      void refresh()
      onDone(s.id)
    },
    onError,
  })
  const update = useMutation({
    ...updateSkillMutation(),
    onSuccess: () => {
      void refresh()
      toast.success('Saved')
    },
    onError,
  })
  const remove = useMutation({
    ...deleteSkillMutation(),
    onSuccess: () => {
      void refresh()
      onDone(null)
    },
    onError,
  })
  const src = skill ?? initial
  const [name, setName] = useState(src?.name ?? '')
  const [description, setDescription] = useState(src?.description ?? '')
  const [body, setBody] = useState(src?.body ?? '')
  const readOnly = skill?.builtin ?? false

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (skill) update.mutate({ path: { skill_id: skill.id }, body: { description, body } })
    else create.mutate({ body: { name, description, body } })
  }

  return (
    <form onSubmit={submit} className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-semibold">
          {skill ? skill.name : 'New skill'}
          {readOnly && (
            <span className="chip">
              <Lock className="size-3" /> built-in
            </span>
          )}
        </h2>
        {skill && <span className="text-xs text-fg-muted">Used by {pluralize(skill.used_by, 'dottie')}</span>}
      </div>
      {!skill && (
        <div>
          <label className="field-label" htmlFor="skill-name">
            Name (lowercase, hyphens)
          </label>
          <input
            id="skill-name"
            className="input font-mono"
            value={name}
            pattern={NAME_PATTERN}
            required
            onChange={(e) => setName(e.target.value.toLowerCase().replace(/\s+/g, '-'))}
            placeholder="weekly-report"
          />
        </div>
      )}
      <div>
        <label className="field-label" htmlFor="skill-desc">
          When to use it (the only part dotties always see)
        </label>
        <textarea
          id="skill-desc"
          className="input min-h-16"
          value={description}
          required
          readOnly={readOnly}
          maxLength={1024}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div>
        <label className="field-label" htmlFor="skill-body">
          Instructions (markdown)
        </label>
        {readOnly ? (
          <div className="rounded-md border border-border bg-muted/40 p-3">
            <Markdown>{body}</Markdown>
          </div>
        ) : (
          <textarea
            id="skill-body"
            className="input min-h-64 font-mono text-[13px]"
            value={body}
            required
            onChange={(e) => setBody(e.target.value)}
          />
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {!readOnly && (
          <button className="btn-primary" disabled={create.isPending || update.isPending}>
            {skill ? 'Save' : 'Create skill'}
          </button>
        )}
        {readOnly && skill && (
          <button
            type="button"
            className="btn-primary"
            onClick={() => onDone(-1)}
            title="Make an editable copy under a new name"
          >
            <Copy className="size-4" /> Duplicate to edit
          </button>
        )}
        {skill && !readOnly && (
          <button
            type="button"
            className="btn-ghost text-danger"
            onClick={() =>
              window.confirm(`Delete "${skill.name}"? Dotties that have it lose it.`) &&
              remove.mutate({ path: { skill_id: skill.id } })
            }
          >
            <Trash2 className="size-4" /> Delete
          </button>
        )}
      </div>
    </form>
  )
}

export function Skills() {
  const skills = useQuery(listSkillsOptions())
  const [selected, setSelected] = useState<number | 'new' | null>(null)
  const [copyOf, setCopyOf] = useState<SkillOut | null>(null)
  const current = skills.data?.find((s) => s.id === selected)
  const done = (id: number | null) => {
    if (id === -1 && current) {
      setCopyOf(current)
      setSelected('new')
    } else {
      setCopyOf(null)
      setSelected(id)
    }
  }
  return (
    <Page wide>
      <PageTitle
        title="Skills"
        sub="Procedures a dottie can read when a task fits. Give them to dotties in their settings."
      >
        <button
          className="btn-primary"
          onClick={() => {
            setCopyOf(null)
            setSelected('new')
          }}
        >
          <Plus className="size-4" /> New skill
        </button>
      </PageTitle>
      <div className="grid gap-4 md:grid-cols-[18rem_1fr]">
        <div className={cn(selected !== null && 'hidden md:block')}>
          {skills.isPending && <ListSkeleton rows={4} />}
          <ul className="space-y-1.5">
            {skills.data?.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => done(s.id)}
                  aria-current={selected === s.id}
                  className={cn(
                    'card w-full text-left transition-colors hover:border-accent',
                    selected === s.id && 'border-accent bg-accent-soft',
                  )}
                >
                  <p className="flex items-center gap-1.5 font-medium">
                    <Sparkles className="size-3.5 text-accent" /> {s.name}
                    {s.builtin && <Lock className="size-3 text-fg-muted" aria-label="built-in" />}
                  </p>
                  <p className="mt-0.5 line-clamp-2 text-xs text-fg-muted">{s.description}</p>
                  <p className="mt-1 text-xs text-fg-muted">{pluralize(s.used_by, 'dottie')}</p>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className={cn(selected === null && 'hidden md:block')}>
          {selected !== null && (
            <button className="btn-ghost mb-2 md:hidden" onClick={() => setSelected(null)}>
              ← All skills
            </button>
          )}
          {selected === 'new' && (
            <SkillForm
              key={`new-${copyOf?.id ?? 0}`}
              onDone={done}
              initial={
                copyOf ? { name: `${copyOf.name}-copy`, description: copyOf.description, body: copyOf.body } : undefined
              }
            />
          )}
          {current && <SkillForm key={current.id} skill={current} onDone={done} />}
          {selected === null && (
            <div className="hidden rounded-lg border border-dashed border-border p-10 text-center text-fg-muted md:block">
              Pick a skill to read it, or write a new one.
            </div>
          )}
        </div>
      </div>
    </Page>
  )
}
