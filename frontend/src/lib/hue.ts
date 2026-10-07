import type { CSSProperties } from 'react'

/** The CSS variable the `dot` colour tokens read: set it on any wrapper to tint everything inside with a dottie's hue. */
export const hueStyle = (hue: number): CSSProperties => ({ ['--dot-hue' as string]: hue })
