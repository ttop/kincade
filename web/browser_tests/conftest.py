"""Real built site, external browser and deterministic worker-boundary helpers."""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic
from urllib.parse import urlencode, urlsplit

import pytest
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "web/.cache/browser-tests"
CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; "
    "worker-src blob:; connect-src 'self' https://cdn.jsdelivr.net https://pypi.org https://files.pythonhosted.org; "
    "style-src 'unsafe-inline'; frame-src blob:; object-src blob:; img-src 'self' data:"
)


@pytest.fixture(scope="session")
def site_files():
    CACHE.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "UV_CACHE_DIR": str(ROOT / "web/.cache/uv")}
    with tempfile.TemporaryDirectory(dir=CACHE, prefix="site-") as destination:
        # Use the existing build functions with a fresh destination; never replace
        # web/site or the wheel a developer's existing HTTP server is serving.
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from pathlib import Path; from web.build import build_wheel, assemble_site, check_site; "
                "wheel = build_wheel(); site = Path(sys.argv[1]); assemble_site(wheel, site); check_site(site, wheel.name)",
                destination,
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        files = {p.name: p.read_bytes() for p in Path(destination).iterdir()}
    assert len(files) == 2
    return files


@pytest.fixture(scope="session")
def site(site_files):
    files = site_files

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parts = urlsplit(self.path).path.strip("/").split("/")
            variant = parts[0] if len(parts) > 1 else "clean"
            name = parts[-1] or "index.html"
            if name == "favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if name == "away":
                data = b"<!doctype html><title>Away</title>Return with Back"
                mime = "text/html"
            elif name == "blocked-font":
                self.send_error(503, "Deliberately unavailable acceptance font")
                return
            else:
                data = files.get(name)
                if data is None:
                    self.send_error(404)
                    return
                mime = "text/html" if name == "index.html" else "application/zip"
                if name == "index.html" and variant in {"font-blocked", "font-hash"}:
                    text = data.decode()
                    start = text.index('<script id="manifest" type="application/json">')
                    start = text.index(">", start) + 1
                    end = text.index("</script>", start)
                    manifest = json.loads(text[start:end])
                    if variant == "font-blocked":
                        manifest["fonts"][0]["url"] = (
                            f"http://127.0.0.1:{self.server.server_port}/blocked-font"
                        )
                    else:
                        manifest["fonts"][0]["sha256"] = "0" * 64
                    data = (text[:start] + json.dumps(manifest) + text[end:]).encode()
                elif name.endswith(".whl") and variant == "wheel-bad":
                    data += b"deliberately mismatched acceptance wheel"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            if variant == "csp":
                self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture(scope="session")
def browser_context():
    CACHE.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(CACHE / "browsers"))
    with (
        tempfile.TemporaryDirectory(dir=CACHE, prefix="profile-") as profile,
        sync_playwright() as pw,
    ):
        launch = {"channel": os.environ.get("KINCADE_BROWSER_CHANNEL", "chromium")}
        if executable := os.environ.get("KINCADE_BROWSER_EXECUTABLE"):
            launch = {"executable_path": executable}
        context = pw.chromium.launch_persistent_context(
            profile,
            headless=os.environ.get("KINCADE_BROWSER_HEADED") != "1",
            viewport={"width": 1440, "height": 1000},
            accept_downloads=True,
            downloads_path=str(Path(profile) / "downloads"),
            args=["--host-resolver-rules=MAP kincade.test 127.0.0.1"],
            ignore_default_args=["--disable-back-forward-cache"],
            **launch,
        )
        context.set_default_timeout(15000)
        context.set_default_navigation_timeout(30000)
        yield context
        context.close()


class App:
    def __init__(self, page, site):
        self.page = page
        self.site = site
        self.errors = []
        self.failed_requests = []
        self.console_errors = []
        self.allow_font_failure = False
        self.lifecycle = deque(maxlen=40)
        self.lifecycle_started = monotonic()
        self.lifecycle_failed = set()
        self.lifecycle_listeners = []
        self.viewer_diagnostic_printed = False
        for emitter, events in (
            (
                page,
                ("close", "crash", "frameattached", "framenavigated", "framedetached"),
            ),
            (page.context, ("close",)),
            (page.context.browser, ("disconnected",)),
        ):
            if emitter is None:
                continue
            for event in events:
                kind = (
                    "page"
                    if emitter is page
                    else "context"
                    if emitter is page.context
                    else "browser"
                )
                name = f"{kind}.{event}"

                def record(value=None, name=name):
                    if name in {
                        "page.close",
                        "page.crash",
                        "context.close",
                        "browser.disconnected",
                    }:
                        self.lifecycle_failed.add(name)
                    self.lifecycle.append(
                        {
                            "event": name,
                            "seconds": round(monotonic() - self.lifecycle_started, 3),
                            "url": getattr(value, "url", None),
                        }
                    )

                emitter.on(event, record)
                self.lifecycle_listeners.append((emitter, event, record))
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda req: self.failed_requests.append(f"{req.url}: {req.failure}"),
        )
        page.on(
            "console",
            lambda msg: (
                self.console_errors.append(msg.text) if msg.type == "error" else None
            ),
        )
        page.add_init_script(path=ROOT / "web/browser_tests/instrument.js")

    def start(self, variant="clean", ready=True, insecure=False, gates=()):
        self.allow_font_failure = variant == "font-blocked"
        url = self.site.replace("127.0.0.1", "kincade.test") if insecure else self.site
        query = "?" + urlencode({"acceptanceHold": ",".join(gates)}) if gates else ""
        self.page.goto(f"{url}/{variant}/index.html{query}")
        if ready:
            try:
                expect(self.page.locator("#status")).to_have_text(
                    "Ready", timeout=120000
                )
            except AssertionError as error:
                raise AssertionError(
                    f"Bootstrap failed: {self.page.locator('#status').inner_text()}\nNetwork: {self.failed_requests}\nConsole: {self.console_errors}"
                ) from error

    def sample(self):
        self.page.locator("#sample").click()
        self.pdf_ready()
        expect(self.page.locator("#root-summary")).to_have_text(
            "Root: I1, George WASHINGTON"
        )

    def sent(self, kind):
        return self.page.evaluate(
            "kind => acceptance.sent.filter(x => x.type === kind)", kind
        )

    def replies(self, kind):
        return self.page.evaluate(
            "kind => acceptance.replies.filter(x => x.type === kind)", kind
        )

    def hold(self, kind):
        self.page.evaluate("kind => acceptance.hold(kind)", kind)

    def held(self, kind, count=1):
        self.page.wait_for_function(
            "([kind, count]) => acceptance.held.filter(x => x.event.data.type === kind).length >= count",
            arg=[kind, count],
            timeout=120000 if kind == "ready" else 15000,
        )

    def release(self, kind):
        self.page.evaluate("kind => acceptance.release(kind)", kind)

    def release_one(self, kind, seq=None):
        self.page.evaluate(
            "([kind, seq]) => acceptance.releaseOne(kind, seq)", [kind, seq]
        )

    def pdf_ready(self):
        expect(self.page.locator("#download-pdf")).to_have_attribute(
            "href", re.compile("^blob:"), timeout=30000
        )
        expect(self.page.locator("#pdf-section")).to_have_attribute(
            "aria-busy", "false", timeout=30000
        )

    def dispose(self):
        for emitter, event, callback in self.lifecycle_listeners:
            emitter.remove_listener(event, callback)
        self.lifecycle_listeners.clear()

    @contextmanager
    def viewer_diagnostics(self):
        try:
            yield
        except (BrowserError, AssertionError):
            if not self.viewer_diagnostic_printed:
                self.viewer_diagnostic_printed = True
                browser = self.page.context.browser
                print(
                    "Native PDF lifecycle: "
                    + json.dumps(
                        {
                            "page_closed": self.page.is_closed(),
                            "fatal_events": sorted(self.lifecycle_failed),
                            "browser_connected": browser.is_connected()
                            if browser
                            else None,
                            "frames": [
                                {"url": f.url, "detached": f.is_detached()}
                                for f in self.page.frames
                            ],
                            "events": list(self.lifecycle),
                        }
                    )
                )
            raise

    def viewer_parent_live(self, source, deadline):
        browser = self.page.context.browser
        assert not self.lifecycle_failed, sorted(self.lifecycle_failed)
        assert not self.page.is_closed(), "Native PDF parent page closed"
        assert browser is not None and browser.is_connected(), (
            "Native PDF browser disconnected"
        )
        # A real parent round trip proves that a child TargetClosedError was not
        # a lost/crashed parent or context. Keep the captured Blob identity too.
        current = self.page.locator("#pdf-frame").get_attribute(
            "src", timeout=max(1, min(15000, (deadline - monotonic()) * 1000))
        )
        assert current == source, (
            f"Native PDF source changed: {source!r} -> {current!r}"
        )

    def native_viewer(self):
        with self.viewer_diagnostics():
            source = self.page.locator("#pdf-frame").get_attribute("src")
            assert source, "Native PDF source unavailable"
            deadline = monotonic() + 35
            discovery_deadline = monotonic() + 5
            while monotonic() < discovery_deadline:
                for frame in self.page.frames:
                    try:
                        if not frame.locator("pdf-viewer").count():
                            continue
                        original = frame.locator("pdf-viewer").evaluate(
                            "e => e.shadowRoot?.querySelector('#plugin')?.getAttribute('original-url')",
                            timeout=max(1, min(15000, (deadline - monotonic()) * 1000)),
                        )
                        if original is not None and original != source:
                            continue
                        self.viewer_parent_live(source, deadline)
                        frame.wait_for_function(
                            """source => {const e = document.querySelector('pdf-viewer');
                            return e.initialLoadComplete_ &&
                              e.shadowRoot.querySelector('#plugin')?.getAttribute('original-url') === source;}""",
                            arg=source,
                            timeout=max(1, (deadline - monotonic()) * 1000),
                        )
                        self.viewer_parent_live(source, deadline)
                        return frame
                    except BrowserTimeout:
                        raise
                    except BrowserError:
                        browser = self.page.context.browser
                        if (
                            frame is self.page.main_frame
                            or not frame.is_detached()
                            or self.lifecycle_failed
                            or self.page.is_closed()
                            or browser is None
                            or not browser.is_connected()
                        ):
                            raise
                        self.viewer_parent_live(source, deadline)
                        # Rediscover only a concretely detached child, within
                        # the original total budget even if readiness began.
                        discovery_deadline = min(deadline, monotonic() + 5)
                self.viewer_parent_live(source, deadline)
                self.page.wait_for_timeout(100)
            raise AssertionError("External Chrome native PDF viewer unavailable")

    def assert_one_page(self):
        with self.viewer_diagnostics():
            viewer = self.native_viewer()
            width = self.page.locator("#pdf-frame").evaluate("e => e.clientWidth")
            viewer.wait_for_function(
                "w => document.querySelector('pdf-viewer').viewport_.size.width === w - 1",
                arg=width,
            )
            geometry = viewer.locator("pdf-viewer").evaluate(
                """e => {const v = e.viewport_; const first = v.getPageScreenRect(0);
                const next = v.pageDimensions_.length > 1 ? v.getPageScreenRect(1) : null;
                return {height:v.size.height, firstBottom:first.y + first.height,
                  secondTop:next?.y, zoom:v.getZoom()};}"""
            )
            assert geometry["height"] >= geometry["firstBottom"] - 1, geometry
            assert geometry["height"] <= geometry["firstBottom"] + 16, geometry
            if geometry["secondTop"] is not None:
                assert geometry["height"] <= geometry["secondTop"], geometry
            return viewer

    def change(self, selector, value):
        before = len(self.replies("rendered"))
        field = self.page.locator(selector)
        tag, kind = field.evaluate("e => [e.tagName, e.type]")
        if kind == "checkbox":
            field.set_checked(value)
        elif tag == "SELECT":
            if selector == "#pedigree-generation-choice" and str(value).isdigit():
                # Playwright string values also match labels: ordinal 4 must
                # choose the fifth preset, rather than the first label "4".
                field.select_option(index=int(value) + 1)
            else:
                field.select_option(str(value))
        else:
            field.fill(str(value))
        self.wait_render(before)
        self.pdf_ready()

    def generations(self, value, wait=True):
        before = len(self.replies("rendered"))
        choice = self.page.locator("#pedigree-generation-choice")
        if choice.input_value() != "custom":
            choice.select_option("custom")
        disclosure = self.page.locator("#more-options")
        if not disclosure.evaluate("e => e.open"):
            disclosure.locator("summary").click()
        self.page.locator("#pedigree-generations").fill(str(value))
        if wait:
            self.wait_render(before)
            self.pdf_ready()

    def chart(self, chart):
        before = len(self.replies("rendered"))
        self.page.locator(f"#chart-{chart}").check()
        self.wait_render(before)
        self.pdf_ready()

    def wait_render(self, before):
        try:
            self.page.wait_for_function(
                "n => acceptance.replies.filter(x => x.type === 'rendered').length > n",
                arg=before,
            )
        except BrowserTimeout as error:
            raise AssertionError(
                f"Render failed: {self.page.locator('#request-error').text_content()}\nReplies: {self.page.evaluate('acceptance.replies')}\nConsole: {self.console_errors}"
            ) from error

    def upload(self, data=None, name="synthetic.ged"):
        before = len(self.replies("opened"))
        searches = len(self.replies("results"))
        if data is None:
            self.page.locator("#file").set_input_files(
                ROOT / "tests/fixtures/pedigree.ged"
            )
        else:
            self.page.locator("#file").set_input_files(
                {"name": name, "mimeType": "application/octet-stream", "buffer": data}
            )
        self.page.wait_for_function(
            "n => acceptance.replies.filter(x => x.type === 'opened').length > n",
            arg=before,
        )
        self.page.wait_for_function(
            "n => acceptance.replies.filter(x => x.type === 'results').length > n",
            arg=searches,
        )

    def select(self, record="I1", wait=True):
        # Reopen even when Search kept focus after selection or a file drop.
        self.page.locator("#search").click()
        choice = self.page.locator(f'#results button[data-record-id="{record}"]')
        if not choice.count():
            self.page.locator("#search").fill(record)
        choice.click()
        if wait:
            self.pdf_ready()

    def pdf(self):
        self.pdf_ready()
        # Download is a product action; fetching a Blob in test JS would add a
        # connect-src requirement the actual page does not have.
        with self.page.expect_download() as download:
            self.page.locator("#download-pdf").click()
        return PdfReader(io.BytesIO(Path(download.value.path()).read_bytes()))

    def download(self):
        with self.page.expect_download() as download:
            self.page.locator("#download-pdf").click()
        result = download.value
        data = Path(result.path()).read_bytes()
        assert PdfReader(io.BytesIO(data)).pages
        return result.suggested_filename


@pytest.fixture
def app(browser_context, site):
    page = browser_context.new_page()
    page.set_viewport_size({"width": 1440, "height": 1000})
    app = App(page, site)
    yield app
    try:
        assert not app.errors, app.errors
        unexpected_console = [
            error
            for error in app.console_errors
            if not (app.allow_font_failure and "503" in error)
        ]
        assert not unexpected_console, unexpected_console
        assert not page.evaluate("window.acceptance?.violations || []")
    finally:
        app.dispose()
        page.close()


def text(pdf):
    return "\n".join(page.extract_text() for page in pdf.pages)


def content(pdf):
    return b"\n".join(page.get_contents().get_data() for page in pdf.pages)


def embedded_fonts(pdf):
    names = set()
    for page in pdf.pages:
        for reference in page["/Resources"]["/Font"].values():
            font = reference.get_object()
            if "/FontDescriptor" in font and "/FontFile2" in font["/FontDescriptor"]:
                names.add(str(font["/BaseFont"]))
    return names
