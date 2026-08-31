document.addEventListener('DOMContentLoaded', () => {
  const registerForm = document.getElementById('registerForm');
  const usernameInput = document.getElementById('username');
  const emailInput = document.getElementById('email');
  const passwordInput = document.getElementById('password');
  const confirmPasswordInput = document.getElementById('confirmPassword');
  const togglePasswordBtn = document.getElementById('togglePassword');
  const toggleConfirmPasswordBtn = document.getElementById('toggleConfirmPassword');
  const alertBanner = document.getElementById('alertBanner');
  const submitBtn = document.getElementById('submitBtn');
  const submitBtnText = document.getElementById('submitBtnText');
  const submitSpinner = document.getElementById('submitSpinner');

  if (usernameInput) {
    usernameInput.focus();
  }

  // Toggle Password Visibilities
  if (togglePasswordBtn && passwordInput) {
    togglePasswordBtn.addEventListener('click', () => {
      const isPassword = passwordInput.type === 'password';
      passwordInput.type = isPassword ? 'text' : 'password';
      togglePasswordBtn.textContent = isPassword ? 'Hide' : 'Show';
    });
  }

  if (toggleConfirmPasswordBtn && confirmPasswordInput) {
    toggleConfirmPasswordBtn.addEventListener('click', () => {
      const isPassword = confirmPasswordInput.type === 'password';
      confirmPasswordInput.type = isPassword ? 'text' : 'password';
      toggleConfirmPasswordBtn.textContent = isPassword ? 'Hide' : 'Show';
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
      submitBtnText.textContent = isLoading ? 'กำลังสร้างบัญชี...' : 'สร้างบัญชีผู้ใช้';
    }
  }

  if (registerForm) {
    registerForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideAlert();

      const username = usernameInput ? usernameInput.value.trim() : '';
      const email = emailInput ? emailInput.value.trim() : '';
      const password = passwordInput ? passwordInput.value : '';
      const confirm_password = confirmPasswordInput ? confirmPasswordInput.value : '';

      // Client-side validations
      if (username.length < 2 || username.length > 80) {
        showAlert('ชื่อผู้ใช้ต้องมีความยาวระหว่าง 2 ถึง 80 ตัวอักษร');
        return;
      }

      if (!email.includes('@') || !email.includes('.')) {
        showAlert('กรุณาระบุรูปแบบอีเมลให้ถูกต้อง');
        return;
      }

      if (password.length < 8 || password.length > 128) {
        showAlert('รหัสผ่านต้องมีความยาวระหว่าง 8 ถึง 128 ตัวอักษร');
        return;
      }

      const hasLetter = /[a-zA-Z]/.test(password);
      const hasDigit = /[0-9]/.test(password);
      if (!hasLetter || !hasDigit) {
        showAlert('รหัสผ่านต้องประกอบด้วยตัวอักษรและตัวเลข');
        return;
      }

      if (password !== confirm_password) {
        showAlert('รหัสผ่านและการยืนยันรหัสผ่านไม่ตรงกัน');
        return;
      }

      setLoading(true);

      try {
        const response = await fetch('/api/auth/register', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            username,
            email,
            password,
            confirm_password
          })
        });

        const data = await response.json();

        if (response.ok && data.success) {
          showAlert('สมัครสมาชิกสำเร็จ! กำลังนำท่านไปยังหน้าเข้าสู่ระบบ...', 'success');
          setTimeout(() => {
            window.location.href = data.redirect_url || '/login';
          }, 1200);
        } else {
          setLoading(false);
          let errorMsg = 'การสมัครสมาชิกล้มเหลว';
          if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map(d => d.msg).join(', ');
          } else if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          }
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
