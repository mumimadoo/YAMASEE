window.WeFoolApp = window.WeFoolApp || {};
window.WeFoolApp.api = window.WeFoolApp.api || {};

function checkUnauthorized(res) {
    if (res && res.status === 401) {
        localStorage.removeItem('activeJobId');
        alert("เซสชันของคุณหมดอายุ หรือจำเป็นต้องเข้าสู่ระบบก่อนใช้งาน");
        window.location.href = "/login";
        return true;
    }
    return false;
}

window.WeFoolApp.api.checkUnauthorized = checkUnauthorized;
window.checkUnauthorized = checkUnauthorized; // Expose globally for backwards compatibility
