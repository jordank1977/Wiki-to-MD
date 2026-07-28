# Changelog

## [2.0.0] - 2026-07-28

### Added
- **Standard Docker Compose Integration**: Created a standard, production-ready `docker-compose.yml` file in the root of the repository, enabling building from local `Dockerfile`, mapping port `8000:8000`, persisting the SQLite database, logs, and compiled assets via local host volume mapping `./data:/app/data`, and configuring the restart policy to `unless-stopped`.
- **Environment Variables Example File**: Created a clean `.env.example` file establishing best practices for user-configurable environment settings (e.g., `WATCHER_POLL_INTERVAL`), completely free of any PII.
- **Comprehensive Production Documentation**: Overhauled and rewrote `README.md` to provide a professional, user-facing overview of the sync engine, explaining the Two-Stage raw/compiled pipeline architecture, key ingestion and updater workflows, and copy-pasteable Docker deployment instructions.

## [1.9.0] - 2026-07-24

### Added
- **Append Last Sync Date to Compiled Bundle Filenames**: Updated compiler logic in `app/compiler.py` to fetch each wiki's `last_sync_timestamp` from the database and inject its sanitized date portion (`YYYY-MM-DD`) into generated Mega-Document filenames (e.g., `[WikiName]_[YYYY-MM-DD]_Bundle_[Index].md`).
- **Date-Injected Export Archive Filenames**: Updated the `/api/wikis/{wiki_id}/download` endpoint in `app/main.py` to name the generated zip file after the formatted sync date, following the pattern `[WikiName]_Export_[YYYY-MM-DD].zip`.
- **Robust Unit Testing**: Updated existing unit tests in `tests/test_compiler.py` and `tests/test_api.py` to fully verify the new date formatting and graceful fallback logic under mocked timestamp scenarios.

### Fixed
- **Compiled .md bundle filename date fallback**: Fixed a bug where `.md` filenames defaulted to `"Never_Synced"` instead of the current system date during initial ingestion/sync because the compiler executes before the database's `last_sync_timestamp` is updated. Both `.md` and `.zip` filename generation now use identical, consistent date fallback logic to use the current system date.

### Modified Files
- `app/compiler.py`
- `app/main.py`
- `tests/test_compiler.py`
- `tests/test_api.py`

## [1.8.0] - 2026-07-24

### Fixed
- **Unhandled CancelledError exception on sync cancellation**: Caught `asyncio.CancelledError` on the backend (`api_stop_wiki` endpoint in `app/main.py`) when awaiting a stopped background task, ensuring a graceful response without throwing unhandled exceptions, stack traces, or 500 Server Errors.
- **Sleek, graceful cancellation logging**: Updated `sync_wiki_pipeline` in `app/sync.py` to log a graceful `Sync aborted by user` INFO message upon cancellation, setting the status cleanly to `Idle` in the database.
- **Frontend UI Error Prevention**: Enhanced `stopSync` fetch logic in `app/static/app.js` with safe JSON parsing and fallback error boundaries, ensuring that abort actions never trigger generic "Unknown Error" alerts.
- **Regression tests**: Added a robust mocked unit test `test_stop_sync_cancelled_error` in `tests/test_api.py` to verify graceful cancellation behavior.

### Modified Files
- `app/main.py`
- `app/sync.py`
- `app/static/app.js`
- `tests/test_api.py`

## [1.7.0] - 2026-07-24

### Added
- **Auto-Populate Wiki Name from URL:** Swapped positions of "MediaWiki Base URL" input and "Wiki Name" input in the registration form (URL is now on the left, Name is on the right).
- **Backend endpoint (`POST /api/wikis/fetch-info`):** Created a new FastAPI endpoint that accepts a URL, connects using `mwclient`, and fetches the wiki's `sitename`.
- **Frontend integration:** Added dynamic event listener (`blur` and `paste` events) to the URL field in `app/static/app.js` to call the new backend endpoint and auto-populate the Pipeline Name input field unless manually edited. Added unit tests in `tests/test_api.py`.

### Modified Files
- `app/main.py`
- `app/static/index.html`
- `app/static/app.js`
- `tests/test_api.py`

## [1.6.0] - 2026-07-24

### Changed
- **Removed EVE Jargon:** Reverted sci-fi and EVE roleplay terminology across the interface and code logic to standard functional equivalents (e.g., "Uplink" -> "Sync", "Telemetry" -> "Metrics" / "Logs", "Sys Station Cmd" -> "Settings", "Signatures" -> "Pipelines", "Purge" -> "Delete", "ABORT" -> "STOP", "ESTABLISH UPLINK" -> "ADD WIKI").
- **Removed NEOCOM Branding:** Completely removed the NEOCOM text, navigation comments, and icons from the top header and navigation area.
- **Enhanced Global Font Scale:** Bounded the overall application typography by increasing the root `html` font size to `18px !important`. Refactored all hardcoded pixel-based text classes (e.g. `text-[11px]`) to standard responsive Tailwind `text-xs` to allow cohesive scaling across all headers, inputs, labels, and terminal log viewports.

### Modified Files
- `app/static/index.html`
- `app/static/app.js`

## [1.5.0] - 2026-07-24

### Changed
- **Muted Monochrome "Slate" Theme:** Migrated the color palette from bright neon cyan to a cohesive, professional slate and zinc gray theme.
- **Removed Neon Glows:** Replaced glowing gradients and box shadows with sleek, industrial borders and backgrounds.
- **Sleek Progress Indicator:** Adjusted the progress bar to render as a muted neutral industrial meter using slate-400 and slate/zinc grays.
- **Refined Alerts & Elements:** Stripped all `text-cyan-*` and `border-cyan-*` utility classes, transitioning components like status badges, pingers, loader animations, scrollbars, text layers, and dynamic alerts to slate/zinc.

### Modified Files
- `app/static/index.html`
- `app/static/app.js`

## [1.4.0] - 2026-07-24

### Changed
- **Increased Global Typography Scale:** Scaled up font sizes across the entire application interface to maximize readability. Bounded base font sizes by shifting typical `text-xs` utility classes to `text-sm`, and `text-sm` classes to `text-base` where appropriate.
- **Enhanced Terminal Logs:** Bumped font size of terminal logs inside both the Global application console and specific Wiki Telemetry modals from `text-[11px]` to `text-sm`.
- **Proportional Headers and Labels:** Adjusted panel headers and input labels proportionally to maintain a crisp, clean visual hierarchy.

### Modified Files
- `app/static/index.html`
- `app/static/app.js`


## [1.3.0] - 2026-07-23

### Added
- **Global Watcher Countdown:** Exposed `GET /api/status` endpoint in the backend returning the exact time the background watcher will run next, and built a live ticking countdown badge near the "Refresh List" button on the UI (e.g. "Next check in: 14m 30s") updating every second.
- **Unit and Integration Tests:** Added unit tests verifying the `/api/status` endpoint response formats for both initialized and non-initialized watcher states.

### Modified Files
- `app/main.py`
- `app/static/index.html`
- `app/static/app.js`
- `tests/test_api.py`


## [1.2.0] - 2026-07-22

### Added
- **Real-Time Subprocess Log Streaming:** Added streaming and real-time logging of the external `wikiteam3dumpgenerator` subprocess standard output and error output, so progress and status of background bootsrapping are fully visible to the user.
- **Copy to Clipboard Buttons:** Implemented "Copy" buttons in the Global application logs console header and inside the Wiki Logs Modal footer.
- **Visual Feedback for Copying:** Added temporary visual indicator (`Copied!`) to copy buttons to indicate successful copying, utilizing robust modern Clipboard API with fallback mechanism to support non-HTTPS and insecure local contexts.
- **Page Download Progress Logging:** Upgraded downloading logs to trace exactly when each wiki page is downloaded/saved during craws, XML parsing, and incremental edits/moves.

### Modified
- **Suppressed Verbose Logging:** Set logger levels for `mwclient`, `urllib3`, `httpx`, and `httpcore` to `WARNING` to keep verbose third-party log entries out of user logs.

### Modified Files
- `app/logging_config.py`
- `app/sync.py`
- `app/static/index.html`
- `app/static/app.js`
- `tests/test_api.py`


## [1.1.0] - 2026-07-22

### Added
- **Wiki-Specific Logs Modal:** Enabled live sync/compile logging by piping execution logs to `/app/data/logs/{wiki_id}.log` using a thread-safe `ContextVar` inside a custom `WikiLogHandler`. Designed an interactive Tailwind CSS terminal modal on the frontend to display and poll these logs in real-time.
- **Downloadable Bundles:** Implemented an in-memory ZIP archive streaming endpoint (`/api/wikis/{wiki_id}/download`) that bundles all compiled markdown page documents for simple local ingestion. Integrated dynamic "Download" action buttons onto each pipeline row in the dashboard.
- **Global Console Logs Section:** Added a terminal-like streaming console box at the bottom of the main dashboard polling `/api/logs/global` every 2 seconds, displaying backend execution output with auto-scrolling, clear view, and viewport control features.
- **Unit and Integration Tests:** Developed robust test cases in `tests/test_api.py` validating correct ZIP generation, global logging retrieval, and wiki-specific logs rendering.

### Modified Files
- `app/main.py`
- `app/sync.py`
- `app/static/index.html`
- `app/static/app.js`
- `tests/test_api.py`

### Added Files
- `app/logging_config.py`


## [1.0.0] - 2026-07-22

### Added
- Created a robust pipeline for MediaWiki data sync and compilation.
- **Database Schema (`app/db.py`):** SQLite schema to track wikis, URLs, status, last sync timestamp, and total pages with async helper functions via `aiosqlite`.
- **Pandoc Converter Module (`app/converter.py`):** Handled conversions from Wikitext to GitHub Flavored Markdown (GFM) using async Pandoc execution and safe title filename sanitization.
- **Sync & Parser Pipeline (`app/sync.py`):** Enabled `wikiteam3dumpgenerator` bootstrapping, standard XML iterative parsing to extract Namespace 0 main articles, fallback `mwclient` crawling, and rate-limiting compliant incremental syncing tracking edits/deletions/moves.
- **Bundle Compiler (`app/compiler.py`):** Implemented deterministic compilation of Markdown pages into word-capped bundles (under 400,000 words limit per bundle) and cleans up old stale bundles on execution.
- **REST APIs (`app/main.py`):** Configured FastAPI endpoints for listing/creating/deleting wikis, triggering full/incremental background sync tasks, and rebuilding compiled bundles.
- **Dashboard Interface (`app/static/index.html` & `app/static/app.js`):** Built a gorgeous single-page client interface using Tailwind CSS and native JS with automatic status polling.
- **Testing suite (`tests/`):** Added a series of tests verifying converter sanitization, word counting, bundle compilation logic, and database/API routes.

### Dependencies
- Added `fastapi`, `uvicorn`, `aiosqlite`, `mwclient`, `wikiteam3`, `pydantic`, `python-slugify`, `pytest`, `pytest-asyncio`, and `httpx` to Python requirements.
