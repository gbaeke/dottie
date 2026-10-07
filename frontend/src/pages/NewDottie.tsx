import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import {
  createDottieMutation,
  listDottiesQueryKey,
  listSkillsOptions,
  listTemplatesOptions,
} from '@/client/@tanstack/react-query.gen'
import type { DottieIn } from '@/client/types.gen'
import { DottieAvatar } from '@/components/DottieAvatar'
import { hueStyle } from '@/lib/hue'
import { DottieForm } from '@/components/DottieForm'
import { ListSkeleton, Page, PageTitle } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { fromTemplate } from '@/lib/templates'
import { cn } from '@/lib/utils'

const BLANK: DottieIn = {
  name: '',
  role: '',
  personality: '',
  hue: 265,
  tools: ['messaging', 'schedule', 'web', 'shell'],
  skill_ids: [],
}

export function NewDottie() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const templates = useQuery(listTemplatesOptions())
  const skills = useQuery(listSkillsOptions())
  const [choice, setChoice] = useState<string>('blank')
  const create = useMutation({
    ...createDottieMutation(),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: listDottiesQueryKey() })
      void navigate(`/dotties/${d.id}`)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const template = templates.data?.find((t) => t.key === choice)
  const initial = template ? fromTemplate(template, skills.data ?? []) : BLANK
  return (
    <Page>
      <PageTitle
        title="New dottie"
        sub="Start from a personality, then make it yours. You can change everything later."
      />
      {(templates.isPending || skills.isPending) && <ListSkeleton rows={2} />}
      {templates.data && skills.data && (
        <>
          <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" role="radiogroup" aria-label="Starting point">
            {[{ key: 'blank', name: 'Blank', role: 'Start from nothing', hue: 265 }, ...templates.data].map((t) => (
              <button
                key={t.key}
                role="radio"
                aria-checked={choice === t.key}
                onClick={() => setChoice(t.key)}
                style={hueStyle(t.hue)}
                className={cn(
                  'card flex items-center gap-3 text-left transition-colors',
                  choice === t.key ? 'border-dot bg-dot-soft' : 'hover:border-dot',
                )}
              >
                <DottieAvatar hue={t.hue} state={choice === t.key ? 'awake' : 'sleeping'} size={40} />
                <span className="min-w-0">
                  <span className="block font-medium">{t.name}</span>
                  <span className="line-clamp-2 text-xs text-fg-muted">{t.role}</span>
                </span>
              </button>
            ))}
          </div>
          <DottieForm
            key={choice}
            initial={initial}
            submitLabel="Create dottie"
            pending={create.isPending}
            onSubmit={(body) => create.mutate({ body })}
          />
        </>
      )}
    </Page>
  )
}
