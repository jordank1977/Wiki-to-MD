import os
import glob
import logging
import datetime
from typing import List

from app.converter import sanitize_filename

logger = logging.getLogger(__name__)

WORD_LIMIT_THRESHOLD = 400000


def count_words(text: str) -> int:
    """Simple and fast word counter."""
    if not text:
        return 0
    return len(text.split())


async def compile_wiki_bundles(
    wiki_id: int, wiki_name: str, raw_dir: str, compiled_dir: str
) -> None:
    """Compiles all individual raw markdown pages into word-capped bundle files."""
    logger.info(f"Starting compilation for wiki '{wiki_name}' (ID: {wiki_id})...")

    # Ensure compiled output directory exists
    os.makedirs(compiled_dir, exist_ok=True)

    # Fetch last_sync_timestamp from the database
    from app.db import get_wiki
    wiki = await get_wiki(wiki_id)
    last_sync = wiki.get("last_sync_timestamp") if wiki else None

    if last_sync:
        try:
            date_str = last_sync.split("T")[0]
            date_str = sanitize_filename(date_str)
        except Exception:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    else:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    # 1. Clean existing bundles in compiled directory
    old_bundles = glob.glob(os.path.join(compiled_dir, "*.md"))
    for old_file in old_bundles:
        try:
            os.remove(old_file)
            logger.info(f"Removed old bundle file: {old_file}")
        except Exception as e:
            logger.error(f"Failed to remove old bundle file {old_file}: {e}")

    # 2. Find and sort all raw markdown files alphabetically to ensure deterministic bundles
    raw_files = sorted(glob.glob(os.path.join(raw_dir, "*.md")))
    if not raw_files:
        logger.warning(f"No raw markdown files found in {raw_dir} to compile.")
        return

    logger.info(f"Found {len(raw_files)} pages to bundle.")

    # Sanitized WikiName for safe filenames
    sanitized_wiki_name = sanitize_filename(wiki_name)

    current_bundle_index = 1
    current_bundle_content: List[str] = []
    current_bundle_words = 0

    def write_current_bundle() -> None:
        nonlocal current_bundle_index, current_bundle_content, current_bundle_words
        if not current_bundle_content:
            return

        bundle_filename = f"{sanitized_wiki_name}_{date_str}_Bundle_{current_bundle_index}.md"
        bundle_path = os.path.join(compiled_dir, bundle_filename)

        logger.info(f"Writing {bundle_filename} with {current_bundle_words} words...")
        with open(bundle_path, "w", encoding="utf-8") as f:
            f.write("\n".join(current_bundle_content))

        current_bundle_index += 1
        current_bundle_content = []
        current_bundle_words = 0

    for file_path in raw_files:
        try:
            # Extract page title from filename
            filename = os.path.basename(file_path)
            title = os.path.splitext(filename)[0]

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Format the page block cleanly
            # We add clear delimiters so RAG can identify boundaries
            formatted_block = f"# Page: {title}\n\n{content}\n\n---\n"
            block_words = count_words(formatted_block)

            # If adding this block exceeds the word limit, write current bundle and start a new one
            if current_bundle_words + block_words > WORD_LIMIT_THRESHOLD:
                # If current bundle is already empty, we must write it anyway to avoid infinite loop
                if current_bundle_content:
                    write_current_bundle()

            current_bundle_content.append(formatted_block)
            current_bundle_words += block_words

        except Exception as e:
            logger.error(f"Error compiling page file '{file_path}': {e}")

    # Write any remaining content to final bundle
    write_current_bundle()
    logger.info(f"Finished compilation. Total bundles generated: {current_bundle_index - 1}")
