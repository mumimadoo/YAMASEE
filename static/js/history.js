/**
 * YAMASEE History UI Logic - Phase 7 Workspace Management
 * Secure, DOM-sanitized history viewer with search, filter, sort, pin/unpin, rename, retry, and delete functionality.
 */
document.addEventListener("DOMContentLoaded", () => {
    let currentPage = 1;
    const pageSize = 12;
    let pendingDeleteId = null;
    let searchDebounceTimer = null;

    // Filter Control Elements
    const searchInput = document.getElementById("searchInput");
    const statusFilter = document.getElementById("statusFilter");
    const sourceTypeFilter = document.getElementById("sourceTypeFilter");
    const sortSelect = document.getElementById("sortSelect");
    const pinnedOnlyToggle = document.getElementById("pinnedOnlyToggle");
    const resetFiltersBtn = document.getElementById("resetFiltersBtn");

    // Main UI State Elements
    const loadingState = document.getElementById("loadingState");
    const errorState = document.getElementById("errorState");
    const errorTitle = document.getElementById("errorTitle");
    const errorMessage = document.getElementById("errorMessage");
    const emptyState = document.getElementById("emptyState");
    const historyGrid = document.getElementById("historyGrid");
    const paginationNav = document.getElementById("paginationNav");
    const prevPageBtn = document.getElementById("prevPageBtn");
    const nextPageBtn = document.getElementById("nextPageBtn");
    const pageInfo = document.getElementById("pageInfo");
    const retryBtn = document.getElementById("retryBtn");
    const logoutBtn = document.getElementById("logoutBtn");
    const statusAlert = document.getElementById("statusAlert");

    // Modal Elements
    const detailModal = document.getElementById("detailModal");
    const closeModalBtn = document.getElementById("closeModalBtn");
    const modalCloseBtn = document.getElementById("modalCloseBtn");
    const modalLoading = document.getElementById("modalLoading");
    const modalBody = document.getElementById("modalBody");
    const downloadTxtBtn = document.getElementById("downloadTxtBtn");
    const downloadPdfBtn = document.getElementById("downloadPdfBtn");

    // Delete Modal Elements
    const deleteConfirmModal = document.getElementById("deleteConfirmModal");
    const closeDeleteModalBtn = document.getElementById("closeDeleteModalBtn");
    const cancelDeleteBtn = document.getElementById("cancelDeleteBtn");
    const confirmDeleteBtn = document.getElementById("confirmDeleteBtn");



    // Logout Handler
    if (logoutBtn) {
        logoutBtn.addEventListener("click", async () => {
            try {
                await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
                window.location.href = "/login";
            } catch (err) {
                window.location.href = "/login";
            }
        });
    }

    // Retry Button (Error State)
    if (retryBtn) {
        retryBtn.addEventListener("click", () => fetchHistory(currentPage));
    }

    // Pagination Click Listeners
    if (prevPageBtn) {
        prevPageBtn.addEventListener("click", () => {
            if (currentPage > 1) fetchHistory(currentPage - 1);
        });
    }
    if (nextPageBtn) {
        nextPageBtn.addEventListener("click", () => fetchHistory(currentPage + 1));
    }

    // Filter Change Listeners
    if (searchInput) {
        searchInput.addEventListener("input", () => {
            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(() => fetchHistory(1), 300);
        });
    }
    if (statusFilter) statusFilter.addEventListener("change", () => fetchHistory(1));
    if (sourceTypeFilter) sourceTypeFilter.addEventListener("change", () => fetchHistory(1));
    if (sortSelect) sortSelect.addEventListener("change", () => fetchHistory(1));
    if (pinnedOnlyToggle) pinnedOnlyToggle.addEventListener("change", () => fetchHistory(1));
    if (resetFiltersBtn) {
        resetFiltersBtn.addEventListener("click", () => {
            if (searchInput) searchInput.value = "";
            if (statusFilter) statusFilter.value = "";
            if (sourceTypeFilter) sourceTypeFilter.value = "";
            if (sortSelect) sortSelect.value = "newest";
            if (pinnedOnlyToggle) pinnedOnlyToggle.checked = false;
            fetchHistory(1);
        });
    }

    // Modal Close Listeners
    if (closeModalBtn) closeModalBtn.addEventListener("click", hideDetailModal);
    if (modalCloseBtn) modalCloseBtn.addEventListener("click", hideDetailModal);
    if (closeDeleteModalBtn) closeDeleteModalBtn.addEventListener("click", hideDeleteModal);
    if (cancelDeleteBtn) cancelDeleteBtn.addEventListener("click", hideDeleteModal);

    // Escape Key Close Modals
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            hideDetailModal();
            hideDeleteModal();
        }
    });

    // Confirm Delete Handler
    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener("click", async () => {
            if (!pendingDeleteId) return;
            confirmDeleteBtn.disabled = true;
            confirmDeleteBtn.textContent = "กำลังลบ...";

            try {
                const res = await fetch(`/api/history/${pendingDeleteId}`, {
                    method: "DELETE",
                    credentials: "same-origin"
                });

                if (res.status === 401) {
                    window.location.href = "/login";
                    return;
                }
                if (res.status === 403) {
                    showAlert("ไม่ได้รับอนุญาตให้ทำรายการนี้ (Cross-origin forbidden)", "error");
                    hideDeleteModal();
                    return;
                }
                if (res.status === 404) {
                    showAlert("ไม่พบรายการดังกล่าว หรือรายการถูกลบไปแล้ว", "error");
                    hideDeleteModal();
                    fetchHistory(currentPage);
                    return;
                }

                if (res.ok) {
                    showAlert("ลบรายการประวัติสำเร็จเรียบร้อยแล้ว", "success");
                    hideDeleteModal();
                    fetchHistory(currentPage);
                } else {
                    showAlert("เกิดข้อผิดพลาดในการลบรายการ", "error");
                    hideDeleteModal();
                }
            } catch (err) {
                showAlert("เกิดข้อผิดพลาดในการเชื่อมต่อกับเซิร์ฟเวอร์", "error");
                hideDeleteModal();
            } finally {
                confirmDeleteBtn.disabled = false;
                confirmDeleteBtn.textContent = "ลบรายการ";
            }
        });
    }

    // Read initial filters from URL params if present
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has("page")) currentPage = parseInt(urlParams.get("page")) || 1;
    if (urlParams.has("search") && searchInput) searchInput.value = urlParams.get("search");
    if (urlParams.has("status") && statusFilter) statusFilter.value = urlParams.get("status");
    if (urlParams.has("source_type") && sourceTypeFilter) sourceTypeFilter.value = urlParams.get("source_type");
    if (urlParams.has("sort") && sortSelect) sortSelect.value = urlParams.get("sort");
    if (urlParams.has("pinned") && pinnedOnlyToggle) pinnedOnlyToggle.checked = urlParams.get("pinned") === "true";

    // Initial Fetch
    fetchHistory(currentPage);

    /**
     * Fetches paginated history from API with search, filter, and sort.
     */
    async function fetchHistory(page) {
        showState("loading");

        const queryObj = new URLSearchParams();
        queryObj.set("page", page);
        queryObj.set("page_size", pageSize);

        if (searchInput && searchInput.value.trim()) queryObj.set("search", searchInput.value.trim());
        if (statusFilter && statusFilter.value) queryObj.set("status", statusFilter.value);
        if (sourceTypeFilter && sourceTypeFilter.value) queryObj.set("source_type", sourceTypeFilter.value);
        if (sortSelect && sortSelect.value) queryObj.set("sort", sortSelect.value);
        if (pinnedOnlyToggle && pinnedOnlyToggle.checked) queryObj.set("pinned", "true");

        // Update URL state without full page reload
        window.history.replaceState(null, "", `${window.location.pathname}?${queryObj.toString()}`);

        try {
            const res = await fetch(`/api/history?${queryObj.toString()}`, {
                method: "GET",
                credentials: "same-origin"
            });

            if (res.status === 401) {
                window.location.href = "/login";
                return;
            }

            if (!res.ok) {
                showErrorState("เกิดข้อผิดพลาดในการเชื่อมต่อ", `ไม่สามารถดึงข้อมูลประวัติได้ (HTTP ${res.status})`);
                return;
            }

            const data = await res.json();
            currentPage = data.page;

            if (!data.items || data.items.length === 0) {
                showState("empty");
                return;
            }

            renderHistoryGrid(data.items);
            renderPagination(data);
            showState("grid");
        } catch (err) {
            showErrorState("เกิดข้อผิดพลาดระบบ", "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้ กรุณาตรวจสอบการเชื่อมต่อ");
        }
    }

    /**
     * Renders history items using safe DOM element creation (NO innerHTML for user strings).
     */
    function renderHistoryGrid(items) {
        historyGrid.textContent = "";

        items.forEach((item) => {
            const card = document.createElement("div");
            card.className = "history-card" + (item.is_pinned ? " is-pinned" : "");
            card.setAttribute("data-analysis-id", item.public_id);

            // Card Header
            const cardHeader = document.createElement("div");
            cardHeader.className = "card-header";

            const title = document.createElement("h3");
            title.className = "card-title";
            title.textContent = item.display_title || "การวิเคราะห์สื่อ";

            // Pin Button
            const pinBtn = document.createElement("button");
            pinBtn.type = "button";
            pinBtn.className = "btn-icon btn-pin" + (item.is_pinned ? " pinned" : "");
            pinBtn.setAttribute("aria-label", item.is_pinned ? "Unpin history item" : "Pin history item");
            pinBtn.textContent = item.is_pinned ? "📌" : "📍";
            pinBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                togglePinHistory(item.public_id, !item.is_pinned);
            });

            const badge = document.createElement("span");
            const srcType = (item.source_type || "media").toLowerCase();
            let label = "Media";
            if (srcType === "youtube") {
                label = "YouTube";
            } else if (srcType === "tiktok" || srcType === "tiktok_url" || srcType === "external_tiktok") {
                label = "TikTok";
            } else if (srcType === "upload" || srcType === "mp4" || srcType === "file") {
                label = "Upload";
            }
            const cleanTypeClass = srcType === "tiktok" || srcType === "tiktok_url" || srcType === "external_tiktok" ? "tiktok" : (srcType === "youtube" ? "youtube" : "upload");
            badge.className = `badge badge-${cleanTypeClass}`;
            badge.textContent = label;

            cardHeader.appendChild(pinBtn);
            cardHeader.appendChild(title);
            cardHeader.appendChild(badge);

            // Card Meta
            const cardMeta = document.createElement("div");
            cardMeta.className = "card-meta";

            const dateSpan = document.createElement("span");
            dateSpan.textContent = `📅 ${formatDate(item.created_at)}`;

            const durationSpan = document.createElement("span");
            durationSpan.textContent = `⏱️ ${formatDuration(item.duration_seconds)}`;

            const statusSpan = document.createElement("span");
            statusSpan.className = `badge badge-${item.status}`;
            statusSpan.textContent = item.status === "completed" ? "สมบูรณ์" : item.status;

            cardMeta.appendChild(dateSpan);
            cardMeta.appendChild(durationSpan);
            cardMeta.appendChild(statusSpan);

            // Card Actions
            const cardActions = document.createElement("div");
            cardActions.className = "card-actions";

            const detailBtn = document.createElement("button");
            detailBtn.type = "button";
            detailBtn.className = "btn-card btn-detail";
            detailBtn.setAttribute("data-analysis-id", item.public_id);
            if (item.status === "completed") {
                detailBtn.textContent = "เปิดผลวิเคราะห์";
                detailBtn.addEventListener("click", (e) => {
                    console.log("[RESTORE] history button clicked");
                    const btn = e.currentTarget || detailBtn;
                    const analysisId = btn.getAttribute("data-analysis-id");
                    console.log("[RESTORE] analysis id from card: " + analysisId);
                    
                    const targetUrl = `/dashboard?analysis_id=${analysisId}`;
                    console.log("[RESTORE] navigating to: " + targetUrl);
                    restoreAnalysisFromHistory(analysisId);
                });
            } else {
                detailBtn.textContent = "ดูรายละเอียด";
                detailBtn.addEventListener("click", (e) => {
                    const btn = e.currentTarget || detailBtn;
                    const analysisId = btn.getAttribute("data-analysis-id");
                    openDetailModal(analysisId);
                });
            }

            const renameBtn = document.createElement("button");
            renameBtn.type = "button";
            renameBtn.className = "btn-card btn-rename";
            renameBtn.textContent = "เปลี่ยนชื่อ";
            renameBtn.addEventListener("click", () => promptRenameHistory(item.public_id, item.display_title));

            cardActions.appendChild(detailBtn);
            cardActions.appendChild(renameBtn);

            // Retry Button for failed URL jobs
            if (item.can_retry) {
                const retryItemBtn = document.createElement("button");
                retryItemBtn.type = "button";
                retryItemBtn.className = "btn-card btn-retry";
                retryItemBtn.textContent = "ลองใหม่";
                retryItemBtn.addEventListener("click", () => retryHistoryItem(item.public_id));
                cardActions.appendChild(retryItemBtn);
            }

            const deleteBtn = document.createElement("button");
            deleteBtn.type = "button";
            deleteBtn.className = "btn-card btn-delete";
            deleteBtn.textContent = "ลบ";
            deleteBtn.addEventListener("click", () => openDeleteModal(item.public_id));
            cardActions.appendChild(deleteBtn);

            card.appendChild(cardHeader);
            card.appendChild(cardMeta);
            card.appendChild(cardActions);

            historyGrid.appendChild(card);
        });
    }

    /**
     * Toggles pin status for a history item.
     */
    async function togglePinHistory(publicId, newPinStatus) {
        try {
            const res = await fetch(`/api/history/${publicId}/pin`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ is_pinned: newPinStatus }),
                credentials: "same-origin"
            });
            if (res.ok) {
                showAlert(newPinStatus ? "ปักหมุดรายการเรียบร้อย" : "ยกเลิกการปักหมุดเรียบร้อย", "success");
                fetchHistory(currentPage);
            } else {
                showAlert("เกิดข้อผิดพลาดในการเปลี่ยนสถานะการปักหมุด", "error");
            }
        } catch (err) {
            showAlert("ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้", "error");
        }
    }

    /**
     * Prompts rename dialog and updates title.
     */
    async function promptRenameHistory(publicId, currentTitle) {
        const newTitle = prompt("กรุณาระบุชื่อรายการวิเคราะห์ใหม่:", currentTitle || "");
        if (newTitle === null) return; // User cancelled
        const cleanTitle = newTitle.trim();
        if (!cleanTitle) {
            showAlert("ชื่อรายการวิเคราะห์ต้องไม่เป็นค่าว่าง", "error");
            return;
        }
        if (cleanTitle.length > 200) {
            showAlert("ชื่อรายการวิเคราะห์ต้องไม่เกิน 200 ตัวอักษร", "error");
            return;
        }

        try {
            const res = await fetch(`/api/history/${publicId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ display_title: cleanTitle }),
                credentials: "same-origin"
            });
            if (res.ok) {
                showAlert("เปลี่ยนชื่อรายการเรียบร้อยแล้ว", "success");
                fetchHistory(currentPage);
            } else {
                showAlert("เกิดข้อผิดพลาดในการเปลี่ยนชื่อรายการ", "error");
            }
        } catch (err) {
            showAlert("ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้", "error");
        }
    }

    /**
     * Retries a failed history item.
     */
    async function retryHistoryItem(publicId) {
        try {
            const res = await fetch(`/api/history/${publicId}/retry`, {
                method: "POST",
                credentials: "same-origin"
            });
            if (res.ok) {
                showAlert("ส่งงานลองใหม่อีกครั้งเรียบร้อยแล้ว", "success");
                window.location.href = "/dashboard";
            } else {
                const errData = await res.json().catch(() => ({}));
                showAlert(errData.detail || "เกิดข้อผิดพลาดในการส่งงานลองใหม่", "error");
            }
        } catch (err) {
            showAlert("ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้", "error");
        }
    }

    /**
     * Updates pagination state.
     */
    function renderPagination(data) {
        const pages = data.pagination ? data.pagination.total_pages : data.total_pages;
        const totalItems = data.pagination ? data.pagination.total_items : data.total;
        const page = data.pagination ? data.pagination.page : data.page;

        if (pages <= 1) {
            paginationNav.style.display = "none";
            return;
        }

        paginationNav.style.display = "flex";
        pageInfo.textContent = `หน้า ${page} จาก ${pages} (รวม ${totalItems} รายการ)`;
        prevPageBtn.disabled = !data.has_previous;
        nextPageBtn.disabled = !data.has_next;
    }

    /**
     * Opens detail modal and fetches full 9-module detail.
     */
    async function openDetailModal(publicId) {
        detailModal.style.display = "flex";
        modalLoading.style.display = "flex";
        modalBody.style.display = "none";
        downloadTxtBtn.style.display = "none";
        downloadPdfBtn.style.display = "none";

        try {
            const res = await fetch(`/api/history/${publicId}`, {
                method: "GET",
                credentials: "same-origin"
            });

            if (res.status === 401) {
                window.location.href = "/login";
                return;
            }
            if (res.status === 404) {
                modalLoading.style.display = "none";
                modalBody.textContent = "";
                const p = document.createElement("p");
                p.textContent = "ไม่พบรายละเอียดของรายการนี้ หรือสิทธิ์การเข้าถึงถูกปฏิเสธ";
                modalBody.appendChild(p);
                modalBody.style.display = "block";
                return;
            }

            const detail = await res.json();
            renderModalContent(detail);
        } catch (err) {
            modalLoading.style.display = "none";
            modalBody.textContent = "";
            const p = document.createElement("p");
            p.textContent = "เกิดข้อผิดพลาดในการโหลดรายละเอียด";
            modalBody.appendChild(p);
            modalBody.style.display = "block";
        }
    }

    /**
     * Renders 9 modules result into modal using safe DOM manipulation.
     */
    function renderModalContent(detail) {
        modalLoading.style.display = "none";
        modalBody.textContent = "";

        const resultData = detail.result_data;

        if (!resultData) {
            const emptyP = document.createElement("p");
            emptyP.textContent = "ไม่มีข้อมูลผลการวิเคราะห์ในแคชสำหรับรายการนี้";
            modalBody.appendChild(emptyP);
        } else {
            const modules = [
                { key: "telemetry", title: "1. ข้อมูลการประมวลผลสื่อ (Telemetry)" },
                { key: "timeline", title: "2. รายการถอดความตามเวลา (Transcript Timeline)" },
                { key: "summary", title: "3. บทสรุปเนื้อหายุทธศาสตร์ (Executive Summary)" },
                { key: "key_takeaways", title: "4. ประเด็นสำคัญเชิงยุทธศาสตร์ (Key Takeaways)" },
                { key: "sentiment_analysis", title: "5. การวิเคราะห์บรรยากาศการนำเสนอ (Presentation Atmosphere)" },
                { key: "swot_analysis", title: "6. การวิเคราะห์ SWOT (SWOT Analysis)" },
                { key: "action_plan", title: "7. แผนปฏิบัติการที่แนะนำ (Action Plan)" },
                { key: "knowledge_tree", title: "8. ผังโครงสร้างความรู้ (Knowledge Tree)" },
                { key: "analytics_metrics", title: "9. ดัชนีวัดผลเชิงวิเคราะห์ (Analytics Metrics)" },
            ];

            modules.forEach((mod) => {
                if (resultData[mod.key]) {
                    const section = document.createElement("div");
                    section.className = "module-section";

                    const secTitle = document.createElement("h3");
                    secTitle.className = "module-title";
                    secTitle.textContent = mod.title;

                    const secContent = document.createElement("div");
                    secContent.className = "module-content";

                    const val = resultData[mod.key];
                    if (typeof val === "string") {
                        secContent.textContent = val;
                    } else {
                        secContent.textContent = JSON.stringify(val, null, 2);
                    }

                    section.appendChild(secTitle);
                    section.appendChild(secContent);
                    modalBody.appendChild(section);
                }
            });
        }

        if (detail.download_available && detail.download_unique_id) {
            downloadTxtBtn.href = `/download/txt/${detail.download_unique_id}`;
            downloadPdfBtn.href = `/download/pdf/${detail.download_unique_id}`;
            downloadTxtBtn.style.display = "inline-block";
            downloadPdfBtn.style.display = "inline-block";
        }

        modalBody.style.display = "block";
    }

    function hideDetailModal() {
        detailModal.style.display = "none";
    }

    function openDeleteModal(publicId) {
        pendingDeleteId = publicId;
        deleteConfirmModal.style.display = "flex";
    }

    function hideDeleteModal() {
        pendingDeleteId = null;
        deleteConfirmModal.style.display = "none";
    }

    function showState(state) {
        loadingState.style.display = state === "loading" ? "flex" : "none";
        errorState.style.display = state === "error" ? "flex" : "none";
        emptyState.style.display = state === "empty" ? "flex" : "none";
        historyGrid.style.display = state === "grid" ? "grid" : "none";
        if (state !== "grid") {
            paginationNav.style.display = "none";
        }
    }

    function showErrorState(title, msg) {
        showState("error");
        errorTitle.textContent = title;
        errorMessage.textContent = msg;
    }

    function showAlert(msg, type) {
        if (!statusAlert) return;
        statusAlert.textContent = msg;
        statusAlert.className = `alert-banner alert-${type}`;
        statusAlert.style.display = "block";
        setTimeout(() => {
            statusAlert.style.display = "none";
        }, 5000);
    }

    function formatDate(isoStr) {
        if (!isoStr) return "ไม่ระบุ";
        try {
            const d = new Date(isoStr);
            return d.toLocaleDateString("th-TH", {
                year: "numeric",
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit"
            });
        } catch (e) {
            return isoStr;
        }
    }

    function formatDuration(sec) {
        if (!sec || sec <= 0) return "ไม่ระบุ";
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${m}:${s < 10 ? '0' : ''}${s} นาที`;
    }

    function restoreAnalysisFromHistory(analysisId) {
        if (!analysisId) return;
        window.location.href = `/dashboard?analysis_id=${analysisId}`;
    }

    // Expose in window namespaces
    window.restoreAnalysisFromHistory = restoreAnalysisFromHistory;
    window.WeFoolApp = window.WeFoolApp || {};
    window.WeFoolApp.history = window.WeFoolApp.history || {};
    window.WeFoolApp.history.restoreAnalysis = restoreAnalysisFromHistory;
});
