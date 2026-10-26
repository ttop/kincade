"""web/build.py and the static page contract: the assembled two-file site, the page's
controls mapped to the worker's options, every bundled language's page text, and basic
HTML safety and accessibility."""

import dataclasses
import hashlib
import importlib.util
import inspect
import itertools
import json
import re
import shutil
import tomllib
from collections import Counter
from html.parser import HTMLParser

import pytest

from kincade import FanOptions, plan_fan
from kincade.fanpdf import FAN_PAPER, INKS
from kincade.pdf import PAPER_SIZES, Options

from conftest import ROOT
from kincade_web import LANGUAGES, PAGE_OPTIONS

WEB = ROOT / "web"

PLURAL_FORMS = {"zero", "one", "two", "few", "many", "other"}  # Unicode CLDR

PAGE_DEFAULTS = {
    "pedigree": {
        "generations": None,
        "exclude_private": False,
        "adoptive_parents": False,
        "event_standins": True,
        "empty_boxes": True,
        "show_ids": False,
        "shorten_places": True,
        "index": True,
        "page_numbers": True,
        "footer": None,
        "title": None,
        "paper": "letter",
        "large_print": False,
        "preserve_case": False,
        "shadow": False,
        "root_family": None,
        "lang": "en",
    },
    "fan": {
        "generations": 6,
        "exclude_private": False,
        "adoptive_parents": False,
        "event_standins": True,
        "preserve_case": False,
        "ink": "color",
        "paper": "letter",
        "title": None,
        "footer": None,
        "lang": "en",
    },
}


def _load_build_module():
    # Loaded by path, not `import build`, to avoid shadowing PyPA's `build` package.
    path = WEB / "build.py"
    spec = importlib.util.spec_from_file_location("kincade_web_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assembled_scripts(site):
    source = (site / "index.html").read_text(encoding="utf-8")
    return {
        name: re.search(
            rf'<script[^>]*id="{name}"[^>]*>(.*?)</script>', source, re.DOTALL
        ).group(1)
        for name in ("manifest", "glue", "worker", "app")
    }


def placeholders(text):
    return set(re.findall(r"\{(\w+)\}", text))


class PageControls(HTMLParser):
    """Parses index.html for its data-option controls, chart radios, labelled
    elements and select options."""

    def __init__(self):
        super().__init__()
        self.controls = []
        self.charts = []
        self.elements = []
        self.in_more_options = False
        self.disclosure_controls = set()
        self.select_id = None
        self.select_options = {}
        self.option = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        if tag == "details" and attrs.get("id") == "more-options":
            self.in_more_options = True
        if tag == "select":
            self.select_id = attrs["id"]
            self.select_options[self.select_id] = []
        if tag == "option":
            self.option = [attrs, ""]
        if self.in_more_options and "data-option" in attrs:
            self.disclosure_controls.add(attrs["id"])
        if tag not in {"input", "select"}:
            return
        if "data-option" in attrs:
            self.controls.append((tag, attrs))
        if tag == "input" and attrs.get("name") == "chart":
            self.charts.append(attrs)

    def handle_data(self, data):
        if self.option is not None:
            self.option[1] += data

    def handle_endtag(self, tag):
        if tag == "option":
            attrs, text = self.option
            self.select_options[self.select_id].append(
                (attrs.get("value", text), "selected" in attrs)
            )
            self.option = None
        if tag == "select":
            self.select_id = None
        if tag == "details":
            self.in_more_options = False


def message_keys_the_page_names():
    """Every message key the page's markup and scripts name, as written or built from
    the codes the worker and the Python glue send."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    glue = (WEB / "kincade_web.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'data-i18n(?:-[\w-]+)?="([\w.]+)"', html))
    keys |= set(re.findall(r'\bt\("([\w.]+)"', app))
    keys |= set(re.findall(r'"((?:error|family|root|options)\.\w+)"', app))
    keys |= set(re.findall(r'\["(\w+\.\w+)"\]', app))
    keys |= {f"step.{code}" for code in re.findall(r'status\("(\w+)"', worker)}
    keys |= {f"error.{code}" for code in re.findall(r'pageError\(\s*"(\w+)"', worker)}
    keys |= {f"error.{code}" for code in re.findall(r'PageError\("(\w+)"', glue)}
    return keys


def test_assemble_site_writes_exactly_two_files(tmp_path, monkeypatch, capsys):
    build_module = _load_build_module()
    wheel = tmp_path / "kincade-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"stand-in wheel bytes")
    site = tmp_path / "site"

    manifest = build_module.assemble_site(wheel, site)
    build_module.check_site(site, wheel.name)
    assert {path.name for path in site.iterdir()} == {"index.html", wheel.name}
    assert (site / wheel.name).read_bytes() == wheel.read_bytes()

    assert manifest["wheel"] == {
        "name": wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }
    assert manifest["pyodide"] == {
        "version": build_module.PYODIDE_VERSION,
        "base": f"https://cdn.jsdelivr.net/pyodide/v{build_module.PYODIDE_VERSION}/full/",
    }
    assert manifest["reportlab"] == "reportlab==5.0.1"
    fonts = json.loads((WEB / "fonts.json").read_text(encoding="utf-8"))
    assert manifest["fonts"] == fonts
    for font in fonts:
        assert font["url"] == build_module.FONT_BASE + font["name"]
    assert list(manifest["languages"]) == list(LANGUAGES)
    assert manifest["messages"] == build_module.read_messages(list(LANGUAGES))

    scripts = assembled_scripts(site)
    assert json.loads(scripts["manifest"]) == manifest
    source = (site / "index.html").read_text(encoding="utf-8")
    for name, file in (
        ("manifest", None),
        ("glue", "kincade_web.py"),
        ("worker", "worker.js"),
        ("app", "app.js"),
    ):
        # Each slot's inserted script appears exactly once in the assembled page.
        assert len(re.findall(rf'<script[^>]*id="{name}"', source)) == 1, name
        if file is not None:
            assert scripts[name] == (WEB / file).read_text(encoding="utf-8")

    # A sample containing "</script>" is escaped as <.
    sample = tmp_path / "sample.ged"
    sample.write_text("0 HEAD\n1 NOTE </ScRiPt><!--\n0 TRLR\n", encoding="utf-8")
    monkeypatch.setattr(build_module, "SAMPLE", sample)
    escaped_site = tmp_path / "escaped-site"
    build_module.assemble_site(wheel, escaped_site)
    serialized = assembled_scripts(escaped_site)["manifest"]
    assert "\\u003c" in serialized
    assert "<" not in serialized
    assert json.loads(serialized)["sample"]["text"] == sample.read_text(
        encoding="utf-8"
    )

    # main(), with build_wheel monkeypatched, prints both files it wrote.
    main_site = tmp_path / "main-site"
    monkeypatch.setattr(build_module, "SITE", main_site)
    monkeypatch.setattr(build_module, "build_wheel", lambda: wheel)
    build_module.main()
    assert {path.name for path in main_site.iterdir()} == {"index.html", wheel.name}
    assert capsys.readouterr().out.splitlines() == [
        f"index.html: {(main_site / 'index.html').stat().st_size} bytes",
        f"{wheel.name}: {(main_site / wheel.name).stat().st_size} bytes",
    ]


def test_build_refuses_bad_inputs(tmp_path, monkeypatch):
    """Every bad input to the site build raises SystemExit naming the problem."""
    build_module = _load_build_module()
    counter = itertools.count()

    def new_site():
        return tmp_path / f"site-{next(counter)}"

    def fresh_web_inputs():
        web = tmp_path / f"web-{next(counter)}"
        web.mkdir()
        for name in (
            "index.html",
            "app.js",
            "worker.js",
            "kincade_web.py",
            "fonts.json",
        ):
            (web / name).write_bytes((WEB / name).read_bytes())
        shutil.copytree(WEB / "lang", web / "lang")
        monkeypatch.setattr(build_module, "WEB", web)
        return web

    stand_in_wheel = tmp_path / "kincade-9.8.7-py3-none-any.whl"
    stand_in_wheel.write_bytes(b"stand-in wheel bytes")

    # A bad wheel name.
    for name in (
        "other-9.8.7-py3-none-any.whl",
        "kincade.whl",
        "kincade--py3-none-any.whl",
    ):
        bad_wheel = tmp_path / name
        bad_wheel.write_bytes(b"wheel")
        with pytest.raises(SystemExit, match="wheel"):
            build_module.assemble_site(bad_wheel, new_site())

    # fonts.json with the wrong count, a wrong URL or a bad hash.
    for mutation in ("missing", "url", "sha256"):
        fresh_web_inputs()
        fonts_path = build_module.WEB / "fonts.json"
        fonts = json.loads(fonts_path.read_text())
        if mutation == "missing":
            fonts.pop()
        else:
            fonts[0][mutation] = "invalid"
        fonts_path.write_text(json.dumps(fonts))
        with pytest.raises(SystemExit, match=r"fonts\.json"):
            build_module.assemble_site(stand_in_wheel, new_site())

    # uv.lock with 0 or 2 reportlab entries, no version, or invalid TOML.
    for lock in (
        "",
        '[[package]]\nname = "other"\nversion = "1"\n',
        '[[package]]\nname = "reportlab"\n',
        '[[package]]\nname = "reportlab"\nversion = "1"\n' * 2,
    ):
        with pytest.raises(SystemExit, match="reportlab"):
            build_module.locked_reportlab(lock)

    # inline_source given "</script" or "<!--".
    for token in ("</ScRiPt", "<!--"):
        for filename in ("app.js", "worker.js", "kincade_web.py"):
            fresh_web_inputs()
            (build_module.WEB / filename).write_text(token)
            with pytest.raises(SystemExit) as error:
                build_module.assemble_site(stand_in_wheel, new_site())
            assert filename in str(error.value), (token, filename)
            assert token.lower() in str(error.value).lower(), (token, filename)

    # index.html with a slot missing or doubled.
    for slot in ("manifest", "glue", "worker", "app"):
        for count in (0, 2):
            fresh_web_inputs()
            path = build_module.WEB / "index.html"
            source = path.read_text()
            insertion = re.search(
                rf'<script[^>]*id="{slot}"[^>]*></script>', source
            ).group()
            path.write_text(source.replace(insertion, insertion * count))
            with pytest.raises(SystemExit, match=slot):
                build_module.assemble_site(stand_in_wheel, new_site())

    # read_messages with a code mismatch or invalid TOML.
    bad_lang = tmp_path / "bad-lang-dir"
    (bad_lang / "lang").mkdir(parents=True)
    (bad_lang / "lang" / "en.toml").write_text("not valid [[[ toml", encoding="utf-8")
    monkeypatch.setattr(build_module, "WEB", bad_lang)
    with pytest.raises(SystemExit, match=r"Invalid en\.toml"):
        build_module.read_messages(["en"])
    (bad_lang / "lang" / "en.toml").write_text(
        '[page]\ntitle = "Kincade"\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="web/lang must have the bundled languages"):
        build_module.read_messages(["de", "en"])

    # check_site with an extra file.
    fresh_web_inputs()
    site = new_site()
    build_module.assemble_site(stand_in_wheel, site)
    (site / "extra.txt").write_text("extra")
    with pytest.raises(SystemExit, match="must contain exactly"):
        build_module.check_site(site, stand_in_wheel.name)

    # build_wheel producing anything but one wheel.
    for wheel_count in (0, 2):
        cache = tmp_path / f"wheel-cache-{wheel_count}"
        cache.mkdir(parents=True)
        monkeypatch.setattr(build_module, "WHEEL_CACHE", cache)

        def run(command, *, check, wheel_count=wheel_count, cache=cache):
            for index in range(wheel_count):
                (cache / f"kincade-{index}.0.0-py3-none-any.whl").write_bytes(b"new")

        monkeypatch.setattr(build_module.subprocess, "run", run)
        with pytest.raises(SystemExit, match="one wheel"):
            build_module.build_wheel()


def test_the_page_controls_map_to_the_worker_options():
    page = PageControls()
    page.feed((WEB / "index.html").read_text(encoding="utf-8"))

    # Each data-option control maps to the charts it applies to; footer appears
    # twice, once as a text field and once as the no-footer checkbox.
    pedigree, fan = frozenset({"pedigree"}), frozenset({"fan"})
    both = frozenset({"pedigree", "fan"})
    expected = Counter(
        {
            ("generations", pedigree): 1,
            ("generations", fan): 1,
            ("paper", pedigree): 1,
            ("paper", fan): 1,
            ("title", pedigree): 1,
            ("title", fan): 1,
            ("large_print", pedigree): 1,
            ("ink", fan): 1,
            ("exclude_private", both): 1,
            ("empty_boxes", pedigree): 1,
            ("show_ids", pedigree): 1,
            ("preserve_case", both): 1,
            ("adoptive_parents", both): 1,
            ("event_standins", both): 1,
            ("shorten_places", pedigree): 1,
            ("shadow", pedigree): 1,
            ("root_family", pedigree): 1,
            ("footer", both): 2,
            ("page_numbers", pedigree): 1,
            ("index", pedigree): 1,
            ("lang", both): 1,
        }
    )
    actual = Counter()
    by_chart = {chart: Counter() for chart in PAGE_OPTIONS}
    for _tag, attrs in page.controls:
        key = attrs["data-option"]
        charts = attrs["data-charts"].split()
        assert charts and len(charts) == len(set(charts)), key
        assert set(charts) <= set(PAGE_OPTIONS), key
        actual[key, frozenset(charts)] += 1
        for chart in charts:
            by_chart[chart][key] += 1
    assert actual == expected

    # PAGE_OPTIONS equals the Options fields minus excluded, and the plan_fan
    # keywords plus FanOptions fields minus excluded.
    excluded = {"today", "compress", "fonts"}
    pedigree_fields = {field.name for field in dataclasses.fields(Options)}
    fan_fields = {field.name for field in dataclasses.fields(FanOptions)}
    planner_keywords = {
        name
        for name, parameter in inspect.signature(plan_fan).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    assert PAGE_OPTIONS["pedigree"] == pedigree_fields - excluded
    assert PAGE_OPTIONS["fan"] == (planner_keywords | fan_fields) - excluded
    for chart, keys in PAGE_OPTIONS.items():
        assert set(by_chart[chart]) == keys, chart
        assert by_chart[chart] == Counter(
            {key: 2 if key == "footer" else 1 for key in keys}
        ), chart

    # Select options match PAPER_SIZES, FAN_PAPER, INKS and fan generations 2 to 7,
    # each defaulting to the library's default.
    assert page.select_options["pedigree-paper"] == [
        (paper, paper == "letter") for paper in PAPER_SIZES
    ]
    assert page.select_options["fan-paper"] == [
        (paper, paper == "letter") for paper in FAN_PAPER
    ]
    assert page.select_options["ink"] == [(ink, ink == "color") for ink in INKS]
    assert page.select_options["fan-generations"] == [
        (str(n), n == 6) for n in range(2, 8)
    ]

    # Control defaults equal the library defaults, with empty_boxes and
    # preserve_case inverted as app.js's settingsSnapshot does.
    for chart, expected_defaults in PAGE_DEFAULTS.items():
        actual_defaults = {}
        for tag, attrs in page.controls:
            if chart not in attrs["data-charts"].split():
                continue
            key = attrs["data-option"]
            if key == "footer" and attrs.get("type") == "checkbox":
                continue
            if tag == "select":
                value = next(
                    value
                    for value, selected in page.select_options[attrs["id"]]
                    if selected
                )
                actual_defaults[key] = (
                    int(value)
                    if key == "generations"
                    else None
                    if key == "root_family" and value == ""
                    else value
                )
            elif attrs["type"] == "checkbox":
                actual_defaults[key] = (
                    ("checked" not in attrs)
                    if key in {"empty_boxes", "preserve_case"}
                    else ("checked" in attrs)
                )
            else:
                assert attrs.get("value", "") == "", key
                actual_defaults[key] = None
        assert actual_defaults == expected_defaults, chart


def test_page_text_in_every_language():
    build_module = _load_build_module()
    messages = build_module.read_messages(list(LANGUAGES))
    assert sorted(messages) == list(LANGUAGES) == ["de", "en", "es", "fr", "it"]

    # Each web/lang file flattens to en's keys.
    for code in LANGUAGES:
        parsed = tomllib.loads(
            (WEB / "lang" / f"{code}.toml").read_text(encoding="utf-8")
        )
        assert set(build_module._flatten_messages(parsed)) == set(messages["en"]), code

    # Each language words every message with the same placeholders and plural
    # tables as English.
    english = messages["en"]
    for code in LANGUAGES:
        if code == "en":
            continue
        translated = messages[code]
        assert set(translated) == set(english), code
        for key, text in english.items():
            if isinstance(text, dict):
                assert "other" in translated[key], (code, key)
                assert set(translated[key]) <= PLURAL_FORMS, (code, key)
                for form in text.values():
                    for value in translated[key].values():
                        assert placeholders(value) == placeholders(form), (code, key)
            else:
                assert isinstance(translated[key], str), (code, key)
                assert placeholders(translated[key]) == placeholders(text), (code, key)

    # Every message the page names exists, and every message is named.
    named = message_keys_the_page_names()
    assert {"step.pyodide", "step.start", "error.download", "error.noPeople"} <= named
    assert named == set(english)

    # Every worker status host has a name.
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    hosts = set(re.findall(r'status\("\w+", "(\w+)"\)', worker))
    app = (WEB / "app.js").read_text(encoding="utf-8")
    host_names = re.search(r"const hostNames = \{(.*?)\};", app, re.DOTALL)[1]
    assert hosts | {"browser"} == set(re.findall(r"(\w+): \(\) =>", host_names))

    # Each language names itself, uniquely.
    names = [messages[code]["page.languageName"] for code in LANGUAGES]
    assert all(name.strip() for name in names)
    assert len(set(names)) == len(names)


def test_page_html_basics():
    page = PageControls()
    page.feed((WEB / "index.html").read_text(encoding="utf-8"))
    elements = {
        attrs["id"]: (tag, attrs) for tag, attrs in page.elements if "id" in attrs
    }

    # ids are unique, and every input and select is labelled.
    ids = [attrs["id"] for _tag, attrs in page.elements if "id" in attrs]
    assert len(ids) == len(set(ids))
    labels = {attrs["for"] for tag, attrs in page.elements if tag == "label"}
    assert {
        attrs["id"]
        for tag, attrs in page.elements
        if tag in {"input", "select"} and not attrs.get("aria-label")
    } <= labels

    assert elements["file"][1]["accept"] == ".ged,.gedcom"

    # The build insertion points are exact and empty.
    scripts = [attrs for tag, attrs in page.elements if tag == "script"]
    assert scripts == [
        {"id": "manifest", "type": "application/json"},
        {"id": "glue", "type": "text/x-python"},
        {"id": "worker", "type": "text/js-worker"},
        {"id": "app"},
    ]
    source = (WEB / "index.html").read_text(encoding="utf-8")
    for attrs in scripts:
        assert re.search(rf'<script[^>]*id="{attrs["id"]}"[^>]*></script>', source), (
            attrs
        )

    # app.js never writes raw HTML; this guards against XSS from GEDCOM names.
    app = (WEB / "app.js").read_text(encoding="utf-8")
    for api in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
        assert api not in app, api
    assert "textContent" in app
