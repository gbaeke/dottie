import { isRouteErrorResponse, Link, useRouteError } from 'react-router'
import { errorMessage } from '@/lib/api'

export function RouteError() {
  const error = useRouteError()
  const message = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : errorMessage(error)
  return (
    <div className="grid h-full place-items-center p-6">
      <div className="card max-w-md space-y-3 text-center">
        <p className="text-lg font-semibold">Something went wrong</p>
        <p className="text-fg-muted">{message}</p>
        <Link to="/" className="btn-primary inline-flex">
          Back to the overview
        </Link>
      </div>
    </div>
  )
}
