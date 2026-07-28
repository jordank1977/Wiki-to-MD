import os
import shutil
import logging
import datetime
from contextlib import asynccontextmanager
from typing import List, Dict, Any

from fastapi import FastAPI, BackgroundTasks, HTTPException, status
from fastapi.staticfiles import StaticFiles
import io
import zipfile
import asyncio
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from app.converter import sanitize_filename

# Track active sync/compile background tasks per wiki ID
active_tasks: Dict[int, asyncio.Task] = {}
next_watcher_run: datetime.datetime | None = None

async def run_tracked_task(wiki_id: int, coro) -> None:
    """Wrapper to run a background coroutine and ensure cleanup from active_tasks."""
    try:
        await coro
    finally:
        active_tasks.pop(wiki_id, None)

from app.db import (
    init_db,
    add_wiki,
    get_all_wikis,
    get_wiki,
    delete_wiki,
    update_wiki_status,
    update_wiki_sync_details,
    update_wiki_pending_changes,
)
from app.sync import sync_wiki_pipeline, connect_site
from app.compiler import compile_wiki_bundles

from app.logging_config import setup_logging, current_wiki_id
setup_logging()
logger = logging.getLogger("app.main")

watcher_task: Any = None


async def check_all_wikis_for_changes() -> None:
    """Checks recent changes for each tracked wiki."""
    logger.info("Watcher checking for changes on tracked wikis...")
    wikis = await get_all_wikis()
    for wiki in wikis:
        wiki_id = wiki["id"]
        last_sync = wiki.get("last_sync_timestamp")
        # If the wiki has never synced, there is no last_sync_timestamp, so we don't check for changes.
        if not last_sync:
            continue

        # If already has pending changes or is busy, no need to check
        if wiki.get("has_pending_changes") or wiki.get("status") in ("Syncing", "Compiling"):
            continue

        try:
            logger.info(f"Watcher: Checking changes for wiki '{wiki['name']}' (ID: {wiki_id}) since {last_sync}")
            site = await connect_site(wiki["url"])

            # Query recentchanges for Namespace 0 starting from last_sync (inclusive) with limit=1.
            def get_changes():
                rc = site.recentchanges(
                    namespace='0',
                    start=last_sync,
                    dir="newer",
                    limit=1
                )
                try:
                    return next(iter(rc), None)
                except StopIteration:
                    return None

            change = await asyncio.to_thread(get_changes)
            if change:
                logger.info(f"Watcher found a pending change for wiki '{wiki['name']}': {change}")
                await update_wiki_pending_changes(wiki_id, True)
            else:
                logger.info(f"Watcher found no new changes for wiki '{wiki['name']}'.")

        except Exception as e:
            logger.error(f"Watcher failed to check wiki '{wiki['name']}' (ID: {wiki_id}): {e}")

        # Respect rate limits/sleep as per AGENTS.md / Memory instructions
        await asyncio.sleep(1)


async def wiki_watcher_loop() -> None:
    """Background task that checks recent changes for tracked wikis periodically."""
    global next_watcher_run
    logger.info("Background watcher loop started.")
    # Run every 30 minutes (1800 seconds)
    # Allow customization via environment variable (e.g., for testing or quick verification)
    poll_interval = float(os.getenv("WATCHER_POLL_INTERVAL", "1800"))
    while True:
        next_watcher_run = datetime.datetime.now(datetime.timezone.utc)
        try:
            await check_all_wikis_for_changes()
        except asyncio.CancelledError:
            logger.info("Watcher loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in background watcher loop: {e}", exc_info=True)

        next_watcher_run = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=poll_interval)
        try:
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("Watcher loop cancelled during sleep.")
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown actions."""
    logger.info("Initializing SQLite Database...")
    await init_db()

    # Ensure raw/compiled directories exist
    os.makedirs("/app/data/raw", exist_ok=True)
    os.makedirs("/app/data/compiled", exist_ok=True)

    # Start the background watcher task
    global watcher_task
    watcher_task = asyncio.create_task(wiki_watcher_loop())

    yield
    logger.info("Shutting down Wiki-to-RAG Sync Engine...")
    if watcher_task:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Wiki-to-RAG Sync Engine MVP",
    description="Maintains an up-to-date, word-capped RAG bundle from MediaWiki sites.",
    version="1.0.0",
    lifespan=lifespan,
)


# Input Pydantic Model
class WikiCreate(BaseModel):
    url: str
    name: str


class WikiFetchInfo(BaseModel):
    url: str


def get_compiled_bundles_count(wiki_id: int) -> int:
    """Calculates number of generated compiled bundle files in the filesystem."""
    compiled_dir = f"/app/data/compiled/{wiki_id}"
    if not os.path.exists(compiled_dir):
        return 0
    return len([f for f in os.listdir(compiled_dir) if f.endswith(".md")])


def get_downloaded_pages_count(wiki_id: int) -> int:
    """Calculates number of raw markdown files in the raw directory."""
    raw_dir = f"/app/data/raw/{wiki_id}"
    if not os.path.exists(raw_dir):
        return 0
    return len([f for f in os.listdir(raw_dir) if f.endswith(".md")])


# Background Tasks
async def run_rebuild_task(wiki_id: int) -> None:
    """Rebuilds bundles in background."""
    current_wiki_id.set(wiki_id)
    wiki = await get_wiki(wiki_id)
    if not wiki:
        return

    await update_wiki_status(wiki_id, "Compiling")
    raw_dir = f"/app/data/raw/{wiki_id}"
    compiled_dir = f"/app/data/compiled/{wiki_id}"

    try:
        await compile_wiki_bundles(wiki_id, wiki["name"], raw_dir, compiled_dir)
        total_pages = 0
        if os.path.exists(raw_dir):
            total_pages = len([f for f in os.listdir(raw_dir) if f.endswith(".md")])

        # Restore last sync timestamp but set status back to Idle
        await update_wiki_sync_details(
            wiki_id,
            wiki.get("last_sync_timestamp"),
            total_pages,
            "Idle",
        )
    except asyncio.CancelledError:
        logger.info(f"Manual rebuild task for wiki {wiki_id} was cancelled.")
        await update_wiki_status(wiki_id, "Idle")
        raise
    except Exception as e:
        logger.error(f"Error in manual rebuild for wiki {wiki_id}: {e}")
        await update_wiki_status(wiki_id, "Error")


# Endpoints
@app.post("/api/wikis/fetch-info", response_model=Dict[str, Any])
async def api_fetch_wiki_info(payload: WikiFetchInfo):
    """Connects to the provided MediaWiki URL and retrieves its sitename."""
    url = payload.url.strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must not be empty.",
        )
    if not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )

    try:
        site = await connect_site(url)
        # Fetch sitename: site.site['sitename'] is standard in mwclient,
        # but let's safely fall back to site.siteinfo if it is populated or try siteinfo['general']['sitename']
        # site.site yields a dict containing 'sitename' as verified in the python shell.
        # site.siteinfo doesn't exist by default on mwclient Site unless fetched or initialized,
        # but 'sitename' is directly inside site.site which is fetched during site_init.
        sitename = None
        if hasattr(site, "site") and "sitename" in site.site:
            sitename = site.site["sitename"]
        else:
            # Fallback to general/sitename query if somehow not present
            try:
                res = await asyncio.to_thread(site.get, "query", meta="siteinfo", siprop="general")
                sitename = res.get("query", {}).get("general", {}).get("sitename")
            except Exception:
                pass

        if not sitename:
            sitename = "Unnamed Wiki"

        return {"sitename": sitename}
    except Exception as e:
        logger.error(f"Failed to fetch wiki sitename for {url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch wiki information. Ensure the URL is a valid MediaWiki API endpoint. Error: {str(e)}",
        )


@app.get("/api/status")
async def api_get_status():
    """Retrieves system status, including the next scheduled background watcher run."""
    global next_watcher_run
    if next_watcher_run is None:
        return {"next_watcher_run": None}
    return {"next_watcher_run": next_watcher_run.isoformat()}


@app.get("/api/wikis", response_model=List[Dict[str, Any]])
async def api_get_all_wikis():
    """Retrieves all tracked wikis with their files and compiled counts."""
    wikis = await get_all_wikis()
    results = []
    for wiki in wikis:
        wiki_dict = dict(wiki)
        wiki_dict["compiled_bundles_count"] = get_compiled_bundles_count(wiki["id"])
        wiki_dict["downloaded_pages"] = get_downloaded_pages_count(wiki["id"])
        results.append(wiki_dict)
    return results


@app.post("/api/wikis", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def api_add_wiki(wiki_in: WikiCreate):
    """Registers a new wiki url to be tracked."""
    url = wiki_in.url.strip()
    name = wiki_in.name.strip()

    if not url or not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL and Name must not be empty.",
        )

    # Ensure trailing slash is cleaned up or standardized if needed
    if not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )

    try:
        wiki = await add_wiki(url, name)
        wiki_dict = dict(wiki)
        wiki_dict["compiled_bundles_count"] = 0
        return wiki_dict
    except Exception as e:
        logger.error(f"Failed to add wiki to database: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register wiki.",
        )


@app.delete("/api/wikis/{wiki_id}")
async def api_delete_wiki(wiki_id: int):
    """Deletes a wiki pipeline, its raw files, and compiled bundles."""
    wiki = await get_wiki(wiki_id)
    if not wiki:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki with ID {wiki_id} not found.",
        )

    # Delete from database
    await delete_wiki(wiki_id)

    # Delete filesystem directories
    raw_dir = f"/app/data/raw/{wiki_id}"
    compiled_dir = f"/app/data/compiled/{wiki_id}"
    temp_dir = f"/app/data/temp/{wiki_id}"

    for path in [raw_dir, compiled_dir, temp_dir]:
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                logger.info(f"Cleaned up path on delete: {path}")
            except Exception as e:
                logger.error(f"Failed to delete directory {path} on wiki deletion: {e}")

    return {"message": "Wiki pipeline successfully deleted."}


@app.post("/api/wikis/{wiki_id}/sync")
async def api_sync_wiki(wiki_id: int):
    """Triggers an incremental or initial sync background task."""
    wiki = await get_wiki(wiki_id)
    if not wiki:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki with ID {wiki_id} not found.",
        )

    if wiki["status"] in ("Syncing", "Compiling"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "message": f"Wiki is currently busy in state: {wiki['status']}. Please wait."
            },
        )

    # Set status to Syncing immediately to prevent concurrent triggers
    await update_wiki_status(wiki_id, "Syncing")

    # Create task and track it
    task = asyncio.create_task(run_tracked_task(wiki_id, sync_wiki_pipeline(wiki_id)))
    active_tasks[wiki_id] = task
    return {"message": "Sync task successfully triggered in the background."}


@app.post("/api/wikis/{wiki_id}/rebuild")
async def api_rebuild_wiki(wiki_id: int):
    """Manually rebuilds word-capped bundles in background."""
    wiki = await get_wiki(wiki_id)
    if not wiki:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki with ID {wiki_id} not found.",
        )

    if wiki["status"] in ("Syncing", "Compiling"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "message": f"Wiki is currently busy in state: {wiki['status']}. Please wait."
            },
        )

    # Set status to Compiling immediately
    await update_wiki_status(wiki_id, "Compiling")

    # Create task and track it
    task = asyncio.create_task(run_tracked_task(wiki_id, run_rebuild_task(wiki_id)))
    active_tasks[wiki_id] = task
    return {"message": "Rebuild task successfully triggered in the background."}


@app.post("/api/wikis/{wiki_id}/stop")
async def api_stop_wiki(wiki_id: int):
    """Stops an ongoing sync or compile background task for a specific wiki."""
    wiki = await get_wiki(wiki_id)
    if not wiki:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki with ID {wiki_id} not found.",
        )

    task = active_tasks.get(wiki_id)
    if task and not task.done():
        logger.info(f"Cancelling active task for wiki {wiki_id}...")
        task.cancel()
        try:
            if task.get_loop() == asyncio.get_running_loop():
                await task
        except asyncio.CancelledError:
            logger.info(f"CancelledError handled successfully for stopped task of wiki {wiki_id}.")
        except Exception:
            pass
        # Set database status to Idle
        await update_wiki_status(wiki_id, "Idle")
        return {"message": "Sync/Rebuild process successfully stopped."}
    else:
        # If no active task reference, but database says Syncing/Compiling, set status to Idle
        if wiki["status"] in ("Syncing", "Compiling"):
            await update_wiki_status(wiki_id, "Idle")
            return {"message": "Process marked as Idle."}
        return {"message": "No active process found to stop."}


def get_last_n_lines(file_path: str, n: int = 200) -> str:
    """Reads the last N lines of a file safely."""
    if not os.path.exists(file_path):
        return ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception:
        return "Error reading log file."


@app.get("/api/wikis/{wiki_id}/logs")
async def api_get_wiki_logs(wiki_id: int):
    """Retrieves execution logs for a specific wiki pipeline."""
    wiki = await get_wiki(wiki_id)
    if not wiki:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki with ID {wiki_id} not found."
        )
    log_file = f"/app/data/logs/{wiki_id}.log"
    if not os.path.exists(log_file):
        return {"logs": "No logs recorded yet."}
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        return {"logs": content}
    except Exception as e:
        logger.error(f"Failed to read logs for wiki {wiki_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read wiki logs."
        )


@app.get("/api/logs/global")
async def api_get_global_logs():
    """Retrieves the last 200 lines of the global application log."""
    log_file = "/app/data/logs/global.log"
    logs = get_last_n_lines(log_file, 200)
    return {"logs": logs}


@app.get("/api/wikis/{wiki_id}/download")
async def api_download_bundles(wiki_id: int):
    """Zips the compiled bundles and sends them to the user's browser."""
    wiki = await get_wiki(wiki_id)
    if not wiki:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wiki with ID {wiki_id} not found.",
        )

    compiled_dir = f"/app/data/compiled/{wiki_id}"
    if not os.path.exists(compiled_dir) or not os.listdir(compiled_dir):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No compiled bundles found for this wiki. Please rebuild or sync first.",
        )

    # Create zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, _, files in os.walk(compiled_dir):
            for file in files:
                if file.endswith(".md"):
                    file_path = os.path.join(root, file)
                    zip_file.write(file_path, arcname=file)

    zip_buffer.seek(0)
    safe_name = sanitize_filename(wiki["name"])

    last_sync = wiki.get("last_sync_timestamp")
    if last_sync:
        try:
            date_str = last_sync.split("T")[0]
            date_str = sanitize_filename(date_str)
        except Exception:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    else:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    filename = f"{safe_name}_Export_{date_str}.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# Serve Static Files
# Create static directory if it doesn't exist
os.makedirs("/app/app/static", exist_ok=True)

@app.get("/")
async def serve_index():
    """Serves the main single-page application dashboard."""
    index_path = "/app/app/static/index.html"
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"message": "Frontend index.html file not found."},
    )

# Mount static files folder
app.mount("/static", StaticFiles(directory="/app/app/static"), name="static")
