"""Assemble the browser page and its wheel into a two-file static site."""

import hashlib
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SITE = WEB / "site"
WHEEL_CACHE = WEB / ".cache" / "wheel"
SAMPLE = ROOT / "docs" / "examples" / "george-washington.ged"
PYODIDE_VERSION = "314.0.7"
FONT_NAMES = {
    "LiberationSans-Regular.ttf",
    "LiberationSans-Bold.ttf",
    "LiberationSerif-Regular.ttf",
    "LiberationSerif-Italic.ttf",
}
FONT_BASE = "https://cdn.jsdelivr.net/npm/@betteroffice/fonts@0.4.0/assets/"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def locked_reportlab(lock_text: str) -> str:
    """Read the equality requirement from the one reportlab lock entry."""
    try:
        lock = tomllib.loads(lock_text)
    except tomllib.TOMLDecodeError as error:
        raise SystemExit(f"Cannot read reportlab from uv.lock: {error}") from error
    packages = [
        package
        for package in lock.get("package", [])
        if package.get("name") == "reportlab"
    ]
    if len(packages) != 1:
        raise SystemExit("uv.lock must contain exactly one reportlab package")
    version = packages[0].get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit("uv.lock reportlab package must have a version")
    return f"reportlab=={version}"


def read_fonts() -> list[dict[str, str]]:
    """Validate the four pinned CDN font objects before embedding them."""
    path = WEB / "fonts.json"
    try:
        fonts = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"Invalid fonts.json: {error}") from error
    message = "fonts.json must contain the four pinned Liberation font objects"
    if not isinstance(fonts, list) or len(fonts) != 4:
        raise SystemExit(message)
    names = set()
    result = []
    for font in fonts:
        if not isinstance(font, dict) or set(font) != {"name", "url", "sha256"}:
            raise SystemExit(message)
        if not all(isinstance(value, str) for value in font.values()):
            raise SystemExit(message)
        name = font["name"]
        if (
            name not in FONT_NAMES
            or name in names
            or font["url"] != FONT_BASE + name
            or not re.fullmatch(r"[0-9a-f]{64}", font["sha256"])
        ):
            raise SystemExit(message)
        names.add(name)
        result.append(font)
    return result


def inline_source(name: str) -> str:
    source = (WEB / name).read_text(encoding="utf-8")
    for token in ("</script", "<!--"):
        if token in source.lower():
            raise SystemExit(f"Cannot inline {name}: refused token {token}")
    return source


def check_site(destination: Path, wheel_name: str) -> None:
    expected = {"index.html", wheel_name}
    if {path.name for path in destination.iterdir()} != expected or not all(
        (destination / name).is_file() for name in expected
    ):
        raise SystemExit(
            f"{destination} must contain exactly index.html and {wheel_name}"
        )


def assemble_site(wheel: Path, destination: Path = SITE) -> dict[str, object]:
    """Inline validated inputs and copy a wheel, without building or fetching it."""
    match = re.fullmatch(r"kincade-([^-]+)-py3-none-any\.whl", wheel.name)
    if match is None:
        raise SystemExit(f"Invalid Kincade wheel filename: {wheel.name}")
    wheel_bytes = wheel.read_bytes()
    manifest: dict[str, object] = {
        "pyodide": {
            "version": PYODIDE_VERSION,
            "base": f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/",
        },
        "wheel": {"name": wheel.name, "sha256": sha256(wheel_bytes)},
        "reportlab": locked_reportlab((ROOT / "uv.lock").read_text(encoding="utf-8")),
        "fonts": read_fonts(),
        "kincade": match[1],
        "sample": {"name": SAMPLE.name, "text": SAMPLE.read_text(encoding="utf-8")},
    }
    slots = {
        '<script id="manifest" type="application/json"></script>': json.dumps(
            manifest, separators=(",", ":")
        ).replace("<", "\\u003c"),
        '<script id="glue" type="text/x-python"></script>': inline_source(
            "kincade_web.py"
        ),
        '<script id="worker" type="text/js-worker"></script>': inline_source(
            "worker.js"
        ),
        '<script id="app"></script>': inline_source("app.js"),
    }
    source = (WEB / "index.html").read_text(encoding="utf-8")
    for insertion, content in slots.items():
        if source.count(insertion) != 1:
            raise SystemExit(f"index.html must contain exactly one {insertion}")
        source = source.replace(
            insertion, insertion.replace("></script>", f">{content}</script>")
        )
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.html").write_text(source, encoding="utf-8")
    (destination / wheel.name).write_bytes(wheel_bytes)
    check_site(destination, wheel.name)
    return manifest


def build_wheel() -> Path:
    """Build into a fresh wheel cache without disturbing other cache entries."""
    if WHEEL_CACHE.exists():
        shutil.rmtree(WHEEL_CACHE)
    WHEEL_CACHE.mkdir(parents=True)
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(WHEEL_CACHE), str(ROOT)],
        check=True,
    )
    wheels = list(WHEEL_CACHE.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("The build must produce exactly one wheel")
    return wheels[0]


def main() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    wheel = build_wheel()
    assemble_site(wheel, SITE)
    check_site(SITE, wheel.name)
    for name in ("index.html", wheel.name):
        print(f"{name}: {(SITE / name).stat().st_size} bytes")


if __name__ == "__main__":
    main()
