import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db
import asyncio


@pytest.fixture(autouse=True)
def setup_db():
    # Use synchronous wrapper to initialize the database
    asyncio.run(init_db())
    yield


def test_api_workflow():
    client = TestClient(app)

    # 1. Clear any pre-existing wiki to ensure deterministic test
    response = client.get("/api/wikis")
    assert response.status_code == 200
    initial_wikis = response.json()

    # 2. Add a new wiki pipeline
    payload = {
        "url": "https://wiki.example.org",
        "name": "Example Wiki"
    }
    response = client.post("/api/wikis", json=payload)
    assert response.status_code == 201
    wiki = response.json()
    assert wiki["name"] == "Example Wiki"
    assert wiki["url"] == "https://wiki.example.org"
    assert wiki["status"] == "Idle"
    assert wiki["total_pages"] == 0
    wiki_id = wiki["id"]

    # 3. List wikis and verify it's there
    response = client.get("/api/wikis")
    assert response.status_code == 200
    wikis = response.json()
    assert len(wikis) >= 1
    assert any(w["id"] == wiki_id for w in wikis)

    # 4. Trigger Rebuild (should succeed and start task in background)
    response = client.post(f"/api/wikis/{wiki_id}/rebuild")
    assert response.status_code == 200
    assert "triggered" in response.json()["message"]

    # 5. Check busy status (should be Compiling because of background task or local transition)
    response = client.get("/api/wikis")
    assert response.status_code == 200

    # 6. Delete the pipeline
    response = client.delete(f"/api/wikis/{wiki_id}")
    assert response.status_code == 200
    assert response.json()["message"] == "Wiki pipeline successfully deleted."

    # 7. Confirm deleted
    response = client.get("/api/wikis")
    assert response.status_code == 200
    wikis_after = response.json()
    assert not any(w["id"] == wiki_id for w in wikis_after)


def test_logs_and_download_endpoints():
    import os
    import shutil
    import zipfile
    import io
    client = TestClient(app)

    # 1. Add a temporary wiki pipeline
    payload = {
        "url": "https://test.wiki.org",
        "name": "Test Logs Wiki"
    }
    response = client.post("/api/wikis", json=payload)
    assert response.status_code == 201
    wiki = response.json()
    wiki_id = wiki["id"]

    # 2. Test global logs endpoint
    response = client.get("/api/logs/global")
    assert response.status_code == 200
    assert "logs" in response.json()

    # 3. Test wiki-specific logs endpoint (when no logs exist)
    response = client.get(f"/api/wikis/{wiki_id}/logs")
    assert response.status_code == 200
    assert response.json()["logs"] == "No logs recorded yet."

    # 4. Test wiki-specific logs endpoint (with log file present)
    log_dir = "/app/data/logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, f"{wiki_id}.log")
    with open(log_file_path, "w", encoding="utf-8") as f:
        f.write("Sync completed successfully for Test Logs Wiki.")

    response = client.get(f"/api/wikis/{wiki_id}/logs")
    assert response.status_code == 200
    assert "Sync completed successfully" in response.json()["logs"]

    # Clean up the dummy log file
    if os.path.exists(log_file_path):
        os.remove(log_file_path)

    # 5. Test download endpoint (when no bundles exist)
    response = client.get(f"/api/wikis/{wiki_id}/download")
    assert response.status_code == 404
    assert "No compiled bundles found" in response.json()["detail"]

    # 6. Test download endpoint (with a compiled bundle file present)
    compiled_dir = f"/app/data/compiled/{wiki_id}"
    os.makedirs(compiled_dir, exist_ok=True)
    bundle_file_path = os.path.join(compiled_dir, "Test_Bundle_1.md")
    with open(bundle_file_path, "w", encoding="utf-8") as f:
        f.write("# Dummy Wiki Bundle Page\nSome content.")

    import datetime
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    expected_filename = f"attachment; filename=Test Logs Wiki_Export_{current_date}.zip"

    response = client.get(f"/api/wikis/{wiki_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert expected_filename in response.headers["content-disposition"]

    # Verify the ZIP contents
    zip_bytes = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        file_list = zf.namelist()
        assert "Test_Bundle_1.md" in file_list
        # Read the file from inside the ZIP
        assert zf.read("Test_Bundle_1.md").decode("utf-8") == "# Dummy Wiki Bundle Page\nSome content."

    # Now let's test with a mock timestamp on the wiki to check custom zip name formatting
    from app.db import update_wiki_sync_details
    asyncio.run(update_wiki_sync_details(wiki_id, "2026-07-24T18:00:00Z", 1, "Idle"))

    response2 = client.get(f"/api/wikis/{wiki_id}/download")
    assert response2.status_code == 200
    assert "attachment; filename=Test Logs Wiki_Export_2026-07-24.zip" in response2.headers["content-disposition"]

    # Clean up dummy compiled dir
    if os.path.exists(compiled_dir):
        shutil.rmtree(compiled_dir)

    # 7. Delete the wiki pipeline
    response = client.delete(f"/api/wikis/{wiki_id}")
    assert response.status_code == 200


def test_logging_configuration():
    import logging
    from app.logging_config import setup_logging
    setup_logging()

    assert logging.getLogger("mwclient").level == logging.WARNING
    assert logging.getLogger("urllib3").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_stop_sync_api():
    from fastapi.testclient import TestClient
    from app.main import app, active_tasks
    import asyncio

    client = TestClient(app)

    # 1. Add temporary wiki
    payload = {
        "url": "https://test.stop.wiki",
        "name": "Test Stop Wiki"
    }
    response = client.post("/api/wikis", json=payload)
    assert response.status_code == 201
    wiki = response.json()
    wiki_id = wiki["id"]

    # 2. Call stop when there is no active task (database is Idle)
    response = client.post(f"/api/wikis/{wiki_id}/stop")
    assert response.status_code == 200
    assert "No active process" in response.json()["message"]

    # 3. Simulate database Syncing status, but no active python task reference
    from app.db import update_wiki_status
    asyncio.run(update_wiki_status(wiki_id, "Syncing"))

    response = client.post(f"/api/wikis/{wiki_id}/stop")
    assert response.status_code == 200
    assert "marked as Idle" in response.json()["message"]

    # 4. Simulate active asyncio.Task tracked using a Mock
    from unittest.mock import MagicMock
    task = MagicMock()
    task.done.return_value = False
    task.get_loop.return_value = None
    active_tasks[wiki_id] = task

    response = client.post(f"/api/wikis/{wiki_id}/stop")
    assert response.status_code == 200
    assert "successfully stopped" in response.json()["message"]
    task.cancel.assert_called_once()

    # Clean up wiki
    response = client.delete(f"/api/wikis/{wiki_id}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_pending_changes_and_watcher():
    from app.db import (
        add_wiki, get_wiki, update_wiki_pending_changes, update_wiki_sync_details, init_db
    )
    from app.main import check_all_wikis_for_changes
    from unittest.mock import AsyncMock, MagicMock, patch

    # Ensure DB is initialized
    await init_db()

    # 1. Create a wiki pipeline
    wiki = await add_wiki("https://test.watcher.wiki", "Test Watcher Wiki")
    wiki_id = wiki["id"]

    # has_pending_changes should be default False
    assert wiki["has_pending_changes"] is False

    # 2. Update to True manually
    await update_wiki_pending_changes(wiki_id, True)
    updated_wiki = await get_wiki(wiki_id)
    assert updated_wiki["has_pending_changes"] is True

    # 3. Complete sync should reset to False
    await update_wiki_sync_details(wiki_id, "2026-07-23T00:00:00Z", 5, "Idle")
    synced_wiki = await get_wiki(wiki_id)
    assert synced_wiki["has_pending_changes"] is False
    assert synced_wiki["last_sync_timestamp"] == "2026-07-23T00:00:00Z"
    assert synced_wiki["total_pages"] == 5

    # 4. Mock mwclient Site connection to test the background watcher
    mock_site = MagicMock()

    # Let's say there are NO changes initially
    mock_site.recentchanges.return_value = []

    with patch("app.main.connect_site", AsyncMock(return_value=mock_site)):
        # Run check_all_wikis_for_changes
        await check_all_wikis_for_changes()

        # Check that has_pending_changes is still False because there are no changes
        checked_wiki = await get_wiki(wiki_id)
        assert checked_wiki["has_pending_changes"] is False

        # Now, simulate a change returned by recentchanges
        mock_site.recentchanges.return_value = [{"title": "New Page", "type": "new"}]

        # Run check again
        await check_all_wikis_for_changes()

        # Now has_pending_changes should be True!
        checked_wiki_with_changes = await get_wiki(wiki_id)
        assert checked_wiki_with_changes["has_pending_changes"] is True

    # Clean up the wiki from db
    from app.db import delete_wiki
    await delete_wiki(wiki_id)


def test_status_endpoint():
    import datetime
    from app.main import app
    import app.main as app_main
    client = TestClient(app)

    # 1. Test when next_watcher_run is None
    app_main.next_watcher_run = None
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json() == {"next_watcher_run": None}

    # 2. Test when next_watcher_run is set
    test_time = datetime.datetime(2026, 7, 23, 12, 34, 56, tzinfo=datetime.timezone.utc)
    app_main.next_watcher_run = test_time
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json() == {"next_watcher_run": "2026-07-23T12:34:56+00:00"}

    # Clean up
    app_main.next_watcher_run = None


def test_downloaded_pages_and_total_pages():
    import os
    import shutil
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import update_wiki_total_pages
    import asyncio

    client = TestClient(app)

    # 1. Add a temporary wiki pipeline
    payload = {
        "url": "https://test.progress.wiki",
        "name": "Test Progress Wiki"
    }
    response = client.post("/api/wikis", json=payload)
    assert response.status_code == 201
    wiki = response.json()
    wiki_id = wiki["id"]

    # 2. Check that downloaded_pages is returned and initially 0
    response = client.get("/api/wikis")
    assert response.status_code == 200
    wikis = response.json()
    target_wiki = next(w for w in wikis if w["id"] == wiki_id)
    assert "downloaded_pages" in target_wiki
    assert target_wiki["downloaded_pages"] == 0

    # 3. Simulate adding raw pages and check downloaded_pages update
    raw_dir = f"/app/data/raw/{wiki_id}"
    os.makedirs(raw_dir, exist_ok=True)
    with open(os.path.join(raw_dir, "Page1.md"), "w", encoding="utf-8") as f:
        f.write("# Page 1")

    response = client.get("/api/wikis")
    assert response.status_code == 200
    wikis = response.json()
    target_wiki = next(w for w in wikis if w["id"] == wiki_id)
    assert target_wiki["downloaded_pages"] == 1

    # 4. Update total_pages using DB helper and check it is reflected
    asyncio.run(update_wiki_total_pages(wiki_id, 42))
    response = client.get("/api/wikis")
    assert response.status_code == 200
    wikis = response.json()
    target_wiki = next(w for w in wikis if w["id"] == wiki_id)
    assert target_wiki["total_pages"] == 42

    # Clean up
    if os.path.exists(raw_dir):
        shutil.rmtree(raw_dir)
    client.delete(f"/api/wikis/{wiki_id}")


def test_fetch_wiki_info():
    from unittest.mock import AsyncMock, MagicMock, patch
    client = TestClient(app)

    # Mock the site object returned by connect_site
    mock_site = MagicMock()
    mock_site.site = {"sitename": "Mocked Wikipedia"}

    with patch("app.main.connect_site", AsyncMock(return_value=mock_site)):
        response = client.post("/api/wikis/fetch-info", json={"url": "https://en.wikipedia.org"})
        assert response.status_code == 200
        assert response.json() == {"sitename": "Mocked Wikipedia"}

    # Test invalid URL formats
    response = client.post("/api/wikis/fetch-info", json={"url": "ftp://not-supported.org"})
    assert response.status_code == 400
    assert "URL must start with" in response.json()["detail"]

    response = client.post("/api/wikis/fetch-info", json={"url": "   "})
    assert response.status_code == 400
    assert "URL must not be empty" in response.json()["detail"]


@pytest.mark.asyncio
async def test_stop_sync_cancelled_error():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.main import api_stop_wiki, active_tasks
    import asyncio
    from app.db import add_wiki, delete_wiki

    wiki = await add_wiki("https://test.cancelled.wiki", "Test Cancelled Wiki")
    wiki_id = wiki["id"]

    mock_loop = MagicMock()

    # Mock task that raises CancelledError when awaited
    task = MagicMock()
    task.done.return_value = False
    task.get_loop.return_value = mock_loop
    task.__await__ = MagicMock()
    # To make `await task` raise CancelledError:
    async def raise_cancelled():
        raise asyncio.CancelledError()
    task.__await__.return_value = raise_cancelled().__await__()

    active_tasks[wiki_id] = task

    with patch("asyncio.get_running_loop", return_value=mock_loop):
        res = await api_stop_wiki(wiki_id)
        assert "successfully stopped" in res["message"]

    await delete_wiki(wiki_id)
