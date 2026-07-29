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


def preprocess_table_attributes(line: str) -> str:
    """Fixes unclosed quotes in table attributes on lines starting with {|."""
    stripped = line.strip()
    if not stripped.startswith("{|"):
        return line

    # Extract the "{|" prefix
    idx = line.find("{|")
    prefix = line[:idx+2]
    rest = line[idx+2:]

    attr_pattern = re.compile(r'\b([a-zA-Z0-9_-]+)\s*=\s*')
    matches = list(attr_pattern.finditer(rest))

    if not matches:
        return line

    chunks = []
    # Add everything before the first attribute
    chunks.append(rest[:matches[0].start()])

    for idx, match in enumerate(matches):
        attr_name = match.group(1)
        start_val_idx = match.end()
        end_val_idx = matches[idx+1].start() if idx + 1 < len(matches) else len(rest)

        val_part = rest[start_val_idx:end_val_idx]
        val_stripped = val_part.strip()
        if val_stripped.startswith('"'):
            if val_stripped.count('"') == 1:
                trailing_whitespace = val_part[len(val_stripped.rstrip()):]
                if not trailing_whitespace and idx + 1 < len(matches):
                    val_part = val_stripped + '" '
                else:
                    val_part = val_stripped + '"' + trailing_whitespace
        elif val_stripped.startswith("'"):
            if val_stripped.count("'") == 1:
                trailing_whitespace = val_part[len(val_stripped.rstrip()):]
                if not trailing_whitespace and idx + 1 < len(matches):
                    val_part = val_stripped + "' "
                else:
                    val_part = val_stripped + "'" + trailing_whitespace

        chunks.append(match.group(0) + val_part)

    return prefix + "".join(chunks)


def preprocess_wikitext(wikitext: str) -> str:
    """Pre-processes Wikitext to clean up known malformed tags, e.g. unclosed quotes in table starts."""
    if not wikitext:
        return wikitext

    lines = wikitext.splitlines()
    processed_lines = []
    for line in lines:
        processed_line = preprocess_table_attributes(line)
        processed_lines.append(processed_line)
    return "\n".join(processed_lines)


async def convert_wikitext_to_markdown(wikitext: str) -> str:
    """Converts MediaWiki wikitext to GitHub Flavored Markdown using Pandoc."""
    if not wikitext:
        return ""

    try:
        # Run light pre-processing pass to correct malformed wikitext
        wikitext = preprocess_wikitext(wikitext)

        # Run pandoc as an async subprocess to avoid blocking the event loop
        # We use standard 'mediawiki' format to prevent Pandoc errors (e.g. Code 23).
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
