import ReactMarkdown, { defaultUrlTransform, type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

const WIKILINK = /\[\[([^\]\n]+)\]\]/g

const components: Components = {
  a: ({ href, children }) =>
    href?.startsWith('wiki:') ? (
      <a href={href}>{children}</a>
    ) : (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ),
}

const urlTransform = (url: string) => (url.startsWith('wiki:') ? url : defaultUrlTransform(url))

/** Markdown with the app's typography. With `onWikiLink`, `[[page]]` becomes a link that calls it with the page name. */
export function Markdown({
  children,
  onWikiLink,
  className,
}: {
  children: string
  onWikiLink?: (path: string) => void
  className?: string
}) {
  const text = onWikiLink
    ? children.replace(WIKILINK, (_, t: string) => `[${t}](wiki:${encodeURIComponent(t.trim())})`)
    : children
  return (
    // links are handled by delegation: the rendered tree stays plain markdown
    <div
      className={cn('prose-dot break-words', className)}
      role="presentation"
      onClick={(e) => {
        const href = (e.target as HTMLElement).closest('a')?.getAttribute('href')
        if (onWikiLink && href?.startsWith('wiki:')) {
          e.preventDefault()
          onWikiLink(decodeURIComponent(href.slice(5)))
        }
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={urlTransform} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
