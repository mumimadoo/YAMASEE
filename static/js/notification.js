document.addEventListener('DOMContentLoaded', () => {
    const bellBtn = document.getElementById('notificationBellBtn');
    const dropdown = document.getElementById('notificationDropdown');
    const unreadBadge = document.getElementById('unreadCountBadge');
    const notificationList = document.getElementById('notificationList');
    const markAllReadBtn = document.getElementById('markAllReadBtn');

    if (!bellBtn) return;

    // Toggle Dropdown
    bellBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
        if (dropdown.style.display === 'block') {
            fetchNotifications();
        }
    });

    // Close Dropdown on click outside
    document.addEventListener('click', () => {
        dropdown.style.display = 'none';
    });
    dropdown.addEventListener('click', (e) => e.stopPropagation());

    // Mark all read
    markAllReadBtn.addEventListener('click', async () => {
        await fetch('/api/notifications/mark-all-read', { method: 'POST' });
        fetchNotifications();
        updateUnreadCount();
    });

    async function updateUnreadCount() {
        const response = await fetch('/api/notifications/unread-count');
        const data = await response.json();
        if (data.count > 0) {
            unreadBadge.textContent = data.count > 99 ? '99+' : data.count;
            unreadBadge.style.display = 'block';
        } else {
            unreadBadge.style.display = 'none';
        }
    }

    async function fetchNotifications() {
        const response = await fetch('/api/notifications');
        const notifications = await response.json();
        
        notificationList.innerHTML = '';
        if (notifications.length === 0) {
            notificationList.innerHTML = '<div style="padding: 10px; text-align: center; color: var(--text-secondary);">No notifications yet</div>';
            return;
        }

        notifications.forEach(n => {
            const div = document.createElement('div');
            div.style.padding = '10px';
            div.style.borderBottom = '1px solid var(--border-color)';
            div.style.cursor = 'pointer';
            div.style.background = n.is_read ? 'transparent' : 'rgba(37, 99, 235, 0.05)';
            div.innerHTML = `
                <div style="font-weight: 600; font-size: 13px; color: var(--text-main);">${n.title}</div>
                <div style="font-size: 12px; color: var(--text-secondary); margin: 4px 0;">${n.message}</div>
                <div style="font-size: 10px; color: var(--text-hint);">${new Date(n.created_at).toLocaleString()}</div>
            `;
            
            div.addEventListener('click', async () => {
                await fetch(`/api/notifications/${n.id}/read`, { method: 'POST' });
                if (n.target_url) window.location.href = n.target_url;
                fetchNotifications();
                updateUnreadCount();
            });
            notificationList.appendChild(div);
        });
    }

    // Polling
    updateUnreadCount();
    setInterval(updateUnreadCount, 30000); // 30 seconds
});
