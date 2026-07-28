import asyncio
import re
import logging

logger = logging.getLogger(__name__)


def sanitize_filename(title: str) -> str:
    r"""Sanitizes a page title to be used as a safe, valid filename.
    Replaces characters like / \ : * ? " < > | with underscores.
    """
    # Replace unsafe characters
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", title)
    # Strip leading/trailing spaces and dots
    cleaned = cleaned.strip(". ")
    # Ensure it's not empty, fallback to 'untitled' if so
    if not cleaned:
        cleaned = "untitled"
    return cleaned


async def convert_wikitext_to_markdown(wikitext: str) -> str:
    """Converts MediaWiki wikitext to GitHub Flavored Markdown using Pandoc."""
    if not wikitext:
        return ""

    try:
        # Run pandoc as an async subprocess to avoid blocking the event loop
        process = await asyncio.create_subprocess_exec(
            "pandoc", "--from", "mediawiki", "--to", "gfm",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate(input=wikitext.encode("utf-8"))

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8").strip()
            logger.error(f"Pandoc error (code {process.returncode}): {error_msg}")
            # Fallback: return the original wikitext or standard format rather than breaking the pipeline
            return wikitext

        return stdout.decode("utf-8")

    except Exception as e:
        logger.error(f"Exception during pandoc execution: {str(e)}")
        return wikitext
