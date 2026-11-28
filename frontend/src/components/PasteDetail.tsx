import { useEffect, useState, useMemo, useRef } from 'react'
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
import markdown_h from 'highlight.js/lib/languages/markdown'
import { fetchPasteDetail, updateTriage } from '../hooks/usePastes'
import { formatSize, splitHighlighted, renderMarkdown } from '../lib/utils'
import { lockScroll } from '../lib/scrollLock'

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
hljs.registerLanguage('markdown', markdown_h)

const TYPE_LANG_MAP: Record<string, string> = {
  json: 'json', html: 'xml', xml: 'xml', python: 'python',
  javascript: 'javascript', shell: 'bash', php: 'php', java: 'java',
  c: 'c', markdown: 'markdown', csv: 'bash', sql: 'sql', css: 'css',
}

const SCAN_LIMIT = 200000  // must match backend/detector.py scan_content() default
const RENDER_LINE_LIMIT = 2000    // cap rendered lines to prevent browser freeze
const RENDER_CHAR_LIMIT = 200000  // cap rendered chars to prevent browser freeze (matches backend scan limit)

interface Secret { type: string; line: number; match: string }
interface PasteDetailData {
  id: string; filename: string; source: string; content: string
  content_type: string; size: number; has_passwords: boolean
  has_secrets: boolean; secrets_detail: Secret[] | null; first_seen: string
  fully_scanned: boolean
  modified_at?: string | null
  triage_status?: string
  triage_note?: string
  triage_reviewer?: string
  triage_updated_at?: string | null
}
interface Props { id: string; onClose: () => void; onTriageSaved?: () => void }

const TRIAGE_OPTIONS = [
  { id: 'new', label: 'New', color: '#888888' },
  { id: 'reviewed', label: 'Reviewed', color: '#00ff41' },
  { id: 'false_positive', label: 'False positive', color: '#ffd700' },
  { id: 'escalated', label: 'Escalated', color: '#ff004d' },
]

export default function PasteDetail({ id, onClose, onTriageSaved }: Props) {
  const [paste, setPaste] = useState<PasteDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(false)
  const [copied, setCopied] = useState(false)
  const [contentVisible, setContentVisible] = useState(true)
  const fetchReqId = useRef(0)

  // Triage state
  const [triageStatus, setTriageStatus] = useState('new')
  const [triageNote, setTriageNote] = useState('')
  const [triageSaving, setTriageSaving] = useState(false)
  const [triageMsg, setTriageMsg] = useState<string | null>(null)

  // LLM state
  const [llmConfigured, setLlmConfigured] = useState(false)
  const [llmLoading, setLlmLoading] = useState(false)
  const [llmResponse, setLlmResponse] = useState<string | null>(null)
  const [llmError, setLlmError] = useState<string | null>(null)

  useEffect(() => {
    const reqId = ++fetchReqId.current
    setLoading(true)
    setFetchError(false)
    setLlmResponse(null)
    setLlmError(null)

    // Fetch paste detail and LLM config in parallel
    Promise.all([
      fetchPasteDetail(id),
      fetch('/api/llm/config').then(r => r.json()).then(d => d.configured).catch(() => false),
    ]).then(([p, configured]) => {
      if (fetchReqId.current !== reqId) return
      setPaste(p)
      setLlmConfigured(configured)
      setLoading(false)
      if (!p) setFetchError(true)
      else if (p.secrets_detail && p.secrets_detail.length > 0) setContentVisible(false)
      else setContentVisible(true)
      setTriageStatus(p?.triage_status || 'new')
      setTriageNote(p?.triage_note || '')
      setTriageMsg(null)
    }).catch(() => {
      if (fetchReqId.current !== reqId) return
      setLoading(false)
      setFetchError(true)
    })
  }, [id])

  // Lock background scrolling while the modal is open.
  useEffect(() => lockScroll(), [])

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

  const handleLlmSummarize = async () => {
    if (llmLoading || !paste) return
    setLlmLoading(true)
    setLlmError(null)
    setLlmResponse(null)
    try {
      const res = await fetch(`/api/llm/summarize/${encodeURIComponent(id)}`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      setLlmResponse(data.summary)
    } catch (e: unknown) {
      setLlmError(e instanceof Error ? e.message : 'Summarization failed')
    } finally {
      setLlmLoading(false)
    }
  }

  const handleDownloadSummary = () => {
    if (!llmResponse) return
    const blob = new Blob([llmResponse], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${paste?.source ?? 'paste'}_${paste?.filename || paste?.id || id}_summary.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleSaveTriage = async (reset = false) => {
    if (!paste || triageSaving) return
    const status = reset ? 'new' : triageStatus
    const note = reset ? '' : triageNote
    setTriageSaving(true)
    setTriageMsg(null)
    try {
      const updated = await updateTriage(id, { status, note })
      setPaste(prev => (prev ? { ...prev, ...updated } : prev))
      setTriageStatus(updated.triage_status)
      setTriageNote(updated.triage_note)
      setTriageMsg(reset ? 'Reset to new' : 'Saved')
      onTriageSaved?.()
      setTimeout(() => setTriageMsg(null), 2500)
    } catch (e: unknown) {
      setTriageMsg(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setTriageSaving(false)
    }
  }

  // modified_at is stored as epoch seconds; triage_updated_at is ISO-8601.
  const changedSinceTriage = (() => {
    if (!paste?.triage_updated_at || !paste?.modified_at) return false
    const raw = paste.modified_at
    const modMs = /^\d+$/.test(raw) ? Number(raw) * 1000 : Date.parse(raw)
    const triMs = Date.parse(paste.triage_updated_at)
    return Number.isFinite(modMs) && Number.isFinite(triMs) && modMs > triMs
  })()

  const highlighted = useMemo(() => {
    if (!paste || !contentVisible) return ''
    const lang = TYPE_LANG_MAP[paste.content_type] || 'plaintext'
    const txt = paste.content || ''
    const isLong = txt.length > RENDER_CHAR_LIMIT
    const input = isLong ? txt.slice(0, RENDER_CHAR_LIMIT) : txt
    try {
      return hljs.highlight(input, { language: lang }).value
    } catch {
      const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      return esc(input)
    }
  }, [paste, contentVisible])

  const highlightedLines = useMemo(
    () => (highlighted ? splitHighlighted(highlighted) : []),
    [highlighted],
  )

  const isTruncated = useMemo(() => {
    if (!paste) return false
    const lineCount = paste.content?.split('\n')?.length || 0
    const charCount = paste.content?.length || 0
    return lineCount > RENDER_LINE_LIMIT || charCount > RENDER_CHAR_LIMIT
  }, [paste])

  // Set of line numbers that have detected secrets (for inline highlighting).
  const secretLines = useMemo(() => {
    const s = new Set<number>()
    if (paste?.secrets_detail) paste.secrets_detail.forEach(d => s.add(d.line))
    return s
  }, [paste])

  const llmResponseHtml = useMemo(
    () => llmResponse ? renderMarkdown(llmResponse) : null,
    [llmResponse],
  )

  return (
    <div onClick={onClose} className="fixed inset-0 z-50 flex items-center justify-center bg-[#0d0d0d]/70 backdrop-blur-sm overflow-y-hidden p-4">
      <div onClick={e => e.stopPropagation()} className="bg-[#0d0d0d] border border-[#222222] rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-[#222222]">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm text-[#e8e8e8] font-medium whitespace-nowrap">{paste?.source || 'Paste Detail'}</span>
            <span className="text-xs text-[#666666] whitespace-nowrap">{paste?.content_type}</span>
            <span className="text-xs text-[#555555] truncate max-w-[200px]" style={{ fontFamily: 'var(--font-mono)' }} title={paste?.filename}>{paste?.filename}</span>
            <span className="text-[10px] text-[#444444] whitespace-nowrap">Indexed: {paste?.first_seen?.slice(0, 10)}</span>
            <span className="text-[10px] text-[#444444] whitespace-nowrap">{formatSize(paste?.size || 0)}</span>
            {paste?.content && paste.content.length > SCAN_LIMIT && !paste.fully_scanned && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#ffd700]/10 text-[#ffd700]/80 whitespace-nowrap"
                title="Only first defined chars were scanned. Line numbers and detected secrets beyond this limit may be incorrect.">
                partial scan
              </span>
            )}
          </div>
          <div className="flex items-center gap-2.5">
            {/* LLM Summarize button */}
            <button onClick={handleLlmSummarize} disabled={llmLoading || !llmConfigured}
              className="text-xs px-3 py-1.5 rounded-md border border-[#ff004d]/40 text-[#ff004d] hover:bg-[#ff004d]/10 hover:border-[#ff004d] transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              title={!llmConfigured ? 'Add an OpenRouter API key in the Config tab to enable' : 'Analyze this paste with LLM'}>
              {llmLoading ? (
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-3 h-3 rounded-full border-2 border-transparent border-t-[#ff004d] border-r-[#ff004d]/60 animate-spin" />
                  Analyzing...
                </span>
              ) : llmResponse ? 'Analyze Again' : 'Analyze with LLM'}
            </button>
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

        {paste && (
          <div className="p-4 border-b border-[#222222] bg-[#0d0d0d]">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs text-[#ff004d] font-medium">Triage</div>
              <div className="text-[10px] text-[#555555]">
                {paste.triage_status && paste.triage_status !== 'new' && paste.triage_reviewer
                  ? `${paste.triage_reviewer} · ${paste.triage_updated_at ? new Date(paste.triage_updated_at).toLocaleString() : 'just now'}`
                  : 'Not reviewed'}
                {changedSinceTriage && (
                  <span className="text-[#ffd700]/80 ml-2">content changed since triage</span>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {TRIAGE_OPTIONS.map(opt => {
                const active = triageStatus === opt.id
                return (
                  <button key={opt.id} onClick={() => setTriageStatus(opt.id)}
                    className="text-[11px] px-2.5 py-1 rounded-md border transition-all cursor-pointer"
                    style={{
                      borderColor: active ? opt.color : '#222222',
                      color: active ? opt.color : '#666666',
                      backgroundColor: active ? `${opt.color}1a` : 'transparent',
                    }}>
                    {opt.label}
                  </button>
                )
              })}
            </div>
            <textarea
              value={triageNote}
              onChange={e => setTriageNote(e.target.value)}
              maxLength={2000}
              rows={2}
              placeholder="Note (optional)"
              className="w-full bg-[#0d0d0d] border border-[#222222] rounded-md px-2.5 py-1.5 text-xs text-[#e8e8e8] outline-none focus:border-[#ff004d] transition-colors resize-y"
            />
            <div className="flex items-center gap-2 mt-2">
              <button onClick={() => handleSaveTriage(false)} disabled={triageSaving}
                className="text-[11px] px-3 py-1 rounded-md border border-[#ff004d]/40 text-[#ff004d] hover:bg-[#ff004d]/10 transition-all disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer">
                {triageSaving ? 'Saving...' : 'Save'}
              </button>
              <button onClick={() => handleSaveTriage(true)} disabled={triageSaving}
                className="text-[11px] px-3 py-1 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer">
                Reset
              </button>
              {triageMsg && <span className="text-[11px] text-[#888888]">{triageMsg}</span>}
            </div>
          </div>
        )}

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

        <div className="flex-1 overflow-y-auto overflow-x-scroll px-4 pt-4 pb-4">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-[#555555]">Loading...</div>
          ) : fetchError ? (
            <div className="flex items-center justify-center h-32">
              <div className="text-center">
                <div className="text-[#ff004d] text-sm mb-1">Failed to load paste</div>
                <div className="text-[#555555] text-xs">{id.slice(0, 24)}...</div>
              </div>
            </div>
          ) : (
            <>
            {llmLoading && (
              <div className="bg-[#0a0a0a] border border-[#222222] rounded-lg p-4 mb-3">
                <div className="flex items-center gap-3 text-xs text-[#555555]">
                  <span className="inline-block w-4 h-4 rounded-full border-2 border-transparent border-t-[#ff004d] border-r-[#ff004d]/60 animate-spin" />
                  Contacting LLM for analysis...
                </div>
              </div>
            )}
            {llmError && !llmLoading && (
              <div className="bg-[#0a0a0a] border border-[#222222] rounded-lg p-3 mb-3">
                <div className="text-xs text-[#ff004d]">LLM Error: {llmError}</div>
              </div>
            )}
            {llmResponseHtml && (
              <div className="bg-[#0a0a0a] border border-[#222222] rounded-lg p-4 mb-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-xs text-[#ff004d] font-medium">LLM Analysis</div>
                  <button onClick={handleDownloadSummary}
                    className="text-[11px] px-2.5 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#ff004d] hover:border-[#ff004d] transition-all cursor-pointer">
                    Download Summary
                  </button>
                </div>
                {paste && paste.size > SCAN_LIMIT && (
                  <div className="text-xs text-[#ffd700]/80 px-3 py-2 mb-3 bg-[#131313] rounded-md"
                    style={{ borderLeft: '3px solid #ffd700' }}>
                    Only the first 200 KB of content were analyzed by the LLM. The full paste may contain additional data beyond this limit.
                  </div>
                )}
                <div className="text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: llmResponseHtml }} />
              </div>
            )}
            {paste && contentVisible && (
              <div className="flex-1 min-w-0">
                {isTruncated && (
                  <div className="text-xs text-[#ffd700]/80 px-3 py-2 mb-2 bg-[#131313] rounded-md">
                    File is large - only first 2,000 lines or 200KB are shown.
                    Use the Download button to view the full content.
                  </div>
                )}
                {highlightedLines.map((lineHtml, i) => (
                  <div key={i} className="flex items-start">
                    <code
                      className="hljs block shrink-0 select-none text-right"
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 13,
                        lineHeight: 1.7,
                        color: '#555555',
                        paddingRight: '0.75rem',
                        marginRight: '0.75rem',
                        borderRight: '1px solid #222222',
                        ...(secretLines.has(i + 1) ? { borderLeft: '2px solid rgba(255,0,77,0.5)' } : {}),
                      }}
                    >{i + 1}</code>
                    <code
                      className="hljs block whitespace-pre flex-1 min-w-0"
                      style={{ fontFamily: 'var(--font-mono)', fontSize: 13, lineHeight: 1.7 }}
                      dangerouslySetInnerHTML={{ __html: lineHtml || ' ' }}
                    />
                  </div>
                ))}
              </div>
            )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}