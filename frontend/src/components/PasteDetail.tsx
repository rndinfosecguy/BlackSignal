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

const HIGHLIGHT_LIMIT = 100000

interface Secret { type: string; line: number; match: string }
interface PasteDetailData {
  id: string; filename: string; source: string; content: string
  content_type: string; size: number; has_passwords: boolean
  has_secrets: boolean; secrets_detail: Secret[] | null; first_seen: string
}
interface Props { id: string; onClose: () => void }

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

  const highlighted = useMemo(() => {
    if (!paste || !contentVisible) return ''
    const lang = TYPE_LANG_MAP[paste.content_type] || 'plaintext'
    const content = paste.content.length > HIGHLIGHT_LIMIT ? paste.content.slice(0, HIGHLIGHT_LIMIT) : paste.content
    try { return hljs.highlight(content, { language: lang }).value }
    catch {
      const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      return esc(content)
    }
  }, [paste, contentVisible])

  const isTruncated = paste ? paste.content.length > HIGHLIGHT_LIMIT : false

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-[#0d0d0d] border border-[#222222] rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-[#222222]">
          <div className="flex items-center gap-3">
            <span className="text-sm text-[#e8e8e8] font-medium">{paste?.source || 'Paste Detail'}</span>
            <span className="text-xs text-[#666666]">{paste?.content_type}</span>
            <span className="text-xs text-[#555555]" style={{ fontFamily: 'var(--font-mono)' }}>{paste?.filename}</span>
          </div>
          <div className="flex items-center gap-2.5">
            {paste?.has_passwords && (
              <span className="text-[10px] px-2 py-1 rounded bg-[#ff004d]/10 text-[#ff004d]">Passwords</span>
            )}
            <button onClick={handleCopy}
              className="text-xs px-3 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all">
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button onClick={onClose} className="text-[#666666] hover:text-[#ff004d] text-lg transition-all leading-none">&times;</button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-[#555555]">Loading...</div>
          ) : fetchError ? (
            <div className="flex items-center justify-center h-32">
              <div className="text-center">
                <div className="text-[#ff004d] text-sm mb-1">Failed to load paste</div>
                <div className="text-[#555555] text-xs">{id.slice(0, 24)}...</div>
              </div>
            </div>
          ) : paste ? (
            <div>
              {paste.secrets_detail && paste.secrets_detail.length > 0 && (
                <div className="mb-3 pb-3 border-b border-[#222222]">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs text-[#ff004d] font-medium">{paste.secrets_detail.length} secret{paste.secrets_detail.length === 1 ? '' : 's'} detected</div>
                    <button onClick={() => setContentVisible(!contentVisible)}
                      className="text-xs text-[#666666] hover:text-[#00e5ff] transition-all">
                      {contentVisible ? 'Hide full content' : 'Show full content'}
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
              {!contentVisible && (
                <div className="flex items-center justify-center py-10">
                  <button onClick={() => setContentVisible(true)}
                    className="text-xs px-5 py-2 rounded-md border border-[#222222] text-[#666666] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all cursor-pointer">
                    Show full paste content
                  </button>
                </div>
              )}
              {contentVisible && (
                <>
                  {isTruncated && <div className="text-[10px] text-[#555555] mb-2">Content truncated to {Math.round(HIGHLIGHT_LIMIT / 1000)}KB</div>}
                  <pre className="text-sm leading-relaxed whitespace-pre-wrap break-all" style={{ fontFamily: 'var(--font-mono)' }}>
                    <code className="hljs" dangerouslySetInnerHTML={{ __html: highlighted }} />
                  </pre>
                </>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}