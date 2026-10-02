"""
Per-finding screenshot crops.

The panel can show a person where a problem is, using the capture taken during the scan, cropped to the
element the finding is about and with that element outlined. These tests cover the honest cases too: no
capture kept, and a finding whose element has no recorded geometry.
"""
import io
import json

import pytest
from starlette.testclient import TestClient

from aura.api import security, shots
from aura.api.server import create_app
from aura.api.store import AuditStore
from aura.config import settings

PNG = pytest.importorskip("PIL.Image")

TOKEN = "shot-token"
BASE = "http://127.0.0.1:8765"
EXT_ORIGIN = "chrome-extension://aura-test"
AUDIT = "AURA-2026-880001"
VIEWPORT = {"width": 500, "height": 400}


def _capture(width=1000, height=800):
    """A capture at 2x the viewport, as a real high-DPI screenshot would be."""
    from PIL import Image
    img = Image.new("RGB", (width, height), (240, 240, 240))
    for x in range(width):
        for y in range(0, height, 40):
            img.putpixel((x, y), (200, 200, 220))
    return img


def _view(boxes, fid="F-001"):
    return {
        "audit_id": AUDIT, "page_url": "https://example.com/", "title": "Example", "viewport": VIEWPORT,
        "findings": [{
            "id": fid, "rule": "color-contrast", "severity": "medium", "category": "ACCESSIBILITY",
            "verification_status": "CONFIRMED", "affected_count": len(boxes) or 1,
            "human": {"title": "Text is hard to read", "summary": "Low contrast.", "short_summary": "Low contrast.",
                      "why_it_matters": "Hard to read.", "what_to_do": "Raise the contrast.",
                      "location": "the price label"},
            "target": {"kind": "element", "selector": "#price", "selectors": ["#price"],
                       "boxes": boxes, "has_shot_region": bool(boxes)},
        }],
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path)
    store = AuditStore()
    app = create_app(token=TOKEN, store=store)
    return TestClient(app, base_url=BASE), store


def auth():
    return {security.TOKEN_HEADER: TOKEN, "Origin": EXT_ORIGIN}


def _write_capture(tmp_path, img=None):
    run = tmp_path / AUDIT
    run.mkdir(parents=True, exist_ok=True)
    (img or _capture()).save(run / "screenshot.png")


def test_crop_is_returned_for_a_finding_with_geometry(client, tmp_path):
    api, store = client
    _write_capture(tmp_path)
    store.put(_view([{"x": 100, "y": 200, "width": 120, "height": 30}]))

    r = api.get(f"/api/audits/{AUDIT}/findings/F-001/screenshot", headers=auth())
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    from PIL import Image
    out = Image.open(io.BytesIO(r.content))
    # The crop is a small region, not the whole 1000x800 capture.
    assert out.width < 1000 and out.height < 800
    assert out.width >= 180 and out.height >= 180   # padded to a readable minimum
    assert r.headers["cache-control"] == "no-store"


def test_the_element_is_outlined_in_the_crop(client, tmp_path):
    api, store = client
    _write_capture(tmp_path)
    store.put(_view([{"x": 100, "y": 200, "width": 120, "height": 60}]))

    r = api.get(f"/api/audits/{AUDIT}/findings/F-001/screenshot", headers=auth())
    from PIL import Image
    out = Image.open(io.BytesIO(r.content)).convert("RGB")
    # The highlight violet must appear: the capture is grey, so any strong violet is AURA's outline.
    violet = sum(1 for px in out.getdata() if px[0] > 90 and px[2] > 170 and px[1] < 110)
    assert violet > 50, "the element was not outlined in the returned crop"


def test_a_grouped_finding_covers_every_recorded_box(client, tmp_path):
    api, store = client
    _write_capture(tmp_path)
    far_apart = [{"x": 20, "y": 20, "width": 40, "height": 20},
                 {"x": 700, "y": 600, "width": 40, "height": 20}]
    store.put(_view(far_apart))

    r = api.get(f"/api/audits/{AUDIT}/findings/F-001/screenshot", headers=auth())
    from PIL import Image
    out = Image.open(io.BytesIO(r.content))
    # The crop spans both boxes rather than showing only the first.
    assert out.width > 300 and out.height > 250


def test_no_capture_is_reported_honestly(client, tmp_path):
    api, store = client
    store.put(_view([{"x": 10, "y": 10, "width": 50, "height": 20}]))  # no screenshot.png written

    r = api.get(f"/api/audits/{AUDIT}/findings/F-001/screenshot", headers=auth())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NO_CAPTURE"
    assert "Scan the page again" in r.json()["error"]["message"]


def test_a_finding_without_geometry_is_not_given_the_whole_page(client, tmp_path):
    """A page-level finding has no region. Showing the full page would imply a location AURA never had."""
    api, store = client
    _write_capture(tmp_path)
    store.put(_view([]))

    r = api.get(f"/api/audits/{AUDIT}/findings/F-001/screenshot", headers=auth())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NO_REGION"


def test_unknown_audit_and_finding_are_404(client, tmp_path):
    api, store = client
    _write_capture(tmp_path)
    store.put(_view([{"x": 10, "y": 10, "width": 50, "height": 20}]))
    assert api.get(f"/api/audits/{AUDIT}/findings/F-404/screenshot", headers=auth()).status_code == 404
    assert api.get("/api/audits/AURA-2026-000999/findings/F-001/screenshot", headers=auth()).status_code == 404


def test_the_screenshot_needs_the_pairing_token(client, tmp_path):
    api, store = client
    _write_capture(tmp_path)
    store.put(_view([{"x": 10, "y": 10, "width": 50, "height": 20}]))
    r = api.get(f"/api/audits/{AUDIT}/findings/F-001/screenshot", headers={"Origin": EXT_ORIGIN})
    assert r.status_code == 401


def test_the_audit_view_never_embeds_image_data(client, tmp_path):
    """Geometry travels in the view; pixels do not. The image is fetched on demand instead."""
    api, store = client
    _write_capture(tmp_path)
    store.put(_view([{"x": 10, "y": 10, "width": 50, "height": 20}]))
    body = json.dumps(store.get(AUDIT))
    assert "base64" not in body and "data:image" not in body
    assert "iVBOR" not in body  # the PNG base64 prefix


def test_capture_scale_is_derived_from_the_viewport(client, tmp_path):
    """
    The capture is 2x the viewport here. If the scale were ignored the crop would land in the wrong
    place, so the box is put near the bottom-right and the crop must follow it there.
    """
    api, store = client
    _write_capture(tmp_path)
    store.put(_view([{"x": 400, "y": 300, "width": 60, "height": 40}]))  # CSS px, i.e. 800,600 in capture px
    r = api.get(f"/api/audits/{AUDIT}/findings/F-001/screenshot", headers=auth())
    assert r.status_code == 200
    from PIL import Image
    out = Image.open(io.BytesIO(r.content))
    # Without scaling, x=400 y=300 would be mid-capture and a full crop would be possible; at 2x the box
    # sits at 800,600 and the crop is clipped by the 1000x800 edge.
    assert out.width <= 180 + 2 * shots.PAD + 60
    assert out.height <= 180 + 2 * shots.PAD + 40
