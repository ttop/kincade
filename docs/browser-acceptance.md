# Automated browser acceptance

The automated Chromium acceptance suite is in `web/browser_tests`. From the
repository root, after installing the optional browser group and full Chromium
as described in [CONTRIBUTING](../CONTRIBUTING.md#automated-acceptance), run:

```sh
uv run --locked --group browser pytest -q web/browser_tests
```

Use `KINCADE_BROWSER_CHANNEL=chrome` for installed external Chrome,
`KINCADE_BROWSER_EXECUTABLE=/path/to/chromium` for a compatible executable, and
`KINCADE_BROWSER_HEADED=1` for visible test windows. The browser always uses its
own temporary profile; no current user session or internal app browser is used.

The suite runs five journeys end to end against the real built site:

- **The sample under the CSP header.** Before a tree is open, search is disabled
  and More options stays closed. The bundled sample renders as a six-page
  pedigree with the expected metadata title, embedded fonts and download name,
  and the live preview iframe tracks that PDF. Typing a surname narrows the
  typeahead and Escape restores the committed root. The Fan chart renders its
  own summary, page geometry and download name. Selecting a root with more
  than one marriage lists each option by spouse; choosing one redraws the
  pedigree with that spouse, and a Fan request from the same root omits the
  marriage override. The whole journey runs with the page's CSP response
  header in place.
- **Your own file and its options.** An uploaded GEDCOM file is searched and a
  root is chosen by keyboard, and the first render matches the full default
  settings. Every More options control — Last name UPPERCASE, record IDs, empty
  boxes, title, footer and no-footer — changes the exact settings sent to the
  worker; UPPERCASE, record IDs, title and footer are also checked directly in
  the drawn PDF text. Exclude private conceals the chosen name and
  birth date in the PDF text and metadata, renames the download, and keeps the
  local search choice without exposing a birth year. Overlapping option changes
  made while a render is in flight never send a second request; releasing the
  held reply sends exactly one more render, for the latest settings.
- **A fresh install in a mounted folder over plain HTTP.** A static host that
  rewrites a mounted, slash-free directory URL without redirecting the browser
  still serves the page, which installs over plain HTTP (`isSecureContext`
  false) without the browser ever leaving the opened URL. The wheel request
  carries the expected mounted path and cache-busting hash query, and its
  SHA-256 matches the manifest. Both chart types render and download.
- **Integrity failures.** A font whose published hash does not match falls back
  to built-in fonts for the sample chart and still downloads. A wheel whose
  bytes do not match its recorded hash fails installation with a retry
  affordance that reloads and fails again against the same corrupt site. A
  wheel request answered with an HTTP error names the status, the URL and the
  site owner. A later clean start recovers fully, with every font embedded
  again.
- **The page in French, then other languages.** Both language pickers list the
  five bundled languages by name and code. Opening the page with `?lang=fr`
  words the page, its placeholders and the rendered sample and Fan chart in
  French. Switching the page language rewords the page and resends the chart
  in the new language, keeping the choice in the address. Choosing a chart
  language apart from the page keeps that chart language when the page is
  reworded again, and sends no new render for a page-only change.

With See an example, root `I1` (George WASHINGTON) and unchanged defaults, acceptance
checks these outputs with no built-in-font note:

| Chart | Summary | PDF | Download filename |
| --- | --- | --- | --- |
| Pedigree | `5 charts, 1 index page, 6 pages` | Six portrait Letter pages, four embedded font subsets | `George Washington cascading pedigree.pdf` |
| Fan | `fan chart, 6 generations, 30 people` | One landscape Letter page, two embedded font subsets | `George Washington fan chart.pdf` |

The harness can hold a reply of a kind back and release every held reply of
that kind at once, without changing its data or replacing Python computation.
The full browser, pinned runtime and fonts must
be reachable; capability or network failures fail with diagnostics rather than
silently skipping. Native tests remain separate: `uv run pytest -q`.

The plain-HTTP journey proves operation outside a secure context. It does not
claim a second physical device, network routing or Safari/Firefox coverage.
The CSP is an exercised policy, not an assertion of minimum directives for all
engines. See [web/README.md](../web/README.md#content-security-policy) for the
exact policy.
