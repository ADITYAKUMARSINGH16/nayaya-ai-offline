import { Children, isValidElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const SECTION_RE = /(\bsection\s*\d{1,4}[a-z]?(?:\(\d+\))?)/gi

/**
 * Walks a React children tree and replaces every "Section N" occurrence in
 * string nodes with a clickable button. Other elements/structure are kept.
 */
function linkifySections(node, onSectionClick) {
  if (node == null || node === false) return node
  if (typeof node === 'string') {
    const parts = node.split(SECTION_RE)
    if (parts.length === 1) return node
    return parts.map((part, i) => {
      if (i % 2 === 1) {
        // Capture group hit — make it interactive
        const numMatch = part.match(/\d{1,4}/)
        const num = numMatch ? numMatch[0] : null
        return (
          <button
            key={i}
            type="button"
            onClick={(e) => {
              e.preventDefault()
              if (num) onSectionClick?.(num)
            }}
            className="inline align-baseline px-1 py-0 -mx-0.5 rounded
                       text-gold-200 underline decoration-gold-400/40
                       underline-offset-2 hover:bg-gold-400/15 hover:decoration-gold-300
                       focus:outline-none focus:ring-1 focus:ring-gold-400/50
                       transition cursor-pointer"
            title={num ? `View Section ${num}` : undefined}
          >
            {part}
          </button>
        )
      }
      return part
    })
  }
  if (Array.isArray(node)) return node.map((c, i) => (
    // eslint-disable-next-line react/no-array-index-key
    <span key={i}>{linkifySections(c, onSectionClick)}</span>
  ))
  if (isValidElement(node)) {
    const kids = node.props?.children
    if (kids == null) return node
    return { ...node, props: { ...node.props, children: Children.map(kids, (c) => linkifySections(c, onSectionClick)) } }
  }
  return node
}

/**
 * Renders assistant output as Markdown. Optional `onSectionClick(num)` makes
 * every "Section N" mention inside the rendered prose clickable.
 */
export default function Markdown({ children, className = '', onSectionClick }) {
  if (typeof children !== 'string') return children

  const wrap = onSectionClick
    ? (Tag) => (props) => <Tag {...props}>{Children.map(props.children, (c) => linkifySections(c, onSectionClick))}</Tag>
    : null

  const components = {
    a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
    img: () => null,
    ...(wrap && {
      p:  wrap('p'),
      li: wrap('li'),
      strong: wrap('strong'),
      em: wrap('em'),
      td: wrap('td'),
      th: wrap('th'),
    }),
  }

  return (
    <div className={`markdown-body ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
