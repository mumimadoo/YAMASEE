from urllib.parse import urlparse
from fastapi import Request

def verify_same_origin(request: Request) -> bool:
    """
    Validates Origin header for state-changing endpoints to prevent CSRF attacks on Cookie sessions.
    
    Policy:
    - If 'Origin' header is provided by browser: must match request target Host (scheme + host + port).
    - If 'Origin' is absent (e.g., non-browser clients, automated scripts): allowed.
    - If 'Origin' mismatch: forbidden (returns False).
    """
    origin = request.headers.get("origin")
    if not origin:
        # Fallback to Referer header if present
        referer = request.headers.get("referer")
        if not referer:
            return True  # Non-browser client or same-origin without Origin/Referer
        parsed_ref = urlparse(referer)
        origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"

    parsed_origin = urlparse(origin)
    origin_netloc = parsed_origin.netloc.lower()

    host_header = request.headers.get("host", "").lower()
    if not host_header:
        host_header = request.url.netloc.lower()

    if origin_netloc != host_header:
        return False

    return True
