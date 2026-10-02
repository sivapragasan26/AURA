import base64
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional


def validate_url(url: str) -> bool:
    """Validate that input URL is valid http/https and safe to open."""
    if not url:
        return False
    url = url.strip()
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.netloc:
            return False
        return True
    except Exception:
        return False


def encode_image_to_base64(image_path: str) -> Optional[str]:
    """Reads image file and encodes to base64 string."""
    try:
        path = Path(image_path)
        if not path.exists():
            return None
        with open(path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
    except Exception:
        return None


def truncate_string(text: str, max_len: int = 150) -> str:
    """Truncate string to max length with ellipsis."""
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= max_len else text[: max_len - 3] + "..."

