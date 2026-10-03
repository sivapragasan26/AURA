import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# PERSIST=0 keeps everything in memory: no audit records, no screenshots, no token file. A hosted
# deployment runs this way, so page content from someone else's browser is never written down, and the
# process starts even where the filesystem is read-only. Local installs default to persisting, which is
# what the Test Lab, the benchmark and the per-finding screenshots rely on.
PERSIST = os.getenv("AURA_PERSIST", "1").strip().lower() not in ("0", "false", "no")

TEMP_DIR = BASE_DIR / "temp_screenshots"


def ensure_dir(path: Path) -> bool:
    """Creates a directory when persistence is on. Returns whether it is usable."""
    if not PERSIST:
        return False
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


ensure_dir(TEMP_DIR)

# AI Provider Settings
AI_PROVIDER = os.getenv("AI_PROVIDER", "mock").lower()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("AI_API_KEY", ""))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", os.getenv("AI_MODEL", "gpt-6-luna"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("AI_API_KEY", ""))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", os.getenv("AI_MODEL", "gemini-3.6-flash"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", os.getenv("AI_API_KEY", ""))
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", os.getenv("AI_MODEL", "claude-haiku-4-5"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", os.getenv("groq_api", os.getenv("GROQ_API", "")))
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

# Upper bound on AI candidates per page (the evidence packet asks for 5-8 depending on page complexity)
AI_MAX_FINDINGS = int(os.getenv("AI_MAX_FINDINGS", "8"))
AI_MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "4096"))
AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "60"))

# Provider preflight: remote checks use non-inference endpoints only (model metadata)
PREFLIGHT_REMOTE_CHECK = os.getenv("PREFLIGHT_REMOTE_CHECK", "true").lower() in ("true", "1", "yes")

# Browser Settings
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() in ("true", "1", "yes")
NAVIGATION_TIMEOUT_MS = int(os.getenv("NAVIGATION_TIMEOUT_MS", "30000"))
ACTION_TIMEOUT_MS = int(os.getenv("ACTION_TIMEOUT_MS", "10000"))

# Viewport presets
VIEWPORT_PRESETS = {
    "Desktop (1440x900)": {"width": 1440, "height": 900},
    "Laptop (1280x800)": {"width": 1280, "height": 800},
    "Tablet (768x1024)": {"width": 768, "height": 1024},
    "Mobile (375x667)": {"width": 375, "height": 667},
}

# Test Lab & Audit Storage Settings
TEST_LAB_DIR = BASE_DIR / "test_lab"
TEST_LAB_PORT = int(os.getenv("TEST_LAB_PORT", "8999"))
RUNS_DIR = BASE_DIR / "runs"
ensure_dir(RUNS_DIR)

PERMITTED_LOCAL_HOSTS = ["localhost", "127.0.0.1", f"127.0.0.1:{TEST_LAB_PORT}"]
SAFETY_INTERACTION_ENABLED = True
MAX_INTERACTIONS_PER_AUDIT = 8
# Extra targeted interactions for controls referenced by AI candidates that were not exercised yet
MAX_TARGETED_INTERACTIONS = 4

# Scoring Weights & Deductions
SCORE_BASE = 100
SEVERITY_DEDUCTIONS = {
    "critical": 20,
    "high": 12,
    "medium": 7,
    "low": 3,
    "info": 0,
}

