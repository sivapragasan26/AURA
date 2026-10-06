"""
Renders the report content into a single Markdown manuscript that can be handed to another tool to
produce the .docx, plus the Appendix 1 code listing as a separate plain-text file.

    python report/make_manuscript.py

Writes report/AURA_Report_Manuscript.md and report/APPENDIX1_CODE.txt. The manuscript carries a
formatting preamble so the document can be reproduced in the college template's layout, then the
complete text of the front matter and all six chapters.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report"))

from content_part1 import (META, ABSTRACT, ACKNOWLEDGEMENT, SYMBOLS, ABBREVIATIONS,
                           CHAPTER_1, CHAPTER_2, CHAPTER_3)
from content_part2 import CHAPTER_4, CHAPTER_5, CHAPTER_6, REFERENCES, APPENDIX_2_STEPS
from export_content import APPENDIX_1_LISTINGS

CHAPTERS = [CHAPTER_1, CHAPTER_2, CHAPTER_3, CHAPTER_4, CHAPTER_5, CHAPTER_6]

PREAMBLE = """<!--
HOW TO BUILD THIS DOCUMENT

Produce a Microsoft Word .docx reproducing the layout of a Pondicherry University B.Tech project
report. Everything below the horizontal rule is the content; this block is instructions only.

Page and type
  A4. Margins: left 1.25 in, top/right/bottom 1.0 in. Times New Roman 12 pt, 1.5 line spacing,
  justified body text with a 0.3 in first-line indent.
  Chapter headings: "CHAPTER N" then the chapter title, both centred, bold, 14 pt, on a new page.
  Section headings: "1.1  OVERVIEW" style, bold, left aligned, 13 pt; sub-sections 12 pt bold.
  Figure captions centred bold 11 pt BELOW the figure; table captions centred bold 11 pt ABOVE
  the table. Tables: header row shaded light blue (D9E2F3), all borders, 10.5 pt text.

Page numbering
  Front matter in roman numerals, body in arabic. The page count is continuous, so if the front
  matter runs to nine pages the body starts at 10. Page number centred in the footer.
  The table of contents and the lists of figures and tables are three-column tables
  (number / title / page no.) with real page numbers filled in, not a generated TOC field.

Order of the document
  1. Title page                      6. Table of contents
  2. Bonafide certificate            7. List of figures
  3. Declaration                     8. List of tables
  4. Acknowledgement                 9. List of symbols
  5. Abstract                       10. List of abbreviations
  then Chapters 1-6, References, Appendix 1, Appendix 2.
  Target length is about 56 pages.

Figures
  Seven PNG files accompany this manuscript. Insert each one where its [FIGURE] marker appears,
  centred, scaled to the text width, with the caption given in the marker.

Appendix 1
  The source code listings are in the accompanying APPENDIX1_CODE.txt. Set them in Consolas 8 pt,
  single spaced, left aligned, keeping the sub-headings that file already carries.
-->

"""


def md_table(spec):
    out = [f"**Table {spec['number']}  {spec['caption']}**", ""]
    out.append("| " + " | ".join(spec["headers"]) + " |")
    out.append("|" + "|".join([" --- "] * len(spec["headers"])) + "|")
    for row in spec["rows"]:
        cells = [str(c).replace("|", "\\|") for c in row]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return out


def render_blocks(blocks):
    out = []
    for b in blocks:
        if "p" in b:
            out += [b["p"], ""]
        elif "bullets" in b:
            out += ["- " + t for t in b["bullets"]] + [""]
        elif "figure" in b:
            f = b["figure"]
            out += [f"[FIGURE {f['number']}: insert `report/figures/{f['file']}` here, "
                    f"caption “Figure {f['number']}  {f['caption']}”]", ""]
        elif "table" in b:
            out += md_table(b["table"])
        else:
            raise ValueError(f"unknown block: {list(b)}")
    return out


def front_matter():
    m = META
    names_sq = ", ".join(f"{n} [REGISTER NO: {r}]" for n, r in m["students"])
    names_dq = ", ".join(f"{n} “Register No: {r}”" for n, r in m["students"])
    L = ["---", "", "# TITLE PAGE", "",
         f"**{m['title']}**", "", f"**{m['report_kind']}**", "", "Submitted by", ""]
    for n, r in m["students"]:
        L += [f"| {n} | REGISTER NO: {r} |"] if False else [f"{n}  —  REGISTER NO: {r}  "]
    L += ["", "Under the guidance of  ", f"**{m['guide']},**  ", f"{m['guide_title']}  ",
          f"{m['department']}", "",
          "in partial fulfillment for the award of the degree  ", "of  ",
          f"**{m['degree']}**  ", "in", "",
          "**DEPARTMENT OF ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING**", "",
          f"**{m['college']}**  ", f"**{m['college_place']}**  ", f"**{m['university']}**", "",
          f"**{m['month_year']}**", "",
          "---", "", "# BONAFIDE CERTIFICATE", "",
          "MANAKULA VINAYAGAR INSTITUTE OF TECHNOLOGY  ", "PONDICHERRY UNIVERSITY", "",
          "DEPARTMENT OF ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING", "",
          f"This is to certify that the project work entitled “{m['title']}” is a Bonafide "
          f"work done by, {names_sq} in partial fulfillment of the requirement for the award of "
          f"B.Tech Degree in Artificial Intelligence and Machine Learning by Pondicherry University "
          f"during the academic year {m['academic_year']}.", "",
          f"PROJECT GUIDE | HEAD OF THE DEPARTMENT", "--- | ---",
          f"{m['guide']} | {m['guide']}",
          f"{m['guide_title']} | {m['guide_title']}",
          f"{m['department_short']} | {m['department_short']}", "",
          "Viva-Voce Examination held on ................................................", "",
          "INTERNAL EXAMINER | EXTERNAL EXAMINER", "--- | ---", " | ", "",
          "---", "", "# DECLARATION", "",
          f"This is to certified that the Report “{m['title']}” is a Bonafide record of "
          f"independent work done by {names_dq} for the award of B.Tech Degree in Artificial "
          f"Intelligence and Machine Learning under the supervision of {m['guide']}, Certified "
          f"further that the work reported herein does not from part of any thesis or dissertation "
          f"on the basis of which degree or award was conferred earlier.", ""]
    for i, (n, _) in enumerate(m["students"], 1):
        L.append(f"{i}. {n}")
    L += ["",
          f"PROJECT GUIDE | HEAD OF THE DEPARTMENT", "--- | ---",
          f"{m['guide']} | {m['guide']}",
          f"{m['guide_title']} | {m['guide_title']}",
          f"{m['department_short']} | {m['department_short']}", "",
          "---", "", "# ACKNOWLEDGEMENT", ""]
    L += [p + "\n" for p in ACKNOWLEDGEMENT]
    for n, r in m["students"]:
        L.append(f"{n}  {r}  ")
    L += ["", "---", "", "# ABSTRACT", ""]
    L += [p + "\n" for p in ABSTRACT]
    L += ["---", "", "# TABLE OF CONTENTS", "",
          "Build this as a three-column table (CHAPTER NO. | TITLE | PAGE NO.) with the entries "
          "below and the real page numbers of the finished document. Front-matter entries take "
          "roman numerals.", "",
          "| CHAPTER NO. | TITLE | PAGE NO. |", "| --- | --- | --- |"]
    for label in ("ACKNOWLEDGEMENT", "ABSTRACT", "LIST OF FIGURES", "LIST OF TABLES",
                  "LIST OF SYMBOLS", "LIST OF ABBREVIATIONS"):
        L.append(f"|  | **{label}** |  |")
    for ch in CHAPTERS:
        L.append(f"| **{ch['number']}** | **{ch['title']}** |  |")
        for s in ch["sections"]:
            L.append(f"| {s['number']} | {s['title'].title()} |  |")
    for label in ("REFERENCES", "APPENDIX 1", "APPENDIX 2"):
        L.append(f"|  | **{label}** |  |")
    L += ["", "---", "", "# LIST OF FIGURES", "",
          "| FIGURE NO. | TITLE | PAGE NO. |", "| --- | --- | --- |"]
    for ch in CHAPTERS:
        for s in ch["sections"]:
            for b in s["blocks"]:
                if "figure" in b:
                    L.append(f"| {b['figure']['number']} | {b['figure']['caption']} |  |")
    L += ["", "---", "", "# LIST OF TABLES", "",
          "| TABLE NO. | TITLE | PAGE NO. |", "| --- | --- | --- |"]
    for ch in CHAPTERS:
        for s in ch["sections"]:
            for b in s["blocks"]:
                if "table" in b:
                    L.append(f"| {b['table']['number']} | {b['table']['caption']} |  |")
    L += ["", "---", "", "# LIST OF SYMBOLS", "", "| SYMBOL | DESCRIPTION |", "| --- | --- |"]
    L += [f"| {a} | {b} |" for a, b in SYMBOLS]
    L += ["", "---", "", "# LIST OF ABBREVIATIONS", "", "| ABBREVIATION | EXPANSION |", "| --- | --- |"]
    L += [f"| {a} | {b} |" for a, b in ABBREVIATIONS]
    L += ["", "---", ""]
    return L


def chapters():
    L = []
    for ch in CHAPTERS:
        L += [f"# CHAPTER {ch['number']}", "", f"# {ch['title']}", ""]
        for s in ch["sections"]:
            depth = "###" if s.get("level") == 3 else "##"
            L += [f"{depth} {s['number']}  {s['title']}", ""]
            L += render_blocks(s["blocks"])
        L += ["---", ""]
    return L


def tail():
    L = ["# REFERENCES", ""]
    L += [f"[{i}]  {r}" + "\n" for i, r in enumerate(REFERENCES, 1)]
    L += ["---", "", "# APPENDIX 1", "",
          "**SOURCE CODE — THE CORE AUDIT AND VERIFICATION PIPELINE**", "",
          "Insert the listings from the accompanying `APPENDIX1_CODE.txt` here, in Consolas 8 pt, "
          "single spaced. Precede them with this paragraph:", "",
          "The listings below are the parts of AURA that implement the mechanism described in "
          "Chapter 4: the relay that lets the browser make the model call, the verification engine "
          "that decides what may be reported, the materiality gate, and the aggregation of measured "
          "findings. They are reproduced from the repository without modification; the file and line "
          "range is given above each listing. Supporting modules — evidence collection, prompt "
          "construction, interpretation, the HTTP API and the extension interface — are omitted "
          "for length.", "",
          "The listings, in order:", ""]
    for rel, start, end, heading in APPENDIX_1_LISTINGS:
        L.append(f"- {heading}  —  `{rel}`")
    L += ["", "---", "", "# APPENDIX 2", "", "**OUTPUT — RUNNING AN AUDIT WITH AURA**", "",
          "AURA is published through the Microsoft Edge Add-ons store and its analysis service runs "
          "publicly at aura-api-vs7e.onrender.com. The steps below are the complete user workflow, "
          "from installation to acting on a finding.", ""]
    for label, text in APPENDIX_2_STEPS:
        L += [f"**{label}**", "", text, ""]
    L += ["**WHAT THE SCAN REPORTS**", "",
          "Each finding is presented with its severity, its category, the verdict the verification "
          "engine assigned, and a one-sentence statement of the problem. The verdict is the part that "
          "distinguishes AURA's output: Confirmed problem means the collected evidence directly "
          "supports the claim, Potential problem that it is consistent with the evidence without "
          "being proved by it, and Needs review that the evidence was insufficient to decide. A claim "
          "the evidence contradicted was discarded before this list was produced and is never shown.",
          "",
          "Where the AI provider is unavailable, rate-limited or refuses the request, the scan still "
          "completes and reports the findings that require no model — accessibility violations, "
          "runtime errors, failed requests and non-responsive controls — and states explicitly "
          "that AI analysis did not run. An empty result is never presented as an absence of problems.",
          ""]
    return L


def appendix_code():
    out = ["APPENDIX 1 — SOURCE CODE: THE CORE AUDIT AND VERIFICATION PIPELINE",
           "Set in Consolas 8 pt, single spaced, left aligned. Keep the sub-headings.", "", ""]
    for rel, start, end, heading in APPENDIX_1_LISTINGS:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        last = len(lines) if end is None else end
        rng = "complete file" if (start, last) == (1, len(lines)) else f"lines {start}-{last}"
        out += [heading, f"{rel}  ({rng})", ""]
        out += [ln.rstrip() for ln in lines[start - 1:last]]
        out += ["", ""]
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    md = PREAMBLE + "\n".join(front_matter() + chapters() + tail()) + "\n"
    out_md = ROOT / "report" / "AURA_Report_Manuscript.md"
    out_md.write_text(md, encoding="utf-8")

    code = "\n".join(appendix_code()) + "\n"
    out_code = ROOT / "report" / "APPENDIX1_CODE.txt"
    out_code.write_text(code, encoding="utf-8")

    words = len(md.split())
    print(f"wrote {out_md.relative_to(ROOT)}  ({len(md) // 1024} KB, ~{words:,} words)")
    print(f"wrote {out_code.relative_to(ROOT)}  ({len(code) // 1024} KB, "
          f"{len(code.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
