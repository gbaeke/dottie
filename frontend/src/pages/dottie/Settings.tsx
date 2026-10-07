import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { deleteDottieMutation, listDottiesQueryKey, updateDottieMutation } from '@/client/@tanstack/react-query.gen'
import { DottieForm } from '@/components/DottieForm'
import { invalidateFamilies } from '@/lib/live'
import { errorMessage } from '@/lib/api'
import { useDottie } from '@/lib/dottie-context'

export function DottieSettings() {
  const d = useDottie()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const refresh = () => invalidateFamilies(qc, ['listDotties', 'getDottie'])
  const update = useMutation({
    ...updateDottieMutation(),
    onSuccess: () => {
      void refresh()
      toast.success('Saved')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    ...deleteDottieMutation(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: listDottiesQueryKey() })
      void navigate('/')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const [confirm, setConfirm] = useState('')
  return (
    <div className="mx-auto max-w-3xl space-y-8 p-4 md:p-8">
      <DottieForm
        initial={{
          name: d.name,
          role: d.role,
          personality: d.personality,
          hue: d.hue,
          model: d.model,
          tools: d.tools,
          mcp_servers: d.mcp_servers,
          skill_ids: d.skill_ids,
        }}
        submitLabel="Save changes"
        pending={update.isPending}
        onSubmit={(body) => update.mutate({ path: { dottie_id: d.id }, body })}
      />
      <section className="card space-y-3 border-danger/40">
        <h2 className="font-semibold text-danger">Delete {d.name}</h2>
        <p className="text-fg-muted">
          This removes {d.name}'s wiki, conversations, schedules and computer. It can't be undone. Type <b>{d.name}</b>{' '}
          to confirm.
        </p>
        <div className="flex gap-2">
          <input
            className="input max-w-xs"
            aria-label="Type the name to confirm"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          <button
            className="btn bg-danger text-white hover:opacity-90"
            disabled={confirm !== d.name || remove.isPending}
            onClick={() => remove.mutate({ path: { dottie_id: d.id } })}
          >
            Delete forever
          </button>
        </div>
      </section>
    </div>
  )
}
