"""
Which AURA code is actually running?

    python -m aura.tools.live_check

The side panel gets its findings from the local AURA server, so an old server process keeps serving old
findings however many times the extension is reloaded. This prints what the code on disk would produce and
what the most recent scan actually produced, so the two can be compared at a glance.
"""
import json
from pathlib import Path

from aura.config import settings


def _disk_version() -> dict:
    from aura.api import views
    from aura.interpretation import interpreter
    return {
        "server computes target.highlightable": "highlightable" in (views._target_view.__doc__ or "")
        or "highlightable" in views.__dict__["_target_view"].__code__.co_consts.__str__(),
        "grouped findings can be highlighted": "GROUP_PRESENTATION" in dir(interpreter),
        "explanations name the element on the page": hasattr(interpreter, "_specifics"),
        "fix-preview feature removed": not hasattr(interpreter, "evaluate_" + "preview" + "_capability"),
    }


def _latest_audit() -> tuple:
    runs = sorted((settings.RUNS_DIR).glob("AURA-*/extension_view.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        return None, None
    return runs[0], json.loads(runs[0].read_text(encoding="utf-8"))


def main() -> None:
    print("CODE ON DISK")
    for label, ok in _disk_version().items():
        print(f"  [{'x' if ok else ' '}] {label}")

    path, view = _latest_audit()
    if not view:
        print("\nNo scan has been stored yet. Scan a page, then run this again.")
        return

    findings = view.get("findings") or []
    with_flag = [f for f in findings if "highlightable" in (f.get("target") or {})]
    offered = [f for f in findings if (f.get("target") or {}).get("highlightable")]
    print(f"\nMOST RECENT SCAN  {view.get('audit_id')}  ({view.get('page_url')})")
    print(f"  stored at: {path}")
    print(f"  findings: {len(findings)}")
    if not with_flag:
        print("  !! None of these findings carry 'highlightable'.")
        print("     The server that ran this scan was older than the code on disk.")
        print("     Stop the AURA server, start it again, then re-scan the page.")
    else:
        print(f"  findings offering Highlight: {len(offered)}/{len(findings)}")
        for f in findings:
            t = f.get("target") or {}
            print(f"    {f['id']:<7} {str(f.get('rule'))[:28]:<28} kind={str(t.get('kind')):<11} "
                  f"highlight={'yes' if t.get('highlightable') else 'no'}")
        if not offered:
            print("     Every finding on this page is page-level or could not be matched to one element.")
            print("     Scan a page with element-level findings to see Highlight offered.")


if __name__ == "__main__":
    main()
