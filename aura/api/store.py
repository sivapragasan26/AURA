"""
Audit store for the API: every scan has its own isolated audit context, keyed by audit_id.

Recent views are kept in memory (bounded) and, where the server persists at all, next to the engine's
audit record (runs/<audit_id>/extension_view.json) so results survive a restart. No global mutable scan
state.

An audit belongs to the install that made it. Audit ids are a running number, so without that an audit
could be read back by anyone holding any valid token simply by counting; a view carries the page's
address, its title and text from it. The owner is the caller's install id (aura/api/security.install_id),
and a request from anyone else is answered as if the audit did not exist.
"""
import json
import re
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

from aura.config import settings

AUDIT_ID_RE = re.compile(r"^AURA-\d{4}-\d{6}$")
MAX_IN_MEMORY = 50


class AuditStore:
    def __init__(self, max_items: int = MAX_IN_MEMORY):
        # audit_id -> (owner install id, view)
        self._items: "OrderedDict[str, tuple]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_items = max_items

    @staticmethod
    def valid_id(audit_id: str) -> bool:
        return bool(AUDIT_ID_RE.match(audit_id or ""))

    def put(self, view: Dict[str, Any], owner: str = "") -> None:
        audit_id = view["audit_id"]
        with self._lock:
            self._items[audit_id] = (owner, view)
            self._items.move_to_end(audit_id)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        if not settings.PERSIST:
            return  # hosted: audits live in memory only, so no page content is written down
        try:
            run_dir = settings.RUNS_DIR / audit_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "extension_view.json").write_text(json.dumps(view, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass

    def get(self, audit_id: str, owner: str = "") -> Optional[Dict[str, Any]]:
        """The audit, if this caller is the install that made it. Anyone else is told there is none."""
        if not self.valid_id(audit_id):
            return None
        with self._lock:
            held = self._items.get(audit_id)
        if held is not None:
            kept_owner, view = held
            return view if kept_owner == owner else None
        if not settings.PERSIST:
            return None   # hosted: nothing was written down, so there is nothing to read back
        # A server that persists is a server someone runs for themselves, and the audit on its disk is
        # theirs. It is read back for them; a hosted deployment never reaches here.
        path = settings.RUNS_DIR / audit_id / "extension_view.json"
        try:
            view = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        with self._lock:
            self._items[audit_id] = (owner, view)
        return view
