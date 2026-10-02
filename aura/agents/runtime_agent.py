from typing import Dict, Any, List, Optional
from aura.analyzers.runtime_analyzer import RuntimeAnalyzer
from aura.models.findings import RuntimeTelemetry, ClassifiedRuntimeEvent


class RuntimeAgent:
    """
    Runtime Agent capturing and classifying live console logs, JavaScript errors,
    unhandled exceptions, and 4xx/5xx network responses.
    """

    def __init__(self):
        self.analyzer = RuntimeAnalyzer()

    def classify(self, telemetry: RuntimeTelemetry) -> List[ClassifiedRuntimeEvent]:
        """Classifies raw runtime telemetry into structured events."""
        return self.analyzer.classify_telemetry(telemetry)

