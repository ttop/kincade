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

The suite checks these behaviors with synthetic GEDCOM trees:

- Ready/bootstrap, early file choices, sample I1 selection, uploads and drops;
  sample intent stays attached to its source file, including failed replacements.
  The visible example action tracks successful source provenance through failed
  replacements and explicit root clear; real uploads restore it even with the
  sample filename. A compact keyboard/click file picker and dropped files show
  the current filename and people count without contradictory native chooser text.
  The Root person panel prompts for an explicit root after upload or clear; selection
  and pending/current PDF rendering hide that prompt.
- Full and filtered search, the 200-result limit, and unique matches that stay
  unselected until click or Enter, including one-person uploads and drops.
  Typing preserves any prior root and PDF; Enter flushes a pending search and
  selects its current first result; Enter during an in-flight search awaits that
  reply. Input-focused Arrow Up/Down navigation, active-row scrolling, duplicate
  names/record IDs/years, selected-name display and editing, unchanged closed Enter
  retaining the selection, reopening/direct arrows searching the committed name
  (including duplicate names after an ID search), IME Enter protection,
  and pointer commitment follow the manual-selection combobox pattern. Tab skips
  result options; selection/Escape/Tab/outside focus or pointer closes the popup
  without implicit commitment, and late replies keep it closed. Dismissing a
  draft or deleted query restores the committed name and searches that name on
  reopen. Pending queries clear old actionable suggestions and active references.
  The trailing keyboard-accessible x clears selection, preview, download and
  summary; the rootless chevron opens the list without selecting. There is no
  separate visible Root line or duplicate native cancel button. Clear cancels
  pending manual selection and current/queued sample reselection, while a fresh
  example action after choosing a real file still selects I1; delayed render
  replies cannot resurrect the cleared PDF, and the next explicit choice renders normally.
  Opening the rootless list preserves a pending sample selection.
- The pedigree-only Root marriage selector appears below the root-person picker
  only when the selected person has more than one partner family. It pairs one
  spouse with that union's date and place, defaults to the first recorded FAMS,
  and distinguishes families by record ID. It retains a choice across privacy,
  surname case, print, parent and Fan switches, while Fan requests omit the
  override. New roots, explicit clear and successful files reset the choice;
  failed replacements preserve it.
  Privacy hides living spouse names and hides marriage details when either
  partner may be living. Held metadata across settings, roots, clears and
  repeated record IDs in new files cannot restore old choices or private labels.
- Every chart's defaults and live settings, paper/print/ink combinations, privacy,
  adoptive parents and event stand-ins with relevant fixture data, blank outlines,
  IDs, places, shadows, index/page numbers, titles and footer override/retention.
- Per-chart generations/paper/title, shared settings, collapsed disclosure values,
  and the 400ms text debounce. Pedigree All and page-boundary presets in both print
  sizes exercise real 11- and 17-generation ancestry chains, checking useful
  caps, extension beyond five levels, actual PDF cutoffs, page counts and geometry.
  Root/parent/print changes preserve valid ordinals or clamp before the first
  affected snapshot. Deep birth and shallow adoptive families, root-only trees
  and print-dependent cyclic plans exercise the selected context. Large print
  preserves preset ordinal,
  Custom preserves literal values and invalid drafts, and Custom opens/focuses
  its More options field. Reveal/disclosure do not send duplicate renders;
  preset/All choices unblock stale invalid custom drafts. Held real replies check
  remapped latest snapshots and existing Fan/invalid-Pedigree ordering.
  Held root metadata across clears, root/mode changes, repeated IDs in new
  datasets and failed replacement opens cannot restore stale caps or PDFs.
  Metadata and render barriers resolve to one latest due preset snapshot;
  All, Custom and Fan remain usable while metadata is pending. Search rows do
  not trigger ancestry planning.
- Real PDF page counts, readable downloads and filenames that keep recorded name
  spelling independently of Last name UPPERCASE; chart surnames are uppercase
  by default and keep recorded case when Last name UPPERCASE is unchecked,
  embedded font subsets, outline paths and page geometry. Five-generation Fan
  downloads keep names and dates in both terminal third-ring cells curved and
  clockwise like their neighbors, with outward glyph tops and names outside dates.
- Compact desktop sidebar with chart above the fold, 320px gutters/no overflow,
  dark/light themes, input-attached dropdown geometry without shifting the root
  card/options/chart, 48rem preview fallback and initial one-paper-page sizing;
  resizing within desktop widths keeps the PDF URL. Actual native page geometry
  checks the full first paper page fits with modest trailing spacing and no part
  of page two visible, across paper sizes and document page counts.
- Separate stale search/render replies, checking unchanged rows after only the
  stale search reply arrives; one render in flight and exact request snapshots.
  Multiple queued opens keep the barrier until the final reply, and the final
  upload owns root selection even when named `pedigree.ged`; failed final opens
  recover the preserved sample with one search. Successful/failed replacements
  retain their source intent;
  invalid pedigree → Fan → invalid pedigree accepts the current fan reply.
- Actual native PDF viewer toolbar/page navigation/zoom, actual persisted Back
  navigation in the Open PDF layout with a usable PDF Blob, wide Back usability
  through restoration or reload, and clean reload.
- One unavailable font and a bad font hash use all-or-nothing base-14 fallback;
  a mismatched wheel fails at this site, Retry reloads, and a clean site recovers.
- A real CSP response header, and plain HTTP on a mapped non-loopback hostname
  with `isSecureContext === false`, using initialization, both charts and downloads.

With See an example, root `I1` (George WASHINGTON) and unchanged defaults, acceptance
checks these outputs with no built-in-font note:

| Chart | Summary | PDF | Download filename |
| --- | --- | --- | --- |
| Pedigree | `5 charts, 1 index page, 6 pages` | Six portrait Letter pages, four embedded font subsets | `George Washington cascading pedigree.pdf` |
| Fan | `fan chart, 6 generations, 30 people` | One landscape Letter page, two embedded font subsets | `George Washington fan chart.pdf` |

The init script installs requested gates before page code starts. The harness
releases individual replies by sequence while keeping newer replies held, without
changing their data or replacing Python computation. The full browser, pinned
runtime and fonts must be reachable; capability or network failures fail with
diagnostics rather than silently skipping. Native tests remain separate:
`uv run pytest -q`.

The HTTP test proves operation outside a secure context. It does not claim a
second physical device, network routing or Safari/Firefox coverage. The CSP is
an exercised policy, not an assertion of minimum directives for all engines.
See [web/README.md](../web/README.md#content-security-policy) for the exact policy.

The Open PDF layout test requires a persisted Back navigation event and checks
that the retained PDF Blob remains usable. The wide-layout test accepts either
restoration or a reload and checks that the returned page can provide a usable
PDF. It does not require wide-layout back-forward cache restoration.
