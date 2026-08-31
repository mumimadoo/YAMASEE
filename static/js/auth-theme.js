// --- YAMASEE SHARED THEME CONTROLLER ---

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme') || 'day';
  const newTheme = currentTheme === 'night' ? 'day' : 'night';
  
  document.documentElement.setAttribute('data-theme', newTheme);
  try {
    localStorage.setItem('theme', newTheme);
  } catch(e) {}
  
  updateThemeToggleButtons(newTheme);

  // Redraw dashboard keywords chart if available
  if (typeof drawKeywordBarChart === 'function' && typeof globalKeywordsChartData !== 'undefined' && globalKeywordsChartData.length > 0) {
    drawKeywordBarChart(globalKeywordsChartData);
  }
}

window.toggleTheme = toggleTheme;

function updateThemeToggleButtons(theme) {
  const toggleBtns = document.querySelectorAll('.theme-toggle-btn');
  toggleBtns.forEach(btn => {
    btn.textContent = theme === 'night' ? '☀️ Day' : '🌙 Night';
    btn.setAttribute('aria-label', `Switch to ${theme === 'night' ? 'Day' : 'Night'} theme`);
  });

  const isNight = theme === 'night';
  document.querySelectorAll('.yamasee-theme-switch-input, .theme-switch__checkbox').forEach(input => {
    input.checked = isNight;
    input.setAttribute('aria-checked', String(isNight));
    input.setAttribute('aria-label', `Switch to ${isNight ? 'day' : 'night'} theme`);
    const wrapper = input.closest('.yamasee-theme-switch, .theme-switch');
    if (wrapper) wrapper.setAttribute('aria-label', `Switch to ${isNight ? 'day' : 'night'} theme`);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const currentTheme = document.documentElement.getAttribute('data-theme') || 'day';
  updateThemeToggleButtons(currentTheme);

  const toggleBtns = document.querySelectorAll('.theme-toggle-btn');
  toggleBtns.forEach(btn => {
    if (!btn.dataset.themeBound) {
      btn.dataset.themeBound = 'true';
      btn.addEventListener('click', toggleTheme);
    }
  });

  document.querySelectorAll('.yamasee-theme-switch-input, .theme-switch__checkbox').forEach(input => {
    if (input.dataset.themeBound) return;
    input.dataset.themeBound = 'true';
    input.addEventListener('change', () => {
      const currentIsNight = document.documentElement.getAttribute('data-theme') === 'night';
      if (input.checked !== currentIsNight) toggleTheme();
    });
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleTheme();
      }
    });
  });

  initUserPopover();
});

if (document.readyState === 'interactive' || document.readyState === 'complete') {
  initUserPopover();
}

function initUserPopover() {
  const userChipBtn = document.getElementById('userChipBtn');
  const userPopoverCard = document.getElementById('userPopoverCard');

  if (userChipBtn && userPopoverCard && !userChipBtn.dataset.popoverBound) {
    userChipBtn.dataset.popoverBound = 'true';
    userChipBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isVisible = userPopoverCard.style.display !== 'none';
      userPopoverCard.style.display = isVisible ? 'none' : 'block';
      userChipBtn.setAttribute('aria-expanded', String(!isVisible));
    });

    userPopoverCard.addEventListener('click', (e) => {
      e.stopPropagation();
    });

    document.addEventListener('click', () => {
      if (userPopoverCard.style.display !== 'none') {
        userPopoverCard.style.display = 'none';
        userChipBtn.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' || e.key === 'Esc') {
        if (userPopoverCard.style.display !== 'none') {
          userPopoverCard.style.display = 'none';
          userChipBtn.setAttribute('aria-expanded', 'false');
        }
      }
    });
  }
}

new MutationObserver(() => {
  updateThemeToggleButtons(document.documentElement.getAttribute('data-theme') || 'day');
}).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
