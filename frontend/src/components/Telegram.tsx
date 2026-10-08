import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageCircle, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import {
  makeCodeMutation,
  telegramStatusOptions,
  telegramStatusQueryKey,
  unlinkChatMutation,
} from '@/client/@tanstack/react-query.gen'
import type { TelegramCode } from '@/client/types.gen'
import { ListSkeleton, Spinner } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { relativeTime } from '@/lib/format'

/** Chat with your dotties from Telegram: link a chat with a one-time code, then pick the dottie in the chat. */
export function Telegram() {
  const qc = useQueryClient()
  const status = useQuery(telegramStatusOptions())
  const [code, setCode] = useState<TelegramCode | null>(null)
  const onError = (e: unknown) => toast.error(errorMessage(e))
  const make = useMutation({ ...makeCodeMutation(), onSuccess: setCode, onError })
  const unlink = useMutation({
    ...unlinkChatMutation(),
    onSuccess: () => qc.invalidateQueries({ queryKey: telegramStatusQueryKey() }),
    onError,
  })

  if (status.isPending) return <ListSkeleton />
  if (status.isError) return <p className="text-danger">{errorMessage(status.error)}</p>

  return (
    <section className="mb-8" aria-labelledby="telegram-title">
      <h2 id="telegram-title" className="mb-1 font-medium">
        Telegram
      </h2>
      {!status.data.enabled ? (
        <p className="text-sm text-fg-muted">
          Not set up. Make a bot with @BotFather and give the app its token (<code>TELEGRAM_BOT_TOKEN</code>), and you
          can talk to your dotties from Telegram.
        </p>
      ) : (
        <>
          <p className="mb-3 text-sm text-fg-muted">
            Link a chat, then choose which dottie you talk to with <code>/dottie</code> in the chat. Their answers come
            back there.
          </p>
          <button className="btn-primary mb-3" disabled={make.isPending} onClick={() => make.mutate({})}>
            {make.isPending ? <Spinner /> : <MessageCircle className="size-4" />} Link a Telegram chat
          </button>
          {code && (
            <p className="mb-3 rounded-md border border-ok/50 bg-ok/10 p-3 text-sm" role="status">
              <a className="font-medium underline" href={code.link} target="_blank" rel="noreferrer">
                Open the bot in Telegram
              </a>{' '}
              and press Start. Or send it <code>/start {code.code}</code>. The code works once, for an hour.
            </p>
          )}
          <ul className="space-y-2">
            {status.data.chats.map((c) => (
              <li key={c.id} className="card flex items-center justify-between gap-3 py-2.5">
                <p className="min-w-0 truncate">
                  <span className="font-medium">A Telegram chat</span>{' '}
                  <span className="text-xs text-fg-muted">
                    · {c.dottie_name ? `talking to ${c.dottie_name}` : 'no dottie chosen yet'} · linked{' '}
                    {relativeTime(c.created_at)}
                  </span>
                </p>
                <button
                  className="btn-ghost shrink-0 p-1.5"
                  aria-label="Unlink this chat"
                  title="Unlink"
                  disabled={unlink.isPending}
                  onClick={() =>
                    window.confirm('Unlink this chat? It stops talking to your dotties.') &&
                    unlink.mutate({ path: { link_id: c.id } })
                  }
                >
                  <Trash2 className="size-4" />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
