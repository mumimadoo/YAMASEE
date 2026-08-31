document.addEventListener('DOMContentLoaded', () => {
    const changePasswordForm = document.getElementById('changePasswordForm');
    const currentPasswordInput = document.getElementById('currentPassword');
    const newPasswordInput = document.getElementById('newPassword');
    const confirmPasswordInput = document.getElementById('confirmPassword');
    const alertBanner = document.getElementById('alertBanner');
    const submitBtn = document.getElementById('submitBtn');
    const submitBtnText = document.getElementById('submitBtnText');
    const submitSpinner = document.getElementById('submitSpinner');
    const logoutBtn = document.getElementById('logoutBtn');

    // Logout Action
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/auth/logout', { method: 'POST' });
                const data = await res.json();
                if (data.redirect_url) {
                    window.location.href = data.redirect_url;
                }
            } catch (err) {
                console.error('Logout error:', err);
            }
        });
    }

    // Toggle Password Visibility
    const toggleBtns = document.querySelectorAll('.btn-toggle-password');
    toggleBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            const targetInput = document.getElementById(targetId);
            if (targetInput) {
                const isPassword = targetInput.type === 'password';
                targetInput.type = isPassword ? 'text' : 'password';
                btn.textContent = isPassword ? 'Hide' : 'Show';
            }
        });
    });

    function showAlert(message, type = 'danger') {
        if (alertBanner) {
            alertBanner.textContent = message; // Safe textContent to prevent XSS
            alertBanner.className = `alert-banner alert-${type}`;
            alertBanner.style.display = 'block';
        }
    }

    function hideAlert() {
        if (alertBanner) {
            alertBanner.className = 'alert-banner';
            alertBanner.textContent = '';
            alertBanner.style.display = 'none';
        }
    }

    function setLoading(isLoading) {
        if (submitBtn) submitBtn.disabled = isLoading;
        if (submitSpinner) submitSpinner.style.display = isLoading ? 'inline-block' : 'none';
        if (submitBtnText) {
            submitBtnText.textContent = isLoading ? 'กำลังเปลี่ยนรหัสผ่าน...' : 'เปลี่ยนรหัสผ่านและเข้าสู่แดชบอร์ด';
        }
    }

    function validatePasswordComplexity(pwd) {
        if (pwd.length < 8) return false;
        const hasLetter = /[a-zA-Z]/.test(pwd);
        const hasDigit = /[0-9]/.test(pwd);
        return hasLetter && hasDigit;
    }

    if (changePasswordForm) {
        changePasswordForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            hideAlert();

            const currentPassword = currentPasswordInput ? currentPasswordInput.value : '';
            const newPassword = newPasswordInput ? newPasswordInput.value : '';
            const confirmPassword = confirmPasswordInput ? confirmPasswordInput.value : '';

            if (!currentPassword || !newPassword || !confirmPassword) {
                showAlert('กรุณากรอกข้อมูลให้ครบถ้วนทุกช่อง');
                return;
            }

            if (!validatePasswordComplexity(newPassword)) {
                showAlert('รหัสผ่านใหม่ต้องมีความยาวอย่างน้อย 8 ตัวอักษร ประกอบด้วยตัวอักษรและตัวเลขอย่างน้อยอย่างละ 1 ตัว');
                return;
            }

            if (newPassword !== confirmPassword) {
                showAlert('รหัสผ่านใหม่และยืนยันรหัสผ่านใหม่ไม่ตรงกัน');
                return;
            }

            setLoading(true);

            try {
                const response = await fetch('/api/auth/change-password', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword, confirm_password: confirmPassword })
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    window.location.href = data.redirect_url || '/dashboard';
                } else {
                    setLoading(false);
                    const errorMsg = data.detail || 'เกิดข้อผิดพลาดในการเปลี่ยนรหัสผ่าน';
                    showAlert(errorMsg, 'danger');
                }
            } catch (err) {
                setLoading(false);
                showAlert('เกิดข้อผิดพลาดในการเชื่อมต่อเครือข่าย กรุณาลองใหม่อีกครั้ง', 'danger');
            }
        });
    }
});
