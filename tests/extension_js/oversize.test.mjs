// A provider that refuses a request for its size must not be sent the same request again.
//
// Bug (fixed): Groq's refusal reads "...please reduce your message size and try again", and
// worthRetrying() matched the phrase "try again", so AURA resent the identical oversized request and
// spent a second call against the same per-minute allowance for a guaranteed second refusal. The retry
// now drops the screenshot instead, which is the only thing that makes the request meaningfully
// smaller, and a scan that would have had no AI analysis gets a text-only one.
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = readFileSync(join(ROOT, "extension", "sidepanel", "providers.js"), "utf8");

// providers.js reaches for fetch and chrome at import time in a browser; here only the two decision
// functions matter, so they are lifted out and evaluated on their own.
function lift(name) {
  const at = SRC.indexOf(`function ${name}(`);
  assert.notEqual(at, -1, `${name} is not defined in providers.js`);
  let depth = 0, i = SRC.indexOf("{", at);
  const start = i;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "{") depth++;
    else if (SRC[i] === "}" && --depth === 0) break;
  }
  return SRC.slice(at, i + 1);
}

const { tooLarge, worthRetrying } = (new Function(
  `${lift("tooLarge")}\n${lift("worthRetrying")}\nreturn { tooLarge, worthRetrying };`))();

const GROQ_413 = "The request was larger than Groq accepts. Request too large for model "
  + "`qwen/qwen3.8-27b` in organization `org_x` service tier `on_demand` on input tokens per minute "
  + "(ITPM): Limit 7000, Requested 7016, please reduce your message size and try again.";

test("Groq's over-size refusal is recognised as over-size", () => {
  assert.equal(tooLarge({ status: 413, message: GROQ_413 }), true);
});

test("it is recognised from the message even when the status is not 413", () => {
  assert.equal(tooLarge({ status: 400, message: GROQ_413 }), true);
  assert.equal(tooLarge({ status: 429, message: "Rate limit reached for input tokens per minute" }), true);
});

test("an over-size refusal is never retried unchanged, despite saying 'try again'", () => {
  assert.match(GROQ_413, /try again/, "the refusal really does contain the phrase that caused the bug");
  assert.equal(worthRetrying({ status: 413, message: GROQ_413 }), false);
});

test("the conditions that do pass on their own are still retried", () => {
  assert.equal(worthRetrying({ status: 429, message: "Rate limit reached. Please try again in 2s" }), true);
  assert.equal(worthRetrying({ status: 503, message: "overloaded" }), true);
  assert.equal(worthRetrying({ status: 0, message: "network" }), true);
  assert.equal(worthRetrying({ status: 200, message: "high demand, usually temporary" }), true);
});

test("a rejected key and an unknown model are still never retried", () => {
  assert.equal(worthRetrying({ status: 401, message: "Invalid API Key" }), false);
  assert.equal(worthRetrying({ status: 404, message: "model not found" }), false);
});

test("callProvider drops the image on an over-size refusal rather than resending it", () => {
  const body = SRC.slice(SRC.indexOf("export async function callProvider"));
  assert.match(body, /if \(tooLarge\(e\)\) \{[\s\S]*?args\.image = null;/,
    "the over-size branch must clear the image before trying again");
  assert.match(body, /if \(!args\.image\) throw e;/,
    "with no image left to drop there is nothing smaller to send, so it must give up");
  assert.match(body, /image_dropped: droppedImage/,
    "the result must record that the model answered without seeing the page");
});
