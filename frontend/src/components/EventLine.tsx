import {
  AlarmClock,
  BookOpen,
  Coffee,
  Hammer,
  Info,
  MessageSquareShare,
  Moon,
  Sun,
  TerminalSquare,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const EVENT_ICON: Record<string, { icon: LucideIcon; tone: string; label: string }> = {
  wake: { icon: Sun, tone: 'text-warn', label: 'Woke up' },
  idle: { icon: Coffee, tone: 'text-ok', label: 'Idle' },
  sleep: { icon: Moon, tone: 'text-fg-muted', label: 'Went to sleep' },
  note: { icon: Info, tone: 'text-fg-muted', label: 'Note' },
  tool: { icon: Hammer, tone: 'text-accent', label: 'Used a tool' },
  tool_result: { icon: TerminalSquare, tone: 'text-fg-muted', label: 'Tool result' },
  sent: { icon: MessageSquareShare, tone: 'text-ok', label: 'Sent a message' },
  schedule: { icon: AlarmClock, tone: 'text-accent', label: 'Scheduled' },
  wiki: { icon: BookOpen, tone: 'text-ok', label: 'Updated the wiki' },
  error: { icon: TriangleAlert, tone: 'text-danger', label: 'Problem' },
}

export function EventIcon({ kind, className }: { kind: string; className?: string }) {
  const meta = EVENT_ICON[kind] ?? EVENT_ICON.tool!
  return <meta.icon className={cn('size-4 shrink-0', meta.tone, className)} aria-label={meta.label} />
}
