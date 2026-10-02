import os
import time
import threading
import http.server
import socketserver
from pathlib import Path
from typing import List, Dict, Any
from aura.config import settings

TEST_LAB_DIR = settings.TEST_LAB_DIR
PORT = settings.TEST_LAB_PORT


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom HTTP Handler suppressing standard server logs during testing."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(TEST_LAB_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # Quiet logging

    def send_head(self):
        # Ground truth is read from disk by the evaluator only. It is never served to a browser, so no page
        # scan (Playwright or the Chrome extension) can ever collect it as evidence.
        if "ground_truth" in self.path.lower():
            self.send_error(404, "Not Found")
            return None
        return super().send_head()


class TestLabLauncher:
    """Manages local HTTP server for AURA Test Lab sites."""

    _server: socketserver.TCPServer = None
    _thread: threading.Thread = None

    @classmethod
    def start_server(cls):
        """Starts local Test Lab HTTP server in background daemon thread if not already active."""
        if cls._server is not None:
            return

        def serve():
            try:
                with socketserver.TCPServer(("127.0.0.1", PORT), QuietHTTPRequestHandler) as httpd:
                    cls._server = httpd
                    httpd.serve_forever()
            except Exception:
                pass

        cls._thread = threading.Thread(target=serve, daemon=True)
        cls._thread.start()
        time.sleep(0.5)

    @classmethod
    def stop_server(cls):
        """Stops Test Lab HTTP server."""
        if cls._server:
            try:
                cls._server.shutdown()
                cls._server.server_close()
            except Exception:
                pass
            finally:
                cls._server = None

    @classmethod
    def list_sites(cls) -> List[Dict[str, Any]]:
        """Lists available test lab site directories with title, description, and ground truth."""
        if not TEST_LAB_DIR.exists():
            return []

        CONSOLIDATED_SUITES = [
            "01_accessibility_suite",
            "02_ui_ux_suite",
            "03_navigation_interaction_suite",
            "04_responsive_runtime_suite",
            "05_mixed_realistic_suite"
        ]

        sites = []
        for item_name in CONSOLIDATED_SUITES:
            item = TEST_LAB_DIR / item_name
            if item.exists() and item.is_dir():
                desc = "Consolidated benchmark suite containing multiple intentional UI/UX defects"
                expected_cnt = 0
                from aura.evaluation.registry import GroundTruthRegistry
                gt_data = GroundTruthRegistry.load_suite_ground_truth(item)
                if gt_data:
                    desc = gt_data.get("description", desc)
                    expected_cnt = len(gt_data.get("expected_findings", []))

                sites.append({
                    "id": item.name,
                    "name": item.name.replace("_", " ").title(),
                    "dir": item,
                    "description": desc,
                    "expected_count": expected_cnt,
                    "url": f"http://127.0.0.1:{PORT}/{item.name}/"
                })
        return sites

