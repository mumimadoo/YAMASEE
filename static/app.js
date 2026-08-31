window.YAMASEE_PRE_RUN_BUILD = "FINAL_FIX_2026_08_23";
window.YAMASEE_BUILD_MARKER = "FINAL_FIX_2026_08_23";
// Note: checkUnauthorized status 401 handler is now in static/js/utils/api.js
const activePollers = new Map();
const activeElapsedIntervals = new Map();
const activeJobData = new Map();

const STAGE_LABELS = {
    "queued": "Queued / อยู่ในคิวประมวลผล",
    "initializing": "Preparing / กำลังเตรียมโครงสร้างพื้นฐาน",
    "preparing": "Preparing / กำลังเตรียมโครงสร้างพื้นฐาน",
    "download": "Downloading Video / กำลังดาวน์โหลดไฟล์สื่อต้นทาง",
    "downloading": "Downloading Video / กำลังดาวน์โหลดไฟล์สื่อต้นทาง",
    "extract": "Extracting Audio / กำลังแยกสัญญาณเสียงและภาพ",
    "extracting": "Extracting Audio / กำลังแยกสัญญาณเสียงและภาพ",
    "vad": "Voice Detection / ตรวจสอบความถูกต้องของเสียงพูด (VAD)",
    "voice_detection": "Voice Detection / ตรวจสอบความถูกต้องของเสียงพูด (VAD)",
    "transcribe": "Speech To Text / ถอดความเสียงพูดระดับยุทธศาสตร์",
    "transcribing": "Speech To Text / ถอดความเสียงพูดระดับยุทธศาสตร์",
    "strategic_analysis": "Strategic Analysis / วิเคราะห์เนื้อหาและโมดูลจิตวิทยา",
    "analysis": "Strategic Analysis / วิเคราะห์เนื้อหาและโมดูลจิตวิทยา",
    "generating_summary": "Generating Summary / สรุปประเด็นหลักและแก่นเนื้อหา",
    "summary": "Generating Summary / สรุปประเด็นหลักและแก่นเนื้อหา",
    "saving_results": "Saving Results / บันทึกผลลัพธ์เข้าคลังระบบ",
    "persist": "Saving Results / บันทึกผลลัพธ์เข้าคลังระบบ",
    "completed": "Completed / เสร็จสมบูรณ์",
    "failed": "Failed / การประมวลผลล้มเหลว",
    "cancelled": "Cancelled / ยกเลิกการประมวลผลแล้ว"
};

function initLogout() {
    const dashboardLogoutBtn = document.getElementById('dashboardLogoutBtn');
    if (dashboardLogoutBtn) {
        let isLoggingOut = false;
        dashboardLogoutBtn.addEventListener('click', async () => {
            if (isLoggingOut) return;
            isLoggingOut = true;
            dashboardLogoutBtn.disabled = true;
            try {
                const res = await fetch('/api/auth/logout', { 
                    method: 'POST', 
                    credentials: 'same-origin'
                });
                if (res.ok) {
                    const data = await res.json();
                    window.location.href = data.redirect_url || '/login';
                } else {
                    alert('Logout failed. Please try again.');
                    isLoggingOut = false;
                    dashboardLogoutBtn.disabled = false;
                }
            } catch (err) {
                console.error('Logout error:', err);
                alert('Connection error during logout.');
                isLoggingOut = false;
                dashboardLogoutBtn.disabled = false;
            }
        });
    }
}

// โหลดระบบออกจากระบบทันที (พยายามเปิดก่อน หรือรอ DOMContentLoaded เพื่อความมั่นใจสูงสุด)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initLogout();
    });
} else {
    initLogout();
}

function toggleInputFields() {
    const mode = document.querySelector('input[name="mediaMode"]:checked').value;
    document.getElementById('youtubeInputWrapper').style.display = (mode === 'youtube') ? 'flex' : 'none';
    document.getElementById('fileInputWrapper').style.display = (mode === 'youtube') ? 'none' : 'flex';
}

function executeModuleSwitch() {
    const selectedValue = document.getElementById('mainDashboardSelector').value;
    document.querySelectorAll('.module-view').forEach(view => { view.classList.remove('active'); });
    const targetModule = document.getElementById('module-' + selectedValue);
    if (targetModule) { targetModule.classList.add('active'); }
}

function startElapsedTimer(jobId, createdAt) {
    if (activeElapsedIntervals.has(jobId)) {
        return;
    }
    const timer = setInterval(() => {
        const elapsedSeconds = Math.max(0, Math.floor(Date.now() / 1000 - createdAt));
        const minutes = Math.floor(elapsedSeconds / 60).toString().padStart(2, '0');
        const seconds = (elapsedSeconds % 60).toString().padStart(2, '0');
        const display = document.getElementById('job-elapsed-display');
        if (display) {
            display.innerText = `${minutes}:${seconds}`;
        }
    }, 1000);
    activeElapsedIntervals.set(jobId, timer);
}

function stopJobTimers(jobId) {
    const poller = activePollers.get(jobId);
    if (poller) {
        clearInterval(poller);
        activePollers.delete(jobId);
    }
    const elapsed = activeElapsedIntervals.get(jobId);
    if (elapsed) {
        clearInterval(elapsed);
        activeElapsedIntervals.delete(jobId);
    }
}

async function cancelCurrentJob(event, jobId) {
    event.preventDefault();
    const btn = document.getElementById('btn-cancel-job');
    if (btn) btn.disabled = true;
    try {
        const res = await fetch(`/api/jobs/${jobId}/cancel`, {
            method: 'POST',
            headers: { 'Origin': window.location.origin }
        });
        if (res.ok) {
            // Cancel initiated successfully
        } else {
            const data = await res.json();
            alert("ไม่สามารถยกเลิกงานได้: " + (data.detail || "เกิดข้อผิดพลาด"));
            if (btn) btn.disabled = false;
        }
    } catch (e) {
        alert("เครือข่ายขัดข้องในการส่งคำขอยกเลิก");
        if (btn) btn.disabled = false;
    }
}

async function retryCurrentJob(event, publicId) {
    event.preventDefault();
    const btn = document.getElementById('btn-retry-job');
    if (btn) btn.disabled = true;
    try {
        const res = await fetch(`/api/history/${publicId}/retry`, {
            method: 'POST',
            headers: { 'Origin': window.location.origin }
        });
        if (res.ok) {
            const data = await res.json();
            if (data.job_id) {
                const errBox = document.getElementById('status-error-box');
                if (errBox) errBox.style.display = 'none';
                if (btn) btn.style.display = 'none';
                localStorage.setItem('activeJobId', data.job_id);
                pollJobStatus(data.job_id);
            }
        } else {
            const data = await res.json();
            alert("ไม่สามารถเริ่มประมวลผลใหม่ได้: " + (data.detail || "เกิดข้อผิดพลาด"));
            if (btn) btn.disabled = false;
        }
    } catch (e) {
        alert("เครือข่ายขัดข้องในการเริ่มประมวลผลใหม่");
        if (btn) btn.disabled = false;
    }
}

function openJobResult(event, jobId) {
    event.preventDefault();
    const jobData = activeJobData.get(jobId);
    if (jobData && jobData.result) {
        injectProcessedDataToDashboard(jobData.result);
        const statusBox = document.getElementById('statusBox');
        if (statusBox) statusBox.style.display = 'none';
        localStorage.removeItem('activeJobId');
    }
}

function pollJobStatus(jobId) {
    if (!jobId) return;
    
    // Clear any existing poller for duplicate safety
    if (activePollers.has(jobId)) {
        stopJobTimers(jobId);
    }
    
    localStorage.setItem('activeJobId', jobId);
    const statusBox = document.getElementById('statusBox');
    if (statusBox) statusBox.style.display = 'block';

    const interval = setInterval(async () => {
        try {
            const res = await fetch(`/job_status/${jobId}`, { credentials: 'same-origin' });
            if (window.WeFoolApp.api.checkUnauthorized(res)) {
                stopJobTimers(jobId);
                return;
            }
            if (res.status === 403 || res.status === 404) {
                stopJobTimers(jobId);
                localStorage.removeItem('activeJobId');
                if (statusBox) statusBox.style.display = 'none';
                return;
            }
            const job = await res.json();
            activeJobData.set(jobId, job);
            
            // 1. Started At & Timer
            const createdAt = job.created_at || (Date.now() / 1000);
            const startedDate = new Date(createdAt * 1000);
            const startedDisplay = document.getElementById('job-started-display');
            if (startedDisplay) {
                startedDisplay.innerText = startedDate.toLocaleTimeString();
            }
            startElapsedTimer(jobId, createdAt);

            // 2. Job ID badge
            const idDisplay = document.getElementById('job-id-display');
            if (idDisplay) idDisplay.innerText = `Job: ${jobId.substring(0, 15)}`;

            // 3. Status badge
            const statusBadge = document.getElementById('job-status-badge');
            if (statusBadge) {
                statusBadge.innerText = job.status;
                statusBadge.className = `badge-status ${job.status}`;
            }

            // 4. Stage label
            const stageDisplay = document.getElementById('job-stage-display');
            const rawStage = job.current_stage || job.status;
            const stageText = STAGE_LABELS[rawStage] || rawStage;
            if (stageDisplay) {
                stageDisplay.innerText = stageText;
            }

            // 5. Progress Fill & Percent (Smooth Animation)
            const progress = (job.progress !== undefined) ? job.progress : 0;
            const progressFill = document.getElementById('progress-bar-fill');
            const percentDisplay = document.getElementById('progress-percent-display');
            
            if (progressFill) {
                progressFill.style.width = `${progress}%`;
                progressFill.setAttribute('aria-valuenow', progress);
                progressFill.setAttribute('aria-valuetext', `${stageText} - ${progress}%`);
            }
            if (percentDisplay) {
                percentDisplay.innerText = `${progress}%`;
            }

            // 6. Inline dynamic sub text inside dashboard list during run
            if (job.status === "processing" || job.status === "queued") {
                const tList = document.getElementById('transcript-list');
                if (tList) tList.innerHTML = `<p style="color:#FF9800;text-align:center;padding-top:40px;">ระบบกำลังดำเนินงานสกัดสถิติตามขบวนการ Pipeline แยกภาพและเสียง... ${progress}%</p>`;
            }

            // 7. Action Button Display Control
            const btnCancel = document.getElementById('btn-cancel-job');
            const btnRetry = document.getElementById('btn-retry-job');
            const btnOpenResult = document.getElementById('btn-open-result');
            const errorBox = document.getElementById('status-error-box');

            if (job.status === "queued" || job.status === "processing") {
                if (btnCancel) {
                    btnCancel.style.display = 'block';
                    btnCancel.disabled = false;
                    btnCancel.onclick = (e) => cancelCurrentJob(e, jobId);
                }
                if (btnRetry) btnRetry.style.display = 'none';
                if (btnOpenResult) btnOpenResult.style.display = 'none';
                if (errorBox) errorBox.style.display = 'none';
            }
            else if (job.status === "completed") {
                stopJobTimers(jobId);
                if (progressFill) {
                    progressFill.style.width = '100%';
                    progressFill.setAttribute('aria-valuenow', 100);
                }
                if (percentDisplay) percentDisplay.innerText = '100%';
                if (btnCancel) btnCancel.style.display = 'none';
                if (btnRetry) btnRetry.style.display = 'none';
                if (btnOpenResult) {
                    btnOpenResult.style.display = 'block';
                    btnOpenResult.onclick = (e) => openJobResult(e, jobId);
                }
                if (errorBox) errorBox.style.display = 'none';
                
                if (job.result) {
                    injectProcessedDataToDashboard(job.result);
                    if (statusBox) statusBox.style.display = 'none';
                    localStorage.removeItem('activeJobId');
                }
            }
            else if (job.status === "failed") {
                stopJobTimers(jobId);
                if (btnCancel) btnCancel.style.display = 'none';
                if (btnOpenResult) btnOpenResult.style.display = 'none';
                
                if (errorBox) {
                    errorBox.style.display = 'block';
                    const friendlyMessage = (job.error_message || "การประมวลผลขัดข้อง").split("\n")[0];
                    errorBox.innerText = `ข้อผิดพลาด: ${friendlyMessage}`;
                }
                
                if (btnRetry) {
                    const isEligible = (job.source_type === "youtube" || job.source_type === "url" || !job.original_filename);
                    if (isEligible && job.public_id) {
                        btnRetry.style.display = 'block';
                        btnRetry.disabled = false;
                        btnRetry.onclick = (e) => retryCurrentJob(e, job.public_id);
                    } else {
                        btnRetry.style.display = 'none';
                    }
                }
            }
            else if (job.status === "cancelled") {
                stopJobTimers(jobId);
                if (btnCancel) btnCancel.style.display = 'none';
                if (btnRetry) btnRetry.style.display = 'none';
                if (btnOpenResult) btnOpenResult.style.display = 'none';
                if (errorBox) {
                    errorBox.style.display = 'block';
                    errorBox.innerText = "งานนี้ถูกยกเลิกเสร็จสิ้นตามคำขอของผู้ใช้";
                }
            }
        } catch (e) {
            stopJobTimers(jobId);
            if (statusBox) statusBox.style.display = 'none';
        }
    }, 2000);

    activePollers.set(jobId, interval);
}

async function checkAndResumeActiveJobs() {
    // 1. Recover from local storage
    const lastJobId = localStorage.getItem('activeJobId');
    if (lastJobId) {
        pollJobStatus(lastJobId);
    }

    // 2. Fetch active jobs list from server
    try {
        const res = await fetch('/api/jobs/active', { credentials: 'same-origin' });
        if (res.ok) {
            const activeJobs = await res.json();
            if (Array.isArray(activeJobs)) {
                activeJobs.forEach(job => {
                    if (job.job_id && job.job_id !== lastJobId) {
                        pollJobStatus(job.job_id);
                    }
                });
            }
        }
    } catch (err) {
        // Silently handle active jobs fetch error
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkAndResumeActiveJobs);
} else {
    checkAndResumeActiveJobs();
}

function formatDurationHHMMSS(seconds) {
    if (seconds === null || seconds === undefined || seconds <= 0 || isNaN(seconds)) {
        return "ยังไม่ทราบความยาว";
    }
    const s = Math.round(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

function setEstimatorUIState(state, data = {}) {
    const estDurationEl = document.getElementById('est-duration');
    const estTokensEl = document.getElementById('est-tokens');
    const estTokensSubEl = document.getElementById('est-tokens-sub');
    const estBudgetEl = document.getElementById('est-budget') || document.getElementById('est-cost');
    const estDisclaimerEl = document.getElementById('est-disclaimer-text');
    const btnContinue = document.getElementById('btnModalContinue');
    const unknownContainer = document.getElementById('unknown-estimate-container');

    if (state === 'WAITING_DURATION') {
        if (estDurationEl) estDurationEl.innerText = "กำลังตรวจสอบ...";
        if (estTokensEl) estTokensEl.innerText = "รอข้อมูลความยาว...";
        if (estTokensSubEl) estTokensSubEl.innerText = "";
        if (estBudgetEl) {
            estBudgetEl.innerText = "รอข้อมูลความยาว...";
            estBudgetEl.style.color = "var(--text-secondary)";
        }
        if (unknownContainer) unknownContainer.style.display = 'none';
        if (btnContinue) {
            btnContinue.disabled = true;
            btnContinue.style.opacity = '0.5';
            btnContinue.style.cursor = 'not-allowed';
        }
    } else if (state === 'ESTIMATING') {
        if (estDurationEl) estDurationEl.innerText = data.duration_formatted || "กำลังตรวจสอบ...";
        if (estTokensEl) estTokensEl.innerText = "กำลังประเมิน...";
        if (estTokensSubEl) estTokensSubEl.innerText = "";
        if (estBudgetEl) {
            estBudgetEl.innerText = "กำลังประเมิน...";
            estBudgetEl.style.color = "var(--text-secondary)";
        }
        if (unknownContainer) unknownContainer.style.display = 'none';
        if (btnContinue) {
            btnContinue.disabled = true;
            btnContinue.style.opacity = '0.5';
            btnContinue.style.cursor = 'not-allowed';
        }
    } else if (state === 'READY') {
        if (unknownContainer) unknownContainer.style.display = 'none';
        if (btnContinue) {
            btnContinue.disabled = false;
            btnContinue.style.opacity = '1';
            btnContinue.style.cursor = 'pointer';
        }

        if (estDurationEl) estDurationEl.innerText = data.duration_formatted || "00:00:00";
        if (estTokensEl) estTokensEl.innerText = data.tokens_range_text || "-";
        if (estTokensSubEl) {
            if (data.is_historical_fallback) {
                estTokensSubEl.innerText = data.explanation_th || data.confidence_note_th || '';
            } else {
                estTokensSubEl.innerText = data.tokens_expected ? `(ค่ากลาง ≈ ${data.tokens_expected.toLocaleString()} Tokens)` : '';
            }
        }
        if (estBudgetEl) {
            estBudgetEl.innerText = data.cost_range_thb_text || "-";
            estBudgetEl.style.color = "#10B981";
        }
        if (estDisclaimerEl) {
            estDisclaimerEl.innerText = data.disclaimer_th || "ค่าใช้จ่ายจริงอาจสูงหรือต่ำกว่าช่วงประมาณการ ขึ้นอยู่กับจำนวน Token, Thinking Tokens, จำนวนครั้งที่เรียกโมเดล, Failover และขั้นตอนที่เกิดขึ้นจริง";
        }
    } else if (state === 'FAILED') {
        if (estDurationEl) estDurationEl.innerText = "ไม่สามารถตรวจสอบความยาวได้";
        if (estTokensEl) estTokensEl.innerText = "ยังไม่สามารถประมาณได้";
        if (estTokensSubEl) estTokensSubEl.innerText = "";
        if (estBudgetEl) {
            estBudgetEl.innerText = "ยังไม่สามารถประมาณได้";
            estBudgetEl.style.color = "var(--text-secondary)";
        }
        if (estDisclaimerEl) {
            estDisclaimerEl.innerText = data.reason || "ไม่สามารถตรวจสอบความยาวสื่อได้ในขณะนี้ คุณสามารถเลือกวิเคราะห์ต่อได้";
        }

        if (unknownContainer) unknownContainer.style.display = 'block';

        const checkbox = document.getElementById('acceptUnknownEstimate');
        if (checkbox) {
            checkbox.checked = false;
            if (btnContinue) {
                btnContinue.disabled = true;
                btnContinue.style.opacity = '0.5';
                btnContinue.style.cursor = 'not-allowed';
            }
            checkbox.onchange = function() {
                if (btnContinue) {
                    btnContinue.disabled = !this.checked;
                    btnContinue.style.opacity = this.checked ? '1' : '0.5';
                    btnContinue.style.cursor = this.checked ? 'pointer' : 'not-allowed';
                }
            };
        }
    }
}

function normalizeModelKey(rawModel) {
    if (!rawModel) return 'gemini-3.5-flash';
    return rawModel.toLowerCase().replace(/^\d+[\.\s]*/, '').replace(/\s+/g, '-').trim();
}

async function refreshPreRunEstimate({ durationSeconds, selectedModel, sourceType }) {
    const modelSelectEl = document.getElementById('estimatorModelSelect');
    const rawModel = selectedModel || (modelSelectEl ? modelSelectEl.value : 'gemini-3.5-flash');
    const normModel = normalizeModelKey(rawModel);
    const srcType = sourceType || window.currentSourceType || 'youtube';

    if ((!durationSeconds || durationSeconds <= 0) && srcType !== 'tiktok') {
        setEstimatorUIState('FAILED', { reason: 'ไม่พบข้อมูลความยาวสื่อเพื่อประมาณการ' });
        return null;
    }

    if (durationSeconds && durationSeconds > 0) {
        window.currentResolvedDurationSeconds = durationSeconds;
    }

    if (window.currentPreCheckData &&
        window.currentPreCheckData.duration_seconds === durationSeconds &&
        window.currentPreCheckData.all_estimates) {
        const estMap = window.currentPreCheckData.all_estimates;
        const est = estMap[normModel] || estMap[rawModel] || window.currentPreCheckData.estimate;
        if (est && (est.duration_known || est.is_historical_fallback)) {
            setEstimatorUIState('READY', est);
            return est;
        }
    }

    const durLabel = (durationSeconds && durationSeconds > 0) ? formatDurationHHMMSS(durationSeconds) : "ยังไม่ทราบก่อนประมวลผล";
    setEstimatorUIState('ESTIMATING', { duration_formatted: durLabel });

    try {
        let fetchUrl = `/api/pre_run_estimate?model=${encodeURIComponent(normModel)}&source_type=${encodeURIComponent(srcType)}`;
        if (durationSeconds && durationSeconds > 0) {
            fetchUrl += `&duration_seconds=${durationSeconds}`;
        }
        const resp = await fetch(fetchUrl);
        if (resp.ok) {
            const data = await resp.json();
            const estMap = data.all_estimates || {};
            const est = estMap[normModel] || data.estimate;
            if (est && (est.duration_known || est.is_historical_fallback || est.fallback_available)) {
                window.currentPreCheckData = Object.assign({}, window.currentPreCheckData || {}, {
                    duration_seconds: durationSeconds,
                    selected_model: normModel,
                    estimate: est,
                    all_estimates: data.all_estimates
                });
                setEstimatorUIState('READY', est);
                return est;
            } else {
                setEstimatorUIState('FAILED', { reason: 'ไม่สามารถประมาณการสำหรับโมเดลที่เลือกได้' });
            }
        } else {
            setEstimatorUIState('FAILED', { reason: 'การเรียกคำนวณประมาณราคาล้มเหลว' });
        }
    } catch (e) {
        console.error("refreshPreRunEstimate fetch error:", e);
        setEstimatorUIState('FAILED', { reason: 'เกิดข้อผิดพลาดเครือข่ายในการประเมินราคา' });
    }
    return null;
}

window.refreshPreRunEstimate = refreshPreRunEstimate;
window.renderModelEstimate = function(mName) {
    const dur = window.currentResolvedDurationSeconds || (window.currentPreCheckData && window.currentPreCheckData.duration_seconds);
    if (dur && dur > 0) {
        refreshPreRunEstimate({ durationSeconds: dur, selectedModel: mName, sourceType: window.currentSourceType || 'youtube' });
    } else {
        setEstimatorUIState('WAITING_DURATION');
    }
};

async function uploadAndProcessData() {
    const selectedMode = document.querySelector('input[name="mediaMode"]:checked').value;
    const youtubeUrl = document.getElementById('youtubeUrl').value.trim();
    const fileInput = document.getElementById('mediaFile');

    if (selectedMode === 'youtube' && !youtubeUrl) { alert('กรุณาระบุลิงก์วิดีโอก่อนครับ'); return; }
    if (selectedMode === 'mp4') {
        if (fileInput.files.length === 0) {
            alert('กรุณาเลือกไฟล์วิดีโอก่อนประมวลผล');
            return;
        }
        if (fileInput.files[0].size > 2147483648) {
            alert('ไฟล์มีขนาดเกิน 2 GB ไม่สามารถอัปโหลดได้');
            return;
        }
    }

    let sourceType = selectedMode;
    if (selectedMode === 'youtube' && youtubeUrl.toLowerCase().includes('tiktok.com')) {
        sourceType = 'tiktok';
    }
    window.currentSourceType = sourceType;
    window.currentResolvedDurationSeconds = null;

    const processBtn = document.querySelector('.btn-process');
    const modal = document.getElementById('tokenEstimatorModal');
    const statusText = document.getElementById('modal-status-text');
    const calcDetails = document.getElementById('modal-calculation-details');
    const actionsBar = document.getElementById('modalActionsBar');
    
    if (processBtn) {
        processBtn.disabled = true;
        processBtn.dataset.origText = processBtn.innerHTML;
        processBtn.innerHTML = 'กำลังตรวจสอบวิดีโอ...';
    }

    modal.style.display = 'flex';
    calcDetails.style.display = 'block';
    actionsBar.style.display = 'flex';
    statusText.style.display = 'block';
    statusText.innerText = 'กำลังตรวจสอบประวัติการวิเคราะห์และประมาณการ...';

    const cacheHitBox = document.getElementById('modal-cache-hit-box');
    const newEstimateBox = document.getElementById('modal-new-estimate-box');
    if (cacheHitBox) cacheHitBox.style.display = 'none';
    if (newEstimateBox) newEstimateBox.style.display = 'block';

    const modelSelectEl = document.getElementById('estimatorModelSelect');
    const currentSelectedModel = modelSelectEl ? modelSelectEl.value : 'gemini-3.5-flash';

    if (window.currentSourceType === 'tiktok') {
        refreshPreRunEstimate({ selectedModel: currentSelectedModel, sourceType: 'tiktok' });
    } else {
        setEstimatorUIState('WAITING_DURATION');
    }

    if (processBtn) {
        processBtn.disabled = false;
        processBtn.innerHTML = processBtn.dataset.origText || 'เริ่มต้นกระบวนการถอดความและประมวลผลข้อมูลทางสถิติ';
    }

    if (modelSelectEl) {
        modelSelectEl.onchange = function() {
            const durSec = window.currentResolvedDurationSeconds ||
                           (window.currentPreCheckData && window.currentPreCheckData.duration_seconds);
            refreshPreRunEstimate({
                durationSeconds: durSec,
                selectedModel: this.value,
                sourceType: window.currentSourceType || 'youtube'
            });
        };
    }

    const checkForm = new FormData();
    checkForm.append('mode', selectedMode);
    checkForm.append('model', currentSelectedModel);

    let mp4DurationSeconds = null;

    if (selectedMode === 'youtube') {
        checkForm.append('youtube_url', youtubeUrl);
    } else {
        checkForm.append('file_name', fileInput.files[0].name);
        checkForm.append('file_size_bytes', fileInput.files[0].size);
        
        try {
            mp4DurationSeconds = await new Promise((resolve) => {
                if (!fileInput.files || fileInput.files.length === 0) { resolve(null); return; }
                const video = document.createElement('video');
                video.preload = 'metadata';
                let timer = setTimeout(() => {
                    window.URL.revokeObjectURL(video.src);
                    resolve(null);
                }, 4000);
                video.onloadedmetadata = function() {
                    clearTimeout(timer);
                    window.URL.revokeObjectURL(video.src);
                    resolve(video.duration && isFinite(video.duration) && video.duration > 0 ? video.duration : null);
                };
                video.onerror = function() {
                    clearTimeout(timer);
                    window.URL.revokeObjectURL(video.src);
                    resolve(null);
                };
                video.src = URL.createObjectURL(fileInput.files[0]);
            });
        } catch (e) {
            console.error("HTML5 file duration extraction error:", e);
        }
        if (mp4DurationSeconds && mp4DurationSeconds > 0) {
            checkForm.append('duration_seconds', mp4DurationSeconds);
            window.currentResolvedDurationSeconds = mp4DurationSeconds;
        }
    }

    const currentDurationRequestToken = Date.now() + "_" + Math.random().toString(36).substring(2, 9);
    window.activeDurationRequestToken = currentDurationRequestToken;

    try {
        const checkRes = await fetch('/pre_check_cache', { method: 'POST', body: checkForm });
        if (!checkRes.ok) {
            const errData = await checkRes.json().catch(() => ({}));
            const errMsg = errData.detail || "เกิดข้อผิดพลาดในการตรวจสอบข้อมูลล่วงหน้า";
            statusText.innerText = `⚠️ ${errMsg}`;
            return;
        }
        const checkData = await checkRes.json();
        window.currentPreCheckData = checkData;
        statusText.style.display = 'none';

        if (checkData.cache_exists) {
            if (cacheHitBox) cacheHitBox.style.display = 'block';
            
            const btnOpenCache = document.getElementById('btnModalOpenCache');
            const btnReanalyze = document.getElementById('btnModalReanalyze');

            if (btnOpenCache) {
                btnOpenCache.onclick = function() {
                    modal.style.display = 'none';
                    injectProcessedDataToDashboard(checkData.result_data);
                };
            }

            if (btnReanalyze) {
                btnReanalyze.onclick = function() {
                    if (cacheHitBox) cacheHitBox.style.display = 'none';
                    if (newEstimateBox) newEstimateBox.style.display = 'block';
                    const activeModel = modelSelectEl ? modelSelectEl.value : currentSelectedModel;
                    const dur = window.currentResolvedDurationSeconds || checkData.duration_seconds;
                    if (dur && dur > 0) {
                        refreshPreRunEstimate({ durationSeconds: dur, selectedModel: activeModel, sourceType: window.currentSourceType });
                    }
                };
            }

            const dur = window.currentResolvedDurationSeconds || checkData.duration_seconds;
            if (dur && dur > 0) {
                refreshPreRunEstimate({ durationSeconds: dur, selectedModel: currentSelectedModel, sourceType: window.currentSourceType });
            }
        } else {
            if (cacheHitBox) cacheHitBox.style.display = 'none';
            if (newEstimateBox) newEstimateBox.style.display = 'block';

            const effectiveDuration = mp4DurationSeconds || checkData.duration_seconds;

            if (effectiveDuration && effectiveDuration > 0) {
                await refreshPreRunEstimate({
                    durationSeconds: effectiveDuration,
                    selectedModel: currentSelectedModel,
                    sourceType: window.currentSourceType
                });
            } else {
                if (checkData && checkData.estimate && (checkData.estimate.is_historical_fallback || checkData.estimate.fallback_available)) {
                    setEstimatorUIState('READY', checkData.estimate);
                } else if (selectedMode === 'mp4') {
                    setEstimatorUIState('FAILED', { reason: 'ไม่สามารถอ่านความยาวไฟล์ MP4 ได้' });
                } else {
                    setEstimatorUIState('WAITING_DURATION');
                }

                if (selectedMode !== 'mp4') {
                    const resolveForm = new FormData();
                    if (youtubeUrl) resolveForm.append('youtube_url', youtubeUrl);
                    resolveForm.append('url', youtubeUrl);
                    resolveForm.append('source_type', window.currentSourceType);
                    resolveForm.append('model', currentSelectedModel);

                    console.log("[PRE-RUN] URL", youtubeUrl);
                    console.log("[PRE-RUN] SOURCE", window.currentSourceType);
                    console.log("[PRE-RUN] RESOLVE START");

                    fetch('/api/resolve_duration', { method: 'POST', body: resolveForm })
                        .then(res => res.json())
                        .then(async (durData) => {
                            console.log("[PRE-RUN] RESOLVE RESPONSE", durData);
                            console.log("[PRE-RUN] DURATION", durData ? durData.duration_seconds : null);
                            console.log("[PRE-RUN] MODEL", currentSelectedModel);

                            if (window.activeDurationRequestToken !== currentDurationRequestToken) {
                                console.warn("Stale duration resolution response discarded.");
                                return;
                            }

                            if (durData && durData.status === "success" && durData.duration_seconds > 0) {
                                window.currentPreCheckData = durData;
                                const activeModel = modelSelectEl ? modelSelectEl.value : currentSelectedModel;
                                await refreshPreRunEstimate({
                                    durationSeconds: durData.duration_seconds,
                                    selectedModel: activeModel,
                                    sourceType: window.currentSourceType
                                });
                            } else if (durData && durData.estimate && (durData.estimate.is_historical_fallback || durData.estimate.fallback_available)) {
                                window.currentPreCheckData = durData;
                                setEstimatorUIState('READY', durData.estimate);
                            } else {
                                const failReason = (durData && durData.reason) || "ไม่สามารถตรวจสอบความยาวสื่อได้ในขณะนี้";
                                console.warn("[PRE-RUN] DURATION RESOLUTION FAILED:", failReason);
                                setEstimatorUIState('FAILED', { reason: failReason });
                            }
                        })
                        .catch(err => {
                            if (window.activeDurationRequestToken !== currentDurationRequestToken) return;
                            console.error("[PRE-RUN] Async duration resolution failed:", err);
                            setEstimatorUIState('FAILED', { reason: 'เกิดข้อผิดพลาดในการตรวจสอบความยาวสื่อ' });
                        });
                }
            }
        }

        document.getElementById('btnModalContinue').onclick = function() {
            modal.style.display = 'none';
            proceedWithActualAnalysis(selectedMode, youtubeUrl, fileInput);
        };

        document.getElementById('btnModalCancel').onclick = function() {
            modal.style.display = 'none';
        };

    } catch (err) {
        alert("กระบวนการดักตรวจเช็กข้อมูลล่วงหน้าขัดข้อง");
        modal.style.display = 'none';
    }
}

async function proceedWithActualAnalysis(selectedMode, youtubeUrl, fileInput) {
    resetDashboard();
    window.WeFoolApp.state.globalTimelineData = [];
    window.WeFoolApp.state.originalThaiTextArray = [];
    
    document.getElementById('transcript-list').innerHTML = `<p style="color:#FF9800;text-align:center;padding-top:40px;">กำลังเรียกใช้โครงสร้างวิเคราะห์ 9 โมดูลหลัก... กรุณารอสักครู่</p>`;
    document.getElementById('pivotLanguageSelect').value = "TH";
    document.getElementById('live-sub-box').innerText = "[ ระบบกำลังเริ่มประมวลผลวิดีโอใหม่... ]";
    document.getElementById('summary-list').innerHTML = `<p style="color:#64748B;">กำลังดำเนินการถอดความและคัดกรองประเด็นยุทธศาสตร์...</p>`;
    
    document.getElementById('t-duration').innerText = "-";
    document.getElementById('t-words').innerText = "-";
    document.getElementById('t-sentences').innerText = "-";
    document.getElementById('t-wpm').innerText = "-";
    if (document.getElementById('t-topics')) document.getElementById('t-topics').innerText = "-";

    // รีเซ็ตแผงรายละเอียด
    if (document.getElementById('detail-name')) document.getElementById('detail-name').innerText = "-";
    if (document.getElementById('detail-size')) document.getElementById('detail-size').innerText = "-";
    if (document.getElementById('detail-analysis-time')) document.getElementById('detail-analysis-time').innerText = "กำลังคำนวณ...";
    
    if (window.WeFoolApp.state.keywordBarChartInstance) { 
        window.WeFoolApp.state.keywordBarChartInstance.destroy(); 
        window.WeFoolApp.state.keywordBarChartInstance = null; 
    }
    
    window.WeFoolApp.player.updateMoodBadges("ไม่ระบุ");

    const summaryBox = document.getElementById("communication-emotion-summary");
    if (summaryBox) {
        summaryBox.textContent = "กำลังวิเคราะห์ภาพรวมบรรยากาศการนำเสนอของคลิป...";
    }

    const communicationTableBody = document.getElementById("communication-table-body");
    if (communicationTableBody) {
        communicationTableBody.innerHTML = "";
        const loadingRow = document.createElement("tr");
        const loadingCell = document.createElement("td");
        loadingCell.colSpan = 3;
        loadingCell.style.textAlign = "center";
        loadingCell.style.color = "#64748B";
        loadingCell.textContent = "กำลังวิเคราะห์บรรยากาศการนำเสนอ...";
        loadingRow.appendChild(loadingCell);
        communicationTableBody.appendChild(loadingRow);
    }
    document.getElementById('recommend-list').innerHTML = `<p style="text-align:center;color:#64748B;width:100%;">กำลังตรวจสอบข้อมูลเชิงสถิติจากเครือข่ายภายนอก...</p>`;
    document.getElementById('chapters-list-container').innerHTML = `<p style="text-align:center;color:#64748B;width:100%;">กำลังจัดสรรสารบัญพิกัดเวลาตามหัวข้อหลัก...</p>`;

    const formData = new FormData();
    formData.append('mode', selectedMode);

    const modelSelect = document.getElementById('estimatorModelSelect');
    if (modelSelect) {
        formData.append('model', modelSelect.value);
    }

    if (selectedMode === 'youtube') {
        formData.append('youtube_url', youtubeUrl);
    } else {
        formData.append('file', fileInput.files[0]);
    }

    const statusBox = document.getElementById('statusBox');
    if (statusBox) {
        statusBox.style.display = 'block';
    }
    const percentDisplay = document.getElementById('progress-percent-display');
    if (percentDisplay) percentDisplay.innerText = '0%';
    const stageDisplay = document.getElementById('job-stage-display');
    if (stageDisplay) stageDisplay.innerText = 'Queued / อยู่ในคิวประมวลผล';

    try {
        const data = await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/submit_analysis');
            
            if (selectedMode === 'mp4') {
                xhr.upload.onprogress = function(event) {
                    if (event.lengthComputable) {
                        const percentComplete = Math.round((event.loaded / event.total) * 100);
                        if (percentDisplay) percentDisplay.innerText = percentComplete + '%';
                        if (stageDisplay) stageDisplay.innerText = `Uploading / กำลังอัปโหลดไฟล์วิดีโอ (${percentComplete}%)`;
                    }
                };
            }
            
            xhr.onload = function() {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        reject(new Error("การประมวลผลผลลัพธ์ล้มเหลว"));
                    }
                } else {
                    let errMsg = "เกิดข้อผิดพลาดในการส่งคำขอประมวลผล";
                    try {
                        const errData = JSON.parse(xhr.responseText);
                        errMsg = errData.error || errData.detail || errMsg;
                    } catch(e) {}
                    reject(new Error(errMsg));
                }
            };
            
            xhr.onerror = function() {
                reject(new Error("การเชื่อมต่อเครือข่ายปลายทางขัดข้อง"));
            };
            
            xhr.send(formData);
        });

        if (data.job_id) { 
            pollJobStatus(data.job_id); 
        } else {
            if (percentDisplay) percentDisplay.innerText = '100%';
            if (stageDisplay) stageDisplay.innerText = 'Completed / ประมวลผลสำเร็จ';
            injectProcessedDataToDashboard(data);
        }
    } catch (error) {
        alert("ไม่สามารถเริ่มประมวลผลได้: " + error.message);
        if (statusBox) statusBox.style.display = 'none';
    }
}

async function injectProcessedDataToDashboard(data) {
    const statusBox = document.getElementById('statusBox');
    const rootData = data.result ? data.result : data;
    
    window.WeFoolApp.state.globalTimelineData = rootData.timeline || [];
    window.WeFoolApp.state.originalThaiTextArray = window.WeFoolApp.state.globalTimelineData.map(item => item.text);

    // เก็บค่า รหัสมีเดีย สำหรับการดาวน์โหลดโมดูล 9
    window.activeMediaId = data.public_id || (rootData.video_url ? rootData.video_url.split('/').pop().replace('.mp4', '') : null);
    
    // รีเซ็ตสถานะการเลือกดาวน์โหลดเมื่อโหลดวิดีโอใหม่
    currentSelectedDownloadFormat = null;
    document.querySelectorAll('.download-format-card').forEach(card => {
        card.style.borderColor = 'var(--border-color)';
        card.style.boxShadow = 'none';
        card.style.background = 'var(--input-bg)';
    });
    const downloadRadios = document.querySelectorAll('input[name="downloadFormat"]');
    downloadRadios.forEach(radio => radio.checked = false);
    const actionBox = document.getElementById('download-action-box');
    if (actionBox) actionBox.style.display = 'none';

    document.getElementById('modelMarker').innerText = 'สถาปัตยกรรม AI ประมวลผล: ' + (rootData.model_used || 'gemini-3.5-flash');
    renderTranscriptComponent(window.WeFoolApp.state.globalTimelineData);

    // อัปเดตข้อมูลรายละเอียด (Box 2)
    const detailName = rootData.media_name || rootData.real_youtube_url || (rootData.video_url ? rootData.video_url.split('/').pop() : "-");
    const detailSize = rootData.file_size_label || "วิเคราะห์จากระบบคลาวด์";
    const detailAnalysisTime = rootData.analysis_time || "โหลดด่วนจากแคชประวัติ (Instant Cached)";

    if (document.getElementById('detail-name')) document.getElementById('detail-name').innerText = detailName;
    if (document.getElementById('detail-size')) document.getElementById('detail-size').innerText = detailSize;
    if (document.getElementById('detail-analysis-time')) document.getElementById('detail-analysis-time').innerText = detailAnalysisTime;

    let summaryHtml = '<ul>';
    if (rootData.summary && rootData.summary.length > 0) {
        rootData.summary.forEach(item => { summaryHtml += `<li>${item}</li>`; });
    } else {
        summaryHtml += `<li>สกัดย่อโครงสร้างความเรียบร้อยเสร็จสิ้นตามระบบ</li>`;
    }
    summaryHtml += '</ul>';
    document.getElementById('summary-list').innerHTML = summaryHtml;

    if (rootData.telemetry) {
        document.getElementById('t-duration').innerText = normalizeTelemetryValue(rootData.telemetry.duration, "duration");
        document.getElementById('t-words').innerText = normalizeTelemetryValue(rootData.telemetry.words, "words");
        document.getElementById('t-sentences').innerText = normalizeTelemetryValue(rootData.telemetry.sentences, "sentences");
        document.getElementById('t-wpm').innerText = normalizeTelemetryValue(rootData.telemetry.wpm, "wpm");
        if (document.getElementById('t-topics')) document.getElementById('t-topics').innerText = rootData.telemetry.topics || "-";
    }

    window.WeFoolApp.state.globalKeywordsChartData = rootData.keywords_chart || [];
    if (window.WeFoolApp.state.globalKeywordsChartData.length > 0) drawKeywordBarChart(window.WeFoolApp.state.globalKeywordsChartData);
    renderCommunicationModule(
        rootData.communication_analysis || [],
        rootData.communication_distribution || rootData.dominant_sentiment || []
    );
    window.WeFoolApp.state.globalCanonicalEmotion = rootData.current_emotion || "ไม่ระบุ";
    window.WeFoolApp.player.updateMoodBadges(window.WeFoolApp.state.globalCanonicalEmotion);
    renderRecommendations(rootData.recommendations || []);
    renderVideoChaptersModule(rootData.video_chapters || [], rootData.knowledge_tree || null);

    // Initialize media player separately at the end
    try {
        await window.WeFoolApp.player.setupMainPlayer(rootData);
    } catch (playerError) {
        console.error("[RESTORE] player initialization failed:", playerError);
        const wrapper = document.getElementById('playerWrapper');
        if (wrapper) {
            wrapper.innerHTML = `<div class="media-unavailable-notice" style="color:var(--text-secondary); padding:40px; text-align:center; background:var(--input-bg); border-radius:8px; line-height:1.6;">⚠️ ไม่พบไฟล์วิดีโอสำหรับผลการวิเคราะห์นี้<br>ข้อความถอดความและผลวิเคราะห์ยังคงใช้งานได้</div>`;
        }
    }

    statusBox.style.display = 'none';
    document.getElementById('mainDashboardSelector').value = "transcript";
    executeModuleSwitch();
}

function renderTranscriptComponent(items, keyword = "") {
    const listContainer = document.getElementById('transcript-list');
    listContainer.innerHTML = '';

    if (items.length === 0) {
        listContainer.innerHTML = `<p style="color:#64748B;text-align:center;">ไม่พบชุดข้อความที่ตรงตามเงื่อนไขการค้นหา</p>`;
        return;
    }

    const escapedKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const keywordRegex = escapedKeyword ? new RegExp(`(${escapedKeyword})`, "gi") : null;
    let innerHtml = '';

    items.forEach((row, index) => {
        const rowIndex = index;
        let txt = row.text;
        if (keywordRegex) {
            txt = txt.replace(keywordRegex, "<mark>$1</mark>");
        }
        innerHtml += `<div class="transcript-row" id="tx-row-${rowIndex}"><button class="time-badge" onclick="warpToTargetTime(${Number(row.start)})">${window.WeFoolApp.time.formatTranscriptTime(row.start)}</button><div class="phrase-box" onclick="warpToTargetTime(${Number(row.start)})">${txt}</div></div>`;
    });
    listContainer.innerHTML = innerHtml;
}

function filterTranscriptData() {
    const kw = document.getElementById('searchKeyword').value.trim();
    if (!kw) { renderTranscriptComponent(window.WeFoolApp.state.globalTimelineData); return; }
    const filtered = window.WeFoolApp.state.globalTimelineData.filter(item => item.text.toLowerCase().includes(kw.toLowerCase()));
    renderTranscriptComponent(filtered, kw);
}

function renderSentimentModule(list, dominantSummary) {
    const tbody = document.getElementById('sentiment-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    const banner = document.getElementById('dominantSentimentBanner');
    if (banner) {
        banner.innerText = `📊 การวิเคราะห์บรรยากาศการนำเสนอรวม: ${dominantSummary}`;
    }
    if (!list || list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="2" style="text-align:center;">ไม่พบคลิปข้อมูลแจกแจงมิติเชิงจิตวิทยาในตาราง</td></tr>`;
        return;
    }
    list.forEach(row => {
        const tr = document.createElement('tr');
        const atmosKey = window.WeFoolApp.player.getAtmosphereFromEmotion(row.sentiment);
        const atmos = window.WeFoolApp.player.atmospheres[atmosKey] || window.WeFoolApp.player.atmospheres.neutral;
        tr.innerHTML = `
            <td style="vertical-align:top;width:25%; color: var(--primary-color); font-weight: 700;">${row.time_range}</td>
            <td>
                <div style="font-size:15px;color: var(--text-main);margin-bottom:4px; font-weight: 600;">${atmos.icon} ${atmos.name}</div>
                <div style="font-size:12px;color: var(--text-secondary);margin-bottom:2px;">${row.trigger}</div>
                <div style="font-size:12px;color: var(--primary-color);">${row.purpose}</div>
            </td>`;
        tbody.appendChild(tr);
    });
}

function renderCommunicationModule(communicationList, emotionSummary) {
    const tbody = document.getElementById("communication-table-body");
    const summaryContainer = document.getElementById("communication-emotion-summary");

    if (!tbody || !summaryContainer) {
        console.error("Module 6 containers not found");
        return;
    }

    tbody.innerHTML = "";
    let summaryText = "ไม่พบข้อมูลภาพรวมบรรยากาศการนำเสนอ";
    if (typeof emotionSummary === "string" && emotionSummary.trim()) {
        summaryText = emotionSummary;
    } else if (Array.isArray(emotionSummary) && emotionSummary.length > 0) {
        summaryText = emotionSummary.map(item => {
            if (item && typeof item === "object") {
                return `${item.strategy || ""}: ${item.percent || 0}%`;
            }
            return String(item);
        }).join(", ");
    }
    summaryContainer.textContent = summaryText;

    window.WeFoolApp.state.globalCommunicationIntervals = Array.isArray(communicationList) ? communicationList : [];

    if (window.WeFoolApp.state.globalCommunicationIntervals.length === 0) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 3;
        td.style.textAlign = "center";
        td.style.color = "#64748B";
        td.textContent = "ไม่พบข้อมูลบรรยากาศการนำเสนอ";
        tr.appendChild(td);
        tbody.appendChild(tr);
    } else {
        window.WeFoolApp.state.globalCommunicationIntervals.forEach((row, index) => {
            const tr = document.createElement("tr");
            tr.id = `communication-row-${index}`;
            tr.className = "communication-mood-row";

            const timeCell = document.createElement("td");
            const strategyCell = document.createElement("td");
            const emotionCell = document.createElement("td");

            timeCell.textContent = String(row.time_range || "-");
            strategyCell.textContent = String(row.strategy || "-");
            
            const atmosKey = window.WeFoolApp.player.getAtmosphereFromEmotion(row.emotion);
            const atmos = window.WeFoolApp.player.atmospheres[atmosKey] || window.WeFoolApp.player.atmospheres.neutral;

            emotionCell.innerHTML = `<span class="atmosphere-badge" style="
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 12.5px;
                font-weight: 600;
                background: rgba(${atmos.rgb}, 0.15);
                color: ${atmos.color};
                border: 1px solid rgba(${atmos.rgb}, 0.3);
                box-shadow: 0 2px 8px rgba(${atmos.rgb}, 0.1);
            ">${atmos.icon} ${atmos.name}</span>`;

            timeCell.style.color = "var(--primary-color)";
            timeCell.style.fontWeight = "700";
            strategyCell.style.fontWeight = "700";

            tr.appendChild(timeCell);
            tr.appendChild(strategyCell);
            tr.appendChild(emotionCell);
            tbody.appendChild(tr);
        });
    }

    const tableScroll = document.querySelector("#module-sentiment .communication-table-scroll");
    if (tableScroll) {
        tableScroll.scrollTop = 0;
        tableScroll.scrollLeft = 0;
    }
}

function drawKeywordBarChart(chartData) {
    const ctx = document.getElementById('keywordBarChart').getContext('2d');
    if (window.WeFoolApp.state.keywordBarChartInstance) window.WeFoolApp.state.keywordBarChartInstance.destroy();
    const limitedData = chartData.slice(0, 5);

    // ตรวจสอบธีมปัจจุบันเพื่อเลือกสีที่แสดงผลลัพธ์คมชัดสูงสุด
    const isDark = document.documentElement.getAttribute('data-theme') === 'night';
    const textColor = isDark ? '#F5F5F5' : '#111827';
    const subTextColor = isDark ? '#B0B0B0' : '#6B7280';
    const gridColor = isDark ? '#303030' : '#E5E7EB';
    const primaryColor = isDark ? '#3B82F6' : '#2563EB';
    const secondaryColor = isDark ? '#2563EB' : '#3B82F6';

    window.WeFoolApp.state.keywordBarChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: limitedData.map(item => item.keyword),
            datasets: [{ 
                label: 'อัตราความถี่ความหนาแน่นของการตรวจพบคำสำคัญ', 
                data: limitedData.map(item => item.count), 
                backgroundColor: primaryColor, 
                borderColor: secondaryColor, 
                borderWidth: 1 
            }]
        },
        options: { 
            responsive: true, 
            maintainAspectRatio: false, 
            scales: { 
                y: { 
                    ticks: { color: subTextColor }, 
                    grid: { color: gridColor } 
                }, 
                x: { 
                    ticks: { color: textColor }, 
                    grid: { display: false } 
                } 
            }, 
            plugins: { 
                legend: { 
                    labels: { 
                        color: textColor, 
                        font: { family: 'Sarabun', weight: 'bold' } 
                    } 
                } 
            } 
        }
    });
}

function renderRecommendations(cards) {
    const container = document.getElementById('recommend-list');
    container.innerHTML = '';
    if (!cards || cards.length === 0) { 
        container.innerHTML = `<p style="color:#64748B;text-align:center;">ไม่พบผลลัพธ์สื่อความใกล้เคียงที่เกี่ยวข้องในฐานระบบ</p>`; 
        return; 
    }
    cards.forEach((card, index) => {
        const rowDiv = document.createElement('div');
        rowDiv.className = 'recommend-row-item';
        rowDiv.innerHTML = `<div class="recommend-row-title">${index + 1}. ${card.title}</div><a href="${card.url}" target="_blank" class="recommend-cover-link"><img src="${card.thumbnail}" class="recommend-cover-img"></a>`;
        container.appendChild(rowDiv);
    });
}

async function executePivotTranslation() {
    let lang = document.getElementById('pivotLanguageSelect').value;
    if (window.WeFoolApp.state.originalThaiTextArray.length === 0) return;
    if (lang === "TH") { 
        window.WeFoolApp.state.globalTimelineData.forEach((item, idx) => { 
            item.text = window.WeFoolApp.state.originalThaiTextArray[idx]; 
        }); 
        renderTranscriptComponent(window.WeFoolApp.state.globalTimelineData); 
        return; 
    }
    
    document.getElementById('transcript-list').innerHTML = `<p style="color:#FF9800;text-align:center;padding-top:40px;">ระบบกำลังส่งสัญญาณแปลชุดโครงสร้างภาษาปลายทางไปยังโครงข่าย AI...</p>`;
    const fData = new FormData(); 
    fData.append('target_lang', lang); 
    fData.append('transcript_text', window.WeFoolApp.state.originalThaiTextArray.join("\n"));

    try {
        const res = await fetch('/translate_timeline', { method: 'POST', body: fData });
        const resData = await res.json();
        if (resData.translated_lines) { 
            window.WeFoolApp.state.globalTimelineData.forEach((item, idx) => { 
                item.text = resData.translated_lines[idx] || item.text; 
            }); 
            renderTranscriptComponent(window.WeFoolApp.state.globalTimelineData); 
        }
    } catch (e) { 
        alert("กระบวนการแปลชุดภาษาขัดข้องในโครงข่ายย่อย"); 
    }
}

function renderVideoChaptersModule(chapters, knowledgeTree) {
    const container = document.getElementById('chapters-list-container');
    container.innerHTML = '';
    
    // [อัปเดตหลักการ Module 8]: ถ้ามีแผนผังองค์ความรู้ (Knowledge Tree) โครงสร้างใหม่ 2 ระดับ
    if (knowledgeTree && knowledgeTree.main_topics && knowledgeTree.main_topics.length > 0) {
        knowledgeTree.main_topics.forEach(topic => {
            const accordionDetails = document.createElement('details');
            accordionDetails.className = 'chapter-accordion-box';

            const accordionSummary = document.createElement('summary');
            accordionSummary.className = 'chapter-summary-bar';
            
            const mainTitle = topic.title || "หัวข้อองค์ความรู้หลัก";
            
            accordionSummary.innerHTML = `
                <div class="summary-left-content">
                    <span class="main-chapter-title">${mainTitle}</span>
                </div>
                <span class="toggle-icon-indicator">▼</span>
            `;
            
            accordionDetails.appendChild(accordionSummary);

            const subChaptersWrapper = document.createElement('div');
            subChaptersWrapper.className = 'sub-chapters-dropdown-container';
            subChaptersWrapper.style.maxHeight = 'none'; // ขยายความยาวได้เต็มพิกัดของโครงสร้างต้นไม้
            subChaptersWrapper.style.gap = '12px';
            subChaptersWrapper.style.padding = '18px 20px';

            // แสดงสรุปหัวข้อหลักแบบกระชับ (Main Topic Summary)
            if (topic.summary) {
                const mainSummaryEl = document.createElement('div');
                mainSummaryEl.style.fontSize = '13px';
                mainSummaryEl.style.color = 'var(--text-desc)';
                mainSummaryEl.style.fontStyle = 'italic';
                mainSummaryEl.style.marginBottom = '8px';
                mainSummaryEl.style.lineHeight = '1.5';
                mainSummaryEl.style.borderBottom = '1px solid var(--border-color)';
                mainSummaryEl.style.paddingBottom = '8px';
                mainSummaryEl.innerText = `สรุปภาพรวม: ${topic.summary}`;
                subChaptersWrapper.appendChild(mainSummaryEl);
            }

            if (topic.sub_topics && topic.sub_topics.length > 0) {
                topic.sub_topics.forEach(sub => {
                    const subItemCard = document.createElement('div');
                    subItemCard.className = 'sub-chapter-node-item';
                    subItemCard.style.padding = '12px 16px';
                    subItemCard.style.flexDirection = 'column';
                    subItemCard.style.alignItems = 'flex-start';
                    subItemCard.style.gap = '6px';
                    
                    const subTitle = sub.title || "หัวข้อย่อยไม่มีชื่อ";
                    const subSummary = sub.summary || "";
                    
                    // คำนวณเวลาเริ่มต้นแรกสุดสำหรับกระโดดเล่นวิดีโอ
                    const firstStart = sub.time_ranges && sub.time_ranges.length > 0 ? sub.time_ranges[0].start : 0;
                    
                    // สร้างป้ายระบุเวลา (Time metadata)
                    let timeLabel = "⏱️ ไม่ระบุเวลา";
                    if (sub.time_ranges && sub.time_ranges.length > 0) {
                        const firstRange = sub.time_ranges[0];
                        timeLabel = `⏱️ ${window.WeFoolApp.time.formatSecondsToLabel(firstRange.start)} - ${window.WeFoolApp.time.formatSecondsToLabel(firstRange.end)}`;
                        if (sub.time_ranges.length > 1) {
                            timeLabel += ` (+${sub.time_ranges.length - 1} ช่วงเวลาเพิ่มเติม)`;
                        }
                    }

                    subItemCard.innerHTML = `
                        <div style="display:flex; justify-space-between; align-items:center; width:100%; gap:12px; flex-wrap:wrap;">
                            <span class="sub-node-text" style="font-weight:700; color:var(--text-main); font-size:13.5px; text-align:left;">🔹 ${subTitle}</span>
                            <span class="sub-node-time" style="min-width:auto; font-size:12px; color:var(--primary-color); font-weight:700;">${timeLabel}</span>
                        </div>
                        <p style="margin: 4px 0 0 0; font-size: 12.5px; color: var(--text-desc); line-height: 1.5; text-align: left; width: 100%;">${subSummary}</p>
                    `;
                    
                    subItemCard.onclick = (e) => {
                        e.stopPropagation(); 
                        window.WeFoolApp.player.warpToTargetTime(firstStart);
                    };
                    
                    subChaptersWrapper.appendChild(subItemCard);
                });
            } else {
                subChaptersWrapper.innerHTML = `<div style="color:#64748B; font-size:12px; padding: 5px 0;">🔍 ไม่พบหัวข้อย่อยสำหรับหมวดหมู่นี้</div>`;
            }

            accordionDetails.appendChild(subChaptersWrapper);
            container.appendChild(accordionDetails);
        });
        return;
    }

    // 🎯 [ระบบบานพับสารบัญแบบเดิม - Fallback ในกรณีที่เป็นแคชประวัติเก่า]:
    if (!chapters || chapters.length === 0) {
        container.innerHTML = `<p style="text-align:center;color:#64748B;width:100%;">🔍 ไม่พบหัวข้อหลักหรือหัวข้อย่อยจากผลวิเคราะห์</p>`;
        return;
    }
    
    chapters.forEach(ch => {
        const accordionDetails = document.createElement('details');
        accordionDetails.className = 'chapter-accordion-box';

        const accordionSummary = document.createElement('summary');
        accordionSummary.className = 'chapter-summary-bar';
        
        const chTitle = ch.chapter_title || "หัวข้อไม่มีชื่อ";
        const chTime = ch.time_range_label || "00:00";
        
        accordionSummary.innerHTML = `
            <div class="summary-left-content">
                <span class="main-chapter-time">⏱️ ${chTime}</span>
                <span class="main-chapter-title">${chTitle}</span>
            </div>
            <span class="toggle-icon-indicator">▼</span>
        `;
        
        accordionDetails.appendChild(accordionSummary);

        if (ch.sub_chapters && ch.sub_chapters.length > 0) {
            const subChaptersWrapper = document.createElement('div');
            subChaptersWrapper.className = 'sub-chapters-dropdown-container';

            ch.sub_chapters.forEach(sub => {
                const subItemCard = document.createElement('div');
                subItemCard.className = 'sub-chapter-node-item';
                
                const subTitle = sub.sub_title || "หัวข้อย่อยไม่มีชื่อ";
                const subTime = sub.time_range_label || "00:00";
                const subStart = sub.start_time_seconds || 0;
                
                subItemCard.innerHTML = `
                    <span class="sub-node-time">📌 ${subTime}</span>
                    <span class="sub-node-text">${subTitle}</span>
                `;
                
                subItemCard.onclick = (e) => {
                    e.stopPropagation(); 
                    window.WeFoolApp.player.warpToTargetTime(subStart);
                };
                
                subChaptersWrapper.appendChild(subItemCard);
            });
            accordionDetails.appendChild(subChaptersWrapper);
        } else {
            const noSubWrapper = document.createElement('div');
            noSubWrapper.className = 'sub-chapters-dropdown-container';
            noSubWrapper.innerHTML = `<div style="color:#64748B; font-size:12px; padding: 5px 15px;">🔍 ไม่พบหัวข้อย่อยสำหรับบทเรียนหลักนี้</div>`;
            accordionDetails.appendChild(noSubWrapper);
        }
        
        container.appendChild(accordionDetails);
    });
}

// --- 🖱️ ระบบ Spotlight Hover Effect จับพิกัดเมาส์เรืองแสงสไตล์ Sci-Fi ---
function initSpotlight() {
    document.addEventListener('mousemove', (e) => {
        const card = e.target.closest('.dashboard-box');
        if (!card) return;
        
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left; // พิกัด X สัมพัทธ์กับการ์ด
        const y = e.clientY - rect.top;  // พิกัด Y สัมพัทธ์กับการ์ด
        
        card.style.setProperty('--mouse-x', `${x}px`);
        card.style.setProperty('--mouse-y', `${y}px`);
    });
}

// โหลด Spotlight ทันทีพร้อม DOM
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSpotlight);
} else {
    initSpotlight();
}

// --- 📥 โมดูลที่ 9: ระบบควบคุมและดาวน์โหลดคำบรรยาย (Module 9 Engine) ---
let currentSelectedDownloadFormat = null;

function handleDownloadFormatChange(format) {
    currentSelectedDownloadFormat = format;
    
    // รีเซ็ตการไฮไลท์ทุกการ์ด
    document.querySelectorAll('.download-format-card').forEach(card => {
        card.style.borderColor = 'var(--border-color)';
        card.style.boxShadow = 'none';
        card.style.background = 'var(--input-bg)';
    });
    
    // ไฮไลท์การ์ดที่ถูกเลือก
    const selectedId = 'card-format-' + format;
    const selectedCard = document.getElementById(selectedId);
    if (selectedCard) {
        selectedCard.style.borderColor = 'var(--primary-color)';
        selectedCard.style.boxShadow = '0 0 15px rgba(37, 99, 235, 0.2)';
        selectedCard.style.background = 'var(--box-inner-bg)';
    }
    
    // แสดงกล่องปุ่มดาวน์โหลดอย่างนุ่มนวล
    const actionBox = document.getElementById('download-action-box');
    if (actionBox) {
        actionBox.style.display = 'block';
    }
}

function executeDownloadAction() {
    if (!window.activeMediaId) {
        alert('❌ กรุณาทำการประมวลผลหรือโหลดข้อมูลสื่อก่อนทำรายการดาวน์โหลดครับ');
        return;
    }
    if (!currentSelectedDownloadFormat) {
        alert('❌ กรุณาเลือกรูปแบบไฟล์ (.txt หรือ .pdf) ก่อนครับ');
        return;
    }
    
    // ทริกเกอร์เรียกเปิดลิงก์ดาวน์โหลดหน้าต่างใหม่
    const downloadUrl = `/download/${currentSelectedDownloadFormat}/${window.activeMediaId}`;
    window.open(downloadUrl, '_blank');
}

// --- 🔄 ระบบกู้คืนผลวิเคราะห์จากประวัติ (Phase 17.5) ---

function resetDashboard() {
    // 1. Stop active timers and reset player variables
    if (window.WeFoolApp && window.WeFoolApp.player && window.WeFoolApp.player.resetPlayerState) {
        window.WeFoolApp.player.resetPlayerState();
    }
    if (window.WeFoolApp && window.WeFoolApp.state) {
        clearInterval(window.WeFoolApp.state.ytTimerInterval);
    }
    
    // Stop HTML5 video safely if it exists
    const wrapper = document.getElementById('playerWrapper');
    if (wrapper) {
        const oldVideo = wrapper.querySelector('video');
        if (oldVideo) {
            try {
                oldVideo.pause();
                oldVideo.src = "";
                oldVideo.load();
            } catch (e) {}
        }
        wrapper.innerHTML = '';
    }

    // 2. Destroy Chart.js instances
    if (window.WeFoolApp && window.WeFoolApp.state && window.WeFoolApp.state.keywordBarChartInstance) {
        window.WeFoolApp.state.keywordBarChartInstance.destroy();
        window.WeFoolApp.state.keywordBarChartInstance = null;
    }

    // 3. Clear old state variables
    if (window.WeFoolApp && window.WeFoolApp.state) {
        window.WeFoolApp.state.activeAnalysisId = null;
        window.WeFoolApp.state.activeRecordMetadata = null;
        window.WeFoolApp.state.globalTimelineData = [];
        window.WeFoolApp.state.originalThaiTextArray = [];
        window.WeFoolApp.state.globalKeywordsChartData = [];
        window.WeFoolApp.state.globalCommunicationIntervals = [];
        window.WeFoolApp.state.globalCanonicalEmotion = "ไม่ระบุ";
        window.WeFoolApp.state.activeCommunicationRow = null;
        window.WeFoolApp.state.lastCommunicationIndex = -1;
    }

    // 4. Clear module DOM contents
    if (document.getElementById('transcript-list')) document.getElementById('transcript-list').innerHTML = '';
    if (document.getElementById('summary-list')) document.getElementById('summary-list').innerHTML = '';
    const recommendList = document.getElementById('recommend-list');
    if (recommendList) recommendList.innerHTML = '';
    const chaptersList = document.getElementById('chapters-list-container');
    if (chaptersList) chaptersList.innerHTML = '';
    
    // Telemetry DOM elements
    if (document.getElementById('t-duration')) document.getElementById('t-duration').innerText = '-';
    if (document.getElementById('t-words')) document.getElementById('t-words').innerText = '-';
    if (document.getElementById('t-sentences')) document.getElementById('t-sentences').innerText = '-';
    if (document.getElementById('t-wpm')) document.getElementById('t-wpm').innerText = '-';
    if (document.getElementById('t-topics')) document.getElementById('t-topics').innerText = '-';

    // Detail panels
    if (document.getElementById('detail-name')) document.getElementById('detail-name').innerText = '-';
    if (document.getElementById('detail-size')) document.getElementById('detail-size').innerText = '-';
    if (document.getElementById('detail-analysis-time')) document.getElementById('detail-analysis-time').innerText = '-';

    // Subtitle & mood
    if (document.getElementById('live-sub-box')) document.getElementById('live-sub-box').innerText = '';
    if (window.WeFoolApp && window.WeFoolApp.player && window.WeFoolApp.player.updateMoodBadges) {
        window.WeFoolApp.player.updateMoodBadges("ไม่ระบุ");
    }

    // Communication strategy
    const commTableBody = document.getElementById("communication-table-body");
    if (commTableBody) commTableBody.innerHTML = "";
    const commSummary = document.getElementById("communication-emotion-summary");
    if (commSummary) commSummary.textContent = "";
}

let isRestoring = false;

function normalizeRestoredAnalysisForDashboard(apiPayload) {
    if (!apiPayload || !apiPayload.result_data) return {};
    
    // Merge result_data and root metadata
    const dashboardPayload = {
        ...apiPayload.result_data,
        public_id: apiPayload.public_id,
        display_title: apiPayload.display_title,
        source_type: apiPayload.source_type,
        source_url: apiPayload.source_url,
        original_filename: apiPayload.original_filename,
        media_name: apiPayload.display_title || apiPayload.original_filename,
        model_used: apiPayload.result_data.model_used || apiPayload.model_used
    };
    
    return dashboardPayload;
}

async function restoreAnalysisFromHistory(analysisId) {
    // Validate UUID format
    if (!analysisId || !/^[a-zA-Z0-9\-]{36}$/.test(analysisId)) {
        alert("รหัสการวิเคราะห์ไม่ถูกต้อง");
        return;
    }

    if (isRestoring) return;
    isRestoring = true;

    // 1. Reset Dashboard
    console.log("[RESTORE] reset started");
    resetDashboard();
    console.log("[RESTORE] reset completed");

    // 2. Show lightweight loading state
    const statusBox = document.getElementById('statusBox');
    const percentDisplay = document.getElementById('progress-percent-display');
    const stageDisplay = document.getElementById('job-stage-display');
    
    if (statusBox) statusBox.style.display = 'block';
    if (percentDisplay) percentDisplay.innerText = '';
    if (stageDisplay) stageDisplay.innerText = 'กำลังเปิดผลวิเคราะห์เดิม...';

    try {
        // 3. Request the saved result
        console.log("[RESTORE] request started");
        const res = await fetch(`/api/analyses/${analysisId}`, {
            method: 'GET',
            credentials: 'same-origin'
        });

        console.log("[RESTORE] response status: " + res.status);

        if (res.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP error! status: ${res.status}`);
        }

        const data = await res.json();
        console.log("[RESTORE] response payload keys: " + Object.keys(data).join(", "));

        // 4. Normalize API response
        const normalized = normalizeRestoredAnalysisForDashboard(data);

        // 5. Switch to or scroll to the main Dashboard results area
        const dashboardBox = document.querySelector('.dashboard-container') || document.querySelector('.main-dashboard-grid');
        if (dashboardBox) {
            dashboardBox.scrollIntoView({ behavior: 'smooth' });
        }

        // 6. Populate source input for reference only, without submitting it
        const youtubeInput = document.getElementById('youtubeUrlInput');
        if (youtubeInput && data.source_url) {
            youtubeInput.value = data.source_url;
        }
        const youtubeUrlElem = document.getElementById('youtubeUrl');
        if (youtubeUrlElem && data.source_url) {
            youtubeUrlElem.value = data.source_url;
        }

        // 7. Restore file details
        if (data.source_type === "upload" || data.source_type === "file" || data.source_type === "mp4") {
            const fileUploadInfo = document.getElementById('file-upload-info');
            if (fileUploadInfo) {
                fileUploadInfo.textContent = data.original_filename || "ไฟล์อัปโหลดเดิม";
            }
        }

        // 8. Restore canonical application state
        if (window.WeFoolApp && window.WeFoolApp.state) {
            window.WeFoolApp.state.activeAnalysisId = data.public_id;
            window.WeFoolApp.state.activeRecordMetadata = {
                public_id: data.public_id,
                display_title: data.display_title,
                source_type: data.source_type,
                source_url: data.source_url,
                original_filename: data.original_filename,
                duration_seconds: data.duration_seconds,
                created_at: data.created_at,
                completed_at: data.completed_at
            };
        }

        // 9. Call existing Dashboard renderers
        console.log("[RESTORE] injection started");
        await injectProcessedDataToDashboard(normalized);
        console.log("[RESTORE] injection completed");

        // 10. Clear loading state
        if (statusBox) statusBox.style.display = 'none';

        // 11. Show dashboard
        console.log("[RESTORE] dashboard visible");
        console.log("[RESTORE] final active analysis id: " + window.WeFoolApp.state.activeAnalysisId);

        // 12. Update browser URL history state (push or replace state)
        const newUrl = `${window.location.pathname}?analysis_id=${analysisId}`;
        window.history.pushState({ analysisId: analysisId }, '', newUrl);

    } catch (err) {
        console.error("Restoration error:", err);
        if (statusBox) statusBox.style.display = 'none';
        
        let friendlyReason = "เกิดข้อผิดพลาดในการโหลดข้อมูล";
        if (err.message.includes("404")) {
            friendlyReason = "ไม่พบรายการ หรือคุณไม่มีสิทธิ์เข้าถึงรายการนี้";
        } else if (err.message.includes("409")) {
            friendlyReason = "รายการยังประมวลผลไม่เสร็จ";
        } else if (err.message.includes("400")) {
            friendlyReason = "รหัสการวิเคราะห์ไม่ถูกต้อง";
        } else if (err.message.includes("SyntaxError") || err.message.includes("JSON")) {
            friendlyReason = "รูปแบบข้อมูลที่บันทึกไว้ไม่สมบูรณ์";
        } else if (err.message) {
            friendlyReason = err.message;
        }
        
        alert(`ไม่สามารถเปิดผลวิเคราะห์เดิมได้: ${friendlyReason}`);
    } finally {
        isRestoring = false;
    }
}

async function checkAndRestoreFromQuery() {
    console.log("[RESTORE] DOM ready");
    const urlParams = new URLSearchParams(window.location.search);
    const analysisId = urlParams.get('analysis_id');
    console.log("[RESTORE] query analysis_id: " + analysisId);
    if (analysisId) {
        if (/^[a-zA-Z0-9\-]{36}$/.test(analysisId)) {
            restoreAnalysisFromHistory(analysisId);
        }
    }
}

// Setup window listener for popstate (browser back/forward navigation)
window.addEventListener('popstate', (event) => {
    const urlParams = new URLSearchParams(window.location.search);
    const analysisId = urlParams.get('analysis_id');
    if (analysisId) {
        if (/^[a-zA-Z0-9\-]{36}$/.test(analysisId)) {
            restoreAnalysisFromHistory(analysisId);
        }
    } else {
        resetDashboard();
    }
});

// Expose in namespaces
window.WeFoolApp = window.WeFoolApp || {};
window.WeFoolApp.analysis = window.WeFoolApp.analysis || {};
window.WeFoolApp.analysis.restoreSavedResult = restoreAnalysisFromHistory;
window.restoreAnalysisFromHistory = restoreAnalysisFromHistory;
window.resetDashboard = resetDashboard;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkAndRestoreFromQuery);
} else {
    checkAndRestoreFromQuery();
}

function normalizeTelemetryValue(val, type) {
    if (val === null || val === undefined || String(val).trim() === "" || String(val).trim() === "-") {
        return "-";
    }
    
    if (type === "duration") {
        const strVal = String(val).trim();
        if (strVal.includes("นาที") || strVal.includes("วินาที")) {
            return strVal;
        }
        const seconds = parseInt(strVal.replace(/[^0-9]/g, ''), 10);
        if (!isNaN(seconds)) {
            const minutes = Math.floor(seconds / 60);
            const remSeconds = seconds % 60;
            if (minutes > 0) {
                return `${minutes} นาที ${remSeconds} วินาที`;
            } else {
                return `${remSeconds} วินาที`;
            }
        }
        return strVal;
    }

    const numericStr = String(val).replace(/[^0-9]/g, '');
    if (numericStr === "") {
        return "-";
    }
    
    const num = parseInt(numericStr, 10);
    if (isNaN(num)) {
        return "-";
    }
    
    const formattedNum = num.toLocaleString('en-US');
    
    if (type === "words") {
        return `${formattedNum} คำ`;
    } else if (type === "sentences") {
        return `${formattedNum} ประโยค`;
    } else if (type === "wpm") {
        return `${formattedNum} คำ/นาที`;
    }
    
    return val;
}
