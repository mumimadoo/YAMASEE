document.addEventListener('DOMContentLoaded', () => {
    const pathname = window.location.pathname.replace(/\/+$/, '') || '/';
    const navItems = Array.from(document.querySelectorAll('.site-header .nav-actions a.btn[href]'));

    navItems.forEach(item => {
        item.classList.remove('active');
        item.removeAttribute('aria-current');
    });

    const routeMatchers = [
        { href: '/comparison/history', matches: path => path === '/comparison/history' },
        { href: '/comparison', matches: path => path === '/comparison' || path.startsWith('/comparison/') },
        { href: '/dashboard', matches: path => path === '/dashboard' },
        { href: '/history', matches: path => path === '/history' },
        { href: '/admin', matches: path => path === '/admin' },
        { href: '/login', matches: path => path === '/login' },
        { href: '/register', matches: path => path === '/register' },
        { href: '/landing', matches: path => path === '/' || path === '/landing' }
    ];

    const route = routeMatchers.find(candidate => candidate.matches(pathname));
    if (!route) return;

    const activeItem = navItems.find(item => item.getAttribute('href') === route.href);
    if (activeItem) {
        activeItem.classList.add('active');
        activeItem.setAttribute('aria-current', 'page');
    }
});
