# Changelog

All notable changes to BlackSignal are documented here.

Dates are based on commit timestamps (UTC+1).

---

## [1.18.0] — 2026-11-28

### Added
- **Identical-paste detection.** Pastes with the same content are grouped via a
  SHA-256 hash. Cards show how many copies exist, and the detail view can apply a
  decision to every identical paste at once.
- **Auto-copy to identical pastes.** When a new copy of an already triaged paste is
  indexed, the decision (status, note, reviewer) is applied automatically. The detail
  view marks it as auto-applied and names the source paste; changing it manually clears
  the marker.
- **Priority queue.** Each paste gets a deterministic 0-100 priority from its detected
  categories (private keys highest, then credentials/API tokens, then PII). The Pastes
  toolbar has a **Priority / Newest** sort, and **Needs triage** selects all `new` pastes,
  sorted by priority (secret-bearing pastes float to the top).
- **Changed since triage filter.** Surfaces pastes that were re-indexed with different
  content after they were reviewed.
- **Review progress** bar on the dashboard triage block.
- **API:** `POST /api/pastes/{id}/triage/identical` applies a decision to all identical
  pastes. `/api/pastes`, `/api/stats`, `/api/pastes/export` and `/api/llm/report` accept
  `stale=true`; `/api/pastes` also accepts `sort=priority`. List/detail responses include
  `duplicate_count`, `triage_auto` and `triage_source`.

### Changed
- Derived hash/priority/stale data lives in a small `paste_meta` side table. It is
  backfilled in the background in batches for databases indexed before this release,
  so existing rows are not rewritten and startup is not blocked.
- Stale detection compares content hashes at index time instead of parsing date strings
  in SQL.
- The post-index cache warm-up now runs the real stats/list/queue accessors (including
  `paste_meta`) instead of hand-written SQL, and no longer performs a full FTS count,
  which cost hundreds of milliseconds per index run and did not warm search pages.
- The paste detail triage controls were redesigned: a segmented decision bar with icons,
  an auto-growing note composer, dirty-state Save/Reset buttons, a status badge in the
  modal header, and a save confirmation that offers "just this paste" or "all identical
  copies" (only shown when the paste has duplicates).

---

## [1.17.0] — 2026-11-28

### Added
- **Triage workflow.** Every paste now carries a review state: `new`, `reviewed`,
  `false_positive`, or `escalated`, plus an optional note, the reviewer, and a timestamp.
  - Paste cards show a colored status badge and a note indicator.
  - The paste detail modal has a **Triage** panel with status buttons, a note field,
    and Save/Reset. It also warns when the paste was modified after it was last triaged.
  - The `+ Add filter` overlay has a **Triage** category, and the Pastes toolbar has a
    one-click **Needs triage** shortcut.
  - The Dashboard shows per-status counts that link straight into the filtered list.
- **API:** `PATCH /api/pastes/{id}/triage` (body `{ status?, note? }`; reviewer comes from
  the session, note capped at 2000 chars). `triage_status` is a repeatable filter on
  `/api/pastes`, `/api/pastes/export`, `/api/stats`, and `/api/llm/report`. Stats return
  `unreviewed`, `reviewed`, `false_positive`, `escalated` counts (plus `*_all`).
  CSV/JSON exports include the triage columns.

### Changed
- **Triage survives re-indexing.** `upsert_paste()` updates content and detections only;
  the triage columns are preserved exactly like `first_seen`. A `purge` reindex still
  clears everything.
- Schema migration adds the triage columns and two indexes in place, using the existing
  `ALTER TABLE ... ADD COLUMN` pattern, so large databases migrate without a rebuild.
- The Dashboard triage block reports overall counts (all pastes) so an active
  `Needs triage` filter does not blank out the progress numbers.
- **Secret-type counts are precomputed** in a small `secret_type_counts` table, maintained
  on upsert/delete and rebuilt once for existing databases. `/api/secret-types` no longer
  has to walk every paste row on a cold cache.
- **Faster stats.** `/api/stats` and the distribution lists now read covering indexes
  instead of scanning the whole `pastes` table (content included). On a large database a
  cold stats request drops from seconds to milliseconds. Existing databases rebuild
  `idx_pastes_stats`, `idx_pastes_source` and `idx_pastes_content_type` once on first
  start (a few seconds on a 600 MB database).
- **Much faster purge.** The destructive `DROP TABLE` step disables SQLite's
  `secure_delete` pragma, which otherwise zeroes every freed page. On the 614 MB dev
  database the drop went from ~37 s to ~4 s; the pragma is restored before reindexing.

### Fixed
- **Triage changes invalidate the stats cache immediately.** Marking a paste no longer
  needs an index run before `/api/stats` and the Dashboard counters reflect it. Only the
  stats cache is dropped; the more expensive distribution caches are left intact.
- Switching to the Dashboard tab, or a background refresh after an index run, no longer
  resets the top counters to global totals. The last applied filters (including triage)
  are kept.

---

## [1.16.3] — 2026-11-27

### Fixed
- **The search bar no longer loses the active term when switching tabs.** The input is
  initialised from the parent's filter state and re-syncs when that state changes, while
  ignoring debounced echoes so in-progress typing isn't overwritten. Previously the filter
  stayed active after returning to the Pastes tab, but the input rendered empty.

---

## [1.16.2] — 2026-11-27

### Changed
- **Risk rating is derived from the identified findings**, not proposed by the model. The
  model now returns only the summary and findings (plus highlights for batch reports);
  the score is computed in code:
  - base by effective severity: Low 18, Medium 40, High 62, Critical 82
  - `combination` findings +8, `contextual` +6
  - +4 per additional high/critical category (max +8)
  - batch: +4 when entities are reused across pastes, +2 per additional (max +8)
  - clamped to 0-100; no findings -> 0 / Low
- **Severity floors** stop critical data being under-rated: passwords, private keys, API
  keys, SSN, passport, card and bank-account entities — and any `combination` finding in
  the credential/PII/financial categories — are at least High regardless of the model's
  label.
- The rating rationale is deterministic and names the finding driving the score; the model
  still writes the executive summary, highlights and per-finding reasoning.
- Any `risk` object returned by the model is ignored.

---

## [1.16.1] — 2026-11-27

### Added
- **Risk rating in the Report Archive.** Each entry shows a colour-coded badge — Critical
  (red), High (orange), Medium (yellow), Low (green) — including the numeric score.
  Reports without a rating (unstructured/legacy) show a grey **No rating** badge.
- Report metadata now stores `risk_level` and `risk_score`, exposed via `/api/reports`.

### Changed
- **Documented 0-100 risk scale:** 0-24 Low, 25-49 Medium, 50-74 High, 75-100 Critical.
  The level is derived from the score (so label and number always agree), the scale is
  printed in the report, and the prompt includes a scoring rubric.
- A missing/invalid score is derived from the model's level instead of silently becoming 0;
  the batch narrative fallback uses 45 (Medium).

---

## [1.16.0] — 2026-11-27

### Added
- **Structured LLM analyses.** The model is asked for a JSON object (summary, risk,
  findings with kind/category/severity/confidence/evidence/entities/relationship).
  Output is validated and normalised, with one repair retry; reports are rendered
  deterministically from that data, so sections and layout no longer vary between runs.
- **Relationship-aware analysis.** Both prompts now look for values that are only
  sensitive in combination or context (credential bundles, PII composites, infrastructure
  maps, business context). Findings carry `kind: standalone|combination|contextual`, the
  involved entities, evidence lines and a relationship description. Personal data is
  explicitly first-class: full names, dates of birth, addresses, phone numbers, government
  IDs and financial data are captured and grouped per person when they describe the same
  individual.
- **Deterministic structural hints.** Before the call, ENV/INI/YAML/JSON/CSV-style
  key/value groups, PEM blocks, JWTs and URLs with embedded credentials are summarised
  with line numbers and supplied to the model to improve relationship detection.
- **Evidence line correction.** When the model cites a nearby line, evidence is re-anchored
  to the actual line containing the excerpt, so reported line numbers are reliable.
- **Batch correlation.** Per-paste structured findings are deduplicated and entities seen
  in multiple pastes are correlated in Python — including full names and addresses, which
  use strict normalised exact-match rules (multi-word names, full addresses) to avoid
  noisy matches. The final report has a **Correlated
  Findings** section and a fixed template. The narrative is the only part written by the
  model.
- Reports store `analysis.json` next to `report.md`; batch ZIP bundles include it too.

### Changed
- `POST /api/llm/summarize/{id}` returns `{ summary, analysis, structured, report_id }`.
- `GET /api/reports/{id}` includes the stored `analysis`.
- Batch reports render a separate **BlackSignal Detections** section for the regex
  scanner's results, distinct from the LLM's structured findings.
- If the model returns invalid JSON twice, the raw text is stored as an *unstructured*
  analysis instead of failing the run.

---

## [1.15.3] — 2026-11-27

### Added
- **Config tab explains the file-count discrepancy.** "Files scanned (last run)" now
  shows how long ago that run finished, "Indexable files" shows the live delta since
  the last run (e.g. `+4,069 since last run`), and a failed index run is surfaced in
  red instead of silently leaving stale numbers in place.
- `/api/last-reindex` now also returns `finished_at`, `duration_seconds`,
  `last_attempt_at`, and `last_error` / `last_error_at` when a run fails.

### Changed
- A failed index run records its error while preserving the last successful run's
  counts, so the UI can distinguish "indexer is behind" from "indexer is broken".

### Fixed
- **Background no longer scrolls behind overlays.** The search loading overlay, paste
  detail, LLM report, report viewer and reindex confirmation now use a reference-counted
  scroll lock (stacked overlays restore scroll only when the last one closes).
- **Loading overlay covers the full viewport on wide screens.** The lock now applies to
  `<html>` as well as `<body>` (a horizontal scrollbar otherwise left an uncovered strip)
  and compensates for the vertical scrollbar so the page doesn't shift.
- **Paste cards no longer cause horizontal overflow** — long filenames truncate and
  unbroken snippets wrap, removing the stray horizontal scrollbar.
- **Disabled LLM buttons** now say to add the key in the **Config tab** instead of
  referencing the removed `data/openrouter.json`.
- **First-boot credentials show the correct URL** (`http://localhost:9090` instead of a
  port-less `http://localhost`), configurable via `PUBLIC_URL`.

---

## [1.15.2] — 2026-11-26

### Changed
- **Single settings store.** `data/settings.json` now holds both the auto-index
  interval and the OpenRouter API key; `data/openrouter.json` is no longer used.
  The file is written atomically with mode `0600` (it may contain a secret) and
  read-modify-write updates are serialised so interval/key saves can't clobber
  each other.
- **Automatic migration:** on startup, a legacy `data/openrouter.json` key is
  imported into settings and the old file is renamed to `openrouter.json.migrated`.
  Existing configs need no manual action.
- The key is no longer read through its own path-discovery logic; settings use the
  shared data-directory resolver.

### Fixed
- `openrouter.json` was previously written world-readable (`0644`); the merged
  store is always `0600`.

---

## [1.15.1] — 2026-11-26

### Security
- **CORS removed.** The API reflected any origin with credentials enabled, letting any
  website read paste data using the visitor's session. The app is same-origin only now.
- **CSV export formula injection fixed.** Cells starting with `=`, `+`, `-`, `@`, tab or CR
  are prefixed with `'` so spreadsheet apps don't execute paste content as formulas.
- **Malformed FTS5 queries return 400** instead of a 500 (`q=test"`, `q=(unclosed`).
- **SPA fallback path traversal hardened** — resolved paths must stay inside the static root.
- **Container hardening:** `no-new-privileges` in compose (the container still runs as
  root by design; non-root is deferred to a future release).

### Fixed
- **Auto-index interval is persisted** to `data/settings.json`, so a user-set interval
  survives restarts instead of silently reverting to the `REINDEX_INTERVAL` env default.
- **LLM report start is atomic** — two rapid requests can no longer start two concurrent
  (paid) runs; the second gets `409`.
- **Exports stream** instead of materializing every matching row in memory, making
  `include_content=true` safe on large databases.

### Added
- `GET /api/healthz` (public) and a Docker `HEALTHCHECK`.
- `frontend/package-lock.json`; the image now builds with `npm ci` for reproducible,
  auditable frontend dependencies.
- Startup logs a warning when `AUTH_DISABLED` is set, so an unauthenticated deployment
  is noticeable in the logs.

---

## [1.15.0] — 2026-11-25

### Added
- **In-app login screen and session authentication.** The browser Basic-Auth popup is
  gone: users sign in on a styled page in the app theme, and the session is kept in a
  signed, `HttpOnly`, `SameSite=Lax` cookie that survives refreshes and restarts until it
  expires (default 7 days, `AUTH_SESSION_DAYS`).
- **App-level auth enforcement.** Every `/api/` route now requires a valid session cookie
  or HTTP Basic credentials, regardless of the reverse proxy. `curl -u user:pass` keeps
  working for API clients (validated by the backend).
- **New endpoints:** `POST /api/auth/login`, `GET /api/auth/session`, `POST /api/auth/logout`.
- **Sign out** action in the footer.
- **Login throttling** — repeated failed attempts per client IP are temporarily locked out.
- **Expired or invalidated sessions** automatically return the UI to the login screen.
- **New environment variables:** `AUTH_SESSION_DAYS`, `AUTH_COOKIE_SECURE` (set behind TLS),
  and `AUTH_DISABLED` (tests/dev only).
- **CSRF guard for mutating API calls.** `POST`/`PUT`/`PATCH`/`DELETE` requests to `/api/*`
  that carry an `Origin` header must match the request host (hostname; ports compared when
  both are present, tolerated when a proxy strips them). Non-browser clients without an
  `Origin` header, such as `curl`, are unaffected.

### Changed
- Credentials remain generated on first boot into `data/.credentials`; the backend derives
  a PBKDF2 hash into `data/.auth.json` and a signing secret into `data/.auth_secret`
  (both mode `600`).
- nginx no longer challenges or serves `.htpasswd`; Basic-Auth termination moved to the app.
- `.credentials` is now written with mode `600`; existing files are tightened to `600`
  on startup.

### Removed
- **`.htpasswd` generation and `apache2-utils`** — no longer needed now that auth is
  validated by the backend against the PBKDF2 hash.
- nginx `auth_basic` configuration.

---

## [1.14.0] — 2026-11-25

### Added
- **Report Archive tab** — LLM reports are now persisted to `data/reports/` and survive
  restarts. A new tab between *Pastes* and *Config* lists every archived report with
  type (Single / Batch), title, timestamp and paste count, and offers **View** (rendered
  markdown), **Download** (single → `.md`, batch → `.zip` with `report.md`,
  `pastes.json` and `pastes/*.md`)
  and **Delete** (with confirmation).
- **Automatic persistence** — each "Analyze with LLM" run saves a single-paste report;
  each completed batch report is saved with its per-paste analyses plus `pastes.json`,
  a structured list of the pastes included (source, ID, filename, content type, size,
  detection flags). Storage failures are logged and never fail the analysis itself.
- **New API endpoints** — `GET /api/reports`, `GET /api/reports/{id}`,
  `GET /api/reports/{id}/download`, `DELETE /api/reports/{id}`.
  `GET /api/llm/report-download` is kept as a backward-compatible alias for the newest
  archived batch report.
- **Retention** — the archive keeps the newest `REPORT_ARCHIVE_MAX` reports (default 100)
  and prunes older ones on save.

---

## [1.13.3] — 2026-11-25

### Changed
- **Clearer Config-tab file counts.** The Database section now separates two scopes that
  previously looked interchangeable: **Indexable files** (regular files directly inside
  each source folder — exactly what the indexer scans) and **Files on disk (recursive)**
  (everything under `raw_pastes/`, including nested folders and files outside source
  folders, which the indexer ignores). When the recursive count is higher, a hint shows
  how many files won't be indexed. The Indexing section's count is relabelled
  **Files scanned (last run)** to make clear it is a historical snapshot, not a live count.
- `GET /api/db-stats` now returns `indexable_files_count` and `raw_files_total`
  (replacing `raw_pastes_count`). `indexable_files_count` is computed via the indexer's
  own `walk_pastes()`, so the two can no longer drift apart by definition.

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