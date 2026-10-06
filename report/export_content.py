"""
Flattens the report content into report/build/content.json for the Word builder.

Keeping content in Python and rendering in JavaScript means the prose stays editable in one place and
the builder never has to parse it. Code listings for Appendix 1 are read from the repository here, so
the appendix is the code that actually shipped rather than a transcription of it.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report"))

from content_part1 import (META, ABSTRACT, ACKNOWLEDGEMENT, SYMBOLS, ABBREVIATIONS,
                           CHAPTER_1, CHAPTER_2, CHAPTER_3)
from content_part2 import CHAPTER_4, CHAPTER_5, CHAPTER_6, REFERENCES, APPENDIX_2_STEPS

# Each listing is (source path, first line, last line or None for the whole file, heading).
APPENDIX_1_LISTINGS = [
    ("aura/api/relay.py", 1, None,
     "A1.1  Browser relay provider - carries the browser's model call through the pipeline"),
    ("aura/verification/verifier.py", 1, None,
     "A1.2  Verification entry point - every candidate is checked against evidence"),
    ("aura/verification/rules.py", 1, None,
     "A1.3  Verdict assignment - CONFIRMED, LIKELY, UNCERTAIN or REJECTED"),
    ("aura/verification/evidence.py", 102, 232,
     "A1.4  Evidence checking - rejecting a claim the measurements contradict"),
    ("aura/verification/materiality.py", 246, 330,
     "A1.5  The materiality gate - separating a defect from a preference"),
    ("aura/findings/aggregation.py", 245, 310,
     "A1.6  Measured interaction outcomes - reporting a control that did nothing"),
]


def listing(rel, start, end, heading):
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    end = len(lines) if end is None else end
    body = lines[start - 1:end]
    return {"heading": heading, "file": rel,
            "range": f"lines {start}-{end}" if (start, end) != (1, len(lines)) else "complete file",
            "lines": [ln.rstrip() for ln in body]}


def figure_sizes():
    from PIL import Image
    out = {}
    for p in sorted((ROOT / "report" / "figures").glob("*.png")):
        with Image.open(p) as im:
            out[p.name] = list(im.size)
    return out


def code_stats():
    """Line counts quoted in the abstract, recomputed so they cannot drift."""
    def count(patterns, exclude=()):
        total = 0
        for pat in patterns:
            for p in ROOT.glob(pat):
                if any(x in p.as_posix() for x in exclude) or not p.is_file():
                    continue
                total += len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        return total
    return {
        "engine": count(["aura/**/*.py"]),
        "extension": count(["extension/**/*.js", "extension/**/*.html", "extension/**/*.css"],
                           exclude=("extension/vendor",)),
        "tests": count(["tests/**/*.py"]),
    }


def main():
    build = ROOT / "report" / "build"
    build.mkdir(exist_ok=True)
    bench = json.loads((ROOT / "report" / "benchmark_result.json").read_text(encoding="utf-8")) \
        if (ROOT / "report" / "benchmark_result.json").is_file() else None
    page_map = {}
    pm = build / "page_numbers.json"
    if pm.is_file():
        page_map = json.loads(pm.read_text(encoding="utf-8"))

    data = {
        "meta": META,
        "abstract": ABSTRACT,
        "acknowledgement": ACKNOWLEDGEMENT,
        "symbols": SYMBOLS,
        "abbreviations": ABBREVIATIONS,
        "chapters": [CHAPTER_1, CHAPTER_2, CHAPTER_3, CHAPTER_4, CHAPTER_5, CHAPTER_6],
        "references": REFERENCES,
        "appendix1": [listing(*spec) for spec in APPENDIX_1_LISTINGS],
        "appendix2_steps": APPENDIX_2_STEPS,
        "figure_sizes": figure_sizes(),
        "code_stats": code_stats(),
        "benchmark": bench,
        "page_numbers": page_map,
    }
    out = build / "content.json"
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    appendix_lines = sum(len(l["lines"]) for l in data["appendix1"])
    print(f"wrote {out.relative_to(ROOT)}")
    print(f"  chapters: {len(data['chapters'])}  figures: {len(data['figure_sizes'])}  "
          f"references: {len(data['references'])}")
    print(f"  appendix 1: {appendix_lines} lines of code across {len(data['appendix1'])} listings")
    print(f"  code stats: {data['code_stats']}")
    print(f"  page numbers known: {len(page_map)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
