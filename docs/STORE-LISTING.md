# Chrome Web Store submission notes

Everything the listing form asks for, with the answers that match what the code actually does. Each
permission justification is the reason a reviewer needs; vague answers are the usual cause of a rejection.

## Listing

- **Name:** AURA — UI/UX Runtime Assurance
- **Short description (132 max):** Scan the page you are on for UI, UX, accessibility and runtime
  problems. Every finding is checked against the evidence.
- **Category:** Developer Tools
- **Language:** English
- **Privacy policy URL:** the hosted copy of [`docs/privacy.html`](privacy.html). Enable GitHub Pages for
  this repository (Settings → Pages → Deploy from branch → `main`, folder `/docs`) and the URL is
  `https://sivapragasan26.github.io/AURA/privacy.html`. A reviewer must be able to open it: do not point
  this at the Render service, whose free tier sleeps.
- **Support URL:** <https://github.com/sivapragasan26/AURA/issues>
- **Licence:** MIT ([LICENSE](../LICENSE)); axe-core keeps the MPL 2.0, see
  [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md)

### Detailed description

> AURA audits the page you are on and tells you what is wrong with it — in plain language, with the
> evidence behind every claim.
>
> Open the side panel, press Scan, and AURA collects what is actually there: the page's structure and
> computed styles, accessibility results from axe-core running in the page, errors the page raised, and
> requests that failed. Nothing is collected until you press Scan.
>
> Every finding is then checked independently against that evidence. A claim the evidence does not support
> is dropped rather than shown, and each finding says how confident AURA is and why. Highlight shows you
> the element on the page; Screenshot shows the problem cropped out of the capture with the element
> outlined; Explain describes the problem without jargon; Ask AURA answers questions about it.
>
> Bring your own AI key — Groq, OpenAI, Gemini or Anthropic — and your browser calls that provider
> directly. The key stays in the extension and the AURA service never receives it. Screenshots never
> leave your browser. You can also run AURA's server on your own machine and keep everything local.
>
> Free, no account, no tracking, no ads.

## Permission justifications

| Permission | Justification to submit |
|---|---|
| `activeTab` | AURA reads the page only in the tab the user is on, and only after they click the AURA toolbar icon on that tab. This is what lets the audit examine the page the user asked about without requesting access to any site in advance. There is no `<all_urls>` permission and no content script: nothing runs in any page until that click. |
| `scripting` | The audit runs three scripts in the scanned tab on demand: a DOM extraction script that reads structure, geometry and computed styles; axe-core, to produce the accessibility results; and a small agent that highlights an element when the user presses Highlight. All three are in the package — no remote code is fetched or executed. |
| `sidePanel` | The entire interface is a side panel, so the audit sits beside the page it is about rather than in a popup that closes. |
| `storage` | Holds the user's own settings: which AI provider and model to use, that provider's API key, and the address of the AURA server. The key is stored here precisely so it can go straight to the provider without passing through our service. |
| Host access to `https://aura-api.onrender.com/` | The AURA service that verifies findings against the collected evidence. |
| Host access to `http://127.0.0.1:8765/` and `http://localhost:8765/` | For users who run AURA's open-source server on their own machine instead, so no page data leaves their computer. |
| Host access to `api.groq.com`, `api.openai.com`, `generativelanguage.googleapis.com`, `api.anthropic.com` | The four AI providers a user can choose. The extension calls whichever one they picked with their own key, so the key never reaches our server. Only the chosen provider is ever contacted. |

## Data-use disclosures

Declare these; each one is accurate:

- **Website content** — collected. The structure and visible text of the page being scanned, needed to
  produce the findings. Not sold, not used for anything other than the audit the user asked for, not used
  for creditworthiness or lending.
- **Web history** — collected, in the narrow sense that the address and title of a scanned page are sent
  (with query strings and fragments stripped). Only for pages the user explicitly scans. Not a browsing
  history: AURA sees nothing unless Scan is pressed.
- **Personally identifiable information, authentication information, financial information, health
  information, personal communications, location, user activity** — not collected. Form field values,
  cookies and storage are excluded by the collector; there is no account and no analytics.

Certify: data is not sold to third parties; data is not used for purposes unrelated to the single purpose;
data is not used for creditworthiness or lending.

**Single purpose:** auditing the user's current page for UI, UX, accessibility and runtime problems.

## Remote code

Declare **no remote code**. The content security policy is `script-src 'self'`, axe-core is vendored in
`extension/vendor/axe.min.js` under the MPL 2.0 (see [`../THIRD-PARTY-NOTICES.md`](../THIRD-PARTY-NOTICES.md)),
and nothing is loaded from a CDN. `tests/test_extension_assets.py` fails if a remote `<script src>` ever
appears in the package.

## Artwork

```bash
python -m aura.tools.listing_art
```

Writes to `dist/listing/`, from a real scan of the Test Lab's realistic page - nothing is mocked up:

- `screenshot-1-findings.png` - the panel beside the scanned page, findings listed
- `screenshot-2-finding.png` - a finding opened, with its evidence
- `screenshot-3-screenshot.png` - the per-finding screenshot crop, the element outlined
- `promo-440x280.png` - the small promotional tile

All three screenshots are 1280 by 800, which is a size the store accepts. Replace them with a scan of a
page of your own if you would rather the listing showed something people recognise. The 128 by 128 store
icon is `extension/icons/icon128.png`, generated by the packaging step.

## What has been proved against a live API

`python tests/live_provider_check.py` drives the real extension in real Chrome and lets it call a
provider for real. As of 3 October 2026:

| Provider | Price | Live check |
|---|---|---|
| Groq `qwen/qwen3.8-27b` | free tier | **Passed end to end** - 8 findings, 3 of them the model's own and confirmed by verification, 7.0 s |
| Gemini `gemini-3.6-flash` | free tier | **Passed end to end** - 6 findings, 1 of them the model's own and confirmed, 15.9 s |
| OpenAI `gpt-6-luna` | paid account | Not run. Ids and request shape corrected; no funded account to test with |
| Anthropic `claude-haiku-4-5` | paid account | Not run. Same |

Two things that run taught us, both now handled:

- Gemini's **first** real call came back "This model is currently experiencing high demand ... usually
  temporary", and the scan was lost. The browser client now retries once on a transient refusal and the
  finished scan records that it did, so a slow scan explains itself. Covered without spending anything
  by `tests/extension_browser_ai_e2e.py`, whose stand-in reproduces that exact reply.
- `gemini-3.5-flash-lite` is faster (8-10 s) but every candidate it proposed was rejected by
  verification, twice. `gemini-3.6-flash` stays the default: slower, and worth it.

A provider that fails for a user does not break the scan: the deterministic findings still come back and
the panel names the provider error.

## Before pressing submit

1. `python -m aura.tools.package_extension` — builds the zip and refuses to build a broken one.
2. Confirm the privacy policy URL opens in a private window.
3. Confirm `aura-api.onrender.com` (or whatever the service is finally called) matches
   `extension/sidepanel/api.js`, `extension/manifest.json` and `render.yaml`. These three must agree, and
   `tests/test_hosted_deployment.py` checks that they do.
4. $5 one-time developer registration fee, if the account is new.
