import { useEffect, useState } from 'react'

interface DbStats {
  db_size_bytes: number
  paste_count: number
  raw_pastes_size_bytes: number
  raw_files_total: number
  indexable_files_count: number
}

interface IndexerInfo {
  interval_seconds: number
  next_run: string | null
  running: boolean
}

interface LastReindex {
  indexed: number
  deleted: number
  skipped: number
  total: number
}

interface Props {
  onReindex: (mode: string) => void
}

export default function ConfigTab({ onReindex }: Props) {
  const [dbStats, setDbStats] = useState<DbStats | null>(null)
  const [indexerInfo, setIndexerInfo] = useState<IndexerInfo | null>(null)
  const [lastReindex, setLastReindex] = useState<LastReindex | null>(null)
  const [keyPreview, setKeyPreview] = useState('')
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [confirmReindex, setConfirmReindex] = useState<string | null>(null)
  const [editingInterval, setEditingInterval] = useState(false)
  const [intervalValue, setIntervalValue] = useState('')
  const [intervalError, setIntervalError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/db-stats')
      .then(r => r.json())
      .then(setDbStats)
      .catch(() => {})
    fetch('/api/llm/key')
      .then(r => r.json())
      .then(d => setKeyPreview(d.key_preview || ''))
      .catch(() => {})
  }, [])

  // Indexer state changes at runtime (reindex runs, interval changes) — keep the
  // in-memory endpoints fresh while this tab is open instead of a one-shot read.
  useEffect(() => {
    let cancelled = false
    const loadIndexer = () => {
      fetch('/api/indexer-info')
        .then(r => r.json())
        .then(d => { if (!cancelled) setIndexerInfo(d) })
        .catch(() => {})
      fetch('/api/last-reindex')
        .then(r => r.json())
        .then(d => { if (!cancelled) setLastReindex(Object.keys(d).length > 0 ? d : null) })
        .catch(() => {})
    }
    loadIndexer()
    const interval = setInterval(loadIndexer, 15000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  const handleEdit = () => {
    setEditValue('')
    setShowKey(false)
    setSaveMsg(null)
    setEditing(true)
  }

  const handleCancel = () => {
    setEditing(false)
    setEditValue('')
    setSaveMsg(null)
  }

  const handleSave = async () => {
    if (!editValue.trim()) return
    setSaving(true)
    setSaveMsg(null)
    try {
      const res = await fetch('/api/llm/key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: editValue.trim() }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Save failed')
      const previewRes = await fetch('/api/llm/key')
      const previewData = await previewRes.json()
      setKeyPreview(previewData.key_preview || '')
      setEditing(false)
      setSaveMsg('Key saved successfully.')
      setTimeout(() => setSaveMsg(null), 3000)
    } catch (e: unknown) {
      setSaveMsg(e instanceof Error ? e.message : 'Failed to save key')
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async () => {
    if (!confirmRemove) {
      setConfirmRemove(true)
      return
    }
    setConfirmRemove(false)
    setSaving(true)
    setSaveMsg(null)
    try {
      const res = await fetch('/api/llm/key', { method: 'DELETE' })
      if (!res.ok) throw new Error('Remove failed')
      setKeyPreview('')
      setSaveMsg('Key removed.')
      setTimeout(() => setSaveMsg(null), 3000)
    } catch (e: unknown) {
      setSaveMsg(e instanceof Error ? e.message : 'Failed to remove key')
    } finally {
      setSaving(false)
    }
  }

  const handleReindex = (mode: string) => {
    setConfirmReindex(mode)
  }

  const handleEditInterval = () => {
    if (indexerInfo) {
      setIntervalValue(String(indexerInfo.interval_seconds / 3600))
    }
    setIntervalError(null)
    setEditingInterval(true)
  }

  const handleCancelInterval = () => {
    setEditingInterval(false)
    setIntervalValue('')
    setIntervalError(null)
  }

  const handleSaveInterval = async () => {
    const val = parseFloat(intervalValue)
    if (isNaN(val) || val < 1) {
      setIntervalError('Minimum 1 hour')
      return
    }
    const seconds = Math.round(val * 3600)
    setIntervalError(null)
    try {
      const res = await fetch('/api/indexer-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval_seconds: seconds }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to update interval')
      setIndexerInfo(data)
      setEditingInterval(false)
    } catch (e: unknown) {
      setIntervalError(e instanceof Error ? e.message : 'Failed to update interval')
    }
  }

  const triggerReindex = (mode: string) => {
    setConfirmReindex(null)
    onReindex(mode)
  }

  const fmt = (bytes: number): string => {
    if (bytes <= 0) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB']
    const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
  }

  const fmtInterval = (secs: number): string => {
    if (secs < 60) return `${secs}s`
    if (secs < 3600) return `${Math.round(secs / 60)}m`
    if (secs % 3600 === 0) return `${secs / 3600}h`
    return `${(secs / 3600).toFixed(1)}h`
  }

  const fmtNextRun = (iso: string | null): string => {
    if (!iso) return 'Unknown'
    const d = new Date(iso)
    const now = new Date()
    const diff = d.getTime() - now.getTime()
    if (diff < 0) return 'Any moment now'
    const mins = Math.round(diff / 60000)
    if (mins < 1) return 'Any moment now'
    if (mins < 60) return `In ${mins}m`
    const hours = Math.floor(mins / 60)
    const rem = mins % 60
    return rem > 0 ? `In ${hours}h ${rem}m` : `In ${hours}h`
  }

  return (
    <div className="space-y-5">
      {/* Indexing section */}
      <div className="bg-[#131313] border border-[#222222] rounded-lg p-5">
        <div className="text-xs text-[#888888] font-medium mb-4 uppercase tracking-wider">
          Indexing
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div>
            <div className="text-xs text-[#555555] mb-1">Auto-index interval</div>
            {editingInterval ? (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <input
                    type="number"
                    min={1}
                    step="0.5"
                    value={intervalValue}
                    onChange={e => setIntervalValue(e.target.value)}
                    className="w-20 bg-[#0d0d0d] border border-[#222222] rounded-md px-2 py-1 text-xs text-[#e8e8e8] outline-none focus:border-[#ff004d] transition-colors"
                  />
                  <span className="text-xs text-[#555555]">hours</span>
                </div>
                <div className="flex items-center gap-1.5 mt-1">
                  <button onClick={handleSaveInterval}
                    className="text-[11px] px-2 py-1 rounded-md border border-[#ff004d]/40 text-[#ff004d] hover:bg-[#ff004d]/10 transition-all cursor-pointer">
                    Save
                  </button>
                  <button onClick={handleCancelInterval}
                    className="text-[11px] px-2 py-1 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all cursor-pointer">
                    Cancel
                  </button>
                </div>
                {intervalError && <div className="text-xs text-[#ff004d]">{intervalError}</div>}
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-sm text-[#e8e8e8]">
                  {indexerInfo ? fmtInterval(indexerInfo.interval_seconds) : '...'}
                </span>
                <button onClick={handleEditInterval}
                  className="text-[10px] px-1.5 py-0.5 rounded border border-[#222222] text-[#555555] hover:text-[#ff004d] hover:border-[#ff004d] transition-all cursor-pointer">
                  Edit
                </button>
              </div>
            )}
          </div>
          <div>
            <div className="text-xs text-[#555555] mb-1">Next auto index</div>
            <div className="text-sm text-[#e8e8e8]">
              {indexerInfo ? fmtNextRun(indexerInfo.next_run) : '...'}
            </div>
          </div>
          <div>
            <div className="text-xs text-[#555555] mb-1">Last result</div>
            <div className="text-sm text-[#e8e8e8]">
              {lastReindex ? (
                <span>
                  <span className="text-[#00e5ff]">{lastReindex.indexed}</span> new,{' '}
                  <span className="text-[#ff004d]">{lastReindex.deleted}</span> deleted
                  {lastReindex.skipped > 0 && <span>, <span className="text-[#ffd700]">{lastReindex.skipped}</span> skipped</span>}
                </span>
              ) : (
                <span className="text-[#555555]">Not yet indexed</span>
              )}
            </div>
          </div>
          <div>
            <div className="text-xs text-[#555555] mb-1"
              title="Files discovered under raw_pastes during the last index run. Includes files skipped as too small (<32 bytes), so it can be higher than the number of pastes in the database.">
              Files scanned (last run)
            </div>
            <div className="text-sm text-[#e8e8e8]">
              {lastReindex ? lastReindex.total.toLocaleString() : '...'}
            </div>
          </div>
        </div>
      </div>

      {/* Reindex section */}
      <div className="bg-[#131313] border border-[#222222] rounded-lg p-5">
        <div className="text-xs text-[#888888] font-medium mb-4 uppercase tracking-wider">
          Reindex
        </div>
        <div className="space-y-3">
          <div onClick={() => handleReindex('standard')}
            className="flex items-center justify-between p-4 rounded-lg border border-[#222222] cursor-pointer hover:bg-[#00e5ff]/5 transition-all">
            <div>
              <div className="text-sm font-medium text-[#00e5ff]">Standard reindex</div>
              <div className="text-xs text-[#555555] mt-1">200K limit per file — quick, respects size limits</div>
            </div>
            <span className="text-[#00e5ff] text-lg">▶</span>
          </div>

          <details className="border border-[#222222] rounded-lg p-4 open:border-[#ffd700]">
            <summary className="text-sm font-medium text-[#ffd700] cursor-pointer">Comprehensive reindex</summary>
            <div className="mt-3 text-xs text-[#777777] leading-relaxed">
              Disables the file size limit and scans the full content of every paste.
              The additional detections depend on your data — pastes with many large files
              will benefit more. It can take significantly longer; for large datasets it
              could take hours.
            </div>
            <button onClick={() => handleReindex('comprehensive')}
              className="w-full mt-3 text-sm px-4 py-2 rounded-md border border-[#ffd700] text-[#ffd700] hover:bg-[#ffd700]/5 transition-all cursor-pointer">
              Start comprehensive reindex
            </button>
          </details>

          <details className="border border-[#222222] rounded-lg p-4">
            <summary className="text-sm font-medium text-[#ff004d] cursor-pointer">Purge & reindex</summary>
            <div className="mt-3 text-xs text-[#ff004d]/80 leading-relaxed">
              Permanently deletes all indexed data from the database and starts a
              fresh reindex from scratch. This cannot be undone. Only use this if
              you want to completely rebuild the index.
            </div>
            <button onClick={() => handleReindex('purge')}
              className="w-full mt-3 text-sm px-4 py-2 rounded-md border border-[#ff004d] text-[#ff004d] hover:bg-[#ff004d]/5 transition-all cursor-pointer">
              Execute purge
            </button>
          </details>
        </div>
      </div>

      {/* Reindex confirmation modal */}
      {confirmReindex && (
        <div onClick={() => setConfirmReindex(null)}
          className="fixed inset-0 z-40 flex items-center justify-center bg-[#0d0d0d]/70 backdrop-blur-sm p-4">
          <div onClick={e => e.stopPropagation()}
            className="bg-[#131313] border border-[#222222] rounded-xl w-full max-w-sm p-6 text-center">
            {(() => {
              const mode = confirmReindex
              const accent = mode === 'purge' ? '#ff004d' : mode === 'comprehensive' ? '#ffd700' : '#00e5ff'
              const title = mode === 'purge' ? 'Purge all data?' : mode === 'comprehensive' ? 'Comprehensive reindex?' : 'Standard reindex?'
              const desc = mode === 'purge'
                ? 'All indexed data will be permanently deleted. A fresh reindex will start from scratch.'
                : mode === 'comprehensive'
                  ? 'All large files will be re-scanned without size limits. This may take a long time.'
                  : 'Only new paste files will be indexed. Already indexed files are skipped.'
              return (
                <>
                <div className="text-sm font-medium mb-3" style={{ color: accent }}>{title}</div>
                <div className="text-xs text-[#555555] mb-5">{desc}</div>
                <div className="flex items-center gap-3 justify-center">
                  <button onClick={() => triggerReindex(mode)}
                    className="text-sm px-5 py-2 rounded-md transition-all cursor-pointer"
                    style={{ border: `1px solid ${accent}`, color: accent, backgroundColor: 'transparent' }}>
                    Yes, start reindex
                  </button>
                  <button onClick={() => setConfirmReindex(null)}
                    className="text-xs px-4 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all cursor-pointer">
                    Cancel
                  </button>
                </div>
                </>
              )
            })()}
          </div>
        </div>
      )}

      {/* Database section */}
      <div className="bg-[#131313] border border-[#222222] rounded-lg p-5">
        <div className="text-xs text-[#888888] font-medium mb-4 uppercase tracking-wider">
          Database
        </div>
        {dbStats ? (
          <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            <div>
              <div className="text-xs text-[#555555] mb-1">Database file size</div>
              <div className="text-sm text-[#e8e8e8]">{fmt(dbStats.db_size_bytes)}</div>
            </div>
            <div>
              <div className="text-xs text-[#555555] mb-1">Indexed pastes</div>
              <div className="text-sm text-[#e8e8e8]">{dbStats.paste_count.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-xs text-[#555555] mb-1">Raw pastes size</div>
              <div className="text-sm text-[#e8e8e8]">{fmt(dbStats.raw_pastes_size_bytes)}</div>
            </div>
            <div>
              <div className="text-xs text-[#555555] mb-1"
                title="Regular files directly inside each source folder — the files the indexer will scan.">
                Indexable files
              </div>
              <div className="text-sm text-[#e8e8e8]">{dbStats.indexable_files_count.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-xs text-[#555555] mb-1"
                title="All files under raw_pastes, recursively — including nested folders and files outside source folders, which the indexer ignores.">
                Files on disk (recursive)
              </div>
              <div className="text-sm text-[#e8e8e8]">{dbStats.raw_files_total.toLocaleString()}</div>
            </div>
          </div>
          {dbStats.raw_files_total > dbStats.indexable_files_count && (
            <div className="text-xs text-[#ffd700]/80 mt-3"
              title="Files nested in subfolders or placed directly in raw_pastes/ are not indexed. Only files directly inside a source folder are scanned.">
              {(dbStats.raw_files_total - dbStats.indexable_files_count).toLocaleString()} file(s) won't be indexed (nested or outside source folders)
            </div>
          )}
          </>
        ) : (
          <div className="text-xs text-[#555555]">Loading...</div>
        )}
      </div>

      {/* OpenRouter API Key section */}
      <div className="bg-[#131313] border border-[#222222] rounded-lg p-5">
        <div className="text-xs text-[#888888] font-medium mb-4 uppercase tracking-wider">
          OpenRouter API Key
        </div>

        {editing ? (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-[#555555] block mb-1">API Key</label>
              <div className="flex items-center gap-2">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={editValue}
                  onChange={e => setEditValue(e.target.value)}
                  placeholder="sk-or-v1-..."
                  className="flex-1 bg-[#0d0d0d] border border-[#222222] rounded-md px-3 py-2 text-xs text-[#e8e8e8] outline-none focus:border-[#00e5ff] transition-colors"
                />
                <button onClick={() => setShowKey(!showKey)}
                  className="text-[11px] px-2 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all cursor-pointer">
                  {showKey ? 'Hide' : 'Show'}
                </button>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleSave} disabled={saving || !editValue.trim()}
                className="text-xs px-4 py-1.5 rounded-md border border-[#00e5ff]/40 text-[#00e5ff] hover:bg-[#00e5ff]/10 hover:border-[#00e5ff] transition-all disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer">
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button onClick={handleCancel}
                className="text-xs px-4 py-1.5 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all cursor-pointer">
                Cancel
              </button>
            </div>
            {saveMsg && (
              <div className={`text-xs ${saveMsg.includes('success') ? 'text-[#00ff41]' : 'text-[#ff004d]'}`}>
                {saveMsg}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <span className="text-xs text-[#555555] block mb-1">Current key</span>
              {keyPreview ? (
                <span className="text-sm text-[#e8e8e8] font-mono">{keyPreview}</span>
              ) : (
                <span className="text-sm text-[#555555] italic">Not configured</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleEdit}
                className="text-xs px-4 py-1.5 rounded-md border border-[#222222] text-[#666666] hover:text-[#00e5ff] hover:border-[#00e5ff] transition-all cursor-pointer">
                {keyPreview ? 'Change' : 'Set Key'}
              </button>
              {keyPreview && !confirmRemove && (
                <button onClick={handleRemove}
                  className="text-xs px-4 py-1.5 rounded-md border border-[#ff004d]/40 text-[#ff004d] hover:bg-[#ff004d]/10 hover:border-[#ff004d] transition-all cursor-pointer">
                  Remove
                </button>
              )}
              {keyPreview && confirmRemove && (
                <span className="flex items-center gap-2">
                  <span className="text-xs text-[#ff004d]">Remove key?</span>
                  <button onClick={handleRemove}
                    className="text-xs px-3 py-1 rounded-md bg-[#ff004d]/20 border border-[#ff004d] text-[#ff004d] hover:bg-[#ff004d]/30 transition-all cursor-pointer">
                    Yes
                  </button>
                  <button onClick={() => setConfirmRemove(false)}
                    className="text-xs px-3 py-1 rounded-md border border-[#222222] text-[#555555] hover:text-[#666666] transition-all cursor-pointer">
                    No
                  </button>
                </span>
              )}
            </div>
            {saveMsg && (
              <div className="text-xs text-[#00ff41]">{saveMsg}</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}