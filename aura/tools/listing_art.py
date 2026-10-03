"""
Makes the Chrome Web Store listing artwork from a real scan.

The screenshots a listing needs are 1280x800. A side panel cannot be captured in place by the debugger,
so each piece is captured for real - the page in one capture, the panel in another - and composited at
the sizes Chrome shows them at. Nothing is drawn or faked: what appears in the images is what the
extension actually produced for that page.

    python -m aura.tools.listing_art

Writes to dist/listing/:
    screenshot-1-findings.png     the panel beside the scanned page, findings listed
    screenshot-2-finding.png      a finding opened, with its evidence
    screenshot-3-screenshot.png   the per-finding screenshot crop
    promo-440x280.png             the small promotional tile

The first three need Chrome and the Test Lab; the tile is drawn and needs neither.
"""
import base64
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dist" / "listing"

CANVAS = (1280, 800)
PANEL_W = 400          # roughly what Chrome gives a side panel
VIOLET = (109, 40, 217)
INK = (28, 27, 34)


def _paste(page_png: bytes, panel_png: bytes) -> bytes:
    """One listing image: the scanned page on the left, the panel on the right, at Chrome's proportions."""
    from PIL import Image

    canvas = Image.new("RGB", CANVAS, (236, 234, 242))
    page = Image.open(io.BytesIO(page_png)).convert("RGB")
    panel = Image.open(io.BytesIO(panel_png)).convert("RGB")

    page_w = CANVAS[0] - PANEL_W
    page = page.resize((page_w, int(page.height * page_w / page.width)), Image.LANCZOS)
    canvas.paste(page.crop((0, 0, page_w, min(page.height, CANVAS[1]))), (0, 0))

    panel = panel.resize((PANEL_W, int(panel.height * PANEL_W / panel.width)), Image.LANCZOS)
    canvas.paste(panel.crop((0, 0, PANEL_W, min(panel.height, CANVAS[1]))), (page_w, 0))

    # A hairline where they meet, as the browser draws it.
    from PIL import ImageDraw
    ImageDraw.Draw(canvas).line([(page_w, 0), (page_w, CANVAS[1])], fill=(205, 202, 214), width=2)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def promo_tile() -> bytes:
    """The 440x280 tile: the extension's own mark, its name, and what it does. No screenshot, no clutter."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = 440, 280
    img = Image.new("RGB", (w, h), (252, 251, 254))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 6], fill=VIOLET)

    # The same mark as the extension icon: a ring with a dot.
    cx, cy, r = 74, 92, 30
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=VIOLET, width=7)
    d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=VIOLET)

    def font(size, bold=False):
        for name in (("seguisb.ttf", "segoeuib.ttf") if bold else ("segoeui.ttf",)):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        try:
            return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default()

    d.text((122, 62), "AURA", font=font(46, bold=True), fill=INK)
    d.text((124, 116), "UI/UX runtime assurance", font=font(19), fill=(92, 90, 104))
    d.text((40, 186), "Scan the page you are on. Every finding", font=font(17), fill=INK)
    d.text((40, 212), "checked against the evidence.", font=font(17), fill=INK)
    d.text((40, 246), "Free - bring your own AI key", font=font(15), fill=VIOLET)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def screenshots() -> int:
    """Scans a Test Lab page with the real extension and composites three listing images."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    import threading
    import time

    import uvicorn

    from aura.api.server import create_app
    from aura.config import settings
    from cdp_harness import ChromeHarness, SidePanel, serve_test_lab

    token = "listing-art-" + "x" * 28
    settings.AI_PROVIDER = "mock"
    server = uvicorn.Server(uvicorn.Config(create_app(token=token), host="127.0.0.1", port=8765,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(60):
        if server.started:
            break
        time.sleep(0.1)

    lab = serve_test_lab()
    page_url = f"{lab}/05_mixed_realistic_suite/index.html"
    h = ChromeHarness(headless=True)
    made = 0
    try:
        ext = h.load_extension(str(ROOT / "extension"))
        options = h.extension_page(ext)
        h.evaluate(options, f"chrome.storage.local.set({{backendUrl: 'http://127.0.0.1:8765', token: '{token}'}})")
        tab = h.open_tab(page_url, new_window=True)
        h.click_toolbar_action(ext, tab)
        panel = SidePanel(h, ext)
        panel.wait_access("access-ok", 25)
        h.activate(tab)
        panel.scan(timeout=240)

        page_session = h.attach(tab)
        # Both panes are captured at the size they are shown at in the finished image, so neither is
        # scaled afterwards and the panel fills its full height rather than leaving the page half empty.
        h.send("Emulation.setDeviceMetricsOverride",
               {"width": CANVAS[0] - PANEL_W, "height": CANVAS[1], "deviceScaleFactor": 1, "mobile": False},
               session=page_session)
        h.send("Emulation.setDeviceMetricsOverride",
               {"width": PANEL_W, "height": CANVAS[1], "deviceScaleFactor": 1, "mobile": False},
               session=panel.session)
        time.sleep(0.8)

        def capture(session):
            return base64.b64decode(h.send("Page.captureScreenshot", {"format": "png"}, session=session)["data"])

        OUT.mkdir(parents=True, exist_ok=True)

        (OUT / "screenshot-1-findings.png").write_bytes(_paste(capture(page_session), capture(panel.session)))
        made += 1

        # A finding open, showing its evidence.
        panel.js("document.querySelector('#findings .finding').click()")
        panel.wait("!document.getElementById('detail').classList.contains('hidden')", 15)
        time.sleep(0.6)
        (OUT / "screenshot-2-finding.png").write_bytes(_paste(capture(page_session), capture(panel.session)))
        made += 1

        # The per-finding screenshot crop, which is the feature worth showing.
        shown = panel.js("""(() => {
          const cards = [...document.querySelectorAll('#findings .finding')];
          for (const c of cards) { c.click();
            if (!document.getElementById('act-shot').classList.contains('hidden')) return true; }
          return false; })()""")
        if shown:
            panel.click("#act-shot")
            panel.wait("document.querySelector('.shot') && document.querySelector('.shot').complete", 25)
            time.sleep(0.6)
            (OUT / "screenshot-3-screenshot.png").write_bytes(_paste(capture(page_session), capture(panel.session)))
            made += 1
        else:
            print("  no finding offered a screenshot on this page; image 3 skipped")
    finally:
        h.close()
        server.should_exit = True
        time.sleep(0.4)
    return made


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    OUT.mkdir(parents=True, exist_ok=True)
    print("Listing artwork")
    (OUT / "promo-440x280.png").write_bytes(promo_tile())
    print(f"  {(OUT / 'promo-440x280.png').relative_to(ROOT)}  440x280")
    if "--tile-only" in argv:
        return 0
    print("  scanning a Test Lab page with the real extension for the screenshots")
    try:
        made = screenshots()
    except Exception as e:
        print(f"  screenshots not produced: {type(e).__name__}: {e}")
        print("  the tile is still written; rerun with Chrome available for the screenshots")
        return 1
    for path in sorted(OUT.glob("screenshot-*.png")):
        from PIL import Image
        with Image.open(path) as img:
            print(f"  {path.relative_to(ROOT)}  {img.width}x{img.height}")
    print(f"\n{made} screenshots and the tile are in {OUT.relative_to(ROOT)}.")
    print("They show a real scan of the Test Lab's realistic page; replace them with a page of your own")
    print("if you would rather the listing showed something recognisable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
