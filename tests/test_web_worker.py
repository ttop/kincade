"""The worker API exactly as worker.js calls it: the browser's Python runs here under
CPython, through the same JSON requests and replies app.js sends and reads."""

import json
import re

import pytest
from reportlab import rl_config

import kincade.pdf
from kincade import FanOptions, plan_fan, render_fan
from kincade.gedcom import read_gedcom
from kincade.pdf import BASE14, Options, render_with_counts

from conftest import FIX, ROOT, ged
from pdfread import count_pages

# ---------------------------------------------------------------- the dispatch fixture


class Bytes:
    """Stands in for the JsProxy buffer worker.js hands the dispatcher: a buffer with
    to_bytes()."""

    def __init__(self, data):
        self._data = data

    def to_bytes(self):
        return self._data


def _worker_dispatch_source():
    """The Python template literal inside worker.js: the second pyodide.runPython(`
    call, which defines _web_session and _web_dispatch. It holds no ${ interpolation,
    so it is plain Python."""
    source = (ROOT / "web" / "worker.js").read_text(encoding="utf-8")
    marker = "pyodide.runPython(`"
    first = source.index(marker)
    start = source.index(marker, first + len(marker)) + len(marker)
    end = source.index("`);", start)
    return source[start:end]


@pytest.fixture
def dispatch(monkeypatch):
    """request, data=None -> the worker's reply dict. Runs kincade_web.py and the
    Python worker.js hands to pyodide.runPython, in one namespace, deterministically."""
    monkeypatch.setattr(rl_config, "invariant", True)
    ns: dict[str, object] = {"__name__": "kincade_web"}
    exec(  # noqa: S102 -- this is the Python the worker runs, run under CPython
        compile(
            (ROOT / "web" / "kincade_web.py").read_text(encoding="utf-8"),
            "kincade_web.py",
            "exec",
        ),
        ns,
    )
    exec(compile(_worker_dispatch_source(), "worker.js", "exec"), ns)  # noqa: S102

    def call(request, data=None):
        return ns["_web_dispatch"](json.dumps(request), Bytes(data))

    call.ns = ns
    return call


# ---------------------------------------------------------------- local data

# Root, with two marriages (F1 and F2).
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
1 BIRT
2 DATE 2000
1 FAMS @F2@
0 @I4@ INDI
1 NAME Alone /Root/
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
2 DATE 2022
2 PLAC Secondtown
0 TRLR
"""

PEDIGREE_DEFAULTS = {
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
}

FAN_DEFAULTS = {
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
}


def ancestry_chain(depth):
    """I1..I`depth`, each the child of the next, in file order."""
    lines = []
    for n in range(1, depth + 1):
        lines += [f"0 @I{n}@ INDI", f"1 NAME Depth{n:02d} /Chain/"]
        if n < depth:
            lines += [f"1 FAMC @F{n}@", f"0 @F{n}@ FAM", f"1 HUSB @I{n + 1}@"]
    return "\n".join(lines).encode()


def metadata_request(seq, tree_version, root_id, **context):
    base = {
        "adoptiveParents": False,
        "largePrint": False,
        "excludePrivate": False,
        "preserveCase": False,
        "lang": "en",
    }
    base.update(context)
    return {
        "type": "root-metadata",
        "seq": seq,
        "treeVersion": tree_version,
        "rootId": root_id,
        **base,
    }


# ---------------------------------------------------------------- tests


def test_open_search_metadata_render_round_trip(dispatch, frozen_today):
    tree = read_gedcom(FIX / "pedigree.ged")
    opened = dispatch({"type": "open"}, (FIX / "pedigree.ged").read_bytes())
    assert opened == {"type": "opened", "count": 28}

    found = dispatch(
        {
            "type": "search",
            "seq": 1,
            "text": "mcclure",
            "excludePrivate": False,
            "standins": True,
        }
    )
    assert found["seq"] == 1 and found["total"] == 3
    assert [row[:2] for row in found["rows"]] == [
        ["I3", "Mary McCLURE"],
        ["I6", "William McCLURE"],
        ["I12", "Samuel McCLURE"],
    ]
    assert all(len(row) == 3 for row in found["rows"])

    empty = dispatch(
        {
            "type": "search",
            "seq": 2,
            "text": "",
            "excludePrivate": False,
            "standins": True,
        }
    )
    assert len(empty["rows"]) == 28

    metadata = dispatch(metadata_request(3, 1, "I1"))
    assert metadata["depth"] == 8
    assert metadata["families"] == [
        {
            "id": "F101",
            "spouse": "Tom BAKER",
            "details": ["m. 5 Jun 2005", "mp. Peoria, Illinois"],
        }
    ]
    context = {
        "treeVersion": 1,
        "rootId": "I1",
        "adoptiveParents": False,
        "largePrint": False,
        "excludePrivate": False,
        "preserveCase": False,
        "lang": "en",
    }
    for key, value in context.items():
        assert metadata[key] == value, key

    rendered = dispatch(
        {
            "type": "render",
            "seq": 4,
            "rootId": "I1",
            "chart": "pedigree",
            "settings": PEDIGREE_DEFAULTS,
        }
    )
    assert rendered["pdf"] == render_with_counts(tree, "I1", Options(fonts=BASE14)).pdf
    assert rendered["filename"] == "Jane ASHFORD cascading pedigree.pdf"
    assert rendered["summary"] == {"charts": 6, "indexPages": 1, "pages": 7}
    assert rendered["preview"] == {"pages": 7, "width": 612, "height": 792}

    fan_reply = dispatch(
        {
            "type": "render",
            "seq": 5,
            "rootId": "I1",
            "chart": "fan",
            "settings": FAN_DEFAULTS,
        }
    )
    assert fan_reply["summary"] == {"generations": 6, "people": 23}
    assert fan_reply["preview"] == {"pages": 1, "width": 792, "height": 612}


def test_errors_are_replies(dispatch):
    before_open = dispatch(
        {
            "type": "search",
            "seq": 1,
            "text": "",
            "excludePrivate": False,
            "standins": True,
        }
    )
    assert before_open == {
        "type": "error",
        "request": "search",
        "message": "Open a GEDCOM file first",
        "code": None,
        "details": "",
        "seq": 1,
    }

    dispatch({"type": "open"}, (FIX / "pedigree.ged").read_bytes())

    no_people = dispatch({"type": "open"}, b"0 HEAD\n0 TRLR\n")
    assert no_people == {
        "type": "error",
        "request": "open",
        "message": "GEDCOM file has no people",
        "code": "noPeople",
        "details": "",
    }
    kept = dispatch(
        {
            "type": "search",
            "seq": 2,
            "text": "",
            "excludePrivate": False,
            "standins": True,
        }
    )
    assert kept["total"] == 28

    stale = dispatch(metadata_request(3, 0, "I1"))
    assert stale == {
        "type": "error",
        "request": "root-metadata",
        "message": "The family tree has changed",
        "code": None,
        "details": "",
        "seq": 3,
    }

    unknown_key = dispatch(
        {
            "type": "render",
            "seq": 4,
            "rootId": "I1",
            "chart": "fan",
            "settings": {"index": False},
        }
    )
    assert unknown_key["message"] == "Unknown fan settings: index"
    unknown_root = dispatch(
        {
            "type": "render",
            "seq": 5,
            "rootId": "missing",
            "chart": "pedigree",
            "settings": {},
        }
    )
    assert unknown_root["message"] == "Unknown root record ID 'missing'"
    unknown_chart = dispatch(
        {"type": "render", "seq": 6, "rootId": "I1", "chart": "bogus", "settings": {}}
    )
    assert unknown_chart["message"] == "Unknown chart 'bogus'"
    unknown_operation = dispatch({"type": "bogus-operation"})
    assert unknown_operation == {
        "type": "error",
        "request": "bogus-operation",
        "message": "Unknown request 'bogus-operation'",
        "code": None,
        "details": "",
    }

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    dispatch.ns["render_with_counts"] = explode
    crashed = dispatch(
        {
            "type": "render",
            "seq": 7,
            "rootId": "I1",
            "chart": "pedigree",
            "settings": {},
        }
    )
    assert crashed["type"] == "error" and crashed["request"] == "render"
    assert crashed["message"] == "Unable to render the family tree."
    assert crashed["code"] is None
    assert "RuntimeError" in crashed["details"] and "boom" in crashed["details"]
    assert crashed["seq"] == 7


def test_render_validates_settings(dispatch):
    dispatch({"type": "open"}, (FIX / "pedigree.ged").read_bytes())
    rejected = [
        ("pedigree", "generations", 0),
        ("pedigree", "generations", -1),
        ("pedigree", "generations", 1.5),
        ("pedigree", "generations", True),
        ("pedigree", "generations", "3"),
        ("fan", "generations", 1),
        ("fan", "generations", 8),
        ("fan", "generations", None),
        ("pedigree", "lang", "xx"),
    ]
    for chart, key, value in rejected:
        reply = dispatch(
            {
                "type": "render",
                "seq": 1,
                "rootId": "I1",
                "chart": chart,
                "settings": {key: value},
            }
        )
        assert reply["type"] == "error", (chart, key, value)

    pedigree_only_key = dispatch(
        {
            "type": "render",
            "seq": 2,
            "rootId": "I1",
            "chart": "fan",
            "settings": {"index": False},
        }
    )
    assert pedigree_only_key["type"] == "error"

    for value in (None, 1, 12):
        accepted = dispatch(
            {
                "type": "render",
                "seq": 3,
                "rootId": "I1",
                "chart": "pedigree",
                "settings": {"generations": value},
            }
        )
        assert accepted["type"] == "rendered", value
    for value in range(2, 8):
        accepted = dispatch(
            {
                "type": "render",
                "seq": 4,
                "rootId": "I1",
                "chart": "fan",
                "settings": {"generations": value},
            }
        )
        assert accepted["type"] == "rendered", value


@pytest.mark.parametrize("chart", ["pedigree", "fan"])
def test_every_page_key_reaches_the_library(dispatch, chart, frozen_today):
    """Every PAGE_OPTIONS key, at a non-default value, gives the dispatcher's render
    the same bytes as calling Options/render_with_counts or plan_fan/render_fan
    directly."""
    from kincade_web import PAGE_OPTIONS

    dispatch({"type": "open"}, MARRIAGES)
    tree = read_gedcom(MARRIAGES)
    if chart == "pedigree":
        settings = {
            "generations": 3,
            "exclude_private": True,
            "adoptive_parents": True,
            "event_standins": False,
            "empty_boxes": False,
            "show_ids": True,
            "shorten_places": False,
            "index": False,
            "page_numbers": False,
            "footer": "Custom footer",
            "title": "Custom title",
            "paper": "a4",
            "large_print": True,
            "preserve_case": True,
            "shadow": True,
            "root_family": "F2",
            "lang": "de",
        }
        assert set(settings) == PAGE_OPTIONS["pedigree"]
        reply = dispatch(
            {
                "type": "render",
                "seq": 1,
                "rootId": "I1",
                "chart": "pedigree",
                "settings": settings,
            }
        )
        expected = render_with_counts(tree, "I1", Options(**settings, fonts=BASE14)).pdf
        assert reply["pdf"] == expected
    else:
        base = {
            "generations": 5,
            "exclude_private": True,
            "adoptive_parents": True,
            "event_standins": False,
            "preserve_case": True,
            "paper": "a4",
            "title": "Custom title",
            "footer": "Custom footer",
            "lang": "de",
        }
        planning_keys = (
            "generations",
            "exclude_private",
            "adoptive_parents",
            "event_standins",
            "preserve_case",
            "lang",
        )
        drawing_keys = ("paper", "title", "footer", "lang")
        for ink in ("color", "grayscale", "bw"):
            settings = {**base, "ink": ink}
            assert set(settings) == PAGE_OPTIONS["fan"], ink
            reply = dispatch(
                {
                    "type": "render",
                    "seq": 1,
                    "rootId": "I1",
                    "chart": "fan",
                    "settings": settings,
                }
            )
            planning = {key: settings[key] for key in planning_keys}
            drawing = {key: settings[key] for key in drawing_keys}
            fan = plan_fan(tree, "I1", **planning, ink=ink)
            expected = render_fan(fan, FanOptions(**drawing, ink=ink, fonts=BASE14))
            assert reply["pdf"] == expected, ink


def test_preview_matches_the_pdf(dispatch):
    dispatch({"type": "open"}, (FIX / "pedigree.ged").read_bytes())
    assert dispatch.ns["_web_session"].preview is None

    for paper, width, height in (("letter", 612, 792), ("a4", 595.28, 841.89)):
        for index in (False, True):
            for large_print in (False, True):
                reply = dispatch(
                    {
                        "type": "render",
                        "seq": 1,
                        "rootId": "I1",
                        "chart": "pedigree",
                        "settings": {
                            "paper": paper,
                            "index": index,
                            "large_print": large_print,
                        },
                    }
                )
                page_count = count_pages(reply["pdf"])
                boxes = re.findall(
                    rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", reply["pdf"]
                )
                assert len(boxes) == page_count, (paper, index, large_print)
                assert [(float(w), float(h)) for w, h in boxes] == [
                    (width, height)
                ] * page_count, (paper, index, large_print)
                assert reply["preview"] == {
                    "pages": page_count,
                    "width": width,
                    "height": height,
                }, (paper, index, large_print)

    for paper, width, height in (
        ("letter", 792, 612),
        ("a4", 841.89, 595.28),
        ("tabloid", 1224, 792),
        ("a3", 1190.55, 841.89),
    ):
        reply = dispatch(
            {
                "type": "render",
                "seq": 2,
                "rootId": "I1",
                "chart": "fan",
                "settings": {"paper": paper},
            }
        )
        assert count_pages(reply["pdf"]) == 1, paper
        boxes = re.findall(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", reply["pdf"])
        assert [(float(w), float(h)) for w, h in boxes] == [(width, height)], paper
        assert reply["preview"] == {"pages": 1, "width": width, "height": height}, paper

    baseline = dispatch(
        {
            "type": "render",
            "seq": 3,
            "rootId": "I1",
            "chart": "fan",
            "settings": {"paper": "tabloid"},
        }
    )
    for chart, settings in (
        ("pedigree", {"generations": 0}),
        ("fan", {"generations": 8}),
    ):
        failed = dispatch(
            {
                "type": "render",
                "seq": 4,
                "rootId": "I1",
                "chart": chart,
                "settings": settings,
            }
        )
        assert failed["type"] == "error", chart
        assert dispatch.ns["_web_session"].preview == baseline["preview"], chart


def test_root_metadata_depth(dispatch):
    tree_version = 0

    def open_tree(data):
        nonlocal tree_version
        reply = dispatch({"type": "open"}, data)
        if reply["type"] == "opened":
            tree_version += 1
        return reply

    def depth(root_id, adoptive=False, large=False):
        return dispatch(
            metadata_request(
                1, tree_version, root_id, adoptiveParents=adoptive, largePrint=large
            )
        )["depth"]

    open_tree(ancestry_chain(11))
    assert depth("I1") == 11
    assert depth("I11") == 1

    for fixture, adoptive, large, expected in (
        ("quirks.ged", False, False, 4),
        ("quirks.ged", True, False, 2),
        ("cycle.ged", False, False, 7),
        ("cycle.ged", False, True, 3),
        ("collapse.ged", False, False, 5),
    ):
        open_tree((FIX / fixture).read_bytes())
        assert depth("I1", adoptive, large) == expected, fixture

    open_tree(
        ancestry_chain(2)
        + b"\n1 FAMC @MissingFamily@\n0 @MissingFamily@ FAM\n1 HUSB @MissingPerson@"
    )
    assert depth("I1") == 2

    # The cache is per (root, adoptive, large) context, and clears on a successful open.
    open_tree((FIX / "cycle.ged").read_bytes())
    calls = []
    real_plan_charts = dispatch.ns["plan_charts"]

    def counting(*args):
        calls.append(args)
        return real_plan_charts(*args)

    dispatch.ns["plan_charts"] = counting
    assert depth("I1") == 7
    assert depth("I1") == 7
    assert len(calls) == 1
    assert depth("I1", large=True) == 3
    assert depth("I1", adoptive=True, large=True) == 3
    assert depth("I2", large=True) == 3
    assert len(calls) == 4
    bad_open = open_tree(b"0 HEAD\n0 TRLR\n")
    assert bad_open["type"] == "error"
    assert depth("I1") == 7
    assert len(calls) == 4
    open_tree(ancestry_chain(11))
    assert depth("I1") == 11
    assert len(calls) == 5


def test_root_metadata_families(dispatch):
    def families(root_id, **context):
        return dispatch(metadata_request(1, 1, root_id, **context))["families"]

    dispatch({"type": "open"}, MARRIAGES)
    assert families("I1") == [
        {
            "id": "F1",
            "spouse": "First McCLURE",
            "details": ["m. 1901", "mp. Firsttown"],
        },
        {
            "id": "F2",
            "spouse": "Second DEWITT",
            "details": ["m. 2022", "mp. Secondtown"],
        },
    ]
    assert families("I2", preserveCase=True) == [
        {"id": "F1", "spouse": "Root Ashford", "details": ["m. 1901", "mp. Firsttown"]}
    ]
    assert families("I1", lang="fr")[0] == {
        "id": "F1",
        "spouse": "First McCLURE",
        "details": ["mar. 1901", "à Firsttown"],
    }

    # Either partner possibly living hides the marriage details, and a living spouse
    # is "Living".
    dispatch.ns["_web_session"].tree.people["I1"].living = True
    assert families("I1", excludePrivate=True) == [
        {"id": "F1", "spouse": "First McCLURE", "details": []},
        {"id": "F2", "spouse": "Living", "details": []},
    ]

    # Families come in FAMS order, then partner families with no backlink; missing
    # links are handled without changing the recorded order. (excludePrivate stays
    # False below, so I1's living override from the previous check has no effect.)
    tree = dispatch.ns["_web_session"].tree
    root = tree.people["I1"]
    root.families = ["missing", "F1", "F1", "unrelated"]
    tree.families["F2"].mother = "unknown-person"
    tree.families["F2"].marriage = None
    tree.families["unrelated"] = type(tree.families["F1"])("unrelated", "I2", "I3")
    assert families("I1") == [
        {
            "id": "F1",
            "spouse": "First McCLURE",
            "details": ["m. 1901", "mp. Firsttown"],
        },
        {"id": "F2", "spouse": "", "details": []},
    ]
    assert root.families[0] == "missing"
    assert families("I3")[-1]["id"] == "unrelated"


def test_search_keeps_names_and_hides_living_years(dispatch):
    dispatch({"type": "open"}, (FIX / "pedigree.ged").read_bytes())
    private = dispatch(
        {
            "type": "search",
            "seq": 1,
            "text": "I1",
            "excludePrivate": True,
            "standins": True,
        }
    )["rows"][0]
    assert private[1] == "Jane ASHFORD"  # the real name is kept
    assert private[2] == ""  # the years are hidden

    plain = dispatch(
        {
            "type": "search",
            "seq": 2,
            "text": "I1",
            "excludePrivate": False,
            "standins": True,
        }
    )["rows"][0]
    assert plain[2] != ""

    # standins toggles whether a stand-in event supplies the written years.
    dispatch(
        {"type": "open"},
        ged("0 @I1@ INDI", "1 NAME Chris /Doe/", "1 CHR", "2 DATE 1850"),
    )
    with_standin = dispatch(
        {
            "type": "search",
            "seq": 3,
            "text": "",
            "excludePrivate": False,
            "standins": True,
        }
    )["rows"][0][2]
    without_standin = dispatch(
        {
            "type": "search",
            "seq": 4,
            "text": "",
            "excludePrivate": False,
            "standins": False,
        }
    )["rows"][0][2]
    assert with_standin != without_standin

    # The rows stop at 200 while the total counts all matches.
    many = b"\n".join(
        f"0 @I{i}@ INDI\n1 NAME Person{i:03} /Many/".encode() for i in range(1, 251)
    )
    dispatch({"type": "open"}, many)
    result = dispatch(
        {
            "type": "search",
            "seq": 5,
            "text": "",
            "excludePrivate": False,
            "standins": True,
        }
    )
    assert result["total"] == 250
    assert len(result["rows"]) == 200


def test_the_chart_language_words_the_pdf_and_the_file_name(dispatch):
    dispatch({"type": "open"}, (FIX / "pedigree.ged").read_bytes())
    dispatch.ns["_web_session"].tree.people["I1"].living = True
    pedigree_reply = dispatch(
        {
            "type": "render",
            "seq": 1,
            "rootId": "I1",
            "chart": "pedigree",
            "settings": {"lang": "fr", "exclude_private": True},
        }
    )
    assert pedigree_reply["filename"] == "Arbre d'ascendance Personne vivante.pdf"

    fan_reply = dispatch(
        {
            "type": "render",
            "seq": 2,
            "rootId": "I1",
            "chart": "fan",
            "settings": {"lang": "it", "exclude_private": True},
        }
    )
    assert fan_reply["filename"] == "Persona vivente albero a ventaglio.pdf"

    # The file name keeps the recorded surname case.
    dispatch({"type": "open"}, ged("0 @I1@ INDI", "1 NAME Jane /Ashford/", "1 DEAT Y"))
    plain = dispatch(
        {"type": "render", "seq": 3, "rootId": "I1", "chart": "fan", "settings": {}}
    )
    assert plain["filename"] == "Jane Ashford fan chart.pdf"


def test_session_fonts(dispatch, tmp_path, monkeypatch):
    dispatch({"type": "open"}, (FIX / "pedigree.ged").read_bytes())
    session = dispatch.ns["_web_session"]

    empty = tmp_path / "empty"
    empty.mkdir()
    assert session.load_fonts(empty) == "base14"
    assert session.fonts is BASE14

    loaded = []

    def load_face(path, psname):
        loaded.append((path.name, psname))
        return kincade.pdf._Face(
            f"F-{len(loaded)}-{path.stem}", lambda ch: ord(ch) < 0x250
        )

    monkeypatch.setattr(kincade.pdf, "_load_ttf", load_face)
    liberation = tmp_path / "liberation"
    liberation.mkdir()
    for name in (
        "LiberationSans-Regular.ttf",
        "LiberationSans-Bold.ttf",
        "LiberationSerif-Regular.ttf",
        "LiberationSerif-Italic.ttf",
    ):
        (liberation / name).write_bytes(b"")
    assert session.load_fonts(liberation) == "embedded"
    assert session.fonts is not BASE14

    # A failure resets to BASE14.
    dispatch.ns["load_fontset"] = lambda dirs: (None, ["italic"])
    assert session.load_fonts(tmp_path) == "base14"
    assert session.fonts is BASE14
