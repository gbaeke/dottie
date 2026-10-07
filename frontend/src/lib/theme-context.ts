import { createContext, useContext } from 'react'

export type Theme = 'system' | 'light' | 'dark'

export const ThemeContext = createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({
  theme: 'system',
  setTheme: () => {},
})

export const useTheme = () => useContext(ThemeContext)
