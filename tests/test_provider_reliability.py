"""
Unit tests for AURA AI Provider Reliability.
Verifies:
- Proper provider instantiation and factory isolation (no silent mock fallback)
- Strict missing-key enforcement (ValueError on analyze, NOT_CONFIGURED on preflight)
- Groq model discovery and availability check (avoiding 404 on slashed model IDs)
- Structured connection test details (latency, status, model metadata) across all providers
- Execution metadata tracking for ProviderStateStore integration
"""

import unittest
from unittest.mock import MagicMock, patch
import requests

from aura.agent.providers import get_ai_provider
from aura.agent.provider import AIProvider
from aura.agent.mock_provider import MockAIProvider
from aura.agent.gemini_provider import GeminiProvider
from aura.agent.groq_provider import GroqProvider
from aura.agent.openai_provider import OpenAIProvider
from aura.agent.anthropic_provider import AnthropicProvider


class TestAIProviderReliability(unittest.TestCase):

    def test_factory_returns_expected_classes(self):
        """Factory must return exact provider requested, never silently substituting."""
        self.assertIsInstance(get_ai_provider("mock"), MockAIProvider)
        self.assertIsInstance(get_ai_provider("gemini"), GeminiProvider)
        self.assertIsInstance(get_ai_provider("groq"), GroqProvider)
        self.assertIsInstance(get_ai_provider("openai"), OpenAIProvider)
        self.assertIsInstance(get_ai_provider("anthropic"), AnthropicProvider)

    def test_factory_defaults_to_mock_only_for_unknown(self):
        """Only unknown or explicitly mock providers should yield MockAIProvider."""
        self.assertIsInstance(get_ai_provider("unknown_provider_xyz"), MockAIProvider)
        self.assertIsInstance(get_ai_provider(None), MockAIProvider)

    def test_missing_key_analyze_raises_value_error(self):
        """All real providers must raise ValueError if API key is missing on analyze()."""
        providers = [
            GeminiProvider(api_key=""),
            GroqProvider(api_key=""),
            OpenAIProvider(api_key=""),
            AnthropicProvider(api_key=""),
        ]
        for p in providers:
            with self.subTest(provider=p.provider_key):
                with self.assertRaises(ValueError):
                    p.analyze("Test prompt")
                # Metadata should reflect CONFIGURATION_ERROR
                meta = getattr(p, "last_execution_metadata", {})
                self.assertEqual(meta.get("failure_category"), "CONFIGURATION_ERROR")

    def test_missing_key_check_availability(self):
        """All real providers must return NOT_CONFIGURED if API key is missing."""
        providers = [
            GeminiProvider(api_key=""),
            GroqProvider(api_key=""),
            OpenAIProvider(api_key=""),
            AnthropicProvider(api_key=""),
        ]
        for p in providers:
            with self.subTest(provider=p.provider_key):
                avail = p.check_availability()
                self.assertEqual(avail.get("status"), "NOT_CONFIGURED")

    def test_missing_key_test_connection(self):
        """All real providers must return success=False and CONFIGURATION_ERROR if API key is missing."""
        providers = [
            GeminiProvider(api_key=""),
            GroqProvider(api_key=""),
            OpenAIProvider(api_key=""),
            AnthropicProvider(api_key=""),
        ]
        for p in providers:
            with self.subTest(provider=p.provider_key):
                success, msg = p.test_connection()
                self.assertFalse(success)
                if hasattr(p, "test_connection_details"):
                    details = p.test_connection_details()
                    self.assertFalse(details["success"])
                    self.assertEqual(details["status"], "CONFIGURATION_ERROR")
                    self.assertIn("latency_ms", details)

    @patch("requests.get")
    def test_groq_check_availability_success(self, mock_get):
        """Groq check_availability queries /models and succeeds when model is present and active."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"x-ratelimit-remaining-requests": "14000"}
        mock_resp.json.return_value = {
            "object": "list",
            "data": [
                {"id": "qwen/qwen3.6-27b", "active": True},
                {"id": "llama-3.3-70b-versatile", "active": True}
            ]
        }
        mock_get.return_value = mock_resp

        provider = GroqProvider(api_key="gsk_test1234567890", model="qwen/qwen3.6-27b")
        avail = provider.check_availability()

        # Endpoint called should be /models (NOT /models/qwen/qwen3.6-27b)
        called_url = mock_get.call_args[0][0]
        self.assertTrue(called_url.endswith("/models"))
        self.assertEqual(avail["status"], "READY")
        self.assertEqual(avail["http_status"], 200)

    @patch("requests.get")
    def test_groq_check_availability_model_missing(self, mock_get):
        """Groq check_availability returns MODEL_UNAVAILABLE if model not in list."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = {
            "object": "list",
            "data": [{"id": "other-model", "active": True}]
        }
        mock_get.return_value = mock_resp

        provider = GroqProvider(api_key="gsk_test1234567890", model="qwen/qwen3.6-27b")
        avail = provider.check_availability()
        self.assertEqual(avail["status"], "MODEL_UNAVAILABLE")

    @patch("requests.get")
    def test_groq_check_availability_model_inactive(self, mock_get):
        """Groq check_availability returns MODEL_UNAVAILABLE if model active=False."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = {
            "object": "list",
            "data": [{"id": "qwen/qwen3.6-27b", "active": False}]
        }
        mock_get.return_value = mock_resp

        provider = GroqProvider(api_key="gsk_test1234567890", model="qwen/qwen3.6-27b")
        avail = provider.check_availability()
        self.assertEqual(avail["status"], "MODEL_UNAVAILABLE")

    @patch("requests.get")
    def test_groq_check_availability_auth_error(self, mock_get):
        """Groq check_availability returns AUTH_INVALID on 401."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        provider = GroqProvider(api_key="gsk_invalid", model="qwen/qwen3.6-27b")
        avail = provider.check_availability()
        self.assertEqual(avail["status"], "AUTH_INVALID")

    @patch("requests.get")
    def test_groq_check_availability_network_error(self, mock_get):
        """Groq check_availability returns NETWORK_UNAVAILABLE on connection error."""
        mock_get.side_effect = requests.RequestException("Connection refused")

        provider = GroqProvider(api_key="gsk_test123", model="qwen/qwen3.6-27b")
        avail = provider.check_availability()
        self.assertEqual(avail["status"], "NETWORK_UNAVAILABLE")

    def test_openai_test_connection_details_structure(self):
        """OpenAI test_connection_details returns expected structure."""
        provider = OpenAIProvider(api_key="", model="gpt-4o")
        details = provider.test_connection_details()
        self.assertIn("success", details)
        self.assertIn("status", details)
        self.assertIn("latency_ms", details)
        self.assertIn("requested_model", details)
        self.assertIn("message", details)

    def test_anthropic_test_connection_details_structure(self):
        """Anthropic test_connection_details returns expected structure."""
        provider = AnthropicProvider(api_key="", model="claude-3-5-sonnet-20241022")
        details = provider.test_connection_details()
        self.assertIn("success", details)
        self.assertIn("status", details)
        self.assertIn("latency_ms", details)
        self.assertIn("requested_model", details)
        self.assertIn("message", details)

    def test_model_cross_validation_warning(self):
        """Factory logs warning when model is not recognized for given provider."""
        with self.assertLogs("AURA", level="WARNING") as cm:
            get_ai_provider("openai", model_name="unknown-model-xyz")
        self.assertTrue(any("not in known models" in output for output in cm.output))


if __name__ == "__main__":
    unittest.main()
