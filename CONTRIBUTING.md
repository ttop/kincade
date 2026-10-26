# Contributing to Kincade

## Setup

Kincade uses [uv](https://docs.astral.sh/uv/). In a clone:

```sh
uv sync            # Python 3.11 or later, reportlab and the dev tools
uv run pytest -q   # the test suite, a few seconds
```

## Tests

- Every test runs isolated from the machine, by the autouse fixture in `tests/conftest.py`. The working folder is an empty temporary folder, and the home folder (`HOME`, and `USERPROFILE` for Windows) is an empty folder inside it, for subprocesses too. There is no per-user config file or language folder, and reportlab's `RL_*` overrides are cleared. `fonts="auto"` gives the base-14 fonts, silently, so no result depends on the fonts a machine has.
- A test marked `@pytest.mark.system_fonts` lets `fonts="auto"` search for TrueType fonts as it does outside the tests. Use the marker only for tests of the font search and of embedding; `uv run pytest -q -m "not system_fonts"` leaves them out.
- CI runs on Ubuntu, macOS and Windows with Python 3.11 and 3.14, on pushes and pull requests. It installs the locked dependencies and runs pytest, ruff check, ruff format --check and mypy. Ubuntu installs Liberation fonts. The full pytest run includes `system_fonts` tests; tests that require embedded fonts skip when none are available.
- Test fixtures are invented. The GEDCOM files in `tests/fixtures/` and every tree
  a test builds use made-up names, such as Jane Doe. Never commit private family
  records. Public historical examples belong in `docs/examples/` and use
  publicly available genealogical facts.
- The doc tests (`tests/test_docs.py`) run the Python examples in the library guide
  (`docs/library.md`) and package docstring, and check that `kincade.example.toml`
  is a valid config file that names every key. A new config key needs an entry in
  the example file.

## Lint, format and types

```sh
uv run ruff check
uv run ruff format   # add --check to report without changing anything
uv run mypy
```

All three are clean, and every commit keeps them clean. `ruff format` lays out the code at 88 columns; wrap comments and docstrings at 88 columns by hand.

## Writing

- American spelling: license, behavior, color, centered.
- "config file" and "record ID" (`I12`, which GEDCOM writes as `@I12@`).
- Docs, comments, docstrings, help text and messages describe what the code does, in the present tense. What changed and why goes in the commit message, and a change that users will notice goes in [CHANGELOG.md](CHANGELOG.md) as well.

## The samples

`docs/examples/` holds a seven-generation pedigree and fan chart for George
Washington, a blank chart, and PNG previews. The source is
[george-washington.ged](docs/examples/george-washington.ged). Unknown or disputed
ancestry remains unfilled.
The examples use the base-14 fonts and reportlab's invariant mode so the same
code makes the same bytes. From the repository root, with Poppler's `pdftoppm`
and `pngquant`:

```sh
uv run python - <<'PY'
from datetime import date
from pathlib import Path

from reportlab import rl_config

from kincade import (
    FanOptions, Options, plan_fan, read_gedcom, render, render_blank, render_fan,
)

rl_config.invariant = 1  # a fixed creation date and document ID
# today fixes the footer date
options = Options(generations=7, fonts="base14", today=date(2026, 10, 14))
tree = read_gedcom("docs/examples/george-washington.ged")
Path("docs/examples/cascading-pedigree.pdf").write_bytes(render(tree, "I1", options))
Path("docs/examples/blank-chart.pdf").write_bytes(render_blank(options))
fan = plan_fan(tree, "I1", generations=7)
fan_options = FanOptions(fonts="base14", today=date(2026, 10, 14))
Path("docs/examples/fan-chart.pdf").write_bytes(render_fan(fan, fan_options))
PY
pdftoppm -f 1 -l 1 -r 200 -x 26 -y 31 -W 1645 -H 2081 -png -singlefile docs/examples/cascading-pedigree.pdf docs/examples/chart1
pdftoppm -f 1 -l 1 -r 150 -png -singlefile docs/examples/fan-chart.pdf docs/examples/fan-chart
pngquant --force --ext .png docs/examples/chart1.png
pngquant --force --ext .png docs/examples/fan-chart.png
```

## Browser page

Build and serve from the repository root:

```sh
uv run python web/build.py
python3 -m http.server -d web/site 8000
```

Open `http://localhost:8000/`. The output contains exactly `index.html` and one
Kincade wheel; publish both from the same build, keeping their filenames and
relative placement. [web/README.md](web/README.md) documents copying that folder,
dependency origins, the GitHub Pages setting and CSP checks.

### Automated acceptance

Install the optional browser tools and full Chromium once:

```sh
uv sync --locked --group browser
PLAYWRIGHT_BROWSERS_PATH=web/.cache/browser-tests/browsers uv run --group browser playwright install --no-shell chromium
```

Run the complete browser acceptance command after changes to `web/`,
`PYODIDE_VERSION`, `web/fonts.json` or locked reportlab, and before merging or
publishing:

```sh
uv run --locked --group browser pytest -q web/browser_tests
```

The suite builds the fresh two-file site, serves it on a temporary port, launches
an isolated full Chromium profile, and runs real Pyodide, Kincade and font downloads.
It needs network access to the pinned dependency origins. Missing browser binaries
or failed downloads fail with diagnostics. Native CPython tests remain separate
and run without browser dependencies. [Browser acceptance](docs/browser-acceptance.md)
describes coverage, browser selection and the scope of HTTP checks.

The harness observes and holds real Worker messages, which one journey uses to
check render ordering. The journeys check real PDF bytes, text and fonts as well as
page behavior; the harness adds no testing hooks to the deployed page. Profiles and build caches live under
ignored `web/.cache/`; each profile and HTTP server are cleaned up after the run.
For a browser finding, add a test at the worker boundary in
`tests/test_web_worker.py`, fix the owning source, and rerun the Python tests and the
journeys before committing. Extend a journey only for behavior only the browser shows.

### Dependency updates

- **Pyodide:** change `PYODIDE_VERSION` in `web/build.py`; the CDN base URL is
  derived from it. Rebuild and rerun automated acceptance, including CSP and
  plain HTTP. Check the pinned URL and browser console/network evidence when
  loading fails before changing the runtime version.
- **Fonts:** verify all four files against the intended upstream Liberation
  release, then update their URLs and SHA-256 values in `web/fonts.json`. Keep
  the four filenames used by `FONT_FILES`. An intentional CDN/package version
  change also updates `FONT_BASE` validation in `web/build.py`. Rebuild and
  rerun automated acceptance, especially embedded fonts and font fallback.
- **reportlab:** use `uv lock --upgrade-package reportlab` within the dependency
  range in `pyproject.toml`. The build derives the exact requirement from
  `uv.lock`; do not add a separate version constant. Run the Python checks,
  rebuild, and rerun automated acceptance for both charts and every ink choice.

## Design

[docs/design.md](docs/design.md) describes the module layering and the rules the code keeps.
