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

## Artwork still to produce

Not generated by the packaging script; these need making before submission.

- **Store icon** 128×128 — `extension/icons/icon128.png` can be used as the basis.
- **Screenshots** at least one, 1280×800 or 640×400. The strongest ones are the panel beside a page with
  findings listed, a finding opened with its evidence, and a cropped screenshot with the element outlined.
- **Small promo tile** 440×280, optional but it is what appears in listings.

## Before pressing submit

1. `python -m aura.tools.package_extension` — builds the zip and refuses to build a broken one.
2. Confirm the privacy policy URL opens in a private window.
3. Confirm `aura-api.onrender.com` (or whatever the service is finally called) matches
   `extension/sidepanel/api.js`, `extension/manifest.json` and `render.yaml`. These three must agree, and
   `tests/test_hosted_deployment.py` checks that they do.
4. $5 one-time developer registration fee, if the account is new.
