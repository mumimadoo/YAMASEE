import ipaddress
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
DISALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "169.254.169.254"}

def is_safe_url(url: str) -> bool:
    """
    Validates URL scheme, credentials, and host destination to prevent SSRF attacks.
    Returns True if valid and safe, False otherwise.
    """
    if not url or not isinstance(url, str):
        return False
    
    url_stripped = url.strip()
    try:
        parsed = urlparse(url_stripped)
    except Exception:
        return False

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False

    if parsed.username or parsed.password:
        return False  # Block userinfo spoofing (e.g. http://user:pass@host)

    hostname = parsed.hostname
    if not hostname:
        return False

    hostname_lower = hostname.lower()
    if hostname_lower in DISALLOWED_HOSTS or hostname_lower.endswith(".localdomain"):
        return False

    # Prevent IP literal loopback, private, link-local, or reserved address access
    try:
        ip = ipaddress.ip_address(hostname_lower)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_unspecified or ip.is_multicast:
            return False
    except ValueError:
        # Not a raw IP string, normal domain hostname
        pass

    return True
