import os
import shutil
import pytest
from app.compiler import compile_wiki_bundles, count_words


def test_count_words():
    assert count_words("Hello world this is a test") == 6
    assert count_words("") == 0
    assert count_words(None) == 0


@pytest.mark.asyncio
async def test_compile_wiki_bundles(tmp_path):
    raw_dir = tmp_path / "raw"
    compiled_dir = tmp_path / "compiled"

    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(compiled_dir, exist_ok=True)

    # Create 3 page files
    page_1_content = "This is the first page of our wiki. It has some text here."
    page_2_content = "Here is the second page, which is also very interesting."
    page_3_content = "Finally, the third page contains some extra information."

    with open(raw_dir / "Page_1.md", "w", encoding="utf-8") as f:
        f.write(page_1_content)
    with open(raw_dir / "Page_2.md", "w", encoding="utf-8") as f:
        f.write(page_2_content)
    with open(raw_dir / "Page_3.md", "w", encoding="utf-8") as f:
        f.write(page_3_content)

    # Mock get_wiki from app.db so compile_wiki_bundles can read last_sync_timestamp
    from unittest.mock import AsyncMock, patch

    # 1. Test Never Synced fallback (now falls back to current system date)
    import datetime
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    with patch("app.db.get_wiki", AsyncMock(return_value={"id": 1, "name": "My_Test_Wiki", "last_sync_timestamp": None})):
        await compile_wiki_bundles(1, "My_Test_Wiki", str(raw_dir), str(compiled_dir))

    # Check that a single bundle is created with the current system date
    bundles = os.listdir(compiled_dir)
    assert len(bundles) == 1
    assert bundles[0] == f"My_Test_Wiki_{current_date}_Bundle_1.md"

    # Verify content of the bundle
    with open(compiled_dir / bundles[0], "r", encoding="utf-8") as f:
        bundle_text = f.read()

    assert "# Page: Page_1" in bundle_text
    assert page_1_content in bundle_text
    assert "# Page: Page_2" in bundle_text
    assert page_2_content in bundle_text
    assert "# Page: Page_3" in bundle_text
    assert page_3_content in bundle_text
    assert "---" in bundle_text

    # Clean compiled files
    for f_name in os.listdir(compiled_dir):
        os.remove(compiled_dir / f_name)

    # 2. Test with actual timestamp
    with patch("app.db.get_wiki", AsyncMock(return_value={"id": 1, "name": "My_Test_Wiki", "last_sync_timestamp": "2026-07-24T18:00:00Z"})):
        await compile_wiki_bundles(1, "My_Test_Wiki", str(raw_dir), str(compiled_dir))

    bundles = os.listdir(compiled_dir)
    assert len(bundles) == 1
    assert bundles[0] == "My_Test_Wiki_2026-07-24_Bundle_1.md"

    # Verify content of the bundle
    with open(compiled_dir / bundles[0], "r", encoding="utf-8") as f:
        bundle_text = f.read()

    assert "# Page: Page_1" in bundle_text
    assert page_1_content in bundle_text
    assert "# Page: Page_2" in bundle_text
    assert page_2_content in bundle_text
    assert "# Page: Page_3" in bundle_text
    assert page_3_content in bundle_text
    assert "---" in bundle_text
