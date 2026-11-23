/** Shared pure utility functions used across the app. */

/**
 * Render basic markdown to HTML. Handles headings, bold, inline code,
 * bullet lists, paragraphs, and code blocks. Safe for our controlled
 * LLM output — no user content passes through.
 */
export function renderMarkdown(text: string): string {
  const esc = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  let html = esc(text)

  // Code blocks (```...```) — render before other inline patterns
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, _lang, code) => {
    return `<pre class="hljs" style="font-family:var(--font-mono);font-size:13px;line-height:1.7;background:#131313;border:1px solid #222;border-radius:6px;padding:12px;overflow-x:auto;margin:8px 0;">${esc(code.trim())}</pre>`
  })

  // Inline code (`...`)
  html = html.replace(/`([^`]+)`/g, '<code style="font-family:var(--font-mono);font-size:12px;background:#1a1a1a;padding:1px 5px;border-radius:3px;color:#ffd700;">$1</code>')

  // Bold **...**
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong style="color:#e8e8e8;">$1</strong>')

  // Headings (## then #)
  html = html.replace(/^## (.+)$/gm, '<h3 style="color:#00e5ff;font-size:14px;font-weight:600;margin:16px 0 8px 0;border-bottom:1px solid #222;padding-bottom:4px;">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h2 style="color:#00e5ff;font-size:16px;font-weight:600;margin:20px 0 10px 0;border-bottom:1px solid #222;padding-bottom:6px;">$1</h2>')

  // Bullet lists (- item)
  html = html.replace(/^- (.+)$/gm, '<li style="color:#aaa;margin:2px 0 2px 16px;list-style:disc;">$1</li>')

  // Line breaks — wrap consecutive non-empty lines in paragraphs, and render
  // markdown tables (consecutive lines starting with '|') as real tables.
  const lines = html.split('\n')
  const wrapped: string[] = []
  let inList = false
  let i = 0

  const splitRow = (row: string): string[] => {
    // Drop the leading/trailing pipe, then split on unescaped pipes
    const trimmed = row.trim().replace(/^\|/, '').replace(/\|$/, '')
    const cells: string[] = []
    let cur = ''
    for (let c = 0; c < trimmed.length; c++) {
      const ch = trimmed[c]
      if (ch === '\\' && trimmed[c + 1] === '|') { cur += '|'; c++; continue }
      if (ch === '|') { cells.push(cur.trim()); cur = ''; continue }
      cur += ch
    }
    cells.push(cur.trim())
    return cells
  }

  const isTableLine = (s: string) => s.startsWith('|') && s.length > 1
  const isSeparator = (s: string) => /^\|[\s:|-]+\|?$/.test(s) && s.includes('-')

  while (i < lines.length) {
    const line = lines[i].trim()
    if (!line) {
      if (inList) { inList = false }
      i++
      continue
    }

    // Markdown table
    if (isTableLine(line)) {
      const tableLines: string[] = []
      while (i < lines.length && isTableLine(lines[i].trim())) {
        tableLines.push(lines[i].trim())
        i++
      }
      let headerCells: string[] = []
      let bodyStart = 0
      if (tableLines.length > 0) {
        headerCells = splitRow(tableLines[0])
        bodyStart = 1
        // Skip separator row if present
        if (tableLines.length > 1 && isSeparator(tableLines[1])) bodyStart = 2
      }
      const th = headerCells.map(c =>
        `<th style="text-align:left;padding:6px 10px;border-bottom:1px solid #333;color:#00e5ff;font-weight:600;white-space:nowrap;">${c}</th>`
      ).join('')
      const bodyRows = tableLines.slice(bodyStart).map(row => {
        const cells = splitRow(row).map(c =>
          `<td style="padding:5px 10px;border-bottom:1px solid #1e1e1e;color:#bbb;vertical-align:top;">${c}</td>`
        ).join('')
        return `<tr>${cells}</tr>`
      }).join('')
      wrapped.push(
        `<div style="overflow-x:auto;margin:10px 0;"><table style="border-collapse:collapse;width:100%;font-size:12px;"><thead><tr>${th}</tr></thead><tbody>${bodyRows}</tbody></table></div>`
      )
      inList = false
      continue
    }

    // Horizontal rule
    if (/^-{3,}$/.test(line)) {
      wrapped.push('<hr style="border:none;border-top:1px solid #222;margin:14px 0;" />')
      inList = false
      i++
      continue
    }

    if (line.startsWith('<h') || line.startsWith('<pre') || line.startsWith('<li')) {
      wrapped.push(line)
      if (line.startsWith('<li')) inList = true
      else inList = false
      i++
      continue
    }
    if (inList) { i++; continue }
    wrapped.push(`<p style="color:#999;font-size:13px;line-height:1.6;margin:4px 0;">${line}</p>`)
    i++
  }

  return wrapped.join('\n')
}

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