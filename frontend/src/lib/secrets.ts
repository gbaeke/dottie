/** Where a value refers to a stored secret: `Bearer {{secret:tavily}}`. Mirrors the backend (engine/secrets.py, mcp.py). */
const REF = /\{\{\s*secret:([a-zA-Z][a-zA-Z0-9_-]{0,39})\s*\}\}/g
const SECRETISH = /key|token|secret|passw|auth|credential|bearer|signature|cookie|sig$/i

export const secretRef = (name: string) => `{{secret:${name}}}`

/** The secret names a value refers to. */
export const refsIn = (value: string): string[] => Array.from(value.matchAll(REF), (m) => m[1]!)

export const looksSecret = (name: string) => SECRETISH.test(name)

/** A key that looks like a credential, with a value that is typed in and not a reference to a secret. */
export const isLiteralCredential = (key: string, value: string) =>
  looksSecret(key) && value.trim() !== '' && refsIn(value).length === 0

/** A URL with a credential-looking query parameter that has a literal value. */
export function urlHasLiteralCredential(url: string): boolean {
  const q = url.split('?')[1]
  if (!q) return false
  return q.split('&').some((pair) => {
    const [k = '', v = ''] = pair.split('=')
    return isLiteralCredential(decodeURIComponent(k), decodeURIComponent(v))
  })
}

export const SECRET_NAME = '[a-zA-Z][a-zA-Z0-9_\\-]{0,39}'
