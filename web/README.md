# Building and hosting the browser page

The page makes cascading pedigree and fan chart PDFs with Kincade in a browser
worker. GEDCOM bytes and generated PDFs stay in the browser.

## Build and serve

From the repository root, with [uv](https://docs.astral.sh/uv/):

```sh
uv run python web/build.py
python3 -m http.server -d web/site 8000
```

Open `http://localhost:8000/` in a browser. Serve the generated `web/site/` folder;
`web/index.html` is a source template. The build runs `uv build --wheel`, inlines
the page scripts, Python glue, manifest and example GEDCOM, and checks that the
output contains exactly these two files:

```text
web/site/
  index.html
  kincade-<version>-py3-none-any.whl
```

Here, `<version>` is the package version. The manifest records the wheel's filename
and SHA-256. The build itself needs uv and network access only if `uv build` must
fetch its build backend. Setting up uv's project environment for the first time
can also need network access to install the locked dependencies. Building does
not fetch Pyodide, reportlab's browser wheel or the fonts.

## Copy to another site

Copy only the generated `index.html` and wheel into one folder on the other static
site, preserving both filenames. Publish them together from the same build. The
wheel URL is relative to the HTML, so the folder works at a site's root or under a
subfolder such as `static/kincade/`. No other build files are needed at the host.

The browser checks the wheel's SHA-256 before installing it. If the files come
from different builds, initialization reports the site-wheel failure and asks the
reader to reload; Retry reloads the page. Replace both files together if reloading
does not resolve it.

## First load and dependencies

The first visit downloads approximately 11 MB of runtime, packages and fonts;
the browser's normal HTTP cache can reuse them on later visits. The page requires
network access for those external dependencies and has no offline mode. Its host
serves only the two generated files.

| Dependency | Browser source | Pin |
| --- | --- | --- |
| Kincade | Wheel beside `index.html` | Build manifest filename and SHA-256 |
| Pyodide, micropip, Pillow, charset-normalizer | `https://cdn.jsdelivr.net/pyodide/v314.0.7/full/` | `PYODIDE_VERSION` in `web/build.py` |
| reportlab | PyPI metadata at `pypi.org`, wheel at `files.pythonhosted.org`, through micropip | `reportlab==5.0.1`, derived from `uv.lock` |
| Liberation Sans Regular and Bold; Liberation Serif Regular and Italic | `https://cdn.jsdelivr.net/npm/@betteroffice/fonts@0.4.0/assets/` | Each URL and SHA-256 in `web/fonts.json` |

The four font assets are byte-identical to Liberation 2.1.5 and use the SIL Open
Font License 1.1. The page checks their hashes before registering them. If any
font is unavailable or does not match, it uses the built-in PDF fonts and names
that fallback in the PDF summary. Those fonts cover Windows-1252; other
characters lose accents or become `?`.

## Update dependencies

- **Pyodide:** update `PYODIDE_VERSION` in `web/build.py`. The build derives the
  runtime base URL from that version. Rebuild and rerun automated acceptance below,
  including CSP and plain HTTP.
- **Fonts:** update the four URLs and SHA-256 values in `web/fonts.json` after
  checking the assets against the intended upstream release. Keep the filenames
  that Kincade uses for its four font roles. `web/build.py` validates the pinned
  `FONT_BASE` and names; an intentional source/version change also updates that
  validation. Rebuild and repeat the embedded-font and fallback checks.
- **reportlab:** use `uv lock --upgrade-package reportlab` to update `uv.lock`
  within the dependency range in `pyproject.toml`. The build reads the locked
  version into the manifest; no separate reportlab version constant is needed.
  Rebuild and rerun automated acceptance, including both charts and all ink choices.

Run the Python suite, lint, formatting and typing checks after source or dependency
changes, and repeat the browser acceptance checks after changes to `web/`,
Pyodide, fonts or reportlab. Automated CPython and assembly tests do not confirm
browser behavior.

## Automated browser acceptance

From the repository root, install the optional tools and full Chromium:

```sh
uv sync --locked --group browser
PLAYWRIGHT_BROWSERS_PATH=web/.cache/browser-tests/browsers uv run --group browser playwright install --no-shell chromium
```

Run the full acceptance suite with one command:

```sh
uv run --locked --group browser pytest -q web/browser_tests
```

The suite builds and serves a fresh site on a temporary port and uses an isolated
external browser profile. It exercises the real pinned Pyodide runtime, reportlab,
Kincade wheel and font assets. Network access is required. Use
`KINCADE_BROWSER_CHANNEL=chrome` for an installed Chrome, or set
`KINCADE_BROWSER_EXECUTABLE` to a full compatible Chromium executable. Set
`KINCADE_BROWSER_HEADED=1` to see the isolated test browser. Browser installs,
profiles and caches stay in ignored `web/.cache/`; no existing user profile is used.
See [the acceptance guide](../docs/browser-acceptance.md) for coverage.

## Content Security Policy

The acceptance server sends this policy as a real HTTP response header and runs
initialization, search, both chart renders, preview and downloads under it:

```text
default-src 'none'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; worker-src blob:; connect-src 'self' https://cdn.jsdelivr.net https://pypi.org https://files.pythonhosted.org; style-src 'unsafe-inline'; frame-src blob:; object-src blob:; img-src 'self' data:
```

The tested policy omits `unsafe-eval`. It is an acceptance policy, not a claim
that every directive is the minimum possible for every browser. The suite records
policy violations and browser errors. Keep the pinned origins and rerun the suite
when changing the policy or runtime dependencies.

Plain HTTP acceptance maps `kincade.test` to the temporary server and asserts
`isSecureContext === false` before real initialization, integrity checks, rendering
and downloading both charts. This verifies the Python `hashlib` path without a
secure context; it does not represent a second physical device or LAN transport.
No manual browser matrix or second-device check is required by this suite.

## GitHub Pages

Once `ttop/kincade` is public, set its repository **Settings → Pages → Source** to
**GitHub Actions** before the first deployment expected to publish. This is the
repository-setting prerequisite.

The Pages workflow runs on pushes to `main` and manual `workflow_dispatch`.
Both jobs skip private repositories. First, its `browser` job calls the reusable
browser acceptance workflow at the same commit with only `contents: read`
permission. The `deploy` job runs only after that suite passes, then builds
`web/site/`, uploads that folder and deploys in the `github-pages` environment
with `contents: read`, `pages: write` and `id-token: write` permissions. Failed,
cancelled or skipped browser acceptance prevents building and publishing,
including on manual dispatch. The browser workflow still runs independently on
pushes, pull requests and manual dispatch, including in private repositories.
