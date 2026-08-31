(function () {
  'use strict';

  const svgNamespace = 'http://www.w3.org/2000/svg';

  function surfaceMarkup(id, colors, path) {
    return `
      <defs>
        <linearGradient id="${id}-color" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="${colors[0]}" stop-opacity=".18"/>
          <stop offset=".34" stop-color="${colors[1]}" stop-opacity=".44"/>
          <stop offset=".66" stop-color="${colors[2]}" stop-opacity=".38"/>
          <stop offset="1" stop-color="#FFFFFF" stop-opacity=".72"/>
        </linearGradient>
        <linearGradient id="${id}-shine" x1="0" y1="1" x2="1" y2="0">
          <stop stop-color="#FFFFFF" stop-opacity="0"/>
          <stop offset=".48" stop-color="#FFFFFF" stop-opacity=".58"/>
          <stop offset=".72" stop-color="#FFFDF8" stop-opacity=".22"/>
          <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
        </linearGradient>
        <filter id="${id}-deform" x="-12%" y="-35%" width="124%" height="170%">
          <feTurbulence type="fractalNoise" baseFrequency=".006 .018" numOctaves="2" seed="${id.charCodeAt(id.length - 1)}" result="noise"/>
          <feDisplacementMap in="SourceGraphic" in2="noise" scale="24" xChannelSelector="R" yChannelSelector="B"/>
        </filter>
      </defs>
      <path d="${path}" fill="url(#${id}-color)" filter="url(#${id}-deform)"/>
      <path d="${path}" fill="url(#${id}-shine)" opacity=".72" transform="translate(0 -10) scale(1 .82)"/>`;
  }

  function makeSurface(className, id, colors, path) {
    const svg = document.createElementNS(svgNamespace, 'svg');
    svg.setAttribute('class', `yamasee-organic-surface ${className}`);
    svg.setAttribute('viewBox', '0 0 1440 420');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.innerHTML = surfaceMarkup(id, colors, path);
    return svg;
  }

  function createSunlight() {
    if (!document.body || document.querySelector('.yamasee-day-sunlight')) return;

    const layer = document.createElement('div');
    layer.className = 'yamasee-day-sunlight';
    layer.setAttribute('aria-hidden', 'true');

    const source = document.createElement('div');
    source.className = 'yamasee-sunlight-source';
    layer.appendChild(source);

    layer.appendChild(makeSurface('yamasee-organic-a', 'day-a', ['#FEF08A', '#FACC15', '#FB923C'], 'M-100 230 C160 40 390 44 610 166 C840 292 1000 350 1540 112 L1540 390 C1090 478 780 344 530 300 C280 256 100 406 -100 340 Z'));
    layer.appendChild(makeSurface('yamasee-organic-b', 'day-b', ['#FFFFFF', '#FB923C', '#FB7185'], 'M-120 122 C210 320 430 350 690 198 C900 74 1130 34 1560 260 L1560 410 C1240 342 1000 286 740 364 C430 456 170 356 -120 282 Z'));
    layer.appendChild(makeSurface('yamasee-organic-c', 'day-c', ['#FFFFFF', '#FDE047', '#FDBA74'], 'M-100 272 C190 92 470 72 710 224 C930 364 1180 342 1540 128 L1540 356 C1260 454 1010 422 760 342 C470 248 190 430 -100 366 Z'));
    layer.appendChild(makeSurface('yamasee-organic-d', 'day-d', ['#FFFDF8', '#FDA4AF', '#FB923C'], 'M-100 154 C240 344 520 318 760 160 C1010 -6 1210 116 1540 300 L1540 420 L-100 420 Z'));

    ['a', 'b', 'c'].forEach((name) => {
      const bloom = document.createElement('div');
      bloom.className = `yamasee-day-bloom yamasee-day-bloom-${name}`;
      layer.appendChild(bloom);
    });

    const texture = document.createElement('div');
    texture.className = 'yamasee-day-texture';
    layer.appendChild(texture);
    document.body.prepend(layer);

    const resize = () => {
      layer.style.height = `${Math.max(document.documentElement.scrollHeight, window.innerHeight)}px`;
    };
    resize();
    if ('ResizeObserver' in window) new ResizeObserver(resize).observe(document.body);
    window.addEventListener('resize', resize, { passive: true });

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const finePointer = window.matchMedia('(pointer: fine)');
    window.addEventListener('pointermove', (event) => {
      if (reducedMotion.matches || !finePointer.matches || document.documentElement.dataset.theme === 'night') return;
      const x = ((event.clientX / window.innerWidth) - 0.5) * 14;
      const y = ((event.clientY / window.innerHeight) - 0.5) * 10;
      layer.style.setProperty('--day-pointer-a-x', `${(x * 0.35).toFixed(2)}px`);
      layer.style.setProperty('--day-pointer-a-y', `${(y * 0.25).toFixed(2)}px`);
      layer.style.setProperty('--day-pointer-b-x', `${(x * -0.2).toFixed(2)}px`);
      layer.style.setProperty('--day-pointer-b-y', `${(y * 0.18).toFixed(2)}px`);
    }, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createSunlight, { once: true });
  } else {
    createSunlight();
  }
}());
