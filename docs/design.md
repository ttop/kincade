# Kincade design notes

The rules the code keeps and where each lives, for contributors. The [README](../README.md) describes Kincade for its users.

## Module layering

The modules are in `kincade/`. The library takes a family tree in memory and returns PDF bytes; GEDCOM reading and the command line are thin layers on top of it.

| Module | Contents | Imports from Kincade |
|---|---|---|
| `model.py` | `Tree`, `Person`, `Family`, `Event`, `Date`, `Day`, `ParentLink`; the choice of parent family; the recognized date shapes | nothing (standard library only) |
| `gedcom.py` | decoding, line parsing, GEDCOM to model | `model` |
| `charts.py` | chart planning, stand-in events, the privacy estimate | `model` |
| `lang.py` | strings, language files, templates, date and name formatting, index sort rules | `model` |
| `pdf.py` | page geometry, fonts, kerning, drawing, `Options`, `render`, `render_blank` | `model`, `charts`, `lang` |
| `fan.py` | `Fan`, `FanCell`, `LegendEntry`, checks, ring geometry, text candidates | nothing |
| `fanplan.py` | ancestor seating, copy counts, years, grandparent-line colors | `model`, `charts`, `lang`, `fan` |
| `fanpdf.py` | `FanOptions`, `render_fan`, page layout, cell fitting and drawing | `lang`, `fan`, `pdf` |
| `cli.py` | arguments, the config file, `--find`, `--show-config`, pedigree and fan runs | `model`, `charts`, `lang`, `pdf`, `gedcom`, `fan`, `fanplan`, `fanpdf` |
| `__init__.py` | the public names | `model`, `gedcom`, `lang`, `pdf`, `fan`, `fanplan`, `fanpdf` |

Only `pdf` and `fanpdf` import reportlab, and only `cli` imports `argparse`. `tests/test_layering.py` checks the table.

## Browser page

The static page runs Kincade under Pyodide in a Web Worker. GEDCOM bytes and
PDF bytes stay in the browser. `web/index.html` supplies markup and CSS,
`web/app.js` owns the interface, `web/worker.js` owns bootstrap and dispatch,
and `web/kincade_web.py` supplies a plain-Python `Session` with no Pyodide imports.
The page uses system UI fonts and plain HTML/CSS/JavaScript. At 48rem and wider,
a compact 19rem controls rail sits beside the chart in a layout up to 86rem wide.
Smaller screens stack the controls and chart, with a 16px side gutter at 320px.
Colors follow `prefers-color-scheme`.

The page has no framework, bundler, service worker, remembered settings, offline
mode, blank chart, fan legends or highlights.
It installs Kincade from the site wheel, with external Pyodide and fonts.

### Build and origins

`uv run python web/build.py` builds one wheel with `uv build --wheel`, then
assembles `web/site/`. That folder contains exactly `index.html` and the wheel.
All URLs for these two files are relative, so the same folder works at a site's
root or in a subfolder. Build output and the wheel cache are ignored by Git.

The HTML inlines the app, worker and Python glue and a JSON manifest whose keys
are `pyodide: {version, base}`, `wheel: {name, sha256}`, `reportlab` (the exact
requirement), `fonts` (four `{name, url, sha256}` objects), `kincade` (the version)
and `sample: {name, text}` from `docs/examples/george-washington.ged`. The build escapes
`<` as `\u003c` in JSON and refuses `</script` and `<!--` in inlined source,
in any letter case. It derives Kincade's version from the wheel filename and
reportlab's version from the single locked package in `uv.lock`.

| Asset | Origin and pin |
|---|---|
| HTML and Kincade wheel | The site's host; wheel filename and SHA-256 in the build manifest |
| Pyodide, micropip, Pillow, charset-normalizer | `https://cdn.jsdelivr.net/pyodide/v314.0.7/full/`; base URL derived from `PYODIDE_VERSION` in `web/build.py` |
| reportlab | PyPI through micropip (`pypi.org` and `files.pythonhosted.org`); currently `reportlab==5.0.1`, derived from `uv.lock` |
| Liberation Sans Regular/Bold and Serif Regular/Italic | `https://cdn.jsdelivr.net/npm/@betteroffice/fonts@0.4.0/assets/`; names, URLs and SHA-256 in `web/fonts.json` |

The four TTFs are byte-identical to Liberation 2.1.5 and use the SIL Open Font
License 1.1. They load into `/fonts` under names `FONT_FILES` recognizes; the
site host does not redistribute them. First load downloads about 11 MB, and
subsequent visits use the browser's normal HTTP cache. Building fetches no
runtime or font assets; uv needs network access when project dependencies or
the build backend are not available locally.

`.github/workflows/pages.yml` runs on pushes to `main` and manual dispatch.
Its `browser` job calls the reusable `.github/workflows/browser.yml` at the same
commit with only `contents: read` permission. The `deploy` job requires that
browser acceptance succeeds before building and publishing the two files; a
failed, cancelled or skipped prerequisite prevents deployment. Both Pages jobs
run only for a public repository. Deployment uses the `github-pages` environment
and grants `contents: read`, `pages: write` and `id-token: write`. The browser
workflow also retains its independent push, pull request and manual runs.
The public repository's Pages source must be GitHub Actions.
[web/README.md](../web/README.md) covers hosting and the CSP exercised by automated acceptance;
[CONTRIBUTING](../CONTRIBUTING.md#browser-page) documents the browser suite.

### Worker bootstrap and protocol

On load, the main thread starts a Blob module worker and sends `init` with the
manifest, glue source from `#glue` and the wheel's absolute URL resolved against
`location.href`. A Blob worker has no page-relative base URL. A promise chain
processes messages in arrival order: each handler finishes and sends its reply
before the next starts, including messages queued during initialization.
Each rejection is caught so later requests can still run. The status line
includes the first-visit download note until Ready; a startup failure names its
step and host and offers Retry.

Initialization reports each step and its host, in this order. Steps travel as
codes (`pyodide`, `micropip`, `reportlab`, `kincade`, `fonts`, `start`) and so
do hosts (`jsdelivr`, `pypi`, `site`, `none`); the page words them.

1. After reporting “Loading Pyodide,” dynamically import the pinned
   `pyodide.mjs` from the absolute jsDelivr URL
   `${manifest.pyodide.base}pyodide.mjs` inside initialization, then call its
   exported `loadPyodide({indexURL: manifest.pyodide.base})`. Pyodide 314.0.7
   requires a module worker. Keeping the import in initialization lets its
   rejection follow the same step, host and message reporting as other
   startup failures.
2. `loadPackage("micropip")` loads micropip from jsDelivr.
3. micropip installs the locked reportlab requirement from PyPI; Pillow and
   charset-normalizer come from jsDelivr.
4. Fetch the site wheel with `?v=<first 12 hex digits of its SHA-256>`, write it
   to `/tmp/<wheel name>`, compare its SHA-256 with the manifest using Python's
   `hashlib`, then install from `emfs:/tmp/<wheel name>`.
5. Fetch the four font files from jsDelivr, check them with `hashlib`, and write
   only matching files to `/fonts` under their manifest names.
6. Run the glue, create a `Session`, and call `load_fonts("/fonts")`.

A wheel mismatch fails initialization, names this site and asks the reader to
reload matching files; Retry reloads. Each missing or mismatched font is left
out, and failure to load all four roles selects `BASE14`. The summary then
names built-in fonts, whose Windows-1252 coverage strips unsupported accents
or replaces characters with `?`. Integrity uses `hashlib`, without a
`crypto.subtle` secure-context dependency. Automated acceptance checks a plain
HTTP origin with `isSecureContext` false; physical LAN routing is outside its scope.

| Request | Reply |
|---|---|
| `init {manifest, glue, wheelUrl}` | `status {step}` per step, then `ready {fonts: "embedded" \| "base14", kincade}`, or `failed {step, host, message, code, params}` |
| `open {bytes}` | `opened {count}` |
| `search {seq, text, excludePrivate, standins}` | `results {seq, total, rows}` |
| `root-metadata {seq, treeVersion, rootId, adoptiveParents, largePrint, excludePrivate, preserveCase, lang}` | `root-metadata {seq, treeVersion, rootId, adoptiveParents, largePrint, excludePrivate, preserveCase, lang, depth, families}`; `families` contains `{id, spouse, details}` objects |
| `render {seq, rootId, chart, settings}` | `rendered {seq, pdf, filename, summary, preview: {pages, width, height}}`, with PDF as a transferred `ArrayBuffer`; `summary` holds counts: `{charts, indexPages, pages}` for a pedigree, `{generations, people}` for a fan |
| Failed `open`, `search`, `root-metadata` or `render` | `error {request, seq, message, code, params, details}`; `seq` for search/metadata/render, empty details for `ValueError` and coded errors, otherwise Python traceback |

A `code` names a page message, filled from any `params`: `download`,
`wheelMismatch`, `notReady` and `noPeople`. Other errors carry a `null` code. The page words an
error with details by its operation and shows a `ValueError` message as written.

### Plain-Python session

`Session` holds the successfully opened tree and the font set, initially
`BASE14`. `load_fonts(directory)` calls `load_fontset([Path(directory)])` and
returns `"embedded"` only when all four roles load, otherwise `"base14"`.
`open(data: bytes)` returns the person count and changes the tree only after a
successful read with at least one person. An unreadable or no-people file
leaves the previous tree intact.

`search(text, exclude_private, standins, limit=200)` returns `(total, rows)`;
rows are `[record ID, name, years]` from `person_line`. Empty text lists everyone
in file order. `find_people` supplies matching behavior; `living_checker` and
`nobody_living` supply the same living estimate as `--find`. The browser calls
`person_line(..., living_name=None)` to keep original names for local root
selection while hiding living years. With `exclude_private`, CLI lists use the
localized living label.

`Session.pedigree_depth(root_id, adoptive_parents, large_print)` returns the
selected root's full known occupied generation depth. It calls the same
cycle-safe `plan_charts(tree, root_id, None, parents, large_print)` used for
rendering and takes the maximum `chart.offset + box_generation(pos)` among
slots whose IDs exist in the current tree. Unknown references and page padding
do not increase the depth. Cycles and pedigree collapse can make depth depend
on print size. The cache key includes root, parent choice and print size;
successful opens clear it, and failed opens preserve it. This read-only metadata
operation changes neither the last PDF preview nor the session's font set.
Search continues to return rows without planning each person's ancestry.

`Session.root_families(root_id, exclude_private=False, preserve_case=False,
lang="en")` returns `{id, spouse, details}` objects for families that name the
root as a partner, preferring FAMS order and including unions without a
reciprocal FAMS link. `spouse` is the spouse's name, or empty when the family
names none. `details` holds the available marriage date and place, worded in
`lang` as a pedigree box words them. The page joins the ID, the spouse or its
own Unknown spouse wording, and the details. Privacy conceals a possibly living
spouse's name with `lang`'s living label and hides either living partner's
marriage details; surname case follows `preserve_case`.
The root-metadata operation returns these families together with pedigree depth.

`Session.render(root_id, chart, settings)` returns `(pdf, filename, summary)`,
where `summary` is the counts the page words.
After success, `Session.preview` holds `{pages, width, height}` for that PDF;
it starts as `None`, and failed renders preserve the previous metadata. Pedigree
uses `Rendered.pages`, including any index pages, and `PAPER_SIZES` for the actual
`Options.paper`. Fan uses one page and `FAN_PAPER` for the actual `FanOptions.paper`.
Width and height are PDF points. The worker attaches these values to the rendered
reply without changing the session's return tuple or the shared summaries.
`PAGE_OPTIONS` is a chart-to-key-set mapping:

- `"pedigree"`: all `Options` dataclass fields except `today`, `compress` and
  `fonts`: `generations`, `exclude_private`, `adoptive_parents`,
  `event_standins`, `empty_boxes`, `show_ids`, `shorten_places`, `index`,
  `page_numbers`, `footer`, `title`, `paper`, `large_print`, `shadow`, `preserve_case`,
  `root_family`, `lang`.
- `"fan"`: `generations`, `exclude_private`, `adoptive_parents`, `event_standins`,
  `preserve_case`, `ink`, `paper`, `title`, `footer`, `lang`; the union of `plan_fan`
  keyword arguments and `FanOptions` fields, with the same three exclusions.

Omitted keys use library defaults. Unknown charts, keys outside the selected
chart's set, unknown root record IDs and a `lang` outside `LANGUAGES`, the
bundled language codes, raise plain `ValueError`. A tree with no people raises
`PageError`, a `ValueError` whose `code` is `noPeople`. Pedigree
Generations accepts `None` or an integer at least 1; fan Generations accepts an
integer from 2 to 7. Neither accepts `bool` as a number.

A pedigree uses `render_with_counts(tree, root_id, Options(**settings,
fonts=self.fonts))` and counts its chart, index and total pages. A fan plans with
generations, privacy, parent mode, stand-ins, surname case, language and ink, then
draws with paper, title, footer, language, ink and the session fonts. Planning and
drawing receive the same ink because `plan_fan` chooses the fills. Its summary
counts generations and `fan_people(fan)`.
Both chart types use uppercase surnames unless `preserve_case` is enabled,
including the pedigree index,
PDF metadata and the default fan title. `lang.fmt_surname` capitalizes letter by
letter and keeps a letter whose capital is longer (ß, not SS). Leading particles
the language's `ignore_particles` skips keep their recorded case (Anna von der
HEIDE), and `lang.index_name` prints them after the given name (HEIDE, Anna von
der), so an entry reads as it files. `SortRules.particle_end` finds where they end. The option does not change stored names,
matching or index sorting. Search rows capitalize surnames.
Both download filenames use `output_root_name(tree, root_id, ...)` with the
chart's privacy and parent settings, plus Large print for pedigree. It returns
the root's recorded name spelling or the chart language's living label when
privacy conceals the root. `default_output_name` and `default_fan_output_name`
make that name file-system safe. Filename spelling is independent of `preserve_case`.
A fan uses sans and bold faces, so its PDF embeds two subsets rather than the
pedigree's four.

`person_line` and `fan_people` in `kincade.cli` serve both the CLI and page;
`fan_summary` words `fan_people` for the CLI. `fan_people` sums
`1 / cell.copies` for filled cells and rounds to count distinct people.
These helpers, `find_people`, `output_root_name`, the filename helpers,
`render_with_counts`, `BASE14`, `display_name`, `living_checker` and `nobody_living`
are not exported through `kincade.__all__`. The page ships and is tested with the
package.

The default printed pedigree heading uses the same `meta_title` template as the
PDF document title, including the privacy-safe root name. An explicit `title`
overrides the printed heading. Blank charts use the base language title. Output
filenames use the language's `file_name`, `fan_file_name` and `blank_file_name`
templates and keep recorded name spelling.

### Controls and rendering state

Pedigree starts selected. The switch sends `chart`, outside `settings`.
Each serialized option control has `data-option` and `data-charts`, naming `pedigree`,
`fan` or `pedigree fan`. Only the selected chart's controls are shown,
serialized and validated. Inactive fields are hidden and retain their values.
Collapsed “More options” controls remain part of the selected chart's settings.
Generations, Paper and Title have separate controls for each chart; all shared
options have one control and one value. Each chart has four always-visible
option controls; the remaining options appear under its disclosure. Root marriage
appears below the root-person selector when that person has multiple families.
Generations and Paper share a row when both controls have at least 12rem of
space, and stack in narrower panels. Ink fills its row, and checkboxes align in a
single column. The Paper label shows the fixed orientation: portrait for Pedigree,
landscape for Fan.
Orientation is not a selectable setting. The disclosure focus outline wraps only
its summary.

| Label | Charts | Control | Default | Sends |
|---|---|---|---|---|
| Generations | pedigree, always | select: All generations, useful full-chart depths, Custom…; normal starts at 4 with stride 3, Large print starts at 3 with stride 2 | All generations | `generations`: the selected total ancestry depth, or `null` for All. These page-boundary depths count the root as 1, rather than promising a PDF page count. |
| Custom generations | pedigree, More options when Custom… selected | number input, placeholder "all" | empty | `generations`: the literal number, or `null` when empty. Anything but a whole number of at least 1 marks the field invalid, and no render is sent; the last PDF stays. |
| Generations | fan, always | select: 2 to 7 | 6 | `generations`: the number |
| Paper | pedigree, always | select: Letter, A4 | Letter | `paper`: `"letter"` or `"a4"` |
| Paper | fan, always | select: Letter, A4, Tabloid, A3 | Letter | `paper`: `"letter"`, `"a4"`, `"tabloid"` or `"a3"`. The fan is always landscape. |
| Large print | pedigree, always | checkbox | off | `large_print` |
| Ink | fan, always | select: Color, Grayscale, Black and white | Color | `ink`: `"color"`, `"grayscale"` or `"bw"` |
| Exclude private | both, always | checkbox | off | `exclude_private` |
| Root marriage | pedigree, below the root person when multiple families exist | select: First recorded marriage and the root's partner families by record ID, spouse and marriage details | First recorded marriage | `root_family`: the selected family ID, or `null` for the default |
| Chart language | both | select: English, Deutsch, Español, Français, Italiano | the page language | `lang`: `"en"`, `"de"`, `"es"`, `"fr"` or `"it"` |
| Leave out unknown ancestors | pedigree | checkbox | off | `empty_boxes`: `true` when NOT checked |
| Show record IDs | pedigree | checkbox | off | `show_ids` |
| Last name UPPERCASE | both | checkbox | on | `preserve_case`: `true` when NOT checked |
| Draw adoptive and foster parents | both | checkbox | off | `adoptive_parents` |
| Christenings and burials stand in for missing births and deaths | both | checkbox | on | `event_standins` |
| Shorten long places | pedigree | checkbox | on | `shorten_places` |
| Drop shadow | pedigree | checkbox | off | `shadow` |
| Title | pedigree | text, placeholder "Cascading Pedigree — Root's name" in the chart language | empty | `title`: the text, or `null` when empty |
| Title | fan | text, placeholder "Root's name — Fan chart" in the chart language | empty | `title`: the text, or `null` when empty |
| Footer | both | text, placeholder "Created <today's date> using Kincade" in the chart language | empty | `footer`: the text, or `null` when empty |
| No footer | both | checkbox; disables Footer | off | `footer: false` when checked, in place of Footer's value |
| Page numbers | pedigree | checkbox | on | `page_numbers` |
| Name index | pedigree | checkbox | on | `index` |

Footer and No footer both carry `data-option="footer"`. No footer disables
Footer but keeps its text, sending `false` instead of that text or `null`.
The fan Title placeholder names no person. The Last name UPPERCASE checkbox
shares its value between chart types, like the privacy checkbox. Its unchecked
state enables `preserve_case`; root metadata and render settings use that same
inverted value. Fan Generations is a select with no invalid choice;
pedigree Custom generations is the only option with a draft that can fail validation.

Root marriage uses the current root-metadata reply's families. It is visible only
for a pedigree root with more than one partner family, below the root-person
selector. It stays hidden while metadata is pending or no root is selected.
The default sends `null`, retaining first-FAMS behavior. A chosen family stays
selected across privacy, surname case, print, parent and Fan changes; Fan requests
omit `root_family`.
A different root, explicit clear or successful file open resets it. Failed opens
preserve it. A refreshed family list removes a choice only if its ID is absent.

The Pedigree selector is UI-only: the custom numerical input remains the sole
`data-option="generations"` owner for Pedigree, and the snapshot resolves the
selected mode to one number or `null`. Presets end at the first full-chart
boundary at or above the selected root's deepest known occupied generation,
with at least one full chart for a root-only tree. A depth of 11 offers
4/7/10/13 normally and 3/5/7/9/11 in Large print; deeper roots can offer more
levels (normal depth 17 reaches 19). Root, parent choice and print changes
refresh these choices. A valid cascade ordinal stays selected (normal 7
becomes large 5); an ordinal above the new cap clamps to its highest useful
level and does not return to the older ordinal later. All stays All and
Custom retains its literal value or invalid draft. Selecting Custom opens More
options and focuses its labelled input. Disclosure and focus changes do not
advance render currency when the effective generation limit is unchanged.
Selecting a preset or All hides the custom field and bypasses a retained invalid
draft. Chart switching preserves the Pedigree mode, draft and Large print;
Fan continues to validate and serialize only its own controls.

The drop zone and its keyboard-accessible Choose file button open a file picker
accepting `.ged` and `.gedcom` files. The native input is hidden; the visible
filename and people count describe the successfully opened source, including
uploads, drops and the example. Failed replacements leave that summary intact.
See an example sits beside Family tree and is hidden only while the current
successful source is the example. Its durable source identity is separate from
its cancellable I1 selection intent; a real file with the same filename is still
an upload. A successful real file restores the example action.
The compact header places the subtitle beside Kincade when space allows, with
privacy assurance beneath it. Version and GitHub sit at the top right on the title
baseline when space allows and wrap on narrow screens. Version comes from the
build manifest before Ready and the worker version afterward. Ready remains
observable and accessible without occupying visible space; loading and failure
status stays visible.
A loaded tree without a chosen root shows Choose a root person to see the chart
in the Root person panel beneath its search field, outside the dropdown. The small
prompt uses the theme error color and a status role. Selection hides the prompt,
and explicit clear restores it.
The main thread owns file choice, root, option values, PDF Blob URL and
independent search/render counters. Root metadata has separate currency and
matches the current successful-open version, root ID, parent choice, print size,
privacy and surname case. Both worker and page advance that tree version only on
successful opens.
Changing context or starting an open invalidates pending metadata; root clear
also invalidates it. Numeric choices keep the selected intent but remain disabled
while no matching horizon is available. Only preset renders wait for that
horizon; All, Custom and Fan keep their existing validation and render behavior.
Applying metadata clamps before taking a due render's settings snapshot, without
advancing render currency or sending a duplicate PDF. The open barrier and the
one-render-in-flight rule still apply; when both barriers clear, the latest due
render uses the latest controls. Search input waits 150 ms; only a reply
matching the latest search `seq` appears. New typing clears old suggestions and
any active highlight while the current search is pending. Enter flushes a pending
search, or awaits an already sent current search, and explicitly picks its first
row when no suggestion is highlighted. Ordinary search replies never pick a root,
even with one match; uploads and drops require click or Enter even with one person.
Typing keeps any selected root and PDF until an affirmative selection or
explicit clear.

The editable combobox shows the committed person's name in the input at rest.
A trailing x button, named “Clear selected person,” removes that selection and
its PDF, download link and summary. With no selection, the button shows a
chevron, named “Open person list,” and focuses/opens the existing scrollable
list without choosing a person. Both button states follow the fieldset's disabled
state until a tree is ready. The input uses text editing without a second native
search-cancel button. The record ID and name remain in a visually hidden live
status describing the input, such as `Root: I12, Jane DOE`, for accessible
selection and duplicate-name disambiguation.
The input, trailing button and attached popup share a close-fitting focus border;
keyboard focus adds a visible ring, with an inset indicator on the button.
Clicking or focusing the committed name selects its text for replacement.
When commitment replaces the query, previous suggestions are invalidated without
sending a search; reopening searches the name now shown in the field. Enter on
an unchanged, closed selection keeps the committed person and PDF. Results for
an unchanged query remain usable, including distinct records with the same name.
The compact, scrollable listbox attaches directly below the input at the same
width and overlays nearby controls without moving the root card, options or
chart. Each suggestion shows its name, record ID and years; duplicate names stay
distinguishable. At most 200 rows appear, with “n of N shown” for longer results
and “0 matches” when none match. Changing Exclude private or event stand-ins
refreshes the years in the list.

The popup starts hidden. Focusing, clicking or typing opens it. New results have
no active suggestion. Arrow Down/Up and pointer movement highlight a suggestion;
arrow navigation keeps DOM focus in the input and scrolls the active row into
view. Only Enter or a row click commits it. The input and listbox follow the
[W3C manual-selection combobox pattern](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/),
using `aria-activedescendant` and `aria-selected` for active suggestions. Options
stay outside the page's Tab sequence. Selection, Escape, Tab, outside focus or
an outside pointer press closes the popup and clears its active reference.
Dismissal cancels any pending manual Enter selection. If a person is committed,
it restores that person's name and invalidates draft-query suggestions and
replies; reopening searches the restored visible name. Without a selection,
dismissal keeps the typed query available for further editing. Late current
search replies update contents without reopening the popup or overwriting
input. Standard caret
and editing keys remain browser-controlled; Enter during IME composition does
not select. Visibility and highlighting alone change no request counter or PDF.

Every open sent advances both counters; every root pick advances the render
counter. A chart switch or option change advances it only when every active
option is valid. Title and Footer input wait 400 ms. `maybeRender` sends only
when the worker is ready, a root is selected, no open is outstanding, no render
is in flight, active settings are valid, and the counter exceeds the last
render sent. At send time it snapshots `seq`, root record ID, selected chart
and all active settings together. The worker dispatches that request snapshot,
never later UI state. At most one render is in flight.

A `rendered` reply ends the in-flight render. It appears only when a root is
selected and its `seq` equals the render counter, replacing the previous PDF
and revoking its Blob URL; stale replies are dropped. Explicit clear cancels
pending manual selection and automatic root intent from the current or already
queued sample choices, while keeping their file opens intact. After choosing a
real file, a fresh See an example action after clear owns fresh I1 intent. Clear invalidates old search replies
and revokes/removes the selected root's PDF. It does not advance render currency
or send a render. An already sent render
keeps its barrier until its reply, which cannot restore a cleared preview;
a subsequent affirmative selection advances the counter and renders normally.
Opening or navigating the rootless list retains the sample's pending I1 intent.
A render error ends the in-flight render too. For a current error the
“Rendering…” state clears, the previous PDF stays and
the error appears. Both paths then try the next due render.

Invalid pedigree Generations leaves the counter unchanged and keeps the last
PDF. In particular, switching from Fan to a still-invalid pedigree sends no
render and makes no counter advance. A current fan reply already in flight
therefore appears with its fan summary and landscape preview geometry even
though Pedigree is now selected.
Fixing Generations advances the counter and sends the pedigree. A valid chart
switch advances the counter and makes an earlier chart's reply stale.

An open during rendering waits behind that request in the worker. Advancing
both counters at send time makes older search and PDF replies stale; no new
render starts while any open is outstanding. A successful open clears root,
search, results and PDF, displays `<file name>: <n> people` and searches everyone
with the picker closed. The sample choice carries root record ID `I1` through
held files, asynchronous reads and the open queue. Only a successful open assigns
that choice to the current tree; subsequent search refreshes keep its pending
root intent until a root is picked. A matching reply picks George WASHINGTON through
the usual selection/render path using current chart/settings. Uploaded files
carry no sample root intent, including uploads named `george-washington.ged`.
A failed open shows an error under the drop zone and preserves the prior tree,
root and PDF. Its advanced counter causes a new render of that root for the
selected valid chart once no open is outstanding. If a failed replacement
canceled the sample's initial search before I1 was selected, the final open error
schedules a fresh search for that preserved sample. An existing pending search
is sent instead, and a selected root prevents redundant sample recovery.
A file chosen before ready
is held; the last choice wins, including a slow earlier file read.

Names, years, record IDs, filenames and errors enter the DOM through
`textContent`, never HTML parsing. `ValueError` messages have no traceback;
other Python exceptions have a short message and a “Details” disclosure.
The PDF area shows an iframe only with `navigator.pdfViewerEnabled` and a
viewport at least 48rem wide; otherwise Open PDF opens the Blob in a new tab.
The iframe initially fits available width and the height of one PDF paper page,
independent of the document's page count. The native viewer provides scrolling
and page navigation for the remaining pages. Its display URL adds
`#view=FitH&navpanes=0`, preserving the native viewer toolbar; Download PDF,
Open PDF and URL revocation use the original unfragmented Blob URL.

Only an accepted `showPdf` reply replaces the saved preview geometry;
`clearPdf` resets it. Sizing never reads current controls, parses the PDF bytes or
extracts page counts from the summary. The container is unhidden before measuring
`frame.clientWidth`, and height is set before assigning the display URL. The
initial height estimates Chromium's native fit-width paper box:
PDF points convert to CSS pixels at 96/72, and the paper box includes 10 pixels
of native shadow and margins in each dimension, scaled together with the page.
Fit zoom uses frame width minus the native viewer's one-pixel scrollbar
reservation, divided by that paper-box width. Height is the paper-box height times fit zoom,
plus the 56-pixel native toolbar and the iframe's measured border height, rounded
up. This avoids counting the outer iframe width as paper width or reserving extra
toolbar space that reveals part of page two. The estimate does not read native
viewer internals at runtime; native viewers expose no portable intrinsic height
API. Other browser viewers can have different toolbar and page spacing.
A `ResizeObserver` watches container width, ignores zero widths and height-only
changes, and updates height without reloading an unchanged display URL. Returning
above 48rem restores sizing from the accepted PDF's geometry. The one-page-height
estimate covers initial fit-width display; later native toolbar zoom or rotation
can change the viewer's internal height. The browser suite checks accepted
geometry and resize behavior against real PDFs.

The PDF section retains an accessible heading without a visible title.
Download PDF sits beside the live summary in a compact row that wraps on narrow
screens. “Rendering…” overlays the preview during rendering. Download PDF uses
the returned filename; the summary combines the returned counts, worded in the
page language, the file size and a built-in-font note when needed. The header
shows the language select and Kincade's version, and links to the repository.

PDF cleanup uses `pagehide`, revoking the Blob URL only when the page is not
being preserved in the back/forward cache (`event.persisted` is false). A cached
page keeps its PDF URL so returning with Back can use the preview and download.
The page registers no `unload` handler.

### Page languages

The page and its PDFs speak the bundled languages, keyed by ISO 639-1 codes:
`en`, `de`, `es`, `fr` and `it`. Both the header's language select and Chart
language build their options from the manifest's bundled languages
(`fillLanguageChoices` in `web/app.js`), each option named in its own language;
`web/index.html` holds only a static English option before the script runs. On
load the page takes `?lang=` when it names a bundled language, else the first
`navigator.languages` tag whose primary subtag does (`fr-CA` gives `fr`), else
English. Choosing a language rewrites the URL's `lang` parameter with
`history.replaceState`.

`web/lang/<code>.toml` holds the page wording: one TOML file per language, a
table per message prefix (`page`, `status`, `step`, `host`, `init`, `error`,
`tree`, `root`, `family`, `options`, `pdf`) and a key per message, with the same
keys and `{name}` placeholders in each file. A plural message is an inline table
of `Intl.PluralRules` categories, `one` and `other`; numbers in messages use
`Intl.NumberFormat` for the page language. Static text names its message with
`data-i18n`, and attributes with `data-i18n-aria-label`, `data-i18n-placeholder`
or `data-i18n-title`. Text the page writes later, such as status, counts and
errors, registers its renderer, so a language change rewords it in place. The
change also rewords generation and family choices and fetches the root metadata
again so marriage details follow. It sends no render unless the chart language
changes.

Chart language is the PDFs' `lang`. It follows the page language while the two
are equal, and a different choice stays when the page language changes. The
Title and Footer placeholders use the chart language's title, fan title, footer,
date format, first-of-month day and months, which `web/build.py` copies from
the language files into the manifest's `languages`. The build also reads
`web/lang/*.toml` with `tomllib`, flattens each file back to the dotted-key
shape, and inlines the result as the manifest's `messages`, failing when the
`web/lang` codes differ from the bundled chart languages. Filenames use the
chart language's file-name templates, as the CLI's do; a concealed root's name
is its living label.

### Verification boundary

`tests/test_web.py` runs under CPython in the existing CI matrix. `web` is on
pytest's Python path, `kincade_web` is a local import for ruff, and both Python
web files are in mypy's scope; JavaScript stays outside those Python tools.
The build module is loaded by path to avoid shadowing PyPA's `build`.
Tests cover atomic opens, privacy/search rows, both charts with every allowed
key, filename/summary behavior, preview metadata against actual PDF page counts
and MediaBoxes for pedigree Letter/A4 with index and large print on/off and all
four fan papers, default geometry and metadata preservation on failure,
invalid charts/keys/roots/generations, all three fan inks against direct
planner/renderer output in invariant mode,
empty-folder font fallback, both directions of chart/control mapping,
manifest values and escaping/refusals, the exact two-file output and the four
font pins. Static assembly checks cover the preview metadata bridge, responsive
iframe wiring, height independent of document page count and absence of a fixed
height; they do not execute a native viewer.
CLI tests cover both shared summaries and unchanged output.
`web/browser_tests` runs real Pyodide in an isolated full Chromium profile,
checks PDF contents and native viewer behavior, and gates real Worker replies
for deterministic ordering scenarios. The optional `browser` dependency group
keeps the default native suite independent. The browser suite checks font and
wheel integrity failures, an actual CSP response header and a mapped HTTP
origin with `isSecureContext` false. It does not simulate a second physical device.

## Chart planning

`charts.plan_charts` returns the charts and draws nothing.

- Positions are Ahnentafel numbers, 1 to 15 (1 to 7 in large print): the father of p is 2p, the mother 2p + 1. `box_generation(p)` is 1 for box 1, 2 for boxes 2-3, 3 for 4-7 and 4 for 8-15.
- Each person has one parent family drawn, never parents from two (`Tree.parent_family`): the links are ranked by most birth relationships, then fewest step relationships, then file order; in adoptive mode the first link with an adopted parent wins, then one with a foster parent, then the same ranking. A step-parent's slot stays `None`, like an unknown ancestor's.
- Continuations are numbered breadth-first: charts in order, and in each chart the last generation (8-15, or 4-7) in order. A person there with a known parent continues on the chart they already root, if any (pedigree collapse, a loop in the data), else on a new chart with that person in box 1. A person roots at most one chart, so planning always ends.
- A chart's `offset` is the number of generations above its box 1: 0 for chart 1, g - 1 for a continuation of a box in generation g. Each level of continuations adds three generations, or two in large print.
- The same parents mode chooses the families for the boxes, the continuations, the fathers' marriage lines, the privacy estimate and the index.
- Only the initial root box uses `Options.root_family` (`--root-family FAMILY`, TOML `root_family`) to pair a spouse name with one marriage. `None` retains exact first-FAMS behavior, even for a missing record. An override accepts a family record ID, including GEDCOM `@ID@` syntax and case-insensitive spelling, and requires the family to exist and name the root as a partner. It does not alter ancestor selection, continuation marriage context or index membership. Missing fields leave labels empty. Living spouse names use `living_name`, and either living partner hides the marriage values under privacy. Fan charts are unchanged. Blank charts ignore the selector and include an empty spouse row in the same enlarged, centered root box.

**The generations limit.** With `--generations N`, a position is drawn only when `offset + box_generation(p) <= N`, and a continuation chart is made only when its boxes 2 and 3 are within the limit (`offset + 2 <= N`). So every chart but chart 1 has a known person in box 2 or 3, and an empty box appears only inside the requested range, where a known line runs out. A continuation number may name a chart that already exists, which obeys the same limit. `tests/test_generations.py` checks this for every root of the fixtures and of generated trees, at every limit from 1 to 9 and none, in both print sizes and both parent modes. The privacy estimate always uses the unlimited plan, so nobody's status depends on `N`.

## Fan chart

`fanplan.plan_fan` turns a tree into a `Fan`. `fanpdf.render_fan` draws a
supplied fan, without choosing ancestors, writing years or assigning colors.
It returns one page of PDF bytes. `Fan`, `FanCell` and `LegendEntry` in
`fan.py` hold the cells, legend, highlight and name.

### Checks and geometry

`fan.check_fan` runs before drawing. Generations are an integer from 2 to 7,
counting the center as 1. Booleans are not generations or slots. Slots are
integers from 1 to `2**generations - 1`, with no duplicates. Every cell except
slot 1 has a nonempty child cell at `slot // 2`. Every fill and legend color
is `None` or `#` followed by six hex digits, in either case. Every highlighted
slot has a cell. A failure raises `ValueError` naming the field and value.
`render_fan` also checks ink and paper against `INKS` and `FAN_PAPER`.

`fan.ring_of(slot)` is `slot.bit_length() - 1`; the position within that ring
is `slot - 2**ring`. The center is a disc; each other cell is an annular
sector. Fathers have twice their child's slot, mothers twice plus one.
`cell_angles` splits the 240° span into equal parts in each ring, from 210° on
the left to −30° on the right, measured counterclockwise from 3 o'clock. The
bottom gap is 120°.

`RING_DEPTHS` and `RING_TEXT_SIZES` in `fan.py` use thousandths of the full
seven-generation radius. `ring_radii` sums the depths, and `fan_radius`
gives the requested outer radius.

| Ring | Cells | Depth | Text size | Direction |
|---|---|---|---|---|
| 0 | 1 | 125 (disc radius) | 27 | level |
| 1 | 2 | 88 | 26 | along the ring |
| 2 | 4 | 87 | 25 | along the ring |
| 3 | 8 | 125 | 23 | along the ring |
| 4 | 16 | 160 | 21.5 | radial |
| 5 | 32 | 190 | 20.5 | radial |
| 6 | 64 | 225 | 19.5 | radial |

`fanpdf.page_layout` scales these units together to fill the region below the
title and above the footer. It centers the fan horizontally. The fan is twice
its radius wide and 1.5 times its radius tall, except at two generations,
where the center disc extends lower than the sectors. For outer radius `R`,
the height is `R + max(R / 2, 125 * units)`, where `units = R /
fan_radius(generations)`. The full radius is the smaller of half the page
width between margins and the region height divided by `1 + max(0.5, 125 /
fan_radius(generations))`. The top of the fan stays at the region's top when
the legend shrinks it. `FAN_PAPER` holds landscape sizes in points: Letter 792
× 612, A4 841.89 × 595.28, Tabloid 1224 × 792 and A3 1190.55 × 841.89. Margins
are `MARGIN` (36 pt). Fewer generations scale up, keeping relative ring depths
and text sizes. At seven generations on Letter, text is about 9 pt in the
center and 6.6 pt in the outer ring.

### Text and fitting

`fan.full_name` keeps supplied case, joins title, given names and surname with
single spaces, and adds the suffix after a comma. `name_lines` splits before
the surname. `text_candidates` tries the full name and years on two lines,
then three lines with the split name, then the same forms condensed by up to
7%. Next come initials for given names after the first, forms without years,
and the shortest forms cut with the language's ellipsis. Without years, full
and split names precede their initial forms. The cut forms are the split
initial name, then the surname alone (or the initial given line when there is
no surname). A suffix that starts with a comma keeps its own comma. Initials
use the first letter in each later given name; a name with no letter stays as
supplied. Empty lines and duplicate candidates are omitted; empty cells have
no text.

`fanpdf.fit_cell` reserves room for a copy mark before trying candidates.
`_line_rooms` uses the disc's chord at each line's far edge for level text,
the arc at the line's inner edge for arc text, and the ring depth within the
wedge for radial text. Lines have `LEADING` (1.15 times the type size) and
`TEXT_MARGIN` (0.3 times the type size) at their edges. Every line must fit;
condensing never goes below `pdf.SQUEEZE` (0.93). The final cut forms use
`pdf.fit_squeezed`; lines cut to nothing are dropped, and at least one line
must remain. The first candidate that fits is drawn. Each line is centered in
its room; a cell with no text that fits draws no text.

For radial text, let `t` be a line's offset from the middle ray, `s` its type
size, `m = TEXT_MARGIN * s`, and `a` the sector angle. Its far edge is `e =
abs(t) + s / 2`. The room starts at `max(inner + m, e / tan(a / 2) + m)` and
ends at `sqrt(outer**2 - e**2) - m`, less the mark's length. This keeps text
inside both the wedge and the outer circle. Arc text fits within the ring
depth after margins and the mark's outer band. Level text sits below that band
and fits the disc chord at each line's far edge, less a margin at each end.

`fanpdf.text_direction` keeps arc labels flowing in one direction. Ring 0 is
level. Rings 1–3 read clockwise, with the first line outermost, including both
end cells of ring 3 below the horizontal. Their glyph tops face outward as the
arc passes below the horizontal. Rings 4–6 read outward on the right and inward
on the left. `_draw_line` places arc glyphs with
`pdf.char_advances`, which keeps the same kerning and widths as
`pdf.text_width`; each arc line is one text object, with a transform for each
glyph and the fitted horizontal scale. Level and radial text rotate the canvas
and use `pdf.draw_text`. The sans face holds cell text and the bold face holds
`×2`, `×3` and higher copy marks at the outer edge (`fan.mark_text`,
`fanpdf._mark_line`). Marks use `MARK_SCALE` (0.7 times the ring's type size).
`FanOptions.fonts` follows the rules of `Options.fonts`, and all drawn text
passes through `FontSet.clean`. A center mark is omitted if it cannot fit its chord at the
top of the disc.

### Ink, highlight and page text

`fanpdf._cell_ink` uses supplied fills. Color and grayscale have thin dark gray
outlines around filled cells. `SEPARATOR_WIDTH` is 0.5 pt, `EMPTY_DASH` is 2 pt
on and 2 pt off, and outline grays are 0.5 for unfilled or empty cells, 0.25 for
filled cells and 0.8 for faded grayscale cells, on a scale from black 0 to white 1.
Black and white ignores fills and the legend and outlines people in black.
Every blank position through the selected generations is unfilled, with a dashed
gray outline for writing in by hand. This includes positions beyond unknown
parents: the renderer draws their outlines without adding cells to the fan model,
whose planning still stops at unknown parents. Unfilled people have thin gray
outlines in color and grayscale.

With `Fan.highlight` set, other cells fade: color mixes one part fill with
three parts white; grayscale removes the fill and uses a pale outline.
Black and white doubles highlighted people's outlines. Empty cells keep
their usual dashed gray outline in every ink, even with a highlight.
`_text_color` chooses black or white by the higher WCAG contrast against the
fill as drawn, after fading; unfilled and black-and-white cells use black
text.

`page_layout` uses `FanOptions.title`, else `lang.fill` with `fan_title` and
`Fan.name`. The title sits top left in bold, fitted with the ellipsis; PDF
Title metadata keeps the full title. `pdf.footer_text` supplies the dated
footer, or the caller's text, or none with `footer=False`. It sits bottom
right, fitted with the ellipsis to the width between margins. The title is 16
pt, the footer 8 pt, with a 10 pt gap to the fan region at each end. Without a
footer the region reaches the bottom margin. The page has no page number.
`pdf.new_canvas` keeps the same document metadata and font setup as the
pedigree.

`fanpdf._legend_boxes` lays out supplied entries in order, column by column,
with a swatch, label and count in parentheses. A `None` color has an outlined
swatch; grayscale outlines every swatch in dark gray. The square's side is 0.8
times the type size, with a 4 pt gap before the label. Row height is 1.25
times the type size; columns have a 14 pt gap. The whole legend is centered
under the fan, with its bottom at the region's bottom. It tries `LEGEND_SIZES`
(9, 8.5, 8, 7.5, 7 pt), and at each size tries one column up to one per entry.
Boxes stay within the margins, above the footer, below the center disc, and
inside the bottom gap or below the fan's lowest point. Its top clears the
center disc by 6 pt. When its top is above the fan's lowest point, its
half-width must be at most `depth * tan(60°) - 6 pt`, where depth is the
distance below the center. If none fits, `page_layout` multiplies the radius
by `FAN_SHRINK` (0.95) and tries again, down to `MIN_FAN_SCALE` (0.25). A
legend that still cannot fit raises `ValueError` with its entry count; no
label is cut. Black and white draws no legend.

### Seating, years and colors

`fanplan.plan_fan` seats the root at 1 and walks breadth-first through the
requested generations. `Tree.parent_ids` uses the same parent-family choice as
the pedigree, with family partner 1 as father and partner 2 as mother. Missing
parents, IDs absent from the tree and step parents get empty cells, with no
cells above them. Each path seats its own copy of a person, with its own
ancestors, even in a loop; the generation limit bounds the walk at 127 cells.
Every copy's `copies` holds that person's total number of seats. Seating work
grows with seats visited, rather than all possible slots. Privacy also
computes the unlimited pedigree plan. Names come from the model, with
`Person.prefix` as the cell title and `lang.fmt_surname` formatting the surname.
Surnames are uppercase unless `preserve_case=True` keeps the recorded spelling;
private cells conceal the name before formatting. Caller-built fan cells are
already ready to draw and keep their supplied case.

`fanplan._years` joins birth and death parts with an en dash, using
`charts.birth_source` and `death_source` with `event_standins`. `_year_text`
takes the first structured year, keeping double years as `lang.format_date`
writes them. About, before/to, after/from and between/from-to use the
language's `years.about`, `before`, `after` and `between` words; an estimated
or calculated date with no form word uses about. Without a structured year,
the first isolated four-digit number in text supplies the year without a word.
`year_unknown` gives no year. `_event_years` prefixes a stand-in's
`years.christening`, `burial` or `cremation` word only when a year exists. A
death record or filled death stand-in without a year gives `years.deceased`.
When neither part has text, years are empty. English examples are `1820–1891`,
`chr 1852–`, `abt 1820–bur 1871` and `1840–Deceased`.

With `exclude_private`, `charts.living_checker` uses the unlimited pedigree
plan, the selected parent mode and today's year. Possibly living people
use the language's `Living` label and lose their years. The generated title and
filename use that label when the root may be living. A caller's `Person.living`
wins.

`fanplan._line_color` chooses by slot, so copies in different grandparent
lines take different fills. `LINE_COLORS` holds:

| Position or line | Color | Grayscale |
|---|---|---|
| Center | `#f7f8fa` | none |
| Father | `#e1e7ef` | none |
| Mother | `#f1e3e8` | none |
| Father's father | `#cddff4` | `#c8c8c8` |
| Father's mother | `#d3ecd9` | `#a6a6a6` |
| Mother's father | `#f6e3bf` | `#e4e4e4` |
| Mother's mother | `#f5d2dd` | `#b8b8b8` |

Black and white has no fills. The planner supplies no legend or highlight.
The grandparent cells name the four lines.

### Command line and config

`cli._mode_settings` decides the mode before mode checks or filtering:
`--blank`, then `--find`, then the merged `fan` setting, else pedigree.
`--fan` together with `--blank` is a usage error. Find runs check neither
chart mode's flags. Fan runs reject pedigree-only command-line flags and
generations outside 2 to 7. Pedigree and blank runs reject command-line ink,
Tabloid and A3. Config keys for the other chart type are ignored, as are
shared values the current mode cannot use: fan generations outside 2 to 7,
or pedigree/blank paper of Tabloid or A3. Ignored settings take the mode's
default and its default source in `--show-config`. `_check_setting` still
rejects values neither mode accepts, including generations below 1.

`cli._make_pedigree` reads the tree and resolves the root for either chart.
`_make_fan` calls the planner and renderer with the loaded language and
shared options. Both chart modes use `output_root_name(tree, root, *,
exclude_private=False, adoptive_parents=False, large_print=False,
living_name="Living")` for automatic filenames. It preserves the recorded name
spelling and applies the same unlimited-plan privacy estimate as the chart,
with the localized living label supplied by the CLI. `preserve_case` controls
chart text, default titles and PDF metadata; automatic filename spelling
does not depend on it. Explicit `-o` and config `output` paths are used as supplied.
`default_output_name`, `default_fan_output_name` and `blank_output_name` fill the
language's file-name template with the root name, capped at 100 characters and 200
UTF-8 bytes. They replace characters a file name cannot hold in the whole name and
add `.pdf`. An empty root name leaves the template's own words
(`cascading pedigree.pdf`), and a template with no words gives `Kincade.pdf`. The summary counts
requested generations and distinct people: each nonempty cell contributes
`1 / copies`, and the sum is rounded. `_write_pdf` writes either chart.

## Layout constants

Every layout number is a named constant in the "Page layout" section of `pdf.py`, in points from the top left. `page_geom(paper, large_print, shadow)` derives the rest and returns a cached, frozen `PageGeom`, which every drawing function takes.

- Paper (`PAPER_SIZES`): Letter 612 × 792, A4 595.28 × 841.89.
- Columns (`column_layout`): box 1 at `LEFT_X` (30), each further left generation `COLUMN_STEP` (43) to the right, the right column `ZONE_CLEARANCE` (27) beyond them, and every box as wide as the right edge allows. In normal print the right edge is `RIGHT_EDGE` (573): boxes are 215 pt wide, at x = 30, 73, 116 and 358. In large print it is `RIGHT_EDGE_INSET` (39) from the page edge: 236.5 pt boxes on Letter, 228.1 pt on A4.
- Rows (`_box_tops`): the right column fills the height from `Y_TOP` (42) to `BOTTOM_INSET` (55.5) above the foot of the page with equal gaps. Other boxes are centered between their parents' facing edges so unequal box heights still leave equal gaps. The root is centered between the edges of its nearest left-zone neighbors (boxes 5 and 6 in normal print, 2 and 3 in large print), including on continuation and blank charts. The initial root keeps that center when enlarged for its spouse row.
- Boxes: the initial root, filled or blank, has eight lines (88 pt), including its localized `labels.spouse` row. It expands by one `LEADING` and sits midway between the edges of its neighboring left-zone boxes. The spouse label uses the detail face and size; its name uses the name face at 90% of the root name size. Cached `box_height(1)` stays 78 pt: continuation roots and fathers keep seven lines (78 pt); mothers keep five (58 pt), from `NAME_BASE`, `DETAIL_GAP`, `LEADING` and `BOTTOM_PAD`. Text is fitted into `TEXT_WIDTH` (207 pt), between `TEXT_INSET_LEFT` (5) and `TEXT_INSET_RIGHT` (3).
- Large print: box text is `LARGE_SIZE` (14) instead of `SIZE` (9), and the box metrics, record ID, box numbers and continuation numbers scale by `LARGE_SCALE` (14/9). The header, footer and index keep their sizes. A record ID's cap top aligns with its name's cap top, using the sans face's cap height (Helvetica's ascent in the built-in fonts).
- Shadows (`shadow_reach`): the bottom edge rises by the shadow's reach, and the right edge moves in only where a shadow would cross the right margin (A4 in normal print: 214.6 pt boxes).
- Index (`INDEX_*`): three columns 10 pt apart between `LEFT_MARGIN` and `RIGHT_MARGIN` (185 pt wide on Letter), 8 pt serif on 10 pt leading, wrapped lines indented 10 pt.

## The privacy estimate

With `exclude_private`, possibly living people use the language's `Living` label
and have no event details or printed record IDs, even with `show_ids`. They are
omitted from the pedigree name index. The top-level language key `living_name`
is `Living` in English and `Lebende Person` in German. Generated filenames, the default
default chart titles and PDF metadata conceal a possibly living root name; explicit titles
and output paths are used as supplied. CLI search and ambiguous-root lists hide
living names and years while retaining record IDs. The browser root picker
keeps original names for local selection and hides living years.

`charts.living_checker` decides who may be living. `Person.living`, when a library caller sets it, wins. Otherwise any `DEAT` (an empty one too), `BURI` or `CREM` record means not living. Otherwise the person may be living when the estimate of their latest birth year is missing or later than `this_year - LIVING_YEARS` (100). Display options never change the verdict.

`latest_birth_year` reads a date at its latest: the later end of a range, the year of a before or to date, ten years more (`ABOUT_MARGIN`) for an approximate, estimated or calculated date, and the second year of a double date. A date whose year cannot be read (`Date.year_unknown`: a calendar the reader cannot convert, a number that is no year) and an open after or from date give this year. `INT d (phrase)` gives the later of the two readings.

`_birth_estimates` estimates everyone in the unlimited plan, taking the first of these that applies:

1. The person's own `BIRT` date (`_own_birth_year`). A recorded birth date that gives no year counts as this year, and nothing overrides it.
2. With no `BIRT` date, the christenings and baptisms: the earliest of their latest years (`_christening_bound`). If they are dated but none gives a year, this year.
3. The descendants: the latest, over every dated descendant, of the descendant's year minus `GENERATION_YEARS` (25) per generation. The walk goes breadth-first over people, so pedigree collapse only adds paths, and it follows only birth links (`Tree.is_birth_parent`), per parent: an adopted, foster, step or other parent gets no estimate from that child.

An open-ended birth (`AFT x`, `FROM x` with no `TO`, and the text shapes `after x`, `since x` and `from x`) skips step 1: it takes the descendants' estimate, but never earlier than x + 1 after "after", or x after "from" or "since". With nothing dated below, or no year x, it is this year.

`--find` and the ambiguous `--root` list call `living_checker` with no charts, so they use each person's own records only. `--find` appends indented spouse-family rows after each matched person. Families follow FAMS order, then actual partner families missing that backlink, without duplicates. Only the exact first FAMS family is marked `(default)`. Each row retains its family record ID, applies surname case and localized name/date settings, and hides marriage details when either partner may be living. The browser picker and ambiguous-root rows keep their person-only format.

## Recognized date shapes

`gedcom.parse_date` reads the GEDCOM date grammar. For the index year
(`lang.year_of`), sorting, the privacy estimate and `--find`, text outside that
grammar gives a year only when the whole text matches a shape of `model.text_date`.
This includes free text in `DATE`, a phrase that is a date's only reading, and the
phrase of `INT`. Its docstring lists each shape and what it means. Fan display
years also accept an isolated four-digit number through `fanplan._year_text`.
`gedcom._UNREAD_CALENDAR` and `_UNREAD_NUMBER` mark a date whose calendar or
numbers are no years of ours as `year_unknown`.

## Index sort key

`pdf.build_index` sorts the entries by:

1. whether the surname is empty or a placeholder such as `(UNKNOWN)` (`lang.is_placeholder_surname`): these go last;
2. the surname's key, then the given name's (without the prefix);
3. the year of the birth, or of the christening standing in for it when the stand-ins are on; a missing or hidden year sorts after every year;
4. the suffix's key, then the record ID.

`lang.SortRules.fold` makes each key from the name as stored, never from its printed capitals: casefold and NFC; for a surname, drop an elided particle (an `ignore_particles` item ending in an apostrophe, such as `d’`) from the front when letters follow it, matching either apostrophe; drop punctuation, with a hyphen or dash (Unicode Pd) becoming a space, so a hyphenated name files word by word; for a surname, the remaining `ignore_particles` as whole words or phrases of words, longest first, again and again, never the last word, then `mc_as_mac`; apply `expand` in one pass, longest key first; replace each `after_z` letter, including letters produced by an expansion, by a private-use character from U+E000, which sorts after z and after the `~` of an expansion; then NFKD, dropping the combining marks. An expansion such as `"aa" = "å"` sorts with Å when `after_z` includes `å`. The sort changes no spelling; only the skipped particles' case and place print differently, as above.

Each entry ends with the boxes where the person is drawn, each from the language's `index.reference` template (`{chart}-{pos}`, German `{chart}/{pos}`), joined by commas.

## Dates in words

`lang.format_date` words a structured date: the qualifier words of `[dates]` before the date, the day from the `[days]` table (else its number), the month from `months.short`, and `date_format` for a full date. Before a date with a day, a word listed in `[dates.with_day]` replaces its plain form (French `avant le 3 mars 1990`, but `avant 1990`). Last, each phrase of `[dates.rewrite]` is replaced where it stands as whole words, longest first, in one pass: Italian elides `dal 8` to `dall’8`. Fan years use the `[years]` templates instead.

## Fonts

`Options.fonts` is `"auto"` (always, on the command line), `"base14"` or a `FontSet` of four roles: sans (the name line, the chart label, the footer and the other small text), bold (the title and box numbers), serif (the detail lines and the index) and italic (the continuation numbers).

`kincade.lang.KincadeWarning` is a `UserWarning` subclass. Unknown language keys
and automatic font fallback use `warnings.warn(..., stacklevel=2)`. Library
callers can capture or filter them with Python's `warnings` module. The CLI
handles only this category for each invocation and immediately prints
`kincade: warning: <message>` to stderr, forwarding other categories to the
previous warning handler.

- `"auto"` (`choose_fonts`) takes the first of each role's candidates in `FONT_FILES` that it finds: Helvetica, else Arial, else Liberation Sans; Times New Roman, else Liberation Serif. It searches the system and user font folders of macOS, Linux and Windows. Before reportlab parses a face, `subset_embeddable` checks its OS/2 `fsType` and refuses a restricted, no-subsetting or bitmap-only face. If any role is missing or refused, the whole document uses the base-14 fonts, never a mix, and `choose_fonts` emits a `KincadeWarning`. `load_fontset` makes the same search and prints nothing: it returns the `FontSet`, or `None` and the roles it could not fill, for a library caller to pass as `Options(fonts=...)`.
- Embedded faces are subsets, and text keeps its Unicode. A character the faces lack loses its accents, else becomes `?` (`FontSet.clean`); with the base-14 fonts that leaves only cp1252.
- reportlab does not kern TrueType text, so `pdf.py` reads each face's `kern` table and draws each line in runs, and every width is measured with the kerning. A malformed table gives no kerning. The base-14 fonts are not kerned.
- GEDCOM parsing and PDF text cleaning use `model.strip_controls`: whitespace
  stays, and other Unicode control characters are removed. The PDF maps
  whitespace to spaces before fitting text.
- Printed places have trimmed comma-separated parts, empty parts omitted, and a comma and space between parts, before fitting and shortening. The model keeps the recorded place. The country-shortening context retains the initial root's default first-FAMS marriage, even when `root_family` selects another marriage, so ancestor and continuation place text stays unchanged.
- A line that is too wide is condensed by up to 7% (`SQUEEZE`), then cut with the language's ellipsis (`fit_squeezed`). A relationship note stays whole: the name is cut before it.
