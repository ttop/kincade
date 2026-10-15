"""The library's one entry point: render(tree, root, options) -> bytes plans the charts,
applies privacy and draws, for a Tree that was read from GEDCOM or built in code;
render_blank(options) -> bytes needs no tree. Options holds every setting under the name
of the command-line flag. The public names are exported from `kincade`.

Synthetic data only: a tree built in code, with no GEDCOM at all.
"""

import dataclasses

import pytest
from reportlab import rl_config

import kincade
import kincade.cli
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
from kincade.pdf import BASE14, FontSet

from conftest import FIX, TODAY
from pdfread import drawn, rectangles, runs


def opts(**kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("fonts", "base14")
    kw.setdefault("compress", False)
    return Options(**kw)


def family_tree():
    """Dayton Pell (born 1990) and his parents, who are both alive in the records, and a
    grandfather who died.
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
                "p2",
                given="Bob",
                surname="Pell",
                birth=year(1960),
                parents=[ParentLink("f2", "birth")],
                families=["f1"],
            ),
            "p3": Person(
                "p3", given="Ann", surname="Gray", birth=year(1962), families=["f1"]
            ),
            "p4": Person(
                "p4",
                given="Cy",
                surname="Pell",
                birth=year(1930),
                death=year(2001),
                families=["f2"],
            ),
        },
        families={
            "f1": Family(
                "f1",
                father="p2",
                mother="p3",
                marriage=Event(Date("exact", Day(1988)), "Elko, NV"),
                children=["p1"],
            ),
            "f2": Family("f2", father="p4", children=["p2"]),
        },
    )


# ---------------------------------------------------------------- the names


def test_the_public_names():
    for name in (
        "Tree",
        "Person",
        "Family",
        "Event",
        "Date",
        "Day",
        "ParentLink",
        "Options",
        "LangError",
        "render",
        "render_blank",
        "read_gedcom",
        "load_fontset",
    ):
        assert name in kincade.__all__ and hasattr(kincade, name), name
    assert (
        kincade.render is kincade.pdf.render
        and kincade.read_gedcom is kincade.gedcom.read_gedcom
        and kincade.load_fontset is kincade.pdf.load_fontset
    )


def test_a_font_set_from_load_fontset_is_what_options_fonts_takes():
    assert isinstance(BASE14, FontSet)
    pdf = render(family_tree(), "p1", opts(fonts=BASE14))
    assert pdf.startswith(b"%PDF")


def test_options_are_named_after_the_command_line_flags():
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


def test_the_options_defaults_are_the_command_lines():
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


# ---------------------------------------------------------------- one call


def test_a_tree_built_in_code_renders_in_one_call_with_no_gedcom():
    pdf = render(family_tree(), "p1", opts(generations=3))
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    text = drawn(pdf)
    assert (
        "Dayton PELL" in text
        and "Bob PELL" in text
        and "Ann GRAY" in text
        and "Cy PELL" in text
    )
    assert (
        "b. 2 Apr 1990" in text
        and "bp. Reno, NV" in text
        and "m. 1988" in text
        and "mp. Elko, NV" in text
    )
    # the footer, dated by Options.today
    assert "Created 10 Oct 2026 using Kincade" in text
    assert "Index" in text and "PELL, Dayton (b. 1990), 1-1" in text  # the name index


def test_render_is_planning_then_drawing(monkeypatch):
    # no creation date or random id: equal runs give equal bytes
    monkeypatch.setattr(rl_config, "invariant", 1)
    tree = family_tree()
    for options in (
        opts(),
        opts(generations=2, exclude_private=True, empty_boxes=False, large_print=True),
        opts(adoptive_parents=True, index=False, shadow=True, paper="a4"),
    ):
        charts = plan_charts(
            tree, "p1", options.generations, options.parents, options.large_print
        )
        assert render(tree, "p1", options) == kincade.pdf.render_pdf(
            charts, tree, options
        )


def test_render_reads_a_gedcom_file_the_same_way():
    tree = read_gedcom(str(FIX / "pedigree.ged"))
    again = read_gedcom((FIX / "pedigree.ged").read_bytes())  # path or bytes
    assert drawn(render(tree, "I1", opts())) == drawn(render(again, "I1", opts()))


def test_render_without_options_uses_the_defaults():
    assert render(family_tree(), "p1").startswith(b"%PDF")


@pytest.mark.parametrize("blank", [False, True])
def test_pdf_author_and_subject_are_empty(blank):
    pdf = render_blank(opts()) if blank else render(family_tree(), "p1", opts())
    assert b"/Author ()" in pdf and b"/Subject ()" in pdf


def test_an_unknown_root_a_bad_generation_count_and_a_bad_paper_are_errors():
    with pytest.raises(KeyError):
        render(family_tree(), "nobody")
    with pytest.raises(ValueError, match="at least 1"):
        render(family_tree(), "p1", opts(generations=0))
    with pytest.raises(ValueError, match="paper"):
        render(family_tree(), "p1", opts(paper="legal"))


def test_drawing_no_charts_is_an_error():
    with pytest.raises(ValueError, match="no charts to draw"):
        kincade.pdf.render_pdf([], family_tree(), opts())


def test_generations_limits_the_pedigree():
    tree = family_tree()
    assert "Cy PELL" in drawn(render(tree, "p1", opts(generations=3)))
    assert "Cy PELL" not in drawn(render(tree, "p1", opts(generations=2)))


# ----------------------------------------------------------------
# the settings, one by one


def test_exclude_private_hides_the_names_and_details_of_people_who_may_be_living():
    text = drawn(render(family_tree(), "p1", opts(exclude_private=True, generations=3)))
    # born 1990
    assert (
        "Living" in text
        and "Dayton PELL" not in text
        and "b. 2 Apr 1990" not in text
        and "bp. Reno, NV" not in text
    )
    # Bob is of an age to be living, and so is the marriage
    assert "Bob PELL" not in text
    assert "b. 1960" not in text and "m. 1988" not in text
    assert "b. 1930" in text and "d. 2001" in text  # Cy has died


def test_event_standins_use_a_christening_for_a_missing_birth():
    tree = family_tree()
    tree.people["p2"].birth = None
    tree.people["p2"].christenings = [Event(Date("exact", Day(1961)), "St Mark")]
    assert "chr. 1961" in drawn(render(tree, "p1", opts(generations=2)))
    assert "chr. 1961" not in drawn(
        render(tree, "p1", opts(generations=2, event_standins=False))
    )


def test_adoptive_parents_draw_the_adoptive_family_and_note_it():
    tree = family_tree()
    tree.people["p1"].parents = [
        ParentLink("f1", "birth"),
        ParentLink("f3", "adopted", "adopted"),
    ]
    tree.families["f3"] = Family("f3", father="p4", children=["p1"])
    assert "Cy PELL" not in drawn(render(tree, "p1", opts(generations=2)))
    adoptive = drawn(render(tree, "p1", opts(generations=2, adoptive_parents=True)))
    assert "Cy PELL" in adoptive and "Dayton PELL (adopted)" in adoptive


def test_empty_boxes_false_leaves_out_unknown_ancestors():
    tree = family_tree()
    with_empty = kincade.pdf.render(tree, "p1", opts(index=False, compress=False))
    without = kincade.pdf.render(
        tree, "p1", opts(index=False, compress=False, empty_boxes=False)
    )
    assert (
        len(rectangles(with_empty, "B*")) == 15 and len(rectangles(without, "B*")) == 4
    )


def test_show_ids_shorten_places_page_numbers_and_index():
    tree = family_tree()
    assert "[p1]" in drawn(render(tree, "p1", opts(show_ids=True)))
    # too wide for its line; NV is the home country
    tree.people["p1"].birth = Event(
        Date("exact", Day(1990, 4, 2)),
        "Sparks, Washoe County, Northern Nevada Region, Western Great Basin, NV",
    )
    assert "bp. Sparks, …, Western Great Basin" in drawn(render(tree, "p1", opts()))
    # only cut at the end
    assert "bp. Sparks, Washoe County, Northern Nevada Region, We…" in drawn(
        render(tree, "p1", opts(shorten_places=False))
    )
    assert not any(
        t.startswith("Page ")
        for t in drawn(render(tree, "p1", opts(page_numbers=False)))
    )
    assert "Page 1 of 2" in drawn(render(tree, "p1", opts()))
    no_index = drawn(render(tree, "p1", opts(index=False)))
    assert "Index" not in no_index and "Page 1 of 1" in no_index


@pytest.mark.parametrize(
    "settings,heading",
    [
        ({}, "Cascading Pedigree — Dayton PELL"),
        ({"preserve_case": True}, "Cascading Pedigree — Dayton Pell"),
        ({"exclude_private": True}, "Cascading Pedigree — Living"),
        ({"lang": "de"}, "Ahnentafel — Dayton PELL"),
        (
            {"lang": {"meta_title": "{title} of {name}"}},
            "Cascading Pedigree of Dayton PELL",
        ),
        ({"title": "Own title"}, "Own title"),
    ],
)
def test_pedigree_heading_uses_the_document_title_by_default(settings, heading):
    pdf = render(family_tree(), "p1", opts(**settings))
    assert heading in drawn(pdf)
    if settings.get("exclude_private"):
        assert not any("Dayton" in value for value in drawn(pdf))


def test_footer_title_and_lang():
    tree = family_tree()
    assert "Mine" in drawn(render(tree, "p1", opts(footer="Mine")))
    off = drawn(render(tree, "p1", opts(footer=False)))
    assert not any(t.startswith("Created") for t in off)
    assert "Own title" in drawn(render(tree, "p1", opts(title="Own title")))
    assert "Ahnentafel — Dayton PELL" in drawn(
        render(tree, "p1", opts(lang="de"))
    )  # a code
    # a mapping of strings
    assert "Stammbaum — Dayton PELL" in drawn(
        render(tree, "p1", opts(lang={"title": "Stammbaum"}))
    )
    with pytest.raises(LangError):
        render(tree, "p1", opts(lang="zz-nope"))
    with pytest.raises(LangError):
        render(tree, "p1", opts(lang={"title": 3}))


def test_large_print_and_paper_and_shadow_change_the_page():
    tree = family_tree()
    plain = render(tree, "p1", opts())
    big = render(tree, "p1", opts(large_print=True))
    name = lambda pdf: next(r for r in runs(pdf) if r.text == "Dayton PELL")
    assert (name(plain).size, name(big).size) == (9, 14)  # the box text
    assert b"/MediaBox [ 0 0 595.28 841.89 ]" in render(tree, "p1", opts(paper="a4"))
    shadowed = render(tree, "p1", opts(shadow=True))
    assert not rectangles(plain, "f*") and rectangles(shadowed, "f*")  # the layers


# ---------------------------------------------------------------- the blank chart


def test_render_blank_takes_the_same_options_and_needs_no_tree():
    blank = render_blank(opts(large_print=True, footer="My footer"))
    text = drawn(blank)
    assert (
        blank.startswith(b"%PDF")
        and "My footer" in text
        and "Cascading Pedigree" in text
    )
    # large print: boxes 1-7
    assert [t for t in text if t.isdigit()] == [str(n) for n in range(1, 8)]
    assert render_blank().startswith(b"%PDF")
    # settings that have nothing to apply to are ignored
    assert drawn(
        render_blank(opts(exclude_private=True, generations=3, show_ids=True))
    ) == drawn(render_blank(opts()))
