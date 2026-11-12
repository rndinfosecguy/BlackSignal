# Changelog

All notable changes to BlackSignal are documented here.

Dates are based on commit timestamps (UTC+1).

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