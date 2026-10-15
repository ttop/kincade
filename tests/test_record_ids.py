"""Record IDs (--show-ids, off by default): the record ID of each box's person,
without the @ signs, in small black type at the box's upper right. Its cap top aligns
with the name's cap top. The name is fitted into the room left of the ID (its normal
width, less the ID's width and 6 pt); the detail lines keep their whole width.
In the index, the ID follows the name and precedes the years.

Synthetic fixtures only.
"""

import re
from collections import Counter

import pytest
from reportlab.pdfbase import pdfmetrics

import kincade
import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade import Person, Tree
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import (
    BOX_W,
    BOX_X0,
    NAME_BASE,
    TEXT_INSET_LEFT,
    TEXT_INSET_RIGHT,
    TEXT_WIDTH,
)

from conftest import ged, render_charts
from pdfread import drawn, runs

ELLIPSIS = "…"


def ids(pdf):
    return [t for t in drawn(pdf) if re.fullmatch(r"\[[A-Za-z0-9_]+\]", t)]


# A root with a father only: box 3 (the mother) is an empty box
FATHER_ONLY = ged(
    "0 @I1@ INDI",
    "1 NAME Root /ROOT/",
    "1 BIRT",
    "2 DATE 1 JAN 1900",
    "2 PLAC Ohio, USA",
    "1 FAMC @F1@",
    "0 @I2@ INDI",
    "1 NAME Dad /ROOT/",
    "1 BIRT",
    "2 DATE 1 JAN 1860",
    "0 @F1@ FAM",
    "1 HUSB @I2@",
)


# ---------------------------------------------------------------- the switch


def test_no_record_ids_by_default(pedigree):
    assert ids(render_charts(pedigree)) == []


def test_show_ids_draws_the_record_id_of_each_known_person_without_the_at_signs(
    pedigree,
):
    found = ids(render_charts(pedigree, generations=3, show_ids=True))
    assert Counter(found) == Counter(f"[I{n}]" for n in range(1, 8))


def test_the_flag_sets_the_option():
    assert (
        kincade.cli._parser()
        .parse_args(["x.ged", "--root", "I1", "--show-ids"])
        .show_ids
        is True
    )


def test_empty_boxes_get_no_id():
    tree = read_gedcom(FATHER_ONLY)
    # boxes 3 to 7 are unknown
    assert ids(render_charts(tree, generations=3, show_ids=True)) == ["[I1]", "[I2]"]


# ---------------------------------------------------------------- where it sits


def test_the_id_ends_at_the_box_right_edge_less_the_text_inset(pedigree):
    pdf = render_charts(pedigree, generations=1, show_ids=True)
    x = next(r for r in runs(pdf) if r.text == "[I1]").x
    right_edge = x + kincade.pdf.text_width("[I1]", "Helvetica", 7)
    # the box's right edge less the inset
    assert right_edge <= BOX_X0[1] + BOX_W - TEXT_INSET_RIGHT + 1e-6
    # right-aligned to it
    assert right_edge == pytest.approx(BOX_X0[1] + BOX_W - TEXT_INSET_RIGHT)


def test_the_id_cap_top_matches_the_name_in_small_black_type(pedigree):
    geom = kincade.pdf.LETTER
    pdf = render_charts(pedigree, generations=1, show_ids=True)
    record = next(r for r in runs(pdf) if r.text == "[I1]")
    y, scale = record.y, record.scale
    # Helvetica capitals rise 718 units per em
    assert y == pytest.approx(geom.box_top[1] - 10 + NAME_BASE - (9 - 7) * 0.718)
    name = next(r for r in runs(pdf) if r.text == "Jane ASHFORD")
    assert y - record.size * 0.718 == pytest.approx(name.y - name.size * 0.718)
    assert scale == pytest.approx(1.0)
    # the fill color in force when the ID is drawn
    before = pdf[: pdf.index(b"([I1]) Tj")]
    color = re.findall(rb"(?:[\d.]+ [\d.]+ [\d.]+ rg|[\d.]+ g)\b", before)[-1]
    assert color in (b"0 0 0 rg", b"0 g")  # solid black, never a gray


def test_the_id_is_in_helvetica_7(pedigree):
    pdf = render_charts(pedigree, generations=1, show_ids=True)
    end = pdf.index(b"([I1]) Tj")
    text_object = pdf[pdf.rindex(b"BT", 0, end) : end]
    name, size = re.findall(rb"/(F\d+) ([\d.]+) Tf\b", text_object)[-1]
    fonts = {
        ref: base
        for base, ref in re.findall(
            rb"/BaseFont /([\w-]+) /Encoding /WinAnsiEncoding /Name /(F\d+)", pdf
        )
    }
    assert (fonts[name], size) == (b"Helvetica", b"7")
    assert re.search(rb"\b1 0 0 1 [\d.]+ [\d.]+ Tm\s*$", text_object)


def test_every_box_has_its_id_at_its_own_name_cap_top(pedigree):
    geom = kincade.pdf.LETTER
    pdf = render_charts(pedigree, generations=3, show_ids=True)
    for r in runs(pdf):
        if re.fullmatch(r"\[I\d+\]", r.text):
            tops = [
                geom.box_top[pos]
                - (10 if pos == 1 else 0)
                + NAME_BASE
                - (9 - 7) * 0.718
                for pos in range(1, 8)
            ]
            assert any(r.y == pytest.approx(t) for t in tops), r


def test_the_id_is_hidden_for_a_living_person_under_private():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Young /ROOT/",
            "1 BIRT",
            "2 DATE 1 JAN 2000",
            "2 PLAC Oslo, Norway",
        )
    )
    pdf = render_charts(tree, generations=1, show_ids=True, exclude_private=True)
    assert "[I1]" not in drawn(pdf)
    assert "Living" in drawn(pdf)
    assert "Oslo, Norway" not in " ".join(drawn(pdf))  # the details stay hidden


# ----------------------------------------------------------------
# the name line makes room for the ID


def test_the_name_is_fitted_into_the_room_left_of_the_id():
    long_name = (
        "Alexandrina Wilhelmina Fredericka Charlotte Josephine Maximiliana Christabella"
    )
    tree = read_gedcom(ged("0 @I1@ INDI", f"1 NAME {long_name} /VANDERBILT/"))
    pdf = render_charts(tree, generations=1, show_ids=True)
    x_id = next(r for r in runs(pdf) if r.text == "[I1]").x
    name = next(r for r in runs(pdf) if r.text.startswith("Alexandrina"))
    assert name.text.endswith(ELLIPSIS)  # cut with the ellipsis: far too long
    # at least 6 pt clear of the ID (the PDF writes 2 decimals)
    assert name.right() <= x_id - 6 + 0.01
    assert name.scale >= 0.5


def test_a_name_that_just_fits_alone_is_squeezed_to_leave_room_for_the_id():
    n = next(
        n
        for n in range(1, 60)
        if kincade.pdf.text_width(f"{'A' * n} ROOT", "Helvetica", 9) > 195
    )
    name = f"{'A' * n} ROOT"
    # fits the whole width, not the room left
    assert 195 < kincade.pdf.text_width(name, "Helvetica", 9) <= TEXT_WIDTH
    tree = read_gedcom(ged("0 @I1@ INDI", f"1 NAME {'A' * n} /ROOT/"))
    plain = next(
        r for r in runs(render_charts(tree, generations=1)) if r.text.startswith("AAA")
    )
    assert plain.scale == pytest.approx(1.0) and plain.text == name
    pdf = render_charts(tree, generations=1, show_ids=True)
    x_id = next(r for r in runs(pdf) if r.text == "[I1]").x
    squeezed = next(r for r in runs(pdf) if r.text.startswith("AAA"))
    assert squeezed.scale < 1.0  # condensed to leave the ID its room
    assert squeezed.right() <= x_id - 6 + 0.01


def test_a_short_name_is_not_changed_by_the_id(pedigree):
    plain = [
        r
        for r in runs(render_charts(pedigree, generations=3))
        if r.text == "Jane ASHFORD"
    ]
    with_ids = [
        r
        for r in runs(render_charts(pedigree, generations=3, show_ids=True))
        if r.text == "Jane ASHFORD"
    ]
    assert plain == with_ids and len(plain) == 1


def test_the_last_detail_line_keeps_its_whole_width_with_ids_on():
    # far too wide for the box line with or without the ID
    long_place = "Q" * 90 + " County, Kentucky"
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Root /ROOT/",
            "1 BIRT",
            "2 DATE 1 JAN 1900",
            "1 DEAT",
            "2 DATE 1 JAN 1950",
            f"2 PLAC {long_place}",
        )
    )
    with_ids = render_charts(tree, generations=1, show_ids=True)
    without = render_charts(tree, generations=1, show_ids=False)
    for pdf in (with_ids, without):
        right = next(r for r in runs(pdf) if r.text.startswith("dp.")).right()
        # the scale is written to 3 decimals
        assert right <= BOX_X0[1] + TEXT_INSET_LEFT + TEXT_WIDTH + 0.01
        # it does use nearly all of it
        assert right > BOX_X0[1] + TEXT_INSET_LEFT + TEXT_WIDTH - 40
    assert next(r for r in runs(with_ids) if r.text.startswith("dp.")) == next(
        r for r in runs(without) if r.text.startswith("dp.")
    )


def test_the_other_detail_lines_are_unchanged_by_ids(pedigree):
    keep = lambda pdf: [
        r
        for r in runs(pdf)
        if r.text != "[I1]" and not re.fullmatch(r"\[I\d+\]", r.text)
    ]
    assert keep(render_charts(pedigree, generations=3, show_ids=True)) == keep(
        render_charts(pedigree, generations=3)
    )


# ---------------------------------------------------------------- the name index


def index_of(tree, root="I1", generations=3, **kw):
    charts = plan_charts(tree, root, generations)
    return kincade.pdf.build_index(
        tree,
        charts,
        lambda pid: False,
        exclude_private=kw.pop("exclude_private", False),
        **kw,
    )


def test_the_index_shows_the_id_after_the_name_and_before_the_years(pedigree):
    lines = index_of(pedigree, show_ids=True)
    assert "ASHFORD, Jane [I1] (b. 1980), 1-1" in lines
    assert any(
        line.startswith("ASHFORD, John [I2] (b. 1950 – d. 2020), ") for line in lines
    )


def test_the_index_is_unchanged_with_ids_off(pedigree):
    assert index_of(pedigree) == index_of(pedigree, show_ids=False)
    assert "ASHFORD, Jane (b. 1980), 1-1" in index_of(pedigree)
    assert not any("[" in line for line in index_of(pedigree))


def test_an_index_entry_without_years_shows_the_id_before_the_locations():
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME Root /ROOT/"))
    assert index_of(tree, generations=1, show_ids=True) == ["ROOT, Root [I1], 1-1"]


def test_the_index_id_uses_the_record_id_template_of_the_language():
    tree = read_gedcom(ged("0 @I1@ INDI", "1 NAME Root /ROOT/"))
    strings = kincade.lang.load_strings(strings={"record_id": "<{id}>"})
    assert index_of(tree, generations=1, show_ids=True, strings=strings) == [
        "ROOT, Root <I1>, 1-1"
    ]


def test_the_index_omits_a_living_person_under_private():
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Young /ROOT/", "1 BIRT", "2 DATE 1 JAN 2000")
    )
    charts = plan_charts(tree, "I1", 1)
    lines = kincade.pdf.build_index(
        tree, charts, lambda pid: True, exclude_private=True, show_ids=True
    )
    assert lines == []


def test_the_pdf_index_pages_carry_the_ids_only_with_show_ids(pedigree):
    on = drawn(render_charts(pedigree, show_ids=True, index=True))
    off = drawn(render_charts(pedigree, index=True))
    assert "ASHFORD, Jane [I1] (b. 1980), 1-1" in on
    assert "ASHFORD, Jane (b. 1980), 1-1" in off
    assert not any(t.startswith("ASHFORD, Jane [") for t in off)


# ----------------------------------------------------------------
# the strings and the config


def test_record_id_is_a_language_key_with_one_placeholder():
    assert kincade.lang.DEFAULT_STRINGS["record_id"] == "[{id}]"
    assert kincade.lang.PLACEHOLDERS["record_id"] == ("id",)
    assert kincade.lang.load_strings("de")["record_id"] == "[{id}]"


@pytest.mark.parametrize(
    "value", ['"[{xref}]"', '"[{id:>5}]"', '"[{id!r}]"', '"[{}]"', '"[id]}"']
)
def test_a_record_id_template_with_anything_but_the_id_placeholder_is_a_langerror(
    tmp_path, value
):
    path = tmp_path / "x.toml"
    path.write_text(f"record_id = {value}\n", encoding="utf-8")
    with pytest.raises(kincade.lang.LangError) as e:
        kincade.lang.load_strings(str(path))
    assert "record_id" in str(e.value)


# ---------------------------------------------------------------- a long record ID

XREF = "W" * 40  # a long GEDCOM 7 record ID, in the widest letter


LONG_ID = ged(
    f"0 @{XREF}@ INDI",
    "1 NAME Root /ROOT/",
    "1 BIRT",
    "2 DATE 1 JAN 1900",
    "1 FAMC @F1@",
    "0 @I2@ INDI",
    "1 NAME Dad /ROOT/",
    "1 FAMC @F2@",
    "0 @I3@ INDI",
    "1 NAME Mum /ROOT/",
    "0 @F1@ FAM",
    "1 HUSB @I2@",
    "1 WIFE @I3@",
    "1 CHIL @" + XREF + "@",
    "0 @F2@ FAM",
    "1 HUSB @I4@",
    "0 @I4@ INDI",
    "1 NAME Grandpa /ROOT/",
)


PAPERS_AND_PRINTS = [("letter", False), ("a4", False), ("letter", True), ("a4", True)]


def id_run(pdf, startswith="[W"):
    return next(r for r in runs(pdf) if r.text.startswith(startswith))


@pytest.mark.parametrize("paper,large", PAPERS_AND_PRINTS)
def test_a_long_record_id_is_cut_to_forty_percent_of_the_text_width_and_stays_in_its_box(
    paper, large
):
    geom = kincade.pdf.page_geom(paper, large)
    tree = read_gedcom(LONG_ID)
    pdf = render_charts(
        tree, XREF, generations=2, paper=paper, large_print=large, show_ids=True
    )
    record = id_run(pdf)
    x, text = record.x, record.text
    width = kincade.pdf.text_width(text, "Helvetica", geom.id_size)
    assert (
        text.startswith("[W")
        and text.endswith(ELLIPSIS + "]")
        and record.scale == pytest.approx(1.0)
    )
    assert geom.id_max == pytest.approx(0.4 * geom.text_w)
    assert width <= geom.id_max + 1e-6
    # as much of it as the cap allows: not a letter less
    assert width > geom.id_max - geom.id_size
    # right-aligned
    assert x + width == pytest.approx(geom.box_x0[1] + geom.box_w - geom.inset_right)
    assert x >= geom.box_x0[1] + geom.inset_left  # inside the box


@pytest.mark.parametrize("paper,large", PAPERS_AND_PRINTS)
def test_the_name_keeps_the_room_a_long_record_id_leaves_it(paper, large):
    geom = kincade.pdf.page_geom(paper, large)
    tree = read_gedcom(LONG_ID)
    pdf = render_charts(
        tree, XREF, generations=2, paper=paper, large_print=large, show_ids=True
    )
    record = id_run(pdf)
    x, y = record.x, record.y
    name = next(r for r in runs(pdf) if r.text == "Root ROOT")  # the name is drawn
    assert name.y - name.size * 0.718 == pytest.approx(y - record.size * 0.718)
    assert name.right() <= x - geom.id_gap + 1e-6
    # the name always has over half the line
    assert geom.text_w - geom.id_max - geom.id_gap > 0.5 * geom.text_w


@pytest.mark.parametrize("paper,large", PAPERS_AND_PRINTS)
def test_a_long_name_beside_a_long_record_id_is_cut_with_room_left(paper, large):
    geom = kincade.pdf.page_geom(paper, large)
    tree = read_gedcom(
        ged(
            f"0 @{XREF}@ INDI",
            "1 NAME Alexandrina Wilhelmina Fredericka Charlotte /VANDERBILT/",
        )
    )
    pdf = render_charts(
        tree, XREF, generations=1, paper=paper, large_print=large, show_ids=True
    )
    x = id_run(pdf).x
    name = next(r for r in runs(pdf) if r.text.startswith("Alexandrina"))
    assert name.text.endswith(ELLIPSIS)
    assert name.right() <= x - geom.id_gap + 0.05  # rounding


@pytest.mark.parametrize(
    "xref", ["I1", "I12", "I1234", "F00123", "Q123456789", "ab-cd_ef"]
)
@pytest.mark.parametrize("paper,large", PAPERS_AND_PRINTS)
def test_an_ordinary_record_id_is_drawn_whole(xref, paper, large):
    geom = kincade.pdf.page_geom(paper, large)
    tree = read_gedcom(ged(f"0 @{xref}@ INDI", "1 NAME Root /ROOT/"))
    pdf = render_charts(
        tree, xref, generations=1, paper=paper, large_print=large, show_ids=True
    )
    record = id_run(pdf, "[")
    x, text = record.x, record.text
    assert text == f"[{xref}]" and record.scale == 1.0
    assert x + kincade.pdf.text_width(text, "Helvetica", geom.id_size) == pytest.approx(
        geom.box_x0[1] + geom.box_w - geom.inset_right
    )
    # none of these is anywhere near it
    assert kincade.pdf.text_width(text, "Helvetica", geom.id_size) <= geom.id_max


def test_the_cut_keeps_a_language_templates_own_text():
    tree = read_gedcom(LONG_ID)
    strings = {"record_id": "No. {id}"}
    text = id_run(
        render_charts(tree, XREF, generations=1, show_ids=True, lang=strings), "No. W"
    ).text
    assert text.startswith("No. W") and text.endswith(ELLIPSIS)
    assert kincade.pdf.text_width(text, "Helvetica", 7) <= kincade.pdf.LETTER.id_max


def test_a_template_wider_than_the_cap_is_cut_as_a_whole():
    tree = read_gedcom(LONG_ID)
    strings = {"record_id": "Record number in the family file {id}"}
    text = id_run(
        render_charts(tree, XREF, generations=1, show_ids=True, lang=strings),
        "Record number",
    ).text
    assert text.endswith(ELLIPSIS)
    assert kincade.pdf.text_width(text, "Helvetica", 7) <= kincade.pdf.LETTER.id_max


def test_a_record_id_that_fits_is_never_changed_by_the_cap():
    # 30 narrow characters are about 55 pt: well under the cap, so no ellipsis
    tree = read_gedcom(ged("0 @" + "i" * 30 + "@ INDI", "1 NAME Root /ROOT/"))
    assert (
        id_run(render_charts(tree, "i" * 30, generations=1, show_ids=True), "[i").text
        == "[" + "i" * 30 + "]"
    )


def test_a_long_record_id_in_the_index_stays_in_its_column():
    """The index fits every line with the ellipsis already, so it needs no cap of its
    own."""
    tree = read_gedcom(LONG_ID)
    charts = plan_charts(tree, XREF, 2)
    entries = kincade.pdf.build_index(
        tree,
        charts,
        lambda pid: False,
        False,
        kincade.pdf.BASE14,
        kincade.lang.DEFAULT_STRINGS,
        True,
        True,
    )
    assert any(XREF[:5] in e for e in entries)
    for entry in entries:
        for text, indent in kincade.pdf._wrap_index_entry(
            entry, "Times-Roman", kincade.pdf.LETTER.index_col_w
        ):
            assert (
                kincade.pdf.text_width(text, "Times-Roman", kincade.pdf.INDEX_SIZE)
                + indent
                <= kincade.pdf.LETTER.index_col_w + 1e-6
            )


def test_the_pdf_shows_the_id_without_at_signs(pedigree):
    pdf = render_charts(pedigree, "I1", generations=3, show_ids=True, index=True)
    found = [t for t in drawn(pdf) if re.fullmatch(r"\[[A-Za-z0-9_]+\]", t)]
    assert {"[I1]", "[I2]", "[I3]"} <= set(found)
    assert any("[I1]" in t and "ASHFORD" in t for t in drawn(pdf))  # the index entry


def test_a_record_id_is_shown_as_it_is():
    tree = Tree({"x-1": Person("x-1", given="Xi")})
    assert "[x-1]" in drawn(render_charts(tree, "x-1", show_ids=True))


@pytest.mark.parametrize("paper", ["letter", "a4"])
@pytest.mark.parametrize("large_print", [False, True])
@pytest.mark.parametrize(
    "fonts_mode", ["base14", pytest.param("auto", marks=pytest.mark.system_fonts)]
)
def test_record_id_and_name_cap_tops_match_in_the_pdf(paper, large_print, fonts_mode):
    fonts = kincade.pdf.choose_fonts(fonts_mode)
    if fonts_mode == "auto" and not fonts.files:
        pytest.skip("no system TrueType fonts")
    tree = Tree(people={"I12": Person("I12", given="Jane", surname="DOE")})
    pdf = render_charts(
        tree, "I12", show_ids=True, fonts=fonts, paper=paper, large_print=large_print
    )
    positions = {}
    for obj in re.findall(rb"BT(.*?)ET", pdf, re.DOTALL):
        text = b"".join(re.findall(rb"\((.*?)\) Tj", obj, re.DOTALL))
        if text in (b"Jane DOE", b"[I12]"):
            font, size = re.search(rb"/(F[\d+]+) ([\d.]+) Tf", obj).groups()
            baseline = float(re.findall(rb"1 0 0 1 [\d.]+ ([\d.]+) Tm", obj)[-1])
            positions[text] = (font, float(size), baseline)
    name, record = positions[b"Jane DOE"], positions[b"[I12]"]
    face = pdfmetrics.getFont(fonts.sans).face
    cap = getattr(face, "capHeight", face.ascent) / 1000
    assert name[0] == record[0]
    assert record[2] + record[1] * cap == pytest.approx(
        name[2] + name[1] * cap, abs=0.1
    )
