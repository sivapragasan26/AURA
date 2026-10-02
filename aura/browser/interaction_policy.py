import re
from urllib.parse import urlparse
from typing import Tuple, Dict, Any, List


class InteractionPolicy:
    """
    Level-B Safety Policy enforcing non-destructive controlled interactions.
    Classifies browser actions as SAFE or BLOCKED based on semantic text, selectors, and roles.
    Enforces same-origin restrictions for navigation.
    """

    SAFE_ACTIONS = {"click", "hover", "scroll", "expand", "navigation", "input"}
    
    BLOCKED_KEYWORDS = [
        "buy", "pay", "checkout", "purchase", "order", "subscribe", "billing",
        "delete", "remove", "destroy", "erase", "purge",
        "password", "credit", "card", "cvv", "bank", "account",
        "send message", "submit order", "post comment", "publish",
        "transfer", "withdraw", "deposit",
        # session-ending actions: they end the audited session and can change account state
        "logout", "log out", "sign out", "signout"
    ]

    BLOCKED_PATTERNS = [
        r"\b(buy|pay|checkout|purchase|order)\b",
        r"\b(delete|remove|destroy|cancel account)\b",
        r"\b(credit|card|cvv|bank|ssn)\b",
        r"\b(password|reset password)\b"
    ]

    @classmethod
    def is_same_origin(cls, current_url: str, target_url: str) -> bool:
        """Verifies if target URL belongs to the same origin (protocol + host + port)."""
        if not target_url or target_url.startswith("#") or target_url.startswith("javascript:"):
            return True
        try:
            curr_p = urlparse(current_url)
            targ_p = urlparse(target_url)
            if not targ_p.netloc:
                return True
            return curr_p.netloc.lower() == targ_p.netloc.lower()
        except Exception:
            return False

    @classmethod
    def is_action_safe(cls, action_type: str, element_info: Dict[str, Any], current_url: str = "") -> Tuple[bool, str]:
        """
        Evaluates whether an interaction is safe to execute.
        Returns (is_safe: bool, reason: str).
        """
        action = (action_type or "").lower().strip()
        if action not in cls.SAFE_ACTIONS:
            return False, f"Action '{action}' is not in allowed SAFE_ACTIONS set."

        # Extract semantic text fields
        text = str(element_info.get("text") or "").lower()
        aria = str(element_info.get("aria_label") or "").lower()
        role = str(element_info.get("role") or "").lower()
        selector = str(element_info.get("selector") or "").lower()
        tag = str(element_info.get("tag") or "").lower()
        input_type = str(element_info.get("type") or "").lower()
        href = str(element_info.get("href") or "").strip()

        combined_target_str = f"{text} {aria} {selector} {input_type}"

        # 1. Same origin check for external navigation links
        if href and current_url and not cls.is_same_origin(current_url, href):
            return False, f"Blocked: Target navigation '{href}' leaves same-origin domain '{current_url}'"

        # 2. Check for blocked keywords / regex patterns
        for pattern in cls.BLOCKED_PATTERNS:
            if re.search(pattern, combined_target_str):
                return False, f"Blocked: Target matches dangerous operation pattern '{pattern}'"

        for kw in cls.BLOCKED_KEYWORDS:
            if kw in combined_target_str:
                return False, f"Blocked: Target contains dangerous keyword '{kw}'"

        # 3. Check input types
        if tag == "input" or role == "textbox":
            if input_type in ("password", "credit-card", "hidden", "file"):
                return False, f"Blocked: Sensitive input type '{input_type}'"

        # 4. Default SAFE
        return True, "Safe interaction permitted under AURA Level-B Safety Policy."

    # ------------------------------------------------------------------
    # Live-session policy (Chrome extension): AURA acts inside the user's REAL, possibly authenticated session,
    # so it is stricter than the Level-B policy used on the engine's own throwaway Playwright browser.
    # ------------------------------------------------------------------
    LIVE_SESSION_ACTIONS = {"click", "hover"}
    LIVE_SESSION_BLOCKED_KEYWORDS = [
        "send", "submit", "confirm", "save", "post", "approve", "reject", "archive", "unsubscribe", "cancel",
        "sign in", "signin", "log in", "login", "register", "sign up", "signup", "invite", "share", "upload",
        "install", "update", "apply", "accept", "decline", "reset", "clear", "empty", "import", "export", "sync",
        "refund", "book", "reserve", "donate", "vote", "follow", "like", "comment", "reply", "rate", "revoke",
        "disable", "deactivate", "enable", "grant", "move", "merge", "deploy", "release", "run", "execute",
        "start", "stop", "restart", "terminate", "kill", "wipe", "drop", "request", "claim", "redeem",
    ]
    LIVE_SESSION_BUDGET = 5

    @classmethod
    def is_action_safe_live_session(cls, action_type: str, element_info: Dict[str, Any], current_url: str = "") -> Tuple[bool, str]:
        """
        Policy for interactions in the user's own browser session. Allowed: clicking or hovering controls that
        cannot submit data or leave the page. Never: typing, form submission, link navigation, or any control
        whose label suggests a state-changing or irreversible operation.
        element_info may carry `in_form` and `effective_type` (the button's real type, 'submit' when unset).
        """
        action = (action_type or "").lower().strip()
        if action not in cls.LIVE_SESSION_ACTIONS:
            return False, f"Blocked (live session): action '{action}' is not allowed on the user's real session."
        ok, reason = cls.is_action_safe(action, element_info, current_url=current_url)
        if not ok:
            return ok, reason

        tag = str(element_info.get("tag") or "").lower()
        role = str(element_info.get("role") or "").lower()
        input_type = str(element_info.get("type") or "").lower()
        effective_type = str(element_info.get("effective_type") or input_type).lower()
        href = str(element_info.get("href") or "").strip()
        label = f"{element_info.get('text') or ''} {element_info.get('aria_label') or ''} {element_info.get('accessible_name') or ''}".lower()

        if tag in ("input", "textarea", "select") and effective_type not in ("button",):
            return False, "Blocked (live session): form fields and submit inputs are never operated in the user's session."
        if effective_type in ("submit", "reset") or (tag == "button" and element_info.get("in_form") and effective_type != "button"):
            return False, "Blocked (live session): control could submit or reset a form."
        if tag == "a" or role == "link":
            h = href.lower()
            if not (h in ("", "#") or h.startswith("javascript:") or (h.startswith("#") and len(h) > 1)):
                return False, "Blocked (live session): link navigation is not exercised in the user's session."
        for kw in cls.LIVE_SESSION_BLOCKED_KEYWORDS:
            if re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", label):
                return False, f"Blocked (live session): label contains state-changing keyword '{kw}'."
        return True, "Permitted under the AURA live-session policy (no typing, no submission, no navigation)."
