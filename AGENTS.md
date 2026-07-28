# Jules / AI Agent Guidelines: Wiki-to-RAG Sync Engine

Welcome to the Wiki-to-RAG Sync Engine repository. This document defines the exact environment, architectural constraints, and coding standards you must follow when contributing to this project.

Always consult the `wiki_rag_sync_spec.md` for feature requirements.

## 1. Project Architecture & Environment

* **Backend:** Python 3.11+, FastAPI, SQLite3.

* **Frontend:** Vanilla JavaScript, HTML5, Tailwind CSS (via CDN is acceptable for simplicity).

* **Environment:** Dockerized.

* **Key OS Package:** `pandoc` MUST be installed via the `Dockerfile` (`apt-get install pandoc`).

## 2. Setup & Execution Commands

When testing or verifying your code, use the following commands:

* **Install dependencies:** `pip install -r requirements.txt`

* **Run backend locally:** `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

* **Build Docker image:** `docker build -t wiki-rag-sync .`

* **Run Docker container:** `docker run -p 8000:8000 -v ./data:/app/data wiki-rag-sync`

## 3. Coding Conventions

### Python / Backend

* **Type Hinting:** Use strict Python type hints for all function signatures and Pydantic models.

* **Async I/O:** FastAPI endpoints must use `async def`.

* **Database:** Use standard `sqlite3` or `aiosqlite`. Keep queries simple and modular. Store the database file in the `/app/data/` volume so it persists across container restarts.

* **Rate Limiting:** Whenever iterating over API calls using `mwclient`, you MUST include a `time.sleep(1)` or `await asyncio.sleep(1)` to prevent rate-limiting and IP bans from target wikis.

### File System Operations

* **Paths:** Never hardcode paths. Use `os.path.join` or `pathlib.Path`.

* **Volumes:** Assume `/app/data/` is the root for all persistent storage.

  * `/app/data/raw/` -> For 1:1 individual Markdown page saves.

  * `/app/data/compiled/` -> For the word-capped RAG bundle files.

### Frontend

* Keep it simple. Do not use React, Vue, or build tools like Webpack.

* Serve static files (HTML/JS) directly from a `/static/` folder via FastAPI.

* Use `fetch()` for API calls to the backend.

## 4. Security & Permissions

### Allowed Actions

* You may read, write, and refactor Python and HTML files.

* You may update `requirements.txt` and the `Dockerfile`.

* You may add logging using the standard Python `logging` module to track sync progress.

### Forbidden Actions (Do NOT do these)

* **NO Web Scraping:** Do not use BeautifulSoup, Scrapy, or Selenium. Only extract text using the MediaWiki APIs (`mwclient` or `wikiteam3`).

* **NO Complex ORMs:** Do not use SQLAlchemy or Alembic unless explicitly requested. A simple SQLite schema is preferred.

* **NO Hardcoded Secrets:** If environment variables are needed, load them via `os.environ` or `python-dotenv`.

## 5. Changelog Protocol

If your task is complete and tests pass, update `CHANGELOG.md` with:

* The feature/fix implemented.

* The specific files modified.

* Any new Python dependencies added.
