"""The public library API: kincade.__all__, the package docstring's promises, and the
Options dataclass. render(tree, root, options) -> bytes plans the charts, applies
privacy and draws, for a Tree read from GEDCOM or built in code; render_blank(options)
-> bytes needs no tree. Options holds every setting under the name of the command-line
flag.

Synthetic data only, built in code or read from the fixtures.
"""

import dataclasses
import datetime
import inspect
import re
from collections import Counter

import pytest
from reportlab import rl_config

import kincade
import kincade.cli
import kincade.gedcom
import kincade.pdf
from kincade import (
    Date,
    Day,
    Event,
    Family,
    LangError,
    Options,
    ParentLink,
    Person,
    Tree,
    read_gedcom,
    render,
    render_blank,
)
from kincade.charts import plan_charts
from kincade.fanpdf import FanOptions
from kincade.fanplan import plan_fan
from kincade.pdf import render_pdf

from conftest import FIX, TODAY
from conftest import render as render_with_defaults
from pdfread import count_pages, drawn, rectangles, runs


def opts(**kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("fonts", "base14")
    kw.setdefault("compress", False)
    return Options(**kw)


# ---------------------------------------------------------------- the names


def test_the_public_names():
    """__all__ matches kincade/__init__.py exactly, every name in it imports,
    __version__ is a string, and the CLI's own helpers are not exported.
    """
    assert kincade.__all__ == [
        "Date",
        "Day",
        "Event",
        "Family",
        "Fan",
        "FanCell",
        "FanOptions",
        "LangError",
        "LegendEntry",
        "Options",
        "ParentLink",
        "Person",
        "Tree",
        "__version__",
        "load_fontset",
        "plan_fan",
        "read_gedcom",
        "render",
        "render_blank",
        "render_fan",
    ]
    for name in kincade.__all__:
        assert hasattr(kincade, name), name
    assert isinstance(kincade.__version__, str)
    assert (
        kincade.render is kincade.pdf.render
        and kincade.read_gedcom is kincade.gedcom.read_gedcom
    )
    for name in ("person_line", "pedigree_summary", "fan_summary"):
        assert name not in kincade.__all__


# ---------------------------------------------------------------- one call, no GEDCOM


def _built_tree():
    """Dayton Pell (root), his birth parents, and a second, adoptive family whose
    mother is a step-parent. Bob is known only by a christening (no birth record);
    Cy by a birth and a burial (no death record). Ann's `living` overrides her
    estimate. Dates are historical so nobody but Ann counts as possibly living.
    """
    exact = lambda y, m=None, d=None: Event(Date("exact", Day(y, m, d)))
    return Tree(
        people={
            "p1": Person(
                "p1",
                given="Dayton",
                surname="Pell",
                birth=Event(Date("exact", Day(1850, 4, 2)), "Reno, NV"),
                parents=[
                    ParentLink("f1", "birth", "birth"),
                    ParentLink("f3", "adopted", "step"),
                ],
            ),
            "p2": Person(
                "p2",
                given="Bob",
                surname="Pell",
                christenings=[Event(Date("exact", Day(1800)), "St Mark")],
                families=["f1"],
            ),
            "p3": Person(
                "p3",
                given="Ann",
                surname="Gray",
                birth=exact(1805),
                families=["f1"],
                living=True,
            ),
            "p4": Person(
                "p4",
                given="Cy",
                surname="Pell",
                birth=exact(1803),
                burials=[Event(Date("exact", Day(1870)))],
                families=["f3"],
            ),
            "p6": Person(
                "p6", given="Rita", surname="Step", birth=exact(1808), families=["f3"]
            ),
        },
        families={
            "f1": Family(
                "f1",
                father="p2",
                mother="p3",
                marriage=Event(Date("exact", Day(1848)), "Elko, NV"),
                children=["p1"],
            ),
            "f3": Family("f3", father="p4", mother="p6", children=["p1"]),
        },
    )


def test_a_tree_built_in_code_renders_in_one_call():
    """A Tree built from Person, Family, Event, Date, Day and ParentLink, with no
    GEDCOM at all, renders names, dates, a marriage and an index entry; adoptive_parents
    draws the adoptive family with its note and leaves the step-parent's box empty;
    exclude_private shows "Living" for only the person whose `living` is True.
    """
    tree = _built_tree()
    pdf = render(tree, "p1", opts(generations=2))
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    text = drawn(pdf)
    assert "Dayton PELL" in text and "Bob PELL" in text and "Ann GRAY" in text
    assert "Cy PELL" not in text  # birth mode: the step/adopted family is not drawn
    assert "b. 2 Apr 1850" in text and "bp. Reno, NV" in text
    assert "m. 1848" in text and "mp. Elko, NV" in text
    assert "chr. 1800" in text  # Bob's christening stands in for his missing birth
    assert "PELL, Dayton (b. 1850), 1-1" in text

    adoptive = drawn(render(tree, "p1", opts(generations=2, adoptive_parents=True)))
    assert "Dayton PELL (adopted)" in adoptive and "Cy PELL" in adoptive
    assert not any("Rita" in t or "STEP" in t for t in adoptive)  # step box stays empty

    private = drawn(render(tree, "p1", opts(generations=2, exclude_private=True)))
    assert private.count("Living") == 1
    assert "Dayton PELL" in private and "Bob PELL" in private  # not flagged living


# ------------------------------------------------------- paths, bytes, planning, drawing


def test_render_reads_paths_and_bytes_and_is_planning_then_drawing(
    monkeypatch, frozen_today
):
    """read_gedcom of a path and of that file's bytes give the same Tree; render(tree,
    root, options) is byte-equal to planning the charts and drawing them separately;
    render with no Options is byte-equal to Options() given explicitly.
    """
    path = FIX / "pedigree.ged"
    assert read_gedcom(str(path)) == read_gedcom(path.read_bytes())

    # no creation date or random id: equal runs give equal bytes
    monkeypatch.setattr(rl_config, "invariant", 1)
    tree = read_gedcom(path)
    options = opts()
    charts = plan_charts(
        tree, "I1", options.generations, options.parents, options.large_print
    )
    assert render(tree, "I1", options) == render_pdf(charts, tree, options)

    assert render(tree, "I1") == render(tree, "I1", Options())


# ---------------------------------------------------------------- the options


def test_options_mirror_the_command_line():
    """Options and FanOptions are named after the command-line flags that set them,
    with the on/off flags that remove something turned around; their defaults are the
    parser's. plan_fan's keywords mirror the ancestry flags it shares with the CLI.
    """
    # today, compress and fonts have no flags; positional fields retain their order
    assert [f.name for f in dataclasses.fields(Options)] == [
        "generations",
        "exclude_private",
        "adoptive_parents",
        "event_standins",
        "empty_boxes",
        "show_ids",
        "shorten_places",
        "index",
        "page_numbers",
        "footer",
        "title",
        "paper",
        "large_print",
        "shadow",
        "lang",
        "today",
        "compress",
        "fonts",
        "preserve_case",
        "root_family",
    ]
    flags = vars(kincade.cli._parser().parse_args(["x.ged", "--root", "I1"]))
    # a field that is off by default has a flag of its name; one that is on, a no- flag
    for name in (
        "exclude_private",
        "preserve_case",
        "adoptive_parents",
        "show_ids",
        "large_print",
        "shadow",
        "title",
        "paper",
        "generations",
        "lang",
        "root_family",
        "ink",  # FanOptions, not Options
        "footer",  # shared with FanOptions
    ):
        assert name in flags, name
    for name, flag in (
        ("event_standins", "no_event_standins"),
        ("empty_boxes", "no_empty"),
        ("shorten_places", "no_shorten_places"),
        ("index", "no_index"),
        ("page_numbers", "no_page_numbers"),
    ):
        assert flag in flags and getattr(Options(), name) is True, name

    o = Options()
    assert o.preserve_case is False
    assert o.root_family is None
    assert (
        o.generations,
        o.exclude_private,
        o.adoptive_parents,
        o.event_standins,
        o.empty_boxes,
        o.show_ids,
        o.shorten_places,
    ) == (None, False, False, True, True, False, True)
    assert (
        o.index,
        o.page_numbers,
        o.footer,
        o.title,
        o.paper,
        o.large_print,
        o.shadow,
        o.lang,
    ) == (True, True, None, None, "letter", False, False, None)

    # FanOptions: the page flags it shares with Options, minus today/compress/fonts
    assert [f.name for f in dataclasses.fields(FanOptions)] == [
        "ink",
        "paper",
        "lang",
        "title",
        "footer",
        "today",
        "compress",
        "fonts",
    ]
    fan = FanOptions()
    assert (fan.ink, fan.paper, fan.lang, fan.title, fan.footer) == (
        "color",
        "letter",
        None,
        None,
        None,
    )

    # plan_fan's keywords (minus tree and root) are flags too, with its own defaults
    plan_fan_defaults = {
        name: p.default
        for name, p in inspect.signature(plan_fan).parameters.items()
        if p.default is not inspect.Parameter.empty
    }
    assert plan_fan_defaults == {
        "generations": 6,
        "exclude_private": False,
        "adoptive_parents": False,
        "event_standins": True,
        "ink": "color",
        "lang": None,
        "preserve_case": False,
    }
    for name in plan_fan_defaults:
        # event_standins is on by default, like Options.event_standins: its flag
        # is the negated "no_event_standins"
        flag = "no_event_standins" if name == "event_standins" else name
        assert flag in flags, name


def test_each_option_changes_the_pdf(pedigree):
    """Each Options field changes the drawn pedigree PDF in the way its docstring
    promises, checked against the pedigree fixture and its default render.
    """
    base = render_with_defaults(pedigree)
    rows = [
        ("generations=1", {"generations": 1}, lambda pdf: count_pages(pdf) == 2),
        ("index=False", {"index": False}, lambda pdf: count_pages(pdf) == 6),
        (
            "large_print",
            {"large_print": True},
            lambda pdf: (
                count_pages(pdf) > count_pages(base)
                and next(r for r in runs(pdf) if r.text == "Jane ASHFORD").size == 14
            ),
        ),
        (
            "paper=a4",
            {"paper": "a4"},
            lambda pdf: b"/MediaBox [ 0 0 595.28 841.89 ]" in pdf,
        ),
        (
            "shadow",
            {"shadow": True},
            lambda pdf: len(rectangles(pdf, "f*")) > len(rectangles(base, "f*")),
        ),
        ("show_ids", {"show_ids": True}, lambda pdf: "[I1]" in drawn(pdf)),
        (
            "empty_boxes=False",
            {"empty_boxes": False},
            lambda pdf: (
                len(rectangles(pdf, "B*", page=None))
                < len(rectangles(base, "B*", page=None))
            ),
        ),
        (
            "page_numbers=False",
            {"page_numbers": False},
            lambda pdf: not any(t.startswith("Page ") for t in drawn(pdf)),
        ),
        (
            "title=Mine",
            {"title": "Mine"},
            lambda pdf: "Mine" in drawn(pdf) and b"/Title (Mine" in pdf,
        ),
        (
            "footer=False",
            {"footer": False},
            lambda pdf: not any(t.startswith("Created") for t in drawn(pdf)),
        ),
        ("footer=F", {"footer": "F"}, lambda pdf: "F" in drawn(pdf)),
        (
            "lang=de",
            {"lang": "de"},
            lambda pdf: "Ahnentafel — Jane ASHFORD" in drawn(pdf),
        ),
        (
            "preserve_case",
            {"preserve_case": True},
            lambda pdf: (
                "Mary McClure" in drawn(pdf) and "Mary McCLURE" not in drawn(pdf)
            ),
        ),
        (
            "exclude_private",
            {"exclude_private": True},
            lambda pdf: "Living" in drawn(pdf) and "Jane ASHFORD" not in drawn(pdf),
        ),
        (
            "today=2026-03-01",
            {"today": datetime.date(2026, 3, 1)},
            lambda pdf: "Created 1 Mar 2026 using Kincade" in drawn(pdf),
        ),
        ("compress=True", {"compress": True}, lambda pdf: drawn(pdf) == []),
    ]
    for label, kwargs, check in rows:
        assert check(render_with_defaults(pedigree, **kwargs)), label


# ---------------------------------------------------------------- errors


def test_errors_name_the_problem(pedigree):
    """Bad input to render, render_pdf and plan_charts raises the error their
    docstrings promise, each naming the problem.
    """
    with pytest.raises(KeyError):
        render(pedigree, "nobody")
    with pytest.raises(ValueError, match="at least 1"):
        render(pedigree, "I1", opts(generations=0))
    with pytest.raises(ValueError, match=r"letter.*a4"):
        render(pedigree, "I1", opts(paper="legal"))
    with pytest.raises(ValueError, match="no charts to draw"):
        render_pdf([], pedigree, opts())

    large = plan_charts(pedigree, "I1", None, "birth", large_print=True)
    with pytest.raises(ValueError, match="large_print"):
        render_pdf(large, pedigree, opts(large_print=False))
    adoptive = plan_charts(pedigree, "I1", None, "adoptive", large_print=False)
    with pytest.raises(ValueError, match="adoptive_parents"):
        render_pdf(adoptive, pedigree, opts(adoptive_parents=False))

    with pytest.raises(ValueError, match="parents must be one of"):
        plan_charts(pedigree, "I1", None, "bogus", False)

    with pytest.raises(ValueError, match="no such family record"):
        render(pedigree, "I1", opts(root_family="F999"))
    with pytest.raises(ValueError, match="is not a partner"):
        render(pedigree, "I1", opts(root_family="F7"))

    with pytest.raises(LangError):
        render(pedigree, "I1", opts(lang={"title": 3}))


# ---------------------------------------------------------------- model validation


def test_model_values_are_checked_where_they_are_made():
    """Date, Day and ParentLink validate their own fields in __post_init__, each error
    naming the field; a table of consistent Dates is accepted.
    """
    with pytest.raises(ValueError, match="'between' needs both start and end"):
        Date("between", Day(1900))
    with pytest.raises(ValueError, match="belongs to the forms"):
        Date("from", Day(1900), Day(1901))
    with pytest.raises(ValueError, match="'text' needs text"):
        Date("text")

    with pytest.raises(ValueError, match=r"Day\.year"):
        Day(0)
    with pytest.raises(ValueError, match=r"Day\.year"):
        Day(10000)
    with pytest.raises(ValueError, match=r"Day\.month"):
        Day(1900, 13)
    with pytest.raises(ValueError, match=r"Day\.day"):
        Day(1900, 1, 32)
    with pytest.raises(ValueError, match=r"Day\.dual_year"):
        Day(1731, dual_year=1731)

    with pytest.raises(ValueError, match=r"Date\.form"):
        Date("bogus")
    with pytest.raises(ValueError, match=r"Date\.quality"):
        Date("exact", Day(1900), quality="bogus")
    with pytest.raises(ValueError, match=r"ParentLink\.father"):
        ParentLink("f1", father="bogus")
    with pytest.raises(ValueError, match=r"ParentLink\.mother"):
        ParentLink("f1", mother="bogus")

    # every valid form constructs without raising
    Date("exact", Day(1900))
    Date("about", Day(1900))
    Date("before", Day(1900))
    Date("after", Day(1900))
    Date("between", Day(1900), Day(1910))
    Date("from", Day(1900))
    Date("to", Day(1900))
    Date("from_to", Day(1900), Day(1910))
    Date("text", text="sometime")


# ---------------------------------------------------------------- the blank chart


def test_render_blank(monkeypatch):
    """render_blank gives one page in the requested paper, print size, shadow,
    footer and language, with no names; options that have nothing to apply to (such
    as generations, exclude_private, show_ids and root_family) leave it byte-identical
    to leaving them out.
    """
    pdf = render_blank(
        opts(paper="a4", large_print=True, shadow=True, footer="F", lang="de")
    )
    assert pdf.startswith(b"%PDF")
    assert count_pages(pdf) == 1
    assert b"/MediaBox [ 0 0 595.28 841.89 ]" in pdf
    text = Counter(t for t in drawn(pdf) if t)
    assert text == Counter(
        {
            "Ahnentafel": 1,
            "F": 1,
            "Ehe mit:": 1,
            "in": 18,
            "geb.": 7,
            "gest.": 7,
            "verh.": 4,
            **{str(n): 1 for n in range(1, 8)},
        }
    )

    monkeypatch.setattr(rl_config, "invariant", 1)
    plain = render_blank(opts())
    unapplied = render_blank(
        opts(generations=3, exclude_private=True, show_ids=True, root_family="F1")
    )
    assert plain == unapplied


# ---------------------------------------------------------------- metadata


def _living_root_tree():
    """A root (p1) born recently enough that the estimate counts them as possibly
    living, with one birth parent (p2) and one birth mother (p3).
    """
    year = lambda y: Event(Date("exact", Day(y)))
    return Tree(
        people={
            "p1": Person(
                "p1",
                given="Dayton",
                surname="Pell",
                birth=Event(Date("exact", Day(1990, 4, 2)), "Reno, NV"),
                parents=[ParentLink("f1", "birth")],
            ),
            "p2": Person(
                "p2", given="Bob", surname="Pell", birth=year(1960), families=["f1"]
            ),
            "p3": Person(
                "p3", given="Ann", surname="Gray", birth=year(1962), families=["f1"]
            ),
        },
        families={"f1": Family("f1", father="p2", mother="p3", children=["p1"])},
    )


def test_the_pdf_metadata():
    """Creator is Kincade; Author and Subject are empty. The default /Title is
    meta_title with the root's name; title= replaces only the title half. Under
    exclude_private with a living root, /Title and the text carry "Living", never the
    name; an explicit title or footer is kept.
    """
    tree = _living_root_tree()
    pdf = render_with_defaults(tree, "p1")
    assert b"/Creator (Kincade)" in pdf
    assert b"/Author ()" in pdf and b"/Subject ()" in pdf
    assert re.search(rb"/Title \(Cascading Pedigree.*Dayton PELL\)", pdf)

    custom = render_with_defaults(tree, "p1", title="Custom")
    assert re.search(rb"/Title \(Custom.*Dayton PELL\)", custom)

    private = render_with_defaults(tree, "p1", exclude_private=True)
    assert re.search(rb"/Title \(Cascading Pedigree.*Living\)", private)
    assert b"Dayton" not in private

    kept = render_with_defaults(
        tree, "p1", exclude_private=True, title="Explicit", footer="Mine"
    )
    assert re.search(rb"/Title \(Explicit.*Living\)", kept)
    assert "Explicit" in drawn(kept) and "Mine" in drawn(kept)
