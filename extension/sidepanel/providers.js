// The AI call, made here in the browser with the user's own key.
//
// AURA's server builds the prompt and verifies the answer, but it never holds a provider credential: the
// key you enter in Settings stays in this extension's storage and goes only to the provider you chose.
// Nothing here decides anything about the finding itself — the prompt comes from the server, the raw
// response goes straight back to it, and the verification that follows is unchanged.
//
// Each provider is described in one place: where to send the request, how to authorise it, how to put the
// prompt and the screenshot into its own format, and where its answer's text sits in the reply. Whether a
// model can be shown an image is NOT decided here; the server reports it (model_capabilities), so there is
// one such table and it is the one the tests cover.

export class ProviderCallError extends Error {
  constructor(message, { status = 0, retryAfter = null, body = null } = {}) {
    super(message);
    this.status = status;          // the provider's HTTP status, 0 when the request never arrived
    this.retryAfter = retryAfter;  // seconds, when the provider said so
    this.body = body;
  }
}

const dataUrl = (b64, mime) => `data:${mime || "image/png"};base64,${b64}`;

export const PROVIDERS = {
  groq: {
    label: "Groq",
    origin: "https://api.groq.com",
    keyHint: "Starts with gsk_ · console.groq.com/keys",
    url: () => "https://api.groq.com/openai/v1/chat/completions",
    headers: (key) => ({ "Content-Type": "application/json", Authorization: `Bearer ${key}` }),
    body: ({ model, prompt, image, mime, jsonMode }) => {
      const content = [];
      if (image) content.push({ type: "image_url", image_url: { url: dataUrl(image, mime) } });
      content.push({ type: "text", text: prompt });
      const payload = {
        model,
        messages: [{ role: "user", content }],
        max_completion_tokens: 8000,
        temperature: 0.2,
      };
      if (jsonMode) payload.response_format = { type: "json_object" };
      return payload;
    },
    text: (reply) => reply?.choices?.[0]?.message?.content || "",
    model: (reply) => reply?.model || null,
    check: () => ({ url: "https://api.groq.com/openai/v1/models", method: "GET" }),
  },

  openai: {
    label: "OpenAI",
    origin: "https://api.openai.com",
    keyHint: "Starts with sk- · platform.openai.com/api-keys",
    url: () => "https://api.openai.com/v1/chat/completions",
    headers: (key) => ({ "Content-Type": "application/json", Authorization: `Bearer ${key}` }),
    body: ({ model, prompt, image, mime, jsonMode }) => {
      const content = [];
      if (image) content.push({ type: "image_url", image_url: { url: dataUrl(image, mime) } });
      content.push({ type: "text", text: prompt });
      const payload = { model, messages: [{ role: "user", content }], temperature: 0.2 };
      if (jsonMode) payload.response_format = { type: "json_object" };
      return payload;
    },
    text: (reply) => reply?.choices?.[0]?.message?.content || "",
    model: (reply) => reply?.model || null,
    check: () => ({ url: "https://api.openai.com/v1/models", method: "GET" }),
  },

  gemini: {
    label: "Gemini",
    origin: "https://generativelanguage.googleapis.com",
    keyHint: "aistudio.google.com/apikey",
    // The key goes in a header, never in the URL: a URL can end up in a log or a referrer.
    url: (model) => `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`,
    headers: (key) => ({ "Content-Type": "application/json", "x-goog-api-key": key }),
    body: ({ model, prompt, image, mime, jsonMode }) => {
      const parts = [{ text: prompt }];
      if (image) parts.push({ inline_data: { mime_type: mime || "image/png", data: image } });
      const payload = { contents: [{ role: "user", parts }], generationConfig: { temperature: 0.2 } };
      if (jsonMode) payload.generationConfig.responseMimeType = "application/json";
      return payload;
    },
    text: (reply) => (reply?.candidates?.[0]?.content?.parts || []).map((p) => p.text || "").join(""),
    model: (reply) => reply?.modelVersion || null,
    check: (model) => ({ url: `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}`, method: "GET" }),
  },

  anthropic: {
    label: "Anthropic",
    origin: "https://api.anthropic.com",
    keyHint: "Starts with sk-ant- · console.anthropic.com/settings/keys",
    url: () => "https://api.anthropic.com/v1/messages",
    headers: (key) => ({
      "Content-Type": "application/json",
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
      // Without this, Anthropic refuses a request made from a browser extension's page.
      "anthropic-dangerous-direct-browser-access": "true",
    }),
    body: ({ model, prompt, image, mime }) => {
      const content = [];
      if (image) content.push({ type: "image", source: { type: "base64", media_type: mime || "image/png", data: image } });
      content.push({ type: "text", text: prompt });
      return { model, max_tokens: 8000, temperature: 0.2, messages: [{ role: "user", content }] };
    },
    text: (reply) => (reply?.content || []).map((b) => b.text || "").join(""),
    model: (reply) => reply?.model || null,
    check: () => ({ url: "https://api.anthropic.com/v1/models", method: "GET" }),
  },
};

export const PROVIDER_ORIGINS = Object.values(PROVIDERS).map((p) => p.origin);

export function callsProviderInBrowser(provider) {
  return Object.prototype.hasOwnProperty.call(PROVIDERS, provider);
}

// What the provider itself said went wrong, in words a person can act on. Never the key, and never a
// guess: when the provider sent no message, the status is all AURA claims to know.
function failureMessage(status, reply, label) {
  const stated = reply?.error?.message || reply?.error?.[0]?.message || reply?.message || "";
  if (status === 401 || status === 403) {
    return `${label} rejected the API key. Check the key in AURA's settings.` + (stated ? ` (${stated})` : "");
  }
  if (status === 404) return `${label} does not have that model available for this key.${stated ? ` (${stated})` : ""}`;
  if (status === 429) return `${label} rate limit reached.${stated ? ` ${stated}` : ""}`;
  if (status === 413) return `The request was larger than ${label} accepts.${stated ? ` ${stated}` : ""}`;
  if (stated) return `${label}: ${stated}`;
  return `${label} returned HTTP ${status}.`;
}

// Worth trying once more, or not. A free model under load answers "this model is currently experiencing
// high demand ... usually temporary" - seen on the first real Gemini call AURA ever made - and throwing
// that straight at the user wastes a scan that would have worked seconds later. A rejected key or an
// unknown model will never succeed on a second attempt and must not be retried.
function worthRetrying(error) {
  if (tooLarge(error)) return false;     // decided separately: the retry has to send less, not the same
  if ([429, 500, 502, 503, 504].includes(error.status)) return true;
  if (error.status === 0) return true;   // the request never arrived
  return /high demand|overload|temporar|try again|unavailable/i.test(error.message || "");
}

// The provider refused this request for its size rather than for the rate it arrived at. Groq says so
// with a 413 and names its input-tokens-per-minute limit - and tells you to "try again", which is why
// this has to be decided before worthRetrying's wording test sees it.
function tooLarge(error) {
  if (error.status === 413) return true;
  return /too large|reduce your message size|input tokens per minute|\bITPM\b/i.test(error.message || "");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function attemptCall(spec, { model, apiKey, prompt, image, mime, jsonMode, timeoutMs }) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(spec.url(model), {
      method: "POST",
      headers: spec.headers(apiKey),
      body: JSON.stringify(spec.body({ model, prompt, image, mime, jsonMode })),
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new ProviderCallError(
      e.name === "AbortError"
        ? `${spec.label} did not answer within ${Math.round(timeoutMs / 1000)}s.`
        : `Could not reach ${spec.label} from this browser. Check the connection and try again.`,
      { status: 0 });
  } finally {
    clearTimeout(timer);
  }

  let reply = null;
  const raw = await res.text();
  try { reply = JSON.parse(raw); } catch (_) { /* a non-JSON body is reported by status alone */ }
  if (!res.ok) {
    const retryAfter = Number(res.headers.get("retry-after")) || null;
    throw new ProviderCallError(failureMessage(res.status, reply, spec.label), { status: res.status, retryAfter });
  }
  const text = spec.text(reply);
  if (!text || !text.trim()) {
    // A reply with no text is not an empty answer: the model stopped for a reason it states, and the
    // reason is what the person needs to read.
    const stop = reply?.candidates?.[0]?.finishReason || reply?.promptFeedback?.blockReason
                 || reply?.choices?.[0]?.finish_reason || reply?.stop_reason;
    throw new ProviderCallError(
      stop ? `${spec.label} returned no text (${stop}).` : `${spec.label} returned an empty response.`,
      { status: res.status });
  }
  return { text, model: spec.model(reply) || model, status: res.status };
}

/**
 * Calls the chosen provider with the prompt the AURA server prepared.
 *
 * Returns { response, meta } where response is the model's raw text, exactly as received — parsing and
 * verification are the server's job. Throws ProviderCallError when the provider refused or was unreachable;
 * the caller reports that to the server, which records the scan as having no AI analysis rather than
 * pretending the model found nothing.
 *
 * One retry, for conditions that pass on their own. `onRetry` is told about it so the panel can say so
 * rather than appearing to hang. When the provider refused the request for its size, the retry drops the
 * screenshot instead of resending the same thing, and `onDropImage` is told so the panel can say that
 * the analysis it got was made without the picture.
 */
export async function callProvider({ provider, model, apiKey, prompt, image = null, mime = "image/png",
                                     jsonMode = true, timeoutMs = 180000, onRetry = null,
                                     onDropImage = null }) {
  const spec = PROVIDERS[provider];
  if (!spec) throw new ProviderCallError(`AURA cannot call '${provider}' from the browser.`);
  if (!apiKey) throw new ProviderCallError(`No ${spec.label} API key. Add one in AURA's settings.`, { status: 401 });

  const started = Date.now();
  const args = { model, apiKey, prompt, image, mime, jsonMode, timeoutMs };
  let droppedImage = false;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const got = await attemptCall(spec, args);
      return {
        response: got.text,
        meta: {
          http_status: got.status,
          actual_model: got.model,
          attempt_count: attempt,
          retry_count: attempt - 1,
          image_dropped: droppedImage,
          elapsed_ms: Date.now() - started,
        },
      };
    } catch (e) {
      const last = attempt === 2;
      if (last || !(e instanceof ProviderCallError)) throw e;
      // Too large is not a condition that passes on its own: sending the same request again spends a
      // second one against the same allowance for the same refusal. Send less instead - without the
      // screenshot - and only when there is a screenshot to drop.
      if (tooLarge(e)) {
        if (!args.image) throw e;
        args.image = null;
        droppedImage = true;
        if (onDropImage) onDropImage(e);
        continue;
      }
      if (!worthRetrying(e)) throw e;
      // The provider's own Retry-After wins, within reason; otherwise a short wait.
      const wait = Math.min(Math.max((e.retryAfter || 0) * 1000, 2500), 15000);
      if (onRetry) onRetry(e, wait);
      await sleep(wait);
    }
  }
  throw new ProviderCallError(`${spec.label} could not be reached.`);   // unreachable; the loop returns or throws
}


/**
 * Checks a key and model without running the model.
 *
 * Each provider offers a metadata endpoint for exactly this; AURA never spends a request on inference to
 * tell someone whether their key works. Returns { status, detail } and never throws.
 */
export async function checkProviderKey({ provider, model, apiKey }) {
  const spec = PROVIDERS[provider];
  if (!spec || !spec.check) return { status: "UNKNOWN", detail: "This provider has no check that avoids running the model." };
  if (!apiKey) return { status: "NOT_CONFIGURED", detail: `No ${spec.label} API key saved in AURA.` };
  const { url, method } = spec.check(model);
  let res;
  try {
    const headers = spec.headers(apiKey);
    delete headers["Content-Type"];
    res = await fetch(url, { method, headers });
  } catch (_) {
    return { status: "CONNECTION_FAILED", detail: `Could not reach ${spec.label} from this browser.` };
  }
  if (res.ok) return { status: "READY", detail: `${spec.label} accepted the key${model ? ` and knows '${model}'` : ""}.` };
  const body = await res.json().catch(() => null);
  const status = res.status === 401 || res.status === 403 ? "AUTH_INVALID"
    : res.status === 404 ? "MODEL_UNAVAILABLE"
    : res.status === 429 ? "RATE_LIMITED" : "UNKNOWN";
  return { status, detail: failureMessage(res.status, body, spec.label) };
}
