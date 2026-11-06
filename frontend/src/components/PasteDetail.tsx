import { useEffect, useState, useMemo } from 'react'
import hljs from 'highlight.js/lib/core'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import css from 'highlight.js/lib/languages/css'
import sql from 'highlight.js/lib/languages/sql'
import bash from 'highlight.js/lib/languages/bash'
import php from 'highlight.js/lib/languages/php'
import java from 'highlight.js/lib/languages/java'
import c from 'highlight.js/lib/languages/c'
import markdown from 'highlight.js/lib/languages/markdown'
import { fetchPasteDetail } from '../hooks/usePastes'

hljs.registerLanguage('json', json)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('css', css)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('php', php)
hljs.registerLanguage('java', java)
hljs.registerLanguage('c', c)
hljs.registerLanguage('markdown', markdown)

const TYPE_LANG_MAP: Record<string, string> = {
  json: 'json', html: 'xml', xml: 'xml', python: 'python',
  javascript: 'javascript', shell: 'bash', php: 'php', java: 'java',
  c: 'c', markdown: 'markdown', csv: 'bash', sql: 'sql', css: 'css',
}

/**
 * Split highlighted HTML into per-line, tag-balanced chunks so each line can be
 * rendered separately (for the gutter) without leaking open <span> tags across
 * line boundaries.
 */
function splitHighlighted(html: string): string[] {
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

interface Secret { type: string; line: number; match: string }
interface PasteDetailData {
  id: string; filename: string; source: string; content: string
  content_type: string; size: number; has_passwords: boolean
  has_secrets: boolean; secrets_detail: Secret[] | null; first_seen: string
}
interface Props { id: string; onClose: () => void }

function formatSize(bytes: number): string {
  if (bytes <= 0) return 'empty'
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

export default function PasteDetail({ id, onClose }: Props) {
  const [paste, setPaste] = useState<PasteDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(false)
  const [copied, setCopied] = useState(false)
  const [contentVisible, setContentVisible] = useState(true)

  useEffect(() => {
    setLoading(true)
    setFetchError(false)
    fetchPasteDetail(id).then(p => {
      setPaste(p)
      setLoading(false)
      if (!p) setFetchError(true)
      else if (p.secrets_detail && p.secrets_detail.length > 0) setContentVisible(false)
      else setContentVisible(true)
    }).catch(() => {
      setLoading(false)
      setFetchError(true)
    })
  }, [id])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const handleCopy = () => {
    if (!paste) return
    navigator.clipboard.writeText(paste.content).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 2000)
    }).catch(() => {})
  }

  const handleDownload = () => {
    if (!paste) return
    const blob = new Blob([paste.content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${paste.source}_${paste.filename || paste.id}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const highlighted = useMemo(() => {
    if (!paste || !contentVisible) return ''
    const lang = TYPE_LANG_MAP[paste.content_type] || 'plaintext'
    try {
      const txt = paste.content || ''
      return hljs.highlight(txt, { language: lang }).value
    } catch {
      const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      return esc(paste.content || '')
    }
  }, [paste, contentVisible])

  const highlightedLines = useMemo(
    () => (highlighted ? splitHighlighted(highlighted) : []),
    [highlighted],
  )

  // Gutter line count — computed from raw content (same as scanner's split("\n"))
  // so line numbers always match regardless of highlight.js output quirks.
  const totalLines = useMemo(() => {
    if (!paste || !contentVisible) return 0
    return paste.content.split('\n').length
  }, [paste, contentVisible])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-[#0d0d0d] border border-[#222222] rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-[#222222]">
          <div className="flex items-center gap-3">
            <span className="text-sm text-[#e8e8e8] font-medium">{paste?.source || 'Paste Detail'}</span>
            <span className="text-xs text-[#666666]">{paste?.content_type}</span>
            <span className="text-xs text-[#555555]" style={{ fontFamily: 'var(--font-mono)' }}>{paste?.filename}</span>
            <span className="text-[10px] text-[#444444]">{formatSize(paste?.size || 0)}</span>
          </div>
          <div className="flex items-center gap-2.5">
            
            <button onClick={handleCopy}
              className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all">
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button onClick={handleDownload}
              className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all">
              Download
            </button>
            <button onClick={onClose} className="text-[#666666] hover:text-[#ff004d] text-lg transition-all leading-none">&times;</button>
          </div>
        </div>

        {paste && paste.secrets_detail && paste.secrets_detail.length > 0 && (
          <div className="bg-[#0d0d0d] p-4 border-b border-[#222222]">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs text-[#ff004d] font-medium">{paste.secrets_detail.length} secret{paste.secrets_detail.length === 1 ? '' : 's'} detected</div>
              <button onClick={() => setContentVisible(!contentVisible)}
                className="text-[11px] px-2.5 py-1.5 rounded-md border border-[#222222] text-[#00e5ff] hover:text-[#ff004d] transition-all cursor-pointer">
                {contentVisible ? 'Hide content' : 'Show content'}
              </button>
            </div>
            <div className="space-y-0.5 max-h-40 overflow-y-auto">
              {paste.secrets_detail.map((s, i) => (
                <div key={i} className="text-xs text-[#777777] leading-relaxed">
                  <span className="text-[#ff004d]">ln {s.line}</span>
                  <span className="text-[#ffd700] ml-1">[{s.type}]</span>
                  <span className="text-[#555555] ml-1" style={{ fontFamily: 'var(--font-mono)' }}>{s.match}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        
        <div className="flex-1 overflow-auto px-4 pb-4">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-[#555555]">Loading...</div>
          ) : fetchError ? (
            <div className="flex items-center justify-center h-32">
              <div className="text-center">
                <div className="text-[#ff004d] text-sm mb-1">Failed to load paste</div>
                <div className="text-[#555555] text-xs">{id.slice(0, 24)}...</div>
              </div>
            </div>
          ) : paste && contentVisible ? (
            <div className="flex">
              <div
                className="shrink-0 select-none text-right pr-3 mr-3 border-r border-[#222222] text-[#555555]"
                style={{ fontFamily: 'var(--font-mono)', fontSize: 13, lineHeight: 1.7 }}
              >
                {Array.from({length: totalLines}).map((_, i) => (
                  <div key={i}>{i + 1}</div>
                ))}
              </div>
              <div className="flex-1 min-w-0 overflow-x-auto">
                {highlightedLines.map((lineHtml, i) => (
                  <code
                    key={i}
                    className="hljs block whitespace-pre"
                    dangerouslySetInnerHTML={{ __html: lineHtml || ' ' }}
                  />
                ))}
              </div>
            </div>
          ) : paste ? null : null}
        </div>
      </div>
    </div>
  )
}