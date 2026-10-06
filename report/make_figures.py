"""
Draws the report's figures as PNGs.

Every figure here describes the system as it actually is: the modules are the real modules, the request
names are the real routes, and the benchmark chart is drawn from benchmark_result.json rather than from
numbers typed in by hand. If the measurement changes, re-running this redraws the chart.

    python report/make_figures.py
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "report" / "figures"
BENCH = ROOT / "report" / "benchmark_result.json"

VIOLET = (109, 40, 217)
INK = (28, 27, 34)
MUTED = (92, 90, 104)
LINE = (170, 168, 182)
BOX_FILL = (243, 240, 253)
WARN = (202, 138, 4)
GOOD = (21, 128, 61)
BAD = (190, 40, 40)
WHITE = (255, 255, 255)


def font(size, bold=False):
    from PIL import ImageFont
    for name in (("seguisb.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def box(d, x, y, w, h, title, lines=(), fill=BOX_FILL, border=VIOLET, title_size=19, body_size=15):
    d.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=fill, outline=border, width=2)
    d.text((x + w / 2, y + 16), title, font=font(title_size, bold=True), fill=INK, anchor="ma")
    ty = y + 20 + title_size + 8
    for line in lines:
        d.text((x + w / 2, ty), line, font=font(body_size), fill=MUTED, anchor="ma")
        ty += body_size + 6


def arrow(d, x1, y1, x2, y2, label="", colour=VIOLET, width=3, label_above=True):
    d.line([x1, y1, x2, y2], fill=colour, width=width)
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    for side in (-0.4, 0.4):
        d.line([x2, y2, x2 - 14 * math.cos(ang + side), y2 - 14 * math.sin(ang + side)], fill=colour, width=width)
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        d.text((mx, my - 20 if label_above else my + 8), label, font=font(14), fill=MUTED, anchor="ma")


def canvas(w, h):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), WHITE)
    return img, ImageDraw.Draw(img)


def save(img, name):
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / name, format="PNG", optimize=True)
    print(f"  {name}  {img.width}x{img.height}")


# ---------------------------------------------------------------- Figure 1.1
def fig_concept():
    img, d = canvas(1100, 520)
    d.text((550, 18), "A page is audited where it is, in the browser the reader is using",
           font=font(20, bold=True), fill=INK, anchor="ma")

    box(d, 60, 90, 300, 330, "The page under audit", (
        "rendered DOM and styles", "accessibility violations", "runtime errors",
        "failed network requests", "a screenshot"), fill=(250, 250, 252), border=LINE)
    box(d, 410, 90, 290, 330, "AURA", (
        "collects the evidence", "asks a model what it sees",
        "checks every claim against", "that same evidence",
        "drops what it cannot support"), border=VIOLET)
    box(d, 750, 90, 290, 330, "What the person sees", (
        "a short problem statement", "where it is on the page",
        "why it matters, in plain words", "how confident AURA is",
        "and on what evidence"), fill=(240, 250, 244), border=GOOD)

    arrow(d, 365, 250, 405, 250)
    arrow(d, 705, 250, 745, 250)
    d.text((550, 450), "No claim reaches the reader unless the page itself supports it.",
           font=font(16), fill=MUTED, anchor="ma")
    save(img, "fig_1_1_concept.png")


# ---------------------------------------------------------------- Figure 3.1
def fig_existing():
    img, d = canvas(1100, 560)
    d.text((550, 16), "Existing system model: two separate worlds",
           font=font(20, bold=True), fill=INK, anchor="ma")

    box(d, 70, 80, 420, 200, "Rule-based checkers  (axe-core, WAVE, Lighthouse)", (
        "Deterministic, repeatable, trustworthy",
        "Only what a rule can express:",
        "missing alt text, contrast, labels, landmarks"), fill=(240, 250, 244), border=GOOD, title_size=17)
    d.text((280, 300), "Cannot see: hierarchy, emphasis, confusion,", font=font(15), fill=BAD, anchor="ma")
    d.text((280, 322), "a destructive button dressed as the primary one", font=font(15), fill=BAD, anchor="ma")

    box(d, 610, 80, 420, 200, "LLM reviewers  (prompt a model with a screenshot)", (
        "Judges layout, emphasis and wording",
        "Fluent, plausible, and unverified:",
        "states problems the page does not have"), fill=(253, 247, 240), border=WARN, title_size=17)
    d.text((820, 300), "No evidence link, no confidence a reader can act on,", font=font(15), fill=BAD, anchor="ma")
    d.text((820, 322), "the same page can yield different answers", font=font(15), fill=BAD, anchor="ma")

    d.rounded_rectangle([70, 380, 1030, 500], radius=10, fill=(252, 243, 243), outline=BAD, width=2)
    d.text((550, 400), "The gap", font=font(19, bold=True), fill=BAD, anchor="ma")
    d.text((550, 432), "One approach is trustworthy but narrow. The other is broad but cannot be trusted.",
           font=font(16), fill=INK, anchor="ma")
    d.text((550, 458), "A developer still has to verify every suggestion by hand, which is the work they wanted done.",
           font=font(16), fill=MUTED, anchor="ma")
    save(img, "fig_3_1_existing.png")


# ---------------------------------------------------------------- Figure 4.1
def fig_architecture():
    img, d = canvas(1180, 760)
    d.text((590, 14), "AURA system architecture", font=font(21, bold=True), fill=INK, anchor="ma")

    d.rounded_rectangle([40, 60, 580, 420], radius=12, outline=VIOLET, width=2, fill=(252, 251, 254))
    d.text((310, 72), "THE USER'S BROWSER", font=font(16, bold=True), fill=VIOLET, anchor="ma")
    box(d, 65, 110, 230, 120, "Side panel", ("findings, highlight,", "screenshot, explain, ask"), title_size=17)
    box(d, 320, 110, 235, 120, "Collector", ("DOM + computed styles", "axe-core, runtime errors", "screenshots"), title_size=17)
    box(d, 65, 255, 230, 140, "Provider client", ("calls Groq / Gemini /", "OpenAI / Anthropic", "with the user's own key"), title_size=17)
    box(d, 320, 255, 235, 140, "Local crop", ("per-finding screenshot", "cut and marked here;", "the image never leaves"), title_size=17)

    d.rounded_rectangle([640, 60, 1140, 420], radius=12, outline=(120, 120, 140), width=2, fill=(250, 250, 252))
    d.text((890, 72), "AURA SERVICE  (Render)", font=font(16, bold=True), fill=(70, 70, 90), anchor="ma")
    box(d, 665, 110, 450, 90, "Evidence packet + prompt", ("the only evidence the model is given",), title_size=17)
    box(d, 665, 215, 450, 90, "Independent verification", ("every claim re-checked against the DOM",), title_size=17)
    box(d, 665, 320, 450, 80, "Materiality gate and scoring", ("unsupported claims dropped, not shown",), title_size=17)

    arrow(d, 555, 170, 660, 155, "evidence")
    arrow(d, 660, 350, 555, 330, "verified findings", label_above=False)

    box(d, 380, 480, 420, 110, "AI provider chosen by the user",
        ("the browser calls it directly, with the user's key;", "the AURA service never receives that key"),
        fill=(253, 247, 240), border=WARN, title_size=17)
    arrow(d, 180, 395, 420, 478, "prompt + screenshot")
    arrow(d, 700, 478, 760, 410, "raw answer", label_above=False)

    d.text((590, 640), "The model is asked what it sees. The service decides what is true.",
           font=font(18, bold=True), fill=INK, anchor="ma")
    d.text((590, 672), "Nothing is written to disk on the service, and no screenshot is ever uploaded to it.",
           font=font(15), fill=MUTED, anchor="ma")
    save(img, "fig_4_1_architecture.png")


# ---------------------------------------------------------------- Figure 4.2
def fig_two_phase():
    img, d = canvas(1150, 620)
    d.text((575, 14), "A scan is two short requests, with the model call in between",
           font=font(20, bold=True), fill=INK, anchor="ma")

    lanes = [("Side panel", 120), ("AURA service", 575), ("AI provider", 1010)]
    for name, x in lanes:
        d.text((x, 62), name, font=font(17, bold=True), fill=VIOLET, anchor="ma")
        d.line([x, 92, x, 530], fill=LINE, width=2)

    steps = [
        (130, 120, 575, "POST /api/audits/prepare   (evidence, no screenshot)", VIOLET),
        (180, 575, 120, "{ audit_id, prompt }", (120, 120, 140)),
        (240, 120, 1010, "the prompt + one screenshot + the user's API key", WARN),
        (300, 1010, 120, "the model's raw answer", (120, 120, 140)),
        (360, 120, 575, "POST /api/audits/{id}/complete   (that answer)", VIOLET),
        (440, 575, 120, "verified findings, with evidence and confidence", GOOD),
    ]
    for y, x1, x2, label, colour in steps:
        arrow(d, x1 + (18 if x2 > x1 else -18), y, x2 + (-18 if x2 > x1 else 18), y, "", colour)
        d.text(((x1 + x2) / 2, y - 24), label, font=font(14), fill=INK, anchor="ma")

    d.rounded_rectangle([250, 400, 900, 404], radius=0, fill=(235, 233, 243))
    d.text((575, 560), "The key and the screenshots never pass through the AURA service.",
           font=font(17, bold=True), fill=INK, anchor="ma")
    d.text((575, 588), "This is also why the service holds no credential belonging to any user.",
           font=font(14), fill=MUTED, anchor="ma")
    save(img, "fig_4_2_two_phase.png")


# ---------------------------------------------------------------- Figure 4.3
def fig_pipeline():
    img, d = canvas(1150, 420)
    d.text((575, 14), "The verification pipeline: what happens to one AI claim",
           font=font(20, bold=True), fill=INK, anchor="ma")

    stages = [
        ("AI candidate", "the model says\nsomething is wrong", BOX_FILL, VIOLET),
        ("Target resolution", "which element\ndoes it mean?", BOX_FILL, VIOLET),
        ("Evidence check", "does the DOM\nsupport the claim?", BOX_FILL, VIOLET),
        ("Materiality gate", "is it a defect,\nor a preference?", BOX_FILL, VIOLET),
        ("Verdict", "CONFIRMED / LIKELY\nUNCERTAIN / REJECTED", (240, 250, 244), GOOD),
    ]
    x, w, gap = 40, 190, 42
    for title, sub, fill, border in stages:
        d.rounded_rectangle([x, 90, x + w, 250], radius=10, fill=fill, outline=border, width=2)
        d.text((x + w / 2, 110), title, font=font(17, bold=True), fill=INK, anchor="ma")
        for i, line in enumerate(sub.split("\n")):
            d.text((x + w / 2, 150 + i * 22), line, font=font(14), fill=MUTED, anchor="ma")
        if x + w + gap < 1100:
            arrow(d, x + w + 6, 170, x + w + gap - 6, 170)
        x += w + gap

    d.text((575, 300), "A claim the evidence contradicts is REJECTED and never reaches the reader.",
           font=font(17, bold=True), fill=BAD, anchor="ma")
    d.text((575, 332), "The ground truth of the benchmark suites is never part of this: it is read only after the audit,",
           font=font(14), fill=MUTED, anchor="ma")
    d.text((575, 354), "so the system cannot be tuned against the answer sheet.",
           font=font(14), fill=MUTED, anchor="ma")
    save(img, "fig_4_3_pipeline.png")


# ---------------------------------------------------------------- Figure 5.1 and 5.2
def fig_benchmark():
    if not BENCH.is_file():
        print("  (benchmark_result.json not found - chart skipped)")
        return
    data = json.loads(BENCH.read_text(encoding="utf-8"))
    agg = data["aggregate"]

    img, d = canvas(1000, 560)
    d.text((500, 14), "Benchmark result: 31 seeded defects across five suites",
           font=font(20, bold=True), fill=INK, anchor="ma")

    bars = [("Precision", (agg.get("micro_precision") or 0) * 100, VIOLET),
            ("Recall", (agg.get("micro_recall") or 0) * 100, GOOD),
            ("F1 score", (agg.get("micro_f1") or 0) * 100, (60, 90, 190))]
    base_y, left, bw, gap = 420, 170, 150, 110
    d.line([left - 40, base_y, 900, base_y], fill=LINE, width=2)
    for i in range(0, 101, 25):
        y = base_y - i * 3.0
        d.line([left - 45, y, 900, y], fill=(238, 237, 244), width=1)
        d.text((left - 55, y - 9), f"{i}%", font=font(14), fill=MUTED, anchor="ra")

    x = left
    for label, value, colour in bars:
        h = value * 3.0
        d.rounded_rectangle([x, base_y - h, x + bw, base_y], radius=6, fill=colour)
        d.text((x + bw / 2, base_y - h - 30), f"{value:.1f}%", font=font(22, bold=True), fill=INK, anchor="ma")
        d.text((x + bw / 2, base_y + 14), label, font=font(17), fill=INK, anchor="ma")
        x += bw + gap

    tp, fp, fn = agg.get("micro_tp", 0), agg.get("micro_fp", 0), agg.get("micro_fn", 0)
    d.text((500, 490), f"True positives {tp}    False positives {fp}    False negatives {fn}",
           font=font(17, bold=True), fill=INK, anchor="ma")
    d.text((500, 518), f"measured {data['measured_at'][:10]} with {data['provider']} / {data.get('model') or '-'}",
           font=font(14), fill=MUTED, anchor="ma")
    save(img, "fig_5_1_benchmark.png")

    # Per-suite
    img, d = canvas(1000, 520)
    d.text((500, 14), "Detection per suite", font=font(20, bold=True), fill=INK, anchor="ma")
    rows = data["per_suite"]
    y = 80
    d.text((60, y), "Suite", font=font(16, bold=True), fill=INK)
    for label, cx in (("TP", 520), ("FP", 600), ("FN", 680)):
        d.text((cx, y), label, font=font(16, bold=True), fill=INK, anchor="ma")
    d.text((850, y), "Recall", font=font(16, bold=True), fill=INK, anchor="ma")
    y += 34
    d.line([60, y - 8, 940, y - 8], fill=LINE, width=2)
    for r in rows:
        name = r["suite"].replace("_", " ").replace("suite", "").strip().title()
        d.text((60, y), name, font=font(15), fill=INK)
        for value, cx, colour in ((r["tp"], 520, GOOD), (r["fp"], 600, WARN), (r["fn"], 680, BAD)):
            d.text((cx, y), str(value), font=font(15, bold=True), fill=colour, anchor="ma")
        rec = (r.get("recall") or 0) * 100
        d.rounded_rectangle([760, y + 3, 760 + rec * 1.6, y + 17], radius=3, fill=VIOLET)
        d.text((940, y), f"{rec:.0f}%", font=font(15), fill=INK, anchor="ra")
        y += 40
    save(img, "fig_5_2_per_suite.png")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("figures:")
    fig_concept()
    fig_existing()
    fig_architecture()
    fig_two_phase()
    fig_pipeline()
    fig_benchmark()
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
