# AURA privacy policy

Last updated: 3 October 2026

AURA is a side-panel extension for Chrome and Microsoft Edge that checks the page you are on for UI,
UX, accessibility and runtime problems. This policy says exactly what leaves your browser, where it goes, and how long it is
kept. It describes the published extension and the AURA service it talks to by default.

Nothing is collected until you press **Scan current page**. AURA does not watch pages in the background:
it has no content scripts, and it can only read a tab after you click its toolbar icon on that tab.

## The short version

| | |
|---|---|
| Your AI provider API key | Stays in this extension. Sent only to the provider you chose. The AURA service never receives it. |
| Screenshots | Stay in this browser. One is sent by your browser to your AI provider; none is ever uploaded to the AURA service or stored anywhere. |
| The page's structure and address | Sent to the AURA service for the scan, kept in memory for that scan, never written to disk. |
| Anything else about you | Not collected. No account, no sign-in, no analytics, no advertising, no tracking. |

## What a scan sends to the AURA service

When you scan a page, the extension collects evidence from that one tab and sends it to the AURA service,
which checks every claim against that evidence and returns the findings. That evidence is:

- **The page's address**, with the query string and fragment removed — `https://shop.example/cart`, not
  `https://shop.example/cart?session=abc#item-3`. The same stripping is applied to every other address in
  the evidence (links, failed requests, error locations).
- **The page's title**, shortened to 200 characters, with anything that looks like a token or key removed.
- **The structure of the page**: element tags, roles, ids, classes, CSS selectors, positions and sizes, and
  computed styles — up to 3,000 elements. Text inside those elements is included, shortened to 300
  characters each, because a finding has to be able to name the button it is about.
- **Accessibility results** from axe-core, which runs inside the page: rule identifiers, severities, and
  the selectors of the elements that failed. No HTML is sent.
- **Errors the page raised while the scan was running**, and resource loads that failed, taken from the
  browser's own Resource Timing data.
- **The size of the browser window** and the pixel size of the screenshot — the size only, not the image.
- **What was clicked**, if you turned on the optional safe interaction test. AURA clicks at most five
  harmless controls. It never types, submits a form, navigates, or presses anything destructive.

### What a scan never collects

Cookies. Local storage or session storage. Passwords, card numbers or anything else typed into a field —
the extractor leaves form field values out entirely. Your browsing history. Any other tab. Anything from
a page you did not scan.

## What your browser sends to your AI provider

If AI analysis is on and you have saved an API key, **your browser** calls the provider you chose — Groq,
OpenAI, Google (Gemini) or Anthropic — directly. The AURA service does not make that call and does not
have your key.

That request contains:

- the evidence summary AURA prepared, which includes the page's stripped address, its title, the elements
  under consideration and the deterministic findings;
- **one screenshot of the visible part of the page**, if the model you chose can accept images. A
  screenshot shows whatever was on screen at that moment, which may include personal information on the
  page. If you would rather not send one, choose a text-only model, or turn AI analysis off and run a
  deterministic scan.

What that provider then does with the request is governed by their own terms, not by this policy:
[Groq](https://groq.com/privacy-policy/), [OpenAI](https://openai.com/policies/privacy-policy),
[Google](https://ai.google.dev/gemini-api/terms), [Anthropic](https://www.anthropic.com/legal/privacy).

With **Mock AI · Demo** selected, no AI request is made at all.

## How long anything is kept

On the AURA service:

- **Nothing is written to disk.** No screenshots, no page content, no audit files.
- A finished audit is held **in memory** so the panel can reopen it: at most 50 at a time, each replaced by
  newer ones, and all of them gone when the service restarts.
- Evidence prepared for a scan whose AI answer has not come back yet is held for at most **10 minutes**,
  then discarded.
- An audit belongs to the install that made it. Another install asking for it is told it does not exist.
- The service's logs contain no page address and no page title. An error is logged with the page it was
  looking at removed.

In your browser:

- Your API key, your provider choice and the service address are in the extension's own storage until you
  change or remove them.
- The audit you are looking at, and the screenshot it crops, live in the side panel and are gone when you
  close it.

## What AURA never does

- It never sells or shares anything with anyone. There are no third parties beyond the AI provider you
  chose yourself.
- It has no account system, no sign-in, no identifiers that follow you. The token the extension uses is
  issued to the install and says nothing about you.
- It runs no remote code: everything the extension executes is in the package your browser installed.
- It does not use what you scan to train anything. AURA has no model of its own to train.

## Optional: running it entirely on your own machine

**You do not need to do this.** AURA works as soon as you install it, against the hosted service described
above, with nothing to set up and nothing to run.

It is offered for people who would rather no page data left their computer at all. AURA's server is open
source, so you can run it yourself: start it with `python -m aura.api` and point the backend at
`http://127.0.0.1:8765` in the extension's settings. The evidence then never leaves your machine, and the
only thing that goes out is your browser's call to your AI provider — which you can also avoid by
selecting Mock AI.

## Children

AURA is a developer tool and is not directed at children.

## Changes

Material changes to what AURA sends or keeps will be reflected here, with the date above updated, before
the version that makes the change is published.

## Contact

Questions about this policy, or a request about data: open an issue at
<https://github.com/sivapragasan26/AURA/issues>.
