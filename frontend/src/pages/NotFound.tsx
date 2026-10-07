import { Link } from 'react-router'

export function NotFound() {
  return (
    <div className="card m-6 max-w-md">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <Link to="/" className="mt-2 inline-block text-accent hover:underline">
        Back home
      </Link>
    </div>
  )
}
