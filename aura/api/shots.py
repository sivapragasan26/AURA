"""
Per-finding screenshot crops.

The panel can show a person WHERE a problem is, using the capture taken during the scan, cropped to the
element the finding is about and with that element boxed. The image is produced on demand from the capture
stored beside the audit (runs/<audit_id>/screenshot.png) and is served by the local server to the local
extension only: nothing is uploaded, and no image is ever embedded in the audit view.

A finding whose element has no recorded geometry (page-level findings, or a target AURA could not match)
has no region to show, and the caller is told so rather than being handed the whole page as if it were the
answer.
"""
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aura.config import settings

PAD = 28           # breathing room around the element, in capture pixels
MIN_SIDE = 180     # never return a sliver
MAX_SIDE = 1400    # keep the response small
BORDER = 4
BORDER_COLOR = (124, 58, 237)      # the same violet the in-page highlight uses
SHADE = (124, 58, 237, 38)


def capture_path(audit_id: str) -> Path:
    return settings.RUNS_DIR / audit_id / "screenshot.png"


def has_capture(audit_id: str) -> bool:
    return capture_path(audit_id).is_file()


def _boxes_of(finding: Dict[str, Any]) -> List[Dict[str, float]]:
    target = finding.get("target") or {}
    out = []
    for b in target.get("boxes") or []:
        try:
            w, h = float(b.get("width") or 0), float(b.get("height") or 0)
            if w > 0 and h > 0:
                out.append({"x": float(b.get("x") or 0), "y": float(b.get("y") or 0), "width": w, "height": h})
        except (TypeError, ValueError):
            continue
    return out


def _union(boxes: List[Dict[str, float]]) -> Tuple[float, float, float, float]:
    left = min(b["x"] for b in boxes)
    top = min(b["y"] for b in boxes)
    right = max(b["x"] + b["width"] for b in boxes)
    bottom = max(b["y"] + b["height"] for b in boxes)
    return left, top, right, bottom


def _badge(pen: Any, x: float, y: float, label: str) -> None:
    """A numbered marker at a box's top-left corner, for a finding that covers several places."""
    size = 20
    left, top = max(0, x - 2), max(0, y - size - 2)
    pen.rectangle([left, top, left + size, top + size], fill=BORDER_COLOR + (235,),
                  outline=(255, 255, 255, 230), width=2)
    try:
        pen.text((left + size / 2, top + size / 2), label, fill=(255, 255, 255, 255), anchor="mm")
    except (TypeError, ValueError):  # very old Pillow without anchor support
        pen.text((left + 6, top + 4), label, fill=(255, 255, 255, 255))


def render(audit_id: str, finding: Dict[str, Any], viewport_width: Optional[float] = None) -> Optional[bytes]:
    """
    PNG bytes showing just the part of the page this finding is about, with the element boxed.

    Returns None when there is no capture or no recorded geometry: the caller reports that honestly
    instead of showing an unrelated part of the page.
    """
    path = capture_path(audit_id)
    if not path.is_file():
        return None
    boxes = _boxes_of(finding)
    if not boxes:
        return None

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    with Image.open(path) as img:
        img = img.convert("RGB")
        # Boxes are in CSS pixels; the capture may be at a higher device pixel ratio. Comparing the
        # capture's width with the viewport recorded for the scan recovers the ratio without needing the
        # page to report it.
        ratio = 1.0
        if viewport_width and viewport_width > 0:
            guess = img.width / float(viewport_width)
            if 0.5 <= guess <= 4.0:
                ratio = guess
        scaled = [{k: v * ratio for k, v in b.items()} for b in boxes]
        left, top, right, bottom = _union(scaled)

        crop_l = max(0, int(left - PAD))
        crop_t = max(0, int(top - PAD))
        crop_r = min(img.width, int(right + PAD))
        crop_b = min(img.height, int(bottom + PAD))
        if crop_r - crop_l < MIN_SIDE:
            grow = (MIN_SIDE - (crop_r - crop_l)) // 2
            crop_l, crop_r = max(0, crop_l - grow), min(img.width, crop_r + grow)
        if crop_b - crop_t < MIN_SIDE:
            grow = (MIN_SIDE - (crop_b - crop_t)) // 2
            crop_t, crop_b = max(0, crop_t - grow), min(img.height, crop_b + grow)
        if crop_r <= crop_l or crop_b <= crop_t:
            return None

        region = img.crop((crop_l, crop_t, crop_r, crop_b)).convert("RGBA")

        # Dim everything except the marked areas, so the eye goes straight to the problem, then outline
        # each one and number it when there is more than one.
        dim = Image.new("RGBA", region.size, (14, 10, 30, 110))
        holes = Image.new("L", region.size, 255)
        cutter = ImageDraw.Draw(holes)
        boxes_px = []
        for b in scaled:
            x0, y0 = b["x"] - crop_l, b["y"] - crop_t
            x1, y1 = x0 + b["width"], y0 + b["height"]
            boxes_px.append((x0, y0, x1, y1))
            cutter.rectangle([x0, y0, x1, y1], fill=0)
        dim.putalpha(Image.composite(dim.getchannel("A"), Image.new("L", region.size, 0), holes))
        shot = Image.alpha_composite(region, dim)

        overlay = Image.new("RGBA", region.size, (0, 0, 0, 0))
        pen = ImageDraw.Draw(overlay)
        for index, (x0, y0, x1, y1) in enumerate(boxes_px, start=1):
            pen.rectangle([x0, y0, x1, y1], fill=SHADE)
            pen.rectangle([x0 - 1, y0 - 1, x1 + 1, y1 + 1], outline=(255, 255, 255, 220), width=BORDER + 3)
            pen.rectangle([x0, y0, x1, y1], outline=BORDER_COLOR, width=BORDER)
            if len(boxes_px) > 1:
                _badge(pen, x0, y0, str(index))
        shot = Image.alpha_composite(shot, overlay).convert("RGB")

        if max(shot.size) > MAX_SIDE:
            factor = MAX_SIDE / max(shot.size)
            shot = shot.resize((max(1, int(shot.width * factor)), max(1, int(shot.height * factor))))

        buf = io.BytesIO()
        shot.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
