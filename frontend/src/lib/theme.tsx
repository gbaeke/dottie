import { useEffect, useState, type ReactNode } from 'react'
import { ThemeContext, type Theme } from '@/lib/theme-context'

const prefersDark = () => matchMedia('(prefers-color-scheme: dark)').matches

function apply(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark' || (theme === 'system' && prefersDark()))
}

/** Light, dark, or the system's choice; remembered in localStorage. useTheme() (theme-context.ts) reads it. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => (localStorage.getItem('theme') as Theme | null) ?? 'system')
  useEffect(() => {
    apply(theme)
    if (theme !== 'system') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => apply('system')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])
  const setTheme = (t: Theme) => {
    localStorage.setItem('theme', t)
    setThemeState(t)
  }
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}
