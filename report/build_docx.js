/*
 * Renders report/build/content.json into the project report .docx.
 *
 * The builder holds no prose of its own beyond the fixed front-matter wording taken from the college
 * template, so correcting the report means editing content_part1.py or content_part2.py and rebuilding.
 *
 *   node build_docx.js [output.docx]
 *
 * Page numbers in the contents and the lists of figures and tables come from build/page_numbers.json,
 * which is produced by paginate.py from a first pass of this build. Run the build twice: once to lay
 * the document out, once with the real numbers.
 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, PageBreak, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, WidthType, ShadingType, BorderStyle, VerticalAlign,
  Footer, PageNumber, NumberFormat, LevelFormat, PositionalTab, PositionalTabAlignment,
  PositionalTabLeader, convertInchesToTwip,
} = require("docx");

const BUILD = __dirname + path.sep + "build";
const FIGDIR = __dirname + path.sep + "figures";
const data = JSON.parse(fs.readFileSync(BUILD + path.sep + "content.json", "utf8"));
const PAGES = data.page_numbers || {};

const SERIF = "Times New Roman";
const MONO = "Consolas";
const CONTENT_DXA = 8666;          // A4 width 11906 less a 1.25in left and 1.0in right margin
const IMG_MAX_PT = 430;            // the same width expressed in points, for ImageRun
const FIG_CAPTIONS = [];           // collected while rendering, for the list of figures
const TBL_CAPTIONS = [];

const page = (key) => (PAGES[key] === undefined ? "" : String(PAGES[key]));

/* ------------------------------------------------------------------ paragraph helpers */

function body(text, opts = {}) {
  return new Paragraph({
    alignment: opts.alignment || AlignmentType.JUSTIFIED,
    spacing: { line: 360, after: opts.after === undefined ? 160 : opts.after },
    indent: opts.indent || { firstLine: convertInchesToTwip(0.3) },
    children: [new TextRun({ text, font: SERIF, size: 24 })],
  });
}

function centered(text, opts = {}) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { line: opts.line || 360, before: opts.before || 0, after: opts.after === undefined ? 120 : opts.after },
    children: [new TextRun({
      text, font: SERIF, size: opts.size || 24, bold: !!opts.bold,
      underline: opts.underline ? {} : undefined, allCaps: !!opts.caps,
    })],
  });
}

function blank(n) {
  const out = [];
  for (let i = 0; i < (n || 1); i++) out.push(new Paragraph({ children: [] }));
  return out;
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function frontHeading(text) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 280, line: 360 },
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text, font: SERIF, size: 28, bold: true })],
  });
}

function chapterHeading(number, title) {
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 160, line: 360 },
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: "CHAPTER " + number, font: SERIF, size: 28, bold: true })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 320, line: 360 },
      children: [new TextRun({ text: title, font: SERIF, size: 28, bold: true })],
    }),
  ];
}

function sectionHeading(number, title, level) {
  return new Paragraph({
    spacing: { before: 240, after: 160, line: 360 },
    heading: level === 3 ? HeadingLevel.HEADING_3 : HeadingLevel.HEADING_2,
    children: [new TextRun({
      text: number + "  " + title, font: SERIF, size: level === 3 ? 24 : 26, bold: true,
    })],
  });
}

function bulletList(items) {
  return items.map((t) => new Paragraph({
    numbering: { reference: "aura-bullets", level: 0 },
    alignment: AlignmentType.JUSTIFIED,
    spacing: { line: 360, after: 120 },
    children: [new TextRun({ text: t, font: SERIF, size: 24 })],
  }));
}

/* ------------------------------------------------------------------ figures and tables */

function figure(spec) {
  const file = FIGDIR + path.sep + spec.file;
  const size = data.figure_sizes[spec.file];
  if (!size) throw new Error("no recorded size for figure " + spec.file);
  const w = Math.min(IMG_MAX_PT, size[0] * 0.62);
  const h = w * (size[1] / size[0]);
  FIG_CAPTIONS.push({ number: spec.number, caption: spec.caption });
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 240, after: 120 },
      children: [new ImageRun({
        type: "png", data: fs.readFileSync(file), transformation: { width: w, height: h },
      })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 280 },
      children: [new TextRun({
        text: "Figure " + spec.number + "  " + spec.caption, font: SERIF, size: 22, bold: true,
      })],
    }),
  ];
}

function cellText(text, opts = {}) {
  return new Paragraph({
    alignment: opts.alignment || AlignmentType.LEFT,
    spacing: { line: 240, before: 40, after: 40 },
    children: [new TextRun({ text: String(text), font: SERIF, size: 21, bold: !!opts.bold })],
  });
}

function dataTable(spec) {
  const widths = spec.widths.slice();
  const scale = CONTENT_DXA / widths.reduce((a, b) => a + b, 0);
  const cols = widths.map((w) => Math.round(w * scale));
  TBL_CAPTIONS.push({ number: spec.number, caption: spec.caption });

  const header = new TableRow({
    tableHeader: true,
    children: spec.headers.map((h, i) => new TableCell({
      width: { size: cols[i], type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill: "D9E2F3", color: "auto" },
      verticalAlign: VerticalAlign.CENTER,
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      children: [cellText(h, { bold: true, alignment: AlignmentType.CENTER })],
    })),
  });

  const rows = spec.rows.map((r) => new TableRow({
    children: r.map((c, i) => new TableCell({
      width: { size: cols[i], type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      children: [cellText(c, { alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.LEFT })],
    })),
  }));

  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 240, after: 120 },
      children: [new TextRun({
        text: "Table " + spec.number + "  " + spec.caption, font: SERIF, size: 22, bold: true,
      })],
    }),
    new Table({ columnWidths: cols, width: { size: CONTENT_DXA, type: WidthType.DXA },
                rows: [header].concat(rows) }),
    new Paragraph({ spacing: { after: 240 }, children: [] }),
  ];
}

function plainTable(cols, rows, opts = {}) {
  const scale = CONTENT_DXA / cols.reduce((a, b) => a + b, 0);
  const w = cols.map((c) => Math.round(c * scale));
  const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const borders = opts.borderless
    ? { top: none, bottom: none, left: none, right: none,
        insideHorizontal: none, insideVertical: none }
    : undefined;
  return new Table({
    columnWidths: w,
    width: { size: CONTENT_DXA, type: WidthType.DXA },
    borders,
    rows: rows.map((r) => new TableRow({
      children: r.map((c, i) => new TableCell({
        width: { size: w[i], type: WidthType.DXA },
        borders: opts.borderless ? borders : undefined,
        verticalAlign: VerticalAlign.CENTER,
        margins: { top: 50, bottom: 50, left: 90, right: 90 },
        children: [typeof c === "object" && c !== null
          ? cellText(c.text, c)
          : cellText(c, { alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.LEFT })],
      })),
    })),
  });
}

/* ------------------------------------------------------------------ front matter */

function titlePage() {
  const m = data.meta;
  const out = [];
  out.push(centered(m.title, { bold: true, size: 32, after: 240, line: 300 }));
  out.push(...blank(1));
  out.push(centered(m.report_kind, { bold: true, size: 28 }));
  out.push(...blank(1));
  out.push(centered("Submitted by", { size: 24 }));
  out.push(...blank(1));
  out.push(plainTable([4400, 4600], m.students.map(
    (s) => [{ text: s[0], bold: true, alignment: AlignmentType.CENTER },
            { text: "REGISTER NO: " + s[1], bold: true, alignment: AlignmentType.CENTER }]),
    { borderless: true }));
  out.push(...blank(1));
  out.push(centered("Under the guidance of", { size: 24, after: 60 }));
  out.push(centered(m.guide + ",", { bold: true, size: 24, after: 60 }));
  out.push(centered(m.guide_title, { size: 24, after: 60 }));
  out.push(centered(m.department, { size: 24 }));
  out.push(...blank(1));
  out.push(centered("in partial fulfillment for the award of the degree", { size: 24, after: 60 }));
  out.push(centered("of", { size: 24, after: 60 }));
  out.push(centered(m.degree, { bold: true, size: 28, after: 60 }));
  out.push(centered("in", { size: 24 }));
  out.push(centered("DEPARTMENT OF ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING",
                    { bold: true, size: 24 }));
  out.push(...blank(1));
  out.push(centered(m.college, { bold: true, size: 26, after: 60 }));
  out.push(centered(m.college_place, { bold: true, size: 26, after: 60 }));
  out.push(centered(m.university, { bold: true, size: 26 }));
  out.push(...blank(1));
  out.push(centered(m.month_year, { bold: true, size: 26 }));
  out.push(pageBreak());
  return out;
}

function signatureBlock() {
  return plainTable([4500, 4500], [
    [{ text: "PROJECT GUIDE", bold: true }, { text: "HEAD OF THE DEPARTMENT", bold: true }],
    [{ text: data.meta.guide }, { text: data.meta.guide }],
    [{ text: data.meta.guide_title }, { text: data.meta.guide_title }],
    [{ text: data.meta.department_short }, { text: data.meta.department_short }],
  ], { borderless: true });
}

function studentList() {
  return data.meta.students.map(
    (s) => [{ text: s[0], bold: true, alignment: AlignmentType.CENTER },
            { text: s[1], bold: true, alignment: AlignmentType.CENTER }]);
}

function certificatePage() {
  const m = data.meta;
  const names = m.students.map((s) => s[0] + " [REGISTER NO: " + s[1] + "]").join(", ");
  const out = [];
  out.push(centered("MANAKULA VINAYAGAR INSTITUTE OF TECHNOLOGY", { bold: true, size: 26, after: 60 }));
  out.push(centered("PONDICHERRY UNIVERSITY", { bold: true, size: 26 }));
  out.push(...blank(1));
  out.push(centered("DEPARTMENT OF ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING",
                    { bold: true, size: 24 }));
  out.push(...blank(1));
  out.push(frontHeading("BONAFIDE CERTIFICATE"));
  out.push(body("This is to certify that the project work entitled \"" + m.title + "\" is a Bonafide "
                + "work done by, " + names + " in partial fulfillment of the requirement for the award "
                + "of B.Tech Degree in Artificial Intelligence and Machine Learning by Pondicherry "
                + "University during the academic year " + m.academic_year + ".",
                { after: 400 }));
  out.push(...blank(2));
  out.push(signatureBlock());
  out.push(...blank(2));
  out.push(body("Viva-Voce Examination held on ................................................"
                + "..............................", { indent: { firstLine: 0 } }));
  out.push(...blank(2));
  out.push(plainTable([4500, 4500], [
    [{ text: "INTERNAL EXAMINER", bold: true }, { text: "EXTERNAL EXAMINER", bold: true }],
  ], { borderless: true }));
  out.push(pageBreak());
  return out;
}

function declarationPage() {
  const m = data.meta;
  const names = m.students.map((s) => s[0] + " \"Register No: " + s[1] + "\"").join(", ");
  const out = [];
  out.push(frontHeading("DECLARATION"));
  out.push(body("This is to certified that the Report \"" + m.title + "\" is a Bonafide record of "
                + "independent work done by " + names + " for the award of B.Tech Degree in Artificial "
                + "Intelligence and Machine Learning under the supervision of " + m.guide + ", "
                + "Certified further that the work reported herein does not from part of any thesis or "
                + "dissertation on the basis of which degree or award was conferred earlier.",
                { after: 400 }));
  out.push(...blank(1));
  m.students.forEach((s, i) => out.push(new Paragraph({
    spacing: { line: 360, after: 80 },
    indent: { left: convertInchesToTwip(0.6) },
    children: [new TextRun({ text: (i + 1) + ".  " + s[0], font: SERIF, size: 24, bold: true })],
  })));
  out.push(...blank(2));
  out.push(signatureBlock());
  out.push(pageBreak());
  return out;
}

function acknowledgementPage() {
  const out = [frontHeading("ACKNOWLEDGEMENT")];
  data.acknowledgement.forEach((p) => out.push(body(p)));
  out.push(...blank(1));
  out.push(plainTable([4500, 4500], studentList(), { borderless: true }));
  out.push(pageBreak());
  return out;
}

function abstractPage() {
  const out = [frontHeading("ABSTRACT")];
  data.abstract.forEach((p) => out.push(body(p)));
  out.push(pageBreak());
  return out;
}

function contentsPage() {
  const rows = [[
    { text: "CHAPTER NO.", bold: true, alignment: AlignmentType.CENTER },
    { text: "TITLE", bold: true, alignment: AlignmentType.CENTER },
    { text: "PAGE NO.", bold: true, alignment: AlignmentType.CENTER },
  ]];
  const front = [
    ["", "ACKNOWLEDGEMENT", page("ACKNOWLEDGEMENT")],
    ["", "ABSTRACT", page("ABSTRACT")],
    ["", "LIST OF FIGURES", page("LIST OF FIGURES")],
    ["", "LIST OF TABLES", page("LIST OF TABLES")],
    ["", "LIST OF SYMBOLS", page("LIST OF SYMBOLS")],
    ["", "LIST OF ABBREVIATIONS", page("LIST OF ABBREVIATIONS")],
  ];
  front.forEach((r) => rows.push([
    { text: r[0], alignment: AlignmentType.CENTER },
    { text: r[1], bold: true },
    { text: r[2], alignment: AlignmentType.CENTER },
  ]));

  data.chapters.forEach((ch) => {
    rows.push([
      { text: String(ch.number), bold: true, alignment: AlignmentType.CENTER },
      { text: ch.title, bold: true },
      { text: page("CHAPTER " + ch.number), alignment: AlignmentType.CENTER },
    ]);
    ch.sections.forEach((s) => rows.push([
      { text: s.number, alignment: AlignmentType.CENTER },
      { text: titleCase(s.title) },
      { text: page(s.number), alignment: AlignmentType.CENTER },
    ]));
  });

  [["REFERENCES", "REFERENCES"], ["APPENDIX 1", "APPENDIX 1"], ["APPENDIX 2", "APPENDIX 2"]]
    .forEach((r) => rows.push([
      { text: "", alignment: AlignmentType.CENTER },
      { text: r[1], bold: true },
      { text: page(r[0]), alignment: AlignmentType.CENTER },
    ]));

  return [frontHeading("TABLE OF CONTENTS"), plainTable([1700, 5800, 1500], rows), pageBreak()];
}

function titleCase(s) {
  const small = new Set(["and", "of", "the", "for", "in", "to", "with", "on", "a", "an", "or"]);
  return s.toLowerCase().split(" ").map((w, i) => {
    if (/^(ui|ux|ai|aura|llm|vlm|wcag)\b/i.test(w)) return w.toUpperCase();
    if (i > 0 && small.has(w)) return w;
    return w.charAt(0).toUpperCase() + w.slice(1);
  }).join(" ");
}

function captionListPage(heading, numberHeader, captions, key) {
  const rows = [[
    { text: numberHeader, bold: true, alignment: AlignmentType.CENTER },
    { text: "TITLE", bold: true, alignment: AlignmentType.CENTER },
    { text: "PAGE NO.", bold: true, alignment: AlignmentType.CENTER },
  ]];
  captions.forEach((c) => rows.push([
    { text: c.number, alignment: AlignmentType.CENTER },
    { text: c.caption },
    { text: page(key + " " + c.number), alignment: AlignmentType.CENTER },
  ]));
  return [frontHeading(heading), plainTable([1700, 5800, 1500], rows), pageBreak()];
}

function twoColumnListPage(heading, leftHeader, rightHeader, pairs) {
  const rows = [[
    { text: leftHeader, bold: true, alignment: AlignmentType.CENTER },
    { text: rightHeader, bold: true, alignment: AlignmentType.CENTER },
  ]];
  pairs.forEach((p) => rows.push([
    { text: p[0], bold: true, alignment: AlignmentType.CENTER }, { text: p[1] },
  ]));
  return [frontHeading(heading), plainTable([2200, 6800], rows), pageBreak()];
}

/* ------------------------------------------------------------------ chapters */

function renderBlocks(blocks) {
  const out = [];
  blocks.forEach((b) => {
    if (b.p !== undefined) out.push(body(b.p));
    else if (b.bullets) out.push(...bulletList(b.bullets));
    else if (b.figure) out.push(...figure(b.figure));
    else if (b.table) out.push(...dataTable(b.table));
    else throw new Error("unknown block: " + JSON.stringify(b).slice(0, 80));
  });
  return out;
}

function renderChapter(ch) {
  const out = chapterHeading(ch.number, ch.title);
  ch.sections.forEach((s) => {
    out.push(sectionHeading(s.number, s.title, s.level || 2));
    out.push(...renderBlocks(s.blocks));
  });
  out.push(pageBreak());
  return out;
}

function referencesPage() {
  const out = [frontHeading("REFERENCES")];
  data.references.forEach((r, i) => out.push(new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    spacing: { line: 300, after: 140 },
    indent: { left: convertInchesToTwip(0.45), hanging: convertInchesToTwip(0.45) },
    children: [new TextRun({ text: "[" + (i + 1) + "]  " + r, font: SERIF, size: 23 })],
  })));
  out.push(pageBreak());
  return out;
}

function codeLines(lines) {
  return lines.map((ln) => new Paragraph({
    spacing: { line: 200, after: 0 },
    alignment: AlignmentType.LEFT,
    children: [new TextRun({ text: ln.length ? ln : " ", font: MONO, size: 16 })],
  }));
}

function appendix1Page() {
  const out = [frontHeading("APPENDIX 1")];
  out.push(centered("SOURCE CODE - THE CORE AUDIT AND VERIFICATION PIPELINE",
                    { bold: true, size: 24, after: 240 }));
  out.push(body("The listings below are the parts of AURA that implement the mechanism described in "
                + "Chapter 4: the relay that lets the browser make the model call, the verification "
                + "engine that decides what may be reported, the materiality gate, and the aggregation "
                + "of measured findings. They are reproduced from the repository without modification; "
                + "the file and line range is given above each listing. Supporting modules - evidence "
                + "collection, prompt construction, interpretation, the HTTP API and the extension "
                + "interface - are omitted for length."));
  data.appendix1.forEach((l) => {
    out.push(new Paragraph({
      spacing: { before: 300, after: 60 },
      heading: HeadingLevel.HEADING_3,
      children: [new TextRun({ text: l.heading, font: SERIF, size: 24, bold: true })],
    }));
    out.push(new Paragraph({
      spacing: { after: 140 },
      children: [new TextRun({ text: l.file + "  (" + l.range + ")", font: MONO, size: 18,
                               italics: true })],
    }));
    out.push(...codeLines(l.lines));
  });
  out.push(pageBreak());
  return out;
}

function appendix2Page() {
  const out = [frontHeading("APPENDIX 2")];
  out.push(centered("OUTPUT - RUNNING AN AUDIT WITH AURA", { bold: true, size: 24, after: 240 }));
  out.push(body("AURA is published through the Microsoft Edge Add-ons store and its analysis service "
                + "runs publicly at aura-api-vs7e.onrender.com. The steps below are the complete user "
                + "workflow, from installation to acting on a finding."));
  data.appendix2_steps.forEach((s) => {
    out.push(new Paragraph({
      spacing: { before: 220, after: 60 },
      children: [new TextRun({ text: s[0], font: SERIF, size: 24, bold: true, underline: {} })],
    }));
    out.push(body(s[1], { indent: { firstLine: 0 } }));
  });
  out.push(...blank(1));
  out.push(centered("WHAT THE SCAN REPORTS", { bold: true, size: 24, before: 240, after: 160 }));
  out.push(body("Each finding is presented with its severity, its category, the verdict the "
                + "verification engine assigned, and a one-sentence statement of the problem. The "
                + "verdict is the part that distinguishes AURA's output: Confirmed problem means the "
                + "collected evidence directly supports the claim, Potential problem that it is "
                + "consistent with the evidence without being proved by it, and Needs review that the "
                + "evidence was insufficient to decide. A claim the evidence contradicted was discarded "
                + "before this list was produced and is never shown."));
  out.push(body("Where the AI provider is unavailable, rate-limited or refuses the request, the scan "
                + "still completes and reports the findings that require no model - accessibility "
                + "violations, runtime errors, failed requests and non-responsive controls - and states "
                + "explicitly that AI analysis did not run. An empty result is never presented as an "
                + "absence of problems."));
  return out;
}

/* ------------------------------------------------------------------ assembly */

function footerFor(format) {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], font: SERIF, size: 22 })],
    })],
  });
}

function pageProps(format, start) {
  return {
    page: {
      size: { width: 11906, height: 16838 },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1800 },
      pageNumbers: { start, formatType: format },
    },
  };
}

function main() {
  const out = process.argv[2] || (BUILD + path.sep + "AURA_Project_Report.docx");

  // Chapters are rendered before the front matter is assembled, because rendering is what collects
  // the figure and table captions that the lists of figures and tables are built from.
  const chapterChildren = [];
  data.chapters.forEach((ch) => chapterChildren.push(...renderChapter(ch)));
  chapterChildren.push(...referencesPage());
  chapterChildren.push(...appendix1Page());
  chapterChildren.push(...appendix2Page());

  const front = []
    .concat(titlePage())
    .concat(certificatePage())
    .concat(declarationPage())
    .concat(acknowledgementPage())
    .concat(abstractPage())
    .concat(contentsPage())
    .concat(captionListPage("LIST OF FIGURES", "FIGURE NO.", FIG_CAPTIONS, "FIGURE"))
    .concat(captionListPage("LIST OF TABLES", "TABLE NO.", TBL_CAPTIONS, "TABLE"))
    .concat(twoColumnListPage("LIST OF SYMBOLS", "SYMBOL", "DESCRIPTION", data.symbols))
    .concat(twoColumnListPage("LIST OF ABBREVIATIONS", "ABBREVIATION", "EXPANSION",
                              data.abbreviations));

  const bodyStart = PAGES["__body_start__"] || 1;

  const doc = new Document({
    creator: data.meta.students.map((s) => s[0]).join(", "),
    title: data.meta.title,
    description: "Project report, " + data.meta.department + ", " + data.meta.month_year,
    styles: {
      default: {
        document: { run: { font: SERIF, size: 24 }, paragraph: { spacing: { line: 360 } } },
      },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { font: SERIF, size: 28, bold: true, color: "000000" },
          paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 240, after: 240 } } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { font: SERIF, size: 26, bold: true, color: "000000" },
          paragraph: { spacing: { before: 240, after: 160 } } },
        { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { font: SERIF, size: 24, bold: true, color: "000000" },
          paragraph: { spacing: { before: 200, after: 140 } } },
      ],
    },
    numbering: {
      config: [{
        reference: "aura-bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: convertInchesToTwip(0.45),
                                         hanging: convertInchesToTwip(0.22) } } },
        }],
      }],
    },
    sections: [
      { properties: pageProps(NumberFormat.LOWER_ROMAN, 1),
        footers: { default: footerFor() }, children: front },
      { properties: pageProps(NumberFormat.DECIMAL, bodyStart),
        footers: { default: footerFor() }, children: chapterChildren },
    ],
  });

  Packer.toBuffer(doc).then((buf) => {
    fs.writeFileSync(out, buf);
    console.log("wrote " + out + "  (" + (buf.length / 1024).toFixed(0) + " KB)");
    console.log("  front matter paragraphs: " + front.length
                + "   body paragraphs: " + chapterChildren.length);
    console.log("  figures listed: " + FIG_CAPTIONS.length
                + "   tables listed: " + TBL_CAPTIONS.length);
    console.log("  body page numbering starts at: " + bodyStart
                + (PAGES["__body_start__"] ? "" : "  (first pass - run paginate.py then rebuild)"));
  }).catch((e) => { console.error(e); process.exit(1); });
}

main();
