import { client } from '@/client/client.gen'

/** Every failed call, as the server describes it: {"error": {"code", "message"}}. */
export class ApiError extends Error {
  code: string
  status: number
  constructor(code: string, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

/** Called once at startup: the generated client (src/client) throws an ApiError for every failure. */
export function setupApiClient() {
  client.interceptors.error.use((error, response) => {
    const body = error as { error?: { code?: string; message?: string } } | undefined
    return new ApiError(
      body?.error?.code ?? 'http_error',
      body?.error?.message ?? response?.statusText ?? 'Network error',
      response?.status ?? 0,
    )
  })
}

export const errorMessage = (e: unknown): string => (e instanceof Error ? e.message : String(e))
