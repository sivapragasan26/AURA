from pathlib import Path
from typing import Dict, Any, Optional
from aura.utils.helpers import encode_image_to_base64
from aura.utils.logger import logger


class ScreenshotAnalyzer:
    """Prepares and validates screenshot payloads for AI vision multimodal analysis."""

    def prepare_screenshot_payload(self, screenshot_path: str) -> Dict[str, Any]:
        """Encodes screenshot image file into base64 payload."""
        path = Path(screenshot_path)
        if not path.exists():
            logger.warning(f"Screenshot file does not exist: {screenshot_path}")
            return {"available": False, "base64_data": None, "mime_type": None}

        base64_data = encode_image_to_base64(screenshot_path)
        mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"

        return {
            "available": base64_data is not None,
            "base64_data": base64_data,
            "mime_type": mime_type,
            "file_path": str(path)
        }

