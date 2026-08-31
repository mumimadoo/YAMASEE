/**
 * YAMASEE Video Comparison Workspace JS
 * Phase 3 & Phase 4 — Video Comparison UI Engine & Pipeline Integration
 */

document.addEventListener('DOMContentLoaded', () => {
    // State Variables
    let selectedSnapshotA = null;
    let selectedSnapshotB = null;
    let currentSlotToSelect = 'A';
    let candidatesList = [];
    let activeFilterType = '';
    let searchQuery = '';
    let deepLinkPublicId = null;
    let isRestoreMode = false;

    let activeProcessingSlot = null; // 'A' | 'B' | null
    const slotJobQueue = { A: null, B: null };

    // DOM Element References
    const btnSelectA = document.getElementById('btnSelectA');
    const btnSelectB = document.getElementById('btnSelectB');
    const btnChangeA = document.getElementById('btnChangeA');
    const btnChangeB = document.getElementById('btnChangeB');
    const startCompareBtn = document.getElementById('startCompareBtn');
    const comparisonModelSelect = document.getElementById('comparisonModelSelect');
    const sameVideoAlert = document.getElementById('sameVideoAlert');

    const unselectedA = document.getElementById('unselectedA');
    const selectedA = document.getElementById('selectedA');
    const titleA = document.getElementById('titleA');
    const durationA = document.getElementById('durationA');
    const dateA = document.getElementById('dateA');
    const thumbA = document.getElementById('thumbA');
    const sourceTypeA = document.getElementById('sourceTypeA');

    const unselectedB = document.getElementById('unselectedB');
    const selectedB = document.getElementById('selectedB');
    const titleB = document.getElementById('titleB');
    const durationB = document.getElementById('durationB');
    const dateB = document.getElementById('dateB');
    const thumbB = document.getElementById('thumbB');
    const sourceTypeB = document.getElementById('sourceTypeB');

    // Phase 4 New Input References
    const btnSubmitUrlA = document.getElementById('btnSubmitUrlA');
    const btnSubmitUrlB = document.getElementById('btnSubmitUrlB');
    const btnChooseFileA = document.getElementById('btnChooseFileA');
    const btnChooseFileB = document.getElementById('btnChooseFileB');
    const btnSubmitFileA = document.getElementById('btnSubmitFileA');
    const btnSubmitFileB = document.getElementById('btnSubmitFileB');
    const fileInputA = document.getElementById('fileInputA');
    const fileInputB = document.getElementById('fileInputB');
    const fileNameA = document.getElementById('fileNameA');
    const fileNameB = document.getElementById('fileNameB');

    const btnRetryA = document.getElementById('btnRetryA');
    const btnRetryB = document.getElementById('btnRetryB');
    const btnChangeFailedA = document.getElementById('btnChangeFailedA');
    const btnChangeFailedB = document.getElementById('btnChangeFailedB');

    const comparisonLoadingState = document.getElementById('comparisonLoadingState');
    const emptyWorkspaceState = document.getElementById('emptyWorkspaceState');
    const comparisonResultContainer = document.getElementById('comparisonResultContainer');
    const comparisonErrorState = document.getElementById('comparisonErrorState');
    const retryCompareBtn = document.getElementById('retryCompareBtn');

    // Modals
    const candidateModal = document.getElementById('candidateModal');
    const btnCloseCandidateModal = document.getElementById('btnCloseCandidateModal');
    const btnCancelCandidateModal = document.getElementById('btnCancelCandidateModal');
    const candidateSearchInput = document.getElementById('candidateSearchInput');
    const candidateFilterTabs = document.getElementById('candidateFilterTabs');
    const candidateListGrid = document.getElementById('candidateListGrid');
    const candidateLoading = document.getElementById('candidateLoading');
    const candidateEmpty = document.getElementById('candidateEmpty');

    const evidenceModal = document.getElementById('evidenceModal');
    const btnCloseEvidenceModal = document.getElementById('btnCloseEvidenceModal');
    const btnCloseEvidenceModalFooter = document.getElementById('btnCloseEvidenceModalFooter');

    // Global Day/Night theme toggle handled by auth-theme.js (.theme-toggle-btn)

    // Logout Handler
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
            } catch (e) {
                console.error('Logout error:', e);
            }
            window.location.href = '/login';
        });
    }

    // Event Listeners for History Modal Selection Buttons
    if (btnSelectA) btnSelectA.addEventListener('click', () => openCandidateModal('A'));
    if (btnSelectB) btnSelectB.addEventListener('click', () => openCandidateModal('B'));
    if (btnChangeA) btnChangeA.addEventListener('click', () => setSlotState('A', 'EMPTY'));
    if (btnChangeB) btnChangeB.addEventListener('click', () => setSlotState('B', 'EMPTY'));

    // Phase 4 & 5.2 New Input Listeners
    if (btnSubmitUrlA) btnSubmitUrlA.addEventListener('click', () => handleUrlSubmit('A'));
    if (btnSubmitUrlB) btnSubmitUrlB.addEventListener('click', () => handleUrlSubmit('B'));

    const urlInputAEl = document.getElementById('urlInputA');
    const urlInputBEl = document.getElementById('urlInputB');
    if (urlInputAEl) urlInputAEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); handleUrlSubmit('A'); } });
    if (urlInputBEl) urlInputBEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); handleUrlSubmit('B'); } });

    setupFilePicker('A');
    setupFilePicker('B');

    // Phase 5.2 Cache Notice & Model Selection Listeners
    ['A', 'B'].forEach(slot => {
        const btnUseCache = document.getElementById(slot === 'A' ? 'btnUseCacheA' : 'btnUseCacheB');
        const btnReanalyze = document.getElementById(slot === 'A' ? 'btnReanalyzeA' : 'btnReanalyzeB');
        const btnCancelModel = document.getElementById(slot === 'A' ? 'btnCancelModelA' : 'btnCancelModelB');
        const btnStartAnalysis = document.getElementById(slot === 'A' ? 'btnStartAnalysisA' : 'btnStartAnalysisB');

        if (btnUseCache) {
            btnUseCache.addEventListener('click', async () => {
                const payload = pendingSlotPayload[slot];
                if (payload && payload.public_id) {
                    try {
                        const snapResp = await fetch(`/api/comparison/snapshots/${payload.public_id}`);
                        if (snapResp.ok) {
                            const snapshot = await snapResp.json();
                            setSlotState(slot, 'READY', { snapshot });
                            return;
                        }
                    } catch (err) {
                        console.error('Error fetching cached snapshot:', err);
                    }
                }
                setSlotState(slot, 'MODEL_CONFIG');
            });
        }

        if (btnReanalyze) {
            btnReanalyze.addEventListener('click', () => {
                if (pendingSlotPayload[slot]) {
                    pendingSlotPayload[slot].force_reanalyze = true;
                }
                setSlotState(slot, 'MODEL_CONFIG');
            });
        }

        if (btnCancelModel) {
            btnCancelModel.addEventListener('click', () => {
                setSlotState(slot, 'EMPTY');
            });
        }

        if (btnStartAnalysis) {
            btnStartAnalysis.addEventListener('click', () => {
                const modelSelect = document.getElementById(slot === 'A' ? 'modelSelectA' : 'modelSelectB');
                const selectedModel = modelSelect ? modelSelect.value : 'gemini-3.5-flash';
                const payload = pendingSlotPayload[slot];

                if (!payload || (!payload.youtube_url && !payload.file)) {
                    alert('ไม่พบข้อมูลวิดีโอสำหรับวิเคราะห์');
                    return;
                }

                payload.model = selectedModel;
                queueOrStartJob(slot, payload.mode, payload);
            });
        }

        const modelSelect = document.getElementById(slot === 'A' ? 'modelSelectA' : 'modelSelectB');
        if (modelSelect) {
            modelSelect.addEventListener('change', () => {
                fetchAndUpdatePreRunEstimate();
            });
        }

        const urlInput = document.getElementById(slot === 'A' ? 'urlInputA' : 'urlInputB');
        if (urlInput) {
            urlInput.addEventListener('input', () => {
                fetchAndUpdatePreRunEstimate();
            });
        }
    });

    if (btnChangeFailedA) btnChangeFailedA.addEventListener('click', () => setSlotState('A', 'EMPTY'));
    if (btnChangeFailedB) btnChangeFailedB.addEventListener('click', () => setSlotState('B', 'EMPTY'));
    if (btnRetryA) btnRetryA.addEventListener('click', () => retrySlotJob('A'));
    if (btnRetryB) btnRetryB.addEventListener('click', () => retrySlotJob('B'));

    // Modal Close Listeners
    if (btnCloseCandidateModal) btnCloseCandidateModal.addEventListener('click', closeCandidateModal);
    if (btnCancelCandidateModal) btnCancelCandidateModal.addEventListener('click', closeCandidateModal);
    if (candidateModal) {
        candidateModal.addEventListener('click', (e) => {
            if (e.target === candidateModal) closeCandidateModal();
        });
    }

    if (btnCloseEvidenceModal) btnCloseEvidenceModal.addEventListener('click', closeEvidenceModal);
    if (btnCloseEvidenceModalFooter) btnCloseEvidenceModalFooter.addEventListener('click', closeEvidenceModal);
    if (evidenceModal) {
        evidenceModal.addEventListener('click', (e) => {
            if (e.target === evidenceModal) closeEvidenceModal();
        });
    }

    // Filter Tabs
    if (candidateFilterTabs) {
        candidateFilterTabs.addEventListener('click', (e) => {
            const btn = e.target.closest('.tab-btn');
            if (!btn) return;
            candidateFilterTabs.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeFilterType = btn.getAttribute('data-type') || '';
            renderCandidateCards();
        });
    }

    // Search Input
    if (candidateSearchInput) {
        candidateSearchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value.trim().toLowerCase();
            renderCandidateCards();
        });
    }

    // Compare Action Button
    if (startCompareBtn) {
        startCompareBtn.addEventListener('click', executeVideoComparison);
    }
    if (retryCompareBtn) {
        retryCompareBtn.addEventListener('click', executeVideoComparison);
    }
    if (comparisonModelSelect) {
        comparisonModelSelect.addEventListener('change', fetchAndUpdatePreRunEstimate);
    }

    // Check Deep Linking via meta tag, URL search params, or URL path
    const metaDeepLink = document.querySelector('meta[name="comparison-public-id"]');
    if (metaDeepLink) {
        deepLinkPublicId = metaDeepLink.getAttribute('content');
    }
    if (!deepLinkPublicId) {
        const urlParams = new URLSearchParams(window.location.search);
        deepLinkPublicId = urlParams.get('comparison_id') || urlParams.get('public_id') || urlParams.get('id');
    }
    if (!deepLinkPublicId) {
        const pathParts = window.location.pathname.split('/');
        if (pathParts.length >= 3 && pathParts[1] === 'comparison' && pathParts[2]) {
            deepLinkPublicId = pathParts[2];
        }
    }

    if (deepLinkPublicId) {
        isRestoreMode = true;
        loadExistingComparisonDetail(deepLinkPublicId);
    } else {
        restoreActiveJobsFromSession();
    }

    // --------------------------------------------------------------------------
    // Slot State Controller (Phase 4 & 5.2)
    // --------------------------------------------------------------------------
    let pendingSlotPayload = { A: null, B: null };
    let precheckTokens = { A: 0, B: 0 };

    function setSlotState(slot, state, data = {}) {
        const isA = slot === 'A';
        const unselectedEl = document.getElementById(isA ? 'unselectedA' : 'unselectedB');
        const cacheNoticeEl = document.getElementById(isA ? 'cacheNoticeA' : 'cacheNoticeB');
        const modelConfigEl = document.getElementById(isA ? 'modelConfigA' : 'modelConfigB');
        const processingEl = document.getElementById(isA ? 'processingA' : 'processingB');
        const selectedEl = document.getElementById(isA ? 'selectedA' : 'selectedB');
        const failedEl = document.getElementById(isA ? 'failedA' : 'failedB');

        if (unselectedEl) unselectedEl.style.display = 'none';
        if (cacheNoticeEl) cacheNoticeEl.style.display = 'none';
        if (modelConfigEl) modelConfigEl.style.display = 'none';
        if (processingEl) processingEl.style.display = 'none';
        if (selectedEl) selectedEl.style.display = 'none';
        if (failedEl) failedEl.style.display = 'none';

        if (state === 'EMPTY') {
            if (unselectedEl) unselectedEl.style.display = 'block';
            if (isA) selectedSnapshotA = null; else selectedSnapshotB = null;
            pendingSlotPayload[slot] = null;
            precheckTokens[slot]++;
            sessionStorage.removeItem(`compare_job_${slot}`);
        } else if (state === 'CACHE_NOTICE') {
            if (cacheNoticeEl) cacheNoticeEl.style.display = 'block';
        } else if (state === 'MODEL_CONFIG') {
            if (modelConfigEl) modelConfigEl.style.display = 'block';
        } else if (state === 'QUEUED' || state === 'PROCESSING') {
            if (processingEl) processingEl.style.display = 'flex';
            const stageTitleEl = document.getElementById(isA ? 'stageTitleA' : 'stageTitleB');
            const progressFillEl = document.getElementById(isA ? 'progressFillA' : 'progressFillB');
            const progressTextEl = document.getElementById(isA ? 'progressTextA' : 'progressTextB');
            const queueNoticeEl = document.getElementById(isA ? 'queueNoticeA' : 'queueNoticeB');

            if (stageTitleEl) stageTitleEl.textContent = data.stage || (state === 'QUEUED' ? 'กำลังรอคิว...' : 'กำลังประมวลผล...');
            const pct = Math.min(100, Math.max(0, data.progress || 0));
            if (progressFillEl) progressFillEl.style.width = pct + '%';
            if (progressTextEl) progressTextEl.textContent = pct + '%';
            if (queueNoticeEl) queueNoticeEl.textContent = data.notice || (state === 'QUEUED' ? 'โปรดรอสักครู่ (ประมวลผลทีละคลิป)...' : 'ระบบกำลังถอดคำพูดและวิเคราะห์');
        } else if (state === 'READY') {
            if (selectedEl) selectedEl.style.display = 'flex';
            const snapshot = data.snapshot;
            if (isA) selectedSnapshotA = snapshot; else selectedSnapshotB = snapshot;
            
            const titleEl = document.getElementById(isA ? 'titleA' : 'titleB');
            const durationEl = document.getElementById(isA ? 'durationA' : 'durationB');
            const dateEl = document.getElementById(isA ? 'dateA' : 'dateB');
            const thumbEl = document.getElementById(isA ? 'thumbA' : 'thumbB');
            const typeEl = document.getElementById(isA ? 'sourceTypeA' : 'sourceTypeB');

            if (titleEl) titleEl.textContent = snapshot.title || snapshot.display_title || '--';
            if (durationEl) durationEl.textContent = '⏱️ ' + formatSeconds(snapshot.duration_seconds || 0);
            if (dateEl) dateEl.textContent = '📅 ' + formatDate(snapshot.analyzed_at || new Date().toISOString());
            if (thumbEl) thumbEl.src = snapshot.thumbnail_url || '/static/Logo_boy.png';
            if (typeEl) typeEl.textContent = (snapshot.source_type || 'MP4').toUpperCase();
        } else if (state === 'FAILED') {
            if (failedEl) failedEl.style.display = 'flex';
            const errorMsgEl = document.getElementById(isA ? 'errorMsgA' : 'errorMsgB');
            if (errorMsgEl) errorMsgEl.textContent = data.error || 'เกิดข้อผิดพลาดในการประมวลผลวิดีโอ';
            if (isA) selectedSnapshotA = null; else selectedSnapshotB = null;
        }

        validateSelection();
        fetchAndUpdatePreRunEstimate();
    }

    // --------------------------------------------------------------------------
    // Pre-Run Cost & Resource Estimation Engine (Phase 5.3)
    // --------------------------------------------------------------------------
    let estimateDebounceTimer = null;

    function fetchAndUpdatePreRunEstimate() {
        if (isRestoreMode) return;
        if (estimateDebounceTimer) clearTimeout(estimateDebounceTimer);
        estimateDebounceTimer = setTimeout(async () => {
            await runPreRunEstimateCalculation();
        }, 150);
    }

    async function runPreRunEstimateCalculation() {
        const buildSideData = (slot) => {
            const isA = slot === 'A';
            const snapshot = isA ? selectedSnapshotA : selectedSnapshotB;
            const payload = pendingSlotPayload[slot];
            const modelSelect = document.getElementById(isA ? 'modelSelectA' : 'modelSelectB');
            const selectedModel = modelSelect ? modelSelect.value : 'gemini-3.5-flash';
            const urlInput = document.getElementById(isA ? 'urlInputA' : 'urlInputB');
            const urlVal = urlInput ? urlInput.value.trim() : null;

            if (snapshot) {
                return {
                    state: 'HISTORY_REUSE',
                    duration_seconds: snapshot.duration_seconds || null,
                    selected_model: snapshot.model_used || selectedModel,
                    analysis_id: snapshot.analysis_id || snapshot.public_id || null,
                    url: snapshot.source_url || urlVal
                };
            } else if (payload) {
                if (payload.public_id && !payload.force_reanalyze) {
                    return {
                        state: 'CACHE_REUSE',
                        duration_seconds: payload.duration_seconds || null,
                        selected_model: selectedModel,
                        analysis_id: payload.public_id,
                        url: payload.youtube_url || null
                    };
                }
                return {
                    state: 'NEW_ANALYSIS_REQUIRED',
                    duration_seconds: payload.duration_seconds || null,
                    selected_model: selectedModel,
                    analysis_id: null,
                    url: payload.youtube_url || null
                };
            } else if (urlVal && urlVal.length > 5) {
                return {
                    state: 'NEW_ANALYSIS_REQUIRED',
                    duration_seconds: null,
                    selected_model: selectedModel,
                    url: urlVal
                };
            } else {
                return {
                    state: 'UNRESOLVED',
                    duration_seconds: null,
                    selected_model: selectedModel
                };
            }
        };

        const sideAData = buildSideData('A');
        const sideBData = buildSideData('B');

        // Hide estimate panels if both slots are empty
        if (sideAData.state === 'UNRESOLVED' && sideBData.state === 'UNRESOLVED') {
            const compactA = document.getElementById('compactEstimateA');
            const compactB = document.getElementById('compactEstimateB');
            const totalCard = document.getElementById('comparisonTotalEstimateCard');
            if (compactA) compactA.style.display = 'none';
            if (compactB) compactB.style.display = 'none';
            if (totalCard) totalCard.style.display = 'none';
            return;
        }

        // Asynchronously resolve URL duration if missing for NEW_ANALYSIS_REQUIRED slots
        const resolveUrlDuration = async (sideData) => {
            if (sideData.state === 'NEW_ANALYSIS_REQUIRED' && (!sideData.duration_seconds || sideData.duration_seconds <= 0) && sideData.url) {
                try {
                    const resp = await fetch(`/api/resolve_duration?url=${encodeURIComponent(sideData.url)}`);
                    if (resp.ok) {
                        const d = await resp.json();
                        if (d.duration_seconds && d.duration_seconds > 0) {
                            sideData.duration_seconds = d.duration_seconds;
                        }
                    }
                } catch (e) {
                    console.warn('Async duration resolution error:', e);
                }
            }
        };

        await Promise.all([resolveUrlDuration(sideAData), resolveUrlDuration(sideBData)]);

        try {
            const comparisonModelSelect = document.getElementById('comparisonModelSelect');
            const comparisonModel = comparisonModelSelect ? comparisonModelSelect.value : 'gemini-2.5-flash';
            const estimateResp = await fetch('/api/comparison/pre-run-estimate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_a: sideAData,
                    video_b: sideBData,
                    comparison_model: comparisonModel
                })
            });

            if (!estimateResp.ok) return;

            const estData = await estimateResp.json();
            renderPreRunEstimateUI(estData);
        } catch (err) {
            console.error('Pre-run estimate calculation error:', err);
        }
    }

    function renderPreRunEstimateUI(estData) {
        if (!estData) return;

        const renderCompactRow = (slot, sideEst) => {
            const isA = slot === 'A';
            const compactEl = document.getElementById(isA ? 'compactEstimateA' : 'compactEstimateB');
            const badgeEl = document.getElementById(isA ? 'estimateBadgeA' : 'estimateBadgeB');

            if (!compactEl) return;

            if (!sideEst || sideEst.state === 'UNRESOLVED' || !sideEst.is_resolved) {
                compactEl.style.display = 'flex';
                if (badgeEl) badgeEl.textContent = '⏳ กำลังเตรียมวิดีโอ...';
                return;
            }

            compactEl.style.display = 'flex';

            if (sideEst.state === 'REUSE') {
                if (badgeEl) badgeEl.textContent = '✓ ใช้ผลวิเคราะห์เดิม — ไม่มีการวิเคราะห์คลิปซ้ำ';
            } else {
                if (badgeEl) badgeEl.textContent = sideEst.label_th || '✨ วิเคราะห์ใหม่';
            }
        };

        renderCompactRow('A', estData.video_a);
        renderCompactRow('B', estData.video_b);

        const totalCard = document.getElementById('comparisonTotalEstimateCard');
        if (totalCard) {
            totalCard.style.display = 'none';
        }
    }

    // --------------------------------------------------------------------------
    // Phase 4 & 5.2 New Video Submissions, Model Selection & Pre-check Cache
    // --------------------------------------------------------------------------
    async function handleUrlSubmit(slot) {
        const isA = slot === 'A';
        const inputEl = document.getElementById(isA ? 'urlInputA' : 'urlInputB');
        const submitBtn = document.getElementById(isA ? 'btnSubmitUrlA' : 'btnSubmitUrlB');
        const url = (inputEl ? inputEl.value : '').trim();
        if (!url) {
            alert('กรุณากรอก URL วิดีโอ YouTube หรือ TikTok');
            return;
        }

        // 1. Immediate UI Feedback (< 200ms)
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '⏳ กำลังตรวจสอบวิดีโอ...';
        }

        let mode = 'youtube';
        if (url.toLowerCase().includes('tiktok.com')) {
            mode = 'tiktok';
        }

        const currentToken = ++precheckTokens[slot];
        pendingSlotPayload[slot] = { mode, youtube_url: url };

        // 2. Open Model Selector immediately (< 300ms)
        setSlotState(slot, 'MODEL_CONFIG');

        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = 'ใช้วิดีโอนี้';
        }

        // 3. Asynchronous Pre-check Cache
        try {
            const formData = new FormData();
            formData.append('mode', mode);
            formData.append('youtube_url', url);

            const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
            const timeoutId = controller ? setTimeout(() => controller.abort(), 5000) : null;

            const checkResp = await fetch('/pre_check_cache', {
                method: 'POST',
                body: formData,
                signal: controller ? controller.signal : undefined
            });
            if (timeoutId) clearTimeout(timeoutId);

            if (precheckTokens[slot] !== currentToken) return;

            if (checkResp.ok) {
                const checkData = await checkResp.json();
                if (precheckTokens[slot] !== currentToken) return;

                if (checkData.cache_exists && checkData.public_id) {
                    pendingSlotPayload[slot] = { mode, youtube_url: url, public_id: checkData.public_id };
                    setSlotState(slot, 'CACHE_NOTICE');
                }
            }
        } catch (e) {
            console.warn('Pre-check cache async error/timeout, user stays in model selection:', e);
        }
    }

    function setupFilePicker(slot) {
        const isA = slot === 'A';
        const fileInput = document.getElementById(isA ? 'fileInputA' : 'fileInputB');
        const chooseBtn = document.getElementById(isA ? 'btnChooseFileA' : 'btnChooseFileB');
        const nameDisplay = document.getElementById(isA ? 'fileNameA' : 'fileNameB');
        const submitBtn = document.getElementById(isA ? 'btnSubmitFileA' : 'btnSubmitFileB');

        if (!chooseBtn || !fileInput) return;

        chooseBtn.addEventListener('click', () => fileInput.click());

        fileInput.addEventListener('change', () => {
            const file = fileInput.files[0];
            if (file) {
                nameDisplay.textContent = file.name;
                nameDisplay.style.display = 'inline-block';
                submitBtn.style.display = 'inline-block';
            } else {
                nameDisplay.style.display = 'none';
                submitBtn.style.display = 'none';
            }
        });

        if (submitBtn) {
            submitBtn.addEventListener('click', () => {
                if (fileInput.files && fileInput.files[0]) {
                    handleFileSubmit(slot, fileInput.files[0]);
                }
            });
        }
    }

    async function handleFileSubmit(slot, file) {
        if (!file) {
            alert('กรุณาเลือกไฟล์ MP4');
            return;
        }

        const isA = slot === 'A';
        const submitBtn = document.getElementById(isA ? 'btnSubmitFileA' : 'btnSubmitFileB');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '⏳ กำลังตรวจสอบวิดีโอ...';
        }

        const currentToken = ++precheckTokens[slot];
        pendingSlotPayload[slot] = { mode: 'mp4', file: file };

        // Open Model Selector immediately (< 300ms)
        setSlotState(slot, 'MODEL_CONFIG');

        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = 'ใช้วิดีโอนี้';
        }

        // Asynchronous Pre-check Cache for MP4
        try {
            const formData = new FormData();
            formData.append('mode', 'mp4');
            formData.append('file_name', file.name);
            formData.append('file_size_bytes', file.size);

            const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
            const timeoutId = controller ? setTimeout(() => controller.abort(), 5000) : null;

            const checkResp = await fetch('/pre_check_cache', {
                method: 'POST',
                body: formData,
                signal: controller ? controller.signal : undefined
            });
            if (timeoutId) clearTimeout(timeoutId);

            if (precheckTokens[slot] !== currentToken) return;

            if (checkResp.ok) {
                const checkData = await checkResp.json();
                if (precheckTokens[slot] !== currentToken) return;

                if (checkData.cache_exists && checkData.public_id) {
                    pendingSlotPayload[slot] = { mode: 'mp4', file: file, public_id: checkData.public_id };
                    setSlotState(slot, 'CACHE_NOTICE');
                }
            }
        } catch (e) {
            console.warn('MP4 pre-check cache async error/timeout:', e);
        }
    }

    // --------------------------------------------------------------------------
    // Sequential Queue & Job Execution
    // --------------------------------------------------------------------------
    function queueOrStartJob(slot, mode, payload) {
        slotJobQueue[slot] = { mode, payload };

        if (activeProcessingSlot && activeProcessingSlot !== slot) {
            // Other slot is active! Queue this slot
            setSlotState(slot, 'QUEUED', { stage: `รอคิว (กำลังประมวลผล Video ${activeProcessingSlot})...`, progress: 0 });
        } else {
            // Start processing immediately
            startAnalysisJob(slot);
        }
    }

    function retrySlotJob(slot) {
        if (slotJobQueue[slot]) {
            startAnalysisJob(slot);
        } else {
            setSlotState(slot, 'EMPTY');
        }
    }

    async function startAnalysisJob(slot) {
        const jobData = slotJobQueue[slot];
        if (!jobData) return;

        activeProcessingSlot = slot;
        setSlotState(slot, 'PROCESSING', { stage: 'ส่งข้อมูลเข้าระบบ...', progress: 10 });

        try {
            const formData = new FormData();
            formData.append('mode', jobData.mode);
            formData.append('mediaMode', jobData.mode);
            if (jobData.payload.youtube_url) {
                formData.append('youtube_url', jobData.payload.youtube_url);
            }
            if (jobData.payload.file) {
                formData.append('file', jobData.payload.file);
            }
            if (jobData.payload.model) {
                formData.append('model', jobData.payload.model);
            }

            const resp = await fetch('/submit_analysis', {
                method: 'POST',
                body: formData
            });

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.detail || errData.error || 'ไม่สามารถส่งวิดีโอเข้าระบบได้');
            }

            const resData = await resp.json();
            const jobId = resData.job_id;

            sessionStorage.setItem(`compare_job_${slot}`, jobId);
            pollJobStatus(slot, jobId);
        } catch (err) {
            console.error(`Slot ${slot} submission error:`, err);
            setSlotState(slot, 'FAILED', { error: err.message });
            activeProcessingSlot = null;
            checkAndStartNextQueuedSlot();
        }
    }

    function pollJobStatus(slot, jobId) {
        const intervalId = setInterval(async () => {
            try {
                const resp = await fetch(`/job_status/${jobId}`);
                if (!resp.ok) {
                    if (resp.status === 404) {
                        clearInterval(intervalId);
                        setSlotState(slot, 'FAILED', { error: 'ไม่พบสถานะงานวิเคราะห์' });
                        activeProcessingSlot = null;
                        checkAndStartNextQueuedSlot();
                    }
                    return;
                }

                const job = await resp.json();
                const stageText = mapJobStageText(job.stage || job.status);

                if (job.status === 'completed') {
                    clearInterval(intervalId);
                    sessionStorage.removeItem(`compare_job_${slot}`);

                    const publicId = job.public_id;
                    let snapshot = null;
                    if (publicId) {
                        const snapResp = await fetch(`/api/comparison/snapshots/${publicId}`);
                        if (snapResp.ok) snapshot = await snapResp.json();
                    }

                    if (!snapshot && job.result) {
                        snapshot = {
                            analysis_id: publicId || jobId,
                            title: job.result.video_title || job.result.title || 'Completed Analysis',
                            source_type: job.source_type || 'mp4',
                            duration_seconds: job.result.duration_seconds || 0,
                            analyzed_at: new Date().toISOString(),
                            thumbnail_url: '/static/Logo_boy.png'
                        };
                    }

                    setSlotState(slot, 'READY', { snapshot });
                    activeProcessingSlot = null;
                    checkAndStartNextQueuedSlot();
                } else if (job.status === 'failed' || job.status === 'error') {
                    clearInterval(intervalId);
                    sessionStorage.removeItem(`compare_job_${slot}`);
                    setSlotState(slot, 'FAILED', { error: job.error_message || job.error || 'การประมวลผลล้มเหลว' });
                    activeProcessingSlot = null;
                    checkAndStartNextQueuedSlot();
                } else {
                    setSlotState(slot, 'PROCESSING', {
                        stage: stageText,
                        progress: job.progress || 15
                    });
                }
            } catch (err) {
                console.error(`Polling error for slot ${slot}:`, err);
            }
        }, 2000);
    }

    function checkAndStartNextQueuedSlot() {
        const nextSlot = activeProcessingSlot === 'A' ? 'B' : 'A';
        if (slotJobQueue[nextSlot] && !activeProcessingSlot) {
            startAnalysisJob(nextSlot);
        }
    }

    function restoreActiveJobsFromSession() {
        ['A', 'B'].forEach(slot => {
            const jobId = sessionStorage.getItem(`compare_job_${slot}`);
            if (jobId) {
                activeProcessingSlot = slot;
                setSlotState(slot, 'PROCESSING', { stage: 'กำลังต่อสายตรวจสถานะงาน...', progress: 15 });
                pollJobStatus(slot, jobId);
            }
        });
    }

    function mapJobStageText(stage) {
        if (!stage) return 'กำลังประมวลผล...';
        const s = stage.toLowerCase();
        if (s.includes('download')) return 'กำลังดาวน์โหลดวิดีโอ...';
        if (s.includes('audio') || s.includes('remux')) return 'กำลังเตรียมไฟล์เสียง...';
        if (s.includes('transcrib') || s.includes('whisper') || s.includes('vad')) return 'กำลังถอดคำพูด (AI Transcription)...';
        if (s.includes('analys') || s.includes('gemini')) return 'กำลังวิเคราะห์เนื้อหาเชิงลึก...';
        if (s.includes('save') || s.includes('persist')) return 'กำลังบันทึกผลการวิเคราะห์...';
        if (s.includes('queued')) return 'กำลังรอคิวระบบ...';
        return stage;
    }

    // --------------------------------------------------------------------------
    // Candidate Modal & Selection Logic
    // --------------------------------------------------------------------------
    async function openCandidateModal(slot) {
        currentSlotToSelect = slot;
        candidateModal.style.display = 'flex';
        candidateLoading.style.display = 'block';
        candidateEmpty.style.display = 'none';
        candidateListGrid.style.display = 'none';

        try {
            const resp = await fetch('/api/comparison/candidates?page=1&page_size=50');
            if (!resp.ok) throw new Error('Failed to load candidate videos');
            const data = await resp.json();
            candidatesList = data.items || [];
            candidateLoading.style.display = 'none';

            if (candidatesList.length === 0) {
                candidateEmpty.style.display = 'block';
            } else {
                candidateListGrid.style.display = 'grid';
                renderCandidateCards();
            }
        } catch (err) {
            console.error('Candidate modal fetch error:', err);
            candidateLoading.style.display = 'none';
            candidateEmpty.style.display = 'block';
        }
    }

    function closeCandidateModal() {
        candidateModal.style.display = 'none';
    }

    function renderCandidateCards() {
        candidateListGrid.innerHTML = '';

        let filtered = candidatesList.filter(item => {
            if (activeFilterType) {
                const src = (item.source_type || '').toLowerCase();
                if (activeFilterType === 'mp4') {
                    if (!['mp4', 'upload', 'file', 'local'].includes(src)) return false;
                } else if (activeFilterType === 'tiktok') {
                    if (!['tiktok', 'tiktok_url', 'external_tiktok'].includes(src)) return false;
                } else if (activeFilterType === 'youtube') {
                    if (!['youtube', 'youtube_url'].includes(src)) return false;
                } else if (src !== activeFilterType) {
                    return false;
                }
            }
            if (searchQuery) {
                const title = (item.display_title || item.title || '').toLowerCase();
                if (!title.includes(searchQuery)) return false;
            }
            return true;
        });

        if (filtered.length === 0) {
            candidateEmpty.style.display = 'block';
            candidateListGrid.style.display = 'none';
            return;
        }

        candidateEmpty.style.display = 'none';
        candidateListGrid.style.display = 'grid';

        filtered.forEach(cand => {
            const card = document.createElement('div');
            card.className = 'candidate-card';

            const candId = cand.analysis_id || cand.public_id;
            const otherSlotId = currentSlotToSelect === 'A' 
                ? (selectedSnapshotB ? (selectedSnapshotB.analysis_id || selectedSnapshotB.public_id) : null)
                : (selectedSnapshotA ? (selectedSnapshotA.analysis_id || selectedSnapshotA.public_id) : null);

            if (candId && candId === otherSlotId) {
                card.classList.add('selected');
            }

            const candTitle = cand.display_title || cand.title || '';
            const formattedDuration = formatSeconds(cand.duration_seconds || 0);
            const formattedDate = formatDate(cand.completed_at || cand.analyzed_at);
            const thumbUrl = cand.thumbnail_url || '/static/Logo_boy.png';

            card.innerHTML = `
                <div class="video-thumb-wrapper" style="height: 100px;">
                    <img src="${thumbUrl}" alt="${escapeHtml(candTitle)}" class="video-thumb" loading="lazy" onerror="this.onerror=null;this.src='/static/Logo_boy.png';">
                    <span class="source-tag">${escapeHtml((cand.source_type || 'MP4').toUpperCase())}</span>
                </div>
                <div class="video-info">
                    <h4 class="video-title" style="font-size: 0.9rem;" title="${escapeHtml(candTitle)}">${escapeHtml(candTitle)}</h4>
                    <div class="video-meta" style="font-size: 0.75rem;">
                        <span>⏱️ ${formattedDuration}</span> • <span>📅 ${formattedDate}</span>
                    </div>
                    <div class="status-ready" style="font-size: 0.75rem;">✓ พร้อมเปรียบเทียบ</div>
                </div>
            `;

            card.addEventListener('click', () => selectCandidateForSlot(cand));
            candidateListGrid.appendChild(card);
        });
    }

    function showCandidateNotice(msg) {
        let noticeEl = document.getElementById('candidateNotice');
        if (!noticeEl) {
            const modalBody = candidateModal.querySelector('.modal-body');
            if (modalBody) {
                noticeEl = document.createElement('div');
                noticeEl.id = 'candidateNotice';
                noticeEl.className = 'alert-box alert-warning';
                noticeEl.style.margin = '0 0 1rem 0';
                modalBody.prepend(noticeEl);
            }
        }
        if (noticeEl) {
            noticeEl.textContent = msg;
            noticeEl.style.display = 'block';
            setTimeout(() => {
                if (noticeEl) noticeEl.style.display = 'none';
            }, 5000);
        }
    }

    async function selectCandidateForSlot(candidate) {
        const candId = candidate.analysis_id || candidate.public_id;
        if (!candId) {
            console.error('Candidate missing ID:', candidate);
            showCandidateNotice('ไม่พบรหัสวิดีโอรายการนี้');
            return;
        }

        // Check A == B
        const otherSelected = currentSlotToSelect === 'A' ? selectedSnapshotB : selectedSnapshotA;
        const otherId = otherSelected ? (otherSelected.analysis_id || otherSelected.public_id) : null;
        if (otherId && otherId === candId) {
            showCandidateNotice('วิดีโอ A และ วิดีโอ B ต้องไม่เป็นรายการเดียวกัน กรุณาเลือกรายการอื่น');
            return;
        }

        // Fetch full snapshot
        try {
            const resp = await fetch(`/api/comparison/snapshots/${candId}`);
            if (!resp.ok) throw new Error(`Failed to fetch snapshot details (status ${resp.status})`);
            const snapshot = await resp.json();

            setSlotState(currentSlotToSelect, 'READY', { snapshot });
            closeCandidateModal();
        } catch (err) {
            console.error('Snapshot fetch error:', err);
            showCandidateNotice('ไม่สามารถโหลดข้อมูลวิดีโอได้ กรุณาลองใหม่อีกครั้ง');
        }
    }

    function validateSelection() {
        if (!selectedSnapshotA || !selectedSnapshotB) {
            sameVideoAlert.style.display = 'none';
            startCompareBtn.disabled = true;
            return;
        }

        const idA = selectedSnapshotA.analysis_id || selectedSnapshotA.public_id;
        const idB = selectedSnapshotB.analysis_id || selectedSnapshotB.public_id;

        if (idA && idB && idA === idB) {
            sameVideoAlert.style.display = 'block';
            startCompareBtn.disabled = true;
        } else {
            sameVideoAlert.style.display = 'none';
            startCompareBtn.disabled = false;
        }
    }

    // --------------------------------------------------------------------------
    // Comparison Engine Trigger (Phase 2 & 3 Reuse)
    // --------------------------------------------------------------------------
    async function executeVideoComparison() {
        if (!selectedSnapshotA || !selectedSnapshotB) return;
        const idA = selectedSnapshotA.analysis_id || selectedSnapshotA.public_id;
        const idB = selectedSnapshotB.analysis_id || selectedSnapshotB.public_id;
        if (!idA || !idB || idA === idB) return;

        // Reset display states
        emptyWorkspaceState.style.display = 'none';
        comparisonResultContainer.style.display = 'none';
        comparisonErrorState.style.display = 'none';
        comparisonLoadingState.style.display = 'block';

        startLoadingStepsAnimation();

        try {
            const comparisonModelSelect = document.getElementById('comparisonModelSelect');
            const comparisonModel = comparisonModelSelect ? comparisonModelSelect.value : 'gemini-2.5-flash';
            const resp = await fetch('/api/comparison/compare', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    analysis_id_a: idA,
                    analysis_id_b: idB,
                    comparison_model: comparisonModel
                })
            });

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.detail || 'เกิดข้อผิดพลาดในการเปรียบเทียบวิดีโอ');
            }

            const comparisonData = await resp.json();
            stopLoadingStepsAnimation();

            comparisonLoadingState.style.display = 'none';
            comparisonResultContainer.style.display = 'block';

            renderComparisonResults(comparisonData);

            if (comparisonData.comparison_public_id) {
                const newUrl = `/comparison/${comparisonData.comparison_public_id}`;
                window.history.pushState({ public_id: comparisonData.comparison_public_id }, '', newUrl);
            }
        } catch (err) {
            console.error('Comparison execution failed:', err);
            stopLoadingStepsAnimation();
            comparisonLoadingState.style.display = 'none';
            comparisonErrorState.style.display = 'block';
            document.getElementById('comparisonErrorMsg').textContent = err.message || 'เกิดข้อผิดพลาด';
        }
    }

    let loadingStepInterval = null;
    function startLoadingStepsAnimation() {
        const stepItems = document.querySelectorAll('.step-item');
        let currentStep = 0;
        stepItems.forEach(s => s.classList.remove('active', 'completed'));
        if (stepItems[0]) stepItems[0].classList.add('active');

        loadingStepInterval = setInterval(() => {
            if (currentStep < stepItems.length - 1) {
                stepItems[currentStep].classList.remove('active');
                stepItems[currentStep].classList.add('completed');
                currentStep++;
                stepItems[currentStep].classList.add('active');
            }
        }, 6000);
    }

    function stopLoadingStepsAnimation() {
        if (loadingStepInterval) {
            clearInterval(loadingStepInterval);
            loadingStepInterval = null;
        }
    }

    async function loadExistingComparisonDetail(publicId) {
        emptyWorkspaceState.style.display = 'none';
        comparisonLoadingState.style.display = 'block';

        try {
            const resp = await fetch(`/api/comparison/${publicId}`);
            if (!resp.ok) throw new Error('ไม่พบข้อมูลการเปรียบเทียบนี้');
            const data = await resp.json();

            comparisonLoadingState.style.display = 'none';
            comparisonResultContainer.style.display = 'block';

            if (data.video_a_snapshot) {
                setSlotState('A', 'READY', { snapshot: data.video_a_snapshot });
            }
            if (data.video_b_snapshot) {
                setSlotState('B', 'READY', { snapshot: data.video_b_snapshot });
            }
            if (comparisonModelSelect && data.model_used) {
                comparisonModelSelect.value = data.model_used;
            }

            renderComparisonResults(data);
        } catch (err) {
            console.error('Failed to load deep link comparison:', err);
            comparisonLoadingState.style.display = 'none';
            comparisonErrorState.style.display = 'block';
            document.getElementById('comparisonErrorMsg').textContent = err.message || 'ไม่สามารถโหลดผลการเปรียบเทียบได้';
        }
    }

    // --------------------------------------------------------------------------
    // Render 6 Core Result Sections & Telemetry
    // --------------------------------------------------------------------------
    function renderComparisonResults(data) {
        console.log("[COMPARE DEBUG] raw data", data);
        const contract = data.result || data.result_json || data.comparison_contract || data;
        console.log("[COMPARE DEBUG] contract", contract);

        renderResultHeader(data);

        const snapA = data.video_a_snapshot || selectedSnapshotA;
        const snapB = data.video_b_snapshot || selectedSnapshotB;

        // 1. Overview
        renderSection01Overview(contract.comparison_overview);

        // 2. Topics & Differences Analysis (Unified Section 2)
        let topicsList = contract.comparison_topics || [];
        if (!topicsList || topicsList.length === 0) {
            topicsList = normalizeLegacyComparisonTopics(contract);
        }
        renderSection02TopicsDifferences(topicsList, contract);

        // 3. Speech Density & Content Pace Graph
        renderSection04SpeechDensity(snapA, snapB);

        // 5. Sentiment & Tone Comparison
        renderSection05Sentiment(contract.sentiment_comparison);

        // 6. Final Comparative Insight
        renderSection06FinalInsight(contract.final_comparative_insight);

        // External Research (Un-numbered)
        const currentPublicId = data.comparison_public_id || data.public_id || deepLinkPublicId;
        renderSectionExternalResearch(data.external_research || contract.external_research, currentPublicId);
    }
    window.renderComparisonResults = renderComparisonResults;
    window.renderComparisonResult = renderComparisonResults;

    function renderCacheBadge(isCached) {
        const badgeEl = document.getElementById('cacheNoticeBanner');
        if (!badgeEl) return;
        if (isCached) {
            badgeEl.style.display = 'inline-flex';
            badgeEl.innerHTML = '⚡ ใช้ผลเปรียบเทียบที่บันทึกไว้ (0 Gemini Calls)';
        } else {
            badgeEl.style.display = 'none';
        }
    }

    function formatProcessingTime(sec) {
        if (sec === null || sec === undefined) return '00:00:00';
        const num = parseFloat(sec);
        if (isNaN(num) || !isFinite(num) || num < 0) return '00:00:00';
        
        const rounded = Math.round(num);
        const h = Math.floor(rounded / 3600);
        const m = Math.floor((rounded % 3600) / 60);
        const s = rounded % 60;
        
        return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    window.formatProcessingTime = formatProcessingTime;

    function renderResultHeader(data) {
        const titleAEl = document.getElementById('summaryTitleA');
        const titleBEl = document.getElementById('summaryTitleB');

        if (titleAEl && selectedSnapshotA) {
            titleAEl.textContent = selectedSnapshotA.title || 'VIDEO A';
        } else if (titleAEl && data.video_a) {
            titleAEl.textContent = data.video_a.title || 'VIDEO A';
        }

        if (titleBEl && selectedSnapshotB) {
            titleBEl.textContent = selectedSnapshotB.title || 'VIDEO B';
        } else if (titleBEl && data.video_b) {
            titleBEl.textContent = data.video_b.title || 'VIDEO B';
        }

        const timeEl = document.getElementById('telemTime');
        const modelEl = document.getElementById('telemModel');
        const tokensEl = document.getElementById('telemTokens');
        const callsEl = document.getElementById('telemCalls');

        const procSec = data.processing_seconds !== undefined ? data.processing_seconds : (data.telemetry ? data.telemetry.processing_seconds : 0);
        const model = data.model_used || (data.telemetry ? data.telemetry.model_used : 'gemini-2.5-flash');
        const calls = data.api_calls !== undefined ? data.api_calls : (data.telemetry ? data.telemetry.api_calls : 1);
        const tokenUsage = data.token_usage || (data.telemetry ? data.telemetry.token_usage : null);

        if (timeEl) timeEl.textContent = formatProcessingTime(procSec);
        if (modelEl) modelEl.textContent = model;

        let totalTokens = 0;
        if (tokenUsage) {
            if (typeof tokenUsage === 'number') {
                totalTokens = tokenUsage;
            } else if (typeof tokenUsage === 'object') {
                if (tokenUsage.comparison && tokenUsage.comparison.total_tokens) {
                    totalTokens = tokenUsage.comparison.total_tokens;
                } else if (tokenUsage.total_tokens) {
                    totalTokens = tokenUsage.total_tokens;
                } else if (tokenUsage.total) {
                    totalTokens = tokenUsage.total;
                }
            }
        }
        if (tokensEl) tokensEl.textContent = totalTokens > 0 ? `${totalTokens.toLocaleString()} Tokens` : 'ไม่มีข้อมูล Token';
        if (callsEl) callsEl.textContent = `${calls} Call${calls === 1 ? '' : 's'}`;

        renderCacheBadge(data.cached);
    }
    window.renderResultHeader = renderResultHeader;
    window.renderSection02TopicsDifferences = renderSection02TopicsDifferences;

    function renderSection01Overview(overview = {}) {
        const summaryEl = document.getElementById('overviewSummaryText');
        const focusAEl = document.getElementById('overviewFocusA');
        const focusBEl = document.getElementById('overviewFocusB');
        const audienceEl = document.getElementById('overviewAudience');

        if (summaryEl) summaryEl.textContent = overview.summary || 'ไม่มีข้อมูลสรุปภาพรวม';
        if (focusAEl) focusAEl.textContent = overview.focus_video_a || overview.video_a_focus || '-';
        if (focusBEl) focusBEl.textContent = overview.focus_video_b || overview.video_b_focus || '-';
        if (audienceEl) audienceEl.textContent = overview.target_audience_comparison || '-';
    }

    // --------------------------------------------------------------------------
    // SECTION 2 — TOPICS & DIFFERENCES ANALYSIS (INSIGHT COMPARISON)
    // --------------------------------------------------------------------------
    let section02SharedExpanded = false;
    let section02DiffExpanded = false;
    let section02UniqueAExpanded = false;
    let section02UniqueBExpanded = false;
    let section02VideoAExpanded = false;
    let section02VideoBExpanded = false;

    function cleanRedundantText(str) {
        if (!str || typeof str !== 'string') return '';
        return str
            .replace(/ไม่มีการกล่าวถึงใน Video A/gi, '')
            .replace(/ไม่มีการกล่าวถึงใน Video B/gi, '')
            .replace(/ไม่มีการกล่าวถึงในวิดีโอ A/gi, '')
            .replace(/ไม่มีการกล่าวถึงในวิดีโอ B/gi, '')
            .replace(/ไม่มีการกล่าวถึง/gi, '')
            .trim();
    }

    const GENERIC_TOPIC_HEADINGS = new Set([
        'เนื้อหาหลัก',
        'ลักษณะตัวละครหลัก',
        'ตัวละครหลัก',
        'ตัวละคร',
        'ประเด็นทางกฎหมาย',
        'ประเด็นสำคัญ',
        'ประเด็นร่วม',
        'จุดแตกต่างสำคัญ',
        'ประเด็นเฉพาะ',
        'ประเด็นเฉพาะ video a',
        'ประเด็นเฉพาะ video b',
        'ประเด็น video a',
        'ประเด็น video b',
        'เหตุการณ์',
        'เรื่องทั่วไป',
        'สังคม',
        'บุคคล'
    ]);

    function isGenericTopicTitle(title) {
        if (!title || typeof title !== 'string') return true;
        const clean = title.trim().toLowerCase();
        if (GENERIC_TOPIC_HEADINGS.has(clean)) return true;
        for (const g of GENERIC_TOPIC_HEADINGS) {
            if (clean === g || clean.startsWith(g)) return true;
        }
        return false;
    }

    function resolveSpecificTopicTitle(rawTitle, desc) {
        if (!isGenericTopicTitle(rawTitle)) return rawTitle.trim();
        if (desc && typeof desc === 'string') {
            const cleanDesc = desc.trim();
            if (cleanDesc && cleanDesc !== '-' && !isGenericTopicTitle(cleanDesc)) {
                const words = cleanDesc.split(/\s+/);
                if (words.length <= 6) return cleanDesc;
                return words.slice(0, 5).join(' ').replace(/[.,:;]+$/, '');
            }
        }
        return '';
    }

    function normalizeLegacyComparisonTopics(contract = {}) {
        const topics = [];

        // 1. Convert shared_topics
        (contract.shared_topics || []).forEach(item => {
            topics.push({
                topic: item.topic || 'ประเด็นร่วม',
                category: 'shared',
                description_a: item.description_a || item.video_a_perspective || '-',
                description_b: item.description_b || item.video_b_perspective || '-',
                key_difference: item.key_difference || item.difference || item.diff_summary || null
            });
        });

        // 2. Convert key_differences
        (contract.key_differences || []).forEach(item => {
            topics.push({
                topic: item.dimension || item.topic || 'จุดแตกต่างสำคัญ',
                category: 'difference',
                description_a: item.video_a_perspective || item.video_a_point || item.description_a || '-',
                description_b: item.video_b_perspective || item.video_b_point || item.description_b || '-',
                impact: item.impact || item.effect || item.result_difference || item.significance || null
            });
        });

        // 3. Convert unique_topics
        const uniqueObj = contract.unique_topics || {};
        (uniqueObj.video_a || uniqueObj.video_a_unique || []).forEach(item => {
            topics.push({
                topic: item.topic || 'ประเด็นเฉพาะ Video A',
                category: 'unique_a',
                description_a: item.description || item.description_a || '-'
            });
        });

        (uniqueObj.video_b || uniqueObj.video_b_unique || []).forEach(item => {
            topics.push({
                topic: item.topic || 'ประเด็นเฉพาะ Video B',
                category: 'unique_b',
                description_b: item.description || item.description_b || '-'
            });
        });

        return topics;
    }

    function adaptLegacyToContentDriven(contract = {}, topicsList = []) {
        const videoATopics = [];
        const videoBTopics = [];
        const keyDifferences = [];

        let allTopics = topicsList && topicsList.length > 0 ? topicsList : [];
        if (allTopics.length === 0 && contract) {
            allTopics = normalizeLegacyComparisonTopics(contract);
        }

        allTopics.forEach(item => {
            if (!item) return;
            const cat = (item.category || '').toLowerCase();
            const rawTitle = item.topic || item.title || '';
            const descA = cleanRedundantText(item.description_a || item.video_a_perspective || '');
            const descB = cleanRedundantText(item.description_b || item.video_b_perspective || '');

            const titleA = resolveSpecificTopicTitle(rawTitle, descA);
            const titleB = resolveSpecificTopicTitle(rawTitle, descB);

            if (cat === 'unique_a' || cat === 'unique-a') {
                if (titleA) videoATopics.push({ title: titleA, description: descA || '-' });
            } else if (cat === 'unique_b' || cat === 'unique-b') {
                if (titleB) videoBTopics.push({ title: titleB, description: descB || '-' });
            } else if (cat === 'shared' || cat === 'difference' || cat === 'diff') {
                if (titleA) videoATopics.push({ title: titleA, description: descA || '-' });
                if (titleB) videoBTopics.push({ title: titleB, description: descB || '-' });
                const diffTitle = isGenericTopicTitle(rawTitle) ? 'จุดเน้นของเนื้อหา' : rawTitle;
                const diffDesc = item.key_difference || item.impact || (descA && descB ? `Video A: ${descA} ↔ Video B: ${descB}` : (descA || descB));
                if (diffDesc && diffDesc !== '-') {
                    keyDifferences.push({ title: diffTitle, description: cleanRedundantText(diffDesc) });
                }
            } else {
                if (titleA) videoATopics.push({ title: titleA, description: descA || '-' });
                if (titleB) videoBTopics.push({ title: titleB, description: descB || '-' });
            }
        });

        // Direct legacy array fallbacks
        if (videoATopics.length === 0 && contract.unique_topics && Array.isArray(contract.unique_topics.video_a)) {
            contract.unique_topics.video_a.forEach(it => {
                const specTitle = resolveSpecificTopicTitle(it.topic || '', it.description || '');
                if (specTitle) videoATopics.push({ title: specTitle, description: cleanRedundantText(it.description || '-') });
            });
        }
        if (videoBTopics.length === 0 && contract.unique_topics && Array.isArray(contract.unique_topics.video_b)) {
            contract.unique_topics.video_b.forEach(it => {
                const specTitle = resolveSpecificTopicTitle(it.topic || '', it.description || '');
                if (specTitle) videoBTopics.push({ title: specTitle, description: cleanRedundantText(it.description || '-') });
            });
        }
        if (keyDifferences.length === 0 && Array.isArray(contract.key_differences)) {
            contract.key_differences.forEach(it => {
                const title = it.title || (isGenericTopicTitle(it.dimension || it.topic || '') ? 'ความแตกต่างที่ค้นพบ' : (it.dimension || it.topic));
                keyDifferences.push({
                    title: title,
                    video_a: it.video_a || it.video_a_perspective || '',
                    video_b: it.video_b || it.video_b_perspective || '',
                    significance: it.significance || it.impact || '',
                    description: cleanRedundantText(it.description || '')
                });
            });
        }

        return {
            video_a_topics: videoATopics,
            video_b_topics: videoBTopics,
            key_differences: keyDifferences
        };
    }

    function renderSection02TopicsDifferences(topicsList = [], contract = {}) {
        const container = document.getElementById('topicsDifferencesContainer');
        if (!container) return;

        let effectiveContract = contract;
        if ((!effectiveContract || Object.keys(effectiveContract).length === 0) && topicsList && typeof topicsList === 'object' && !Array.isArray(topicsList)) {
            effectiveContract = topicsList;
        }

        let topicAnalysis = effectiveContract ? effectiveContract.topic_analysis : null;
        if (!topicAnalysis || (!Array.isArray(topicAnalysis.video_a_topics) && !Array.isArray(topicAnalysis.video_b_topics))) {
            topicAnalysis = adaptLegacyToContentDriven(effectiveContract, Array.isArray(topicsList) ? topicsList : []);
        }

        const cleanAndDedupe = (list) => {
            const result = [];
            const seen = new Set();
            (list || []).forEach(it => {
                const title = (it.title || it.topic || '').trim();
                if (!title || isGenericTopicTitle(title)) return;
                const lower = title.toLowerCase();
                if (seen.has(lower)) return;
                seen.add(lower);
                result.push({
                    title: title,
                    description: cleanRedundantText(it.description || it.description_a || it.description_b || '-')
                });
            });
            return result.slice(0, 6);
        };

        const videoATopics = cleanAndDedupe(topicAnalysis.video_a_topics || []);
        const videoBTopics = cleanAndDedupe(topicAnalysis.video_b_topics || []);
        const rawKeyDifferences = topicAnalysis.key_differences || [];

        // Clean & normalize key_differences
        const keyDifferences = [];
        (rawKeyDifferences || []).forEach(diff => {
            if (!diff || typeof diff !== 'object') return;
            const title = (diff.title || diff.dimension || diff.topic || '').trim();
            const videoA = cleanRedundantText(diff.video_a || diff.video_a_perspective || '');
            const videoB = cleanRedundantText(diff.video_b || diff.video_b_perspective || '');
            const significance = cleanRedundantText(diff.significance || diff.impact || '');
            const desc = cleanRedundantText(diff.description || '');

            if (!title && !videoA && !videoB && !desc && !significance) return;

            keyDifferences.push({
                title: title || 'ความแตกต่างที่ค้นพบ',
                video_a: videoA,
                video_b: videoB,
                significance: significance,
                description: desc
            });
        });

        const MAX_TOPICS_DEFAULT = 3;
        const visibleATopics = section02VideoAExpanded ? videoATopics : videoATopics.slice(0, MAX_TOPICS_DEFAULT);
        const visibleBTopics = section02VideoBExpanded ? videoBTopics : videoBTopics.slice(0, MAX_TOPICS_DEFAULT);

        let html = '<div class="content-driven-section2">';

        // TOP HALF: Independent Topics Dual Grid
        html += `
            <div class="topics-dual-grid">
                <!-- Video A Column -->
                <div class="topics-column side-a">
                    <div class="column-header">
                        <span class="video-badge badge-a">VIDEO A</span>
                        <h3 class="column-title">ประเด็นสำคัญใน Video A</h3>
                    </div>
                    <div class="topic-cards-list">
        `;
        if (videoATopics.length > 0) {
            visibleATopics.forEach(t => {
                const title = t.title || t.topic || 'ประเด็นสำคัญ';
                const desc = cleanRedundantText(t.description || t.description_a || '');
                html += `
                    <div class="content-topic-card topic-card-a">
                        <div class="topic-card-title">📌 ${escapeHtml(title)}</div>
                        <div class="topic-card-desc">${escapeHtml(desc || '-')}</div>
                    </div>
                `;
            });
            if (videoATopics.length > MAX_TOPICS_DEFAULT) {
                const rem = videoATopics.length - MAX_TOPICS_DEFAULT;
                const btnLabel = section02VideoAExpanded ? 'ซ่อนเพิ่มเติม' : `ดูเพิ่มเติม (${rem})`;
                html += `
                    <button type="button" id="btnToggleVideoATopics" class="btn-toggle-column-topics">
                        ${btnLabel}
                    </button>
                `;
            }
        } else {
            html += '<p class="text-desc" style="font-size: 0.85rem; padding: 0.5rem 0;">ไม่พบข้อมูลประเด็นสำคัญใน Video A</p>';
        }
        html += `
                    </div>
                </div>

                <!-- Video B Column -->
                <div class="topics-column side-b">
                    <div class="column-header">
                        <span class="video-badge badge-b">VIDEO B</span>
                        <h3 class="column-title">ประเด็นสำคัญใน Video B</h3>
                    </div>
                    <div class="topic-cards-list">
        `;
        if (videoBTopics.length > 0) {
            visibleBTopics.forEach(t => {
                const title = t.title || t.topic || 'ประเด็นสำคัญ';
                const desc = cleanRedundantText(t.description || t.description_b || '');
                html += `
                    <div class="content-topic-card topic-card-b">
                        <div class="topic-card-title">📌 ${escapeHtml(title)}</div>
                        <div class="topic-card-desc">${escapeHtml(desc || '-')}</div>
                    </div>
                `;
            });
            if (videoBTopics.length > MAX_TOPICS_DEFAULT) {
                const rem = videoBTopics.length - MAX_TOPICS_DEFAULT;
                const btnLabel = section02VideoBExpanded ? 'ซ่อนเพิ่มเติม' : `ดูเพิ่มเติม (${rem})`;
                html += `
                    <button type="button" id="btnToggleVideoBTopics" class="btn-toggle-column-topics">
                        ${btnLabel}
                    </button>
                `;
            }
        } else {
            html += '<p class="text-desc" style="font-size: 0.85rem; padding: 0.5rem 0;">ไม่พบข้อมูลประเด็นสำคัญใน Video B</p>';
        }
        html += `
                    </div>
                </div>
            </div>
        `;

        // BOTTOM HALF: Derived Clear Differences
        const MAX_DIFF_DEFAULT = 3;
        const visibleKeyDifferences = section02DiffExpanded ? keyDifferences : keyDifferences.slice(0, MAX_DIFF_DEFAULT);

        html += `
            <div class="differences-block">
                <div class="differences-header">
                    <h3>⚖️ ความแตกต่างที่ชัดเจน</h3>
                    <span class="differences-subtitle">ข้อค้นพบที่เกิดจากการนำประเด็นของทั้งสองวิดีโอมาวิเคราะห์ร่วมกัน</span>
                </div>
                <div class="differences-cards-list">
        `;
        if (keyDifferences.length > 0) {
            visibleKeyDifferences.forEach((diff, idx) => {
                const title = diff.title || `ความแตกต่างที่ ${idx + 1}`;
                const videoA = diff.video_a;
                const videoB = diff.video_b;
                const significance = diff.significance;
                const desc = diff.description;

                html += `
                    <div class="clear-difference-card">
                        <div class="diff-card-header">
                            <h4 class="diff-card-title">${escapeHtml(title)}</h4>
                        </div>
                `;

                if (videoA || videoB) {
                    html += `
                        <div class="diff-evidence-grid">
                            <div class="diff-evidence-box side-a">
                                <div class="diff-evidence-header">
                                    <span class="video-badge badge-a">🔵 VIDEO A</span>
                                </div>
                                <div class="diff-evidence-content">${escapeHtml(videoA || 'ไม่พบการกล่าวถึงประเด็นนี้ใน Video A')}</div>
                            </div>
                            <div class="diff-evidence-box side-b">
                                <div class="diff-evidence-header">
                                    <span class="video-badge badge-b">🩷 VIDEO B</span>
                                </div>
                                <div class="diff-evidence-content">${escapeHtml(videoB || 'ไม่พบการกล่าวถึงประเด็นนี้ใน Video B')}</div>
                            </div>
                        </div>
                    `;
                } else if (desc) {
                    html += `
                        <div class="diff-card-desc">${escapeHtml(desc)}</div>
                    `;
                }

                if (significance) {
                    html += `
                        <div class="diff-significance-box">
                            <div class="diff-significance-header">
                                <span class="diff-significance-icon">💡</span>
                                <span class="diff-significance-label">ทำไมความแตกต่างนี้สำคัญ</span>
                            </div>
                            <div class="diff-significance-content">${escapeHtml(significance)}</div>
                        </div>
                    `;
                }

                html += `</div>`;
            });

            if (keyDifferences.length > MAX_DIFF_DEFAULT) {
                const remDiff = keyDifferences.length - MAX_DIFF_DEFAULT;
                const btnDiffLabel = section02DiffExpanded ? 'ซ่อนความแตกต่างเพิ่มเติม' : `ดูความแตกต่างเพิ่มเติม (${remDiff})`;
                html += `
                    <button type="button" id="btnToggleDifferences" class="btn-toggle-column-topics">
                        ${btnDiffLabel}
                    </button>
                `;
            }
        } else {
            // NO MEANINGFUL DIFFERENCE STATE
            html += `
                <div class="diff-empty-state">
                    <div class="diff-empty-icon">⚖️</div>
                    <div class="diff-empty-title">ไม่พบความแตกต่างเพิ่มเติมที่มีนัยสำคัญ</div>
                    <div class="diff-empty-subtitle">ความแตกต่างหลักของวิดีโอทั้งสองครอบคลุมอยู่ในภาพรวมการเปรียบเทียบแล้ว</div>
                </div>
            `;
        }

        html += `
                </div>
            </div>
        </div>
        `;

        container.innerHTML = html;

        const btnToggleA = document.getElementById('btnToggleVideoATopics');
        if (btnToggleA) {
            btnToggleA.onclick = () => {
                section02VideoAExpanded = !section02VideoAExpanded;
                renderSection02TopicsDifferences(topicsList, contract);
            };
        }

        const btnToggleB = document.getElementById('btnToggleVideoBTopics');
        if (btnToggleB) {
            btnToggleB.onclick = () => {
                section02VideoBExpanded = !section02VideoBExpanded;
                renderSection02TopicsDifferences(topicsList, contract);
            };
        }

        const btnToggleDiff = document.getElementById('btnToggleDifferences');
        if (btnToggleDiff) {
            btnToggleDiff.onclick = () => {
                section02DiffExpanded = !section02DiffExpanded;
                renderSection02TopicsDifferences(topicsList, contract);
            };
        }
    }

    function getCategoryBadgeMeta(cat) {
        switch (cat) {
            case 'shared':
                return { label: 'เหมือนกัน', icon: '💡', cssClass: 'badge-cat-shared' };
            case 'difference':
                return { label: 'แตกต่าง', icon: '⚖️', cssClass: 'badge-cat-diff' };
            case 'unique_a':
                return { label: 'เฉพาะ Video A', icon: '🔹', cssClass: 'badge-cat-unique-a' };
            case 'unique_b':
                return { label: 'เฉพาะ Video B', icon: '🔹', cssClass: 'badge-cat-unique-b' };
            default:
                return { label: 'เปรียบเทียบ', icon: '📌', cssClass: 'badge-cat-shared' };
        }
    }

    // Stopwords set for frequency calculation
    const THAI_ENGLISH_STOPWORDS = new Set([
        'ครับ', 'ค่ะ', 'คือ', 'แล้ว', 'แบบ', 'มัน', 'ที่', 'จะ', 'ให้', 'ได้', 'ก็', 'และ',
        'ใน', 'มี', 'การ', 'ความ', 'เป็น', 'จาก', 'บน', 'กับ', 'โดย', 'หรือ', 'เพื่อ',
        'งาน', 'ทำ', 'ไป', 'มา', 'อยู่', 'นี้', 'นั้น', 'มาก', 'ขึ้น', 'ลง', 'ไม่',
        'ใช่', 'ว่า', 'ต้อง', 'อาจ', 'ถ้า', 'แต่', 'the', 'is', 'a', 'an', 'and',
        'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from',
        'up', 'about', 'into', 'over', 'after', 'this', 'that', 'it', 'its'
    ]);

    // Term Synonym Normalization Mapping (deterministic, 0 AI calls)
    const SYNONYM_MAP = {
        'artificial intelligence': ["ai", "artificial intelligence", "ปัญญาประดิษฐ์", "เอไอ", "llm", "โมเดล"],
        'ปัญญาประดิษฐ์': ["ai", "artificial intelligence", "ปัญญาประดิษฐ์", "เอไอ", "llm", "โมเดล"],
        'machine learning': ["ml", "machine learning"],
        'เอไอ': ["ai", "artificial intelligence", "ปัญญาประดิษฐ์", "เอไอ", "llm", "โมเดล"],
        "ai": ["ai", "artificial intelligence", "ปัญญาประดิษฐ์", "เอไอ", "llm", "โมเดล"],
        "agent": ["agent", "agents", "เอเจนต์", "ai agent"],
        "tiktok": ["tiktok", "ติ๊กต๊อก", "ทิกทอก"],
        "youtube": ["youtube", "ยูทูป", "ยูทูบ"],
        "python": ["python", "ไพธอน"],
        "data": ["data", "ข้อมูล"],
        "prompt": ["prompt", "พรอมต์"],
        "robot": ["robot", "หุ่นยนต์"],
        "automation": ["automation", "ออโตเมชัน", "ระบบอัตโนมัติ"],
        "การดำเนินคดี": ["การดำเนินคดี", "ฟ้อง", "โจทก์", "กฎหมาย", "ศาล", "คดี"],
        "คดีความ": ["การดำเนินคดี", "ฟ้อง", "โจทก์", "กฎหมาย", "ศาล", "คดี"],
        "กฎหมาย": ["การดำเนินคดี", "ฟ้อง", "โจทก์", "กฎหมาย", "ศาล", "คดี"]
    };

    let activeConceptFocus = null;

    function countTranscriptTermFrequency(term, transcriptList) {
        if (!term || !transcriptList || !Array.isArray(transcriptList)) return 0;
        const cleanTerm = term.trim().toLowerCase();
        if (THAI_ENGLISH_STOPWORDS.has(cleanTerm)) return 0;

        let count = 0;
        transcriptList.forEach(seg => {
            if (!seg || !seg.text) return;
            const txt = String(seg.text).toLowerCase();
            if (txt.includes(cleanTerm)) {
                const matches = txt.split(cleanTerm).length - 1;
                count += matches;
            }
        });
        return count;
    }

    function groupAdjacentSegments(segments, totalDuration, maxGap = 15.0) {
        if (!segments || segments.length === 0) return [];
        const sorted = [...segments].sort((a, b) => parseFloat(a.start) - parseFloat(b.start));
        const merged = [];
        let curr = {
            start: parseFloat(sorted[0].start),
            end: parseFloat(sorted[0].end || sorted[0].start + 1.0)
        };

        for (let i = 1; i < sorted.length; i++) {
            const segStart = parseFloat(sorted[i].start);
            const segEnd = parseFloat(sorted[i].end || segStart + 1.0);
            if (segStart - curr.end <= maxGap) {
                curr.end = Math.max(curr.end, segEnd);
            } else {
                merged.push(curr);
                curr = { start: segStart, end: segEnd };
            }
        }
        merged.push(curr);

        return merged.map(r => {
            const pctStart = Math.min(100, Math.max(0, (r.start / totalDuration) * 100.0));
            const pctEnd = Math.min(100, Math.max(0, (r.end / totalDuration) * 100.0));
            return {
                start: r.start,
                end: r.end,
                pctStart: Math.round(pctStart * 10) / 10,
                pctEnd: Math.round(pctEnd * 10) / 10,
                formattedStr: `${formatSeconds(r.start)}–${formatSeconds(r.end)}`,
                pctStr: `${Math.round(pctStart)}%–${Math.round(pctEnd)}%`
            };
        });
    }

    function getTranscriptList(snap) {
        if (!snap) return [];
        let t = snap.transcript || snap.transcript_segments || snap.segments || snap.timeline || snap.transcript_json || [];
        if (typeof t === 'string') {
            try { t = JSON.parse(t); } catch (e) { t = []; }
        }
        if (!Array.isArray(t)) return [];
        return t;
    }

    let conceptsExpandState = {
        A: false,
        SHARED: false,
        B: false
    };

    let _section07BucketConceptsA = new Map();
    let _section07BucketConceptsB = new Map();

    function extractConceptCandidates(contract, snapA, snapB) {
        const listA = getTranscriptList(snapA);
        const listB = getTranscriptList(snapB);
        const durA = Math.max(1, parseFloat(snapA ? (snapA.duration_seconds || snapA.duration || 1) : 1));
        const durB = Math.max(1, parseFloat(snapB ? (snapB.duration_seconds || snapB.duration || 1) : 1));

        const candidatesMap = new Map();

        function addCandidate(rawTitle, source, defaultSide, extraTerms = []) {
            if (!rawTitle || typeof rawTitle !== 'string') return;
            const cleanTitle = rawTitle.trim();
            if (cleanTitle.length < 2) return;

            const normalizedKey = cleanTitle.toLowerCase();
            let synonyms = [cleanTitle];

            for (const [key, synList] of Object.entries(SYNONYM_MAP)) {
                if (synList.some(s => s.toLowerCase() === normalizedKey || normalizedKey.includes(s.toLowerCase()))) {
                    synList.forEach(s => {
                        if (!synonyms.some(existing => existing.toLowerCase() === s.toLowerCase())) {
                            synonyms.push(s);
                        }
                    });
                }
            }

            extraTerms.forEach(t => {
                if (t && typeof t === 'string' && t.trim().length > 1 && !synonyms.some(s => s.toLowerCase() === t.trim().toLowerCase())) {
                    synonyms.push(t.trim());
                }
            });

            if (!candidatesMap.has(normalizedKey)) {
                candidatesMap.set(normalizedKey, {
                    title: cleanTitle,
                    source: source,
                    defaultSide: defaultSide,
                    related_terms: synonyms,
                    fromSemantic: ['shared_topic', 'unique_topic', 'difference', 'viewpoint_relationship'].includes(source)
                });
            }
        }

        (contract.shared_topics || []).forEach(item => {
            if (item.topic) addCandidate(item.topic, 'shared_topic', 'SHARED');
        });

        (contract.key_differences || []).forEach(item => {
            if (item.dimension) addCandidate(item.dimension, 'difference', 'SHARED');
        });

        const uniqueObj = contract.unique_topics || {};
        (uniqueObj.video_a || uniqueObj.video_a_unique || []).forEach(item => {
            if (item.topic) addCandidate(item.topic, 'unique_topic', 'A');
        });
        (uniqueObj.video_b || uniqueObj.video_b_unique || []).forEach(item => {
            if (item.topic) addCandidate(item.topic, 'unique_topic', 'B');
        });

        (contract.viewpoint_relationships || []).forEach(item => {
            if (item.topic) addCandidate(item.topic, 'viewpoint_relationship', 'SHARED');
        });

        const kwObj = contract.keyword_comparison || {};
        (kwObj.shared || []).forEach(kw => addCandidate(kw, 'keyword', 'SHARED'));
        (kwObj.video_a_only || []).forEach(kw => addCandidate(kw, 'keyword', 'A'));
        (kwObj.video_b_only || []).forEach(kw => addCandidate(kw, 'keyword', 'B'));

        const conceptsList = [];

        candidatesMap.forEach((cand, key) => {
            const termsToSearch = cand.related_terms;

            const matchedSegsA = [];
            let countA = 0;
            listA.forEach(seg => {
                if (!seg) return;
                const textRaw = seg.text || seg.content || seg.phrase || seg.raw_text || (typeof seg === 'string' ? seg : '');
                if (!textRaw) return;
                const textLower = String(textRaw).toLowerCase();
                let matchesInSeg = 0;
                termsToSearch.forEach(term => {
                    const tLower = term.toLowerCase();
                    if (THAI_ENGLISH_STOPWORDS.has(tLower)) return;
                    if (textLower.includes(tLower)) {
                        matchesInSeg += textLower.split(tLower).length - 1;
                    }
                });
                if (matchesInSeg > 0) {
                    countA += matchesInSeg;
                    matchedSegsA.push({
                        start: parseFloat(seg.start ?? seg.startTime ?? seg.start_time ?? 0),
                        end: parseFloat(seg.end ?? seg.endTime ?? seg.end_time ?? (parseFloat(seg.start || 0) + 1.0)),
                        text: textRaw
                    });
                }
            });

            const matchedSegsB = [];
            let countB = 0;
            listB.forEach(seg => {
                if (!seg) return;
                const textRaw = seg.text || seg.content || seg.phrase || seg.raw_text || (typeof seg === 'string' ? seg : '');
                if (!textRaw) return;
                const textLower = String(textRaw).toLowerCase();
                let matchesInSeg = 0;
                termsToSearch.forEach(term => {
                    const tLower = term.toLowerCase();
                    if (THAI_ENGLISH_STOPWORDS.has(tLower)) return;
                    if (textLower.includes(tLower)) {
                        matchesInSeg += textLower.split(tLower).length - 1;
                    }
                });
                if (matchesInSeg > 0) {
                    countB += matchesInSeg;
                    matchedSegsB.push({
                        start: parseFloat(seg.start ?? seg.startTime ?? seg.start_time ?? 0),
                        end: parseFloat(seg.end ?? seg.endTime ?? seg.end_time ?? (parseFloat(seg.start || 0) + 1.0)),
                        text: textRaw
                    });
                }
            });

            // Pure keyword candidates without transcript mentions get filtered out
            if (!cand.fromSemantic && countA === 0 && countB === 0) return;

            const rangesA = groupAdjacentSegments(matchedSegsA, durA, 15.0);
            const rangesB = groupAdjacentSegments(matchedSegsB, durB, 15.0);

            // Grouping logic (Part 1)
            let finalSide = cand.defaultSide;
            let isSemanticOnly = false;
            let isSemanticShared = false;

            if (countA > 0 && countB > 0) {
                finalSide = 'SHARED';
            } else if (countA > 0 && countB === 0) {
                if (cand.defaultSide === 'SHARED' && cand.fromSemantic) {
                    finalSide = 'SHARED';
                    isSemanticShared = true;
                } else {
                    finalSide = 'A';
                }
            } else if (countB > 0 && countA === 0) {
                if (cand.defaultSide === 'SHARED' && cand.fromSemantic) {
                    finalSide = 'SHARED';
                    isSemanticShared = true;
                } else {
                    finalSide = 'B';
                }
            } else if (countA === 0 && countB === 0) {
                isSemanticOnly = true;
                if (cand.defaultSide === 'SHARED') {
                    isSemanticShared = true;
                }
                finalSide = cand.defaultSide;
            }

            let importance = 'low';
            if (cand.fromSemantic || (countA + countB) >= 5) {
                importance = 'high';
            } else if ((countA + countB) >= 2) {
                importance = 'medium';
            }

            if (importance === 'low' && !cand.fromSemantic) return;

            const displayRelated = termsToSearch.filter(t => t.toLowerCase() !== cand.title.toLowerCase());

            conceptsList.push({
                id: 'concept_' + Math.random().toString(36).substring(2, 9),
                title: cand.title,
                side: finalSide,
                related_terms: displayRelated,
                mentions_a: countA,
                mentions_b: countB,
                ranges_a: rangesA,
                ranges_b: rangesB,
                importance: importance,
                fromSemantic: cand.fromSemantic,
                isSemanticOnly: isSemanticOnly,
                isSemanticShared: isSemanticShared,
                source: cand.source
            });
        });

        return conceptsList;
    }
    window.extractConceptCandidates = extractConceptCandidates;

    function precomputeSection07BucketMappings(allConcepts, snapA, snapB) {
        _section07BucketConceptsA = new Map();
        _section07BucketConceptsB = new Map();

        const dataA = calculateSpeechDensityData(snapA);
        const dataB = calculateSpeechDensityData(snapB);

        if (dataA && dataA.hasData) {
            dataA.buckets.forEach(b => {
                const matched = [];
                allConcepts.forEach(c => {
                    if (c.side === 'A' || c.side === 'SHARED') {
                        const hasOverlap = (c.ranges_a || []).some(r => r.start <= b.endTime && r.end >= b.startTime);
                        if (hasOverlap) matched.push(c);
                    }
                });
                _section07BucketConceptsA.set(b.index, matched);
            });
        }

        if (dataB && dataB.hasData) {
            dataB.buckets.forEach(b => {
                const matched = [];
                allConcepts.forEach(c => {
                    if (c.side === 'B' || c.side === 'SHARED') {
                        const hasOverlap = (c.ranges_b || []).some(r => r.start <= b.endTime && r.end >= b.startTime);
                        if (hasOverlap) matched.push(c);
                    }
                });
                _section07BucketConceptsB.set(b.index, matched);
            });
        }
    }

    function renderSection06KeyConceptsAnalysis(contract = {}, snapA = null, snapB = null) {
        snapA = snapA || selectedSnapshotA;
        snapB = snapB || selectedSnapshotB;

        const gridEl = document.getElementById('keyConceptsGrid');
        const listAEl = document.getElementById('conceptsListA');
        const listSharedEl = document.getElementById('conceptsListShared');
        const listBEl = document.getElementById('conceptsListB');

        if (!gridEl) return;

        const allConcepts = extractConceptCandidates(contract, snapA, snapB);

        const allA = allConcepts.filter(c => c.side === 'A')
            .sort((a, b) => (b.importance === 'high' ? 1 : 0) - (a.importance === 'high' ? 1 : 0) || (b.mentions_a - a.mentions_a) || a.title.localeCompare(b.title));

        const allShared = allConcepts.filter(c => c.side === 'SHARED')
            .sort((a, b) => (b.importance === 'high' ? 1 : 0) - (a.importance === 'high' ? 1 : 0) || ((b.mentions_a + b.mentions_b) - (a.mentions_a + a.mentions_b)) || a.title.localeCompare(b.title));

        const allB = allConcepts.filter(c => c.side === 'B')
            .sort((a, b) => (b.importance === 'high' ? 1 : 0) - (a.importance === 'high' ? 1 : 0) || (b.mentions_b - a.mentions_b) || a.title.localeCompare(b.title));

        window._currentKeyConceptsMap = new Map();
        allConcepts.forEach(c => window._currentKeyConceptsMap.set(c.id, c));

        window.extractConceptCandidates = extractConceptCandidates;
        window.calculateSpeechDensityData = calculateSpeechDensityData;

        precomputeSection07BucketMappings(allConcepts, snapA, snapB);

        function updateColumnRendering() {
            if (listAEl) {
                const visibleA = conceptsExpandState.A ? allA : allA.slice(0, 3);
                listAEl.innerHTML = renderConceptCardList(visibleA, 'A', allA.length > 3, conceptsExpandState.A, allA.length);
            }
            if (listBEl) {
                const visibleB = conceptsExpandState.B ? allB : allB.slice(0, 3);
                listBEl.innerHTML = renderConceptCardList(visibleB, 'B', allB.length > 3, conceptsExpandState.B, allB.length);
            }

            if (allShared.length === 0) {
                gridEl.classList.add('has-no-shared');
                if (listSharedEl) {
                    listSharedEl.innerHTML = `
                        <div class="empty-shared-card">
                            <strong>ไม่พบประเด็นที่มีการกล่าวถึงโดยตรงร่วมกัน</strong>
                            <p style="margin-top:0.35rem; font-size:0.8rem; color:var(--text-muted, #94A3B8);">
                                เนื้อหาของสองวิดีโอมีจุดเน้นแตกต่างกันค่อนข้างชัดเจน
                            </p>
                        </div>
                    `;
                }
            } else {
                gridEl.classList.remove('has-no-shared');
                if (listSharedEl) {
                    const visibleShared = conceptsExpandState.SHARED ? allShared : allShared.slice(0, 3);
                    listSharedEl.innerHTML = renderConceptCardList(visibleShared, 'SHARED', allShared.length > 3, conceptsExpandState.SHARED, allShared.length);
                }
            }

            gridEl.querySelectorAll('.btn-toggle-expand').forEach(btn => {
                btn.onclick = (e) => {
                    e.stopPropagation();
                    const col = btn.getAttribute('data-column');
                    if (col) {
                        conceptsExpandState[col] = !conceptsExpandState[col];
                        updateColumnRendering();
                    }
                };
            });

            gridEl.querySelectorAll('.btn-view-on-graph').forEach(btn => {
                btn.onclick = (e) => {
                    e.stopPropagation();
                    const conceptId = btn.getAttribute('data-concept-id');
                    const conceptObj = window._currentKeyConceptsMap ? window._currentKeyConceptsMap.get(conceptId) : null;
                    if (conceptObj) {
                        activeConceptFocus = conceptObj;
                        renderSection07SpeechDensity(snapA, snapB);
                        const sec07 = document.getElementById('contentmap-section');
                        if (sec07) {
                            sec07.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        }
                    }
                };
            });
        }

        updateColumnRendering();
    }

    function getCleanVideoTitle(snap, defaultLabel) {
        if (!snap) return defaultLabel;
        let t = snap.title || snap.display_title || snap.filename || '';
        t = String(t).trim();
        if (!t || t.startsWith('http://') || t.startsWith('https://') || t.startsWith('www.')) {
            return defaultLabel;
        }
        return t;
    }

    function renderSparklineSvg(ranges, strokeColor) {
        if (!ranges || ranges.length === 0) {
            return '<span class="mini-dist-empty-inline">ไม่พบตำแหน่งเวลาที่ชัดเจน</span>';
        }
        const numBuckets = 10;
        const bucketCounts = new Array(numBuckets).fill(0);

        ranges.forEach(r => {
            const startPct = Math.max(0, Math.min(100, parseFloat(r.pctStart || 0)));
            const endPct = Math.max(0, Math.min(100, parseFloat(r.pctEnd || 0)));
            for (let i = 0; i < numBuckets; i++) {
                const bStart = i * 10;
                const bEnd = (i + 1) * 10;
                const overlap = Math.max(0, Math.min(endPct, bEnd) - Math.max(startPct, bStart));
                if (overlap > 0) {
                    bucketCounts[i] += (overlap / 10.0);
                }
            }
        });

        const maxVal = Math.max(0.1, ...bucketCounts);
        const svgWidth = 110;
        const svgHeight = 14;
        const barWidth = Math.floor(svgWidth / numBuckets) - 2;

        let rects = '';
        bucketCounts.forEach((val, i) => {
            const h = val > 0 ? Math.max(3, Math.round((val / maxVal) * (svgHeight - 2))) : 2;
            const x = i * (barWidth + 2);
            const y = svgHeight - h;
            const opacity = val > 0 ? 0.85 : 0.2;
            rects += `<rect x="${x}" y="${y}" width="${barWidth}" height="${h}" rx="1.5" fill="${strokeColor}" opacity="${opacity}" />`;
        });

        return `
            <div class="mini-sparkline-wrapper">
                <span class="sparkline-tick">0%</span>
                <svg viewBox="0 0 ${svgWidth} ${svgHeight}" class="mini-sparkline-svg">
                    ${rects}
                </svg>
                <span class="sparkline-tick">100%</span>
            </div>
        `;
    }

    function renderMiniConceptDistribution(c) {
        const hasRangesA = c.ranges_a && c.ranges_a.length > 0;
        const hasRangesB = c.ranges_b && c.ranges_b.length > 0;

        if (!hasRangesA && !hasRangesB) {
            return `<div class="concept-mini-dist-empty">ไม่พบตำแหน่งเวลาที่ชัดเจน</div>`;
        }

        if (c.side === 'A') {
            return `
                <div class="concept-mini-dist-container">
                    <div class="mini-dist-row">
                        ${renderSparklineSvg(c.ranges_a, '#3B82F6')}
                    </div>
                </div>
            `;
        } else if (c.side === 'B') {
            return `
                <div class="concept-mini-dist-container">
                    <div class="mini-dist-row">
                        ${renderSparklineSvg(c.ranges_b, '#EC4899')}
                    </div>
                </div>
            `;
        } else {
            return `
                <div class="concept-mini-dist-container">
                    <div class="mini-dist-row">
                        <span class="mini-dist-label slot-a">A</span>
                        ${renderSparklineSvg(c.ranges_a, '#3B82F6')}
                    </div>
                    <div class="mini-dist-row">
                        <span class="mini-dist-label slot-b">B</span>
                        ${renderSparklineSvg(c.ranges_b, '#EC4899')}
                    </div>
                </div>
            `;
        }
    }

    function renderConceptCardList(concepts, side, hasMore = false, isExpanded = false, totalCount = 0) {
        if (!concepts || concepts.length === 0) {
            let emptyMsg = 'ไม่มีประเด็นเฉพาะ';
            if (side === 'A') emptyMsg = 'ไม่พบประเด็นเด่นที่มีการกล่าวถึงโดยตรงใน Video A';
            else if (side === 'B') emptyMsg = 'ไม่พบประเด็นเด่นที่มีการกล่าวถึงโดยตรงใน Video B';
            else emptyMsg = 'ไม่พบประเด็นที่มีการกล่าวถึงโดยตรงร่วมกัน';

            return `<div class="empty-shared-card" style="font-size:0.82rem; padding:0.85rem;"><strong>${emptyMsg}</strong></div>`;
        }

        let cardsHtml = concepts.map(c => {
            const iconMap = {
                'shared_topic': '💡',
                'difference': '⚖️',
                'unique_topic': '🔹',
                'viewpoint_relationship': '🧠',
                'keyword': '🏷️'
            };
            const icon = iconMap[c.source] || '📌';

            let statusBadgeHtml = '';
            if (c.isSemanticShared) {
                statusBadgeHtml = `<span class="importance-badge semantic-shared">🧠 ประเด็นร่วมเชิงความหมาย</span>`;
            } else if (c.isSemanticOnly) {
                statusBadgeHtml = `<span class="importance-badge semantic">🧠 ประเด็นเชิงความหมาย</span>`;
            } else {
                const importanceText = c.importance === 'high' ? '● สูง' : '● ปานกลาง';
                const importanceClass = c.importance === 'high' ? 'high' : 'medium';
                statusBadgeHtml = `<span class="importance-badge ${importanceClass}">${importanceText}</span>`;
            }

            let originBadgeHtml = '';
            if (c.fromSemantic) {
                originBadgeHtml = `<span class="origin-badge">🧠 ความสำคัญจากการวิเคราะห์</span>`;
            } else {
                originBadgeHtml = `<span class="origin-badge">🎙️ การกล่าวถึงจาก Transcript</span>`;
            }

            let termsTokensHtml = '';
            if (c.related_terms && c.related_terms.length > 0) {
                const maxVisible = 3;
                const visible = c.related_terms.slice(0, maxVisible);
                const extraCount = c.related_terms.length - maxVisible;
                const tokens = visible.map(t => `<span class="term-chip">${escapeHtml(t)}</span>`).join('');
                const extraChip = extraCount > 0 ? `<span class="term-chip chip-overflow">+${extraCount}</span>` : '';
                termsTokensHtml = `
                    <div class="concept-terms-chips">
                        ${tokens}${extraChip}
                    </div>
                `;
            }

            let mentionsHtml = '';
            if (c.isSemanticOnly && c.mentions_a === 0 && c.mentions_b === 0) {
                mentionsHtml = `<div class="concept-mentions"><span class="badge-slot slot-semantic">🎙️ ไม่พบคำกล่าวถึงโดยตรง</span></div>`;
            } else if (c.side === 'A') {
                mentionsHtml = `<div class="concept-mentions"><span class="badge-slot slot-a">🎙️ กล่าวถึงใน Video A: ${c.mentions_a} ครั้ง</span></div>`;
            } else if (c.side === 'B') {
                mentionsHtml = `<div class="concept-mentions"><span class="badge-slot slot-b">🎙️ กล่าวถึงใน Video B: ${c.mentions_b} ครั้ง</span></div>`;
            } else {
                if (c.mentions_a > 0 && c.mentions_b > 0) {
                    mentionsHtml = `<div class="concept-mentions"><span class="badge-slot slot-a">🎙️ Video A: ${c.mentions_a} ครั้ง</span><span class="badge-slot slot-b">Video B: ${c.mentions_b} ครั้ง</span></div>`;
                } else if (c.mentions_a > 0) {
                    mentionsHtml = `<div class="concept-mentions"><span class="badge-slot slot-a">🎙️ Video A: ${c.mentions_a} ครั้ง (ไม่พบใน B)</span></div>`;
                } else if (c.mentions_b > 0) {
                    mentionsHtml = `<div class="concept-mentions"><span class="badge-slot slot-b">🎙️ Video B: ${c.mentions_b} ครั้ง (ไม่พบใน A)</span></div>`;
                } else {
                    mentionsHtml = `<div class="concept-mentions"><span class="badge-slot slot-semantic">🎙️ ไม่พบคำกล่าวถึงโดยตรง</span></div>`;
                }
            }

            let noteLabelHtml = '';
            if (c.isSemanticShared && (c.mentions_a === 0 || c.mentions_b === 0)) {
                noteLabelHtml = `<div class="semantic-note-label">AI วิเคราะห์ว่ามีความเกี่ยวข้องร่วมกัน แต่ไม่พบคำกล่าวถึงโดยตรงครบทั้งสองวิดีโอ</div>`;
            } else if (c.isSemanticOnly) {
                noteLabelHtml = `<div class="semantic-note-label">ไม่พบการกล่าวถึงด้วยคำตรงใน Transcript</div>`;
            }

            const ranges = c.side === 'A' ? c.ranges_a : (c.side === 'B' ? c.ranges_b : [...(c.ranges_a || []), ...(c.ranges_b || [])]);
            let rangesHtml = '';
            if (ranges && ranges.length > 0) {
                const firstRange = ranges[0];
                const lastRange = ranges[ranges.length - 1];
                const pctRangeStr = `${firstRange.pctStart}%–${lastRange.pctEnd}%`;
                rangesHtml = `
                    <div class="concept-time-ranges">
                        ช่วงเด่น ${pctRangeStr} (${firstRange.formattedStr})
                    </div>
                `;
            } else {
                rangesHtml = `
                    <div class="concept-time-ranges empty-range">
                        ไม่พบตำแหน่งเวลาที่ชัดเจน
                    </div>
                `;
            }

            const miniDistHtml = (c.isSemanticOnly && (!ranges || ranges.length === 0)) ? '' : renderMiniConceptDistribution(c);

            return `
                <div class="concept-card side-${c.side.toLowerCase()}">
                    <div class="concept-card-header">
                        <h4 class="concept-title">${icon} ${escapeHtml(c.title)}</h4>
                        <div class="concept-badges-wrapper">
                            ${statusBadgeHtml}
                        </div>
                    </div>
                    
                    <div class="concept-origin-wrapper">
                        ${originBadgeHtml}
                    </div>

                    ${termsTokensHtml}
                
                    ${mentionsHtml}
                    
                    ${noteLabelHtml}

                    ${miniDistHtml}

                    ${rangesHtml}
                
                    <div class="concept-card-actions">
                        <button type="button" class="btn btn-sm btn-outline btn-view-on-graph" data-concept-id="${c.id}">
                            ดูบนกราฟ →
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        if (hasMore) {
            const toggleText = isExpanded ? 'ซ่อนเพิ่มเติม' : `ดูเพิ่มเติม (${totalCount - 3})`;
            cardsHtml += `
                <div class="expand-concepts-wrapper" style="margin-top: 0.4rem; text-align: center;">
                    <button type="button" class="btn btn-sm btn-outline btn-toggle-expand" data-column="${side}" style="width: 100%; font-size: 0.8rem;">
                        ${toggleText}
                    </button>
                </div>
            `;
        }

        return cardsHtml;
    }

    function renderSection06KeywordComparison(kwObj = {}) {
        renderSection06KeyConceptsAnalysis({ keyword_comparison: kwObj }, selectedSnapshotA, selectedSnapshotB);
    }

    // --------------------------------------------------------------------------
    // Section 07 — Speech Density & Content Pace Graph Engine (Deterministic JS)
    // --------------------------------------------------------------------------
    let currentSpeechDensityMode = 'normalized'; // 'normalized' | 'realtime'

    function countWordsInText(text) {
        if (!text || typeof text !== 'string') return 0;
        const str = text.trim();
        if (!str) return 0;

        if (typeof Intl !== 'undefined' && typeof Intl.Segmenter === 'function') {
            const segmenter = new Intl.Segmenter('th', { granularity: 'word' });
            return Array.from(segmenter.segment(str)).filter(part => part.isWordLike).length;
        }

        const cleanStr = str.replace(/[.,!?;:"'()\[\]{}–—\-\n\r\t]/g, ' ');
        const thaiWords = cleanStr.match(/[\u0E00-\u0E7F]+/g) || [];
        const nonThaiWords = cleanStr.match(/[a-zA-Z0-9_]+/g) || [];

        return thaiWords.length + nonThaiWords.length;
    }

    function getAuthoritativeTranscriptSegments(snapshot) {
        if (!snapshot) return [];
        if (Array.isArray(snapshot.transcript) && snapshot.transcript.length > 0) {
            return snapshot.transcript;
        }
        if (Array.isArray(snapshot.transcript_segments) && snapshot.transcript_segments.length > 0) {
            return snapshot.transcript_segments;
        }
        if (Array.isArray(snapshot.timeline) && snapshot.timeline.length > 0) {
            return snapshot.timeline;
        }
        if (Array.isArray(snapshot.segments) && snapshot.segments.length > 0) {
            return snapshot.segments;
        }
        if (snapshot.transcript_json) {
            if (Array.isArray(snapshot.transcript_json)) return snapshot.transcript_json;
            if (typeof snapshot.transcript_json === 'object' && Array.isArray(snapshot.transcript_json.segments)) {
                return snapshot.transcript_json.segments;
            }
        }
        return [];
    }
    window.getAuthoritativeTranscriptSegments = getAuthoritativeTranscriptSegments;

    function calculateSpeechDensityData(snapshot) {
        if (!snapshot) return null;
        const segments = getAuthoritativeTranscriptSegments(snapshot);
        const latestEnd = segments.reduce((maxEnd, seg) => {
            const end = Number(seg && seg.end);
            return Number.isFinite(end) ? Math.max(maxEnd, end) : maxEnd;
        }, 0);
        const duration = Math.max(1.0, Number(snapshot.duration_seconds) || 0, latestEnd);
        const buckets = segments.map((seg, index) => {
            const parsedStart = Number(seg && seg.start);
            const parsedEnd = Number(seg && seg.end);
            const startTime = Number.isFinite(parsedStart) ? parsedStart : 0;
            const endTime = Number.isFinite(parsedEnd) ? parsedEnd : startTime;
            const segmentDuration = endTime - startTime;
            const wordCount = countWordsInText(String((seg && seg.text) || ''));
            const density = segmentDuration > 0 ? (wordCount / segmentDuration) * 10 : 0;
            const roundedDensity = Math.round(density * 10) / 10;
            return {
                index,
                segmentIndex: index,
                startTime,
                endTime,
                rawCount: roundedDensity,
                smoothedCount: roundedDensity,
                wordCount,
                segments: [seg],
                pctStart: (startTime / duration) * 100.0,
                pctEnd: (endTime / duration) * 100.0,
                pctMid: (((startTime + endTime) / 2.0) / duration) * 100.0
            };
        });

        let maxBucket = buckets.length ? buckets[0] : null;
        let minBucket = buckets.length ? buckets[0] : null;
        buckets.forEach(b => {
            if (!maxBucket || b.rawCount > maxBucket.rawCount) maxBucket = b;
            if (!minBucket || b.rawCount < minBucket.rawCount) minBucket = b;
        });

        let maxShiftVal = 0;
        let shiftBucket = null;
        for (let i = 1; i < buckets.length; i++) {
            const diff = Math.abs(buckets[i].smoothedCount - buckets[i - 1].smoothedCount);
            if (diff > maxShiftVal) {
                maxShiftVal = diff;
                shiftBucket = buckets[i];
            }
        }
        if (maxShiftVal < 1.5) shiftBucket = null;

        const thirdSize = Math.max(1, Math.floor(buckets.length / 3));
        const firstThird = buckets.slice(0, thirdSize);
        const midThird = buckets.slice(thirdSize, thirdSize * 2);
        const lastThird = buckets.slice(thirdSize * 2);

        const avgFirst = firstThird.reduce((acc, b) => acc + b.rawCount, 0) / (firstThird.length || 1);
        const avgMid = midThird.reduce((acc, b) => acc + b.rawCount, 0) / (midThird.length || 1);
        const avgLast = lastThird.reduce((acc, b) => acc + b.rawCount, 0) / (lastThird.length || 1);

        let paceClassification = 'กระจายค่อนข้างสม่ำเสมอ';
        if (avgFirst > 1.25 * ((avgMid + avgLast) / 2)) {
            paceClassification = 'หนาแน่นช่วงต้น';
        } else if (avgMid > 1.25 * ((avgFirst + avgLast) / 2)) {
            paceClassification = 'หนาแน่นช่วงกลาง';
        } else if (avgLast > 1.25 * ((avgFirst + avgMid) / 2)) {
            paceClassification = 'หนาแน่นช่วงท้าย';
        }

        const totalWords = buckets.reduce((acc, b) => acc + b.wordCount, 0);

        return {
            duration,
            buckets,
            maxBucket,
            minBucket,
            shiftBucket,
            maxShiftVal,
            paceClassification,
            totalWords: Math.round(totalWords),
            hasData: buckets.length > 0
        };
    }
    window.calculateSpeechDensityData = calculateSpeechDensityData;

    function renderSection04SpeechDensity(snapA = null, snapB = null) {
        snapA = snapA || selectedSnapshotA;
        snapB = snapB || selectedSnapshotB;

        const container = document.getElementById('speechDensitySvgContainer');
        const summaryGrid = document.getElementById('densitySummaryGrid');
        if (!container) return;

        const dataA = calculateSpeechDensityData(snapA);
        const dataB = calculateSpeechDensityData(snapB);

        const hasAnyData = (dataA && dataA.hasData) || (dataB && dataB.hasData);

        if (!hasAnyData) {
            container.innerHTML = '<div style="padding: 2rem; text-align: center; color: var(--text-muted); font-size: 0.95rem;">⚠️ ข้อมูลคำพูดไม่เพียงพอสำหรับสร้างกราฟความหนาแน่น</div>';
            if (summaryGrid) summaryGrid.innerHTML = '';
            return;
        }

        const btnNorm = document.getElementById('btnDensityModeNormalized');
        const btnReal = document.getElementById('btnDensityModeRealtime');

        if (btnNorm && btnReal) {
            btnNorm.onclick = () => {
                currentSpeechDensityMode = 'normalized';
                btnNorm.className = 'btn btn-sm btn-primary';
                btnReal.className = 'btn btn-sm btn-outline';
                renderDensitySvgGraph(dataA, dataB, snapA, snapB, 'normalized');
            };
            btnReal.onclick = () => {
                currentSpeechDensityMode = 'realtime';
                btnReal.className = 'btn btn-sm btn-primary';
                btnNorm.className = 'btn btn-sm btn-outline';
                renderDensitySvgGraph(dataA, dataB, snapA, snapB, 'realtime');
            };
        }

        renderDensitySvgGraph(dataA, dataB, snapA, snapB, currentSpeechDensityMode);
        renderDensitySummaryCards(dataA, dataB, snapA, snapB);
    }
    function renderSection07SpeechDensity(snapA = null, snapB = null) {
        return renderSection04SpeechDensity(snapA, snapB);
    }

    function renderDensitySvgGraph(dataA, dataB, snapA, snapB, mode) {
        const container = document.getElementById('speechDensitySvgContainer');
        if (!container) return;

        const bannerEl = document.getElementById('conceptFocusBanner');
        const bannerTitleEl = document.getElementById('conceptFocusTitle');
        const bannerSubEl = document.getElementById('conceptFocusSubtitle');
        const clearBtn = document.getElementById('btnClearConceptFocus');

        if (activeConceptFocus) {
            if (bannerEl) bannerEl.style.display = 'flex';
            if (bannerTitleEl) bannerTitleEl.textContent = activeConceptFocus.title;
            if (bannerSubEl) {
                if (activeConceptFocus.side === 'SHARED') {
                    const rA = activeConceptFocus.ranges_a;
                    const rB = activeConceptFocus.ranges_b;
                    const strA = rA && rA.length > 0 ? `Video A: ${activeConceptFocus.mentions_a} ครั้ง (${rA[0].pctStart}%–${rA[rA.length-1].pctEnd}%)` : `Video A: ${activeConceptFocus.mentions_a} ครั้ง`;
                    const strB = rB && rB.length > 0 ? `Video B: ${activeConceptFocus.mentions_b} ครั้ง (${rB[0].pctStart}%–${rB[rB.length-1].pctEnd}%)` : `Video B: ${activeConceptFocus.mentions_b} ครั้ง`;
                    bannerSubEl.textContent = `ประเด็นร่วม • ${strA} • ${strB}`;
                } else {
                    const ranges = activeConceptFocus.side === 'A' ? activeConceptFocus.ranges_a : activeConceptFocus.ranges_b;
                    const rangeStr = ranges && ranges.length > 0 ? `ช่วงหลัก: ${ranges[0].pctStart}%–${ranges[ranges.length-1].pctEnd}%` : 'ไม่พบตำแหน่งเวลาตรง';
                    const sideLabel = activeConceptFocus.side === 'A' ? 'Video A' : 'Video B';
                    const count = activeConceptFocus.side === 'A' ? activeConceptFocus.mentions_a : activeConceptFocus.mentions_b;
                    const countStr = count > 0 ? `${count} ครั้ง` : 'ไม่พบโดยตรง';
                    bannerSubEl.textContent = `${sideLabel}: ${countStr} • ${rangeStr}`;
                }
            }
            if (clearBtn) {
                clearBtn.onclick = () => {
                    activeConceptFocus = null;
                    renderSection07SpeechDensity(snapA, snapB);
                };
            }
        } else {
            if (bannerEl) bannerEl.style.display = 'none';
        }

        const cleanTitleA = getCleanVideoTitle(snapA, 'Video A');
        const cleanTitleB = getCleanVideoTitle(snapB, 'Video B');
        const dispA = cleanTitleA.length > 32 ? cleanTitleA.substring(0, 30) + '...' : cleanTitleA;
        const dispB = cleanTitleB.length > 32 ? cleanTitleB.substring(0, 30) + '...' : cleanTitleB;

        const svgWidth = 800;
        const svgHeight = 280;
        const padLeft = 55;
        const padRight = 30;
        const padTop = 40;
        const padBottom = 50;

        const chartW = svgWidth - padLeft - padRight;
        const chartH = svgHeight - padTop - padBottom;

        let maxY = 10;
        if (dataA && dataA.hasData) {
            dataA.buckets.forEach(b => { maxY = Math.max(maxY, b.smoothedCount, b.rawCount); });
        }
        if (dataB && dataB.hasData) {
            dataB.buckets.forEach(b => { maxY = Math.max(maxY, b.smoothedCount, b.rawCount); });
        }
        maxY = Math.ceil(maxY * 1.15);

        const getY = (val) => padTop + chartH - (val / maxY) * chartH;

        let svgContent = '';

        const gridSteps = 4;
        for (let i = 0; i <= gridSteps; i++) {
            const val = Math.round((maxY / gridSteps) * i);
            const y = getY(val);
            svgContent += `<line x1="${padLeft}" y1="${y}" x2="${svgWidth - padRight}" y2="${y}" stroke="var(--border-color, rgba(255,255,255,0.08))" stroke-dasharray="2 4" opacity="0.25" />`;
            svgContent += `<text x="${padLeft - 8}" y="${y + 4}" font-size="11" fill="var(--text-desc, #94A3B8)" text-anchor="end">${val}</text>`;
        }

        let pointsA = [];
        let pointsB = [];

        const maxDur = Math.max(
            dataA ? dataA.duration : 0,
            dataB ? dataB.duration : 0,
            1.0
        );

        if (mode === 'normalized') {
            for (let i = 0; i <= 4; i++) {
                const pct = i * 25;
                const x = padLeft + (pct / 100.0) * chartW;
                svgContent += `<line x1="${x}" y1="${padTop}" x2="${x}" y2="${padTop + chartH}" stroke="var(--border-color, rgba(255,255,255,0.08))" stroke-dasharray="2 4" opacity="0.25" />`;
                svgContent += `<text x="${x}" y="${padTop + chartH + 20}" font-size="11" fill="var(--text-desc, #94A3B8)" text-anchor="middle">${pct}%</text>`;
            }

            if (dataA && dataA.hasData) {
                dataA.buckets.forEach(b => {
                    const x = padLeft + (b.pctMid / 100.0) * chartW;
                    const y = getY(b.smoothedCount);
                    pointsA.push({ x, y, b, video: 'A', title: cleanTitleA });
                });
            }

            if (dataB && dataB.hasData) {
                dataB.buckets.forEach(b => {
                    const x = padLeft + (b.pctMid / 100.0) * chartW;
                    const y = getY(b.smoothedCount);
                    pointsB.push({ x, y, b, video: 'B', title: cleanTitleB });
                });
            }
        } else {
            const numLabels = 5;
            for (let i = 0; i <= numLabels; i++) {
                const sec = (maxDur / numLabels) * i;
                const x = padLeft + (sec / maxDur) * chartW;
                svgContent += `<line x1="${x}" y1="${padTop}" x2="${x}" y2="${padTop + chartH}" stroke="var(--border-color, rgba(255,255,255,0.08))" stroke-dasharray="2 4" opacity="0.25" />`;
                svgContent += `<text x="${x}" y="${padTop + chartH + 20}" font-size="11" fill="var(--text-desc, #94A3B8)" text-anchor="middle">${formatSeconds(sec)}</text>`;
            }

            if (dataA && dataA.hasData) {
                dataA.buckets.forEach(b => {
                    const midSec = (b.startTime + b.endTime) / 2.0;
                    const x = padLeft + (midSec / maxDur) * chartW;
                    const y = getY(b.smoothedCount);
                    pointsA.push({ x, y, b, video: 'A', title: cleanTitleA });
                });
            }

            if (dataB && dataB.hasData) {
                dataB.buckets.forEach(b => {
                    const midSec = (b.startTime + b.endTime) / 2.0;
                    const x = padLeft + (midSec / maxDur) * chartW;
                    const y = getY(b.smoothedCount);
                    pointsB.push({ x, y, b, video: 'B', title: cleanTitleB });
                });
            }
        }

        // Overlay Concept Range Highlights if Active (Part 5, 6, 12)
        if (activeConceptFocus) {
            const highlightA = activeConceptFocus.side === 'A' || activeConceptFocus.side === 'SHARED';
            const highlightB = activeConceptFocus.side === 'B' || activeConceptFocus.side === 'SHARED';

            if (highlightA && activeConceptFocus.ranges_a) {
                activeConceptFocus.ranges_a.forEach(r => {
                    let x1, x2;
                    if (mode === 'normalized') {
                        x1 = padLeft + (r.pctStart / 100.0) * chartW;
                        x2 = padLeft + (r.pctEnd / 100.0) * chartW;
                    } else {
                        x1 = padLeft + (r.start / maxDur) * chartW;
                        x2 = padLeft + (r.end / maxDur) * chartW;
                    }
                    const w = Math.max(8, x2 - x1);
                    svgContent += `
                        <rect x="${x1}" y="${padTop}" width="${w}" height="${chartH}"
                              fill="rgba(59, 130, 246, 0.18)" stroke="#3B82F6" stroke-width="1.5" stroke-dasharray="4 2" rx="4" />
                    `;
                });
            }

            if (highlightB && activeConceptFocus.ranges_b) {
                activeConceptFocus.ranges_b.forEach(r => {
                    let x1, x2;
                    if (mode === 'normalized') {
                        x1 = padLeft + (r.pctStart / 100.0) * chartW;
                        x2 = padLeft + (r.pctEnd / 100.0) * chartW;
                    } else {
                        x1 = padLeft + (r.start / maxDur) * chartW;
                        x2 = padLeft + (r.end / maxDur) * chartW;
                    }
                    const w = Math.max(8, x2 - x1);
                    svgContent += `
                        <rect x="${x1}" y="${padTop}" width="${w}" height="${chartH}"
                              fill="rgba(236, 72, 153, 0.18)" stroke="#EC4899" stroke-width="1.5" stroke-dasharray="4 2" rx="4" />
                    `;
                });
            }
        }

        function buildSmoothPath(pts) {
            if (!pts || pts.length === 0) return '';
            if (pts.length === 1) return `M ${pts[0].x} ${pts[0].y}`;

            let d = `M ${pts[0].x} ${pts[0].y}`;
            for (let i = 0; i < pts.length - 1; i++) {
                const p0 = pts[i];
                const p1 = pts[i + 1];
                const cx = (p0.x + p1.x) / 2;
                d += ` C ${cx} ${p0.y}, ${cx} ${p1.y}, ${p1.x} ${p1.y}`;
            }
            return d;
        }

        if (pointsA.length > 0) {
            const pathD = buildSmoothPath(pointsA);
            const firstX = pointsA[0].x;
            const lastX = pointsA[pointsA.length - 1].x;
            const baseY = padTop + chartH;
            const areaD = `${pathD} L ${lastX} ${baseY} L ${firstX} ${baseY} Z`;

            svgContent += `
                <defs>
                    <linearGradient id="gradDensityA" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#3B82F6" stop-opacity="${activeConceptFocus ? '0.12' : '0.25'}"/>
                        <stop offset="100%" stop-color="#3B82F6" stop-opacity="0.0"/>
                    </linearGradient>
                </defs>
                <path d="${areaD}" fill="url(#gradDensityA)" />
                <path d="${pathD}" fill="none" stroke="#3B82F6" stroke-width="${activeConceptFocus ? '2.5' : '3'}" stroke-linecap="round" opacity="${activeConceptFocus ? '0.65' : '1.0'}" />
            `;
        }

        if (pointsB.length > 0) {
            const pathD = buildSmoothPath(pointsB);
            const firstX = pointsB[0].x;
            const lastX = pointsB[pointsB.length - 1].x;
            const baseY = padTop + chartH;
            const areaD = `${pathD} L ${lastX} ${baseY} L ${firstX} ${baseY} Z`;

            svgContent += `
                <defs>
                    <linearGradient id="gradDensityB" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#EC4899" stop-opacity="${activeConceptFocus ? '0.12' : '0.25'}"/>
                        <stop offset="100%" stop-color="#EC4899" stop-opacity="0.0"/>
                    </linearGradient>
                </defs>
                <path d="${areaD}" fill="url(#gradDensityB)" />
                <path d="${pathD}" fill="none" stroke="#EC4899" stroke-width="${activeConceptFocus ? '2.5' : '3'}" stroke-linecap="round" opacity="${activeConceptFocus ? '0.65' : '1.0'}" />
            `;
        }

        const allPoints = [...pointsA, ...pointsB];
        allPoints.forEach(pt => {
            const color = pt.video === 'A' ? '#3B82F6' : '#EC4899';
            const isPeak = (pt.video === 'A' && dataA && dataA.maxBucket && dataA.maxBucket.index === pt.b.index) ||
                           (pt.video === 'B' && dataB && dataB.maxBucket && dataB.maxBucket.index === pt.b.index);

            let nodeOpacity = '0.35';
            let strokeWidth = '2';
            let rVal = isPeak ? '5.5' : '4.5';

            if (isPeak) {
                nodeOpacity = '1.0';
            }

            if (activeConceptFocus) {
                const targetRanges = pt.video === 'A' ? activeConceptFocus.ranges_a : activeConceptFocus.ranges_b;
                const isInRange = (targetRanges || []).some(r => {
                    return pt.b.startTime <= r.end && pt.b.endTime >= r.start;
                });
                if (isInRange) {
                    rVal = '6.5';
                    strokeWidth = '2.5';
                    nodeOpacity = '1.0';
                }
            }

            if (isPeak && pt.b.rawCount > 0) {
                svgContent += `
                    <g transform="translate(${pt.x}, ${pt.y - 12})" opacity="1.0">
                        <rect x="-18" y="-12" width="36" height="15" rx="3" fill="${color}" opacity="0.9"/>
                        <text x="0" y="-1" font-size="9" font-weight="bold" fill="#FFFFFF" text-anchor="middle">▲ Peak</text>
                    </g>
                `;
            }

            const dataStr = JSON.stringify({
                video: pt.video,
                bIndex: pt.b.index,
                segmentIndex: pt.b.segmentIndex,
                title: pt.title,
                timeStr: `${formatSeconds(pt.b.startTime)}–${formatSeconds(pt.b.endTime)}`,
                pctStr: `${Math.round(pt.b.pctMid)}%`,
                rawCount: pt.b.rawCount,
                smoothedCount: pt.b.smoothedCount,
                segCount: pt.b.segments.length,
                snippets: pt.b.segments.map(s => s.text || '').join(' ... ')
            }).replace(/"/g, '&quot;');

            svgContent += `
                <circle cx="${pt.x}" cy="${pt.y}" r="${rVal}" fill="${color}" stroke="#FFFFFF" stroke-width="${strokeWidth}"
                        opacity="${nodeOpacity}"
                        style="cursor: pointer; transition: opacity 0.15s ease, r 0.15s ease;"
                        data-density="${dataStr}"
                        class="density-chart-node" />
            `;
        });

        const legendHtml = `
            <div class="density-legend-bar" style="display: flex; justify-content: space-between; align-items: center; padding: 0 0.5rem 0.6rem 0.5rem; font-size: 0.85rem;">
                <div style="display: flex; gap: 1.25rem; align-items: center; flex-wrap: wrap;">
                    <span style="display: inline-flex; align-items: center; gap: 0.4rem; color: #3B82F6; font-weight: 600;" title="${escapeHtml(cleanTitleA)}">
                        <span style="width: 10px; height: 10px; border-radius: 50%; background: #3B82F6; display: inline-block;"></span>
                        Video A — ${escapeHtml(dispA)}
                    </span>
                    <span style="display: inline-flex; align-items: center; gap: 0.4rem; color: #EC4899; font-weight: 600;" title="${escapeHtml(cleanTitleB)}">
                        <span style="width: 10px; height: 10px; border-radius: 50%; background: #EC4899; display: inline-block;"></span>
                        Video B — ${escapeHtml(dispB)}
                    </span>
                </div>
                <span style="color: var(--text-desc, #94A3B8); font-size: 0.78rem;">Y-Axis: ความหนาแน่นของคำพูด</span>
            </div>
        `;

        container.innerHTML = legendHtml + `
            <svg viewBox="0 0 ${svgWidth} ${svgHeight}" style="width: 100%; height: 100%; overflow: visible;">
                ${svgContent}
            </svg>
            <div id="densityTooltipPopover" class="density-tooltip" style="display: none;"></div>
        `;

        attachDensityChartInteractions(container, snapA, snapB);
    }

    function attachDensityChartInteractions(container, snapA = null, snapB = null) {
        const tooltip = container.querySelector('#densityTooltipPopover');
        const detailPanel = document.getElementById('densityPointDetailPanel');
        const detailTitle = document.getElementById('densityDetailTitle');
        const detailContent = document.getElementById('densityDetailContent');
        const btnCloseDetail = document.getElementById('btnCloseDensityDetail');

        if (btnCloseDetail && detailPanel) {
            btnCloseDetail.onclick = () => { detailPanel.style.display = 'none'; };
        }

        container.querySelectorAll('.density-chart-node').forEach(node => {
            node.addEventListener('mouseenter', (e) => {
                const raw = e.currentTarget.getAttribute('data-density');
                if (!raw || !tooltip) return;
                try {
                    const info = JSON.parse(raw);
                    tooltip.style.display = 'block';

                    const conceptList = info.video === 'A' ? _section07BucketConceptsA.get(info.bIndex) : _section07BucketConceptsB.get(info.bIndex);
                    let conceptsTooltipHtml = '';
                    if (conceptList && conceptList.length > 0) {
                        const titles = Array.from(new Set(conceptList.map(c => c.title))).slice(0, 3);
                        conceptsTooltipHtml = `<div style="margin-top:0.35rem; border-top:1px stroke rgba(255,255,255,0.15); padding-top:0.25rem;">📌 <strong>ประเด็นที่พบ:</strong> ${escapeHtml(titles.join(', '))}</div>`;
                    } else {
                        conceptsTooltipHtml = `<div style="margin-top:0.35rem; border-top:1px stroke rgba(255,255,255,0.15); padding-top:0.25rem; color:var(--text-muted, #94A3B8);">📌 ไม่พบประเด็นเฉพาะในช่วงนี้</div>`;
                    }

                    tooltip.innerHTML = `
                        <strong>VIDEO ${info.video} (${info.pctStr} ของคลิป)</strong><br/>
                        ⏱️ ${info.timeStr}<br/>
                        💬 ${info.rawCount} คำ / 10 วินาที (${info.segCount} segment)
                        ${conceptsTooltipHtml}
                    `;
                    const rect = container.getBoundingClientRect();
                    const nodeRect = e.currentTarget.getBoundingClientRect();
                    const leftPos = Math.min(rect.width - 180, Math.max(10, nodeRect.left - rect.left - 60));
                    const topPos = Math.max(10, nodeRect.top - rect.top - 65);
                    tooltip.style.left = leftPos + 'px';
                    tooltip.style.top = topPos + 'px';
                } catch (err) {
                    console.error('Tooltip parse error:', err);
                }
            });

            node.addEventListener('mouseleave', () => {
                if (tooltip) tooltip.style.display = 'none';
            });

            node.addEventListener('click', (e) => {
                const raw = e.currentTarget.getAttribute('data-density');
                if (!raw || !detailPanel) return;
                try {
                    const info = JSON.parse(raw);
                    detailPanel.style.display = 'block';

                    const targetSnap = (info.video === 'A' ? snapA : snapB) || (info.video === 'A' ? selectedSnapshotA : selectedSnapshotB);
                    const allSegs = getAuthoritativeTranscriptSegments(targetSnap);

                    const selectedSegment = allSegs[info.segmentIndex];
                    const dedupped = selectedSegment ? [selectedSegment] : [];

                    if (detailTitle) {
                        detailTitle.innerHTML = `🔍 [VIDEO ${info.video}] ช่วงเวลา ${escapeHtml(info.timeStr)} (${info.pctStr} ของคลิป)`;
                    }

                    let verbatimHtml = '';
                    if (dedupped.length > 0) {
                        const verbatimText = dedupped.map(s => String(s.text || '').trim()).filter(Boolean).join(' ');
                        const origStartSec = parseFloat(dedupped[0].start || 0);
                        const origEndSec = parseFloat(dedupped[dedupped.length - 1].end || origStartSec + 1.0);
                        const origTimeStr = `${formatSeconds(origStartSec)}–${formatSeconds(origEndSec)}`;

                        verbatimHtml = `
                            <div class="verbatim-transcript-container" style="margin-top: 0.75rem; padding: 1rem; border-radius: 12px; background: rgba(0,0,0,0.06); border-left: 4px solid ${info.video === 'A' ? '#3B82F6' : '#EC4899'};">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; flex-wrap: wrap; gap: 0.35rem;">
                                    <h4 style="margin: 0; font-size: 0.95rem; font-weight: 700; color: var(--text-main);">🎙️ คำพูดจริงจาก Transcript</h4>
                                    <span style="font-size: 0.78rem; color: var(--text-muted);">Segments: ${dedupped.length} • ช่วงต้นฉบับ: ${origTimeStr}</span>
                                </div>
                                <div class="verbatim-text" style="font-style: italic; font-size: 0.9rem; line-height: 1.6; color: var(--text-main); font-weight: 500;">
                                    "${escapeHtml(verbatimText)}"
                                </div>
                            </div>
                        `;
                    } else {
                        verbatimHtml = `
                            <div class="no-transcript-container" style="margin-top: 0.75rem; padding: 1rem; border-radius: 12px; background: rgba(0,0,0,0.04); border: 1px dashed var(--border-color); text-align: center; color: var(--text-muted); font-size: 0.9rem;">
                                <h4 style="margin: 0 0 0.35rem 0; font-size: 0.95rem; font-weight: 700; color: var(--text-main);">🎙️ คำพูดจริงจาก Transcript</h4>
                                <span style="font-weight: 600; color: var(--text-desc); display: block;">ไม่พบคำพูดจาก Transcript ในช่วงเวลานี้</span>
                            </div>
                        `;
                    }

                    if (detailContent) {
                        detailContent.innerHTML = `
                            <div class="density-detail-meta" style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                                <span style="color: ${info.video === 'A' ? '#3B82F6' : '#EC4899'}; font-weight: 700;">VIDEO ${info.video}</span> •
                                ⏱️ ${escapeHtml(info.timeStr)} (${escapeHtml(info.pctStr)}) •
                                💬 ${info.rawCount} คำ / 10 วินาที •
                                Segments: ${dedupped.length}
                            </div>
                            ${verbatimHtml}
                        `;
                    }
                } catch (err) {
                    console.error('Detail click error:', err);
                }
            });
        });
    }

    function renderDensitySummaryCards(dataA, dataB, snapA, snapB) {
        const container = document.getElementById('densitySummaryGrid');
        if (!container) return;

        let html = '';

        if (dataA && dataA.hasData) {
            const peakStr = `${formatSeconds(dataA.maxBucket.startTime)}–${formatSeconds(dataA.maxBucket.endTime)}`;
            const minStr = dataA.minBucket ? `${formatSeconds(dataA.minBucket.startTime)}–${formatSeconds(dataA.minBucket.endTime)}` : '-';
            const shiftStr = dataA.shiftBucket ? `${formatSeconds(dataA.shiftBucket.startTime)}–${formatSeconds(dataA.shiftBucket.endTime)}` : '-';

            html += `
                <div class="density-summary-card card-a">
                    <h4 style="color: #3B82F6;">📌 สรุปจังหวะ VIDEO A</h4>
                    <div class="density-stat-row">
                        <span>ช่วงความหนาแน่นสูงสุด (Peak):</span>
                        <span class="density-stat-value">⏱️ ${peakStr} (${Math.round(dataA.maxBucket.pctMid)}%)</span>
                    </div>
                    <div class="density-stat-row">
                        <span>ช่วงผ่อนคลายที่สุด (Quiet):</span>
                        <span class="density-stat-value">⏱️ ${minStr}</span>
                    </div>
                    <div class="density-stat-row">
                        <span>จุดเปลี่ยนจังหวะหลัก (Shift):</span>
                        <span class="density-stat-value">⏱️ ${shiftStr}</span>
                    </div>
                    <div class="density-stat-row">
                        <span>จังหวะหลัก (Pace):</span>
                        <span class="density-stat-value" style="color: #3B82F6;">🌊 ${dataA.paceClassification}</span>
                    </div>
                </div>
            `;
        }

        if (dataB && dataB.hasData) {
            const peakStr = `${formatSeconds(dataB.maxBucket.startTime)}–${formatSeconds(dataB.maxBucket.endTime)}`;
            const minStr = dataB.minBucket ? `${formatSeconds(dataB.minBucket.startTime)}–${formatSeconds(dataB.minBucket.endTime)}` : '-';
            const shiftStr = dataB.shiftBucket ? `${formatSeconds(dataB.shiftBucket.startTime)}–${formatSeconds(dataB.shiftBucket.endTime)}` : '-';

            html += `
                <div class="density-summary-card card-b">
                    <h4 style="color: #EC4899;">📌 สรุปจังหวะ VIDEO B</h4>
                    <div class="density-stat-row">
                        <span>ช่วงความหนาแน่นสูงสุด (Peak):</span>
                        <span class="density-stat-value">⏱️ ${peakStr} (${Math.round(dataB.maxBucket.pctMid)}%)</span>
                    </div>
                    <div class="density-stat-row">
                        <span>ช่วงผ่อนคลายที่สุด (Quiet):</span>
                        <span class="density-stat-value">⏱️ ${minStr}</span>
                    </div>
                    <div class="density-stat-row">
                        <span>จุดเปลี่ยนจังหวะหลัก (Shift):</span>
                        <span class="density-stat-value">⏱️ ${shiftStr}</span>
                    </div>
                    <div class="density-stat-row">
                        <span>จังหวะหลัก (Pace):</span>
                        <span class="density-stat-value" style="color: #EC4899;">🌊 ${dataB.paceClassification}</span>
                    </div>
                </div>
            `;
        }

        if (activeConceptFocus) {
            const sideLabel = activeConceptFocus.side === 'A' ? 'Video A' : (activeConceptFocus.side === 'B' ? 'Video B' : 'ทั้งสองวิดีโอ');
            const ranges = activeConceptFocus.side === 'A' ? activeConceptFocus.ranges_a : (activeConceptFocus.side === 'B' ? activeConceptFocus.ranges_b : [...(activeConceptFocus.ranges_a || []), ...(activeConceptFocus.ranges_b || [])]);
            const rangeStr = ranges && ranges.length > 0 ? `และกระจุกตัวในช่วง ${ranges[0].pctStart}%–${ranges[ranges.length-1].pctEnd}% ของคลิป` : 'แต่ไม่พบคำกล่าวถึงโดยตรงใน Transcript';

            html += `
                <div class="density-synthesis-box" style="grid-column: 1 / -1; margin-top: 0.75rem; padding: 0.75rem 1rem; background: var(--input-bg, rgba(255,255,255,0.03)); border: 1px solid var(--accent-purple, #8B5CF6); border-radius: 8px; font-size: 0.88rem; color: var(--text-main, #FFFFFF);">
                    💬 <strong>การสังเคราะห์ประเด็นโฟกัส:</strong> ประเด็น "${escapeHtml(activeConceptFocus.title)}" ปรากฏเด่นใน ${sideLabel} ${rangeStr}
                </div>
            `;
        } else if (dataA && dataA.hasData && dataB && dataB.hasData) {
            const paceA = (dataA.paceClassification || '').replace('หนาแน่นช่วง', '');
            const paceB = (dataB.paceClassification || '').replace('หนาแน่นช่วง', '');
            const peakA = Math.round(dataA.maxBucket.pctMid);
            const peakB = Math.round(dataB.maxBucket.pctMid);
            html += `
                <div class="density-synthesis-box" style="grid-column: 1 / -1; margin-top: 0.75rem; padding: 0.75rem 1rem; background: var(--input-bg, rgba(255,255,255,0.03)); border: 1px solid var(--border-color, rgba(255,255,255,0.1)); border-radius: 8px; font-size: 0.88rem; color: var(--text-main, #FFFFFF);">
                    💬 <strong>ภาพรวมเชิงโครงสร้าง:</strong> Video A มีความหนาแน่นของคำพูดค่อนข้างกระจายตัวในช่วง${paceA || 'กลาง'} (จุดพีค ${peakA}%) ขณะที่ Video B มีจุดพีคชัดเจนในช่วงประมาณ ${peakB}% ของคลิป
                </div>
            `;
        }

        container.innerHTML = html;
    }

    function renderSection05Sentiment(sentimentObj = {}) {
        const textAEl = document.getElementById('sentimentTextA');
        const textBEl = document.getElementById('sentimentTextB');
        const synthEl = document.getElementById('sentimentSynthesis');

        const sentAText = typeof sentimentObj.video_a_sentiment === 'string'
            ? sentimentObj.video_a_sentiment
            : (sentimentObj.video_a ? (sentimentObj.video_a.description || sentimentObj.video_a.overall_tone) : '-');

        const sentBText = typeof sentimentObj.video_b_sentiment === 'string'
            ? sentimentObj.video_b_sentiment
            : (sentimentObj.video_b ? (sentimentObj.video_b.description || sentimentObj.video_b.overall_tone) : '-');

        const notesText = sentimentObj.comparison_notes || sentimentObj.comparison_synthesis || '-';

        if (textAEl) textAEl.textContent = sentAText;
        if (textBEl) textBEl.textContent = sentBText;
        if (synthEl) synthEl.textContent = notesText;
    }
    const renderSection07Sentiment = renderSection05Sentiment;

    function renderSection06FinalInsight(insightObj = {}) {
        const coreEl = document.getElementById('insightCore');
        const concEl = document.getElementById('insightConclusion');
        const recEl = document.getElementById('insightRecommendation');

        if (coreEl) coreEl.textContent = insightObj.core_takeaway || '-';
        if (concEl) concEl.textContent = insightObj.comparative_conclusion || '-';
        if (recEl) recEl.textContent = insightObj.recommendation || '-';
    }
    const renderSection08FinalInsight = renderSection06FinalInsight;

    // --------------------------------------------------------------------------
    // PART 4 — EXTERNAL RESEARCH POC UI & HANDLERS
    // --------------------------------------------------------------------------
    let activeExternalSourcesModalData = [];

    function renderSectionExternalResearch(extData, publicId) {
        const container = document.getElementById('externalTopicsContainer');
        const timestampEl = document.getElementById('externalSearchTimestamp');
        const btnRefresh = document.getElementById('btnRefreshExternalResearch');

        if (!container) return;

        if (!extData) {
            container.innerHTML = '<p class="text-desc">ไม่มีข้อมูลภายนอก (กด "อัปเดตข้อมูลล่าสุด" เพื่อเริ่มการวิจัยภายนอก)</p>';
            if (btnRefresh && publicId) {
                btnRefresh.onclick = () => fetchOrRefreshExternalResearch(publicId, true);
            }
            return;
        }

        const ts = extData.search_timestamp ? formatDate(extData.search_timestamp) : 'ยังไม่ลงวันที่';
        if (timestampEl) timestampEl.textContent = `ข้อมูลภายนอก ณ วันที่ ${ts}`;

        if (btnRefresh && publicId) {
            btnRefresh.onclick = () => fetchOrRefreshExternalResearch(publicId, true);
        }

        const topics = extData.topics || [];
        if (topics.length === 0) {
            container.innerHTML = '<p class="text-desc">ไม่พบประเด็นภายนอก</p>';
            return;
        }

        let html = '';
        topics.forEach((tp, idx) => {
            const topicName = tp.topic || 'ประเด็นภายนอก';
            const findings = tp.findings || 'ไม่พบข้อมูล';
            const relevance = tp.relevance || '-';
            const dateStr = tp.date || '-';
            const sourceCount = tp.source_count || 0;
            const confidence = tp.confidence || 'ต่ำ';
            const status = tp.verification_status || 'INSUFFICIENT_EVIDENCE';

            let statusBadgeClass = 'status-unverified';
            let statusText = 'ยังไม่พบหลักฐานยืนยัน';
            if (status === 'VERIFIED') {
                statusBadgeClass = 'status-verified';
                statusText = '✓ ยืนยันจากแหล่งภายนอก';
            } else if (status === 'CONFLICTING_SOURCES') {
                statusBadgeClass = 'status-partially_verified';
                statusText = '⚠️ พบข้อมูลที่ยังไม่ตรงกัน';
            } else if (status === 'INSUFFICIENT_EVIDENCE') {
                statusBadgeClass = 'status-unverified';
                statusText = 'ยังไม่พบข้อมูลภายนอกที่น่าเชื่อถือเพียงพอสำหรับยืนยันประเด็นนี้';
            }

            const sourcesJson = JSON.stringify(tp.sources || []).replace(/"/g, '&quot;');

            html += `
                <div class="external-topic-card card-inner">
                    <div class="ext-topic-header">
                        <h3>🌐 Topic: ${escapeHtml(topicName)}</h3>
                        <div class="ext-meta-badges">
                            <span class="status-badge ${statusBadgeClass}">${statusText}</span>
                            <span class="confidence-badge conf-${confidence.toLowerCase()}">ความน่าเชื่อถือ: ${escapeHtml(confidence)}</span>
                        </div>
                    </div>
                    
                    <div class="ext-findings-block" style="margin-top: 0.5rem; font-size: 0.95rem;">
                        <strong>สิ่งที่พบจากภายนอก:</strong>
                        <p style="margin-top: 0.25rem;">${escapeHtml(findings)}</p>
                    </div>

                    ${tp.conflict_details ? `
                        <div class="ext-conflict-box alert-banner alert-warning" style="margin-top: 0.5rem; font-size: 0.85rem;">
                            <strong>รายละเอียดข้อขัดแย้ง:</strong> ${escapeHtml(tp.conflict_details)}
                        </div>
                    ` : ''}

                    <div class="ext-relevance-block" style="margin-top: 0.5rem; font-size: 0.85rem; opacity: 0.9;">
                        📌 <strong>ความเกี่ยวข้องกับวิดีโอ:</strong> ${escapeHtml(relevance)}
                    </div>

                    <div class="ext-footer-meta" style="margin-top: 0.75rem; display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 0.5rem;">
                        <span>📅 ค้นเมื่อ: ${escapeHtml(dateStr)} • 📚 จำนวนแหล่งข้อมูล: ${sourceCount} รายการ</span>
                        <button type="button" class="btn btn-sm btn-outline btn-view-ext-sources" data-sources="${sourcesJson}" data-topic="${escapeHtml(topicName)}">
                            📖 ดูแหล่งข้อมูล (${sourceCount})
                        </button>
                    </div>
                </div>
            `;
        });

        container.innerHTML = html;

        // Attach Sources Modal click listeners
        container.querySelectorAll('.btn-view-ext-sources').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const btnTarget = e.currentTarget;
                const rawSources = btnTarget.getAttribute('data-sources');
                const topicName = btnTarget.getAttribute('data-topic') || '';
                try {
                    const sources = JSON.parse(rawSources);
                    openExternalSourcesModal(topicName, sources);
                } catch (err) {
                    console.error('Error parsing external sources JSON:', err);
                }
            });
        });

        // Render Telemetry
        const telem = extData.telemetry || {};
        const extTelemBar = document.getElementById('externalTelemetryBar');
        if (extTelemBar) {
            const queries = telem.search_queries ? telem.search_queries.length : 0;
            const sources = telem.source_count || 0;
            const calls = telem.api_calls || 0;
            const tokens = telem.total_token_count || 0;
            const timeFormatted = typeof formatProcessingTime === 'function' ? formatProcessingTime(telem.processing_seconds) : `${(telem.processing_seconds || 0).toFixed(2)}s`;
            const providerMsg = telem.provider_configured === false ? " (Search Provider Unconfigured)" : "";

            extTelemBar.innerHTML = `
                🔍 Search Queries: <strong>${queries}</strong> • 
                📚 Sources Ranked: <strong>${sources}</strong> • 
                🤖 Gemini Calls: <strong>${calls}</strong> • 
                📊 Tokens: <strong>${tokens}</strong> • 
                ⏱️ Time: <strong>${timeFormatted}</strong>${providerMsg}
            `;
        }
    }

    async function fetchOrRefreshExternalResearch(publicId, isRefresh = false) {
        const timestampEl = document.getElementById('externalSearchTimestamp');
        if (timestampEl) timestampEl.textContent = 'กำลังประมวลผลข้อมูลภายนอก (POC)...';

        try {
            const url = `/api/comparison/${publicId}/external-research?refresh=${isRefresh ? 'true' : 'false'}`;
            const resp = await fetch(url, { method: 'POST' });
            if (!resp.ok) throw new Error('ไม่สามารถโหลดข้อมูลภายนอกได้');

            const data = await resp.json();
            renderSectionExternalResearch(data.external_research, publicId);
        } catch (err) {
            console.error('External research fetch error:', err);
            if (timestampEl) timestampEl.textContent = 'เกิดข้อผิดพลาดในการดึงข้อมูลภายนอก';
        }
    }

    function openExternalSourcesModal(topicName, sources) {
        const modal = document.getElementById('externalSourcesModal');
        const titleEl = document.getElementById('externalSourcesModalTitle');
        const listEl = document.getElementById('externalSourcesList');

        if (!modal || !listEl) return;

        if (titleEl) titleEl.textContent = `🌐 แหล่งข้อมูลอ้างอิงภายนอก: ${topicName}`;

        if (!sources || sources.length === 0) {
            listEl.innerHTML = '<p class="text-desc">ไม่มีรายการแหล่งข้อมูลภายนอกสำหรับประเด็นนี้</p>';
        } else {
            let html = '';
            sources.forEach(src => {
                const tierClass = (src.tier || 'Tier C').toLowerCase().replace(' ', '-');
                html += `
                    <div class="external-source-item-card card-inner" style="margin-bottom: 0.75rem;">
                        <div class="src-header" style="display: flex; justify-content: space-between; align-items: center;">
                            <span class="source-name font-semibold" style="font-size: 1rem;">${escapeHtml(src.source_name || 'Web Source')}</span>
                            <span class="tier-tag tier-${tierClass}">${escapeHtml(src.tier || 'Tier C')}</span>
                        </div>
                        <h4 style="margin: 0.25rem 0; font-size: 0.95rem;">${escapeHtml(src.title || '-')}</h4>
                        <p style="font-size: 0.85rem; margin-top: 0.25rem;"><strong>ข้อมูลที่ใช้สนับสนุน:</strong> ${escapeHtml(src.supporting_claim || '-')}</p>
                        <div class="src-meta" style="margin-top: 0.5rem; font-size: 0.75rem; display: flex; justify-content: space-between;">
                            <span>📅 วันที่เผยแพร่: ${escapeHtml(src.published_date || '-')}</span>
                            <a href="${escapeHtml(src.url || '#')}" target="_blank" rel="noopener noreferrer" class="link-url">🔗 ไปยัง URL แหล่งข้อมูล</a>
                        </div>
                    </div>
                `;
            });
            listEl.innerHTML = html;
        }

        modal.style.display = 'flex';
    }

    const btnCloseExtSources = document.getElementById('btnCloseExternalSourcesModal');
    const btnCloseExtSourcesFooter = document.getElementById('btnCloseExternalSourcesModalFooter');
    const externalSourcesModal = document.getElementById('externalSourcesModal');

    if (btnCloseExtSources) btnCloseExtSources.addEventListener('click', () => { if (externalSourcesModal) externalSourcesModal.style.display = 'none'; });
    if (btnCloseExtSourcesFooter) btnCloseExtSourcesFooter.addEventListener('click', () => { if (externalSourcesModal) externalSourcesModal.style.display = 'none'; });
    if (externalSourcesModal) {
        externalSourcesModal.addEventListener('click', (e) => {
            if (e.target === externalSourcesModal) externalSourcesModal.style.display = 'none';
        });
    }


    // --------------------------------------------------------------------------
    // Evidence Interaction & Authoritative Transcript Viewer
    // --------------------------------------------------------------------------
    function renderEvidenceBtn(ev, defaultSlot = 'A') {
        if (!ev) return '';

        const slot = ev.video || ev.video_slot || defaultSlot;
        const ts = ev.timestamp || (ev.start !== undefined ? formatSeconds(ev.start) : '00:00');
        const status = ev.verification_status || 'VERIFIED';
        const badgeStr = getVerificationStatusBadge(status);

        const evJson = JSON.stringify(ev).replace(/"/g, '&quot;');

        return `
            <button type="button" class="btn btn-sm btn-evidence-trigger" data-evidence="${evJson}" data-slot="${slot}">
                📍 Video ${slot}: ${ts} (${badgeStr})
            </button>
        `;
    }

    function getVerificationStatusBadge(status) {
        switch (status) {
            case 'VERIFIED': return '✓ Verified';
            case 'PARTIALLY_VERIFIED': return '~ Partial';
            case 'UNVERIFIED': default: return '❌ Unverified';
        }
    }

    function attachEvidenceClickListeners(container) {
        if (!container) return;
        container.querySelectorAll('.btn-evidence-trigger').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const btnTarget = e.currentTarget;
                const evRaw = btnTarget.getAttribute('data-evidence');
                const slot = btnTarget.getAttribute('data-slot') || 'A';

                try {
                    const evData = JSON.parse(evRaw);
                    openEvidenceModal(evData, slot);
                } catch (err) {
                    console.error('Evidence parsing error:', err);
                }
            });
        });
    }

    function openEvidenceModal(ev, slot) {
        const targetSnapshot = slot === 'B' ? selectedSnapshotB : selectedSnapshotA;
        const videoTitle = targetSnapshot ? targetSnapshot.title : (slot === 'B' ? 'VIDEO B' : 'VIDEO A');

        document.getElementById('evVideoTitle').textContent = `[VIDEO ${slot}] ${videoTitle}`;
        const tsDisplay = ev.timestamp || (ev.start !== undefined ? formatSeconds(ev.start) : '00:00');
        document.getElementById('evTimestamp').textContent = `⏱️ Timestamp: ${tsDisplay}`;

        const statusBadge = document.getElementById('evStatusBadge');
        const st = ev.verification_status || 'VERIFIED';
        statusBadge.textContent = getVerificationStatusBadge(st);
        statusBadge.className = `status-badge status-${st.toLowerCase()}`;

        const transcriptEl = document.getElementById('evTranscriptText');
        transcriptEl.textContent = ev.resolved_transcript_text || ev.transcript_text || ev.quote || 'ไม่มีข้อความถอดคำพูดสำหรับช่วงเวลานี้';

        evidenceModal.style.display = 'flex';
    }

    function closeEvidenceModal() {
        evidenceModal.style.display = 'none';
    }

    // Utility Helpers
    function formatSeconds(secs) {
        if (!secs || isNaN(secs)) return '00:00';
        const s = Math.floor(secs);
        const m = Math.floor(s / 60);
        const remSec = s % 60;
        return `${m.toString().padStart(2, '0')}:${remSec.toString().padStart(2, '0')}`;
    }

    function formatDate(dateStr) {
        if (!dateStr) return '-';
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: '2-digit' });
        } catch (e) {
            return dateStr;
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    window.extractConceptCandidates = extractConceptCandidates;
    window.calculateSpeechDensityData = calculateSpeechDensityData;
});
