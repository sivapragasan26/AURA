// Per-finding screenshot crops, made here in the browser.
//
// The capture taken during the scan never leaves this browser, so the cropping happens here: the part of
// the page a finding is about, with the element boxed and everything else dimmed, so the eye goes straight
// to the problem. This is the same treatment the engine applies in aura/api/shots.py, kept deliberately
// identical so a self-hosted server and the hosted service show a person the same image.
//
// A finding whose element has no recorded geometry - a page-level problem, or a target AURA could not
// match - has no region to show, and the caller is told so rather than being handed the whole page as if
// it were the answer.

const PAD = 28;          // breathing room around the element, in capture pixels
const MIN_SIDE = 180;    // never return a sliver
const MAX_SIDE = 1400;   // keep the image small enough to show instantly
const BORDER = 4;
const BORDER_COLOR = "rgb(124, 58, 237)";   // the same violet the in-page highlight uses
const SHADE = "rgba(124, 58, 237, 0.149)";
const DIM = "rgba(14, 10, 30, 0.431)";

export class NoShot extends Error {}

function boxesOf(finding) {
  const target = (finding && finding.target) || {};
  return (target.boxes || [])
    .map((b) => ({ x: Number(b.x) || 0, y: Number(b.y) || 0, width: Number(b.width) || 0, height: Number(b.height) || 0 }))
    .filter((b) => b.width > 0 && b.height > 0);
}

function badge(ctx, x, y, label) {
  const size = 20;
  const left = Math.max(0, x - 2);
  const top = Math.max(0, y - size - 2);
  ctx.fillStyle = "rgba(124, 58, 237, 0.92)";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
  ctx.lineWidth = 2;
  ctx.fillRect(left, top, size, size);
  ctx.strokeRect(left, top, size, size);
  ctx.fillStyle = "#fff";
  ctx.font = "600 13px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, left + size / 2, top + size / 2 + 1);
}

/**
 * A blob URL for the part of the capture this finding is about.
 *
 * @param {{base64: string, width: number, height: number}} capture the scan's capture, still in memory
 * @param {object} finding the finding from the audit view (its target.boxes carry the geometry)
 * @param {number} [viewportWidth] the viewport recorded for the scan, to recover the device pixel ratio
 * @throws {NoShot} when there is no capture or no recorded geometry for this finding
 */
export async function cropFinding(capture, finding, viewportWidth) {
  if (!capture || !capture.base64) {
    throw new NoShot("No screenshot was kept for this scan. Scan the page again to capture one.");
  }
  const boxes = boxesOf(finding);
  if (!boxes.length) {
    throw new NoShot("AURA has no part of the screenshot for this one: the capture covers what was on "
      + "screen during the scan, and this sits outside it or has no recorded position.");
  }

  const bmp = await createImageBitmap(await (await fetch(`data:image/png;base64,${capture.base64}`)).blob());
  try {
    // Boxes are in CSS pixels; the capture may be at a higher device pixel ratio. Comparing the capture's
    // width with the viewport recorded for the scan recovers the ratio without the page reporting it.
    let ratio = 1;
    if (viewportWidth > 0) {
      const guess = bmp.width / viewportWidth;
      if (guess >= 0.5 && guess <= 4) ratio = guess;
    }
    const scaled = boxes.map((b) => ({ x: b.x * ratio, y: b.y * ratio, width: b.width * ratio, height: b.height * ratio }));
    const left = Math.min(...scaled.map((b) => b.x));
    const top = Math.min(...scaled.map((b) => b.y));
    const right = Math.max(...scaled.map((b) => b.x + b.width));
    const bottom = Math.max(...scaled.map((b) => b.y + b.height));

    let cropL = Math.max(0, Math.round(left - PAD));
    let cropT = Math.max(0, Math.round(top - PAD));
    let cropR = Math.min(bmp.width, Math.round(right + PAD));
    let cropB = Math.min(bmp.height, Math.round(bottom + PAD));
    if (cropR - cropL < MIN_SIDE) {
      const grow = Math.floor((MIN_SIDE - (cropR - cropL)) / 2);
      cropL = Math.max(0, cropL - grow);
      cropR = Math.min(bmp.width, cropR + grow);
    }
    if (cropB - cropT < MIN_SIDE) {
      const grow = Math.floor((MIN_SIDE - (cropB - cropT)) / 2);
      cropT = Math.max(0, cropT - grow);
      cropB = Math.min(bmp.height, cropB + grow);
    }
    if (cropR <= cropL || cropB <= cropT) {
      throw new NoShot("This finding sits outside the screenshot taken during the scan.");
    }

    const w = cropR - cropL;
    const h = cropB - cropT;
    const canvas = new OffscreenCanvas(w, h);
    const ctx = canvas.getContext("2d");
    ctx.drawImage(bmp, cropL, cropT, w, h, 0, 0, w, h);

    const local = scaled.map((b) => ({ x: b.x - cropL, y: b.y - cropT, width: b.width, height: b.height }));

    // Dim everything except the marked areas: fill the whole crop, then punch the boxes back out.
    ctx.save();
    ctx.fillStyle = DIM;
    ctx.beginPath();
    ctx.rect(0, 0, w, h);
    for (const b of local) ctx.rect(b.x, b.y, b.width, b.height);
    ctx.fill("evenodd");
    ctx.restore();

    local.forEach((b, i) => {
      ctx.fillStyle = SHADE;
      ctx.fillRect(b.x, b.y, b.width, b.height);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.86)";
      ctx.lineWidth = BORDER + 3;
      ctx.strokeRect(b.x - 1, b.y - 1, b.width + 2, b.height + 2);
      ctx.strokeStyle = BORDER_COLOR;
      ctx.lineWidth = BORDER;
      ctx.strokeRect(b.x, b.y, b.width, b.height);
      if (local.length > 1) badge(ctx, b.x, b.y, String(i + 1));
    });

    let out = canvas;
    const longest = Math.max(w, h);
    if (longest > MAX_SIDE) {
      const factor = MAX_SIDE / longest;
      out = new OffscreenCanvas(Math.round(w * factor), Math.round(h * factor));
      out.getContext("2d").drawImage(canvas, 0, 0, w, h, 0, 0, out.width, out.height);
    }
    return URL.createObjectURL(await out.convertToBlob({ type: "image/png" }));
  } finally {
    bmp.close();
  }
}
