import logging
import sys
from typing import List, Dict, Any, Callable, Optional

# Configure standard logger
logger = logging.getLogger("AURA")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s", datefmt="%H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class ExecutionStepTracker:
    """Tracks analysis progress steps for the Streamlit UI."""

    def __init__(self, callback: Optional[Callable[[str, str], None]] = None):
        self.steps: List[Dict[str, Any]] = []
        self.callback = callback

    def add_step(self, title: str, status: str = "running", detail: str = ""):
        step = {"title": title, "status": status, "detail": detail}
        self.steps.append(step)
        logger.info(f"Step: {title} [{status}] {detail}")
        if self.callback:
            self.callback(title, status)

    def update_last_step(self, status: str, detail: str = ""):
        if self.steps:
            self.steps[-1]["status"] = status
            if detail:
                self.steps[-1]["detail"] = detail
            title = self.steps[-1]["title"]
            logger.info(f"Updated Step: {title} -> [{status}] {detail}")
            if self.callback:
                self.callback(title, status)

    def get_steps(self) -> List[Dict[str, Any]]:
        return self.steps

