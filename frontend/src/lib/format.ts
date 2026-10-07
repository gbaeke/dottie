/** Small, dependency-free formatting: relative times, cron in words, and the schedule presets. */

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never'
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 31_536_000],
    ['month', 2_592_000],
    ['week', 604_800],
    ['day', 86_400],
    ['hour', 3600],
    ['minute', 60],
  ]
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit)
  }
  return Math.abs(seconds) < 10 ? 'just now' : rtf.format(seconds, 'second')
}

export const absoluteTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const pad = (n: number | string) => String(n).padStart(2, '0')

/** "0 8 * * 1-5" → "Weekdays at 08:00". Common patterns only; anything else comes back as the raw cron. */
export function humanizeCron(cron: string): string {
  const f = cron.trim().split(/\s+/)
  if (f.length !== 5) return cron
  const [min, hour, dom, mon, dow] = f as [string, string, string, string, string]
  const isNum = (v: string) => /^\d+$/.test(v)
  if (min === '*' && hour === '*' && dom === '*' && mon === '*' && dow === '*') return 'Every minute'
  if (/^\*\/\d+$/.test(min) && hour === '*' && dom === '*' && mon === '*' && dow === '*')
    return `Every ${min.slice(2)} minutes`
  if (isNum(min) && hour === '*' && dom === '*' && mon === '*' && dow === '*')
    return min === '0' ? 'Every hour' : `Every hour at :${pad(min)}`
  if (!isNum(min) || !isNum(hour) || mon !== '*') return cron
  const time = `${pad(hour)}:${pad(min)}`
  if (dom === '*' && dow === '*') return `Every day at ${time}`
  if (dom === '*' && dow === '1-5') return `Weekdays at ${time}`
  if (dom === '*' && dow === '0,6') return `Weekends at ${time}`
  if (dom === '*' && /^[0-7]$/.test(dow)) return `Every ${DAYS[Number(dow) % 7]} at ${time}`
  if (isNum(dom) && dow === '*') return `Monthly on day ${dom} at ${time}`
  return cron
}

export type Preset = 'weekdays' | 'daily' | 'weekly' | 'hourly' | 'once' | 'custom'
export const PRESETS: { key: Preset; label: string }[] = [
  { key: 'weekdays', label: 'Every weekday' },
  { key: 'daily', label: 'Every day' },
  { key: 'weekly', label: 'Every week' },
  { key: 'hourly', label: 'Every hour' },
  { key: 'once', label: 'Once' },
  { key: 'custom', label: 'Custom cron' },
]

/** The cron a preset stands for; `time` is "HH:MM", `day` 0-6 (Sunday = 0). */
export function presetCron(preset: Preset, time: string, day: number, custom: string): string | null {
  const [h = '8', m = '0'] = time.split(':')
  const at = `${Number(m)} ${Number(h)}`
  switch (preset) {
    case 'weekdays':
      return `${at} * * 1-5`
    case 'daily':
      return `${at} * * *`
    case 'weekly':
      return `${at} * * ${day}`
    case 'hourly':
      return `${Number(m)} * * * *`
    case 'custom':
      return custom.trim() || null
    default:
      return null
  }
}

export const describeTiming = (s: { cron: string | null; run_at: string | null }) =>
  s.cron ? humanizeCron(s.cron) : s.run_at ? `Once, ${absoluteTime(s.run_at)}` : 'No timing'

export const pluralize = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export const HUES = [20, 45, 85, 140, 175, 200, 235, 265, 295, 330, 350, 10]
