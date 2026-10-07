import { hueStyle } from '@/lib/hue'
import { cn } from '@/lib/utils'

/** A dottie as a dot: asleep (closed eyes, drifting z), queued (open eyes, dashed ring), awake (open eyes, glowing). */
export function DottieAvatar({
  hue,
  state = 'sleeping',
  size = 40,
  className,
}: {
  hue: number
  state?: string
  size?: number
  className?: string
}) {
  const asleep = state === 'sleeping'
  const ink = `oklch(0.3 0.08 ${hue})`
  return (
    <span
      role="img"
      aria-label={`${state}`}
      className={cn(
        'relative inline-grid shrink-0 place-items-center rounded-full',
        state === 'awake' && 'anim-glow',
        className,
      )}
      style={{
        ...hueStyle(hue),
        width: size,
        height: size,
        background: `radial-gradient(circle at 30% 25%, oklch(0.94 0.07 ${hue}), oklch(0.74 0.14 ${hue}) 70%)`,
      }}
    >
      <svg viewBox="0 0 40 40" className="size-full" aria-hidden>
        {asleep ? (
          <g fill="none" stroke={ink} strokeWidth="2.2" strokeLinecap="round">
            <path d="M11 21 q3.5 3.2 7 0" />
            <path d="M22 21 q3.5 3.2 7 0" />
          </g>
        ) : (
          <g fill={ink}>
            <ellipse className="anim-blink" cx="14.5" cy="20" rx="2.4" ry="3" />
            <ellipse className="anim-blink" cx="25.5" cy="20" rx="2.4" ry="3" />
          </g>
        )}
      </svg>
      {state === 'queued' && (
        <span className="anim-spin absolute -inset-1 rounded-full border-2 border-dashed border-dot" aria-hidden />
      )}
      {asleep && size >= 32 && (
        <span
          aria-hidden
          className="anim-z absolute -top-1 -right-1 font-semibold text-dot-ink"
          style={{ fontSize: Math.max(10, size * 0.28) }}
        >
          z
        </span>
      )}
    </span>
  )
}
