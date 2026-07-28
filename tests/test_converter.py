import pytest
from app.converter import sanitize_filename, convert_wikitext_to_markdown


def test_sanitize_filename():
    assert sanitize_filename("Tengu") == "Tengu"
    assert sanitize_filename("Talk:Guides/Tengu & Loki: 2024?") == "Talk_Guides_Tengu & Loki_ 2024_"
    assert sanitize_filename("File:Image.png") == "File_Image.png"
    assert sanitize_filename("   ") == "untitled"
    assert sanitize_filename("...Page...") == "Page"


@pytest.mark.asyncio
async def test_convert_wikitext_to_markdown():
    wikitext = "= Main Header =\nSome ''italic'' and '''bold''' text."
    markdown = await convert_wikitext_to_markdown(wikitext)

    # We check if header and formatting were parsed by pandoc
    assert "# Main Header" in markdown
    # Note: Pandoc converts ''italic'' to *italic* or _italic_ and '''bold''' to **bold**
    assert "italic" in markdown
    assert "bold" in markdown
