import os
import shutil
import glob
import re
import asyncio
import logging
import datetime
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from typing import Generator, Tuple, Optional

import mwclient

from app.db import update_wiki_status, update_wiki_sync_details, get_wiki, update_wiki_total_pages
from app.converter import convert_wikitext_to_markdown, sanitize_filename
from app.compiler import compile_wiki_bundles
from app.logging_config import current_wiki_id

logger = logging.getLogger(__name__)

RAW_DIR_ROOT = "/app/data/raw"
COMPILED_DIR_ROOT = "/app/data/compiled"
TEMP_DIR_ROOT = "/app/data/temp"


def parse_xml_dump(xml_path: str) -> Generator[Tuple[str, str], None, None]:
    """Parses a MediaWiki XML dump using memory-efficient iterparse.
    Filters strictly for Namespace 0 (Main articles).
    """
    context = ET.iterparse(xml_path, events=("start", "end"))
    context = iter(context)
    try:
        event, root = next(context)
    except StopIteration:
        return

    # Extract namespace prefix
    m = re.match(r"\{.*\}", root.tag)
    ns = m.group(0) if m else ""

    for event, elem in context:
        if event == "end" and elem.tag == f"{ns}page":
            title_elem = elem.find(f"{ns}title")
            ns_elem = elem.find(f"{ns}ns")

            title = title_elem.text if title_elem is not None else ""
            namespace = ns_elem.text if ns_elem is not None else ""

            # Namespace 0 represents main articles
            if namespace == "0" and title:
                revision = elem.find(f"{ns}revision")
                if revision is not None:
                    text_elem = revision.find(f"{ns}text")
                    text = text_elem.text if text_elem is not None and text_elem.text else ""
                    yield title, text

            # Clear elements from memory to keep footprint low
            elem.clear()
            root.clear()


async def connect_site(url: str) -> mwclient.Site:
    """Connects to a MediaWiki Site, auto-detecting the API path."""
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    host = parsed.netloc

    paths_to_try = []
    if parsed.path and parsed.path != "/":
        url_path = parsed.path
        if not url_path.endswith("/"):
            url_path += "/"
        paths_to_try.append(url_path)

    # Standard MediaWiki API paths to try
    for p in ["/", "/w/", "/mediawiki/"]:
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
    temp_dir = os.path.join(TEMP_DIR_ROOT, str(wiki_id))

    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(compiled_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # Fetch site statistics before beginning sync
        try:
            logger.info(f"Connecting to site to fetch total pages statistics: {wiki['url']}")
            site = await connect_site(wiki["url"])
            res = site.get('query', meta='siteinfo', siprop='statistics')
            site.siteinfo = res.get('query', {})
            total_pages_stat = site.siteinfo.get('statistics', {}).get('articles', 0)
            logger.info(f"Total pages tracking: found {total_pages_stat} articles from siteinfo")
            await update_wiki_total_pages(wiki_id, total_pages_stat)
        except Exception as e:
            logger.error(f"Failed to fetch site statistics or update total pages: {e}")

        last_sync = wiki.get("last_sync_timestamp")

        # Bootstrapping (Initial Ingestion)
        if not last_sync:
            logger.info(f"Starting initial ingestion for wiki: {wiki['name']} ({wiki['url']})")

            # Trigger wikiteam3 subprocess
            cmd = [
                "wikiteam3dumpgenerator",
                wiki["url"],
                "--xml",
                "--curonly",
                "--force",
                "--path", temp_dir
            ]
            logger.info(f"Running subprocess command: {' '.join(cmd)}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Automatically pass "y" to resume prompts
            try:
                process.stdin.write(b"y\n")
                await process.stdin.drain()
            except Exception as e:
                logger.warning(f"Failed to write 'y\\n' to wikiteam3 stdin: {e}")

            # Consume subprocess stdout and stderr streams asynchronously to log in real-time
            async def log_stream(stream, is_stderr=False):
                while True:
                    line_bytes = await stream.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode('utf-8', errors='replace').rstrip()
                    if line:
                        if is_stderr:
                            logger.info(f"[wikiteam3-stderr] {line}")
                        else:
                            logger.info(f"[wikiteam3-stdout] {line}")

            try:
                await asyncio.gather(
                    log_stream(process.stdout, is_stderr=False),
                    log_stream(process.stderr, is_stderr=True),
                    process.wait()
                )
            except asyncio.CancelledError:
                logger.info("Sync pipeline cancelled. Terminating wikiteam3 subprocess...")
                try:
                    process.terminate()
                    await process.wait()
                except Exception as e:
                    logger.warning(f"Failed to terminate wikiteam3 subprocess: {e}")
                raise

            if process.returncode != 0:
                logger.warning(
                    f"wikiteam3dumpgenerator exited with non-zero code {process.returncode}. "
                    f"Falling back to crawling API with mwclient."
                )
                # Fallback to mwclient Crawl Ingestion
                await run_mwclient_full_crawl(wiki_id, wiki["url"], raw_dir)
            else:
                logger.info("wikiteam3dumpgenerator completed successfully. Parsing XML dump...")
                # Find parsed XML files
                xml_files = glob.glob(os.path.join(temp_dir, "**/*.xml"), recursive=True)
                if not xml_files:
                    logger.warning("No XML file found in wikiteam3 output. Falling back to mwclient crawl.")
                    await run_mwclient_full_crawl(wiki_id, wiki["url"], raw_dir)
                else:
                    # Parse the first XML file found
                    xml_path = xml_files[0]
                    logger.info(f"Found XML dump file: {xml_path}")

                    pages_count = 0
                    for title, wikitext in parse_xml_dump(xml_path):
                        # Convert and save
                        markdown = await convert_wikitext_to_markdown(wikitext)
                        filename = sanitize_filename(title) + ".md"
                        file_path = os.path.join(raw_dir, filename)

                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(markdown)

                        pages_count += 1
                        logger.info(f"Page downloaded and saved from XML: '{title}' ({pages_count} total)")

                    logger.info(f"Initial XML ingestion complete. Extracted {pages_count} pages.")

            # Clean up temp folder
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory {temp_dir}: {e}")

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


async def run_mwclient_full_crawl(wiki_id: int, url: str, raw_dir: str) -> None:
    """Fallback crawl of the full wiki using mwclient."""
    logger.info("Running fallback full crawl using mwclient API...")
    site = await connect_site(url)

    pages_count = 0
    # mwclient site.allpages generates all pages
    for page in site.allpages(namespace='0'):
        title = page.name
        try:
            wikitext = page.text()
            markdown = await convert_wikitext_to_markdown(wikitext)
            filename = sanitize_filename(title) + ".md"
            file_path = os.path.join(raw_dir, filename)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(markdown)

            pages_count += 1
            logger.info(f"Page downloaded and saved: '{title}' ({pages_count} total)")
        except Exception as e:
            logger.error(f"Failed to crawl page '{title}': {e}")

        # AGENTS.md rate limiting rule: MUST include 1s sleep per iteration
        await asyncio.sleep(1)

    logger.info(f"Fallback crawl complete. Saved {pages_count} pages.")


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
