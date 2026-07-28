# **Product Specification: Wiki-to-RAG Sync Engine**

## **1\. Overview**

The Wiki-to-RAG Sync Engine is a Dockerized web application designed to maintain an up-to-date, RAG-compatible (e.g., NotebookLM) knowledge base extracted from MediaWiki sites.

Because tools like NotebookLM have strict limits on file counts (max 50 sources) and file sizes (max 500,000 words per source), standard 1:1 page-to-file syncing fails for large wikis. This app solves the problem by maintaining a 1:1 raw file structure on the backend for fast incremental updates, and automatically compiling them into word-capped "Mega-Documents" for the RAG to ingest.

## **2\. Tech Stack**

* **Deployment:** Docker (designed to run on Proxmox or standard Docker hosts).  
* **Backend:** Python (FastAPI).  
* **Database:** SQLite.  
* **Conversion Engine:** Pandoc (installed OS-level in the Dockerfile).  
* **API Client:** mwclient (for incremental updates), wikiteam3 (for initial bootstrapping).  
* **Frontend:** Vanilla JS, HTML, Tailwind CSS.

## **3\. Core Architecture: The Two-Stage Pipeline**

To balance the need for fast incremental syncing with the strict file-count limits of RAGs, the storage layer uses a two-stage approach mounted to a local Docker volume (/app/data/):

### **Stage 1: /data/raw/**

* Contains individual .md files for every page on the wiki (e.g., Tengu.md).  
* **Why:** When a wiki page is updated, the backend simply overwrites that specific file. When a page is deleted, the backend deletes the file. No massive text parsing is required.  
* *This folder is hidden from the RAG.*

### **Stage 2: /data/compiled/**

* Contains concatenated "Mega-Documents" (e.g., \[WikiName\]\_Bundle\_1.md).  
* **Why:** RAGs cannot ingest 4,500 individual files. The app concatenates the raw files into chunks that stay safely under a 400,000-word limit.  
* *This folder is synced via Google Drive/local sync to the RAG.*

## **4\. Key Workflows**

### **4.1 Initial Ingestion (Bootstrapping)**

For a massive wiki, scraping via standard API requests is too slow.

* The backend triggers a wikiteam3 subprocess (wikiteam3dumpgenerator \<url\> \--xml \--curonly \--force).  
* **CRITICAL:** The subprocess MUST bypass interactive prompts by passing standard input (e.g., input=b"y\\n" in Python's subprocess.run). If it fails, the error is suppressed and it gracefully falls back to mwclient.  
* A Python parser extracts the XML, filtering strictly for **Namespace 0** (Main articles only, ignoring Talk, User, File/Image, and Category pages to keep the RAG clean).  
* Pandoc converts the raw Wikitext to GitHub Flavored Markdown (GFM).  
* Files are saved individually to /data/raw/.

### **4.2 Incremental Syncing (The Updater)**

To pull in daily/weekly changes without re-downloading the wiki:

* The backend uses mwclient to query the MediaWiki API based on the last\_sync\_timestamp stored in SQLite.  
* **Namespace Filtering:** ALL mwclient queries (allpages, recentchanges, etc.) MUST be strictly limited to namespace=0 to prevent downloading images, files, and talk pages.  
* **Total Pages Tracking:** Before beginning a sync, use the site.siteinfo\['statistics'\]\['articles'\] property from mwclient to get the total number of articles on the wiki. Update the database or global state so the frontend knows the total page count.  
* **Query 1 (action=query\&list=recentchanges):** Identifies edited or newly created pages. The backend fetches the updated Wikitext, converts it via Pandoc, and adds/overwrites the .md file in /data/raw/.  
* **Query 2 (action=query\&list=logevents):** Tracks administrative actions.  
  * If letype="delete", the local .md file is deleted.  
  * If letype="move", the old .md file is deleted, and the new title is fetched and saved.  
* The last\_sync\_timestamp is updated in the database.  
* The has\_pending\_changes flag is reset to False.

### **4.3 The Compiler (Bundling)**

Triggered automatically after a sync, or manually via the UI.

* The compiler iterates through all .md files in /data/raw/.  
* It tracks the cumulative word count.  
* It combines files and outputs to /data/compiled/\[WikiName\]\_Bundle\_\[Index\].md.  
* When the word count reaches the safe threshold (400,000 words), it rolls over to a new bundle index.

### **4.4 Cancellation & State Management**

* The backend must maintain a global dictionary of active sync processes (e.g., active\_syncs\[wiki\_id\] \= asyncio.Event()).  
* Provides a POST /api/wikis/{id}/cancel endpoint.  
* The sync loops (mwclient fetching or XML parsing) must check this event/flag. If triggered, the process safely aborts, logs the cancellation, and reverts the wiki status to "Idle".  
* Ensure to catch any generic Exception, or asyncio.CancelledError, setting the status back to "Idle" or "Aborted". Do not throw an unknown error, catch it cleanly.

### **4.5 Background Polling (The Watcher)**

* A lightweight asyncio background task runs periodically (e.g., every 30 minutes).  
* It iterates through all tracked wikis in the database.  
* It queries the mwclient recentchanges API endpoint using the last\_sync\_timestamp (filtered to namespace=0). It limits the query to 1 result to minimize API load.  
* If a new change is detected, it updates the has\_pending\_changes flag in the SQLite database to True.  
* The backend tracks the exact timestamp of the *next* scheduled polling run and exposes it to the frontend via API (e.g., /api/status).

### **4.6 Notifications**

* When events occur (e.g., sync started, sync finished, error), a notification message is created.  
* Notifications are stored temporarily (e.g., in memory or a capped list) by the backend and broadcasted/polled by the frontend.

## **5\. User Interface (Frontend) \- "EVE Online" Tactical Theme**

The frontend must be styled entirely around a dark, sci-fi "EVE Online NeoCom" aesthetic.

**Core Theming Rules (Tailwind):**

* **Backgrounds:** Deep space blues and blacks (e.g., bg-slate-950).  
* **Panels/Cards:** Translucent with slight blurs (bg-slate-900/80 backdrop-blur-sm), sharp corners (minimal rounding, e.g., rounded-sm), and thin, high-contrast borders (e.g., border border-slate-700/50 or border-zinc-800).  
* **Text:** Muted grays (text-slate-300 or text-zinc-300) with bright cyan (text-cyan-400) or amber (text-orange-400) highlights. Use normal casing for standard text, uppercase only sparingly for main panel headers. Base font size should be at least text-sm or text-base for readability.  
* **Metrics:** Values and numbers should use tabular/mono-spaced fonts.

### **5.1 Tactical Dashboard (Fixed-Height Cards)**

The "Active Wiki Pipelines" section must **NOT** use a standard HTML \<table\>. It must use a list of **fixed-height horizontal cards** (using Tailwind flexbox or grid, e.g., h-32).

Each Tactical Card displays:

* **Target Info:** Wiki Name and URL.  
* **Telemetry (Metrics):** Total indexed raw pages and compiled bundles, styled as dense data readouts.  
* **Last Uplink:** Date/Time of the last successful sync.  
* **Live Progress Bar:** When a wiki is "Syncing", a progress bar (styled like a capacitor or shield bar: sleek, neutral industrial meter, bg-slate-400 or bg-zinc-500) and a ratio readout (\[downloaded\] / \[total\]) are displayed. The total is fetched via site.siteinfo\['statistics'\]\['articles'\].  
  * **CRITICAL UI RULE:** To prevent layout jumping, the vertical space for the progress bar MUST always be reserved in the DOM. When "Idle", the progress bar container should be made invisible (e.g., using Tailwind's invisible class, NOT hidden), so the card height never changes.  
* **Status:** (Idle, Syncing, Compiling, Error, Cancelling).  
* **Updates Available Indicator:** A visual "Ping" or amber warning icon if has\_pending\_changes \= True.  
* **Global Watcher Countdown:** A live, ticking countdown timer prominently displayed near the "Refresh List" button indicating when the backend will next check for updates (e.g., "NEXT UPLINK IN: 14m 30s").

### **5.2 Command Buttons (Compact Layout)**

Action buttons must be rendered inside the fixed-height card aligned to the right. They must have a tactical feel: thin borders, transparent backgrounds that glow on hover, and uppercase text. They should be arranged in a neat layout that does not wrap (e.g., a uniform grid or icon-heavy row).

* Sync: Manually triggers the incremental update.  
* Stop: **Only visible when status is "Syncing".** Triggers the cancel endpoint. Styled with a warning color (e.g., dark red/orange borders).  
* Rebuild: Manually regenerates files.  
* Logs: Opens a modal showing real-time backend execution logs for this specific wiki.  
* Download: Zips the contents of /data/compiled/{wiki\_id}/ and triggers a download.

### **5.3 Global System Terminal**

* A dedicated UI section streaming live global backend stdout/stderr logs.  
* Styled to look like an in-game hacker terminal: pitch black background, monospace bright green or cyan text, featuring a "Copy Data" button. Text should be comfortably readable (e.g., text-sm or text-base). Preserve original casing.

### **5.4 Notification Drawer**

* A notification drawer button in the lower right corner.  
* When a new notification arrives, a temporary pop-up appears attached above the button and disappears after 5 seconds.  
* Clicking the button opens a hovering list (drawer) of recent notifications.  
* Clicking the button again closes the drawer.  
* The drawer should automatically close after 5 seconds of inactivity/no mouse hover.

## **6\. Database Schema (SQLite)**

**Table: wikis**

* id (PK)  
* url (String)  
* name (String)  
* last\_sync\_timestamp (DateTime)  
* status (String)  
* total\_pages (Integer)  
* total\_pages\_to\_sync (Integer)  
* has\_pending\_changes (Boolean)
