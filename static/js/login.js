document.addEventListener('DOMContentLoaded', () => {
  const loginForm = document.getElementById('loginForm');
  const emailInput = document.getElementById('email');
  const passwordInput = document.getElementById('password');
  const togglePasswordBtn = document.getElementById('togglePassword');
  const alertBanner = document.getElementById('alertBanner');
  const submitBtn = document.getElementById('submitBtn');
  const submitBtnText = document.getElementById('submitBtnText');
  const submitSpinner = document.getElementById('submitSpinner');

  if (emailInput) {
    emailInput.focus();
  }

  // Toggle Password Visibility
  if (togglePasswordBtn && passwordInput) {
    togglePasswordBtn.addEventListener('click', () => {
      const isPassword = passwordInput.type === 'password';
      passwordInput.type = isPassword ? 'text' : 'password';
      togglePasswordBtn.textContent = isPassword ? 'Hide' : 'Show';
    });
  }

  function showAlert(message, type = 'danger') {
    if (alertBanner) {
      alertBanner.textContent = message; // Safe textContent to prevent XSS
      alertBanner.className = `alert-banner alert-${type}`;
    }
  }

  function hideAlert() {
    if (alertBanner) {
      alertBanner.className = 'alert-banner';
      alertBanner.textContent = '';
    }
  }

  function setLoading(isLoading) {
    if (submitBtn) {
      submitBtn.disabled = isLoading;
    }
    if (submitSpinner) {
      submitSpinner.style.display = isLoading ? 'inline-block' : 'none';
    }
    if (submitBtnText) {
      submitBtnText.textContent = isLoading ? 'กำลังเข้าสู่ระบบ...' : 'เข้าสู่ระบบ';
    }
  }

  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideAlert();

      const email = emailInput ? emailInput.value.trim() : '';
      const password = passwordInput ? passwordInput.value : '';

      if (!email || !password) {
        showAlert('กรุณากรอกชื่อผู้ใช้หรืออีเมล และรหัสผ่านให้ครบถ้วน');
        return;
      }

      setLoading(true);

      try {
        const response = await fetch('/api/auth/login', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (response.ok && data.success) {
          window.location.href = data.redirect_url || '/dashboard';
        } else {
          setLoading(false);
          const errorMsg = data.detail || 'ชื่อผู้ใช้ อีเมล หรือรหัสผ่านไม่ถูกต้อง';
          showAlert(errorMsg, 'danger');
        }
      } catch (err) {
        setLoading(false);
        showAlert('เกิดข้อผิดพลาดในการเชื่อมต่อเครือข่าย กรุณาลองใหม่อีกครั้ง', 'danger');
      }
    });
  }

  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
      } catch (e) {}
      window.location.href = '/login';
    });
  }
});
