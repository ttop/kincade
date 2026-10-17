"""First visits work even when a static host serves a directory without a slash."""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from conftest import App, embedded_fonts, text


@pytest.fixture
def directory_site(site_files, mount):
    """Emulate the S3/CloudFront rewrite without redirecting the browser URL."""
    wheel_name = next(name for name in site_files if name.endswith(".whl"))
    pages = {mount or "/", mount + "/", mount + "/index.html"}

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
        viewport={"width": 1440, "height": 1000}, accept_downloads=True
    ) as context:
        page = context.new_page()
        page.set_default_timeout(15000)
        app = App(page, directory_site)
        try:
            yield app
            assert not app.errors, app.errors
            assert not page.evaluate("acceptance.violations")
        finally:
            app.dispose()


@pytest.mark.parametrize(
    "mount,entry",
    [
        ("", "/"),
        ("", "/index.html"),
        ("/kincade", "/kincade"),
        ("/kincade", "/kincade/"),
        ("/kincade", "/kincade/index.html"),
        ("/tools/kincade", "/tools/kincade?from=blog#example"),
        ("/tools/kincade", "/tools/kincade/?from=blog#example"),
        ("/tools/kincade", "/tools/kincade/index.html?from=blog#example"),
    ],
    ids=[
        "root",
        "root-index",
        "no-slash",
        "slash",
        "index",
        "nested-no-slash-query",
        "nested-slash-query",
        "nested-index-query",
    ],
)
def test_fresh_directory_install_and_both_pdf_downloads(fresh_app, mount, entry):
    app = fresh_app
    with app.page.expect_response(
        lambda response: (
            response.url.startswith(app.site + "/")
            and urlsplit(response.url).path.endswith(".whl")
        ),
        timeout=120000,
    ) as download:
        app.page.goto(app.site + entry)
    response = download.value
    manifest = json.loads(app.page.locator("#manifest").text_content())
    wheel = manifest["wheel"]
    assert response.url == (
        f"{app.site}{mount}/{wheel['name']}?v={wheel['sha256'][:12]}"
    )
    assert response.status == 200
    assert hashlib.sha256(response.body()).hexdigest() == wheel["sha256"]
    expect(app.page.locator("#status")).to_have_text("Ready", timeout=120000)
    expect(app.page.locator("#retry")).to_be_hidden()
    # Prove the client fix works without a host or client redirect.
    assert app.page.url == app.site + entry
    app.sample()
    pedigree = app.pdf()
    assert len(pedigree.pages) == 6
    assert "George WASHINGTON" in text(pedigree)
    assert len(embedded_fonts(pedigree)) == 4
    app.chart("fan")
    fan = app.pdf()
    assert len(fan.pages) == 1
    assert "George WASHINGTON" in text(fan)
    assert len(embedded_fonts(fan)) == 2
    assert not app.failed_requests, app.failed_requests
    assert not app.console_errors, app.console_errors


@pytest.mark.parametrize("mount", ["/kincade"])
def test_missing_wheel_reports_http_status_url_and_recovery_hint(fresh_app, mount):
    app = fresh_app
    app.page.set_viewport_size({"width": 320, "height": 800})
    app.page.route(
        app.site + "/**/*.whl?*",
        lambda route: route.fulfill(
            status=403, content_type="application/xml", body="<Code>AccessDenied</Code>"
        ),
    )
    app.page.goto(app.site + mount)
    manifest = json.loads(app.page.locator("#manifest").text_content())
    wheel = manifest["wheel"]
    url = f"{app.site}{mount}/{wheel['name']}?v={wheel['sha256'][:12]}"
    expect(app.page.locator("#retry")).to_be_visible(timeout=120000)
    expect(app.page.locator("#status")).to_contain_text(f"HTTP 403 for {url}")
    expect(app.page.locator("#status")).to_contain_text("site owner")
    assert app.page.evaluate("document.documentElement.scrollWidth <= innerWidth")
