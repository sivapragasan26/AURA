from typing import List, Dict, Any
from aura.models.findings import ConsoleError, NetworkFailure, RuntimeTelemetry


class RuntimeCollector:
    """Collects runtime telemetry (console errors, network failures, timing) from Playwright page events."""

    def __init__(self):
        self.console_errors: List[ConsoleError] = []
        self.network_failures: List[NetworkFailure] = []
        self.page_load_time_ms: float = 0.0

    def attach_listeners(self, page):
        """Attaches Playwright event listeners for console logging and network monitoring."""

        def handle_console(msg):
            if msg.type in ("error", "warning"):
                location = f"{msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}" if msg.location else None
                self.console_errors.append(
                    ConsoleError(
                        type=msg.type,
                        text=msg.text,
                        location=location
                    )
                )

        def handle_page_error(exc):
            self.console_errors.append(
                ConsoleError(
                    type="exception",
                    text=str(exc),
                    location=None
                )
            )

        def handle_response(response):
            if response.status >= 400:
                self.network_failures.append(
                    NetworkFailure(
                        url=response.url,
                        status=response.status,
                        status_text=response.status_text,
                        method=response.request.method
                    )
                )

        page.on("console", handle_console)
        page.on("pageerror", handle_page_error)
        page.on("response", handle_response)

    def set_load_time(self, load_time_ms: float):
        self.page_load_time_ms = load_time_ms

    def get_telemetry(self, url: str, title: str, viewport: Dict[str, int], screenshot_path: str = None) -> RuntimeTelemetry:
        return RuntimeTelemetry(
            url=url,
            title=title,
            viewport=viewport,
            page_load_time_ms=self.page_load_time_ms,
            console_errors=self.console_errors,
            network_failures=self.network_failures,
            screenshot_path=screenshot_path
        )

