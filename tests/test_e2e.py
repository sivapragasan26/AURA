import time
import threading
import http.server
import socketserver
from pathlib import Path
from aura.engine import AURAEngine
from aura.config import settings

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo-site"
PORT = 8998


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress HTTP server output in test logs


def run_server():
    import os
    os.chdir(DEMO_DIR)
    with socketserver.TCPServer(("127.0.0.1", PORT), QuietHTTPRequestHandler) as httpd:
        httpd.serve_forever()


def test_e2e_v02_aura_audit():
    # 1. Start demo HTTP server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(1)  # Allow server to initialize

    target_url = f"http://127.0.0.1:{PORT}"

    # 2. Run AURA Engine analysis
    engine = AURAEngine()
    report_data = engine.run_analysis(
        url=target_url,
        viewport_preset="Desktop (1440x900)",
        headless=True
    )

    report = report_data["report_model"]
    aggregation = report_data["aggregation"]

    # 3. Assert report output
    assert report.url == target_url
    assert report.scores.overall >= 0 and report.scores.overall <= 100
    assert len(report.findings) > 0
    assert len(report.rejected_findings) > 0  # Rejection verification confirmed!
    assert report.runtime_telemetry.screenshot_path is not None
    assert Path(report.runtime_telemetry.screenshot_path).exists()
    assert report.is_mock_mode is True

    # 4. Assert aggregation output
    assert len(aggregation.findings) > 0
    assert "defect(s)" in aggregation.summary_text or "defect" in aggregation.summary_text


