/**
 * YAMASEE Video Comparison History JS
 */
document.addEventListener('DOMContentLoaded', () => {
    let currentPage = 1;
    let totalPages = 1;

    const historyLoading = document.getElementById('historyLoading');
    const historyEmpty = document.getElementById('historyEmpty');
    const historyGrid = document.getElementById('historyGrid');
    const paginationContainer = document.getElementById('paginationContainer');
    const btnPrevPage = document.getElementById('btnPrevPage');
    const btnNextPage = document.getElementById('btnNextPage');
    const pageIndicator = document.getElementById('pageIndicator');

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

    if (btnPrevPage) {
        btnPrevPage.addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                loadHistory(currentPage);
            }
        });
    }

    if (btnNextPage) {
        btnNextPage.addEventListener('click', () => {
            if (currentPage < totalPages) {
                currentPage++;
                loadHistory(currentPage);
            }
        });
    }

    loadHistory(currentPage);

    async function loadHistory(page = 1) {
        historyLoading.style.display = 'block';
        historyEmpty.style.display = 'none';
        historyGrid.style.display = 'none';
        paginationContainer.style.display = 'none';

        try {
            const resp = await fetch(`/api/comparison/history?page=${page}&page_size=12`);
            if (!resp.ok) throw new Error('ไม่สามารถโหลดประวัติการเปรียบเทียบได้');

            const data = await resp.json();
            historyLoading.style.display = 'none';

            const items = data.items || [];
            totalPages = data.total_pages || 1;
            currentPage = data.page || 1;

            if (items.length === 0) {
                historyEmpty.style.display = 'block';
                return;
            }

            historyGrid.style.display = 'grid';
            renderHistoryCards(items);

            if (totalPages > 1) {
                paginationContainer.style.display = 'flex';
                pageIndicator.textContent = `หน้า ${currentPage} / ${totalPages}`;
                btnPrevPage.disabled = currentPage <= 1;
                btnNextPage.disabled = currentPage >= totalPages;
            }
        } catch (err) {
            console.error('Failed to load comparison history:', err);
            historyLoading.style.display = 'none';
            historyEmpty.style.display = 'block';
        }
    }

    function renderHistoryCards(items) {
        historyGrid.innerHTML = '';
        items.forEach(item => {
            const card = document.createElement('div');
            card.className = 'history-item-card card-inner';

            const videoA = item.video_a || {};
            const videoB = item.video_b || {};

            const dateStr = formatDate(item.created_at);
            const modelUsed = item.model_used || 'gemini-2.5-flash';
            const procSecFormatted = typeof formatProcessingTime === 'function' ? formatProcessingTime(item.processing_seconds) : (item.processing_seconds || 0).toFixed(2);
            const totalTokens = (item.total_tokens || 0).toLocaleString();
            const apiCalls = item.api_calls !== undefined ? item.api_calls : 1;
            const isCached = item.cached || apiCalls === 0;

            const cacheBadgeHtml = isCached
                ? '<span class="status-badge-chip cached">⚡ Cached (0 Calls)</span>'
                : '<span class="status-badge-chip generated">✨ Generated</span>';

            card.innerHTML = `
                <div class="card-header-row">
                    <div class="comp-pair-thumbs">
                        <div class="thumb-slot">
                            <img src="${videoA.thumbnail_url || '/static/Logo_boy.png'}" alt="A">
                            <span class="slot-tag slot-a">A</span>
                        </div>
                        <div class="vs-mini">VS</div>
                        <div class="thumb-slot">
                            <img src="${videoB.thumbnail_url || '/static/Logo_boy.png'}" alt="B">
                            <span class="slot-tag slot-b">B</span>
                        </div>
                    </div>
                    <div class="comp-status-meta">
                        ${cacheBadgeHtml}
                        <span class="date-tag">📅 ${dateStr}</span>
                    </div>
                </div>

                <div class="card-titles-row">
                    <div class="title-block">
                        <span class="slot-label slot-a">VIDEO A</span>
                        <h3 class="v-title">${escapeHtml(videoA.title || 'Video A')}</h3>
                    </div>
                    <div class="title-block">
                        <span class="slot-label slot-b">VIDEO B</span>
                        <h3 class="v-title">${escapeHtml(videoB.title || 'Video B')}</h3>
                    </div>
                </div>

                <div class="telemetry-info-grid">
                    <div class="telem-item">🤖 Model: <strong>${escapeHtml(modelUsed)}</strong></div>
                    <div class="telem-item">⏱️ Time: <strong>${procSecFormatted}</strong></div>
                    <div class="telem-item">📊 Tokens: <strong>${totalTokens}</strong></div>
                    <div class="telem-item">📞 API Calls: <strong>${apiCalls}</strong></div>
                </div>

                <div class="card-actions-row">
                    <a href="/comparison/${item.public_id}" class="btn btn-primary btn-view-result">
                        👁️ ดูผลอีกครั้ง
                    </a>
                    <button type="button" class="btn btn-outline btn-delete-comparison" data-public-id="${escapeHtml(item.public_id)}">
                        ลบ
                    </button>
                </div>
            `;
            historyGrid.appendChild(card);
        });

        historyGrid.querySelectorAll('.btn-delete-comparison').forEach(button => {
            button.addEventListener('click', async () => {
                const publicId = button.getAttribute('data-public-id');
                if (!publicId || !window.confirm('ต้องการลบประวัติการเปรียบเทียบรายการนี้หรือไม่?')) return;

                button.disabled = true;
                try {
                    const resp = await fetch(`/api/comparison/${encodeURIComponent(publicId)}`, { method: 'DELETE' });
                    if (!resp.ok) {
                        const error = await resp.json().catch(() => ({}));
                        throw new Error(error.detail || 'ไม่สามารถลบประวัติการเปรียบเทียบได้');
                    }
                    window.alert('ลบประวัติการเปรียบเทียบแล้ว');
                    const remainingCards = historyGrid.querySelectorAll('.history-item-card').length - 1;
                    if (remainingCards === 0 && currentPage > 1) currentPage--;
                    await loadHistory(currentPage);
                } catch (err) {
                    console.error('Failed to delete comparison:', err);
                    window.alert(err.message || 'ไม่สามารถลบประวัติการเปรียบเทียบได้');
                    button.disabled = false;
                }
            });
        });
    }

    function formatDate(dateStr) {
        if (!dateStr) return '-';
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString('th-TH', {
                day: 'numeric',
                month: 'short',
                year: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
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
});
