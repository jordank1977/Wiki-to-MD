// Global state to store the list of pipelines
let wikis = [];
let pollingInterval = null;
let globalLogsInterval = null;
let activeWikiLogId = null;
let wikiLogsInterval = null;
let nextWatcherRunTime = null;

// State to track if the name field has been manually edited by the user
let isNameManuallyEdited = false;

// Notification state
let notifications = [];
let unreadCount = 0;
let popupTimeout = null;
let drawerInactivityTimeout = null;

// On document load
document.addEventListener("DOMContentLoaded", () => {
    // Initial fetch
    fetchWikis();
    fetchStatus();

    // Setup Form submission
    const form = document.getElementById("add-wiki-form");
    form.addEventListener("submit", handleAddWiki);

    const urlInput = document.getElementById("wiki-url");
    const nameInput = document.getElementById("wiki-name");

    if (urlInput && nameInput) {
        // Track manual changes to the name input
        nameInput.addEventListener("input", () => {
            isNameManuallyEdited = nameInput.value.trim().length > 0;
        });

        // Trigger fetch sitename on blur or paste
        urlInput.addEventListener("blur", handleUrlFetchInfo);
        urlInput.addEventListener("paste", () => {
            // Wait for paste to complete
            setTimeout(handleUrlFetchInfo, 100);
        });
    }

    // Setup Notification Drawer auto-close and interaction handlers
    const drawer = document.getElementById("notification-drawer");
    if (drawer) {
        drawer.addEventListener("mouseenter", () => {
            clearDrawerInactivityTimer();
        });
        drawer.addEventListener("mouseleave", () => {
            startDrawerInactivityTimer();
        });
        drawer.addEventListener("click", (event) => {
            event.stopPropagation();
            clearDrawerInactivityTimer();
        });
    }

    document.addEventListener("click", () => {
        closeDrawer();
    });

    // Setup periodic polling every 3 seconds to update statuses
    pollingInterval = setInterval(() => {
        fetchWikis();
        fetchStatus();
    }, 3000);

    // Setup global log polling every 2 seconds
    fetchGlobalLogs();
    globalLogsInterval = setInterval(fetchGlobalLogs, 2000);

    // Setup live countdown timer ticking every 1 second
    setInterval(updateCountdownTimer, 1000);
});

// Fetch all wiki pipelines from the backend API
async function fetchWikis() {
    try {
        const response = await fetch("/api/wikis");
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        wikis = await response.json();
        renderWikis();
    } catch (error) {
        console.error("Failed to fetch wikis:", error);
    }
}

// Render the list of wiki pipelines in the UI as sleek horizontal tactical cards
function renderWikis() {
    const loadingState = document.getElementById("loading-state");
    const emptyState = document.getElementById("empty-state");
    const pipelinesList = document.getElementById("pipelines-list");

    // Hide loading state
    if (loadingState) loadingState.classList.add("hidden");

    if (wikis.length === 0) {
        if (emptyState) emptyState.classList.remove("hidden");
        if (pipelinesList) pipelinesList.innerHTML = "";
        return;
    }

    if (emptyState) emptyState.classList.add("hidden");

    // Clear and populate the card container
    pipelinesList.innerHTML = "";
    wikis.forEach(wiki => {
        // Status indicator styling (EVE Online style colors and glows)
        let statusBadgeClass = "";
        switch (wiki.status) {
            case "Idle":
                statusBadgeClass = "border-emerald-900/30 bg-emerald-950/10 text-emerald-500";
                break;
            case "Syncing":
                statusBadgeClass = "border-slate-700/40 bg-slate-800/10 text-slate-300 animate-pulse";
                break;
            case "Compiling":
                statusBadgeClass = "border-fuchsia-800/40 bg-fuchsia-950/10 text-fuchsia-400 animate-pulse";
                break;
            case "Error":
                statusBadgeClass = "border-rose-950 bg-rose-950/25 text-rose-500";
                break;
            case "Cancelling":
                statusBadgeClass = "border-amber-900 bg-amber-950/15 text-amber-500 animate-pulse";
                break;
            default:
                statusBadgeClass = "border-slate-850 bg-slate-950/20 text-slate-500";
        }

        // Format Sync dates (UTC)
        const formattedDate = wiki.last_sync_timestamp
            ? new Date(wiki.last_sync_timestamp).toLocaleString()
            : "Never Synced";

        const isBusy = wiki.status === "Syncing" || wiki.status === "Compiling";
        const isSyncing = wiki.status === "Syncing";

        // Calculate progress percentage for Syncing state
        let percent = 0;
        if (wiki.total_pages > 0) {
            percent = Math.min(100, Math.round((wiki.downloaded_pages / wiki.total_pages) * 100));
        }

        // Updates Available warning indicator
        const pendingBadge = wiki.has_pending_changes
            ? `<span class="inline-flex items-center space-x-1 border border-amber-900/60 bg-amber-950/10 text-amber-500 text-xs px-1.5 py-0.5 animate-pulse ml-1.5 font-mono-tech tracking-wide normal-case">
                <i class="fa-solid fa-triangle-exclamation text-amber-500"></i>
                <span>Pending Updates</span>
               </span>`
            : "";

        // Action buttons styling
        const syncBtnClass = wiki.has_pending_changes
            ? "eve-btn-amber"
            : "";

        const disableAttr = isBusy ? "disabled" : "";

        // Stop button - visible ONLY when status is "Syncing"
        const stopButton = isSyncing
            ? `<button onclick="stopSync(${wiki.id})" class="eve-btn eve-btn-rose text-xs px-2 py-1 flex items-center space-x-1 uppercase tracking-wide">
                    <i class="fa-solid fa-ban text-xs"></i>
                    <span>STOP</span>
               </button>`
            : "";

        const card = document.createElement("div");
        card.className = "eve-window p-3 shadow-none transition-all duration-150";

        card.innerHTML = `
            <div class="grid grid-cols-1 lg:grid-cols-12 gap-3 items-center">

                <!-- Column 1: TARGET INFO & SYNC STATUS (Cols: 4) -->
                <div class="lg:col-span-4 min-w-0">
                    <div class="flex items-center space-x-2 mb-0.5">
                        <span class="relative flex h-1.5 w-1.5">
                            <span class="animate-ping absolute inline-flex h-full w-full opacity-75 ${wiki.status === 'Syncing' ? 'bg-slate-400' : (wiki.has_pending_changes ? 'bg-amber-500' : 'bg-emerald-500')}"></span>
                            <span class="relative inline-flex h-1.5 w-1.5 ${wiki.status === 'Syncing' ? 'bg-slate-400' : (wiki.has_pending_changes ? 'bg-amber-500' : 'bg-emerald-500')}"></span>
                        </span>
                        <span class="text-sm font-bold tracking-wide text-slate-300 normal-case truncate font-mono-tech flex items-center">
                            ${wiki.name}
                            ${pendingBadge}
                        </span>
                    </div>
                    <div class="text-xs text-slate-500 font-mono-tech truncate normal-case mb-0.5">
                        Addr: <span class="text-slate-400 hover:text-slate-300 select-all normal-case">${wiki.url}</span>
                    </div>
                    <div class="text-xs text-slate-500 font-mono-tech normal-case">
                        Last Sync: <span class="text-slate-400 normal-case">${formattedDate}</span>
                    </div>
                </div>

                <!-- Column 2: DATA METRICS (Cols: 4) -->
                <div class="lg:col-span-4 flex flex-col justify-center">
                    <!-- Metrics readouts and status badge side-by-side -->
                    <div class="flex items-center justify-between gap-2">
                        <div class="flex space-x-3 font-mono-tech text-xs tracking-wide text-slate-500">
                            <div>
                                <div class="text-xs text-slate-600 normal-case">Raw Pages</div>
                                <div class="text-sm font-bold text-slate-300 leading-none">${wiki.total_pages}</div>
                            </div>
                            <div class="border-l border-slate-800 pl-3.5">
                                <div class="text-xs text-slate-600 normal-case">Bundles</div>
                                <div class="text-sm font-bold text-fuchsia-500 leading-none">${wiki.compiled_bundles_count}</div>
                            </div>
                        </div>

                        <!-- Status Badge -->
                        <span class="inline-flex items-center px-2 py-0.5 text-xs font-bold font-mono-tech tracking-wide border uppercase ${statusBadgeClass}">
                            ${wiki.status}
                        </span>
                    </div>

                    <!-- Progress Bar container (Reserved space: uses invisible when not syncing to avoid layout shift) -->
                    <div class="h-5 mt-1 flex items-center ${isSyncing ? '' : 'invisible'}" style="min-height: 20px;">
                        <div class="w-full flex items-center space-x-1.5">
                            <div class="flex-1 capacitor-bar">
                                <div class="capacitor-bar-fill" style="width: ${percent}%"></div>
                            </div>
                            <span class="text-xs font-mono-tech text-slate-400 whitespace-nowrap">${wiki.downloaded_pages}/${wiki.total_pages} [${percent}%]</span>
                        </div>
                    </div>
                </div>

                <!-- Column 3: COMMAND STACK (Cols: 4) -->
                <div class="lg:col-span-4 flex items-center justify-end gap-1 flex-wrap">
                    <button onclick="triggerSync(${wiki.id})" ${disableAttr}
                        class="eve-btn text-xs px-2 py-1 flex items-center space-x-1 uppercase tracking-wide ${syncBtnClass}"
                        title="Start sync">
                        <i class="fa-solid fa-circle-play text-xs"></i>
                        <span>SYNC</span>
                    </button>
                    <button onclick="triggerRebuild(${wiki.id})" ${disableAttr}
                        class="eve-btn eve-btn-fuchsia text-xs px-2 py-1 flex items-center space-x-1 uppercase tracking-wide"
                        title="Rebuild bundles">
                        <i class="fa-solid fa-cubes text-xs"></i>
                        <span>REBUILD</span>
                    </button>
                    ${stopButton}
                    <button onclick="openLogsModal(${wiki.id}, '${wiki.name.replace(/'/g, "\\'")}')"
                        class="eve-btn text-xs px-2 py-1 flex items-center space-x-1 uppercase tracking-wide"
                        title="Open log viewer">
                        <i class="fa-solid fa-terminal text-xs"></i>
                        <span>LOGS</span>
                    </button>
                    <button onclick="downloadBundles(${wiki.id})" ${wiki.compiled_bundles_count === 0 ? "disabled" : ""}
                        class="eve-btn eve-btn-emerald text-xs px-2 py-1 flex items-center space-x-1 uppercase tracking-wide"
                        title="Download compiled bundles as ZIP">
                        <i class="fa-solid fa-file-arrow-down text-xs"></i>
                        <span>DOWNLOAD</span>
                    </button>
                    <button onclick="deletePipeline(${wiki.id})" ${disableAttr}
                        class="eve-btn eve-btn-rose text-xs px-1.5 py-1 uppercase tracking-wide"
                        title="Delete pipeline">
                        <i class="fa-solid fa-trash-can text-xs"></i>
                    </button>
                </div>

            </div>
        `;

        pipelinesList.appendChild(card);
    });
}

// Automatically fetch wiki sitename when URL is provided
async function handleUrlFetchInfo() {
    const urlInput = document.getElementById("wiki-url");
    const nameInput = document.getElementById("wiki-name");
    if (!urlInput || !nameInput) return;

    const url = urlInput.value.trim();
    if (!url || !url.startsWith("http://") && !url.startsWith("https://")) {
        return; // Only fetch if we have a valid prefix
    }

    // Only populate if Name has not been manually edited by the user OR is currently empty
    if (isNameManuallyEdited && nameInput.value.trim().length > 0) {
        return;
    }

    try {
        // Show subtle status or placeholder
        if (!nameInput.value) {
            nameInput.placeholder = "Fetching sitename...";
        }

        const response = await fetch("/api/wikis/fetch-info", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ url })
        });

        if (response.ok) {
            const data = await response.json();
            if (data.sitename && (!isNameManuallyEdited || !nameInput.value.trim())) {
                nameInput.value = data.sitename;
                // Since it's auto-populated, we don't count it as a manual edit unless the user changes it
            }
        }
    } catch (error) {
        console.error("Error fetching wiki sitename:", error);
    } finally {
        nameInput.placeholder = "e.g., Wiki Name";
    }
}

// Handle Add Wiki pipeline form submission
async function handleAddWiki(event) {
    event.preventDefault();

    const nameInput = document.getElementById("wiki-name");
    const urlInput = document.getElementById("wiki-url");

    const payload = {
        name: nameInput.value.trim(),
        url: urlInput.value.trim()
    };

    try {
        const response = await fetch("/api/wikis", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (response.ok) {
            showAlert("success", `Wiki pipeline "${payload.name}" successfully created.`);
            nameInput.value = "";
            urlInput.value = "";
            isNameManuallyEdited = false; // Reset tracking
            fetchWikis();
        } else {
            showAlert("error", data.detail || "Failed to create wiki pipeline.");
        }
    } catch (error) {
        console.error("Error creating wiki pipeline:", error);
        showAlert("error", "An unexpected error occurred.");
    }
}

// Trigger Incremental Sync for a specific wiki
async function triggerSync(wikiId) {
    try {
        const response = await fetch(`/api/wikis/${wikiId}/sync`, {
            method: "POST"
        });
        const data = await response.json();

        if (response.ok) {
            showAlert("success", "Sync process initiated successfully.");
            fetchWikis();
        } else {
            showAlert("error", data.message || data.detail || "Failed to trigger sync.");
        }
    } catch (error) {
        console.error("Error triggering sync:", error);
        showAlert("error", "An unexpected sync error occurred.");
    }
}

// Trigger Manual Bundle Rebuild for a specific wiki
async function triggerRebuild(wikiId) {
    try {
        const response = await fetch(`/api/wikis/${wikiId}/rebuild`, {
            method: "POST"
        });
        const data = await response.json();

        if (response.ok) {
            showAlert("success", "Bundle compilation initiated.");
            fetchWikis();
        } else {
            showAlert("error", data.message || data.detail || "Failed to trigger rebuild.");
        }
    } catch (error) {
        console.error("Error triggering rebuild:", error);
        showAlert("error", "An unexpected compilation error occurred.");
    }
}

// Delete a wiki pipeline
async function deletePipeline(wikiId) {
    const wiki = wikis.find(w => w.id === wikiId);
    if (!wiki) return;

    const confirmed = confirm(`Are you sure you want to delete "${wiki.name}"?\nAll saved data will be permanently deleted.`);
    if (!confirmed) return;

    try {
        const response = await fetch(`/api/wikis/${wikiId}`, {
            method: "DELETE"
        });
        const data = await response.json();

        if (response.ok) {
            showAlert("success", `Pipeline "${wiki.name}" and all associated data have been deleted.`);
            fetchWikis();
        } else {
            showAlert("error", data.detail || "Failed to delete pipeline.");
        }
    } catch (error) {
        console.error("Error deleting pipeline:", error);
        showAlert("error", "An unexpected error occurred while deleting the pipeline.");
    }
}

// Utility to display alert pop-up and record notification
function showAlert(type, message) {
    // Add to notification history list
    const notification = {
        id: Date.now() + Math.random().toString(36).substr(2, 5),
        type,
        message,
        timestamp: new Date()
    };
    notifications.unshift(notification); // Newest first

    const drawer = document.getElementById("notification-drawer");
    const isDrawerOpen = drawer && !drawer.classList.contains("hidden");

    if (!isDrawerOpen) {
        unreadCount++;
        updateNotificationBadge();
    }

    renderNotificationList();

    // Setup and trigger the popup alert
    const popup = document.getElementById("notification-popup");
    const popupIcon = document.getElementById("popup-icon");
    const popupMessage = document.getElementById("popup-message");

    if (popup && popupIcon && popupMessage) {
        popupMessage.innerText = message;

        // Reset class lists
        popup.className = "p-2.5 bg-slate-950/95 border flex items-start space-x-2 backdrop-blur-md shadow-lg pointer-events-auto transition-all duration-300 w-72 sm:w-80";

        if (type === "success") {
            popup.classList.add("border-emerald-900/50");
            popupIcon.className = "text-emerald-500 text-sm mt-0.5";
            popupIcon.innerHTML = '<i class="fa-solid fa-circle-check"></i>';
        } else if (type === "error") {
            popup.classList.add("border-rose-950");
            popupIcon.className = "text-rose-500 text-sm mt-0.5";
            popupIcon.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i>';
        } else {
            popup.classList.add("border-slate-800");
            popupIcon.className = "text-slate-400 text-sm mt-0.5";
            popupIcon.innerHTML = '<i class="fa-solid fa-circle-info"></i>';
        }

        popup.classList.remove("hidden");

        // Clear existing popup timeout if active
        if (popupTimeout) {
            clearTimeout(popupTimeout);
        }

        // Auto-dismiss pop-up after 5 seconds
        popupTimeout = setTimeout(closePopup, 5000);
    }
}

// Dismiss popup alert
function closePopup() {
    const popup = document.getElementById("notification-popup");
    if (popup) {
        popup.classList.add("hidden");
    }
    if (popupTimeout) {
        clearTimeout(popupTimeout);
        popupTimeout = null;
    }
}

// Update the badge count indicator
function updateNotificationBadge() {
    const badge = document.getElementById("notification-badge");
    if (badge) {
        if (unreadCount > 0) {
            badge.innerText = unreadCount;
            badge.classList.remove("hidden");
        } else {
            badge.classList.add("hidden");
        }
    }
}

// Render the notifications history inside the drawer
function renderNotificationList() {
    const list = document.getElementById("notification-list");
    if (!list) return;

    if (notifications.length === 0) {
        list.innerHTML = `<div class="text-slate-600 text-center py-4">No recent messages.</div>`;
        return;
    }

    list.innerHTML = "";
    notifications.forEach(notif => {
        let borderClass = "border-slate-800/40";
        let iconHtml = '<i class="fa-solid fa-circle-info text-slate-400"></i>';

        if (notif.type === "success") {
            borderClass = "border-emerald-900/30 bg-emerald-950/5";
            iconHtml = '<i class="fa-solid fa-circle-check text-emerald-500"></i>';
        } else if (notif.type === "error") {
            borderClass = "border-rose-950 bg-rose-950/5";
            iconHtml = '<i class="fa-solid fa-circle-exclamation text-rose-500"></i>';
        }

        const timeStr = notif.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

        const item = document.createElement("div");
        item.className = `p-2 bg-slate-950 border ${borderClass} flex items-start space-x-2`;
        item.innerHTML = `
            <div class="text-xs mt-0.5">${iconHtml}</div>
            <div class="flex-1 min-w-0">
                <p class="text-slate-300 leading-normal break-words">${notif.message}</p>
                <span class="text-[10px] text-slate-600 font-mono-tech mt-0.5 block">${timeStr}</span>
            </div>
        `;
        list.appendChild(item);
    });
}

// Toggle notification drawer visibility
function toggleDrawer(event) {
    if (event) {
        event.stopPropagation();
    }
    const drawer = document.getElementById("notification-drawer");
    if (!drawer) return;

    const isOpen = !drawer.classList.contains("hidden");

    if (isOpen) {
        closeDrawer();
    } else {
        // Open drawer
        drawer.classList.remove("hidden");
        unreadCount = 0;
        updateNotificationBadge();
        startDrawerInactivityTimer();
    }
}

// Close notification drawer
function closeDrawer() {
    const drawer = document.getElementById("notification-drawer");
    if (drawer && !drawer.classList.contains("hidden")) {
        drawer.classList.add("hidden");
    }
    clearDrawerInactivityTimer();
}

// Start 5-second inactivity auto-close timer
function startDrawerInactivityTimer() {
    clearDrawerInactivityTimer();
    drawerInactivityTimeout = setTimeout(() => {
        closeDrawer();
    }, 5000);
}

// Clear inactivity auto-close timer
function clearDrawerInactivityTimer() {
    if (drawerInactivityTimeout) {
        clearTimeout(drawerInactivityTimeout);
        drawerInactivityTimeout = null;
    }
}

// Clear all notifications
function clearNotifications() {
    notifications = [];
    unreadCount = 0;
    updateNotificationBadge();
    renderNotificationList();
}

// Global log functions
async function fetchGlobalLogs() {
    try {
        const response = await fetch("/api/logs/global");
        if (!response.ok) return;
        const data = await response.json();
        const pre = document.getElementById("global-log-content");
        if (!pre) return;

        const autoScrollCheck = document.getElementById("global-auto-scroll");
        const autoScroll = autoScrollCheck ? autoScrollCheck.checked : true;
        pre.textContent = data.logs || "System Logs: Stream empty.";

        if (autoScroll) {
            pre.scrollTop = pre.scrollHeight;
        }
    } catch (err) {
        console.error("Failed to fetch global logs:", err);
    }
}

function clearGlobalLogs() {
    const pre = document.getElementById("global-log-content");
    if (pre) pre.textContent = "";
}

// Wiki-specific logs modal functions
function openLogsModal(wikiId, wikiName) {
    activeWikiLogId = wikiId;
    const modalWikiElem = document.getElementById("modal-wiki-name");
    if (modalWikiElem) modalWikiElem.innerText = wikiName;

    const modal = document.getElementById("logs-modal");
    if (modal) modal.classList.remove("hidden");

    fetchWikiLogs();
    if (wikiLogsInterval) clearInterval(wikiLogsInterval);
    wikiLogsInterval = setInterval(fetchWikiLogs, 2000);
}

// Close Wiki-specific logs modal
function closeLogsModal() {
    const modal = document.getElementById("logs-modal");
    if (modal) modal.classList.add("hidden");

    if (wikiLogsInterval) {
        clearInterval(wikiLogsInterval);
        wikiLogsInterval = null;
    }
    activeWikiLogId = null;
}

async function fetchWikiLogs() {
    if (!activeWikiLogId) return;
    try {
        const response = await fetch(`/api/wikis/${activeWikiLogId}/logs`);
        if (!response.ok) return;
        const data = await response.json();
        const pre = document.getElementById("modal-log-content");
        if (!pre) return;

        const autoScrollCheck = document.getElementById("modal-auto-scroll");
        const autoScroll = autoScrollCheck ? autoScrollCheck.checked : true;
        pre.textContent = data.logs || "Logs: No output generated yet.";

        if (autoScroll) {
            pre.scrollTop = pre.scrollHeight;
        }
    } catch (err) {
        console.error("Failed to fetch wiki logs:", err);
    }
}

function clearModalLogs() {
    const pre = document.getElementById("modal-log-content");
    if (pre) pre.textContent = "";
}

// Download bundles zip function
function downloadBundles(wikiId) {
    window.location.href = `/api/wikis/${wikiId}/download`;
}

// Copy content helper with clipboard API and textarea fallback
async function copyToClipboard(text, buttonElement) {
    if (!text) return;
    let success = false;
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            success = true;
        }
    } catch (err) {
        console.warn("navigator.clipboard failed, trying fallback...", err);
    }

    if (!success) {
        // Fallback approach
        try {
            const textarea = document.createElement("textarea");
            textarea.value = text;
            textarea.style.top = "0";
            textarea.style.left = "0";
            textarea.style.position = "fixed";
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            success = document.execCommand("copy");
            document.body.removeChild(textarea);
        } catch (err) {
            console.error("Fallback copy failed:", err);
        }
    }

    if (success) {
        // Visual feedback
        const originalText = buttonElement.innerHTML;
        buttonElement.innerHTML = `<i class="fa-solid fa-check"></i> <span>COPIED!</span>`;
        buttonElement.disabled = true;
        setTimeout(() => {
            buttonElement.innerHTML = originalText;
            buttonElement.disabled = false;
        }, 2000);
    } else {
        alert("FAILED TO COPY STREAM.");
    }
}

function copyGlobalLogs() {
    const pre = document.getElementById("global-log-content");
    const btn = document.getElementById("copy-global-btn");
    if (pre && btn) {
        copyToClipboard(pre.textContent, btn);
    }
}

function copyModalLogs() {
    const pre = document.getElementById("modal-log-content");
    const btn = document.getElementById("copy-modal-btn");
    if (pre && btn) {
        copyToClipboard(pre.textContent, btn);
    }
}

// Stop ongoing process for a specific wiki
async function stopSync(wikiId) {
    try {
        const response = await fetch(`/api/wikis/${wikiId}/stop`, {
            method: "POST"
        });
        let data = {};
        try {
            data = await response.json();
        } catch (e) {
            console.warn("Could not parse stop response as JSON:", e);
        }

        if (response.ok) {
            showAlert("success", "Sync process stopped.");
            fetchWikis();
        } else {
            // Gracefully handle cancellation status or messages without showing generic "Unknown Error"
            const errorMsg = data.message || data.detail || "Sync successfully stopped.";
            showAlert("success", errorMsg);
            fetchWikis();
        }
    } catch (error) {
        console.error("Error stopping process:", error);
        // Handle gracefully by letting the user know the stop action was sent
        showAlert("success", "Sync process stopped.");
        fetchWikis();
    }
}

// Fetch status of background watcher next run
async function fetchStatus() {
    try {
        const response = await fetch("/api/status");
        if (response.ok) {
            const data = await response.json();
            if (data.next_watcher_run) {
                nextWatcherRunTime = new Date(data.next_watcher_run);
                const container = document.getElementById("watcher-countdown");
                if (container) {
                    container.classList.remove("hidden");
                }
            } else {
                nextWatcherRunTime = null;
                const container = document.getElementById("watcher-countdown");
                if (container) {
                    container.classList.add("hidden");
                }
            }
        }
    } catch (error) {
        console.error("Failed to fetch status:", error);
    }
}

// Update countdown timer displayed on UI
function updateCountdownTimer() {
    const timerElem = document.getElementById("countdown-timer");
    if (!timerElem) return;

    if (!nextWatcherRunTime) {
        timerElem.textContent = "--M --S";
        return;
    }

    const now = new Date();
    const diffMs = nextWatcherRunTime - now;
    if (diffMs <= 0) {
        timerElem.textContent = "COMMENCING...";
        return;
    }

    const totalSeconds = Math.floor(diffMs / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;

    timerElem.textContent = `${minutes}M ${seconds}S`;
}
