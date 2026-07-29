# Wiki-to-RAG Sync Engine

A production-ready, self-hosted web application that automatically syncs and compiles MediaWiki content into optimized, word-capped "Mega-Documents" designed for ingestion by Retrieval-Augmented Generation (RAG) platforms (such as Google NotebookLM).

## 📖 Overview & Motivation

Retrieval-Augmented Generation (RAG) tools like **NotebookLM** have revolutionized document analysis but impose strict platform-level constraints (e.g., a maximum of 50 uploaded sources and a 500,000-word limit per source). Attempting to sync a massive Wiki 1:1 (one file per page) quickly exceeds the source count limit, while uploading the entire wiki as a single massive document can easily exceed individual file limits.

The **Wiki-to-RAG Sync Engine** solves this dilemma. It sits between your MediaWiki target and your RAG pipelines, employing a smart **Two-Stage Pipeline** that guarantees fast, lightweight updates on the backend while automatically maintaining beautifully formatted, size-capped bundles optimized for RAG ingestion.

---

## 🏗️ Architecture: The Two-Stage Pipeline

To balance fast incremental syncing with RAG ingestion limits, the storage layer uses a two-stage approach mapped to a persistent local Docker volume (`/app/data/`):

### 📁 Stage 1: Raw Page Cache (`/app/data/raw/`)
* **What it does:** Stores individual `.md` files for every main namespace page of the wiki (e.g., `Tengu.md`).
* **Why:** Enables fast, efficient incremental syncs. When a page is added, updated, or deleted on the wiki, only the specific file is overwritten or removed. This avoids expensive re-parsing of the entire wiki.
* *Note: This folder is meant for internal backend tracking and is kept separate from your RAG imports.*

### 📁 Stage 2: Compiled Mega-Documents (`/app/data/compiled/`)
* **What it does:** Concatenates individual raw files into unified "Mega-Documents" (e.g., `[WikiName]_[YYYY-MM-DD]_Bundle_[Index].md`).
* **Why:** Combines thousands of pages into a handful of files, ensuring the source count stays well below RAG limits. The compiler monitors the word count as it merges pages, automatically rolling over to a new bundle index when a safe, customizable threshold (typically 400,000 words) is reached.
* *Note: This is the directory you sync to your RAG platform (e.g., via Google Drive or local sync tools).*

---

## ⚙️ Key Workflows

### ⚡ 1. Initial Ingestion (Bootstrapping)
For large wikis, traditional scraping page-by-page via standard API requests is extremely slow. The sync engine accelerates this via a dedicated bootstrapping routine:
1. It launches a standard XML dump generator (`wikiteam3dumpgenerator`) in a subprocess to quickly grab the entire database.
2. An interactive bypass automatically replies to resume prompts.
3. If the XML dump fails, it gracefully falls back to a multi-threaded `mwclient` crawling strategy.
4. A standard XML parser processes the dump, filtering **strictly for Namespace 0** (main articles only) to keep talk pages, files, categories, and user pages out of your RAG.
5. System-level `pandoc` converts the raw Wikitext to GitHub Flavored Markdown (GFM) and writes the output into `Stage 1` raw files.

### 🔄 2. Incremental Syncing (The Updater)
To pull in daily or weekly updates without re-downloading the entire wiki:
* The updater uses the `mwclient` API to query the wiki's recent edits since the `last_sync_timestamp` stored in SQLite.
* It identifies edited, newly created, deleted, or moved pages:
  * **Edits / Creates:** Re-downloads the page text, converts it via Pandoc, and updates the cache in `Stage 1`.
  * **Deletes:** Removes the cached page from `Stage 1`.
  * **Moves:** Renames or deletes the old cached file, translating the new title into a fresh converted `.md` file.
* Once completed, it logs the sync timestamp in the database and clears pending change notifications.

### 📦 3. The Compiler (Bundling)
The compilation task automatically runs after a successful sync or can be manually triggered via the web dashboard.
* It cleans up old compiled files.
* It sequentially reads the raw files, appending them to a combined Markdown document.
* It inserts header boundaries and counts words deterministically, automatically generating a new bundle once the threshold is crossed.

### 🕵️ 4. Background Watcher
A background asyncio worker runs periodically (configurable, e.g., every 30 minutes) to poll target wikis for fresh edits:
* If changes are detected, it updates the `has_pending_changes` flag in the SQLite database, alerting the UI.
* The frontend receives the exact timestamp of the next run to display a live countdown timer.

---

## 🐳 Quick Start with Docker Compose

Running the Wiki-to-RAG Sync Engine is straightforward using Docker Compose.

### Prerequisites
- Docker and Docker Compose installed on your system.

### Deployment Steps

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/example-username/wiki-to-rag-sync.git
   cd wiki-to-rag-sync
   ```

2. **Configure Environment Variables (Optional):**
   Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
   *Customize values (such as `WATCHER_POLL_INTERVAL`) in `.env` if desired.*

3. **Deploy the Service:**
   ```bash
   docker compose up -d --build
   ```

4. **Access the Dashboard:**
   Open your browser and navigate to:
   ```
   http://localhost:8000
   ```

---

## 💾 Volume Mapping & Data Persistence

The docker-compose setup mounts the host directory `./data` to `/app/data` inside the container. This folder keeps all critical persistent assets safe across container updates and restarts:

* `/app/data/database.db`: The SQLite database tracking configured wikis, sync timestamps, and state.
* `/app/data/raw/`: Individual raw Markdown page caches (Stage 1).
* `/app/data/compiled/`: Word-capped compiled bundles ready for RAG ingestion (Stage 2).
* `/app/data/logs/`: Streaming logs from active/past background sync and compilation tasks.

**To back up your data or grab compiled bundles directly from the host machine, simply access the `./data` directory relative to your Docker Compose file.**

---

## 🛡️ License

Distributed under the MIT License. See `LICENSE` for more details (if applicable).
