# Changelog

All notable changes to BlackSignal are documented here.

Dates are based on commit timestamps (UTC+1).

---

## [1.13.2] — 2026-11-24

### Changed
- **Consistent red accent across the UI.** The signature red (`#ff004d`) now also drives
  the navigation tabs (Dashboard / Pastes / Config), the list grouping options
  (None / Source / Type), the search bar focus and button hover, the loading overlay
  spinner, the active pagination page, filter chips and the "+ Add filter" overlay, and
  the auto-index interval edit/save controls in the Config tab.
- Cyan is retained only where it carries meaning: the technical-vs-personal detection
  encoding (cyan = technical, yellow = personal) in the dashboard and secret-type chips.

---

## [1.13.1] — 2026-11-24

### Fixed
- **LLM report no longer freezes the app on large datasets.** The 500-paste cap was
  checked only after every matching paste had been loaded into memory with its full
  content. The cap is now enforced with a cheap `COUNT(*)` before any content is read,
  results are hard-capped in SQL, and paste bodies are fetched lazily one at a time.
- **API responsiveness while indexing.** The indexer runs CPU-bound detection in threads
  inside the same process as the web server, and Python's `re` engine holds the GIL, so
  heavy scans could starve the event loop and stall `/api/index-status` (which delayed the
  loading overlay). Mitigations: startup no longer blocks on a full stats scan, the stats
  warm-up waits until the indexer is idle, the GIL switch interval is lowered to 1 ms, and
  the scan loop yields periodically between lines.
- **Index status polling.** The frontend polled only every 60 s, so a single failed poll
  after a restart delayed the loading overlay by up to a minute. It now polls every 3 s
  while indexing, before the first data load, or after a failed request, and every 60 s
  when idle.
- **LLM report progress bar.** It reset to 0 when per-paste analysis finished. It now stays
  full during the final aggregation, which is labelled "Synthesizing final report…".
- **Config tab "Total indexed"** was misleading — it is the number of files found on disk
  during the last run (including <32-byte files skipped at index time), not the database
  row count. Renamed to **"Files found (last run)"** with a tooltip, and the value now
  refreshes every 15 s while the tab is open.
- **Paste detail spacing** — the first block in the scroll area no longer sticks to the
  top border.
- The LLM loading spinner in the paste detail now uses the red LLM accent instead of cyan.

---

## [1.13.0] — 2026-11-23

### Added
- **LLM per-paste analysis** — "Analyze with LLM" button in the paste detail view sends
  the first 200 KB of a paste to OpenRouter (`meta-llama/llama-3.1-8b-instruct`) and renders
  a structured markdown summary: technical/infrastructure findings, personal/PII findings,
  and a risk assessment. The response can be downloaded as `.md`.
- **LLM batch report** — "LLM Report" in the export row analyzes every paste matching the
  current filters individually, then synthesizes an overall security report (executive
  summary, most critical findings, overview by category, top sources of risk) plus a
  deduplicated **Detailed Findings** table (source, paste ID, type, line, finding).
  Reports run in a background thread with progress polling and can be cancelled.
- **ZIP report download** — the finished report downloads as a bundle with `report.md` at
  the root and one markdown analysis per paste under `pastes/`. Filenames are sanitized and
  de-duplicated to prevent path traversal.
- **Config tab** — new navigation tab combining database statistics (DB size, indexed
  pastes, raw paste size/count), indexer statistics (interval, next run, last result),
  reindex controls, and OpenRouter key management (masked preview, set, change, remove).
- **Editable auto-index interval** — change the periodic reindex interval at runtime
  (minimum 1 hour) without editing `docker-compose.yml`.
- **OpenRouter configuration** — `data/openrouter.json` (`{ "openrouter_key": "..." }`) or
  the Config tab. The key is stored server-side and never exposed to the browser; only a
  masked preview is shown.
- **DB / scheduler API endpoints** — `GET /api/db-stats`, `GET|POST /api/indexer-info`,
  and the `/api/llm/*` endpoints (config, key, summarize, report, report-status,
  report-cancel, report-download).
- **Markdown table and horizontal-rule rendering** — the frontend markdown renderer now
  renders `|` tables and `---` rules, used by the LLM views.

### Changed
- The standalone **Reindex tab was merged into the Config tab** — same standard /
  comprehensive / purge actions and confirmation dialogs, now alongside the other
  operational settings.
- LLM-related buttons and accents use the app's red theme instead of cyan.
- LLM features degrade gracefully: without a configured key the buttons are visible but
  disabled, with a tooltip explaining how to enable them.

---

## [1.12.0] — 2026-11-21

### Added
- **macOS-style command palette filter overlay** — clicking `+ Add filter` opens
  a floating overlay with a blurred backdrop. Category grid (Source / Type / Secrets /
  Date range) leads to chip selection. Filters are batched — changes only apply when
  the overlay closes.
- **Multi-select source and type filters** — `source` and `content_type` API params
  changed from single strings to repeatable lists. Multiple sources or types can be
  selected simultaneously and are combined with `IN (...)` SQL.
- **`fully_scanned` flag** — tracks whether a paste was fully scanned (comprehensive)
  or partially (default 200K limit). "Partially scanned" badge in detail view respects
  this flag.
- **Date range filter** — filter pastes by `first_seen` range with efficient index
  scans. Available via query params `date_from` / `date_to` and the filter overlay.
- **Indexed timestamp display** — paste cards and detail view show `Indexed: YYYY-MM-DD`
  next to the file size.

### Changed
- Source and Type filter pills no longer grey out in the `+ Add filter` menu —
  multi-select means you can always add more.
- "Has secrets" replaces "Secrets only" for clarity.
- Filter changes are batched on overlay close — one API call per category instead of
  one per chip click.

---

## [1.11.0] — 2026-11-21

### Added
- **Date range filter** — filter pastes by `first_seen` range via two date inputs or
  query params `date_from` / `date_to` on `/api/pastes`, `/api/stats`,
  `/api/pastes/export`. Efficient range scans on the existing `first_seen DESC` index.
- **Indexed timestamp display** — paste cards and detail view show `Indexed: YYYY-MM-DD`
  to indicate when the system first analyzed the paste, next to the file size.

---

## [1.10.1] — 2026-11-21

### Fixed
- Large paste content in detail view is capped at 2,000 lines or 200KB to prevent
  browser freeze. A warning banner explains the truncation. Full file still
  available via the Download button.

---

## [1.10.0] — 2026-11-21

### Added
- **`fully_scanned` flag** — new DB column tracks whether a paste was completely scanned
  or only partially (first 200K chars). Comprehensive reindex sets `fully_scanned=1` for
  all files. The "partial scan" label in the detail view respects this flag — it only
  shows for files > 200K that were not fully scanned.

---

## [1.9.2] — 2026-11-21

### Added
- Docker log rotation — `max-size: 10m` with 3 retained files keeps container logs
  bounded at ~30MB regardless of uptime

---

## [1.9.1] — 2026-11-21

### Changed
- Progress updates fire ~10x more frequently for the `/api/index-status` endpoint,
  so the frontend progress bar updates evenly during long index runs instead of
  stalling between log intervals

### Fixed
- Purge uses `DROP TABLE` instead of `DELETE FROM` — reduces clear time from
  30–60s to <50ms on a large database

---

## [1.9.0] — 2026-11-21

### Added
- **Incremental auto-reindex** — the 24h scheduled reindex now only re-processes
  files whose `mtime` has changed. Unchanged files are skipped entirely (no disk I/O,
  no regex scanning). Manual reindexes (standard, comprehensive, purge) are unaffected
  and still perform a full scan.

---

## [1.8.1] — 2026-11-19

### Fixed
- Personal email false positives: block `example.com` / `.org` / `.net` placeholder
  domains, `grokbot` bot addresses, and long local parts (UUIDs / random identifiers)

---

## [1.8.0] — 2026-11-19

### Added
- **Filtered count updates** — when a source or type filter is selected, the chip
  counts for types, sources, and secret types re-fetch to show counts within the
  filtered context (e.g. clicking "pastebin" updates type counts to show how many
  json/text pastes are in pastebin). Global counts are restored when filters clear.

---

## [1.7.0] — 2026-11-19

### Added
- **Loading overlay with liquid glass effect** — when a filter/search takes longer than
  1 second, a full-screen overlay appears with `backdrop-filter: blur(3px)`, a
  semi-transparent dark background, and a centered spinner with "Loading..." text.
  Disappears automatically when the response arrives.

---

## [1.6.1] — 2026-11-19

### Fixed
- Group buttons (Source / Type) are grayed out and non-clickable when no filters are
  active — grouping without filters would show the full dataset, which is redundant
- Grouping auto-switches to "None" when all filters are cleared

---

## [1.6.0] — 2026-11-17

### Added
- **Export findings** — CSV and JSON export of search results at `/api/pastes/export`.
  Respects all active filters (source, type, search query, secret types). CSV includes
  a `secrets_detail` column with the affected line text per finding. JSON includes the
  full structured `secrets_detail` array with `type`, `line`, `match`, and `line_text`.
  Export buttons (CSV / JSON) sit alongside the Group toggle in the pastes tab.
- **`line_text` in findings** — each detection now stores the full line content from
  the paste alongside the match text. A one-time reindex populates this for historical
  pastes.

---

## [1.5.0] — 2026-11-17

### Added
- **Collapsible source/type filters** — Source and Type rows can be collapsed,
  showing only the current selection (e.g. "Source: pastebin" in cyan). Click
  the row header to expand and change filters. Secrets and Category rows
  remain always visible.
- **Search result grouping** — new Group toggle (None / Source / Type) above
  the pastes list. Results are grouped into collapsible sections by source or
  content type, each showing up to 5 preview cards with a "View all" button.
- **Interactive API docs** — Swagger UI at `/api/docs` and ReDoc at
  `/api/redoc`, auto-generated from FastAPI's OpenAPI schema.

---

## [1.4.0] — 2026-11-17

### Added
- **Interactive API docs** — Swagger UI at `/api/docs` and ReDoc at `/api/redoc`,
  auto-generated from FastAPI's OpenAPI schema. Lists every endpoint, parameter,
  and response format with live try-it-out functionality.

---

## [1.3.4] — 2026-11-16

### Fixed
- Paste ID collision across sources — `walk_pastes()` now uses `source:filename` as the
  paste ID instead of the bare filename, preventing data loss when different paste sites
  share the same file naming convention (e.g. both `pastebin/abc123` and `github/abc123`
  now get unique IDs `pastebin:abc123` and `github:abc123`)

---

## [1.3.3] — 2026-11-14

### Fixed
- Credential assignment false positives: skip boolean (`true`/`false`) and config-state
  (`enabled`/`disabled`) values — these are not real credentials

---

## [1.3.2] — 2026-11-13

### Fixed
- FTS5 warm-up query — replaced `MATCH '""'` (syntax error on empty DB) with
  `count(*)` which safely walks the FTS segment tree without erroring
- `/api/index-status` endpoint changed from sync to async — avoids GIL contention with
  indexer worker threads, preventing request delays during big-file processing
- Cache warm-up now also touches the `first_seen DESC` index (main pastes list query)
  and `COUNT(DISTINCT source)` (used by stats)

---

## [1.3.1] — 2026-11-12

### Added
- Cache warm-up now runs after every reindex operation (standard, comprehensive, purge),
  not only at boot — first queries after a manual reindex are just as fast as after boot

### Changed
- Moved warm-up logic from a boot-only thread into `index_all_pastes()` in scheduler,
  so it automatically fires at the end of every index run

---

## [1.3.0] — 2026-11-11

### Added
- **OS filesystem cache warm-up** — common database queries run in a background thread
  at boot, so first-user interactions (source filter, stats, type distribution) serve
  instantly with no cold-start delay
- **Filter chips category row** — Technical / Personal chips separate the flat list of
  secret type chips into two sub-rows with distinct dot colors (teal / yellow)
- **`set_index_running()` helper** — purge now marks itself running before the long
  `clear_all_data()` call, so the index-status endpoint reflects the true state
- **README** — updated features and API docs for new personal data detection and
  cache warm-up

### Fixed
- **Personal email false positives**: domain minimum 2→3 chars, skip if domain starts
  with a digit or has mixed-case in the middle (caught random encoded text like
  `b6b@bl.aI`, `WYC@np.PR`)
- **Passport false positives**: skip if digit portion starts with a leading zero
  (catches ID numbers like `A0100001`) or if preceded by `@`/`|` (catches tag values
  like `TM188688`)
- **BTC/ETH address false positives**: skip if preceded/followed by `/`, `.`, or `\`
  (catches file path segments like `3DgxuLmE2A6nscDXTE9pfUjBuEC`)
- **Purge status timing**: index status now immediately shows `running: true` instead
  of waiting 30–60s through `clear_all_data()`
- **Label clean-up**: `Email:pw` → `Email:password` in header stats, `active pattern
  categories` → `different categories` on dashboard

---

## [1.2.1] — 2026-11-11

### Fixed
- Purge status polling race — index-status now shows `running: true` immediately when
  purge starts, preventing the frontend from making data API calls on a partially
  cleared database

---

## [1.2.0] — 2026-11-11

### Added
- Personal data detection patterns: `personal_email`, `ssn`, `btc_address`,
  `eth_address`, `passport`, `name_dob`
- `PATTERN_CATEGORIES` mapping in detector for Technical / Personal classification
- Dashboard split into Technical Detections and Personal Detections columns with
  stat cards
- Post-hoc filters for personal data (SSN: reject test numbers; Passport: skip
  short/code matches)
- `personal_email` skipped if already caught by `email:password`
- Header labels: "Total pastes", "Affected", "Email:password", "Sources"

### Changed
- `_HAS_TRIGGER` pre-filter updated for new patterns
- Version bump: 1.1.8 → 1.2.0 (feature release)

---

## [1.1.8] — 2026-11-10

### Fixed
- False positive rate reduced across multiple detection patterns

---

## [1.1.6] — 2026-11-10

### Fixed
- Multiple small fixes (stability, UI edge cases)

---

## [1.1.5] — 2026-11-10

### Fixed
- Line number mismatch in paste detail view

---

## [1.1.4] — 2026-11-09

### Added
- Reindex toast notification — user sees a summary of what was indexed/deleted/skipped
  after a reindex completes

---

## [1.1.3] — 2026-11-09

### Changed
- Code cleanup (dead code removal, consistency pass)

---

## [1.1.2] — 2026-11-08

### Fixed
- Bug fixes and refactor across backend and frontend

---

## [1.1.1] — 2026-11-08

### Fixed
- Stats syncing bug where cached stats would return stale counts after reindex

---

## [1.1.0] — 2026-11-08

### Added
- **Purge mode** — `?mode=purge` for reindex API: clears the entire database, then
  performs a full reindex from scratch
- README updated with purge API docs

---

## [1.0.0] — 2026-11-08

### Added
- **Dashboard** — overview tab showing detection rates, source/type distributions,
  and per-type breakdowns
- First major release with dashboard, filtering, and full-text search

---

## [0.11.2] — 2026-11-08

### Fixed
- Secret type filter using `LIKE` matching (comma-separated string column)
- False positive fixes across multiple patterns

---

## [0.11.0] — 2026-11-07

### Changed
- Reduced false positive rate for credit card, private key, and auth header
  detection

---

## [0.10.2] — 2026-11-07

### Fixed
- Filename collision in indexer when multiple sources have identically named files

---

## [0.10.1] — 2026-11-07

### Fixed
- Secret type chip dot colors in filter bar

---

## [0.10.0] — 2026-11-07

### Changed
- Major indexing rework: thread-pooled I/O, single-threaded DB writes,
  `INDEX_WORKERS` env var, `ThreadPoolExecutor` for parallel file processing

---

## [0.9.0] — 2026-11-07

### Added
- Semantic versioning via `VERSION` file and `/api/version` endpoint
- This is the first versioned release; earlier development was unversioned