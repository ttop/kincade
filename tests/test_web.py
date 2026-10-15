import dataclasses
import hashlib
import importlib.util
import inspect
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from reportlab import rl_config

from kincade import FanOptions, Options, plan_fan, render_fan
from kincade.pdf import BASE14, FONT_FILES, render_with_counts

import kincade_web
from conftest import FIX, ROOT
from kincade_web import PAGE_OPTIONS, Session
from pdfread import count_pages


@pytest.fixture
def session():
    result = Session()
    result.open((FIX / "pedigree.ged").read_bytes())
    return result


def test_open_rejects_empty_tree_without_replacing_previous_tree():
    session = Session()
    assert session.open((FIX / "pedigree.ged").read_bytes()) == 28
    old_tree = session.tree
    with pytest.raises(ValueError, match="no people"):
        session.open(b"0 HEAD\n0 TRLR\n")
    assert session.tree is old_tree


def test_search_returns_names_years_privacy_and_total_before_limit(session):
    total, rows = session.search("I1", False, True)
    assert (total, rows) == (1, [["I1", "Jane ASHFORD", "1980-"]])
    assert session.search("I1", True, True)[1][0][2] == ""
    assert session.search("", False, True, limit=1)[0] == 28
    assert len(session.search("", False, True, limit=1)[1]) == 1


@pytest.mark.parametrize("operation", ["search", "render"])
def test_operations_before_open_are_plain_value_errors(operation):
    session = Session()
    with pytest.raises(ValueError) as error:
        if operation == "search":
            session.search("", False, True)
        else:
            session.render("I1", "pedigree", {})
    assert type(error.value) is ValueError


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
    },
}


@pytest.mark.parametrize(
    "chart,filename,summary,pages",
    [
        (
            "pedigree",
            "Jane ASHFORD cascading pedigree.pdf",
            "6 charts, 1 index page, 7 pages",
            7,
        ),
        (
            "fan",
            "Jane ASHFORD fan chart.pdf",
            "fan chart, 6 generations, 23 people",
            1,
        ),
    ],
)
def test_render_accepts_every_page_key(session, chart, filename, summary, pages):
    settings = PAGE_DEFAULTS[chart]
    assert set(settings) == PAGE_OPTIONS[chart]
    pdf, actual_filename, actual_summary = session.render("I1", chart, settings)
    assert pdf.startswith(b"%PDF")
    assert count_pages(pdf) == pages
    assert (actual_filename, actual_summary) == (filename, summary)
    if chart == "fan":
        assert b"/MediaBox [ 0 0 792 612 ]" in pdf


@pytest.mark.parametrize("chart", ["pedigree", "fan"])
def test_omitted_settings_use_library_defaults(session, chart, monkeypatch):
    monkeypatch.setattr(rl_config, "invariant", True)
    session.fonts = dataclasses.replace(
        BASE14,
        sans="Courier",
        bold="Courier-Bold",
        serif="Courier",
        italic="Courier-Oblique",
    )
    actual, _filename, _summary = session.render("I1", chart, {})
    if chart == "pedigree":
        expected = render_with_counts(
            session.tree, "I1", Options(fonts=session.fonts)
        ).pdf
    else:
        expected = render_fan(
            plan_fan(session.tree, "I1"), FanOptions(fonts=session.fonts)
        )
    assert actual == expected


def test_preview_starts_empty_before_any_render(session):
    assert Session().preview is None
    assert session.preview is None


@pytest.mark.parametrize(
    "paper,width,height", [("letter", 612, 792), ("a4", 595.28, 841.89)]
)
@pytest.mark.parametrize("index", [False, True])
@pytest.mark.parametrize("large_print", [False, True])
def test_pedigree_preview_matches_every_pdf_page(
    session, paper, width, height, index, large_print
):
    result = session.render(
        "I1", "pedigree", {"paper": paper, "index": index, "large_print": large_print}
    )
    assert len(result) == 3
    pdf, _filename, _summary = result
    page_count = count_pages(pdf)
    boxes = re.findall(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", pdf)
    assert len(boxes) == page_count
    assert [(float(w), float(h)) for w, h in boxes] == [(width, height)] * page_count
    assert session.preview == {"pages": page_count, "width": width, "height": height}
    assert page_count > 1


@pytest.mark.parametrize(
    "paper,width,height",
    [
        ("letter", 792, 612),
        ("a4", 841.89, 595.28),
        ("tabloid", 1224, 792),
        ("a3", 1190.55, 841.89),
    ],
)
def test_fan_preview_matches_landscape_pdf_paper(session, paper, width, height):
    result = session.render("I1", "fan", {"paper": paper})
    assert len(result) == 3
    pdf, _filename, _summary = result
    assert count_pages(pdf) == 1
    boxes = re.findall(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", pdf)
    assert [(float(w), float(h)) for w, h in boxes] == [(width, height)]
    assert session.preview == {"pages": 1, "width": width, "height": height}


@pytest.mark.parametrize(
    "chart,pages,width,height",
    [
        ("pedigree", 7, 612, 792),
        ("fan", 1, 792, 612),
    ],
)
def test_preview_uses_library_defaults(session, chart, pages, width, height):
    session.render("I1", chart, {})
    assert session.preview == {"pages": pages, "width": width, "height": height}


@pytest.mark.parametrize(
    "chart,settings",
    [
        ("pedigree", {"generations": 0}),
        ("pedigree", {"paper": "bad"}),
        ("fan", {"generations": 8}),
        ("fan", {"paper": "bad"}),
    ],
)
def test_failed_render_retains_previous_preview(session, chart, settings):
    session.render("I1", "fan", {"paper": "tabloid"})
    previous = session.preview
    with pytest.raises(ValueError):
        session.render("I1", chart, settings)
    assert session.preview is previous


def test_each_fan_ink_matches_planning_and_drawing(session, monkeypatch):
    monkeypatch.setattr(rl_config, "invariant", True)
    pdfs = []
    for ink in ("color", "grayscale", "bw"):
        actual, filename, summary = session.render("I1", "fan", {"ink": ink})
        expected = render_fan(
            plan_fan(session.tree, "I1", ink=ink),
            FanOptions(ink=ink, fonts=session.fonts),
        )
        assert actual == expected
        assert filename == "Jane ASHFORD fan chart.pdf"
        assert summary == "fan chart, 6 generations, 23 people"
        pdfs.append(actual)
    assert len(set(pdfs)) == 3


def test_filenames_keep_recorded_root_surname_case():
    session = Session()
    session.open(b"0 HEAD\n0 @I1@ INDI\n1 NAME Jane /Ashford/\n0 TRLR\n")
    assert session.search("I1", False, True)[1][0][1] == "Jane ASHFORD"
    assert session.render("I1", "fan", {})[1] == "Jane Ashford fan chart.pdf"
    assert (
        session.render("I1", "fan", {"preserve_case": True})[1]
        == "Jane Ashford fan chart.pdf"
    )
    assert session.render("I1", "pedigree", {})[1] == (
        "Jane Ashford cascading pedigree.pdf"
    )


@pytest.mark.parametrize("chart", ["pedigree", "fan"])
@pytest.mark.parametrize("key", ["unknown", "lang", "today", "compress", "fonts"])
def test_non_page_keys_are_plain_value_errors(session, chart, key):
    with pytest.raises(ValueError) as error:
        session.render("I1", chart, {key: None})
    assert type(error.value) is ValueError


@pytest.mark.parametrize(
    "root,chart,settings",
    [
        ("I1", "unknown", {}),
        ("missing", "pedigree", {}),
        ("missing", "fan", {}),
        ("I1", "fan", {"shadow": False}),
        ("I1", "pedigree", {"ink": "color"}),
    ],
)
def test_chart_key_and_root_validation(session, root, chart, settings):
    with pytest.raises(ValueError) as error:
        session.render(root, chart, settings)
    assert type(error.value) is ValueError


@pytest.mark.parametrize(
    "chart,value",
    [
        *[("pedigree", value) for value in (0, -1, "3", True, False, 3.0)],
        *[("fan", value) for value in (1, 8, None, "6", True, False, 6.0)],
    ],
)
def test_invalid_generations_are_plain_value_errors(session, chart, value):
    with pytest.raises(ValueError) as error:
        session.render("I1", chart, {"generations": value})
    assert type(error.value) is ValueError


@pytest.mark.parametrize("value", [None, 1, 3])
def test_pedigree_accepts_valid_generations(session, value):
    assert session.render("I1", "pedigree", {"generations": value})[0].startswith(
        b"%PDF"
    )


@pytest.mark.parametrize("value", range(2, 8))
def test_fan_accepts_its_generation_range(session, value):
    pdf, _filename, summary = session.render("I1", "fan", {"generations": value})
    assert count_pages(pdf) == 1
    assert summary.startswith(f"fan chart, {value} generations, ")


def test_option_sets_match_both_library_interfaces():
    excluded = {"lang", "today", "compress", "fonts"}
    pedigree_fields = {field.name for field in dataclasses.fields(Options)}
    fan_fields = {field.name for field in dataclasses.fields(FanOptions)}
    planner_keywords = {
        name
        for name, parameter in inspect.signature(plan_fan).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    assert set(PAGE_OPTIONS) == {"pedigree", "fan"}
    assert all(isinstance(keys, frozenset) for keys in PAGE_OPTIONS.values())
    assert PAGE_OPTIONS["pedigree"] == pedigree_fields - excluded
    assert PAGE_OPTIONS["fan"] == (planner_keywords | fan_fields) - excluded
    assert PAGE_OPTIONS["fan"] == {
        "generations",
        "exclude_private",
        "adoptive_parents",
        "event_standins",
        "preserve_case",
        "ink",
        "paper",
        "title",
        "footer",
    }


def test_empty_font_directory_uses_base14(session, tmp_path):
    assert session.fonts is BASE14
    assert session.load_fonts(tmp_path) == "base14"
    assert session.fonts is BASE14
    for chart in PAGE_OPTIONS:
        pdf = session.render("I1", chart, {})[0]
        assert pdf.startswith(b"%PDF")
        assert b"/FontFile2" not in pdf


def test_font_loading_uses_only_the_given_directory_and_resets_on_failure(
    session, tmp_path, monkeypatch
):
    calls = []
    embedded = dataclasses.replace(BASE14, files=("sans", "bold", "serif", "italic"))
    answers = iter([(embedded, []), (None, ["italic"])])

    def load(directories):
        calls.append(directories)
        return next(answers)

    monkeypatch.setattr(kincade_web, "load_fontset", load)
    assert session.load_fonts(str(tmp_path)) == "embedded"
    assert session.fonts is embedded
    assert session.load_fonts(tmp_path) == "base14"
    assert session.fonts is BASE14
    assert calls == [[Path(tmp_path)], [Path(tmp_path)]]


WEB = Path(__file__).resolve().parents[1] / "web"


def test_font_manifest_covers_every_role_with_pinned_https_assets():
    path = WEB / "fonts.json"
    assert path.is_file()
    fonts = json.loads(path.read_text())
    assert len(fonts) == 4
    names = {font["name"] for font in fonts}
    assert len(names) == 4
    for font in fonts:
        assert set(font) == {"name", "url", "sha256"}
        url = urlsplit(font["url"])
        assert url.scheme == "https"
        assert url.netloc
        assert re.fullmatch(r"[0-9a-f]{64}", font["sha256"])
    for candidates in FONT_FILES.values():
        assert len(names & {name for name, _face in candidates}) == 1


def test_worker_digest_path_works_without_web_crypto():
    path = WEB / "worker.js"
    assert path.is_file()
    source = path.read_text()
    assert "hashlib" in source
    assert "crypto.subtle" not in source


class PageControls(HTMLParser):
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


def test_page_option_mapping_for_both_charts():
    page = PageControls()
    page.feed((ROOT / "web/index.html").read_text(encoding="utf-8"))
    pedigree = frozenset({"pedigree"})
    fan = frozenset({"fan"})
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
        }
    )
    actual = Counter()
    by_chart = {chart: Counter() for chart in PAGE_OPTIONS}
    for _tag, attrs in page.controls:
        key = attrs["data-option"]
        charts = attrs["data-charts"].split()
        assert charts and len(charts) == len(set(charts))
        assert set(charts) <= set(PAGE_OPTIONS)
        actual[key, frozenset(charts)] += 1
        for chart in charts:
            by_chart[chart][key] += 1
    assert actual == expected
    for chart, keys in PAGE_OPTIONS.items():
        assert set(by_chart[chart]) == keys
        assert by_chart[chart] == Counter(
            {key: 2 if key == "footer" else 1 for key in keys}
        )
    assert {radio["value"] for radio in page.charts} == {"pedigree", "fan"}
    assert len(page.charts) == 2
    assert all(radio.get("type") == "radio" for radio in page.charts)
    assert [radio["value"] for radio in page.charts if "checked" in radio] == [
        "pedigree"
    ]
    assert all("data-option" not in radio for radio in page.charts)


def test_page_uses_safe_text_apis():
    source = (ROOT / "web/app.js").read_text(encoding="utf-8")
    for api in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
        assert api not in source
    assert "textContent" in source


def test_pdf_url_cleanup_preserves_pages_in_back_forward_cache():
    # Static cleanup contract; web/browser_tests/test_viewer.py exercises
    # Chromium Back navigation and PDF usability after restoration or reload.
    source = (WEB / "app.js").read_text(encoding="utf-8")
    handler = re.search(
        r'window\.addEventListener\("pagehide", \(event\) => \{([^}]+)\}\);',
        source,
    )
    assert handler is not None, "PDF cleanup must use pagehide"
    assert re.search(
        r"if\s*\(!event\.persisted\s*&&\s*pdfUrl\)\s*"
        r"URL\.revokeObjectURL\(pdfUrl\);",
        handler[1],
    ), "Cached pages must retain their PDF URL for Back navigation"
    assert not re.search(r'addEventListener\("unload"', source)


def test_page_html_defaults_labels_and_disclosure():
    page = PageControls()
    page.feed((ROOT / "web/index.html").read_text(encoding="utf-8"))
    elements = {
        attrs["id"]: (tag, attrs) for tag, attrs in page.elements if "id" in attrs
    }
    ids = [attrs["id"] for _tag, attrs in page.elements if "id" in attrs]
    assert len(ids) == len(set(ids))
    labels = {attrs["for"] for tag, attrs in page.elements if tag == "label"}
    assert {
        attrs["id"]
        for tag, attrs in page.elements
        if tag in {"input", "select"} and not attrs.get("aria-label")
    } <= labels
    assert elements["file"][1]["accept"] == ".ged,.gedcom"
    generations = elements["pedigree-generations"][1]
    assert {
        key: generations[key] for key in ("type", "min", "step", "placeholder")
    } == {"type": "number", "min": "1", "step": "1", "placeholder": "all"}
    assert (
        elements["pedigree-title"][1]["placeholder"]
        == "Cascading Pedigree — Root's name"
    )
    assert elements["fan-title"][1]["placeholder"] == "Root's name — Fan chart"
    assert "data-option" not in elements["pedigree-generation-choice"][1]
    assert "pedigree-generations" in page.disclosure_controls
    assert page.select_options == {
        "pedigree-generation-choice": [("all", True), ("custom", False)],
        "root-family": [("", True)],
        "fan-generations": [(str(n), n == 6) for n in range(2, 8)],
        "pedigree-paper": [("letter", True), ("a4", False)],
        "fan-paper": [
            ("letter", True),
            ("a4", False),
            ("tabloid", False),
            ("a3", False),
        ],
        "ink": [("color", True), ("grayscale", False), ("bw", False)],
    }
    for chart, expected in PAGE_DEFAULTS.items():
        actual = {}
        always = []
        for tag, attrs in page.controls:
            if chart not in attrs["data-charts"].split():
                continue
            key = attrs["data-option"]
            if attrs["id"] not in page.disclosure_controls and key != "root_family":
                always.append(key)
            if key == "footer" and attrs.get("type") == "checkbox":
                assert "checked" not in attrs
                continue
            if tag == "select":
                value = next(
                    value
                    for value, selected in page.select_options[attrs["id"]]
                    if selected
                )
                actual[key] = (
                    int(value)
                    if key == "generations"
                    else None
                    if key == "root_family" and value == ""
                    else value
                )
            elif attrs["type"] == "checkbox":
                actual[key] = (
                    ("checked" not in attrs)
                    if key in {"empty_boxes", "preserve_case"}
                    else ("checked" in attrs)
                )
            else:
                assert attrs.get("value", "") == ""
                actual[key] = None
        assert actual == expected
        assert set(always) == (
            {"paper", "exclude_private", "large_print"}
            if chart == "pedigree"
            else {"generations", "paper", "exclude_private", "ink"}
        )
        assert len(always) == (3 if chart == "pedigree" else 4)
    assert "open" not in elements["more-options"][1]
    assert "disabled" in elements["root-controls"][1]
    assert "disabled" in elements["option-controls"][1]


def test_root_picker_starts_closed_with_accessible_search_relationship():
    # Markup contract only; focus, Escape and selection run in web/browser_tests.
    page = PageControls()
    page.feed((WEB / "index.html").read_text(encoding="utf-8"))
    elements = {
        attrs["id"]: (tag, attrs) for tag, attrs in page.elements if "id" in attrs
    }
    search = elements["search"][1]
    assert search["role"] == "combobox"
    assert search["aria-autocomplete"] == "list"
    assert search["aria-controls"] == "results"
    assert search["type"] == "text"
    assert search["aria-describedby"] == "root-summary"
    assert elements["root-action"][0] == "button"
    assert elements["root-action"][1]["type"] == "button"
    assert elements["root-action"][1]["aria-label"] == "Open person list"
    assert elements["root-list-icon"][1]["aria-hidden"] == "true"
    assert "hidden" in elements["root-clear-icon"][1]
    assert elements["root-summary"][1]["class"] == "visually-hidden"
    assert elements["results"][1]["role"] == "listbox"
    assert search["aria-expanded"] == "false"
    assert "hidden" in elements["root-choices"][1]
    assert elements["results"][1]["aria-label"] == "Matching people"
    assert elements["root-summary"][1]["aria-live"] == "polite"


def test_page_html_has_exact_empty_build_insertion_points():
    page = PageControls()
    page.feed((ROOT / "web/index.html").read_text(encoding="utf-8"))
    scripts = [attrs for tag, attrs in page.elements if tag == "script"]
    assert scripts == [
        {"id": "manifest", "type": "application/json"},
        {"id": "glue", "type": "text/x-python"},
        {"id": "worker", "type": "text/js-worker"},
        {"id": "app"},
    ]
    source = (ROOT / "web/index.html").read_text(encoding="utf-8")
    for attrs in scripts:
        assert re.search(rf'<script[^>]*id="{attrs["id"]}"[^>]*></script>', source)


@pytest.fixture
def build_module():
    path = WEB / "build.py"
    assert path.is_file(), "the site build is not implemented"
    spec = importlib.util.spec_from_file_location("kincade_web_build", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stand_in_wheel(tmp_path):
    wheel = tmp_path / "kincade-9.8.7-py3-none-any.whl"
    wheel.write_bytes(b"stand-in wheel bytes")
    return wheel


@pytest.fixture
def build_inputs(build_module, tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    for name in ("index.html", "app.js", "worker.js", "kincade_web.py", "fonts.json"):
        (web / name).write_bytes((WEB / name).read_bytes())
    monkeypatch.setattr(build_module, "WEB", web)
    return web


def assembled_scripts(site):
    source = (site / "index.html").read_text(encoding="utf-8")
    return {
        name: re.search(
            rf'<script[^>]*id="{name}"[^>]*>(.*?)</script>', source, re.DOTALL
        ).group(1)
        for name in ("manifest", "glue", "worker", "app")
    }


def test_build_reads_the_locked_reportlab_requirement(build_module):
    assert build_module.locked_reportlab(
        (ROOT / "uv.lock").read_text(encoding="utf-8")
    ) == ("reportlab==5.0.1")
    assert (
        build_module.locked_reportlab(
            '[[package]]\nname = "reportlab"\nversion = "9.8.7"\n'
        )
        == "reportlab==9.8.7"
    )


@pytest.mark.parametrize(
    "lock",
    [
        "",
        '[[package]]\nname = "other"\nversion = "1"\n',
        '[[package]]\nname = "reportlab"\n',
        '[[package]]\nname = "reportlab"\nversion = "1"\n' * 2,
    ],
)
def test_build_refuses_missing_or_ambiguous_reportlab(build_module, lock):
    with pytest.raises(SystemExit, match="reportlab"):
        build_module.locked_reportlab(lock)


def test_assemble_site_inlines_manifest_and_sources_into_exactly_two_files(
    build_module, stand_in_wheel, tmp_path
):
    site = tmp_path / "site"
    manifest = build_module.assemble_site(stand_in_wheel, site)
    scripts = assembled_scripts(site)
    assert json.loads(scripts["manifest"]) == manifest
    assert set(manifest) == {
        "pyodide",
        "wheel",
        "reportlab",
        "fonts",
        "kincade",
        "sample",
    }
    assert manifest["pyodide"] == {
        "version": "314.0.7",
        "base": "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/",
    }
    assert manifest["wheel"] == {
        "name": stand_in_wheel.name,
        "sha256": hashlib.sha256(stand_in_wheel.read_bytes()).hexdigest(),
    }
    assert (
        build_module.sha256(stand_in_wheel.read_bytes()) == manifest["wheel"]["sha256"]
    )
    assert manifest["reportlab"] == "reportlab==5.0.1"
    assert manifest["fonts"] == json.loads(
        (WEB / "fonts.json").read_text(encoding="utf-8")
    )
    assert manifest["kincade"] == "9.8.7"
    assert manifest["sample"] == {
        "name": "george-washington.ged",
        "text": (ROOT / "docs/examples/george-washington.ged").read_text(
            encoding="utf-8"
        ),
    }
    for name, file in {
        "glue": "kincade_web.py",
        "worker": "worker.js",
        "app": "app.js",
    }.items():
        assert scripts[name] == (WEB / file).read_text(encoding="utf-8")
    assert {path.name for path in site.iterdir()} == {"index.html", stand_in_wheel.name}
    assert (site / stand_in_wheel.name).read_bytes() == stand_in_wheel.read_bytes()
    second = tmp_path / "second-site"
    assert build_module.assemble_site(stand_in_wheel, second) == manifest
    assert (second / "index.html").read_bytes() == (site / "index.html").read_bytes()


def test_assembled_bootstrap_supports_the_pinned_module_worker_runtime(
    build_module, stand_in_wheel, tmp_path
):
    # A classic worker or script loader rejects Pyodide before startup can finish.
    site = tmp_path / "site"
    build_module.assemble_site(stand_in_wheel, site)
    scripts = assembled_scripts(site)
    module_worker = re.search(
        r'new\s+Worker\(workerUrl,\s*\{\s*type:\s*[\'"]module[\'"]\s*\}\)',
        scripts["app"],
    )
    module_loader = re.search(
        r"async function initialize\([^)]*\)\s*\{\s*"
        r'status\("Loading Pyodide", "jsDelivr"\);\s*'
        r"const\s+\{loadPyodide\}\s*=\s*await import\("
        r"`\$\{manifest\.pyodide\.base\}pyodide\.mjs`\);\s*"
        r"pyodide\s*=\s*await loadPyodide\("
        r"\{indexURL:\s*manifest\.pyodide\.base\}\);",
        scripts["worker"],
    )
    assert (bool(module_worker), bool(module_loader)) == (True, True)


def test_assembled_preview_connects_render_geometry_to_responsive_iframe(
    build_module, stand_in_wheel, tmp_path
):
    # Static assembly contract only; native viewer behavior runs in web/browser_tests.
    site = tmp_path / "site"
    build_module.assemble_site(stand_in_wheel, site)
    scripts = assembled_scripts(site)
    assert '"preview": _web_session.preview' in scripts["worker"]
    assert "reply.preview" in scripts["app"]
    assert "frame.clientWidth" in scripts["app"]
    sizing = re.search(
        r"function updatePreview\(\) \{(.*?)\n  \}", scripts["app"], re.DOTALL
    )[1]
    assert not re.search(r"\bpdfPreview\s*\.\s*pages\b", sizing), (
        "Preview height must not depend on document page count"
    )
    assert "ResizeObserver" in scripts["app"]
    assert "#view=FitH&navpanes=0" in scripts["app"]
    assert "toolbar=0" not in scripts["app"]
    css = re.search(
        r"<style>(.*?)</style>", (site / "index.html").read_text(), re.DOTALL
    )[1]
    iframe_rule = re.search(r"iframe\s*\{([^}]+)\}", css)[1]
    assert not re.search(r"(?:^|;)\s*height\s*:", iframe_rule)


def test_assembled_sample_selection_tracks_the_successfully_opened_choice(
    build_module, stand_in_wheel, tmp_path
):
    # Static provenance contract, not automated interaction acceptance. The
    # originating choice must survive reads/queueing and belong to the open tree.
    site = tmp_path / "site"
    build_module.assemble_site(stand_in_wheel, site)
    app = assembled_scripts(site)["app"]
    assert re.search(r'name: manifest.sample.name, rootId: "I1"', app)
    assert "sendOpen(choice, bytes)" in app
    assert "openingFiles.push(choice)" in app
    opened = re.search(r'case "opened": \{(.*?)\n      \}', app, re.DOTALL)[1]
    assert "const choice = openingFiles.shift()" in opened
    assert "currentTreeChoice = choice" in opened
    search = re.search(
        r"function scheduleSearch\([^)]*\) \{(.*?)\n  \}", app, re.DOTALL
    )[1]
    assert "currentTreeChoice?.rootId" in search
    assert re.search(r"pendingSearch = \{[^}]*rootId", search)
    sample = json.loads(assembled_scripts(site)["manifest"])["sample"]
    session = Session()
    assert session.open(sample["text"].encode()) == 47
    assert session.search("I1", False, True)[1] == [
        ["I1", "George WASHINGTON", "1732-1799"]
    ]


def test_assembled_failed_open_recovers_only_unselected_sample_without_pending_search(
    build_module, stand_in_wheel, tmp_path
):
    # Static scheduling contract; web/browser_tests/test_ordering.py exercises
    # failed-open recovery with held replies and explicit root selection.
    site = tmp_path / "site"
    build_module.assemble_site(stand_in_wheel, site)
    app = assembled_scripts(site)["app"]
    failed_open = re.search(
        r'if \(reply.request === "open"\) \{(.*?)\n        \} else if',
        app,
        re.DOTALL,
    )[1]
    assert re.search(
        r"if \(!openOutstanding\) \{\s*"
        r"if \(!root && currentTreeChoice\?\.rootId && !pendingSearch\) \{\s*"
        r"scheduleSearch\(true\);\s*"
        r"\} else \{\s*sendPendingSearch\(\);\s*\}\s*\}",
        failed_open,
    ), "Final failed replacement must restore canceled sample search, with guards"
    assert "maybeRender();" in failed_open


def test_assemble_escapes_sample_text_before_embedding_json(
    build_module, stand_in_wheel, tmp_path, monkeypatch
):
    sample = tmp_path / "pedigree.ged"
    sample.write_text("0 HEAD\n1 NOTE </ScRiPt><!--\n0 TRLR\n")
    monkeypatch.setattr(build_module, "SAMPLE", sample)
    site = tmp_path / "site"
    build_module.assemble_site(stand_in_wheel, site)
    serialized = assembled_scripts(site)["manifest"]
    assert "\\u003c" in serialized
    assert "<" not in serialized
    assert sample.read_text() not in serialized
    assert json.loads(serialized)["sample"]["text"] == sample.read_text()


@pytest.mark.parametrize("filename", ["app.js", "worker.js", "kincade_web.py"])
@pytest.mark.parametrize("token", ["</ScRiPt", "<!--"])
def test_inline_refuses_html_raw_text_tokens(
    build_module, build_inputs, stand_in_wheel, tmp_path, filename, token
):
    (build_inputs / filename).write_text(token)
    site = tmp_path / "site"
    with pytest.raises(SystemExit) as error:
        build_module.assemble_site(stand_in_wheel, site)
    assert filename in str(error.value)
    assert token.lower() in str(error.value).lower()
    assert not site.exists()


@pytest.mark.parametrize("slot", ["manifest", "glue", "worker", "app"])
@pytest.mark.parametrize("count", [0, 2])
def test_assemble_requires_each_unique_template_slot(
    build_module, build_inputs, stand_in_wheel, tmp_path, slot, count
):
    path = build_inputs / "index.html"
    source = path.read_text()
    insertion = re.search(rf'<script[^>]*id="{slot}"[^>]*></script>', source).group()
    path.write_text(source.replace(insertion, insertion * count))
    with pytest.raises(SystemExit, match=slot):
        build_module.assemble_site(stand_in_wheel, tmp_path / "site")


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "name", "url", "sha256", "keys", "type"],
)
def test_build_rejects_invalid_font_manifest(
    build_module, build_inputs, stand_in_wheel, tmp_path, mutation
):
    path = build_inputs / "fonts.json"
    fonts = json.loads(path.read_text())
    if mutation == "missing":
        fonts.pop()
    elif mutation == "duplicate":
        fonts[1] = fonts[0]
    elif mutation == "type":
        fonts[0] = "not a font object"
    elif mutation == "keys":
        fonts[0]["extra"] = True
    else:
        fonts[0][mutation] = "invalid"
    path.write_text(json.dumps(fonts))
    with pytest.raises(SystemExit, match=r"fonts\.json"):
        build_module.assemble_site(stand_in_wheel, tmp_path / "site")


@pytest.mark.parametrize(
    "name",
    ["other-9.8.7-py3-none-any.whl", "kincade.whl", "kincade--py3-none-any.whl"],
)
def test_build_rejects_invalid_wheel_names(build_module, tmp_path, name):
    wheel = tmp_path / name
    wheel.write_bytes(b"wheel")
    with pytest.raises(SystemExit, match="wheel"):
        build_module.assemble_site(wheel, tmp_path / "site")


@pytest.mark.parametrize("wheel_count", [0, 1, 2])
def test_build_wheel_cleans_only_its_cache_and_requires_one_wheel(
    build_module, tmp_path, monkeypatch, wheel_count
):
    cache = tmp_path / ".cache" / "wheel"
    cache.mkdir(parents=True)
    (cache / "stale.whl").write_bytes(b"old")
    sibling = cache.parent / "keep"
    sibling.write_bytes(b"keep")
    monkeypatch.setattr(build_module, "WHEEL_CACHE", cache)

    def run(command, *, check):
        assert check is True
        assert command == ["uv", "build", "--wheel", "--out-dir", str(cache), str(ROOT)]
        assert not (cache / "stale.whl").exists()
        for index in range(wheel_count):
            (cache / f"kincade-{index}.0.0-py3-none-any.whl").write_bytes(b"new")

    monkeypatch.setattr(build_module.subprocess, "run", run)
    if wheel_count == 1:
        assert build_module.build_wheel() == cache / "kincade-0.0.0-py3-none-any.whl"
    else:
        with pytest.raises(SystemExit, match="one wheel"):
            build_module.build_wheel()
    assert sibling.read_bytes() == b"keep"


def test_build_main_replaces_only_the_site_and_prints_both_files(
    build_module, stand_in_wheel, tmp_path, monkeypatch, capsys
):
    site = tmp_path / "site"
    site.mkdir()
    (site / "stale.txt").write_text("stale")
    sibling = tmp_path / "keep.txt"
    sibling.write_text("keep")
    monkeypatch.setattr(build_module, "SITE", site)
    monkeypatch.setattr(build_module, "build_wheel", lambda: stand_in_wheel)
    build_module.main()
    assert {path.name for path in site.iterdir()} == {"index.html", stand_in_wheel.name}
    assert sibling.read_text() == "keep"
    assert capsys.readouterr().out.splitlines() == [
        f"index.html: {(site / 'index.html').stat().st_size} bytes",
        f"{stand_in_wheel.name}: {stand_in_wheel.stat().st_size} bytes",
    ]


def ancestry_chain(depth):
    lines = []
    for n in range(1, depth + 1):
        lines += [f"0 @I{n}@ INDI", f"1 NAME Depth{n:02d} /Chain/"]
        if n < depth:
            lines += [f"1 FAMC @F{n}@", f"0 @F{n}@ FAM", f"1 HUSB @I{n + 1}@"]
    return "\n".join(lines).encode()


@pytest.mark.parametrize("depth", [1, 11, 17])
@pytest.mark.parametrize("large", [False, True])
def test_root_depth_counts_known_occupied_generations(depth, large):
    session = Session()
    session.open(ancestry_chain(depth))
    assert session.pedigree_depth("I1", False, large) == depth
    assert session.pedigree_depth(f"I{depth}", False, large) == 1


@pytest.mark.parametrize(
    "fixture,adoptive,large,depth",
    [
        ("quirks.ged", False, False, 4),
        ("quirks.ged", True, False, 2),
        ("cycle.ged", False, False, 7),
        ("cycle.ged", False, True, 3),
        ("collapse.ged", False, False, 5),
    ],
)
def test_root_depth_uses_renderer_parent_and_cycle_rules(
    fixture, adoptive, large, depth
):
    session = Session()
    session.open((FIX / fixture).read_bytes())
    assert session.pedigree_depth("I1", adoptive, large) == depth


def test_root_depth_ignores_missing_people_and_page_padding():
    session = Session()
    session.open(
        ancestry_chain(2)
        + b"\n1 FAMC @MissingFamily@\n0 @MissingFamily@ FAM\n1 HUSB @MissingPerson@"
    )
    assert session.pedigree_depth("I1", False, False) == 2


def test_root_depth_validation_preserves_preview_and_fonts(session):
    session.render("I1", "fan", {"paper": "tabloid"})
    preview, fonts = session.preview, session.fonts
    assert session.pedigree_depth("I1", False, False) >= 1
    with pytest.raises(ValueError, match="Unknown root"):
        session.pedigree_depth("missing", False, False)
    assert session.preview is preview
    assert session.fonts is fonts
    with pytest.raises(ValueError, match="Open a GEDCOM"):
        Session().pedigree_depth("I1", False, False)


def test_root_depth_cache_is_per_context_and_successful_dataset(monkeypatch):
    session = Session()
    session.open((FIX / "cycle.ged").read_bytes())
    calls = []
    real_plan = kincade_web.plan_charts

    def plan(*args):
        calls.append(args)
        return real_plan(*args)

    monkeypatch.setattr(kincade_web, "plan_charts", plan)
    assert session.pedigree_depth("I1", False, False) == 7
    assert session.pedigree_depth("I1", False, False) == 7
    assert len(calls) == 1
    assert session.pedigree_depth("I1", False, True) == 3
    assert session.pedigree_depth("I1", True, True) == 3
    assert session.pedigree_depth("I2", False, True) == 3
    assert len(calls) == 4
    session.search("", False, True)
    assert len(calls) == 4  # Searching people never plans their ancestry.
    with pytest.raises(ValueError):
        session.open(b"0 HEAD\n0 TRLR")
    assert session.pedigree_depth("I1", False, False) == 7
    assert len(calls) == 4
    session.open(ancestry_chain(11))
    assert session.pedigree_depth("I1", False, False) == 11
    assert len(calls) == 5


MARRIAGES = b"""0 HEAD
0 @I1@ INDI
1 NAME Root /Ashford/
1 DEAT Y
1 FAMS @F1@
1 FAMS @F2@
0 @I2@ INDI
1 NAME First /McClure/
1 DEAT Y
1 FAMS @F1@
0 @I3@ INDI
1 NAME Second /DeWitt/
1 DEAT Y
1 FAMS @F2@
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 MARR
2 DATE 1901
2 PLAC Firsttown
0 @F2@ FAM
1 HUSB @I1@
1 WIFE @I3@
1 MARR
2 DATE 1922
2 PLAC Secondtown
0 TRLR
"""


@pytest.fixture
def marriage_session():
    result = Session()
    result.open(MARRIAGES)
    return result


def test_root_family_choices_pair_spouses_and_marriages_in_recorded_order(
    marriage_session,
):
    choices = marriage_session.root_families("I1")
    assert choices == [
        {"id": "F1", "label": "F1 · First McCLURE · m. 1901 · mp. Firsttown"},
        {"id": "F2", "label": "F2 · Second DEWITT · m. 1922 · mp. Secondtown"},
    ]
    assert marriage_session.root_families("I2", preserve_case=True) == [
        {"id": "F1", "label": "F1 · Root Ashford · m. 1901 · mp. Firsttown"}
    ]


@pytest.mark.parametrize("living", ["I1", "I3"])
def test_root_family_choices_hide_marriage_for_either_living_partner(
    marriage_session,
    living,
):
    marriage_session.tree.people[living].living = True
    choices = marriage_session.root_families("I1", exclude_private=True)
    assert choices[1] == {
        "id": "F2",
        "label": "F2 · Living" if living == "I3" else "F2 · Second DEWITT",
    }
    assert marriage_session.root_families("I1")[1]["label"] == (
        "F2 · Second DEWITT · m. 1922 · mp. Secondtown"
    )


def test_root_family_choices_handle_missing_links_without_changing_default(
    marriage_session,
):
    tree = marriage_session.tree
    root = tree.people["I1"]
    root.families = ["missing", "F1", "F1", "unrelated"]
    tree.families["F2"].mother = "unknown-person"
    tree.families["F2"].marriage = None
    tree.families["unrelated"] = type(tree.families["F1"])("unrelated", "I2", "I3")
    assert marriage_session.root_families("I1") == [
        {"id": "F1", "label": "F1 · First McCLURE · m. 1901 · mp. Firsttown"},
        {"id": "F2", "label": "F2 · Unknown spouse"},
    ]
    assert root.families[0] == "missing"
    assert marriage_session.root_families("I3")[-1]["id"] == "unrelated"


def test_root_family_choice_validation_and_new_files(marriage_session):
    with pytest.raises(ValueError, match="Unknown root"):
        marriage_session.root_families("missing")
    with pytest.raises(ValueError, match="Open a GEDCOM"):
        Session().root_families("I1")
    marriage_session.open(b"0 @I1@ INDI\n1 NAME New /Root/\n0 TRLR")
    assert marriage_session.root_families("I1") == []


def test_browser_render_root_family_override_matches_real_options(
    marriage_session,
    monkeypatch,
):
    monkeypatch.setattr(rl_config, "invariant", True)
    actual = marriage_session.render("I1", "pedigree", {"root_family": "F2"})[0]
    expected = render_with_counts(
        marriage_session.tree,
        "I1",
        Options(root_family="F2", fonts=marriage_session.fonts),
    ).pdf
    assert actual == expected
    assert actual != marriage_session.render("I1", "pedigree", {})[0]
    with pytest.raises(ValueError):
        marriage_session.render("I1", "fan", {"root_family": "F2"})
    with pytest.raises(ValueError):
        marriage_session.render("I2", "pedigree", {"root_family": "F2"})
