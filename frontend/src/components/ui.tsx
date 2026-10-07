import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { DottieAvatar } from '@/components/DottieAvatar'
import { hueStyle } from '@/lib/hue'
import { cn } from '@/lib/utils'

export const Skeleton = ({ className }: { className?: string }) => <div className={cn('skeleton h-4', className)} />

export const Spinner = ({ className }: { className?: string }) => (
  <Loader2 className={cn('size-4 animate-spin', className)} aria-label="Loading" />
)

const STATE_LABEL: Record<string, string> = { sleeping: 'Asleep', queued: 'Waking up', awake: 'Awake' }

export function StatePill({ state }: { state: string }) {
  const tone =
    state === 'awake' ? 'bg-ok/15 text-ok' : state === 'queued' ? 'bg-warn/15 text-warn' : 'bg-muted text-fg-muted'
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium', tone)}>
      <span className={cn('size-1.5 rounded-full bg-current', state === 'awake' && 'animate-pulse')} />
      {STATE_LABEL[state] ?? state}
    </span>
  )
}

export function UnreadBadge({ n }: { n: number }) {
  if (n <= 0) return null
  return (
    <span
      className="inline-grid min-w-5 place-items-center rounded-full bg-accent px-1.5 text-[11px] font-semibold text-accent-fg"
      aria-label={`${n} unread`}
    >
      {n}
    </span>
  )
}

export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn('relative h-5 w-9 shrink-0 rounded-full transition-colors', checked ? 'bg-accent' : 'bg-border')}
    >
      <span
        className={cn(
          'absolute top-0.5 left-0.5 size-4 rounded-full bg-surface shadow transition-transform',
          checked && 'translate-x-4',
        )}
      />
    </button>
  )
}

export function DottieChip({ name, hue }: { name: string; hue: number }) {
  return (
    <span className="chip" style={hueStyle(hue)}>
      <DottieAvatar hue={hue} size={14} state="awake" className="[&_svg]:hidden" />
      {name}
    </span>
  )
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border px-6 py-10 text-center">
      {icon && <div className="text-fg-muted">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <div className="max-w-md text-fg-muted">{children}</div>}
    </div>
  )
}

export function PageTitle({ title, children, sub }: { title: string; sub?: string; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-0.5 text-fg-muted">{sub}</p>}
      </div>
      {children}
    </div>
  )
}

export const ListSkeleton = ({ rows = 3, className }: { rows?: number; className?: string }) => (
  <div className={cn('space-y-3', className)} aria-busy>
    {Array.from({ length: rows }, (_, i) => (
      <Skeleton key={i} className="h-16 w-full" />
    ))}
  </div>
)

export const Page = ({ children, wide }: { children: ReactNode; wide?: boolean }) => (
  <div className={cn('mx-auto p-4 md:p-8', wide ? 'max-w-7xl' : 'max-w-5xl')}>{children}</div>
)
