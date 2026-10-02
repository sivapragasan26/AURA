from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class AIProvider(ABC):
    """Abstract Base Class for AURA Multimodal AI Providers."""

    # Short identifier used for credentials, tracked provider state and reports
    provider_key: str = "unknown"

    @abstractmethod
    def analyze(self, prompt: str, screenshot_base64: Optional[str] = None, mime_type: str = "image/png") -> str:
        """Analyzes prompt and optional screenshot, returning raw JSON response string."""
        pass

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        """Tests provider API credentials and connection health, returning (success, message)."""
        pass

    def analyze_packet(self, packet: Any) -> str:
        """
        Provider-neutral entry point: the focused EvidencePacket is rendered once (text + screenshot);
        each provider only converts those into its own API format inside analyze().
        """
        return self.analyze(
            prompt=packet.to_prompt(),
            screenshot_base64=packet.screenshot_base64,
            mime_type=packet.screenshot_mime or "image/png",
        )

    def check_availability(self) -> Dict[str, Any]:
        """
        Non-inference availability check (auth / model metadata). Must never run a model inference.
        Returns {"status": <PreflightStatus value>, "http_status": int|None, "detail": str,
        "provider_reported": dict}. Providers without such an endpoint report UNKNOWN.
        """
        return {"status": "UNKNOWN", "http_status": None, "detail": "No non-inference availability check for this provider", "provider_reported": {}}

    def capabilities(self) -> Optional[Dict[str, Any]]:
        """Documented model capabilities (image_input, json_mode) or None when unknown."""
        return None
