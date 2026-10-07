import { useQuery } from '@tanstack/react-query'
import { CalendarClock, Inbox, LayoutGrid, Menu, Monitor, Moon, Plus, Sparkles, Sun, X } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router'
import { inboxOptions, listDottiesOptions, systemOptions } from '@/client/@tanstack/react-query.gen'
import { DottieAvatar } from '@/components/DottieAvatar'
import { hueStyle } from '@/lib/hue'
import { UnreadBadge } from '@/components/ui'
import { useLiveUpdates } from '@/lib/live'
import { useTheme } from '@/lib/theme-context'
import { cn } from '@/lib/utils'

export function Logo() {
  return (
    <span className="flex items-center gap-2 text-lg font-semibold tracking-tight">
      <span className="flex items-end gap-0.5" aria-hidden>
        <span className="size-2 rounded-full bg-accent" />
        <span className="size-3 rounded-full bg-accent/70" />
        <span className="size-1.5 rounded-full bg-accent/40" />
      </span>
      dottie
    </span>
  )
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const next = { system: 'light', light: 'dark', dark: 'system' } as const
  const Icon = { system: Monitor, light: Sun, dark: Moon }[theme]
  return (
    <button
      className="btn-ghost p-1.5"
      onClick={() => setTheme(next[theme])}
      title={`Theme: ${theme}`}
      aria-label={`Theme: ${theme}. Click to change`}
    >
      <Icon className="size-4" />
    </button>
  )
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'flex items-center gap-3 rounded-md px-3 py-1.5 transition-colors',
    isActive ? 'bg-accent-soft font-medium text-accent' : 'text-fg-muted hover:bg-muted hover:text-fg',
  )

function Sidebar({ close }: { close: () => void }) {
  const dotties = useQuery(listDottiesOptions())
  const inbox = useQuery(inboxOptions())
  const system = useQuery(systemOptions())
  const unread = inbox.data?.filter((i) => !i.message.read_at).length ?? 0
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4">
        <Logo />
      </div>
      <nav className="flex flex-col gap-0.5 px-2" aria-label="Main">
        <NavLink to="/" end className={linkClass} onClick={close}>
          <LayoutGrid className="size-4" /> Overview
        </NavLink>
        <NavLink to="/inbox" className={linkClass} onClick={close}>
          <Inbox className="size-4" /> <span className="flex-1">Inbox</span>
          <UnreadBadge n={unread} />
        </NavLink>
        <NavLink to="/scheduled" className={linkClass} onClick={close}>
          <CalendarClock className="size-4" /> Scheduled
        </NavLink>
        <NavLink to="/skills" className={linkClass} onClick={close}>
          <Sparkles className="size-4" /> Skills
        </NavLink>
      </nav>
      <div className="mt-4 flex items-center justify-between px-5 text-xs font-medium tracking-wide text-fg-muted uppercase">
        Dotties
      </div>
      <nav className="mt-1 flex-1 space-y-0.5 overflow-y-auto px-2" aria-label="Dotties">
        {dotties.data?.map((d) => (
          <NavLink key={d.id} to={`/dotties/${d.id}`} className={linkClass} onClick={close} style={hueStyle(d.hue)}>
            <DottieAvatar hue={d.hue} state={d.state} size={24} />
            <span className="min-w-0 flex-1 truncate">{d.name}</span>
            <UnreadBadge n={d.unread} />
            <span className="sr-only">{d.state}</span>
          </NavLink>
        ))}
        {dotties.isPending && <div className="skeleton mx-1 h-7" />}
        <NavLink to="/dotties/new" className={linkClass} onClick={close}>
          <span className="grid size-6 place-items-center rounded-full border border-dashed border-fg-muted">
            <Plus className="size-3.5" />
          </span>
          New dottie
        </NavLink>
      </nav>
      <div className="flex items-center justify-between gap-2 border-t border-border p-3 text-xs text-fg-muted">
        <span className="min-w-0 truncate" title="Model and sandbox backend">
          {system.data ? (
            <>
              <span
                className={cn(
                  'mr-1.5 inline-block size-1.5 rounded-full',
                  system.data.llm_configured ? 'bg-ok' : 'bg-warn',
                )}
              />
              {system.data.llm_configured ? system.data.llm_model : 'no model'} · {system.data.sandbox_backend}
            </>
          ) : (
            'Connecting…'
          )}
        </span>
        <ThemeToggle />
      </div>
    </div>
  )
}

export function Shell() {
  useLiveUpdates()
  const [open, setOpen] = useState(false)
  return (
    <div className="flex h-full flex-col md:flex-row">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-surface px-3 md:hidden">
        <Logo />
        <button className="btn-ghost p-1.5" onClick={() => setOpen(true)} aria-label="Open menu">
          <Menu className="size-5" />
        </button>
      </header>
      <aside className="hidden w-60 shrink-0 border-r border-border bg-surface md:block">
        <Sidebar close={() => {}} />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal aria-label="Menu">
          <button className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} aria-label="Close menu" />
          <aside className="anim-rise absolute inset-y-0 left-0 w-72 max-w-[85%] bg-surface shadow-xl">
            <button
              className="btn-ghost absolute top-2 right-2 p-1.5"
              onClick={() => setOpen(false)}
              aria-label="Close menu"
            >
              <X className="size-5" />
            </button>
            <Sidebar close={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <main className="min-h-0 min-w-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
