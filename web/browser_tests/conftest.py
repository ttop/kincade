"""Real built site, external browser and deterministic worker-boundary helpers."""

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import pytest
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "web/.cache/browser-tests"


def _load_build_module():
    # Loaded by path, not `import build`, to avoid shadowing PyPA's `build` package.
    spec = importlib.util.spec_from_file_location(
        "kincade_web_build", ROOT / "web/build.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The page's own text in each language, as the built site carries it.
LANGUAGES = sorted(path.stem for path in (ROOT / "web/lang").glob("*.toml"))
MESSAGES = _load_build_module().read_messages(LANGUAGES)
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
            data = files.get(name)
            if data is None:
                self.send_error(404)
                return
            mime = "text/html" if name == "index.html" else "application/zip"
            if name == "index.html" and variant == "font-hash":
                text = data.decode()
                start = text.index('<script id="manifest" type="application/json">')
                start = text.index(">", start) + 1
                end = text.index("</script>", start)
                manifest = json.loads(text[start:end])
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
            locale="en-US",
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

    def start(self, variant="clean", ready=True, lang=None):
        """Open the page, with ?lang= when `lang` is given, and wait for Ready in that
        language, else English."""
        params = {"lang": lang} if lang else {}
        query = "?" + urlencode(params) if params else ""
        self.page.goto(f"{self.site}/{variant}/index.html{query}")
        if ready:
            try:
                expect(self.page.locator("#status")).to_have_text(
                    MESSAGES[lang or "en"]["status.ready"],
                    timeout=120000,
                )
            except AssertionError as error:
                raise AssertionError(
                    f"Bootstrap failed: {self.page.locator('#status').inner_text()}\nNetwork: {self.failed_requests}\nConsole: {self.console_errors}"
                ) from error

    def sample(self):
        self.page.locator("#sample").click()
        self.pdf_ready()
        expect(self.page.locator("#root-summary")).to_contain_text(
            ": I1, George WASHINGTON"
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
            timeout=15000,
        )

    def release(self, kind):
        self.page.evaluate("kind => acceptance.release(kind)", kind)

    def pdf_ready(self):
        expect(self.page.locator("#download-pdf")).to_have_attribute(
            "href", re.compile("^blob:"), timeout=30000
        )
        expect(self.page.locator("#pdf-section")).to_have_attribute(
            "aria-busy", "false", timeout=30000
        )

    def change(self, selector, value):
        before = len(self.replies("rendered"))
        field = self.page.locator(selector)
        tag, kind = field.evaluate("e => [e.tagName, e.type]")
        if kind == "checkbox":
            if field.is_checked() == bool(value):
                # Already in the requested state: setting it again fires no change
                # event, so there would be no render to wait for.
                return
            field.set_checked(value)
        elif tag == "SELECT":
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

    def upload(self):
        before = len(self.replies("opened"))
        searches = len(self.replies("results"))
        self.page.locator("#file").set_input_files(ROOT / "tests/fixtures/pedigree.ged")
        self.page.wait_for_function(
            "n => acceptance.replies.filter(x => x.type === 'opened').length > n",
            arg=before,
        )
        self.page.wait_for_function(
            "n => acceptance.replies.filter(x => x.type === 'results').length > n",
            arg=searches,
        )

    def select(self, record="I1"):
        # Reopen even when Search kept focus after selection or a file drop.
        self.page.locator("#search").click()
        choice = self.page.locator(f'#results button[data-record-id="{record}"]')
        if not choice.count():
            self.page.locator("#search").fill(record)
        choice.click()
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
    assert not app.errors, app.errors
    assert not app.console_errors, app.console_errors
    assert not page.evaluate("window.acceptance?.violations || []")
    page.close()


@pytest.fixture
def directory_site(site_files):
    """Emulate a static host's directory rewrite without redirecting the browser,
    serving the site mounted below a path."""
    mount = "/tools/kincade"
    wheel_name = next(name for name in site_files if name.endswith(".whl"))
    pages = {mount, mount + "/", mount + "/index.html"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in pages:
                data = site_files["index.html"]
                mime = "text/html"
            elif path == mount + "/" + wheel_name:
                data = site_files[wheel_name]
                mime = "application/zip"
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            else:
                self.send_error(403, "AccessDenied: no object at this path")
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def fresh_app(browser_context, directory_site):
    # Each URL gets empty cache/storage, independently of other browser tests.
    with browser_context.browser.new_context(
        viewport={"width": 1440, "height": 1000},
        accept_downloads=True,
        locale="en-US",
    ) as context:
        page = context.new_page()
        page.set_default_timeout(15000)
        app = App(page, directory_site)
        yield app
        assert not app.errors, app.errors
        assert not page.evaluate("acceptance.violations")


def text(pdf):
    return "\n".join(page.extract_text() for page in pdf.pages)


def embedded_fonts(pdf):
    names = set()
    for page in pdf.pages:
        for reference in page["/Resources"]["/Font"].values():
            font = reference.get_object()
            if "/FontDescriptor" in font and "/FontFile2" in font["/FontDescriptor"]:
                names.add(str(font["/BaseFont"]))
    return names
