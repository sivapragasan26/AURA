"""
Audit store for the API: every scan has its own isolated audit context, keyed by audit_id.

Recent views are kept in memory (bounded) and persisted next to the engine's audit record
(runs/<audit_id>/extension_view.json) so results survive a server restart. No global mutable scan state.
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
        self._items: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_items = max_items

    @staticmethod
    def valid_id(audit_id: str) -> bool:
        return bool(AUDIT_ID_RE.match(audit_id or ""))

    def put(self, view: Dict[str, Any]) -> None:
        audit_id = view["audit_id"]
        with self._lock:
            self._items[audit_id] = view
            self._items.move_to_end(audit_id)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        try:
            run_dir = settings.RUNS_DIR / audit_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "extension_view.json").write_text(json.dumps(view, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass

    def get(self, audit_id: str) -> Optional[Dict[str, Any]]:
        if not self.valid_id(audit_id):
            return None
        with self._lock:
            if audit_id in self._items:
                return self._items[audit_id]
        path = settings.RUNS_DIR / audit_id / "extension_view.json"
        try:
            view = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        with self._lock:
            self._items[audit_id] = view
        return view
