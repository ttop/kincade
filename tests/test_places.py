"""Printed places have trimmed comma-separated parts, empty parts omitted, and a
comma and space between parts. Tidying applies before fitting with either setting.
A place line (label + place) that does not fit is shortened before it is truncated.

The steps stop at the first that fits: (a) drop the home country, the last part,
when the place has two or more parts and that part is the home country; (b) drop the
middle parts one at a time, starting with the second, keeping the first and last.
One part, the language's ellipsis, marks the dropped run: "A, B, C, D" becomes
"A, …, C, D" and then "A, …, D". Dropping the country leaves no marker. Finally the
rest is truncated with the ellipsis. --no-shorten-places only truncates.

Synthetic fixtures only.
"""

import pytest

import kincade.charts
import kincade.cli
import kincade.gedcom
import kincade.lang
import kincade.pdf
from kincade.charts import plan_charts
from kincade.gedcom import read_gedcom
from kincade.pdf import Options

from conftest import FIX, ged, render_charts
from pdfread import drawn

# A root born in a long place. Three other people were born in USA places, so USA is the
# home country (3 times, and no other last part comes close), and the root's line is far
# wider than its box line.
LONG = "Springfield, Greene County, Northern Missouri, Western Region, USA"
HOME_GED = ged(
    "0 @I1@ INDI",
    "1 NAME Root /ROOT/",
    "1 BIRT",
    f"2 PLAC {LONG}",
    "1 FAMC @F1@",
    "0 @I2@ INDI",
    "1 NAME Dad /ROOT/",
    "1 BIRT",
    "2 PLAC Ohio, USA",
    "0 @I3@ INDI",
    "1 NAME Mum /ROOT/",
    "1 BIRT",
    "2 PLAC Kent, USA",
    "0 @F1@ FAM",
    "1 HUSB @I2@",
    "1 WIFE @I3@",
)


# ---------------------------------------------------------------- the home country


@pytest.mark.parametrize(
    "places,home",
    [
        (
            ["A, X, USA", "B, Y, USA", "C, Z, France"],
            "usa",
        ),  # two against one: a plurality
        (
            ["A, USA", "B, USA", "C, USA", "D, France", "E, France"],
            "usa",
        ),  # three against two: a strict plurality
        (["A, USA", "B, USA", "C, France", "D, France"], None),  # a tie
        (["A, USA", "B, France", "C, Ohio"], None),  # each once: nothing occurs twice
        (["A, USA"], None),  # one place: not enough
        ([], None),
        (
            ["A, x, usa ", "B, Y, USA", "C, Z, Usa"],
            "usa",
        ),  # trimmed and case-insensitive
        (["A, ,", "B, , USA", "C, USA "], "usa"),  # empty parts are not parts
    ],
)
def test_the_home_country_is_the_common_last_part_when_it_is_a_strict_plurality(
    places, home
):
    assert kincade.pdf.home_country(places) == home


def test_a_place_with_one_part_counts_by_that_part():
    assert kincade.pdf.home_country(["Paris", "Paris", "London"]) == "paris"


# ---------------------------------------------------------------- one place line


def test_a_place_that_fits_is_returned_exactly_as_it_is():
    line = kincade.pdf.shorten_place_line(
        "bp.", "Oakshire  by Service, Greene, Missouri, USA", "usa", lambda t: True
    )
    # double space and all
    assert line == "bp. Oakshire  by Service, Greene, Missouri, USA"


def test_the_home_country_is_dropped_first():
    fits = lambda t: len(t) <= 35
    assert (
        kincade.pdf.shorten_place_line(
            "bp.", "Springfield, Greene, Missouri, USA", "usa", fits
        )
        == "bp. Springfield, Greene, Missouri"
    )


def test_a_foreign_country_is_kept():
    never = lambda t: False
    assert (
        kincade.pdf.shorten_place_line(
            "bp.", "Dublin, Co. Dublin, Ireland", "usa", never
        )
        == "bp. Dublin, …, Ireland"
    )


def test_a_one_part_place_is_not_dropped_even_when_it_is_the_home_country():
    assert (
        kincade.pdf.shorten_place_line("bp.", "USA", "usa", lambda t: False)
        == "bp. USA"
    )


def test_a_two_part_place_has_no_middle_to_drop_and_no_marker():
    never = lambda t: False
    assert (
        kincade.pdf.shorten_place_line("bp.", "Ohio, France", "usa", never)
        == "bp. Ohio, France"
    )
    # the home country, unmarked
    assert (
        kincade.pdf.shorten_place_line("bp.", "Ohio, USA", "usa", never) == "bp. Ohio"
    )


def test_the_dropped_middle_is_marked_with_the_ellipsis():
    never = lambda t: False
    assert (
        kincade.pdf.shorten_place_line(
            "bp.", "Jefferson Township, Buchanan County, Iowa", None, never
        )
        == "bp. Jefferson Township, …, Iowa"
    )


def test_the_middle_parts_go_one_at_a_time_from_the_second_and_the_first_and_last_stay():
    tried = []

    def fits(text):
        tried.append(text)
        return False

    assert (
        kincade.pdf.shorten_place_line("bp.", "A, B, C, D, E", None, fits)
        == "bp. A, …, E"
    )
    assert tried == [
        "bp. A, B, C, D, E",
        "bp. A, …, C, D, E",
        "bp. A, …, D, E",
        "bp. A, …, E",
    ]


def test_four_parts_drop_the_second_then_the_third_and_the_run_stays_one_marker():
    tried = []

    def fits(text):
        tried.append(text)
        return False

    assert (
        kincade.pdf.shorten_place_line("bp.", "p0, p1, p2, p3", None, fits)
        == "bp. p0, …, p3"
    )
    assert tried == ["bp. p0, p1, p2, p3", "bp. p0, …, p2, p3", "bp. p0, …, p3"]


def test_there_is_never_a_second_marker_next_to_the_first():
    seen = []

    def fits(text):
        seen.append(text)
        return False

    kincade.pdf.shorten_place_line("bp.", "A, B, C, D, E, F, G", "usa", fits)
    assert seen and all(t.count("…") <= 1 for t in seen)
    assert not any(", …, …" in t or "…, …" in t for t in seen)


def test_the_marker_is_the_languages_ellipsis():
    never = lambda t: False
    assert (
        kincade.pdf.shorten_place_line("bp.", "A, B, C, D", None, never, ellipsis="...")
        == "bp. A, ..., D"
    )
    assert (
        kincade.pdf.shorten_place_line("bp.", "A, B, C, D", None, never, ellipsis="..")
        == "bp. A, .., D"
    )


def test_the_width_check_sees_the_marker():
    # "bp. A, CCCCCC, D" would fit this room, but the marked line "bp. A, …, CCCCCC, D"
    # is wider than that
    room = kincade.pdf.text_width("bp. A, CCCCCC, D", "Times-Roman", kincade.pdf.SIZE)
    fits = lambda t: kincade.pdf.text_width(t, "Times-Roman", kincade.pdf.SIZE) <= room
    assert (
        kincade.pdf.shorten_place_line("bp.", "A, B, CCCCCC, D", None, fits)
        == "bp. A, …, D"
    )


def test_the_home_country_drop_is_not_marked_but_the_middle_drop_after_it_is():
    tried = []

    def fits(text):
        tried.append(text)
        return False

    assert (
        kincade.pdf.shorten_place_line(
            "bp.", "Springfield, Greene, Missouri, USA", "usa", fits
        )
        == "bp. Springfield, …, Missouri"
    )
    assert tried == [
        "bp. Springfield, Greene, Missouri, USA",
        "bp. Springfield, Greene, Missouri",
        "bp. Springfield, …, Missouri",
    ]


def test_the_steps_stop_at_the_first_that_fits():
    tried = []

    def fits(text):
        tried.append(text)
        return text == "bp. A, …, C, D, E"

    assert (
        kincade.pdf.shorten_place_line("bp.", "A, B, C, D, E", None, fits)
        == "bp. A, …, C, D, E"
    )
    assert tried == ["bp. A, B, C, D, E", "bp. A, …, C, D, E"]


def test_when_no_step_fits_the_fully_shortened_line_is_what_the_ellipsis_cuts():
    never = lambda t: False
    assert (
        kincade.pdf.shorten_place_line(
            "bp.", "Springfield, Greene, Missouri, USA", "usa", never
        )
        == "bp. Springfield, …, Missouri"
    )


# ---------------------------------------------------------------- the render


def test_a_long_birth_place_is_shortened_to_fit_its_line_not_truncated():
    # the parents' USA places make USA the home country
    text = drawn(render_charts(read_gedcom(HOME_GED), generations=2))
    # USA dropped, then Greene County marked
    assert "bp. Springfield, …, Northern Missouri, Western Region" in text
    assert not any(t.startswith("bp. Springfield") and t.endswith("…") for t in text)


def test_the_drawn_marker_is_the_languages_ellipsis():
    text = drawn(
        render_charts(read_gedcom(HOME_GED), generations=2, lang={"ellipsis": "..."})
    )
    assert "bp. Springfield, ..., Northern Missouri, Western Region" in text


def test_one_usa_place_alone_is_not_a_home_country():
    # the only drawn place with USA: no plurality
    text = drawn(render_charts(read_gedcom(HOME_GED), generations=1))
    # USA is kept; two middle parts marked as one
    assert "bp. Springfield, …, Western Region, USA" in text


def test_a_place_that_does_not_fit_after_the_steps_is_truncated_with_the_ellipsis():
    part = "Y" * 120
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI", "1 NAME Root /ROOT/", "1 BIRT", f"2 PLAC {part}, {'Z' * 120}"
        )
    )
    text = drawn(render_charts(tree, generations=1))
    line = next(t for t in text if t.startswith("bp. Y"))
    assert line.endswith("…") and line.startswith("bp. " + "Y" * 20)


def test_no_shorten_places_only_truncates():
    off = drawn(
        render_charts(read_gedcom(HOME_GED), generations=1, shorten_places=False)
    )
    truncated, _ = kincade.pdf.fit_squeezed(
        "bp. " + LONG, "Times-Roman", kincade.pdf.SIZE, kincade.pdf.TEXT_WIDTH
    )
    assert truncated.endswith("…") and truncated.startswith(
        "bp. Springfield, Greene County"
    )
    assert next(t for t in off if t.startswith("bp. Springfield")) == truncated


def test_only_lines_that_would_have_been_truncated_change():
    tree = read_gedcom(HOME_GED)
    on = drawn(render_charts(tree, generations=2))
    off = drawn(render_charts(tree, generations=2, shorten_places=False))
    assert len(on) == len(off)
    changed = [(a, b) for a, b in zip(on, off, strict=True) if a != b]
    assert changed and all(b.endswith("…") for _, b in changed)


def test_places_that_fit_are_drawn_the_same_with_and_without_shortening():
    tree = read_gedcom(FIX / "pedigree.ged")
    assert drawn(render_charts(tree, generations=5)) == drawn(
        render_charts(tree, generations=5, shorten_places=False)
    )


def test_the_home_country_comes_from_the_places_drawn_only():
    living = ged(
        "0 @I1@ INDI",
        "1 NAME Root /ROOT/",
        "1 BIRT",
        "2 DATE 1 JAN 1990",
        "2 PLAC Oslo, Norway",
        "1 FAMC @F1@",
        "0 @I2@ INDI",
        "1 NAME Dad /ROOT/",
        "1 BIRT",
        "2 DATE 1 JAN 1900",
        "2 PLAC Kent, USA",
        "0 @F1@ FAM",
        "1 HUSB @I2@",
    )
    tree = read_gedcom(living)
    charts = plan_charts(tree, "I1", 2)
    opts = Options(exclude_private=True)
    fonts = kincade.pdf.choose_fonts("base14")
    doc = kincade.pdf._Doc(
        tree,
        opts,
        fonts,
        kincade.lang.DEFAULT_STRINGS,
        lambda pid: pid == "I1",
        kincade.pdf.LETTER,
    )
    places = kincade.pdf._drawn_places(doc, charts)
    assert "Oslo, Norway" not in places and "Kent, USA" in places


def test_the_flag_and_the_config_key_set_the_option(tmp_path, capsys, rendered_options):
    base = [
        str(FIX / "pedigree.ged"),
        "--root",
        "@I1@",
        "--generations",
        "1",
        "-o",
        str(tmp_path / "x.pdf"),
    ]
    assert kincade.cli.main(base) == 0
    assert kincade.cli.main(base + ["--no-shorten-places"]) == 0
    assert [o.shorten_places for o in rendered_options] == [True, False]
    (tmp_path / "kincade.toml").write_text(
        "no_shorten_places = true\n", encoding="utf-8"
    )
    assert kincade.cli.main(["--show-config"]) == 0
    assert "no_shorten_places = true" in capsys.readouterr().out


# ----------------------------------------------------------------
# a place of nothing but commas

COMMAS = ["," * 100, ", " * 60, ",, ,," * 25, " , " * 40]


@pytest.mark.parametrize("place", COMMAS)
@pytest.mark.parametrize("home", [None, "usa"])
def test_a_place_without_parts_prints_only_its_label(place, home):
    never = lambda t: False
    assert kincade.pdf.place_parts(place) == []
    assert kincade.pdf.shorten_place_line("bp.", place, home, never) == "bp."


@pytest.mark.parametrize(
    "place,expected",
    [(place, "bp.") for place in COMMAS]
    + [
        (",", "bp."),
        ("," * 5 + "Paris" + "," * 100, "bp. Paris"),
        ("Paris" + ", " * 80 + "France", "bp. Paris, France"),
    ],
)
def test_a_birth_place_prints_its_parts_with_either_shortening_setting(place, expected):
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Root /ROOT/", "1 BIRT", f"2 PLAC {place}")
    )
    on = drawn(render_charts(tree, generations=1))
    off = drawn(render_charts(tree, generations=1, shorten_places=False))
    assert on == off
    assert expected in on


def test_a_place_of_commas_beside_a_home_country_matches_without_shortening():
    tree = read_gedcom(
        ged(
            "0 @I1@ INDI",
            "1 NAME Root /ROOT/",
            "1 BIRT",
            f"2 PLAC {',' * 100}",
            "1 FAMC @F1@",
            "0 @I2@ INDI",
            "1 NAME Dad /ROOT/",
            "1 BIRT",
            "2 PLAC Ohio, USA",
            "0 @I3@ INDI",
            "1 NAME Mum /ROOT/",
            "1 BIRT",
            "2 PLAC Kent, USA",
            "0 @F1@ FAM",
            "1 HUSB @I2@",
            "1 WIFE @I3@",
        )
    )
    assert drawn(render_charts(tree, generations=2)) == drawn(
        render_charts(tree, generations=2, shorten_places=False)
    )


def test_a_long_place_of_commas_prints_only_its_label():
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Root /ROOT/", "1 BIRT", f"2 PLAC {',' * 100}")
    )
    line = next(
        t for t in drawn(render_charts(tree, generations=1)) if t.startswith("bp.")
    )
    assert line == "bp."


def test_places_made_of_commas_do_not_disturb_the_home_country():
    places = ["," * 100, "A, USA", "B, USA", "C, France"]
    assert kincade.pdf.home_country(places) == "usa"


# ----------------------------------------------------------------
# a place label that is empty


@pytest.mark.parametrize("fits", [True, False])
def test_an_empty_label_gives_a_place_line_with_no_leading_space(fits):
    line = kincade.pdf.shorten_place_line(
        "", "Springfield, Greene, Missouri, USA", "usa", lambda t: fits
    )
    assert line == (
        "Springfield, Greene, Missouri, USA" if fits else "Springfield, …, Missouri"
    )


@pytest.mark.parametrize("shorten", [True, False])
def test_an_empty_place_label_draws_the_place_alone(shorten):
    tree = read_gedcom(
        ged("0 @I1@ INDI", "1 NAME Root /ROOT/", "1 BIRT", "2 PLAC Springfield, Ohio")
    )
    text = drawn(
        render_charts(
            tree,
            generations=1,
            shorten_places=shorten,
            lang={"labels": {"birth_place": ""}},
        )
    )
    assert "Springfield, Ohio" in text


@pytest.mark.parametrize("shorten", [False, True])
@pytest.mark.parametrize(
    "tag,label",
    [
        ("BIRT", "bp."),
        ("CHR", "chrp."),
        ("BAPM", "chrp."),
        ("DEAT", "dp."),
        ("BURI", "burp."),
        ("CREM", "cremp."),
        ("MARR", "mp."),
    ],
)
@pytest.mark.parametrize(
    "place,tidied",
    [
        ("Frogmore House,Windsor,,England", "Frogmore House, Windsor, England"),
        ("Kensington,Palace,London,England", "Kensington, Palace, London, England"),
        (" ,  Example Town  ,,, Sample County ,  ", "Example Town, Sample County"),
    ],
)
def test_each_printed_event_place_has_tidy_comma_parts(
    tag, label, place, tidied, shorten
):
    lines = ["0 @I12@ INDI", "1 NAME Jane /Doe/"]
    if tag == "MARR":
        lines += ["1 FAMS @F1@", "0 @F1@ FAM", "1 HUSB @I12@"]
    lines += [f"1 {tag}", f"2 PLAC {place}"]
    tree = read_gedcom(ged(*lines))
    text = drawn(render_charts(tree, "I12", generations=1, shorten_places=shorten))
    assert f"{label} {tidied}" in text
    event = (
        tree.families["F1"].marriage
        if tag == "MARR"
        else {
            "BIRT": tree.people["I12"].birth,
            "DEAT": tree.people["I12"].death,
            "CHR": next(iter(tree.people["I12"].christenings), None),
            "BAPM": next(iter(tree.people["I12"].christenings), None),
            "BURI": next(iter(tree.people["I12"].burials), None),
            "CREM": next(iter(tree.people["I12"].cremations), None),
        }[tag]
    )
    assert event.place == place.strip()


def test_place_parts_are_tidied_before_fitting_and_shortening():
    tried = []

    def fits(text):
        tried.append(text)
        return len(text) <= len("bp. A, B, C")

    assert (
        kincade.pdf.shorten_place_line("bp.", " A,B,,C,USA ", "usa", fits)
        == "bp. A, B, C"
    )
    assert tried == ["bp. A, B, C, USA", "bp. A, B, C"]
