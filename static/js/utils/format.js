window.WeFoolApp = window.WeFoolApp || {};
window.WeFoolApp.format = window.WeFoolApp.format || {};

// HTML escaping helper
function escapeHtml(text) {
    if (!text) return "";
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Safe text fallback
function safeFallback(value, fallback = "ไม่ระบุ") {
    if (value === undefined || value === null || String(value).trim() === "") {
        return fallback;
    }
    return value;
}

window.WeFoolApp.format.escapeHtml = escapeHtml;
window.WeFoolApp.format.safeFallback = safeFallback;

window.escapeHtml = escapeHtml;
window.safeFallback = safeFallback;
