/** Shared pure utility functions used across the app. */

export function sourceColor(source: string): string {
  let hash = 0
  for (let i = 0; i < source.length; i++)
    hash = source.charCodeAt(i) + ((hash << 5) - hash)
  const hue = Math.abs(hash) % 360
  return `hsl(${hue}, 80%, 55%)`
}

export function formatSize(bytes: number): string {
  if (bytes <= 0) return 'empty'
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

/**
 * Split highlighted HTML into per-line, tag-balanced chunks so each line can be
 * rendered separately (for the gutter) without leaking open <span> tags across
 * line boundaries.
 */
export function splitHighlighted(html: string): string[] {
  const lines: string[] = []
  const stack: string[] = []      // currently open <span ...> opening strings
  let buf = ''

  const flush = () => {
    // close all open spans for this line, then re-open for the next
    lines.push(buf + stack.map(() => '</span>').join(''))
    buf = stack.join('')
  }

  let i = 0
  while (i < html.length) {
    const ch = html[i]
    if (ch === '<') {
      const end = html.indexOf('>', i)
      if (end === -1) break
      const tag = html.slice(i, end + 1)
      if (tag.startsWith('</span')) {
        stack.pop()
      } else if (tag.startsWith('<span')) {
        stack.push(tag)
      }
      buf += tag
      i = end + 1
      continue
    }
    if (ch === '\n') {
      flush()
      i += 1
      continue
    }
    buf += ch
    i += 1
  }
  flush()
  return lines
}