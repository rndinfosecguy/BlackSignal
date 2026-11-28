# BlackSignal API

Current version: **1.19.0**

The API is same-origin only - there is no CORS support. Browsers must reach it through the same host/port as the SPA (or a reverse proxy); `curl` and other non-browser clients are unaffected.

All endpoints require authentication with the session cookie set by `/api/auth/login` or HTTP Basic credentials, except `/api/auth/*` and `/api/healthz`.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/openapi.json` | Raw OpenAPI schema (machine-readable) |
| GET | `/api/docs` | Swagger UI - interactive API explorer |
| GET | `/api/redoc` | ReDoc - clean scrollable API docs |
| GET | `/api/pastes` | Paginated/searchable list. Params: `q`, `source` (repeatable), `content_type` (repeatable), `has_secrets`, `secret_type` (repeatable, OR), `triage_status` (repeatable, OR), `stale=true` (changed since triage), `sort=priority` (default newest), `page`, `per_page`, `group_by` (source or content_type), `date_from` (YYYY-MM-DD), `date_to` (YYYY-MM-DD) |
| GET | `/api/pastes/export` | Export search results as CSV or JSON. Params: same as `/api/pastes` (except `page`, `per_page`, `sort`) + `format=csv\|json` (default csv) + `include_content=true\|false` (default false) + `date_from`, `date_to`. Includes triage columns and honours the triage/stale filters |
| GET | `/api/pastes/{id}` | Full paste content + detected secrets + triage state, `duplicate_count`, and auto-triage provenance |
| PATCH | `/api/pastes/{id}/triage` | Update triage for one paste. Body: `{ "status"?: "new"\|"reviewed"\|"false_positive"\|"escalated", "note"?: "..." }`. Reviewer is taken from the session. Returns `{ triage_status, triage_note, triage_reviewer, triage_updated_at, triage_auto, triage_source }` |
| POST | `/api/pastes/{id}/triage/identical` | Apply one decision to every paste with the same content hash. Body: `{ "status": "...", "note"?: "..." }`. Returns `{ updated: N }` |
| GET | `/api/stats` | Filter-aware counts (pastes/secrets/passwords/sources) plus triage counts (`unreviewed`, `reviewed`, `false_positive`, `escalated`, with `*_all` totals). Params: same filter params as `/api/pastes` (no pagination), including `stale` |
| GET | `/api/sources` | Source distribution. Optional: `?content_type=` |
| GET | `/api/types` | Content-type distribution. Optional: `?source=` |
| GET | `/api/secret-types` | Detected secret categories with counts. Optional: `?source=`, `?content_type=` |
| GET | `/api/index-status` | Indexer progress: `{ running, current, total, phase }` |
| GET | `/api/indexer-info` | Scheduler info: `{ interval_seconds, next_run, running }`. The interval is persisted in `data/settings.json` and survives restarts. |
| POST | `/api/indexer-info` | Update auto-index interval. Body: `{ "interval_seconds": N }` (minimum 3600) |
| POST | `/api/reindex` | Trigger a manual re-index. Accepts `?mode=standard` (default), `?mode=comprehensive` (no size limit), or `?mode=purge` (clear DB + full reindex) |
| GET | `/api/db-stats` | Database stats: `{ db_size_bytes, paste_count, raw_pastes_size_bytes, raw_files_total, indexable_files_count }` - `indexable_files_count` mirrors the indexer walk; `raw_files_total` is recursive |
| GET | `/api/version` | App version: `{ version: "1.19.0" }` |
| GET | `/api/last-reindex` | Last reindex result: `{ indexed, deleted, skipped, total, finished_at, duration_seconds, last_attempt_at, last_error? }` or `{}` if none. Counts are from the last **successful** run; failure details are included without discarding them. |
| POST | `/api/auth/login` | Sign in. Body: `{ "username": "...", "password": "..." }` - sets the session cookie |
| GET | `/api/auth/session` | Session state: `{ authenticated: bool, username }` |
| POST | `/api/auth/logout` | Clear the session cookie |
| GET | `/api/healthz` | Liveness probe (public): `{ status: "ok" }` |
| GET | `/api/llm/config` | Whether LLM features are enabled: `{ configured: true\|false }` |
| GET | `/api/llm/key` | Masked key preview: `{ key_preview: "sk-or-v1-...abcd" }` (empty if unset) |
| POST | `/api/llm/key` | Set the OpenRouter key. Body: `{ "key": "sk-or-v1-..." }` |
| DELETE | `/api/llm/key` | Remove the stored OpenRouter key |
| POST | `/api/llm/summarize/{id}` | Analyze one paste. Returns `{ summary: "<rendered markdown>", analysis: {...}\|null, structured: bool, report_id }` |
| POST | `/api/llm/report` | Start a batch report for the filtered pastes. Same filter params as `/api/pastes/export` |
| GET | `/api/llm/report-status` | Report progress: `{ running, current, total, phase, final_report, error }` |
| POST | `/api/llm/report-cancel` | Cancel an in-progress report |
| GET | `/api/llm/report-download` | Backward-compatible alias: newest archived batch report as a ZIP |
| GET | `/api/reports` | List archived LLM reports: `{ reports: [{ id, type, created_at, title, paste_count?, risk_level?, risk_score? }] }` |
| DELETE | `/api/reports` | Purge every archived report: `{ deleted: N }` |
| GET | `/api/reports/{id}` | One report: `{ meta, markdown, analysis }` (`analysis` is the structured result, or `null`) |
| GET | `/api/reports/{id}/download` | Download one report - single → `.md`, batch → `.zip` |
| DELETE | `/api/reports/{id}` | Delete an archived report |

Example - export CSV with source and date range:

```bash
curl -u admin:PASSWORD \
  "http://localhost:9090/api/pastes/export?format=csv&source=pastebin&source=github&date_from=2026-11-01&date_to=2026-11-21"
```
