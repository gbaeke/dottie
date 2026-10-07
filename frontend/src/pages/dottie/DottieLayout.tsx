import { useQuery } from '@tanstack/react-query'
import { Activity, BookOpen, CalendarClock, MessageSquare, Settings } from 'lucide-react'
import { NavLink, Outlet, useParams } from 'react-router'
import { getDottieOptions, systemOptions } from '@/client/@tanstack/react-query.gen'
import { DottieAvatar } from '@/components/DottieAvatar'
import { hueStyle } from '@/lib/hue'
import { Skeleton, StatePill } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const TABS = [
  { to: '', label: 'Chat', icon: MessageSquare },
  { to: 'wiki', label: 'Wiki', icon: BookOpen },
  { to: 'schedules', label: 'Schedules', icon: CalendarClock },
  { to: 'activity', label: 'Activity', icon: Activity },
  { to: 'settings', label: 'Settings', icon: Settings },
]

export function DottieLayout() {
  const { id } = useParams()
  const dottie = useQuery(getDottieOptions({ path: { dottie_id: Number(id) } }))
  const system = useQuery(systemOptions())
  const d = dottie.data
  if (dottie.isError) return <p className="p-8 text-danger">{errorMessage(dottie.error)}</p>
  return (
    <div className="flex h-full flex-col" style={d ? hueStyle(d.hue) : undefined}>
      <header className="shrink-0 border-b border-border bg-surface px-4 pt-4 md:px-8">
        {!d ? (
          <div className="flex gap-4 pb-3">
            <Skeleton className="size-14 rounded-full" />
            <Skeleton className="h-10 w-64" />
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pb-3">
            <DottieAvatar hue={d.hue} state={d.state} size={56} />
            <div className="min-w-0 flex-1 basis-56">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-xl font-semibold tracking-tight">{d.name}</h1>
                <StatePill state={d.state} />
              </div>
              <p className="truncate text-fg-muted">{d.role || 'No role yet'}</p>
            </div>
            <div className="flex flex-wrap gap-1.5 text-xs">
              <span className="chip">
                {d.next_run_at ? `next wake ${relativeTime(d.next_run_at)}` : 'nothing scheduled'}
              </span>
              {d.tools.includes('shell') && (
                <span className="chip">computer · {system.data?.sandbox_backend ?? '…'}</span>
              )}
              {d.tools
                .filter((t) => t !== 'shell')
                .map((t) => (
                  <span key={t} className="chip">
                    {t}
                  </span>
                ))}
              {d.mcp_servers.length > 0 && <span className="chip">{d.mcp_servers.length} MCP</span>}
            </div>
          </div>
        )}
        <nav className="-mb-px flex gap-1 overflow-x-auto" aria-label="Dottie sections">
          {TABS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={label}
              to={to}
              end={to === ''}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-1.5 border-b-2 px-3 py-2 whitespace-nowrap transition-colors',
                  isActive ? 'border-dot font-medium text-fg' : 'border-transparent text-fg-muted hover:text-fg',
                )
              }
            >
              <Icon className="size-4" /> {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <div className="min-h-0 flex-1 overflow-auto">{d && <Outlet context={d} />}</div>
    </div>
  )
}
