import os
import asyncio
import logging
import datetime
from urllib.parse import urlparse
from typing import Dict

import mwclient

from app.db import update_wiki_status, update_wiki_sync_details, get_wiki, update_wiki_total_pages
from app.converter import convert_wikitext_to_markdown, sanitize_filename
from app.compiler import compile_wiki_bundles
from app.logging_config import current_wiki_id

logger = logging.getLogger(__name__)

RAW_DIR_ROOT = "/app/data/raw"
COMPILED_DIR_ROOT = "/app/data/compiled"

# Global state to track real-time download counts per wiki ID
current_download_count: Dict[int, int] = {}


async def connect_site(url: str) -> mwclient.Site:
    """Connects to a MediaWiki Site, auto-detecting the API path."""
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    host = parsed.netloc

    # Always prioritize '/' to connect instantly on the first try
    paths_to_try = ["/"]

    if parsed.path and parsed.path != "/":
        url_path = parsed.path
        if not url_path.endswith("/"):
            url_path += "/"
        # Avoid standard article paths (like /wiki/...) as they are not API endpoints
        if not url_path.startswith("/wiki/") and url_path not in paths_to_try:
            paths_to_try.append(url_path)

    # Standard MediaWiki API paths to try as fallbacks
    for p in ["/w/", "/mediawiki/"]:
        if p not in paths_to_try:
            paths_to_try.append(p)

    last_err = None
    for path in paths_to_try:
        try:
            logger.info(f"Attempting to connect to mwclient.Site on host={host}, path={path}, scheme={scheme}")
            site = await asyncio.to_thread(mwclient.Site, host, path=path, scheme=scheme)
            logger.info(f"Connected successfully using path={path}")
            return site
        except Exception as e:
            last_err = e
            continue

    raise Exception(f"Failed to connect to MediaWiki API at {url}. Last error: {last_err}")


async def sync_wiki_pipeline(wiki_id: int) -> None:
    """Core stage-1 and stage-2 sync pipeline.
    Runs asynchronously as a background task.
    """
    current_wiki_id.set(wiki_id)
    wiki = await get_wiki(wiki_id)
    if not wiki:
        logger.error(f"Wiki with id {wiki_id} not found in database.")
        return

    # Update status to Syncing
    await update_wiki_status(wiki_id, "Syncing")

    # Define paths
    raw_dir = os.path.join(RAW_DIR_ROOT, str(wiki_id))
    compiled_dir = os.path.join(COMPILED_DIR_ROOT, str(wiki_id))

    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(compiled_dir, exist_ok=True)

    try:
        current_total_pages = 0
        # Fetch site statistics before beginning sync
        try:
            logger.info(f"Connecting to site to fetch total pages statistics: {wiki['url']}")
            site = await connect_site(wiki["url"])
            res = site.get('query', meta='siteinfo', siprop='statistics')
            site.siteinfo = res.get('query', {})
            total_pages_stat = site.siteinfo.get('statistics', {}).get('articles', 0)
            logger.info(f"Total pages tracking: found {total_pages_stat} articles from siteinfo")
            await update_wiki_total_pages(wiki_id, total_pages_stat)
            current_total_pages = total_pages_stat
        except Exception as e:
            logger.error(f"Failed to fetch site statistics or update total pages: {e}")
            current_total_pages = wiki.get("total_pages", 0) or 0

        last_sync = wiki.get("last_sync_timestamp")

        # Bootstrapping (Initial Ingestion)
        if not last_sync:
            logger.info(f"Starting initial ingestion for wiki: {wiki['name']} ({wiki['url']})")
            await run_mwclient_bulk_sync(wiki_id, wiki["url"], raw_dir)

        # Incremental Syncing
        else:
            logger.info(f"Starting incremental sync for wiki: {wiki['name']} since {last_sync}")
            await run_mwclient_incremental_sync(wiki_id, wiki["url"], raw_dir, last_sync)

        # Stage 2: Compiling / Bundling
        logger.info(f"Triggering compilation / bundling for wiki: {wiki['name']}")
        await update_wiki_status(wiki_id, "Compiling")

        # Count actual markdown files in raw folder
        total_pages = len([f for f in os.listdir(raw_dir) if f.endswith(".md")])

        # Compile bundles
        await compile_wiki_bundles(wiki_id, wiki["name"], raw_dir, compiled_dir)

        # Update last sync timestamp and status to Idle
        current_time = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        await update_wiki_sync_details(wiki_id, current_time, total_pages, "Idle")
        logger.info(f"Sync pipeline successfully completed for wiki: {wiki['name']}")

    except asyncio.CancelledError:
        logger.info("Sync aborted by user")
        await update_wiki_status(wiki_id, "Idle")
        raise
    except Exception as e:
        logger.exception(f"Error in sync pipeline for wiki {wiki_id}: {str(e)}")
        await update_wiki_status(wiki_id, "Error")
    finally:
        current_download_count.pop(wiki_id, None)


async def run_mwclient_bulk_sync(wiki_id: int, url: str, raw_dir: str) -> None:
    """Bulk sync of the full wiki using MediaWiki's generator API."""
    logger.info("Running bulk sync using mwclient API generator...")
    site = await connect_site(url)

    wiki = await get_wiki(wiki_id)
    current_total_pages = wiki["total_pages"] if wiki else 0

    pages_count = 0
    current_download_count[wiki_id] = 0

    kwargs = {
        'action': 'query',
        'generator': 'allpages',
        'gapnamespace': 0,
        'gapfilterredir': 'nonredirects',  # Filters out redirect pages
        'gaplimit': 50,  # Fetch up to 50 pages per API call
        'prop': 'revisions',
        'rvprop': 'content',
        'rvslots': 'main'
    }

    continue_params = {}
    while True:
        params = {**kwargs, **continue_params}
        logger.info(f"Fetching bulk pages with params: {params}")
        try:
            res = await asyncio.to_thread(site.api, **params)
        except Exception as e:
            logger.error(f"Failed bulk API query: {e}")
            break

        query_data = res.get("query", {})
        pages_data = query_data.get("pages", {})

        for page_key, page_val in pages_data.items():
            # Check for cancellation and yield execution
            await asyncio.sleep(0)

            title = page_val.get("title")
            if "missing" in page_val or not title:
                continue

            revisions = page_val.get("revisions", [])
            if not revisions:
                continue

            rev = revisions[0]
            wikitext = ""
            if "slots" in rev and "main" in rev["slots"]:
                wikitext = rev["slots"]["main"].get("*", "") or ""
            elif "*" in rev:
                wikitext = rev.get("*", "") or ""

            try:
                markdown = await convert_wikitext_to_markdown(wikitext)
                filename = sanitize_filename(title) + ".md"
                file_path = os.path.join(raw_dir, filename)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown)

                pages_count += 1
                current_download_count[wiki_id] = pages_count
                logger.info(f"Page bulk downloaded and saved: '{title}' ({pages_count} total)")

                # Dynamic Denominator Adjustment
                if pages_count > current_total_pages:
                    current_total_pages = pages_count
                    await update_wiki_total_pages(wiki_id, current_total_pages)

            except Exception as e:
                logger.error(f"Failed to process page '{title}': {e}")

        if "continue" in res:
            continue_params = res["continue"]
            logger.info(f"More pages available. Continuing with token: {continue_params}")
        else:
            break

        # Respect 1.5s delay between requests
        await asyncio.sleep(1.5)

    logger.info(f"Bulk sync complete. Saved {pages_count} pages.")


async def run_mwclient_incremental_sync(wiki_id: int, url: str, raw_dir: str, last_sync_time_str: str) -> None:
    """Performs an incremental sync using mwclient since the last sync timestamp."""
    site = await connect_site(url)

    # 1. Query Recent Changes (Edits and Creations)
    logger.info(f"Querying recent changes since {last_sync_time_str}")

    # mwclient.recentchanges accepts ISO 8601 string or struct_time for start
    # We fetch newest to oldest or vice-versa. dir='newer' gets them ascending.
    recent_changes = site.recentchanges(
        namespace='0',
        start=last_sync_time_str,
        dir="newer"
    )

    processed_pages = set()
    for change in recent_changes:
        title = change.get("title")
        change_type = change.get("type")

        if not title or title in processed_pages:
            continue

        processed_pages.add(title)

        # If edit or new creation, fetch updated wikitext, convert and save
        if change_type in ("edit", "new"):
            logger.info(f"Syncing updated/new page: {title}")
            try:
                page = site.pages[title]
                if page.redirects_to is not None:
                    logger.info(f"Page '{title}' is a redirect. Removing local file if exists.")
                    filename = sanitize_filename(title) + ".md"
                    file_path = os.path.join(raw_dir, filename)
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            logger.info(f"Deleted redirect local file: {file_path}")
                        except Exception as e:
                            logger.error(f"Failed to delete local redirect file '{file_path}': {e}")
                else:
                    wikitext = page.text()
                    markdown = await convert_wikitext_to_markdown(wikitext)

                    filename = sanitize_filename(title) + ".md"
                    file_path = os.path.join(raw_dir, filename)

                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(markdown)
                    logger.info(f"Page downloaded and saved: '{title}' (via incremental sync)")

            except Exception as e:
                logger.error(f"Failed to sync updated page '{title}': {e}")

            # Respect rate limit per AGENTS.md
            await asyncio.sleep(1)

    # 2. Query Log Events (Administrative actions: deletes & moves)
    logger.info(f"Querying log events since {last_sync_time_str}")
    log_events = site.logevents(
        start=last_sync_time_str,
        dir="newer"
    )

    for log in log_events:
        log_type = log.get("type")
        ns = log.get("ns")
        title = log.get("title")

        if ns != 0 or not title:
            continue

        if log_type == "delete":
            logger.info(f"Syncing deleted page: {title}")
            filename = sanitize_filename(title) + ".md"
            file_path = os.path.join(raw_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted local file: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to delete local file '{file_path}': {e}")

        elif log_type == "move":
            logger.info(f"Syncing moved page from: {title}")
            # Delete old file
            old_filename = sanitize_filename(title) + ".md"
            old_file_path = os.path.join(raw_dir, old_filename)
            if os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                    logger.info(f"Deleted old local file: {old_file_path}")
                except Exception as e:
                    logger.error(f"Failed to delete old local file '{old_file_path}': {e}")

            # Fetch new page if it's in Namespace 0
            params = log.get("params") or {}
            target_ns = params.get("target_ns")
            target_title = params.get("target_title")

            if target_ns == 0 and target_title:
                logger.info(f"Syncing moved target page: {target_title}")
                try:
                    page = site.pages[target_title]
                    if page.redirects_to is not None:
                        logger.info(f"Moved target page '{target_title}' is a redirect. Excluding.")
                    else:
                        wikitext = page.text()
                        markdown = await convert_wikitext_to_markdown(wikitext)

                        new_filename = sanitize_filename(target_title) + ".md"
                        new_file_path = os.path.join(raw_dir, new_filename)

                        with open(new_file_path, "w", encoding="utf-8") as f:
                            f.write(markdown)
                        logger.info(f"Page downloaded and saved: '{target_title}' (moved target page via incremental sync)")
                except Exception as e:
                    logger.error(f"Failed to sync moved target page '{target_title}': {e}")

                # Respect rate limit per AGENTS.md
                await asyncio.sleep(1)
