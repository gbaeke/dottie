import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

/** Which query families each kind of server-side change makes stale (ids are the generated query keys' `_id`). */
const AFFECTED: Record<string, string[]> = {
  messages: ['listConversations', 'listMessages', 'inbox', 'listDotties', 'getDottie', 'traffic', 'listAll'],
  events: ['listEvents', 'listDottieEvents'],
  runs: ['listRuns', 'listDotties', 'getDottie', 'listEvents', 'listDottieEvents'],
  wiki: ['listPages', 'readPage'],
  dotties: ['listDotties', 'getDottie', 'listTemplates'],
}

/** Refetch every query made by one of these generated options (by name, e.g. 'listDotties'), whatever its arguments. */
/* oxlint-disable no-underscore-dangle -- `_id` is the generated client's own key field */
export const invalidateFamilies = (qc: QueryClient, names: string[]) =>
  qc.invalidateQueries({ predicate: (q) => names.includes((q.queryKey[0] as { _id?: string } | undefined)?._id ?? '') })
/* oxlint-enable no-underscore-dangle */

function invalidate(qc: QueryClient, kinds: string[]) {
  void invalidateFamilies(
    qc,
    kinds.flatMap((k) => AFFECTED[k] ?? []),
  )
}

/** One EventSource for the whole app: the server says what changed, the matching queries refetch. */
export function useLiveUpdates() {
  const qc = useQueryClient()
  useEffect(() => {
    let source: EventSource | undefined
    let timer: number | undefined
    let delay = 1000
    let closed = false
    const connect = () => {
      source = new EventSource('/api/stream')
      source.onopen = () => {
        delay = 1000
        invalidate(qc, Object.keys(AFFECTED)) // whatever happened while we were away
      }
      source.addEventListener('changed', (e) => {
        const { changed } = JSON.parse((e as MessageEvent<string>).data) as { changed: string[] }
        invalidate(qc, changed)
      })
      source.onerror = () => {
        source?.close()
        if (closed) return
        timer = window.setTimeout(connect, delay)
        delay = Math.min(delay * 2, 15_000)
      }
    }
    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      source?.close()
    }
  }, [qc])
}
