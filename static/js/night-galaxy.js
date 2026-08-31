(function () {
  'use strict';

  function createOrb(className) {
    const orb = document.createElement('div');
    orb.className = `yamasee-aurora-orb ${className}`;
    const core = document.createElement('span');
    core.className = 'yamasee-orb-core';
    orb.appendChild(core);
    return orb;
  }

  function seededValue(index, salt) {
    const value = Math.sin(index * 91.731 + salt * 37.119) * 43758.5453;
    return value - Math.floor(value);
  }

  function createGalaxy() {
    if (!document.body || document.querySelector('.yamasee-night-galaxy')) return;

    const layer = document.createElement('div');
    layer.className = 'yamasee-night-galaxy';
    layer.setAttribute('aria-hidden', 'true');

    const haze = document.createElement('div');
    haze.className = 'yamasee-galaxy-haze';
    layer.appendChild(haze);

    [
      'yamasee-orb-purple',
      'yamasee-orb-pink',
      'yamasee-orb-blue',
      'yamasee-orb-orange',
      'yamasee-orb-magenta-deep',
      'yamasee-orb-warm-deep'
    ].forEach((className) => layer.appendChild(createOrb(className)));

    const stars = document.createElement('div');
    stars.className = 'yamasee-star-field';
    const initialHeight = Math.max(document.documentElement.scrollHeight, window.innerHeight);
    const starCount = Math.min(520, Math.max(140, Math.ceil(initialHeight / 900) * 120));
    for (let index = 0; index < starCount; index += 1) {
      const star = document.createElement('i');
      const bright = index % 13 === 0;
      star.className = `yamasee-star${bright ? ' is-bright' : ''}`;
      star.style.left = `${(seededValue(index, 1) * 98 + 1).toFixed(3)}%`;
      star.style.top = `${(seededValue(index, 2) * 99).toFixed(3)}%`;
      star.style.setProperty('--star-size', `${bright ? 1.7 : 0.55 + seededValue(index, 3) * 0.8}px`);
      star.style.setProperty('--star-opacity', `${bright ? 0.62 : 0.12 + seededValue(index, 4) * 0.30}`);
      star.style.setProperty('--star-delay', `${-(seededValue(index, 5) * 9).toFixed(2)}s`);
      star.style.setProperty('--star-color', index % 17 === 0 ? '#F9A8D4' : index % 23 === 0 ? '#C4B5FD' : '#FFFFFF');
      stars.appendChild(star);
    }
    layer.appendChild(stars);
    document.body.prepend(layer);

    const resize = () => {
      layer.style.height = `${Math.max(document.documentElement.scrollHeight, window.innerHeight)}px`;
    };
    resize();
    if ('ResizeObserver' in window) new ResizeObserver(resize).observe(document.body);
    window.addEventListener('resize', resize, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createGalaxy, { once: true });
  } else {
    createGalaxy();
  }
}());
